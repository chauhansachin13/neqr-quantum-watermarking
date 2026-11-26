"""Log-depth Carry-Lookahead (Brent-Kung CLA) circuits for NEQR watermarking.

The v2 ``qwm.circuits.lean`` module cuts qubit width from 146 to 44 qubits by
switching to in-place Cuccaro ripple-carry adders, whose depth scales linearly
with operand width (``O(n)``).  For noise-dominated NISQ execution where idle
decoherence scales with circuit duration, this module provides a logarithmic-
depth Brent-Kung carry-lookahead adder (:func:`cla_adder`, ``O(log n)`` carry
tree) and a parallel binary-reduction averaging tree:

* :func:`cla_adder` - clean, garbage-free ``n``-bit CLA adder supporting optional
  ``carry_in``, ``carry_out``, and relative-phase Toffoli (``rccx``) gates.
* :class:`ShallowGenerationCircuit` - 69 qubits (unmasked) or 52 active qubits
  (masked), cutting compiled two-qubit and total circuit depth roughly in half
  relative to :class:`qwm.circuits.lean.LeanGenerationCircuit`.
* :class:`ShallowKeyedEmbeddingCircuit` - 59-qubit keyed MSB-plane embedding
  circuit matching :class:`qwm.circuits.secure.SecureEmbeddingCircuit`.
* :class:`ShallowBlindVerificationCircuit` - 60-qubit blind verification circuit
  matching :class:`qwm.circuits.secure.BlindVerificationCircuit`.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from qiskit import QuantumCircuit, QuantumRegister
from qiskit.circuit import Qubit
from qiskit.circuit.library import MCXGate

from qwm.circuits.lean import append_lean_ppb, load_block
from qwm.circuits.secure import append_mac_network, msb_message_qubits
from qwm.secure.authentication import SecureWatermark
from qwm.simulation import bits_to_int, run_basis
from qwm.watermark.generation import block_pixels, block_watermark_bits

__all__ = [
    "plan_brent_kung",
    "cla_adder",
    "append_cla",
    "append_shallow_average",
    "ShallowBlockRegisters",
    "append_shallow_generation",
    "ShallowGenerationCircuit",
    "ShallowKeyedEmbeddingCircuit",
    "ShallowBlindVerificationCircuit",
]


def plan_brent_kung(width: int) -> list[tuple[int, int, tuple[int, int], tuple[int, int]]]:
    """Plan non-leaf group-propagate intervals ``P[lo..hi]`` for a ``width``-bit BK tree.

    Leaf intervals ``(i, i)`` reuse ``b[i]`` in-place after computing ``a[i] ^ b[i]``;
    intervals starting at ``lo == 0`` are never needed because ``P[0..hi]`` only ever
    would update a carry from before bit 0.
    """
    if width < 1:
        raise ValueError("width must be at least 1")
    allocs: list[tuple[int, int, tuple[int, int], tuple[int, int]]] = []
    stride = 1
    while 2 * stride <= width:
        for right in range(2 * stride - 1, width, 2 * stride):
            left = right - stride
            lo = right - 2 * stride + 1
            if lo > 0:
                allocs.append((lo, right, (lo, left), (left + 1, right)))
        stride *= 2
    return allocs


def _append_cla_raw(
    qc: QuantumCircuit,
    a: Sequence[Qubit],
    b: Sequence[Qubit],
    carry: Sequence[Qubit],
    p_anc: Sequence[Qubit],
    carry_out: Qubit | None = None,
    carry_in: Qubit | None = None,
    *,
    relative_phase: bool = False,
    rp_p_only: bool = True,
) -> None:
    """Emit CLA addition onto explicit qubit lists in ``qc``."""
    n = len(a)
    if len(b) != n or len(carry) < n:
        raise ValueError("a, b, and carry must have compatible lengths >= n")
    pa = plan_brent_kung(n)
    if len(p_anc) < len(pa):
        raise ValueError(f"p_anc requires at least {len(pa)} qubits for n={n}")

    p_map: dict[tuple[int, int], Qubit] = {(i, i): b[i] for i in range(n)}
    for idx, (lo, hi, _, _) in enumerate(pa):
        p_map[(lo, hi)] = p_anc[idx]

    def build_carry_tree() -> QuantumCircuit:
        sub = QuantumCircuit(*qc.qregs)
        toff_c = sub.rccx if (relative_phase and not rp_p_only) else sub.ccx
        toff_p = sub.rccx if relative_phase else sub.ccx
        for i in range(n):
            toff_c(a[i], b[i], carry[i])
            sub.cx(a[i], b[i])
        if carry_in is not None:
            toff_c(b[0], carry_in, carry[0])

        p_created: list[tuple[int, int, int]] = []
        stride = 1
        while 2 * stride <= n:
            for right in range(2 * stride - 1, n, 2 * stride):
                left = right - stride
                toff_c(p_map[(left + 1, right)], carry[left], carry[right])
                lo = right - 2 * stride + 1
                if lo > 0:
                    toff_p(p_map[(lo, left)], p_map[(left + 1, right)], p_map[(lo, right)])
                    p_created.append((lo, left, right))
            stride *= 2

        stride //= 2
        while stride >= 1:
            for left in range(2 * stride - 1, n, 2 * stride):
                right = left + stride
                if right < n:
                    toff_c(p_map[(left + 1, right)], carry[left], carry[right])
            stride //= 2

        for lo, left, right in reversed(p_created):
            toff_p(p_map[(lo, left)], p_map[(left + 1, right)], p_map[(lo, right)])
        for i in range(n):
            sub.cx(a[i], b[i])
        return sub

    fwd = build_carry_tree()
    qc.compose(fwd, inplace=True)
    if carry_out is not None:
        qc.cx(carry[n - 1], carry_out)
    for i in range(n):
        qc.cx(a[i], b[i])
        if i == 0 and carry_in is not None:
            qc.cx(carry_in, b[0])
        elif i > 0:
            qc.cx(carry[i - 1], b[i])
    for i in range(n):
        qc.x(b[i])
    qc.compose(fwd.inverse(), inplace=True)
    for i in range(n):
        qc.x(b[i])


def cla_adder(
    n: int,
    carry_in: bool = False,
    carry_out: bool = True,
    relative_phase: bool = False,
    rp_p_only: bool = True,
) -> QuantumCircuit:
    """Reversible in-place Brent-Kung carry-lookahead adder: ``b <- (a + b + cin) mod 2**n``.

    Uses Drapers et al.'s carry-tree uncomputation via bitwise complement, restoring
    ``a``, ``cin``, ``carry``, and internal propagate ancillas ``panc`` cleanly to their
    initial states.  Setting ``rp_p_only=True`` keeps exact unitary equivalence with
    ``relative_phase=False``; setting ``rp_p_only=False`` inside an outer Bennett
    compute/uncompute block uses ``rccx`` on all Toffolis for minimal depth.
    """
    a = QuantumRegister(n, "a")
    b = QuantumRegister(n, "b")
    c = QuantumRegister(n, "c")
    regs: list[QuantumRegister] = [a, b, c]
    cin = QuantumRegister(1, "cin") if carry_in else None
    if cin is not None:
        regs.append(cin)
    cout = QuantumRegister(1, "cout") if carry_out else None
    if cout is not None:
        regs.append(cout)
    p_allocs = plan_brent_kung(n)
    p_anc = QuantumRegister(len(p_allocs), "panc") if p_allocs else None
    if p_anc is not None:
        regs.append(p_anc)

    qc = QuantumCircuit(*regs, name=f"CLA{n}")
    _append_cla_raw(
        qc,
        list(a),
        list(b),
        list(c),
        list(p_anc) if p_anc is not None else [],
        carry_out=cout[0] if cout is not None else None,
        carry_in=cin[0] if cin is not None else None,
        relative_phase=relative_phase,
        rp_p_only=rp_p_only,
    )
    return qc


def append_cla(
    qc: QuantumCircuit,
    a: Sequence[Qubit],
    b: Sequence[Qubit],
    carry: Sequence[Qubit],
    p_anc: Sequence[Qubit],
    carry_out: Qubit | None = None,
    carry_in: Qubit | None = None,
    relative_phase: bool = False,
    rp_p_only: bool = True,
) -> None:
    """Compose a :func:`cla_adder` onto arbitrary wires in ``qc``."""
    sub = cla_adder(
        len(a),
        carry_in=carry_in is not None,
        carry_out=carry_out is not None,
        relative_phase=relative_phase,
        rp_p_only=rp_p_only,
    )
    wires = list(a) + list(b) + list(carry[: len(a)])
    if carry_in is not None:
        wires.append(carry_in)
    if carry_out is not None:
        wires.append(carry_out)
    n_p = len(plan_brent_kung(len(a)))
    if n_p:
        wires.extend(list(p_anc[:n_p]))
    qc.compose(sub, wires, inplace=True)


class ShallowBlockRegisters:
    """Qubit layout for shallow CLA block generation, embedding and verification."""

    def __init__(self, masked: bool = False):
        self.masked = bool(masked)
        width = 6 if self.masked else 8
        n_p = max(len(plan_brent_kung(width)), len(plan_brent_kung(width + 1)))
        n_p = max(n_p, 1)
        self.pixels = [QuantumRegister(8, f"p{i}") for i in range(4)]
        self.out = QuantumRegister(8, "out")
        self.ca = QuantumRegister(width, "ca")
        self.cb = QuantumRegister(width, "cb")
        self.pa = QuantumRegister(len(plan_brent_kung(width)), "pa") if plan_brent_kung(width) else None
        self.pb = QuantumRegister(len(plan_brent_kung(width)), "pb") if plan_brent_kung(width) else None
        self.ext = QuantumRegister(3, "ext")
        self.cin = None if self.masked else QuantumRegister(2, "cin")
        # Ensure Stage 2 propagate ancillas fit plan_brent_kung(width + 1)
        extra_p = max(0, len(plan_brent_kung(width + 1)) - 2 * len(plan_brent_kung(width)))
        self.p_extra = QuantumRegister(extra_p, "pe") if extra_p else None
        _ = n_p

    @property
    def ancillas(self) -> list[Qubit]:
        qubits = list(self.ca) + list(self.cb) + list(self.ext)
        if self.pa is not None:
            qubits.extend(self.pa)
        if self.pb is not None:
            qubits.extend(self.pb)
        if self.cin is not None:
            qubits.extend(self.cin)
        if self.p_extra is not None:
            qubits.extend(self.p_extra)
        return qubits

    def registers(self) -> list[QuantumRegister]:
        regs: list[QuantumRegister] = [*self.pixels, self.out, self.ca, self.cb]
        if self.pa is not None:
            regs.append(self.pa)
        if self.pb is not None:
            regs.append(self.pb)
        regs.append(self.ext)
        if self.cin is not None:
            regs.append(self.cin)
        if self.p_extra is not None:
            regs.append(self.p_extra)
        return regs

    def circuit(self, name: str, extra: Sequence[QuantumRegister] = ()) -> QuantumCircuit:
        return QuantumCircuit(*self.registers(), *extra, name=name)


def append_shallow_average(
    qc: QuantumCircuit,
    pixels: Sequence[Sequence[Qubit]],
    out: Sequence[Qubit],
    ca: Sequence[Qubit],
    cb: Sequence[Qubit],
    pa: Sequence[Qubit],
    pb: Sequence[Qubit],
    ext: Sequence[Qubit],
    cin: Sequence[Qubit] | None = None,
    masked: bool = False,
    relative_phase: bool = True,
) -> None:
    """XOR block average onto ``out`` via parallel CLA pair sums and Bennett uncomputation."""
    lo = 2 if masked else 0
    a0, a1, a2, a3 = (list(p[lo:8]) for p in pixels)
    compute = QuantumCircuit(*qc.qregs)

    if not masked:
        if cin is None or len(cin) < 2:
            raise ValueError("cin with 2 qubits required when masked=False")
        compute.x(cin[0])
        compute.x(cin[1])

    # Level 1: p0 + p1 and p2 + p3 run on strictly disjoint qubits in parallel.
    append_cla(
        compute,
        a0,
        a1,
        ca,
        pa,
        carry_out=ext[0],
        carry_in=None if masked else cin[0],
        relative_phase=relative_phase,
        rp_p_only=False,
    )
    append_cla(
        compute,
        a2,
        a3,
        cb,
        pb,
        carry_out=ext[1],
        carry_in=None if masked else cin[1],
        relative_phase=relative_phase,
        rp_p_only=False,
    )
    if not masked:
        compute.x(cin[0])
        compute.x(cin[1])

    # Level 2: (p0 + p1) + (p2 + p3) using cleaned Stage-1 ancillas.
    s01 = a1 + [ext[0]]
    s23 = a3 + [ext[1]]
    c_hi = list(ca) + [cb[0]]
    p_hi = list(pa) + list(pb)
    append_cla(
        compute,
        s01,
        s23,
        c_hi,
        p_hi,
        carry_out=ext[2],
        carry_in=None,
        relative_phase=relative_phase,
        rp_p_only=False,
    )

    total = a3 + [ext[1], ext[2]]
    aa = total if masked else total[2:10]
    qc.compose(compute, inplace=True)
    for k in range(8):
        qc.cx(aa[k], out[k])
    qc.compose(compute.inverse(), inplace=True)


def append_shallow_generation(
    qc: QuantumCircuit,
    lay: ShallowBlockRegisters,
    masked: bool | None = None,
    relative_phase: bool = True,
) -> None:
    """Content code ``Wb = PPB xor AA`` computed in parallel CLA depth onto ``lay.out``."""
    use_masked = lay.masked if masked is None else bool(masked)
    for i in range(4):
        append_lean_ppb(
            qc,
            list(lay.pixels[i]),
            lay.out[2 * i],
            lay.out[2 * i + 1],
            lay.ca[i],
            masked=use_masked,
            relative_phase=relative_phase,
        )
    pa = list(lay.pa or []) + list(lay.p_extra or [])
    pb = list(lay.pb or [])
    append_shallow_average(
        qc,
        [list(p) for p in lay.pixels],
        list(lay.out),
        list(lay.ca),
        list(lay.cb),
        pa,
        pb,
        list(lay.ext),
        cin=list(lay.cin) if lay.cin is not None else None,
        masked=use_masked,
        relative_phase=relative_phase,
    )


class ShallowGenerationCircuit:
    """Shallow CLA block watermark generation (69 qubits unmasked, 52 active masked)."""

    def __init__(self, block, masked: bool = False, load_inputs: bool = True, relative_phase: bool = True):
        self.block = np.asarray(block, dtype=np.int64)
        if self.block.shape != (2, 2):
            raise ValueError("block must be 2x2")
        self.pixels = block_pixels(self.block)
        self.masked = bool(masked)
        self.relative_phase = relative_phase
        self.layout = ShallowBlockRegisters(masked=self.masked)
        qc = self.layout.circuit("ShallowGeneration")
        if load_inputs:
            load_block(qc, self.layout.pixels, self.pixels)
            qc.barrier(label="inputs")
        append_shallow_generation(qc, self.layout, masked=self.masked, relative_phase=relative_phase)
        self.circuit = qc

    def _index(self, q: Qubit) -> int:
        return self.circuit.find_bit(q).index

    def run(self) -> dict:
        bits = run_basis(self.circuit)
        wb = [bits[self._index(q)] for q in self.layout.out]
        restored = [bits_to_int(bits[self._index(q)] for q in reg) for reg in self.layout.pixels]
        clean = all(bits[self._index(q)] == 0 for q in self.layout.ancillas)
        return {"watermark": wb, "pixels_restored": restored == self.pixels, "ancillas_clean": clean}

    def expected(self) -> list[int]:
        img = self.block & 0xFC if self.masked else self.block
        return block_watermark_bits(img)


class _ShallowSecureBase:
    def __init__(self, block, key, nonce, image_shape, row: int, col: int, load_inputs: bool = True):
        self.block = np.asarray(block, dtype=np.int64)
        if self.block.shape != (2, 2):
            raise ValueError("block must be 2x2")
        self.pixels = block_pixels(self.block)
        self.key, self.nonce = key, nonce
        self.image_shape = tuple(image_shape[:2])
        self.row, self.col = int(row), int(col)
        sw = SecureWatermark(key, nonce)
        self.mac = sw.mac(self.image_shape)
        self.block_index = self.row * (self.image_shape[1] // 2) + self.col
        self.layout = ShallowBlockRegisters(masked=True)
        self.load_inputs = load_inputs

    def _keyed_tag(self, qc: QuantumCircuit) -> None:
        lay = self.layout
        append_shallow_generation(qc, lay, masked=True)
        self.mac_cnots = append_mac_network(
            qc,
            msb_message_qubits(lay.pixels),
            list(lay.out),
            self.mac.matrix(self.block_index),
            self.mac.mask(self.block_index),
        )


class ShallowKeyedEmbeddingCircuit(_ShallowSecureBase):
    """Shallow CLA keyed tag generation + LSB embedding for block ``(row, col)`` (59 qubits)."""

    def __init__(self, block, key, nonce, image_shape, row: int, col: int, load_inputs: bool = True):
        super().__init__(block, key, nonce, image_shape, row, col, load_inputs)
        lay = self.layout
        qc = lay.circuit("ShallowSecureEmbedding")
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
        return {
            "watermarked_pixels": pixels,
            "watermarked_block": np.asarray(pixels, dtype=np.uint8).reshape(2, 2),
        }


class ShallowBlindVerificationCircuit(_ShallowSecureBase):
    """Shallow CLA blind verification of block ``(row, col)``: flag = 1 iff authentic (60 qubits)."""

    def __init__(self, block, key, nonce, image_shape, row: int, col: int, load_inputs: bool = True):
        super().__init__(block, key, nonce, image_shape, row, col, load_inputs)
        lay = self.layout
        self.flag = QuantumRegister(1, "flag")
        qc = lay.circuit("ShallowBlindVerification", extra=[self.flag])
        if load_inputs:
            load_block(qc, lay.pixels, self.pixels)
            qc.barrier(label="inputs")
        self._keyed_tag(qc)
        qc.barrier(label="tag")
        for i in range(4):
            qc.cx(lay.pixels[i][0], lay.out[2 * i])
            qc.cx(lay.pixels[i][1], lay.out[2 * i + 1])
        qc.append(MCXGate(8, ctrl_state=0), list(lay.out) + [self.flag[0]])
        self.circuit = qc

    def run(self) -> dict:
        bits = run_basis(self.circuit)
        idx = self.circuit.find_bit
        extracted = []
        for i in range(4):
            extracted += [
                bits[idx(self.layout.pixels[i][0]).index],
                bits[idx(self.layout.pixels[i][1]).index],
            ]
        clean = all(bits[idx(q).index] == 0 for q in self.layout.ancillas)
        return {
            "extracted_bits": extracted,
            "authentic": bool(bits[idx(self.flag[0]).index]),
            "ancillas_clean": clean,
        }
