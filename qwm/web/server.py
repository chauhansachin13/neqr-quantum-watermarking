"""
Interactive demo: ``qwm serve`` -> http://127.0.0.1:8765

A small JSON API on top of the package, served with the standard library
(:class:`http.server.ThreadingHTTPServer`, no web framework), plus a
single-page front-end in ``qwm/web/static``.  Every number shown in the page
comes from the same code as the CLI and the experiments.

Endpoints (POST bodies and responses are JSON, images are PNG data URLs):

* ``GET  /api/meta``      images, schemes, attacks, classifier status
* ``POST /api/embed``     ``{image | upload, mode, key, nonce}`` -> cover, watermarked, metrics
* ``POST /api/attack``    ``{session, kind: global|local|paint, name, params | image}``
* ``POST /api/verify``    ``{session}`` -> tamper overlay, verdict, repaired image
* ``POST /api/classify``  ``{session}`` -> attack-class probabilities
* ``POST /api/block``     ``{session, row, col}`` -> the 2x2 block through every circuit
* ``GET  /api/resources`` circuit resource table
"""

from __future__ import annotations

import base64
import json
import threading
import time
import uuid
import webbrowser
from collections import OrderedDict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import matplotlib

# Request handlers run on worker threads; macOS GUI backends crash when a
# figure is created off the main thread, so pin the headless Agg backend
# before anything imports pyplot.
matplotlib.use("Agg", force=True)

import cv2  # noqa: E402
import numpy as np  # noqa: E402

STATIC = Path(__file__).resolve().parent / "static"
_MPL_LOCK = threading.Lock()  # matplotlib is not thread-safe
RESULTS = Path(__file__).resolve().parents[2] / "results"
MAX_BODY = 12 * 1024 * 1024
MAX_SESSIONS = 40
SIZE = 256

MODES = {
    "paper": "Base scheme, literal rule (RPA -> XOR -> QE -> Pauli-X)",
    "lsb": "Base scheme, LSB replacement (needs the reference bits)",
    "opap": "v3 base upgrade: Optimal Pixel Adjustment Process (OPAP, ~46.4 dB)",
    "keyed": "Proposed: keyed blind authentication (2x2 blocks)",
    "keyed-opt": "v3 blind authentication (81-coset MSE optimal, ~46.4 dB)",
    "recovery": "Proposed: keyed self-recovery (4x4 blocks)",
    "recovery-dual": "v3 dual-partner Haar self-recovery (8x8 blocks, 2^-16 MAC)",
}
LOCAL_EDITS = ("text_overlay", "blackout", "copy_move", "splice", "lsb_preserving_splice", "local_blur")


# --------------------------------------------------------------------------- #
# image helpers
# --------------------------------------------------------------------------- #
def to_data_url(img: np.ndarray) -> str:
    arr = np.asarray(img)
    if arr.ndim == 3:
        arr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    ok, buf = cv2.imencode(".png", arr)
    if not ok:  # pragma: no cover
        raise RuntimeError("PNG encoding failed")
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode("ascii")


def from_data_url(url: str) -> np.ndarray:
    if not isinstance(url, str) or "," not in url:
        raise ValueError("expected a data URL")
    raw = base64.b64decode(url.split(",", 1)[1], validate=False)
    img = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError("could not decode the image")
    return img


def amplified_difference(a: np.ndarray, b: np.ndarray, gain: int = 64) -> np.ndarray:
    d = np.abs(a.astype(np.int64) - b.astype(np.int64)) * gain
    return np.clip(d, 0, 255).astype(np.uint8)


def overlay(img: np.ndarray, tamper: np.ndarray, block: int) -> np.ndarray:
    from qwm.studies import _overlay

    return _overlay(img, tamper, block)


# --------------------------------------------------------------------------- #
# application state
# --------------------------------------------------------------------------- #
class DemoApp:
    def __init__(self, prepare_classifier: bool = True) -> None:
        self.sessions: OrderedDict[str, dict] = OrderedDict()
        self.lock = threading.Lock()
        self.classifier = None
        self.classifier_features = "descriptors_v2"
        self.ood_threshold = 0.50
        self.classifier_info = "training a quick Random Forest in the background ..."
        if prepare_classifier:
            threading.Thread(target=self._prepare_classifier, daemon=True).start()
        else:
            self.classifier_info = "classifier disabled"

    # -- classifier ---------------------------------------------------------
    def _prepare_classifier(self) -> None:
        try:
            import joblib

            saved = RESULTS / "classifier" / "descriptors_random" / "random_forest.joblib"
            if saved.exists():
                self.classifier = joblib.load(saved)
                self.classifier_features = "descriptors"
                self.ood_threshold = 0.48
                self.classifier_info = "Random Forest (Table 18) on 137-d descriptors, trained on 4,500 attacked images"
                return
            from sklearn.model_selection import train_test_split

            from qwm.classifier.benchmark import CalibratedOpenSetDetector
            from qwm.classifier.dataset import build_dataset
            from qwm.classifier.train import make_classifier
            from qwm.data import default_image_set, load_image

            t0 = time.perf_counter()
            covers = [load_image(n, SIZE) for n in default_image_set(offline=True)]
            ds = build_dataset(covers, samples_per_class=60, size=SIZE, features="descriptors_v2", seed=1)
            tr, va = train_test_split(np.arange(len(ds.y)), test_size=0.2, stratify=ds.y, random_state=1)
            cal_clf = make_classifier().fit(ds.X[tr], ds.y[tr])
            det = CalibratedOpenSetDetector(cal_clf, keep=0.95).calibrate(ds.X[va])
            self.classifier = make_classifier().fit(ds.X, ds.y)
            self.classifier_features = "descriptors_v2"
            self.ood_threshold = det.threshold
            self.classifier_info = (
                f"Random Forest on 162-d v3 forensic descriptors ({len(ds.y)} samples, "
                f"{time.perf_counter() - t0:.1f} s, OOD threshold {det.threshold:.2f})"
            )
        except Exception as exc:  # pragma: no cover - reported in the UI
            self.classifier_info = f"classifier unavailable: {exc}"

    # -- sessions -----------------------------------------------------------
    def _new_session(self, data: dict) -> str:
        sid = uuid.uuid4().hex
        with self.lock:
            self.sessions[sid] = data
            while len(self.sessions) > MAX_SESSIONS:
                self.sessions.popitem(last=False)
        return sid

    def _session(self, sid: str) -> dict:
        with self.lock:
            if sid not in self.sessions:
                raise KeyError("unknown or expired session - embed an image first")
            self.sessions.move_to_end(sid)
            return self.sessions[sid]

    @staticmethod
    def _scheme(mode: str, key: str, nonce: str):
        from qwm.secure import (
            DualPartnerSelfRecoveringWatermark,
            SecureWatermark,
            SelfRecoveringWatermark,
        )

        if mode == "keyed":
            return SecureWatermark(key, nonce)
        if mode == "keyed-opt":
            return SecureWatermark(key, nonce, optimize=True)
        if mode == "recovery":
            return SelfRecoveringWatermark(key, nonce)
        return DualPartnerSelfRecoveringWatermark(key, nonce)

    # -- endpoints ----------------------------------------------------------
    def meta(self) -> dict:
        from qwm.attacks import ATTACK_NAMES, DEFAULT_PARAMS
        from qwm.classifier.dataset import PRETTY_NAMES
        from qwm.data import available_images
        from qwm.tamper import PRETTY

        local = [n for n in available_images(include_standard=False)]
        standard = [p.stem for p in sorted((RESULTS.parent / "data" / "images").glob("*.png"))]
        return {
            "images": standard + [n for n in local if n not in standard],
            "modes": MODES,
            "attacks": [{"name": n, "label": PRETTY_NAMES[n], "params": DEFAULT_PARAMS.get(n, {})} for n in ATTACK_NAMES if n != "no_attack"],
            "local_edits": [{"name": n, "label": PRETTY[n]} for n in LOCAL_EDITS],
            "classifier": {"ready": self.classifier is not None, "info": self.classifier_info},
        }

    def embed(self, req: dict) -> dict:
        from qwm.data import load_image, resize
        from qwm.metrics.image import quality_report
        from qwm.watermark import embed_image, generate_watermark

        mode = req.get("mode", "keyed")
        if mode not in MODES:
            raise ValueError(f"unknown mode {mode!r}")
        if req.get("upload"):
            cover = resize(from_data_url(req["upload"]), SIZE)
            source = "upload"
        else:
            source = str(req.get("image") or "camera")
            cover = load_image(source, SIZE)
        key, nonce = str(req.get("key") or "demo-key"), str(req.get("nonce") or source)
        t0 = time.perf_counter()
        ref = None
        if mode in ("paper", "lsb", "opap"):
            watermarked, ref = embed_image(cover, mode=mode)
            side_bits = int(ref.size)
        else:
            watermarked = self._scheme(mode, key, nonce).embed(cover)
            side_bits = 0
        t_embed = time.perf_counter() - t0
        q = quality_report(cover, watermarked)
        sid = self._new_session(
            {"cover": cover, "watermarked": watermarked, "attacked": watermarked.copy(), "mode": mode, "key": key, "nonce": nonce, "ref": ref, "source": source, "last_attack": "no attack"}
        )
        return {
            "session": sid,
            "cover": to_data_url(cover),
            "watermarked": to_data_url(watermarked),
            "difference": to_data_url(amplified_difference(cover, watermarked)),
            "metrics": {
                "psnr": q["psnr"],
                "ssim": q["ssim"],
                "mse": q["mse"],
                "bpp": 2.0,
                "embed_ms": 1000 * t_embed,
                "side_information_bits": side_bits,
                "content_code_bits": int(generate_watermark(cover).size),
            },
            "mode": mode,
            "mode_label": MODES[mode],
            "key": key,
            "nonce": nonce,
        }

    def attack(self, req: dict) -> dict:
        from qwm.attacks import apply_attack
        from qwm.data import load_image
        from qwm.metrics.image import quality_report
        from qwm.tamper import PRETTY, apply_manipulation

        s = self._session(req["session"])
        wm = s["watermarked"]
        kind = req.get("kind", "global")
        rng = np.random.default_rng(int(req.get("seed", 0)))
        if kind == "paint":
            attacked = from_data_url(req["image"])
            if attacked.shape != wm.shape:
                attacked = cv2.resize(attacked, wm.shape[::-1], interpolation=cv2.INTER_NEAREST)
            label = "hand edit"
        elif kind == "local":
            name = req["name"]
            donor = load_image("baboon" if s["source"] != "baboon" else "camera", SIZE)
            attacked, _ = apply_manipulation(name, wm, rng, donor, float(req.get("fraction", 0.2)))
            label = PRETTY[name]
        elif kind == "none":
            attacked, label = wm.copy(), "no attack"
        else:
            name = req["name"]
            params = {k: v for k, v in (req.get("params") or {}).items() if v is not None}
            attacked = apply_attack(wm, name, seed=int(req.get("seed", 0)), **params)
            label = name.replace("_", " ")
        s["attacked"] = attacked.astype(np.uint8)
        s["last_attack"] = label
        q = quality_report(s["cover"], attacked)
        return {"attacked": to_data_url(attacked), "label": label, "psnr": q["psnr"], "ssim": q["ssim"], "changed_pixels": int((attacked != wm).sum())}

    def verify(self, req: dict) -> dict:
        from qwm.metrics.image import psnr
        from qwm.watermark import bit_error_rate, extract_image, tamper_map

        s = self._session(req["session"])
        img, mode = s["attacked"], s["mode"]
        t0 = time.perf_counter()
        out: dict = {"mode": mode}
        if mode == "paper":
            raw, corrected = extract_image(img, s["ref"])
            tamper = np.zeros(raw.shape[:2], dtype=bool)
            out.update(
                {
                    "note": "The literal rule inverts the two LSBs whatever the watermark is, and the extraction's QE + Pauli-X step overwrites every read-out bit with the reference bit, so this check always reports 'authentic'. That is why v2 adds the LSB and keyed schemes.",
                    "ber_after_qe": bit_error_rate(corrected, s["ref"]),
                }
            )
            block = 2
        elif mode in ("lsb", "opap"):
            raw, _ = extract_image(img)
            tamper = tamper_map(raw, s["ref"])
            block = 2
            mode_note = "OPAP adjusts +/-4 MSBs to cut MSE from ~2.5 to ~1.5 (PSNR ~46.4 dB). " if mode == "opap" else ""
            out.update({"ber": bit_error_rate(raw, s["ref"]), "note": f"{mode_note}Non-blind: needs the {s['ref'].size:,} reference bits stored at embedding time; content edits that keep the two LSBs are invisible to it."})
        elif mode in ("keyed", "keyed-opt"):
            res = self._scheme(mode, s["key"], s["nonce"]).verify(img)
            tamper, block = res.tamper_map, 2
            opt_note = " Optimal 81-coset embedding raises PSNR to ~46.4 dB with zero receiver changes." if mode == "keyed-opt" else ""
            out["note"] = f"Blind: only the key and nonce are needed. A changed block passes with probability 2^-8.{opt_note}"
        else:
            res = self._scheme(mode, s["key"], s["nonce"]).recover(img)
            block = 8 if mode == "recovery-dual" else 4
            tamper = res.tamper_map
            detail = (
                f"Primary Haar: {res.extra.get('primary_restored', 0)}, Secondary fallback: {res.extra.get('secondary_restored', 0)}. Forgery probability 2^-16."
                if mode == "recovery-dual"
                else "A changed block passes with probability 2^-12."
            )
            out.update(
                {
                    "recovered": to_data_url(res.recovered),
                    "psnr_recovered": psnr(s["cover"], res.recovered),
                    "psnr_attacked": psnr(s["cover"], img),
                    "restored_fraction": res.restored_fraction,
                    "note": f"Blind: failed {block}x{block} blocks are rebuilt from partner recovery codes (inpainting if partners failed too). {detail}",
                }
            )
        n_bad = int(tamper.sum())
        out.update(
            {
                "overlay": to_data_url(overlay(img, tamper, block)),
                "blocks_failed": n_bad,
                "blocks_total": int(tamper.size),
                "block_size": block,
                "verdict": "authentic" if n_bad == 0 else "tampered",
                "verify_ms": 1000 * (time.perf_counter() - t0),
            }
        )
        return out

    def classify(self, req: dict) -> dict:
        from qwm.classifier.dataset import CLASS_NAMES, PRETTY_NAMES
        from qwm.classifier.features import extract_features

        s = self._session(req["session"])
        if self.classifier is None:
            return {"ready": False, "info": self.classifier_info}
        x = extract_features(s["attacked"], self.classifier_features, SIZE)[None, :]
        proba = self.classifier.predict_proba(x)[0]
        classes = [CLASS_NAMES[int(c)] for c in self.classifier.classes_]
        rows = sorted(({"name": PRETTY_NAMES[c], "p": float(p)} for c, p in zip(classes, proba, strict=True)), key=lambda r: -r["p"])
        top_p = float(rows[0]["p"])
        return {
            "ready": True,
            "info": self.classifier_info,
            "probabilities": rows,
            "predicted": rows[0]["name"],
            "actual": s["last_attack"],
            "confidence": top_p,
            "threshold": float(self.ood_threshold),
            "is_unknown": bool(top_p < self.ood_threshold),
        }

    def block(self, req: dict) -> dict:
        import io

        import matplotlib.pyplot as plt

        from qwm.circuits import (
            ShallowBlindVerificationCircuit,
            ShallowGenerationCircuit,
            WatermarkEmbeddingCircuit,
            WatermarkExtractionCircuit,
            WatermarkGenerationCircuit,
            run_neqr_ppb_superposition,
        )
        from qwm.circuits.lean import LeanGenerationCircuit
        from qwm.circuits.secure import BlindVerificationCircuit
        from qwm.neqr import neqr_block_circuit
        from qwm.nisq import BlockTask, compile_logical, gate_counts
        from qwm.watermark import block_trace

        s = self._session(req["session"])
        r, c = int(req["row"]), int(req["col"])
        hb, wb = s["cover"].shape[0] // 2, s["cover"].shape[1] // 2
        if not (0 <= r < hb and 0 <= c < wb):
            raise ValueError("block outside the image")
        blk = s["cover"][2 * r : 2 * r + 2, 2 * c : 2 * c + 2].astype(int)
        trace = block_trace(blk)
        timings = {}

        def timed(name, fn):
            t0 = time.perf_counter()
            val = fn()
            timings[name] = 1000 * (time.perf_counter() - t0)
            return val

        gen = WatermarkGenerationCircuit(blk)
        g = timed("base generation", gen.run)
        emb = WatermarkEmbeddingCircuit(blk, g["watermark"])
        e = timed("base embedding", emb.run)
        ext = WatermarkExtractionCircuit(e["watermarked_block"], g["watermark"])
        x = timed("base extraction", ext.run)
        lean = LeanGenerationCircuit(blk)
        lg = timed("lean generation", lean.run)
        shallow = ShallowGenerationCircuit(blk)
        sg = timed("shallow CLA generation", shallow.run)
        sup = timed("NEQR superposition PPB", lambda: run_neqr_ppb_superposition(blk.astype(np.uint8)))
        gc_lean = gate_counts(compile_logical(BlockTask("ln", "lean", "generation", lean.circuit, [lean.circuit.find_bit(q).index for q in lean.layout.out], trace["watermark"])))
        gc_sh = gate_counts(compile_logical(BlockTask("sh", "shallow", "generation", shallow.circuit, [shallow.circuit.find_bit(q).index for q in shallow.layout.out], trace["watermark"])))
        circuits = [
            {"name": "Base generation (RPA + D4 + CNOT)", "qubits": gen.circuit.num_qubits, "result": f"PPB {g['ppb']}  AA {g['aa']}  Wb {''.join(map(str, g['watermark']))}"},
            {"name": "Base embedding (RPA + QE + Pauli-X)", "qubits": emb.circuit.num_qubits, "result": f"|W> = {e['watermarked_pixels']}"},
            {"name": "Base extraction (RPS + QE + Pauli-X)", "qubits": ext.circuit.num_qubits, "result": f"raw {''.join(map(str, x['raw_bits']))} -> Wb {''.join(map(str, x['extracted_bits']))}"},
            {"name": "Lean generation (Cuccaro + uncompute)", "qubits": lean.circuit.num_qubits, "result": f"Wb {''.join(map(str, lg['watermark']))}, depth {gc_lean['depth']}, 2Q={gc_lean['two_qubit_gates']}, clean={lg['pixels_restored'] and lg['ancillas_clean']}"},
            {"name": "v3 Shallow generation (Brent-Kung CLA)", "qubits": shallow.circuit.num_qubits, "result": f"Wb {''.join(map(str, sg['watermark']))}, depth {gc_sh['depth']} (vs {gc_lean['depth']}), clean={sg['ancillas_clean']}"},
            {"name": "v3 NEQR pixel superposition PPB (Statevector)", "qubits": sup["qubits"], "result": f"all 4 coords uniform={sup['uniform']}, exact_ppb={sup['exact_match']}, anc_clean={sup['ancilla_clean_prob']:.6f}"},
        ]
        if s["mode"] in ("keyed", "keyed-opt"):
            cur = s["attacked"][2 * r : 2 * r + 2, 2 * c : 2 * c + 2]
            bv = BlindVerificationCircuit(cur, s["key"], s["nonce"], s["cover"].shape, r, c)
            v = timed("keyed blind verification", bv.run)
            sbv = ShallowBlindVerificationCircuit(cur, s["key"], s["nonce"], s["cover"].shape, r, c)
            sv = timed("shallow blind verification", sbv.run)
            circuits.append({"name": "Keyed blind verification (current image)", "qubits": bv.circuit.num_qubits, "result": "authentic" if v["authentic"] else "TAMPERED"})
            circuits.append({"name": "v3 Shallow blind verification (CLA)", "qubits": sbv.circuit.num_qubits, "result": f"{'authentic' if sv['authentic'] else 'TAMPERED'}, anc_clean={sv['ancillas_clean']}"})
        buf = io.BytesIO()
        with _MPL_LOCK:
            fig = neqr_block_circuit(blk).draw("mpl", fold=-1, scale=0.55)
            fig.savefig(buf, format="png", dpi=90, bbox_inches="tight")
            plt.close(fig)
        return {
            "row": r,
            "col": c,
            "pixels": blk.ravel().tolist(),
            "binary": [format(int(v), "08b") for v in blk.ravel()],
            "trace": {"ppb": trace["ppb"], "sum": trace["sum"], "aa": trace["aa"], "watermark": trace["watermark"]},
            "circuits": circuits,
            "timings_ms": timings,
            "neqr": "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii"),
        }

    def resources(self) -> dict:
        import csv

        path = RESULTS / "nisq" / "nisq_resources.csv"
        if not path.exists():
            return {"rows": [], "note": "run `qwm nisq` to generate the table"}
        with path.open() as fh:
            return {"rows": list(csv.DictReader(fh))}

    def nisq_block(self, req: dict) -> dict:
        from qwm.circuits import ShallowGenerationCircuit
        from qwm.circuits.lean import LeanGenerationCircuit
        from qwm.nisq import BlockTask, compile_logical, gate_counts, thermal_success_probability
        from qwm.watermark import block_watermark_bits

        s = self._session(req["session"])
        r, c = int(req.get("row", 0)), int(req.get("col", 0))
        hb, wb = s["cover"].shape[0] // 2, s["cover"].shape[1] // 2
        if not (0 <= r < hb and 0 <= c < wb):
            raise ValueError("block outside the image")
        blk = s["cover"][2 * r : 2 * r + 2, 2 * c : 2 * c + 2].astype(int)
        expected = block_watermark_bits(blk)
        p2 = float(req.get("p2", 5e-4))
        t1 = float(req.get("t1_us", 300.0)) * 1e-6
        t2 = 0.65 * t1
        shots = int(min(max(int(req.get("shots", 250)), 50), 1000))

        lg = LeanGenerationCircuit(blk)
        sg = ShallowGenerationCircuit(blk)
        tasks = [
            ("Lean generation (44q Cuccaro)", BlockTask("lean", "lean", "generation", lg.circuit, [lg.circuit.find_bit(q).index for q in lg.layout.out], expected)),
            ("Shallow CLA generation (69q BK)", BlockTask("shallow", "shallow", "generation", sg.circuit, [sg.circuit.find_bit(q).index for q in sg.layout.out], expected)),
        ]
        rows = []
        for label, t in tasks:
            compiled = compile_logical(t)
            gc = gate_counts(compiled)
            res = thermal_success_probability(compiled, t.expected_key, t1=t1, t2=t2, p2=p2, shots=shots, seed=7)
            rows.append(
                {
                    "name": label,
                    "qubits": t.circuit.num_qubits,
                    "two_qubit_gates": gc["two_qubit_gates"],
                    "depth": gc["depth"],
                    "duration_us": res["duration_us"],
                    "success": res["success"],
                    "bit_error_rate": res["bit_error_rate"],
                }
            )
        return {"row": r, "col": c, "p2": p2, "t1_us": t1 * 1e6, "t2_us": t2 * 1e6, "shots": shots, "rows": rows}

    def paper_summary(self) -> dict:
        from qwm.circuits import WatermarkEmbeddingCircuit, WatermarkGenerationCircuit
        from qwm.paper_checks import check_table9, psnr_bounds_2bpp
        from qwm.resources import complexity_comparison, measure_all_families, reported_resources
        from qwm.watermark import block_trace

        worked = [[50, 60], [48, 32]]
        tr = block_trace(worked)
        wb = WatermarkGenerationCircuit(worked).run()["watermark"]
        emb = WatermarkEmbeddingCircuit(worked, wb)
        t9 = check_table9()
        return {
            "worked": {
                "block": worked,
                "ppb": tr["ppb"],
                "sum": tr["sum"],
                "aa": tr["aa"],
                "watermark": wb,
                "watermarked_paper": emb.run()["watermarked_pixels"],
                "unitary_inverse": emb.verify_unitary_inverse()["exact_unitary_inverse"],
            },
            "table21": reported_resources(8)["table21"],
            "circuit_families": measure_all_families(worked),
            "table9": t9,
            "table9_violations": sum(not row["consistent"] for row in t9),
            "psnr_bounds": psnr_bounds_2bpp(),
            "complexity": complexity_comparison(),
        }


# --------------------------------------------------------------------------- #
# HTTP layer
# --------------------------------------------------------------------------- #
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png"}


def make_handler(app: DemoApp):
    class Handler(BaseHTTPRequestHandler):
        server_version = "qwm-demo"

        def log_message(self, fmt, *args):  # quiet
            pass

        def _send(self, status: int, body: bytes, ctype: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, payload) -> None:
            self._send(status, json.dumps(payload, default=float).encode("utf-8"), "application/json")

        def do_GET(self):  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path == "/api/meta":
                return self._json(200, app.meta())
            if path == "/api/resources":
                return self._json(200, app.resources())
            if path == "/api/paper":
                return self._json(200, app.paper_summary())
            if path in ("/", "/index.html"):
                path = "/index.html"
            target = (STATIC / path.lstrip("/")).resolve()
            if STATIC not in target.parents or not target.is_file():
                return self._send(404, b"not found", "text/plain")
            return self._send(200, target.read_bytes(), CONTENT_TYPES.get(target.suffix, "application/octet-stream"))

        def do_POST(self):  # noqa: N802
            routes = {
                "/api/embed": app.embed,
                "/api/attack": app.attack,
                "/api/verify": app.verify,
                "/api/classify": app.classify,
                "/api/block": app.block,
                "/api/nisq_block": app.nisq_block,
            }
            fn = routes.get(self.path)
            if fn is None:
                return self._json(404, {"error": "not found"})
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return self._json(400, {"error": "invalid Content-Length"})
            if length < 0:
                return self._json(400, {"error": "invalid Content-Length"})
            if length > MAX_BODY:
                return self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "request too large"})
            try:
                req = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(req, dict):
                    raise ValueError("expected a JSON object")
                return self._json(200, fn(req))
            except (KeyError, ValueError) as exc:
                return self._json(400, {"error": str(exc).strip("'")})
            except Exception as exc:  # pragma: no cover - surfaced to the UI
                return self._json(500, {"error": f"{type(exc).__name__}: {exc}"})

    return Handler


def make_server(host: str = "127.0.0.1", port: int = 8765, prepare_classifier: bool = True) -> tuple[ThreadingHTTPServer, DemoApp]:
    """Create (but do not start) the demo server; ``port=0`` picks a free port."""
    # Secondary threads get a 512 KiB stack on macOS, which Qiskit's Rust core
    # overflows (segmentation fault) when a circuit is built on a request
    # thread.  Give every thread created from now on a generous stack and
    # initialise Qiskit once on the calling thread.
    threading.stack_size(64 * 1024 * 1024)
    from qiskit import QuantumCircuit, QuantumRegister

    QuantumCircuit(QuantumRegister(2, "warmup")).cx(0, 1)
    app = DemoApp(prepare_classifier=prepare_classifier)
    httpd = ThreadingHTTPServer((host, port), make_handler(app))
    httpd.daemon_threads = True
    return httpd, app


def serve(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    httpd, _ = make_server(host, port)
    url = f"http://{host}:{httpd.server_address[1]}/"
    print(f"qwm demo running on {url}  (Ctrl+C to stop)", flush=True)
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover
        pass
    finally:
        httpd.server_close()
