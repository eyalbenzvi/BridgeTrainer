from bridge_trainer.app.webapp import _problem_html
from bridge_trainer.engine.classify import TYPE_IDS


def test_problem_page_carries_classification_ui():
    html = _problem_html()
    # type badge with the problem card, difficulty revealed with the verdict
    assert "typeBadgeHtml(P)" in html
    assert 'id="diffline"' in html
    assert "diffLineHtml(P)" in html
    # every taxonomy id has a display name in the JS map
    for tid in TYPE_IDS:
        assert f"{tid}:" in html
