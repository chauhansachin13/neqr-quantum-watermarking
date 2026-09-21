import numpy as np
import pytest

from qwm.circuits import (
    WatermarkEmbeddingCircuit,
    WatermarkExtractionCircuit,
    WatermarkGenerationCircuit,
)

EXPECTED_WB = [1, 1, 0, 0, 1, 1, 0, 1]


def test_generation_circuit_worked_example(example_block):
    gen = WatermarkGenerationCircuit(example_block)
    out = gen.run()
    assert out["watermark"] == EXPECTED_WB
    assert out["aa"] == 48
    assert out["ppb"] == [(1, 1), (0, 0), (0, 0), (0, 1)]
    ops = gen.circuit.count_ops()
    assert ops["RPA4"] == 4 and ops["RPA8"] == 2 and ops["RPA9"] == 1 and ops["RPA10"] == 1 and ops["D4_10"] == 1


def test_embedding_circuit_worked_example(example_block):
    emb = WatermarkEmbeddingCircuit(example_block, EXPECTED_WB)
    assert emb.run()["watermarked_pixels"] == [49, 63, 51, 35]
    ops = emb.circuit.count_ops()
    assert ops["RHA"] == 8 and ops["QE1"] == 8


def test_extraction_circuit_worked_example():
    ext = WatermarkExtractionCircuit([[49, 63], [51, 35]], EXPECTED_WB)
    out = ext.run()
    assert out["extracted_bits"] == EXPECTED_WB
    assert out["raw_bits"] == [1, 0, 1, 1, 1, 1, 1, 1]
    ops = ext.circuit.count_ops()
    assert ops["RHS"] == 8 and ops["QE1"] == 8


def test_extraction_without_reference():
    ext = WatermarkExtractionCircuit([[49, 63], [51, 35]])
    out = ext.run()
    assert out["raw_bits"] == out["extracted_bits"] == [1, 0, 1, 1, 1, 1, 1, 1]


@pytest.mark.parametrize("seed", range(6))
def test_circuits_match_reference_on_random_blocks(seed):
    rng = np.random.default_rng(seed)
    block = rng.integers(0, 256, (2, 2))
    gen = WatermarkGenerationCircuit(block)
    wb = gen.run()["watermark"]
    assert wb == gen.expected()
    emb = WatermarkEmbeddingCircuit(block, wb)
    wblock = emb.run()["watermarked_block"]
    assert wblock.tolist() == emb.expected().tolist()
    ext = WatermarkExtractionCircuit(wblock, wb)
    out = ext.run()
    assert (out["raw_bits"], out["extracted_bits"]) == ext.expected()


def test_generation_circuit_on_aer(example_block):
    """The reversible circuit also runs on the Aer matrix-product-state simulator."""
    from qwm.simulation import aer_counts

    gen = WatermarkGenerationCircuit(example_block)
    qc = gen.circuit.copy()
    qc.measure_all()
    counts = aer_counts(qc, shots=16, method="matrix_product_state", seed=3)
    assert len(counts) == 1
    bitstring = next(iter(counts)).replace(" ", "")[::-1]
    assert [int(bitstring[q]) for q in gen.output_qubits] == EXPECTED_WB


def test_invalid_inputs():
    with pytest.raises(ValueError):
        WatermarkGenerationCircuit(np.zeros((3, 3)))
    with pytest.raises(ValueError):
        WatermarkEmbeddingCircuit(np.zeros((2, 2)), [1, 0])
    with pytest.raises(ValueError):
        WatermarkExtractionCircuit(np.zeros((2, 2)), [1] * 7)
