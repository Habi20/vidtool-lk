"""Single source of truth for settings. Nothing else reads os.environ."""
import os
import secrets
from pathlib import Path

HOST = "127.0.0.1"  # never 0.0.0.0 in MVP: local-only is the main security control
PORT = int(os.environ.get("SHRINKWRAP_PORT", "8765"))

DATA_DIR = Path(os.environ.get("SHRINKWRAP_DATA", Path.home() / ".shrinkwrap")).resolve()
UPLOAD_DIR = DATA_DIR / "uploads"
OUTPUT_DIR = DATA_DIR / "outputs"
LOG_DIR = DATA_DIR / "logs"
DB_PATH = DATA_DIR / "jobs.db"

MAX_UPLOAD_BYTES = int(os.environ.get("SHRINKWRAP_MAX_GB", "20")) * 1024**3
ALLOWED_EXT = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".flv", ".wmv", ".mpg", ".mpeg", ".ts", ".3gp"}
ALLOWED_HOSTS = {"127.0.0.1", "localhost"}
ALLOWED_ORIGINS = {f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"}

# Fresh per process: a page from another site cannot guess it.
TOKEN = secrets.token_urlsafe(32)

for d in (UPLOAD_DIR, OUTPUT_DIR, LOG_DIR):
    d.mkdir(parents=True, exist_ok=True)
