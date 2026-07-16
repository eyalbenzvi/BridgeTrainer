"""Random problem generation + the pool store + the web app shell."""
import json
from pathlib import Path

import pytest

from bridge_trainer.app.webapp import write_app
from bridge_trainer.generate.random_problem import generate_problem
from bridge_trainer.pool.store import ProblemPool


def _first_accepted(start, n_deals=80, tries=40):
    for seed in range(start, start + tries):
        rec, _ = generate_problem(seed=seed, n_deals=n_deals)
        if rec is not None:
            return seed, rec
    raise AssertionError("no seed accepted — generator gate too strict?")


@pytest.fixture(scope="module")
def problem():
    return _first_accepted(0)[1]


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


def test_generated_problem_has_notes(problem):
    """Every stem call and every option carries an explanation."""
    assert len(problem["auction_notes"]) == len(problem["auction"])
    assert all(problem["auction_notes"]), "empty auction note"
    assert set(problem["option_notes"]) == set(problem["candidates"])
    for note in problem["option_notes"].values():
        assert note["shows"]
        assert "simulated auctions end in" in note["partner"]


def test_rule_phrases_cover_every_bot_rule():
    """Each rule name the bidder can emit has a human phrasing."""
    import re
    from pathlib import Path
    import bridge_trainer.bot.bidder as bidder_mod
    from bridge_trainer.generate.notes import rule_phrase
    src = Path(bidder_mod.__file__).read_text()
    rules = set(re.findall(r'BotCall\((?:[^,]+),\s*f?"([a-z0-9_{}.()]+)"',
                           src))
    for rule in rules:
        probe = re.sub(r"\{[^}]*\}", "s", rule)
        assert rule_phrase(probe), f"no phrase for bot rule {probe!r}"


def test_generation_is_deterministic():
    seed, a = _first_accepted(0, n_deals=60)
    b, _ = generate_problem(seed=seed, n_deals=60)
    assert b is not None
    a = dict(a)
    a.pop("created_at"), b.pop("created_at")
    assert a == b


def test_adaptive_dd_checkpoints(monkeypatch):
    """With interim checkpoints active the record stays schema-valid and
    reports how many deals the verdict actually used."""
    import bridge_trainer.generate.random_problem as rp
    monkeypatch.setattr(rp, "DD_CHECKPOINTS", (30, 50))
    seed, rec = _first_accepted(0, n_deals=80)
    assert 30 <= rec["generator"]["n_deals"] <= 80
    assert set(rec["verdict"]["accepted"]) <= set(rec["candidates"])
    # Deterministic under the same checkpoint schedule.
    rec2, _ = generate_problem(seed=seed, n_deals=80)
    rec, rec2 = dict(rec), dict(rec2)
    rec.pop("created_at"), rec2.pop("created_at")
    assert rec == rec2


def test_produce_batch_parallel(tmp_path):
    """jobs>1 fills the pool with valid records (which seed lands first
    legitimately depends on completion order)."""
    from bridge_trainer.generate.producer import produce_batch
    made = produce_batch(tmp_path / "par", count=1, max_seconds=300.0,
                         base_seed=0, n_deals=60, jobs=2)
    assert len(made) == 1
    rec = ProblemPool(tmp_path / "par").get(made[0])
    assert set(rec["verdict"]["accepted"]) <= set(rec["candidates"])
    index = json.loads((tmp_path / "par" / "index.json").read_text())
    assert index["count"] == 1


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
