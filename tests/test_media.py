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


def test_combine_audio_maps_streams_and_bounds_duration():
    cmd = media.build_command(Path("in.mp4"), Path("out.mp4"), opts(mode="combine"), 45.0, audio_src=Path("track.m4a"))
    assert "-i" in cmd
    # Two -i flags for video and audio
    indices = [i for i, x in enumerate(cmd) if x == "-i"]
    assert len(indices) == 2
    assert cmd[indices[0] + 1] == "in.mp4"
    assert cmd[indices[1] + 1] == "track.m4a"
    # Stream mappings
    assert "-map" in cmd
    assert cmd[cmd.index("-map") + 1] == "0:v:0"
    map2_idx = cmd.index("-map", cmd.index("-map") + 2)
    assert cmd[map2_idx + 1] == "1:a:0"
    # Video copied, audio transcoded to aac
    assert "-c:v" in cmd and cmd[cmd.index("-c:v") + 1] == "copy"
    assert "-c:a" in cmd and cmd[cmd.index("-c:a") + 1] == "aac"
    # Duration bounded to video length
    assert "-t" in cmd and cmd[cmd.index("-t") + 1] == "45.000"


def test_compress_with_audio_maps_audio_source():
    cmd = media.build_command(Path("in.mp4"), Path("out.mp4"), opts(mode="compress"), 60.0, audio_src=Path("audio.wav"))
    assert "-map" in cmd
    assert "1:a:0" in cmd
    assert "-c:v" in cmd and cmd[cmd.index("-c:v") + 1] == "libx264"
    assert "-c:a" in cmd and cmd[cmd.index("-c:a") + 1] == "aac"
    assert "-t" in cmd and cmd[cmd.index("-t") + 1] == "60.000"


def test_compression_quality_bitrates_and_crf():
    # Smallest file uses 96k audio and high compression CRF
    cmd_small = media.build_command(Path("in.mp4"), Path("out.mp4"), opts(quality="small", codec="h265"), 100)
    assert cmd_small[cmd_small.index("-crf") + 1] == "34"
    assert cmd_small[cmd_small.index("-b:a") + 1] == "96k"

    # Balanced uses 128k audio
    cmd_bal = media.build_command(Path("in.mp4"), Path("out.mp4"), opts(quality="balanced", codec="h264"), 100)
    assert cmd_bal[cmd_bal.index("-crf") + 1] == "23"
    assert cmd_bal[cmd_bal.index("-b:a") + 1] == "128k"


