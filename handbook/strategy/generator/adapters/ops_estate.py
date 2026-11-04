"""The ops-estate adapter: content-from-code, read from content.py's audit. converge-run.json was written by cycle.py,
which writes to the instance, so it feeds no line (R5). The rules are 3c's (2026-11-02): R1 to R6 and the reach rule,
and R7 to R13 (adapters/__init__.py). Every line is scope `estate` (one instance, one owner prefix), mode `detected`;
the record stores no exit (--check's exit keys on dangling references, not naming) and no platform evaluation time.

- The desired state (the repository): not covered. converge.py's dry run prints what it would create or update, exits
  0 either way and writes no record; `converge.py --check` with a record is 3c's queue. The integrity count may make
  this line drifted only once content.py splits dangling references by owner (moot today: none dangle).
- The naming grammar each owned object's name holds (VCF Operations). Each owned object is an item, counted per class
  of the census (a name two classes share counts in both). An object on a class's failing list is drifted; every other
  owned object is in sync by meaning, under R13 in the README's own words for the practice (README, practice 1): "every
  class holds its grammar, read by meaning" (`conformingToSchema` is a histogram, not the declaration, 3c B17). A class
  whose owned count less its failing list differs from its count conforming by meaning is check_failed (the counts
  disagree). The line is check_failed when no naming vocabulary was given (kinds and scope values were not
  checked), or when a class's listing reads empty (R7). Views and dashboards are not read: the grammar covers them and
  content.py lists eight classes; once the register gives them a declaration of their own (3c, B16), that line is not
  covered and the naming line no longer names them. A listing cut at its page limit cannot be
  told from a whole one until content.py records the server's totals.
"""

from __future__ import annotations

from ..drift import line
from ..drift import unread as unread_line
from ..models import Register
from ..policy import Loaded
from . import utc, worst

COMPANION = "handbook/ops-estate"
CHECK = "each owned object's name against the grammar, class by class (content.py)"
VIEWS_WHY = "not read: content.py lists eight classes, and no path it tried could list views or dashboards (noReadSurface)"


def _views(obj: str) -> bool:
    return "view's" in obj or "dashboard" in obj


DESIRED_WHY = (
    "not read: converge.py --state <file> --dry-run prints what it would create or update, exits 0 either way and "
    "writes no record; the one committed converge run wrote to the instance"
)


def _naming(rec: dict, views_apart: bool) -> tuple[str, int, list[dict], list[str]]:
    census = rec.get("census") or []
    unread = []
    if (
        not views_apart
    ):  # named here only until the register gives views and dashboards a declaration of their own
        unread.append(
            "views and dashboards (the grammar covers them; content.py lists eight classes)"
        )
    unread.append("whether a listing was cut at its page limit (the record keeps no server totals)")
    if not census:
        return "check_failed", 0, [], ["the census (no class was read)", *unread]
    if not rec.get("namingVocabulary"):
        return (
            "check_failed",
            0,
            [],
            ["the kinds and scope values (no naming vocabulary was given)", *unread],
        )
    results, items, declared = [], [], 0
    for c in census:
        if not c.get("total"):
            results.append("check_failed")
            unread.append(f"the {c.get('class')} (the listing read empty)")
            continue
        owned, failing = c.get("owned") or 0, c.get("failing") or []
        if owned - len(failing) != c.get("conformingByMeaning"):
            results.append("check_failed")  # the A9 analogue (3c, finding 6)
            unread.append(f"the {c.get('class')} (its counts disagree)")
            continue
        declared += owned
        results += ["in_sync"] * (owned - len(failing))
        for f in failing:
            results.append("drifted")
            items.append(
                {
                    "declared": {
                        "class": c.get("class"),
                        "name": f.get("name"),
                        "grammar": "holds",
                    },
                    "actual": {
                        "class": c.get("class"),
                        "name": f.get("name"),
                        "reasons": f.get("reasons"),
                    },
                    "resolution": "open",
                }
            )
    return worst(results), declared, items, unread


def lines(records: dict[str, dict], pol: Loaded, register: Register, capability: str) -> list[dict]:
    ((record_path, rec),) = records.items()
    common = {
        "capability": capability,
        "scope": "estate",
        "read_at": utc(rec["captured_utc"]),
        "companion": COMPANION,
        "record": record_path,
        "exit": None,
        "pol": pol,
    }
    out = []
    decls = next(c for c in register.capabilities if c.id == capability).declarations
    views_apart = any(_views(d.object.lower()) for d in decls)
    for decl in decls:
        obj = decl.object.lower()
        if "naming grammar" in obj and _views(obj):
            out.append(unread_line(declaration=decl, check=VIEWS_WHY, **common))
        elif "naming grammar" in obj:
            result, declared, items, unread = _naming(rec, views_apart)
            out.append(
                line(
                    declaration=decl,
                    store="VCF Operations",
                    declared_version=None,
                    mode="detected",
                    result=result,
                    items_declared=declared,
                    items_drifted=len(items),
                    items=items,
                    checked_at=None,
                    check=CHECK + f"; not read: {'; '.join(unread)}",
                    **common,
                )
            )
        else:
            why = (
                DESIRED_WHY
                if "desired state" in obj
                else "not read: no rule of the ops-estate adapter reads this declaration"
            )
            out.append(unread_line(declaration=decl, check=why, **common))
    return out
