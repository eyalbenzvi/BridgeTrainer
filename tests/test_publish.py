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
    entries = publish(PROBLEMS, root, seed=7, n_override=48, cache_dir=cache,
                      variants_override=3)
    return root, entries


def test_site_structure(site):
    root, entries = site
    assert (root / "index.html").exists()
    assert (root / ".nojekyll").exists()
    for e in entries:
        assert e.variants == 3
        assert (root / e.id / "index.html").exists()  # redirect page
        for k in range(e.variants):
            assert (root / e.id / f"v{k}" / "index.html").exists()
            assert (root / e.id / f"v{k}" / "report.html").exists()


def _payload(root, entries, k):
    html = (root / entries[0].id / f"v{k}" / "index.html").read_text()
    m = re.search(r"const V = (\{.*?\});\n", html)
    assert m, "quiz payload missing"
    return json.loads(m.group(1))


def test_quiz_payload_is_valid_json_with_verdict(site):
    root, entries = site
    payload = _payload(root, entries, 0)
    assert payload["pid"] == entries[0].id
    assert payload["k"] == 0 and payload["total"] == 3
    actions = {c["action"] for c in payload["corrected"]}
    assert set(payload["accepted"]) <= actions
    assert {"P", "3S", "X"} == actions
    # Both views present (INV5), and every candidate row carries EV + CI.
    for view in ("raw", "corrected"):
        for row in payload[view]:
            assert "ev" in row and "ci" in row and "vs" in row


def test_variants_have_distinct_hands_and_v0_is_authored(site):
    root, entries = site
    pages = [(root / entries[0].id / f"v{k}" / "index.html").read_text()
             for k in range(3)]
    # v0 shows the authored hand (K93 in spades).
    assert "K93" in pages[0].replace("&#9824; K93", "K93")
    hands = []
    for page in pages:
        m = re.search(r'<div class="hand">(.*?)</div>', page, re.S)
        hands.append(m.group(1))
    assert len(set(hands)) == 3, "variants should deal different hands"


def test_quiz_page_never_leaks_verdict_before_answer(site):
    root, entries = site
    html = (root / entries[0].id / "v0" / "index.html").read_text()
    # The verdict block starts hidden and is only populated by JS.
    assert 'id="verdict"' in html
    assert "#verdict { display: none; }" in html
    assert "Next deal" in html


def test_index_lists_all_problems_with_variant_totals(site):
    root, entries = site
    html = (root / "index.html").read_text()
    for e in entries:
        assert f'href="{e.id}/index.html"' in html
        assert f'data-total="{e.variants}"' in html


def test_redirect_page_targets_first_unanswered(site):
    root, entries = site
    html = (root / entries[0].id / "index.html").read_text()
    assert "location.replace" in html
    assert 'href="v0/index.html"' in html  # no-JS fallback


def test_mobile_viewport_everywhere(site):
    root, entries = site
    for page in (root / "index.html",
                 root / entries[0].id / "index.html",
                 root / entries[0].id / "v0" / "index.html",
                 root / entries[0].id / "v0" / "report.html"):
        assert 'name="viewport"' in page.read_text(), page
