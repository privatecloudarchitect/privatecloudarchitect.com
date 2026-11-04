"""The platform-lifecycle adapter: controlled-platform-change, read from lifecycle.py's join of each offered upgrade to
its bundles, on both instances. f8's rules R1 to R6 apply (adapters/__init__.py).

- The depot configuration and the bundles staged for each offered upgrade: one line, scope `estate`, each instance an
  item (f8: the rehearsal instance is judged as the one asked about, since its content has to be staged before the
  rehearsal). An instance offering no upgrade is in sync with nothing to stage, said in words (R3); each offer is
  judged on its own (f8), staged when its bundle's download is SUCCESSFUL. An offer whose bundle is not staged is drift,
  listing its bundle; one whose bundle lookup failed (no download status) is check_failed until lifecycle.py records the
  failure apart from "unstaged" (f8's queue). The depot half has no declared state on record, so it is named unread.
- The rehearsal discipline and the weekly join job are not read: the companion reads versions and offers at a moment,
  not a change history.

The mode is `detected`; the record stores no platform evaluation time and no exit code.
"""

from __future__ import annotations

from ..drift import line
from ..drift import unread as unread_line
from ..models import Register
from ..policy import Loaded
from . import utc, worst

COMPANION = "handbook/platform-lifecycle"
CHECK = "the join of each offered upgrade to its bundles, on both instances (lifecycle.py)"
DEPOT_WHY = "not read: no record holds a declared depot configuration for any instance to read the depot against"
REHEARSAL_WHY = "not read: the companion reads versions and offers at a moment, not the rehearsal discipline or the weekly job"


def _instances(rec: dict, obj: str) -> tuple[str, int, list[dict], list[str], str]:
    instances = rec.get("instances") or []
    if not instances:
        return "check_failed", 0, [], ["no instance was read"], ""
    results, items, unread, quiet = [], [], [], []
    if (
        "depot" in obj
    ):  # named while the declaration still carries the depot (f8's split gives it its own)
        unread.append("the depot configuration (no declared depot state on record)")
    for inst in instances:
        label, offers = inst.get("label"), inst.get("join") or []
        if not offers and not inst.get("upgradables"):
            results.append("in_sync")
            quiet.append(label)
            continue
        for n, offer in enumerate(offers, 1):
            if offer.get("downloadStatus") is None:
                results.append("check_failed")
                unread.append(f"offer {n} on {label}: its bundle lookup failed")
            elif not offer.get("staged"):
                results.append("drifted")
                items.append(
                    {
                        "declared": {"instance": label, "offer": n, "bundle": "SUCCESSFUL"},
                        "actual": {
                            "instance": label,
                            "offer": n,
                            "bundleType": offer.get("bundleType"),
                            "downloadStatus": offer.get("downloadStatus"),
                            "sizeMB": offer.get("sizeMB"),
                        },
                        "resolution": "open",
                    }
                )
            else:
                results.append("in_sync")
        if inst.get("upgradables") and not offers:
            results.append("check_failed")
            unread.append(f"the offers on {label} (upgrades counted, none joined)")
    said = f"; no upgrade offered on {', '.join(quiet)}, so nothing to stage there" if quiet else ""
    return worst(results), len(results), items, unread, said


def lines(records: dict[str, dict], pol: Loaded, register: Register, capability: str) -> list[dict]:
    ((record_path, rec),) = records.items()
    out = []
    for decl in next(c for c in register.capabilities if c.id == capability).declarations:
        common = {
            "capability": capability,
            "declaration": decl,
            "scope": "estate",
            "read_at": utc(rec["captured_utc"]),
            "companion": COMPANION,
            "record": record_path,
            "exit": None,
            "pol": pol,
        }
        # keyed on phrases, never on "rehearsal" alone: the staged-bundles declaration names the rehearsal instance (f8)
        obj = decl.object.lower()
        if "bundles staged" not in obj:
            why = (
                DEPOT_WHY
                if "depot configuration" in obj
                else REHEARSAL_WHY
                if "rehearsal discipline" in obj
                else "not read: no rule of the platform-lifecycle adapter reads this declaration"
            )
            out.append(unread_line(check=why, **common))
            continue
        result, declared, items, unread, said = _instances(rec, obj)
        out.append(
            line(
                store="SDDC Manager",
                declared_version=None,
                mode="detected",
                result=result,
                items_declared=declared,
                items_drifted=len(items),
                items=items,
                checked_at=None,
                check=CHECK + said + (f"; not read: {'; '.join(unread)}" if unread else ""),
                **common,
            )
        )
    return out
