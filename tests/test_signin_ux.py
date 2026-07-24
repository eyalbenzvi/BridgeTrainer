"""First-run / sign-in UX (task T18 / UX-I-2, safe subset).

Per the agreed scope (no full guest mode): the gate now states the product
value and that progress syncs, surfaces a sign-in error with a retry instead of
swallowing it, the misleading "guest — saved locally" copy is gone, and the
bt-save-failed event (from T9) shows a toast. These tests pin those.
"""
from __future__ import annotations

from importlib import resources

import pytest

from bridge_trainer.app.webapp import (_dashboard_html, _index_html,
                                       _lead_html, _problem_html)


def _fb() -> str:
    return (resources.files("bridge_trainer") / "web"
            / "bt-firebase.js").read_text(encoding="utf-8")


def test_gate_states_value_and_surfaces_errors():
    src = _fb()
    # a value/benefit line and the sync promise (not just "sign in")
    assert "משוב מיידי" in src
    assert "מסתנכרנת בין המכשירים" in src
    # a live error region + a retry-safe onclick that catches doSignIn's reject
    assert 'id=\'bt-signin-err\'' in src or 'id="bt-signin-err"' in src
    assert "doSignIn()" in src
    gate = src[src.index('btn.onclick = () => {'):src.index("}\nfunction ungate")]
    assert ".catch(" in gate and ".finally(" in gate
    assert "btn.disabled = true" in gate and "btn.disabled = false" in gate
    # bt-firebase.js is a static file (not a Python string): dashes must be
    # literal, not "\\u2014" escapes that would render as raw text.
    assert "בברידג' —" in src
    assert "0–100" in src


def test_no_misleading_guest_copy():
    js = _index_html()
    assert "ההתקדמות נשמרת מקומית" not in js       # the false promise is gone
    assert "לא מחובר — התחבר כדי לשמור התקדמות" in js


def test_settings_signin_onclick_swallows_rejection():
    js = _index_html()
    # the nav/settings sign-in button guards the promise doSignIn now rejects
    assert "if (p && p.catch) p.catch(() => {})" in js


@pytest.mark.parametrize("html_fn", [_index_html, _problem_html, _lead_html,
                                     _dashboard_html])
def test_save_failed_toast_wired_on_every_page(html_fn):
    js = html_fn()
    assert 'addEventListener("bt-save-failed"' in js
    assert "function btToast(" in js
    # the faded toast must not linger as an invisible click-blocker
    assert "pointer-events:none" in js
