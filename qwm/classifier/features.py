"""Feature extraction for attack classification.

Two feature representations are available:

* ``"pixels"`` (Sec. 4.8.2 / Table 17 of the reference design): the attacked
  watermarked image is kept as a fixed-size grayscale matrix, its intensities
  are normalised to ``[0, 1]`` and flattened (``256 x 256 -> 65,536`` features).
* ``"descriptors"``: a compact vector (~140 values) of distortion-sensitive
  statistics - intensity histogram and entropy, saturated-pixel and border
  statistics, median-residual and gradient statistics, high-frequency energy,
  8x8 blockiness, bit-plane statistics and a coarse thumbnail.  These
  describe *how* an image was distorted rather than *what* it shows, which
  makes the classifier robust to unseen cover images and attack strengths.
"""

from __future__ import annotations

import cv2
import numpy as np
from scipy import stats

FEATURE_KINDS = ("pixels", "descriptors")


def image_to_feature(image: np.ndarray, size: int = 256) -> np.ndarray:
    """Normalised, flattened pixel intensities (``"pixels"`` representation)."""
    img = np.asarray(image)
    if img.ndim != 2:
        raise ValueError("expected a 2-D grayscale image")
    if img.shape != (size, size):
        img = cv2.resize(img, (size, size), interpolation=cv2.INTER_AREA)
    return (img.astype(np.float32) / 255.0).reshape(-1)


def _border_zero_fractions(img: np.ndarray, width: int = 4) -> list[float]:
    return [
        float((img[:width, :] == 0).mean()),
        float((img[-width:, :] == 0).mean()),
        float((img[:, :width] == 0).mean()),
        float((img[:, -width:] == 0).mean()),
    ]


def _high_frequency_ratios(img: np.ndarray) -> list[float]:
    f = np.abs(np.fft.fftshift(np.fft.fft2(img.astype(np.float64) - img.mean()))) ** 2
    h, w = f.shape
    yy, xx = np.mgrid[0:h, 0:w]
    r = np.sqrt((yy - h / 2) ** 2 + (xx - w / 2) ** 2) / (min(h, w) / 2)
    total = f.sum() + 1e-12
    return [float(f[r > t].sum() / total) for t in (0.1, 0.25, 0.5, 0.75)]


def _blockiness(img: np.ndarray, block: int = 8) -> list[float]:
    x = img.astype(np.float64)
    dh = np.abs(np.diff(x, axis=1))
    dv = np.abs(np.diff(x, axis=0))
    cols = np.arange(dh.shape[1])
    rows = np.arange(dv.shape[0])
    at_h = dh[:, (cols + 1) % block == 0].mean() if dh.size else 0.0
    off_h = dh[:, (cols + 1) % block != 0].mean() if dh.size else 0.0
    at_v = dv[(rows + 1) % block == 0, :].mean() if dv.size else 0.0
    off_v = dv[(rows + 1) % block != 0, :].mean() if dv.size else 0.0
    return [float(at_h / (off_h + 1e-6)), float(at_v / (off_v + 1e-6))]


def image_descriptors(image: np.ndarray, size: int = 256) -> np.ndarray:
    """Distortion-sensitive descriptor vector (``"descriptors"`` representation)."""
    img = np.asarray(image)
    if img.ndim != 2:
        raise ValueError("expected a 2-D grayscale image")
    if img.shape != (size, size):
        img = cv2.resize(img, (size, size), interpolation=cv2.INTER_AREA)
    img = img.astype(np.uint8)
    x = img.astype(np.float64)
    feats: list[float] = []

    # intensity histogram, entropy, flatness, number of used levels
    hist = np.bincount(img.ravel(), minlength=256).astype(np.float64)
    hist /= hist.sum()
    feats += list(hist.reshape(32, 8).sum(axis=1))
    nz = hist[hist > 0]
    feats += [float(-(nz * np.log2(nz)).sum()), float(np.std(hist) * 256), float((hist > 0).sum() / 256.0)]
    feats += [float(x.mean() / 255.0), float(x.std() / 255.0), float(stats.skew(x.ravel())), float(stats.kurtosis(x.ravel()))]

    # saturated pixels and zero borders (impulse noise, cropping, rotation)
    feats += [float((img == 0).mean()), float((img == 255).mean())]
    feats += _border_zero_fractions(img)
    feats += [float(((img == 0) | (img == 255)).mean())]

    # median residual statistics (noise / smoothing signature)
    res = x - cv2.medianBlur(img, 3).astype(np.float64)
    ares = np.abs(res)
    feats += [float(ares.mean()), float(res.std()), float(stats.kurtosis(res.ravel())), float((ares > 8).mean()), float((ares > 32).mean()), float((ares == 0).mean())]

    # gradient / sharpness statistics
    gx = cv2.Sobel(x, cv2.CV_64F, 1, 0, ksize=3)
    gy = cv2.Sobel(x, cv2.CV_64F, 0, 1, ksize=3)
    mag = np.hypot(gx, gy)
    lap = cv2.Laplacian(x, cv2.CV_64F)
    feats += [float(mag.mean()), float(mag.std()), float(lap.var()), float((mag < 1.0).mean())]

    # spectral energy and JPEG blockiness
    feats += _high_frequency_ratios(img)
    feats += _blockiness(img)

    # bit-plane statistics (LSB watermark planes are sensitive to every attack)
    b0, b1, b2 = img & 1, (img >> 1) & 1, (img >> 2) & 1
    feats += [float(b0.mean()), float(b1.mean()), float(b2.mean())]
    feats += [float(np.mean(b0 == b1)), float(np.mean(b0[:, :-1] == b0[:, 1:])), float(np.mean(b0[:-1, :] == b0[1:, :]))]

    # local variance distribution
    mean_local = cv2.blur(x, (5, 5))
    var_local = cv2.blur(x * x, (5, 5)) - mean_local**2
    feats += list(np.percentile(var_local, [5, 25, 50, 75, 95]) / 255.0**2)

    # coarse thumbnail (spatial layout: text, cropped regions, rotation corners)
    thumb = cv2.resize(img, (8, 8), interpolation=cv2.INTER_AREA).astype(np.float64) / 255.0
    feats += list(thumb.ravel())
    return np.asarray(feats, dtype=np.float32)


def descriptor_names() -> list[str]:
    """Names of the entries of :func:`image_descriptors`, in order."""
    names = [f"hist_bin_{i:02d}" for i in range(32)]
    names += ["entropy", "hist_spread", "used_levels", "mean", "std", "skewness", "kurtosis"]
    names += ["frac_black", "frac_white", "border_black_top", "border_black_bottom", "border_black_left", "border_black_right", "frac_saturated"]
    names += ["median_res_absmean", "median_res_std", "median_res_kurtosis", "median_res_gt8", "median_res_gt32", "median_res_zero"]
    names += ["gradient_mean", "gradient_std", "laplacian_var", "flat_fraction"]
    names += ["hf_energy_0.10", "hf_energy_0.25", "hf_energy_0.50", "hf_energy_0.75", "blockiness_h", "blockiness_v"]
    names += ["bitplane0_mean", "bitplane1_mean", "bitplane2_mean", "bitplane0_eq_1", "bitplane0_hcorr", "bitplane0_vcorr"]
    names += [f"local_var_p{p}" for p in (5, 25, 50, 75, 95)]
    names += [f"thumb_{r}{c}" for r in range(8) for c in range(8)]
    return names


def extract_features(image: np.ndarray, kind: str = "pixels", size: int = 256) -> np.ndarray:
    if kind == "pixels":
        return image_to_feature(image, size)
    if kind == "descriptors":
        return image_descriptors(image, size)
    raise ValueError(f"unknown feature kind {kind!r}; expected one of {FEATURE_KINDS}")


def feature_length(kind: str = "pixels", size: int = 256) -> int:
    if kind == "pixels":
        return size * size
    return int(extract_features(np.zeros((size, size), dtype=np.uint8), kind, size).shape[0])
