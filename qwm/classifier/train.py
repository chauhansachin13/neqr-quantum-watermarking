"""
Random Forest attack classifier: training, cross-validation and statistics.

Hyper-parameters (Table 18): 100 trees, Gini impurity, unlimited depth,
``min_samples_split=2``, ``min_samples_leaf=1``, ``max_features="sqrt"``,
bootstrap sampling, no class weighting, ``random_state=42``.

Evaluation (Sec. 4.8.4 / Tables 19-20): 80:20 stratified train/test split,
stratified 5-fold cross-validation on the training set, accuracy / precision /
recall / F1 (overall and per class), confusion matrix, a 95 % confidence
interval for the test accuracy and a one-sided binomial test against the
chance level of a nine-class problem (11.11 %).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from scipy import stats
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split

from qwm.classifier.dataset import CLASS_NAMES, PRETTY_NAMES

HYPERPARAMETERS = {
    "n_estimators": 100,
    "criterion": "gini",
    "max_depth": None,
    "min_samples_split": 2,
    "min_samples_leaf": 1,
    "max_features": "sqrt",
    "bootstrap": True,
    "class_weight": None,
    "random_state": 42,
}


def make_classifier(seed: int = 42, n_jobs: int = -1) -> RandomForestClassifier:
    params = {**HYPERPARAMETERS, "random_state": seed}
    return RandomForestClassifier(n_jobs=n_jobs, **params)


def split_dataset(X: np.ndarray, y: np.ndarray, test_size: float = 0.2, seed: int = 42):
    return train_test_split(X, y, test_size=test_size, stratify=y, random_state=seed)


def cross_validate(X_train: np.ndarray, y_train: np.ndarray, folds: int = 5, seed: int = 42) -> np.ndarray:
    skf = StratifiedKFold(n_splits=folds, shuffle=True, random_state=seed)
    return cross_val_score(make_classifier(seed), X_train, y_train, cv=skf, scoring="accuracy")


def confidence_interval(correct: int, total: int, alpha: float = 0.05) -> dict[str, tuple[float, float]]:
    """Wald (normal approximation) and Wilson score intervals for a proportion."""
    p = correct / total
    z = stats.norm.ppf(1 - alpha / 2)
    half = z * np.sqrt(p * (1 - p) / total)
    wald = (max(0.0, p - half), min(1.0, p + half))
    denom = 1 + z**2 / total
    centre = (p + z**2 / (2 * total)) / denom
    spread = z * np.sqrt(p * (1 - p) / total + z**2 / (4 * total**2)) / denom
    wilson = (max(0.0, centre - spread), min(1.0, centre + spread))
    return {"wald": wald, "wilson": wilson}


def binomial_test_vs_chance(correct: int, total: int, chance: float = 1.0 / 9.0) -> float:
    """One-sided binomial test p-value that accuracy exceeds ``chance``."""
    return float(stats.binomtest(correct, total, chance, alternative="greater").pvalue)


def per_class_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> list[dict]:
    labels = list(range(len(CLASS_NAMES)))
    cm = confusion_matrix(y_true, y_pred, labels=labels)
    prec = precision_score(y_true, y_pred, labels=labels, average=None, zero_division=0)
    rec = recall_score(y_true, y_pred, labels=labels, average=None, zero_division=0)
    f1 = f1_score(y_true, y_pred, labels=labels, average=None, zero_division=0)
    rows = []
    n = cm.sum()
    for i, name in enumerate(CLASS_NAMES):
        tp = cm[i, i]
        fp = cm[:, i].sum() - tp
        fn = cm[i, :].sum() - tp
        tn = n - tp - fp - fn
        rows.append(
            {
                "label": i,
                "attack": PRETTY_NAMES[name],
                "accuracy": float((tp + tn) / n) if n else 0.0,  # one-vs-rest accuracy
                "precision": float(prec[i]),
                "recall": float(rec[i]),
                "f1": float(f1[i]),
                "support": int(cm[i, :].sum()),
                "correct": int(tp),
            }
        )
    return rows


@dataclass
class EvaluationResult:
    accuracy: float
    precision: float
    recall: float
    f1: float
    correct: int
    total: int
    confidence_interval_wald: tuple[float, float]
    confidence_interval_wilson: tuple[float, float]
    chance_level: float
    binomial_p_value: float
    cv_scores: list[float]
    per_class: list[dict]
    confusion_matrix: list[list[int]]
    n_train: int
    n_test: int
    hyperparameters: dict

    def to_json(self, path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2))
        return path


def evaluate(model: RandomForestClassifier, X_test: np.ndarray, y_test: np.ndarray, cv_scores=None, n_train: int = 0) -> EvaluationResult:
    y_pred = model.predict(X_test)
    labels = list(range(len(CLASS_NAMES)))
    correct = int((y_pred == y_test).sum())
    total = int(len(y_test))
    ci = confidence_interval(correct, total)
    return EvaluationResult(
        accuracy=float(accuracy_score(y_test, y_pred)),
        precision=float(precision_score(y_test, y_pred, average="macro", zero_division=0)),
        recall=float(recall_score(y_test, y_pred, average="macro", zero_division=0)),
        f1=float(f1_score(y_test, y_pred, average="macro", zero_division=0)),
        correct=correct,
        total=total,
        confidence_interval_wald=ci["wald"],
        confidence_interval_wilson=ci["wilson"],
        chance_level=1.0 / len(CLASS_NAMES),
        binomial_p_value=binomial_test_vs_chance(correct, total, 1.0 / len(CLASS_NAMES)),
        cv_scores=[float(s) for s in (cv_scores if cv_scores is not None else [])],
        per_class=per_class_metrics(y_test, y_pred),
        confusion_matrix=confusion_matrix(y_test, y_pred, labels=labels).tolist(),
        n_train=int(n_train),
        n_test=total,
        hyperparameters=dict(HYPERPARAMETERS),
    )


def run_experiment(X: np.ndarray, y: np.ndarray, seed: int = 42, folds: int = 5, do_cv: bool = True, verbose: bool = False) -> tuple[RandomForestClassifier, EvaluationResult]:
    """Full protocol: stratified split -> CV on the training set -> final fit -> test evaluation."""
    X_train, X_test, y_train, y_test = split_dataset(X, y, 0.2, seed)
    cv_scores = None
    if do_cv:
        cv_scores = cross_validate(X_train, y_train, folds, seed)
        if verbose:
            print(f"  {folds}-fold CV accuracy: {cv_scores.mean():.4f} +/- {cv_scores.std():.4f}")
    model = make_classifier(seed)
    model.fit(X_train, y_train)
    result = evaluate(model, X_test, y_test, cv_scores, n_train=len(y_train))
    if verbose:
        print(f"  test accuracy: {result.accuracy:.4f} ({result.correct}/{result.total})")
    return model, result


def plot_confusion_matrix(cm, path, title: str = "Attack classification confusion matrix") -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    cm = np.asarray(cm)
    fig, ax = plt.subplots(figsize=(8.5, 7))
    im = ax.imshow(cm, cmap="Blues")
    ax.set_xticks(range(len(CLASS_NAMES)))
    ax.set_yticks(range(len(CLASS_NAMES)))
    names = [PRETTY_NAMES[n] for n in CLASS_NAMES]
    ax.set_xticklabels(names, rotation=45, ha="right")
    ax.set_yticklabels(names)
    ax.set_xlabel("Predicted")
    ax.set_ylabel("True")
    ax.set_title(title)
    thresh = cm.max() / 2.0 if cm.size else 0
    for i in range(cm.shape[0]):
        for j in range(cm.shape[1]):
            ax.text(j, i, str(cm[i, j]), ha="center", va="center", color="white" if cm[i, j] > thresh else "black", fontsize=8)
    fig.colorbar(im, ax=ax, fraction=0.046)
    fig.tight_layout()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path
