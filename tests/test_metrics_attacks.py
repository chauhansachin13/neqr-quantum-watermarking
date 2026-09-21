import numpy as np
import pytest

from qwm.attacks import ATTACK_NAMES, apply_attack, random_attack_params
from qwm.metrics import (
    NOISE_MODELS,
    apply_noise,
    block_metrics,
    fidelity,
    histogram,
    histogram_similarity,
    image_metrics,
    mse,
    psnr,
    purity,
    quality_report,
    ssim,
    ssim_global,
    trace_distance,
)
from qwm.metrics.quantum import block_states, pure_block_fidelity


def test_image_metrics_identity(natural_image):
    assert mse(natural_image, natural_image) == 0.0
    assert psnr(natural_image, natural_image) == float("inf")
    assert ssim(natural_image, natural_image) == pytest.approx(1.0)
    assert ssim_global(natural_image, natural_image) == pytest.approx(1.0)
    assert histogram_similarity(natural_image, natural_image) == 1.0


def test_psnr_known_value(natural_image):
    noisy = natural_image.astype(np.int64) ^ 0b11  # invert two LSBs
    value = psnr(natural_image, noisy)
    assert 40.0 < value < 43.0
    report = quality_report(natural_image, noisy)
    assert set(report) == {"mse", "psnr", "ssim", "ssim_global", "histogram_similarity"}


def test_histogram_sums_to_pixels(natural_image):
    assert histogram(natural_image).sum() == natural_image.size


@pytest.mark.parametrize("name", ATTACK_NAMES)
def test_attacks_preserve_shape_and_dtype(natural_image, name):
    out = apply_attack(natural_image, name, seed=0)
    assert out.shape == natural_image.shape and out.dtype == np.uint8
    if name != "no_attack":
        assert not np.array_equal(out, natural_image)


def test_random_attack_params_are_valid(natural_image):
    rng = np.random.default_rng(0)
    for name in ATTACK_NAMES:
        params = random_attack_params(name, rng)
        out = apply_attack(natural_image, name, seed=1, **params)
        assert out.shape == natural_image.shape


def test_unknown_attack(natural_image):
    with pytest.raises(KeyError):
        apply_attack(natural_image, "unknown")


def test_pure_state_metrics(example_block):
    psi, phi = block_states(example_block, [[49, 63], [51, 35]])
    assert fidelity(psi, psi) == pytest.approx(1.0)
    assert fidelity(psi, phi) == pytest.approx(0.0)
    assert trace_distance(psi, phi) == pytest.approx(1.0)
    assert purity(psi) == 1.0
    partial = example_block.copy()
    partial[0, 0] ^= 1
    assert pure_block_fidelity(example_block, partial) == pytest.approx(0.5625)
    assert fidelity(psi, block_states(example_block, partial)[1]) == pytest.approx(0.5625)


@pytest.mark.parametrize("model", [m for m in NOISE_MODELS if m != "none"])
def test_noise_channels_reduce_purity(example_block, model):
    psi, _ = block_states(example_block, example_block)
    rho = apply_noise(psi, model, 0.05)
    assert np.isclose(np.trace(rho.data).real, 1.0)
    assert purity(rho) < 1.0
    assert 0.0 < fidelity(psi, rho) < 1.0


def test_mixed_state_fidelity_matches_qiskit():
    from qiskit.quantum_info import random_density_matrix, state_fidelity

    a, b = random_density_matrix(4, seed=1), random_density_matrix(4, seed=2)
    assert fidelity(a, b) == pytest.approx(state_fidelity(a, b), abs=1e-9)


def test_block_metrics_keys(example_block):
    m = block_metrics(example_block, [[49, 63], [51, 35]], "depolarizing", 0.02)
    assert set(m) >= {"fidelity", "trace_distance", "purity_cover", "purity_watermarked", "purity_ratio"}
    assert 0.0 <= m["trace_distance"] <= 1.0


def test_image_metrics_noiseless(random_image):
    from qwm.watermark import embed_image

    w, _ = embed_image(random_image, mode="lsb")
    m = image_metrics(random_image, w)
    assert m["blocks_evaluated"] == 256 and 0.0 <= m["fidelity"] <= 1.0 and m["purity_ratio"] == 1.0
