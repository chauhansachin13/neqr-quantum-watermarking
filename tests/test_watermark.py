import numpy as np
import pytest

from qwm.watermark import (
    arithmetic_average,
    bit_error_rate,
    block_trace,
    block_watermark_bits,
    embed_block,
    embed_image,
    embed_pixel_trace,
    extract_block,
    extract_image,
    extract_pixel_trace,
    generate_watermark,
    normalized_correlation,
    payload_capacity,
    pixel_position_bits,
    tamper_map,
)

EXPECTED_WB = [1, 1, 0, 0, 1, 1, 0, 1]


def test_worked_example_generation(example_block):
    t = block_trace(example_block)
    assert t["ppb"] == [(1, 1), (0, 0), (0, 0), (0, 1)]
    assert t["sum"] == 190 and t["aa"] == 48
    assert t["watermark"] == EXPECTED_WB


def test_pixel_position_bits_examples():
    assert pixel_position_bits(50) == (1, 1)
    assert pixel_position_bits(60) == (0, 0)
    assert pixel_position_bits(48) == (0, 0)
    assert pixel_position_bits(32) == (0, 1)


def test_arithmetic_average_rounding():
    assert arithmetic_average([[50, 60], [48, 32]]) == 48  # 47.5 -> 48
    assert arithmetic_average([[0, 0], [0, 1]]) == 0  # 0.25 -> 0
    assert arithmetic_average([[255, 255], [255, 255]]) == 255


def test_worked_example_embedding(example_block):
    assert embed_block(example_block, EXPECTED_WB).tolist() == [[49, 63], [51, 35]]


def test_table3_trace():
    trace = embed_pixel_trace(50, 1, 1)
    s0, s1 = trace["steps"]
    assert (s0["rpa_result"], s0["xor_result"], s0["qe_equal"], s0["embedded_bit"]) == (1, 0, 1, 1)
    assert (s1["rpa_result"], s1["xor_result"], s1["qe_equal"], s1["embedded_bit"]) == (1, 1, 1, 0)
    assert trace["watermarked_pixel"] == 49


def test_worked_example_extraction():
    raw, out = extract_block([[49, 63], [51, 35]], EXPECTED_WB)
    assert out == EXPECTED_WB
    assert raw == [1, 0, 1, 1, 1, 1, 1, 1]


def test_table4_trace():
    trace = extract_pixel_trace(49, (1, 1))
    s0, s1 = trace["steps"]
    assert (s0["xor_result"], s0["rps_result"], s0["qe_equal"], s0["extracted_bit"]) == (1, 1, 1, 1)
    assert (s1["xor_result"], s1["rps_result"], s1["qe_equal"], s1["extracted_bit"]) == (0, 0, 0, 1)


def test_paper_mode_inverts_two_lsbs(random_image):
    w, _ = embed_image(random_image, mode="paper")
    assert np.array_equal(w, random_image ^ 0b11)


def test_lsb_mode_blind_extraction(random_image):
    w, wb = embed_image(random_image, mode="lsb")
    raw, corrected = extract_image(w, wb)
    assert bit_error_rate(raw, wb) == 0.0
    assert normalized_correlation(raw, wb) == pytest.approx(1.0)
    assert not tamper_map(raw, wb).any()
    assert np.array_equal(corrected, wb)
    assert np.array_equal(w >> 2, random_image >> 2)


def test_vectorised_matches_blockwise(random_image):
    wb = generate_watermark(random_image)
    for r in range(0, 32, 2):
        for c in range(0, 32, 2):
            block = random_image[r : r + 2, c : c + 2]
            assert wb[r // 2, c // 2].tolist() == block_watermark_bits(block)
    for mode in ("paper", "lsb"):
        w, _ = embed_image(random_image, wb, mode)
        raw, corrected = extract_image(w, wb)
        for r in range(0, 32, 4):
            for c in range(0, 32, 4):
                block = random_image[r : r + 2, c : c + 2]
                bits = wb[r // 2, c // 2]
                assert w[r : r + 2, c : c + 2].tolist() == embed_block(block, bits, mode).tolist()
                rb, cb = extract_block(w[r : r + 2, c : c + 2], bits)
                assert raw[r // 2, c // 2].tolist() == rb and corrected[r // 2, c // 2].tolist() == cb


def test_verified_extraction_always_returns_reference(random_image):
    w, wb = embed_image(random_image, mode="paper")
    _, corrected = extract_image(w, wb)
    assert np.array_equal(corrected, wb)


def test_tamper_map_detects_modified_blocks(random_image):
    w, wb = embed_image(random_image, mode="lsb")
    tampered = w.copy()
    tampered[4:6, 4:6] ^= 0b01
    raw, _ = extract_image(tampered, wb)
    tm = tamper_map(raw, wb)
    assert tm[2, 2] and tm.sum() == 1


def test_payload_capacity():
    cap = payload_capacity((256, 256))
    assert cap["blocks"] == 16384 and cap["bits_embedded"] == 131072 and cap["bpp"] == 2.0


def test_invalid_mode(random_image):
    with pytest.raises(ValueError):
        embed_image(random_image, mode="nope")
