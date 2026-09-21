"""
Dividing-4 (D4) module - integer division by four with SWAP gates.

The D4 model (Sec. 2.3 / Fig. 2) shifts an ``n``-qubit register two
positions towards the least significant end using only SWAP gates.  Two
ancilla qubits initialised to ``|0>`` supply the two new most significant
bits, and the two discarded least significant bits end up on the ancilla
wires as garbage - nothing is erased, so the operation stays reversible.

Qubit order: ``m_0 .. m_{n-1}, anc_0, anc_1``.  Afterwards qubits
``0 .. n-1`` hold ``floor(M / 4)`` and qubits ``n, n+1`` hold ``m_0, m_1``.
"""

from __future__ import annotations

from qiskit import QuantumCircuit
from qiskit.circuit import Gate


class DividingFour:
    def __init__(self, n: int):
        if n < 1:
            raise ValueError("n must be >= 1")
        self.n = n
        self.circuit = self._build()

    def _build(self) -> QuantumCircuit:
        n = self.n
        qc = QuantumCircuit(n + 2, name=f"D4_{n}")
        for i in range(n):
            qc.swap(i, i + 2)
        return qc

    @property
    def gate(self) -> Gate:
        return self.circuit.to_gate(label=f"D4({self.n})")

    @property
    def value_qubits(self) -> list[int]:
        return list(range(self.n))

    @property
    def garbage_qubits(self) -> list[int]:
        return [self.n, self.n + 1]

    @property
    def num_qubits(self) -> int:
        return self.n + 2

    @staticmethod
    def divide(m: int) -> int:
        return m >> 2

    def simulate(self, m: int) -> int:
        from qwm.simulation import bits_to_int, run_basis

        init = {i: (m >> i) & 1 for i in range(self.n)}
        bits = run_basis(self.circuit, init)
        return bits_to_int(bits[: self.n])


def d4_gate(n: int) -> Gate:
    return DividingFour(n).gate
