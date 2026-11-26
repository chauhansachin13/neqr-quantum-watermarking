import json
import threading
import urllib.request

import numpy as np
import pytest

from qwm.attacks import ATTACK_NAMES
from qwm.classifier.benchmark import (
    CalibratedOpenSetDetector,
    build_benchmark_data,
    unseen_attack_samples,
)
from qwm.classifier.dataset import CLASS_NAMES
from qwm.classifier.features import (
    FEATURE_KINDS,
    descriptor_v2_names,
    extract_features,
    feature_length,
)
from qwm.classifier.train import make_classifier
from qwm.cli import main as cli_main
from qwm.data import default_image_set, load_image
from qwm.metrics.image import psnr
from qwm.nisq import block_tasks, compile_logical, thermal_success_probability
from qwm.secure import DualPartnerSelfRecoveringWatermark, SecureWatermark, SelfRecoveringWatermark
from qwm.studies import thermal_nisq_study
from qwm.tamper import apply_manipulation
from qwm.watermark import embed_image, embed_pixel, extract_image
from qwm.web.server import make_server


def test_opap_mode_beats_lsb_psnr_and_preserves_extraction():
    img = load_image("camera", 128)
    wm_lsb, ref = embed_image(img, mode="lsb")
    wm_opap, ref_opap = embed_image(img, mode="opap")
    assert np.array_equal(ref, ref_opap)
    ext, _ = extract_image(wm_opap)
    assert np.array_equal(ext, ref)
    assert psnr(img, wm_opap) > 46.0
    assert psnr(img, wm_opap) > psnr(img, wm_lsb) + 1.8

    for p in (0, 1, 2, 251, 252, 255):
        for w0 in (0, 1):
            for w1 in (0, 1):
                out = embed_pixel(p, w0, w1, mode="opap")
                assert (out & 1) == w0 and ((out >> 1) & 1) == w1


def test_keyed_optimal_mse_keeps_blind_receiver_compatible():
    img = load_image("camera", 128)
    sw_std = SecureWatermark("opt-secret", "cam128", optimize=False)
    sw_opt = SecureWatermark("opt-secret", "cam128", optimize=True)
    wm_std = sw_std.embed(img)
    wm_opt = sw_opt.embed(img)
    assert psnr(img, wm_opt) > 46.0
    assert psnr(img, wm_opt) > psnr(img, wm_std) + 1.8
    assert sw_std.verify(wm_opt).authentic
    assert sw_opt.verify(wm_opt).authentic
    assert not SecureWatermark("wrong-key", "cam128").verify(wm_opt).authentic

    bad = wm_opt.copy()
    bad[16:20, 16:20] ^= 0b01
    res = sw_std.verify(bad)
    assert not res.authentic
    assert res.tamper_map[8:10, 8:10].all()


@pytest.mark.parametrize("recon", ["bicubic", "interpolate", "flat"])
def test_dual_partner_8x8_recovery_and_rgb(recon: str):
    img = load_image("camera", 128)
    du = DualPartnerSelfRecoveringWatermark("dual-k", "cam128", reconstruction=recon)
    wm = du.embed(img)
    assert psnr(img, wm) > 43.9
    assert not du.verify(wm).any()

    wrong_pass = 1.0 - float(DualPartnerSelfRecoveringWatermark("wrong-k", "cam128").verify(wm).mean())
    assert wrong_pass < 0.008

    # Attack 35% of image to force both primary and secondary partner fallbacks
    rng = np.random.default_rng(7)
    donor = load_image("coins", 128)
    attacked, changed = apply_manipulation("blackout", wm, rng, donor, fraction=0.35)
    res = du.recover(attacked)
    assert res.tamper_map.shape == (16, 16)
    assert res.restored_fraction >= 0.90
    assert res.extra["secondary_restored"] >= 0
    assert res.extra["forgery_prob"] == pytest.approx(2**-16)
    assert psnr(img[changed], res.recovered[changed]) > psnr(img[changed], attacked[changed]) + 5.0

    # Colour roundtrip + 4x4 bicubic reconstruction
    rgb = np.random.default_rng(3).integers(0, 256, (64, 64, 3), dtype=np.uint8)
    wm_rgb = du.embed(rgb)
    assert du.recover(wm_rgb).authentic
    wm_rgb[8:24, 8:24] = 128
    assert du.recover(wm_rgb).restored_fraction > 0.75

    sr_bic = SelfRecoveringWatermark("k4", "cam", reconstruction="bicubic")
    wm_sr = sr_bic.embed(img)
    assert sr_bic.recover(wm_sr).authentic


def test_descriptors_v2_and_open_set_detector():
    assert "descriptors_v2" in FEATURE_KINDS
    names = descriptor_v2_names()
    assert len(names) == 162
    assert feature_length("descriptors_v2", 128) == 162

    covers = [load_image(n, 128) for n in default_image_set(offline=True)[:4]]
    vec = extract_features(covers[0], "descriptors_v2", 128)
    assert vec.shape == (162,) and np.all(np.isfinite(vec))

    data = build_benchmark_data(covers, samples_per_class=8, size=128, seed=3, pixel_sizes=(), include_v2_descriptors=True)
    assert "descriptors_v2" in data.features
    X = data.features["descriptors_v2"]
    y = data.y
    clf = make_classifier(seed=3, n_jobs=1).fit(X[::2], y[::2])
    det = CalibratedOpenSetDetector(clf, keep=0.90).calibrate(X[1::2])
    pred_known = det.predict_with_rejection(X[1::2])
    assert float(np.mean(~pred_known["is_unknown"])) >= 0.85

    Xu, _ = unseen_attack_samples(covers, per_attack=2, size=128, seed=11, feature_kind="descriptors_v2")
    assert Xu.shape == (16, 162)
    assert len(CLASS_NAMES) == len(ATTACK_NAMES)


def test_thermal_nisq_api_and_study():
    assert len(block_tasks()) == 8
    tasks = block_tasks(include_shallow=True)
    assert len(tasks) == 11
    sh = [t for t in tasks if t.name == "shallow generation"][0]
    compiled = compile_logical(sh)
    res = thermal_success_probability(compiled, sh.expected_key, t1=500e-6, t2=300e-6, p2=5e-4, shots=100)
    assert 0.0 <= res["success"] <= 1.0
    assert res["duration_us"] > 0.0
    df = thermal_nisq_study(t1_values=(400e-6,), p2=5e-4, shots=80)
    assert {"lean generation", "shallow generation", "shallow keyed embedding"}.issubset(set(df["circuit"]))


def test_cli_v3_commands(tmp_path):
    from qwm.circuits import WatermarkEmbeddingCircuit, WatermarkGenerationCircuit
    from qwm.data import load_image, save_image

    block = np.array([[50, 60], [48, 32]])
    wb = WatermarkGenerationCircuit(block).run()["watermark"]
    assert WatermarkEmbeddingCircuit(block, wb).verify_unitary_inverse()["exact_unitary_inverse"]
    assert load_image("House1", 32).shape == (32, 32)
    assert load_image("Flower", 32).shape == (32, 32)

    wm_path = tmp_path / "opt.png"
    assert cli_main(["embed", "camera", "--size", "64", "--mode", "keyed-opt", "--key", "k1", "-o", str(wm_path)]) == 0
    assert cli_main(["verify", str(wm_path), "--mode", "keyed", "--key", "k1"]) == 0

    opap_path = tmp_path / "opap.png"
    opap_bits = tmp_path / "opap.npy"
    assert cli_main(["embed", "camera", "--size", "64", "--mode", "opap", "-o", str(opap_path), "--save-watermark", str(opap_bits)]) == 0
    assert cli_main(["verify", str(opap_path), "--mode", "opap", "--reference", str(opap_bits)]) == 0

    # Color RGB image preservation end-to-end with native size
    rgb_in = tmp_path / "rgb_cover.png"
    rgb_wm = tmp_path / "rgb_wm.png"
    rgb = np.random.default_rng(1).integers(0, 256, (32, 40, 3), dtype=np.uint8)
    save_image(rgb, rgb_in)
    assert cli_main(["embed", str(rgb_in), "--mode", "recovery-dual", "--key", "rgbk", "-o", str(rgb_wm)]) == 0
    assert cli_main(["verify", str(rgb_wm), "--mode", "recovery-dual", "--key", "rgbk"]) == 0

    dual_path = tmp_path / "dual.png"
    assert cli_main(["embed", "camera", "--size", "64", "--mode", "recovery-dual", "--key", "k2", "-o", str(dual_path)]) == 0
    assert cli_main(["verify", str(dual_path), "--mode", "recovery-dual", "--key", "k2"]) == 0

    assert cli_main(["superposition", "--image", "camera", "--shots", "128"]) == 0
    assert cli_main(["run", "--image", "camera", "--size", "64"]) == 0
    assert cli_main(["run", "camera", "--size", "32"]) == 0
    assert cli_main(["run", "--size", "32"]) == 0


def test_web_v3_endpoints():
    httpd, _ = make_server("127.0.0.1", 0, prepare_classifier=False)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        def post(path: str, payload: dict) -> dict:
            req = urllib.request.Request(
                base + path,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8"))

        with urllib.request.urlopen(base + "/api/paper", timeout=20) as resp:
            paper = json.loads(resp.read().decode("utf-8"))
        assert paper["worked"]["unitary_inverse"] and paper["table9_violations"] == 6
        assert len(paper["circuit_families"]) == 11

        e_opt = post("/api/embed", {"image": "camera", "mode": "keyed-opt", "key": "web-k"})
        assert e_opt["metrics"]["psnr"] > 46.0
        v_opt = post("/api/verify", {"session": e_opt["session"]})
        assert v_opt["verdict"] == "authentic"

        e_dual = post("/api/embed", {"image": "camera", "mode": "recovery-dual", "key": "web-k2"})
        post("/api/attack", {"session": e_dual["session"], "kind": "local", "name": "blackout", "fraction": 0.25})
        v_dual = post("/api/verify", {"session": e_dual["session"]})
        assert v_dual["verdict"] == "tampered" and v_dual["block_size"] == 8 and v_dual["restored_fraction"] > 0.85

        blk = post("/api/block", {"session": e_opt["session"], "row": 0, "col": 0})
        names = [c["name"] for c in blk["circuits"]]
        assert any("Shallow generation" in n for n in names)
        assert any("NEQR pixel superposition" in n for n in names)

        nisq_res = post("/api/nisq_block", {"session": e_opt["session"], "row": 0, "col": 0, "p2": 0.0005, "t1_us": 400, "shots": 80})
        assert len(nisq_res["rows"]) == 2
        assert nisq_res["rows"][1]["depth"] < nisq_res["rows"][0]["depth"]
    finally:
        httpd.shutdown()
        httpd.server_close()
