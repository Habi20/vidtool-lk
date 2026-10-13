from pathlib import Path
import pytest
from app import media


def opts(**kw):
    return {"mode": "compress", "codec": "h264", "quality": "balanced", "speed": "fast",
            "max_height": None, "container": "mp4", "start": 0, "end": None, **kw}


def test_compress_command_has_no_shell_and_uses_crf():
    cmd = media.build_command(Path("in.mp4"), Path("out.mp4"), opts(), 100)
    assert isinstance(cmd, list) and "-crf" in cmd and cmd[cmd.index("-crf") + 1] == "23"


def test_trim_only_copies_streams():
    cmd = media.build_command(Path("in.mp4"), Path("out.mp4"), opts(mode="trim", start=5, end=10), 100)
    assert "copy" in cmd and "-ss" in cmd and cmd[cmd.index("-t") + 1] == "5.000"


def test_bad_trim_rejected():
    with pytest.raises(media.MediaError):
        media.build_command(Path("a"), Path("b"), opts(start=50, end=10), 100)


def test_network_protocols_blocked():
    assert "-protocol_whitelist" in media.build_command(Path("a"), Path("b"), opts(), 10)
