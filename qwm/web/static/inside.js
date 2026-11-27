"use strict";
// Animated step-by-step Airplane Watermarking Simulation.
// Focuses strictly on HOW watermarking is done in a very simple visual way.

(function () {
  const SCENE_DUR = 5.6;
  const SCENES = [
    {
      title: "1. Slice the Airplane Photo Into 2x2 Squares",
      ref: "Step 1 · NEQR 2x2 Block Partition",
      summary: "We split the Airplane photo into tiny 4-pixel squares. Let us zoom onto one square from the airplane wing.",
    },
    {
      title: "2. Open 2 Empty Secret Slots Inside Each Pixel",
      ref: "Step 2 · 8-Bit Intensity & 2 LSB Host Shelf",
      summary: "Each pixel holds 6 main brightness bits (untouched!) and 2 tiny lowest bits at the end. Adjusting those 2 bits is invisible to human eyes.",
    },
    {
      title: "3. Build an 8-Bit Secret Watermark Stamp",
      ref: "Step 3 · RPA + D4 Average ⊕ PPB (+ Secret Key)",
      summary: "We blend the 4 Airplane pixels' average shade, their local pattern, and your secret key into 8 golden watermark pearls.",
    },
    {
      title: "4. Hide 2 Golden Pearls Inside Each Airplane Pixel",
      ref: "Step 4 · Reversible Watermark Embedding (2 bpp)",
      summary: "Every pair of golden pearls drops into the 2 tiny secret shelves of Pixel 1, Pixel 2, Pixel 3, and Pixel 4 across the Airplane.",
    },
    {
      title: "5. Tuck Spare Clones & Finish Watermarked Airplane",
      ref: "Step 5 · Partner Clones + Original vs Watermarked",
      summary: "Tiny backup copies also hide safely in opposite sky corners, and the finished Watermarked Airplane looks 98.4%+ identical to the Original!",
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
    clock: 0,
    coverImg: null,
    wmImg: null,
    data: {
      pixels: [204, 198, 200, 194],
      aa: 199,
      watermark: [1, 0, 1, 1, 0, 1, 0, 1],
      watermarkedPixels: [205, 199, 201, 193],
    },
  };

  const C_BG = "#0c0b09";
  const C_CARD = "#171411";
  const C_BORDER = "#332c24";
  const C_TEXT = "#f5f2eb";
  const C_MUTED = "#b5ada0";
  const C_GOLD = "#f5b864";
  const C_OK = "#4ade80";
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
    rrect(ctx, x, y, w, 24, 999);
    ctx.fill();
    ctx.fillStyle = fg;
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";
    ctx.fillText(text, x + 10, y + 12.5);
    ctx.restore();
    return w;
  }

  function drawOrb(ctx, x, y, color, r = 6.5) {
    ctx.save();
    ctx.fillStyle = color;
    ctx.shadowColor = color;
    ctx.shadowBlur = 16;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  }

  function drawAmbientDust(ctx, W, H, t) {
    ctx.save();
    for (let i = 0; i < 16; i++) {
      const px = ((i * 137 + t * 18) % (W - 40)) + 20;
      const py = ((i * 73 + Math.sin(t * 1.4 + i) * 14) % (H - 80)) + 70;
      const a = 0.14 + 0.12 * Math.sin(t * 2.2 + i);
      ctx.fillStyle = i % 2 === 0 ? `rgba(245,184,100,${a})` : `rgba(74,222,128,${a})`;
      ctx.beginPath();
      ctx.arc(px, py, 2.2, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.restore();
  }

  function drawImg(ctx, img, x, y, size, radius = 12) {
    ctx.save();
    rrect(ctx, x, y, size, size, radius);
    ctx.clip();
    if (img && img.complete && img.naturalWidth > 0) {
      ctx.drawImage(img, x, y, size, size);
    } else {
      ctx.fillStyle = "#29231d";
      ctx.fillRect(x, y, size, size);
    }
    ctx.restore();
  }

  function drawHeader(ctx, W, idx, sceneP) {
    const sc = SCENES[idx] || SCENES[0];
    const tag = sim.paperLabels ? `STEP ${idx + 1}/5 · ${sc.ref}` : `WATERMARKING STEP ${idx + 1} OF 5 · AIRPLANE EXAMPLE`;
    ctx.fillStyle = C_GOLD;
    ctx.font = "700 11px 'JetBrains Mono', monospace";
    ctx.textAlign = "left";
    ctx.fillText(tag, 36, 32);

    ctx.fillStyle = "#ffffff";
    ctx.font = "700 22px 'Inter', sans-serif";
    ctx.fillText(sc.title, 36, 62);

    ctx.strokeStyle = "#2a241d";
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(36, 80);
    ctx.lineTo(W - 36, 80);
    ctx.stroke();

    ctx.strokeStyle = C_GOLD;
    ctx.beginPath();
    ctx.moveTo(36, 80);
    ctx.lineTo(36 + (W - 72) * sceneP, 80);
    ctx.stroke();
  }

  // ----------------------------------------------------------- STEP 1: Slice Airplane Into 2x2 Blocks
  function drawScene1(ctx, W, H, p, t) {
    const px = 44, py = 112, ps = 276;
    drawImg(ctx, sim.coverImg, px, py, ps);

    // Sweeping shimmer grid over Airplane
    const gridA = ease(clamp01(p * 2.2));
    ctx.save();
    ctx.strokeStyle = `rgba(245,184,100,${0.28 * gridA})`;
    ctx.lineWidth = 1;
    for (let i = 1; i < 8; i++) {
      const k = i * (ps / 8);
      ctx.beginPath();
      ctx.moveTo(px + k, py);
      ctx.lineTo(px + k, py + ps);
      ctx.moveTo(px, py + k);
      ctx.lineTo(px + ps, py + k);
      ctx.stroke();
    }
    ctx.restore();

    // Floating magnifying reticle smoothly landing on wing
    const rx = lerp(px + 28, px + 114, ease(clamp01(p * 1.4)));
    const ry = lerp(py + 30, py + 118, ease(clamp01(p * 1.4)));
    const rs = 36 + Math.sin(t * 4) * 2;
    ctx.strokeStyle = C_GOLD;
    ctx.lineWidth = 2.8;
    rrect(ctx, rx, ry, rs, rs, 6);
    ctx.stroke();
    pill(ctx, px + 10, py + 10, "Original Airplane", "rgba(12,11,9,0.78)", "#fff");

    // Connecting dotted rays
    const bx = 408, by = 148, tile = 104;
    const z = ease(clamp01((p - 0.15) * 1.6));
    ctx.save();
    ctx.strokeStyle = `rgba(245,184,100,${0.55 * z})`;
    ctx.setLineDash([6, 6]);
    ctx.lineDashOffset = -t * 28;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(rx + rs, ry);
    ctx.lineTo(bx, by);
    ctx.moveTo(rx + rs, ry + rs);
    ctx.lineTo(bx, by + tile * 2);
    ctx.stroke();
    ctx.restore();

    // Zoomed 2x2 Airplane Wing Pixels
    const labels = ["Top-Left", "Top-Right", "Bottom-Left", "Bottom-Right"];
    for (let i = 0; i < 4; i++) {
      const col = i % 2, row = Math.floor(i / 2);
      const tx = lerp(rx, bx + col * (tile + 8), z);
      const ty = lerp(ry, by + row * (tile + 8), z);
      const sz = lerp(rs / 2, tile, z);
      const val = sim.data.pixels[i];

      ctx.fillStyle = `rgb(${val},${val},${val})`;
      ctx.strokeStyle = i === Math.floor(t * 2) % 4 ? C_OK : C_GOLD;
      ctx.lineWidth = 2.2;
      rrect(ctx, tx, ty, sz, sz, 10);
      ctx.fill();
      ctx.stroke();

      if (z > 0.65) {
        ctx.fillStyle = val > 135 ? "#141413" : "#ffffff";
        ctx.font = "700 22px 'Inter', sans-serif";
        ctx.textAlign = "center";
        ctx.fillText(String(val), tx + sz / 2, ty + sz / 2);
        ctx.font = "600 10.5px 'Inter', sans-serif";
        ctx.fillText(labels[i], tx + sz / 2, ty + sz - 14);
      }
    }

    // Friendly explainer card on far right
    const fx = 664, fy = 148, fw = 260, fh = 216;
    ctx.fillStyle = C_CARD;
    ctx.strokeStyle = C_BORDER;
    rrect(ctx, fx, fy, fw, fh, 14);
    ctx.fill();
    ctx.stroke();
    ctx.textAlign = "left";
    ctx.fillStyle = C_GOLD;
    ctx.font = "700 12px 'Inter', sans-serif";
    ctx.fillText("ONE TINY AIRPLANE PATCH", fx + 20, fy + 34);
    ctx.fillStyle = C_TEXT;
    ctx.font = "600 14.5px 'Inter', sans-serif";
    ctx.fillText("Just 4 tiny dots at a time!", fx + 20, fy + 68);
    ctx.fillStyle = C_MUTED;
    ctx.font = "400 13px 'Inter', sans-serif";
    ctx.fillText("Each 256×256 Airplane image has", fx + 20, fy + 104);
    ctx.fillText("16,384 of these 2×2 blocks.", fx + 20, fy + 124);
    ctx.fillText("We lock every single block one", fx + 20, fy + 152);
    ctx.fillText("after another cleanly.", fx + 20, fy + 172);
    if (sim.paperLabels) pill(ctx, fx + 18, fy + 182, "NEQR 10-qubit state |C>", "#26211b", C_GOLD);

    pill(ctx, 44, H - 52, "Every pixel shade (0–255) simply tells how bright that Airplane spot is.", "#191612", C_GOLD);
  }

  // ----------------------------------------------------------- STEP 2: Secret 2-Bit Shelf Inside Pixel
  function drawScene2(ctx, W, H, p, t) {
    const val = sim.data.pixels[0];
    const open = ease(clamp01(p * 1.9));

    // Left: Airplane Pixel Card opening its 8 slots
    const cx = 44, cy = 116, cw = 520, ch = 286;
    ctx.fillStyle = C_CARD;
    ctx.strokeStyle = C_BORDER;
    rrect(ctx, cx, cy, cw, ch, 14);
    ctx.fill();
    ctx.stroke();

    ctx.textAlign = "left";
    ctx.fillStyle = "#ffffff";
    ctx.font = "700 16px 'Inter', sans-serif";
    ctx.fillText(`Inside 1 Airplane Pixel (Brightness = ${val})`, cx + 22, cy + 38);
    ctx.fillStyle = C_MUTED;
    ctx.font = "400 13px 'Inter', sans-serif";
    ctx.fillText("Every pixel is built from 8 switches — the last 2 barely change brightness!", cx + 22, cy + 62);

    const bits = val.toString(2).padStart(8, "0");
    for (let i = 0; i < 8; i++) {
      const sx = cx + 22 + i * 59;
      const slideY = lerp(cy + 140, cy + 96, open);
      const isSecret = i >= 6;
      const pulse = isSecret ? 0.5 + 0.5 * Math.sin(t * 6) : 0;

      ctx.fillStyle = isSecret ? `rgba(74,222,128,${0.18 + 0.25 * pulse})` : "#24201b";
      ctx.strokeStyle = isSecret ? C_OK : "#453e35";
      ctx.lineWidth = isSecret ? 2.4 : 1.4;
      rrect(ctx, sx, slideY, 48, 72, 10);
      ctx.fill();
      ctx.stroke();

      ctx.fillStyle = isSecret ? C_OK : "#fff";
      ctx.font = "700 19px 'JetBrains Mono', monospace";
      ctx.textAlign = "center";
      ctx.fillText(bits[i], sx + 24, slideY + 38);
      ctx.font = "600 10px 'Inter', sans-serif";
      ctx.fillStyle = isSecret ? C_OK : C_MUTED;
      ctx.fillText(isSecret ? "SLOT" : `B${8 - i}`, sx + 24, slideY + 59);
    }

    ctx.textAlign = "left";
    ctx.fillStyle = C_MUTED;
    ctx.font = "600 12px 'Inter', sans-serif";
    ctx.fillText("← Top 6 Main Brightness Switches (Never Touched)", cx + 24, cy + 200);
    ctx.fillStyle = C_OK;
    ctx.fillText("↑ Last 2 Secret Watermark Pockets!", cx + 286, cy + 228);

    // Right: Animated Eye Comparison on Airplane Patch
    const rx = 594, ry = 116, rw = 326, rh = 286;
    ctx.fillStyle = C_CARD;
    ctx.strokeStyle = open > 0.6 ? C_OK : C_BORDER;
    rrect(ctx, rx, ry, rw, rh, 14);
    ctx.fill();
    ctx.stroke();

    ctx.fillStyle = C_GOLD;
    ctx.font = "700 12px 'Inter', sans-serif";
    ctx.fillText("EYE VISIBILITY TEST", rx + 22, ry + 34);

    // Two side-by-side swatches morphing slightly (e.g. 204 -> 205)
    const afterVal = val ^ 1;
    ctx.fillStyle = `rgb(${val},${val},${val})`;
    rrect(ctx, rx + 22, ry + 58, 126, 126, 12);
    ctx.fill();
    ctx.fillStyle = val > 130 ? "#141413" : "#fff";
    ctx.font = "700 13px 'Inter', sans-serif";
    ctx.textAlign = "center";
    ctx.fillText(`Before (${val})`, rx + 85, ry + 124);

    const morph = lerp(val, afterVal, clamp01(Math.sin(t * 2) * 0.5 + 0.5));
    ctx.fillStyle = `rgb(${Math.round(morph)},${Math.round(morph)},${Math.round(morph)})`;
    rrect(ctx, rx + 178, ry + 58, 126, 126, 12);
    ctx.fill();
    ctx.fillStyle = val > 130 ? "#141413" : "#fff";
    ctx.fillText(`With Lock (${afterVal})`, rx + 241, ry + 124);

    ctx.textAlign = "left";
    ctx.fillStyle = C_OK;
    ctx.font = "700 14px 'Inter', sans-serif";
    ctx.fillText("✓ Both look identical to eyes!", rx + 22, ry + 220);
    ctx.fillStyle = C_MUTED;
    ctx.font = "400 12.5px 'Inter', sans-serif";
    ctx.fillText("4 pixels × 2 slots = 8 hidden watermark bits", rx + 22, ry + 246);
    if (sim.paperLabels) ctx.fillText("Capacity = 2 bits per pixel (2 bpp).", rx + 22, ry + 266);
  }

  // ----------------------------------------------------------- STEP 3: Generate 8 Watermark Pearls
  function drawScene3(ctx, W, H, p, t) {
    const s1 = ease(clamp01(p * 2.2));
    const s2 = ease(clamp01((p - 0.25) * 2.2));
    const s3 = ease(clamp01((p - 0.5) * 2.2));

    // Left 3 friendly input pills
    const inputs = [
      { title: "1. Airplane Avg Light", sub: `Avg shade = ${sim.data.aa}`, col: C_GOLD, y: 120 },
      { title: "2. Block Pattern Clues", sub: "Shape + texture bits", col: C_SKY, y: 212 },
      { title: "3. Your Secret Key", sub: "Password hash lock", col: C_OK, y: 304 },
    ];

    inputs.forEach((inp, k) => {
      ctx.fillStyle = C_CARD;
      ctx.strokeStyle = p > k * 0.14 ? inp.col : C_BORDER;
      ctx.lineWidth = 1.8;
      rrect(ctx, 44, inp.y, 240, 74, 12);
      ctx.fill();
      ctx.stroke();

      ctx.textAlign = "left";
      ctx.fillStyle = inp.col;
      ctx.font = "700 13.5px 'Inter', sans-serif";
      ctx.fillText(inp.title, 62, inp.y + 29);
      ctx.fillStyle = C_MUTED;
      ctx.font = "400 12.5px 'Inter', sans-serif";
      ctx.fillText(inp.sub, 62, inp.y + 52);

      // Curved glowing flow wire into center blender
      ctx.strokeStyle = "#332c24";
      ctx.lineWidth = 2.5;
      ctx.beginPath();
      ctx.moveTo(284, inp.y + 37);
      ctx.bezierCurveTo(340, inp.y + 37, 340, 250, 396, 250);
      ctx.stroke();

      // Continuous animated orb riding wire!
      const prog = ((t * 0.8 + k * 0.3) % 1);
      if (s1 > 0.1) {
        const bx = lerp(284, 396, ease(prog));
        const by = lerp(inp.y + 37, 250, ease(prog));
        drawOrb(ctx, bx, by, inp.col, 6);
      }
    });

    // Center Blender / Mixer Ring (pulsing continuously!)
    const mx = 468, my = 250, mr = 64;
    ctx.save();
    ctx.translate(mx, my);
    ctx.rotate(t * 1.8);
    ctx.strokeStyle = C_GOLD;
    ctx.lineWidth = 3;
    ctx.setLineDash([14, 8]);
    ctx.beginPath();
    ctx.arc(0, 0, mr, 0, Math.PI * 2);
    ctx.stroke();
    ctx.restore();

    ctx.fillStyle = C_CARD;
    ctx.beginPath();
    ctx.arc(mx, my, mr - 10, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#fff";
    ctx.font = "700 13.5px 'Inter', sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("MIX &", mx, my - 6);
    ctx.fillText("LOCK", mx, my + 12);

    // Output beam L -> Right 8 Watermark Pearls box
    ctx.strokeStyle = "#332c24";
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(532, 250);
    ctx.lineTo(596, 250);
    ctx.stroke();
    if (s2 > 0.2) drawOrb(ctx, lerp(532, 596, (t * 1.4) % 1), 250, C_GOLD, 7);

    // Right: Output 8 Golden Watermark Pearls
    const rx = 596, ry = 132, rw = 324, rh = 244;
    ctx.fillStyle = C_CARD;
    ctx.strokeStyle = s3 > 0.3 ? C_GOLD : C_BORDER;
    ctx.lineWidth = 2;
    rrect(ctx, rx, ry, rw, rh, 14);
    ctx.fill();
    ctx.stroke();

    ctx.textAlign = "left";
    ctx.fillStyle = C_GOLD;
    ctx.font = "700 12.5px 'Inter', sans-serif";
    ctx.fillText("8-BIT SECRET WATERMARK STAMP", rx + 22, ry + 36);
    ctx.fillStyle = C_MUTED;
    ctx.font = "400 12.5px 'Inter', sans-serif";
    ctx.fillText("Custom-built just for this Airplane square!", rx + 22, ry + 58);

    for (let i = 0; i < 8; i++) {
      const bit = sim.data.watermark[i];
      const bx = rx + 36 + (i % 4) * 68;
      const by = ry + 108 + Math.floor(i / 4) * 64 + Math.sin(t * 4 + i * 0.7) * 3;
      const show = ease(clamp01((p - 0.3 - i * 0.05) * 3.5));
      ctx.globalAlpha = 0.25 + 0.75 * show;
      ctx.fillStyle = bit ? C_GOLD : "#2c2620";
      ctx.strokeStyle = C_GOLD;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(bx, by, 21, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
      ctx.fillStyle = bit ? "#141413" : "#ffffff";
      ctx.font = "700 16px 'JetBrains Mono', monospace";
      ctx.textAlign = "center";
      ctx.fillText(String(bit), bx, by + 5);
      ctx.globalAlpha = 1;
    }

    if (sim.paperLabels) pill(ctx, 44, H - 52, "Formula: Wb = AA ⊕ PPB (v2 adds SHAKE-256 Toeplitz MAC)", "#191612", C_GOLD);
    else pill(ctx, 44, H - 52, "Now we have 8 tiny golden proof pearls to tuck back into our 4 Airplane pixels!", "#191612", C_GOLD);
  }

  // ----------------------------------------------------------- STEP 4: Hide 2 Pearls Into Each Airplane Pixel
  function drawScene4(ctx, W, H, p, t) {
    // Left top: 8 Pearls waiting to drop
    const wb = sim.data.watermark;
    const pixels = sim.data.pixels;
    const outPixels = sim.data.watermarkedPixels;

    ctx.textAlign = "left";
    ctx.fillStyle = C_GOLD;
    ctx.font = "700 12px 'Inter', sans-serif";
    ctx.fillText("8 WATERMARK PEARLS FLY INTO THE 4 AIRPLANE PIXELS", 44, 118);

    // 4 destination pixel boxes along middle
    const cardW = 140, gap = 16;
    for (let i = 0; i < 4; i++) {
      const px = 44 + i * (cardW + gap), py = 228, ph = 152;
      const dropP = ease(clamp01((p - i * 0.14) * 2.2));
      const landed = dropP > 0.88;

      ctx.fillStyle = C_CARD;
      ctx.strokeStyle = landed ? C_OK : C_BORDER;
      ctx.lineWidth = landed ? 2.2 : 1.4;
      rrect(ctx, px, py, cardW, ph, 12);
      ctx.fill();
      ctx.stroke();

      // Pixel preview swatch at top
      const v = landed ? outPixels[i] : pixels[i];
      ctx.fillStyle = `rgb(${v},${v},${v})`;
      rrect(ctx, px + 16, py + 16, cardW - 32, 46, 8);
      ctx.fill();
      ctx.fillStyle = v > 130 ? "#141413" : "#fff";
      ctx.font = "700 13px 'Inter', sans-serif";
      ctx.textAlign = "center";
      ctx.fillText(`Pixel ${i + 1}: ${v}`, px + cardW / 2, py + 43);

      // 2 Secret Pearl Slots at bottom
      for (let b = 0; b < 2; b++) {
        const bit = wb[2 * i + b];
        const slotX = px + 36 + b * 48, slotY = py + 98;
        ctx.fillStyle = landed ? "rgba(74,222,128,0.22)" : "#26211b";
        ctx.strokeStyle = landed ? C_OK : C_GOLD;
        ctx.lineWidth = 1.8;
        ctx.beginPath();
        ctx.arc(slotX, slotY, 16, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();

        // Pearl flying down smoothly!
        const startX = 62 + (2 * i + b) * 72, startY = 148;
        const fx = lerp(startX, slotX, dropP);
        const fy = lerp(startY, slotY, dropP);
        drawOrb(ctx, fx, fy, landed ? C_OK : C_GOLD, 11);
        ctx.fillStyle = "#141413";
        ctx.font = "700 12px 'JetBrains Mono', monospace";
        ctx.fillText(String(bit), fx, fy + 4);
      }

      ctx.fillStyle = landed ? C_OK : C_MUTED;
      ctx.font = "600 11.5px 'Inter', sans-serif";
      ctx.fillText(landed ? "✓ Hidden!" : "Waiting...", px + cardW / 2, py + 136);
    }

    // Far Right: Watermarked Airplane glowing with green lock wave!
    const ax = 682, ay = 132, as = 240;
    drawImg(ctx, sim.wmImg || sim.coverImg, ax, ay, as);
    const waveY = ay + ((t * 90) % as);
    ctx.save();
    ctx.strokeStyle = "rgba(74,222,128,0.85)";
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(ax, waveY);
    ctx.lineTo(ax + as, waveY);
    ctx.stroke();
    ctx.restore();

    rrect(ctx, ax, ay, as, as, 12);
    ctx.strokeStyle = C_OK;
    ctx.lineWidth = 2.2;
    ctx.stroke();
    pill(ctx, ax + 10, ay + 10, "Locking Full Airplane…", "rgba(6,95,70,0.86)", "#fff");

    pill(ctx, 44, H - 52, "Repeated cleanly for every 2×2 square so the entire Airplane carries an invisible watermark.", "#191612", C_GOLD);
  }

  // ----------------------------------------------------------- STEP 5: Spare Backups + Final Before/After Sweep
  function drawScene5(ctx, W, H, p, t) {
    // Left: Airplane tucking spare wing copies into corners
    const gx = 44, gy = 114, gs = 282;
    drawImg(ctx, sim.wmImg || sim.coverImg, gx, gy, gs);
    ctx.fillStyle = "rgba(12,11,9,0.28)";
    ctx.fillRect(gx, gy, gs, gs);

    const sx = gx + 106, sy = gy + 114;
    const p1x = gx + 224, p1y = gy + 46;
    const p2x = gx + 216, p2y = gy + 234;
    ctx.strokeStyle = C_GOLD;
    ctx.lineWidth = 2.4;
    ctx.strokeRect(sx - 18, sy - 18, 36, 36);

    function cloneArc(x1, y1, cx, cy, x2, y2, col, tag, offset) {
      ctx.save();
      ctx.strokeStyle = col;
      ctx.lineWidth = 2.4;
      ctx.beginPath();
      ctx.moveTo(x1, y1);
      ctx.quadraticCurveTo(cx, cy, x2, y2);
      ctx.stroke();
      const prog = (t * 0.65 + offset) % 1;
      const bx = (1 - prog) * (1 - prog) * x1 + 2 * (1 - prog) * prog * cx + prog * prog * x2;
      const by = (1 - prog) * (1 - prog) * y1 + 2 * (1 - prog) * prog * cy + prog * prog * y2;
      drawOrb(ctx, bx, by, col, 6.5);
      ctx.fillStyle = col;
      rrect(ctx, x2 - 26, y2 - 12, 52, 24, 999);
      ctx.fill();
      ctx.fillStyle = "#141413";
      ctx.font = "700 10px 'Inter', sans-serif";
      ctx.textAlign = "center";
      ctx.fillText(tag, x2, y2 + 3.5);
      ctx.restore();
    }

    cloneArc(sx, sy, gx + 170, gy + 24, p1x, p1y, C_GOLD, "Copy 1", 0);
    cloneArc(sx, sy, gx + 168, gy + 220, p2x, p2y, C_SKY, "Copy 2", 0.45);
    pill(ctx, gx + 10, gy + 10, "Backups Saved in Corners", "rgba(12,11,9,0.78)", C_GOLD);

    // Right: Animated Live Wipe Between Original Airplane & Watermarked Airplane
    const wx = 368, wy = 114, ws = 282;
    drawImg(ctx, sim.wmImg || sim.coverImg, wx, wy, ws);
    const sweep = 0.5 + 0.42 * Math.sin(t * 1.8);
    ctx.save();
    ctx.beginPath();
    ctx.rect(wx, wy, ws * sweep, ws);
    ctx.clip();
    drawImg(ctx, sim.coverImg, wx, wy, ws);
    ctx.restore();

    ctx.strokeStyle = C_GOLD;
    ctx.lineWidth = 2.8;
    ctx.beginPath();
    ctx.moveTo(wx + ws * sweep, wy);
    ctx.lineTo(wx + ws * sweep, wy + ws);
    ctx.stroke();
    rrect(ctx, wx, wy, ws, ws, 12);
    ctx.strokeStyle = C_OK;
    ctx.lineWidth = 2;
    ctx.stroke();

    pill(ctx, wx + 10, wy + 10, "Original", "rgba(12,11,9,0.78)", "#fff");
    pill(ctx, wx + ws - 110, wy + 10, "Watermarked", "rgba(6,95,70,0.88)", "#fff");

    // Summary Column on far right
    const sx2 = 674, sy2 = 114, sw = 248, sh = 282;
    ctx.fillStyle = C_CARD;
    ctx.strokeStyle = C_OK;
    ctx.lineWidth = 1.8;
    rrect(ctx, sx2, sy2, sw, sh, 14);
    ctx.fill();
    ctx.stroke();

    ctx.textAlign = "left";
    ctx.fillStyle = C_OK;
    ctx.font = "700 12.5px 'Inter', sans-serif";
    ctx.fillText("✓ AIRPLANE WATERMARKED!", sx2 + 18, sy2 + 34);
    const items = [
      "Looks 98.4%+ identical",
      "Every 2×2 block locked",
      "Dual backups tucked away",
      "Ready to catch & heal edits!",
    ];
    items.forEach((it, idx) => {
      ctx.fillStyle = C_TEXT;
      ctx.font = "600 13px 'Inter', sans-serif";
      ctx.fillText(`• ${it}`, sx2 + 18, sy2 + 78 + idx * 42);
    });
    if (sim.paperLabels) {
      ctx.fillStyle = C_MUTED;
      ctx.font = "500 11px 'JetBrains Mono', monospace";
      ctx.fillText("2 bpp · 16,384 blocks", sx2 + 18, sy2 + 254);
    }

    pill(ctx, 44, H - 52, "Done! Try Step 2 above to cut or draw over this watermarked Airplane and watch it auto-heal!", "#191612", C_OK);
  }

  function renderFrame() {
    const canvas = $("inside-canvas");
    if (!canvas) return;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const W = 960, H = 490;
    if (canvas.width !== W * dpr || canvas.height !== H * dpr) {
      canvas.width = W * dpr;
      canvas.height = H * dpr;
    }
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    ctx.fillStyle = C_BG;
    ctx.fillRect(0, 0, W, H);
    drawAmbientDust(ctx, W, H, sim.clock);

    const safeElapsed = Number.isFinite(sim.elapsed) ? Math.max(0, Math.min(TOTAL_DUR - 0.001, sim.elapsed)) : 0;
    sim.elapsed = safeElapsed;
    const idx = Math.max(0, Math.min(SCENES.length - 1, Math.floor(safeElapsed / SCENE_DUR)));
    const localP = clamp01((safeElapsed - idx * SCENE_DUR) / SCENE_DUR);

    drawHeader(ctx, W, idx, localP);
    if (idx === 0) drawScene1(ctx, W, H, localP, sim.clock);
    else if (idx === 1) drawScene2(ctx, W, H, localP, sim.clock);
    else if (idx === 2) drawScene3(ctx, W, H, localP, sim.clock);
    else if (idx === 3) drawScene4(ctx, W, H, localP, sim.clock);
    else drawScene5(ctx, W, H, localP, sim.clock);

    updateTransportUI(idx);
  }

  function updateTransportUI(idx) {
    const playBtn = $("inside-play");
    if (playBtn) playBtn.innerHTML = sim.playing ? "&#10074;&#10074; Pause" : "&#9654; Play";
    const clk = $("inside-clock");
    if (clk) clk.textContent = `Step ${idx + 1} / ${SCENES.length} · ${sim.elapsed.toFixed(1)}s / ${TOTAL_DUR.toFixed(0)}s`;
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
      sim.clock += dt;
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
    sim.rafId = requestAnimationFrame(tick);
  }

  function ensureLoop() {
    cancelAnimationFrame(sim.rafId);
    sim.lastTs = performance.now();
    renderFrame();
    if (sim.openFlag) sim.rafId = requestAnimationFrame(tick);
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
        if (ctxData.coverUrl) {
          const im = new Image();
          im.onload = () => {
            sim.coverImg = im;
            renderFrame();
          };
          im.src = ctxData.coverUrl;
        }
        if (ctxData.wmUrl) {
          const wm = new Image();
          wm.onload = () => {
            sim.wmImg = wm;
            renderFrame();
          };
          wm.src = ctxData.wmUrl;
        }
        if (Array.isArray(ctxData.pixels) && ctxData.pixels.length === 4) sim.data.pixels = ctxData.pixels;
        if (Number.isFinite(ctxData.aa)) sim.data.aa = ctxData.aa;
        if (Array.isArray(ctxData.watermark) && ctxData.watermark.length === 8) sim.data.watermark = ctxData.watermark;
        if (Array.isArray(ctxData.watermarkedPixels) && ctxData.watermarkedPixels.length === 4) {
          sim.data.watermarkedPixels = ctxData.watermarkedPixels;
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
      if (btn) btn.textContent = sim.paperLabels ? "Paper Terms: On" : "Paper Terms: Off";
      renderFrame();
    },
    scrubRatio(r) {
      const safeR = Number.isFinite(r) ? r : 0;
      sim.elapsed = clamp01(safeR) * (TOTAL_DUR - 0.01);
      ensureLoop();
    },
  };
})();
