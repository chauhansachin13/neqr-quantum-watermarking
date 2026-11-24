"""
NISQ feasibility study: hardware mapping and noisy simulation of the circuits.

The reference design reports qubit counts but never runs its circuits with
noise ("a simulator applies gates exactly; a real quantum processor does
not").  This module answers the obvious follow-up questions for one 2x2 block:

1. **What does each circuit cost on real connectivity?**  Circuits are
   compiled to ``{u, cx}`` with all-to-all connectivity and to
   ``{rz, sx, x, cx}`` on an IBM-style heavy-hex lattice
   (:func:`qiskit.transpiler.CouplingMap.from_heavy_hex`) with Sabre layout and
   routing, and their two-qubit gate counts and depths are reported.
2. **How often is the answer still right under noise?**  Every CNOT is
   followed by a two-qubit depolarising channel that applies a uniformly random
   non-identity Pauli with probability ``p2``; every single-qubit gate by a
   one-qubit channel with probability ``p1`` (default ``p2 / 10``); measured
   bits flip with probability ``p_meas``.  The circuits are simulated with
   Qiskit Aer's matrix-product-state method, which handles the 40-200 qubit
   circuits here because their states stay close to basis states.  The
   *success probability* is the share of shots whose output register equals
   the noiseless answer.
3. **What error rate would make it practical?**  The two-qubit error at which
   the success probability crosses 99 % (and 50 %) is interpolated from a
   sweep.

The estimated success probability (ESP, the probability that no gate fails
at all) is reported alongside as the usual analytic lower bound.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from qiskit import QuantumCircuit, transpile
from qiskit.transpiler import CouplingMap

from qwm.resources import flatten_reversible

__all__ = [
    "BlockTask",
    "block_tasks",
    "compile_logical",
    "compile_heavy_hex",
    "heavy_hex_distance",
    "estimated_success_probability",
    "noise_model",
    "success_probability",
    "threshold",
]

WORKED_BLOCK = np.array([[50, 60], [48, 32]])


@dataclass
class BlockTask:
    """A block circuit together with the qubits that hold its answer."""

    name: str
    family: str  # "base-v1" | "lean" | "keyed"
    stage: str  # "generation" | "embedding" | "extraction" | "verification"
    circuit: QuantumCircuit
    outputs: list[int]
    expected: list[int]

    @property
    def expected_key(self) -> str:
        """Aer count key of the noiseless answer (classical bit 0 is rightmost)."""
        return "".join(str(int(b)) for b in reversed(self.expected))


def _pixel_bits(circuit: QuantumCircuit, regs, pixels) -> tuple[list[int], list[int]]:
    outs, exp = [], []
    for reg, v in zip(regs, pixels, strict=True):
        for k in range(8):
            outs.append(circuit.find_bit(reg[k]).index)
            exp.append((int(v) >> k) & 1)
    return outs, exp


def block_tasks(block=WORKED_BLOCK, key: str = "nisq-demo-key", nonce: str = "block") -> list[BlockTask]:
    """All circuit families evaluated by the study, built for one block."""
    from qwm.circuits import (
        WatermarkEmbeddingCircuit,
        WatermarkExtractionCircuit,
        WatermarkGenerationCircuit,
    )
    from qwm.circuits.lean import LeanEmbeddingCircuit, LeanExtractionCircuit, LeanGenerationCircuit
    from qwm.circuits.secure import BlindVerificationCircuit, SecureEmbeddingCircuit
    from qwm.watermark.embedding import embed_block
    from qwm.watermark.generation import block_watermark_bits

    block = np.asarray(block)
    wb = block_watermark_bits(block)
    tasks: list[BlockTask] = []

    gen = WatermarkGenerationCircuit(block)
    tasks.append(BlockTask("base-v1 generation", "base-v1", "generation", gen.circuit, gen.output_qubits, wb))
    emb = WatermarkEmbeddingCircuit(block, wb)
    paper_w = embed_block(block, wb, mode="paper").reshape(-1)
    o, e = _pixel_bits(emb.circuit, [emb.circuit.qregs[i] for i in range(4)], paper_w)
    tasks.append(BlockTask("base-v1 embedding", "base-v1", "embedding", emb.circuit, o, e))
    ext = WatermarkExtractionCircuit(paper_w.reshape(2, 2), wb)
    tasks.append(BlockTask("base-v1 extraction", "base-v1", "extraction", ext.circuit, ext.output_qubits, wb))

    lg = LeanGenerationCircuit(block)
    tasks.append(BlockTask("lean generation", "lean", "generation", lg.circuit, [lg.circuit.find_bit(q).index for q in lg.layout.out], wb))
    le = LeanEmbeddingCircuit(block, wb)
    lsb_w = embed_block(block, wb, mode="lsb").reshape(-1)
    o, e = _pixel_bits(le.circuit, le.pix, lsb_w)
    tasks.append(BlockTask("lean embedding", "lean", "embedding", le.circuit, o, e))
    lx = LeanExtractionCircuit(lsb_w.reshape(2, 2), wb)
    outs = [lx.circuit.find_bit(lx.flag[0]).index]
    tasks.append(BlockTask("lean extraction", "lean", "extraction", lx.circuit, outs, [1]))

    shape = (2, 2)
    se = SecureEmbeddingCircuit(block, key, nonce, shape, 0, 0)
    watermarked = se.run()["watermarked_pixels"]
    o, e = _pixel_bits(se.circuit, se.layout.pixels, watermarked)
    tasks.append(BlockTask("keyed embedding", "keyed", "embedding", se.circuit, o, e))
    bv = BlindVerificationCircuit(np.asarray(watermarked).reshape(2, 2), key, nonce, shape, 0, 0)
    tasks.append(BlockTask("keyed blind verification", "keyed", "verification", bv.circuit, [bv.circuit.find_bit(bv.flag[0]).index], [1]))
    return tasks


# --------------------------------------------------------------------------- #
# Compilation
# --------------------------------------------------------------------------- #
BASIS = ["rz", "sx", "x", "cx"]  # IBM-style native set (rz is virtual, i.e. error-free)


def _measured_flat(task: BlockTask) -> QuantumCircuit:
    """Reversible-level circuit with the output register measured.

    Measurements are added *before* transpiling: the optimiser may replace
    SWAP gates by a relabelling of qubits, and only then does it keep track of
    where each output ends up.
    """
    flat = flatten_reversible(task.circuit)
    qc = QuantumCircuit(flat.num_qubits, len(task.outputs))
    qc.compose(flat, inplace=True)
    qc.measure(task.outputs, list(range(len(task.outputs))))
    return qc


def compile_logical(task: BlockTask, optimization_level: int = 2, seed: int = 11) -> QuantumCircuit:
    """All-to-all compilation to ``{rz, sx, x, cx}`` with the outputs measured."""
    return transpile(_measured_flat(task), basis_gates=BASIS, optimization_level=optimization_level, seed_transpiler=seed)


def heavy_hex_distance(num_qubits: int) -> int:
    """Smallest odd code distance whose heavy-hex lattice holds ``num_qubits``."""
    d = 3
    while CouplingMap.from_heavy_hex(d).size() < num_qubits:
        d += 2
    return d


def compile_heavy_hex(task: BlockTask, distance: int | None = None, optimization_level: int = 3, seed: int = 11) -> QuantumCircuit:
    """Sabre layout + routing on a heavy-hex lattice, basis ``{rz, sx, x, cx}``."""
    flat_m = _measured_flat(task)
    d = distance or heavy_hex_distance(flat_m.num_qubits)
    cmap = CouplingMap.from_heavy_hex(d)
    return transpile(
        flat_m,
        coupling_map=cmap,
        basis_gates=BASIS,
        optimization_level=optimization_level,
        seed_transpiler=seed,
        layout_method="sabre",
        routing_method="sabre",
    )


def gate_counts(qc: QuantumCircuit) -> dict:
    ops = qc.count_ops()
    two_q = int(ops.get("cx", 0))
    one_q = int(sum(v for k, v in ops.items() if k not in ("cx", "measure", "barrier", "rz")))  # rz is virtual
    active = {qc.find_bit(q).index for inst in qc.data if inst.operation.name not in ("barrier",) for q in inst.qubits}
    return {
        "two_qubit_gates": two_q,
        "one_qubit_gates": one_q,
        "depth": int(qc.depth(lambda inst: inst.operation.name not in ("barrier", "measure"))),
        "two_qubit_depth": int(qc.depth(lambda inst: inst.operation.num_qubits == 2)),
        "active_qubits": len(active),
        "measured": int(ops.get("measure", 0)),
    }


def estimated_success_probability(counts: dict, p2: float, p1: float | None = None, p_meas: float = 0.0) -> float:
    """Probability that no gate and no read-out fails: ``(1-p1)^n1 (1-p2)^n2 (1-pm)^nm``."""
    p1 = p2 / 10.0 if p1 is None else p1
    return float((1 - p1) ** counts["one_qubit_gates"] * (1 - p2) ** counts["two_qubit_gates"] * (1 - p_meas) ** counts["measured"])


# --------------------------------------------------------------------------- #
# Noisy simulation
# --------------------------------------------------------------------------- #
def noise_model(p2: float, p1: float | None = None, p_meas: float = 0.0, one_qubit_gates=("sx", "x")):
    """Depolarising noise: random non-identity Pauli with probability ``p2`` / ``p1``.

    ``rz`` is implemented virtually (a frame change) on IBM hardware and is
    therefore noiseless here.
    """
    from qiskit_aer.noise import NoiseModel, ReadoutError, depolarizing_error

    p1 = p2 / 10.0 if p1 is None else p1
    nm = NoiseModel()
    if p2 > 0:
        # Qiskit's parameter lambda mixes with the maximally mixed state, which
        # contains the identity: Pauli-error probability = lambda * (4^n - 1) / 4^n.
        nm.add_all_qubit_quantum_error(depolarizing_error(min(1.0, p2 * 16 / 15), 2), ["cx"])
    if p1 > 0:
        nm.add_all_qubit_quantum_error(depolarizing_error(min(1.0, p1 * 4 / 3), 1), list(one_qubit_gates))
    if p_meas > 0:
        nm.add_all_qubit_readout_error(ReadoutError([[1 - p_meas, p_meas], [p_meas, 1 - p_meas]]))
    return nm


def success_probability(
    compiled: QuantumCircuit,
    expected_key: str,
    p2: float,
    p1: float | None = None,
    p_meas: float = 0.0,
    shots: int = 2000,
    seed: int = 7,
    threads: int = 0,
) -> dict:
    """Aer (MPS) estimate of P[output == noiseless answer] and the mean bit error.

    ``threads=0`` lets Aer use every core; worker processes pass ``1``.
    """
    from qiskit_aer import AerSimulator

    nm = noise_model(p2, p1, p_meas) if (p2 > 0 or (p1 or 0) > 0 or p_meas > 0) else None
    sim = AerSimulator(method="matrix_product_state", noise_model=nm, seed_simulator=seed, max_parallel_threads=threads)
    counts = sim.run(compiled, shots=shots).result().get_counts()
    good = counts.get(expected_key, 0)
    n_bits = len(expected_key)
    ref = np.array([int(c) for c in expected_key])
    wrong_bits = 0
    for key, c in counts.items():
        k = key.replace(" ", "")
        wrong_bits += c * int(np.sum(np.array([int(ch) for ch in k]) != ref))
    p = good / shots
    stderr = float(np.sqrt(max(p * (1 - p), 1.0 / shots) / shots))
    return {"success": p, "stderr": stderr, "bit_error_rate": wrong_bits / (shots * n_bits), "shots": shots}


def threshold(p_values, success_values, target: float) -> float | None:
    """Two-qubit error rate where the success curve crosses ``target`` (log-linear interpolation)."""
    p = np.asarray(p_values, dtype=float)
    s = np.asarray(success_values, dtype=float)
    order = np.argsort(p)
    p, s = p[order], s[order]
    for i in range(len(p) - 1):
        if s[i] >= target >= s[i + 1] and s[i] != s[i + 1]:
            lp = np.log10(p[i]) + (target - s[i]) * (np.log10(p[i + 1]) - np.log10(p[i])) / (s[i + 1] - s[i])
            return float(10**lp)
    return None
