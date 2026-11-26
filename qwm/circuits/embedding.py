"""
Quantum circuit for watermark embedding into one ``2x2`` block (Fig. 13).

For every pixel ``|C_i>`` and LSB position ``k in {0, 1}``:

* an RHA (1-bit RPA) adds ``|C_i^{k+1}>`` and ``|Wb_{2i+k}>``; a CNOT merges
  sum and carry into the ``|RPA result>`` qubit;
* a CNOT with ``|C_i^{k+1}>`` produces ``|XOR result>``;
* a 1-qubit QE compares it with ``|C_i^k>``;
* a controlled Pauli-X flips the result when the QE reports equality;
* a SWAP incorporates the result into ``|C_i^k>`` (the old bit becomes
  garbage, keeping the circuit reversible).
"""

from __future__ import annotations

import numpy as np
from qiskit import QuantumCircuit, QuantumRegister

from qwm.gates.adder import reversible_half_adder
from qwm.gates.equal import QuantumEqual
from qwm.simulation import bits_to_int, run_basis
from qwm.watermark.embedding import embed_block
from qwm.watermark.generation import block_pixels


class WatermarkEmbeddingCircuit:
    def __init__(self, block, watermark_bits):
        self.block = np.asarray(block, dtype=np.int64)
        if self.block.shape != (2, 2):
            raise ValueError("block must be 2x2")
        self.pixels = block_pixels(self.block)
        self.watermark = [int(b) & 1 for b in watermark_bits]
        if len(self.watermark) != 8:
            raise ValueError("eight watermark bits are required")
        self.circuit = self._build()

    def _build(self) -> QuantumCircuit:
        C = [QuantumRegister(8, f"c{i}") for i in range(4)]
        W = QuantumRegister(8, "wb")
        E = [QuantumRegister(6, f"anc{i}") for i in range(4)]
        qc = QuantumCircuit(*C, W, *E, name="WatermarkEmbedding")

        for i, v in enumerate(self.pixels):
            for k in range(8):
                if (v >> k) & 1:
                    qc.x(C[i][k])
        for k, b in enumerate(self.watermark):
            if b:
                qc.x(W[k])
        qc.barrier(label="inputs")

        rha = reversible_half_adder().to_gate(label="RPA")
        qe1 = QuantumEqual(1).gate
        for i in range(4):
            for k in range(2):
                a, c, w = C[i][k + 1], C[i][k], W[2 * i + k]
                ycopy, carry, eq = E[i][3 * k], E[i][3 * k + 1], E[i][3 * k + 2]
                qc.append(rha, [a, ycopy, w, carry])  # w <- a xor w, carry <- a.w
                qc.cx(carry, w)  # |RPA result> = sum xor carry
                qc.cx(a, w)  # |XOR result>
                qc.append(qe1, [w, c, eq])  # eq <- (XOR result == C^k)
                qc.cx(eq, w)  # Pauli-X when equal
                qc.swap(w, c)  # incorporate into C^k
            qc.barrier(label=f"pixel {i}")

        self.pixel_qubits = [[qc.find_bit(q).index for q in reg] for reg in C]
        return qc

    def run(self) -> dict:
        bits = run_basis(self.circuit)
        pixels = [bits_to_int(bits[q] for q in reg) for reg in self.pixel_qubits]
        return {"watermarked_pixels": pixels, "watermarked_block": np.asarray(pixels, dtype=np.uint8).reshape(2, 2)}

    def expected(self) -> np.ndarray:
        return embed_block(self.block, self.watermark, mode="paper")

    def verify_unitary_inverse(self) -> dict:
        """Verify Sec. 3.5 / Eq. (12)-(16): ``U^dagger |W> = |C> (x) |Wb>``."""
        roundtrip = self.circuit.compose(self.circuit.inverse())
        # Note: inputs were prepended via X gates inside self.circuit, so the gate
        # body U followed by U^dagger cancels back to the exact input state;
        # stripping input prep by running U_body then U_body^dagger returns |C> and |Wb>.
        prep = QuantumCircuit(self.circuit.num_qubits)
        for i, v in enumerate(self.pixels):
            for k in range(8):
                if (v >> k) & 1:
                    prep.x(i * 8 + k)
        for k, b in enumerate(self.watermark):
            if b:
                prep.x(32 + k)
        body = QuantumCircuit(*self.circuit.qregs)
        past_inputs = False
        for inst in self.circuit.data:
            if inst.operation.name == "barrier" and inst.operation.label == "inputs":
                past_inputs = True
                continue
            if past_inputs:
                body.append(inst.operation, inst.qubits, inst.clbits)
        full = prep.compose(body).compose(body.inverse())
        bits = run_basis(full)
        restored_pixels = [bits_to_int(bits[q] for q in reg) for reg in self.pixel_qubits]
        restored_wb = [int(bits[32 + k]) for k in range(8)]
        restored_anc = all(bits[q] == 0 for q in range(40, self.circuit.num_qubits))
        _ = roundtrip
        return {
            "pixels_restored": restored_pixels == self.pixels,
            "watermark_restored": restored_wb == self.watermark,
            "ancillas_clean": restored_anc,
            "exact_unitary_inverse": restored_pixels == self.pixels and restored_wb == self.watermark and restored_anc,
        }
