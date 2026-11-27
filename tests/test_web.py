"""Smoke tests of the demo web server (stdlib HTTP server on a free port)."""

import json
import threading
import urllib.error
import urllib.request

import numpy as np
import pytest

from qwm.web.server import from_data_url, make_server, to_data_url


@pytest.fixture(scope="module")
def server():
    httpd, app = make_server("127.0.0.1", 0, prepare_classifier=False)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    yield base, app
    httpd.shutdown()
    httpd.server_close()


def _get(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        return r.status, r.read()


def _post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_data_url_roundtrip():
    img = np.arange(64, dtype=np.uint8).reshape(8, 8)
    assert np.array_equal(from_data_url(to_data_url(img)), img)


def test_static_files_and_traversal(server):
    base, _ = server
    status, body = _get(base + "/")
    assert status == 200 and b"NEQR Quantum Watermarking" in body
    for path in ("/style.css", "/app.js", "/inside.js"):
        assert _get(base + path)[0] == 200
    with pytest.raises(urllib.error.HTTPError) as err:
        _get(base + "/../server.py")
    assert err.value.code == 404


def test_meta(server):
    base, _ = server
    status, body = _get(base + "/api/meta")
    meta = json.loads(body)
    assert status == 200 and "camera" in meta["images"] and {"paper", "lsb", "opap", "keyed", "keyed-opt", "recovery", "recovery-dual"}.issubset(meta["modes"])
    status_def, emb_def = _post(base + "/api/embed", {"mode": "recovery-dual"})
    assert status_def == 200 and emb_def["nonce"] in ("airplane", "rocket")


@pytest.mark.parametrize("mode", ["keyed", "recovery", "lsb", "paper"])
def test_embed_attack_verify(server, mode):
    base, _ = server
    status, emb = _post(base + "/api/embed", {"image": "camera", "mode": mode, "key": "k", "nonce": "n"})
    assert status == 200 and emb["metrics"]["psnr"] > 38
    sid = emb["session"]
    status, ver = _post(base + "/api/verify", {"session": sid})
    assert status == 200 and ver["verdict"] == "authentic"
    status, att = _post(base + "/api/attack", {"session": sid, "kind": "local", "name": "blackout", "fraction": 0.2, "seed": 1})
    assert status == 200 and att["changed_pixels"] > 0
    status, ver = _post(base + "/api/verify", {"session": sid})
    assert status == 200
    if mode == "paper":
        assert ver["verdict"] == "authentic"  # the literal rule cannot detect anything (documented)
    else:
        assert ver["verdict"] == "tampered"
    if mode == "recovery":
        assert ver["psnr_recovered"] > ver["psnr_attacked"] + 5


def test_block_endpoint_runs_qiskit_on_a_request_thread(server):
    base, _ = server
    _, emb = _post(base + "/api/embed", {"image": "camera", "mode": "keyed", "key": "k"})
    status, blk = _post(base + "/api/block", {"session": emb["session"], "row": 10, "col": 20})
    assert status == 200
    names = [c["name"] for c in blk["circuits"]]
    assert any("Lean generation" in n for n in names) and blk["neqr"].startswith("data:image/png")
    assert blk["trace"]["watermark"] == [int(b) for b in blk["circuits"][0]["result"].split("Wb ")[1]]


def test_errors_are_json(server):
    base, _ = server
    with urllib.request.urlopen(base + "/api/health") as resp:
        assert resp.status == 200
        health = json.loads(resp.read().decode())
    assert health["status"] == "ok" and "version" in health
    status, body = _post(base + "/api/verify", {"session": "nope"})
    assert status == 400 and "session" in body["error"]
    status, body = _post(base + "/api/embed", {"image": "camera", "mode": "bogus"})
    assert status == 400
    status, body = _post(base + "/api/embed", [])
    assert status == 400 and "JSON object" in body["error"]
