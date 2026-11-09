"""The day2-pathways adapter: workload-day2, read from pathways.py's read-only audit. f8's rules R1 to R6 apply
(adapters/__init__.py).

- The Day-2 rule (never changed in vCenter) is not read: the companion "does not touch vCenter", and a change made there
  is reverted with nothing recording it (README).
- The watched fields, one line at scope `organization` (the audit reads every deployment the identity can see; a
  machine's placeholder follows listing order, so it names an item and keys no line, R6). Each claimed machine is an
  item: one whose declared fields agree with the cached object and the live machine is in sync. A machine whose
  Supervisor object is MISSING is drifted (f8's decision, by R1: declared present, actual missing), the MISSING the
  item and its field drift not counted; where its deployment
  is a tombstone (DELETE_SUCCESSFUL still listing a resource) the item records that (f8: the record contradicts itself, and
  exit 1 keys on it). Under STALE, field drift counts and carries the syncStatus. A claim whose namespace was not
  reachable, or a machine not found live that is neither MISSING nor drifted, is check_failed. An empty audit cannot be
  told from a failed listing, and exactly 200 rows may be a truncated one: both are check_failed until pathways.py
  records the listing's status and pages (f8's queue).

The mode is `detected`; the record stores no exit code and no time for the cached object.
"""

from __future__ import annotations

from ..drift import line
from ..drift import unread as unread_line
from ..models import Register
from ..policy import Loaded
from . import utc, worst

COMPANION = "handbook/day2-pathways"
CHECK = "every claimed machine through its claim, declared fields against cached and live (pathways.py's audit)"
PAGE = (
    200  # the audit's listing size (pathways.py size=200): a full page may be a truncated listing
)


def _machines(rec: dict) -> tuple[str, int, list[dict], list[str]]:
    rows = rec.get("audit")
    if not rows:
        return (
            "check_failed",
            0,
            [],
            ["the audit listed no machine, which a failed listing also gives"],
        )
    tomb = {t.get("name"): t for t in rec.get("tombstones") or []}
    results, items, unread = [], [], []
    if len(rows) >= PAGE:
        results.append("check_failed")
        unread.append(f"machines past the first {PAGE} (the listing is not paged)")
    for r in rows:
        machine, sync = r.get("machine"), r.get("syncStatus")
        fields = sorted(set(r.get("declaredVsObserved") or []) | set(r.get("declaredVsLive") or []))
        if sync == "MISSING":
            t = tomb.get(r.get("deployment"))
            results.append("drifted")
            items.append(
                {
                    "declared": {
                        "machine": machine,
                        "deployment": "DELETE_SUCCESSFUL" if t else "present",
                    },
                    "actual": {"machine": machine, "syncStatus": "MISSING"}
                    | ({"resourcesStillListed": t.get("resourcesStillListed")} if t else {}),
                    "resolution": "open",
                }
            )
        elif fields:
            results.append("drifted")
            items.append(
                {
                    "declared": {"machine": machine, "fields": fields},
                    "actual": {"machine": machine, "differs": fields, "syncStatus": sync},
                    "resolution": "open",
                }
            )
        elif r.get("agrees"):
            results.append("in_sync")
        else:
            results.append("check_failed")
            unread.append(
                f"{machine}, "
                + (
                    "its claim's namespace not reachable"
                    if not r.get("claimNamespaceReachable")
                    else "not found live"
                )
            )
    return worst(results), len(rows), items, unread


def lines(records: dict[str, dict], pol: Loaded, register: Register, capability: str) -> list[dict]:
    ((record_path, rec),) = records.items()
    out = []
    for decl in next(c for c in register.capabilities if c.id == capability).declarations:
        common = {
            "capability": capability,
            "declaration": decl,
            "scope": "organization",
            "read_at": utc(rec["captured_utc"]),
            "companion": COMPANION,
            "record": record_path,
            "exit": None,
            "pol": pol,
        }
        if decl.system == "repo":
            out.append(
                unread_line(
                    check="not read: the companion does not touch vCenter, and a change made there is reverted with "
                    "nothing recording it",
                    **common,
                )
            )
            continue
        result, declared, items, unread = _machines(rec)
        out.append(
            line(
                store="VCF Automation",
                declared_version=None,
                mode="detected",
                result=result,
                items_declared=declared,
                items_drifted=len(items),
                items=items,
                checked_at=None,
                check=CHECK + (f"; not read: {'; '.join(unread)}" if unread else ""),
                **common,
            )
        )
    return out
