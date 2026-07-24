import json

from bridge_trainer.app.webapp import _problem_html, _taxonomy_he_json
from bridge_trainer.engine.classify import TYPE_IDS


def test_problem_page_carries_classification_ui():
    html = _problem_html()
    # type badge with the problem card, difficulty revealed with the verdict
    assert "typeBadgeHtml(P)" in html
    assert 'id="diffline"' in html
    assert "diffLineHtml(P)" in html
    # every taxonomy id has a display name in the injected map (ARCH-5:
    # TYPE_NAMES is now derived from window.TAXONOMY_HE, not a JS literal)
    taxonomy = json.loads(_taxonomy_he_json())
    for tid in TYPE_IDS:
        assert tid in taxonomy and taxonomy[tid][0]
