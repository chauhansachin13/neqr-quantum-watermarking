"""Tests for the grounded project & research-paper Q&A assistant."""

import json
import threading
import urllib.request

import pytest

from qwm.assistant import ProjectAssistant
from qwm.web.server import make_server


@pytest.fixture(scope="module")
def qa():
    return ProjectAssistant()


def test_grounded_project_and_paper_queries(qa):
    res_neqr = qa.ask("Why is NEQR used instead of FRQI?")
    assert res_neqr["grounded"] is True
    assert "4,194,304" in res_neqr["answer"] and "4,294,967,296" in res_neqr["answer"]
    assert any("Base Paper" in s or "Table 11" in s for s in res_neqr["sources"])

    res_v3 = qa.ask("How does v3 Dual-Partner 8x8 Haar self-recovery heal damage?")
    assert res_v3["grounded"] is True
    assert "8x8" in res_v3["answer"] and "99.9%" in res_v3["answer"]

    res_table9 = qa.ask("What consistency issue did qwm paper-checks find in Table 9?")
    assert res_table9["grounded"] is True
    assert "6" in res_table9["answer"] and "Fuchs" in res_table9["answer"]

    res_wm = qa.ask("How does watermarking work step by step on the airplane example?")
    assert res_wm["grounded"] is True
    assert "2x2" in res_wm["answer"] and "PPB" in res_wm["answer"]


def test_out_of_scope_query_is_declined(qa):
    res = qa.ask("Who won the FIFA World Cup in 2022 and what is Bitcoin price today?")
    assert res["grounded"] is False
    assert "Sahu et al." in res["answer"]
    assert res["sources"] == []


def test_empty_and_too_long_queries_raise(qa):
    with pytest.raises(ValueError, match="enter a question"):
        qa.ask("   ")
    with pytest.raises(ValueError, match="under 500"):
        qa.ask("x" * 501)


def test_api_ask_endpoint():
    httpd, _ = make_server("127.0.0.1", 0, prepare_classifier=False)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        req = urllib.request.Request(
            f"{base}/api/ask",
            data=json.dumps({"question": "How many qubits do the lean circuits use?"}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            body = json.loads(r.read())
        assert r.status == 200 and body["grounded"] is True and "44" in body["answer"]
    finally:
        httpd.shutdown()
        httpd.server_close()
