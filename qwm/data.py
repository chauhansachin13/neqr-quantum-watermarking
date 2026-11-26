"""
Test image handling.

Standard grayscale test images (Lena, Baboon, Peppers, Barbara, Boat,
House, Airplane, ...) are downloaded on demand into ``data/images`` from a
public mirror; a few sample images shipped with scikit-image and synthetic
images are always available so that the pipeline (and the tests) work
offline.
"""

from __future__ import annotations

import urllib.request
from pathlib import Path

import cv2
import numpy as np

try:  # silence libtiff tag warnings printed by OpenCV while decoding downloads
    cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
except AttributeError:  # pragma: no cover - older OpenCV
    pass

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "images"

_MIRROR = "https://raw.githubusercontent.com/mohammadimtiazz/standard-test-images-for-Image-Processing/master/standard_test_images/"

#: name -> file in the mirror
STANDARD_IMAGES: dict[str, str] = {
    "lena": "lena_gray_512.tif",
    "baboon": "mandril_gray.tif",
    "peppers": "peppers_gray.tif",
    "barbara": "barbara.bmp",
    "boat": "boat.png",
    "house": "house.tif",
    "airplane": "jetplane.tif",
    "man": "pirate.tif",
    "cameraman": "cameraman.tif",
    "lake": "lake.tif",
    "livingroom": "livingroom.tif",
    "walkbridge": "walkbridge.tif",
    "woman_blonde": "woman_blonde.tif",
    "woman_darkhair": "woman_darkhair.tif",
    "flowers": "tulips.png",
    "fruits": "fruits.png",
}

#: names of images bundled with scikit-image
SKIMAGE_IMAGES = ("camera", "moon", "coins", "astronaut", "coffee", "chelsea", "horse", "clock", "rocket", "hubble_deep_field", "immunohistochemistry")

SYNTHETIC_IMAGES = ("gradient", "checkerboard", "noise", "circles")

_ALIASES = {
    "house1": "house",
    "flower": "flowers",
    "pepper": "peppers",
    "mandril": "baboon",
    "jetplane": "airplane",
    "pirate": "man",
}


def to_gray_u8(image: np.ndarray) -> np.ndarray:
    img = np.asarray(image)
    if img.ndim == 3:
        img = cv2.cvtColor(img[..., :3], cv2.COLOR_RGB2GRAY)
    if img.dtype != np.uint8:
        img = img.astype(np.float64)
        if img.max() <= 1.0:
            img = img * 255.0
        img = np.clip(np.rint(img), 0, 255).astype(np.uint8)
    return img


def resize(image: np.ndarray, size: int = 256) -> np.ndarray:
    img = to_gray_u8(image)
    if img.shape != (size, size):
        interp = cv2.INTER_AREA if img.shape[0] > size else cv2.INTER_CUBIC
        img = cv2.resize(img, (size, size), interpolation=interp)
    return img


def synthetic_image(name: str, size: int = 256, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:size, 0:size]
    if name == "gradient":
        img = (xx + yy) / (2 * (size - 1)) * 255
    elif name == "checkerboard":
        img = (((xx // (size // 8)) + (yy // (size // 8))) % 2) * 200 + 30
    elif name == "noise":
        img = rng.integers(0, 256, (size, size))
    elif name == "circles":
        r = np.sqrt((xx - size / 2) ** 2 + (yy - size / 2) ** 2)
        img = (np.sin(r / 6.0) * 0.5 + 0.5) * 255
    else:
        raise KeyError(f"unknown synthetic image {name!r}")
    return np.clip(np.rint(img), 0, 255).astype(np.uint8)


def download_standard_images(names=None, dest: Path = DATA_DIR, overwrite: bool = False) -> list[Path]:
    """Download the standard test images (returns the local paths)."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    names = list(STANDARD_IMAGES) if names is None else list(names)
    paths = []
    for name in names:
        target = dest / f"{name}.png"
        if target.exists() and not overwrite:
            paths.append(target)
            continue
        url = _MIRROR + STANDARD_IMAGES[name]
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            buf = np.frombuffer(resp.read(), dtype=np.uint8)
        img = cv2.imdecode(buf, cv2.IMREAD_UNCHANGED)
        if img is None:
            raise RuntimeError(f"could not decode {url}")
        if img.ndim == 3:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        cv2.imwrite(str(target), to_gray_u8(img))
        paths.append(target)
    return paths


def load_image(name_or_path: str, size: int | None = 256) -> np.ndarray:
    """Load a grayscale test image by name (standard / scikit-image / synthetic) or path."""
    p = Path(name_or_path)
    if p.exists():
        img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
        if img is None:
            raise RuntimeError(f"could not read {p}")
    else:
        key = _ALIASES.get(str(name_or_path).strip().lower(), str(name_or_path).strip().lower())
        if key in STANDARD_IMAGES:
            local = DATA_DIR / f"{key}.png"
            if not local.exists():
                download_standard_images([key])
            img = cv2.imread(str(local), cv2.IMREAD_GRAYSCALE)
        elif key in SKIMAGE_IMAGES:
            import skimage.data as skdata

            img = to_gray_u8(getattr(skdata, key)())
        elif key in SYNTHETIC_IMAGES:
            img = synthetic_image(key, size or 256)
        else:
            raise KeyError(f"unknown image {name_or_path!r}")
    return resize(img, size) if size else to_gray_u8(img)


def load_image_preserve(name_or_path: str, size: int | None = None, allow_color: bool = False) -> np.ndarray:
    """Load an image preserving color RGB when ``allow_color=True`` and native size when ``size=None``."""
    p = Path(name_or_path)
    if p.exists() and allow_color:
        raw = cv2.imread(str(p), cv2.IMREAD_UNCHANGED)
        if raw is None:
            raise RuntimeError(f"could not read {p}")
        if raw.ndim == 3:
            rgb = cv2.cvtColor(raw[..., :3], cv2.COLOR_BGR2RGB)
            if size:
                interp = cv2.INTER_AREA if rgb.shape[0] > size else cv2.INTER_CUBIC
                rgb = cv2.resize(rgb, (size, size), interpolation=interp)
            return rgb.astype(np.uint8)
    return load_image(name_or_path, size)


def available_images(include_standard: bool = True) -> list[str]:
    names = list(SKIMAGE_IMAGES) + list(SYNTHETIC_IMAGES)
    if include_standard:
        names = list(STANDARD_IMAGES) + names
    return names


def default_image_set(offline: bool = False) -> list[str]:
    """Images used by the evaluation scripts."""
    if offline:
        return ["camera", "moon", "coins", "astronaut", "coffee", "chelsea", "horse", "clock"]
    return list(STANDARD_IMAGES) + ["camera", "moon", "coins", "astronaut"]


def save_image(image: np.ndarray, path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    arr = np.asarray(image)
    if arr.ndim == 3 and arr.shape[2] >= 3:
        arr = np.clip(np.rint(arr[..., :3]), 0, 255).astype(np.uint8)
        cv2.imwrite(str(path), cv2.cvtColor(arr, cv2.COLOR_RGB2BGR))
    else:
        cv2.imwrite(str(path), to_gray_u8(arr))
    return path
