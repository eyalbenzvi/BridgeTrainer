"""Integration tests: the local analyze server end-to-end over HTTP."""
from __future__ import annotations

import json
import threading
import urllib.request

import pytest

from bridge_trainer.analysis.server import serve

PAYLOAD = {
    "dealer": "E", "vul": "Both", "my_seat": "S",
    "my_hand": "AQ2.KJ3.KQ54.A32",
    "auction": ["2H", "X", "P", "3S", "P", "4S", "P", "P", "P"],
    "decision_indices": [1],
    "system": "two_over_one", "scoring": "IMP",
    "candidates": ["X", "3NT", "P"],
    "overrides": {}, "seed": 11, "max_deals": 150,
}


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    import os
    os.environ["BT_ANALYSIS_ENGINE"] = "legacy"   # tests run w/o the Ben venv
    reports = tmp_path_factory.mktemp("reports")
    httpd = serve(port=0, reports_dir=reports, open_browser=False)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}"
    httpd.shutdown()


def test_serves_analyze_page(server):
    with urllib.request.urlopen(server + "/") as r:
        body = r.read().decode()
    assert r.status == 200
    assert 'dir="rtl"' in body
    assert "תיבת" in body or "ניתוח הכרזה" in body
    assert 'id="bbox"' in body and 'id="picker"' in body


def test_analyze_endpoint_full_flow(server):
    req = urllib.request.Request(
        server + "/api/analyze",
        data=json.dumps(PAYLOAD).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=600) as r:
        data = json.loads(r.read())
    assert data["ok"]
    (rep,) = data["reports"]
    assert rep["decision_index"] == 1
    assert rep["actual"] == "X"
    assert rep["n_deals"] >= 100

    # the saved HTML report is served back and is a full spec-4.1 document
    with urllib.request.urlopen(server + rep["html_url"]) as r:
        html_doc = r.read().decode()
    assert "חלוקות מייצגות" in html_doc and "rec-banner" in html_doc

    with urllib.request.urlopen(server + rep["json_url"]) as r:
        facts = json.loads(r.read())
    assert facts["candidates"] == ["X", "3NT", "P"]

    if rep["pdf_url"]:
        with urllib.request.urlopen(server + rep["pdf_url"]) as r:
            assert r.read()[:5] == b"%PDF-"


def test_analyze_rejects_bad_payload(server):
    bad = dict(PAYLOAD, auction=["2H", "2H"], decision_indices=[1])
    req = urllib.request.Request(
        server + "/api/analyze", data=json.dumps(bad).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req, timeout=60)
    assert exc.value.code == 400
    body = json.loads(exc.value.read())
    assert not body["ok"] and "illegal" in body["error"]


def test_no_path_traversal(server):
    req = urllib.request.Request(server + "/reports/../../etc/passwd")
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req, timeout=10)
    assert exc.value.code == 404
