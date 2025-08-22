"""
Build metadata dicts to pass to ffmpeg (-metadata key=value).
We keep keys simple and widely recognized: title, date, year.
"""



def build_metadata(title: str | None, year: int | None) -> dict[str, str]:
    meta: dict[str, str] = {}
    if title:
        meta["title"] = title
    if year:
        meta["date"] = str(year)  # ffmpeg commonly accepts "date"
        meta["year"] = str(year)  # some players read "year"
    return meta
