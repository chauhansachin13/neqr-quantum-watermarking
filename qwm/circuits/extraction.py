"""
Quantum circuit for watermark extraction from one ``2x2`` block (Fig. 14).

For every watermarked pixel ``|W_i>`` and LSB position ``k in {0, 1}``:

* two CNOTs compute ``|XOR result> = |W_i^{k+1} xor W_i^k>``;
* an RHS (1-bit RPS) subtracts ``|W_i^{k+1}>`` from it, giving ``|RPS result>``
  (the embedded bit);
* a copy of the raw bit is kept;
* if a reference watermark is supplied, a 1-qubit QE compares the RPS result
  with ``|Wb_{2i+k}>`` and a Pauli-X (controlled on *inequality*) corrects it.
"""

from __future__ import annotations

import numpy as np
from qiskit import QuantumCircuit, QuantumRegister
from qiskit.circuit.library import MCXGate

from qwm.gates.equal import QuantumEqual
from qwm.gates.subtractor import reversible_half_subtractor
from qwm.simulation import run_basis
from qwm.watermark.extraction import extract_block
from qwm.watermark.generation import block_pixels


class WatermarkExtractionCircuit:
    def __init__(self, block, reference_bits=None):
        self.block = np.asarray(block, dtype=np.int64)
        if self.block.shape != (2, 2):
            raise ValueError("block must be 2x2")
        self.pixels = block_pixels(self.block)
        self.reference = None if reference_bits is None else [int(b) & 1 for b in reference_bits]
        if self.reference is not None and len(self.reference) != 8:
            raise ValueError("eight reference bits are required")
        self.circuit = self._build()

    def _build(self) -> QuantumCircuit:
        Wp = [QuantumRegister(8, f"w{i}") for i in range(4)]
        E = [QuantumRegister(12, f"anc{i}") for i in range(4)]
        regs = [*Wp, *E]
        R = None
        if self.reference is not None:
            R = QuantumRegister(8, "ref")
            regs.append(R)
        qc = QuantumCircuit(*regs, name="WatermarkExtraction")

        for i, v in enumerate(self.pixels):
            for k in range(8):
                if (v >> k) & 1:
                    qc.x(Wp[i][k])
        if R is not None:
            for k, b in enumerate(self.reference):
                if b:
                    qc.x(R[k])
        qc.barrier(label="inputs")

        rhs = reversible_half_subtractor().to_gate(label="RPS")
        qe1 = QuantumEqual(1).gate
        flip_if_different = MCXGate(1, ctrl_state=0)
        raw_qubits, out_qubits = [], []
        for i in range(4):
            for k in range(2):
                hi, lo = Wp[i][k + 1], Wp[i][k]
                t, u, v, b, raw, eq = (E[i][6 * k + j] for j in range(6))
                qc.cx(hi, t)
                qc.cx(lo, t)  # |XOR result>
                qc.cx(hi, u)  # RPS subtrahend
                qc.append(rhs, [t, v, u, b])  # u <- t - u = |RPS result>
                qc.cx(u, raw)  # keep the raw bit
                if R is not None:
                    qc.append(qe1, [u, R[2 * i + k], eq])
                    qc.append(flip_if_different, [eq, u])  # Pauli-X when not similar
                raw_qubits.append(qc.find_bit(raw).index)
                out_qubits.append(qc.find_bit(u).index)
            qc.barrier(label=f"pixel {i}")

        self.raw_qubits = raw_qubits
        self.output_qubits = out_qubits
        return qc

    def run(self) -> dict:
        bits = run_basis(self.circuit)
        return {
            "raw_bits": [bits[q] for q in self.raw_qubits],
            "extracted_bits": [bits[q] for q in self.output_qubits],
        }

    def expected(self) -> tuple[list[int], list[int]]:
        return extract_block(self.block, self.reference)
