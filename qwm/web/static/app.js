"use strict";
// NEQR quantum watermarking studio - editorial hero & 1-click self-healing UX.

const $ = (id) => document.getElementById(id);
const state = { session: null, mode: "recovery-dual", meta: null, paintValue: 255, imageSize: 256, blockRow: 0, blockCol: 0 };

const MODE_INFO = {
  "recovery-dual": { title: "Auto-Heal (8×8 Haar)", tag: "best", text: "Invisible + self-healing · 2^-16 check" },
  "keyed-opt": { title: "Max Quality Blind", tag: "v3", text: "~46.4 dB PSNR · blind 2^-8 MAC" },
  opap: { title: "OPAP Base", tag: "v3", text: "~46.4 dB · needs reference bits" },
  keyed: { title: "Keyed Blind (2×2)", tag: "v2", text: "Block MAC tamper detection" },
  recovery: { title: "Auto-Heal (4×4)", tag: "v2", text: "Partner AA recovery + 12-bit MAC" },
  lsb: { title: "LSB Replacement", tag: "base", text: "~44.1 dB reference LSB embedding" },
  paper: { title: "Literal Paper Rule", tag: "base", text: "RPA → XOR → QE → Pauli-X rule" },
};

const GLOBAL_PARAMS = {
  gaussian_noise: ["sigma", 0.005, 0.3, 0.005, 0.02, "σ"],
  salt_pepper_noise: ["density", 0.005, 0.3, 0.005, 0.02, "density"],
  median_filter: ["kernel", 3, 7, 2, 3, "kernel"],
  histogram_equalization: null,
  jpeg_compression: ["quality", 10, 95, 1, 75, "quality"],
  cropping: ["fraction", 0.05, 0.5, 0.01, 0.2, "fraction"],
  rotation: ["angle", -45, 45, 1, 5, "angle °"],
  text_addition: null,
};

function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (t.hidden = true), 5000);
}

async function api(path, body) {
  const opts = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
  if (!res.ok || data.error) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

async function busy(button, fn) {
  const html = button.innerHTML;
  button.disabled = true;
  button.textContent = "Working…";
  try {
    await fn();
  } catch (err) {
    toast(err.message);
  } finally {
    button.disabled = false;
    button.innerHTML = html;
  }
}

const fmt = (v, d = 2) => (v === null || v === undefined ? "–" : !isFinite(v) ? "∞" : Number(v).toFixed(d));
const chip = (label, value) => `<span class="chip"><b>${value}</b>${label}</span>`;

// --------------------------------------------------------------------------- setup
function syncModeUI(mode) {
  state.mode = mode;
  document.querySelectorAll(".mode").forEach((m) => {
    const inp = m.querySelector("input");
    if (inp) inp.checked = inp.value === mode;
    m.classList.toggle("selected", inp && inp.value === mode);
  });
  document.querySelectorAll(".preset-card").forEach((c) => c.classList.toggle("active", c.dataset.preset === mode));
  if ($("keyrow")) $("keyrow").style.display = mode.startsWith("keyed") || mode.startsWith("recovery") ? "" : "none";
}

function renderModes() {
  const box = $("modes");
  box.innerHTML = "";
  for (const [mode, info] of Object.entries(MODE_INFO)) {
    const lab = document.createElement("label");
    lab.className = "mode" + (mode === state.mode ? " selected" : "");
    lab.innerHTML = `<input type="radio" name="mode" value="${mode}" ${mode === state.mode ? "checked" : ""}><span class="dot"></span>
      <span><b>${info.title}<span class="tag">${info.tag}</span></b><small>${info.text}</small></span>`;
    lab.querySelector("input").addEventListener("change", () => syncModeUI(mode));
    box.appendChild(lab);
  }
  document.querySelectorAll(".preset-card").forEach((card) =>
    card.addEventListener("click", () => {
      syncModeUI(card.dataset.preset);
      busy($("embed-sec-btn"), embed);
    })
  );
}

async function init() {
  renderModes();
  try {
    const meta = await api("/api/meta");
    state.meta = meta;
    const sel = $("image");
    for (const name of meta.images) sel.add(new Option(name, name));
    sel.value = meta.images.includes("airplane")
      ? "airplane"
      : meta.images.includes("rocket")
        ? "rocket"
        : meta.images.includes("peppers")
          ? "peppers"
          : meta.images[0];
    document.querySelectorAll(".sample-dot").forEach((b) => b.classList.toggle("active", b.dataset.sample === sel.value));
    for (const e of meta.local_edits) $("local-name").add(new Option(e.label, e.name));
    $("local-name").value = "lsb_preserving_splice";
    for (const a of meta.attacks) $("global-name").add(new Option(a.label, a.name));
    $("global-name").value = "jpeg_compression";
    setGlobalParam();
    $("status").textContent = "Ready · local quantum lab";
    pollClassifier();
    await embed();
  } catch (err) {
    $("status").textContent = "Server offline";
    toast(err.message);
  }
}

async function pollClassifier() {
  const meta = await api("/api/meta").catch(() => null);
  if (!meta) return;
  $("clf-info").textContent = meta.classifier.info;
  if (!meta.classifier.ready) setTimeout(pollClassifier, 2500);
}

// --------------------------------------------------------------------------- step 1
async function readUpload() {
  const f = $("upload").files[0] || ($("upload-dup") && $("upload-dup").files[0]);
  if (!f) return null;
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result);
    r.onerror = reject;
    r.readAsDataURL(f);
  });
}

async function embed() {
  const upload = await readUpload();
  const body = { mode: state.mode, key: $("key").value, nonce: $("nonce").value };
  if (upload) body.upload = upload;
  else body.image = $("image").value;
  const r = await api("/api/embed", body);
  state.session = r.session;
  $("cover").src = r.cover;
  $("watermarked").src = r.watermarked;
  $("dl-watermarked").href = r.watermarked;
  $("hero-img").src = r.watermarked;
  $("tile-attack-img").src = r.watermarked;
  $("difference").src = r.difference;
  $("embed-out").hidden = false;
  $("pickbox").hidden = true;
  const m = r.metrics;
  $("hero-psnr").textContent = fmt(m.psnr, 2);
  const delta = m.psnr - 44.15;
  $("hero-delta").textContent = `${delta >= 0 ? "+" : ""}${fmt(delta, 2)} dB`;
  $("hero-side").textContent = state.mode.startsWith("recovery") ? "Auto-Heal On" : state.mode.startsWith("keyed") ? "Spot Edits" : "Reference";
  $("m-ssim-pct").textContent = `${fmt(m.ssim * 100, 1)}%`;

  $("embed-metrics").innerHTML =
    chip("PSNR", `${fmt(m.psnr)} dB`) + chip("SSIM", fmt(m.ssim, 4)) + chip("MSE", fmt(m.mse, 3)) +
    chip("Speed", `${fmt(m.embed_ms, 1)} ms`);

  // Plain-English top strip readout
  const schemeName = (MODE_INFO[state.mode] || {}).title || state.mode;
  $("hero-story").textContent = `Locked "${body.upload ? "your uploaded photo" : body.image}" (${fmt(m.ssim * 100, 1)}% identical visually). Click ▶ on the next tile to cut part of the image and watch it self-heal.`;
  $("tile4-title").innerHTML = "Protected<br>Ready";
  $("tile4-sub").textContent = `${fmt(m.ssim * 100, 1)}% visual match · ${schemeName}`;

  loadCanvas(r.watermarked);
  $("attacked").src = r.watermarked;
  $("attack-caption").textContent = "Untouched watermarked image";
  $("attack-out").hidden = false;
  for (const id of ["verify-out", "verdict"]) $(id).hidden = true;
  $("verify-note").textContent = "Apply any tamper on the left or click Verify & Repair to check authenticity.";
  $("bars").innerHTML = "";
  $("block-out").hidden = true;
}

function pickBlock(ev) {
  if (!state.session) return;
  const img = $("cover");
  const rect = img.getBoundingClientRect();
  const x = Math.floor(((ev.clientX - rect.left) / rect.width) * state.imageSize);
  const y = Math.floor(((ev.clientY - rect.top) / rect.height) * state.imageSize);
  const row = Math.max(0, Math.min(state.imageSize / 2 - 1, Math.floor(y / 2)));
  const col = Math.max(0, Math.min(state.imageSize / 2 - 1, Math.floor(x / 2)));
  const box = $("pickbox");
  const scale = rect.width / state.imageSize;
  const size = Math.max(8, 2 * scale);
  box.style.width = box.style.height = `${size}px`;
  box.style.left = `${(col * 2 + 1) * scale - size / 2}px`;
  box.style.top = `${(row * 2 + 1) * scale - size / 2}px`;
  box.hidden = false;
  inspectBlock(row, col).catch((e) => toast(e.message));
}

// --------------------------------------------------------------------------- step 2
function loadCanvas(src) {
  const c = $("canvas");
  const ctx = c.getContext("2d");
  const im = new Image();
  im.onload = () => {
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(im, 0, 0, c.width, c.height);
  };
  im.src = src;
  state.canvasSrc = src;
}

function setupPaint() {
  const c = $("canvas");
  const ctx = c.getContext("2d");
  let drawing = false;
  let last = null;
  const pos = (ev) => {
    const r = c.getBoundingClientRect();
    return [((ev.clientX - r.left) / r.width) * c.width, ((ev.clientY - r.top) / r.height) * c.height];
  };
  const dot = (p) => {
    const v = state.paintValue;
    ctx.strokeStyle = ctx.fillStyle = `rgb(${v},${v},${v})`;
    ctx.lineWidth = Number($("brush").value);
    ctx.lineCap = "round";
    ctx.beginPath();
    if (last) {
      ctx.moveTo(last[0], last[1]);
      ctx.lineTo(p[0], p[1]);
      ctx.stroke();
    } else {
      ctx.arc(p[0], p[1], ctx.lineWidth / 2, 0, 2 * Math.PI);
      ctx.fill();
    }
    last = p;
  };
  c.addEventListener("pointerdown", (e) => {
    if (!state.session) return toast("Protect an image first");
    drawing = true;
    last = null;
    c.setPointerCapture(e.pointerId);
    dot(pos(e));
  });
  c.addEventListener("pointermove", (e) => drawing && dot(pos(e)));
  c.addEventListener("pointerup", () => ((drawing = false), (last = null)));
  $("swatches").addEventListener("click", (e) => {
    const b = e.target.closest(".sw");
    if (!b) return;
    state.paintValue = Number(b.dataset.v);
    document.querySelectorAll(".sw").forEach((s) => s.classList.toggle("active", s === b));
  });
  $("paint-reset").addEventListener("click", () => state.canvasSrc && loadCanvas(state.canvasSrc));
}

function setGlobalParam() {
  const spec = GLOBAL_PARAMS[$("global-name").value];
  const wrap = $("global-param-wrap");
  if (!spec) {
    wrap.style.visibility = "hidden";
    return;
  }
  wrap.style.visibility = "visible";
  const [, min, max, step, def, label] = spec;
  const s = $("global-param");
  Object.assign(s, { min, max, step });
  s.value = def;
  $("global-param-label").textContent = label;
  $("global-param-v").textContent = def;
}

async function attack(body) {
  if (!state.session) throw new Error("Protect an image first");
  const r = await api("/api/attack", { session: state.session, seed: Math.floor(Math.random() * 1e6), ...body });
  $("attacked").src = r.attacked;
  $("tile-attack-img").src = r.attacked;
  $("attack-caption").textContent = `${r.label} · ${fmt(r.psnr)} dB · ${r.changed_pixels.toLocaleString()} px`;
  $("attack-out").hidden = false;
  for (const id of ["verify-out", "verdict"]) $(id).hidden = true;
  $("verify-note").textContent = "";
  $("bars").innerHTML = "";
}

// --------------------------------------------------------------------------- steps 3-5
async function verify() {
  if (!state.session) throw new Error("Protect an image first");
  const r = await api("/api/verify", { session: state.session });
  $("overlay").src = r.overlay;
  $("dl-overlay").href = r.overlay;
  $("verify-out").hidden = false;
  const v = $("verdict");
  v.hidden = false;
  const ok = r.verdict === "authentic";
  v.className = "verdict " + (ok ? "ok" : "bad");
  const pct = (100 * r.blocks_failed) / r.blocks_total;
  v.innerHTML = ok
    ? `Looks Real! All ${r.blocks_total.toLocaleString()} blocks verified untouched`
    : `Fake Edit Spotted in ${r.blocks_failed.toLocaleString()} / ${r.blocks_total.toLocaleString()} blocks (${fmt(pct)}% of photo)`;
  if (r.ber !== undefined) v.innerHTML += `<small>BER vs reference: ${fmt(r.ber, 4)}</small>`;
  const rf = $("recovered-fig");
  if (r.recovered) {
    $("recovered").src = r.recovered;
    $("dl-recovered").href = r.recovered;
    $("hero-img").src = r.recovered;
    $("recovered-caption").textContent = `Healed ${fmt(100 * r.restored_fraction, 0)}% (${fmt(r.psnr_attacked)} → ${fmt(r.psnr_recovered)} dB)`;
    $("tile4-title").innerHTML = `Fixed<br>${fmt(100 * r.restored_fraction, 0)}%`;
    $("tile4-sub").textContent = `${fmt(r.psnr_attacked)} → ${fmt(r.psnr_recovered)} dB restored`;
    $("hero-story").textContent = `Caught ${r.blocks_failed} forged blocks (${fmt(pct)}%) and rebuilt damaged pixels automatically (${fmt(100 * r.restored_fraction, 0)}% healed).`;
    rf.hidden = false;
  } else {
    rf.hidden = true;
    $("tile4-title").innerHTML = ok ? "Real &amp;<br>Safe" : "Edit<br>Caught";
    $("tile4-sub").textContent = ok ? "0 tampered spots" : `${r.blocks_failed} altered spots highlighted`;
  }
  $("verify-note").textContent = ok
    ? "No edits detected anywhere in this photo."
    : r.recovered
      ? `Rebuilt ${fmt(100 * r.restored_fraction, 0)}% of the damaged area using hidden backup copies elsewhere in your photo.`
      : (r.note || "");
}

async function classify() {
  if (!state.session) throw new Error("Protect an image first");
  const r = await api("/api/classify", { session: state.session });
  $("clf-info").textContent = r.info;
  if (!r.ready) return toast("Classifier still warming up — retry in a moment");
  $("clf-top-pct").textContent = `${fmt(100 * r.confidence, 1)}%`;
  $("clf-top-lbl").textContent = r.predicted;
  $("clf-ood-pill").hidden = false;
  $("clf-ood-pill").textContent = r.is_unknown ? "Unseen Type" : "Recognized";
  const oodPill = r.is_unknown
    ? `<span class="ood-badge warn">OOD (${fmt(100 * r.confidence, 1)}% &lt; ${fmt(100 * r.threshold, 1)}%)</span>`
    : `<span class="ood-badge safe">Known (${fmt(100 * r.confidence, 1)}% &ge; ${fmt(100 * r.threshold, 1)}%)</span>`;
  $("bars").innerHTML = r.probabilities
    .slice(0, 5)
    .map(
      (p, i) => `<div class="bar ${i === 0 ? "best" : ""}"><span>${p.name}</span><div class="track"><div class="fill" style="width:${(100 * p.p).toFixed(1)}%"></div></div><span class="pct">${(100 * p.p).toFixed(1)}%</span></div>`
    )
    .join("") + `<p class="note">Applied: <b>${r.actual}</b> ${oodPill}</p>`;
}

async function inspectBlock(row, col) {
  state.blockRow = row;
  state.blockCol = col;
  const r = await api("/api/block", { session: state.session, row, col });
  $("block-id").textContent = `(${row}, ${col})`;
  const t = r.trace;
  const rows = [
    ["Pixels", r.pixels.join(", ")],
    ["Binary", r.binary.join(" ")],
    ["PPB", t.ppb.map((p) => p.join("")).join(" ")],
    ["AA = ⌊S/4 + 0.5⌋", `${t.sum} → ${t.aa}`],
    ["Watermark Wb", t.watermark.join("")],
  ];
  $("block-kv").innerHTML = rows.map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join("");
  $("block-circuits").querySelector("tbody").innerHTML = r.circuits
    .map((c) => `<tr><td>${c.name}</td><td>${c.qubits}</td><td>${c.result}</td></tr>`)
    .join("");
  $("neqr").src = r.neqr;
  $("block-out").hidden = false;
  $("nisq-tbl").hidden = true;
  if ($("quantum-details")) $("quantum-details").open = true;
  $("block-hint").textContent = `Block (${row}, ${col}) simulated in ${fmt(Object.values(r.timings_ms).reduce((a, b) => a + b, 0), 0)} ms.`;
}

async function runBlockNisq() {
  if (!state.session) throw new Error("Protect an image first");
  const r = await api("/api/nisq_block", {
    session: state.session,
    row: state.blockRow,
    col: state.blockCol,
    p2: Number($("nisq-p2").value),
    t1_us: Number($("nisq-t1").value),
  });
  $("nisq-tbl").querySelector("tbody").innerHTML = r.rows
    .map((row) => `<tr><td>${row.name}</td><td>${row.qubits}</td><td>${row.two_qubit_gates}</td><td>${row.depth}</td><td>${fmt(row.duration_us, 1)}</td><td>${fmt(100 * row.success, 1)}%</td></tr>`)
    .join("");
  $("nisq-tbl").hidden = false;
  if ($("quantum-details")) $("quantum-details").open = true;
  if (r.rows[1]) $("stat-depth").textContent = `${r.rows[1].depth}`;
}

// --------------------------------------------------------------------------- views & 1-click flows
function setupTheme() {
  const root = document.documentElement;
  let saved = null;
  try {
    saved = localStorage.getItem("qwm-theme");
  } catch (_) {
    saved = null;
  }
  root.dataset.theme = saved === "dark" ? "dark" : "light";
  $("theme").addEventListener("click", () => {
    root.dataset.theme = root.dataset.theme === "dark" ? "light" : "dark";
    try {
      localStorage.setItem("qwm-theme", root.dataset.theme);
    } catch (_) {
      /* private mode */
    }
  });
}

function showView(view) {
  const dash = $("dashboard-view");
  const paper = $("paper-view");
  const inside = $("inside-view");
  const isPaper = view === "paper";
  const isInside = view === "inside";
  if (dash) dash.hidden = isPaper || isInside;
  if (paper) paper.hidden = !isPaper;
  if (inside) inside.hidden = !isInside;
  if (!isInside && window.InsideSim) window.InsideSim.close();
  document.querySelectorAll(".rail-nav a").forEach((l) => {
    const v = l.dataset.view || "dashboard";
    if (isPaper) l.classList.toggle("active", v === "paper");
    else if (isInside) l.classList.toggle("active", v === "inside");
    else l.classList.toggle("active", v === "dashboard" && l.getAttribute("href") === "#studio-sec");
  });
  if (isPaper) {
    loadPaperSummary();
    paper.scrollIntoView({ behavior: "smooth" });
  } else if (isInside) {
    launchInsideSimulation();
    inside.scrollIntoView({ behavior: "smooth" });
  }
}

async function launchInsideSimulation() {
  const coverEl = $("cover");
  const coverUrl = coverEl && coverEl.src ? coverEl.src : "";
  let ctxData = { imageName: $("image") ? $("image").value : "airplane", row: state.blockRow, col: state.blockCol, coverUrl };
  if (state.session) {
    try {
      const blk = await api("/api/block", { session: state.session, row: state.blockRow, col: state.blockCol });
      const ps = blk.pixels || [50, 60, 48, 32];
      const wb = blk.trace.watermark || [1, 1, 0, 0, 1, 1, 0, 1];
      const wPs = ps.map((p, i) => {
        let out = p;
        for (let b = 0; b < 2; b++) {
          const targetBit = wb[2 * i + b];
          out = (out & ~(1 << b)) | ((targetBit & 1) << b);
        }
        return out;
      });
      ctxData = {
        ...ctxData,
        pixels: ps,
        binary: blk.binary,
        ppb: blk.trace.ppb,
        sum: blk.trace.sum,
        aa: blk.trace.aa,
        watermark: wb,
        watermarkedPixels: wPs,
      };
    } catch (_) {
      /* fallback defaults */
    }
  }
  if (window.InsideSim) window.InsideSim.open(ctxData);
}

function setupNav() {
  document.querySelectorAll(".rail-nav a").forEach((a) => {
    a.addEventListener("click", (ev) => {
      const view = a.dataset.view || "dashboard";
      showView(view);
      if (view === "paper" || view === "inside") ev.preventDefault();
    });
  });
  $("hero-paper-icon").addEventListener("click", () => showView("paper"));
  if ($("show-inside-btn")) $("show-inside-btn").addEventListener("click", () => showView("inside"));
  if ($("step5-inside-btn")) $("step5-inside-btn").addEventListener("click", () => showView("inside"));
  if ($("banner-inside-btn")) $("banner-inside-btn").addEventListener("click", () => showView("inside"));
  $("back-overview").addEventListener("click", () => {
    showView("dashboard");
    $("top").scrollIntoView({ behavior: "smooth" });
  });
  if ($("back-from-inside")) {
    $("back-from-inside").addEventListener("click", () => {
      showView("dashboard");
      $("top").scrollIntoView({ behavior: "smooth" });
    });
  }
  if ($("inside-play")) $("inside-play").addEventListener("click", () => window.InsideSim && window.InsideSim.togglePlay());
  if ($("inside-prev")) $("inside-prev").addEventListener("click", () => window.InsideSim && window.InsideSim.prev());
  if ($("inside-next")) $("inside-next").addEventListener("click", () => window.InsideSim && window.InsideSim.next());
  if ($("inside-replay")) $("inside-replay").addEventListener("click", () => window.InsideSim && window.InsideSim.replay());
  if ($("inside-speed")) $("inside-speed").addEventListener("click", () => window.InsideSim && window.InsideSim.cycleSpeed());
  if ($("inside-labels")) $("inside-labels").addEventListener("click", () => window.InsideSim && window.InsideSim.togglePaperLabels());
  if ($("inside-scrub")) {
    $("inside-scrub").addEventListener("click", (e) => {
      const r = $("inside-scrub").getBoundingClientRect();
      window.InsideSim && window.InsideSim.scrubRatio((e.clientX - r.left) / r.width);
    });
  }
}

async function loadPaperSummary() {
  const r = await api("/api/paper");
  $("paper-families-tbl").querySelector("tbody").innerHTML = r.circuit_families
    .map((x) => `<tr><td>${x.circuit}</td><td>${x.family}</td><td>${x.qubits}</td><td>${x.cnot_count}</td><td>${x.cnot_level_depth}</td></tr>`)
    .join("");
  $("paper-bounds-tbl").querySelector("tbody").innerHTML = r.psnr_bounds
    .map((x) => `<tr><td>${x.method}</td><td>${fmt(x.mse, 4)}</td><td>${fmt(x.psnr_db, 2)}</td></tr>`)
    .join("");
  const w = r.worked;
  $("paper-worked-note").textContent =
    `Worked block [[50,60],[48,32]]: AA=${w.aa}, Wb=${w.watermark.join("")}, |W>=${JSON.stringify(w.watermarked_paper)}, exact inverse U†|W>=|C>⊗|Wb>: ${w.unitary_inverse}. Table 9 violations: ${r.table9_violations}/${r.table9.length}.`;
  $("paper-t9-tbl").querySelector("tbody").innerHTML = r.table9
    .map((x) => `<tr><td>${x.image}</td><td>${x.fidelity}</td><td>${x.trace_distance}</td><td>${x.purity}</td><td><span class="pill-status ${x.consistent ? "ok" : "bad"}">${x.consistent ? "OK" : "Violates"}</span></td></tr>`)
    .join("");
  $("paper-comp-tbl").querySelector("tbody").innerHTML = r.complexity
    .map((x) => `<tr><td>${x.image}</td><td>${x.n}</td><td>${Number(x.FRQI).toLocaleString()}</td><td>${Number(x.NEQR).toLocaleString()}</td></tr>`)
    .join("");
}

async function runFullDemo() {
  showView("dashboard");
  await embed();
  await attack({ kind: "local", name: "blackout", fraction: 0.2 });
  await verify();
  if (state.meta && state.meta.classifier && state.meta.classifier.ready) {
    await classify().catch(() => null);
  } else {
    const meta = await api("/api/meta").catch(() => null);
    if (meta && meta.classifier && meta.classifier.ready) await classify().catch(() => null);
  }
  await inspectBlock(64, 64);
  await runBlockNisq();
}

async function quickTamperAndHeal(attackBody) {
  await attack(attackBody);
  await verify();
}

// --------------------------------------------------------------------------- wiring
document.addEventListener("DOMContentLoaded", () => {
  setupTheme();
  setupNav();
  init();
  setupPaint();

  $("embed").addEventListener("click", (e) => busy(e.target, embed));
  $("embed-sec-btn").addEventListener("click", (e) => busy(e.target, embed));
  $("image").addEventListener("change", () => {
    document.querySelectorAll(".sample-dot").forEach((b) => b.classList.toggle("active", b.dataset.sample === $("image").value));
    busy($("embed"), embed);
  });
  document.querySelectorAll(".sample-dot").forEach((b) =>
    b.addEventListener("click", () => {
      const name = b.dataset.sample;
      $("upload").value = "";
      if ($("upload-dup")) $("upload-dup").value = "";
      $("image").disabled = false;
      $("clear-upload").hidden = true;
      if ([...$("image").options].some((o) => o.value === name)) $("image").value = name;
      document.querySelectorAll(".sample-dot").forEach((d) => d.classList.toggle("active", d === b));
      busy($("embed"), embed);
    })
  );

  $("cover").addEventListener("click", pickBlock);
  document.querySelectorAll(".tab").forEach((tab) =>
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t === tab));
      document.querySelectorAll(".tabpane").forEach((p) => (p.hidden = p.dataset.pane !== tab.dataset.tab));
    })
  );

  $("paint-apply").addEventListener("click", (e) => busy(e.target, () => quickTamperAndHeal({ kind: "paint", image: $("canvas").toDataURL("image/png") })));
  $("local-frac").addEventListener("input", () => ($("local-frac-v").textContent = Number($("local-frac").value).toFixed(2)));
  $("local-apply").addEventListener("click", (e) => busy(e.target, () => quickTamperAndHeal({ kind: "local", name: $("local-name").value, fraction: Number($("local-frac").value) })));
  $("global-name").addEventListener("change", setGlobalParam);
  $("global-param").addEventListener("input", () => ($("global-param-v").textContent = $("global-param").value));
  $("global-apply").addEventListener("click", (e) =>
    busy(e.target, () => {
      const name = $("global-name").value;
      const spec = GLOBAL_PARAMS[name];
      const params = spec ? { [spec[0]]: Number($("global-param").value) } : {};
      return quickTamperAndHeal({ kind: "global", name, params });
    })
  );

  $("quick-blackout").addEventListener("click", (e) => busy(e.target, () => quickTamperAndHeal({ kind: "local", name: "blackout", fraction: 0.2 })));
  $("quick-splice").addEventListener("click", (e) => busy(e.target, () => quickTamperAndHeal({ kind: "local", name: "lsb_preserving_splice", fraction: 0.2 })));
  $("none-apply").addEventListener("click", (e) => busy(e.target, () => quickTamperAndHeal({ kind: "none" })));
  $("verify").addEventListener("click", (e) => busy(e.target, verify));
  $("classify").addEventListener("click", (e) => busy(e.target, classify));
  $("nisq-p2").addEventListener("input", () => ($("nisq-p2-v").textContent = $("nisq-p2").value));
  $("nisq-t1").addEventListener("input", () => ($("nisq-t1-v").textContent = $("nisq-t1").value));
  $("nisq-run").addEventListener("click", (e) => busy(e.target, runBlockNisq));

  $("run-full").addEventListener("click", (e) => busy(e.target, runFullDemo));
  $("hero-demo-icon").addEventListener("click", () => $("run-full").click());
  const tileTamper = $("tile-tamper-trigger");
  tileTamper.addEventListener("click", () => busy($("run-full"), () => quickTamperAndHeal({ kind: "local", name: "blackout", fraction: 0.2 })));
  tileTamper.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      tileTamper.click();
    }
  });

  const handleUploadChange = (srcInput) => {
    const file = srcInput.files[0];
    if (srcInput === $("upload-dup") && file && $("upload")) {
      const dt = new DataTransfer();
      dt.items.add(file);
      $("upload").files = dt.files;
    }
    const hasFile = Boolean($("upload").files[0] || ($("upload-dup") && $("upload-dup").files[0]));
    $("image").disabled = hasFile;
    $("clear-upload").hidden = !hasFile;
    if (hasFile) busy($("embed"), embed);
  };
  $("upload").addEventListener("change", (e) => handleUploadChange(e.target));
  if ($("upload-dup")) $("upload-dup").addEventListener("change", (e) => handleUploadChange(e.target));
  $("clear-upload").addEventListener("click", () => {
    $("upload").value = "";
    if ($("upload-dup")) $("upload-dup").value = "";
    $("image").disabled = false;
    $("clear-upload").hidden = true;
    busy($("embed"), embed);
  });
});
