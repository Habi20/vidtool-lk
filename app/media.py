"""All FFmpeg knowledge lives here. Nothing else builds commands or touches subprocess."""
import json
import subprocess
from pathlib import Path
from typing import Callable

CRF = {"h264": {"small": 28, "balanced": 23, "high": 19}, "h265": {"small": 32, "balanced": 28, "high": 24}}
PRESET = {"fast": "veryfast", "balanced": "medium", "thorough": "slow"}
LIB = {"h264": "libx264", "h265": "libx265"}


class MediaError(Exception):
    """Message is safe to show to the user."""


def probe(path: Path) -> dict:
    """Ask ffprobe what the file really is. The extension is never trusted."""
    cmd = ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
    except FileNotFoundError:
        raise MediaError("FFmpeg is not installed or not on PATH")
    except subprocess.TimeoutExpired:
        raise MediaError("File could not be read in time")
    if r.returncode != 0:
        raise MediaError("File is not a readable media file")
    data = json.loads(r.stdout or "{}")
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)

    # Some audio files (e.g. mp3, m4a) have embedded album art tagged as video stream
    is_attached_pic = bool(video and video.get("disposition", {}).get("attached_pic"))

    fmt_duration = data.get("format", {}).get("duration")
    stream_duration = (video.get("duration") if video and not is_attached_pic else None) or (audio.get("duration") if audio else None)

    duration = 0.0
    try:
        if fmt_duration and fmt_duration != "N/A":
            duration = float(fmt_duration)
        elif stream_duration and stream_duration != "N/A":
            duration = float(stream_duration)
    except (ValueError, TypeError):
        duration = 0.0

    if video and not is_attached_pic and duration > 0:
        return {
            "media_type": "video",
            "duration": duration,
            "width": video.get("width"),
            "height": video.get("height"),
            "codec": video.get("codec_name"),
            "has_audio": audio is not None,
        }
    elif audio and duration > 0:
        return {
            "media_type": "audio",
            "duration": duration,
            "codec": audio.get("codec_name"),
            "channels": audio.get("channels"),
            "sample_rate": audio.get("sample_rate"),
        }
    else:
        raise MediaError("No playable video or audio stream found in this file")


def trim_window(o: dict, duration: float) -> tuple[float, float]:
    start = float(o.get("start") or 0)
    end = min(float(o["end"]), duration) if o.get("end") else duration
    if start >= end:
        raise MediaError("Trim start must be before trim end")
    return start, end


def build_command(src: Path, dst: Path, o: dict, duration: float, audio_src: Path | None = None) -> list[str]:
    """Returns an argv list. It is never joined into a string or run through a shell."""
    start, end = trim_window(o, duration)
    cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-y", "-protocol_whitelist", "file",
           "-progress", "pipe:1", "-nostats"]
    if start > 0:
        cmd += ["-ss", f"{start:.3f}"]            # before -i = fast seek
    cmd += ["-i", str(src)]
    if audio_src:
        if start > 0:
            cmd += ["-ss", f"{start:.3f}"]
        cmd += ["-i", str(audio_src)]

    clip_dur = end - start
    if start > 0 or end < duration or audio_src:
        cmd += ["-t", f"{clip_dur:.3f}"]

    if audio_src:
        cmd += ["-map", "0:v:0", "-map", "1:a:0", "-sn", "-dn"]
    else:
        cmd += ["-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn"]

    mode = o.get("mode", "compress")
    if mode == "combine":                         # instant mux: copy video, transcode audio to standard aac
        cmd += ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k"]
    elif mode == "trim":                          # lossless cuts
        if audio_src:
            cmd += ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-avoid_negative_ts", "make_zero"]
        else:
            cmd += ["-c", "copy", "-avoid_negative_ts", "make_zero"]
    else:
        codec = o["codec"]
        cmd += ["-c:v", LIB[codec], "-crf", str(CRF[codec][o["quality"]]), "-preset", PRESET[o["speed"]],
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k"]
        if o.get("max_height"):
            cmd += ["-vf", f"scale=-2:'min(ih,{int(o['max_height'])})'"]
        if codec == "h265" and o["container"] == "mp4":
            cmd += ["-tag:v", "hvc1"]              # Apple/QuickTime compatibility
    if o["container"] == "mp4":
        cmd += ["-movflags", "+faststart"]
    cmd.append(str(dst))
    return cmd


def run(cmd: list[str], total_seconds: float, log_path: Path, on_progress: Callable[[float], None]) -> None:
    """Run ffmpeg without a shell. stderr goes to a log file so it can never fill a pipe and deadlock."""
    with open(log_path, "w") as log:
        log.write(" ".join(cmd) + "\n\n")
        log.flush()
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=log, text=True)
        for line in p.stdout:
            key, _, val = line.strip().partition("=")
            if key in ("out_time_us", "out_time_ms"):
                clean_val = val.lstrip("-")
                if clean_val.isdigit():
                    sec = int(val) / 1_000_000
                    prog = max(0.0, min(sec / max(total_seconds, 0.001), 0.99))
                    on_progress(prog)
        if p.wait() != 0:
            raise MediaError(f"Encoding failed (see log {log_path.name})")

