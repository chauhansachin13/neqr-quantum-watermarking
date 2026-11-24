import numpy as np
import pytest

from qwm.attacks import UNSEEN_ATTACKS, apply_unseen_attack, random_unseen_params
from qwm.classifier.benchmark import (
    RF_NAME,
    benchmark_splits,
    build_benchmark_data,
    compare_models,
    mcnemar_exact,
    open_set_evaluation,
    unseen_attack_samples,
)
from qwm.classifier.features import descriptor_names, feature_length
from qwm.nisq import estimated_success_probability, threshold
from qwm.paper_checks import check_table9, consistent, psnr_bounds_2bpp
from qwm.tamper import MANIPULATIONS, apply_manipulation, block_truth, detection_scores


# --------------------------------------------------------------------------- paper checks
def test_table9_has_six_physically_impossible_rows():
    rows = check_table9()
    bad = [r["image"] for r in rows if not r["consistent"]]
    assert bad == ["Bird", "Man", "Boat", "House1", "House2", "Aerial"]


def test_fuchs_van_de_graaf_edge_cases():
    assert consistent(1.0, 0.0) and not consistent(1.0, 0.2)
    assert consistent(0.0, 1.0) and not consistent(0.5, 0.0)
    assert consistent(0.9999, 0.0)  # within rounding of the printed digits


def test_psnr_bounds_2bpp():
    b = {row["method"].split(" ")[0]: row for row in psnr_bounds_2bpp()}
    vals = [row["psnr_db"] for row in psnr_bounds_2bpp()]
    assert vals[0] == pytest.approx(44.15, abs=0.01)  # 2-LSB replacement
    assert vals[1] == pytest.approx(46.37, abs=0.01)  # optimal pixel adjustment
    assert vals[3] == pytest.approx(48.41, abs=0.01)  # sphere-packing limit
    assert vals[4] > vals[3] + 10  # the reported value is far beyond the limit
    assert b


# --------------------------------------------------------------------------- tamper module
@pytest.mark.parametrize("name", MANIPULATIONS)
def test_manipulations_report_exactly_the_changed_pixels(name, natural_image):
    from qwm.data import synthetic_image

    donor = synthetic_image("checkerboard", 64)
    rng = np.random.default_rng(3)
    out, changed = apply_manipulation(name, natural_image, rng, donor, 0.25)
    assert out.shape == natural_image.shape and out.dtype == np.uint8
    assert np.array_equal(changed, out != natural_image)
    assert changed.any()
    if name == "lsb_preserving_splice":
        assert np.array_equal(out & 3, natural_image & 3)


def test_block_truth_and_scores():
    m = np.zeros((8, 8), bool)
    m[0, 0] = m[5, 6] = True
    t = block_truth(m, 2)
    assert t.sum() == 2 and t[0, 0] and t[2, 3]
    s = detection_scores(t, t)
    assert s["tpr"] == 1 and s["fpr"] == 0 and s["f1"] == 1
    s = detection_scores(np.zeros_like(t), t)
    assert s["tpr"] == 0 and s["f1"] == 0


# --------------------------------------------------------------------------- classifier benchmark
def test_descriptor_names_cover_the_vector():
    assert len(descriptor_names()) == feature_length("descriptors", 64)


@pytest.mark.parametrize("name", list(UNSEEN_ATTACKS))
def test_unseen_attacks(name, natural_image):
    rng = np.random.default_rng(0)
    out = apply_unseen_attack(natural_image, name, seed=1, **random_unseen_params(name, rng))
    assert out.shape == natural_image.shape and out.dtype == np.uint8


def test_mcnemar_exact():
    y = np.zeros(20, int)
    a = np.zeros(20, int)
    b = np.zeros(20, int)
    b[:10] = 1  # A right / B wrong on 10 samples, no disagreement the other way
    r = mcnemar_exact(y, a, b)
    assert r["a_only_correct"] == 10 and r["b_only_correct"] == 0
    assert r["p_value"] == pytest.approx(2 * 0.5**10)
    assert mcnemar_exact(y, a, a)["p_value"] == 1.0


def test_benchmark_pipeline_small():
    from qwm.data import load_image

    covers = [load_image(n, 64) for n in ("camera", "coins", "moon", "astronaut", "gradient")]
    data = build_benchmark_data(covers, samples_per_class=6, size=64, pixel_sizes=(16,))
    assert data.features["descriptors"].shape == (54, len(descriptor_names()))
    splits = benchmark_splits(data.y, data.groups, seed=1)
    tr, te = splits["cover_disjoint"]
    assert not set(data.groups[tr]) & set(data.groups[te])
    rows = compare_models(data, splits, {"descriptors": [RF_NAME, "Logistic regression"], "pixels16": [RF_NAME]})
    assert {r["protocol"] for r in rows} == {"random", "cover_disjoint"}
    assert all(0 <= r["accuracy"] <= 1 for r in rows)
    from qwm.classifier.train import make_classifier

    rf = make_classifier().fit(data.features["descriptors"][tr], data.y[tr])
    Xu, nu = unseen_attack_samples(covers, per_attack=2, size=64)
    res = open_set_evaluation(rf, data.features["descriptors"][te], data.y[te], Xu, nu)
    assert 0 <= res["unseen_rejected"] <= 1 and len(res["per_attack"]) == len(UNSEEN_ATTACKS)


# --------------------------------------------------------------------------- NISQ helpers
def test_threshold_interpolation():
    p = [1e-5, 1e-4, 1e-3]
    s = [1.0, 0.9, 0.1]
    t = threshold(p, s, 0.5)
    assert 1e-4 < t < 1e-3
    assert threshold(p, s, 0.95) == pytest.approx(10 ** (-5 + 0.5), rel=1e-6)
    assert threshold(p, [1, 1, 1], 0.5) is None


def test_estimated_success_probability():
    counts = {"one_qubit_gates": 10, "two_qubit_gates": 100, "measured": 4}
    assert estimated_success_probability(counts, 1e-3, 1e-4, 0.0) == pytest.approx((1 - 1e-4) ** 10 * (1 - 1e-3) ** 100)


def test_noiseless_compiled_task_is_exact():
    from qwm.nisq import block_tasks, compile_heavy_hex, compile_logical, success_probability

    task = next(t for t in block_tasks() if t.name == "lean extraction")
    for qc in (compile_logical(task), compile_heavy_hex(task)):
        assert success_probability(qc, task.expected_key, 0.0, shots=16)["success"] == 1.0


def test_nisq_job_sweeps_with_early_stopping():
    from qwm.nisq import block_tasks
    from qwm.studies import _nisq_job

    idx = next(i for i, t in enumerate(block_tasks()) if t.name == "lean extraction")
    res = _nisq_job((idx, "all-to-all", (1e-4, 0.3, 0.5), 64, 1, 0.5))
    rows = res["rows"]
    assert [r["p2"] for r in rows] == [1e-4, 0.3, 0.5]
    assert rows[0]["measured"] and rows[0]["success"] > 0.8
    assert rows[1]["measured"] and rows[1]["success"] < 0.5  # heavy noise: below the stop threshold
    assert not rows[2]["measured"] and rows[2]["success"] == 0.0  # skipped, recorded as 0


def test_our_quantum_metrics_obey_fuchs_van_de_graaf():
    from pathlib import Path

    import pandas as pd
    from qiskit.quantum_info import random_density_matrix, random_statevector

    from qwm.metrics.quantum import fidelity, trace_distance

    for seed in range(12):
        for rho, sigma in (
            (random_density_matrix(4, seed=seed), random_density_matrix(4, seed=seed + 100)),
            (random_statevector(8, seed=seed), random_statevector(8, seed=seed + 50)),
        ):
            f, t = fidelity(rho, sigma), trace_distance(rho, sigma)
            assert consistent(f, t, tol=1e-9), (f, t)
    csv = Path(__file__).resolve().parents[1] / "results" / "quantum_metrics_lsb.csv"
    if csv.exists():  # block averages obey the bounds too (both sides are concave in F)
        for row in pd.read_csv(csv).itertuples():
            assert consistent(row.fidelity, row.trace_distance, tol=1e-9), row
