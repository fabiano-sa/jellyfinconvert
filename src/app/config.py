"""
Configuration defaults for the converter.

This module centralizes tunable defaults so we don't scatter magic numbers
across the codebase. You can change presets, codecs, CRF values, etc. here
and other modules will pick them up.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Defaults:
    # IO folders (can be overridden by env or CLI)
    default_input_dir: Path = Path(os.getenv("JFCVT_INPUT_DIR", "videos/input"))
    default_output_dir: Path = Path(os.getenv("JFCVT_OUTPUT_DIR", "videos/output"))

    # Codecs and containers
    video_codec_h264: str = "libx264"  # base codec
    video_codec_h265: str = "libx265"  # optional (better compression, slower)
    audio_codec: str = "aac"  # universal compatibility
    container: str = "mp4"  # default between mp4/mkv

    # Quality / speed knobs
    crf_h264: int = 20  # lower = better quality (and bigger file)
    crf_h265: int = 24
    preset: str = "medium"  # ffmpeg presets: ultrafast..veryslow
    audio_bitrate: str = "192k"

    # Optional resolution cap (e.g., 1080 for 1080p)
    max_height: int | None = None

    # Logging & reports
    log_dir: Path = Path("logs")
    report_csv: Path = Path("logs/report.csv")
    report_json: Path = Path("logs/report.json")


DEFAULTS = Defaults()
