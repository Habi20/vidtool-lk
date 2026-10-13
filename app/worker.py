"""One job at a time: an encoder already uses every CPU core, so parallel jobs only slow each other."""
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import db, media, security
from .config import LOG_DIR, OUTPUT_DIR

log = logging.getLogger("shrinkwrap.worker")
_pool = ThreadPoolExecutor(max_workers=1)


def submit(job_id: str) -> None:
    _pool.submit(_run, job_id)


def _run(job_id: str) -> None:
    job = db.get(job_id)
    if not job:
        return
    o = json.loads(job["options"])
    src = Path(job["input_path"])
    audio_src = Path(job["audio_path"]) if job.get("audio_path") else None

    dst = OUTPUT_DIR / f"{job_id}.{o['container']}"
    try:
        db.update(job_id, status="running", progress=0)
        start, end = media.trim_window(o, job["duration"])
        cmd = media.build_command(src, dst, o, job["duration"], audio_src=audio_src)
        log.info("job %s: %s", job_id, " ".join(cmd))
        media.run(cmd, end - start, LOG_DIR / f"{job_id}.log", lambda p: db.update(job_id, progress=p))
        db.update(job_id, status="done", progress=1, output_path=str(dst), out_size=dst.stat().st_size)
    except media.MediaError as e:
        dst.unlink(missing_ok=True)
        db.update(job_id, status="failed", error=str(e))
    except Exception:
        log.exception("job %s crashed", job_id)       # full detail goes to logs only, never to the browser
        dst.unlink(missing_ok=True)
        db.update(job_id, status="failed", error="Unexpected error (see logs)")
    finally:
        if not db.is_file_referenced(str(src), exclude_job_id=job_id):
            src.unlink(missing_ok=True)
        if audio_src and not db.is_file_referenced(str(audio_src), exclude_job_id=job_id):
            audio_src.unlink(missing_ok=True)
