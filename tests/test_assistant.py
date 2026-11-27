"""Tests for the first-person Hybrid RAG project & research-paper assistant."""

import json
import threading
import urllib.request

import pytest

from qwm.assistant import ProjectAssistant
from qwm.web.server import make_server


@pytest.fixture(scope="module")
def qa():
    return ProjectAssistant()


def test_first_person_tests_and_project_queries(qa):
    res_tests = qa.ask("what tests u did?")
    assert res_tests["grounded"] is True
    assert "I built" in res_tests["answer"] and "pytest" in res_tests["answer"] and "202" in res_tests["answer"]
    assert "i will answer" not in res_tests["answer"].lower()

    res_neqr = qa.ask("Why is NEQR used instead of FRQI?")
    assert res_neqr["grounded"] is True
    assert "4,194,304" in res_neqr["answer"] and "4,294,967,296" in res_neqr["answer"]

    res_v3 = qa.ask("How does v3 Dual-Partner 8x8 Haar self-recovery heal damage?")
    assert res_v3["grounded"] is True
    assert "8×8" in res_v3["answer"] or "8x8" in res_v3["answer"]
    assert "99.9%" in res_v3["answer"]

    res_table9 = qa.ask("What bugs did paper-checks find in Table 9?")
    assert res_table9["grounded"] is True
    assert "6 of 16" in res_table9["answer"] and "Fuchs" in res_table9["answer"]

    res_bugs_base = qa.ask("What bugs did you find in the base paper?")
    assert res_bugs_base["grounded"] is True and res_bugs_base["topic_id"] == "table9_checks"

    res_wm = qa.ask("How does watermarking work step by step on the airplane?")
    assert res_wm["grounded"] is True
    assert "2×2" in res_wm["answer"] and "PPB" in res_wm["answer"]


def test_greetings_followups_and_out_of_scope(qa):
    hello = qa.ask("hi")
    assert hello["grounded"] is True and "PhotoShield" in hello["answer"] or "NEQR" in hello["answer"]

    first = qa.ask("How many qubits do the lean circuits use?")
    assert first["grounded"] is True and "44" in first["answer"]

    followup = qa.ask("tell me more", last_topic=first["topic_id"])
    assert followup["grounded"] is True

    off_topic = qa.ask("Who won the FIFA World Cup in 2022 and what is Bitcoin price today?")
    assert off_topic["grounded"] is False
    assert "outside" in off_topic["answer"]
    assert "i can only answer" not in off_topic["answer"].lower()


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
            data=json.dumps({"question": "What tests did you run?", "last_topic": "overview"}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            body = json.loads(r.read())
        assert r.status == 200 and body["grounded"] is True and "202" in body["answer"]
    finally:
        httpd.shutdown()
        httpd.server_close()
