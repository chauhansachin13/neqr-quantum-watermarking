"""
Reverse Parallel Adder (RPA) - reversible ripple-carry addition.

The RPA (Sec. 2.2 / Fig. 1 of the reference design) is composed of one
Reversible Half Adder (RHA) for the least significant bit followed by
``n-1`` Reversible Full Adders (RFA).  Every stage keeps its inputs
recoverable, so the whole adder is a permutation of the computational basis
and can be undone by running it backwards.

Wire semantics (little-endian, index 0 = LSB)::

    RHA : |x>|0>|y>|0>      ->  |x>|y>|x xor y>|x and y>
    RFA : |z>|x>|0>|y>|0>   ->  |z>|x>|y>|x xor y xor z>|carry(x, y, z)>

The ``n``-qubit RPA uses ``4n`` qubits: ``n`` for ``x``, ``n`` ancillas that
receive a copy of ``y``, ``n`` for ``y`` (overwritten with the sum bits) and
``n`` ancillas that receive the carries (the last one is the carry-out).
"""

from __future__ import annotations

from dataclasses import dataclass

from qiskit import QuantumCircuit
from qiskit.circuit import Gate


def reversible_half_adder() -> QuantumCircuit:
    """RHA on 4 qubits ``(x, a, y, b)``: ``a <- y``, ``y <- x^y``, ``b <- x&y``."""
    qc = QuantumCircuit(4, name="RHA")
    x, a, y, b = 0, 1, 2, 3
    qc.cx(y, a)  # copy y
    qc.ccx(x, y, b)  # carry = x . y
    qc.cx(x, y)  # sum = x xor y
    return qc


def reversible_full_adder() -> QuantumCircuit:
    """RFA on 5 qubits ``(z, x, a, y, b)`` with carry-in ``z``.

    ``a <- y``, ``y <- x^y^z``, ``b <- (x&y) ^ ((x^y)&z)``.
    """
    qc = QuantumCircuit(5, name="RFA")
    z, x, a, y, b = 0, 1, 2, 3, 4
    qc.cx(y, a)  # copy y
    qc.ccx(x, y, b)  # partial carry x . y
    qc.cx(x, y)  # y = x xor y
    qc.ccx(y, z, b)  # carry-out = x.y xor (x xor y).z
    qc.cx(z, y)  # sum = x xor y xor z
    return qc


@dataclass(frozen=True)
class RPALayout:
    """Qubit bookkeeping for an ``n``-bit RPA (indices are little-endian)."""

    n: int

    @property
    def x(self) -> list[int]:
        return list(range(0, self.n))

    @property
    def y_copy(self) -> list[int]:
        """Ancilla wires that hold a copy of ``y`` after the adder ran."""
        return list(range(self.n, 2 * self.n))

    @property
    def y(self) -> list[int]:
        """Input wires of ``y``; they hold the sum bits ``r_0..r_{n-1}`` afterwards."""
        return list(range(2 * self.n, 3 * self.n))

    @property
    def sum(self) -> list[int]:
        return self.y

    @property
    def carry(self) -> list[int]:
        """Ancilla wires that hold the carries ``z_0..z_{n-1}``; ``z_{n-1}`` is the carry-out."""
        return list(range(3 * self.n, 4 * self.n))

    @property
    def carry_out(self) -> int:
        return 4 * self.n - 1

    @property
    def num_qubits(self) -> int:
        return 4 * self.n


class ReverseParallelAdder:
    """``n``-bit RPA built from one RHA and ``n-1`` RFAs.

    >>> rpa = ReverseParallelAdder(4)
    >>> rpa.add(5, 9)
    (14, 0)
    """

    def __init__(self, n: int):
        if n < 1:
            raise ValueError("n must be >= 1")
        self.n = n
        self.layout = RPALayout(n)
        self.circuit = self._build()

    def _build(self) -> QuantumCircuit:
        n, lay = self.n, self.layout
        qc = QuantumCircuit(4 * n, name=f"RPA{n}")
        rha = reversible_half_adder().to_gate(label="RHA")
        rfa = reversible_full_adder().to_gate(label="RFA")
        qc.append(rha, [lay.x[0], lay.y_copy[0], lay.y[0], lay.carry[0]])
        for i in range(1, n):
            qc.append(rfa, [lay.carry[i - 1], lay.x[i], lay.y_copy[i], lay.y[i], lay.carry[i]])
        return qc

    @property
    def gate(self) -> Gate:
        return self.circuit.to_gate(label=f"RPA{self.n}")

    # -- classical reference -------------------------------------------------
    @staticmethod
    def add(x: int, y: int, n: int | None = None) -> tuple[int, int]:
        """Classical reference: returns ``(sum mod 2**n, carry_out)``."""
        if n is None:
            n = max(x.bit_length(), y.bit_length(), 1)
        s = x + y
        return s & ((1 << n) - 1), (s >> n) & 1

    @staticmethod
    def carries(x: int, y: int, n: int) -> list[int]:
        """Classical reference for the carry register ``z_0..z_{n-1}``."""
        out, c = [], 0
        for i in range(n):
            xi, yi = (x >> i) & 1, (y >> i) & 1
            c = (xi & yi) | ((xi ^ yi) & c)
            out.append(c)
        return out

    def simulate(self, x: int, y: int) -> dict[str, int | list[int]]:
        """Run the circuit on basis inputs and decode the output registers."""
        from qwm.simulation import bits_to_int, run_basis

        lay = self.layout
        init = {q: (x >> i) & 1 for i, q in enumerate(lay.x)}
        init.update({q: (y >> i) & 1 for i, q in enumerate(lay.y)})
        bits = run_basis(self.circuit, init)
        return {
            "x": bits_to_int(bits[q] for q in lay.x),
            "y_copy": bits_to_int(bits[q] for q in lay.y_copy),
            "sum": bits_to_int(bits[q] for q in lay.sum),
            "carries": [bits[q] for q in lay.carry],
            "carry_out": bits[lay.carry_out],
        }


def rpa_gate(n: int) -> Gate:
    """Convenience: the ``n``-bit RPA as a Qiskit gate."""
    return ReverseParallelAdder(n).gate
