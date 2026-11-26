"use strict";
// NEQR quantum watermarking dashboard - clean modern Nixtio-inspired GUI.

const $ = (id) => document.getElementById(id);
const state = { session: null, mode: "keyed-opt", meta: null, paintValue: 255, imageSize: 256, blockRow: 0, blockCol: 0 };

const MODE_INFO = {
  paper: { title: "Base: literal rule", tag: "base", text: "RPA → XOR → QE → Pauli-X rule" },
  lsb: { title: "Base: LSB replacement", tag: "base", text: "PPB ⊕ AA (needs reference bits)" },
  opap: { title: "Base: OPAP", tag: "v3", text: "±4 MSB adjustment (~46.4 dB)" },
  keyed: { title: "Keyed blind (2×2)", tag: "v2", text: "MAC blind verify (2^-8 prob)" },
  "keyed-opt": { title: "Keyed optimal", tag: "v3", text: "81-coset blind (~46.4 dB)" },
  recovery: { title: "Self-recovery (4×4)", tag: "v2", text: "Partner AA code + 12-bit MAC" },
  "recovery-dual": { title: "Dual-partner Haar (8×8)", tag: "v3", text: "Primary + backup Haar (2^-16)" },
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

function renderDotMatrix(values = [0.35, 0.55, 0.45, 0.72, 0.30, 0.50, 0.85, 0.65, 0.48]) {
  const box = $("dot-matrix");
  if (!box) return;
  box.innerHTML = values
    .map((v) => {
      const n = Math.max(1, Math.min(5, Math.round(v * 5)));
      let dots = "";
      for (let i = 0; i < 5; i++) {
        const cls = i < n ? (n >= 4 && i === n - 1 ? "dm-dot peak" : "dm-dot on") : "dm-dot";
        dots += `<span class="${cls}"></span>`;
      }
      return `<div class="dm-col">${dots}</div>`;
    })
    .join("");
}

// --------------------------------------------------------------------------- setup
function renderModes() {
  const box = $("modes");
  box.innerHTML = "";
  for (const [mode, info] of Object.entries(MODE_INFO)) {
    const lab = document.createElement("label");
    lab.className = "mode" + (mode === state.mode ? " selected" : "");
    lab.innerHTML = `<input type="radio" name="mode" value="${mode}" ${mode === state.mode ? "checked" : ""}><span class="dot"></span>
      <span><b>${info.title}<span class="tag">${info.tag}</span></b><small>${info.text}</small></span>`;
    lab.querySelector("input").addEventListener("change", () => {
      state.mode = mode;
      document.querySelectorAll(".mode").forEach((m) => m.classList.toggle("selected", m.querySelector("input").checked));
      $("keyrow").style.display = mode.startsWith("keyed") || mode.startsWith("recovery") ? "" : "none";
    });
    box.appendChild(lab);
  }
}

async function init() {
  renderModes();
  renderDotMatrix();
  try {
    const meta = await api("/api/meta");
    state.meta = meta;
    const sel = $("image");
    for (const name of meta.images) sel.add(new Option(name, name));
    sel.value = meta.images.includes("peppers") ? "peppers" : meta.images[0];
    for (const e of meta.local_edits) $("local-name").add(new Option(e.label, e.name));
    $("local-name").value = "lsb_preserving_splice";
    for (const a of meta.attacks) $("global-name").add(new Option(a.label, a.name));
    $("global-name").value = "jpeg_compression";
    setGlobalParam();
    $("status").textContent = "Live · local simulation";
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
  const f = $("upload").files[0];
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
  setHero(r.watermarked);
  $("difference").src = r.difference;
  $("embed-out").hidden = false;
  $("pickbox").hidden = true;
  const m = r.metrics;
  $("hero-psnr").textContent = fmt(m.psnr, 2);
  $("hero-delta").textContent = `${fmt(m.psnr - 44.15, 2) >= 0 ? "+" : ""}${fmt(m.psnr - 44.15, 2)} dB`;
  $("hero-side").textContent = m.side_information_bits ? `${m.side_information_bits.toLocaleString()} bits` : "Key only";
  const psnrShare = Math.min(100, Math.max(20, (m.psnr / 48.4) * 100));
  $("m-psnr-pct").textContent = `${fmt(psnrShare, 0)}%`;
  $("bar-psnr").style.width = `${psnrShare}%`;
  $("m-ssim-pct").textContent = `${fmt(m.ssim * 100, 1)}%`;
  $("bar-ssim").style.width = `${Math.min(100, m.ssim * 100)}%`;

  $("embed-metrics").innerHTML =
    chip("PSNR", `${fmt(m.psnr)} dB`) + chip("SSIM", fmt(m.ssim, 4)) + chip("MSE", fmt(m.mse, 3)) +
    chip("Time", `${fmt(m.embed_ms, 1)} ms`);
  loadCanvas(r.watermarked);
  $("attacked").src = r.watermarked;
  $("attack-caption").textContent = "Untouched watermarked image";
  $("attack-out").hidden = false;
  for (const id of ["verify-out", "verdict"]) $(id).hidden = true;
  $("verify-note").textContent = "";
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
    if (!state.session) return toast("Embed an image first");
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
  if (!state.session) throw new Error("Embed an image first");
  const r = await api("/api/attack", { session: state.session, seed: Math.floor(Math.random() * 1e6), ...body });
  $("attacked").src = r.attacked;
  $("attack-caption").textContent = `${r.label} · ${fmt(r.psnr)} dB · ${r.changed_pixels.toLocaleString()} px`;
  $("attack-out").hidden = false;
  for (const id of ["verify-out", "verdict"]) $(id).hidden = true;
  $("verify-note").textContent = "";
  $("bars").innerHTML = "";
}

// --------------------------------------------------------------------------- steps 3-5
async function verify() {
  if (!state.session) throw new Error("Embed an image first");
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
    ? `Authentic — all ${r.blocks_total.toLocaleString()} blocks verified`
    : `Tampered — ${r.blocks_failed.toLocaleString()} / ${r.blocks_total.toLocaleString()} ${r.block_size}×${r.block_size} blocks failed (${fmt(pct)}%)`;
  if (r.ber !== undefined) v.innerHTML += `<small>BER vs reference: ${fmt(r.ber, 4)}</small>`;
  const rf = $("recovered-fig");
  if (r.recovered) {
    $("recovered").src = r.recovered;
    $("dl-recovered").href = r.recovered;
    $("recovered-caption").textContent = `${fmt(r.psnr_attacked)} → ${fmt(r.psnr_recovered)} dB (${fmt(100 * r.restored_fraction, 0)}% restored)`;
    rf.hidden = false;
  } else rf.hidden = true;
  $("verify-note").textContent = r.note || "";
}

async function classify() {
  if (!state.session) throw new Error("Embed an image first");
  const r = await api("/api/classify", { session: state.session });
  $("clf-info").textContent = r.info;
  if (!r.ready) return toast("Classifier still warming up — retry in a moment");
  $("clf-top-pct").textContent = `${fmt(100 * r.confidence, 1)}%`;
  $("clf-top-lbl").textContent = r.predicted;
  $("clf-ood-pill").textContent = r.is_unknown ? "OOD Flagged" : "In-distribution";
  renderDotMatrix(r.probabilities.slice(0, 9).map((p) => Math.max(0.15, p.p)));
  const oodPill = r.is_unknown
    ? `<span class="ood-badge warn">OOD (${fmt(100 * r.confidence, 1)}% &lt; ${fmt(100 * r.threshold, 1)}%)</span>`
    : `<span class="ood-badge safe">Known (${fmt(100 * r.confidence, 1)}% &ge; ${fmt(100 * r.threshold, 1)}%)</span>`;
  $("bars").innerHTML = r.probabilities
    .slice(0, 5)
    .map(
      (p, i) => `<div class="bar ${i === 0 ? "best" : ""}"><span>${p.name}</span><div class="track"><div class="fill" style="width:${(100 * p.p).toFixed(1)}%"></div></div><span class="pct">${(100 * p.p).toFixed(1)}%</span></div>`
    )
    .join("") + `<p class="hint">Applied: <b>${r.actual}</b> ${oodPill}</p>`;
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
  $("block-hint").textContent = `Block (${row}, ${col}) simulated in ${fmt(Object.values(r.timings_ms).reduce((a, b) => a + b, 0), 0)} ms.`;
}

async function runBlockNisq() {
  if (!state.session) throw new Error("Embed an image first");
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
  if (r.rows[1]) {
    $("stat-depth").textContent = `${r.rows[1].depth}`;
    const barP = $("bar-nisq-p");
    if (barP) barP.style.height = `${Math.max(18, Math.round(r.rows[0].success * 96))}px`;
  }
}

// --------------------------------------------------------------------------- look and feel
function setHero(src) {
  const img = $("hero-img");
  img.classList.remove("ready");
  img.onload = () => setTimeout(() => img.classList.add("ready"), 20);
  img.src = src;
}

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

function setupSpy() {
  const links = [...document.querySelectorAll(".side-nav a")];
  links.forEach((a) => {
    a.addEventListener("click", () => {
      links.forEach((l) => l.classList.remove("active"));
      a.classList.add("active");
    });
  });
}

// --------------------------------------------------------------------------- wiring
document.addEventListener("DOMContentLoaded", () => {
  setupTheme();
  setupSpy();
  init();
  setupPaint();
  $("embed").addEventListener("click", (e) => busy(e.target, embed));
  $("image").addEventListener("change", () => busy($("embed"), embed));
  $("cover").addEventListener("click", pickBlock);
  document.querySelectorAll(".tab").forEach((tab) =>
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t === tab));
      document.querySelectorAll(".tabpane").forEach((p) => (p.hidden = p.dataset.pane !== tab.dataset.tab));
    })
  );
  $("paint-apply").addEventListener("click", (e) => busy(e.target, () => attack({ kind: "paint", image: $("canvas").toDataURL("image/png") })));
  $("local-frac").addEventListener("input", () => ($("local-frac-v").textContent = Number($("local-frac").value).toFixed(2)));
  $("local-apply").addEventListener("click", (e) => busy(e.target, () => attack({ kind: "local", name: $("local-name").value, fraction: Number($("local-frac").value) })));
  $("global-name").addEventListener("change", setGlobalParam);
  $("global-param").addEventListener("input", () => ($("global-param-v").textContent = $("global-param").value));
  $("global-apply").addEventListener("click", (e) =>
    busy(e.target, () => {
      const name = $("global-name").value;
      const spec = GLOBAL_PARAMS[name];
      const params = spec ? { [spec[0]]: Number($("global-param").value) } : {};
      return attack({ kind: "global", name, params });
    })
  );
  $("none-apply").addEventListener("click", (e) => busy(e.target, () => attack({ kind: "none" })));
  $("verify").addEventListener("click", (e) => busy(e.target, verify));
  $("classify").addEventListener("click", (e) => busy(e.target, classify));
  $("nisq-p2").addEventListener("input", () => ($("nisq-p2-v").textContent = $("nisq-p2").value));
  $("nisq-t1").addEventListener("input", () => ($("nisq-t1-v").textContent = $("nisq-t1").value));
  $("nisq-run").addEventListener("click", (e) => busy(e.target, runBlockNisq));
  $("upload").addEventListener("change", () => {
    const hasFile = Boolean($("upload").files[0]);
    $("image").disabled = hasFile;
    $("clear-upload").hidden = !hasFile;
  });
  $("clear-upload").addEventListener("click", () => {
    $("upload").value = "";
    $("image").disabled = false;
    $("clear-upload").hidden = true;
  });
});
