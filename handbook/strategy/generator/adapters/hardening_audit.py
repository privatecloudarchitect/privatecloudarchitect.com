"""The hardening-audit adapter: hardening-posture, read from hardening.py's seven reads over three token planes. f8's
rules R1 to R6 apply (adapters/__init__.py).

Each declaration is matched by what it declares, so the adapter reads the register before and after 64 splits its
second declaration in three (step 5's release):

- The fix log is not read: "the harness keeps no state between runs" (README), so no record joins a finding to its fix.
- The audit-trail minimum your estate decides: the figure is the portfolio's, `AUDIT_MIN_DAYS` under the capability's
  parameters (schema 5), never the harness's default and never a literal here (GATE-14). With no figure, or one of
  kind not_recorded (the served projection stubs an unapproved one so), the line is not covered, the reading kept in
  the check text. With a figure, the item is how far back the audit trail answers: drifted when its oldest readable
  event is younger than the minimum, in sync when at or beyond it, check_failed when the read did not complete or
  records no window, or when the figure's unit is not days (the record's window is in days). The read cannot say why a
  window is short (a retention setting, or an estate younger than the minimum; README); the line says only that the
  declared minimum is not met. The mode is `detected`.
- Each token plane read by a credential (after the split): one line, scope `organization`, each plane an item; a plane
  with no credential set is drifted; a set plane whose reads were all made is in sync; a skip on a set plane is
  check_failed, since an outage lands as a skip too (f8).
- Each plane's owner is not covered: the record holds credential coverage, never an owner (R4). Before the split, the
  one declaration that joins the minimum and the owners is not covered for both reasons.

The mode is `detected` for the planes line; the record stores its own exit code, carried on every line.
"""

from __future__ import annotations

from collections.abc import Mapping

from ..drift import line
from ..drift import unread as unread_line
from ..models import Parameter, Register
from ..policy import Loaded
from . import utc, worst

COMPANION = "handbook/hardening-audit"
CHECK = "the seven reads across the three token planes, skips named (hardening.py)"
CHECK_TRAIL = "the audit trail's oldest readable event against your estate's minimum (hardening.py's audit-trail read)"
PLANES = {"sddc": "lifecycle", "ops": "operations", "vcfa": "tenancy"}


def _trail_words(rec: dict) -> str:
    t = (rec.get("reads") or {}).get("audit-trail") or {}
    window = t.get("windowDays")
    default = t.get("minDays")
    return (
        f"no declared audit-trail minimum is on record (window {window} days; the harness default "
        f"{default} is not a declaration)"
    )


def _planes(rec: dict) -> tuple[str, int, list[dict], list[str]]:
    planes, reads = rec.get("planes") or {}, rec.get("reads") or {}
    if not planes:
        return "check_failed", 0, [], ["no plane was recorded"]
    skipped = {s.get("read"): s.get("reason") for s in rec.get("skips") or []}
    results, items, unread = [], [], []
    for key, name in PLANES.items():
        on_plane = [r for r in reads.values() if r.get("plane") == name]
        if planes.get(key) != "set":
            results.append("drifted")
            items.append(
                {
                    "declared": {"plane": name, "credential": "set"},
                    "actual": {"plane": name, "credential": planes.get(key)},
                    "resolution": "open",
                }
            )
        elif any(r.get("status") != "read" for r in on_plane) or any(
            k in skipped for k, r in reads.items() if r.get("plane") == name
        ):
            results.append("check_failed")
            unread.append(f"a read on the {name} plane was skipped")
        else:
            results.append("in_sync")
    return worst(results), len(PLANES), items, unread


def _trail(rec: dict, p: Parameter) -> tuple[str, list[dict], list[str]]:
    t = (rec.get("reads") or {}).get("audit-trail") or {}
    window = t.get("windowDays")
    if t.get("status") != "read" or not isinstance(window, int):
        return (
            "check_failed",
            [],
            ["the audit trail's window (the read did not complete or records none)"],
        )
    if p.unit != "days":
        return (
            "check_failed",
            [],
            [f"the minimum against the window (the minimum is in {p.unit}, the window in days)"],
        )
    if window < p.value:
        return (
            "drifted",
            [
                {
                    "declared": {"audit trail answers back, days": p.value},
                    "actual": {"oldest readable event, days back": window},
                    "resolution": "open",
                }
            ],
            [],
        )
    return "in_sync", [], []


def lines(
    records: dict[str, dict],
    pol: Loaded,
    register: Register,
    capability: str,
    parameters: Mapping[str, Parameter] | None = None,
) -> list[dict]:
    minimum = (parameters or {}).get("AUDIT_MIN_DAYS")
    if minimum is not None and minimum.kind == "not_recorded":
        minimum = None
    ((record_path, rec),) = records.items()
    out = []
    for decl in next(c for c in register.capabilities if c.id == capability).declarations:
        common = {
            "capability": capability,
            "declaration": decl,
            "scope": "organization",
            "read_at": utc(rec["captured"]),
            "companion": COMPANION,
            "record": record_path,
            "exit": rec.get("exit"),
            "pol": pol,
        }
        obj = decl.object.lower()
        if "fix log" in obj:
            out.append(
                unread_line(
                    check="not read: the harness keeps no state between runs, so no record joins a finding to its fix",
                    **common,
                )
            )
        elif "read by a credential" in obj or ("credential" in obj and "owner" not in obj):
            result, declared, items, unread = _planes(rec)
            out.append(
                line(
                    store="the token planes",
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
        elif "minimum" in obj and "owner" not in obj and minimum is not None:
            result, items, unread = _trail(rec, minimum)
            out.append(
                line(
                    store="VCF Automation's audit trail",
                    declared_version=f"AUDIT_MIN_DAYS {minimum.value} {minimum.unit} ({minimum.kind})",
                    mode="detected",
                    result=result,
                    items_declared=1,
                    items_drifted=len(items),
                    items=items,
                    checked_at=None,
                    check=CHECK_TRAIL + (f"; not read: {'; '.join(unread)}" if unread else ""),
                    **common,
                )
            )
        else:
            whys = []
            if "minimum" in obj:
                whys.append(_trail_words(rec))
            if "owner" in obj:
                whys.append(
                    "no record names a plane's owner (the harness reads credential coverage, not ownership)"
                )
            out.append(
                unread_line(
                    check="not read: " + ("; ".join(whys) or "no record holds this declaration"),
                    **common,
                )
            )
    return out
