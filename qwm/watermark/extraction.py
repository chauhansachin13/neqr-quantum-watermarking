"""
Watermark extraction from a watermarked (and possibly attacked) image.

Sec. 3.4 / Table 4 of the reference design, for pixel bit ``k`` in ``{0, 1}``:

1. ``XOR``     : ``x = W^{k+1} xor W^k``;
2. ``RPS``     : ``d = RPS(x, W^{k+1})`` - the 1-qubit difference ``x - W^{k+1}``,
   which equals the embedded bit ``W^k``;
3. ``QE``      : compare ``d`` with the reference watermark bit ``Wb``;
4. ``Pauli-X`` : if they differ, flip ``d``.

The *raw* bits (after step 2) are what a blind receiver observes; the
*corrected* bits (after step 4) are the reference-verified output.  Comparing
raw and reference bits gives the bit error rate and a per-block tamper map.
"""

from __future__ import annotations

import numpy as np

from qwm.gates.subtractor import ReverseParallelSubtractor
from qwm.watermark.generation import BITS_PER_BLOCK


def extract_pixel_trace(pixel: int, reference: tuple[int, int] | None = None) -> dict:
    """Step-by-step extraction of the two bits hidden in one pixel (Table 4)."""
    pixel = int(pixel)
    bits = [(pixel >> k) & 1 for k in range(8)]
    steps, raw, corrected = [], [], []
    for k in range(2):
        x = bits[k + 1] ^ bits[k]
        d, _ = ReverseParallelSubtractor.subtract(x, bits[k + 1], 1)
        entry = {"bit": k, "xor_result": x, "rps_result": d}
        out = d
        if reference is not None:
            eq = int(d == int(reference[k]))
            out = d if eq else d ^ 1
            entry.update({"reference_bit": int(reference[k]), "qe_equal": eq, "pauli_x_applied": not eq})
        entry["extracted_bit"] = out
        steps.append(entry)
        raw.append(d)
        corrected.append(out)
    return {"pixel": pixel, "steps": steps, "raw_bits": raw, "extracted_bits": corrected}


def extract_block(block, reference_bits=None) -> tuple[list[int], list[int]]:
    """``(raw_bits, extracted_bits)`` of a ``2x2`` watermarked block."""
    b = np.asarray(block, dtype=np.int64).reshape(-1)
    raw, out = [], []
    for i in range(4):
        ref = None if reference_bits is None else (reference_bits[2 * i], reference_bits[2 * i + 1])
        t = extract_pixel_trace(b[i], ref)
        raw += t["raw_bits"]
        out += t["extracted_bits"]
    return raw, out


def extract_image(image: np.ndarray, reference: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray | None]:
    """Vectorised extraction for a whole image.

    Returns ``(raw_bits, corrected_bits)`` with shape ``(H//2, W//2, 8)``;
    ``corrected_bits`` is ``None`` when no reference watermark is given.
    """
    img = np.asarray(image)
    if img.ndim != 2:
        raise ValueError("expected a 2-D grayscale image")
    h, w = (img.shape[0] // 2) * 2, (img.shape[1] // 2) * 2
    img = img[:h, :w].astype(np.int64)
    raw = np.zeros((h // 2, w // 2, BITS_PER_BLOCK), dtype=np.uint8)
    for i, (r, c) in enumerate(((0, 0), (0, 1), (1, 0), (1, 1))):
        sub = img[r::2, c::2]
        # XOR followed by RPS difference recovers bit k: (W^{k+1} ^ W^k) - W^{k+1} = W^k
        raw[..., 2 * i] = (((sub >> 1) ^ sub) ^ (sub >> 1)) & 1
        raw[..., 2 * i + 1] = (((sub >> 2) ^ (sub >> 1)) ^ (sub >> 2)) & 1
    if reference is None:
        return raw, None
    ref = np.asarray(reference, dtype=np.uint8)
    hh, ww = min(ref.shape[0], raw.shape[0]), min(ref.shape[1], raw.shape[1])
    corrected = raw[:hh, :ww].copy()
    equal = corrected == ref[:hh, :ww]
    corrected = np.where(equal, corrected, corrected ^ 1)
    return raw, corrected


def bit_error_rate(bits_a: np.ndarray, bits_b: np.ndarray) -> float:
    a, b = np.asarray(bits_a, dtype=np.int64), np.asarray(bits_b, dtype=np.int64)
    if a.shape != b.shape:
        raise ValueError("bit arrays must have the same shape")
    return float(np.mean(a != b)) if a.size else 0.0


def normalized_correlation(bits_a: np.ndarray, bits_b: np.ndarray) -> float:
    """NC between two bit arrays mapped to ``{-1, +1}``."""
    a = 2.0 * np.asarray(bits_a, dtype=np.float64) - 1.0
    b = 2.0 * np.asarray(bits_b, dtype=np.float64) - 1.0
    denom = np.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / denom) if denom else 0.0


def tamper_map(raw_bits: np.ndarray, reference: np.ndarray) -> np.ndarray:
    """Boolean ``(H//2, W//2)`` map: ``True`` where a block's bits disagree with the reference."""
    a, b = np.asarray(raw_bits, dtype=np.uint8), np.asarray(reference, dtype=np.uint8)
    hh, ww = min(a.shape[0], b.shape[0]), min(a.shape[1], b.shape[1])
    return np.any(a[:hh, :ww] != b[:hh, :ww], axis=-1)
