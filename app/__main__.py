import logging
import shutil
import sys

import uvicorn

from . import config

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            sys.exit(f"{tool} not found. Install FFmpeg first (see README).")
    print(f"\n  Shrinkwrap is running. Open:\n  http://{config.HOST}:{config.PORT}/?t={config.TOKEN}\n")
    uvicorn.run("app.main:app", host=config.HOST, port=config.PORT, log_level="warning")
