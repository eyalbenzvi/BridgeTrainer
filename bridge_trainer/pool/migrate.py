"""One-time schema canonicalization for pool records (ARCH-9).

Historical records come in a few generations, and the web client currently
absorbs the differences at read time — ``normalize()`` in webapp.py handles
three verdict shapes, and the scorer tolerates two. The finding's fix is to
canonicalize records ONCE, in the producer, so the client can eventually drop
its legacy branches.

This module is the producer-side half: a PURE ``canonicalize_record`` (unit
tested here) plus ``detect_schema``. The runnable migration is
``scripts/migrate_schema.py`` (dry-run by default). Removing the client's
legacy branches is deliberately a SEPARATE, approved step — it must not happen
until this migration has actually run against the live database, exactly as the
index-format split (T12) was staged. See docs/infra_fixes_plan_round2.md.

Canonical record shape (target of the migration):
  * ``schema``            one of pool.store.SUPPORTED_SCHEMAS, stamped to match
                          the record's actual content (not hard-coded to 1).
  * ``classification``    always a dict (``{}`` when unknown), never absent.
  * ``verdict.corrected`` / ``verdict.raw`` rows key the call as ``bid`` (the
                          oldest authored records used ``action``); the alias is
                          added, the original key left in place for safety.

Only these safe, reversible normalizations are automated. Deeper verdict-shape
consolidation (collapsing raw ``verdict.table`` into ``verdict.corrected``)
is intentionally NOT done here: it is display-layer logic that belongs to the
page, and rewriting it in stored data needs domain review first.
"""
from __future__ import annotations

from .store import SUPPORTED_SCHEMAS


def detect_schema(rec: dict) -> int:
    """The schema generation a record actually belongs to.

    Honors an already-valid ``schema`` field; otherwise infers: a mode-aware
    lead record (a ``training`` block carrying IMP metrics) is schema 2, and
    everything else — bidding problems and legacy tricks-only leads — is 1.
    """
    sc = rec.get("schema")
    if sc in SUPPORTED_SCHEMAS:
        return sc
    if rec.get("kind") == "lead":
        tr = rec.get("training")
        modes = tr.get("modes") if isinstance(tr, dict) else None
        if isinstance(modes, dict) and modes.get("IMP"):
            return 2
    return 1


def canonicalize_record(rec: dict) -> tuple[dict, bool]:
    """Return ``(canonical_record, changed)``. Pure — does not mutate *rec*.

    Applies only the safe normalizations documented in the module docstring.
    ``changed`` is False when *rec* is already canonical, so the migration can
    skip a write (and report an accurate count).
    """
    out = dict(rec)
    changed = False

    # 1. a schema field that reflects the record's real generation
    want = detect_schema(out)
    if out.get("schema") != want:
        out["schema"] = want
        changed = True

    # 2. classification is always a dict
    if not isinstance(out.get("classification"), dict):
        out["classification"] = {}
        changed = True

    # 3. verdict rows carry a `bid` alias (oldest authored rows used `action`)
    v = out.get("verdict")
    if isinstance(v, dict):
        v_new = dict(v)
        touched = False
        for key in ("corrected", "raw"):
            rows = v.get(key)
            if not isinstance(rows, list):
                continue
            new_rows = []
            for r in rows:
                if (isinstance(r, dict) and "action" in r and "bid" not in r):
                    r = {**r, "bid": r["action"]}
                    touched = True
                new_rows.append(r)
            v_new[key] = new_rows
        if touched:
            out["verdict"] = v_new
            changed = True

    return out, changed
