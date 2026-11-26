"use strict";
// NEQR quantum watermarking - interactive demo front-end (no dependencies).

const $ = (id) => document.getElementById(id);
const state = { session: null, mode: "keyed-opt", meta: null, paintValue: 255, imageSize: 256, blockRow: 0, blockCol: 0 };

const MODE_INFO = {
  paper: { title: "Base: literal rule", tag: "base", text: "RPA → XOR → QE → Pauli-X exactly as written in the paper." },
  lsb: { title: "Base: LSB replacement", tag: "base", text: "Content code PPB ⊕ AA in the two LSBs; checking it needs the stored reference bits." },
  opap: { title: "Base v3: OPAP", tag: "v3", text: "Optimal Pixel Adjustment Process shifts ±4 MSBs where valid, boosting PSNR from ~44.1 to ~46.4 dB." },
  keyed: { title: "Keyed blind authentication", tag: "v2", text: "Content code ⊕ keyed one-time MAC. Verify with the key alone; 2×2 localisation." },
  "keyed-opt": { title: "Keyed blind authentication (optimal)", tag: "v3", text: "81-coset MSB search per 2×2 block: ~46.4 dB PSNR with 100% unchanged blind receiver verification." },
  recovery: { title: "Keyed self-recovery (4×4)", tag: "v2", text: "Blocks carry a partner's AA recovery code + a 12-bit MAC: detect and repair." },
  "recovery-dual": { title: "Dual-partner Haar recovery (8×8)", tag: "v3", text: "68-bit primary + 44-bit secondary companded Haar codes + 16-bit MAC (2^-16 forgery, >97% code recovery)." },
};

// main slider of every global attack: [param, min, max, step, default, label]
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
  const label = button.textContent;
  button.disabled = true;
  button.textContent = "working…";
  try {
    await fn();
  } catch (err) {
    toast(err.message);
  } finally {
    button.disabled = false;
    button.textContent = label;
  }
}

const fmt = (v, d = 2) => (v === null || v === undefined ? "–" : !isFinite(v) ? "∞" : Number(v).toFixed(d));
const chip = (label, value) => `<span class="chip"><b>${value}</b>${label}</span>`;

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
    $("status").textContent = "Connected · every result is computed live on this machine";
    pollClassifier();
    await embed(); // start populated: the hero shows the freshly watermarked image
  } catch (err) {
    $("status").textContent = "server not reachable";
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
  $("embed-metrics").innerHTML =
    chip("PSNR", `${fmt(m.psnr)} dB`) + chip("SSIM", fmt(m.ssim, 4)) + chip("payload", `${m.bpp} bpp`) +
    chip("side information", m.side_information_bits ? `${m.side_information_bits.toLocaleString()} bits` : "key only") +
    chip("embed", `${fmt(m.embed_ms, 1)} ms`);
  loadCanvas(r.watermarked);
  // reset downstream panels
  $("attacked").src = r.watermarked;
  $("attack-caption").textContent = "untouched watermarked image";
  $("attack-out").hidden = false;
  for (const id of ["verify-out", "verdict"]) $(id).hidden = true;
  $("verify-note").textContent = "";
  $("bars").innerHTML = "";
  $("block-out").hidden = true;
}

// pick a block on the cover
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
    if (!state.session) return toast("embed an image first");
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
  if (!state.session) throw new Error("embed an image first");
  const r = await api("/api/attack", { session: state.session, seed: Math.floor(Math.random() * 1e6), ...body });
  $("attacked").src = r.attacked;
  $("attack-caption").textContent = `${r.label} · PSNR vs cover ${fmt(r.psnr)} dB · ${r.changed_pixels.toLocaleString()} pixels changed`;
  $("attack-out").hidden = false;
  for (const id of ["verify-out", "verdict"]) $(id).hidden = true;
  $("verify-note").textContent = "";
  $("bars").innerHTML = "";
}

// --------------------------------------------------------------------------- steps 3-5
async function verify() {
  if (!state.session) throw new Error("embed an image first");
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
    : `Tampered — ${r.blocks_failed.toLocaleString()} of ${r.blocks_total.toLocaleString()} ${r.block_size}×${r.block_size} blocks failed (${fmt(pct)} %)`;
  if (r.ber !== undefined) v.innerHTML += `<small>bit error rate vs reference bits: ${fmt(r.ber, 4)}</small>`;
  const rf = $("recovered-fig");
  if (r.recovered) {
    $("recovered").src = r.recovered;
    $("dl-recovered").href = r.recovered;
    $("recovered-caption").textContent = `repaired · PSNR ${fmt(r.psnr_attacked)} → ${fmt(r.psnr_recovered)} dB · ${fmt(100 * r.restored_fraction, 0)} % rebuilt from codes`;
    rf.hidden = false;
  } else rf.hidden = true;
  $("verify-note").textContent = r.note || "";
}

async function classify() {
  if (!state.session) throw new Error("embed an image first");
  const r = await api("/api/classify", { session: state.session });
  $("clf-info").textContent = r.info;
  if (!r.ready) return toast("the classifier is still training, try again in a few seconds");
  const oodNote = r.is_unknown
    ? ` · <b>FLAGGED UNKNOWN / OOD</b> (confidence ${fmt(100 * r.confidence, 1)}% &lt; threshold ${fmt(100 * r.threshold, 1)}%)`
    : ` · confidence ${fmt(100 * r.confidence, 1)}% (threshold ${fmt(100 * r.threshold, 1)}%)`;
  $("bars").innerHTML = r.probabilities
    .map(
      (p, i) => `<div class="bar ${i === 0 ? "best" : ""}"><span>${p.name}</span><div class="track"><div class="fill" style="width:${(100 * p.p).toFixed(1)}%"></div></div><span class="pct">${(100 * p.p).toFixed(1)}%</span></div>`
    )
    .join("") + `<p class="hint">applied: <b>${r.actual}</b> · predicted: <b>${r.predicted}</b>${oodNote}</p>`;
}

async function inspectBlock(row, col) {
  state.blockRow = row;
  state.blockCol = col;
  const r = await api("/api/block", { session: state.session, row, col });
  $("block-id").textContent = `(${row}, ${col})`;
  const t = r.trace;
  const rows = [
    ["pixels C00 C01 C10 C11", r.pixels.join(", ")],
    ["binary", r.binary.join(" ")],
    ["pixel position bits", t.ppb.map((p) => p.join("")).join(" ")],
    ["sum → AA = ⌊S/4 + 0.5⌋", `${t.sum} → ${t.aa}`],
    ["watermark Wb0…Wb7", t.watermark.join("")],
  ];
  $("block-kv").innerHTML = rows.map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join("");
  $("block-circuits").querySelector("tbody").innerHTML = r.circuits
    .map((c) => `<tr><td>${c.name}</td><td>${c.qubits}</td><td>${c.result}</td></tr>`)
    .join("");
  $("neqr").src = r.neqr;
  $("block-out").hidden = false;
  $("nisq-tbl").hidden = true;
  $("block-hint").textContent = `Simulated exactly in ${fmt(Object.values(r.timings_ms).reduce((a, b) => a + b, 0), 0)} ms. Click another block to compare.`;
}

async function runBlockNisq() {
  if (!state.session) throw new Error("embed an image first");
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
}

// --------------------------------------------------------------------------- look and feel
function setHero(src) {
  const img = $("hero-img");
  img.classList.remove("ready");
  img.onload = () => setTimeout(() => img.classList.add("ready"), 30);
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
  if (saved === "light" || saved === "dark") root.dataset.theme = saved;
  $("theme").addEventListener("click", () => {
    const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    try {
      localStorage.setItem("qwm-theme", root.dataset.theme);
    } catch (_) {
      /* private mode: the choice just is not remembered */
    }
  });
}

function setupMotion() {
  const items = document.querySelectorAll(".chapter-head, .chapter-body, .metrics div");
  // no entrance animation when the page loads in a background tab (observers may never fire)
  const animate = document.visibilityState === "visible" && "IntersectionObserver" in window && !matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (!animate) return setupSpy();
  items.forEach((el, i) => {
    el.classList.add("reveal");
    el.style.transitionDelay = `${(i % 5) * 60}ms`;
  });
  const io = new IntersectionObserver(
    (entries) => entries.forEach((e) => e.isIntersecting && (e.target.classList.add("in"), io.unobserve(e.target))),
    { threshold: 0.12 }
  );
  items.forEach((el) => io.observe(el));
  setupSpy();
}

function setupSpy() {
  const links = [...document.querySelectorAll(".rail-nav a")];
  const spy = new IntersectionObserver(
    (entries) => {
      for (const e of entries) {
        if (!e.isIntersecting) continue;
        links.forEach((a) => a.classList.toggle("active", a.getAttribute("href") === `#${e.target.id}`));
      }
    },
    { rootMargin: "-45% 0px -50% 0px" }
  );
  document.querySelectorAll(".chapter").forEach((c) => spy.observe(c));

  const visual = document.querySelector(".hero-visual");
  if (!matchMedia("(prefers-reduced-motion: reduce)").matches) {
    addEventListener("scroll", () => visual.style.setProperty("--parallax", `${Math.min(scrollY, 900) * 0.18}px`), { passive: true });
  }
}

// --------------------------------------------------------------------------- wiring
document.addEventListener("DOMContentLoaded", () => {
  setupTheme();
  setupMotion();
  init();
  setupPaint();
  $("embed").addEventListener("click", (e) => busy(e.target, embed));
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
  $("upload").addEventListener("change", () => $("upload").files[0] && ($("image").disabled = true));
});
