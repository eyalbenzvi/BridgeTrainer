"""Wave E — CSS / a11y / RTL / UX round-3 findings (source-level guards; the
visual behaviour is verified manually, but the wiring is pinned here)."""
from __future__ import annotations

import re

from bridge_trainer.app.webapp import (_CSS, _SHARED_JS, _dashboard_html,
                                        _index_html, _lead_html, _problem_html)


# ---- UX-A-6: suit glyphs carry VS15 and force text rendering ----------------
def test_suit_glyphs_have_variation_selector():
    assert "\\u2660\\uFE0E" in _SHARED_JS and "\\u2665\\uFE0E" in _SHARED_JS
    assert "\\u2666\\uFE0E" in _SHARED_JS and "\\u2663\\uFE0E" in _SHARED_JS
    assert "font-variant-emoji: text" in _CSS


# ---- UX-A-5: signed EV / bar values are LTR-isolated ------------------------
def test_signed_numbers_are_ltr_isolated():
    ev = re.search(r"\.opt \.ev \{[^}]*\}", _CSS, re.S).group(0)
    assert "unicode-bidi: isolate" in ev and "direction: ltr" in ev
    bar = re.search(r"^\.barval \{[^}]*\}", _CSS, re.S | re.M).group(0)
    assert "unicode-bidi: isolate" in bar


# ---- UX-A-8: difficulty segments expose aria-pressed ------------------------
def test_difficulty_segments_have_aria_pressed():
    idx = _index_html()
    # the diff-seg buttons are BUILT with aria-pressed (the finding's change)
    assert 'data-level="${lv}" aria-pressed="false"' in idx
    # ...and applyFilterUi keeps it in sync alongside the .active class
    assert 'b.setAttribute("aria-pressed", on ? "true" : "false")' in idx
    assert "box-shadow: inset 0 -3px 0 var(--accent)" in _CSS  # non-colour cue


# ---- UX-A-9: wide tables scroll on phones; desktop keeps full width ---------
def test_wide_tables_and_breakpoint():
    assert "#ctable, #rtable, #ltable" in _CSS
    assert "overflow-x: auto" in _CSS
    # the display:block scroll is scoped to a mobile breakpoint (desktop keeps
    # normal full-width tables)
    assert "@media (max-width: 600px)" in _CSS
    assert "@media (max-width: 380px)" in _CSS


# ---- UX-A-10: tap targets + token-following tint ----------------------------
def test_tap_targets_and_no_hardcoded_tint():
    assert "#C8102E0A" not in _CSS                 # all 3 replaced
    assert _CSS.count("color-mix(in srgb, var(--loss) 4%, transparent)") == 3
    alllink = re.search(r"\.alllink \{[^}]*\}", _CSS, re.S).group(0)
    assert "min-height: 24px" in alllink
    assert ".infot::after" in _CSS and "button.gloss::after" in _CSS


# ---- PERF-F-8 / UX-I-4: head theme snippet + lead skeleton + guidance -------
def test_theme_applied_in_head_on_every_page():
    for page in (_index_html(), _problem_html(), _lead_html(), _dashboard_html()):
        # the inline snippet runs before the stylesheet link
        head = page[:page.index("app.css")]
        assert "localStorage.getItem('bt_theme')" in head
        assert "setAttribute('data-theme'" in head


def test_lead_has_skeleton_and_bidding_has_guidance():
    lead = _lead_html()
    assert 'id="modebanner"><div class="skl"' in lead
    assert 'id="problem"><div class="skl"' in lead
    assert "הקש הכרזה במכרז כדי לראות" in _problem_html()   # parity hint


# ---- UX-I-5: clear-filters dead end -----------------------------------------
def test_clear_filter_guidance_and_disabled_cta():
    idx = _index_html()
    assert 'id="hint-diff"' in idx and 'id="hint-type"' in idx
    assert 'getElementById("hint-diff").hidden' in idx
    assert 'aria-disabled' in idx                  # dead CTA marked disabled
    assert 'deal.setAttribute("tabindex", "-1")' in idx


# ---- UX-I-6: session run no longer leaks ------------------------------------
def test_session_ttl_kind_and_summary_persistence():
    assert "SESSION_TTL_MS" in _SHARED_JS
    assert "Date.now() - s.startedAt > SESSION_TTL_MS" in _SHARED_JS
    assert "kind !== s.kind) return;" in _SHARED_JS   # out-of-scenario guard
    assert "startedAt: Date.now()" in _index_html()
    summ = _index_html()
    # the summary is NOT deleted on render (only on an explicit action)
    body = summ[summ.index("function renderSessionSummary"):]
    body = body[:body.index("if (document.readyState")]
    assert 'localStorage.removeItem("bt_session")' not in \
        body[:body.index("const endRun")]
    assert 'id="sum-close"' in summ


# ---- UX-A-7 / UX-I-9: radiogroup restructured -------------------------------
def test_mode_selector_moved_out_of_radio_and_roving_tabindex():
    idx = _index_html()
    # the MP/IMP pills live in a wrapper AFTER the scenario cards, not inside a
    # role="radio" element
    assert '<div class="modewrap" id="modewrap"' in idx
    assert idx.index('id="modewrap"') > idx.index('id="count-lead"')
    # the lead card no longer wraps the pills
    lead_card = idx[idx.index('data-kind="lead"'):idx.index('id="modewrap"')]
    assert "modepills" not in lead_card
    # roving tabindex + arrow-key navigation
    assert "c.tabIndex = on ? 0 : -1" in idx
    assert "ArrowRight" in idx and "ArrowLeft" in idx and "moveScen" in idx
