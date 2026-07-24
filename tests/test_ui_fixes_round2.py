"""Guardrails for the round-2 UI fixes (user-requested):

UI-1  the dashboard legend/footnote rides on the felt, so it must use the
      on-felt tone, not the card --muted (dark-green-on-green in light mode).
UI-2  the home lead scenario card reserves a constant #modegoal height so
      toggling MP<->IMP doesn't reflow the layout.
UI-3  the major/minor suit terms read as מייג'ור/מיינור.
UI-4  the ranked-leads table shows a panel score per lead.
UI-5  the ranked-leads table is open by default.
"""
from __future__ import annotations

import json

from bridge_trainer.app.webapp import (_CSS, _dashboard_html, _lead_html,
                                       _taxonomy_he_json)
from bridge_trainer.engine.lead_classify import LEAD_TAXONOMY


def test_ui1_dashboard_footnote_uses_on_felt_tone():
    dash = _dashboard_html()
    assert "#dash { color: var(--on-felt); }" in dash
    assert "#dash .dtab > .footnote { color: var(--on-felt-muted); }" in dash


def test_ui2_modegoal_reserves_constant_height():
    # scoped to the home div by id so the problem-page banner span is untouched
    assert "#modegoal { min-height" in _CSS


def test_ui3_major_minor_transliterated():
    # ARCH-5 made the taxonomy modules the single source; the label/tooltip is
    # injected as window.TAXONOMY_HE (via _taxonomy_he_json), no longer a
    # literal in _SHARED_JS.
    tip = json.loads(_taxonomy_he_json())["lead_suit_game"][1]
    assert "מייג'ור" in tip and "מיינור" in tip
    assert "בגבוה" not in tip and "בנמוך" not in tip
    suit_game = next(t for t in LEAD_TAXONOMY if t[0] == "lead_suit_game")
    assert "מייג'ור" in suit_game[3] and "מיינור" in suit_game[3]


def test_ui4_ranked_leads_table_has_score_column():
    lead = _lead_html()
    # a score header cell and a per-row score chip computed for the active mode
    assert 'glossHtml("panel", "ציון")' in lead
    assert "btScoreChipHtml(btScoreLead(P, r.card, MODE).score, true)" in lead


def test_ui5_ranked_leads_table_open_by_default():
    lead = _lead_html()
    assert '<details open><summary>כל 13 ההובלות, מדורגות</summary>' in lead
