"""
Conversion orchestrator (Milestone 2).

What's new vs M1:
- Actually runs ffmpeg (no longer dry-run only).
- Probes input with ffprobe to decide a scale filter (max height).
- Writes to a temporary file first, then renames atomically on success.

Not yet in M2 (we'll add in M3):
- Explicit stream mapping (-map) and copy rules for audio/subtitles.
- Overwrite/skip policies, parallelism, advanced logging.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple, List

from .config import DEFAULTS, Defaults
from .jellyfin_naming import movie_filename
from .metadata import build_metadata
from .ffmpeg_utils import ffprobe_info, build_scale_filter, run, run_streaming, get_duration


@dataclass
class ConvertOptions:
    """
    User-configurable conversion options.

    For M2 we support:
    - codec (h264/h265), crf/bitrate, preset, container
    - title/year (metadata + filename)
    - max_height (scale filter applied when needed)
    - dry_run: if True, we only print the command
    """
    hevc: bool = False                 # True => H.265, False => H.264
    crf: Optional[int] = None          # if None, use default by codec
    bitrate: Optional[str] = None      # overrides CRF if set
    max_height: Optional[int] = None   # e.g., 1080 => limit to 1080p
    container: Optional[str] = None    # "mp4" or "mkv"
    preset: Optional[str] = None       # ffmpeg preset
    title: Optional[str] = None
    year: Optional[int] = None
    dry_run: bool = False              # M2 default: execute unless user asks for dry-run
    verbose: bool = False
    audio_track: Optional[int] = None 

def _target_video_codec(hevc: bool, defaults: Defaults) -> str:
    return defaults.video_codec_h265 if hevc else defaults.video_codec_h264


def _tmp_output_path(final_path: Path) -> Path:
    # e.g., "Demo (2025).mp4" -> "Demo (2025).tmp.mp4"
    return final_path.with_name(f"{final_path.stem}.tmp{final_path.suffix}")


def build_ffmpeg_cmd(
    input_path: Path,
    output_path: Path,
    scale_filter: Optional[str],
    opts: ConvertOptions,
    defaults: Defaults = DEFAULTS,
) -> List[str]:
    """
    Build an ffmpeg command list based on options + decided scale filter.
    """
    vcodec = _target_video_codec(opts.hevc, defaults)
    preset = opts.preset or defaults.preset

    # CRF vs bitrate
    if opts.bitrate:
        video_quality_args = ["-b:v", opts.bitrate]
    else:
        crf = opts.crf if opts.crf is not None else (
            defaults.crf_h265 if opts.hevc else defaults.crf_h264
        )
        video_quality_args = ["-crf", str(crf)]

    meta = build_metadata(opts.title, opts.year)
    meta_args: List[str] = []
    for k, v in meta.items():
        meta_args += ["-metadata", f"{k}={v}"]

    filter_args: List[str] = []
    if scale_filter:
        # Keep aspect ratio: scale=-2:MAX (already decided upstream)
        filter_args = ["-vf", scale_filter]

    cmd: List[str] = [
        "ffmpeg",
        "-y",  # allow overwrite (we'll add policies later)
        "-hide_banner",
        "-loglevel", "info",
        "-i", str(input_path),
        *filter_args,
        "-c:v", vcodec,
        "-preset", preset,
        *video_quality_args,
        "-c:a", defaults.audio_codec,
        "-b:a", defaults.audio_bitrate,
        *meta_args,
        str(output_path),
    ]
    return cmd


def convert_file(src: Path, out_dir: Path, opts) -> Tuple[bool, str, Path, List[str]]:
    """
    Convert a single file using ffmpeg. Writes to a temporary file inside `out_dir`
    and atomically renames to the final output on success.

    Returns:
        (success, error_message, final_output_path, ffmpeg_cmd)
    """

    # 1) Decide names/paths (FINAL and TMP *dentro* de out_dir)
    container = (opts.container or DEFAULTS.container).lower()
    final_out = out_dir / movie_filename(opts.title, opts.year, container)
    tmp_out = final_out.with_name(final_out.stem + ".tmp" + final_out.suffix)

    # 2) Build ffmpeg command (write directly to tmp_out in the CORRECT folder)
    v_codec = DEFAULTS.video_codec_h265 if getattr(opts, "hevc", False) else DEFAULTS.video_codec_h264
    crf = opts.crf if opts.crf is not None else (DEFAULTS.crf_h265 if getattr(opts, "hevc", False) else DEFAULTS.crf_h264)
    a_bitrate = DEFAULTS.audio_bitrate

    # Probe to know if scaling is needed
    try:
        info = ffprobe_info(src)
    except Exception as e:
        return False, f"ffprobe failed: {e}", final_out, []

    scale = build_scale_filter(opts.max_height, info) if getattr(opts, "max_height", None) else None
    vf = ["-vf", scale] if scale else []

    audio_streams = [s for s in info.get("streams", []) if s.get("codec_type") == "audio"]
    audio_count = len(audio_streams)

    requested = getattr(opts, "audio_track", None)  # vindo de --audio-track
    if requested is not None and (requested < 0 or requested >= audio_count):
        chosen_audio = 0
        print(f"  ⚠️  Requested audio track {requested} not available (found {audio_count}). Falling back to 0.")
    else:
        chosen_audio = requested if requested is not None else 0

    map_args = [
        "-map", "0:v:0",
        "-map", f"0:a:{chosen_audio}",
        "-map", "0:s:0?"  # legenda 0 se existir (opcional)
    ]

    cmd = [
        "ffmpeg", "-y",
        "-hide_banner", "-loglevel", "info",
        "-i", str(src),
        *map_args,
        "-c:v", v_codec, "-preset", DEFAULTS.preset,
    ]
    if getattr(opts, "bitrate", None):
        cmd += ["-b:v", str(opts.bitrate)]
    else:
        cmd += ["-crf", str(crf)]

    cmd += [
        "-c:a", DEFAULTS.audio_codec, "-b:a", a_bitrate,
        "-metadata", f"title={opts.title or ''}",
    ]
    if opts.year:
        cmd += ["-metadata", f"date={opts.year}", "-metadata", f"year={opts.year}"]

    cmd += vf
    cmd += [str(tmp_out)]

    # 3) Dry-run? Só retorna o plano
    if getattr(opts, "dry_run", False):
        return True, "", final_out, cmd

    # 4) Limpeza prévia do tmp (caso exista de execução anterior)
    try:
        if tmp_out.exists():
            tmp_out.unlink()
    except Exception:
        pass

    # 5) Executa ffmpeg **UMA ÚNICA VEZ**
    duration = get_duration(str(src))
    code = run_streaming(cmd, duration, verbose=getattr(opts, "verbose", False))
    if code != 0:
        try:
            if tmp_out.exists():
                tmp_out.unlink()
        except Exception:
            pass
        return False, "ffmpeg returned non-zero exit code", final_out, cmd

    # 6) Rename atômico tmp → final
    try:
        tmp_out.replace(final_out)
    except Exception as e:
        try:
            if tmp_out.exists():
                tmp_out.unlink()
        except Exception:
            pass
        return False, f"Atomic rename failed: {e}", final_out, cmd

    return True, "", final_out, cmd
