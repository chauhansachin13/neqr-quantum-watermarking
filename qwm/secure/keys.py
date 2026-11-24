"""
Key material for the keyed (secure) watermarking schemes.

Everything secret is derived from a user key and a per-image nonce with
SHAKE-256, an extendable-output function from the SHA-3 family, using
domain separation so that independent streams never overlap:

``keystream(key, nonce, domain, n)`` = SHAKE-256("qwm-v2" | domain | key | nonce)[:n]

Two primitives are built on top of it.

* :class:`ToeplitzMAC` - a one-time message authentication code
  ``tag = T_b . m  xor  c_b`` over GF(2), with a fresh random Toeplitz matrix
  ``T_b`` and mask ``c_b`` for every block ``b``.  Toeplitz matrices form an
  XOR-universal hash family (Krawczyk, CRYPTO 1994), so for any message
  ``m' != m`` an adversary who has seen ``(m, tag)`` but not the key forges a
  valid tag with probability exactly ``2**-tag_bits``.  The map is linear, so
  the quantum version is a network of CNOT gates (plus X gates for ``c_b``)
  with no ancilla qubits.
* :func:`keyed_derangement` - a permutation without fixed points, used to
  pick the partner block that stores another block's recovery data.  It is a
  Fisher-Yates shuffle driven directly by the keystream, so it does not depend
  on NumPy's random-number generators (whose streams may change between
  releases) and a watermark stays verifiable across library versions.

The one-time guarantee holds per (key, nonce) pair: watermarking two images
with the same key **and** nonce lets an attacker combine their blocks, so a
unique nonce (an image ID, a timestamp, a counter) should be used per image.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np

__all__ = ["keystream", "keystream_bits", "ToeplitzMAC", "keyed_derangement", "to_bytes"]

_PREFIX = b"qwm-v2"


def to_bytes(value) -> bytes:
    """Encode a key or nonce given as ``str`` / ``bytes`` / ``int`` / ``None``."""
    if value is None:
        return b""
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray | memoryview):
        return bytes(value)
    if isinstance(value, str):
        return value.encode("utf-8")
    if isinstance(value, int | np.integer):
        return str(int(value)).encode("ascii")
    raise TypeError(f"cannot use {type(value).__name__} as key material")


def _seed(key, nonce, domain: str) -> bytes:
    k, n, d = to_bytes(key), to_bytes(nonce), domain.encode("utf-8")
    if not k:
        raise ValueError("the secret key must not be empty")
    parts = [_PREFIX, d, k, n]
    return b"".join(len(p).to_bytes(4, "big") + p for p in parts)


def keystream(key, nonce, domain: str, n_bytes: int) -> np.ndarray:
    """``n_bytes`` pseudo-random bytes bound to ``(key, nonce, domain)``."""
    if n_bytes < 0:
        raise ValueError("n_bytes must be non-negative")
    return np.frombuffer(hashlib.shake_256(_seed(key, nonce, domain)).digest(int(n_bytes)), dtype=np.uint8).copy()


def keystream_bits(key, nonce, domain: str, shape) -> np.ndarray:
    """Pseudo-random bits (``uint8`` 0/1) of the given shape."""
    shape = (shape,) if isinstance(shape, int | np.integer) else tuple(shape)
    n_bits = int(np.prod(shape))
    raw = keystream(key, nonce, domain, (n_bits + 7) // 8)
    return np.unpackbits(raw, bitorder="little")[:n_bits].reshape(shape)


@dataclass
class ToeplitzMAC:
    """Per-block one-time MAC ``tag_b(m) = T_b m xor c_b`` over GF(2).

    Parameters
    ----------
    key, nonce:
        Secret key and per-image nonce.
    domain:
        Domain-separation label (scheme, image shape, channel).
    n_blocks:
        Number of blocks that each get an independent ``(T_b, c_b)``.
    msg_bits, tag_bits:
        Message length ``L`` and tag length ``t``.  ``T_b`` is a ``t x L``
        Toeplitz matrix defined by ``t + L - 1`` random bits.
    """

    key: object
    nonce: object
    domain: str
    n_blocks: int
    msg_bits: int
    tag_bits: int

    def __post_init__(self) -> None:
        if self.msg_bits < 1 or self.tag_bits < 1:
            raise ValueError("msg_bits and tag_bits must be positive")
        diag_len = self.tag_bits + self.msg_bits - 1
        bits = keystream_bits(self.key, self.nonce, f"mac|{self.domain}", (self.n_blocks, diag_len + self.tag_bits))
        self._diag = bits[:, :diag_len]
        self._mask = bits[:, diag_len:]
        i = np.arange(self.tag_bits)[:, None]
        j = np.arange(self.msg_bits)[None, :]
        self._index = i - j + self.msg_bits - 1  # T[i, j] = diag[i - j + L - 1]

    @property
    def forgery_probability(self) -> float:
        return 2.0 ** (-self.tag_bits)

    def matrix(self, block: int) -> np.ndarray:
        """The ``t x L`` Toeplitz matrix of one block."""
        return self._diag[block][self._index]

    def mask(self, block: int) -> np.ndarray:
        return self._mask[block].copy()

    def tags(self, messages: np.ndarray) -> np.ndarray:
        """Tags of all blocks at once: ``messages`` has shape ``(n_blocks, msg_bits)``."""
        m = np.asarray(messages, dtype=np.uint8)
        if m.shape != (self.n_blocks, self.msg_bits):
            raise ValueError(f"expected messages of shape {(self.n_blocks, self.msg_bits)}, got {m.shape}")
        out = np.empty((self.n_blocks, self.tag_bits), dtype=np.uint8)
        # process in chunks to bound memory for large images
        step = max(1, 4_000_000 // (self.tag_bits * self.msg_bits))
        for s in range(0, self.n_blocks, step):
            t = self._diag[s : s + step][:, self._index]  # (chunk, t, L)
            out[s : s + step] = (np.einsum("btl,bl->bt", t, m[s : s + step], dtype=np.int64) & 1).astype(np.uint8)
        return out ^ self._mask

    def tag(self, block: int, message) -> np.ndarray:
        m = np.asarray(message, dtype=np.int64)
        return ((self.matrix(block).astype(np.int64) @ m) & 1).astype(np.uint8) ^ self._mask[block]


def keyed_derangement(key, nonce, domain: str, n: int) -> np.ndarray:
    """A keyed permutation of ``range(n)`` with no fixed points (``n >= 2``)."""
    if n < 2:
        raise ValueError("a derangement needs at least two elements")
    words = keystream(key, nonce, f"perm|{domain}", 8 * n).view(">u8").astype(object)
    perm = list(range(n))
    for i in range(n - 1, 0, -1):  # Fisher-Yates driven by 64-bit keystream words
        j = int(words[i] % (i + 1))
        perm[i], perm[j] = perm[j], perm[i]
    perm = np.asarray(perm, dtype=np.int64)
    fixed = np.flatnonzero(perm == np.arange(n))
    if len(fixed) >= 2:  # rotate the fixed points among themselves
        perm[fixed] = np.roll(fixed, -1)
    elif len(fixed) == 1:  # swap the single fixed point with a keyed partner
        f = int(fixed[0])
        j = int(words[0] % (n - 1))
        j = j + 1 if j >= f else j
        perm[f], perm[j] = perm[j], perm[f]
    return perm
