"use strict";
// Crystal-clear 5-part visual story showing how photo protection & self-healing works.
// Zero raw binary or intimidating math unless the viewer turns on "Quantum Math".

(function () {
  const SCENE_DUR = 5.2;
  const SCENES = [
    {
      title: "1. Tiny Invisible Ink Inside Pixels",
      ref: "Base Paper Sec. 2.1 · NEQR + 2 LSBs",
      summary: "We adjust only the smallest 0.4% of brightness inside tiny picture dots. Human eyes see zero difference, yet the photo can now carry secret safety notes.",
    },
    {
      title: "2. Locking Every Square With a Password",
      ref: "Paper Sec. 3.1–3.2 · RPA, D4, XOR & QE",
      summary: "Each small square gets its own invisible padlock computed from your secret key. If anyone later draws or cuts over a square, its padlock breaks immediately.",
    },
    {
      title: "3. Hiding Spare Backups Across the Photo",
      ref: "Self-Recovery · Dual-Partner Clones",
      summary: "Every part shrinks two tiny spare snapshots of itself and tucks them into completely different corners. Even if a whole wing is erased, distant corners still keep the spare!",
    },
    {
      title: "4. Sweeping Scanner Spots Fake Edits Red",
      ref: "Blind Verify · Grover 15q Radar",
      summary: "A fast scanner checks every padlock across the image. Genuine untouched squares light up green; altered squares glow red so you see the exact fake patch.",
    },
    {
      title: "5. Flying Backups Home to Heal the Photo",
      ref: "Partner Healing · Reversible U† Verification",
      summary: "Those safe spare copies fly back into the damaged hole to reconstruct the missing airplane wing or sky cleanly — bringing the damaged spot right back!",
    },
  ];

  const TOTAL_DUR = SCENES.length * SCENE_DUR;
  const $ = (id) => document.getElementById(id);

  const sim = {
    openFlag: false,
    playing: false,
    paperLabels: false,
    speed: 1.0,
    elapsed: 0,
    lastTs: 0,
    rafId: 0,
    imgObj: null,
    imageName: "airplane",
  };

  const C_BG = "#0e0c0a";
  const C_CARD = "#191613";
  const C_BORDER = "#332c24";
  const C_TEXT = "#f5f2eb";
  const C_MUTED = "#b5ada0";
  const C_GOLD = "#f5b864";
  const C_OK = "#4ade80";
  const C_BAD = "#fb7185";
  const C_SKY = "#7dd3fc";

  const clamp01 = (x) => Math.max(0, Math.min(1, x));
  const ease = (x) => {
    const t = clamp01(x);
    return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
  };
  const lerp = (a, b, t) => a + (b - a) * clamp01(t);

  function rrect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.roundRect(x, y, w, h, r);
  }

  function pill(ctx, x, y, text, bg, fg) {
    ctx.save();
    ctx.font = "600 11.5px 'Inter', sans-serif";
    const w = ctx.measureText(text).width + 20;
    ctx.fillStyle = bg;
    rrect(ctx, x, y, w, 25, 999);
    ctx.fill();
    ctx.fillStyle = fg;
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";
    ctx.fillText(text, x + 10, y + 12.5);
    ctx.restore();
    return w;
  }

  function drawPadlock(ctx, cx, cy, scale, color, locked = true) {
    ctx.save();
    ctx.translate(cx, cy);
    ctx.scale(scale, scale);
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    ctx.lineWidth = 2.4;
    ctx.beginPath();
    if (locked) ctx.arc(0, -6, 6, Math.PI, 0);
    else ctx.arc(3, -8, 6, Math.PI * 1.15, -0.15);
    ctx.stroke();
    rrect(ctx, -9, -4, 18, 14, 3);
    ctx.fill();
    ctx.fillStyle = "#0e0c0a";
    ctx.beginPath();
    ctx.arc(0, 3, 2.2, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  }

  function drawOrb(ctx, x, y, color, r = 6.5) {
    ctx.save();
    ctx.fillStyle = color;
    ctx.shadowColor = color;
    ctx.shadowBlur = 14;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  }

  function drawPhoto(ctx, x, y, size, radius = 12) {
    ctx.save();
    rrect(ctx, x, y, size, size, radius);
    ctx.clip();
    if (sim.imgObj && sim.imgObj.complete) {
      ctx.drawImage(sim.imgObj, x, y, size, size);
    } else {
      ctx.fillStyle = "#26211c";
      ctx.fillRect(x, y, size, size);
    }
    ctx.restore();
  }

  function drawHeader(ctx, W, idx, sceneP) {
    const sc = SCENES[idx];
    const tag = sim.paperLabels ? `PART ${idx + 1}/5  ·  ${sc.ref}` : `STEP ${idx + 1} OF 5  ·  EASY VISUAL GUIDE`;
    ctx.fillStyle = C_GOLD;
    ctx.font = "700 11px 'JetBrains Mono', monospace";
    ctx.textAlign = "left";
    ctx.fillText(tag, 36, 34);

    ctx.fillStyle = "#ffffff";
    ctx.font = "700 23px 'Inter', sans-serif";
    ctx.fillText(sc.title, 36, 64);

    ctx.fillStyle = C_MUTED;
    ctx.font = "500 12px 'Inter', sans-serif";
    ctx.textAlign = "right";
    ctx.fillText(`Active Photo: ${sim.imageName}`, W - 36, 34);

    ctx.strokeStyle = "#2a241d";
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(36, 82);
    ctx.lineTo(W - 36, 82);
    ctx.stroke();

    ctx.strokeStyle = C_GOLD;
    ctx.beginPath();
    ctx.moveTo(36, 82);
    ctx.lineTo(36 + (W - 72) * sceneP, 82);
    ctx.stroke();
  }

  // ----------------------------------------------------------- PART 1: Side-by-side Same Look + Invisible 0.4% Mark
  function drawScene1(ctx, W, H, p) {
    const px = 44, py = 114, ps = 250;
    drawPhoto(ctx, px, py, ps);
    ctx.strokeStyle = C_BORDER;
    ctx.lineWidth = 1.5;
    rrect(ctx, px, py, ps, ps, 12);
    ctx.stroke();

    const focus = ease(clamp01(p * 1.8));
    const rx = px + 92, ry = py + 84, rs = 44;
    ctx.strokeStyle = C_GOLD;
    ctx.lineWidth = 2.5;
    rrect(ctx, rx, ry, rs, rs, 6);
    ctx.stroke();
    pill(ctx, px + 10, py + 10, "Your Photo", "rgba(14,12,10,0.78)", "#fff");

    // Zoomed smooth patch + clear Before vs After eye test card
    const cx = 340, cy = 114, cw = 576, ch = 280;
    ctx.fillStyle = C_CARD;
    ctx.strokeStyle = C_BORDER;
    rrect(ctx, cx, cy, cw, ch, 14);
    ctx.stroke();
    ctx.fill();

    ctx.fillStyle = "#ffffff";
    ctx.font = "600 16px 'Inter', sans-serif";
    ctx.textAlign = "left";
    ctx.fillText("Why can't human eyes see the hidden lock?", cx + 26, cy + 38);
    ctx.fillStyle = C_MUTED;
    ctx.font = "400 13px 'Inter', sans-serif";
    ctx.fillText("We nudge a tiny dot's shade by less than 1% — invisible to your eye, readable by computer.", cx + 26, cy + 62);

    // Left swatch: Original brightness
    const sw1x = cx + 30, sw2x = cx + 310, swy = cy + 92, sww = 230, swh = 110;
    ctx.fillStyle = "rgb(148,148,148)";
    rrect(ctx, sw1x, swy, sww, swh, 12);
    ctx.fill();
    ctx.fillStyle = "#141413";
    ctx.font = "700 14px 'Inter', sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("Before: Normal Dot", sw1x + sww / 2, swy + 48);
    ctx.font = "500 12px 'Inter', sans-serif";
    ctx.fillText("Plain shade (100%)", sw1x + sww / 2, swy + 70);

    // Arrow
    ctx.fillStyle = C_GOLD;
    ctx.font = "700 22px 'Inter', sans-serif";
    ctx.fillText("→", cx + 285, swy + 58);

    // Right swatch: +1% hidden ink (looks identical!)
    const afterShade = Math.round(lerp(148, 149, focus));
    ctx.fillStyle = `rgb(${afterShade},${afterShade},${afterShade})`;
    ctx.strokeStyle = focus > 0.5 ? C_OK : C_BORDER;
    ctx.lineWidth = 2.5;
    rrect(ctx, sw2x, swy, sww, swh, 12);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = "#141413";
    ctx.font = "700 14px 'Inter', sans-serif";
    ctx.fillText("After: With Secret Ink", sw2x + sww / 2, swy + 48);
    ctx.font = "500 12px 'Inter', sans-serif";
    ctx.fillText("99.6% same shade to eye ✓", sw2x + sww / 2, swy + 70);

    ctx.textAlign = "left";
    pill(
      ctx,
      cx + 30,
      cy + 224,
      sim.paperLabels ? "Uses last 2 LSBs of 8-bit NEQR pixels" : "Result: Two colors look 100% identical to people, yet carry hidden data!",
      "#231f1a",
      C_GOLD
    );
  }

  // ----------------------------------------------------------- PART 2: Secret Padlocks Stamped on Every Tile
  function drawScene2(ctx, W, H, p) {
    const gx = 48, gy = 114, gs = 266;
    drawPhoto(ctx, gx, gy, gs);
    ctx.fillStyle = "rgba(12,10,8,0.28)";
    ctx.fillRect(gx, gy, gs, gs);

    const step = gs / 4;
    const stamped = Math.floor(ease(p) * 16);
    for (let r = 0; r < 4; r++) {
      for (let c = 0; c < 4; c++) {
        const idx = r * 4 + c;
        const tx = gx + c * step, ty = gy + r * step;
        ctx.strokeStyle = idx <= stamped ? "rgba(245,184,100,0.7)" : "rgba(255,255,255,0.2)";
        ctx.lineWidth = 1.3;
        ctx.strokeRect(tx, ty, step, step);
        if (idx <= stamped) {
          drawPadlock(ctx, tx + step / 2, ty + step / 2 + 2, 0.72, C_GOLD, true);
        }
      }
    }
    rrect(ctx, gx, gy, gs, gs, 12);
    ctx.strokeStyle = C_GOLD;
    ctx.lineWidth = 2;
    ctx.stroke();

    // Right cards explaining Locked vs Tampered
    const rx = 360, rw = 556;
    ctx.fillStyle = C_CARD;
    ctx.strokeStyle = C_BORDER;
    rrect(ctx, rx, 114, rw, 130, 14);
    ctx.fill();
    ctx.stroke();
    drawPadlock(ctx, rx + 42, 178, 1.3, C_OK, true);
    ctx.fillStyle = C_OK;
    ctx.font = "700 15px 'Inter', sans-serif";
    ctx.textAlign = "left";
    ctx.fillText("Every square gets a unique invisible lock", rx + 78, 160);
    ctx.fillStyle = C_MUTED;
    ctx.font = "400 13px 'Inter', sans-serif";
    ctx.fillText("Locked using the square's own texture + your secret password.", rx + 78, 184);
    if (sim.paperLabels) ctx.fillText("RPA + D4 + CNOT computes PPB ⊕ AA MAC tags.", rx + 78, 206);

    ctx.fillStyle = C_CARD;
    ctx.strokeStyle = p > 0.45 ? C_BAD : C_BORDER;
    rrect(ctx, rx, 260, rw, 130, 14);
    ctx.fill();
    ctx.stroke();
    drawPadlock(ctx, rx + 42, 324, 1.3, C_BAD, false);
    ctx.fillStyle = C_BAD;
    ctx.font = "700 15px 'Inter', sans-serif";
    ctx.fillText("If anyone edits or pastes here later — lock snaps open!", rx + 78, 306);
    ctx.fillStyle = C_MUTED;
    ctx.font = "400 13px 'Inter', sans-serif";
    ctx.fillText("Even a clever Photoshop patch can't fake a secret key it doesn't know.", rx + 78, 330);
  }

  // ----------------------------------------------------------- PART 3: Hiding Two Backup Stickers Elsewhere
  function drawScene3(ctx, W, H, p) {
    const gx = 48, gy = 114, gs = 290;
    drawPhoto(ctx, gx, gy, gs);
    ctx.fillStyle = "rgba(11,10,8,0.34)";
    ctx.fillRect(gx, gy, gs, gs);

    const step = gs / 8;
    ctx.strokeStyle = "rgba(255,255,255,0.22)";
    ctx.lineWidth = 1;
    for (let i = 1; i < 8; i++) {
      ctx.beginPath();
      ctx.moveTo(gx + i * step, gy);
      ctx.lineTo(gx + i * step, gy + gs);
      ctx.moveTo(gx, gy + i * step);
      ctx.lineTo(gx + gs, gy + i * step);
      ctx.stroke();
    }

    const sx = gx + 2.5 * step, sy = gy + 3.5 * step;
    const p1x = gx + 6.5 * step, p1y = gy + 1.5 * step;
    const p2x = gx + 5.5 * step, p2y = gy + 6.5 * step;

    ctx.fillStyle = "rgba(245,184,100,0.45)";
    ctx.strokeStyle = C_GOLD;
    ctx.lineWidth = 2.5;
    ctx.fillRect(sx - step / 2, sy - step / 2, step, step);
    ctx.strokeRect(sx - step / 2, sy - step / 2, step, step);

    const a1 = ease(clamp01((p - 0.1) * 1.9));
    const a2 = ease(clamp01((p - 0.32) * 1.9));

    function arcCopy(x1, y1, cx, cy, x2, y2, prog, col, tag) {
      ctx.save();
      ctx.strokeStyle = col;
      ctx.lineWidth = 2.5;
      ctx.beginPath();
      ctx.moveTo(x1, y1);
      ctx.quadraticCurveTo(cx, cy, x2, y2);
      ctx.stroke();
      const t = prog;
      const bx = (1 - t) * (1 - t) * x1 + 2 * (1 - t) * t * cx + t * t * x2;
      const by = (1 - t) * (1 - t) * y1 + 2 * (1 - t) * t * cy + t * t * y2;
      if (prog > 0.02 && prog < 0.98) drawOrb(ctx, bx, by, col, 6.5);
      if (prog > 0.78) {
        ctx.fillStyle = col;
        rrect(ctx, x2 - step / 2 - 4, y2 - step / 2, step + 8, step, 6);
        ctx.fill();
        ctx.fillStyle = "#0e0c0a";
        ctx.font = "700 10px 'Inter', sans-serif";
        ctx.textAlign = "center";
        ctx.fillText(tag, x2, y2 + 4);
      }
      ctx.restore();
    }

    arcCopy(sx, sy, gx + 4.5 * step, gy + 0.4 * step, p1x, p1y, a1, C_GOLD, "Copy 1");
    arcCopy(sx, sy, gx + 4.2 * step, gy + 6.4 * step, p2x, p2y, a2, C_SKY, "Copy 2");

    // Simple everyday house-key analogy on right
    const rx = 380, rw = 536;
    const boxes = [
      { title: "Spare Key Trick (Why Copies Go Elsewhere)", text: "If an attacker erases the wing here, they also erase whatever was saved inside the wing.", col: C_GOLD },
      { title: "Backup Copy 1 tucked into top sky corner", text: "A shrunk summary of the wing hides invisibly inside a far corner.", col: C_OK },
      { title: "Backup Copy 2 tucked into opposite corner", text: "Even if a huge chunk is cut out, another spare backup still survives!", col: C_SKY },
    ];
    boxes.forEach((b, k) => {
      const y = 114 + k * 98;
      ctx.fillStyle = C_CARD;
      ctx.strokeStyle = p > k * 0.25 ? b.col : C_BORDER;
      ctx.lineWidth = 1.5;
      rrect(ctx, rx, y, rw, 84, 12);
      ctx.fill();
      ctx.stroke();
      ctx.fillStyle = b.col;
      ctx.font = "700 14.5px 'Inter', sans-serif";
      ctx.textAlign = "left";
      ctx.fillText(b.title, rx + 20, y + 30);
      ctx.fillStyle = C_MUTED;
      ctx.font = "400 13px 'Inter', sans-serif";
      ctx.fillText(b.text, rx + 20, y + 56);
    });
  }

  // ----------------------------------------------------------- PART 4: Scanning Check Spots Fake Box
  function drawScene4(ctx, W, H, p) {
    const gx = 48, gy = 114, gs = 290;
    const cutP = ease(clamp01(p * 3.0));
    const scanP = clamp01((p - 0.2) / 0.7);
    const dx = gx + 76, dy = gy + 82, ds = 114;

    ctx.save();
    rrect(ctx, gx, gy, gs, gs, 12);
    ctx.clip();
    drawPhoto(ctx, gx, gy, gs, 0);
    if (cutP > 0.02) {
      ctx.fillStyle = `rgba(12,10,8,${0.95 * cutP})`;
      ctx.fillRect(dx, dy, ds, ds);
    }
    if (p > 0.2) {
      const sy = gy + gs * scanP;
      ctx.strokeStyle = C_GOLD;
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.moveTo(gx, sy);
      ctx.lineTo(gx + gs, sy);
      ctx.stroke();
      if (sy > dy) {
        ctx.fillStyle = "rgba(251, 113, 133, 0.28)";
        ctx.fillRect(dx, dy, ds, Math.min(ds, sy - dy));
        ctx.strokeStyle = C_BAD;
        ctx.lineWidth = 3;
        ctx.strokeRect(dx, dy, ds, ds);
      }
    }
    ctx.restore();

    rrect(ctx, gx, gy, gs, gs, 12);
    ctx.strokeStyle = scanP > 0.5 ? C_BAD : C_BORDER;
    ctx.lineWidth = 1.6;
    ctx.stroke();

    // Right: Friendly Safe vs Damaged visual result
    const rx = 380, rw = 536;
    ctx.fillStyle = C_CARD;
    ctx.strokeStyle = C_BORDER;
    rrect(ctx, rx, 114, rw, 290, 14);
    ctx.fill();
    ctx.stroke();

    ctx.fillStyle = "#ffffff";
    ctx.font = "700 16px 'Inter', sans-serif";
    ctx.textAlign = "left";
    ctx.fillText("How the app tells real areas from fake edits", rx + 24, 152);

    // Clean vs Broken boxes
    ctx.fillStyle = "rgba(74, 222, 128, 0.12)";
    ctx.strokeStyle = C_OK;
    rrect(ctx, rx + 24, 180, 232, 140, 12);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = C_OK;
    ctx.font = "700 28px 'Inter', sans-serif";
    ctx.fillText("✓ Safe", rx + 42, 226);
    ctx.fillStyle = C_TEXT;
    ctx.font = "600 13.5px 'Inter', sans-serif";
    ctx.fillText("95% untouched sky & body", rx + 42, 258);
    ctx.fillStyle = C_MUTED;
    ctx.font = "400 12.5px 'Inter', sans-serif";
    ctx.fillText("Padlocks match perfectly.", rx + 42, 282);

    ctx.fillStyle = "rgba(251, 113, 133, 0.14)";
    ctx.strokeStyle = scanP > 0.45 ? C_BAD : C_BORDER;
    rrect(ctx, rx + 276, 180, 236, 140, 12);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = C_BAD;
    ctx.font = "700 28px 'Inter', sans-serif";
    ctx.fillText("✕ Altered!", rx + 294, 226);
    ctx.fillStyle = C_TEXT;
    ctx.font = "600 13.5px 'Inter', sans-serif";
    ctx.fillText("5% cut-out rectangle", rx + 294, 258);
    ctx.fillStyle = C_MUTED;
    ctx.font = "400 12.5px 'Inter', sans-serif";
    ctx.fillText("Painted red immediately!", rx + 294, 282);

    ctx.fillStyle = C_GOLD;
    ctx.font = "500 12.5px 'Inter', sans-serif";
    ctx.fillText(
      sim.paperLabels ? "15-qubit Grover search highlights mismatched locks" : "You see exact red highlights right where someone tampered.",
      rx + 24,
      368
    );
  }

  // ----------------------------------------------------------- PART 5: Rescue Backups Fly Back & Heal
  function drawScene5(ctx, W, H, p) {
    const gx = 48, gy = 114, gs = 290;
    const dx = gx + 76, dy = gy + 82, ds = 114;
    const healP = ease(clamp01((p - 0.14) / 0.65));

    ctx.save();
    rrect(ctx, gx, gy, gs, gs, 12);
    ctx.clip();
    drawPhoto(ctx, gx, gy, gs, 0);
    if (1 - healP > 0.01) {
      ctx.fillStyle = `rgba(12,10,8,${1 - healP})`;
      ctx.fillRect(dx, dy, ds, ds);
      ctx.strokeStyle = `rgba(74,222,128,${Math.sin(healP * Math.PI)})`;
      ctx.lineWidth = 3;
      ctx.strokeRect(dx, dy, ds, ds);
    }
    ctx.restore();

    rrect(ctx, gx, gy, gs, gs, 12);
    ctx.strokeStyle = healP > 0.85 ? C_OK : C_GOLD;
    ctx.lineWidth = 2;
    ctx.stroke();

    if (healP > 0.02 && healP < 0.96) {
      drawOrb(ctx, lerp(gx + 244, dx + ds / 2, healP), lerp(gy + 40, dy + ds / 2, healP), C_OK, 7.5);
      drawOrb(ctx, lerp(gx + 215, dx + ds / 2, healP), lerp(gy + 246, dy + ds / 2, healP), C_GOLD, 7.5);
    }

    ctx.fillStyle = healP > 0.85 ? C_OK : C_GOLD;
    ctx.font = "700 13.5px 'Inter', sans-serif";
    ctx.textAlign = "left";
    ctx.fillText(healP > 0.85 ? `✓ ${Math.round(healP * 100)}% Healed & Restored!` : "Copying Spare Backups Back Into the Hole...", gx, gy + gs + 28);

    const rx = 380, rw = 536;
    ctx.fillStyle = C_CARD;
    ctx.strokeStyle = healP > 0.85 ? C_OK : C_BORDER;
    rrect(ctx, rx, 114, rw, 290, 14);
    ctx.fill();
    ctx.stroke();

    ctx.fillStyle = C_GOLD;
    ctx.font = "700 12px 'Inter', sans-serif";
    ctx.fillText("DONE AUTOMATICALLY IN MILLISECONDS", rx + 24, 150);

    const steps = [
      { t: "1. Spotted broken padlocks", d: "Found only the tampered box without touching clean sky.", col: C_OK },
      { t: "2. Fetched spare backups", d: "Read hidden wing & fuselage details from safe corners.", col: C_GOLD },
      { t: "3. Rebuilt missing pixels", d: "Painted back the real picture so you keep the full photo.", col: C_SKY },
    ];
    steps.forEach((s, i) => {
      const y = 186 + i * 70;
      ctx.fillStyle = s.col;
      ctx.font = "700 16px 'Inter', sans-serif";
      ctx.fillText("✓", rx + 24, y);
      ctx.fillStyle = "#ffffff";
      ctx.font = "600 14px 'Inter', sans-serif";
      ctx.fillText(s.t, rx + 50, y);
      ctx.fillStyle = C_MUTED;
      ctx.font = "400 13px 'Inter', sans-serif";
      ctx.fillText(s.d, rx + 50, y + 22);
    });
  }

  function renderFrame() {
    const canvas = $("inside-canvas");
    if (!canvas) return;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const W = 960, H = 480;
    if (canvas.width !== W * dpr || canvas.height !== H * dpr) {
      canvas.width = W * dpr;
      canvas.height = H * dpr;
    }
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    ctx.fillStyle = C_BG;
    ctx.fillRect(0, 0, W, H);

    const safeElapsed = Number.isFinite(sim.elapsed) ? Math.max(0, Math.min(TOTAL_DUR - 0.001, sim.elapsed)) : 0;
    sim.elapsed = safeElapsed;
    const idx = Math.max(0, Math.min(SCENES.length - 1, Math.floor(safeElapsed / SCENE_DUR)));
    const localP = clamp01((safeElapsed - idx * SCENE_DUR) / SCENE_DUR);

    drawHeader(ctx, W, idx, localP);
    if (idx === 0) drawScene1(ctx, W, H, localP);
    else if (idx === 1) drawScene2(ctx, W, H, localP);
    else if (idx === 2) drawScene3(ctx, W, H, localP);
    else if (idx === 3) drawScene4(ctx, W, H, localP);
    else drawScene5(ctx, W, H, localP);

    updateTransportUI(idx);
  }

  function updateTransportUI(idx) {
    const playBtn = $("inside-play");
    if (playBtn) playBtn.innerHTML = sim.playing ? "&#10074;&#10074; Pause" : "&#9654; Play";
    const clk = $("inside-clock");
    if (clk) clk.textContent = `Part ${idx + 1} / ${SCENES.length} · ${sim.elapsed.toFixed(1)}s / ${TOTAL_DUR.toFixed(0)}s`;
    const pct = clamp01(sim.elapsed / TOTAL_DUR) * 100;
    const fill = $("inside-scrub-fill");
    if (fill) fill.style.width = `${pct}%`;
    const scrub = $("inside-scrub");
    if (scrub) scrub.setAttribute("aria-valuenow", String(Math.round(pct)));
    const sc = SCENES[idx] || SCENES[0];
    const capTitle = $("inside-cap-title");
    const capText = $("inside-cap-text");
    if (capTitle) capTitle.textContent = sim.paperLabels ? `${sc.title} (${sc.ref})` : sc.title;
    if (capText) capText.textContent = sc.summary;
    document.querySelectorAll(".inside-chap").forEach((el, k) => el.classList.toggle("active", k === idx));
  }

  function tick(ts) {
    if (!sim.openFlag) return;
    if (sim.lastTs) {
      const dt = Math.max(0, Math.min(0.1, (ts - sim.lastTs) / 1000));
      if (sim.playing) {
        sim.elapsed += dt * sim.speed;
        if (sim.elapsed >= TOTAL_DUR) {
          sim.elapsed = TOTAL_DUR - 0.001;
          sim.playing = false;
        }
      }
    }
    sim.lastTs = ts;
    renderFrame();
    if (sim.playing) sim.rafId = requestAnimationFrame(tick);
  }

  function ensureLoop() {
    cancelAnimationFrame(sim.rafId);
    sim.lastTs = performance.now();
    renderFrame();
    if (sim.playing && sim.openFlag) sim.rafId = requestAnimationFrame(tick);
  }

  function buildChapters() {
    const box = $("inside-chapters");
    if (!box || box.children.length) return;
    SCENES.forEach((sc, idx) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "inside-chap" + (idx === 0 ? " active" : "");
      b.textContent = sc.title;
      b.addEventListener("click", () => window.InsideSim.goScene(idx));
      box.appendChild(b);
    });
  }

  window.InsideSim = {
    open(ctxData) {
      buildChapters();
      if (ctxData) {
        if (ctxData.imageName) sim.imageName = ctxData.imageName;
        if (ctxData.coverUrl) {
          const im = new Image();
          im.onload = () => {
            sim.imgObj = im;
            renderFrame();
          };
          im.src = ctxData.coverUrl;
        }
      }
      sim.openFlag = true;
      sim.elapsed = 0;
      sim.playing = true;
      ensureLoop();
    },
    close() {
      sim.openFlag = false;
      sim.playing = false;
      cancelAnimationFrame(sim.rafId);
    },
    togglePlay() {
      if (!sim.playing && sim.elapsed >= TOTAL_DUR - 0.02) sim.elapsed = 0;
      sim.playing = !sim.playing;
      ensureLoop();
    },
    replay() {
      sim.elapsed = 0;
      sim.playing = true;
      ensureLoop();
    },
    goScene(idx) {
      const i = Math.max(0, Math.min(SCENES.length - 1, idx));
      sim.elapsed = i * SCENE_DUR + 0.05;
      sim.playing = true;
      ensureLoop();
    },
    prev() {
      const cur = Math.floor(sim.elapsed / SCENE_DUR);
      this.goScene(Math.max(0, cur - 1));
    },
    next() {
      const cur = Math.floor(sim.elapsed / SCENE_DUR);
      this.goScene(Math.min(SCENES.length - 1, cur + 1));
    },
    cycleSpeed() {
      const next = sim.speed === 1 ? 1.5 : sim.speed === 1.5 ? 0.5 : 1;
      sim.speed = next;
      const btn = $("inside-speed");
      if (btn) btn.textContent = `${next}×`;
    },
    togglePaperLabels() {
      sim.paperLabels = !sim.paperLabels;
      const btn = $("inside-labels");
      if (btn) btn.textContent = sim.paperLabels ? "Quantum Math: On" : "Quantum Math: Off";
      renderFrame();
    },
    scrubRatio(r) {
      const safeR = Number.isFinite(r) ? r : 0;
      sim.elapsed = clamp01(safeR) * (TOTAL_DUR - 0.01);
      ensureLoop();
    },
  };
})();
