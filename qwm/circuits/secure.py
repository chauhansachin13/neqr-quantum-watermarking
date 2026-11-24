"""
Circuits of the keyed scheme (:mod:`qwm.secure`) for one 2x2 block.

* :class:`SecureEmbeddingCircuit` (44 qubits): lean generation of the base
  content code on the MSB plane, the block's Toeplitz MAC as a CNOT network
  (``o_i ^= m_j`` wherever ``T_b[i, j] = 1``, then ``X`` where ``c_b[i] = 1``),
  and eight SWAPs that move the tag into the two LSBs of each pixel.
* :class:`BlindVerificationCircuit` (45 qubits): recompute the tag from the
  received MSBs, XOR the received LSBs onto it (8 CNOTs) and set one flag
  qubit with a zero-controlled MCX - the QE step, but against a recomputed
  value instead of a stored reference.

The key enters only as circuit *structure* (which CNOT / X gates exist), the
same way classical bits enter the base design; no qubit stores key material.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from qiskit import QuantumCircuit, QuantumRegister
from qiskit.circuit import Qubit
from qiskit.circuit.library import MCXGate

from qwm.circuits.lean import LeanBlockRegisters, append_lean_generation, load_block
from qwm.secure.authentication import MSB_SHIFT, SecureWatermark
from qwm.secure.keys import ToeplitzMAC
from qwm.simulation import bits_to_int, run_basis
from qwm.watermark.generation import block_pixels

__all__ = ["append_mac_network", "msb_message_qubits", "SecureEmbeddingCircuit", "BlindVerificationCircuit"]


def msb_message_qubits(pixel_regs: Sequence[QuantumRegister]) -> list[Qubit]:
    """The 24 MAC message qubits in the order of :func:`qwm.secure.msb_message_bits`."""
    return [reg[k] for reg in pixel_regs for k in range(MSB_SHIFT, 8)]


def append_mac_network(qc: QuantumCircuit, message: Sequence[Qubit], out: Sequence[Qubit], matrix: np.ndarray, mask: np.ndarray) -> int:
    """XOR ``matrix . message xor mask`` onto ``out``; returns the number of CNOTs."""
    matrix = np.asarray(matrix)
    if matrix.shape != (len(out), len(message)):
        raise ValueError("matrix shape does not match the registers")
    n_cx = 0
    for i, o in enumerate(out):
        for j, m in enumerate(message):
            if matrix[i, j]:
                qc.cx(m, o)
                n_cx += 1
        if mask[i]:
            qc.x(o)
    return n_cx


def _block_mac(key, nonce, image_shape, row: int, col: int) -> tuple[ToeplitzMAC, int]:
    sw = SecureWatermark(key, nonce)
    mac = sw.mac(tuple(image_shape[:2]))
    wb = image_shape[1] // 2
    return mac, row * wb + col


class _SecureBase:
    def __init__(self, block, key, nonce, image_shape, row: int, col: int, load_inputs: bool = True):
        self.block = np.asarray(block, dtype=np.int64)
        if self.block.shape != (2, 2):
            raise ValueError("block must be 2x2")
        self.pixels = block_pixels(self.block)
        self.key, self.nonce = key, nonce
        self.image_shape = tuple(image_shape[:2])
        self.row, self.col = int(row), int(col)
        self.mac, self.block_index = _block_mac(key, nonce, self.image_shape, self.row, self.col)
        self.layout = LeanBlockRegisters()
        self.load_inputs = load_inputs

    def _keyed_tag(self, qc: QuantumCircuit) -> None:
        lay = self.layout
        append_lean_generation(qc, lay, masked=True)  # base content code of the MSB plane
        self.mac_cnots = append_mac_network(
            qc, msb_message_qubits(lay.pixels), list(lay.out), self.mac.matrix(self.block_index), self.mac.mask(self.block_index)
        )


class SecureEmbeddingCircuit(_SecureBase):
    """Keyed tag generation + LSB embedding for block ``(row, col)`` of an image."""

    def __init__(self, block, key, nonce, image_shape, row: int, col: int, load_inputs: bool = True):
        super().__init__(block, key, nonce, image_shape, row, col, load_inputs)
        lay = self.layout
        qc = lay.circuit("SecureEmbedding")
        if load_inputs:
            load_block(qc, lay.pixels, self.pixels)
            qc.barrier(label="inputs")
        self._keyed_tag(qc)
        qc.barrier(label="tag")
        for i in range(4):
            qc.swap(lay.out[2 * i], lay.pixels[i][0])
            qc.swap(lay.out[2 * i + 1], lay.pixels[i][1])
        self.circuit = qc

    def run(self) -> dict:
        bits = run_basis(self.circuit)
        idx = self.circuit.find_bit
        pixels = [bits_to_int(bits[idx(q).index] for q in reg) for reg in self.layout.pixels]
        return {"watermarked_pixels": pixels, "watermarked_block": np.asarray(pixels, dtype=np.uint8).reshape(2, 2)}


class BlindVerificationCircuit(_SecureBase):
    """Blind check of block ``(row, col)``: flag = 1 iff the LSBs match the keyed tag."""

    def __init__(self, block, key, nonce, image_shape, row: int, col: int, load_inputs: bool = True):
        super().__init__(block, key, nonce, image_shape, row, col, load_inputs)
        lay = self.layout
        self.flag = QuantumRegister(1, "flag")
        qc = lay.circuit("BlindVerification", extra=[self.flag])
        if load_inputs:
            load_block(qc, lay.pixels, self.pixels)
            qc.barrier(label="inputs")
        self._keyed_tag(qc)
        qc.barrier(label="tag")
        for i in range(4):  # out ^= extracted LSBs  ->  all zero iff authentic
            qc.cx(lay.pixels[i][0], lay.out[2 * i])
            qc.cx(lay.pixels[i][1], lay.out[2 * i + 1])
        qc.append(MCXGate(8, ctrl_state=0), list(lay.out) + [self.flag[0]])
        self.circuit = qc

    def run(self) -> dict:
        bits = run_basis(self.circuit)
        idx = self.circuit.find_bit
        extracted = []
        for i in range(4):
            extracted += [bits[idx(self.layout.pixels[i][0]).index], bits[idx(self.layout.pixels[i][1]).index]]
        return {"extracted_bits": extracted, "authentic": bool(bits[idx(self.flag[0]).index])}
