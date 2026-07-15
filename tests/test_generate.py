"""Random problem generation + the pool store + the web app shell."""
import json
from pathlib import Path

import pytest

from bridge_trainer.app.webapp import write_app
from bridge_trainer.generate.random_problem import generate_problem
from bridge_trainer.pool.store import ProblemPool


@pytest.fixture(scope="module")
def problem():
    rec, reason = generate_problem(seed=0, n_deals=80)
    assert rec is not None, reason
    return rec


def test_generated_problem_schema(problem):
    for key in ("schema", "id", "dealer", "vul", "seat", "hand", "auction",
                "candidates", "verdict", "difficulty", "quality",
                "generator", "full_deal"):
        assert key in problem, key
    v = problem["verdict"]
    assert set(v["accepted"]) <= set(problem["candidates"])
    assert len(problem["candidates"]) >= 2
    actions = {r["action"] for r in v["corrected"]}
    assert actions == set(problem["candidates"])
    # The hero's hand is part of the recorded full deal.
    assert problem["full_deal"][problem["seat"]] == problem["hand"]


def test_generation_is_deterministic():
    a, _ = generate_problem(seed=0, n_deals=60)
    b, _ = generate_problem(seed=0, n_deals=60)
    assert a is not None and b is not None
    a.pop("created_at"), b.pop("created_at")
    assert a == b


def test_pool_roundtrip(tmp_path, problem):
    pool = ProblemPool(tmp_path)
    pid = pool.add(problem)
    assert pool.ids() == [pid]
    assert pool.get(pid)["hand"] == problem["hand"]
    with pytest.raises(FileExistsError):
        pool.add(problem)
    index = pool.rebuild_index()
    assert index["count"] == 1
    assert index["problems"][0]["id"] == pid
    on_disk = json.loads((tmp_path / "index.json").read_text())
    assert on_disk == index


def test_webapp_shell(tmp_path):
    write_app(tmp_path)
    for f in ("index.html", "p.html", ".nojekyll"):
        assert (tmp_path / f).exists()
    index = (tmp_path / "index.html").read_text()
    assert "Deal me a hand" in index
    assert "data/index.json" in index
    page = (tmp_path / "p.html").read_text()
    assert "data/problems/" in page
    assert 'name="viewport"' in page
