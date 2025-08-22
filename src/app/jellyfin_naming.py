"""
Jellyfin-friendly naming helpers.

For movies we keep: "Title (Year).ext"
Later we can extend this module to support series (SxxEyy) or other naming rules.
"""

from pathlib import Path


def sanitize_name(name: str) -> str:
    """
    Replace path separators and collapse multiple spaces to keep filenames safe.
    """
    return " ".join(name.replace("/", "-").split())


def movie_filename(title: str | None, year: int | None, container: str) -> str:
    """
    Build a Jellyfin-friendly filename like: "Movie Title (2024).mp4"
    """
    title_part = sanitize_name(title or "Unknown Title")
    year_part = f" ({year})" if year else ""
    return f"{title_part}{year_part}.{container.lower()}"


def movie_folder(title: str | None, year: int | None) -> Path:
    """Return folder name 'Title (Year)' or 'Title' if year is missing."""
    title_part = sanitize_name(title or "Unknown Title")
    year_part = f" ({year})" if year else ""
    return Path(f"{title_part}{year_part}")
