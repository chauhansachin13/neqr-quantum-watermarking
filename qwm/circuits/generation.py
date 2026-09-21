"""
Quantum circuit for watermark qubit generation of one ``2x2`` block (Fig. 11).

Step 1 - PPB: one 4-bit RPA per pixel adds the low and high nibble; CNOT
chains reduce the carry and sum registers to parities and a final CNOT
combines them.
Step 2 - AA: three RPAs (8, 8 and 9 bits) sum the four pixels, a fourth RPA
adds the rounding constant ``|2>`` and the D4 module divides by four.
Step 3 - XOR: eight CNOTs controlled by the PPB qubits act on the AA qubits,
which then hold ``Wb_0 .. Wb_7``.
"""

from __future__ import annotations

import numpy as np
from qiskit import QuantumCircuit, QuantumRegister

from qwm.gates.adder import ReverseParallelAdder
from qwm.gates.divider import DividingFour
from qwm.simulation import run_basis
from qwm.watermark.generation import block_pixels, block_watermark_bits


class WatermarkGenerationCircuit:
    """Build (and optionally simulate) the generation circuit for ``block``."""

    def __init__(self, block):
        self.block = np.asarray(block, dtype=np.int64)
        if self.block.shape != (2, 2):
            raise ValueError("block must be 2x2")
        self.pixels = block_pixels(self.block)
        self.circuit = self._build()

    def _build(self) -> QuantumCircuit:
        C = [QuantumRegister(8, f"c{i}") for i in range(4)]
        P = [QuantumRegister(8, f"ppb{i}") for i in range(4)]
        A1, A2, A3 = QuantumRegister(16, "aa1"), QuantumRegister(16, "aa2"), QuantumRegister(18, "aa3")
        K, A4, D = QuantumRegister(10, "round"), QuantumRegister(20, "aa4"), QuantumRegister(2, "d4")
        qc = QuantumCircuit(*C, *P, A1, A2, A3, K, A4, D, name="WatermarkGeneration")

        # -- input preparation (basis-state pixel registers) -----------------
        for i, v in enumerate(self.pixels):
            for k in range(8):
                if (v >> k) & 1:
                    qc.x(C[i][k])
        qc.barrier(label="inputs")

        # -- Step 1: pixel position bits -------------------------------------
        rpa4 = ReverseParallelAdder(4).gate
        ppb = []
        for i in range(4):
            low, high = [C[i][k] for k in range(4)], [C[i][k] for k in range(4, 8)]
            copy, carry = [P[i][k] for k in range(4)], [P[i][k] for k in range(4, 8)]
            qc.append(rpa4, low + copy + high + carry)
            for k in range(3):  # CNOT chain: parity of the carry register
                qc.cx(carry[k], carry[3])
            for k in range(3):  # CNOT chain: parity of the sum register
                qc.cx(high[k], high[3])
            qc.cx(carry[3], high[3])  # PPB_{i,2} = parity(sum) xor parity(carry)
            ppb.append((carry[3], high[3]))
        qc.barrier(label="PPB")
        # after the RPA the high nibble lives on the copy ancillas
        value = [[C[i][k] for k in range(4)] + [P[i][k] for k in range(4)] for i in range(4)]

        # -- Step 2: arithmetic average --------------------------------------
        rpa8, rpa9, rpa10 = (ReverseParallelAdder(n).gate for n in (8, 9, 10))
        qc.append(rpa8, value[0] + list(A1[0:8]) + value[1] + list(A1[8:16]))
        s1 = value[1] + [A1[15]]
        qc.append(rpa8, value[2] + list(A2[0:8]) + value[3] + list(A2[8:16]))
        s2 = value[3] + [A2[15]]
        qc.append(rpa9, s1 + list(A3[0:9]) + s2 + list(A3[9:18]))
        total = s2 + [A3[17]]  # 10-bit block sum
        qc.x(K[1])  # rounding constant |2>
        qc.append(rpa10, list(K) + list(A4[0:10]) + total + list(A4[10:20]))
        qc.append(DividingFour(10).gate, total + list(D))
        aa = total[:8]
        qc.barrier(label="AA")

        # -- Step 3: XOR PPB with AA -----------------------------------------
        for k in range(8):
            qc.cx(ppb[k // 2][k % 2], aa[k])

        self.pixel_qubits = [[qc.find_bit(q).index for q in reg] for reg in C]
        self.ppb_qubits = [(qc.find_bit(a).index, qc.find_bit(b).index) for a, b in ppb]
        self.aa_qubits = [qc.find_bit(q).index for q in total]
        self.output_qubits = [qc.find_bit(q).index for q in aa]
        return qc

    def run(self) -> dict:
        """Simulate exactly and decode PPB, AA and the watermark qubits."""
        bits = run_basis(self.circuit)
        ppb = [(bits[a], bits[b]) for a, b in self.ppb_qubits]
        watermark = [bits[q] for q in self.output_qubits]
        # AA qubits were XOR-ed with the PPB bits; undo to report the average
        aa_bits = [watermark[k] ^ ppb[k // 2][k % 2] for k in range(8)]
        aa = sum(b << k for k, b in enumerate(aa_bits))
        return {"ppb": ppb, "aa": aa, "watermark": watermark}

    def expected(self) -> list[int]:
        return block_watermark_bits(self.block)
