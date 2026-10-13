# Shrinkwrap

Local video compress, trim & audio combiner. See `DESIGN.md` (architecture) and `WHY.md` (reasoning).

- **Compress & Trim**: Fast H.264 / H.265 compression, lossless cutting.
- **Video + Audio Combiner**: Replace or attach audio tracks to videos (e.g. `.mp4` video + `.m4a` audio, `.wav`, `.mp3`, etc.). Instant lossless video muxing or combined compression.
- **Single & Batch Management**: Smart filename auto-pairing, per-video audio selection, or apply one audio across all videos.

## Run
1. Install FFmpeg: `brew install ffmpeg` / `sudo apt install ffmpeg` / `winget install ffmpeg`
2. `python -m venv .venv && source .venv/bin/activate` (Windows: `.venv\Scripts\activate`)
3. `pip install -r requirements.txt`
4. `python -m app` then open the full link it prints (it contains a one-time token).

Data lives in `~/.shrinkwrap` (override with `SHRINKWRAP_DATA`). Tests: `python -m pytest tests`.

