# Why it is built this way

Each decision, the principle behind it, and the cost we accepted.

## Architecture

**FFmpeg as the engine, not a custom codec.** Video encoding is a decade-scale problem that FFmpeg already solves for every format. Our value is a safe, simple wrapper. *Principle: don't reinvent; integrate.* Cost: an install step.

**One module owns FFmpeg (`media.py`).** If FFmpeg flags change, or you add GPU encoders, there is exactly one file to edit. *Principles: single responsibility, encapsulate what changes.*

**Layers with one-way dependencies.** `main.py` never builds a command; `media.py` never knows HTTP. Pure functions (`security.py`, `build_command`) are testable with no server. *Principles: separation of concerns, dependency inversion.* This is also why hosting later is a small step: the web layer can change without touching the engine.

**Python + FastAPI + vanilla JS.** Fewest moving parts that still gives a typed API and a real UI. No build step, no node_modules, so there is nothing to break or audit. *Principles: KISS, YAGNI.* Cost: the UI is hand-written, which is fine at this size.

**SQLite, not Postgres.** One user, one machine, zero setup, survives restarts. The `db.py` interface is small, so swapping later is cheap.

**Single-worker queue.** Encoders already saturate all cores. Two parallel jobs finish later than two sequential ones and use more RAM. Parallelism is a hosting-era feature.

**Polling, not WebSockets.** One request per second to localhost costs nothing and has no connection state to debug. *Principle: simplest thing that works.*

## Security

**Local-only first.** Binding to `127.0.0.1` removes most attack surface in one line. Every other control is defense in depth, because a local server can still be hit by a malicious website in your browser (CSRF, DNS rebinding), which is why the token, Host check and Origin check exist.

**Allowlists, never blocklists.** Extensions, option values, ID format and SQL columns are all "only these". A blocklist has to anticipate every attack; an allowlist only has to know what is valid.

**Never trust the extension; ask ffprobe.** Renaming `x.exe` to `x.mp4` must not matter. The probe is the real validation.

**Server-chosen filenames.** User text is only ever displayed, never used in a path. That makes path traversal structurally impossible rather than "checked for".

**argv list, no shell.** With no shell there is no quoting to get wrong, so command injection cannot happen from option values.

**`-protocol_whitelist file`.** Media containers and playlists can reference URLs. This stops FFmpeg from being used to fetch network resources or read unexpected sources.

**Strict CSP + `textContent`.** Even if a hostile filename got through, nothing would execute. Two independent layers for the same threat.

**Generic errors out, detail in logs.** The browser gets "Unexpected error"; the log gets the stack trace. Attackers learn nothing, you lose no debugging ability.

**Honest limit:** a crafted file can still target FFmpeg bugs. For your own files this is low risk; hosting must add sandboxing (see DESIGN §7).

## Debuggability

**Every job writes the exact ffmpeg command and its stderr to `logs/<id>.log`.** Most bugs in this kind of tool are "which flags did we send?" The answer is one `cat` away and the command can be copy-pasted into a terminal.

**stderr goes to a file, not a pipe.** A full pipe can freeze FFmpeg, which looks like a random hang. This is a classic bug removed by design.

**Pure, small functions with tests.** `build_command` takes a dict and returns a list. No mocks, no setup.

**Small honest state machine.** Four statuses, a DB `CHECK`, and failure on restart, so there are no zombie "running" jobs to puzzle over.

**Typed options (`Literal` enums).** Bad input is rejected at the door with a clear message, instead of failing deep inside FFmpeg.

## Product choices

**"Trim only" uses stream copy.** For cutting you don't need to re-encode: it takes seconds and loses no quality. Trade-off: cuts snap to keyframes, so the UI labels it "instant" and the doc states the limit. Choose Compress when exact cut points matter.

**CRF, not target bitrate.** CRF gives consistent visual quality and usually the smallest file for it. Target-size mode is listed for later.

**H.264 default, H.265 optional.** H.264 plays everywhere; H.265 is smaller but not universal, so it is opt-in.

**Delete input after processing.** Uploading copies the file; keeping copies would silently fill your disk.

## Why hosting features are deferred

Auto-scaling, rapid server adaptation and multi-user auth all need decisions (cloud, queue, billing) that you can't make well until the local tool proves useful. The seams are already in place: `media.py` (engine), `worker.py` (execution), `db.py` (state). Replacing each is a contained change, which is the practical meaning of "build for now, don't block later".
