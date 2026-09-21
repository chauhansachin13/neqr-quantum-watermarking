import numpy as np
import pytest


@pytest.fixture
def example_block():
    """The worked example of the reference design."""
    return np.array([[50, 60], [48, 32]], dtype=np.uint8)


@pytest.fixture
def random_image():
    rng = np.random.default_rng(2024)
    return rng.integers(0, 256, (32, 32)).astype(np.uint8)


@pytest.fixture
def natural_image():
    from qwm.data import load_image

    return load_image("camera", 64)
