import sqlite3
import pytest
from pathlib import Path
from app import db, config

def test_db_migration_idempotence(tmp_path, monkeypatch):
    db_file = tmp_path / "test_jobs.db"
    monkeypatch.setattr(config, "DB_PATH", db_file)
    monkeypatch.setattr(db, "DB_PATH", db_file)

    # 1. Create an old schema database without batch_id
    old_schema = """
    CREATE TABLE jobs (
      id TEXT PRIMARY KEY,
      display_name TEXT NOT NULL,
      input_path TEXT NOT NULL,
      output_path TEXT,
      options TEXT NOT NULL,
      status TEXT NOT NULL,
      progress REAL NOT NULL DEFAULT 0,
      error TEXT,
      in_size INTEGER,
      out_size INTEGER,
      duration REAL,
      created_at REAL NOT NULL
    );
    """
    with sqlite3.connect(db_file) as conn:
        conn.executescript(old_schema)
        conn.execute(
            "INSERT INTO jobs (id, display_name, input_path, options, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("job1", "test.mp4", "/tmp/test.mp4", "{}", "done", 1000.0)
        )
        conn.commit()

    # 2. Run init() first time
    db.init()

    # Verify columns exist and data intact
    with db.conn() as c:
        cols = [r["name"] for r in c.execute("PRAGMA table_info(jobs)").fetchall()]
        assert "batch_id" in cols
        assert "audio_path" in cols
        row = c.execute("SELECT * FROM jobs WHERE id='job1'").fetchone()
        assert row is not None
        assert row["display_name"] == "test.mp4"

    # 3. Run init() second time (idempotence)
    db.init()

    with db.conn() as c:
        cols = [r["name"] for r in c.execute("PRAGMA table_info(jobs)").fetchall()]
        assert cols.count("batch_id") == 1
        assert cols.count("audio_path") == 1
        row = c.execute("SELECT * FROM jobs WHERE id='job1'").fetchone()
        assert row is not None
        assert row["display_name"] == "test.mp4"


def test_batch_stats_counting(tmp_path, monkeypatch):
    db_file = tmp_path / "test_stats.db"
    monkeypatch.setattr(config, "DB_PATH", db_file)
    monkeypatch.setattr(db, "DB_PATH", db_file)
    db.init()

    batch_id = "a1b2c3d4e5f60718293a4b5c6d7e8f90"
    db.create_job("j1", "clip1.mp4", "/tmp/1", {}, 100, 10.0, batch_id=batch_id)
    db.create_job("j2", "clip2.mp4", "/tmp/2", {}, 250, 12.0, batch_id=batch_id)

    stats = db.get_batch_stats(batch_id)
    assert stats["count"] == 2
    assert stats["total_size"] == 350


def test_is_file_referenced(tmp_path, monkeypatch):
    db_file = tmp_path / "test_ref.db"
    monkeypatch.setattr(config, "DB_PATH", db_file)
    monkeypatch.setattr(db, "DB_PATH", db_file)
    db.init()

    audio_file = "/tmp/shared_music.m4a"
    db.create_job("j1", "video1.mp4", "/tmp/v1.mp4", {}, 100, 10.0, audio_path=audio_file)
    db.create_job("j2", "video2.mp4", "/tmp/v2.mp4", {}, 200, 15.0, audio_path=audio_file)

    # Both jobs are queued, so audio_file is referenced
    assert db.is_file_referenced(audio_file)
    # When j1 finishes, audio_file is still referenced by j2
    assert db.is_file_referenced(audio_file, exclude_job_id="j1")
    # Mark j2 as done
    db.update("j2", status="done")
    # Now excluding j1, j2 is done, so no active job references it
    assert not db.is_file_referenced(audio_file, exclude_job_id="j1")
