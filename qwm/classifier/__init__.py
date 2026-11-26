"""AI-assisted attack classification with a Random Forest."""

from qwm.classifier.dataset import (
    CLASS_LABELS,
    CLASS_NAMES,
    PRETTY_NAMES,
    AttackDataset,
    build_dataset,
)
from qwm.classifier.features import (
    FEATURE_KINDS,
    extract_features,
    image_descriptors,
    image_descriptors_v2,
    image_to_feature,
)
from qwm.classifier.train import (
    HYPERPARAMETERS,
    EvaluationResult,
    binomial_test_vs_chance,
    confidence_interval,
    cross_validate,
    evaluate,
    make_classifier,
    plot_confusion_matrix,
    run_experiment,
    split_dataset,
)

__all__ = [
    "CLASS_LABELS",
    "CLASS_NAMES",
    "PRETTY_NAMES",
    "HYPERPARAMETERS",
    "AttackDataset",
    "EvaluationResult",
    "binomial_test_vs_chance",
    "build_dataset",
    "confidence_interval",
    "cross_validate",
    "evaluate",
    "FEATURE_KINDS",
    "extract_features",
    "image_descriptors",
    "image_descriptors_v2",
    "image_to_feature",
    "make_classifier",
    "plot_confusion_matrix",
    "run_experiment",
    "split_dataset",
]
