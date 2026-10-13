"""SQLite access. Every query is parameterized; values are never spliced into SQL."""
import json
import sqlite3
import time
from contextlib import contextmanager

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
  created_at REAL NOT NULL
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


def init():
    with conn() as c:
        c.executescript(SCHEMA)
        # A crash mid-encode must not leave jobs "running" forever.
        c.execute("UPDATE jobs SET status='failed', error='Interrupted by restart' WHERE status IN ('queued','running')")


def create_job(job_id, display_name, input_path, options: dict, in_size, duration):
    with conn() as c:
        c.execute(
            "INSERT INTO jobs (id, display_name, input_path, options, status, in_size, duration, created_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (job_id, display_name, str(input_path), json.dumps(options), "queued", in_size, duration, time.time()),
        )


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


def list_jobs(limit=50):
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,))]


def delete(job_id):
    with conn() as c:
        c.execute("DELETE FROM jobs WHERE id=?", (job_id,))
