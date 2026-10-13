# Shrinkwrap: Design

Local video compressor and trimmer. MVP scope: runs on your machine, nothing leaves it.

## 1. Goals and non-goals

| In the MVP | Out of the MVP (later) |
|---|---|
| Compress video (H.264 / H.265) | Hosting on a server |
| Trim (lossless instant cut, or cut + re-encode) | Multi-user accounts |
| Combine video with audio files (instant mux or compress + audio) | Parallel workers, autoscaling, queues |
| Accept video (mp4, mkv, mov, avi, webm, m4v, flv, wmv, mpg, ts, 3gp) & audio (m4a, mp3, aac, wav, flac, ogg, opus, wma, mka, aiff, alac) | Hardware encoders (NVENC, VideoToolbox, QSV) |
| Smart audio mapping for single videos & batches (auto-matching by filename, manual assignment, apply one to all) | Watch-folder mode |
| Local-only, hardened frontend, backend and DB | Cloud object storage |
| Easy to debug and extend | Distributed queue |

## 2. Architecture

```
 Browser (static HTML/CSS/JS, no framework, no inline script)
    |  HTTP on 127.0.0.1 only, X-Token header
    v
 app/main.py      HTTP layer: auth, validation, responses        (no ffmpeg, no SQL)
    |-- security.py   pure validators (ids, extensions, paths)
    |-- db.py         SQLite, parameterized queries only
    '-- worker.py     single-thread job runner
          '-- media.py    the ONLY place that knows FFmpeg (probe, build argv, run)
                |
              ffmpeg / ffprobe  (subprocess, argv list, no shell)

 ~/.shrinkwrap/  uploads/  outputs/  logs/  jobs.db
```

Dependency rule: arrows only point down. `media.py` and `security.py` import nothing from the web layer, so they can be tested and reused without a server (this is also the seam where a CLI or a remote worker plugs in later).

## 3. Request flow

1. `POST /api/upload?name=clip.mov`: raw body is streamed to `uploads/<uuid>.<ext>` in chunks (size capped), then `ffprobe` inspects streams and detects media type (`video` or `audio`). Returns `file_id`, duration, resolution, codec.
2. `POST /api/jobs`: validates options (enums and numeric ranges), checks trim window, verifies primary file is video and optional `audio_file_id` has audio stream, validates `batch_id` (if provided, client-generated via `crypto.randomUUID()`) and enforces `MAX_BATCH_FILES` & `MAX_BATCH_BYTES`, inserts a `queued` row, hands the id to the worker.
3. Worker: `queued` → `running` (progress parsed from ffmpeg `-progress`) → `done` or `failed`. Uploaded copies are unlinked once all referencing jobs complete.
4. UI polls `GET /api/jobs` once a second while anything is active. For single jobs, offers `GET /api/jobs/{id}/download`. For batches of 2+ completed jobs sharing a `batch_id`, offers `GET /api/batches/{batch_id}/download` (streamed ZIP file).

Job state machine: `queued → running → done | failed`. On restart, any leftover `queued/running` rows become `failed` ("Interrupted by restart"). On startup, uploads older than 24 hours are automatically swept.

## 4. API

| Method | Path | Purpose |
|---|---|---|
| GET | `/?t=<token>` | Serves the UI (token injected into a meta tag) |
| POST | `/api/upload?name=` | Stream a video or audio file in |
| POST | `/api/jobs` | Create job `{file_id, name, options, batch_id?, audio_file_id?, audio_name?}` |
| GET | `/api/jobs` | List jobs (paths stripped, includes `batch_id` and audio details) |
| GET | `/api/jobs/{id}/download` | Download single result |
| GET | `/api/batches/{batch_id}/download` | Stream ZIP of completed batch outputs |
| DELETE | `/api/jobs/{id}` | Delete job and output |

Options: `mode` compress/trim/combine, `codec` h264/h265, `quality` small/balanced/high, `speed` fast/balanced/thorough, `max_height` 2160/1440/1080/720/480/null, `container` mp4/mkv, `start`, `end` (seconds), `audio_name` (string).

## 5. Data model

One table, `jobs`: `id, display_name, input_path, output_path, options(JSON), status, progress, error, in_size, out_size, duration, created_at, batch_id, audio_path`. `status` has a `CHECK` constraint. `display_name` is for the UI only; output files in `outputs/` are named `<safe_stem>-<tag>-<short_id>.<ext>` to reflect the video's actual name while preventing collisions. `batch_id` groups multiple jobs created together. `audio_path` stores optional replacement audio file.

## 6. FFmpeg behaviour

| Mode | What runs | Speed | Notes |
|---|---|---|---|
| Fast Merge (combine) | `-c:v copy`, `-c:a aac -b:a 128k` | Instant | Maps video from source, audio from audio file; output bounded to video duration |
| Trim only | `-c copy` (or `-c:v copy -c:a aac -b:a 128k` if audio attached) | Near instant | Cuts land on keyframes, so can be off by a second or two |
| Compress & Merge | `libx264`/`libx265`, CRF by quality, AAC (`96k`/`128k`/`160k`), optional scale | Depends on speed preset | Replaces audio if `audio_src` attached; `+faststart` for MP4, `hvc1` tag for H.265 MP4 |

CRF: H.264 30 / 23 / 19, H.265 34 / 28 / 24 (small / balanced / high). Presets: veryfast / medium / slow. Audio bitrate: 96k (small), 128k (balanced), 160k (high). When combining audio, stream `0:v:0` is mapped with `1:a:0`, dropping original video audio and extraneous subtitle/data tracks. Output length is strictly bound with `-t` to video duration. Downloads are named `<video_stem>-combined.<ext>` (or `-compressed.<ext>`).

## 7. Security model (frontend, backend, DB)

Reading of the requirement: *defend against* common vulnerabilities. Here is each threat and its control.

| Layer | Threat | Control | Where |
|---|---|---|---|
| Network | Anyone on LAN reaches the app | Bind `127.0.0.1` only | `config.py` |
| Network | DNS rebinding | `Host` header must be localhost | `main.guard` |
| Backend | Other websites calling the API (CSRF) | Per-run random token + `Origin` check on writes | `main.auth/guard` |
| Backend | Path traversal | Server-generated UUID filenames; `parse_id` regex; `is_within` check | `security.py` |
| Backend | Command injection | argv list, never `shell=True`; all options are enums or numbers | `media.py`, `Options` |
| Backend | Malicious media (SSRF via playlists, file reads) | Extension allowlist + `ffprobe` check + `-protocol_whitelist file` | `media.py` |
| Backend | Disk exhaustion | Max upload size, streaming (no RAM blowup), cleanup of inputs, 24h upload sweep | `main.upload`, `worker`, `db.init` |
| Backend | Batch abuse | Server-enforced `MAX_BATCH_FILES` and `MAX_BATCH_BYTES` limits | `main.create_job` |
| Backend | Zip archive extraction / traversal | Streamed `ZIP_STORED` with `force_zip64=True`, `security.is_within` verification, case-insensitive filename deduplication | `main.download_batch` |
| Backend | Info leakage | Generic errors to client, details in `logs/`; docs/openapi disabled; absolute paths stripped from API | `main.py` |
| DB | SQL injection | Parameterized queries; dynamic columns come from an allowlist; `CHECK` constraint | `db.py` |
| Frontend | XSS | `textContent` only, no `innerHTML`; strict CSP (`script-src 'self'`, no inline) | `app.js`, `main.guard` |
| Frontend | Clickjacking / sniffing | `X-Frame-Options`, `frame-ancestors 'none'`, `nosniff` | `main.guard` |
| Frontend | Token in history | `history.replaceState` removes it from the URL | `app.js` |

Known limits: FFmpeg itself can have parsing bugs on hostile files. For personal files this is acceptable; for hosting, run it in a container with no network and a seccomp profile.

## 8. Directory layout

```
app/  config.py security.py db.py media.py worker.py main.py __main__.py
static/  index.html style.css app.js
tests/   test_security.py test_media.py
DESIGN.md  WHY.md  README.md  requirements.txt
```

## 9. Debugging guide

| Symptom | Look at |
|---|---|
| Job failed | `~/.shrinkwrap/logs/<job_id>.log` (first line is the exact ffmpeg command; copy-paste it) |
| 401 / 403 | Open the full link from the terminal; check Host/Origin |
| Upload rejected | Extension not in `ALLOWED_EXT`, or ffprobe found no video stream |
| Wrong options | `media.build_command` is a pure function: call it in a Python shell |
| Stuck job | Restart; leftovers are marked failed |

## 10. Testing

`pytest tests`. Unit tests cover validators and command building (pure functions, no ffmpeg needed). Next to add: an integration test that encodes a 1-second generated clip (`ffmpeg -f lavfi -i testsrc`).

## 11. Roadmap after the MVP

1. Hardware encoder detection (`h264_videotoolbox`, `h264_nvenc`) behind one config switch in `media.py`.
2. Target-size mode (two-pass, bitrate from duration).
3. Hosting: swap token for real auth, move storage behind a `Storage` interface, run `worker.py` as separate processes fed by a queue (Redis/SQS), containerise ffmpeg with no network.
4. Adaptive scaling: worker count and encoder preset chosen from queue depth and CPU.
5. Cancel button (store ffmpeg PID, `terminate()`).
