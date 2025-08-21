"""
FFmpeg helpers: probing, command execution, and small utilities.

Added: run_streaming() to print ffmpeg stderr live (progress/stats)
so the CLI is not silent during long encodes.
"""

import json, subprocess, re, sys, time
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Regex para capturar "time=HH:MM:SS.xx"
TIME_RE = re.compile(r"time=(\d+):(\d+):(\d+\.\d+)")

def format_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02}:{m:02}:{s:02}"

def get_duration(path: str) -> float:
    """Retorna a duração do arquivo em segundos via ffprobe"""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True
    )
    try:
        return float(result.stdout.strip())
    except:
        return 0.0


class FFmpegError(RuntimeError):
    """Raised when ffprobe/ffmpeg fails."""


def run(cmd: List[str]) -> Tuple[int, str, str]:
    """
    Run a command and return (exit_code, stdout, stderr).
    Kept for places where we don't need live output.
    """
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out, err = proc.communicate()
    return proc.returncode, out, err


def run_streaming(cmd: List[str], duration: float = 0.0, verbose: bool = False) -> int:
    """
    Run ffmpeg and stream stderr. Se `duration > 0`, mostra barra de progresso.
    - verbose=False: mostra barra (se der) OU logs crus se não houver duração.
    - verbose=True: mostra logs crus SEMPRE e, se houver duração, também a barra.
    """
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1
    )
    assert proc.stderr is not None
    last_update = 0.0
    bar_len = 30

    for line in proc.stderr:
        line = line.rstrip()
        if not line:
            continue

        # Sempre imprime logs se verbose
        if verbose:
            sys.stderr.write(line + "\n")
            sys.stderr.flush()

        # Progresso (quando sabemos a duração)
        if duration > 0 and "time=" in line:
            m = TIME_RE.search(line)
            if m:
                h, m_, s = m.groups()
                elapsed = int(h) * 3600 + int(m_) * 60 + float(s)
                pct = max(0.0, min(100.0, (elapsed / duration) * 100.0))

                now = time.time()
                if now - last_update > 0.5:  # ~2 updates/seg
                    filled = int(bar_len * pct / 100.0)
                    bar = "█" * filled + "░" * (bar_len - filled)
                    # se verbose está ativo, a barra vai na mesma linha com \r
                    # se não está, a barra substitui a saída "crua"
                    sys.stderr.write(
                        f"\r[{bar}] {pct:5.1f}%  {format_time(elapsed)} / {format_time(duration)}"
                    )
                    sys.stderr.flush()
                    last_update = now

        # Quando NÃO há duração e NÃO estamos em verbose, imprima o log cru
        if duration <= 0 and not verbose:
            sys.stderr.write(line + "\n")
            sys.stderr.flush()

    ret = proc.wait()
    if duration > 0:
        sys.stderr.write(f"\r[{'█'*bar_len}] 100.0%  {format_time(duration)} / {format_time(duration)}\n")
        sys.stderr.flush()
    return ret


def ffprobe_info(path: Path) -> Dict[str, Any]:
    """
    Query media info using ffprobe and return a JSON dict with streams/format.
    """
    cmd = [
        "ffprobe",
        "-v", "error",
        "-print_format", "json",
        "-show_format", "-show_streams",
        str(path),
    ]
    code, out, err = run(cmd)
    if code != 0:
        raise FFmpegError(f"ffprobe failed: {err.strip()}")
    return json.loads(out)


def human_size(bytes_: int) -> str:
    """
    Convert a byte count into a human-readable string (e.g., 12.3 MB).
    """
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(bytes_)
    for u in units:
        if size < 1024 or u == units[-1]:
            return f"{size:.2f} {u}"
        size /= 1024


def build_scale_filter(max_height: Optional[int], streams: Dict[str, Any]) -> Optional[str]:
    """
    Decide whether we need a scale filter, based on the max height constraint.
    """
    if not max_height:
        return None
    v = next((s for s in streams.get("streams", []) if s.get("codec_type") == "video"), None)
    if not v:
        return None
    try:
        height = int(v.get("height", 0) or 0)
    except (TypeError, ValueError):
        height = 0
    if height and height > max_height:
        return f"scale=-2:{max_height}"
    return None

# --- Subtitles helpers -------------------------------------------------------

def list_subtitle_streams(info: Dict[str, Any]) -> list[dict]:
    """Return only subtitle streams from ffprobe JSON."""
    return [s for s in info.get("streams", []) if s.get("codec_type") == "subtitle"]

SDH_HINTS = {"sdh", "cc", "closed", "hearing", "impaired", "hi"}  # lowercased tokens

def is_sdh_sub(stream: dict) -> bool:
    """Heurística: tenta identificar SDH/Closed Captions por tags/disposition/título."""
    disp = stream.get("disposition") or {}
    if int(disp.get("hearing_impaired", 0)) == 1:
        return True
    tags = stream.get("tags") or {}
    t_title = (tags.get("title") or "").lower()
    t_lang = (tags.get("language") or "").lower()
    # alguns lançamentos marcam SDH no título ou no language (ex.: "eng-sdh")
    haystack = f"{t_title} {t_lang}".lower()
    return any(h in haystack for h in SDH_HINTS)

def sub_short_desc(s: dict) -> str:
    """Resumo para UI: [idx] lang=por | codec=ass | sdh/no | title=... | forced=yes/no"""
    tags = s.get("tags") or {}
    lang = (tags.get("language") or "und").lower()
    title = tags.get("title") or ""
    codec = s.get("codec_name") or "?"
    forced = (s.get("disposition") or {}).get("forced", 0)
    sdh = is_sdh_sub(s)
    bits = [
        f"lang={lang}",
        f"codec={codec}",
        f"sdh={'yes' if sdh else 'no'}",
        f"forced={'yes' if int(forced)==1 else 'no'}",
    ]
    if title:
        bits.append(f"title={title}")
    return " | ".join(bits)

def is_text_sub(codec: str) -> bool:
    """Text-based codecs we can convert to SRT."""
    return codec.lower() in {"subrip", "srt", "ass", "ssa", "webvtt", "mov_text", "text"}

def default_sub_ext(codec: str) -> str:
    c = codec.lower()
    if c in {"subrip", "srt"}:
        return ".srt"
    if c in {"ass", "ssa"}:
        return ".srt"  # vamos converter pra srt
    if c in {"webvtt"}:
        return ".srt"  # converte pra srt
    if c in {"mov_text", "text"}:
        return ".srt"
    if c in {"hdmv_pgs_subtitle", "pgs"}:
        return ".sup"
    if c in {"dvd_subtitle", "dvb_subtitle", "vobsub"}:
        return ".sub"  # pode gerar .sub + .idx dependendo do fonte
    return ".srt"
