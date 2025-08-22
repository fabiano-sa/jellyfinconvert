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

from .config import DEFAULTS, Defaults
from .ffmpeg_utils import (
    build_scale_filter,
    default_sub_ext,
    ffprobe_info,
    get_duration,
    is_text_sub,
    run,
    run_streaming,
    sub_short_desc,
)
from .jellyfin_naming import movie_filename
from .metadata import build_metadata


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

    hevc: bool = False  # True => H.265, False => H.264
    crf: int | None = None  # if None, use default by codec
    bitrate: str | None = None  # overrides CRF if set
    max_height: int | None = None  # e.g., 1080 => limit to 1080p
    container: str | None = None  # "mp4" or "mkv"
    preset: str | None = None  # ffmpeg preset
    title: str | None = None
    year: int | None = None
    dry_run: bool = False  # M2 default: execute unless user asks for dry-run
    verbose: bool = False
    audio_track: int | None = None
    no_copy_subs: bool = False


def _target_video_codec(hevc: bool, defaults: Defaults) -> str:
    return defaults.video_codec_h265 if hevc else defaults.video_codec_h264


def build_ffmpeg_cmd(
    input_path: Path,
    output_path: Path,
    scale_filter: str | None,
    opts: ConvertOptions,
    defaults: Defaults = DEFAULTS,
    audio_map_index: int = 0,
    include_sub_0_optional: bool = True,
) -> list[str]:
    """
    Build an ffmpeg command list based on options + decided scale filter.
    """
    vcodec = _target_video_codec(opts.hevc, defaults)
    preset = opts.preset or defaults.preset

    # CRF vs bitrate
    if opts.bitrate:
        video_quality_args = ["-b:v", opts.bitrate]
    else:
        crf = (
            opts.crf
            if opts.crf is not None
            else (defaults.crf_h265 if opts.hevc else defaults.crf_h264)
        )
        video_quality_args = ["-crf", str(crf)]

    meta = build_metadata(opts.title, opts.year)
    meta_args: list[str] = []
    for k, v in meta.items():
        meta_args += ["-metadata", f"{k}={v}"]

    filter_args: list[str] = []
    if scale_filter:
        # Keep aspect ratio: scale=-2:MAX (already decided upstream)
        filter_args = ["-vf", scale_filter]

    # Mapas de streams (vídeo 0, áudio escolhido)
    map_args: list[str] = ["-map", "0:v:0", "-map", f"0:a:{audio_map_index}"]

    # Subtítulos: por padrão não copiar para MP4 (PGS não é suportado) ou quando no_copy_subs=True
    ext = output_path.suffix.lower().lstrip(".")
    can_copy_subs = (ext != "mp4") and include_sub_0_optional and (not opts.no_copy_subs)
    if can_copy_subs:
        map_args += ["-map", "0:s:0?"]

    cmd: list[str] = [
        "ffmpeg",
        "-y",  # allow overwrite (we'll add policies later)
        "-hide_banner",
        "-loglevel",
        "info",
        "-i",
        str(input_path),
        *map_args,
        *filter_args,
        "-c:v",
        vcodec,
        "-preset",
        preset,
        *video_quality_args,
        "-c:a",
        defaults.audio_codec,
        "-b:a",
        defaults.audio_bitrate,
        *meta_args,
    ]

    # MP4: melhor para streaming (Jellyfin/web players)
    ext = output_path.suffix.lower().lstrip(".")
    if ext == "mp4":
        cmd += ["-movflags", "+faststart"]

    cmd += [str(output_path)]
    return cmd


def _build_sub_extraction_cmd(
    src: Path, sub_index: int, out_path: Path, codec_name: str
) -> list[str]:
    """
    Build ffmpeg command to extract a subtitle stream:
    - For text codecs ⇒ convert to SRT: -map 0:s:i -c:s srt
    - For image codecs (PGS/DVD) ⇒ copy: -map 0:s:i -c:s copy
    """
    is_text = is_text_sub(codec_name)
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "info",
        "-i",
        str(src),
        "-map",
        f"0:s:{sub_index}",
        "-c:s",
        "srt" if is_text else "copy",
        str(out_path),
    ]
    return cmd


def extract_subs(
    src: Path, streams: list[dict], indexes: list[int], base_out_dir: Path, base_name: str
) -> list[Path]:
    """
    Extract selected subtitle streams. Returns list of generated files.
    base_name: e.g. 'Cyberpunk Edgerunners (2012)' to compose file names.
    """
    base_out_dir.mkdir(parents=True, exist_ok=True)
    out_files: list[Path] = []
    for i in indexes:
        s = streams[i]
        tags = s.get("tags") or {}
        lang = (tags.get("language") or "und").lower()
        title = tags.get("title") or ""
        codec = s.get("codec_name") or "unknown"
        ext = default_sub_ext(codec)
        suffix_bits = [lang]
        if title:
            # evitar espaços/delimitar; limpa título simples
            clean_title = " ".join(title.replace("/", "-").split())
            suffix_bits.append(clean_title)
        suffix = "." + ".".join([b for b in suffix_bits if b])
        out_name = f"{base_name}{suffix}{ext}"
        out_path = base_out_dir / out_name
        cmd = _build_sub_extraction_cmd(src, i, out_path, codec)
        code = run(cmd)[0]
        if code == 0 and out_path.exists():
            out_files.append(out_path)
        else:
            # tenta explicar mínimamente
            print(f"  ⚠️  Failed to extract subtitle #{i} ({sub_short_desc(s)}).")
    return out_files


def convert_file(src: Path, out_dir: Path, opts) -> tuple[bool, str, Path, list[str]]:
    """
    Convert a single file using ffmpeg. Writes to a temporary file inside `out_dir`
    and atomically renames to the final output on success.

    Returns:
        (success, error_message, final_output_path, ffmpeg_cmd)
    """

    # 1) Garante diretório e decide names/paths (FINAL e TMP *dentro* de out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    container = (opts.container or DEFAULTS.container).lower()
    title = opts.title or src.stem
    final_out = out_dir / movie_filename(title, opts.year, container)
    tmp_out = final_out.with_name(final_out.stem + ".tmp" + final_out.suffix)

    # 2) Build ffmpeg command (write directly to tmp_out in the CORRECT folder)
    # (quality knobs calculados mais abaixo ao montar cmd)
    try:
        info = ffprobe_info(src)
    except Exception as e:
        return False, f"ffprobe failed: {e}", final_out, []

    scale = build_scale_filter(opts.max_height, info) if getattr(opts, "max_height", None) else None

    audio_streams = [s for s in info.get("streams", []) if s.get("codec_type") == "audio"]
    audio_count = len(audio_streams)

    requested = getattr(opts, "audio_track", None)  # vindo de --audio-track
    if requested is not None and (requested < 0 or requested >= audio_count):
        chosen_audio = 0
        print(
            f"  ⚠️  Requested audio track {requested} not available "
            f"(found {audio_count}). Falling back to 0."
        )
    else:
        chosen_audio = requested if requested is not None else 0

    cmd = build_ffmpeg_cmd(
        input_path=src,
        output_path=tmp_out,
        scale_filter=scale,
        opts=opts,
        defaults=DEFAULTS,
        audio_map_index=chosen_audio,
        include_sub_0_optional=True,
    )

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
