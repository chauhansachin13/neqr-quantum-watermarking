import numpy as np
import pytest
from qiskit import QuantumCircuit, QuantumRegister
from qiskit.quantum_info import Operator

from qwm.circuits.lean import (
    LeanEmbeddingCircuit,
    LeanExtractionCircuit,
    LeanGenerationCircuit,
    append_cuccaro,
    append_lean_ppb,
    cuccaro_adder,
)
from qwm.circuits.secure import BlindVerificationCircuit, SecureEmbeddingCircuit
from qwm.secure import SecureWatermark
from qwm.simulation import bits_to_int, run_basis
from qwm.watermark.embedding import embed_block
from qwm.watermark.generation import block_watermark_bits, pixel_position_bits

EXPECTED_WB = [1, 1, 0, 0, 1, 1, 0, 1]


@pytest.mark.parametrize("relative_phase", [False, True])
@pytest.mark.parametrize("n", [1, 2, 3])
def test_cuccaro_adder_exhaustive(n, relative_phase):
    qc = cuccaro_adder(n, relative_phase=relative_phase)
    for a in range(2**n):
        for b in range(2**n):
            init = {i: (a >> i) & 1 for i in range(n)}
            init.update({n + i: (b >> i) & 1 for i in range(n)})
            bits = run_basis(qc, init)
            assert bits_to_int(bits[:n]) == a
            assert bits_to_int(bits[n : 2 * n]) == (a + b) % 2**n
            assert bits[2 * n] == 0 and bits[2 * n + 1] == (a + b) >> n


def test_cuccaro_carry_in_adds_one():
    n = 3
    qc = QuantumCircuit(2 * n + 2)
    qc.x(2 * n)  # carry-in = 1
    append_cuccaro(qc, list(range(n)), list(range(n, 2 * n)), 2 * n, 2 * n + 1)
    for a in range(8):
        for b in range(8):
            init = {i: (a >> i) & 1 for i in range(n)}
            init.update({n + i: (b >> i) & 1 for i in range(n)})
            bits = run_basis(qc, init)
            s = a + b + 1
            assert bits_to_int(bits[n : 2 * n]) == s % 8 and bits[2 * n + 1] == s >> 3 and bits[2 * n] == 1


@pytest.mark.parametrize("n", [2, 3])
def test_relative_phase_adder_is_the_same_unitary(n):
    a = Operator(cuccaro_adder(n, relative_phase=False)).data
    b = Operator(cuccaro_adder(n, relative_phase=True)).data
    assert np.allclose(a, b)


@pytest.mark.parametrize("masked", [False, True])
def test_lean_ppb_exhaustive_and_unitary_equivalence(masked):
    def build(rp):
        p, o, an = QuantumRegister(8, "p"), QuantumRegister(2, "o"), QuantumRegister(1, "an")
        qc = QuantumCircuit(p, o, an)
        append_lean_ppb(qc, list(p), o[0], o[1], an[0], masked, rp)
        return qc

    qc = build(True)
    for v in range(256):
        bits = run_basis(qc, {i: (v >> i) & 1 for i in range(8)})
        assert (bits[8], bits[9]) == pixel_position_bits(v & 0xFC if masked else v)
        assert bits_to_int(bits[:8]) == v and bits[10] == 0
    assert np.allclose(Operator(build(False)).data, Operator(build(True)).data)


def test_lean_generation_worked_example():
    g = LeanGenerationCircuit([[50, 60], [48, 32]])
    r = g.run()
    assert r["watermark"] == EXPECTED_WB and r["pixels_restored"] and r["ancillas_clean"]
    assert g.circuit.num_qubits == 44


@pytest.mark.parametrize("masked", [False, True])
def test_lean_generation_matches_reference(masked):
    rng = np.random.default_rng(99)
    blocks = [np.full((2, 2), 255), np.zeros((2, 2), int), np.array([[255, 255], [255, 253]])]
    blocks += [rng.integers(0, 256, (2, 2)) for _ in range(60)]
    for blk in blocks:
        g = LeanGenerationCircuit(blk, masked=masked)
        r = g.run()
        assert r["watermark"] == g.expected()
        assert r["pixels_restored"] and r["ancillas_clean"]  # garbage-free


def test_lean_embedding_and_extraction():
    blk = np.array([[50, 60], [48, 32]])
    wb = block_watermark_bits(blk)
    emb = LeanEmbeddingCircuit(blk, wb)
    assert emb.circuit.num_qubits == 40
    out = emb.run()["watermarked_block"]
    assert np.array_equal(out, embed_block(blk, wb, mode="lsb"))
    ext = LeanExtractionCircuit(out, wb)
    assert ext.circuit.num_qubits == 41
    assert ext.run() == {"extracted_bits": wb, "authentic": True}
    bad = out.copy()
    bad[1, 1] ^= 1
    assert LeanExtractionCircuit(bad, wb).run()["authentic"] is False


def test_lean_circuits_use_fewer_qubits_than_reported():
    from qwm.resources import reported_resources

    rep = reported_resources(8)
    assert LeanGenerationCircuit([[1, 2], [3, 4]]).circuit.num_qubits < rep["watermark_generation"]["total"] / 8


def test_secure_circuits_match_the_classical_scheme(natural_image):
    img = natural_image[:16, :16]
    key, nonce = "circuit-key", "n1"
    sw = SecureWatermark(key, nonce)
    wm = sw.embed(img)
    rng = np.random.default_rng(4)
    for _ in range(6):
        r, c = (int(v) for v in rng.integers(0, 8, 2))
        blk, wblk = img[2 * r : 2 * r + 2, 2 * c : 2 * c + 2], wm[2 * r : 2 * r + 2, 2 * c : 2 * c + 2]
        se = SecureEmbeddingCircuit(blk, key, nonce, img.shape, r, c)
        assert se.circuit.num_qubits == 44
        assert np.array_equal(se.run()["watermarked_block"], wblk)
        bv = BlindVerificationCircuit(wblk, key, nonce, img.shape, r, c)
        assert bv.circuit.num_qubits == 45
        assert bv.run()["authentic"] is True
        bad = wblk.copy()
        bad[0, 1] ^= 0b1000  # MSB change, LSBs kept
        assert BlindVerificationCircuit(bad, key, nonce, img.shape, r, c).run()["authentic"] == bool(sw.verify(_patched(wm, bad, r, c)).tamper_map[r, c] == 0)


def _patched(img, block, r, c):
    out = img.copy()
    out[2 * r : 2 * r + 2, 2 * c : 2 * c + 2] = block
    return out
