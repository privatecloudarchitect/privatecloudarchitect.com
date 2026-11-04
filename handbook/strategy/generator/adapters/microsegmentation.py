"""The microsegmentation adapter: east-west-segmentation, read from posture.py's four reads. traffic.py is a writing
probe and feeds no line (R5). f8's rules R1 to R6 apply (adapters/__init__.py).

- The segmentation posture, one line at scope `organization` (the record names no VPC). The region's firewall
  capabilities not entitled is drift: the declared posture cannot be enforced, and the read that said so succeeded
  (f8); a capability list read as empty is check_failed, since a failed read gives the same (f8). Each attachment is an
  item: a profile carrying the strategy `none`, or none at all, is drift by the chapter's rule whatever was approved (a
  profile nobody runs). An attachment carrying any other strategy is not read and adds no result: no approved strategy
  is on record, so posture.py does not reach that part (f8's reach rule, correcting its first answer; the structural fix
  is a register split, posture realized against strategy approved, the second not_covered). The entitlement read is an
  item too: entitled is in sync, not entitled is drift, no answer recorded is check_failed. Each firewall section is an
  item: enabled rules the platform has not realized are drift. Rules landed over named groups and their categories are
  not read (a tenant-side audit is silent above its own level).
- The promise table is not read: no record holds which category and owner enforce each promise.

The mode is `detected`; the record stores no platform evaluation time and no exit code.
"""

from __future__ import annotations

from ..drift import line
from ..drift import unread as unread_line
from ..models import Register
from ..policy import Loaded
from . import utc, worst

COMPANION = "handbook/microsegmentation"
CHECK = "the capability list, the strategy per attachment and each section's rules (posture.py)"


def _posture(rec: dict) -> tuple[str, int, list[dict], list[str]]:
    results, items = [], []
    unread = [
        "rules over named groups and their categories (a tenant-side audit reads its own level only)"
    ]
    caps = rec.get("capabilities") or {}
    if not caps.get("total"):
        results.append("check_failed")
        unread.append("the region's capability list (read as empty)")
    elif rec.get("entitled") is True:
        results.append("in_sync")
    elif rec.get("entitled") is None:
        results.append("check_failed")
        unread.append("whether the firewall capabilities are entitled (no answer recorded)")
    else:
        results.append("drifted")
        items.append(
            {
                "declared": "the firewall capabilities entitled",
                "actual": {"disabled": caps.get("disabledList")},
                "resolution": "open",
            }
        )
    rows = rec.get("posture") or []
    if not rows:
        results.append("check_failed")
        unread.append("no attachment was listed, which a failed listing also gives")
    carrying = []
    for n, row in enumerate(rows, 1):
        strategies = row.get("strategies") or []
        if not strategies or strategies == ["none"]:
            results.append("drifted")
            items.append(
                {
                    "declared": {"attachment": n, "strategy": "one the platform runs"},
                    "actual": {"attachment": n, "strategies": strategies},
                    "resolution": "open",
                }
            )
        else:
            carrying.append(str(n))
    if carrying:
        unread.append(
            f"no approved strategy on record (attachment {', '.join(carrying)} carries a strategy)"
        )
    for s in rec.get("sections") or []:
        enabled = (s.get("rules") or 0) - (s.get("disabledRules") or 0)
        if enabled > 0 and s.get("realized") != "True":
            results.append("drifted")
            items.append(
                {
                    "declared": {
                        "section priority": s.get("priority"),
                        "enabled rules": "realized",
                    },
                    "actual": {
                        "section priority": s.get("priority"),
                        "realized": s.get("realized"),
                    },
                    "resolution": "open",
                }
            )
        else:
            results.append("in_sync")
    return worst(results), len(results), items, unread


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
        obj = decl.object.lower()
        if "segmentation posture" not in obj:
            why = (
                "not read: no record holds which policy category and owner enforce each isolation promise"
                if "promise table" in obj
                else "not read: no record holds an approved security strategy for any VPC, or its approver"
                if "security strategy approved" in obj
                else "not read: no rule of the microsegmentation adapter reads this declaration"
            )
            out.append(unread_line(check=why, **common))
            continue
        result, declared, items, unread = _posture(rec)
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
                check=CHECK + f"; not read: {'; '.join(unread)}",
                **common,
            )
        )
    return out
