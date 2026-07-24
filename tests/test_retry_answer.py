"""Re-attempt an answered problem (task T17 / UX-I-3).

The dashboard promises a "review" loop, but an answered problem used to lock
its buttons forever. Now both trainer pages show a "try again" button (and the
dashboard/summary links deep-link with ?retry=1) that re-opens the problem;
the re-answer records via BT.record (attemptCount++) but keeps the first score
and must NOT count toward the practice session.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile

import pytest

from bridge_trainer.app.webapp import (_dashboard_html, _index_html,
                                       _lead_html, _problem_html)
from tests.test_home_early_click import _extract_function

needs_node = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node not available")


@needs_node
def test_routeFor_appends_retry_flag():
    fn = _extract_function(_index_html(), "routeFor")
    harness = (
        fn
        + """
        function leadMode() { return 'MP'; }
        console.log(JSON.stringify([
          routeFor('bidding', 'abc'),
          routeFor('bidding', 'abc', { retry: true }),
          routeFor('lead', 'x y', { retry: true }),
        ]));
        """
    )
    fd, path = tempfile.mkstemp(suffix=".js")
    try:
        os.write(fd, harness.encode("utf-8"))
        os.close(fd)
        res = subprocess.run(["node", path], capture_output=True, text=True)
        assert res.returncode == 0, res.stderr
        plain, retry, lead = json.loads(res.stdout.strip().splitlines()[-1])
    finally:
        os.unlink(path)
    assert plain == "p.html?id=abc"
    assert retry == "p.html?id=abc&retry=1"
    assert lead.startswith("lead.html?id=x%20y&mode=MP") and lead.endswith("&retry=1")


@pytest.mark.parametrize("html_fn", [_problem_html, _lead_html])
def test_answered_problem_offers_retry_without_polluting_score_or_session(html_fn):
    js = html_fn()
    reveal = _extract_function(js, "reveal")
    # a "try again" affordance is injected into the verdict
    assert '"retry-answer"' in reveal
    assert "resetForRetry" in reveal

    reset = _extract_function(js, "resetForRetry")
    assert 'style.display = "none"' in reset      # hides the verdict
    assert "RETRYING = true" in reset
    assert "b.disabled = false" in reset          # re-enables the buttons

    # the commit path allows a re-answer only via RETRYING, records it, but
    # skips bumpSession (so the session/aggregates aren't inflated)
    commit = _extract_function(js, "commit" if "function commit" in js
                               else "choose")
    assert "&& !RETRYING" in commit
    assert "if (!RETRYING) bumpSession" in commit
    assert "RETRYING = false" in commit

    init = _extract_function(js, "init")
    assert 'get("retry") === "1"' in init
    assert "!retryParam" in init                  # ?retry=1 skips auto-reveal


def test_dashboard_and_summary_review_links_use_retry():
    # rendered output (the f-string's doubled braces collapse to single)
    assert "{retry: true}" in _dashboard_html()
    assert "{retry: true}" in _index_html()
