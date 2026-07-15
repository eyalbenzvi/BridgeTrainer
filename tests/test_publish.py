"""Static site generator: structure, quiz payload, and progress plumbing."""
import json
import re
from pathlib import Path

import pytest

from bridge_trainer.app.publish import publish

PROBLEMS = Path("problems")


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    root = tmp_path_factory.mktemp("site")
    cache = tmp_path_factory.mktemp("cache")
    entries = publish(PROBLEMS, root, seed=7, n_override=48, cache_dir=cache)
    return root, entries


def test_site_structure(site):
    root, entries = site
    assert (root / "index.html").exists()
    assert (root / ".nojekyll").exists()
    for e in entries:
        assert (root / e.id / "index.html").exists()
        assert (root / e.id / "report.html").exists()


def test_quiz_payload_is_valid_json_with_verdict(site):
    root, entries = site
    html = (root / entries[0].id / "index.html").read_text()
    m = re.search(r"const V = (\{.*?\});\n", html)
    assert m, "quiz payload missing"
    payload = json.loads(m.group(1))
    assert payload["id"] == entries[0].id
    actions = {c["action"] for c in payload["corrected"]}
    assert set(payload["accepted"]) <= actions
    assert {"P", "3S", "X"} == actions
    # Both views present (INV5), and every candidate row carries EV + CI.
    for view in ("raw", "corrected"):
        for row in payload[view]:
            assert "ev" in row and "ci" in row and "vs" in row


def test_quiz_page_never_leaks_verdict_before_answer(site):
    root, entries = site
    html = (root / entries[0].id / "index.html").read_text()
    # The verdict block starts hidden and is only populated by JS.
    assert 'id="verdict"' in html
    assert "#verdict { display: none; }" in html


def test_index_lists_all_problems(site):
    root, entries = site
    html = (root / "index.html").read_text()
    for e in entries:
        assert f'href="{e.id}/index.html"' in html


def test_mobile_viewport_everywhere(site):
    root, entries = site
    for page in (root / "index.html",
                 root / entries[0].id / "index.html",
                 root / entries[0].id / "report.html"):
        assert 'name="viewport"' in page.read_text(), page
