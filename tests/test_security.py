import pytest
from app import security as s


def test_ext_allowlist():
    assert s.validate_ext("a.MP4") == ".mp4"
    for bad in ["a.exe", "a", "a.mp4.sh", ""]:
        with pytest.raises(ValueError):
            s.validate_ext(bad)


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
