"use strict";
const TOKEN = document.querySelector('meta[name="token"]').content;
history.replaceState(null, "", "/");               // keep token out of address bar / browser history

const $ = (id) => document.getElementById(id);

const AUDIO_EXTS = new Set([".m4a", ".mp3", ".aac", ".wav", ".flac", ".ogg", ".opus", ".wma", ".mka", ".aiff", ".alac"]);

function isAudio(file) {
  const name = file && file.name ? file.name : "";
  const ext = name.substring(name.lastIndexOf(".")).toLowerCase();
  return AUDIO_EXTS.has(ext);
}

function getStem(filename) {
  const name = filename || "";
  const lastDot = name.lastIndexOf(".");
  return lastDot > 0 ? name.substring(0, lastDot) : name;
}

// State
let currentVideos = [];                            // Array of { id, file }
let currentAudios = [];                            // Array of { id, file }
let currentSingleUpload = null;                    // { file_id, name, duration, ... }
let singleAttachedAudio = null;                    // File object for single video flow
let singleAudioUpload = null;                      // { file_id, name, duration, codec, size }
let batchAudioAssignments = {};                    // { videoId: audioId }

const fmtSize = (b) => {
  if (!b || b <= 0) return "0 B";
  return b >= 1e9 ? (b / 1e9).toFixed(2) + " GB" : (b / 1e6).toFixed(1) + " MB";
};

const fmtTime = (s) => {
  s = Math.round(s || 0);
  const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = s % 60;
  return (h ? h + ":" + String(m).padStart(2, "0") : m) + ":" + String(x).padStart(2, "0");
};

function parseTime(v) {                              // "90" | "1:30" | "1:02:03" -> seconds, or null
  v = (v || "").trim();
  if (!v) return null;
  const p = v.split(":").map(Number);
  if (p.some((n) => !Number.isFinite(n) || n < 0) || p.length > 3) return NaN;
  return p.reduce((a, n) => a * 60 + n, 0);
}

const showError = (t) => { $("msg").textContent = t || ""; };

async function api(path, opts = {}) {
  const r = await fetch(path, {
    ...opts,
    headers: {
      "X-Token": TOKEN,
      "Content-Type": "application/json",
      ...(opts.headers || {})
    }
  });
  if (!r.ok) {
    let m = "Request failed";
    try { m = (await r.json()).detail || m; } catch {}
    throw new Error(m);
  }
  return r.json();
}

function uploadFilePromise(file, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/upload?name=" + encodeURIComponent(file.name));
    xhr.setRequestHeader("X-Token", TOKEN);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total);
    };
    xhr.onload = () => {
      let body = {};
      try { body = JSON.parse(xhr.responseText); } catch {}
      if (xhr.status !== 200) {
        reject(new Error(body.detail || `Upload failed (${xhr.status})`));
      } else {
        resolve(body);
      }
    };
    xhr.onerror = () => reject(new Error("Network error during upload"));
    xhr.send(file);
  });
}

function autoMatchBatchAudios() {
  currentVideos.forEach((v) => {
    const vStem = getStem(v.file.name).toLowerCase().trim();
    const matchedAudio = currentAudios.find((a) => getStem(a.file.name).toLowerCase().trim() === vStem);
    if (matchedAudio && !batchAudioAssignments[v.id]) {
      batchAudioAssignments[v.id] = matchedAudio.id;
    }
  });
}

function updateGlobalAudioDropdown() {
  const select = $("batchGlobalAudioSelect");
  select.replaceChildren();

  const defOpt = document.createElement("option");
  defOpt.value = "";
  defOpt.textContent = "Apply audio to all videos...";
  select.append(defOpt);

  const noneOpt = document.createElement("option");
  noneOpt.value = "__NONE__";
  noneOpt.textContent = "Clear all (keep original audio)";
  select.append(noneOpt);

  currentAudios.forEach((a) => {
    const opt = document.createElement("option");
    opt.value = a.id;
    opt.textContent = `🎵 ${a.file.name}`;
    select.append(opt);
  });
}

function updateModeVisibility() {
  const mode = document.querySelector('input[name="mode"]:checked')?.value || "compress";
  $("encOpts").hidden = (mode === "trim" || mode === "combine");
  const descEl = $("modeDesc");
  if (descEl) {
    if (mode === "compress") {
      descEl.textContent = "Compresses video to reduce file size (CRF). Merges attached audio without bloating file size.";
    } else if (mode === "combine") {
      descEl.textContent = "Keeps original video quality without re-encoding (instant). Replaces audio track.";
    } else {
      descEl.textContent = "Cuts video instantly without re-encoding.";
    }
  }
}

function updateUIForFiles() {
  showError("");
  const videoCount = currentVideos.length;
  const fileListEl = $("fileList");
  const trimNoteEl = $("trimNote");
  const singleAudioSection = $("singleAudioSection");
  const batchToolbar = $("batchToolbar");
  const trimRadio = document.querySelector('input[name="mode"][value="trim"]');
  const combineRadio = document.querySelector('input[name="mode"][value="combine"]');
  const compressRadio = document.querySelector('input[name="mode"][value="compress"]');
  const startInput = $("start");
  const endInput = $("end");
  const goBtn = $("go");
  const goText = $("goText");

  fileListEl.replaceChildren();

  if (videoCount === 0) {
    currentSingleUpload = null;
    singleAttachedAudio = null;
    singleAudioUpload = null;
    batchAudioAssignments = {};
    $("dropText").textContent = "Drop videos & audio files here, or click to choose";
    $("meta").textContent = "";
    fileListEl.hidden = true;
    trimNoteEl.hidden = true;
    singleAudioSection.hidden = true;
    batchToolbar.hidden = true;
    trimRadio.disabled = false;
    combineRadio.disabled = false;
    startInput.disabled = false;
    endInput.disabled = false;
    goBtn.disabled = true;
    goText.textContent = "Start Job";
    updateModeVisibility();
    return;
  }

  if (videoCount === 1) {
    // Single Video Flow
    fileListEl.hidden = true;
    trimNoteEl.hidden = true;
    batchToolbar.hidden = true;
    singleAudioSection.hidden = false;
    trimRadio.disabled = false;
    combineRadio.disabled = false;
    startInput.disabled = false;
    endInput.disabled = false;
    goText.textContent = "Start Job";

    updateSingleAudioCard();
    uploadSingleVideo(currentVideos[0].file);
  } else {
    // Multi-file Batch Flow
    currentSingleUpload = null;
    singleAttachedAudio = null;
    singleAudioUpload = null;
    $("dropText").textContent = `${videoCount} videos selected`;
    $("meta").textContent = "";
    fileListEl.hidden = false;
    trimNoteEl.hidden = false;
    singleAudioSection.hidden = true;
    batchToolbar.hidden = false;

    // In batch mode, trimming is disabled
    trimRadio.disabled = true;
    if (document.querySelector('input[name="mode"]:checked')?.value === "trim") {
      compressRadio.checked = true;
    }
    startInput.value = "";
    endInput.value = "";
    startInput.disabled = true;
    endInput.disabled = true;

    goText.textContent = "Start All Jobs";
    goBtn.disabled = false;

    updateGlobalAudioDropdown();

    currentVideos.forEach((v, idx) => {
      const li = document.createElement("li");
      li.className = "file-item";

      const main = document.createElement("div");
      main.className = "file-item-main";

      const header = document.createElement("div");
      header.className = "file-item-header";

      const fname = document.createElement("span");
      fname.className = "file-name";
      fname.textContent = v.file.name;

      const fmeta = document.createElement("span");
      fmeta.className = "file-meta";
      fmeta.textContent = fmtSize(v.file.size);

      header.append(fname, fmeta);

      const audioRow = document.createElement("div");
      audioRow.className = "file-item-audio-row";

      const audioSelect = document.createElement("select");
      audioSelect.className = "batch-audio-select";
      audioSelect.title = "Select audio to pair with this video";

      const noAudioOpt = document.createElement("option");
      noAudioOpt.value = "";
      noAudioOpt.textContent = "No extra audio (keep original)";
      audioSelect.append(noAudioOpt);

      const assignedAudioId = batchAudioAssignments[v.id] || "";
      const vStem = getStem(v.file.name).toLowerCase().trim();

      currentAudios.forEach((a) => {
        const opt = document.createElement("option");
        opt.value = a.id;
        const aStem = getStem(a.file.name).toLowerCase().trim();
        const isMatched = (vStem === aStem);
        opt.textContent = `🎵 ${a.file.name}${isMatched ? " (name match)" : ""}`;
        audioSelect.append(opt);
      });

      audioSelect.value = assignedAudioId;
      audioSelect.onchange = () => {
        batchAudioAssignments[v.id] = audioSelect.value;
        updateUIForFiles();
      };

      audioRow.append(audioSelect);

      const currentAssigned = currentAudios.find((a) => a.id === assignedAudioId);
      if (currentAssigned && getStem(currentAssigned.file.name).toLowerCase().trim() === vStem) {
        const matchBadge = document.createElement("span");
        matchBadge.className = "badge-matched";
        matchBadge.textContent = "Matched";
        audioRow.append(matchBadge);
      }

      main.append(header, audioRow);

      const rmBtn = document.createElement("button");
      rmBtn.className = "link";
      rmBtn.textContent = "Remove";
      rmBtn.type = "button";
      rmBtn.onclick = () => {
        delete batchAudioAssignments[v.id];
        currentVideos.splice(idx, 1);
        updateUIForFiles();
      };

      li.append(main, rmBtn);
      fileListEl.append(li);
    });
  }
  updateModeVisibility();
}

function updateSingleAudioCard() {
  const emptyBox = $("singleAudioEmpty");
  const attachedBox = $("singleAudioAttached");

  if (!singleAttachedAudio) {
    emptyBox.hidden = false;
    attachedBox.hidden = true;
    return;
  }

  emptyBox.hidden = true;
  attachedBox.hidden = false;
  $("singleAudioName").textContent = singleAttachedAudio.name;
  if (singleAudioUpload) {
    $("singleAudioMeta").textContent = `${fmtTime(singleAudioUpload.duration)} · ${fmtSize(singleAttachedAudio.size)} · ${singleAudioUpload.codec || 'audio'}`;
  } else {
    $("singleAudioMeta").textContent = `Uploading audio... (${fmtSize(singleAttachedAudio.size)})`;
  }
}

function uploadSingleAudio(file) {
  singleAudioUpload = null;
  updateSingleAudioCard();
  uploadFilePromise(file)
    .then((res) => {
      singleAudioUpload = {
        file_id: res.file_id,
        name: file.name,
        duration: res.duration,
        codec: res.codec,
        size: res.size
      };
      updateSingleAudioCard();
    })
    .catch((err) => {
      showError(`Audio upload failed: ${err.message}`);
      singleAttachedAudio = null;
      singleAudioUpload = null;
      updateSingleAudioCard();
    });
}

function uploadSingleVideo(file) {
  showError("");
  $("go").disabled = true;
  currentSingleUpload = null;
  const bar = $("up");
  bar.hidden = false;
  bar.value = 0;

  const xhr = new XMLHttpRequest();
  xhr.open("POST", "/api/upload?name=" + encodeURIComponent(file.name));
  xhr.setRequestHeader("X-Token", TOKEN);
  xhr.upload.onprogress = (e) => {
    if (e.lengthComputable) bar.value = e.loaded / e.total;
  };
  xhr.onload = () => {
    bar.hidden = true;
    let body = {};
    try { body = JSON.parse(xhr.responseText); } catch {}
    if (xhr.status !== 200) return showError(body.detail || "Upload failed");

    currentSingleUpload = { file_id: body.file_id, name: file.name, duration: body.duration };
    $("dropText").textContent = file.name;
    $("meta").textContent = `${fmtTime(body.duration)} · ${body.width || '?'}×${body.height || '?'} · ${body.codec || 'video'} · ${fmtSize(body.size)}`;
    $("go").disabled = false;
  };
  xhr.onerror = () => {
    bar.hidden = true;
    showError("Upload failed. Is Shrinkwrap server running?");
  };
  xhr.send(file);
}

function handleFileSelect(files) {
  if (!files || files.length === 0) return;
  const fileArray = Array.from(files);

  const newVideos = [];
  const newAudios = [];

  fileArray.forEach((f) => {
    if (isAudio(f)) {
      newAudios.push({ id: crypto.randomUUID().replaceAll("-", ""), file: f });
    } else {
      newVideos.push({ id: crypto.randomUUID().replaceAll("-", ""), file: f });
    }
  });

  // If currently 1 video and user drops an audio file
  if (currentVideos.length === 1 && newVideos.length === 0 && newAudios.length > 0) {
    singleAttachedAudio = newAudios[0].file;
    uploadSingleAudio(singleAttachedAudio);
    return;
  }

  // If user drops files
  if (newVideos.length > 0) {
    currentVideos = newVideos;
  }

  if (newAudios.length > 0) {
    currentAudios = [...currentAudios, ...newAudios];
  }

  // If 1 video and 1 audio selected together
  if (currentVideos.length === 1 && currentAudios.length > 0) {
    singleAttachedAudio = currentAudios[0].file;
    uploadSingleAudio(singleAttachedAudio);
  } else if (currentVideos.length >= 2) {
    autoMatchBatchAudios();
  } else if (currentVideos.length === 0 && currentAudios.length > 0) {
    showError("Please select at least one video file. Audio files are combined into videos.");
    return;
  }

  updateUIForFiles();
}

// Single audio attach handlers
$("singleAudioFile").addEventListener("change", (e) => {
  const f = e.target.files && e.target.files[0];
  if (!f) return;
  singleAttachedAudio = f;
  uploadSingleAudio(f);
  updateModeVisibility();
});

$("singleAudioRemove").addEventListener("click", () => {
  singleAttachedAudio = null;
  singleAudioUpload = null;
  updateSingleAudioCard();
  updateModeVisibility();
});

// Batch toolbar handlers
$("batchAudioInput").addEventListener("change", (e) => {
  if (!e.target.files || e.target.files.length === 0) return;
  Array.from(e.target.files).forEach((f) => {
    currentAudios.push({ id: crypto.randomUUID().replaceAll("-", ""), file: f });
  });
  autoMatchBatchAudios();
  updateUIForFiles();
});

$("batchGlobalAudioSelect").addEventListener("change", (e) => {
  const val = e.target.value;
  if (!val) return;
  currentVideos.forEach((v) => {
    batchAudioAssignments[v.id] = (val === "__NONE__" ? "" : val);
  });
  updateUIForFiles();
});

$("batchAutoMatchBtn").addEventListener("click", () => {
  autoMatchBatchAudios();
  updateUIForFiles();
});

// File picker & dropzone
$("file").addEventListener("change", (e) => handleFileSelect(e.target.files));
const drop = $("drop");
drop.addEventListener("keydown", (e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), $("file").click()));
["dragover", "dragenter"].forEach((n) => drop.addEventListener(n, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((n) => drop.addEventListener(n, () => drop.classList.remove("over")));
drop.addEventListener("drop", (e) => {
  e.preventDefault();
  handleFileSelect(e.dataTransfer.files);
});

// Mode switch handler
document.querySelectorAll('input[name="mode"]').forEach((r) =>
  r.addEventListener("change", updateModeVisibility)
);

// Start Job
$("go").addEventListener("click", async () => {
  if (currentVideos.length === 0) return;
  showError("");

  const mode = document.querySelector('input[name="mode"]:checked').value;
  const start = parseTime($("start").value), end = parseTime($("end").value);

  if (mode === "trim" || currentVideos.length === 1) {
    if (Number.isNaN(start) || Number.isNaN(end)) return showError("Enter valid times like 90, 1:30 or 1:02:03.");
    if (end !== null && (end <= (start || 0))) return showError("Trim end must be after trim start.");
  }

  const options = {
    mode,
    codec: $("codec").value,
    quality: $("quality").value,
    speed: $("speed").value,
    max_height: $("height").value ? Number($("height").value) : null,
    container: $("container").value,
    start: start || 0,
    end: mode === "trim" ? end : null
  };

  $("go").disabled = true;

  // Single video flow
  if (currentVideos.length === 1) {
    if (!currentSingleUpload) return;
    if (mode === "combine" && !singleAttachedAudio) {
      showError("Please attach an audio file to combine with this video.");
      $("go").disabled = false;
      return;
    }

    try {
      let audio_file_id = null;
      let audio_name = null;

      if (singleAttachedAudio) {
        if (!singleAudioUpload) {
          const up = await uploadFilePromise(singleAttachedAudio);
          singleAudioUpload = { file_id: up.file_id, name: singleAttachedAudio.name };
        }
        audio_file_id = singleAudioUpload.file_id;
        audio_name = singleAudioUpload.name;
      }

      await api("/api/jobs", {
        method: "POST",
        body: JSON.stringify({
          file_id: currentSingleUpload.file_id,
          name: currentSingleUpload.name,
          options,
          audio_file_id,
          audio_name
        })
      });

      currentVideos = [];
      currentAudios = [];
      singleAttachedAudio = null;
      singleAudioUpload = null;
      updateUIForFiles();
      refresh();
    } catch (e) {
      showError(e.message);
      $("go").disabled = false;
    }
    return;
  }

  // Multi-file batch flow
  if (mode === "combine") {
    const hasAnyAudio = currentVideos.some((v) => !!batchAudioAssignments[v.id]);
    if (!hasAnyAudio) {
      showError("Please assign an audio file to at least one video for Combine mode.");
      $("go").disabled = false;
      return;
    }
  }

  const batch_id = crypto.randomUUID().replaceAll("-", "");
  const bar = $("up");
  bar.hidden = false;
  bar.value = 0;

  const errors = [];
  const videosToUpload = [...currentVideos];

  // 1. Identify and upload needed audio files (each unique audio file uploaded once)
  const neededAudioIds = new Set(
    videosToUpload.map((v) => batchAudioAssignments[v.id]).filter(Boolean)
  );
  const audioUploadMap = new Map(); // audioId -> { file_id, name }
  const audioList = currentAudios.filter((a) => neededAudioIds.has(a.id));

  const totalSteps = audioList.length + videosToUpload.length;
  let currentStep = 0;

  for (let i = 0; i < audioList.length; i++) {
    const a = audioList[i];
    try {
      const up = await uploadFilePromise(a.file, (pct) => {
        bar.value = (currentStep + pct) / totalSteps;
      });
      audioUploadMap.set(a.id, { file_id: up.file_id, name: a.file.name });
    } catch (err) {
      errors.push(`Audio ${a.file.name}: ${err.message}`);
    }
    currentStep++;
  }

  // 2. Upload videos and submit jobs
  for (let i = 0; i < videosToUpload.length; i++) {
    const v = videosToUpload[i];
    try {
      const uploadRes = await uploadFilePromise(v.file, (pct) => {
        bar.value = (currentStep + pct) / totalSteps;
      });

      const assignedAudioId = batchAudioAssignments[v.id];
      const assignedUpload = assignedAudioId ? audioUploadMap.get(assignedAudioId) : null;

      await api("/api/jobs", {
        method: "POST",
        body: JSON.stringify({
          file_id: uploadRes.file_id,
          name: v.file.name,
          options,
          batch_id,
          audio_file_id: assignedUpload ? assignedUpload.file_id : null,
          audio_name: assignedUpload ? assignedUpload.name : null
        })
      });
    } catch (err) {
      errors.push(`${v.file.name}: ${err.message}`);
    }
    currentStep++;
  }

  bar.hidden = true;
  currentVideos = [];
  currentAudios = [];
  batchAudioAssignments = {};
  updateUIForFiles();

  if (errors.length > 0) {
    showError("Some files failed:\n" + errors.join("; "));
  }
  refresh();
});

function render(jobs) {
  const list = $("list");
  list.replaceChildren();
  $("empty").hidden = jobs.length > 0;

  // Count done jobs per batch
  const batchDoneCounts = {};
  jobs.forEach((j) => {
    if (j.batch_id && j.status === "done") {
      batchDoneCounts[j.batch_id] = (batchDoneCounts[j.batch_id] || 0) + 1;
    }
  });

  const renderedBatches = new Set();

  for (const j of jobs) {
    if (j.batch_id && !renderedBatches.has(j.batch_id)) {
      renderedBatches.add(j.batch_id);
      const doneCount = batchDoneCounts[j.batch_id] || 0;

      const batchHeader = document.createElement("li");
      batchHeader.className = "batch-group-header";

      const title = document.createElement("span");
      title.className = "batch-title";
      title.textContent = `Batch (${j.batch_id.substring(0, 8)})`;
      batchHeader.append(title);

      if (doneCount >= 2) {
        const dlAllLink = document.createElement("a");
        dlAllLink.className = "batch-download-btn";
        dlAllLink.textContent = `Download All (${doneCount} ZIP)`;
        dlAllLink.href = `/api/batches/${j.batch_id}/download?t=${encodeURIComponent(TOKEN)}`;
        batchHeader.append(dlAllLink);
      }

      list.append(batchHeader);
    }

    const li = document.createElement("li");
    const row = document.createElement("div");
    row.className = "row";

    const nameCol = document.createElement("div");
    nameCol.style.display = "flex";
    nameCol.style.flexDirection = "column";
    nameCol.style.overflow = "hidden";
    nameCol.style.flex = "1";

    const name = document.createElement("span");
    name.className = "name";
    name.textContent = j.display_name;
    nameCol.append(name);

    let optsObj = {};
    try { optsObj = JSON.parse(j.options || "{}"); } catch {}
    if (optsObj.audio_name) {
      const aTag = document.createElement("span");
      aTag.className = "audio-tag";
      aTag.textContent = `🎵 + ${optsObj.audio_name}`;
      nameCol.append(aTag);
    }

    const st = document.createElement("span");
    st.className = "state " + j.status;
    st.textContent = {
      queued: "Waiting",
      running: `${Math.round((j.progress || 0) * 100)}%`,
      done: "Done",
      failed: j.error || "Failed"
    }[j.status] || j.status;

    row.append(nameCol, st);
    li.append(row);

    const inSize = j.in_size || 1;
    const outSize = j.out_size || 0;

    const bar = document.createElement("div");
    bar.className = "bar" + (j.status === "done" ? " saved" : "");
    const fill = document.createElement("i");
    const fillWidth = j.status === "done" ? (outSize / inSize) * 100 : (j.progress || 0) * 100;
    fill.style.width = Math.min(Math.max(0, fillWidth), 100) + "%";
    bar.append(fill);
    li.append(bar);

    const foot = document.createElement("div");
    foot.className = "row";
    const sizes = document.createElement("span");
    sizes.className = "sizes";
    if (j.status === "done") {
      const pct = Math.round((1 - outSize / inSize) * 100);
      sizes.textContent = `${fmtSize(j.in_size)} → ${fmtSize(j.out_size)} (${pct >= 0 ? pct + "% smaller" : -pct + "% larger"})`;
    } else {
      sizes.textContent = fmtSize(j.in_size);
    }
    foot.append(sizes);

    const actions = document.createElement("span");
    if (j.status === "done") {
      const a = document.createElement("a");
      a.textContent = "Download";
      const stem = j.display_name.replace(/\.[^/.]+$/, "");
      const ext = j.output_path ? j.output_path.substring(j.output_path.lastIndexOf('.')) : '.mp4';
      const isCombined = Boolean(optsObj.audio_name || optsObj.mode === "combine");
      const tag = isCombined ? "combined" : (optsObj.mode === "trim" ? "trimmed" : "comp");
      a.download = `${stem}-${tag}${ext}`;
      a.href = `/api/jobs/${j.id}/download?t=${encodeURIComponent(TOKEN)}`;
      actions.append(a);
    }
    if (j.status !== "running" && j.status !== "queued") {
      const b = document.createElement("button");
      b.className = "link";
      b.textContent = "Remove";
      b.onclick = async () => {
        try {
          await api(`/api/jobs/${j.id}`, { method: "DELETE" });
          refresh();
        } catch (err) {
          showError(err.message);
        }
      };
      actions.append(b);
    }
    foot.append(actions);
    li.append(foot);
    list.append(li);
  }
}

let timer;
async function refresh() {
  clearTimeout(timer);
  try {
    const jobs = await api("/api/jobs");
    render(jobs);
    if (jobs.some((j) => j.status === "queued" || j.status === "running")) {
      timer = setTimeout(refresh, 1000);
    }
  } catch (e) {
    showError(e.message);
  }
}

refresh();
