"""The log-alerts adapter: threat-alerting, read from deploy.py's status read-back. prove.py --send sends syslog lines
and feeds no line (R5); the signature searches compare nothing declared. The rules are 3c's (2026-11-02): R1 to R6 and
the reach rule, and R7 to R13 (adapters/__init__.py).

The capability declares four signals: a shell or SSH switched on, a host firewall off, and sign-in failures. They ride
two bundles, since deploy.py's bundle carries one kind: Host Access (HostSystem) and Access (the vCenter adapter
instance), committed by 3c from the chapter's workshop starters. A status record of any other bundle is no read of
the declaration (R10): the committed one is the Storage Path bundle, the proof of the deploy method only.

- The signal catalog (the repository): not covered. No record compares the catalog with anything.
- The log alert bundle and its group (VCF Operations). Scope `estate` (the record names no cluster; its scope name is a
  placeholder, R6). A status record of a declared bundle is read so: each alert of the bundle is an item, drifted when
  absent or when fewer of its monitors are enabled than it has (a missing monitor and a disabled one never fire alike),
  in sync when present with every monitor enabled; a field missing or not a count is check_failed. Whether the record
  covers the whole bundle is not read: status honours --only and records neither the flag nor the bundle's alert ids
  (3c's queue; then a missing id is check_failed). `raised` is no declared state. The group is an item: absent or empty
  is drifted, provided the membership read succeeded; members present is in sync. The policy is an item: absent is
  drifted, and present is check_failed, strict (3c): status reads that a policy of the name exists, never its
  assignment to the group or each alert's state in it. Until deploy.py pages `find()`, a group or policy read as
  absent is check_failed, since it may sit past the first page.

The mode is `detected`; status always returns 0, so no exit is stored, and no platform evaluation time.
"""

from __future__ import annotations

from ..drift import line
from ..drift import unread as unread_line
from ..models import Register
from ..policy import Loaded
from . import utc, worst

COMPANION = "handbook/log-alerts"
CHECK = "the deploy's read-back of the bundle (deploy.py status)"
DECLARED_BUNDLES = ("Host Access", "Access")  # the four signals' bundles (3c, B1 and B2)
CATALOG_WHY = (
    "not read: no record compares the signal catalog with anything; deploy.py status reads the bundle file as the "
    "declared side of the VCF Operations line"
)


def _status(rec: dict) -> tuple[str, int, list[dict], list[str]]:
    results, items, unread = [], [], []
    alerts = rec.get("alerts") or []
    if not alerts:
        return "check_failed", 0, [], ["the bundle's alerts (none on the record)"]
    for a in alerts:
        monitors, on = a.get("monitors"), a.get("monitorsEnabled")
        if not isinstance(monitors, int) or not isinstance(on, int) or "present" not in a:
            results.append("check_failed")
            unread.append(f"alert {a.get('id')} (a field missing or not a count)")
        elif not a["present"]:
            results.append("drifted")
            items.append(
                {
                    "declared": {"alert": a.get("id"), "present": True},
                    "actual": {"alert": a.get("id"), "present": False},
                    "resolution": "open",
                }
            )
        elif on < monitors or monitors < 1:
            results.append("drifted")
            items.append(
                {
                    "declared": {"alert": a.get("id"), "monitors enabled": monitors},
                    "actual": {"alert": a.get("id"), "monitors enabled": on},
                    "resolution": "open",
                }
            )
        else:
            results.append("in_sync")
    if rec.get("group") is not True:
        results.append("check_failed")
        unread.append("the group (read as absent; find() reads one page)")
    elif not rec.get("members"):
        results.append("drifted")
        items.append(
            {
                "declared": {"group": "members"},
                "actual": {"group": "no members"},
                "resolution": "open",
            }
        )
    else:
        results.append("in_sync")
    results.append("check_failed")
    unread.append(
        "the policy's assignment to the group and each alert's state in it (status reads that a policy of the name "
        + ("exists" if rec.get("policy") is True else "is absent, past the first page or not")
        + ")"
    )
    unread.append(
        "whether the record covers the whole bundle (status honours --only and records neither)"
    )
    return worst(results), len(results), items, unread


def lines(records: dict[str, dict], pol: Loaded, register: Register, capability: str) -> list[dict]:
    ((record_path, rec),) = records.items()
    common = {
        "capability": capability,
        "scope": "estate",
        "read_at": utc(rec["read_at"]),
        "companion": COMPANION,
        "record": record_path,
        "exit": None,
        "pol": pol,
    }
    out = []
    for decl in next(c for c in register.capabilities if c.id == capability).declarations:
        obj = decl.object.lower()
        if "signal catalog" in obj:
            out.append(unread_line(declaration=decl, check=CATALOG_WHY, **common))
        elif "bundle" in obj and rec.get("bundle") not in DECLARED_BUNDLES:
            out.append(
                unread_line(
                    declaration=decl,
                    check="not read: the one deploy-status record holds another bundle, not the four signals this "
                    "capability declares; no bundle, status or proof record of theirs is committed",
                    **common,
                )
            )
        elif "bundle" in obj:
            result, declared, items, unread = _status(rec)
            out.append(
                line(
                    declaration=decl,
                    store="VCF Operations and Log Management",
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
        else:
            out.append(
                unread_line(
                    declaration=decl,
                    check="not read: no rule of the log-alerts adapter reads this declaration",
                    **common,
                )
            )
    return out
