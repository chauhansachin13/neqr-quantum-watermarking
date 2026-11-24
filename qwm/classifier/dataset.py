"""
Dataset construction for AI-assisted attack classification (Sec. 4.8.1).

Attacked watermarked images are generated for nine balanced classes
(``no_attack``, Gaussian noise, salt-and-pepper noise, median filtering,
histogram equalisation, JPEG compression, cropping, rotation and text
addition).  Diversity comes from (i) several cover images, (ii) random
augmentation of the cover (flips, 90-degree rotations, random crops) before
watermark embedding and (iii) randomised attack parameters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from qwm.attacks import ATTACK_NAMES, DEFAULT_PARAMS, apply_attack, random_attack_params
from qwm.classifier.features import extract_features, feature_length
from qwm.data import default_image_set, load_image
from qwm.watermark.embedding import embed_image

CLASS_NAMES = tuple(ATTACK_NAMES)
CLASS_LABELS = {name: i for i, name in enumerate(CLASS_NAMES)}
PRETTY_NAMES = {
    "no_attack": "No attack",
    "gaussian_noise": "Gaussian noise",
    "salt_pepper_noise": "Salt-and-pepper noise",
    "median_filter": "Median filter",
    "histogram_equalization": "Histogram equalization",
    "jpeg_compression": "JPEG compression",
    "cropping": "Cropping",
    "rotation": "Rotation",
    "text_addition": "Text addition",
}


def augment_cover(image: np.ndarray, rng: np.random.Generator, size: int) -> np.ndarray:
    """Random flip / rotation / crop of a cover image, resized to ``size``."""
    img = image
    if rng.random() < 0.5:
        img = img[:, ::-1]
    if rng.random() < 0.3:
        img = img[::-1, :]
    k = int(rng.integers(0, 4))
    img = np.rot90(img, k)
    h, w = img.shape
    scale = float(rng.uniform(0.6, 1.0))
    ch, cw = max(8, int(h * scale)), max(8, int(w * scale))
    r0, c0 = int(rng.integers(0, h - ch + 1)), int(rng.integers(0, w - cw + 1))
    img = np.ascontiguousarray(img[r0 : r0 + ch, c0 : c0 + cw])
    if img.shape != (size, size):
        img = cv2.resize(img, (size, size), interpolation=cv2.INTER_AREA)
    return img


@dataclass
class AttackDataset:
    X: np.ndarray
    y: np.ndarray
    meta: list[dict] = field(default_factory=list)
    size: int = 256
    features: str = "pixels"
    params: str = "random"
    groups: np.ndarray | None = None  # index of the cover image each sample was made from

    def save(self, path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        groups = self.groups if self.groups is not None else np.full(len(self.y), -1)
        np.savez_compressed(path, X=self.X, y=self.y, size=self.size, features=self.features, params=self.params, groups=groups)
        return path

    @classmethod
    def load(cls, path) -> AttackDataset:
        data = np.load(path, allow_pickle=False)
        groups = data["groups"] if "groups" in data.files else None
        return cls(X=data["X"], y=data["y"], size=int(data["size"]), features=str(data["features"]), params=str(data["params"]), groups=groups)


def iter_attacked_samples(
    covers: list[np.ndarray],
    samples_per_class: int = 500,
    size: int = 256,
    mode: str = "lsb",
    seed: int = 42,
    params: str = "random",
):
    """Yield ``(label, attack_name, cover_index, attack_params, attacked_image)``.

    The random stream is identical to :func:`build_dataset`, so the same seed
    reproduces the same samples whatever features are computed from them.
    """
    if params not in ("random", "table7"):
        raise ValueError("params must be 'random' or 'table7'")
    rng = np.random.default_rng(seed)
    for label, name in enumerate(CLASS_NAMES):
        for _ in range(samples_per_class):
            cover_idx = int(rng.integers(0, len(covers)))
            cover = augment_cover(covers[cover_idx], rng, size)
            watermarked, _ = embed_image(cover, mode=mode)
            attack_params = random_attack_params(name, rng) if params == "random" else dict(DEFAULT_PARAMS[name])
            attacked = apply_attack(watermarked, name, seed=int(rng.integers(0, 2**31 - 1)), **attack_params)
            yield label, name, cover_idx, attack_params, attacked


def build_dataset(
    covers: list[np.ndarray] | None = None,
    samples_per_class: int = 500,
    size: int = 256,
    feature_size: int | None = None,
    mode: str = "lsb",
    seed: int = 42,
    verbose: bool = False,
    features: str = "pixels",
    params: str = "random",
) -> AttackDataset:
    """Generate the balanced attack dataset.

    Parameters
    ----------
    covers:
        Cover images (any size); loaded from :func:`qwm.data.default_image_set`
        when ``None``.
    samples_per_class:
        500 gives the 4,500-sample dataset of the reference design.
    size:
        Working resolution of the watermarked images.
    feature_size:
        Resolution of the feature vector (``size`` by default).
    mode:
        Embedding mode used to create the watermarked images.
    features:
        ``"pixels"`` (normalised flattened intensities) or ``"descriptors"``.
    params:
        ``"random"`` draws the attack strength of every sample at random;
        ``"table7"`` uses the fixed parameters of Table 7 (only the noise
        realisation and the cover augmentation vary between samples).
    """
    if covers is None:
        covers = [load_image(n, size) for n in default_image_set()]
    feature_size = feature_size or size
    if params not in ("random", "table7"):
        raise ValueError("params must be 'random' or 'table7'")
    n_total = samples_per_class * len(CLASS_NAMES)
    X = np.empty((n_total, feature_length(features, feature_size)), dtype=np.float32)
    y = np.empty(n_total, dtype=np.int64)
    groups = np.empty(n_total, dtype=np.int64)
    meta: list[dict] = []
    for row, (label, name, cover_idx, attack_params, attacked) in enumerate(iter_attacked_samples(covers, samples_per_class, size, mode, seed, params)):
        X[row] = extract_features(attacked, features, feature_size)
        y[row] = label
        groups[row] = cover_idx
        meta.append({"class": name, "cover": cover_idx, "params": attack_params})
        if verbose and (row + 1) % samples_per_class == 0:
            print(f"  generated {samples_per_class} samples for class {label} ({name})")
    return AttackDataset(X=X, y=y, meta=meta, size=feature_size, features=features, params=params, groups=groups)
