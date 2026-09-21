"""
Simulation back-ends for the reversible circuits used in this project.

Every arithmetic/logic module in the framework (RPA, RPS, D4, QE, the
watermark generation, embedding and extraction circuits) is built from
*permutation* gates only: X, CNOT, Toffoli, multi-controlled X and SWAP.
Such circuits map computational-basis states to computational-basis states,
so they can be simulated exactly - and for hundreds of qubits - by tracking a
single classical bit per qubit.  :class:`BasisStateSimulator` does exactly
that and is the workhorse used by the tests and by the full-image pipeline.

For the small superposition circuits (NEQR encoding of a 2x2 block, 10
qubits) the module also exposes thin wrappers around Qiskit's
``Statevector`` and the Aer simulator.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

import numpy as np
from qiskit import QuantumCircuit
from qiskit.quantum_info import Statevector

# Gate names that the basis-state simulator understands natively.  Any other
# operation must expose a ``definition`` composed (recursively) of these.
_X_LIKE = {"x", "cx", "ccx", "mcx", "c3x", "c4x", "mcx_gray", "mcx_recursive", "mcx_vchain"}
_IGNORED = {"barrier", "id", "delay", "measure", "reset"}


class UnsupportedGateError(ValueError):
    """Raised when a circuit contains a gate that is not a permutation gate."""


class BasisStateSimulator:
    """Exact classical simulator for permutation (reversible) circuits.

    Example
    -------
    >>> from qiskit import QuantumCircuit
    >>> qc = QuantumCircuit(2); qc.x(0); qc.cx(0, 1)
    >>> BasisStateSimulator().run(qc)
    [1, 1]
    """

    def run(
        self,
        circuit: QuantumCircuit,
        initial: Sequence[int] | Mapping[int, int] | int | None = None,
    ) -> list[int]:
        """Propagate a basis state through ``circuit``.

        Parameters
        ----------
        circuit:
            A Qiskit circuit built from permutation gates.
        initial:
            Initial bit values.  Either a sequence with one entry per qubit
            (qubit ``i`` -> ``initial[i]``), a mapping ``{qubit_index: bit}``
            (unspecified qubits start in ``0``), an integer whose binary
            expansion is read little-endian (bit ``i`` -> qubit ``i``), or
            ``None`` for the all-zero state.

        Returns
        -------
        list[int]
            Final bit value of every qubit, indexed by qubit position.
        """
        n = circuit.num_qubits
        bits = self._initial_bits(n, initial)
        self._apply(circuit, bits, list(range(n)))
        return bits

    # ------------------------------------------------------------------ #
    @staticmethod
    def _initial_bits(n: int, initial) -> list[int]:
        bits = [0] * n
        if initial is None:
            return bits
        if isinstance(initial, int):
            for i in range(n):
                bits[i] = (initial >> i) & 1
            return bits
        if isinstance(initial, Mapping):
            for k, v in initial.items():
                bits[int(k)] = int(v) & 1
            return bits
        initial = list(initial)
        if len(initial) != n:
            raise ValueError(f"initial state has {len(initial)} bits, circuit has {n} qubits")
        return [int(b) & 1 for b in initial]

    def _apply(self, circuit: QuantumCircuit, bits: list[int], qmap: list[int]) -> None:
        """Apply ``circuit`` in place; ``qmap[i]`` is the global index of local qubit ``i``."""
        for inst in circuit.data:
            op = inst.operation
            name = op.name
            idx = [qmap[circuit.find_bit(q).index] for q in inst.qubits]
            if name in _IGNORED:
                continue
            if name == "swap":
                a, b = idx
                bits[a], bits[b] = bits[b], bits[a]
                continue
            if name in _X_LIKE or name.startswith("mcx"):
                n_ctrl = getattr(op, "num_ctrl_qubits", 0) or 0
                ctrl_state = getattr(op, "ctrl_state", None)
                controls, target = idx[:n_ctrl], idx[-1]
                if ctrl_state is None:
                    ctrl_state = (1 << n_ctrl) - 1
                active = all(bits[c] == ((ctrl_state >> k) & 1) for k, c in enumerate(controls))
                if active:
                    bits[target] ^= 1
                continue
            definition = getattr(op, "definition", None)
            if definition is None:
                raise UnsupportedGateError(f"gate '{name}' is not a permutation gate")
            self._apply(definition, bits, idx)


def run_basis(circuit: QuantumCircuit, initial=None) -> list[int]:
    """Convenience wrapper around :meth:`BasisStateSimulator.run`."""
    return BasisStateSimulator().run(circuit, initial)


def bits_to_int(bits: Iterable[int]) -> int:
    """Little-endian bit list -> integer (``bits[0]`` is the LSB)."""
    value = 0
    for i, b in enumerate(bits):
        value |= (int(b) & 1) << i
    return value


def int_to_bits(value: int, n: int) -> list[int]:
    """Integer -> little-endian bit list of length ``n``."""
    return [(int(value) >> i) & 1 for i in range(n)]


def statevector(circuit: QuantumCircuit) -> Statevector:
    """Exact statevector of a (small) circuit."""
    return Statevector(circuit.remove_final_measurements(inplace=False))


def probabilities(circuit: QuantumCircuit) -> np.ndarray:
    """Measurement probabilities of every computational basis state."""
    return statevector(circuit).probabilities()


_AER_NATIVE = {
    "x", "y", "z", "h", "s", "sdg", "t", "tdg", "sx", "sxdg", "p", "u", "u1", "u2", "u3",
    "rx", "ry", "rz", "cx", "cy", "cz", "ch", "cp", "ccx", "cswap", "swap", "mcx",
    "measure", "barrier", "id", "reset", "delay",
}


def flatten_custom_gates(circuit: QuantumCircuit) -> QuantumCircuit:
    """Decompose composite (user-defined) gates until only native gates remain."""
    qc = circuit
    while True:
        custom = {inst.operation.name for inst in qc.data if inst.operation.name not in _AER_NATIVE and getattr(inst.operation, "definition", None) is not None}
        if not custom:
            return qc
        qc = qc.decompose(gates_to_decompose=sorted(custom))


def aer_counts(circuit: QuantumCircuit, shots: int = 4096, method: str = "automatic", seed: int | None = None) -> dict[str, int]:
    """Run ``circuit`` on the Aer simulator and return measurement counts.

    The circuit is measured on all qubits if it contains no measurements.
    ``method`` may be e.g. ``"statevector"`` or ``"matrix_product_state"``
    (the latter simulates permutation circuits on many qubits cheaply).
    Composite gates are flattened first so that wide circuits (more qubits
    than the backend's default target) can be executed without transpiling.
    """
    from qiskit_aer import AerSimulator

    qc = circuit.copy()
    if qc.num_clbits == 0:
        qc.measure_all()
    qc = flatten_custom_gates(qc)
    backend = AerSimulator(method=method, seed_simulator=seed)
    result = backend.run(qc, shots=shots).result()
    return dict(result.get_counts())
