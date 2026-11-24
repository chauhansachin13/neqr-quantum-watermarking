"""
Hardware-efficient ("lean") circuits for one 2x2 block.

The reference design spends 354 qubits on watermark generation and 400 each
on embedding and extraction, because every RPA keeps a copy of one operand
and all carries (``4n`` qubits per ``n``-bit addition) and nothing is ever
uncomputed.  The circuits in this module compute *exactly the same
functions* with in-place arithmetic and uncomputation:

* **Cuccaro ripple-carry adder** (Cuccaro, Draper, Kutin, Moulton 2004):
  ``b <- a + b`` in place with one shared carry-in ancilla and one carry-out
  qubit, ``2n`` Toffoli and ``4n + 1`` CNOT gates.
* **Pixel position bits from half an adder.**  The base design keeps the
  sum and carry registers of ``low + high`` and reduces them to parities.
  Since ``s_i = l_i xor h_i xor c_{i-1}``::

      PPB_1 = c_0 xor c_1 xor c_2 xor c_3      (parity of the carries)
      PPB_2 = parity(s) xor PPB_1 = parity(pixel) xor c_3

  and the MAJ ladder of a Cuccaro adder leaves exactly ``c_0..c_3`` on the
  low-nibble wires, so a MAJ ladder, five CNOTs, the parity CNOTs and the
  reversed ladder give both bits - no sum bits and no carry register.
* **Rounded average without D4 gates.**  ``AA = floor(S/4 + 0.5) =
  (S + 2) >> 2``: the ``+2`` is a carry-in of 1 on each of the two first
  additions and the division by four is a relabelling of wires (no SWAPs).
* **Bennett uncomputation.**  After the watermark is XOR-ed into an 8-qubit
  output register, every adder runs backwards, so the pixel registers and all
  ancillas return to their initial state (garbage-free).
* **Relative-phase Toffolis.**  Every Toffoli above sits in a matched
  compute/uncompute pair whose wires hold the same values at both ends, so
  each can be a 3-CNOT Margolus gate instead of a 6-CNOT Toffoli: the phases
  cancel and the circuit is the *same unitary* (checked with
  :class:`qiskit.quantum_info.Operator` in the tests).  This removes about a
  third of the CNOTs.

Resulting widths for one block: generation 44 qubits, embedding 40,
non-blind extraction 41 (versus 354 / 400 / 400 reported, and 146 / 64 / 88
for the module-faithful circuits in :mod:`qwm.circuits`).
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from qiskit import QuantumCircuit, QuantumRegister
from qiskit.circuit import Qubit
from qiskit.circuit.library import MCXGate

from qwm.simulation import bits_to_int, run_basis
from qwm.watermark.embedding import embed_block
from qwm.watermark.generation import block_pixels, block_watermark_bits

__all__ = [
    "cuccaro_adder",
    "append_cuccaro",
    "append_lean_ppb",
    "append_lean_average",
    "LeanBlockRegisters",
    "LeanGenerationCircuit",
    "LeanEmbeddingCircuit",
    "LeanExtractionCircuit",
]


# --------------------------------------------------------------------------- #
# Cuccaro ripple-carry adder
# --------------------------------------------------------------------------- #
def _toffoli(qc: QuantumCircuit, c1, c2, t, relative_phase: bool) -> None:
    if relative_phase:
        qc.rccx(c1, c2, t)  # Margolus gate: 3 CNOTs, Toffoli up to a diagonal phase
    else:
        qc.ccx(c1, c2, t)


def _maj(qc: QuantumCircuit, x, y, z, relative_phase: bool = False) -> None:
    """MAJ(c_i, b_i, a_i): leaves the carry c_{i+1} on ``z``."""
    qc.cx(z, y)
    qc.cx(z, x)
    _toffoli(qc, x, y, z, relative_phase)


def _uma(qc: QuantumCircuit, x, y, z, relative_phase: bool = False) -> None:
    """UnMajority-and-Add (2-CNOT version): restores ``x``/``z`` and leaves the sum on ``y``."""
    _toffoli(qc, x, y, z, relative_phase)
    qc.cx(z, x)
    qc.cx(x, y)


def append_cuccaro(
    qc: QuantumCircuit,
    a: Sequence[Qubit],
    b: Sequence[Qubit],
    cin: Qubit,
    cout: Qubit | None = None,
    relative_phase: bool = False,
) -> None:
    """Append ``b <- a + b`` (mod ``2**n``); the carry-out is XOR-ed onto ``cout``.

    ``a`` and ``cin`` are restored afterwards (``cin`` acts as a carry-in).
    With ``relative_phase=True`` every Toffoli is a 3-CNOT Margolus gate: the
    Toffoli of ``MAJ_i`` and the one of ``UMA_i`` act on the same three wires
    with the same values (everything in between is restored), so their
    relative phases cancel and the adder is *exactly* the same unitary.
    """
    n = len(a)
    if n != len(b) or n == 0:
        raise ValueError("a and b must be non-empty registers of equal length")
    rp = relative_phase
    _maj(qc, cin, b[0], a[0], rp)
    for i in range(1, n):
        _maj(qc, a[i - 1], b[i], a[i], rp)
    if cout is not None:
        qc.cx(a[n - 1], cout)
    for i in range(n - 1, 0, -1):
        _uma(qc, a[i - 1], b[i], a[i], rp)
    _uma(qc, cin, b[0], a[0], rp)


def cuccaro_adder(n: int, carry_out: bool = True, relative_phase: bool = False) -> QuantumCircuit:
    """Stand-alone ``n``-bit Cuccaro adder on ``a (n), b (n), cin, [cout]``."""
    a, b = QuantumRegister(n, "a"), QuantumRegister(n, "b")
    cin = QuantumRegister(1, "cin")
    regs = [a, b, cin]
    cout = None
    if carry_out:
        cout = QuantumRegister(1, "cout")
        regs.append(cout)
    qc = QuantumCircuit(*regs, name=f"CDKM{n}")
    append_cuccaro(qc, list(a), list(b), cin[0], cout[0] if cout is not None else None, relative_phase)
    return qc


# --------------------------------------------------------------------------- #
# Building blocks of the lean generation circuit
# --------------------------------------------------------------------------- #
def append_lean_ppb(
    qc: QuantumCircuit,
    pixel: Sequence[Qubit],
    out1: Qubit,
    out2: Qubit,
    cin: Qubit,
    masked: bool = False,
    relative_phase: bool = True,
) -> None:
    """XOR ``(PPB_1, PPB_2)`` of one 8-qubit pixel onto ``out1`` / ``out2``.

    Only the MAJ half of a Cuccaro adder is needed.  After the MAJ ladder of
    ``low + high`` the wires hold ``cin = a_0``, ``low[i] = c_i xor a_{i+1}``
    and ``low[n-1] = c_{n-1}`` (``a`` = low nibble, ``c_i`` = carry out of bit
    ``i``), so XOR-ing ``parity(a)`` beforehand and all those wires afterwards
    leaves ``PPB_1 = c_0 xor c_1 xor c_2 xor c_3`` (the parity of the carry
    register of the base design), and ``PPB_2 = parity(pixel) xor c_3``; the
    ladder is then run backwards.  ``masked=True`` evaluates the bits of
    ``pixel & 0xFC`` (the two LSB qubits are ignored; the carries out of the
    two zero bits vanish).  ``cin`` must be ``|0>`` and is restored.  The
    ladder's Toffolis may be relative-phase gates: the reversed ladder undoes
    each phase and the CNOTs in between only read the ladder wires.
    """
    if masked:
        par = list(pixel[2:8])
        low, high = list(pixel[2:4]), list(pixel[6:8])  # bits 0,1 of the masked low nibble are 0
    else:
        par = list(pixel)
        low, high = list(pixel[0:4]), list(pixel[4:8])
    for q in par:  # out2 = parity(pixel)
        qc.cx(q, out2)
    for q in low:  # pre-cancel the operand bits that the ladder leaves on its wires
        qc.cx(q, out1)
    ladder = QuantumCircuit(*qc.qregs)
    _maj(ladder, cin, high[0], low[0], relative_phase)
    for i in range(1, len(low)):
        _maj(ladder, low[i - 1], high[i], low[i], relative_phase)
    qc.compose(ladder, inplace=True)
    for q in [cin] + low:  # out1 = parity(a) xor parity(a) xor parity(c) = PPB_1
        qc.cx(q, out1)
    qc.cx(low[-1], out2)  # PPB_2 = parity(pixel) xor c_3
    qc.compose(ladder.inverse(), inplace=True)  # uncompute the carries


def append_lean_average(
    qc: QuantumCircuit,
    pixels: Sequence[Sequence[Qubit]],
    out: Sequence[Qubit],
    cin: Qubit,
    ext: Sequence[Qubit],
    masked: bool = False,
    relative_phase: bool = True,
) -> None:
    """XOR the block average onto the 8-qubit register ``out`` and uncompute.

    ``masked=False``: ``AA = floor((p0+p1+p2+p3)/4 + 0.5)`` (base scheme).
    ``masked=True`` : ``AA = sum(p_i >> 2)``, the exact average of the MSB plane.
    ``ext`` are three ``|0>`` qubits ``(e1, e3, e4)`` that extend the partial
    sums; ``e4`` doubles as the carry-in of the second first-level adder, so
    ``p0 + p1`` and ``p2 + p3`` run in parallel.
    """
    e1, e3, e4 = ext
    lo = 2 if masked else 0
    p0, p1, p2, p3 = (list(p[lo:8]) for p in pixels)
    compute = QuantumCircuit(*qc.qregs)
    if not masked:
        compute.x(cin)  # carry-in 1 on both first-level adders: the total becomes S + 2
        compute.x(e4)
    rp = relative_phase
    append_cuccaro(compute, p0, p1, cin, e1, rp)  # (p1, e1) = p0 + p1 (+1)
    append_cuccaro(compute, p2, p3, e4, e3, rp)  # (p3, e3) = p2 + p3 (+1), in parallel
    if not masked:
        compute.x(cin)
        compute.x(e4)
    append_cuccaro(compute, p1 + [e1], p3 + [e3], cin, e4, rp)  # (p3, e3, e4) = S (+2)
    total = p3 + [e3, e4]
    # masked : 8-bit sum of the four 6-bit MSB values (exactly the MSB-plane average);
    # full   : (S + 2) >> 2 = floor(S/4 + 0.5) - dividing by four is a relabelling of
    #          wires, so the D4 module needs no gates and the rounding costs nothing.
    aa = total if masked else total[2:10]
    qc.compose(compute, inplace=True)
    for k in range(8):
        qc.cx(aa[k], out[k])
    qc.compose(compute.inverse(), inplace=True)  # Bennett uncomputation


class LeanBlockRegisters:
    """Register layout shared by the lean circuits (44 qubits)."""

    def __init__(self) -> None:
        self.pixels = [QuantumRegister(8, f"p{i}") for i in range(4)]
        self.out = QuantumRegister(8, "wb")
        self.anc = QuantumRegister(4, "anc")  # cin, e1, e3, e4

    def circuit(self, name: str, extra: Sequence[QuantumRegister] = ()) -> QuantumCircuit:
        return QuantumCircuit(*self.pixels, self.out, self.anc, *extra, name=name)

    @property
    def cin(self):
        return self.anc[0]

    @property
    def ext(self):
        return [self.anc[1], self.anc[2], self.anc[3]]


def load_block(qc: QuantumCircuit, regs: Sequence[QuantumRegister], pixels: Sequence[int]) -> None:
    for reg, v in zip(regs, pixels, strict=True):
        for k in range(len(reg)):
            if (int(v) >> k) & 1:
                qc.x(reg[k])


def append_lean_generation(qc: QuantumCircuit, lay: LeanBlockRegisters, masked: bool = False, relative_phase: bool = True) -> None:
    """Content code ``Wb = PPB xor AA`` of the block XOR-ed onto ``lay.out``.

    Each pixel's PPB ladder borrows its own ancilla as carry-in, so the four
    ladders act on disjoint qubits and run in parallel.
    """
    for i in range(4):
        append_lean_ppb(qc, list(lay.pixels[i]), lay.out[2 * i], lay.out[2 * i + 1], lay.anc[i], masked, relative_phase)
    append_lean_average(qc, [list(p) for p in lay.pixels], list(lay.out), lay.cin, lay.ext, masked, relative_phase)


# --------------------------------------------------------------------------- #
# Block circuits
# --------------------------------------------------------------------------- #
class LeanGenerationCircuit:
    """Garbage-free watermark generation for one block (44 qubits).

    >>> LeanGenerationCircuit([[50, 60], [48, 32]]).run()["watermark"]
    [1, 1, 0, 0, 1, 1, 0, 1]
    """

    def __init__(self, block, masked: bool = False, load_inputs: bool = True, relative_phase: bool = True):
        self.block = np.asarray(block, dtype=np.int64)
        if self.block.shape != (2, 2):
            raise ValueError("block must be 2x2")
        self.pixels = block_pixels(self.block)
        self.masked = masked
        self.relative_phase = relative_phase
        self.layout = LeanBlockRegisters()
        qc = self.layout.circuit("LeanGeneration")
        if load_inputs:
            load_block(qc, self.layout.pixels, self.pixels)
            qc.barrier(label="inputs")
        append_lean_generation(qc, self.layout, masked=masked, relative_phase=relative_phase)
        self.circuit = qc

    def _index(self, q) -> int:
        return self.circuit.find_bit(q).index

    def run(self) -> dict:
        bits = run_basis(self.circuit)
        wb = [bits[self._index(q)] for q in self.layout.out]
        restored = [bits_to_int(bits[self._index(q)] for q in reg) for reg in self.layout.pixels]
        clean = all(bits[self._index(q)] == 0 for q in self.layout.anc)
        return {"watermark": wb, "pixels_restored": restored == self.pixels, "ancillas_clean": clean}

    def expected(self) -> list[int]:
        img = self.block & 0xFC if self.masked else self.block
        return block_watermark_bits(img)


class LeanEmbeddingCircuit:
    """LSB-replacement embedding of eight given watermark bits (40 qubits, 8 SWAPs)."""

    def __init__(self, block, watermark_bits, load_inputs: bool = True):
        self.block = np.asarray(block, dtype=np.int64)
        self.pixels = block_pixels(self.block)
        self.watermark = [int(b) & 1 for b in watermark_bits]
        if len(self.watermark) != 8:
            raise ValueError("eight watermark bits are required")
        self.pix = [QuantumRegister(8, f"p{i}") for i in range(4)]
        self.wb = QuantumRegister(8, "wb")
        qc = QuantumCircuit(*self.pix, self.wb, name="LeanEmbedding")
        if load_inputs:
            load_block(qc, self.pix, self.pixels)
            for k, b in enumerate(self.watermark):
                if b:
                    qc.x(self.wb[k])
            qc.barrier(label="inputs")
        for i in range(4):
            qc.swap(self.wb[2 * i], self.pix[i][0])
            qc.swap(self.wb[2 * i + 1], self.pix[i][1])
        self.circuit = qc

    def run(self) -> dict:
        bits = run_basis(self.circuit)
        idx = self.circuit.find_bit
        pixels = [bits_to_int(bits[idx(q).index] for q in reg) for reg in self.pix]
        return {"watermarked_pixels": pixels, "watermarked_block": np.asarray(pixels, dtype=np.uint8).reshape(2, 2)}

    def expected(self) -> np.ndarray:
        return embed_block(self.block, self.watermark, mode="lsb")


class LeanExtractionCircuit:
    """Non-blind extraction (base scheme): read the LSBs, compare with the reference (41 qubits).

    The XOR + RPS step of the base design computes ``(W^{k+1} xor W^k) - W^{k+1} = W^k``,
    i.e. the identity, so extraction is a read-out of the two LSB qubits; the QE
    comparison with the reference watermark becomes 8 CNOTs and one
    zero-controlled MCX writing a single "authentic" flag.
    """

    def __init__(self, block, reference_bits, load_inputs: bool = True):
        self.block = np.asarray(block, dtype=np.int64)
        self.pixels = block_pixels(self.block)
        self.reference = [int(b) & 1 for b in reference_bits]
        self.pix = [QuantumRegister(8, f"w{i}") for i in range(4)]
        self.ref = QuantumRegister(8, "ref")
        self.flag = QuantumRegister(1, "flag")
        qc = QuantumCircuit(*self.pix, self.ref, self.flag, name="LeanExtraction")
        if load_inputs:
            load_block(qc, self.pix, self.pixels)
            for k, b in enumerate(self.reference):
                if b:
                    qc.x(self.ref[k])
            qc.barrier(label="inputs")
        for i in range(4):
            qc.cx(self.pix[i][0], self.ref[2 * i])
            qc.cx(self.pix[i][1], self.ref[2 * i + 1])
        qc.append(MCXGate(8, ctrl_state=0), list(self.ref) + [self.flag[0]])
        self.circuit = qc

    def run(self) -> dict:
        bits = run_basis(self.circuit)
        idx = self.circuit.find_bit
        extracted = []
        for i in range(4):
            extracted += [bits[idx(self.pix[i][0]).index], bits[idx(self.pix[i][1]).index]]
        return {"extracted_bits": extracted, "authentic": bool(bits[idx(self.flag[0]).index])}
