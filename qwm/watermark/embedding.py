"""
Watermark embedding into the two least significant bits of every pixel.

Two embedding rules are provided.

``mode="paper"`` follows the reversible-circuit procedure of Sec. 3.3 /
Table 3 of the reference design literally.  For pixel bit ``k`` in ``{0, 1}``
with watermark bit ``w`` (``Wb_{2i+k}`` for the ``i``-th pixel of the block):

1. ``RPA``  : ``r = RPA(C^{k+1}, w)`` - the 1-qubit adder result, read as
   "sum or carry" so that ``|1> + |1> -> |1>`` as in Table 3;
2. ``XOR``  : ``x = r xor C^{k+1}``;
3. ``QE``   : compare ``x`` with the current bit ``C^k``;
4. ``Pauli-X``: if they are equal flip ``x``;
5. the result replaces ``C^k``.

Steps 3-4 map any ``x`` to ``not C^k``, so this rule always inverts the two
LSBs of the cover pixel - the watermarked image is independent of the
watermark content (the content is instead verified during extraction, where
the QE model compares the recovered LSBs with the reference watermark).

``mode="lsb"`` performs plain LSB replacement, i.e. Step 1 of Sec. 3.3
("``Wb_0`` and ``Wb_1`` embed to ``C^0`` and ``C^1``"), which yields a blind,
content-carrying 2 bpp watermark.
"""

from __future__ import annotations

import numpy as np

from qwm.watermark.generation import BITS_PER_BLOCK, generate_watermark

MODES = ("paper", "lsb", "opap")


def _opap_2bit(original: np.ndarray, embedded: np.ndarray) -> np.ndarray:
    """Chan-Cheng Optimal Pixel Adjustment Process for 2-bit LSB embedding.

    When ``embedded - original`` is ``+3`` (or ``-3``) and shifting the MSB
    plane by ``-4`` (or ``+4``) stays within ``[0, 255]``, error drops from
    ``±3`` (squared error 9) to ``∓1`` (squared error 1) while leaving the two
    embedded LSBs untouched.
    """
    orig = np.asarray(original, dtype=np.int64)
    out = np.asarray(embedded, dtype=np.int64).copy()
    diff = out - orig
    sub_mask = (diff == 3) & (out >= 4)
    add_mask = (diff == -3) & (out <= 251)
    out[sub_mask] -= 4
    out[add_mask] += 4
    return out


def rpa_result_1bit(a: int, w: int) -> int:
    """1-qubit RPA read-out used in Table 3: ``sum xor carry`` (``= a or w``)."""
    s, c = (a ^ w), (a & w)
    return s ^ c


def embed_pixel_trace(pixel: int, w0: int, w1: int) -> dict:
    """Step-by-step embedding of one pixel (``mode="paper"``), see Table 3."""
    pixel = int(pixel)
    bits = [(pixel >> k) & 1 for k in range(8)]
    steps = []
    for k, w in ((0, w0), (1, w1)):
        a, c = bits[k + 1], bits[k]
        r = rpa_result_1bit(a, w)
        x = r ^ a
        eq = int(x == c)
        new = x ^ eq
        steps.append(
            {
                "bit": k,
                "watermark_bit": w,
                "rpa_inputs": (a, w),
                "rpa_result": r,
                "xor_result": x,
                "qe_equal": eq,
                "pauli_x_applied": bool(eq),
                "embedded_bit": new,
            }
        )
        bits[k] = new
    new_pixel = sum(b << k for k, b in enumerate(bits))
    return {"pixel": pixel, "steps": steps, "watermarked_pixel": new_pixel}


def embed_pixel(pixel: int, w0: int, w1: int, mode: str = "paper") -> int:
    if mode == "paper":
        return embed_pixel_trace(pixel, w0, w1)["watermarked_pixel"]
    if mode in ("lsb", "opap"):
        orig = int(pixel)
        out = (orig & ~0b11) | ((int(w1) & 1) << 1) | (int(w0) & 1)
        if mode == "opap":
            diff = out - orig
            if diff == 3 and out >= 4:
                out -= 4
            elif diff == -3 and out <= 251:
                out += 4
        return out
    raise ValueError(f"unknown mode {mode!r}; expected one of {MODES}")


def embed_block(block, watermark_bits, mode: str = "paper") -> np.ndarray:
    """Embed eight watermark bits into a ``2x2`` block."""
    b = np.asarray(block, dtype=np.int64).reshape(-1)
    wb = [int(v) for v in watermark_bits]
    out = [embed_pixel(b[i], wb[2 * i], wb[2 * i + 1], mode) for i in range(4)]
    return np.asarray(out, dtype=np.uint8).reshape(2, 2)


def embed_image(image: np.ndarray, watermark: np.ndarray | None = None, mode: str = "paper") -> tuple[np.ndarray, np.ndarray]:
    """Embed a watermark into every ``2x2`` block of ``image``.

    Parameters
    ----------
    image:
        2-D uint8 cover image.
    watermark:
        ``(H//2, W//2, 8)`` bit array; generated from the cover if ``None``.
    mode:
        ``"paper"`` or ``"lsb"`` (see module docstring).

    Returns
    -------
    (watermarked_image, watermark_bits)
    """
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}; expected one of {MODES}")
    img = np.asarray(image)
    if img.ndim != 2:
        raise ValueError("expected a 2-D grayscale image")
    if watermark is None:
        watermark = generate_watermark(img)
    watermark = np.asarray(watermark, dtype=np.int64)
    h, w = 2 * watermark.shape[0], 2 * watermark.shape[1]
    out = img.astype(np.int64).copy()
    region = out[:h, :w]
    if mode == "paper":
        # RPA -> XOR -> QE -> Pauli-X reduces to inverting both LSBs.
        region ^= 0b11
    else:
        wb = watermark
        orig_region = region.copy() if mode == "opap" else None
        for i, (r, c) in enumerate(((0, 0), (0, 1), (1, 0), (1, 1))):
            sub = region[r::2, c::2]
            sub &= ~0b11
            sub |= wb[..., 2 * i] | (wb[..., 2 * i + 1] << 1)
        if mode == "opap":
            region[:] = _opap_2bit(orig_region, region)
    return out.astype(np.uint8), watermark.astype(np.uint8)


def payload_capacity(image_shape: tuple[int, int]) -> dict:
    """Payload figures of Sec. 4.3 (8 bits per ``2x2`` block = 2 bpp)."""
    h, w = image_shape[0] // 2 * 2, image_shape[1] // 2 * 2
    blocks = (h // 2) * (w // 2)
    total_bits = blocks * BITS_PER_BLOCK
    return {
        "pixels": h * w,
        "blocks": blocks,
        "bits_embedded": total_bits,
        "bpp": total_bits / (h * w) if h * w else 0.0,
    }
