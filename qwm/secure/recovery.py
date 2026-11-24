"""
Self-recovering keyed watermark (proposed extension, 4x4 blocks).

Same payload as the base scheme - two LSBs per pixel, 2 bpp - but organised
so that a tampered region can be *repaired*, the future-work item named by
the reference design ("tamper detection and self-recovery").

For every 4x4 block ``B`` (four 2x2 sub-blocks, 32 LSB slots):

* **Recovery code** ``rec(B)``: the rounded arithmetic average of each 2x2
  sub-block - exactly the AA that the base scheme computes with RPA + D4 -
  truncated to its 5 most significant bits (4 x 5 = 20 bits).
* ``rec(B)`` is stored in a keyed **partner** block ``P = pi(B)``
  (:func:`keyed_derangement`), far away from ``B`` on average, so a local
  edit rarely destroys a block together with its backup.
* **Authentication tag** ``tag(P)``: a 12-bit keyed one-time MAC of the
  partner's 96 MSBs together with the 20 recovery bits it carries
  (``116`` message bits).  Any change to a block - MSBs, stored recovery
  bits or tag - is caught except with probability ``2**-12``.

Verification is blind and per block.  A failed block ``B`` is rebuilt from
the recovery code held by ``pi(B)`` when that partner verifies; the few
blocks whose partner was also hit are filled by inpainting.  By default the
rebuilt area is interpolated on the 2x2 sub-block grid (true means of the
authentic neighbours plus the decoded codes, upsampled bilinearly), which
beats flat 2x2 patches by a few tenths of a dB on most images; authentic
pixels are never modified.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from qwm.secure.keys import ToeplitzMAC, keyed_derangement

RBLOCK = 4
SUB = 2
REC_BITS_PER_SUB = 5
REC_BITS = 4 * REC_BITS_PER_SUB  # 20
TAG_BITS = 12
SLOTS = RBLOCK * RBLOCK * 2  # 32 LSB slots per block
MSB_SHIFT = 2
MSG_BITS = RBLOCK * RBLOCK * (8 - MSB_SHIFT) + REC_BITS  # 96 + 20 = 116
SUB_ORDER = ((0, 0), (0, 2), (2, 0), (2, 2))  # sub-block offsets inside a 4x4 block

__all__ = ["SelfRecoveringWatermark", "RecoveryResult", "recovery_codes", "decode_recovery_codes"]


def _crop(image: np.ndarray) -> np.ndarray:
    img = np.asarray(image)
    h, w = (img.shape[0] // RBLOCK) * RBLOCK, (img.shape[1] // RBLOCK) * RBLOCK
    return img[:h, :w]


def _to_blocks(img: np.ndarray) -> np.ndarray:
    """``(H, W)`` -> ``(nb, 16)`` pixels of every 4x4 block in raster order."""
    h, w = img.shape
    return img.reshape(h // RBLOCK, RBLOCK, w // RBLOCK, RBLOCK).transpose(0, 2, 1, 3).reshape(-1, RBLOCK * RBLOCK)


def _from_blocks(blocks: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    h, w = shape
    return blocks.reshape(h // RBLOCK, w // RBLOCK, RBLOCK, RBLOCK).transpose(0, 2, 1, 3).reshape(h, w)


def recovery_codes(image: np.ndarray) -> np.ndarray:
    """``(nb, 4)`` 5-bit codes: ``AA(sub-block) >> 3`` with ``AA = floor(sum/4 + 0.5)``."""
    img = _crop(image).astype(np.int64)
    blocks = _to_blocks(img).reshape(-1, RBLOCK, RBLOCK)
    codes = []
    for r, c in SUB_ORDER:
        s = blocks[:, r : r + SUB, c : c + SUB].sum(axis=(1, 2))
        aa = (s + 2) >> 2  # rounded arithmetic average (RPA + D4)
        codes.append(aa >> (8 - REC_BITS_PER_SUB))
    return np.stack(codes, axis=-1)


def decode_recovery_codes(codes: np.ndarray) -> np.ndarray:
    """5-bit codes -> mid-point intensities of the quantisation cells."""
    step = 1 << (8 - REC_BITS_PER_SUB)
    return np.clip(np.asarray(codes, dtype=np.int64) * step + step // 2, 0, 255)


def _codes_to_bits(codes: np.ndarray) -> np.ndarray:
    k = np.arange(REC_BITS_PER_SUB)
    return ((codes[..., None] >> k) & 1).reshape(codes.shape[0], REC_BITS).astype(np.uint8)


def _bits_to_codes(bits: np.ndarray) -> np.ndarray:
    b = bits.reshape(bits.shape[0], 4, REC_BITS_PER_SUB).astype(np.int64)
    return (b << np.arange(REC_BITS_PER_SUB)).sum(axis=-1)


def _msb_bits(blocks: np.ndarray) -> np.ndarray:
    """``(nb, 16)`` pixels -> ``(nb, 96)`` bits 2..7 of every pixel (LSB first)."""
    k = np.arange(MSB_SHIFT, 8)
    return ((blocks[..., None] >> k) & 1).reshape(blocks.shape[0], -1).astype(np.uint8)


def _lsb_slots(blocks: np.ndarray) -> np.ndarray:
    """``(nb, 16)`` pixels -> ``(nb, 32)`` slots (pixel-major: bit 0 then bit 1)."""
    return np.stack([blocks & 1, (blocks >> 1) & 1], axis=-1).reshape(blocks.shape[0], SLOTS).astype(np.uint8)


def _write_slots(blocks: np.ndarray, slots: np.ndarray) -> np.ndarray:
    s = slots.reshape(blocks.shape[0], RBLOCK * RBLOCK, 2).astype(np.int64)
    return (blocks & ~0b11) | s[..., 0] | (s[..., 1] << 1)


@dataclass
class RecoveryResult:
    """Outcome of verification plus self-recovery."""

    recovered: np.ndarray  # repaired image (same shape as the input)
    tamper_map: np.ndarray  # (H/4, W/4) bool, True = block failed verification
    restored_map: np.ndarray  # blocks rebuilt from their partner's recovery code
    inpainted_map: np.ndarray  # blocks whose partner also failed (inpainted)
    block: int = RBLOCK
    extra: dict = field(default_factory=dict)

    @property
    def tampered_fraction(self) -> float:
        return float(self.tamper_map.mean()) if self.tamper_map.size else 0.0

    @property
    def authentic(self) -> bool:
        return not bool(self.tamper_map.any())

    @property
    def restored_fraction(self) -> float:
        """Share of the failed blocks that were rebuilt from recovery codes."""
        n = int(self.tamper_map.sum())
        return float(self.restored_map.sum() / n) if n else 1.0

    def pixel_mask(self, which: str = "tamper", shape=None) -> np.ndarray:
        src = {"tamper": self.tamper_map, "restored": self.restored_map, "inpainted": self.inpainted_map}[which]
        m = np.kron(src.astype(np.uint8), np.ones((self.block, self.block), dtype=np.uint8)).astype(bool)
        if shape is not None and tuple(shape[:2]) != m.shape:
            full = np.zeros(shape[:2], dtype=bool)
            full[: m.shape[0], : m.shape[1]] = m
            m = full
        return m


class SelfRecoveringWatermark:
    """Keyed fragile watermark with tamper localisation and self-recovery.

    >>> import numpy as np
    >>> from qwm.data import synthetic_image
    >>> img = synthetic_image("circles", 64)
    >>> srw = SelfRecoveringWatermark("k3y", nonce="demo")
    >>> wm = srw.embed(img)
    >>> bad = wm.copy(); bad[8:24, 8:24] = 255
    >>> res = srw.recover(bad)
    >>> bool(res.tamper_map.any()), res.restored_fraction > 0.8
    (True, True)
    """

    tag_bits = TAG_BITS
    block = RBLOCK
    RECONSTRUCTIONS = ("interpolate", "flat")

    def __init__(self, key, nonce=b"", reconstruction: str = "interpolate"):
        if reconstruction not in self.RECONSTRUCTIONS:
            raise ValueError(f"reconstruction must be one of {self.RECONSTRUCTIONS}")
        self.key = key
        self.nonce = nonce
        self.reconstruction = reconstruction

    # ------------------------------------------------------------------ #
    def _domain(self, shape: tuple[int, int], channel: int) -> str:
        return f"recover4x4|{shape[0]}x{shape[1]}|ch{channel}"

    def mac(self, shape: tuple[int, int], channel: int = 0) -> ToeplitzMAC:
        h, w = (shape[0] // RBLOCK) * RBLOCK, (shape[1] // RBLOCK) * RBLOCK
        nb = (h // RBLOCK) * (w // RBLOCK)
        return ToeplitzMAC(self.key, self.nonce, self._domain((h, w), channel), nb, MSG_BITS, TAG_BITS)

    def partners(self, shape: tuple[int, int], channel: int = 0) -> np.ndarray:
        """``partners[b]`` = index of the block that stores block ``b``'s recovery code."""
        h, w = (shape[0] // RBLOCK) * RBLOCK, (shape[1] // RBLOCK) * RBLOCK
        nb = (h // RBLOCK) * (w // RBLOCK)
        return keyed_derangement(self.key, self.nonce, self._domain((h, w), channel), nb)

    # ------------------------------------------------------------------ #
    def _embed_channel(self, channel_img: np.ndarray, channel: int) -> np.ndarray:
        full = np.asarray(channel_img)
        img = _crop(full).astype(np.int64)
        if img.shape[0] < RBLOCK or img.shape[1] < RBLOCK:
            raise ValueError("image must be at least 4x4")
        blocks = _to_blocks(img)
        perm = self.partners(img.shape, channel)
        codes = recovery_codes(img)
        stored = np.empty_like(codes)
        stored[perm] = codes  # block perm[b] carries the code of block b
        rec_bits = _codes_to_bits(stored)
        msg = np.concatenate([_msb_bits(blocks), rec_bits], axis=1)
        tags = self.mac(img.shape, channel).tags(msg)
        slots = np.concatenate([rec_bits, tags], axis=1)
        out = full.astype(np.int64).copy()
        out[: img.shape[0], : img.shape[1]] = _from_blocks(_write_slots(blocks, slots), img.shape)
        return out.astype(np.uint8)

    def embed(self, cover: np.ndarray) -> np.ndarray:
        img = np.asarray(cover)
        if img.dtype != np.uint8:
            raise ValueError("cover must be uint8")
        if img.ndim == 2:
            return self._embed_channel(img, 0)
        if img.ndim == 3:
            return np.stack([self._embed_channel(img[..., c], c) for c in range(img.shape[2])], axis=-1)
        raise ValueError("expected a 2-D or 3-D image")

    # ------------------------------------------------------------------ #
    def _check(self, img: np.ndarray, channel: int):
        blocks = _to_blocks(img)
        slots = _lsb_slots(blocks)
        rec_bits, tag_read = slots[:, :REC_BITS], slots[:, REC_BITS:]
        msg = np.concatenate([_msb_bits(blocks), rec_bits], axis=1)
        valid = np.all(self.mac(img.shape, channel).tags(msg) == tag_read, axis=1)
        return valid, _bits_to_codes(rec_bits)

    def verify(self, image: np.ndarray) -> np.ndarray:
        """``(H/4, W/4)`` tamper map (True = failed) of a grayscale or colour image."""
        img = np.asarray(image)
        channels = [img] if img.ndim == 2 else [img[..., c] for c in range(img.shape[2])]
        maps = []
        for c, ch in enumerate(channels):
            crop = _crop(ch).astype(np.int64)
            valid, _ = self._check(crop, c)
            maps.append(~valid.reshape(crop.shape[0] // RBLOCK, crop.shape[1] // RBLOCK))
        return np.logical_or.reduce(maps)

    def _recover_channel(self, channel_img: np.ndarray, channel: int):
        full = np.asarray(channel_img)
        img = _crop(full).astype(np.int64)
        h, w = img.shape
        hb, wb = h // RBLOCK, w // RBLOCK
        valid, carried = self._check(img, channel)
        perm = self.partners(img.shape, channel)
        tampered = ~valid
        partner_ok = valid[perm]
        restore = tampered & partner_ok
        inpaint = tampered & ~partner_ok
        values = decode_recovery_codes(carried[perm])  # (nb, 4): code of every block, read from its partner

        if self.reconstruction == "flat":
            blocks = _to_blocks(img).reshape(-1, RBLOCK, RBLOCK).copy()
            for s, (r, c) in enumerate(SUB_ORDER):
                blocks[restore, r : r + SUB, c : c + SUB] = values[restore, s][:, None, None]
            out = _from_blocks(blocks.reshape(-1, RBLOCK * RBLOCK), img.shape).astype(np.uint8)
            inpaint_px = np.kron(inpaint.reshape(hb, wb).astype(np.uint8), np.ones((RBLOCK, RBLOCK), np.uint8))
            if inpaint_px.any():
                out = cv2.inpaint(out, inpaint_px * 255, 3, cv2.INPAINT_TELEA)
        else:
            # Interpolate on the 2x2-sub-block grid: authentic sub-blocks contribute their
            # true mean, rebuilt ones their decoded AA code, lost ones are inpainted at low
            # resolution; the grid is then upsampled bilinearly into the failed blocks only.
            low = img.reshape(h // SUB, SUB, w // SUB, SUB).mean(axis=(1, 3))
            unknown = np.zeros(low.shape, dtype=bool)
            by, bx = np.divmod(np.arange(hb * wb), wb)
            for s, (r, c) in enumerate(SUB_ORDER):
                ys, xs = 2 * by + r // SUB, 2 * bx + c // SUB
                low[ys[restore], xs[restore]] = values[restore, s]
                unknown[ys[inpaint], xs[inpaint]] = True
            low8 = np.clip(np.rint(low), 0, 255).astype(np.uint8)
            if unknown.any():
                low8 = cv2.inpaint(low8, unknown.astype(np.uint8) * 255, 3, cv2.INPAINT_TELEA)
            up = cv2.resize(low8.astype(np.float32), (w, h), interpolation=cv2.INTER_LINEAR)
            region = np.kron(tampered.reshape(hb, wb).astype(np.uint8), np.ones((RBLOCK, RBLOCK), np.uint8)).astype(bool)
            out = img.copy()
            out[region] = np.clip(np.rint(up[region]), 0, 255)
            out = out.astype(np.uint8)

        result = full.copy()
        result[:h, :w] = out
        return result, tampered.reshape(hb, wb), restore.reshape(hb, wb), inpaint.reshape(hb, wb)

    def recover(self, image: np.ndarray) -> RecoveryResult:
        """Verify every block and repair the ones that failed."""
        img = np.asarray(image)
        if img.ndim == 2:
            rec, t, r, i = self._recover_channel(img, 0)
            return RecoveryResult(rec, t, r, i)
        outs = [self._recover_channel(img[..., c], c) for c in range(img.shape[2])]
        rec = np.stack([o[0] for o in outs], axis=-1)
        t = np.logical_or.reduce([o[1] for o in outs])
        r = np.logical_and.reduce([o[2] | ~o[1] for o in outs]) & t
        i = t & ~r
        return RecoveryResult(rec, t, r, i)
