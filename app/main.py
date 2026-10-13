import io
import secrets
import time
import uuid
import zipfile
from pathlib import Path
from typing import Literal, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config, db, media, security, worker

STATIC = Path(__file__).parent.parent / "static"
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
db.init()

CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
       "img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


class StreamBuffer(io.RawIOBase):
    def __init__(self):
        self._buffer = bytearray()

    def write(self, b):
        if b:
            self._buffer.extend(b)
        return len(b)

    def read_all(self):
        chunk = bytes(self._buffer)
        self._buffer.clear()
        return chunk


@app.middleware("http")
async def guard(request: Request, call_next):
    # DNS-rebinding defense: only accept requests addressed to localhost.
    if security.host_only(request.headers.get("host", "")) not in config.ALLOWED_HOSTS:
        return JSONResponse({"error": "Bad host"}, status_code=403)
    # CSRF defense: state-changing calls must come from our own origin.
    if request.method not in ("GET", "HEAD") and request.headers.get("origin") not in config.ALLOWED_ORIGINS:
        return JSONResponse({"error": "Bad origin"}, status_code=403)
    resp = await call_next(request)
    resp.headers.update({"Content-Security-Policy": CSP, "X-Content-Type-Options": "nosniff",
                         "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY", "Cache-Control": "no-store"})
    return resp


def auth(request: Request):
    supplied = request.headers.get("x-token") or request.query_params.get("t") or ""
    if not secrets.compare_digest(supplied.encode(), config.TOKEN.encode()):
        raise HTTPException(401, "Unauthorized")


class Options(BaseModel):
    mode: Literal["compress", "trim"] = "compress"
    codec: Literal["h264", "h265"] = "h264"
    quality: Literal["small", "balanced", "high"] = "balanced"
    speed: Literal["fast", "balanced", "thorough"] = "fast"
    max_height: Optional[Literal[2160, 1440, 1080, 720, 480]] = None
    container: Literal["mp4", "mkv"] = "mp4"
    start: float = Field(0, ge=0, le=172800)
    end: Optional[float] = Field(None, gt=0, le=172800)


class JobRequest(BaseModel):
    file_id: str
    name: str = Field("video", max_length=255)
    options: Options
    batch_id: Optional[str] = None


@app.get("/", response_class=HTMLResponse)
def index(t: str = ""):
    if not secrets.compare_digest(t.encode(), config.TOKEN.encode()):
        return HTMLResponse("Open the full link printed in your terminal.", status_code=401)
    return (STATIC / "index.html").read_text().replace("__TOKEN__", config.TOKEN)


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.post("/api/upload", dependencies=[Depends(auth)])
async def upload(request: Request, name: str):
    try:
        ext = security.validate_ext(name)
    except ValueError as e:
        raise HTTPException(415, str(e))
    file_id = uuid.uuid4().hex
    dest = config.UPLOAD_DIR / f"{file_id}{ext}"   # server-generated name; user input never touches the path
    size = 0
    try:
        with open(dest, "wb") as f:
            async for chunk in request.stream():
                size += len(chunk)
                if size > config.MAX_UPLOAD_BYTES:
                    raise HTTPException(413, "File too large")
                f.write(chunk)
        info = await run_in_threadpool(media.probe, dest)
    except media.MediaError as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(415, str(e))
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    return {"file_id": file_id, "size": size, **info}


def _to_dict(model: BaseModel) -> dict:
    return model.model_dump() if hasattr(model, "model_dump") else model.dict()


@app.post("/api/jobs", dependencies=[Depends(auth)])
def create_job(req: JobRequest):
    try:
        file_id = security.parse_id(req.file_id)
    except ValueError:
        raise HTTPException(400, "Invalid file id")

    batch_id = None
    if req.batch_id:
        try:
            batch_id = security.parse_id(req.batch_id)
        except ValueError:
            raise HTTPException(400, "Invalid batch id")
        stats = db.get_batch_stats(batch_id)
        if stats["count"] >= config.MAX_BATCH_FILES:
            raise HTTPException(413, f"Batch file count limit ({config.MAX_BATCH_FILES}) exceeded")

    src = next(config.UPLOAD_DIR.glob(f"{file_id}.*"), None)
    if not src or not security.is_within(config.UPLOAD_DIR, src):
        raise HTTPException(404, "Upload not found")

    if batch_id:
        if stats["total_size"] + src.stat().st_size > config.MAX_BATCH_BYTES:
            raise HTTPException(413, "Batch total size limit exceeded")

    info = media.probe(src)
    opts_dict = _to_dict(req.options)
    try:
        media.trim_window(opts_dict, info["duration"])
    except media.MediaError as e:
        raise HTTPException(422, str(e))
    job_id = uuid.uuid4().hex
    db.create_job(job_id, security.display_name(req.name), src, opts_dict, src.stat().st_size, info["duration"], batch_id)
    worker.submit(job_id)
    return db.get(job_id)


@app.get("/api/jobs", dependencies=[Depends(auth)])
def jobs():
    return [{k: v for k, v in j.items() if k not in ("input_path", "output_path")} for j in db.list_jobs()]


@app.get("/api/jobs/{job_id}/download", dependencies=[Depends(auth)])
def download(job_id: str):
    job = _job_or_404(job_id)
    out = Path(job["output_path"] or "")
    if job["status"] != "done" or not security.is_within(config.OUTPUT_DIR, out) or not out.exists():
        raise HTTPException(404, "Output not available")
    filename = f"{Path(job['display_name']).stem}-comp{out.suffix}"
    return FileResponse(out, filename=filename, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/api/batches/{batch_id}/download", dependencies=[Depends(auth)])
def download_batch(batch_id: str):
    try:
        security.parse_id(batch_id)
    except ValueError:
        raise HTTPException(400, "Invalid batch id")

    batch_jobs = db.get_batch_jobs(batch_id)
    valid_jobs = []
    raw_names = []
    for j in batch_jobs:
        if j["status"] == "done" and j["output_path"]:
            out = Path(j["output_path"])
            if security.is_within(config.OUTPUT_DIR, out) and out.exists():
                valid_jobs.append(j)
                stem = Path(j["display_name"]).stem
                raw_names.append(f"{stem}-comp{out.suffix}")

    if not valid_jobs:
        raise HTTPException(404, "No completed outputs found for this batch")

    deduped_names = security.deduplicate_names(raw_names)

    def stream_zip():
        buf = StreamBuffer()
        with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_STORED) as zf:
            for job, entry_name in zip(valid_jobs, deduped_names):
                out_path = Path(job["output_path"])
                info = zipfile.ZipInfo(entry_name)
                info.date_time = time.localtime(out_path.stat().st_mtime)[:6]
                info.external_attr = 0o600 << 16
                with zf.open(info, mode="w", force_zip64=True) as dest_file:
                    with open(out_path, "rb") as src_file:
                        while chunk := src_file.read(64 * 1024):
                            dest_file.write(chunk)
                            yield buf.read_all()
                yield buf.read_all()
        yield buf.read_all()

    filename = f"shrinkwrap-batch-{batch_id[:8]}.zip"
    return StreamingResponse(
        stream_zip(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@app.delete("/api/jobs/{job_id}", dependencies=[Depends(auth)])
def remove(job_id: str):
    job = _job_or_404(job_id)
    if job["status"] == "running":
        raise HTTPException(409, "Job is running")
    if job["output_path"] and security.is_within(config.OUTPUT_DIR, Path(job["output_path"])):
        Path(job["output_path"]).unlink(missing_ok=True)
    db.delete(job_id)
    return {"ok": True}


def _job_or_404(job_id: str) -> dict:
    try:
        security.parse_id(job_id)
    except ValueError:
        raise HTTPException(400, "Invalid id")
    job = db.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job
