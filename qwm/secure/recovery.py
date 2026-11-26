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
    RECONSTRUCTIONS = ("bicubic", "interpolate", "flat")

    def __init__(self, key, nonce=b"", reconstruction: str = "bicubic"):
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
            interp = cv2.INTER_CUBIC if self.reconstruction == "bicubic" else cv2.INTER_LINEAR
            up = cv2.resize(low8.astype(np.float32), (w, h), interpolation=interp)
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


# --------------------------------------------------------------------------- #
# v3 Enhancement: Dual-partner 8x8 Haar companded self-recovery (2 bpp)
# --------------------------------------------------------------------------- #
RBLOCK8 = 8
SLOTS8 = RBLOCK8 * RBLOCK8 * 2  # 128 LSB bits at 2 bpp
PRIMARY_BITS8 = 68  # 4 quadrants x (6 DC + 4 H + 4 V + 3 D)
SECONDARY_BITS8 = 44  # 4 quadrants x (5 DC + 2 H + 2 V + 2 D)
TAG_BITS8 = 16  # 68 + 44 + 16 = 128 bits, forgery probability 2**-16
MSG_BITS8 = RBLOCK8 * RBLOCK8 * (8 - MSB_SHIFT) + PRIMARY_BITS8 + SECONDARY_BITS8  # 384 + 112 = 496

_QUAD_SLICES = ((0, 0), (0, 4), (4, 0), (4, 4))
_HAAR_SCALE = 200.0


def _haar_coeffs_4x4(quads: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """2D block Haar averages across ``(..., 4, 4)`` quadrants into 4x(2x2) sub-means."""
    # Compute means of the four 2x2 sub-quadrants (tl, tr, bl, br)
    tl = quads[..., :2, :2].mean(axis=(-2, -1))
    tr = quads[..., :2, 2:].mean(axis=(-2, -1))
    bl = quads[..., 2:, :2].mean(axis=(-2, -1))
    br = quads[..., 2:, 2:].mean(axis=(-2, -1))
    dc = 0.25 * (tl + tr + bl + br)
    hx = 0.5 * ((tl + bl) - (tr + br))
    hy = 0.5 * ((tl + tr) - (bl + br))
    hd = 0.5 * ((tl + br) - (tr + bl))
    return dc, hx, hy, hd


def _synth_quads_4x4(dc: np.ndarray, hx: np.ndarray, hy: np.ndarray, hd: np.ndarray) -> np.ndarray:
    """Reconstruct ``(..., 4, 4)`` float values from quantized 2D Haar coefficients."""
    tl = dc + 0.5 * (hx + hy + hd)
    tr = dc + 0.5 * (-hx + hy - hd)
    bl = dc + 0.5 * (hx - hy - hd)
    br = dc + 0.5 * (-hx - hy + hd)
    out = np.empty(dc.shape + (4, 4), dtype=np.float32)
    out[..., :2, :2] = tl[..., None, None]
    out[..., :2, 2:] = tr[..., None, None]
    out[..., 2:, :2] = bl[..., None, None]
    out[..., 2:, 2:] = br[..., None, None]
    return np.clip(out, 0.0, 255.0)


def _quant_sqrt(vals: np.ndarray, bits: int, scale: float = _HAAR_SCALE) -> np.ndarray:
    half = (1 << (bits - 1)) - 1
    if half <= 0:
        return np.zeros(vals.shape, dtype=np.int64)
    norm = np.clip(vals / scale, -1.0, 1.0)
    signed = np.sign(norm) * np.sqrt(np.abs(norm))
    q = np.rint(signed * half).astype(np.int64)
    return np.clip(q, -half, half) + half


def _dequant_sqrt(q: np.ndarray, bits: int, scale: float = _HAAR_SCALE) -> np.ndarray:
    half = (1 << (bits - 1)) - 1
    if half <= 0:
        return np.zeros(q.shape, dtype=np.float32)
    s = (np.clip(q.astype(np.float32), 0.0, float(2 * half)) - half) / float(half)
    return np.sign(s) * (s * s) * scale


def _pack_bits_seq(arr: np.ndarray, widths: tuple[int, ...]) -> np.ndarray:
    """Pack ``(nb, 4, K)`` integer fields with bit-widths ``widths`` into flat bits."""
    pieces = []
    for k, w in enumerate(widths):
        v = arr[..., k : k + 1]
        shifts = np.arange(w, dtype=np.int64)
        pieces.append((v >> shifts) & 1)
    bits = np.concatenate(pieces, axis=-1)
    return bits.reshape(arr.shape[0], -1).astype(np.uint8)


def _unpack_bits_seq(bits: np.ndarray, widths: tuple[int, ...]) -> np.ndarray:
    per_q = sum(widths)
    b = bits.reshape(bits.shape[0], 4, per_q).astype(np.int64)
    cols = []
    pos = 0
    for w in widths:
        sl = b[..., pos : pos + w]
        cols.append((sl << np.arange(w, dtype=np.int64)).sum(axis=-1))
        pos += w
    return np.stack(cols, axis=-1)


def _disjoint_derangement_pair(key, nonce, domain: str, n: int) -> tuple[np.ndarray, np.ndarray]:
    """Two keyed derangements ``(p1, p2)`` with ``p2[i] != p1[i]`` wherever ``n >= 3``."""
    p1 = keyed_derangement(key, nonce, f"{domain}|p1", n)
    p2 = keyed_derangement(key, nonce, f"{domain}|p2", n)
    if n < 3:
        return p1, p2
    for i in range(n):
        if p2[i] == p1[i]:
            for step in range(1, n):
                j = (i + step) % n
                if p2[j] != i and p2[i] != j and p2[j] != p1[i] and p2[i] != p1[j]:
                    p2[i], p2[j] = p2[j], p2[i]
                    break
    return p1, p2


class DualPartnerSelfRecoveringWatermark:
    """Dual-partner 8x8 keyed fragile watermark with Haar companded self-recovery.

    Splits the ``128`` LSB slots (2 bpp) of every 8x8 block into:

    * **68 bits** primary companded-Haar code (6-bit DC + 4-bit H + 4-bit V +
      3-bit D per 4x4 quadrant) for partner block ``pi_1(B)``;
    * **44 bits** secondary companded-Haar code (5-bit DC + 2-bit H/V/D) for
      independent partner ``pi_2(B) != pi_1(B)`` so contiguous crops destroying
      the primary partner can still fall back cleanly to embedded backup codes;
    * **16 bits** keyed Toeplitz MAC tag over all 384 MSBs and 112 carried
      recovery bits (forgery probability ``2**-16`` per block).
    """

    tag_bits = TAG_BITS8
    block = RBLOCK8
    RECONSTRUCTIONS = ("bicubic", "interpolate", "flat")

    def __init__(self, key, nonce=b"", reconstruction: str = "bicubic"):
        if reconstruction not in self.RECONSTRUCTIONS:
            raise ValueError(f"reconstruction must be one of {self.RECONSTRUCTIONS}")
        self.key = key
        self.nonce = nonce
        self.reconstruction = reconstruction

    def _domain(self, shape: tuple[int, int], channel: int) -> str:
        return f"recover8x8|{shape[0]}x{shape[1]}|ch{channel}"

    def _cropped_shape(self, shape: tuple[int, int]) -> tuple[int, int]:
        return (shape[0] // RBLOCK8) * RBLOCK8, (shape[1] // RBLOCK8) * RBLOCK8

    def mac(self, shape: tuple[int, int], channel: int = 0) -> ToeplitzMAC:
        h, w = self._cropped_shape(shape)
        nb = (h // RBLOCK8) * (w // RBLOCK8)
        return ToeplitzMAC(self.key, self.nonce, self._domain((h, w), channel), nb, MSG_BITS8, TAG_BITS8)

    def partners(self, shape: tuple[int, int], channel: int = 0) -> tuple[np.ndarray, np.ndarray]:
        h, w = self._cropped_shape(shape)
        nb = (h // RBLOCK8) * (w // RBLOCK8)
        return _disjoint_derangement_pair(self.key, self.nonce, self._domain((h, w), channel), nb)

    @staticmethod
    def encode_primary(blocks: np.ndarray) -> np.ndarray:
        """Encode ``(nb, 8, 8)`` blocks into ``(nb, 68)`` companded-Haar bits."""
        quads = np.stack([blocks[:, r : r + 4, c : c + 4] for r, c in _QUAD_SLICES], axis=1)
        dc, hx, hy, hd = _haar_coeffs_4x4(quads.astype(np.float32))
        q_dc = np.clip((np.rint(dc).astype(np.int64)) >> 2, 0, 63)
        q_hx = _quant_sqrt(hx, 4)
        q_hy = _quant_sqrt(hy, 4)
        q_hd = _quant_sqrt(hd, 3)
        return _pack_bits_seq(np.stack([q_dc, q_hx, q_hy, q_hd], axis=-1), (6, 4, 4, 3))

    @staticmethod
    def encode_secondary(blocks: np.ndarray) -> np.ndarray:
        """Encode ``(nb, 8, 8)`` blocks into ``(nb, 44)`` backup Haar bits."""
        quads = np.stack([blocks[:, r : r + 4, c : c + 4] for r, c in _QUAD_SLICES], axis=1)
        dc, hx, hy, hd = _haar_coeffs_4x4(quads.astype(np.float32))
        q_dc = np.clip((np.rint(dc).astype(np.int64)) >> 3, 0, 31)
        q_hx = _quant_sqrt(hx, 2)
        q_hy = _quant_sqrt(hy, 2)
        q_hd = _quant_sqrt(hd, 2)
        return _pack_bits_seq(np.stack([q_dc, q_hx, q_hy, q_hd], axis=-1), (5, 2, 2, 2))

    @staticmethod
    def decode_primary(bits: np.ndarray) -> np.ndarray:
        """Decode ``(nb, 68)`` bits into ``(nb, 8, 8)`` float32 reconstructions."""
        vals = _unpack_bits_seq(bits, (6, 4, 4, 3))
        dc = vals[..., 0].astype(np.float32) * 4.0 + 2.0
        hx = _dequant_sqrt(vals[..., 1], 4)
        hy = _dequant_sqrt(vals[..., 2], 4)
        hd = _dequant_sqrt(vals[..., 3], 3)
        q_rec = _synth_quads_4x4(dc, hx, hy, hd)
        nb = bits.shape[0]
        out = np.empty((nb, RBLOCK8, RBLOCK8), dtype=np.float32)
        for q_idx, (r, c) in enumerate(_QUAD_SLICES):
            out[:, r : r + 4, c : c + 4] = q_rec[:, q_idx]
        return out

    @staticmethod
    def decode_secondary(bits: np.ndarray) -> np.ndarray:
        """Decode ``(nb, 44)`` backup bits into ``(nb, 8, 8)`` float32 reconstructions."""
        vals = _unpack_bits_seq(bits, (5, 2, 2, 2))
        dc = vals[..., 0].astype(np.float32) * 8.0 + 4.0
        hx = _dequant_sqrt(vals[..., 1], 2)
        hy = _dequant_sqrt(vals[..., 2], 2)
        hd = _dequant_sqrt(vals[..., 3], 2)
        q_rec = _synth_quads_4x4(dc, hx, hy, hd)
        nb = bits.shape[0]
        out = np.empty((nb, RBLOCK8, RBLOCK8), dtype=np.float32)
        for q_idx, (r, c) in enumerate(_QUAD_SLICES):
            out[:, r : r + 4, c : c + 4] = q_rec[:, q_idx]
        return out

    @staticmethod
    def _to_blocks8(img: np.ndarray) -> np.ndarray:
        h, w = img.shape
        return img.reshape(h // RBLOCK8, RBLOCK8, w // RBLOCK8, RBLOCK8).swapaxes(1, 2).reshape(-1, RBLOCK8, RBLOCK8)

    @staticmethod
    def _from_blocks8(blocks: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
        h, w = shape
        return blocks.reshape(h // RBLOCK8, w // RBLOCK8, RBLOCK8, RBLOCK8).swapaxes(1, 2).reshape(h, w)

    def _embed_channel(self, channel_img: np.ndarray, channel: int) -> np.ndarray:
        full = np.asarray(channel_img)
        h, w = self._cropped_shape(full.shape[:2])
        if h < RBLOCK8 or w < RBLOCK8:
            raise ValueError("image must be at least 8x8 for DualPartnerSelfRecoveringWatermark")
        img = full[:h, :w].astype(np.int64)
        blocks = self._to_blocks8(img)
        msb_blocks = blocks & ~0b11
        p1, p2 = self.partners(img.shape, channel)

        pri_src = self.encode_primary(msb_blocks)
        sec_src = self.encode_secondary(msb_blocks)
        pri_carried = np.empty_like(pri_src)
        sec_carried = np.empty_like(sec_src)
        pri_carried[p1] = pri_src
        sec_carried[p2] = sec_src

        k_msb = np.arange(MSB_SHIFT, 8)
        flat_blk = blocks.reshape(blocks.shape[0], -1)
        msb_bits = ((flat_blk[..., None] >> k_msb) & 1).reshape(blocks.shape[0], -1).astype(np.uint8)
        msg = np.concatenate([msb_bits, pri_carried, sec_carried], axis=1)
        tags = self.mac(img.shape, channel).tags(msg)
        slots = np.concatenate([pri_carried, sec_carried, tags], axis=1).reshape(blocks.shape[0], 64, 2)
        emb = (flat_blk & ~0b11) | slots[..., 0] | (slots[..., 1] << 1)
        out = full.copy()
        out[:h, :w] = self._from_blocks8(emb.reshape(-1, RBLOCK8, RBLOCK8), (h, w)).astype(np.uint8)
        return out

    def embed(self, cover: np.ndarray) -> np.ndarray:
        img = np.asarray(cover)
        if img.dtype != np.uint8:
            raise ValueError("cover must be uint8")
        if img.ndim == 2:
            return self._embed_channel(img, 0)
        if img.ndim == 3:
            return np.stack([self._embed_channel(img[..., c], c) for c in range(img.shape[2])], axis=-1)
        raise ValueError("expected a 2-D or 3-D image")

    def _check(self, img: np.ndarray, channel: int):
        blocks = self._to_blocks8(img)
        flat = blocks.reshape(blocks.shape[0], -1)
        slots = np.stack([flat & 1, (flat >> 1) & 1], axis=-1).reshape(blocks.shape[0], SLOTS8).astype(np.uint8)
        pri = slots[:, :PRIMARY_BITS8]
        sec = slots[:, PRIMARY_BITS8 : PRIMARY_BITS8 + SECONDARY_BITS8]
        tag_read = slots[:, PRIMARY_BITS8 + SECONDARY_BITS8 :]
        k_msb = np.arange(MSB_SHIFT, 8)
        msb_bits = ((flat[..., None] >> k_msb) & 1).reshape(blocks.shape[0], -1).astype(np.uint8)
        msg = np.concatenate([msb_bits, pri, sec], axis=1)
        valid = np.all(self.mac(img.shape, channel).tags(msg) == tag_read, axis=1)
        return valid, pri, sec

    def verify(self, image: np.ndarray) -> np.ndarray:
        """``(H/8, W/8)`` tamper map (True = failed) of a grayscale or colour image."""
        img = np.asarray(image)
        channels = [img] if img.ndim == 2 else [img[..., c] for c in range(img.shape[2])]
        maps = []
        for c, ch in enumerate(channels):
            h, w = self._cropped_shape(ch.shape[:2])
            valid, _, _ = self._check(ch[:h, :w].astype(np.int64), c)
            maps.append(~valid.reshape(h // RBLOCK8, w // RBLOCK8))
        return np.logical_or.reduce(maps)

    def _recover_channel(self, channel_img: np.ndarray, channel: int):
        full = np.asarray(channel_img)
        h, w = self._cropped_shape(full.shape[:2])
        img = full[:h, :w].astype(np.int64)
        hb, wb = h // RBLOCK8, w // RBLOCK8
        valid, pri_carried, sec_carried = self._check(img, channel)
        p1, p2 = self.partners(img.shape, channel)
        tampered = ~valid
        use_pri = tampered & valid[p1]
        use_sec = tampered & (~valid[p1]) & valid[p2]
        restored = use_pri | use_sec
        inpaint = tampered & (~restored)

        pri_vals = self.decode_primary(pri_carried[p1])
        sec_vals = self.decode_secondary(sec_carried[p2])

        blocks = self._to_blocks8(img).astype(np.float32).copy()
        blocks[use_pri] = pri_vals[use_pri]
        blocks[use_sec] = sec_vals[use_sec]

        if self.reconstruction == "flat":
            out = np.clip(np.rint(self._from_blocks8(blocks, (h, w))), 0, 255).astype(np.uint8)
            inpaint_px = np.kron(inpaint.reshape(hb, wb).astype(np.uint8), np.ones((RBLOCK8, RBLOCK8), np.uint8))
            if inpaint_px.any():
                out = cv2.inpaint(out, inpaint_px * 255, 3, cv2.INPAINT_TELEA)
        else:
            canvas = self._from_blocks8(blocks, (h, w))
            low = canvas.reshape(h // SUB, SUB, w // SUB, SUB).mean(axis=(1, 3))
            unknown = np.kron(inpaint.reshape(hb, wb).astype(np.uint8), np.ones((4, 4), np.uint8))
            low8 = np.clip(np.rint(low), 0, 255).astype(np.uint8)
            if unknown.any():
                low8 = cv2.inpaint(low8, unknown * 255, 3, cv2.INPAINT_TELEA)
            interp = cv2.INTER_LINEAR if self.reconstruction == "interpolate" else cv2.INTER_CUBIC
            up = cv2.resize(low8.astype(np.float32), (w, h), interpolation=interp)
            tamp_px = np.kron(tampered.reshape(hb, wb).astype(bool), np.ones((RBLOCK8, RBLOCK8), bool))
            out_f = img.astype(np.float32).copy()
            out_f[tamp_px] = up[tamp_px]
            out = np.clip(np.rint(out_f), 0, 255).astype(np.uint8)

        result = full.copy()
        result[:h, :w] = out
        stats = {
            "primary_restored": int(use_pri.sum()),
            "secondary_restored": int(use_sec.sum()),
            "inpainted": int(inpaint.sum()),
        }
        return (
            result,
            tampered.reshape(hb, wb),
            restored.reshape(hb, wb),
            inpaint.reshape(hb, wb),
            stats,
        )

    def recover(self, image: np.ndarray) -> RecoveryResult:
        """Verify every 8x8 block and repair tampered ones using primary -> secondary -> inpaint."""
        img = np.asarray(image)
        if img.ndim == 2:
            rec, t, r, i, st = self._recover_channel(img, 0)
            st["forgery_prob"] = float(2**-TAG_BITS8)
            return RecoveryResult(rec, t, r, i, block=RBLOCK8, extra=st)
        outs = [self._recover_channel(img[..., c], c) for c in range(img.shape[2])]
        rec = np.stack([o[0] for o in outs], axis=-1)
        t = np.logical_or.reduce([o[1] for o in outs])
        r = np.logical_and.reduce([o[2] | ~o[1] for o in outs]) & t
        i = t & ~r
        extra = {
            "primary_restored": int(sum(o[4]["primary_restored"] for o in outs)),
            "secondary_restored": int(sum(o[4]["secondary_restored"] for o in outs)),
            "inpainted": int(sum(o[4]["inpainted"] for o in outs)),
            "forgery_prob": float(2**-TAG_BITS8),
        }
        return RecoveryResult(rec, t, r, i, block=RBLOCK8, extra=extra)
