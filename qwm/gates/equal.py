"""
Quantum Equal (QE) module - reversible equality comparator.

Given two ``n``-qubit registers ``|I>`` and ``|J>`` and one ancilla ``|0>``,
QE (Sec. 2.4 / Fig. 3) sets the ancilla to ``|1>`` iff ``I == J``:

1. ``CNOT(i_k -> j_k)`` for every ``k`` (``j_k`` becomes ``i_k xor j_k``);
2. an ``n``-controlled NOT on the ancilla with all controls on ``|0>``;
3. the CNOTs of step 1 again to restore ``|J>``.

Qubit order: ``i_0..i_{n-1}, j_0..j_{n-1}, x``.
"""

from __future__ import annotations

from qiskit import QuantumCircuit
from qiskit.circuit import Gate
from qiskit.circuit.library import MCXGate


class QuantumEqual:
    def __init__(self, n: int):
        if n < 1:
            raise ValueError("n must be >= 1")
        self.n = n
        self.circuit = self._build()

    def _build(self) -> QuantumCircuit:
        n = self.n
        qc = QuantumCircuit(2 * n + 1, name=f"QE{n}")
        i_reg, j_reg, x = list(range(n)), list(range(n, 2 * n)), 2 * n
        for a, b in zip(i_reg, j_reg, strict=True):
            qc.cx(a, b)
        qc.append(MCXGate(n, ctrl_state=0), j_reg + [x])
        for a, b in zip(i_reg, j_reg, strict=True):
            qc.cx(a, b)
        return qc

    @property
    def gate(self) -> Gate:
        return self.circuit.to_gate(label=f"QE{self.n}")

    @property
    def i_qubits(self) -> list[int]:
        return list(range(self.n))

    @property
    def j_qubits(self) -> list[int]:
        return list(range(self.n, 2 * self.n))

    @property
    def result_qubit(self) -> int:
        return 2 * self.n

    @property
    def num_qubits(self) -> int:
        return 2 * self.n + 1

    @staticmethod
    def equal(i: int, j: int) -> int:
        return int(i == j)

    def simulate(self, i: int, j: int) -> int:
        from qwm.simulation import run_basis

        init = {q: (i >> k) & 1 for k, q in enumerate(self.i_qubits)}
        init.update({q: (j >> k) & 1 for k, q in enumerate(self.j_qubits)})
        return run_basis(self.circuit, init)[self.result_qubit]


def qe_gate(n: int) -> Gate:
    return QuantumEqual(n).gate
