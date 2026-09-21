import itertools

import pytest

from qwm.gates import (
    DividingFour,
    QuantumEqual,
    ReverseParallelAdder,
    ReverseParallelSubtractor,
    reversible_full_adder,
    reversible_full_subtractor,
    reversible_half_adder,
    reversible_half_subtractor,
)
from qwm.simulation import BasisStateSimulator, run_basis


def test_half_adder_truth_table():
    qc = reversible_half_adder()
    for x, y in itertools.product((0, 1), repeat=2):
        out = run_basis(qc, {0: x, 2: y})
        assert out == [x, y, x ^ y, x & y]


def test_full_adder_truth_table():
    qc = reversible_full_adder()
    for z, x, y in itertools.product((0, 1), repeat=3):
        out = run_basis(qc, {0: z, 1: x, 3: y})
        carry = (x & y) | ((x ^ y) & z)
        assert out == [z, x, y, x ^ y ^ z, carry]


def test_half_subtractor_truth_table():
    qc = reversible_half_subtractor()
    for x, y in itertools.product((0, 1), repeat=2):
        out = run_basis(qc, {0: x, 2: y})
        assert out == [x, y, x ^ y, (1 - x) & y]


def test_full_subtractor_truth_table():
    qc = reversible_full_subtractor()
    for z, x, y in itertools.product((0, 1), repeat=3):
        out = run_basis(qc, {0: z, 1: x, 3: y})
        borrow = ((1 - (x ^ y)) & z) ^ ((1 - x) & y)
        assert out == [z, x, y, x ^ y ^ z, borrow]


@pytest.mark.parametrize("n", [1, 2, 3, 4])
def test_rpa_exhaustive(n):
    rpa = ReverseParallelAdder(n)
    assert rpa.circuit.num_qubits == 4 * n
    for x, y in itertools.product(range(2**n), repeat=2):
        r = rpa.simulate(x, y)
        s, c = ReverseParallelAdder.add(x, y, n)
        assert (r["sum"], r["carry_out"], r["x"], r["y_copy"]) == (s, c, x, y)
        assert r["carries"] == ReverseParallelAdder.carries(x, y, n)


def test_rpa_8bit_examples():
    rpa = ReverseParallelAdder(8)
    assert rpa.simulate(50, 60)["sum"] == 110
    r = rpa.simulate(200, 100)
    assert r["sum"] == (300 & 0xFF) and r["carry_out"] == 1


@pytest.mark.parametrize("n", [1, 2, 3, 4])
def test_rps_exhaustive(n):
    rps = ReverseParallelSubtractor(n)
    for x, y in itertools.product(range(2**n), repeat=2):
        r = rps.simulate(x, y)
        d, b = ReverseParallelSubtractor.subtract(x, y, n)
        assert (r["difference"], r["borrow_out"]) == (d, b)


@pytest.mark.parametrize("n", [1, 2, 4, 8, 10])
def test_d4_exhaustive(n):
    d4 = DividingFour(n)
    assert d4.circuit.num_qubits == n + 2
    for m in range(2**n):
        assert d4.simulate(m) == m >> 2


@pytest.mark.parametrize("n", [1, 2, 3, 4])
def test_qe_exhaustive(n):
    qe = QuantumEqual(n)
    assert qe.circuit.num_qubits == 2 * n + 1
    for i, j in itertools.product(range(2**n), repeat=2):
        assert qe.simulate(i, j) == int(i == j)


def test_qe_restores_inputs():
    qe = QuantumEqual(3)
    bits = run_basis(qe.circuit, {0: 1, 1: 0, 2: 1, 3: 1, 4: 1, 5: 0})
    assert bits[:6] == [1, 0, 1, 1, 1, 0]
    assert bits[6] == 0


def test_modules_are_reversible():
    """Running a module followed by its inverse restores the input."""
    for module in (ReverseParallelAdder(3).circuit, ReverseParallelSubtractor(3).circuit, DividingFour(4).circuit, QuantumEqual(2).circuit):
        qc = module.compose(module.inverse())
        init = [(i * 7) % 2 for i in range(qc.num_qubits)]
        assert BasisStateSimulator().run(qc, init) == init


def test_simulator_rejects_non_permutation_gates():
    from qiskit import QuantumCircuit

    from qwm.simulation import UnsupportedGateError

    qc = QuantumCircuit(1)
    qc.h(0)
    with pytest.raises(UnsupportedGateError):
        run_basis(qc)


def test_simulator_initial_state_forms():
    from qiskit import QuantumCircuit

    qc = QuantumCircuit(3)
    qc.cx(0, 2)
    assert run_basis(qc, 0b001) == [1, 0, 1]
    assert run_basis(qc, [1, 0, 0]) == [1, 0, 1]
    assert run_basis(qc, {0: 1}) == [1, 0, 1]
    assert run_basis(qc) == [0, 0, 0]
