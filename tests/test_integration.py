import io
import shutil
import subprocess
import time
import uuid
import zipfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")


@pytest.fixture
def client():
    return TestClient(app, base_url=f"http://127.0.0.1:{config.PORT}")


@pytest.fixture
def sample_video(tmp_path):
    """Generate a 1-second test clip using ffmpeg lavfi."""
    video_path = tmp_path / "test_clip.mp4"
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=1000:duration=1",
        "-c:v", "libx264", "-c:a", "aac",
        str(video_path)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0 or not video_path.exists():
        pytest.skip(f"Could not generate sample video: {res.stderr}")
    return video_path


@pytest.fixture
def sample_audio(tmp_path):
    """Generate a 2-second test audio file in m4a format."""
    audio_path = tmp_path / "test_audio.m4a"
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
        "-c:a", "aac",
        str(audio_path)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0 or not audio_path.exists():
        pytest.skip(f"Could not generate sample audio: {res.stderr}")
    return audio_path


def test_auth_rejection(client):
    res = client.get("/api/jobs", headers={"Host": f"127.0.0.1:{config.PORT}"})
    assert res.status_code == 401


def test_host_rejection(client):
    res = client.get("/api/jobs", headers={"Host": "evil.com"})
    assert res.status_code == 403
    assert res.json() == {"error": "Bad host"}


def test_csrf_origin_rejection(client):
    headers = {
        "Host": f"127.0.0.1:{config.PORT}",
        "X-Token": config.TOKEN,
        "Origin": "http://evil-website.com"
    }
    res = client.post("/api/jobs", json={}, headers=headers)
    assert res.status_code == 403
    assert res.json() == {"error": "Bad origin"}


def test_upload_and_job_lifecycle(client, sample_video):
    headers = {
        "Host": f"127.0.0.1:{config.PORT}",
        "X-Token": config.TOKEN,
        "Origin": f"http://127.0.0.1:{config.PORT}"
    }

    # 1. Upload video
    with open(sample_video, "rb") as f:
        res = client.post(
            f"/api/upload?name={sample_video.name}",
            content=f.read(),
            headers=headers
        )
    assert res.status_code == 200, f"Upload failed: {res.text}"
    data = res.json()
    assert "file_id" in data
    assert data["duration"] > 0
    file_id = data["file_id"]

    # 2. Create compression job
    job_req = {
        "file_id": file_id,
        "name": "my_sample_video.mp4",
        "options": {
            "mode": "compress",
            "codec": "h264",
            "quality": "small",
            "speed": "fast",
            "max_height": 480,
            "container": "mp4",
            "start": 0,
            "end": 0.5
        }
    }
    res = client.post("/api/jobs", json=job_req, headers=headers)
    assert res.status_code == 200, f"Job creation failed: {res.text}"
    job = res.json()
    job_id = job["id"]
    assert job["status"] in ("queued", "running")

    # 3. Poll job until done
    for _ in range(50):
        res = client.get("/api/jobs", headers=headers)
        assert res.status_code == 200
        jobs = res.json()
        target = next((j for j in jobs if j["id"] == job_id), None)
        assert target is not None
        if target["status"] in ("done", "failed"):
            break
        time.sleep(0.1)

    assert target["status"] == "done", f"Job failed: {target.get('error')}"
    assert target["out_size"] > 0

    # 4. Download processed output
    res = client.get(f"/api/jobs/{job_id}/download", headers=headers)
    assert res.status_code == 200
    assert len(res.content) == target["out_size"]

    # 5. Delete job
    res = client.delete(f"/api/jobs/{job_id}", headers=headers)
    assert res.status_code == 200

    # Verify job is gone
    res = client.get("/api/jobs", headers=headers)
    assert not any(j["id"] == job_id for j in res.json())


def test_batch_encoding_and_zip_download(client, sample_video):
    headers = {
        "Host": f"127.0.0.1:{config.PORT}",
        "X-Token": config.TOKEN,
        "Origin": f"http://127.0.0.1:{config.PORT}"
    }

    batch_id = uuid.uuid4().hex

    # 1. Upload first clip
    with open(sample_video, "rb") as f:
        res1 = client.post(f"/api/upload?name=clip1.mp4", content=f.read(), headers=headers)
    assert res1.status_code == 200
    file_id1 = res1.json()["file_id"]

    # 2. Upload second clip (same content, different display name)
    with open(sample_video, "rb") as f:
        res2 = client.post(f"/api/upload?name=clip1.mp4", content=f.read(), headers=headers)
    assert res2.status_code == 200
    file_id2 = res2.json()["file_id"]

    options = {
        "mode": "compress",
        "codec": "h264",
        "quality": "small",
        "speed": "fast",
        "max_height": 480,
        "container": "mp4",
        "start": 0,
        "end": 1.0
    }

    # Submit job 1
    res = client.post("/api/jobs", json={"file_id": file_id1, "name": "clip1.mp4", "options": options, "batch_id": batch_id}, headers=headers)
    assert res.status_code == 200
    job1_id = res.json()["id"]

    # Submit job 2
    res = client.post("/api/jobs", json={"file_id": file_id2, "name": "clip1.mp4", "options": options, "batch_id": batch_id}, headers=headers)
    assert res.status_code == 200
    job2_id = res.json()["id"]

    # Poll both jobs until done
    for _ in range(100):
        res = client.get("/api/jobs", headers=headers)
        jobs = res.json()
        j1 = next((j for j in jobs if j["id"] == job1_id), None)
        j2 = next((j for j in jobs if j["id"] == job2_id), None)
        if j1 and j2 and j1["status"] in ("done", "failed") and j2["status"] in ("done", "failed"):
            break
        time.sleep(0.1)

    assert j1["status"] == "done", f"Job 1 failed: {j1.get('error')}"
    assert j2["status"] == "done", f"Job 2 failed: {j2.get('error')}"

    # Download batch zip
    res = client.get(f"/api/batches/{batch_id}/download?t={config.TOKEN}", headers=headers)
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/zip"

    # Verify zip archive entries and deduplicated names
    zf = zipfile.ZipFile(io.BytesIO(res.content))
    names = zf.namelist()
    assert len(names) == 2
    assert "clip1-comp.mp4" in names
    assert "clip1-comp (2).mp4" in names


def test_combine_video_and_audio_lifecycle(client, sample_video, sample_audio):
    headers = {
        "Host": f"127.0.0.1:{config.PORT}",
        "X-Token": config.TOKEN,
        "Origin": f"http://127.0.0.1:{config.PORT}"
    }

    # 1. Upload video
    with open(sample_video, "rb") as f:
        res_v = client.post(f"/api/upload?name={sample_video.name}", content=f.read(), headers=headers)
    assert res_v.status_code == 200
    video_file_id = res_v.json()["file_id"]
    assert res_v.json()["media_type"] == "video"

    # 2. Upload audio (m4a)
    with open(sample_audio, "rb") as f:
        res_a = client.post(f"/api/upload?name={sample_audio.name}", content=f.read(), headers=headers)
    assert res_a.status_code == 200
    audio_file_id = res_a.json()["file_id"]
    assert res_a.json()["media_type"] == "audio"

    # 3. Create combine job
    job_req = {
        "file_id": video_file_id,
        "name": "combined_test.mp4",
        "audio_file_id": audio_file_id,
        "audio_name": "test_audio.m4a",
        "options": {
            "mode": "combine",
            "codec": "h264",
            "quality": "balanced",
            "speed": "fast",
            "container": "mp4",
            "start": 0
        }
    }
    res = client.post("/api/jobs", json=job_req, headers=headers)
    assert res.status_code == 200, f"Combine job creation failed: {res.text}"
    job_id = res.json()["id"]

    # 4. Poll until completed
    for _ in range(50):
        res = client.get("/api/jobs", headers=headers)
        assert res.status_code == 200
        jobs = res.json()
        target = next((j for j in jobs if j["id"] == job_id), None)
        assert target is not None
        if target["status"] in ("done", "failed"):
            break
        time.sleep(0.1)

    assert target["status"] == "done", f"Job failed: {target.get('error')}"
    assert target["out_size"] > 0

    # 5. Download output and verify filename and content
    dl = client.get(f"/api/jobs/{job_id}/download", headers=headers)
    assert dl.status_code == 200
    assert len(dl.content) == target["out_size"]
    assert "combined_test-combined.mp4" in dl.headers.get("content-disposition", "")

    # 6. Clean up
    client.delete(f"/api/jobs/{job_id}", headers=headers)
