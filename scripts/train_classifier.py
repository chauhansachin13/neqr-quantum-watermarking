"""Build the attack dataset and train / evaluate the Random Forest (Sec. 4.8).

Example:
    python scripts/train_classifier.py --samples-per-class 500 --size 256 --out results/classifier
"""

from __future__ import annotations

import argparse
from pathlib import Path

from qwm.experiments import attack_classification


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--samples-per-class", type=int, default=500)
    p.add_argument("--size", type=int, default=256)
    p.add_argument("--feature-size", type=int, default=None)
    p.add_argument("--mode", choices=("paper", "lsb"), default="lsb")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--folds", type=int, default=5)
    p.add_argument("--features", choices=("pixels", "descriptors"), default="pixels")
    p.add_argument("--params", choices=("random", "table7"), default="random")
    p.add_argument("--out", type=Path, default=Path("results/classifier"))
    args = p.parse_args()
    summary = attack_classification(args.samples_per_class, args.size, args.feature_size, args.mode, args.seed, args.folds, out_dir=args.out, features=args.features, params=args.params)
    r = summary["result"]
    print(f"accuracy {100 * r['accuracy']:.2f}%  precision {100 * r['precision']:.2f}%  recall {100 * r['recall']:.2f}%  F1 {100 * r['f1']:.2f}%")


if __name__ == "__main__":
    main()
