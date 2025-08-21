"""
Build metadata dicts to pass to ffmpeg (-metadata key=value).
We keep keys simple and widely recognized: title, date, year.
"""

from typing import Dict, Optional


def build_metadata(title: Optional[str], year: Optional[int]) -> Dict[str, str]:
    meta: Dict[str, str] = {}
    if title:
        meta["title"] = title
    if year:
        meta["date"] = str(year)  # ffmpeg commonly accepts "date"
        meta["year"] = str(year)  # some players read "year"
    return meta
