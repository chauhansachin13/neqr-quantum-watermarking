"""
Image processing attacks used for the robustness evaluation (Table 7).

Every attack takes and returns a ``uint8`` grayscale image of the same size:

* ``no_attack``               - identity
* ``gaussian_noise``          - additive Gaussian noise (mean 0, ``sigma`` on the [0, 1] scale)
* ``salt_pepper_noise``       - impulse noise with the given ``density``
* ``median_filter``           - ``k x k`` median filtering (blurring effect)
* ``histogram_equalization``  - global histogram equalisation
* ``jpeg_compression``        - JPEG re-encoding at ``quality``
* ``cropping``                - a rectangle of the image is blanked out
* ``rotation``                - rotation by ``angle`` degrees about the centre
* ``text_addition``           - a text string ("Confidential") is drawn onto the image

:data:`ATTACKS` maps class names to callables, and :func:`apply_attack`
dispatches by name with optional parameter overrides.
"""

from __future__ import annotations

from collections.abc import Callable

import cv2
import numpy as np

ATTACK_NAMES = (
    "no_attack",
    "gaussian_noise",
    "salt_pepper_noise",
    "median_filter",
    "histogram_equalization",
    "jpeg_compression",
    "cropping",
    "rotation",
    "text_addition",
)


def _u8(image) -> np.ndarray:
    img = np.asarray(image)
    if img.dtype != np.uint8:
        img = np.clip(np.rint(img), 0, 255).astype(np.uint8)
    if img.ndim != 2:
        raise ValueError("expected a 2-D grayscale image")
    return img


def no_attack(image, **_) -> np.ndarray:
    return _u8(image).copy()


def gaussian_noise(image, sigma: float = 0.25, mean: float = 0.0, seed: int | None = None) -> np.ndarray:
    """Additive Gaussian noise; ``sigma``/``mean`` are relative to the [0, 1] intensity range."""
    rng = np.random.default_rng(seed)
    img = _u8(image).astype(np.float64) / 255.0
    noisy = img + rng.normal(mean, sigma, img.shape)
    return np.clip(noisy * 255.0, 0, 255).astype(np.uint8)


def salt_pepper_noise(image, density: float = 0.25, seed: int | None = None) -> np.ndarray:
    rng = np.random.default_rng(seed)
    img = _u8(image).copy()
    mask = rng.random(img.shape)
    img[mask < density / 2] = 0
    img[(mask >= density / 2) & (mask < density)] = 255
    return img


def median_filter(image, kernel: int = 3, **_) -> np.ndarray:
    kernel = int(kernel) | 1  # must be odd
    return cv2.medianBlur(_u8(image), kernel)


def histogram_equalization(image, **_) -> np.ndarray:
    return cv2.equalizeHist(_u8(image))


def jpeg_compression(image, quality: int = 50, **_) -> np.ndarray:
    ok, buf = cv2.imencode(".jpg", _u8(image), [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    if not ok:
        raise RuntimeError("JPEG encoding failed")
    return cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE)


def cropping(image, fraction: float = 0.25, position: str = "top_left", fill: int = 0, **_) -> np.ndarray:
    """Blank out a ``fraction``-sized square (relative side length) of the image."""
    img = _u8(image).copy()
    h, w = img.shape
    ch, cw = max(1, int(round(h * fraction))), max(1, int(round(w * fraction)))
    anchors = {
        "top_left": (0, 0),
        "top_right": (0, w - cw),
        "bottom_left": (h - ch, 0),
        "bottom_right": (h - ch, w - cw),
        "center": ((h - ch) // 2, (w - cw) // 2),
    }
    r, c = anchors[position]
    img[r : r + ch, c : c + cw] = fill
    return img


def rotation(image, angle: float = 45.0, **_) -> np.ndarray:
    img = _u8(image)
    h, w = img.shape
    m = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), float(angle), 1.0)
    return cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)


def text_addition(image, text: str = "Confidential", scale: float | None = None, thickness: int | None = None, color: int = 255, **_) -> np.ndarray:
    img = _u8(image).copy()
    h, w = img.shape
    scale = scale if scale is not None else max(0.4, w / 256.0)
    thickness = thickness if thickness is not None else max(1, int(round(w / 128.0)))
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness)
    org = (max(0, (w - tw) // 2), max(th, (h + th) // 2))
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, int(color), thickness, cv2.LINE_AA)
    return img


ATTACKS: dict[str, Callable[..., np.ndarray]] = {
    "no_attack": no_attack,
    "gaussian_noise": gaussian_noise,
    "salt_pepper_noise": salt_pepper_noise,
    "median_filter": median_filter,
    "histogram_equalization": histogram_equalization,
    "jpeg_compression": jpeg_compression,
    "cropping": cropping,
    "rotation": rotation,
    "text_addition": text_addition,
}

# Default parameters (Table 7 of the reference design).
DEFAULT_PARAMS: dict[str, dict] = {
    "no_attack": {},
    "gaussian_noise": {"sigma": 0.25, "mean": 0.0},
    "salt_pepper_noise": {"density": 0.25},
    "median_filter": {"kernel": 3},
    "histogram_equalization": {},
    "jpeg_compression": {"quality": 50},
    "cropping": {"fraction": 0.25, "position": "top_left"},
    "rotation": {"angle": 45.0},
    "text_addition": {"text": "Confidential"},
}


def apply_attack(image, name: str, seed: int | None = None, **params) -> np.ndarray:
    if name not in ATTACKS:
        raise KeyError(f"unknown attack {name!r}; choose from {list(ATTACKS)}")
    kwargs = {**DEFAULT_PARAMS.get(name, {}), **params}
    if name in ("gaussian_noise", "salt_pepper_noise"):
        kwargs["seed"] = seed
    return ATTACKS[name](image, **kwargs)


def random_attack_params(name: str, rng: np.random.Generator) -> dict:
    """Randomised parameters used to build a diverse classification dataset."""
    if name == "gaussian_noise":
        return {"sigma": float(rng.uniform(0.02, 0.3)), "mean": 0.0}
    if name == "salt_pepper_noise":
        return {"density": float(rng.uniform(0.02, 0.3))}
    if name == "median_filter":
        return {"kernel": int(rng.choice([3, 5, 7]))}
    if name == "jpeg_compression":
        return {"quality": int(rng.integers(10, 90))}
    if name == "cropping":
        return {"fraction": float(rng.uniform(0.15, 0.4)), "position": str(rng.choice(["top_left", "top_right", "bottom_left", "bottom_right", "center"]))}
    if name == "rotation":
        return {"angle": float(rng.uniform(5.0, 85.0) * rng.choice([-1, 1]))}
    if name == "text_addition":
        return {"text": str(rng.choice(["Confidential", "SECRET", "Copyright", "DRAFT", "Sample"])), "scale": float(rng.uniform(0.6, 1.6)), "thickness": int(rng.integers(1, 4))}
    return {}


# --------------------------------------------------------------------------- #
# Attacks the classifier never sees during training (open-set evaluation)
# --------------------------------------------------------------------------- #
def gaussian_blur(image, sigma: float = 1.5, **_) -> np.ndarray:
    return cv2.GaussianBlur(_u8(image), (0, 0), float(sigma))


def sharpen(image, amount: float = 1.0, sigma: float = 1.0, **_) -> np.ndarray:
    """Unsharp masking."""
    img = _u8(image).astype(np.float64)
    blurred = cv2.GaussianBlur(img, (0, 0), float(sigma))
    return np.clip(img + float(amount) * (img - blurred), 0, 255).astype(np.uint8)


def rescale(image, factor: float = 0.5, **_) -> np.ndarray:
    """Down-sample by ``factor`` and back (resolution loss)."""
    img = _u8(image)
    h, w = img.shape
    small = cv2.resize(img, (max(1, int(w * factor)), max(1, int(h * factor))), interpolation=cv2.INTER_AREA)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)


def gamma_correction(image, gamma: float = 0.7, **_) -> np.ndarray:
    x = _u8(image).astype(np.float64) / 255.0
    return np.clip(np.rint(255.0 * x ** float(gamma)), 0, 255).astype(np.uint8)


def brightness(image, delta: int = 30, **_) -> np.ndarray:
    return np.clip(_u8(image).astype(np.int64) + int(delta), 0, 255).astype(np.uint8)


def speckle_noise(image, sigma: float = 0.1, seed: int | None = None, **_) -> np.ndarray:
    """Multiplicative noise ``x * (1 + n)``."""
    rng = np.random.default_rng(seed)
    x = _u8(image).astype(np.float64)
    return np.clip(x * (1.0 + rng.normal(0.0, float(sigma), x.shape)), 0, 255).astype(np.uint8)


def motion_blur(image, length: int = 7, angle: float = 0.0, **_) -> np.ndarray:
    length = max(3, int(length) | 1)
    kernel = np.zeros((length, length), dtype=np.float64)
    kernel[length // 2, :] = 1.0
    rot = cv2.getRotationMatrix2D((length / 2 - 0.5, length / 2 - 0.5), float(angle), 1.0)
    kernel = cv2.warpAffine(kernel, rot, (length, length))
    kernel /= max(kernel.sum(), 1e-9)
    return np.clip(cv2.filter2D(_u8(image).astype(np.float64), -1, kernel), 0, 255).astype(np.uint8)


def contrast_stretch(image, low: float = 0.05, high: float = 0.95, **_) -> np.ndarray:
    """Linear stretch of the [low, high] percentile range to [0, 255]."""
    x = _u8(image).astype(np.float64)
    lo, hi = np.percentile(x, [100 * low, 100 * high])
    if hi <= lo:
        return _u8(image).copy()
    return np.clip((x - lo) * 255.0 / (hi - lo), 0, 255).astype(np.uint8)


UNSEEN_ATTACKS: dict[str, Callable[..., np.ndarray]] = {
    "gaussian_blur": gaussian_blur,
    "sharpen": sharpen,
    "rescale": rescale,
    "gamma_correction": gamma_correction,
    "brightness": brightness,
    "speckle_noise": speckle_noise,
    "motion_blur": motion_blur,
    "contrast_stretch": contrast_stretch,
}


def random_unseen_params(name: str, rng: np.random.Generator) -> dict:
    if name == "gaussian_blur":
        return {"sigma": float(rng.uniform(0.8, 2.5))}
    if name == "sharpen":
        return {"amount": float(rng.uniform(0.5, 2.0)), "sigma": float(rng.uniform(0.8, 2.0))}
    if name == "rescale":
        return {"factor": float(rng.uniform(0.3, 0.7))}
    if name == "gamma_correction":
        return {"gamma": float(rng.choice([rng.uniform(0.4, 0.8), rng.uniform(1.25, 2.2)]))}
    if name == "brightness":
        return {"delta": int(rng.choice([-1, 1]) * rng.integers(15, 60))}
    if name == "speckle_noise":
        return {"sigma": float(rng.uniform(0.05, 0.25))}
    if name == "motion_blur":
        return {"length": int(rng.choice([5, 7, 9, 11])), "angle": float(rng.uniform(0, 180))}
    if name == "contrast_stretch":
        return {"low": float(rng.uniform(0.01, 0.1)), "high": float(rng.uniform(0.9, 0.99))}
    raise KeyError(f"unknown unseen attack {name!r}")


def apply_unseen_attack(image, name: str, seed: int | None = None, **params) -> np.ndarray:
    if name not in UNSEEN_ATTACKS:
        raise KeyError(f"unknown unseen attack {name!r}; choose from {list(UNSEEN_ATTACKS)}")
    if name == "speckle_noise":
        params["seed"] = seed
    return UNSEEN_ATTACKS[name](image, **params)
