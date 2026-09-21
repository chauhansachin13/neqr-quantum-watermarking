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
    return 0


def cmd_embed(args) -> int:
    from qwm.data import load_image, save_image
    from qwm.metrics.image import quality_report
    from qwm.watermark import embed_image

    cover = load_image(args.image, args.size)
    watermarked, wb = embed_image(cover, mode=args.mode)
    out = save_image(watermarked, args.output)
    q = quality_report(cover, watermarked)
    print(f"watermarked image written to {out}  (PSNR {q['psnr']:.2f} dB, SSIM {q['ssim']:.4f}, mode={args.mode})")
    if args.save_watermark:
        np.save(args.save_watermark, wb)
        print(f"watermark bits saved to {args.save_watermark} shape={wb.shape}")
    return 0


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
    print("Measured (this implementation):")
    for name, m in data["measured_block_circuits"].items():
        print(f"  {name:22s} qubits={m['qubits']:4d} (data {m['data_qubits']}, ancilla {m['ancilla_qubits']}) gates={m['reversible_gates']} depth={m['reversible_depth']} CNOT-level: {m['cnot_count']} CNOT, depth {m['cnot_level_depth']}")
    print("Preparation complexity:", data["preparation_complexity"])
    return 0


def cmd_draw(args) -> int:
    from qwm.experiments import draw_circuits

    for p in draw_circuits(args.out):
        print(f"wrote {p}")
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

    s = sub.add_parser("demo", help="run the worked 2x2 example through the reference code and the Qiskit circuits")
    s.add_argument("--block", default="[[50,60],[48,32]]", help="2x2 block as JSON")
    s.set_defaults(func=cmd_demo)

    s = sub.add_parser("embed", help="watermark an image")
    s.add_argument("image", help="image name (lena, baboon, camera, ...) or path")
    s.add_argument("-o", "--output", default="watermarked.png")
    s.add_argument("--mode", choices=("paper", "lsb"), default="paper")
    s.add_argument("--size", type=int, default=256)
    s.add_argument("--save-watermark", help="save the generated watermark bits as .npy")
    s.set_defaults(func=cmd_embed)

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
    s.add_argument("--features", choices=("pixels", "descriptors"), default="pixels", help="feature representation (pixels = Table 17)")
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

    s = sub.add_parser("download-images", help="download the standard grayscale test images")
    s.set_defaults(func=cmd_download)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
