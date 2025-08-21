from app.jellyfin_naming import movie_filename, sanitize_name
from app.metadata import build_metadata


def test_movie_filename():
    assert movie_filename("My Film", 2024, "mp4") == "My Film (2024).mp4"
    assert movie_filename("A/B Test", None, "mkv") == "A-B Test.mkv"


def test_build_metadata():
    meta = build_metadata("Title", 2023)
    assert meta["title"] == "Title"
    assert meta["year"] == "2023"
    assert meta["date"] == "2023"
