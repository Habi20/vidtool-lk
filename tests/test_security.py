import pytest
from app import security as s


def test_ext_allowlist():
    assert s.validate_ext("a.MP4") == ".mp4"
    assert s.validate_ext("song.M4A") == ".m4a"
    assert s.validate_ext("track.mp3") == ".mp3"
    assert s.validate_ext("audio.wav") == ".wav"
    for bad in ["a.exe", "a", "a.mp4.sh", ""]:
        with pytest.raises(ValueError):
            s.validate_ext(bad)


def test_audio_and_video_helpers():
    assert s.is_video_ext("clip.mp4")
    assert s.is_video_ext("movie.mkv")
    assert not s.is_video_ext("song.m4a")
    assert s.is_audio_ext("song.m4a")
    assert s.is_audio_ext("voice.wav")
    assert not s.is_audio_ext("clip.mp4")


@pytest.mark.parametrize("bad", ["../etc/passwd", "x" * 31, "g" * 32, "a'; DROP TABLE jobs;--", "*" * 32])
def test_id_rejects_garbage(bad):
    with pytest.raises(ValueError):
        s.parse_id(bad)


def test_display_name_is_sanitized():
    assert "/" not in s.display_name("../../a<script>.mp4")


def test_is_within(tmp_path):
    assert s.is_within(tmp_path, tmp_path / "a.mp4")
    assert not s.is_within(tmp_path, tmp_path / ".." / "x")


def test_host_only():
    assert s.host_only("127.0.0.1:8765") == "127.0.0.1"
    assert s.host_only("evil.com:80") == "evil.com"


def test_deduplicate_names():
    names = ["video.mp4", "VIDEO.mp4", "video (2).mp4", "other.mkv"]
    deduped = s.deduplicate_names(names)
    assert deduped == ["video.mp4", "VIDEO (2).mp4", "video (2) (2).mp4", "other.mkv"]

