"""
Utilities to infer human-friendly title and year from common "scene/release" filenames.

Examples handled:
- "Cyberpunk.Edgerunners.2022.UNRATED.1080p.BluRay.x265-RARBG"
- "Movie.Title.2019.2160p.WEB-DL.x265-Group"
- "Some-Film-Name (2021) 1080p BluRay x264"
- "Another_Movie_2008_BRRip_xvid"

Heuristics:
- Year: first 4-digit year in 1900..2099 (regex-based).
- Title tokens: take tokens until we hit a known tag (resolution/source/codec/etc.)
  or a dash-separated group suffix. Replace separators with spaces and collapse.
"""

from __future__ import annotations

import re
from pathlib import Path

# Acceptable year pattern (not part of a longer number)
YEAR_RE = re.compile(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)")

# Token separators we often see in releases
TOKEN_SPLIT_RE = re.compile(r"[.\s_\-]+")

# Stopword/tag sets (lowercased) used to stop capturing title tokens
RES_TAGS = {
    "480p",
    "576p",
    "720p",
    "1080p",
    "1440p",
    "2160p",
    "4k",
    "8k",
}
SOURCE_TAGS = {
    "bluray",
    "bdrip",
    "brrip",
    "web",
    "webrip",
    "web-dl",
    "webdl",
    "hdrip",
    "dvdrip",
    "dvd",
    "hdtv",
    "remux",
    "blu-ray",
}
CODEC_TAGS = {
    "x264",
    "x265",
    "h264",
    "h265",
    "hevc",
    "av1",
    "xvid",
    "divx",
}
AUDIO_TAGS = {
    "aac",
    "ac3",
    "eac3",
    "ddp",
    "dd+",
    "dts",
    "truehd",
    "atmos",
    "mp3",
    "flac",
}
EDITION_TAGS = {
    "unrated",
    "extended",
    "director",
    "cut",
    "remastered",
    "proper",
    "repack",
    "theatrical",
}
LANG_TAGS = {
    "multi",
    "dual",
    "ita",
    "lat",
    "esp",
    "eng",
    "pt",
    "pt-br",
    "br",
    "subs",
}

STOP_TAGS = RES_TAGS | SOURCE_TAGS | CODEC_TAGS | AUDIO_TAGS | EDITION_TAGS | LANG_TAGS


def _split_title_group(stem: str) -> str:
    """
    If the filename has a scene-group suffix like "...-RARBG" or "...-GROUP",
    keep only the left side for title inference.
    """
    # Keep only the left part before the last '-' when it looks like a group tag.
    # Example: "Title.2022.1080p.x265-RARBG" -> "Title.2022.1080p.x265"
    if "-" in stem:
        left, right = stem.rsplit("-", 1)
        # Heuristic: if the right part is short (group tag), drop it
        if 1 <= len(right) <= 12:
            return left
    return stem


def _is_stop_tag(tok: str) -> bool:
    t = tok.lower()
    return t in STOP_TAGS


def _clean_tokens(tokens: list[str]) -> list[str]:
    """
    Remove empty tokens and obvious junk (e.g., extra brackets).
    """
    out: list[str] = []
    for t in tokens:
        t = t.strip("[](){}")
        if not t:
            continue
        out.append(t)
    return out


def _collapse_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def infer_title_and_year(filename: str) -> tuple[str, int | None]:
    """
    Infer a human-friendly title and (optionally) a year from a release filename.

    Returns:
        (title, year)  where year may be None if not found
    """
    stem = Path(filename).stem

    # 1) Remove trailing group suffix like "-RARBG"
    stem = _split_title_group(stem)

    # 2) Find year anywhere in the stem (we'll also use it as a stop signal)
    m = YEAR_RE.search(stem)
    year: int | None = int(m.group(1)) if m else None

    # 3) Tokenize by common separators (., _, -, space)
    tokens = _clean_tokens(TOKEN_SPLIT_RE.split(stem))

    # 4) Accumulate title tokens until a stop tag or after the year is seen
    title_tokens: list[str] = []
    for tok in tokens:
        # If we hit the year, mark and don't include it as a title token
        if YEAR_RE.fullmatch(tok or ""):
            # Once year is seen, usually the rest are tags; we break here.
            break

        # Stop at known tags like 1080p, BluRay, x265, etc.
        if _is_stop_tag(tok):
            break

        # Some releases put edition words before year; keep them if they are meaningful?
        # Here we keep only non-stop tokens.
        title_tokens.append(tok)

    # Fallback: if nothing captured yet and we saw a year, take everything before year
    if not title_tokens and m:
        before_year = stem[: m.start()]
        title_tokens = _clean_tokens(TOKEN_SPLIT_RE.split(before_year))

    # If still empty, use the stem as-is (last resort)
    if not title_tokens:
        title_tokens = [stem]

    # 5) Join tokens with spaces and tidy up
    raw_title = _collapse_spaces(" ".join(title_tokens))

    # Example cleanup: "Cyberpunk Edgerunners" (replace dots/underscores already handled)
    # Optional: smarter capitalization could be added; we keep original case of tokens.

    return raw_title, year
