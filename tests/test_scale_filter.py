from app.ffmpeg_utils import build_scale_filter


def test_build_scale_filter_when_height_exceeds():
    streams = {"streams": [{"codec_type": "video", "height": 2160}]}
    assert build_scale_filter(1080, streams) == "scale=-2:1080"

def test_build_scale_filter_no_limit_or_small():
    streams = {"streams": [{"codec_type": "video", "height": 720}]}
    assert build_scale_filter(None, streams) is None
    assert build_scale_filter(1080, streams) is None
