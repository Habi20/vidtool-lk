"""SQLite access. Every query is parameterized; values are never spliced into SQL."""
import json
import sqlite3
import time
from contextlib import contextmanager

from . import config
from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  input_path TEXT NOT NULL,
  output_path TEXT,
  options TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('queued','running','done','failed')),
  progress REAL NOT NULL DEFAULT 0,
  error TEXT,
  in_size INTEGER,
  out_size INTEGER,
  duration REAL,
  created_at REAL NOT NULL,
  batch_id TEXT,
  audio_path TEXT
);
"""


@contextmanager
def conn():
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    try:
        yield c
        c.commit()
    finally:
        c.close()


def cleanup_old_uploads():
    now = time.time()
    cutoff = now - 86400
    if config.UPLOAD_DIR.exists():
        for p in config.UPLOAD_DIR.glob("*"):
            if p.is_file() and p.stat().st_mtime < cutoff:
                p.unlink(missing_ok=True)


def init():
    with conn() as c:
        c.executescript(SCHEMA)
        cols = [r["name"] for r in c.execute("PRAGMA table_info(jobs)").fetchall()]
        if "batch_id" not in cols:
            c.execute("ALTER TABLE jobs ADD COLUMN batch_id TEXT")
        if "audio_path" not in cols:
            c.execute("ALTER TABLE jobs ADD COLUMN audio_path TEXT")
        # A crash mid-encode must not leave jobs "running" forever.
        c.execute("UPDATE jobs SET status='failed', error='Interrupted by restart' WHERE status IN ('queued','running')")
    cleanup_old_uploads()


def create_job(job_id, display_name, input_path, options: dict, in_size, duration, batch_id: str = None, audio_path: str = None):
    with conn() as c:
        c.execute(
            "INSERT INTO jobs (id, display_name, input_path, audio_path, options, status, in_size, duration, created_at, batch_id)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (job_id, display_name, str(input_path), str(audio_path) if audio_path else None, json.dumps(options), "queued", in_size, duration, time.time(), batch_id),
        )


def is_file_referenced(path_str: str, exclude_job_id: str = None) -> bool:
    with conn() as c:
        query = "SELECT 1 FROM jobs WHERE (input_path=? OR audio_path=?) AND status IN ('queued','running')"
        params = [path_str, path_str]
        if exclude_job_id:
            query += " AND id != ?"
            params.append(exclude_job_id)
        row = c.execute(query, params).fetchone()
        return row is not None


_UPDATABLE = {"status", "progress", "error", "output_path", "out_size"}


def update(job_id, **fields):
    assert set(fields) <= _UPDATABLE, f"unexpected columns: {set(fields) - _UPDATABLE}"
    cols = ", ".join(f"{k}=?" for k in fields)  # column names from the allowlist above; values are bound
    with conn() as c:
        c.execute(f"UPDATE jobs SET {cols} WHERE id=?", (*fields.values(), job_id))


def get(job_id):
    with conn() as c:
        row = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return dict(row) if row else None


def get_batch_stats(batch_id: str):
    with conn() as c:
        row = c.execute("SELECT COUNT(*) as count, COALESCE(SUM(in_size), 0) as total_size FROM jobs WHERE batch_id=?", (batch_id,)).fetchone()
        return dict(row) if row else {"count": 0, "total_size": 0}


def get_batch_jobs(batch_id: str):
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM jobs WHERE batch_id=? ORDER BY created_at ASC", (batch_id,))]


def list_jobs(limit=50):
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,))]


def delete(job_id):
    with conn() as c:
        c.execute("DELETE FROM jobs WHERE id=?", (job_id,))
