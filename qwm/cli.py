"""Command-line interface: ``qwm <command> [options]``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from qwm.version import __version__

DEFAULT_OUT = Path("results")


def _images_arg(value: str | None, offline: bool = False) -> list[str]:
    from qwm.data import default_image_set

    if value:
        return [v.strip() for v in value.split(",") if v.strip()]
    return default_image_set(offline)


# --------------------------------------------------------------------------- #
def cmd_demo(args) -> int:
    from qwm.circuits import (
        WatermarkEmbeddingCircuit,
        WatermarkExtractionCircuit,
        WatermarkGenerationCircuit,
    )
    from qwm.watermark import block_trace, embed_pixel_trace, extract_pixel_trace

    block = np.array(json.loads(args.block)).reshape(2, 2)
    print(f"cover block |C> =\n{block}\n")
    trace = block_trace(block)
    print("Step 1-3  watermark generation (classical reference)")
    print(f"  PPB per pixel      : {trace['ppb']}")
    print(f"  block sum / AA     : {trace['sum']} / {trace['aa']}  (AA bits s0..s7 = {trace['aa_bits']})")
    print(f"  watermark Wb0..Wb7 : {trace['watermark']}\n")

    gen = WatermarkGenerationCircuit(block)
    g = gen.run()
    print(f"Qiskit generation circuit ({gen.circuit.num_qubits} qubits): PPB={g['ppb']} AA={g['aa']} Wb={g['watermark']}")
    emb = WatermarkEmbeddingCircuit(block, g["watermark"])
    e = emb.run()
    print(f"Qiskit embedding circuit  ({emb.circuit.num_qubits} qubits): |W> = {e['watermarked_pixels']}")
    ext = WatermarkExtractionCircuit(e["watermarked_block"], g["watermark"])
    x = ext.run()
    print(f"Qiskit extraction circuit ({ext.circuit.num_qubits} qubits): raw LSBs={x['raw_bits']} extracted Wb={x['extracted_bits']}\n")

    print("Step-wise embedding of the first pixel (Table 3):")
    for step in embed_pixel_trace(int(block[0, 0]), g["watermark"][0], g["watermark"][1])["steps"]:
        print(f"  bit {step['bit']}: RPA{step['rpa_inputs']} -> {step['rpa_result']}, XOR -> {step['xor_result']}, QE equal={step['qe_equal']}, Pauli-X={step['pauli_x_applied']}, embedded bit={step['embedded_bit']}")
    print("Step-wise extraction of the first watermarked pixel (Table 4):")
    for step in extract_pixel_trace(e["watermarked_pixels"][0], g["watermark"][:2])["steps"]:
        print(f"  bit {step['bit']}: XOR -> {step['xor_result']}, RPS -> {step['rps_result']}, QE equal={step['qe_equal']}, Pauli-X={step['pauli_x_applied']}, extracted bit={step['extracted_bit']}")

    from qwm.circuits import ShallowGenerationCircuit, run_neqr_ppb_superposition
    from qwm.circuits.lean import LeanGenerationCircuit

    unit = emb.verify_unitary_inverse()
    lg = LeanGenerationCircuit(block)
    sg = ShallowGenerationCircuit(block)
    sup = run_neqr_ppb_superposition(block.astype(np.uint8))
    print(f"\nPaper Eq.(12)-(16) unitary inverse U^dagger|W>=|C>(x)|Wb>: exact={unit['exact_unitary_inverse']}")
    print(f"v2 Lean generation    ({lg.circuit.num_qubits} qubits): Wb={lg.run()['watermark']} clean={lg.run()['ancillas_clean']}")
    print(f"v3 Shallow CLA gen    ({sg.circuit.num_qubits} qubits): Wb={sg.run()['watermark']} clean={sg.run()['ancillas_clean']}")
    print(f"v3 NEQR superposition ({sup['qubits']} qubits): exact_ppb={sup['exact_match']} uniform={sup['uniform']} ancilla_clean={sup['ancilla_clean_prob']:.6f}")
    return 0


KEYED_MODES = ("keyed", "keyed-opt", "recovery", "recovery-dual")


def _keyed_scheme(mode: str, key: str | None, nonce: str):
    from qwm.secure import (
        DualPartnerSelfRecoveringWatermark,
        SecureWatermark,
        SelfRecoveringWatermark,
    )

    if not key:
        raise SystemExit(f"--key is required for --mode {mode}")
    if mode == "keyed":
        return SecureWatermark(key, nonce)
    if mode == "keyed-opt":
        return SecureWatermark(key, nonce, optimize=True)
    if mode == "recovery":
        return SelfRecoveringWatermark(key, nonce)
    return DualPartnerSelfRecoveringWatermark(key, nonce)


def cmd_embed(args) -> int:
    from qwm.data import load_image_preserve, save_image
    from qwm.metrics.image import quality_report
    from qwm.watermark import embed_image

    is_file = Path(args.image).exists()
    size = None if (args.size == 0 or (args.size is None and is_file)) else (args.size or 256)
    cover = load_image_preserve(args.image, size=size, allow_color=(args.mode in KEYED_MODES))
    if args.mode in KEYED_MODES:
        watermarked, wb = _keyed_scheme(args.mode, args.key, args.nonce).embed(cover), None
    else:
        watermarked, wb = embed_image(cover, mode=args.mode)
    out = save_image(watermarked, args.output)
    q = quality_report(cover, watermarked)
    print(f"watermarked image written to {out}  (shape={cover.shape}, PSNR {q['psnr']:.2f} dB, SSIM {q['ssim']:.4f}, mode={args.mode})")
    if args.save_watermark and wb is not None:
        np.save(args.save_watermark, wb)
        print(f"watermark bits saved to {args.save_watermark} shape={wb.shape}")
    elif args.mode not in KEYED_MODES and not args.save_watermark:
        print("tip: pass --save-watermark wb.npy to verify later, or use --mode keyed-opt / recovery-dual for blind verification")
    elif args.mode in KEYED_MODES:
        print("blind scheme: verification needs only the key and nonce (no reference bits)")
    return 0


def cmd_verify(args) -> int:
    from qwm.data import load_image_preserve, save_image
    from qwm.studies import _overlay
    from qwm.watermark import extract_image, tamper_map

    is_keyed = args.mode in KEYED_MODES
    img = load_image_preserve(args.image, size=None, allow_color=is_keyed)
    if not is_keyed:
        if not args.reference:
            raise SystemExit(f"--reference <wb.npy> is required when verifying --mode {args.mode} (or use --mode keyed / recovery)")
        ref = np.load(args.reference)
        raw, _ = extract_image(img, ref)
        tamper = tamper_map(raw, ref)
        block = 2
        res = None
    else:
        scheme = _keyed_scheme(args.mode, args.key, args.nonce)
        if args.mode in ("keyed", "keyed-opt"):
            res = scheme.verify(img)
            tamper, block = res.tamper_map, 2
        elif args.mode == "recovery":
            res = scheme.recover(img)
            tamper, block = res.tamper_map, 4
        else:
            res = scheme.recover(img)
            tamper, block = res.tamper_map, 8
    n_bad, n = int(tamper.sum()), int(tamper.size)
    verdict = "AUTHENTIC" if n_bad == 0 else f"TAMPERED: {n_bad} of {n} blocks ({100 * n_bad / n:.2f} %) failed"
    print(f"{args.image}: {verdict}")
    if args.overlay:
        import cv2

        Path(args.overlay).parent.mkdir(parents=True, exist_ok=True)
        vis = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        cv2.imwrite(str(args.overlay), cv2.cvtColor(_overlay(vis, tamper, block), cv2.COLOR_RGB2BGR))
        print(f"tamper map written to {args.overlay}")
    if res is not None and args.mode in ("recovery", "recovery-dual") and n_bad and args.recovered:
        save_image(res.recovered, args.recovered)
        print(f"repaired image written to {args.recovered} ({100 * res.restored_fraction:.1f} % of failed blocks rebuilt from recovery codes)")
    return 0 if n_bad == 0 else 2


def cmd_extract(args) -> int:
    from qwm.data import load_image
    from qwm.watermark import (
        bit_error_rate,
        extract_image,
        normalized_correlation,
        tamper_map,
        watermark_to_image,
    )

    img = load_image(args.image, None)
    ref = np.load(args.reference) if args.reference else None
    raw, corrected = extract_image(img, ref)
    print(f"extracted {raw.shape[0]}x{raw.shape[1]} blocks x 8 bits")
    if ref is not None:
        print(f"BER (raw vs reference) = {bit_error_rate(raw, ref):.4f}, NC = {normalized_correlation(raw, ref):.4f}, tampered blocks = {int(tamper_map(raw, ref).sum())}")
    if args.output:
        from qwm.data import save_image

        save_image(watermark_to_image(raw), args.output)
        print(f"raw watermark bit-planes written to {args.output}")
    if args.save_bits:
        np.save(args.save_bits, raw)
    return 0


def cmd_evaluate(args) -> int:
    from qwm.experiments import imperceptibility

    df = imperceptibility(_images_arg(args.images, args.offline), size=args.size, out_dir=args.out)
    with_cols = ["image", "mode", "mse", "psnr_db", "ssim", "ssim_global", "ber_raw", "embed_time_s", "extract_time_s"]
    print(df[with_cols].to_string(index=False, float_format=lambda v: f"{v:.4f}"))
    return 0


def cmd_attacks(args) -> int:
    from qwm.experiments import robustness

    df = robustness(_images_arg(args.images, args.offline), mode=args.mode, size=args.size, out_dir=args.out)
    summary = df.groupby(["attack", "params"], sort=False)[["psnr_db", "ssim", "ber", "nc"]].mean().reset_index()
    print(summary.to_string(index=False, float_format=lambda v: f"{v:.4f}"))
    return 0


def cmd_quantum(args) -> int:
    from qwm.experiments import quantum_noise

    df = quantum_noise(_images_arg(args.images, args.offline), mode=args.mode, size=args.size, max_blocks=args.max_blocks, out_dir=args.out)
    print(df.to_string(index=False, float_format=lambda v: f"{v:.4f}"))
    return 0


def cmd_classify(args) -> int:
    from qwm.experiments import attack_classification

    if args.quick:
        args.samples_per_class = min(args.samples_per_class, 40)
        args.feature_size = min(args.feature_size or args.size, 64)
    summary = attack_classification(
        samples_per_class=args.samples_per_class,
        size=args.size,
        feature_size=args.feature_size,
        mode=args.mode,
        seed=args.seed,
        folds=args.folds,
        images=_images_arg(args.images, args.offline) if args.images or args.offline else None,
        out_dir=args.out,
        features=args.features,
        params=args.params,
    )
    r = summary["result"]
    print(f"\ntest accuracy {100 * r['accuracy']:.2f}% ({r['correct']}/{r['total']}), precision {100 * r['precision']:.2f}%, recall {100 * r['recall']:.2f}%, F1 {100 * r['f1']:.2f}%")
    lo, hi = r["confidence_interval_wald"]
    print(f"95% CI (Wald) {100 * lo:.2f}% - {100 * hi:.2f}%; binomial test vs chance ({100 * r['chance_level']:.2f}%): p = {r['binomial_p_value']:.2e}")
    if r["cv_scores"]:
        print(f"{len(r['cv_scores'])}-fold CV accuracy: {100 * np.mean(r['cv_scores']):.2f}% +/- {100 * np.std(r['cv_scores']):.2f}%")
    return 0


def cmd_resources(args) -> int:
    from qwm.experiments import resource_analysis

    data = resource_analysis(args.n, out_dir=args.out)
    rep = data["reported"]
    print(f"Reported (n={args.n}): qubits per module {rep['module_qubits']}; gate complexity {rep['module_gate_complexity']}")
    print(f"  generation {rep['watermark_generation']}\n  embedding  {rep['embedding']}\n  extraction {rep['extraction']}")
    print("Measured (v1 module-faithful block circuits):")
    for name, m in data["measured_block_circuits"].items():
        print(f"  {name:22s} qubits={m['qubits']:4d} (data {m['data_qubits']}, ancilla {m['ancilla_qubits']}) gates={m['reversible_gates']} depth={m['reversible_depth']} CNOT-level: {m['cnot_count']} CNOT, depth {m['cnot_level_depth']}")
    print("Comparison across circuit generations (2x2 block):")
    for row in data["measured_all_families"]:
        print(f"  {row['circuit']:26s} [{row['family']:10s}] qubits={row['qubits']:3d}  CNOT={row['cnot_count']:4d}  depth={row['cnot_level_depth']:4d}")
    print("Preparation complexity:", data["preparation_complexity"])
    return 0


def cmd_run(args) -> int:
    """Single-command guided tour of the paper + v2/v3 extensions."""
    import pandas as pd

    from qwm.data import load_image
    from qwm.metrics.image import quality_report
    from qwm.paper_checks import check_table9
    from qwm.resources import measure_all_families
    from qwm.secure import (
        DualPartnerSelfRecoveringWatermark,
        SecureWatermark,
        SelfRecoveringWatermark,
    )
    from qwm.tamper import apply_manipulation
    from qwm.watermark import embed_image

    image_name = (getattr(args, "image_opt", None) or getattr(args, "image", None) or "camera").strip() or "camera"

    print("=== 1/4 Worked Block (Sec. 3 / Fig. 6, 12, 13, 14) ===")
    cmd_demo(argparse.Namespace(block="[[50,60],[48,32]]"))

    print(f"\n=== 2/4 Imperceptibility & Self-Recovery on {image_name!r} ({args.size}x{args.size}) ===")
    img = load_image(image_name, args.size)
    rows = []
    for name, wm_img in [
        ("paper (v1)", embed_image(img, mode="paper")[0]),
        ("lsb (v1)", embed_image(img, mode="lsb")[0]),
        ("opap (v3)", embed_image(img, mode="opap")[0]),
        ("keyed (v2)", SecureWatermark("demo", "run").embed(img)),
        ("keyed-opt (v3)", SecureWatermark("demo", "run", optimize=True).embed(img)),
        ("recovery-4x4 (v2)", SelfRecoveringWatermark("demo", "run").embed(img)),
        ("recovery-dual (v3)", DualPartnerSelfRecoveringWatermark("demo", "run").embed(img)),
    ]:
        q = quality_report(img, wm_img)
        rows.append({"scheme": name, "psnr_db": q["psnr"], "ssim": q["ssim"], "mse": q["mse"]})
    print(pd.DataFrame(rows).to_string(index=False, float_format=lambda v: f"{v:.4f}"))

    du = DualPartnerSelfRecoveringWatermark("demo", "run")
    wm_d = du.embed(img)
    attacked, changed = apply_manipulation("blackout", wm_d, np.random.default_rng(7), img, fraction=0.25)
    rec = du.recover(attacked)
    print(
        f"Dual-partner 8x8 recovery (25% blackout): edited region {quality_report(img[changed], attacked[changed])['psnr']:.2f} dB "
        f"-> {quality_report(img[changed], rec.recovered[changed])['psnr']:.2f} dB ({100 * rec.restored_fraction:.1f}% restored from codes)"
    )

    print("\n=== 3/4 Quantum Circuit Families & NEQR Superposition ===")
    print(pd.DataFrame(measure_all_families()).to_string(index=False))
    cmd_superposition(argparse.Namespace(image=image_name, key="run-key", shots=128))

    print("\n=== 4/4 Paper Table 9 Consistency ===")
    t9 = check_table9()
    print(f"Verified {len(t9)} rows: {sum(not r['consistent'] for r in t9)} violate Fuchs-van de Graaf bounds.")
    return 0


def cmd_draw(args) -> int:
    from qwm.experiments import draw_circuits

    for p in draw_circuits(args.out):
        print(f"wrote {p}")
    return 0


def cmd_tamper_study(args) -> int:
    from qwm.studies import tamper_study

    out = tamper_study(_images_arg(args.images, args.offline), fraction=args.fraction, repeats=args.repeats, out_dir=args.out)
    piv = out["summary"].pivot(index="manipulation", columns="scheme", values="tpr")
    print("block-level detection rate (TPR); false-positive rate is 0 for every scheme on untouched blocks:")
    print(piv.to_string(float_format=lambda v: f"{v:.3f}"))
    print("\nself-recovery (PSNR in the edited region, dB):")
    print(out["recovery"][["manipulation", "psnr_attacked_region", "psnr_recovered_region", "restored_fraction"]].to_string(index=False, float_format=lambda v: f"{v:.2f}"))
    return 0


def cmd_nisq(args) -> int:
    from qwm.studies import DEFAULT_P2, nisq_study, thermal_nisq_study

    p_values = [float(v) for v in args.p2.split(",")] if args.p2 else DEFAULT_P2
    out = nisq_study(
        p_values,
        shots=args.shots,
        out_dir=args.out,
        verbose=True,
        workers=args.workers,
        include_shallow=getattr(args, "shallow", False),
    )
    print(out["resources"].to_string(index=False))
    print(out["thresholds"].to_string(index=False))
    if getattr(args, "thermal", False):
        df_th = thermal_nisq_study(shots=min(args.shots, 500), out_dir=args.out)
        print("\nT1/T2 ALAP thermal relaxation comparison:")
        print(df_th.to_string(index=False, float_format=lambda v: f"{v:.4f}"))
    return 0


def cmd_superposition(args) -> int:
    from qwm.circuits.superposition import (
        block_neqr_blind_verify,
        run_block_neqr_superposition,
        run_grover_tamper_search,
        run_neqr_ppb_superposition,
    )
    from qwm.data import load_image
    from qwm.secure import SecureWatermark
    from qwm.watermark.generation import pixel_position_bits

    patch = load_image(args.image, 16)[:4, :4]
    ppb_res = run_neqr_ppb_superposition(patch)
    auth = (patch & 0xFC).copy()
    for r in range(4):
        for c in range(4):
            b0, b1 = pixel_position_bits(int(auth[r, c]))
            auth[r, c] |= b0 | (b1 << 1)
    tampered = auth.copy()
    tampered[2, 1] ^= 0b01
    gr_res = run_grover_tamper_search(tampered)
    blk_res = run_block_neqr_superposition(patch, shots=args.shots)

    sw = SecureWatermark(args.key, "cli-superposition")
    wm = sw.embed(patch)
    wm[2:4, 0:2] ^= 0b11
    bv_res = block_neqr_blind_verify(wm, args.key, "cli-superposition", shots=args.shots)

    print(f"NEQR pixel PPB superposition (4x4, {ppb_res['qubits']}q Statevector): exact={ppb_res['exact_match']}, uniform={ppb_res['uniform']}, ancilla_clean={ppb_res['ancilla_clean_prob']:.6f}")
    print(f"NEQR Grover tamper search ({gr_res['qubits']}q, {gr_res['iterations']} iters): flagged={gr_res['flagged_coords']}, prob_mass={gr_res['tampered_probability_mass']:.4f}, gain={gr_res['amplification_gain']:.2f}x")
    print(f"Block-NEQR generation MPS ({blk_res['qubits']}q, {blk_res['n_blocks']} blocks): accuracy={blk_res['accuracy']:.4f}, all_blocks_seen={blk_res['all_blocks_seen']}")
    print(f"Block-NEQR blind verify MPS ({bv_res['qubits']}q, {bv_res['n_blocks']} blocks): accuracy={bv_res['accuracy']:.4f}, matches_classical={bv_res['matches_classical']}")
    return 0


def cmd_classifier_benchmark(args) -> int:
    from qwm.studies import classifier_study

    sizes = (64,) if args.quick else (64, 256)
    out = classifier_study(samples_per_class=args.samples_per_class, seed=args.seed, unseen_per_attack=args.unseen_per_attack, pixel_sizes=sizes, out_dir=args.out)
    m = out["models"]
    print(m.pivot_table(index=["features", "model"], columns="protocol", values="accuracy").to_string(float_format=lambda v: f"{v:.4f}"))
    o = out["open_set"]
    print(f"open set: {100 * o['unseen_rejected']:.1f} % of unseen-attack images rejected at a threshold keeping {100 * o['known_accepted']:.1f} % of known ones (AUROC {o['auroc']:.3f})")
    return 0


def cmd_paper_checks(args) -> int:
    from qwm.studies import paper_check_study

    out = paper_check_study(args.out)
    print(f"Table 9: {out['violations']} of {len(out['table9'])} rows violate the Fuchs-van de Graaf inequalities")
    for r in out["table9"]:
        if not r["consistent"]:
            print(f"  {r['image']:9s} F={r['fidelity']:<7g} T={r['trace_distance']:<7g} -> {r['reason']}")
    print("PSNR limits for 2 bits per pixel:")
    for b in out["psnr_bounds"]:
        print(f"  {b['method']:62s} MSE {b['mse']:7.4f}  PSNR {b['psnr_db']:6.2f} dB")
    return 0


def cmd_serve(args) -> int:
    from qwm.web.server import serve

    serve(host=args.host, port=args.port, open_browser=not args.no_browser)
    return 0


def cmd_download(args) -> int:
    from qwm.data import download_standard_images

    for p in download_standard_images():
        print(f"ok {p}")
    return 0


# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="qwm", description="NEQR-based quantum image watermarking with reversible quantum logic")
    p.add_argument("--version", action="version", version=f"qwm {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("run", help="one-command complete showcase of paper reproduction + v2/v3 enhancements")
    s.add_argument("image", nargs="?", default=None, help="test image (default: camera, works offline)")
    s.add_argument("--image", dest="image_opt", default=None, help="test image name or path")
    s.add_argument("--size", type=int, default=128)
    s.set_defaults(func=cmd_run)

    s = sub.add_parser("demo", help="run the worked 2x2 example through the reference code and the Qiskit circuits")
    s.add_argument("--block", default="[[50,60],[48,32]]", help="2x2 block as JSON")
    s.set_defaults(func=cmd_demo)

    s = sub.add_parser("embed", help="watermark an image (supports color RGB images in keyed/recovery modes)")
    s.add_argument("image", help="image name (lena, baboon, camera, ...) or path")
    s.add_argument("-o", "--output", default="watermarked.png")
    s.add_argument("--mode", choices=("paper", "lsb", "opap", "keyed", "keyed-opt", "recovery", "recovery-dual"), default="paper", help="paper/lsb/opap = base scheme; keyed*/recovery* = proposed blind schemes")
    s.add_argument("--key", help="secret key (keyed / recovery modes)")
    s.add_argument("--nonce", default="", help="per-image nonce, e.g. an image ID (keyed / recovery modes)")
    s.add_argument("--size", type=int, default=None, help="resize to NxN (default: 256 for named samples, native size for local files; 0=native)")
    s.add_argument("--save-watermark", help="save the generated watermark bits as .npy (base scheme)")
    s.set_defaults(func=cmd_embed)

    s = sub.add_parser("verify", help="verify (and repair) a watermarked image (blind for keyed*/recovery*, or --reference .npy for lsb/opap)")
    s.add_argument("image")
    s.add_argument("--mode", choices=("lsb", "opap") + KEYED_MODES, default="keyed")
    s.add_argument("--key", default=None)
    s.add_argument("--nonce", default="")
    s.add_argument("--reference", help=".npy file with reference watermark bits (for lsb/opap modes)")
    s.add_argument("--overlay", help="write the image with failed blocks highlighted")
    s.add_argument("--recovered", help="recovery mode: write the repaired image")
    s.set_defaults(func=cmd_verify)

    s = sub.add_parser("extract", help="extract the watermark bits from a watermarked image")
    s.add_argument("image")
    s.add_argument("--reference", help=".npy file with the reference watermark bits")
    s.add_argument("-o", "--output", help="write the raw watermark bit-planes as an image")
    s.add_argument("--save-bits", help="save the raw bits as .npy")
    s.set_defaults(func=cmd_extract)

    for name, func, helptext in (
        ("evaluate", cmd_evaluate, "PSNR / SSIM / timing of the watermarking (Tables 5, 12-14)"),
        ("attacks", cmd_attacks, "robustness against image processing attacks (Tables 7, 8, 15)"),
        ("quantum-metrics", cmd_quantum, "fidelity, trace distance and purity under noise channels (Table 9)"),
    ):
        s = sub.add_parser(name, help=helptext)
        s.add_argument("--images", help="comma separated image names/paths")
        s.add_argument("--offline", action="store_true", help="only use images bundled with scikit-image")
        s.add_argument("--size", type=int, default=256)
        s.add_argument("--out", type=Path, default=DEFAULT_OUT)
        if name != "evaluate":
            s.add_argument("--mode", choices=("paper", "lsb"), default="lsb")
        if name == "quantum-metrics":
            s.add_argument("--max-blocks", type=int, default=8, help="blocks sampled per image for the density-matrix evaluation")
        s.set_defaults(func=func)

    s = sub.add_parser("classify", help="train and evaluate the Random Forest attack classifier (Sec. 4.8)")
    s.add_argument("--samples-per-class", type=int, default=500)
    s.add_argument("--size", type=int, default=256)
    s.add_argument("--feature-size", type=int, default=None, help="feature-vector resolution (default: --size)")
    s.add_argument("--mode", choices=("paper", "lsb"), default="lsb")
    s.add_argument("--seed", type=int, default=42)
    s.add_argument("--folds", type=int, default=5)
    s.add_argument("--images", help="comma separated cover image names")
    s.add_argument("--offline", action="store_true")
    s.add_argument("--features", choices=("pixels", "descriptors", "descriptors_v2"), default="pixels", help="feature representation (pixels = Table 17)")
    s.add_argument("--params", choices=("random", "table7"), default="random", help="attack strengths: randomised or fixed to Table 7")
    s.add_argument("--quick", action="store_true", help="small dataset and 64x64 features for a fast smoke run")
    s.add_argument("--out", type=Path, default=DEFAULT_OUT / "classifier")
    s.set_defaults(func=cmd_classify)

    s = sub.add_parser("resources", help="quantum resource analysis (Sec. 4.9)")
    s.add_argument("--n", type=int, default=8)
    s.add_argument("--out", type=Path, default=DEFAULT_OUT)
    s.set_defaults(func=cmd_resources)

    s = sub.add_parser("draw", help="render the circuits to PNG files")
    s.add_argument("--out", type=Path, default=DEFAULT_OUT / "figures")
    s.set_defaults(func=cmd_draw)

    s = sub.add_parser("tamper-study", help="blind tamper localisation, forgery and self-recovery study (v2)")
    s.add_argument("--images", help="comma separated image names/paths")
    s.add_argument("--offline", action="store_true")
    s.add_argument("--fraction", type=float, default=0.2, help="side of the edited square relative to the image side")
    s.add_argument("--repeats", type=int, default=3)
    s.add_argument("--out", type=Path, default=DEFAULT_OUT / "tamper")
    s.set_defaults(func=cmd_tamper_study)

    s = sub.add_parser("nisq", help="heavy-hex compilation and noisy Aer simulation of every block circuit (v2/v3)")
    s.add_argument("--p2", help="comma separated two-qubit error rates")
    s.add_argument("--shots", type=int, default=2000)
    s.add_argument("--workers", type=int, default=None, help="parallel worker processes (default: cores - 1)")
    s.add_argument("--shallow", action="store_true", help="include shallow Brent-Kung CLA circuits in the sweep")
    s.add_argument("--thermal", action="store_true", help="also evaluate T1/T2 ALAP-scheduled idle decoherence")
    s.add_argument("--out", type=Path, default=DEFAULT_OUT / "nisq")
    s.set_defaults(func=cmd_nisq)

    s = sub.add_parser("superposition", help="run true NEQR superposition PPB, Grover tamper search, and multi-block MPS verification (v3)")
    s.add_argument("--image", default="camera")
    s.add_argument("--key", default="superposition-demo-key")
    s.add_argument("--shots", type=int, default=512)
    s.set_defaults(func=cmd_superposition)

    s = sub.add_parser("classifier-benchmark", help="cover-disjoint testing, baselines + McNemar, open-set detection (v2)")
    s.add_argument("--samples-per-class", type=int, default=500)
    s.add_argument("--unseen-per-attack", type=int, default=100)
    s.add_argument("--seed", type=int, default=42)
    s.add_argument("--quick", action="store_true", help="skip the 65,536-d pixel features")
    s.add_argument("--out", type=Path, default=DEFAULT_OUT / "classifier" / "benchmark")
    s.set_defaults(func=cmd_classifier_benchmark)

    s = sub.add_parser("paper-checks", help="consistency checks of reported numbers (Table 9, PSNR bound)")
    s.add_argument("--out", type=Path, default=DEFAULT_OUT / "paper_checks")
    s.set_defaults(func=cmd_paper_checks)

    for alias in ("serve", "ui"):
        s = sub.add_parser(alias, help="interactive web dashboard on http://localhost:8765")
        s.add_argument("--host", default="127.0.0.1")
        s.add_argument("--port", type=int, default=8765)
        s.add_argument("--no-browser", action="store_true")
        s.set_defaults(func=cmd_serve)

    s = sub.add_parser("download-images", help="download the standard grayscale test images")
    s.set_defaults(func=cmd_download)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
