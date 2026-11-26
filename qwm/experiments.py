"""
Experiment runners that reproduce the evaluation of the reference design.

Every function returns plain Python/pandas objects and (optionally) writes
CSV tables and figures under an output directory, so they can be used from
the command line (:mod:`qwm.cli`), from notebooks or from tests.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from qwm.attacks import ATTACK_NAMES, DEFAULT_PARAMS, apply_attack
from qwm.data import load_image, save_image
from qwm.metrics.image import histogram, quality_report
from qwm.metrics.quantum import image_metrics
from qwm.watermark.embedding import embed_image, payload_capacity
from qwm.watermark.extraction import (
    bit_error_rate,
    extract_image,
    normalized_correlation,
    tamper_map,
)
from qwm.watermark.generation import generate_watermark

ATTACK_LEVELS: dict[str, list[dict]] = {
    "gaussian_noise": [{"sigma": 0.01}, {"sigma": 0.05}, {"sigma": 0.25}],
    "salt_pepper_noise": [{"density": 0.01}, {"density": 0.05}, {"density": 0.25}],
    "median_filter": [{"kernel": 3}, {"kernel": 5}],
    "histogram_equalization": [{}],
    "jpeg_compression": [{"quality": 90}, {"quality": 70}, {"quality": 50}],
    "cropping": [{"fraction": 0.1}, {"fraction": 0.25}],
    "rotation": [{"angle": 5.0}, {"angle": 45.0}],
    "text_addition": [{"text": "Confidential"}],
}


def _fmt_params(params: dict) -> str:
    return ", ".join(f"{k}={v}" for k, v in params.items()) or "-"


# --------------------------------------------------------------------------- #
# Imperceptibility (Tables 5 / 12, histogram analysis of Table 6)
# --------------------------------------------------------------------------- #
def imperceptibility(images: list[str], modes=("paper", "lsb"), size: int = 256, out_dir: Path | None = None) -> pd.DataFrame:
    rows = []
    for name in images:
        cover = load_image(name, size)
        wm = generate_watermark(cover)
        for mode in modes:
            t0 = time.perf_counter()
            watermarked, _ = embed_image(cover, wm, mode)
            t_embed = time.perf_counter() - t0
            t0 = time.perf_counter()
            raw, corrected = extract_image(watermarked, wm)
            t_extract = time.perf_counter() - t0
            q = quality_report(cover, watermarked)
            rows.append(
                {
                    "image": name,
                    "mode": mode,
                    "mse": q["mse"],
                    "psnr_db": q["psnr"],
                    "ssim": q["ssim"],
                    "ssim_global": q["ssim_global"],
                    "histogram_similarity": q["histogram_similarity"],
                    "ber_raw": bit_error_rate(raw, wm),
                    "ber_verified": bit_error_rate(corrected, wm),
                    "nc_raw": normalized_correlation(raw, wm),
                    "embed_time_s": t_embed,
                    "extract_time_s": t_extract,
                    "bpp": payload_capacity(cover.shape)["bpp"],
                }
            )
            if out_dir is not None:
                save_image(watermarked, Path(out_dir) / "watermarked" / f"{name}_{mode}.png")
    df = pd.DataFrame(rows)
    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        df.to_csv(out_dir / "imperceptibility.csv", index=False)
        _plot_histograms(images[:4], size, out_dir / "histograms.png")
    return df


def _plot_histograms(images: list[str], size: int, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(len(images), 4, figsize=(14, 3.0 * len(images)))
    axes = np.atleast_2d(axes)
    for r, name in enumerate(images):
        cover = load_image(name, size)
        watermarked, _ = embed_image(cover, mode="lsb")
        axes[r, 0].imshow(cover, cmap="gray", vmin=0, vmax=255)
        axes[r, 0].set_title(f"{name}: cover")
        axes[r, 1].bar(range(256), histogram(cover), width=1.0, color="black")
        axes[r, 1].set_title("cover histogram")
        axes[r, 2].imshow(watermarked, cmap="gray", vmin=0, vmax=255)
        axes[r, 2].set_title(f"watermarked (PSNR {quality_report(cover, watermarked)['psnr']:.2f} dB)")
        axes[r, 3].bar(range(256), histogram(watermarked), width=1.0, color="black")
        axes[r, 3].set_title("watermarked histogram")
        for ax in axes[r, (0, 2)]:
            ax.axis("off")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


# --------------------------------------------------------------------------- #
# Robustness against attacks (Tables 7 / 8 / 15)
# --------------------------------------------------------------------------- #
def robustness(images: list[str], mode: str = "lsb", size: int = 256, levels: dict | None = None, seed: int = 0, out_dir: Path | None = None) -> pd.DataFrame:
    levels = ATTACK_LEVELS if levels is None else levels
    rows = []
    examples: dict[str, np.ndarray] = {}
    for name in images:
        cover = load_image(name, size)
        wm = generate_watermark(cover)
        watermarked, _ = embed_image(cover, wm, mode)
        for attack in ATTACK_NAMES:
            if attack == "no_attack":
                variants = [{}]
            else:
                variants = levels.get(attack, [DEFAULT_PARAMS[attack]])
            for params in variants:
                attacked = apply_attack(watermarked, attack, seed=seed, **params)
                raw, _ = extract_image(attacked, wm)
                q = quality_report(cover, attacked)
                rows.append(
                    {
                        "image": name,
                        "attack": attack,
                        "params": _fmt_params(params),
                        "psnr_db": q["psnr"],
                        "ssim": q["ssim"],
                        "ber": bit_error_rate(raw, wm),
                        "nc": normalized_correlation(raw, wm),
                        "tampered_block_fraction": float(tamper_map(raw, wm).mean()),
                    }
                )
                key = f"{attack}|{_fmt_params(params)}"
                if key not in examples:
                    examples[key] = attacked
    df = pd.DataFrame(rows)
    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        df.to_csv(out_dir / f"robustness_{mode}.csv", index=False)
        summary = df.groupby(["attack", "params"], sort=False)[["psnr_db", "ssim", "ber", "nc"]].mean().reset_index()
        summary.to_csv(out_dir / f"robustness_{mode}_summary.csv", index=False)
        _plot_attack_gallery(examples, out_dir / "attacks.png")
    return df


def _plot_attack_gallery(examples: dict[str, np.ndarray], path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    keys = list(examples)
    cols = 4
    rows = int(np.ceil(len(keys) / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(3.2 * cols, 3.4 * rows))
    for ax in np.ravel(axes):
        ax.axis("off")
    for ax, key in zip(np.ravel(axes), keys, strict=False):
        attack, params = key.split("|")
        ax.imshow(examples[key], cmap="gray", vmin=0, vmax=255)
        ax.set_title(f"{attack}\n{params}", fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


# --------------------------------------------------------------------------- #
# Quantum noise and decoherence (Table 9)
# --------------------------------------------------------------------------- #
def quantum_noise(images: list[str], mode: str = "lsb", size: int = 256, noise_models=("none", "depolarizing", "amplitude_damping", "phase_damping"), levels=(0.01, 0.05, 0.1), max_blocks: int = 8, out_dir: Path | None = None) -> pd.DataFrame:
    rows = []
    for name in images:
        cover = load_image(name, size)
        watermarked, _ = embed_image(cover, mode=mode)
        for model in noise_models:
            for p in [0.0] if model == "none" else levels:
                m = image_metrics(cover, watermarked, model, p, max_blocks=max_blocks)
                rows.append({"image": name, "noise": model, "p": p, **m})
    df = pd.DataFrame(rows)
    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        df.to_csv(out_dir / f"quantum_metrics_{mode}.csv", index=False)
    return df


# --------------------------------------------------------------------------- #
# AI-assisted attack classification (Sec. 4.8)
# --------------------------------------------------------------------------- #
def attack_classification(samples_per_class: int = 500, size: int = 256, feature_size: int | None = None, mode: str = "lsb", seed: int = 42, folds: int = 5, images: list[str] | None = None, out_dir: Path | None = None, verbose: bool = True, features: str = "pixels", params: str = "random") -> dict:
    from qwm.classifier.dataset import build_dataset
    from qwm.classifier.train import plot_confusion_matrix, run_experiment
    from qwm.data import default_image_set

    covers = [load_image(n, size) for n in (images or default_image_set())]
    t0 = time.perf_counter()
    if verbose:
        print(f"building dataset: {samples_per_class} samples x {9} classes from {len(covers)} cover images ...")
    ds = build_dataset(covers, samples_per_class, size, feature_size, mode, seed, verbose, features, params)
    t_data = time.perf_counter() - t0
    if verbose:
        print(f"dataset ready: X={ds.X.shape} ({t_data:.1f}s); training Random Forest ...")
    t0 = time.perf_counter()
    model, result = run_experiment(ds.X, ds.y, seed, folds, do_cv=folds > 1, verbose=verbose)
    t_train = time.perf_counter() - t0
    summary = {
        "samples": int(len(ds.y)),
        "samples_per_class": samples_per_class,
        "features": features,
        "attack_params": params,
        "feature_length": int(ds.X.shape[1]),
        "dataset_time_s": t_data,
        "train_eval_time_s": t_train,
        "result": json.loads(json.dumps(result.__dict__, default=list)),
    }
    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        result.to_json(out_dir / "classification_result.json")
        (out_dir / "classification_summary.json").write_text(json.dumps(summary, indent=2))
        pd.DataFrame(result.per_class).to_csv(out_dir / "classification_per_class.csv", index=False)
        plot_confusion_matrix(result.confusion_matrix, out_dir / "confusion_matrix.png")
        try:
            import joblib

            joblib.dump(model, out_dir / "random_forest.joblib")
        except Exception:  # pragma: no cover - optional
            pass
    return summary


# --------------------------------------------------------------------------- #
# Resource analysis (Sec. 4.9)
# --------------------------------------------------------------------------- #
def resource_analysis(n: int = 8, out_dir: Path | None = None) -> dict:
    from qwm.resources import (
        complexity_comparison,
        measure_all_families,
        measure_block_circuits,
        measure_modules,
        reported_resources,
    )

    data = {
        "reported": reported_resources(n),
        "measured_modules": measure_modules(n),
        "measured_block_circuits": measure_block_circuits(),
        "measured_all_families": measure_all_families(),
        "preparation_complexity": complexity_comparison(),
    }
    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "resources.json").write_text(json.dumps(data, indent=2))
    return data


# --------------------------------------------------------------------------- #
# Circuit drawings
# --------------------------------------------------------------------------- #
def draw_circuits(out_dir: Path, block=((50, 60), (48, 32))) -> list[Path]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from qwm.circuits import (
        ShallowGenerationCircuit,
        WatermarkEmbeddingCircuit,
        WatermarkExtractionCircuit,
        WatermarkGenerationCircuit,
        neqr_ppb_superposition_circuit,
    )
    from qwm.circuits.lean import LeanGenerationCircuit
    from qwm.gates import (
        DividingFour,
        QuantumEqual,
        ReverseParallelAdder,
        ReverseParallelSubtractor,
        reversible_full_adder,
        reversible_full_subtractor,
        reversible_half_adder,
        reversible_half_subtractor,
    )
    from qwm.neqr import neqr_block_circuit

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    block = np.asarray(block)
    gen = WatermarkGenerationCircuit(block)
    wb = gen.run()["watermark"]
    emb = WatermarkEmbeddingCircuit(block, wb)
    wblock = emb.run()["watermarked_block"]
    ext = WatermarkExtractionCircuit(wblock, wb)
    items = {
        "neqr_block": neqr_block_circuit(block),
        "rha": reversible_half_adder(),
        "rfa": reversible_full_adder(),
        "rpa_2bit": ReverseParallelAdder(2).circuit.decompose(),
        "rhs": reversible_half_subtractor(),
        "rfs": reversible_full_subtractor(),
        "rps_2bit": ReverseParallelSubtractor(2).circuit.decompose(),
        "d4_4bit": DividingFour(4).circuit,
        "qe_3bit": QuantumEqual(3).circuit,
        "watermark_generation": gen.circuit,
        "watermark_embedding": emb.circuit,
        "watermark_extraction": ext.circuit,
        "lean_generation": LeanGenerationCircuit(block).circuit,
        "shallow_generation": ShallowGenerationCircuit(block).circuit,
        "neqr_superposition_ppb": neqr_ppb_superposition_circuit(block.astype(np.uint8)),
    }
    paths = []
    for name, qc in items.items():
        path = out_dir / f"{name}.png"
        fold = 40 if qc.num_qubits <= 20 else -1
        fig = qc.draw("mpl", fold=fold, scale=0.6 if qc.num_qubits > 20 else 1.0)
        fig.savefig(path, dpi=110, bbox_inches="tight")
        plt.close(fig)
        paths.append(path)
    return paths
