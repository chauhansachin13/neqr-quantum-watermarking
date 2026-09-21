"""
Watermark qubit generation: pixel position bits (PPB) + arithmetic average (AA).

For every non-overlapping ``2x2`` block ``[[C00, C01], [C10, C11]]`` of the
cover image eight watermark bits ``Wb_0 .. Wb_7`` are derived from the
block's own content (Sec. 3.2):

**Pixel position bits** (Sec. 3.2.1, Fig. 9).  Each 8-bit pixel ``P_i`` is
split into its low nibble ``P_i^(L) = b_3 b_2 b_1 b_0`` and high nibble
``P_i^(R) = b_7 b_6 b_5 b_4``.  A 4-bit RPA adds the two nibbles and yields
two 4-qubit registers - the sum bits ``T_{i,2}`` and the carry bits
``T_{i,1}``.  A CNOT chain (``CNOT^(x)4``) reduces each register to its parity
and a final CNOT combines the two parities::

    PPB_{i,1} = parity(carries)
    PPB_{i,2} = parity(sum bits) xor PPB_{i,1}

**Arithmetic average** (Sec. 3.2.2).  Three RPAs sum the four pixels and the
D4 module divides by four with rounding: ``AA = floor(S / 4 + 0.5)``.  Its
8-bit binary expansion is ``s_7 .. s_0``.

**Watermark bits** (Fig. 10/11).  ``Wb_k = s_k xor PPB_{floor(k/2)+1, (k mod 2)+1}``.

Worked example from the reference design: block ``[[50, 60], [48, 32]]``
gives ``PPB = (1,1), (0,0), (0,0), (0,1)``, ``AA = 48`` and
``Wb = 1,1,0,0,1,1,0,1`` (``Wb_0`` first).
"""

from __future__ import annotations

import numpy as np

from qwm.gates.adder import ReverseParallelAdder

BLOCK = 2
BITS_PER_BLOCK = 8


def parity(bits) -> int:
    p = 0
    for b in bits:
        p ^= int(b) & 1
    return p


def nibbles(pixel: int) -> tuple[int, int]:
    """``(low, high)`` 4-bit halves of an 8-bit pixel."""
    pixel = int(pixel)
    return pixel & 0xF, (pixel >> 4) & 0xF


def pixel_position_bits(pixel: int) -> tuple[int, int]:
    """``(PPB_1, PPB_2)`` of a single pixel (classical reference)."""
    low, high = nibbles(pixel)
    s, _ = ReverseParallelAdder.add(low, high, 4)
    carries = ReverseParallelAdder.carries(low, high, 4)
    p_carry = parity(carries)
    p_sum = parity((s >> k) & 1 for k in range(4))
    return p_carry, p_sum ^ p_carry


def arithmetic_average(block) -> int:
    """``floor(sum / 4 + 0.5)`` of a ``2x2`` block (RPA + D4 with rounding)."""
    total = int(np.asarray(block, dtype=np.int64).sum())
    return (total + 2) >> 2


def block_pixels(block) -> list[int]:
    """Pixels of a block in the order ``C00, C01, C10, C11``."""
    b = np.asarray(block, dtype=np.int64)
    return [int(v) for v in b.reshape(-1)]


def block_watermark_bits(block) -> list[int]:
    """The eight watermark bits ``Wb_0..Wb_7`` of one ``2x2`` block."""
    pixels = block_pixels(block)
    if len(pixels) != 4:
        raise ValueError("block must contain exactly four pixels")
    aa = arithmetic_average(block)
    ppb = [pixel_position_bits(p) for p in pixels]
    return [((aa >> k) & 1) ^ ppb[k // 2][k % 2] for k in range(BITS_PER_BLOCK)]


def block_trace(block) -> dict:
    """All intermediate quantities of the generation step (for reports/tests)."""
    pixels = block_pixels(block)
    total = sum(pixels)
    aa = arithmetic_average(block)
    ppb = [pixel_position_bits(p) for p in pixels]
    return {
        "pixels": pixels,
        "sum": total,
        "aa": aa,
        "aa_bits": [(aa >> k) & 1 for k in range(8)],
        "ppb": ppb,
        "watermark": block_watermark_bits(block),
    }


# --------------------------------------------------------------------------- #
# Vectorised full-image versions
# --------------------------------------------------------------------------- #
def _ppb_array(pixels: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Vectorised :func:`pixel_position_bits` for an integer array."""
    p = pixels.astype(np.int64)
    low, high = p & 0xF, (p >> 4) & 0xF
    s = (low + high) & 0xF
    # ripple carries
    c = np.zeros_like(p)
    carry_parity = np.zeros_like(p)
    for k in range(4):
        lk, hk = (low >> k) & 1, (high >> k) & 1
        c = (lk & hk) | ((lk ^ hk) & c)
        carry_parity ^= c
    sum_parity = ((s) ^ (s >> 1) ^ (s >> 2) ^ (s >> 3)) & 1
    ppb1 = carry_parity
    ppb2 = sum_parity ^ ppb1
    return ppb1, ppb2


def generate_watermark(image: np.ndarray) -> np.ndarray:
    """Watermark bits of every ``2x2`` block of ``image``.

    Returns an array of shape ``(H//2, W//2, 8)`` with ``[..., k] = Wb_k``.
    Odd trailing rows/columns are ignored.
    """
    img = np.asarray(image)
    if img.ndim != 2:
        raise ValueError("expected a 2-D grayscale image")
    h, w = (img.shape[0] // BLOCK) * BLOCK, (img.shape[1] // BLOCK) * BLOCK
    img = img[:h, :w].astype(np.int64)
    c00, c01 = img[0::2, 0::2], img[0::2, 1::2]
    c10, c11 = img[1::2, 0::2], img[1::2, 1::2]
    aa = (c00 + c01 + c10 + c11 + 2) >> 2
    ppbs = [_ppb_array(c) for c in (c00, c01, c10, c11)]
    out = np.zeros((h // BLOCK, w // BLOCK, BITS_PER_BLOCK), dtype=np.uint8)
    for k in range(BITS_PER_BLOCK):
        out[..., k] = ((aa >> k) & 1) ^ ppbs[k // 2][k % 2]
    return out


def watermark_to_image(bits: np.ndarray) -> np.ndarray:
    """Pack ``(h, w, 8)`` watermark bits into an ``(h, w)`` uint8 image (for display)."""
    bits = np.asarray(bits, dtype=np.int64)
    return sum((bits[..., k] << k) for k in range(bits.shape[-1])).astype(np.uint8)
