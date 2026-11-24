"""
Keyed, blind, self-authenticating watermark (proposed extension, 2x2 blocks).

The base scheme derives the watermark from the *whole* 8-bit cover block and
then overwrites the two least significant bits, so the receiver can no longer
recompute it: extraction needs the reference watermark (131,072 side bits for
a 256x256 image), content changes that keep the LSBs go unnoticed, and anyone
who knows the algorithm can re-create a valid watermark.

This module keeps the base scheme's building blocks and payload (8 bits per
2x2 block, 2 bpp, LSB replacement) but changes *what* is embedded:

    Wb(b) = g(MSB(b))  xor  T_b . MSB(b)  xor  c_b

* ``g`` is the base scheme's content code (pixel position bits xor rounded
  arithmetic average, RPA + D4 + CNOT) evaluated on the six most significant
  bits of each pixel, which embedding never touches;
* ``T_b . MSB(b) xor c_b`` is a keyed one-time MAC (:class:`ToeplitzMAC`)
  of the block's 24 MSBs - a CNOT network in circuit form.

Verification is blind: recompute ``Wb`` from the received MSBs and the key,
read the two LSBs and compare (the QE step).  A block fails when anything in
it changed, an untouched block never fails, and an attacker without the key
passes a modified block with probability ``2**-8``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from qwm.secure.keys import ToeplitzMAC
from qwm.watermark.embedding import embed_image
from qwm.watermark.extraction import extract_image
from qwm.watermark.generation import generate_watermark

BLOCK = 2
TAG_BITS = 8
MSB_SHIFT = 2  # pixels keep bits 2..7
MSB_BITS = 8 - MSB_SHIFT
MSG_BITS = 4 * MSB_BITS  # 24 message bits per block
PIXEL_ORDER = ((0, 0), (0, 1), (1, 0), (1, 1))  # C00, C01, C10, C11

__all__ = ["SecureWatermark", "AuthenticationResult", "msb_message_bits", "content_code"]


def _even(image: np.ndarray) -> np.ndarray:
    img = np.asarray(image)
    h, w = (img.shape[0] // BLOCK) * BLOCK, (img.shape[1] // BLOCK) * BLOCK
    return img[:h, :w]


def msb_message_bits(image: np.ndarray) -> np.ndarray:
    """``(H/2, W/2, 24)`` MAC messages: bits 2..7 of C00, C01, C10, C11 (LSB first)."""
    img = _even(image).astype(np.int64)
    parts = []
    for r, c in PIXEL_ORDER:
        sub = img[r::2, c::2]
        for k in range(MSB_SHIFT, 8):
            parts.append((sub >> k) & 1)
    return np.stack(parts, axis=-1).astype(np.uint8)


def content_code(image: np.ndarray) -> np.ndarray:
    """Base-scheme watermark (PPB xor AA) of the MSB plane ``image & 0xFC``."""
    return generate_watermark(_even(image).astype(np.int64) & 0xFC)


@dataclass
class AuthenticationResult:
    """Outcome of a blind verification."""

    tamper_map: np.ndarray  # (H/2, W/2) bool, True = block failed
    extracted: np.ndarray  # (H/2, W/2, 8) bits read from the LSBs
    expected: np.ndarray  # (H/2, W/2, 8) bits recomputed from the MSBs and the key
    block: int = BLOCK

    @property
    def tampered_fraction(self) -> float:
        return float(self.tamper_map.mean()) if self.tamper_map.size else 0.0

    @property
    def authentic(self) -> bool:
        return not bool(self.tamper_map.any())

    def pixel_mask(self, shape=None) -> np.ndarray:
        """Tamper map expanded to pixel resolution (optionally padded to ``shape``)."""
        m = np.kron(self.tamper_map.astype(np.uint8), np.ones((self.block, self.block), dtype=np.uint8)).astype(bool)
        if shape is not None and tuple(shape[:2]) != m.shape:
            full = np.zeros(shape[:2], dtype=bool)
            full[: m.shape[0], : m.shape[1]] = m
            m = full
        return m


class SecureWatermark:
    """Blind fragile watermark with a keyed MAC on top of the base content code.

    >>> import numpy as np
    >>> img = np.random.default_rng(0).integers(0, 256, (16, 16), dtype=np.uint8)
    >>> sw = SecureWatermark("my secret key", nonce="image-001")
    >>> wm = sw.embed(img)
    >>> sw.verify(wm).authentic
    True
    """

    tag_bits = TAG_BITS
    block = BLOCK

    def __init__(self, key, nonce=b"", use_content_code: bool = True):
        self.key = key
        self.nonce = nonce
        self.use_content_code = use_content_code

    # ------------------------------------------------------------------ #
    def _mac(self, shape: tuple[int, int], channel: int) -> ToeplitzMAC:
        h, w = shape
        domain = f"auth2x2|{h}x{w}|ch{channel}"
        return ToeplitzMAC(self.key, self.nonce, domain, (h // BLOCK) * (w // BLOCK), MSG_BITS, TAG_BITS)

    def mac(self, shape: tuple[int, int], channel: int = 0) -> ToeplitzMAC:
        """The per-block MAC used for an image of ``shape`` (exposed for the circuits)."""
        return self._mac(tuple(shape[:2]), channel)

    def watermark_bits(self, image: np.ndarray, channel: int = 0) -> np.ndarray:
        """``(H/2, W/2, 8)`` watermark bits recomputed from the MSBs of a 2-D image."""
        img = _even(image)
        if img.ndim != 2:
            raise ValueError("watermark_bits expects a single 2-D channel")
        hb, wb = img.shape[0] // BLOCK, img.shape[1] // BLOCK
        msg = msb_message_bits(img).reshape(hb * wb, MSG_BITS)
        tags = self._mac(np.asarray(image).shape[:2], channel).tags(msg).reshape(hb, wb, TAG_BITS)
        if self.use_content_code:
            tags = tags ^ content_code(img)
        return tags

    # ------------------------------------------------------------------ #
    def _embed_channel(self, channel_img: np.ndarray, channel: int) -> np.ndarray:
        wm = self.watermark_bits(channel_img, channel)
        out, _ = embed_image(channel_img, wm, mode="lsb")
        return out

    def embed(self, cover: np.ndarray) -> np.ndarray:
        """Watermark a grayscale (H x W) or colour (H x W x C) uint8 image."""
        img = np.asarray(cover)
        if img.dtype != np.uint8:
            raise ValueError("cover must be uint8")
        if img.ndim == 2:
            return self._embed_channel(img, 0)
        if img.ndim == 3:
            return np.stack([self._embed_channel(img[..., c], c) for c in range(img.shape[2])], axis=-1)
        raise ValueError("expected a 2-D or 3-D image")

    def _verify_channel(self, channel_img: np.ndarray, channel: int) -> AuthenticationResult:
        expected = self.watermark_bits(channel_img, channel)
        extracted, _ = extract_image(channel_img)
        return AuthenticationResult(np.any(extracted != expected, axis=-1), extracted, expected)

    def verify(self, image: np.ndarray) -> AuthenticationResult:
        """Blind verification; colour images fail a block if any channel fails."""
        img = np.asarray(image)
        if img.ndim == 2:
            return self._verify_channel(img, 0)
        results = [self._verify_channel(img[..., c], c) for c in range(img.shape[2])]
        tamper = np.logical_or.reduce([r.tamper_map for r in results])
        return AuthenticationResult(
            tamper,
            np.concatenate([r.extracted for r in results], axis=-1),
            np.concatenate([r.expected for r in results], axis=-1),
        )
