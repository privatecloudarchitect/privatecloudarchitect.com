"""The cartography adapter: inventory-of-record, read from the coverage read (writeback_tags.py --coverage), counts only.
f8's rules R1 to R6 apply (adapters/__init__.py).

Two lines, scope `estate` (the record names no vCenter):

- The governed categories and their values. The categories the classifier gives no value by design are left out of what
  is declared and named in the check text: tier comes "only from unambiguous components" and env proposals "never ride
  recommended" (README), so `identity.app-layer` and `lifecycle.env-observed` carry no value until one is approved (f8).
  Every other governed category is declared; one with carriers is defined on the vCenter (a tag resolves only against a
  defined category), one without carriers cannot be told defined or not, so it is check_failed (R1). The values half is
  not read.
- Each workload's governed tags. Every workload the classifier walked is declared. A workload on the vCenter with no
  governed tag is drift; a workload held for lack of a signal was never looked up on the vCenter, so it is check_failed
  (f8, R1); a walked workload not found on the vCenter is check_failed too.

The mode is `detected`; the record stores neither a platform evaluation time nor an exit code (`coverage()` returns 0).
Until the companion looks held workloads up on the vCenter (f8's queue), the second line cannot read in_sync while any
workload is held.
"""

from __future__ import annotations

from ..drift import line
from ..drift import unread as unread_line
from ..models import Register
from ..policy import Loaded
from . import utc, worst

COMPANION = "frameworks/cartography"
CHECK = "the coverage read over the workloads the classifier walked, counts only (writeback_tags.py --coverage)"
# no value by design until one is approved (README: tier from unambiguous components only; env proposals never recommended)
BY_DESIGN = ("identity.app-layer", "lifecycle.env-observed")
VALUES_WHY = (
    "not read: the coverage read counts the categories that carry tags, never each category's values against a "
    "declared list"
)
DEFAULT_WHY = "not read: no rule of the cartography adapter reads this declaration"


def _categories(rec: dict, obj: str) -> tuple[str, int, int, list[dict], list[str]]:
    per = rec.get("perCategory") or {}
    declared = [c for c in per if c not in BY_DESIGN]
    results, unread = [], []
    if (
        "values" in obj
    ):  # named while the declaration still carries its values (f8's split gives them their own)
        unread.append("the values half (the record counts categories, not their values)")
    for c in declared:
        if per[c] > 0:
            results.append("in_sync")
        else:
            results.append("check_failed")
            unread.append(f"whether {c} is defined (no workload carries it)")
    if not per:
        unread.append("no category was counted")
    note = f"{', '.join(c for c in BY_DESIGN if c in per)} carry no value by design until one is approved"
    return worst(results), len(declared), 0, [], [*unread, note]


def _workloads(rec: dict) -> tuple[str, int, int, list[dict], list[str]]:
    walked, held = rec.get("walked"), rec.get("heldNoSignal") or 0
    found, tagged = rec.get("onThisVcenter"), rec.get("withAnyGovernedTag")
    if not isinstance(walked, int) or not isinstance(found, int) or not isinstance(tagged, int):
        return "check_failed", 0, 0, [], ["the coverage counts are missing"]
    results, items, unread = [], [], []
    untagged = found - tagged
    if untagged > 0:
        results.append("drifted")
        items.append(
            {
                "declared": "a governed tag on each workload",
                "actual": f"{untagged} workloads on the vCenter carry none",
                "resolution": "open",
            }
        )
    if held:
        results.append("check_failed")
        unread.append(f"{held} workloads held for lack of a signal, never looked up on the vCenter")
    missing = walked - held - found
    if missing > 0:
        results.append("check_failed")
        unread.append(f"{missing} walked workloads not found on the vCenter")
    if found:
        results.append("in_sync")
    return worst(results), walked, untagged if items else 0, items, unread


def lines(records: dict[str, dict], pol: Loaded, register: Register, capability: str) -> list[dict]:
    ((record_path, rec),) = records.items()
    out = []
    for decl in next(c for c in register.capabilities if c.id == capability).declarations:
        obj = decl.object.lower()
        if obj.startswith("governed tag categories"):
            result, declared, drifted, items, unread = _categories(rec, obj)
        elif "workload" in obj:
            result, declared, drifted, items, unread = _workloads(rec)
        else:
            out.append(
                unread_line(
                    capability=capability,
                    declaration=decl,
                    scope="estate",
                    read_at=utc(rec["captured_utc"]),
                    companion=COMPANION,
                    check=VALUES_WHY if obj.startswith("the values of") else DEFAULT_WHY,
                    record=record_path,
                    exit=None,
                    pol=pol,
                )
            )
            continue
        out.append(
            line(
                capability=capability,
                declaration=decl,
                store="vCenter",
                declared_version=None,
                scope="estate",
                mode="detected",
                result=result,
                items_declared=declared,
                items_drifted=drifted,
                items=items,
                read_at=utc(rec["captured_utc"]),
                checked_at=None,
                companion=COMPANION,
                check=CHECK + (f"; not read: {'; '.join(unread)}" if unread else ""),
                record=record_path,
                exit=None,
                pol=pol,
            )
        )
    return out
