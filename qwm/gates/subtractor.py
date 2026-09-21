"""
Reverse Parallel Subtractor (RPS) - reversible ripple-borrow subtraction.

Mirrors :mod:`qwm.gates.adder`: a Reversible Half Subtractor (RHS) for the
least significant bit and ``n-1`` Reversible Full Subtractors (RFS)
(Sec. 2.5 / Fig. 4 of the reference design).

Wire semantics::

    RHS : |x>|0>|y>|0>     ->  |x>|y>|x xor y>|not(x) and y>
    RFS : |z>|x>|0>|y>|0>  ->  |z>|x>|y>|x xor y xor z>|borrow(x, y, z)>

where ``z`` is the borrow-in and ``borrow = not(x xor y).z xor not(x).y``.
"""

from __future__ import annotations

from qiskit import QuantumCircuit
from qiskit.circuit import Gate

from qwm.gates.adder import RPALayout


def reversible_half_subtractor() -> QuantumCircuit:
    """RHS on 4 qubits ``(x, a, y, b)``: ``a <- y``, ``y <- x^y``, ``b <- ~x&y``."""
    qc = QuantumCircuit(4, name="RHS")
    x, a, y, b = 0, 1, 2, 3
    qc.cx(y, a)  # copy y
    qc.x(x)
    qc.ccx(x, y, b)  # borrow = not(x) . y
    qc.x(x)
    qc.cx(x, y)  # difference = x xor y
    return qc


def reversible_full_subtractor() -> QuantumCircuit:
    """RFS on 5 qubits ``(z, x, a, y, b)`` with borrow-in ``z``."""
    qc = QuantumCircuit(5, name="RFS")
    z, x, a, y, b = 0, 1, 2, 3, 4
    qc.cx(y, a)  # copy y
    qc.x(x)
    qc.ccx(x, y, b)  # not(x) . y
    qc.x(x)
    qc.cx(x, y)  # y = x xor y
    qc.x(y)
    qc.ccx(y, z, b)  # borrow-out ^= not(x xor y) . z
    qc.x(y)
    qc.cx(z, y)  # difference = x xor y xor z
    return qc


class ReverseParallelSubtractor:
    """``n``-bit RPS computing ``x - y`` (mod ``2**n``) with a borrow chain.

    Uses the same :class:`~qwm.gates.adder.RPALayout` as the adder; after the
    circuit ran the ``y`` wires hold the difference bits and the ``carry``
    wires hold the borrows (the last one is the borrow-out, i.e. ``x < y``).
    """

    def __init__(self, n: int):
        if n < 1:
            raise ValueError("n must be >= 1")
        self.n = n
        self.layout = RPALayout(n)
        self.circuit = self._build()

    def _build(self) -> QuantumCircuit:
        n, lay = self.n, self.layout
        qc = QuantumCircuit(4 * n, name=f"RPS{n}")
        rhs = reversible_half_subtractor().to_gate(label="RHS")
        rfs = reversible_full_subtractor().to_gate(label="RFS")
        qc.append(rhs, [lay.x[0], lay.y_copy[0], lay.y[0], lay.carry[0]])
        for i in range(1, n):
            qc.append(rfs, [lay.carry[i - 1], lay.x[i], lay.y_copy[i], lay.y[i], lay.carry[i]])
        return qc

    @property
    def gate(self) -> Gate:
        return self.circuit.to_gate(label=f"RPS{self.n}")

    @staticmethod
    def subtract(x: int, y: int, n: int) -> tuple[int, int]:
        """Classical reference: ``(x - y mod 2**n, borrow_out)``."""
        return (x - y) & ((1 << n) - 1), int(x < y)

    def simulate(self, x: int, y: int) -> dict[str, int | list[int]]:
        from qwm.simulation import bits_to_int, run_basis

        lay = self.layout
        init = {q: (x >> i) & 1 for i, q in enumerate(lay.x)}
        init.update({q: (y >> i) & 1 for i, q in enumerate(lay.y)})
        bits = run_basis(self.circuit, init)
        return {
            "x": bits_to_int(bits[q] for q in lay.x),
            "y_copy": bits_to_int(bits[q] for q in lay.y_copy),
            "difference": bits_to_int(bits[q] for q in lay.sum),
            "borrows": [bits[q] for q in lay.carry],
            "borrow_out": bits[lay.carry_out],
        }


def rps_gate(n: int) -> Gate:
    return ReverseParallelSubtractor(n).gate
