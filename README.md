# Shrinkwrap

Local video compress + trim. See `DESIGN.md` (architecture) and `WHY.md` (reasoning).

## Run
1. Install FFmpeg: `brew install ffmpeg` / `sudo apt install ffmpeg` / `winget install ffmpeg`
2. `python -m venv .venv && source .venv/bin/activate` (Windows: `.venv\Scripts\activate`)
3. `pip install -r requirements.txt`
4. `python -m app` then open the full link it prints (it contains a one-time token).

Data lives in `~/.shrinkwrap` (override with `SHRINKWRAP_DATA`). Tests: `pytest tests`.
