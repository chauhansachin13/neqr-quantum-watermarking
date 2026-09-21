"""
Novel Enhanced Quantum Representation (NEQR) of grayscale images.

An image of size ``2**n x 2**n`` with ``q``-bit pixels is stored as

    |I> = 1/2**n * sum_{Y,X} |f(Y,X)> (x) |Y X>

where ``|f(Y,X)>`` is the ``q``-qubit basis state of the pixel intensity and
``|Y X>`` is the ``2n``-qubit position register.  The preparation circuit
(Algorithms 1 and 2 of the reference design) applies Hadamard gates to the
position qubits and, for every pixel, a multi-controlled NOT on each
intensity qubit whose bit is ``1`` - controlled on the position register
being equal to that pixel's coordinates.

Qubit layout used throughout the package (little-endian, matching Qiskit):

* qubits ``0 .. q-1``      : intensity register (bit 0 = LSB of the pixel)
* qubits ``q .. q+2n-1``   : position register ``X_0..X_{n-1}, Y_0..Y_{n-1}``

For the ``2x2`` blocks used by the watermarking scheme ``n = 1`` and the
circuit has ``8 + 2 = 10`` qubits, exactly as in Algorithm 1 (``idx`` register
of 2 qubits and ``intensity`` register of 8 qubits).
"""

from __future__ import annotations

import numpy as np
from qiskit import QuantumCircuit, QuantumRegister
from qiskit.circuit.library import MCXGate
from qiskit.quantum_info import Statevector


def _check_image(image: np.ndarray) -> tuple[np.ndarray, int, int]:
    image = np.asarray(image)
    if image.ndim != 2:
        raise ValueError("NEQR expects a 2-D grayscale image")
    h, w = image.shape
    ny, nx = int(np.log2(h)), int(np.log2(w))
    if 2**ny != h or 2**nx != w:
        raise ValueError("image sides must be powers of two")
    return image.astype(np.int64), ny, nx


def position_index(y: int, x: int, nx: int) -> int:
    """Integer value of the position register ``|Y X>`` (``Y`` most significant)."""
    return (y << nx) | x


def neqr_circuit(image: np.ndarray, bit_depth: int = 8, barriers: bool = True) -> QuantumCircuit:
    """Build the NEQR preparation circuit for ``image``.

    Parameters
    ----------
    image:
        2-D array with sides that are powers of two and values in
        ``[0, 2**bit_depth)``.
    bit_depth:
        Number of intensity qubits ``q`` (8 for grayscale).
    barriers:
        Insert a barrier after every pixel for readability (as in Fig. 8).
    """
    image, ny, nx = _check_image(image)
    if image.min() < 0 or image.max() >= 2**bit_depth:
        raise ValueError(f"pixel values must fit in {bit_depth} bits")
    n_pos = ny + nx
    intensity = QuantumRegister(bit_depth, "intensity")
    idx = QuantumRegister(n_pos, "idx")
    qc = QuantumCircuit(intensity, idx, name="NEQR")

    # Algorithm 1: identity gates on the intensity qubits, Hadamards on the
    # position qubits and a barrier for readability.
    for k in range(bit_depth):
        qc.id(intensity[k])
    for k in range(n_pos):
        qc.h(idx[k])
    if barriers:
        qc.barrier()

    # Algorithm 2: encode every pixel with Toffoli / multi-controlled NOT gates
    # fired by the position register being equal to the pixel coordinates.
    mcx = MCXGate(n_pos)
    for y in range(2**ny):
        for x in range(2**nx):
            value = int(image[y, x])
            p = position_index(y, x, nx)
            zero_ctrls = [idx[k] for k in range(n_pos) if not (p >> k) & 1]
            for qb in zero_ctrls:
                qc.x(qb)
            for k in range(bit_depth):
                if (value >> k) & 1:
                    qc.append(mcx, [idx[j] for j in range(n_pos)] + [intensity[k]])
            for qb in zero_ctrls:
                qc.x(qb)
            if barriers:
                qc.barrier()
    return qc


def neqr_block_circuit(block: np.ndarray, barriers: bool = True) -> QuantumCircuit:
    """NEQR circuit of one ``2x2`` block (10 qubits)."""
    block = np.asarray(block)
    if block.shape != (2, 2):
        raise ValueError("block must be 2x2")
    return neqr_circuit(block, 8, barriers)


def neqr_statevector(image: np.ndarray, bit_depth: int = 8) -> Statevector:
    """Closed-form NEQR state (no circuit simulation needed)."""
    image, ny, nx = _check_image(image)
    n_pos = ny + nx
    amp = np.zeros(2 ** (bit_depth + n_pos), dtype=complex)
    scale = 1.0 / np.sqrt(2**n_pos)
    for y in range(2**ny):
        for x in range(2**nx):
            p = position_index(y, x, nx)
            amp[(p << bit_depth) | int(image[y, x])] = scale
    return Statevector(amp)


def decode_statevector(state: Statevector | np.ndarray, shape: tuple[int, int], bit_depth: int = 8) -> np.ndarray:
    """Recover the image from an NEQR state by reading the dominant intensity per position."""
    probs = np.abs(np.asarray(state.data if isinstance(state, Statevector) else state)) ** 2
    h, w = shape
    nx = int(np.log2(w))
    out = np.zeros((h, w), dtype=np.uint8)
    span = 2**bit_depth
    for y in range(h):
        for x in range(w):
            p = position_index(y, x, nx)
            seg = probs[p * span : (p + 1) * span]
            out[y, x] = int(np.argmax(seg))
    return out


def decode_counts(counts: dict[str, int], shape: tuple[int, int], bit_depth: int = 8) -> np.ndarray:
    """Recover the image from Aer measurement counts (bitstrings are big-endian)."""
    h, w = shape
    nx = int(np.log2(w))
    best: dict[int, tuple[int, int]] = {}
    for bitstring, c in counts.items():
        value = int(bitstring.replace(" ", ""), 2)
        p, v = value >> bit_depth, value & ((1 << bit_depth) - 1)
        if p not in best or c > best[p][0]:
            best[p] = (c, v)
    out = np.zeros((h, w), dtype=np.uint8)
    for y in range(h):
        for x in range(w):
            out[y, x] = best.get(position_index(y, x, nx), (0, 0))[1]
    return out


def encode_decode_roundtrip(image: np.ndarray, bit_depth: int = 8) -> np.ndarray:
    """Build the circuit, simulate it exactly and decode the image back."""
    qc = neqr_circuit(image, bit_depth, barriers=False)
    sv = Statevector(qc)
    return decode_statevector(sv, np.asarray(image).shape, bit_depth)


def iter_blocks(image: np.ndarray, size: int = 2):
    """Yield ``((row, col), block)`` for every non-overlapping ``size x size`` block."""
    image = np.asarray(image)
    h, w = image.shape
    for r in range(0, h - h % size, size):
        for c in range(0, w - w % size, size):
            yield (r, c), image[r : r + size, c : c + size]
