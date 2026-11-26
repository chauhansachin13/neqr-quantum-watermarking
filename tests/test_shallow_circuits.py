import numpy as np
import pytest
from qiskit import QuantumCircuit
from qiskit.quantum_info import Operator, Statevector

from qwm.circuits import (
    ShallowBlindVerificationCircuit,
    ShallowGenerationCircuit,
    ShallowKeyedEmbeddingCircuit,
    cla_adder,
)
from qwm.circuits.lean import LeanGenerationCircuit
from qwm.circuits.secure import BlindVerificationCircuit, SecureEmbeddingCircuit
from qwm.nisq import WORKED_BLOCK, BlockTask, compile_logical, gate_counts
from qwm.simulation import bits_to_int, run_basis


@pytest.mark.parametrize("n", [1, 2, 3])
@pytest.mark.parametrize("carry_in", [False, True])
def test_cla_adder_unitary_equivalence(n: int, carry_in: bool):
    u_ref = Operator(cla_adder(n, carry_in=carry_in, carry_out=True, relative_phase=False)).data
    u_rp = Operator(cla_adder(n, carry_in=carry_in, carry_out=True, relative_phase=True, rp_p_only=True)).data
    assert np.allclose(u_ref, u_rp)


def test_cla_adder_4bit_superposition_phase_exact():
    qc_ref = cla_adder(4, carry_in=True, carry_out=True, relative_phase=False)
    qc_opt = cla_adder(4, carry_in=True, carry_out=True, relative_phase=True, rp_p_only=True)
    prep = QuantumCircuit(qc_ref.num_qubits)
    for idx in list(range(8)) + [12]:  # a[0..3], b[0..3], cin
        prep.h(idx)
    sv_ref = Statevector(prep.compose(qc_ref)).data
    sv_opt = Statevector(prep.compose(qc_opt)).data
    assert np.allclose(sv_ref, sv_opt)


@pytest.mark.parametrize("n", [1, 2, 3, 4])
def test_cla_adder_exhaustive_basis_clean_ancillas(n: int):
    qc = cla_adder(n, carry_in=True, carry_out=True, relative_phase=True, rp_p_only=False)
    mod = 1 << n
    for cin in (0, 1):
        for a in range(mod):
            for b in range(mod):
                init = {i: (a >> i) & 1 for i in range(n)}
                init.update({n + i: (b >> i) & 1 for i in range(n)})
                init[3 * n] = cin
                bits = run_basis(qc, init)
                total = a + b + cin
                assert bits_to_int(bits[:n]) == a
                assert bits_to_int(bits[n : 2 * n]) == total % mod
                assert bits[3 * n + 1] == (total >> n)
                assert all(x == 0 for x in bits[2 * n : 3 * n])
                assert all(x == 0 for x in bits[3 * n + 2 :])


@pytest.mark.parametrize("masked", [False, True])
def test_shallow_generation_matches_lean_and_cuts_depth(masked: bool):
    rng = np.random.default_rng(13)
    blocks = [WORKED_BLOCK] + [rng.integers(0, 256, size=(2, 2), dtype=np.uint8) for _ in range(3)]
    for blk in blocks:
        sg = ShallowGenerationCircuit(blk, masked=masked)
        res = sg.run()
        assert res["watermark"] == sg.expected()
        assert res["pixels_restored"]
        assert res["ancillas_clean"]

    sg = ShallowGenerationCircuit(WORKED_BLOCK, masked=masked)
    lg = LeanGenerationCircuit(WORKED_BLOCK, masked=masked)
    d_sh = gate_counts(compile_logical(BlockTask("sh", "shallow", "gen", sg.circuit, [sg.circuit.find_bit(q).index for q in sg.layout.out], sg.expected())))["depth"]
    d_ln = gate_counts(compile_logical(BlockTask("ln", "lean", "gen", lg.circuit, [lg.circuit.find_bit(q).index for q in lg.layout.out], lg.expected())))["depth"]
    assert d_sh < 0.65 * d_ln


def test_shallow_keyed_embed_and_verify():
    key, nonce = "shallow-test-key", "blk-1"
    se_lean = SecureEmbeddingCircuit(WORKED_BLOCK, key, nonce, (8, 8), 1, 2).run()
    se_sh = ShallowKeyedEmbeddingCircuit(WORKED_BLOCK, key, nonce, (8, 8), 1, 2).run()
    assert np.array_equal(se_lean["watermarked_block"], se_sh["watermarked_block"])

    bv_lean = BlindVerificationCircuit(se_sh["watermarked_block"], key, nonce, (8, 8), 1, 2).run()
    bv_sh = ShallowBlindVerificationCircuit(se_sh["watermarked_block"], key, nonce, (8, 8), 1, 2).run()
    assert bv_sh["authentic"] and bv_sh["ancillas_clean"]
    assert bv_sh["extracted_bits"] == bv_lean["extracted_bits"]

    bad = se_sh["watermarked_block"].copy()
    bad[1, 0] ^= 0b01
    bv_bad = ShallowBlindVerificationCircuit(bad, key, nonce, (8, 8), 1, 2).run()
    assert (not bv_bad["authentic"]) and bv_bad["ancillas_clean"]
