"""Continuous generation: date-based pool growth and the drill manifest."""
import datetime
import json
import re
from pathlib import Path

import pytest

from bridge_trainer.app.publish import publish

PROBLEMS = Path("problems")


def _yesterday(days=1):
    return (datetime.datetime.now(datetime.timezone.utc).date()
            - datetime.timedelta(days=days)).isoformat()


def test_growth_adds_deals_per_day(tmp_path):
    entries = publish(PROBLEMS, tmp_path / "site", seed=7, n_override=24,
                      cache_dir=tmp_path / "cache", variants_override=100,
                      grow_per_day=2, grow_anchor=_yesterday(2))
    # Base variants + 2 days x 2 deals. variants_override=100 doesn't cap.
    for e in entries:
        base = e.variants - 4
        assert base >= 1
        assert (tmp_path / "site" / e.id / f"v{e.variants - 1}").exists()


def test_future_anchor_adds_nothing(tmp_path):
    future = (datetime.datetime.now(datetime.timezone.utc).date()
              + datetime.timedelta(days=3)).isoformat()
    a = publish(PROBLEMS, tmp_path / "a", seed=7, n_override=24,
                cache_dir=tmp_path / "cache", variants_override=2,
                grow_per_day=5, grow_anchor=future)
    assert all(e.variants == 2 for e in a)


def test_index_has_drill_button_and_manifest(tmp_path):
    entries = publish(PROBLEMS, tmp_path / "site", seed=7, n_override=24,
                      cache_dir=tmp_path / "cache", variants_override=2)
    html = (tmp_path / "site" / "index.html").read_text()
    assert "Deal me a hand" in html
    m = re.search(r"const MANIFEST = (\[.*?\]);\n", html)
    assert m
    manifest = json.loads(m.group(1))
    assert {e["id"] for e in manifest} == {e.id for e in entries}
    assert all(e["total"] == 2 for e in manifest)
