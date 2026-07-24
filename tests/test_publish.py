"""Static site generator: structure, quiz payload, and progress plumbing."""
import json
import re
from pathlib import Path

import pytest

from bridge_trainer.app.publish import publish

PROBLEMS = Path("tests/fixtures")


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


COMP = "comp_3s_over_3h"


def _payload(root, pid, k):
    html = (root / pid / f"v{k}" / "index.html").read_text()
    m = re.search(r"const V = (\{.*?\});\n", html)
    assert m, "quiz payload missing"
    return json.loads(m.group(1))


def test_quiz_payload_is_valid_json_with_verdict(site):
    root, entries = site
    payload = _payload(root, COMP, 0)
    assert payload["pid"] == COMP
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
    pages = [(root / COMP / f"v{k}" / "index.html").read_text()
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


def test_republish_skips_unchanged_variants(tmp_path, monkeypatch):
    """PERF-D-10: a second publish re-runs only v0 per problem (needed for the
    entry metadata); already-stamped k>0 variants are skipped, and bumping
    TEMPLATE_VERSION forces a full re-render again."""
    import bridge_trainer.app.publish as pub

    root, cache = tmp_path / "site", tmp_path / "cache"
    calls = {"n": 0}
    real = pub.run_problem

    def counting(*a, **k):
        calls["n"] += 1
        return real(*a, **k)
    monkeypatch.setattr(pub, "run_problem", counting)

    entries = publish(PROBLEMS, root, seed=7, n_override=48, cache_dir=cache,
                      variants_override=2)
    first = calls["n"]
    assert first == len(entries) * 2                # v0 + v1 per problem

    v1 = root / entries[0].id / "v1" / "index.html"
    before = v1.stat().st_mtime_ns

    calls["n"] = 0
    publish(PROBLEMS, root, seed=7, n_override=48, cache_dir=cache,
            variants_override=2)
    assert calls["n"] == len(entries)               # only v0 re-ran; v1 skipped
    assert v1.stat().st_mtime_ns == before          # v1 not rewritten

    calls["n"] = 0
    monkeypatch.setattr(pub, "TEMPLATE_VERSION", pub.TEMPLATE_VERSION + 1)
    publish(PROBLEMS, root, seed=7, n_override=48, cache_dir=cache,
            variants_override=2)
    assert calls["n"] == len(entries) * 2           # template bump re-renders all


def test_republish_regrows_when_total_changes(tmp_path, monkeypatch):
    """A grown `total` must re-render existing variants too, since each page
    bakes the absolute deal counter / nextUnseen bound (PERF-D-10 correctness)."""
    import bridge_trainer.app.publish as pub

    root, cache = tmp_path / "site", tmp_path / "cache"
    publish(PROBLEMS, root, seed=7, n_override=48, cache_dir=cache,
            variants_override=2)
    v1 = root / "comp_3s_over_3h" / "v1" / "index.html"
    assert "/ 2</span>" in v1.read_text()           # counter shows total=2

    calls = {"n": 0}
    real = pub.run_problem
    monkeypatch.setattr(pub, "run_problem",
                        lambda *a, **k: (calls.__setitem__("n", calls["n"] + 1),
                                         real(*a, **k))[1])
    publish(PROBLEMS, root, seed=7, n_override=48, cache_dir=cache,
            variants_override=3)                     # total grows 2 -> 3
    assert calls["n"] > 0                            # not fully skipped
    assert "/ 3</span>" in v1.read_text()            # v1's counter updated


def test_mobile_viewport_everywhere(site):
    root, entries = site
    for page in (root / "index.html",
                 root / entries[0].id / "index.html",
                 root / entries[0].id / "v0" / "index.html",
                 root / entries[0].id / "v0" / "report.html"):
        assert 'name="viewport"' in page.read_text(), page
