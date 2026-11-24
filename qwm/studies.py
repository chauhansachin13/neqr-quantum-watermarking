"""
Runners for the studies added in v2 (the reproduction runners stay in
:mod:`qwm.experiments`):

* :func:`tamper_study`      - blind tamper localisation, forgery resistance and
  self-recovery of the keyed schemes against the base scheme;
* :func:`nisq_study`        - hardware mapping and noisy simulation of every
  block circuit;
* :func:`classifier_study`  - cover-disjoint testing, baselines with McNemar
  tests, open-set detection and feature importances;
* :func:`paper_check_study` - consistency checks of reported numbers.

Each returns plain Python / pandas objects and writes CSV / JSON / PNG files
when ``out_dir`` is given.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from qwm.data import default_image_set, load_image
from qwm.metrics.image import psnr

SCHEME_LABELS = {
    "base": "Base scheme (needs reference bits)",
    "keyed": "Keyed 2x2 (blind)",
    "recovery": "Self-recovering 4x4 (blind)",
}


def _plt():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


# --------------------------------------------------------------------------- #
# Tamper localisation, forgery and self-recovery
# --------------------------------------------------------------------------- #
def tamper_study(
    images: list[str] | None = None,
    fraction: float = 0.2,
    repeats: int = 3,
    size: int = 256,
    seed: int = 0,
    key: str = "study-secret-key",
    out_dir: Path | None = None,
) -> dict:
    from qwm.secure import SecureWatermark, SelfRecoveringWatermark
    from qwm.tamper import MANIPULATIONS, apply_manipulation, block_truth, detection_scores
    from qwm.watermark.embedding import embed_image
    from qwm.watermark.extraction import extract_image, tamper_map

    images = images or default_image_set()
    covers = {n: load_image(n, size) for n in images}
    rows, forgery = [], []
    gallery = {}
    for ii, name in enumerate(images):
        cover = covers[name]
        donor = covers[images[(ii + 1) % len(images)]]
        base_wm, base_ref = embed_image(cover, mode="lsb")
        sw = SecureWatermark(key, nonce=name)
        srw = SelfRecoveringWatermark(key, nonce=name)
        wms = {"base": base_wm, "keyed": sw.embed(cover), "recovery": srw.embed(cover)}
        # keyless forgery: blocks that pass verification under a wrong key
        forgery.append(
            {
                "image": name,
                "keyed_pass_rate_wrong_key": 1.0 - SecureWatermark("wrong-" + key, nonce=name).verify(wms["keyed"]).tampered_fraction,
                "recovery_pass_rate_wrong_key": 1.0 - float(SelfRecoveringWatermark("wrong-" + key, nonce=name).verify(wms["recovery"]).mean()),
                "base_blind_false_alarm": float(np.any(extract_image(base_wm)[0] != embed_image(base_wm, mode="lsb")[1], axis=-1).mean()),
            }
        )
        for k, manip in enumerate(("none",) + MANIPULATIONS):
            for rep in range(1 if manip == "none" else repeats):
                for scheme, wm in wms.items():
                    rng = np.random.default_rng([seed, ii, k, rep])  # same edit for every scheme
                    if manip == "none":
                        attacked, changed = wm.copy(), np.zeros(wm.shape, dtype=bool)
                    else:
                        attacked, changed = apply_manipulation(manip, wm, rng, donor, fraction)
                    extra = {}
                    if scheme == "base":
                        pred, block = tamper_map(extract_image(attacked)[0], base_ref), 2
                    elif scheme == "keyed":
                        pred, block = sw.verify(attacked).tamper_map, 2
                    else:
                        res = srw.recover(attacked)
                        pred, block = res.tamper_map, 4
                        region = changed if changed.any() else np.ones_like(changed)
                        extra = {
                            "psnr_attacked_region": psnr(cover[region], attacked[region]),
                            "psnr_recovered_region": psnr(cover[region], res.recovered[region]),
                            "psnr_attacked": psnr(cover, attacked),
                            "psnr_recovered": psnr(cover, res.recovered),
                            "restored_fraction": res.restored_fraction,
                        }
                        if rep == 0 and name == images[0]:
                            gallery.setdefault(manip, {}).update({"recovered": res.recovered, "changed": changed})
                    scores = detection_scores(pred, block_truth(changed, block))
                    if rep == 0 and name == images[0]:
                        gallery.setdefault(manip, {})[f"pred_{scheme}"] = (pred, block)
                        gallery[manip].setdefault("attacked_" + scheme, attacked)
                    rows.append({"image": name, "manipulation": manip, "repeat": rep, "scheme": scheme, "block": block, **scores, **extra})
    df = pd.DataFrame(rows)
    fdf = pd.DataFrame(forgery)
    quality = scheme_quality(covers, key)
    agg = {"tpr": "mean", "fpr": "mean", "f1": "mean", "iou": "mean"}
    summary = df.groupby(["manipulation", "scheme"], sort=False).agg(agg).reset_index()
    rec = df[df.scheme == "recovery"].groupby("manipulation", sort=False)[["psnr_attacked_region", "psnr_recovered_region", "psnr_attacked", "psnr_recovered", "restored_fraction"]].mean().reset_index()
    out = {"rows": df, "summary": summary, "recovery": rec, "forgery": fdf, "quality": quality}
    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        df.to_csv(out_dir / "tamper_detection.csv", index=False)
        summary.to_csv(out_dir / "tamper_detection_summary.csv", index=False)
        rec.to_csv(out_dir / "self_recovery_summary.csv", index=False)
        fdf.to_csv(out_dir / "forgery.csv", index=False)
        quality.to_csv(out_dir / "scheme_quality.csv", index=False)
        _plot_tamper_gallery(covers[images[0]], gallery, out_dir / "tamper_gallery.jpg")
    return out


def scheme_quality(covers: dict[str, np.ndarray], key: str = "study-secret-key") -> pd.DataFrame:
    """PSNR / SSIM / timing of every scheme on every cover (all at 2 bpp)."""
    from qwm.metrics.image import quality_report
    from qwm.secure import SecureWatermark, SelfRecoveringWatermark
    from qwm.watermark.embedding import embed_image

    rows = []
    for name, cover in covers.items():
        schemes = {
            "base (paper rule)": lambda c: embed_image(c, mode="paper")[0],
            "base (LSB)": lambda c: embed_image(c, mode="lsb")[0],
            "keyed 2x2": SecureWatermark(key, name).embed,
            "self-recovery 4x4": SelfRecoveringWatermark(key, name).embed,
        }
        for scheme, fn in schemes.items():
            t0 = time.perf_counter()
            wm = fn(cover)
            dt = time.perf_counter() - t0
            q = quality_report(cover, wm)
            rows.append({"image": name, "scheme": scheme, "psnr_db": q["psnr"], "ssim": q["ssim"], "mse": q["mse"], "embed_ms": 1000 * dt})
    return pd.DataFrame(rows)


def _overlay(img: np.ndarray, pred: np.ndarray, block: int) -> np.ndarray:
    rgb = np.repeat(img[..., None], 3, axis=-1).astype(np.float64)
    m = np.kron(pred.astype(np.uint8), np.ones((block, block), np.uint8)).astype(bool)
    full = np.zeros(img.shape, bool)
    full[: m.shape[0], : m.shape[1]] = m
    rgb[full] = 0.45 * rgb[full] + 0.55 * np.array([230.0, 30.0, 30.0])
    return rgb.astype(np.uint8)


def _plot_tamper_gallery(cover: np.ndarray, gallery: dict, path: Path) -> None:
    plt = _plt()
    manips = [m for m in ("text_overlay", "copy_move", "splice", "lsb_preserving_splice", "blackout") if m in gallery]
    cols = ["tampered", "base scheme (reference)", "keyed 2x2 (blind)", "self-recovery 4x4: detected", "self-recovery 4x4: repaired"]
    fig, axes = plt.subplots(len(manips), len(cols), figsize=(3.0 * len(cols), 3.1 * len(manips)))
    axes = np.atleast_2d(axes)
    from qwm.tamper import PRETTY

    for r, m in enumerate(manips):
        g = gallery[m]
        panels = [
            (g["attacked_keyed"], None),
            (_overlay(g["attacked_base"], *g["pred_base"]), None),
            (_overlay(g["attacked_keyed"], *g["pred_keyed"]), None),
            (_overlay(g["attacked_recovery"], *g["pred_recovery"]), None),
            (g["recovered"], f"PSNR {psnr(cover, g['recovered']):.1f} dB"),
        ]
        for c, (im, note) in enumerate(panels):
            ax = axes[r, c]
            ax.imshow(im, cmap="gray", vmin=0, vmax=255)
            ax.set_xticks([])
            ax.set_yticks([])
            if r == 0:
                ax.set_title(cols[c], fontsize=9)
            if c == 0:
                ax.set_ylabel(PRETTY[m], fontsize=9)
            if note:
                ax.set_xlabel(note, fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=105, pil_kwargs={"quality": 86, "optimize": True})
    plt.close(fig)


# --------------------------------------------------------------------------- #
# NISQ feasibility
# --------------------------------------------------------------------------- #
DEFAULT_P2 = (1e-5, 3e-5, 1e-4, 3e-4, 1e-3, 3e-3, 1e-2)


def _nisq_job(args) -> dict:
    """One (circuit, topology) noise sweep; runs in a worker process."""
    task_index, topology, p_values, shots, seed, stop_below = args
    from qwm.nisq import (
        block_tasks,
        compile_heavy_hex,
        compile_logical,
        estimated_success_probability,
        gate_counts,
        success_probability,
    )

    t = block_tasks()[task_index]
    t0 = time.perf_counter()
    qc = compile_logical(t) if topology == "all-to-all" else compile_heavy_hex(t)
    counts = gate_counts(qc)
    rows, stopped = [], False
    for p in sorted(p_values):
        n_shots = shots if p <= 1e-3 else max(250, shots // 4)
        t1 = time.perf_counter()
        if stopped:
            # success only falls as p grows; once it is ~0 the rest is ~0 too
            r, measured = {"success": 0.0, "stderr": 0.0, "bit_error_rate": float("nan")}, False
        else:
            r, measured = success_probability(qc, t.expected_key, p, shots=n_shots, seed=seed, threads=1), True
            stopped = r["success"] < stop_below
        rows.append(
            {
                "circuit": t.name,
                "family": t.family,
                "topology": topology,
                "p2": p,
                "p1": p / 10,
                "success": r["success"],
                "stderr": r["stderr"],
                "bit_error_rate": r["bit_error_rate"],
                "esp": estimated_success_probability(counts, p),
                "measured": measured,
                "shots": n_shots if measured else 0,
                "seconds": time.perf_counter() - t1,
            }
        )
    return {"name": t.name, "family": t.family, "stage": t.stage, "qubits": t.circuit.num_qubits, "topology": topology, "counts": counts, "rows": rows, "seconds": time.perf_counter() - t0}


def nisq_study(
    p_values=DEFAULT_P2,
    shots: int = 2000,
    seed: int = 7,
    out_dir: Path | None = None,
    verbose: bool = False,
    workers: int | None = None,
    stop_below: float = 0.002,
) -> dict:
    """Compile every block circuit, then sweep the two-qubit error rate with Aer.

    The (circuit, topology) sweeps run in parallel worker processes.  Points
    above 1e-3 use a quarter of the shots, and once a curve has fallen below
    ``stop_below`` the higher error rates are recorded as 0 without simulating
    (``measured = False`` in the CSV); success can only decrease with ``p``.
    """
    import os
    from concurrent.futures import ProcessPoolExecutor, as_completed

    from qiskit.transpiler import CouplingMap

    from qwm.nisq import block_tasks, heavy_hex_distance, threshold

    tasks = block_tasks()
    jobs = [(i, topo, tuple(p_values), shots, seed, stop_below) for i in range(len(tasks)) for topo in ("heavy-hex", "all-to-all")]
    jobs.sort(key=lambda j: -tasks[j[0]].circuit.num_qubits)  # widest first for load balancing
    workers = workers or max(1, min(len(jobs), (os.cpu_count() or 2) - 1))
    out_path = Path(out_dir) if out_dir is not None else None
    if out_path is not None:
        out_path.mkdir(parents=True, exist_ok=True)
    results = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_nisq_job, j) for j in jobs]
        for fut in as_completed(futures):
            res = fut.result()
            results.append(res)
            if verbose:
                last = [r for r in res["rows"] if r["measured"]]
                print(f"  done {res['name']:26s} {res['topology']:10s} in {res['seconds']:6.1f}s; " + " ".join(f"{r['p2']:.0e}:{r['success']:.3f}" for r in last), flush=True)
            if out_path is not None:  # keep partial results in case the run is interrupted
                pd.DataFrame([r for x in results for r in x["rows"]]).to_csv(out_path / "nisq_noise_sweep.partial.csv", index=False)

    order = {t.name: i for i, t in enumerate(tasks)}
    results.sort(key=lambda r: (order[r["name"]], r["topology"]))
    res_rows = []
    for t in tasks:
        by_topo = {r["topology"]: r["counts"] for r in results if r["name"] == t.name}
        d = heavy_hex_distance(t.circuit.num_qubits)
        a, h = by_topo["all-to-all"], by_topo["heavy-hex"]
        res_rows.append(
            {
                "circuit": t.name,
                "family": t.family,
                "stage": t.stage,
                "qubits": t.circuit.num_qubits,
                "cx_all_to_all": a["two_qubit_gates"],
                "depth_all_to_all": a["depth"],
                "heavy_hex_distance": d,
                "heavy_hex_lattice_qubits": CouplingMap.from_heavy_hex(d).size(),
                "cx_heavy_hex": h["two_qubit_gates"],
                "depth_heavy_hex": h["depth"],
                "routing_cx_overhead": h["two_qubit_gates"] / max(1, a["two_qubit_gates"]),
            }
        )
    sweep = pd.DataFrame([r for x in results for r in x["rows"]])
    thr_rows = []
    for (name, topo), g in sweep.groupby(["circuit", "topology"], sort=False):
        g = g.sort_values("p2")
        thr_rows.append({"circuit": name, "topology": topo, "p2_for_99pct": threshold(g.p2, g.success, 0.99), "p2_for_50pct": threshold(g.p2, g.success, 0.5)})
    paper = [
        {"circuit": "reported: watermark generation", "family": "paper", "stage": "generation", "qubits": 354},
        {"circuit": "reported: embedding", "family": "paper", "stage": "embedding", "qubits": 400},
        {"circuit": "reported: extraction", "family": "paper", "stage": "extraction", "qubits": 400},
    ]
    resources = pd.DataFrame(paper + res_rows)
    thresholds = pd.DataFrame(thr_rows)
    if out_path is not None:
        resources.to_csv(out_path / "nisq_resources.csv", index=False)
        sweep.to_csv(out_path / "nisq_noise_sweep.csv", index=False)
        thresholds.to_csv(out_path / "nisq_thresholds.csv", index=False)
        (out_path / "nisq_noise_sweep.partial.csv").unlink(missing_ok=True)
        _plot_nisq(sweep, out_path / "nisq_success.png")
    return {"resources": resources, "sweep": sweep, "thresholds": thresholds}


def _plot_nisq(sweep: pd.DataFrame, path: Path) -> None:
    plt = _plt()
    styles = {
        "base-v1 generation": ("#8c564b", "-", "o"),
        "lean generation": ("#1f77b4", "-", "s"),
        "keyed embedding": ("#2ca02c", "-", "^"),
        "keyed blind verification": ("#d62728", "-", "D"),
        "base-v1 extraction": ("#8c564b", "--", "o"),
        "lean extraction": ("#1f77b4", "--", "s"),
    }
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.6), sharey=True)
    for ax, topo in zip(axes, ("all-to-all", "heavy-hex"), strict=True):
        sub = sweep[sweep.topology == topo]
        for name, (color, ls, mk) in styles.items():
            s = sub[sub.circuit == name].sort_values("p2")
            if s.empty:
                continue
            ax.errorbar(s.p2, s.success, yerr=s.stderr, color=color, ls=ls, marker=mk, ms=4, capsize=2, label=name)
            if "measured" in s and (~s.measured.astype(bool)).any():
                u = s[~s.measured.astype(bool)]
                ax.plot(u.p2, u.success, ls="none", marker=mk, ms=5, mfc="white", mec=color)
        ax.set_xscale("log")
        ax.axhline(0.99, color="grey", lw=0.8, ls=":")
        ax.axvspan(1e-3, 1e-2, color="orange", alpha=0.08, label="two-qubit error of today's NISQ devices" if topo == "all-to-all" else None)
        ax.set_xlabel("two-qubit depolarising error p2 (single-qubit p1 = p2/10)")
        ax.set_title(f"one 2x2 block, {topo} connectivity")
        ax.grid(alpha=0.3)
    axes[0].set_ylabel("P[output exactly right]")
    axes[0].legend(fontsize=8, loc="lower left")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


# --------------------------------------------------------------------------- #
# Attack-classifier benchmark
# --------------------------------------------------------------------------- #
def classifier_study(samples_per_class: int = 500, seed: int = 42, images: list[str] | None = None, unseen_per_attack: int = 100, pixel_sizes=(64, 256), out_dir: Path | None = None, verbose: bool = True) -> dict:
    from qwm.classifier.benchmark import (
        RF_NAME,
        benchmark_splits,
        build_benchmark_data,
        compare_models,
        open_set_evaluation,
        top_features,
        unseen_attack_samples,
    )
    from qwm.classifier.train import make_classifier

    covers = [load_image(n, 256) for n in (images or default_image_set())]
    if verbose:
        print(f"building {samples_per_class * 9} attacked images from {len(covers)} covers ...")
    data = build_benchmark_data(covers, samples_per_class, 256, seed, pixel_sizes=pixel_sizes, verbose=verbose)
    splits = benchmark_splits(data.y, data.groups, seed)
    feature_sets = {"descriptors": None, "pixels64": [RF_NAME, "Logistic regression", "SVM (RBF)"], "pixels256": [RF_NAME]}
    from qwm.classifier.benchmark import candidate_models

    feature_sets["descriptors"] = list(candidate_models(seed))
    rows = compare_models(data, splits, {k: v for k, v in feature_sets.items() if k in data.features}, seed, verbose)
    tr, te = splits["random"]
    Xd = data.features["descriptors"]
    rf = make_classifier(seed).fit(Xd[tr], data.y[tr])
    Xu, nu = unseen_attack_samples(covers, unseen_per_attack, 256, seed + 1)
    open_set = open_set_evaluation(rf, Xd[te], data.y[te], Xu, nu)
    ctr, cte = splits["cover_disjoint"]
    rf_g = make_classifier(seed).fit(Xd[ctr], data.y[ctr])
    open_set_g = open_set_evaluation(rf_g, Xd[cte], data.y[cte], Xu, nu)
    importances = top_features(rf, k=15)
    out = {
        "models": pd.DataFrame(rows),
        "open_set": open_set,
        "open_set_cover_disjoint": open_set_g,
        "top_features": importances,
        "n_samples": int(len(data.y)),
        "n_covers": data.n_covers,
        "test_covers_disjoint": sorted(int(c) for c in set(data.groups[cte])),
        "build_time_s": data.build_time_s,
    }
    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out["models"].to_csv(out_dir / "benchmark_models.csv", index=False)
        pd.DataFrame(open_set["per_attack"]).to_csv(out_dir / "open_set_per_attack.csv", index=False)
        summary = {k: v for k, v in out.items() if k not in ("models",)}
        (out_dir / "benchmark_summary.json").write_text(json.dumps(summary, indent=2, default=str))
        _plot_benchmark(out["models"], open_set, importances, out_dir / "benchmark.png")
    return out


def _plot_benchmark(models: pd.DataFrame, open_set: dict, importances, path: Path) -> None:
    plt = _plt()
    fig, axes = plt.subplots(1, 3, figsize=(17, 5.2), gridspec_kw={"width_ratios": [1.35, 1, 1]})
    d = models[models.features == "descriptors"]
    names = list(dict.fromkeys(d.model))
    x = np.arange(len(names))
    for off, (proto, color) in zip((-0.2, 0.2), (("random", "#4c72b0"), ("cover_disjoint", "#dd8452")), strict=True):
        vals = [float(d[(d.model == n) & (d.protocol == proto)].accuracy.iloc[0]) for n in names]
        axes[0].bar(x + off, vals, 0.4, color=color, label="random split" if proto == "random" else "unseen covers")
    axes[0].set_xticks(x)
    axes[0].set_xticklabels(names, rotation=30, ha="right", fontsize=8)
    axes[0].set_ylim(0.5, 1.0)
    axes[0].set_ylabel("test accuracy")
    axes[0].set_title("attack classification, 137-d descriptors")
    axes[0].legend(fontsize=8, loc="lower left")
    axes[0].grid(axis="y", alpha=0.3)
    pa = pd.DataFrame(open_set["per_attack"])
    axes[1].barh(pa.attack, pa.rejected_as_unknown, color="#55a868")
    axes[1].set_xlim(0, 1)
    axes[1].set_title(f"unseen attacks flagged 'unknown'\n(threshold keeps 95% of known; AUROC {open_set['auroc']:.2f})", fontsize=10)
    for i, (r, c) in enumerate(zip(pa.rejected_as_unknown, pa.most_often_called, strict=True)):
        axes[1].text(min(r + 0.02, 0.5), i, f"else -> {c}".replace("_", " "), va="center", fontsize=7)
    names_i = [n for n, _ in importances][::-1]
    vals_i = [v for _, v in importances][::-1]
    axes[2].barh(names_i, vals_i, color="#8172b2")
    axes[2].set_title("top-15 descriptor importances (Random Forest)", fontsize=10)
    axes[2].tick_params(axis="y", labelsize=7)
    fig.tight_layout()
    fig.savefig(path, dpi=115)
    plt.close(fig)


# --------------------------------------------------------------------------- #
# Consistency checks of reported numbers
# --------------------------------------------------------------------------- #
def paper_check_study(out_dir: Path | None = None) -> dict:
    from qwm.paper_checks import check_table9, psnr_bounds_2bpp

    table9 = check_table9()
    bounds = psnr_bounds_2bpp()
    out = {"table9": table9, "violations": sum(not r["consistent"] for r in table9), "psnr_bounds": bounds}
    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "paper_checks.json").write_text(json.dumps(out, indent=2))
        pd.DataFrame(table9).to_csv(out_dir / "table9_check.csv", index=False)
        pd.DataFrame(bounds).to_csv(out_dir / "psnr_bounds.csv", index=False)
    return out
