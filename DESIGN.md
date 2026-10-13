# Shrinkwrap: Design

Local video compressor and trimmer. MVP scope: runs on your machine, nothing leaves it.

## 1. Goals and non-goals

| In the MVP | Out of the MVP (later) |
|---|---|
| Compress video (H.264 / H.265) | Hosting on a server |
| Trim (lossless instant cut, or cut + re-encode) | Multi-user accounts |
| Accept most common formats (mp4, mkv, mov, avi, webm, m4v, flv, wmv, mpg, ts, 3gp) | Parallel workers, autoscaling, queues |
| Local-only, hardened frontend, backend and DB | Hardware encoders (NVENC, VideoToolbox, QSV) |
| Easy to debug and extend | Batch / watch-folder mode |

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

1. `POST /api/upload?name=clip.mov`: raw body is streamed to `uploads/<uuid>.<ext>` in chunks (size capped), then `ffprobe` confirms it is a real video. Returns `file_id`, duration, resolution.
2. `POST /api/jobs`: validates options (enums and numeric ranges), checks trim window, inserts a `queued` row, hands the id to the worker.
3. Worker: `queued` → `running` (progress parsed from ffmpeg `-progress`) → `done` or `failed`. The uploaded copy is deleted afterwards.
4. UI polls `GET /api/jobs` once a second while anything is active, then offers `GET /api/jobs/{id}/download`.

Job state machine: `queued → running → done | failed`. On restart, any leftover `queued/running` rows become `failed` ("Interrupted by restart").

## 4. API

| Method | Path | Purpose |
|---|---|---|
| GET | `/?t=<token>` | Serves the UI (token injected into a meta tag) |
| POST | `/api/upload?name=` | Stream a video in |
| POST | `/api/jobs` | Create job `{file_id, name, options}` |
| GET | `/api/jobs` | List jobs (paths stripped) |
| GET | `/api/jobs/{id}/download` | Download result |
| DELETE | `/api/jobs/{id}` | Delete job and output |

Options: `mode` compress/trim, `codec` h264/h265, `quality` small/balanced/high, `speed` fast/balanced/thorough, `max_height` 2160/1440/1080/720/480/null, `container` mp4/mkv, `start`, `end` (seconds).

## 5. Data model

One table, `jobs`: `id, display_name, input_path, output_path, options(JSON), status, progress, error, in_size, out_size, duration, created_at`. `status` has a `CHECK` constraint. `display_name` is for the UI only; real files are always `<uuid>.<ext>`.

## 6. FFmpeg behaviour

| Mode | What runs | Speed | Notes |
|---|---|---|---|
| Trim only | `-c copy` | Near instant | Cuts land on keyframes, so can be off by a second or two |
| Compress | `libx264`/`libx265`, CRF by quality, `aac 128k`, optional scale | Depends on speed preset | `+faststart` for MP4, `hvc1` tag for H.265 MP4 |

CRF: H.264 28 / 23 / 19, H.265 32 / 28 / 24 (small / balanced / high). Presets: veryfast / medium / slow. Only the first video stream and first audio stream are kept; subtitles and data streams are dropped.

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
| Backend | Disk exhaustion | Max upload size, streaming (no RAM blowup), cleanup of inputs | `main.upload`, `worker` |
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
