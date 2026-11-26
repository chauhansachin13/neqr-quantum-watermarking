"""Image quality metrics: MSE, PSNR, SSIM (Eqs. 17-19) and histograms."""

from __future__ import annotations

import numpy as np


def _pair(a, b) -> tuple[np.ndarray, np.ndarray]:
    a, b = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    if a.shape != b.shape:
        raise ValueError(f"shape mismatch: {a.shape} vs {b.shape}")
    return a, b


def mse(original, distorted) -> float:
    """Mean squared error (Eq. 17)."""
    a, b = _pair(original, distorted)
    return float(np.mean((a - b) ** 2))


def psnr(original, distorted, peak: float = 255.0) -> float:
    """Peak signal-to-noise ratio in dB (Eq. 18); ``inf`` for identical images."""
    err = mse(original, distorted)
    if err == 0:
        return float("inf")
    return float(10.0 * np.log10(peak**2 / err))


def ssim_global(original, distorted, peak: float = 255.0, k1: float = 0.01, k2: float = 0.03) -> float:
    """Structural similarity computed with global statistics (Eq. 19)."""
    x, y = _pair(original, distorted)
    c1, c2 = (k1 * peak) ** 2, (k2 * peak) ** 2
    mu_x, mu_y = x.mean(), y.mean()
    var_x, var_y = x.var(), y.var()
    cov = np.mean((x - mu_x) * (y - mu_y))
    num = (2 * mu_x * mu_y + c1) * (2 * cov + c2)
    den = (mu_x**2 + mu_y**2 + c1) * (var_x + var_y + c2)
    return float(num / den)


def ssim(original, distorted, peak: float = 255.0) -> float:
    """Windowed SSIM (7x7 uniform window, standard implementation)."""
    from skimage.metrics import structural_similarity

    x, y = _pair(original, distorted)
    channel_axis = -1 if x.ndim == 3 else None
    return float(structural_similarity(x, y, data_range=peak, channel_axis=channel_axis))


def histogram(image, bins: int = 256) -> np.ndarray:
    """Grey-level histogram (frequency of every intensity)."""
    hist, _ = np.histogram(np.asarray(image).ravel(), bins=bins, range=(0, bins))
    return hist


def histogram_similarity(original, distorted, bins: int = 256) -> float:
    """Histogram intersection in ``[0, 1]`` (1 = identical histograms)."""
    h1, h2 = histogram(original, bins), histogram(distorted, bins)
    return float(np.minimum(h1, h2).sum() / max(h1.sum(), 1))


def quality_report(original, distorted) -> dict[str, float]:
    """All image metrics in one dictionary."""
    return {
        "mse": mse(original, distorted),
        "psnr": psnr(original, distorted),
        "ssim": ssim(original, distorted),
        "ssim_global": ssim_global(original, distorted),
        "histogram_similarity": histogram_similarity(original, distorted),
    }
