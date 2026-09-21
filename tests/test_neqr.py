import numpy as np
import pytest
from qiskit.quantum_info import Statevector

from qwm.neqr import (
    decode_counts,
    decode_statevector,
    encode_decode_roundtrip,
    iter_blocks,
    neqr_block_circuit,
    neqr_circuit,
    neqr_statevector,
)


def test_block_circuit_has_ten_qubits(example_block):
    qc = neqr_block_circuit(example_block)
    assert qc.num_qubits == 10
    ops = qc.count_ops()
    assert ops["h"] == 2 and ops["ccx"] == sum(bin(int(v)).count("1") for v in example_block.ravel())


def test_block_roundtrip(example_block):
    assert np.array_equal(encode_decode_roundtrip(example_block), example_block)


def test_closed_form_matches_circuit(example_block):
    sv = Statevector(neqr_block_circuit(example_block, barriers=False))
    assert np.allclose(sv.data, neqr_statevector(example_block).data)


@pytest.mark.parametrize("side", [2, 4, 8])
def test_roundtrip_random_images(side):
    rng = np.random.default_rng(side)
    img = rng.integers(0, 256, (side, side)).astype(np.uint8)
    assert np.array_equal(encode_decode_roundtrip(img), img)


def test_uniform_position_probabilities(example_block):
    probs = neqr_statevector(example_block).probabilities()
    assert np.count_nonzero(probs) == 4
    assert np.allclose(probs[probs > 0], 0.25)


def test_decode_counts(example_block):
    from qwm.simulation import aer_counts

    qc = neqr_block_circuit(example_block, barriers=False)
    counts = aer_counts(qc, shots=2048, seed=1)
    assert np.array_equal(decode_counts(counts, (2, 2)), example_block)


def test_decode_statevector_shape(example_block):
    sv = neqr_statevector(example_block)
    assert decode_statevector(sv, (2, 2)).shape == (2, 2)


def test_invalid_images():
    with pytest.raises(ValueError):
        neqr_circuit(np.zeros((3, 3), dtype=np.uint8))
    with pytest.raises(ValueError):
        neqr_circuit(np.full((2, 2), 300))


def test_iter_blocks(random_image):
    blocks = list(iter_blocks(random_image))
    assert len(blocks) == (32 // 2) ** 2
    (r, c), blk = blocks[1]
    assert (r, c) == (0, 2) and blk.shape == (2, 2)
