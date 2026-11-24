"""
Stricter evaluation of the AI-assisted attack classifier.

Sec. 4.8 of the reference design reports a single Random Forest evaluated on a
random 80:20 split, without a baseline ("no paired comparison against another
model is claimed") and without testing attacks outside the nine training
classes.  This module adds the missing pieces:

1. **Cover-disjoint testing.**  With a random split the same cover images
   (augmented) appear in training and test data, so a model can partly
   recognise *content*.  :func:`benchmark_splits` also builds a split with
   :class:`~sklearn.model_selection.StratifiedGroupKFold` in which no test
   sample shares its cover image with a training sample.
2. **Baselines with paired significance tests.**  Six standard classifiers are
   trained on the same split and compared with the Random Forest of Table 18
   with an exact McNemar test on the discordant test predictions.
3. **Open-set detection.**  Eight attacks that never occur in training
   (blur, sharpening, rescaling, gamma, brightness, speckle noise, motion blur,
   contrast stretch) are thrown at the trained forest; its maximum class
   probability is used as a confidence score, the threshold is set to accept
   95 % of the known-attack test images, and the share of unseen-attack images
   rejected as "unknown" (plus the ROC AUC) is reported.
4. **Explainability.**  Impurity-based feature importances of the forest on the
   named descriptor vector.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import cv2
import numpy as np
from scipy import stats
from sklearn.base import clone
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score
from sklearn.model_selection import StratifiedGroupKFold, train_test_split
from sklearn.neighbors import KNeighborsClassifier
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

from qwm.attacks import UNSEEN_ATTACKS, apply_unseen_attack, random_unseen_params
from qwm.classifier.dataset import CLASS_NAMES, augment_cover, iter_attacked_samples
from qwm.classifier.features import descriptor_names, image_descriptors, image_to_feature
from qwm.classifier.train import make_classifier
from qwm.watermark.embedding import embed_image

__all__ = [
    "BenchmarkData",
    "build_benchmark_data",
    "benchmark_splits",
    "candidate_models",
    "mcnemar_exact",
    "compare_models",
    "open_set_evaluation",
    "top_features",
]

RF_NAME = "Random Forest (Table 18)"


@dataclass
class BenchmarkData:
    y: np.ndarray
    groups: np.ndarray
    features: dict[str, np.ndarray]  # name -> (n, d)
    n_covers: int
    build_time_s: float


def build_benchmark_data(
    covers: list[np.ndarray],
    samples_per_class: int = 500,
    size: int = 256,
    seed: int = 42,
    params: str = "random",
    mode: str = "lsb",
    pixel_sizes=(64, 256),
    verbose: bool = False,
) -> BenchmarkData:
    """Generate the attacked images once and compute every feature set from them."""
    t0 = time.perf_counter()
    n = samples_per_class * len(CLASS_NAMES)
    desc = np.empty((n, len(descriptor_names())), dtype=np.float32)
    pix = {s: np.empty((n, s * s), dtype=np.float32) for s in pixel_sizes}
    y = np.empty(n, dtype=np.int64)
    g = np.empty(n, dtype=np.int64)
    for row, (label, _name, cover_idx, _params, attacked) in enumerate(iter_attacked_samples(covers, samples_per_class, size, mode, seed, params)):
        desc[row] = image_descriptors(attacked, size)
        for s in pixel_sizes:
            pix[s][row] = image_to_feature(attacked, s)
        y[row] = label
        g[row] = cover_idx
        if verbose and (row + 1) % (samples_per_class * 3) == 0:
            print(f"  {row + 1}/{n} samples")
    feats = {"descriptors": desc}
    for s in pixel_sizes:
        feats[f"pixels{s}"] = pix[s]
    return BenchmarkData(y=y, groups=g, features=feats, n_covers=len(covers), build_time_s=time.perf_counter() - t0)


def benchmark_splits(y: np.ndarray, groups: np.ndarray, seed: int = 42) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """``random`` (stratified 80:20, the paper's protocol) and ``cover_disjoint``."""
    idx = np.arange(len(y))
    tr, te = train_test_split(idx, test_size=0.2, stratify=y, random_state=seed)
    sgkf = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=seed)
    gtr, gte = next(sgkf.split(idx, y, groups))
    assert not set(groups[gtr]) & set(groups[gte])
    return {"random": (np.sort(tr), np.sort(te)), "cover_disjoint": (gtr, gte)}


def candidate_models(seed: int = 42) -> dict[str, object]:
    """The forest of Table 18 and six standard baselines."""
    return {
        RF_NAME: make_classifier(seed),
        "Extra Trees": ExtraTreesClassifier(n_estimators=300, random_state=seed, n_jobs=-1),
        "Hist. gradient boosting": HistGradientBoostingClassifier(random_state=seed),
        "SVM (RBF)": make_pipeline(StandardScaler(), SVC(C=10.0, gamma="scale", random_state=seed)),
        "Logistic regression": make_pipeline(StandardScaler(), LogisticRegression(max_iter=3000, C=1.0)),
        "k-NN (k=5)": make_pipeline(StandardScaler(), KNeighborsClassifier(n_neighbors=5)),
        "MLP (128-64)": make_pipeline(StandardScaler(), MLPClassifier(hidden_layer_sizes=(128, 64), max_iter=800, early_stopping=True, random_state=seed)),
    }


def mcnemar_exact(y_true: np.ndarray, pred_a: np.ndarray, pred_b: np.ndarray) -> dict:
    """Exact (binomial) two-sided McNemar test on the discordant pairs."""
    a_ok = np.asarray(pred_a) == np.asarray(y_true)
    b_ok = np.asarray(pred_b) == np.asarray(y_true)
    b = int(np.sum(a_ok & ~b_ok))  # A right, B wrong
    c = int(np.sum(~a_ok & b_ok))  # A wrong, B right
    p = 1.0 if b + c == 0 else float(stats.binomtest(min(b, c), b + c, 0.5).pvalue)
    return {"a_only_correct": b, "b_only_correct": c, "p_value": p}


def compare_models(
    data: BenchmarkData,
    splits: dict,
    feature_sets: dict[str, list[str]] | None = None,
    seed: int = 42,
    verbose: bool = False,
) -> list[dict]:
    """Fit every (feature set, model) on every split; McNemar against the forest."""
    models = candidate_models(seed)
    if feature_sets is None:
        feature_sets = {
            "descriptors": list(models),
            "pixels64": [RF_NAME, "Logistic regression", "SVM (RBF)"],
            "pixels256": [RF_NAME],
        }
    rows = []
    for protocol, (tr, te) in splits.items():
        for feat, names in feature_sets.items():
            if feat not in data.features:
                continue
            X = data.features[feat]
            preds = {}
            for name in names:
                t0 = time.perf_counter()
                model = clone(models[name]).fit(X[tr], data.y[tr])
                preds[name] = model.predict(X[te])
                rows.append(
                    {
                        "protocol": protocol,
                        "features": feat,
                        "model": name,
                        "accuracy": float(accuracy_score(data.y[te], preds[name])),
                        "macro_f1": float(f1_score(data.y[te], preds[name], average="macro")),
                        "n_train": int(len(tr)),
                        "n_test": int(len(te)),
                        "fit_time_s": time.perf_counter() - t0,
                    }
                )
                if verbose:
                    print(f"  [{protocol:14s}] {feat:11s} {name:26s} acc={rows[-1]['accuracy']:.4f}")
            ref = preds.get(RF_NAME)
            for r in rows:
                if r["protocol"] == protocol and r["features"] == feat:
                    if ref is None or r["model"] == RF_NAME:
                        r.setdefault("mcnemar_p_vs_rf", None)
                    else:
                        r["mcnemar_p_vs_rf"] = mcnemar_exact(data.y[te], ref, preds[r["model"]])["p_value"]
    return rows


# --------------------------------------------------------------------------- #
# Open-set detection of attacks outside the training classes
# --------------------------------------------------------------------------- #
def unseen_attack_samples(covers: list[np.ndarray], per_attack: int = 100, size: int = 256, seed: int = 7, mode: str = "lsb"):
    """Descriptor vectors of watermarked images hit by attacks never seen in training."""
    rng = np.random.default_rng(seed)
    X, names = [], []
    for name in UNSEEN_ATTACKS:
        for _ in range(per_attack):
            cover = augment_cover(covers[int(rng.integers(0, len(covers)))], rng, size)
            wm, _ = embed_image(cover, mode=mode)
            attacked = apply_unseen_attack(wm, name, seed=int(rng.integers(0, 2**31 - 1)), **random_unseen_params(name, rng))
            if attacked.shape != (size, size):
                attacked = cv2.resize(attacked, (size, size))
            X.append(image_descriptors(attacked, size))
            names.append(name)
    return np.asarray(X, dtype=np.float32), np.asarray(names)


def open_set_evaluation(model, X_known_test: np.ndarray, y_known_test: np.ndarray, X_unseen: np.ndarray, unseen_names: np.ndarray, keep: float = 0.95) -> dict:
    """Max-probability rejection of unseen attacks at a threshold that keeps ``keep`` of the known ones."""
    p_known = model.predict_proba(X_known_test).max(axis=1)
    p_unseen = model.predict_proba(X_unseen)
    conf_unseen = p_unseen.max(axis=1)
    tau = float(np.quantile(p_known, 1.0 - keep))
    known_acc = float(np.mean(model.predict(X_known_test) == y_known_test))
    labels = np.r_[np.zeros(len(p_known)), np.ones(len(conf_unseen))]
    auroc = float(roc_auc_score(labels, -np.r_[p_known, conf_unseen]))
    per_attack = []
    pred_unseen = p_unseen.argmax(axis=1)
    for name in dict.fromkeys(unseen_names):
        m = unseen_names == name
        mapped = np.bincount(pred_unseen[m], minlength=len(CLASS_NAMES))
        per_attack.append(
            {
                "attack": name,
                "rejected_as_unknown": float(np.mean(conf_unseen[m] < tau)),
                "mean_confidence": float(conf_unseen[m].mean()),
                "most_often_called": CLASS_NAMES[int(mapped.argmax())],
                "share_called_that": float(mapped.max() / m.sum()),
            }
        )
    return {
        "threshold": tau,
        "known_accepted": float(np.mean(p_known >= tau)),
        "known_accuracy": known_acc,
        "unseen_rejected": float(np.mean(conf_unseen < tau)),
        "auroc": auroc,
        "per_attack": per_attack,
    }


def top_features(model, names: list[str] | None = None, k: int = 15) -> list[tuple[str, float]]:
    names = names or descriptor_names()
    imp = np.asarray(model.feature_importances_)
    order = np.argsort(imp)[::-1][:k]
    return [(names[i], float(imp[i])) for i in order]
