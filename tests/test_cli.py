import numpy as np

from qwm.cli import main
from qwm.data import save_image


def test_demo(capsys):
    assert main(["demo"]) == 0
    out = capsys.readouterr().out
    assert "[1, 1, 0, 0, 1, 1, 0, 1]" in out and "[49, 63, 51, 35]" in out


def test_embed_extract_roundtrip(tmp_path, natural_image, capsys):
    cover = tmp_path / "cover.png"
    save_image(natural_image, cover)
    wm = tmp_path / "wm.png"
    bits = tmp_path / "bits.npy"
    assert main(["embed", str(cover), "-o", str(wm), "--mode", "lsb", "--size", "64", "--save-watermark", str(bits)]) == 0
    assert main(["extract", str(wm), "--reference", str(bits), "-o", str(tmp_path / "planes.png")]) == 0
    out = capsys.readouterr().out
    assert "BER (raw vs reference) = 0.0000" in out
    assert np.load(bits).shape == (32, 32, 8)


def test_resources_command(tmp_path, capsys):
    assert main(["resources", "--out", str(tmp_path)]) == 0
    assert (tmp_path / "resources.json").exists()


def test_evaluate_offline(tmp_path, capsys):
    assert main(["evaluate", "--images", "camera,coins", "--size", "64", "--out", str(tmp_path)]) == 0
    assert (tmp_path / "imperceptibility.csv").exists()


def test_attacks_offline(tmp_path):
    assert main(["attacks", "--images", "camera", "--size", "64", "--out", str(tmp_path)]) == 0
    assert (tmp_path / "robustness_lsb_summary.csv").exists()


def test_quick_classifier(tmp_path):
    assert main(["classify", "--quick", "--images", "camera,coins", "--size", "64", "--samples-per-class", "5", "--folds", "2", "--out", str(tmp_path)]) == 0
    assert (tmp_path / "confusion_matrix.png").exists()
