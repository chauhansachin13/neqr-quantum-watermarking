import json

import numpy as np
import pytest

from qwm.classifier import (
    CLASS_NAMES,
    HYPERPARAMETERS,
    binomial_test_vs_chance,
    build_dataset,
    confidence_interval,
    image_to_feature,
    make_classifier,
    run_experiment,
)
from qwm.resources import (
    complexity_comparison,
    d4_gate_complexity,
    measure_block_circuits,
    measure_modules,
    qe_gate_complexity,
    reported_resources,
    rpa_gate_complexity,
    rps_gate_complexity,
)


def test_feature_vector(natural_image):
    f = image_to_feature(natural_image, 32)
    assert f.shape == (1024,) and f.dtype == np.float32 and 0.0 <= f.min() and f.max() <= 1.0


def test_hyperparameters_match_table18():
    clf = make_classifier()
    assert clf.n_estimators == 100 and clf.criterion == "gini" and clf.max_depth is None
    assert clf.min_samples_split == 2 and clf.min_samples_leaf == 1 and clf.max_features == "sqrt"
    assert clf.bootstrap is True and clf.class_weight is None and clf.random_state == 42
    assert HYPERPARAMETERS["n_estimators"] == 100


def test_confidence_interval_reference_values():
    ci = confidence_interval(869, 900)
    lo, hi = ci["wald"]
    assert lo == pytest.approx(0.9536, abs=5e-4) and hi == pytest.approx(0.9775, abs=5e-4)
    assert binomial_test_vs_chance(869, 900) < 1e-3


def test_small_classification_experiment(natural_image, tmp_path):
    covers = [natural_image, natural_image[::-1].copy()]
    ds = build_dataset(covers, samples_per_class=10, size=64, feature_size=32, seed=1)
    assert ds.X.shape == (10 * len(CLASS_NAMES), 32 * 32) and len(np.unique(ds.y)) == len(CLASS_NAMES)
    path = ds.save(tmp_path / "ds.npz")
    assert path.exists()
    model, result = run_experiment(ds.X, ds.y, seed=1, folds=2)
    assert result.total == 18 and 0.0 <= result.accuracy <= 1.0
    assert len(result.per_class) == len(CLASS_NAMES)
    assert np.asarray(result.confusion_matrix).sum() == result.total
    out = result.to_json(tmp_path / "res.json")
    assert json.loads(out.read_text())["n_test"] == 18


def test_gate_complexity_formulas():
    assert rpa_gate_complexity(8) == 68 and rps_gate_complexity(8) == 68
    assert d4_gate_complexity(8) == 51 and qe_gate_complexity(8) == 117


def test_reported_qubit_totals():
    rep = reported_resources(8)
    assert rep["module_qubits"] == {"RPA": 32, "RPS": 32, "D4": 10, "QE": 17}
    assert rep["watermark_generation"]["total"] == 354
    assert rep["embedding"]["total"] == 400 and rep["extraction"]["total"] == 400


def test_measured_resources():
    m = measure_block_circuits()
    assert m["watermark_generation"]["qubits"] == 146
    assert m["embedding"]["qubits"] == 64 and m["extraction"]["qubits"] == 88
    for entry in m.values():
        assert entry["reversible_gate_total"] > 0 and entry["reversible_depth"] > 0 and entry["cnot_count"] > 0
    mods = measure_modules(4)
    assert mods["RPA"]["qubits"] == 16 and mods["QE"]["qubits"] == 9 and mods["D4"]["reversible_gates"] == {"swap": 4}


def test_complexity_comparison():
    rows = complexity_comparison()
    r256 = rows[-1]
    assert r256["FRQI"] == 2**32 and r256["NEQR"] == 4194304
