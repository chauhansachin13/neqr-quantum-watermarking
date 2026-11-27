"use strict";
// Interactive canvas animation explaining NEQR watermarking internals from Sahu et al. (Array 31, 2026) + v2/v3.

(function () {
  const SCENE_DUR = 5.6; // seconds per scene
  const SCENES = [
    {
      title: "1. Photo -> Quantum Memory (NEQR)",
      ref: "Sec. 2.1 · Eq. (1)",
      summary: "Your photo splits into tiny 2×2 pixel blocks. 2 position qubits put all 4 pixels in superposition at once while 8 brightness qubits store each pixel's grayscale number.",
    },
    {
      title: "2. Building the Invisible Fingerprint (Wb)",
      ref: "Sec. 3.1 · Fig. 6",
      summary: "Quantum gates read position features (PPB), compute the block's average brightness (Adder + D4 Divider), and XOR them into an 8-bit secret fingerprint (Wb) unique to this exact spot.",
    },
    {
      title: "3. Hiding It Invisibly & Optimizing Clarity",
      ref: "Sec. 3.2 · Table 3 & v3 OPAP",
      summary: "RPA -> XOR -> QE checks if the tiny bottom bits match Wb and flips mismatched bits cleanly with Pauli-X. v3 OPAP then nudges pixels by ±4 so your eyes see zero difference (~46.4 dB PSNR).",
    },
    {
      title: "4. Spreading Backup Clones Across the Photo",
      ref: "v2 Keyed & v3 Dual 8×8 Haar",
      summary: "Each 8×8 tile gets a tamper-proof keyed lock (Toeplitz MAC) and mails compressed mini-backups of itself to two distant partner blocks across your image.",
    },
    {
      title: "5. Catching Forgeries & Healing Damage",
      ref: "Sec. 3.3 & v3 15q Grover Search",
      summary: "When someone edits or erases part of the photo, the lock fails, Grover quantum search zeroes in on tampered blocks (15.38× boost), and backup clones fly back to heal the hole 100%.",
    },
    {
      title: "6. Exact Reverse Proof U† & AI Detective",
      ref: "Eqs. (12–16) & Sec. 4.8 OOD",
      summary: "Because every gate is reversible (U†|W⟩ = |C⟩⊗|Wb⟩), running the circuit backward restores original pixels perfectly — and the AI classifier identifies what attack tool was used.",
    },
  ];

  const TOTAL_DUR = SCENES.length * SCENE_DUR;
  const $ = (id) => document.getElementById(id);

  const sim = {
    openFlag: false,
    playing: false,
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
      ppb: [[1, 1], [0, 0], [0, 0], [0, 1]],
      sum: 190,
      aa: 48,
      watermark: [1, 1, 0, 0, 1, 1, 0, 1],
      watermarkedPixels: [49, 63, 51, 35],
      unitaryInverse: true,
    },
  };

  const C_BG = "#090807";
  const C_PANEL = "#15120f";
  const C_WIRE = "#3a342c";
  const C_CREAM = "#f2ecdf";
  const C_GOLD = "#dcc5a4";
  const C_AMBER = "#f5b864";
  const C_OK = "#4ade80";
  const C_BAD = "#f87171";
  const C_VIOLET = "#c4b5fd";
  const C_MUTED = "#9e9689";

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

  function drawGate(ctx, x, y, w, h, label, active = 0, accent = C_GOLD) {
    ctx.save();
    ctx.fillStyle = active > 0.1 ? `rgba(220,197,164,${0.14 + 0.18 * active})` : "#181512";
    ctx.strokeStyle = active > 0.1 ? accent : "#433c33";
    ctx.lineWidth = active > 0.1 ? 2 : 1.2;
    roundRect(ctx, x, y, w, h, 8);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = active > 0.1 ? "#ffffff" : C_GOLD;
    ctx.font = "600 12px 'JetBrains Mono', monospace";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(label, x + w / 2, y + h / 2);
    ctx.restore();
  }

  function drawPulse(ctx, x1, y1, x2, y2, t, color = C_AMBER, radius = 4.5) {
    const u = clamp01(t);
    if (u <= 0 || u >= 1) return;
    const x = lerp(x1, x2, u);
    const y = lerp(y1, y2, u);
    ctx.save();
    ctx.fillStyle = color;
    ctx.shadowColor = color;
    ctx.shadowBlur = 12;
    ctx.beginPath();
    ctx.arc(x, y, radius, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  }

  function drawHeader(ctx, W, idx, sceneP) {
    ctx.fillStyle = C_GOLD;
    ctx.font = "600 11px 'JetBrains Mono', monospace";
    ctx.textAlign = "left";
    ctx.fillText(`STAGE 0${idx + 1} / 06  ·  ${SCENES[idx].ref.toUpperCase()}`, 32, 34);

    ctx.fillStyle = "#ffffff";
    ctx.font = "400 22px 'Inter', sans-serif";
    ctx.fillText(SCENES[idx].title, 32, 62);

    ctx.fillStyle = C_MUTED;
    ctx.font = "500 11px 'JetBrains Mono', monospace";
    ctx.textAlign = "right";
    ctx.fillText(`Cover: ${sim.data.imageName}  ·  Block (${sim.data.row}, ${sim.data.col})`, W - 32, 34);

    // Subtle divider line with progress sweep
    ctx.strokeStyle = "#26211b";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(32, 78);
    ctx.lineTo(W - 32, 78);
    ctx.stroke();

    ctx.strokeStyle = C_AMBER;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(32, 78);
    ctx.lineTo(32 + (W - 64) * sceneP, 78);
    ctx.stroke();
  }

  // ------------------------------------------------------------------ SCENE 1: NEQR Grid & Superposition
  function drawScene1(ctx, W, H, p) {
    const d = sim.data;
    const z = ease(clamp01(p * 1.4));

    // Left: Image preview + zooming 2x2 patch
    const imgX = 36, imgY = 108, imgS = 220;
    ctx.save();
    roundRect(ctx, imgX, imgY, imgS, imgS, 8);
    ctx.clip();
    if (sim.imgObj && sim.imgObj.complete) {
      ctx.drawImage(sim.imgObj, imgX, imgY, imgS, imgS);
    } else {
      ctx.fillStyle = "#26201a";
      ctx.fillRect(imgX, imgY, imgS, imgS);
    }
    ctx.fillStyle = "rgba(9,8,7,0.34)";
    ctx.fillRect(imgX, imgY, imgS, imgS);
    ctx.restore();

    ctx.strokeStyle = "#463d32";
    ctx.lineWidth = 1.2;
    roundRect(ctx, imgX, imgY, imgS, imgS, 8);
    ctx.stroke();

    // Reticle over picked block
    const rx = imgX + 64 + 60 * (1 - z * 0.15);
    const ry = imgY + 62 + 40 * (1 - z * 0.15);
    ctx.strokeStyle = C_AMBER;
    ctx.lineWidth = 2;
    ctx.strokeRect(rx, ry, 28, 28);

    // Zoomed 2x2 Matrix beside it
    const bx = 296, by = 138, cell = 74;
    ctx.strokeStyle = "rgba(245,184,100,0.45)";
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(rx + 28, ry);
    ctx.lineTo(bx, by);
    ctx.moveTo(rx + 28, ry + 28);
    ctx.lineTo(bx, by + cell * 2);
    ctx.stroke();
    ctx.setLineDash([]);

    const posLabels = ["|00⟩", "|01⟩", "|10⟩", "|11⟩"];
    for (let i = 0; i < 4; i++) {
      const cx = bx + (i % 2) * cell;
      const cy = by + Math.floor(i / 2) * cell;
      const reveal = ease(clamp01((p - i * 0.08) * 2.2));
      const v = d.pixels[i];
      ctx.fillStyle = `rgb(${v},${v},${v})`;
      ctx.globalAlpha = 0.25 + 0.75 * reveal;
      ctx.fillRect(cx + 2, cy + 2, cell - 4, cell - 4);
      ctx.globalAlpha = 1;
      ctx.strokeStyle = C_GOLD;
      ctx.strokeRect(cx + 2, cy + 2, cell - 4, cell - 4);

      ctx.fillStyle = v > 140 ? "#11100e" : "#ffffff";
      ctx.font = "700 16px 'JetBrains Mono', monospace";
      ctx.textAlign = "center";
      ctx.fillText(String(v), cx + cell / 2, cy + cell / 2 - 4);
      ctx.font = "500 10px 'JetBrains Mono', monospace";
      ctx.fillText(posLabels[i], cx + cell / 2, cy + cell / 2 + 16);
    }
    ctx.fillStyle = C_MUTED;
    ctx.font = "500 11px 'Inter', sans-serif";
    ctx.textAlign = "left";
    ctx.fillText("Zoomed 2×2 Pixel Block |C⟩", bx, by - 14);

    // Right: NEQR Quantum Lanes (H⊗H + 8 bit qubits)
    const qx = 490, qy = 122;
    drawGate(ctx, qx, qy + 52, 54, 150, "H⊗H", clamp01(p * 3), C_AMBER);
    ctx.fillStyle = C_CREAM;
    ctx.font = "500 11px 'JetBrains Mono', monospace";
    ctx.textAlign = "center";
    ctx.fillText("Position |yx⟩", qx + 27, qy + 225);

    for (let i = 0; i < 4; i++) {
      const ly = qy + 34 + i * 74;
      const laneP = ease(clamp01((p - 0.18 - i * 0.08) * 2.1));
      ctx.strokeStyle = C_WIRE;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(qx + 54, ly + 18);
      ctx.lineTo(W - 44, ly + 18);
      ctx.stroke();

      drawPulse(ctx, qx + 54, ly + 18, W - 48, ly + 18, (p * 1.4 - i * 0.1) % 1, C_AMBER);

      ctx.fillStyle = C_GOLD;
      ctx.font = "600 12px 'JetBrains Mono', monospace";
      ctx.textAlign = "left";
      ctx.fillText(`${posLabels[i]}  amp=0.50`, qx + 70, ly + 6);

      // 8-bit register display
      const bits = d.binary[i] || "00000000";
      for (let b = 0; b < 8; b++) {
        const bitX = qx + 195 + b * 29;
        const isPPB = b === 5 || b === 6; // bits 2 & 1
        const isLSB = b >= 6;
        ctx.fillStyle = laneP > 0.1 ? (isPPB ? "rgba(245,184,100,0.22)" : isLSB ? "rgba(74,222,128,0.16)" : "#191612") : "#12100d";
        ctx.strokeStyle = isPPB ? C_AMBER : isLSB ? C_OK : "#3c352d";
        roundRect(ctx, bitX, ly + 4, 24, 26, 5);
        ctx.fill();
        ctx.stroke();
        ctx.fillStyle = "#ffffff";
        ctx.font = "700 12px 'JetBrains Mono', monospace";
        ctx.textAlign = "center";
        ctx.fillText(bits[b], bitX + 12, ly + 17);
      }
    }

    ctx.fillStyle = C_MUTED;
    ctx.font = "500 11px 'JetBrains Mono', monospace";
    ctx.textAlign = "left";
    ctx.fillText("|C⟩ = ½ ∑ |q₇…q₀⟩ ⊗ |yx⟩   ·   Amber: bits 2,1 (PPB)   ·   Green: 2 LSB host slots", 36, H - 24);
  }

  // ------------------------------------------------------------------ SCENE 2: Watermark Generation
  function drawScene2(ctx, W, H, p) {
    const d = sim.data;
    const ppbStrs = d.ppb.map((x) => `${x[0]}${x[1]}`);
    const aaBits = (d.aa & 0xff).toString(2).padStart(8, "0");

    // Wires across 4 pixel branches + AA branch
    const y0 = 135;
    for (let i = 0; i < 4; i++) {
      const y = y0 + i * 54;
      ctx.strokeStyle = C_WIRE;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(46, y);
      ctx.lineTo(820, y);
      ctx.stroke();

      ctx.fillStyle = "#fff";
      ctx.font = "600 12px 'JetBrains Mono', monospace";
      ctx.textAlign = "left";
      ctx.fillText(`P${i}=${d.pixels[i]}`, 46, y - 12);

      drawGate(ctx, 130, y - 18, 84, 36, "RPA", clamp01((p - i * 0.05) * 3.5), C_AMBER);
      drawPulse(ctx, 60, y, 214, y, p * 2.8 - i * 0.1, C_AMBER);

      // PPB token emerging
      if (p > 0.25) {
        ctx.fillStyle = C_AMBER;
        ctx.font = "700 12px 'JetBrains Mono', monospace";
        ctx.textAlign = "center";
        ctx.fillText(`PPB ${ppbStrs[i]}`, 270, y - 13);
      }
      drawPulse(ctx, 214, y, 610, y, (p - 0.25) * 2.1, C_AMBER);
    }

    // Quantum Sum & Divider D4
    drawGate(ctx, 336, 128, 108, 198, `∑ Sum=${d.sum}`, clamp01((p - 0.18) * 3), C_VIOLET);
    drawGate(ctx, 476, 178, 114, 96, `D4 → AA=${d.aa}`, clamp01((p - 0.36) * 3), C_VIOLET);
    drawPulse(ctx, 444, 226, 476, 226, (p - 0.32) * 3, C_VIOLET);
    drawPulse(ctx, 590, 226, 650, 226, (p - 0.45) * 3, C_VIOLET);

    // XOR combiner
    drawGate(ctx, 646, 122, 102, 210, "PPB ⊕ AA", clamp01((p - 0.52) * 3), C_OK);

    // Final 8-bit Watermark Banner
    const wRev = ease(clamp01((p - 0.56) * 2.5));
    const rx = 776, ry = 132;
    ctx.fillStyle = C_PANEL;
    ctx.strokeStyle = wRev > 0.2 ? C_OK : "#332d25";
    ctx.lineWidth = 1.6;
    roundRect(ctx, rx, ry, 152, 192, 12);
    ctx.fill();
    ctx.stroke();

    ctx.fillStyle = C_GOLD;
    ctx.font = "600 11px 'JetBrains Mono', monospace";
    ctx.textAlign = "center";
    ctx.fillText("8-BIT WATERMARK", rx + 76, ry + 26);

    ctx.fillStyle = C_MUTED;
    ctx.font = "500 10px 'JetBrains Mono', monospace";
    ctx.fillText(`AA: ${aaBits}`, rx + 76, ry + 48);

    const wb = d.watermark.join("");
    for (let k = 0; k < 8; k++) {
      const col = k % 4, row = Math.floor(k / 4);
      const bx = rx + 18 + col * 30, by = ry + 72 + row * 44;
      const bitOn = p > 0.6 + k * 0.03;
      ctx.fillStyle = bitOn ? "rgba(74,222,128,0.22)" : "#1f1b16";
      ctx.strokeStyle = bitOn ? C_OK : "#3a342c";
      roundRect(ctx, bx, by, 24, 30, 5);
      ctx.fill();
      ctx.stroke();
      ctx.fillStyle = "#fff";
      ctx.font = "700 14px 'JetBrains Mono', monospace";
      ctx.fillText(wb[k], bx + 12, by + 16);
    }

    // Bottom Qubit Efficiency Bar Comparison
    const bars = [
      { label: "v1 Paper Reference", q: 146, col: "#71695e", note: "146 qubits · depth 157" },
      { label: "v2 Lean Cuccaro", q: 44, col: C_GOLD, note: "44 qubits · −70% width" },
      { label: "v3 Shallow Brent-Kung CLA", q: 69, col: C_OK, note: "69 qubits · depth 485 vs 888" },
    ];
    bars.forEach((b, idx) => {
      const by = H - 118 + idx * 32;
      const animW = (b.q / 150) * 320 * ease(clamp01((p - 0.15) * 1.8));
      ctx.fillStyle = C_CREAM;
      ctx.font = "500 11.5px 'Inter', sans-serif";
      ctx.textAlign = "left";
      ctx.fillText(b.label, 48, by + 10);
      ctx.fillStyle = "#1d1a16";
      roundRect(ctx, 250, by, 320, 14, 999);
      ctx.fill();
      ctx.fillStyle = b.col;
      roundRect(ctx, 250, by, Math.max(8, animW), 14, 999);
      ctx.fill();
      ctx.fillStyle = C_MUTED;
      ctx.font = "500 11px 'JetBrains Mono', monospace";
      ctx.fillText(b.note, 586, by + 11);
    });
  }

  // ------------------------------------------------------------------ SCENE 3: Reversible Embedding & OPAP
  function drawScene3(ctx, W, H, p) {
    const d = sim.data;
    const gx = 46, gy = 165;

    ctx.strokeStyle = C_WIRE;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(gx, gy);
    ctx.lineTo(585, gy);
    ctx.moveTo(gx, gy + 74);
    ctx.lineTo(585, gy + 74);
    ctx.stroke();

    ctx.fillStyle = C_CREAM;
    ctx.font = "600 12px 'JetBrains Mono', monospace";
    ctx.textAlign = "left";
    ctx.fillText("Cover LSB (q₀,q₁)", gx, gy - 16);
    ctx.fillText("Watermark Wb", gx, gy + 58);

    drawGate(ctx, 132, gy - 22, 86, 44, "RPA", clamp01(p * 3.5), C_AMBER);
    drawGate(ctx, 248, gy - 22, 86, 44, "XOR", clamp01((p - 0.2) * 3.5), C_AMBER);
    drawGate(ctx, 364, gy - 22, 92, 118, "QE (== ?)", clamp01((p - 0.4) * 3.5), C_VIOLET);

    const mismatch = (d.pixels[0] & 1) !== d.watermark[0];
    drawGate(ctx, 488, gy - 22, 84, 44, mismatch ? "Pauli-X" : "Identity", clamp01((p - 0.6) * 3.5), mismatch ? C_BAD : C_OK);

    drawPulse(ctx, gx, gy, 572, gy, p * 1.5, C_AMBER);
    drawPulse(ctx, gx, gy + 74, 410, gy + 74, p * 1.8, C_OK);

    // Pixel state before -> after
    const boxY = 305;
    for (let i = 0; i < 4; i++) {
      const bx = 46 + i * 132;
      const flipped = p > 0.65;
      const val = flipped ? d.watermarkedPixels[i] : d.pixels[i];
      ctx.fillStyle = C_PANEL;
      ctx.strokeStyle = flipped ? C_OK : "#3a342c";
      roundRect(ctx, bx, boxY, 116, 86, 10);
      ctx.fill();
      ctx.stroke();
      ctx.fillStyle = C_MUTED;
      ctx.font = "500 10px 'JetBrains Mono', monospace";
      ctx.textAlign = "center";
      ctx.fillText(`Pixel P${i}`, bx + 58, boxY + 20);
      ctx.fillStyle = "#ffffff";
      ctx.font = "700 22px 'JetBrains Mono', monospace";
      ctx.fillText(String(val), bx + 58, boxY + 50);
      ctx.fillStyle = flipped ? C_OK : C_GOLD;
      ctx.font = "500 10px 'JetBrains Mono', monospace";
      ctx.fillText(flipped ? `Δ=${val - d.pixels[i] >= 0 ? "+" : ""}${val - d.pixels[i]}` : "carrier", bx + 58, boxY + 72);
    }

    // Right panel: v3 OPAP & 81-Coset optimization visual
    const ox = 610, oy = 116, ow = 314, oh = 285;
    ctx.fillStyle = C_PANEL;
    ctx.strokeStyle = "#2b251e";
    roundRect(ctx, ox, oy, ow, oh, 12);
    ctx.fill();
    ctx.stroke();

    ctx.fillStyle = C_GOLD;
    ctx.font = "600 11px 'JetBrains Mono', monospace";
    ctx.textAlign = "left";
    ctx.fillText("v3 OPAP / ±4 COSET OPTIMIZATION", ox + 18, oy + 28);

    const optBars = [
      { label: "Paper Literal Rule", db: 41.1, w: 0.45, c: "#71695e" },
      { label: "Standard 2-LSB", db: 44.2, w: 0.72, c: C_GOLD },
      { label: "v3 OPAP / Keyed-Opt", db: 46.4, w: 0.96, c: C_OK },
    ];
    optBars.forEach((o, k) => {
      const y = oy + 62 + k * 68;
      ctx.fillStyle = "#fff";
      ctx.font = "500 12px 'Inter', sans-serif";
      ctx.fillText(`${o.label}`, ox + 18, y);
      ctx.fillStyle = o.c;
      ctx.font = "700 13px 'JetBrains Mono', monospace";
      ctx.textAlign = "right";
      ctx.fillText(`${o.db.toFixed(1)} dB`, ox + ow - 18, y);
      ctx.textAlign = "left";
      ctx.fillStyle = "#24201a";
      roundRect(ctx, ox + 18, y + 10, ow - 36, 12, 999);
      ctx.fill();
      ctx.fillStyle = o.c;
      roundRect(ctx, ox + 18, y + 10, (ow - 36) * o.w * ease(clamp01((p - 0.1 * k) * 2)), 12, 999);
      ctx.fill();
    });

    ctx.fillStyle = C_MUTED;
    ctx.font = "500 11px 'Inter', sans-serif";
    ctx.fillText("Closest intensity keeping same 2 LSBs", ox + 18, oy + oh - 22);
  }

  // ------------------------------------------------------------------ SCENE 4: Blind MAC & Partner Links
  function drawScene4(ctx, W, H, p) {
    const gx = 48, gy = 112, gs = 290;
    ctx.save();
    roundRect(ctx, gx, gy, gs, gs, 10);
    ctx.clip();
    if (sim.imgObj && sim.imgObj.complete) ctx.drawImage(sim.imgObj, gx, gy, gs, gs);
    ctx.fillStyle = "rgba(9,8,7,0.45)";
    ctx.fillRect(gx, gy, gs, gs);

    // 8x8 block grid overlay
    ctx.strokeStyle = "rgba(220,197,164,0.22)";
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
    ctx.restore();
    roundRect(ctx, gx, gy, gs, gs, 10);
    ctx.strokeStyle = "#3f382e";
    ctx.stroke();

    // Source block S -> Partner P1 (Primary 68b) & Partner P2 (Secondary 44b)
    const sx = gx + 1.5 * step, sy = gy + 2.5 * step;
    const p1x = gx + 6.5 * step, p1y = gy + 1.5 * step;
    const p2x = gx + 5.5 * step, p2y = gy + 6.5 * step;

    ctx.fillStyle = "rgba(245,184,100,0.4)";
    ctx.strokeStyle = C_AMBER;
    ctx.lineWidth = 2;
    ctx.fillRect(sx - step / 2, sy - step / 2, step, step);
    ctx.strokeRect(sx - step / 2, sy - step / 2, step, step);

    // Animated quadratic arcs to deranged partners
    const arcProg1 = ease(clamp01((p - 0.15) * 2.2));
    const arcProg2 = ease(clamp01((p - 0.3) * 2.2));

    function drawArc(x1, y1, cx, cy, x2, y2, prog, col, lbl) {
      ctx.save();
      ctx.strokeStyle = col;
      ctx.lineWidth = 2.2;
      ctx.setLineDash([280]);
      ctx.lineDashOffset = 280 * (1 - prog);
      ctx.beginPath();
      ctx.moveTo(x1, y1);
      ctx.quadraticCurveTo(cx, cy, x2, y2);
      ctx.stroke();
      ctx.setLineDash([]);
      if (prog > 0.75) {
        ctx.fillStyle = col;
        ctx.fillRect(x2 - step / 2, y2 - step / 2, step, step);
        ctx.fillStyle = "#090807";
        ctx.font = "700 11px 'JetBrains Mono', monospace";
        ctx.textAlign = "center";
        ctx.fillText(lbl, x2, y2 + 4);
      }
      ctx.restore();
    }

    drawArc(sx, sy, gx + 4 * step, gy - 10, p1x, p1y, arcProg1, C_AMBER, "P1");
    drawArc(sx, sy, gx + 3 * step, gy + 5.5 * step, p2x, p2y, arcProg2, C_VIOLET, "P2");

    // Right side breakdown card: 128-bit 8x8 Payload Budget
    const rx = 384, ry = 112, rw = 540, rh = 290;
    ctx.fillStyle = C_PANEL;
    ctx.strokeStyle = "#2b251e";
    roundRect(ctx, rx, ry, rw, rh, 12);
    ctx.fill();
    ctx.stroke();

    ctx.fillStyle = C_GOLD;
    ctx.font = "600 11px 'JetBrains Mono', monospace";
    ctx.textAlign = "left";
    ctx.fillText("DUAL-PARTNER 8×8 PAYLOAD BUDGET (128 LSB SLOTS)", rx + 22, ry + 32);

    // 128-bit split bar (68 + 44 + 16)
    const bx = rx + 22, by = ry + 60, bw = rw - 44;
    const barReveal = ease(clamp01(p * 2));
    const segs = [
      { frac: 68 / 128, label: "Primary Haar (68b)", col: C_AMBER },
      { frac: 44 / 128, label: "Backup Haar (44b)", col: C_VIOLET },
      { frac: 16 / 128, label: "Toeplitz MAC (16b)", col: C_OK },
    ];
    let curX = bx;
    segs.forEach((s) => {
      const w = bw * s.frac * barReveal;
      ctx.fillStyle = s.col;
      ctx.fillRect(curX, by, Math.max(0, w - 3), 28);
      curX += w;
    });

    segs.forEach((s, idx) => {
      const ly = ry + 116 + idx * 48;
      ctx.fillStyle = s.col;
      ctx.beginPath();
      ctx.arc(bx + 8, ly + 8, 5, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = "#fff";
      ctx.font = "600 13px 'Inter', sans-serif";
      ctx.fillText(s.label, bx + 24, ly + 12);
      ctx.fillStyle = C_MUTED;
      ctx.font = "400 12px 'Inter', sans-serif";
      const desc =
        idx === 0
          ? "Companded low-res quadrant code sent to Primary Partner P1"
          : idx === 1
            ? "Independent secondary copy sent to disjoint Partner P2"
            : "Keyed SHAKE-256 tag (only 2⁻¹⁶ chance a forgery passes blind verify)";
      ctx.fillText(desc, bx + 24, ly + 30);
    });
  }

  // ------------------------------------------------------------------ SCENE 5: Forgery, Grover Search & Self-Healing
  function drawScene5(ctx, W, H, p) {
    const gx = 46, gy = 112, gs = 290;
    const attackPhase = clamp01(p / 0.34);
    const groverPhase = clamp01((p - 0.3) / 0.38);
    const healPhase = ease(clamp01((p - 0.65) / 0.35));

    ctx.save();
    roundRect(ctx, gx, gy, gs, gs, 10);
    ctx.clip();
    if (sim.imgObj && sim.imgObj.complete) ctx.drawImage(sim.imgObj, gx, gy, gs, gs);

    // Cutout damage fading out as healPhase -> 1
    const dmgX = gx + 75, dmgY = gy + 82, dmgS = 110;
    const dmgAlpha = attackPhase * (1 - healPhase);
    if (dmgAlpha > 0.02) {
      ctx.fillStyle = `rgba(10, 8, 7, ${0.92 * dmgAlpha})`;
      ctx.fillRect(dmgX, dmgY, dmgS, dmgS);
      ctx.strokeStyle = `rgba(248, 113, 113, ${dmgAlpha})`;
      ctx.lineWidth = 2.2;
      ctx.strokeRect(dmgX, dmgY, dmgS, dmgS);
    }
    ctx.restore();

    roundRect(ctx, gx, gy, gs, gs, 10);
    ctx.strokeStyle = healPhase > 0.85 ? C_OK : attackPhase > 0.5 ? C_BAD : "#3f382e";
    ctx.lineWidth = 1.6;
    ctx.stroke();

    // Flying recovery streams during healing phase
    if (p > 0.62 && healPhase < 0.98) {
      drawPulse(ctx, gx + 250, gy + 45, dmgX + dmgS / 2, dmgY + dmgS / 2, healPhase, C_OK, 5.5);
      drawPulse(ctx, gx + 225, gy + 245, dmgX + dmgS / 2, dmgY + dmgS / 2, healPhase, C_AMBER, 5.5);
    }

    ctx.fillStyle = healPhase > 0.85 ? C_OK : C_BAD;
    ctx.font = "600 12px 'JetBrains Mono', monospace";
    ctx.textAlign = "left";
    ctx.fillText(
      healPhase > 0.85 ? "HEALED: 100% RESTORED FROM PARTNER CODES" : attackPhase > 0.4 ? "TAMPER DETECTED: MAC MISMATCH" : "BLACKOUT ATTACK INCOMING",
      gx,
      H - 36
    );

    // Right Panel: 15-qubit Grover Amplitude Amplification
    const rx = 382, ry = 112, rw = 544, rh = 290;
    ctx.fillStyle = C_PANEL;
    ctx.strokeStyle = "#2b251e";
    roundRect(ctx, rx, ry, rw, rh, 12);
    ctx.fill();
    ctx.stroke();

    const iters = Math.min(3, Math.floor(groverPhase * 3.9));
    const targetProb = lerp(1 / 16, 0.9613, ease(groverPhase));
    const otherProb = (1 - targetProb) / 15;

    ctx.fillStyle = C_GOLD;
    ctx.font = "600 11px 'JetBrains Mono', monospace";
    ctx.fillText(`v3 15-QUBIT GROVER TAMPER SEARCH  ·  ITERATION ${iters} / 3`, rx + 22, ry + 30);

    ctx.fillStyle = "#ffffff";
    ctx.font = "600 14px 'Inter', sans-serif";
    ctx.fillText(`Flagged pixel mass: ${(targetProb * 100).toFixed(1)}%  (${(targetProb * 16).toFixed(2)}× gain)`, rx + 22, ry + 54);

    // 16 pixel probability bars
    const bx0 = rx + 22, byBase = ry + 236, maxH = 148;
    for (let i = 0; i < 16; i++) {
      const isTarget = i === 9; // coord (2,1)
      const val = isTarget ? targetProb : otherProb;
      const bh = Math.max(4, val * maxH);
      const bx = bx0 + i * 31;
      ctx.fillStyle = isTarget ? C_AMBER : "#3a342c";
      roundRect(ctx, bx, byBase - bh, 22, bh, 4);
      ctx.fill();
      if (isTarget) {
        ctx.fillStyle = C_AMBER;
        ctx.font = "700 10px 'JetBrains Mono', monospace";
        ctx.textAlign = "center";
        ctx.fillText("(2,1)", bx + 11, byBase + 16);
      }
    }
    ctx.textAlign = "left";
    ctx.fillStyle = C_MUTED;
    ctx.font = "400 11.5px 'Inter', sans-serif";
    ctx.fillText("O(√N) oracle flips phase on tampered PPB ≠ LSB; diffuser boosts probability.", rx + 22, ry + rh - 20);
  }

  // ------------------------------------------------------------------ SCENE 6: Exact Unitary Reverse U† & AI Forensics
  function drawScene6(ctx, W, H, p) {
    // Top Half: Mirror Unitary Inverse Circuit
    ctx.fillStyle = C_GOLD;
    ctx.font = "600 11px 'JetBrains Mono', monospace";
    ctx.textAlign = "left";
    ctx.fillText("EXACT UNITARY REVERSIBILITY  U† |W⟩ = |C⟩ ⊗ |Wb⟩  (EQS. 12–16)", 46, 114);

    const gatesRev = ["Pauli-X†", "QE†", "XOR†", "RPA†"];
    const wy = 166;
    ctx.strokeStyle = C_WIRE;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(46, wy);
    ctx.lineTo(W - 46, wy);
    ctx.stroke();

    gatesRev.forEach((lbl, idx) => {
      const x = 180 + idx * 145;
      const revAct = clamp01((p - (3 - idx) * 0.14) * 3);
      drawGate(ctx, x, wy - 20, 108, 40, lbl, revAct, C_OK);
    });
    // Pulse traveling RIGHT -> LEFT in inverse mode!
    drawPulse(ctx, W - 120, wy, 90, wy, (p * 1.4) % 1, C_OK, 5);

    ctx.fillStyle = C_OK;
    ctx.font = "600 12px 'JetBrains Mono', monospace";
    ctx.fillText(`Recovered Clean Pixels: [${sim.data.pixels.join(", ")}]   Ancilla Clean Prob: 1.0000`, 46, 224);

    // Bottom Half: 162-d AI Forensic Classifier & OOD Threshold
    const ay = 258, aw = W - 92, ah = 190;
    ctx.fillStyle = C_PANEL;
    ctx.strokeStyle = "#2b251e";
    roundRect(ctx, 46, ay, aw, ah, 12);
    ctx.fill();
    ctx.stroke();

    ctx.fillStyle = C_GOLD;
    ctx.font = "600 11px 'JetBrains Mono', monospace";
    ctx.fillText("162-D MULTI-DOMAIN RANDOM FOREST + CALIBRATED OOD DETECTOR", 68, ay + 28);

    const preds = [
      { name: "Blackout / Object Cutout", pct: 0.78, c: C_AMBER },
      { name: "Cropping", pct: 0.11, c: C_GOLD },
      { name: "LSB-Preserving Splice", pct: 0.06, c: C_VIOLET },
      { name: "Unknown / Out-of-Distribution Gate (0.42)", pct: 0.05, c: C_MUTED },
    ];
    preds.forEach((pr, idx) => {
      const by = ay + 54 + idx * 32;
      const fillP = ease(clamp01((p - 0.12 - idx * 0.08) * 2.2));
      ctx.fillStyle = idx === 0 ? "#ffffff" : C_CREAM;
      ctx.font = "500 12px 'Inter', sans-serif";
      ctx.textAlign = "left";
      ctx.fillText(pr.name, 68, by + 10);

      ctx.fillStyle = "#24201a";
      roundRect(ctx, 370, by, 430, 12, 999);
      ctx.fill();
      ctx.fillStyle = pr.c;
      roundRect(ctx, 370, by, Math.max(4, 430 * pr.pct * fillP), 12, 999);
      ctx.fill();

      ctx.fillStyle = "#fff";
      ctx.font = "600 11.5px 'JetBrains Mono', monospace";
      ctx.textAlign = "right";
      ctx.fillText(`${(pr.pct * 100 * fillP).toFixed(1)}%`, W - 70, by + 10);
    });
  }

  function renderFrame() {
    const canvas = $("inside-canvas");
    if (!canvas) return;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const W = 960, H = 500;
    if (canvas.width !== W * dpr || canvas.height !== H * dpr) {
      canvas.width = W * dpr;
      canvas.height = H * dpr;
    }
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    // Void-black stage backdrop with subtle golden ambient corner glow
    ctx.fillStyle = C_BG;
    ctx.fillRect(0, 0, W, H);
    const grad = ctx.createRadialGradient(W * 0.78, H * 0.14, 10, W * 0.78, H * 0.14, 420);
    grad.addColorStop(0, "rgba(218, 154, 78, 0.14)");
    grad.addColorStop(1, "transparent");
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, W, H);

    const idx = Math.min(SCENES.length - 1, Math.floor(sim.elapsed / SCENE_DUR));
    const localP = clamp01((sim.elapsed - idx * SCENE_DUR) / SCENE_DUR);

    drawHeader(ctx, W, idx, localP);
    if (idx === 0) drawScene1(ctx, W, H, localP);
    else if (idx === 1) drawScene2(ctx, W, H, localP);
    else if (idx === 2) drawScene3(ctx, W, H, localP);
    else if (idx === 3) drawScene4(ctx, W, H, localP);
    else if (idx === 4) drawScene5(ctx, W, H, localP);
    else drawScene6(ctx, W, H, localP);

    updateTransportUI(idx);
  }

  function updateTransportUI(idx) {
    const playBtn = $("inside-play");
    if (playBtn) playBtn.innerHTML = sim.playing ? "&#10074;&#10074; Pause" : "&#9654; Play";
    const clk = $("inside-clock");
    if (clk) clk.textContent = `Scene ${idx + 1} / ${SCENES.length} · ${sim.elapsed.toFixed(1)}s / ${TOTAL_DUR.toFixed(0)}s`;
    const fill = $("inside-scrub-fill");
    const pct = clamp01(sim.elapsed / TOTAL_DUR) * 100;
    if (fill) fill.style.width = `${pct}%`;
    const scrub = $("inside-scrub");
    if (scrub) scrub.setAttribute("aria-valuenow", String(Math.round(pct)));
    const capTitle = $("inside-cap-title");
    const capText = $("inside-cap-text");
    if (capTitle) capTitle.textContent = `${SCENES[idx].title} (${SCENES[idx].ref})`;
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
    scrubRatio(r) {
      sim.elapsed = clamp01(r) * (TOTAL_DUR - 0.01);
      ensureLoop();
    },
  };
})();
