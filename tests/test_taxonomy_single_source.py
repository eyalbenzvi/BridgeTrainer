"""ARCH-5: the Hebrew type labels/tooltips have a single source of truth.

Previously TYPE_NAMES was a JS literal in webapp.py that duplicated — and had
drifted from — classify.LABELS_HE / lead_classify.LEAD_LABELS_HE ("ניסיון סלאם"
vs "ניסיון סלם", "החלטת כפל" vs "להכפיל או להכריז", "סלאם" vs "סלם"). Now every
page injects window.TAXONOMY_HE built from the taxonomy modules, and _SHARED_JS
derives TYPE_NAMES from it. These tests pin that: the injected map matches the
modules exactly, and no page keeps the old literal.
"""
from __future__ import annotations

import json

from bridge_trainer.app.webapp import (_SHARED_JS, _dashboard_html,
                                        _index_html, _lead_html, _problem_html,
                                        _taxonomy_he_json)
from bridge_trainer.engine.classify import LABELS_HE, TOOLTIPS_HE
from bridge_trainer.engine.lead_classify import LEAD_LABELS_HE, LEAD_TOOLTIPS_HE

PAGES = (_index_html, _problem_html, _lead_html, _dashboard_html)


def test_json_keys_cover_both_taxonomies_exactly():
    data = json.loads(_taxonomy_he_json())
    expected = set(LABELS_HE) | set(LEAD_LABELS_HE)
    assert set(data) == expected


def test_labels_match_the_modules_no_drift():
    data = json.loads(_taxonomy_he_json())
    for tid, label in {**LABELS_HE, **LEAD_LABELS_HE}.items():
        assert data[tid][0] == label, tid
    # the specific drifts the finding called out are now consistent
    assert data["slam_try"][0] == "ניסיון סלם"
    assert data["double_or_bid"][0] == "להכפיל או להכריז"
    assert data["lead_slam"][0] == "סלם"


def test_every_type_has_a_nonempty_tooltip():
    data = json.loads(_taxonomy_he_json())
    for tid, pair in data.items():
        assert pair[1].strip(), f"{tid} has no tooltip"
    # tooltips come from the modules, not a webapp literal
    for tid, tip in TOOLTIPS_HE.items():
        assert json.loads(_taxonomy_he_json())[tid][1] == tip
    for tid, tip in LEAD_TOOLTIPS_HE.items():
        assert json.loads(_taxonomy_he_json())[tid][1] == tip


def test_all_pages_inject_taxonomy_before_shared_bundle():
    for f in PAGES:
        html = f()
        assert html.count("window.TAXONOMY_HE = ") == 1, f.__name__
        assert html.index("window.TAXONOMY_HE") < html.index("bt-shared.js"), \
            f.__name__


def test_type_names_derived_not_literal():
    # the JS derives TYPE_NAMES from the injected global; the old object
    # literal (with its drifted values) is gone
    assert 'const TYPE_NAMES = (typeof window' in _SHARED_JS
    assert "ניסיון סלאם" not in _SHARED_JS      # the old drifted label
    assert "החלטת כפל" not in _SHARED_JS
