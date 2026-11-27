"use strict";
// Easy-to-understand 5-scene animated visual story showing how the photo protection & auto-healing works.

(function () {
  const SCENE_DUR = 5.4;
  const SCENES = [
    {
      title: "1. Breaking the Photo Into Tiny Squares",
      ref: "Paper Sec. 2.1 · NEQR",
      summary: "Every picture is a grid of tiny brightness squares. Adjusting the last 2 tiny brightness levels inside a square is completely invisible to human eyes—so we store secret safety clues there.",
    },
    {
      title: "2. Locking Each Square With an Invisible Fingerprint",
      ref: "Paper Sec. 3.1–3.2 · RPA, D4, XOR & QE",
      summary: "The app reads each 2×2 block's average brightness and pattern, creates a unique secret lock tag with your key, and hides it inside those invisible slots while keeping 98.4% visual match.",
    },
    {
      title: "3. Hiding Backup Clones Across the Image",
      ref: "v2 & v3 · Dual-Partner 8×8 Shards",
      summary: "Before finishing, every tile shrinks a backup snapshot of itself and hides two copies in faraway corners of your photo. If one area gets deleted, its clones elsewhere survive!",
    },
    {
      title: "4. Spotting Any Cut, Paint, or Fake Edit",
      ref: "Sec. 3.3 · Blind Verify + 15q Grover Search",
      summary: "If someone cuts out an object or edits the photo, a fast quantum scanner checks every tile's lock. Untouched areas stay green; altered areas glow red right away.",
    },
    {
      title: "5. Flying Backups Home to Heal the Photo",
      ref: "v3 Self-Recovery + Eqs. 12–16 U† Reverse",
      summary: "Backup clones fly straight back from safe corners to rebuild missing pixels (up to 100% healed!), and reversible quantum gates verify everything cleanly alongside the AI detector.",
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
    data: {
      imageName: "airplane",
      row: 0,
      col: 0,
      pixels: [50, 60, 48, 32],
      binary: ["00110010", "00111100", "00110000", "00100000"],
      sum: 190,
      aa: 48,
      watermark: [1, 1, 0, 0, 1, 1, 0, 1],
      watermarkedPixels: [49, 63, 51, 35],
    },
  };

  const C_BG = "#0b0a08";
  const C_CARD = "#161310";
  const C_WIRE = "#3c352d";
  const C_CREAM = "#f4ede0";
  const C_GOLD = "#e5c69b";
  const C_AMBER = "#f5b864";
  const C_OK = "#4ade80";
  const C_BAD = "#fb7185";
  const C_VIOLET = "#c4b5fd";
  const C_MUTED = "#a89f92";

  const clamp01 = (x) => Math.max(0, Math.min(1, x));
  const ease = (x) => {
    const t = clamp01(x);
    return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
  };
  const lerp = (a, b, t) => a + (b - a) * clamp01(t);

  function roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.roundRect(x, y, w, h, r);
  }

  function pill(ctx, x, y, text, bg, fg) {
    ctx.save();
    ctx.font = "600 11px 'Inter', sans-serif";
    const w = ctx.measureText(text).width + 20;
    ctx.fillStyle = bg;
    roundRect(ctx, x, y, w, 24, 999);
    ctx.fill();
    ctx.fillStyle = fg;
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";
    ctx.fillText(text, x + 10, y + 12.5);
    ctx.restore();
    return w;
  }

  function drawOrb(ctx, x, y, color, r = 6) {
    ctx.save();
    ctx.fillStyle = color;
    ctx.shadowColor = color;
    ctx.shadowBlur = 14;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  }

  function drawStageHeader(ctx, W, idx, sceneP) {
    const sc = SCENES[idx];
    const tag = sim.paperLabels ? `SCENE ${idx + 1}/5  ·  ${sc.ref}` : `HOW IT WORKS  ·  PART ${idx + 1} OF 5`;
    ctx.fillStyle = C_GOLD;
    ctx.font = "600 11px 'JetBrains Mono', monospace";
    ctx.textAlign = "left";
    ctx.fillText(tag, 36, 34);

    ctx.fillStyle = "#ffffff";
    ctx.font = "500 23px 'Inter', sans-serif";
    ctx.fillText(sc.title, 36, 64);

    ctx.fillStyle = C_MUTED;
    ctx.font = "500 11.5px 'Inter', sans-serif";
    ctx.textAlign = "right";
    ctx.fillText(`Photo: ${sim.data.imageName}`, W - 36, 34);

    ctx.strokeStyle = "#26211b";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(36, 82);
    ctx.lineTo(W - 36, 82);
    ctx.stroke();

    ctx.strokeStyle = C_AMBER;
    ctx.beginPath();
    ctx.moveTo(36, 82);
    ctx.lineTo(36 + (W - 72) * sceneP, 82);
    ctx.stroke();
  }

  function drawPhoto(ctx, x, y, size, radius = 12) {
    ctx.save();
    roundRect(ctx, x, y, size, size, radius);
    ctx.clip();
    if (sim.imgObj && sim.imgObj.complete) ctx.drawImage(sim.imgObj, x, y, size, size);
    else {
      ctx.fillStyle = "#26201a";
      ctx.fillRect(x, y, size, size);
    }
    ctx.restore();
  }

  // ----------------------------------------------------------- SCENE 1: Zoom into pixels & invisible bits
  function drawScene1(ctx, W, H, p) {
    const d = sim.data;
    const z = ease(clamp01(p * 1.6));

    // Left: Photo with glowing focus box
    const px = 44, py = 116, ps = 240;
    drawPhoto(ctx, px, py, ps);
    ctx.strokeStyle = "#3f382e";
    ctx.lineWidth = 1.5;
    roundRect(ctx, px, py, ps, ps, 12);
    ctx.stroke();

    const rx = px + 92, ry = py + 86, rs = 34;
    ctx.strokeStyle = C_AMBER;
    ctx.lineWidth = 2.5;
    roundRect(ctx, rx, ry, rs, rs, 4);
    ctx.stroke();
    pill(ctx, px + 10, py + 10, "Your Photo", "rgba(11,10,8,0.75)", "#fff");

    // Connecting zoom lines
    const bx = 336, by = 136, tile = 84;
    ctx.strokeStyle = "rgba(245,184,100,0.5)";
    ctx.setLineDash([5, 5]);
    ctx.beginPath();
    ctx.moveTo(rx + rs, ry);
    ctx.lineTo(bx, by);
    ctx.moveTo(rx + rs, ry + rs);
    ctx.lineTo(bx, by + tile * 2);
    ctx.stroke();
    ctx.setLineDash([]);

    // Middle: Zoomed 2x2 bright squares
    for (let i = 0; i < 4; i++) {
      const tx = bx + (i % 2) * tile;
      const ty = by + Math.floor(i / 2) * tile;
      const val = d.pixels[i];
      ctx.fillStyle = `rgb(${val},${val},${val})`;
      ctx.globalAlpha = 0.3 + 0.7 * z;
      roundRect(ctx, tx + 3, ty + 3, tile - 6, tile - 6, 8);
      ctx.fill();
      ctx.globalAlpha = 1;
      ctx.strokeStyle = C_GOLD;
      ctx.lineWidth = 1.6;
      roundRect(ctx, tx + 3, ty + 3, tile - 6, tile - 6, 8);
      ctx.stroke();

      ctx.fillStyle = val > 140 ? "#11100e" : "#ffffff";
      ctx.font = "700 18px 'Inter', sans-serif";
      ctx.textAlign = "center";
      ctx.fillText(String(val), tx + tile / 2, ty + tile / 2 + 4);
    }
    ctx.fillStyle = C_MUTED;
    ctx.font = "500 12px 'Inter', sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("Zoomed 4 Tiny Squares", bx + tile, by + tile * 2 + 24);

    // Right: Clear Brightness Bar + "Secret Storage Slots" analogy
    const rx2 = 546, ry2 = 126, rw = 370, rh = 240;
    ctx.fillStyle = C_CARD;
    ctx.strokeStyle = "#2b251e";
    roundRect(ctx, rx2, ry2, rw, rh, 14);
    ctx.fill();
    ctx.stroke();

    ctx.fillStyle = C_GOLD;
    ctx.font = "600 12px 'Inter', sans-serif";
    ctx.textAlign = "left";
    ctx.fillText(sim.paperLabels ? "8 QUBITS PER PIXEL (2 LSB HOST SLOTS)" : "HOW WE HIDE DATA WITHOUT CHANGING LOOKS", rx2 + 20, ry2 + 30);

    // 8 lights row
    const bits = d.binary[0] || "00110010";
    for (let b = 0; b < 8; b++) {
      const lx = rx2 + 20 + b * 41;
      const ly = ry2 + 64;
      const isHiddenSlot = b >= 6;
      const pulse = isHiddenSlot ? 0.5 + 0.5 * Math.sin(p * Math.PI * 6) : 0;
      ctx.fillStyle = isHiddenSlot ? `rgba(74, 222, 128, ${0.18 + 0.25 * pulse})` : "#1f1b17";
      ctx.strokeStyle = isHiddenSlot ? C_OK : "#3d362e";
      ctx.lineWidth = isHiddenSlot ? 2 : 1.2;
      roundRect(ctx, lx, ly, 34, 46, 8);
      ctx.fill();
      ctx.stroke();
      ctx.fillStyle = "#fff";
      ctx.font = "700 15px 'JetBrains Mono', monospace";
      ctx.textAlign = "center";
      ctx.fillText(bits[b], lx + 17, ly + 28);
    }

    // Visual brackets explaining left 6 vs right 2
    ctx.fillStyle = C_MUTED;
    ctx.font = "500 11.5px 'Inter', sans-serif";
    ctx.textAlign = "left";
    ctx.fillText("Main brightness (Untouched)", rx2 + 22, ry2 + 132);
    ctx.fillStyle = C_OK;
    ctx.font = "600 12px 'Inter', sans-serif";
    ctx.fillText("Last 2 tiny bits = Secret Shelf!", rx2 + 195, ry2 + 132);

    ctx.fillStyle = C_CREAM;
    ctx.font = "400 13px 'Inter', sans-serif";
    ctx.fillText("Changing 50 → 49 is only 0.4% change.", rx2 + 20, ry2 + 176);
    ctx.fillStyle = C_MUTED;
    ctx.fillText("Human eyes see the exact same color!", rx2 + 20, ry2 + 198);
    ctx.fillText("In quantum mode, H gates hold all 4 at once.", rx2 + 20, ry2 + 220);

    pill(ctx, 44, H - 56, "Key Idea: Tiny invisible shifts let a photo carry hidden safety proof", "#1a1713", C_GOLD);
  }

  // ----------------------------------------------------------- SCENE 2: Building the Lock & Putting It In
  function drawScene2(ctx, W, H, p) {
    const d = sim.data;
    const step1 = ease(clamp01(p * 2.2));
    const step2 = ease(clamp01((p - 0.3) * 2.4));
    const step3 = ease(clamp01((p - 0.62) * 2.6));

    // Left Card: Inputs (Block Squares + Key)
    ctx.fillStyle = C_CARD;
    ctx.strokeStyle = "#2f2922";
    roundRect(ctx, 40, 118, 220, 270, 14);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = C_GOLD;
    ctx.font = "600 12px 'Inter', sans-serif";
    ctx.textAlign = "left";
    ctx.fillText("STEP A · READ SQUARE", 60, 148);
    ctx.fillStyle = "#fff";
    ctx.font = "500 14px 'Inter', sans-serif";
    ctx.fillText(`Pixels: [${d.pixels.join(", ")}]`, 60, 184);
    ctx.fillText(`Avg Light: ${d.aa}`, 60, 214);
    ctx.fillText("Your Key: demo-key", 60, 244);
    ctx.fillStyle = C_MUTED;
    ctx.font = "400 12px 'Inter', sans-serif";
    ctx.fillText(sim.paperLabels ? "Uses RPA, Adder & D4" : "Reads brightness + secret key", 60, 286);

    // Center Factory Box: Secret Fingerprint Maker
    ctx.fillStyle = step2 > 0.1 ? "rgba(229,198,155,0.12)" : C_CARD;
    ctx.strokeStyle = step2 > 0.1 ? C_AMBER : "#2f2922";
    ctx.lineWidth = 2;
    roundRect(ctx, 326, 132, 270, 240, 16);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = C_AMBER;
    ctx.font = "600 12px 'Inter', sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("STEP B · CREATE SECRET LOCK", 461, 166);

    ctx.fillStyle = "#fff";
    ctx.font = "700 22px 'JetBrains Mono', monospace";
    ctx.fillText(step2 > 0.2 ? d.watermark.join("") : "········", 461, 224);
    ctx.fillStyle = C_MUTED;
    ctx.font = "400 12px 'Inter', sans-serif";
    ctx.fillText("8-Bit Safety Fingerprint", 461, 254);
    ctx.fillText("Unique to this square — fakes fail!", 461, 294);
    if (sim.paperLabels) ctx.fillText("Wb = PPB ⊕ AA", 461, 324);

    // Animated flowing wire L -> Center -> R
    ctx.strokeStyle = C_WIRE;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(260, 252);
    ctx.lineTo(326, 252);
    ctx.moveTo(596, 252);
    ctx.lineTo(664, 252);
    ctx.stroke();
    if (step1 > 0 && step1 < 1) drawOrb(ctx, lerp(260, 326, step1), 252, C_AMBER, 6);
    if (step3 > 0 && step3 < 1) drawOrb(ctx, lerp(596, 664, step3), 252, C_OK, 6);

    // Right Card: Protected Pixels Output
    ctx.fillStyle = C_CARD;
    ctx.strokeStyle = step3 > 0.5 ? C_OK : "#2f2922";
    roundRect(ctx, 664, 118, 256, 270, 14);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = step3 > 0.5 ? C_OK : C_GOLD;
    ctx.font = "600 12px 'Inter', sans-serif";
    ctx.textAlign = "left";
    ctx.fillText("STEP C · SAVED INVISIBLE", 684, 148);

    for (let i = 0; i < 4; i++) {
      const y = 186 + i * 38;
      const before = d.pixels[i], after = step3 > 0.4 ? d.watermarkedPixels[i] : before;
      ctx.fillStyle = "#fff";
      ctx.font = "500 13px 'Inter', sans-serif";
      ctx.fillText(`Square ${i + 1}:`, 684, y);
      ctx.font = "700 14px 'JetBrains Mono', monospace";
      ctx.fillStyle = step3 > 0.4 ? C_OK : C_GOLD;
      ctx.fillText(`${before} → ${after}`, 772, y);
    }
    ctx.fillStyle = C_MUTED;
    ctx.font = "500 12px 'Inter', sans-serif";
    ctx.fillText("Visual Match: 98.4% Identical ✓", 684, 356);

    pill(ctx, 40, H - 56, "Key Idea: Even if someone pastes over the photo later, the secret lock inside won't match!", "#1a1713", C_GOLD);
  }

  // ----------------------------------------------------------- SCENE 3: Hiding Two Backup Clones
  function drawScene3(ctx, W, H, p) {
    const gx = 48, gy = 114, gs = 300;
    drawPhoto(ctx, gx, gy, gs);
    ctx.fillStyle = "rgba(11,10,8,0.38)";
    ctx.fillRect(gx, gy, gs, gs);

    // 8x8 tile lines
    ctx.strokeStyle = "rgba(244,237,224,0.22)";
    ctx.lineWidth = 1;
    const step = gs / 8;
    for (let i = 1; i < 8; i++) {
      ctx.beginPath();
      ctx.moveTo(gx + i * step, gy);
      ctx.lineTo(gx + i * step, gy + gs);
      ctx.moveTo(gx, gy + i * step);
      ctx.lineTo(gx + gs, gy + i * step);
      ctx.stroke();
    }
    roundRect(ctx, gx, gy, gs, gs, 12);
    ctx.strokeStyle = "#433c33";
    ctx.stroke();

    // Source Tile -> Primary & Secondary Partners
    const sx = gx + 2.5 * step, sy = gy + 3.5 * step;
    const p1x = gx + 6.5 * step, p1y = gy + 1.5 * step;
    const p2x = gx + 5.5 * step, p2y = gy + 6.5 * step;

    ctx.fillStyle = "rgba(245,184,100,0.45)";
    ctx.strokeStyle = C_AMBER;
    ctx.lineWidth = 2.5;
    ctx.fillRect(sx - step / 2, sy - step / 2, step, step);
    ctx.strokeRect(sx - step / 2, sy - step / 2, step, step);

    const a1 = ease(clamp01((p - 0.12) * 1.9));
    const a2 = ease(clamp01((p - 0.34) * 1.9));

    function flyBeam(x1, y1, cx, cy, x2, y2, prog, col, tag) {
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
      if (prog > 0.8) {
        ctx.fillStyle = col;
        ctx.fillRect(x2 - step / 2, y2 - step / 2, step, step);
        ctx.fillStyle = "#0b0a08";
        ctx.font = "700 10px 'Inter', sans-serif";
        ctx.textAlign = "center";
        ctx.fillText(tag, x2, y2 + 3.5);
      }
      ctx.restore();
    }

    flyBeam(sx, sy, gx + 4.5 * step, gy + 0.5 * step, p1x, p1y, a1, C_AMBER, "Copy 1");
    flyBeam(sx, sy, gx + 4 * step, gy + 6.2 * step, p2x, p2y, a2, C_VIOLET, "Copy 2");

    // Friendly Explanation Cards on the right
    const rx = 392, rw = 528;
    const steps = [
      { title: "Why hide copies far away?", body: "If someone erases the airplane wing, any lock inside that spot gets erased too. So every tile sends a compressed backup snapshot to two unrelated distant spots!", col: C_AMBER },
      { title: "Primary Backup Copy (Main Helper)", body: "Stored in a completely different corner using your secret key shuffle.", col: C_GOLD },
      { title: "Extra Safety Copy (Second Helper)", body: "Even if a huge chunk (up to 40%!) is damaged, the backup clone restores it cleanly.", col: C_VIOLET },
    ];
    steps.forEach((st, idx) => {
      const cy = 114 + idx * 102;
      ctx.fillStyle = C_CARD;
      ctx.strokeStyle = idx === 0 || p > 0.25 + idx * 0.2 ? st.col : "#2b251e";
      ctx.lineWidth = 1.4;
      roundRect(ctx, rx, cy, rw, 88, 12);
      ctx.fill();
      ctx.stroke();
      ctx.fillStyle = st.col;
      ctx.font = "600 14px 'Inter', sans-serif";
      ctx.textAlign = "left";
      ctx.fillText(st.title, rx + 20, cy + 30);
      ctx.fillStyle = C_MUTED;
      ctx.font = "400 12.5px 'Inter', sans-serif";
      ctx.fillText(st.body.slice(0, 74), rx + 20, cy + 54);
      if (st.body.length > 74) ctx.fillText(st.body.slice(74), rx + 20, cy + 72);
    });
  }

  // ----------------------------------------------------------- SCENE 4: Forgery + Fast Scanner Catch
  function drawScene4(ctx, W, H, p) {
    const gx = 48, gy = 116, gs = 290;
    const attackT = ease(clamp01(p * 3.2));
    const scanT = clamp01((p - 0.22) / 0.68);

    ctx.save();
    roundRect(ctx, gx, gy, gs, gs, 12);
    ctx.clip();
    drawPhoto(ctx, gx, gy, gs, 0);

    // Cutout damage box stamps down
    const dx = gx + 76, dy = gy + 84, ds = 112;
    if (attackT > 0.02) {
      ctx.fillStyle = `rgba(12, 10, 9, ${0.95 * attackT})`;
      ctx.fillRect(dx, dy, ds, ds);
    }

    // Sweeping check bar
    if (p > 0.22) {
      const scanY = gy + gs * scanT;
      ctx.strokeStyle = C_AMBER;
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.moveTo(gx, scanY);
      ctx.lineTo(gx + gs, scanY);
      ctx.stroke();

      // Highlight damaged box in glowing red once scanner reaches it
      if (scanY > dy) {
        ctx.strokeStyle = C_BAD;
        ctx.lineWidth = 3;
        ctx.strokeRect(dx, dy, ds, ds);
      }
    }
    ctx.restore();

    roundRect(ctx, gx, gy, gs, gs, 12);
    ctx.strokeStyle = scanT > 0.5 ? C_BAD : "#3f382e";
    ctx.lineWidth = 1.6;
    ctx.stroke();

    ctx.fillStyle = scanT > 0.4 ? C_BAD : C_GOLD;
    ctx.font = "600 13px 'Inter', sans-serif";
    ctx.textAlign = "left";
    ctx.fillText(scanT > 0.4 ? "✕ Fake Box Caught Instantly!" : "Checking Every Photo Lock…", gx, gy + gs + 26);

    // Right side: Clear Check Result & Grover Radar Bar Chart
    const rx = 382, ry = 116, rw = 538, rh = 290;
    ctx.fillStyle = C_CARD;
    ctx.strokeStyle = "#2f2922";
    roundRect(ctx, rx, ry, rw, rh, 14);
    ctx.fill();
    ctx.stroke();

    ctx.fillStyle = "#fff";
    ctx.font = "600 15px 'Inter', sans-serif";
    ctx.fillText("How We Spot Fake Edits Instantly", rx + 22, ry + 34);
    ctx.fillStyle = C_MUTED;
    ctx.font = "400 12.5px 'Inter', sans-serif";
    ctx.fillText("Original untouched blocks match their lock (Green). Edited squares fail (Red)!", rx + 22, ry + 58);

    const bars = 12;
    const groverBoost = ease(clamp01((p - 0.35) * 1.8));
    const baseY = ry + 236;
    for (let i = 0; i < bars; i++) {
      const isBad = i === 5 || i === 6;
      const bh = isBad ? lerp(20, 146, groverBoost) : lerp(22, 10, groverBoost);
      const bx = rx + 28 + i * 41;
      ctx.fillStyle = isBad ? C_BAD : "#2e2923";
      roundRect(ctx, bx, baseY - bh, 26, bh, 5);
      ctx.fill();
      if (isBad && groverBoost > 0.5) {
        ctx.fillStyle = C_BAD;
        ctx.font = "700 10px 'Inter', sans-serif";
        ctx.textAlign = "center";
        ctx.fillText("FAKE", bx + 13, baseY + 16);
      }
    }
    ctx.textAlign = "left";
    ctx.fillStyle = C_GOLD;
    ctx.font = "500 11.5px 'Inter', sans-serif";
    ctx.fillText(sim.paperLabels ? "Grover 15q search boosts altered pixels 15.38× in 3 steps" : "Quantum radar zooms straight onto every edited pixel!", rx + 22, ry + rh - 18);
  }

  // ----------------------------------------------------------- SCENE 5: Flyback Healing + Summary
  function drawScene5(ctx, W, H, p) {
    const gx = 48, gy = 116, gs = 290;
    const dx = gx + 76, dy = gy + 84, ds = 112;
    const healP = ease(clamp01((p - 0.16) / 0.62));

    // Photo starts with black cutout and heals smoothly back!
    ctx.save();
    roundRect(ctx, gx, gy, gs, gs, 12);
    ctx.clip();
    drawPhoto(ctx, gx, gy, gs, 0);
    const holeAlpha = 1 - healP;
    if (holeAlpha > 0.01) {
      ctx.fillStyle = `rgba(12, 10, 9, ${holeAlpha})`;
      ctx.fillRect(dx, dy, ds, ds);
      ctx.strokeStyle = `rgba(74, 222, 128, ${0.85 * Math.sin(healP * Math.PI)})`;
      ctx.lineWidth = 3;
      ctx.strokeRect(dx, dy, ds, ds);
    }
    ctx.restore();

    roundRect(ctx, gx, gy, gs, gs, 12);
    ctx.strokeStyle = healP > 0.85 ? C_OK : C_GOLD;
    ctx.lineWidth = 2;
    ctx.stroke();

    // Flying rescue orbs from partner blocks back to damaged spot
    if (healP > 0.02 && healP < 0.96) {
      drawOrb(ctx, lerp(gx + 245, dx + ds / 2, healP), lerp(gy + 42, dy + ds / 2, healP), C_OK, 7);
      drawOrb(ctx, lerp(gx + 215, dx + ds / 2, healP), lerp(gy + 245, dy + ds / 2, healP), C_AMBER, 7);
    }

    ctx.fillStyle = healP > 0.85 ? C_OK : C_GOLD;
    ctx.font = "600 13px 'Inter', sans-serif";
    ctx.textAlign = "left";
    ctx.fillText(healP > 0.85 ? `✓ ${Math.round(healP * 100)}% Restored Back to Normal!` : "Flying Backups Home to Rebuild…", gx, gy + gs + 26);

    // Right: Crisp Takeaways Card
    const rx = 382, ry = 116, rw = 538, rh = 290;
    ctx.fillStyle = C_CARD;
    ctx.strokeStyle = healP > 0.85 ? C_OK : "#2f2922";
    ctx.lineWidth = 1.6;
    roundRect(ctx, rx, ry, rw, rh, 14);
    ctx.fill();
    ctx.stroke();

    ctx.fillStyle = C_GOLD;
    ctx.font = "600 12px 'Inter', sans-serif";
    ctx.fillText("WHAT HAPPENED BEHIND THE SCENES", rx + 24, ry + 34);

    const bullets = [
      { icon: "✓", col: C_OK, title: "1. Damaged Spot Located", desc: "The hidden fingerprint failed only inside the tampered rectangle." },
      { icon: "✓", col: C_AMBER, title: "2. Hidden Copies Found Elsewhere", desc: "Safe partner tiles around the photo delivered their stored backups." },
      { icon: "✓", col: C_VIOLET, title: "3. Missing Picture Rebuilt", desc: "Missing pixels were reconstructed cleanly — almost good as new!" },
      { icon: "✓", col: C_CREAM, title: "4. AI Detective Ready", desc: "An AI model can even identify what tool made the fake edit." },
    ];
    bullets.forEach((b, k) => {
      const by = ry + 62 + k * 54;
      ctx.fillStyle = b.col;
      ctx.font = "700 15px 'Inter', sans-serif";
      ctx.fillText(b.icon, rx + 24, by + 10);
      ctx.fillStyle = "#fff";
      ctx.font = "600 13.5px 'Inter', sans-serif";
      ctx.fillText(b.title, rx + 50, by + 10);
      ctx.fillStyle = C_MUTED;
      ctx.font = "400 12px 'Inter', sans-serif";
      ctx.fillText(b.desc, rx + 50, by + 29);
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
    const grad = ctx.createRadialGradient(W * 0.78, H * 0.14, 10, W * 0.78, H * 0.14, 420);
    grad.addColorStop(0, "rgba(218, 154, 78, 0.14)");
    grad.addColorStop(1, "transparent");
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, W, H);

    const idx = Math.min(SCENES.length - 1, Math.floor(sim.elapsed / SCENE_DUR));
    const localP = clamp01((sim.elapsed - idx * SCENE_DUR) / SCENE_DUR);

    drawStageHeader(ctx, W, idx, localP);
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
    const capTitle = $("inside-cap-title");
    const capText = $("inside-cap-text");
    if (capTitle) capTitle.textContent = sim.paperLabels ? `${SCENES[idx].title} (${SCENES[idx].ref})` : SCENES[idx].title;
    if (capText) capText.textContent = SCENES[idx].summary;
    document.querySelectorAll(".inside-chap").forEach((el, k) => el.classList.toggle("active", k === idx));
  }

  function tick(ts) {
    if (!sim.openFlag) return;
    if (sim.lastTs) {
      const dt = Math.min(0.1, (ts - sim.lastTs) / 1000);
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
        Object.assign(sim.data, ctxData);
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
      if (btn) btn.textContent = sim.paperLabels ? "Paper Labels: On" : "Paper Labels: Off";
      renderFrame();
    },
    scrubRatio(r) {
      sim.elapsed = clamp01(r) * (TOTAL_DUR - 0.01);
      ensureLoop();
    },
  };
})();
