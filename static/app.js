"use strict";
const TOKEN = document.querySelector('meta[name="token"]').content;
history.replaceState(null, "", "/");               // keep the token out of the address bar/history
const $ = (id) => document.getElementById(id);
let current = null;                                  // {file_id, name, duration}

const fmtSize = (b) => b >= 1e9 ? (b / 1e9).toFixed(2) + " GB" : (b / 1e6).toFixed(1) + " MB";
const fmtTime = (s) => { s = Math.round(s); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = s % 60;
  return (h ? h + ":" + String(m).padStart(2, "0") : m) + ":" + String(x).padStart(2, "0"); };
function parseTime(v) {                              // "90" | "1:30" | "1:02:03" -> seconds, or null
  v = v.trim(); if (!v) return null;
  const p = v.split(":").map(Number); if (p.some((n) => !Number.isFinite(n) || n < 0) || p.length > 3) return NaN;
  return p.reduce((a, n) => a * 60 + n, 0);
}
const showError = (t) => { $("msg").textContent = t || ""; };

async function api(path, opts = {}) {
  const r = await fetch(path, { ...opts, headers: { "X-Token": TOKEN, "Content-Type": "application/json", ...(opts.headers || {}) } });
  if (!r.ok) { let m = "Request failed"; try { m = (await r.json()).detail || m; } catch {} throw new Error(m); }
  return r.json();
}

function upload(file) {
  showError(""); $("go").disabled = true; current = null;
  const bar = $("up"); bar.hidden = false; bar.value = 0;
  const xhr = new XMLHttpRequest();
  xhr.open("POST", "/api/upload?name=" + encodeURIComponent(file.name));
  xhr.setRequestHeader("X-Token", TOKEN);
  xhr.upload.onprogress = (e) => { if (e.lengthComputable) bar.value = e.loaded / e.total; };
  xhr.onload = () => {
    bar.hidden = true;
    let body = {}; try { body = JSON.parse(xhr.responseText); } catch {}
    if (xhr.status !== 200) return showError(body.detail || "Upload failed");
    current = { file_id: body.file_id, name: file.name, duration: body.duration };
    $("dropText").textContent = file.name;
    $("meta").textContent = `${fmtTime(body.duration)} · ${body.width}×${body.height} · ${body.codec} · ${fmtSize(body.size)}`;
    $("go").disabled = false;
  };
  xhr.onerror = () => { bar.hidden = true; showError("Upload failed. Is Shrinkwrap still running?"); };
  xhr.send(file);
}

$("file").addEventListener("change", (e) => e.target.files[0] && upload(e.target.files[0]));
const drop = $("drop");
drop.addEventListener("keydown", (e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), $("file").click()));
["dragover", "dragenter"].forEach((n) => drop.addEventListener(n, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((n) => drop.addEventListener(n, () => drop.classList.remove("over")));
drop.addEventListener("drop", (e) => { e.preventDefault(); e.dataTransfer.files[0] && upload(e.dataTransfer.files[0]); });

document.querySelectorAll('input[name="mode"]').forEach((r) =>
  r.addEventListener("change", () => { $("encOpts").hidden = r.value === "trim" && r.checked; }));

$("go").addEventListener("click", async () => {
  showError("");
  const start = parseTime($("start").value), end = parseTime($("end").value);
  if (Number.isNaN(start) || Number.isNaN(end)) return showError("Enter times like 90, 1:30 or 1:02:03.");
  if (end !== null && (end <= (start || 0))) return showError("Trim end must be after trim start.");
  const mode = document.querySelector('input[name="mode"]:checked').value;
  const options = { mode, codec: $("codec").value, quality: $("quality").value, speed: $("speed").value,
    max_height: $("height").value ? Number($("height").value) : null, container: $("container").value,
    start: start || 0, end };
  try {
    await api("/api/jobs", { method: "POST", body: JSON.stringify({ file_id: current.file_id, name: current.name, options }) });
    current = null; $("go").disabled = true; $("dropText").textContent = "Drop a video here, or choose a file"; $("meta").textContent = "";
    refresh();
  } catch (e) { showError(e.message); }
});

function render(jobs) {
  const list = $("list"); list.replaceChildren(); $("empty").hidden = jobs.length > 0;
  for (const j of jobs) {                            // textContent only: file names are never parsed as HTML
    const li = document.createElement("li");
    const row = document.createElement("div"); row.className = "row";
    const name = document.createElement("span"); name.className = "name"; name.textContent = j.display_name;
    const st = document.createElement("span"); st.className = "state " + j.status;
    st.textContent = { queued: "Waiting", running: Math.round(j.progress * 100) + "%", done: "Done", failed: j.error || "Failed" }[j.status];
    row.append(name, st); li.append(row);

    const bar = document.createElement("div"); bar.className = "bar" + (j.status === "done" ? " saved" : "");
    const fill = document.createElement("i");
    fill.style.width = (j.status === "done" ? (j.out_size / j.in_size) * 100 : j.progress * 100) + "%";
    bar.append(fill); li.append(bar);

    const foot = document.createElement("div"); foot.className = "row";
    const sizes = document.createElement("span"); sizes.className = "sizes";
    if (j.status === "done") {
      const pct = Math.round((1 - j.out_size / j.in_size) * 100);
      sizes.textContent = `${fmtSize(j.in_size)} → ${fmtSize(j.out_size)} (${pct >= 0 ? pct + "% smaller" : -pct + "% larger"})`;
    } else sizes.textContent = fmtSize(j.in_size);
    foot.append(sizes);
    const actions = document.createElement("span");
    if (j.status === "done") {
      const a = document.createElement("a"); a.textContent = "Download"; a.href = `/api/jobs/${j.id}/download?t=${encodeURIComponent(TOKEN)}`; actions.append(a);
    }
    if (j.status !== "running" && j.status !== "queued") {
      const b = document.createElement("button"); b.className = "link"; b.textContent = "Remove";
      b.onclick = async () => { await api(`/api/jobs/${j.id}`, { method: "DELETE" }); refresh(); }; actions.append(b);
    }
    foot.append(actions); li.append(foot); list.append(li);
  }
}

let timer;
async function refresh() {
  clearTimeout(timer);
  try {
    const jobs = await api("/api/jobs"); render(jobs);
    if (jobs.some((j) => j.status === "queued" || j.status === "running")) timer = setTimeout(refresh, 1000);
  } catch (e) { showError(e.message); }
}
refresh();
