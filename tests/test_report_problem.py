"""Report-a-problem affordance on the two problem pages.

Every problem page (bidding p.html, opening-lead lead.html) carries a discreet
"⚑" flag in the topbar that opens a bottom sheet: the user picks one fault
type, may add free text, and sends the report over WhatsApp (a wa.me deep link
to a fixed number — no backend). The message must name the problem id, its
type, the chosen answer, the fault, optional detail, and a link back to the
problem. Both scenarios wire the same shared openReport() so the machinery
lives once in _SHARED_JS.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile

import pytest

from bridge_trainer.app.webapp import (_CSS, _SHARED_JS, _lead_html,
                                       _problem_html)
from test_home_early_click import _extract_function

needs_node = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node not available")

# the exact fault list the product spec asks for, in order
REASONS = [
    "הכרזה לא הגיונית",
    "הסבר לא מתאים להכרזה",
    "חסרה אפשרות הכרזה",
    "ניקוד לא הגיוני",
    "ניתוח יד לא הגיוני",
    "באג בתוכנה",
]


def test_report_reasons_and_phone_are_defined_once():
    for r in REASONS:
        assert f'"{r}"' in _SHARED_JS, f"missing fault reason: {r}"
    # the destination number is a single source of truth in the shared JS
    assert _SHARED_JS.count('REPORT_PHONE = "972547918413"') == 1


def test_whatsapp_message_carries_every_required_field():
    build = _extract_function(_SHARED_JS, "buildReportSheet")
    # a wa.me deep link built from the fixed number
    assert '"https://wa.me/" + REPORT_PHONE + "?text=" +' in build
    assert "encodeURIComponent(lines.join(" in build
    assert "window.open(url" in build
    # every field the spec requires
    assert "מזהה בעיה: " in build          # problem id
    assert "סוג הבעיה: " in build          # problem type
    assert "התשובה שנבחרה: " in build      # chosen answer
    assert "התקלה: " + "" in build         # selected fault (concatenated below)
    assert "_reportReason" in build
    assert "פירוט: " in build              # free text
    assert "קישור: " in build              # link back to the problem


def test_send_is_gated_until_a_fault_is_chosen():
    build = _extract_function(_SHARED_JS, "buildReportSheet")
    # the send button ships disabled and is enabled only once a chip is picked
    assert '"#rep-send"' in build
    assert "sendBtn.disabled = false" in build
    open_fn = _extract_function(_SHARED_JS, "openReport")
    assert 'disabled = true' in open_fn     # reset on every open


@pytest.mark.parametrize("html_fn", [_problem_html, _lead_html])
def test_problem_pages_expose_and_wire_the_report_flag(html_fn):
    html = html_fn()
    # a hidden topbar flag that the page reveals once the problem loads
    assert 'id="report-open"' in html
    assert 'class="reportbtn"' in html
    init = _extract_function(html, "init")
    # wired with the live context: id, hebrew type, url, and chosen answer
    assert "wireReport(" in init
    assert "id: P.id" in init
    assert "type: reportTypeLabel(P)" in init
    assert "url: location.href" in init
    assert "answer: LAST_ANSWER" in init
    # the chosen call is captured at reveal time so a report can name it
    assert "LAST_ANSWER = chosen" in _extract_function(html, "reveal")


def test_report_styles_are_present():
    for sel in [".reportbtn", ".repchip", ".reptext", ".sendbtn"]:
        assert sel in _CSS, f"missing style: {sel}"


@needs_node
def test_reportTypeLabel_prefixes_scenario_and_uses_hebrew_type():
    fn = _extract_function(_SHARED_JS, "reportTypeLabel")
    harness = (
        fn
        + """
        function kindOf(p) { return p.kind || "bidding"; }
        const TYPE_NAMES = { overcall: ["יד גבולית", "tip"] };
        console.log(JSON.stringify([
          reportTypeLabel({ classification: { type: "overcall" } }),
          reportTypeLabel({ kind: "lead", type: "overcall" }),
          reportTypeLabel({ kind: "lead", classification: { type: "unknown" } }),
        ]));
        """
    )
    fd, path = tempfile.mkstemp(suffix=".js")
    try:
        os.write(fd, harness.encode("utf-8"))
        os.close(fd)
        res = subprocess.run(["node", path], capture_output=True, text=True)
        assert res.returncode == 0, res.stderr
        bidding, lead, unknown = json.loads(res.stdout.strip().splitlines()[-1])
    finally:
        os.unlink(path)
    assert bidding == "הכרזה · יד גבולית"
    assert lead == "הובלה · יד גבולית"
    assert unknown == "הובלה"      # falls back to the scenario alone
