import numpy as np
import pytest

from qwm.circuits.superposition import (
    block_neqr_blind_verify,
    run_block_neqr_superposition,
    run_grover_tamper_search,
    run_neqr_ppb_superposition,
)
from qwm.secure import SecureWatermark
from qwm.watermark.generation import pixel_position_bits


def _sample_patch() -> np.ndarray:
    return np.array(
        [
            [50, 60, 120, 121],
            [48, 32, 200, 201],
            [10, 20, 30, 40],
            [90, 91, 92, 93],
        ],
        dtype=np.uint8,
    )


@pytest.mark.parametrize("masked", [False, True])
@pytest.mark.parametrize("shape", [(2, 2), (4, 4)])
def test_neqr_ppb_superposition_exact_statevector(masked: bool, shape: tuple[int, int]):
    patch = _sample_patch()[: shape[0], : shape[1]]
    res = run_neqr_ppb_superposition(patch, masked=masked)
    assert res["exact_match"]
    assert res["uniform"]
    assert res["ancilla_clean_prob"] > 1.0 - 1e-9
    assert np.array_equal(res["decoded_ppb"], res["expected_ppb"])


def test_grover_tamper_search_blind_and_reference():
    patch = _sample_patch()
    auth = (patch & 0xFC).copy()
    ref_lsb = np.zeros((4, 4, 2), dtype=np.uint8)
    for y in range(4):
        for x in range(4):
            b0, b1 = pixel_position_bits(int(auth[y, x]))
            auth[y, x] |= b0 | (b1 << 1)
            ref_lsb[y, x] = (b0, b1)

    res_clean = run_grover_tamper_search(auth)
    assert res_clean["n_marked_true"] == 0
    assert res_clean["flagged_coords"] == []
    assert res_clean["ancilla_clean_prob"] > 1.0 - 1e-9

    tampered = auth.copy()
    tampered[2, 1] ^= 0b10
    res_blind = run_grover_tamper_search(tampered)
    assert res_blind["exact_match"]
    assert res_blind["flagged_coords"] == [(2, 1)]
    assert res_blind["tampered_probability_mass"] > 0.95
    assert res_blind["ancilla_clean_prob"] > 1.0 - 1e-9

    # Also test reference-LSB mode where LSB was swapped without matching PPB rule
    ref_img = (patch & 0xFC).copy()
    ref_img[0, 3] |= 0b10
    custom_ref = np.zeros((4, 4, 2), dtype=np.uint8)
    tampered_ref = ref_img.copy()
    tampered_ref[0, 3] ^= 0b11
    res_ref = run_grover_tamper_search(tampered_ref, reference_lsb=custom_ref)
    assert (0, 3) in res_ref["flagged_coords"]


@pytest.mark.parametrize("masked", [False, True])
def test_block_neqr_superposition_mps(masked: bool):
    res = run_block_neqr_superposition(_sample_patch(), masked=masked, shots=512, seed=7)
    assert res["qubits"] == 46
    assert res["all_blocks_seen"]
    assert res["accuracy"] == 1.0


def test_block_neqr_blind_verify_mps():
    patch = _sample_patch()
    sw = SecureWatermark("mps-key", "p0")
    wm = sw.embed(patch)
    wm[2:4, 0:2] ^= 0b11
    res = block_neqr_blind_verify(wm, "mps-key", "p0", shots=512, seed=7)
    assert res["qubits"] == 47
    assert res["accuracy"] == 1.0
    assert res["ancilla_clean_rate"] == 1.0
    assert res["matches_classical"]
    assert bool(res["tamper_blocks_quantum"][1, 0])
    assert not bool(res["tamper_blocks_quantum"][0, 0])
