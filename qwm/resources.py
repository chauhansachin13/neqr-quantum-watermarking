"""
Quantum resource analysis (Sec. 4.9): qubit counts, gate counts and depth.

Two views are provided:

* :func:`reported_resources` reproduces the closed-form figures of the
  reference design (``9n-4`` CNOT-equivalents for an ``n``-bit RPA/RPS,
  ``6n+3`` for D4, ``16n-11`` for QE; 354 qubits for watermark generation
  and 400 for embedding and extraction with ``n = 8``, Table 21).
* :func:`measure_circuit` / :func:`measure_block_circuits` count the actual
  resources of the Qiskit circuits built by this package, after decomposing
  the modules into ``{X, CNOT, Toffoli, SWAP}`` and into ``{U, CNOT}``.
"""

from __future__ import annotations

import numpy as np
from qiskit import QuantumCircuit, transpile

from qwm.circuits import (
    WatermarkEmbeddingCircuit,
    WatermarkExtractionCircuit,
    WatermarkGenerationCircuit,
)


# --------------------------------------------------------------------------- #
# Closed-form figures from the reference design
# --------------------------------------------------------------------------- #
def rpa_gate_complexity(n: int) -> int:
    """RHA (5 CNOT) + (n-1) RFA (9 CNOT each) = ``9n - 4``."""
    return 9 * n - 4


def rps_gate_complexity(n: int) -> int:
    return 9 * n - 4


def d4_gate_complexity(n: int) -> int:
    """``2n + 1`` SWAP gates, 3 CNOTs each = ``6n + 3``."""
    return 6 * n + 3


def qe_gate_complexity(n: int) -> int:
    """``2n`` CNOTs + one ``n``-controlled NOT (``2(n-1)`` Toffolis + 1 CNOT) = ``16n - 11``."""
    return 16 * n - 11


def module_qubits(n: int) -> dict[str, int]:
    return {"RPA": 4 * n, "RPS": 4 * n, "D4": n + 2, "QE": 2 * n + 1}


def reported_resources(n: int = 8) -> dict:
    """Qubit budget of Sec. 4.9.3 / Table 21 for ``n``-bit registers."""
    q = module_qubits(n)
    generation = {"RPA": 10 * q["RPA"], "D4": q["D4"], "CNOT": 12 * 2}
    generation["total"] = sum(generation.values())
    embedding = {"RPA": 8 * q["RPA"], "QE": 8 * q["QE"], "Pauli-X": 8}
    embedding["total"] = sum(embedding.values())
    extraction = {"RPS": 8 * q["RPS"], "QE": 8 * q["QE"], "Pauli-X": 8}
    extraction["total"] = sum(extraction.values())
    return {
        "n": n,
        "module_qubits": q,
        "module_gate_complexity": {
            "RPA": rpa_gate_complexity(n),
            "RPS": rps_gate_complexity(n),
            "D4": d4_gate_complexity(n),
            "QE": qe_gate_complexity(n),
        },
        "watermark_generation": generation,
        "embedding": embedding,
        "extraction": extraction,
        "table21": [
            {"component": "RPA module", "operation": "Reversible addition", "data": 256, "ancilla": 64, "total": 320, "gates": "CNOT, Toffoli", "depth": "Moderate"},
            {"component": "D4 module", "operation": "Divide-by-4 operation", "data": 8, "ancilla": 2, "total": 10, "gates": "SWAP, CNOT", "depth": "Low"},
            {"component": "QE module", "operation": "Quantum equality comparison", "data": 132, "ancilla": 4, "total": 136, "gates": "CNOT, Toffoli, Pauli-X", "depth": "Moderate"},
            {"component": "Watermark generation circuit", "operation": "PPB + AA + XOR generation", "data": 288, "ancilla": 66, "total": 354, "gates": "RPA, D4, CNOT", "depth": "Moderate-to-High"},
            {"component": "Embedding circuit", "operation": "Reversible LSB embedding", "data": 320, "ancilla": 80, "total": 400, "gates": "RPA, QE, Pauli-X, CNOT", "depth": "High"},
            {"component": "Extraction circuit", "operation": "Reversible LSB extraction", "data": 320, "ancilla": 80, "total": 400, "gates": "RPS, QE, Pauli-X, CNOT", "depth": "High"},
        ],
    }


def frqi_preparation_ops(n: int) -> int:
    """FRQI preparation cost ``O(2**(4n))`` for a ``2**n x 2**n`` image."""
    return 2 ** (4 * n)


def neqr_preparation_ops(n: int, q: int = 8) -> int:
    """NEQR preparation cost ``O(q * n * 2**(2n))`` (Table 11)."""
    return q * n * 2 ** (2 * n)


def complexity_comparison(sizes=(4, 16, 256), q: int = 8) -> list[dict]:
    rows = []
    for side in sizes:
        n = int(np.log2(side))
        rows.append({"image": f"{side}x{side}", "n": n, "FRQI": frqi_preparation_ops(n), "NEQR": neqr_preparation_ops(n, q)})
    return rows


# --------------------------------------------------------------------------- #
# Measured figures from the constructed circuits
# --------------------------------------------------------------------------- #
REVERSIBLE_LEAVES = ("x", "cx", "ccx", "rccx", "swap")


def _is_leaf(name: str) -> bool:
    return name in REVERSIBLE_LEAVES or name.startswith("mcx") or name.startswith("cx_o") or name in ("c3x", "c4x")


def flatten_reversible(qc: QuantumCircuit) -> QuantumCircuit:
    """Expand composite modules down to ``{X, CNOT, Toffoli, SWAP, MCX}`` leaves."""
    out = QuantumCircuit(qc.num_qubits, name=qc.name)

    def visit(circ: QuantumCircuit, qmap: list[int]) -> None:
        for inst in circ.data:
            op = inst.operation
            idx = [qmap[circ.find_bit(q).index] for q in inst.qubits]
            if op.name in ("barrier", "id"):
                continue
            if _is_leaf(op.name) or op.definition is None:
                out.append(op, idx)
            else:
                visit(op.definition, idx)

    visit(qc, list(range(qc.num_qubits)))
    return out


def measure_circuit(qc: QuantumCircuit) -> dict:
    """Qubits, gate composition and depth of ``qc`` at two decomposition levels."""
    flat = flatten_reversible(qc)
    rev_ops = {}
    for inst in flat.data:
        op = inst.operation
        name = op.name
        n_ctrl = getattr(op, "num_ctrl_qubits", None)
        if name.startswith("mcx") and n_ctrl:
            name = f"mcx({n_ctrl})"
        elif name.startswith("cx_o"):
            name = "cx"
        rev_ops[name] = rev_ops.get(name, 0) + 1
    cnot_level = transpile(flat, basis_gates=["u", "cx"], optimization_level=0)
    cl_ops = {k: int(v) for k, v in cnot_level.count_ops().items()}
    ancilla = sum(len(reg) for reg in qc.qregs if reg.name.startswith(("anc", "aa", "ppb", "d4", "round")))
    return {
        "qubits": qc.num_qubits,
        "data_qubits": qc.num_qubits - ancilla,
        "ancilla_qubits": ancilla,
        "reversible_gates": rev_ops,
        "reversible_gate_total": int(sum(rev_ops.values())),
        "reversible_depth": flat.depth(),
        "cnot_count": cl_ops.get("cx", 0),
        "single_qubit_count": cl_ops.get("u", 0),
        "cnot_level_depth": cnot_level.depth(),
    }


def measure_block_circuits(block=((50, 60), (48, 32))) -> dict[str, dict]:
    """Measured resources of the generation / embedding / extraction circuits."""
    block = np.asarray(block)
    gen = WatermarkGenerationCircuit(block)
    wb = gen.run()["watermark"]
    emb = WatermarkEmbeddingCircuit(block, wb)
    wblock = emb.run()["watermarked_block"]
    ext = WatermarkExtractionCircuit(wblock, wb)
    return {
        "watermark_generation": measure_circuit(gen.circuit),
        "embedding": measure_circuit(emb.circuit),
        "extraction": measure_circuit(ext.circuit),
    }


def measure_modules(n: int = 8) -> dict[str, dict]:
    from qwm.gates import (
        DividingFour,
        QuantumEqual,
        ReverseParallelAdder,
        ReverseParallelSubtractor,
    )

    out = {
        "RPA": measure_circuit(ReverseParallelAdder(n).circuit),
        "RPS": measure_circuit(ReverseParallelSubtractor(n).circuit),
        "D4": measure_circuit(DividingFour(n).circuit),
        "QE": measure_circuit(QuantumEqual(n).circuit),
    }
    ancilla = {"RPA": 2 * n, "RPS": 2 * n, "D4": 2, "QE": 1}
    for name, res in out.items():
        res["ancilla_qubits"] = ancilla[name]
        res["data_qubits"] = res["qubits"] - ancilla[name]
    return out
