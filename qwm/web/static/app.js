"use strict";
// Interactive controller for PhotoShield (animations, Airplane simulation & Grounded AI Q&A).

const $ = (id) => document.getElementById(id);
const state = {
  session: null,
  mode: "recovery-dual",
  meta: null,
  paintValue: 255,
  imageSize: 256,
  blockRow: 0,
  blockCol: 0,
  airplaneCover: "",
  airplaneWm: "",
  airplaneBlock: null,
};

const MODE_INFO = {
  "recovery-dual": { title: "Auto-Heal (Best)", tag: "best", text: "Catches fake edits + heals damaged parts" },
  "keyed-opt": { title: "Spot Edits Only", tag: "v3", text: "Sharpest look · marks edited boxes in red" },
  opap: { title: "OPAP Base", tag: "v3", text: "High clarity baseline (needs reference)" },
  keyed: { title: "Keyed Blind (2x2)", tag: "v2", text: "Secret-key tamper detection" },
  recovery: { title: "Auto-Heal (4x4)", tag: "v2", text: "Older single-partner healing" },
  lsb: { title: "LSB Replacement", tag: "base", text: "Classic baseline comparison" },
  paper: { title: "Paper Rule (Original)", tag: "base", text: "Exact literal rule from base paper" },
};

const GLOBAL_PARAMS = {
  gaussian_noise: ["sigma", 0.005, 0.3, 0.005, 0.02, "Strength"],
  salt_pepper_noise: ["density", 0.005, 0.3, 0.005, 0.02, "Amount"],
  median_filter: ["kernel", 3, 7, 2, 3, "Size"],
  histogram_equalization: null,
  jpeg_compression: ["quality", 10, 95, 1, 75, "Quality"],
  cropping: ["fraction", 0.05, 0.5, 0.01, 0.2, "Cut size"],
  rotation: ["angle", -45, 45, 1, 5, "Angle"],
  text_addition: null,
};

function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (t.hidden = true), 4500);
}

async function api(path, body) {
  const opts = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
  if (!res.ok || data.error) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

async function busy(button, fn) {
  const html = button ? button.innerHTML : "";
  if (button) {
    button.disabled = true;
    button.textContent = "Working...";
  }
  try {
    await fn();
  } catch (err) {
    toast(err.message);
  } finally {
    if (button) {
      button.disabled = false;
      button.innerHTML = html;
    }
  }
}

const fmt = (v, d = 2) => (v === null || v === undefined ? "-" : !isFinite(v) ? "inf" : Number(v).toFixed(d));
const chip = (label, value) => `<span class="chip"><b>${value}</b>${label}</span>`;

function pulseScan(photoWrapParentId) {
  const wrap = $(photoWrapParentId) && $(photoWrapParentId).querySelector(".photo-wrap");
  if (!wrap) return;
  wrap.classList.remove("is-scanning");
  void wrap.offsetWidth;
  wrap.classList.add("is-scanning");
}

function markStepDone(stepNumber) {
  document.querySelectorAll(".flow-node").forEach((el) => {
    const n = Number(el.dataset.step);
    el.classList.toggle("done", n < stepNumber);
    el.classList.toggle("active", n === stepNumber);
  });
}

function setupScrollReveals() {
  const els = document.querySelectorAll(".reveal");
  if (!("IntersectionObserver" in window)) {
    els.forEach((e) => e.classList.add("visible"));
    return;
  }
  const io = new IntersectionObserver(
    (entries) => {
      entries.forEach((ent) => {
        if (ent.isIntersecting) {
          ent.target.classList.add("visible");
          ent.target.classList.remove("pre-reveal");
          io.unobserve(ent.target);
        }
      });
    },
    { threshold: 0.08 }
  );
  els.forEach((el) => {
    const rect = el.getBoundingClientRect();
    if (rect.top > window.innerHeight * 0.95) el.classList.add("pre-reveal");
    else el.classList.add("visible");
    io.observe(el);
  });
}

function setupHeroWipe() {
  const slider = $("hero-wipe");
  const clip = $("hero-wipe-clip");
  const divider = $("hero-wipe-divider");
  const stage = $("hero-wipe-stage");
  if (!slider || !clip || !divider) return;
  const apply = (pct) => {
    const clamped = Math.max(0, Math.min(100, pct));
    clip.style.clipPath = `inset(0 ${100 - clamped}% 0 0)`;
    divider.style.left = `${clamped}%`;
    slider.value = String(Math.round(clamped));
  };
  slider.addEventListener("input", () => apply(Number(slider.value)));
  if (stage) {
    stage.addEventListener("pointermove", (e) => {
      if (e.buttons !== 1) return;
      const r = stage.getBoundingClientRect();
      apply(((e.clientX - r.left) / r.width) * 100);
    });
  }
}

function syncModeUI(mode) {
  state.mode = mode;
  document.querySelectorAll(".mode").forEach((m) => {
    const inp = m.querySelector("input");
    if (inp) inp.checked = inp.value === mode;
    m.classList.toggle("selected", Boolean(inp && inp.value === mode));
  });
  document.querySelectorAll(".preset-card").forEach((c) => c.classList.toggle("active", c.dataset.preset === mode));
  if ($("keyrow")) $("keyrow").style.display = mode.startsWith("keyed") || mode.startsWith("recovery") ? "" : "none";
}

function renderModes() {
  const box = $("modes");
  if (!box) return;
  box.innerHTML = "";
  for (const [mode, info] of Object.entries(MODE_INFO)) {
    const lab = document.createElement("label");
    lab.className = "mode" + (mode === state.mode ? " selected" : "");
    lab.innerHTML = `<input type="radio" name="mode" value="${mode}" ${mode === state.mode ? "checked" : ""}>
      <span><b>${info.title}<span class="tag">${info.tag}</span></b><small>${info.text}</small></span>`;
    lab.querySelector("input").addEventListener("change", () => syncModeUI(mode));
    box.appendChild(lab);
  }
  document.querySelectorAll(".preset-card").forEach((card) =>
    card.addEventListener("click", () => {
      syncModeUI(card.dataset.preset);
      busy($("embed"), embed);
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
    $("status").textContent = "Server Ready";
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
  $("clf-info").textContent = meta.classifier.ready
    ? "AI Detective ready to guess edit type."
    : "AI Detective warming up in background...";
  if (!meta.classifier.ready) setTimeout(pollClassifier, 2500);
}

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
  $("difference").src = r.difference;
  $("pickbox").hidden = true;

  const chosenName = body.upload ? "upload" : body.image;
  if (!state.airplaneCover || chosenName === "airplane") {
    state.airplaneCover = r.cover;
    state.airplaneWm = r.watermarked;
    if ($("hero-cover")) $("hero-cover").src = r.cover;
    if ($("hero-wm")) $("hero-wm").src = r.watermarked;
  } else if (chosenName !== "airplane") {
    if ($("hero-cover")) $("hero-cover").src = r.cover;
    if ($("hero-wm")) $("hero-wm").src = r.watermarked;
  }

  const m = r.metrics;
  const pct = fmt(m.ssim * 100, 1);
  if ($("hero-match-badge")) $("hero-match-badge").textContent = `${pct}% Visual Match`;
  const lockLabel = state.mode.startsWith("recovery") ? "Locked + Auto-Heal" : "Locked (Spot Only)";
  $("m-ssim-pct").textContent = `${pct}% Identical to Eye · ${lockLabel}`;
  $("embed-metrics").innerHTML =
    chip("PSNR Clarity", `${fmt(m.psnr)} dB`) +
    chip("SSIM Match", fmt(m.ssim, 4)) +
    chip("Speed", `${fmt(m.embed_ms, 1)} ms`);

  pulseScan("wm-card");
  markStepDone(2);

  loadCanvas(r.watermarked);
  $("attacked").src = r.watermarked;
  $("attack-caption").textContent = "Untouched protected photo";
  $("attack-out").hidden = false;
  $("verify-out").hidden = true;
  $("verdict").hidden = true;
  $("verify-note").hidden = false;
  if ($("ai-result-box")) $("ai-result-box").hidden = true;
  if ($("block-out")) $("block-out").hidden = true;
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
    if (!state.session) return toast("Protect a photo first");
    drawing = true;
    last = null;
    c.setPointerCapture(e.pointerId);
    dot(pos(e));
  });
  c.addEventListener("pointermove", (e) => drawing && dot(pos(e)));
  c.addEventListener("pointerup", () => {
    drawing = false;
    last = null;
  });
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
  if (!state.session) throw new Error("Protect a photo first");
  const r = await api("/api/attack", { session: state.session, seed: Math.floor(Math.random() * 1e6), ...body });
  $("attacked").src = r.attacked;
  $("attack-caption").textContent = r.changed_pixels > 0
    ? `Applied "${r.label}" (${r.changed_pixels.toLocaleString()} pixels edited)`
    : "Clean untouched photo";
  $("attack-out").hidden = false;
  if ($("ai-result-box")) $("ai-result-box").hidden = true;
  markStepDone(3);
}

async function verify() {
  if (!state.session) throw new Error("Protect a photo first");
  const r = await api("/api/verify", { session: state.session });
  $("overlay").src = r.overlay;
  $("dl-overlay").href = r.overlay;
  $("verify-out").hidden = false;
  $("verify-note").hidden = true;

  pulseScan("overlay-card");

  const v = $("verdict");
  v.hidden = false;
  const ok = r.verdict === "authentic";
  v.className = "verdict " + (ok ? "ok" : "bad");
  const pct = fmt((100 * r.blocks_failed) / r.blocks_total, 1);

  if (ok) {
    v.innerHTML = `Genuine Photo! Zero fake edits found anywhere.<small>Checked all ${r.blocks_total.toLocaleString()} image blocks.</small>`;
  } else if (r.recovered) {
    v.innerHTML = `Fake Edit Caught in ${pct}% of the photo — ${fmt(100 * r.restored_fraction, 0)}% healed back!<small>Red highlights the edited area; the fixed image beside it was rebuilt from hidden backups.</small>`;
  } else {
    v.innerHTML = `Fake Edit Caught in ${pct}% of the photo (${r.blocks_failed.toLocaleString()} blocks)!<small>Choose "Protect + Auto-Heal" in Step 1 if you also want automatic pixel repair.</small>`;
  }

  const rf = $("recovered-fig");
  if (r.recovered) {
    $("recovered").src = r.recovered;
    $("dl-recovered").href = r.recovered;
    $("recovered-caption").textContent = ok
      ? "Already Clean (No healing needed)"
      : `${fmt(100 * r.restored_fraction, 0)}% Restored Automatically`;
    rf.hidden = false;
    pulseScan("recovered-fig");
  } else {
    rf.hidden = true;
  }
}

async function classify() {
  if (!state.session) throw new Error("Protect a photo first");
  const r = await api("/api/classify", { session: state.session });
  $("clf-info").textContent = r.ready ? "Top AI matches below:" : r.info;
  if (!r.ready) return toast("AI Detective is still warming up — try again in a few seconds");
  $("ai-result-box").hidden = false;
  $("clf-top-pct").textContent = `${fmt(100 * r.confidence, 1)}% match`;
  $("clf-top-lbl").textContent = `AI guess: ${r.predicted}`;
  $("bars").innerHTML = r.probabilities
    .slice(0, 4)
    .map(
      (p, i) => `<div class="bar ${i === 0 ? "best" : ""}"><span>${p.name}</span><div class="track"><div class="fill" style="width:${(100 * p.p).toFixed(1)}%"></div></div><span class="pct">${(100 * p.p).toFixed(1)}%</span></div>`
    )
    .join("");
}

async function inspectBlock(row, col) {
  state.blockRow = row;
  state.blockCol = col;
  const r = await api("/api/block", { session: state.session, row, col });
  $("block-id").textContent = `(${row}, ${col})`;
  const t = r.trace;
  const rows = [
    ["Pixels", r.pixels.join(", ")],
    ["AA = floor(S/4 + 0.5)", `${t.sum} -> ${t.aa}`],
    ["Watermark Wb", t.watermark.join("")],
  ];
  $("block-kv").innerHTML = rows.map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join("");
  $("block-circuits").querySelector("tbody").innerHTML = r.circuits
    .map((c) => `<tr><td>${c.name}</td><td>${c.qubits}</td><td>${c.result}</td></tr>`)
    .join("");
  $("neqr").src = r.neqr;
  $("block-out").hidden = false;
  $("quantum-details").open = true;
  $("block-hint").textContent = `Block (${row}, ${col}) simulated live.`;
}

async function runBlockNisq() {
  if (!state.session) throw new Error("Protect a photo first");
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
    `Worked block [[50,60],[48,32]]: AA=${w.aa}, Wb=${w.watermark.join("")}, inverse exact: ${w.unitary_inverse}. Table 9 violations: ${r.table9_violations}/${r.table9.length}.`;
  $("paper-t9-tbl").querySelector("tbody").innerHTML = r.table9
    .map((x) => `<tr><td>${x.image}</td><td>${x.fidelity}</td><td>${x.trace_distance}</td><td>${x.purity}</td><td><span class="pill-status ${x.consistent ? "ok" : "bad"}">${x.consistent ? "OK" : "Violates"}</span></td></tr>`)
    .join("");
  $("paper-comp-tbl").querySelector("tbody").innerHTML = r.complexity
    .map((x) => `<tr><td>${x.image}</td><td>${x.n}</td><td>${Number(x.FRQI).toLocaleString()}</td><td>${Number(x.NEQR).toLocaleString()}</td></tr>`)
    .join("");
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
  const label = () => ($("theme").textContent = root.dataset.theme === "dark" ? "Light Mode" : "Dark Mode");
  label();
  $("theme").addEventListener("click", () => {
    root.dataset.theme = root.dataset.theme === "dark" ? "light" : "dark";
    label();
    try {
      localStorage.setItem("qwm-theme", root.dataset.theme);
    } catch (_) {
      /* ignore */
    }
  });
}

async function openInsideCinema() {
  const view = $("inside-view");
  const invite = $("inside-invite");
  view.hidden = false;
  if (invite) invite.hidden = true;
  view.scrollIntoView({ behavior: "smooth", block: "start" });
  markStepDone(4);

  if (window.InsideSim) {
    window.InsideSim.open({
      coverUrl: state.airplaneCover || ($("cover") ? $("cover").src : ""),
      wmUrl: state.airplaneWm || ($("watermarked") ? $("watermarked").src : ""),
    });
  }
}

function closeInsideCinema() {
  const view = $("inside-view");
  const invite = $("inside-invite");
  view.hidden = true;
  if (invite) invite.hidden = false;
  if (window.InsideSim) window.InsideSim.close();
}

function setupInsideNav() {
  for (const id of ["show-inside-btn", "nav-inside-btn", "banner-inside-btn"]) {
    if ($(id)) $(id).addEventListener("click", openInsideCinema);
  }
  if ($("back-from-inside")) $("back-from-inside").addEventListener("click", closeInsideCinema);
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

// --------------------------------------------------------------------------- Grounded AI Assistant
function appendMsg(role, title, text, sources = []) {
  const thread = $("ask-messages");
  const wrap = document.createElement("div");
  wrap.className = `qa-msg ${role}`;
  const bubble = document.createElement("div");
  bubble.className = "qa-bubble";

  if (title) {
    const st = document.createElement("strong");
    st.textContent = title;
    bubble.appendChild(st);
  }
  const p = document.createElement("p");
  p.textContent = text;
  bubble.appendChild(p);

  if (sources.length) {
    const srcRow = document.createElement("div");
    srcRow.className = "qa-sources";
    for (const s of sources) {
      const sp = document.createElement("span");
      sp.className = "src-tag";
      sp.textContent = `Source: ${s}`;
      srcRow.appendChild(sp);
    }
    bubble.appendChild(srcRow);
  }

  wrap.appendChild(bubble);
  thread.appendChild(wrap);
  thread.scrollTop = thread.scrollHeight;
  return wrap;
}

async function submitQuestion(qText) {
  const q = (qText || "").trim();
  if (!q) return;
  markStepDone(5);
  appendMsg("user", "", q);
  if ($("ask-input")) $("ask-input").value = "";

  const thread = $("ask-messages");
  const typing = document.createElement("div");
  typing.className = "qa-msg bot";
  typing.innerHTML = `<div class="qa-bubble"><div class="typing-dots"><span></span><span></span><span></span></div></div>`;
  thread.appendChild(typing);
  thread.scrollTop = thread.scrollHeight;

  try {
    const r = await api("/api/ask", { question: q });
    typing.remove();
    appendMsg("bot", r.grounded ? r.title || "Grounded Answer" : "Scope Notice", r.answer, r.sources || []);
  } catch (err) {
    typing.remove();
    appendMsg("bot", "Error", err.message);
  }
}

function setupAssistant() {
  const form = $("ask-form");
  const chips = $("ask-chips");
  if (form) {
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      submitQuestion($("ask-input").value);
    });
  }
  if (chips) {
    chips.addEventListener("click", (e) => {
      const btn = e.target.closest(".qa-chip");
      if (btn && btn.dataset.q) submitQuestion(btn.dataset.q);
    });
  }
}

async function quickTamperAndHeal(attackBody) {
  await attack(attackBody);
  await verify();
}

async function runFullDemo() {
  await embed();
  await attack({ kind: "local", name: "blackout", fraction: 0.2 });
  await verify();
  $("tamper-sec").scrollIntoView({ behavior: "smooth", block: "start" });
}

document.addEventListener("DOMContentLoaded", () => {
  setupTheme();
  setupHeroWipe();
  setupScrollReveals();
  setupInsideNav();
  setupAssistant();
  init();
  setupPaint();

  $("embed").addEventListener("click", (e) => busy(e.target, embed));
  $("image").addEventListener("change", () => {
    document.querySelectorAll(".sample-dot").forEach((b) => b.classList.toggle("active", b.dataset.sample === $("image").value));
    busy($("embed"), embed);
  });
  document.querySelectorAll(".sample-dot").forEach((b) =>
    b.addEventListener("click", () => {
      const name = b.dataset.sample;
      $("upload").value = "";
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
  $("load-paper-tables-btn").addEventListener("click", (e) => busy(e.target, loadPaperSummary));
  $("run-full").addEventListener("click", (e) => busy(e.target, runFullDemo));

  $("upload").addEventListener("change", () => {
    const hasFile = Boolean($("upload").files[0]);
    $("image").disabled = hasFile;
    $("clear-upload").hidden = !hasFile;
    document.querySelectorAll(".sample-dot").forEach((d) => d.classList.toggle("active", !hasFile && d.dataset.sample === $("image").value));
    if (hasFile) busy($("embed"), embed);
  });
  $("clear-upload").addEventListener("click", () => {
    $("upload").value = "";
    $("image").disabled = false;
    $("clear-upload").hidden = true;
    document.querySelectorAll(".sample-dot").forEach((d) => d.classList.toggle("active", d.dataset.sample === $("image").value));
    busy($("embed"), embed);
  });
});
