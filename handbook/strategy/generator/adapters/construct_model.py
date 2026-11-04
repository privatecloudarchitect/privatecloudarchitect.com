"""The construct-model adapter: tenancy-model, read from inventory.py's edge map and its naming audit. f8's rules R1 to
R6 apply (adapters/__init__.py).

Two lines, scope `organization` ("the records hold what that organization can see", README):

- The tenancy layout: the five tenancy edges only (f8: the other edges are the taxonomy, not the layout declaration),
  Organization to Project, Project to Supervisor Namespace, and Supervisor Namespace to Region, to Namespace Class and to
  VPC. An edge read live that holds its cardinality is in sync; one that does not is drifted, its cardinality against
  the counts your estate bore; an edge not read (no provider bearer) is check_failed (R2); an edge with nothing to count
  on this estate is skipped and named in the check text, never vacuously in sync. "Per boundary" and "per team" are on
  no record (the layout review is manual), and "bound at create" only on the 9.1.0 bindings read, so each is named
  unread while the declaration carries it; f8's split moves the first to a declaration of its own and the second to a
  step, since a writing probe proves it (f8, 2026-11-02).
- The naming standard: every audited object is declared; an object that does not match its construct's pattern is
  drifted. An audit pattern that differs from the standard means the audit ran against another standard: check_failed.
  The constructs the audit does not reach are named in the check text and leave the line's state as the audited
  constructs give it (f8's reach rule, which corrects its first answer; extending the audit is on f8's queue).

The mode is `detected`; no record stores a platform evaluation time or an exit code (inventory.py's exits mean the
records were written or not, never drift).
"""

from __future__ import annotations

from ..drift import line
from ..drift import unread as unread_line
from ..models import Register
from ..policy import Loaded
from . import utc, worst

COMPANION = "handbook/construct-model"
CHECK_EDGES = "the edge map, the tenancy edges' cardinalities against the counts your estate bore (inventory.py)"
CHECK_NAMES = "the naming audit against the standard, a format check (inventory.py)"
BOUNDARIES_WHY = (
    "not read: no record holds which audited boundary each organization defends or which team each project serves "
    "(the layout review is manual)"
)
TENANCY_EDGES = (
    ("Organization", "Project"),
    ("Project", "Supervisor Namespace"),
    ("Supervisor Namespace", "Region"),
    ("Supervisor Namespace", "Namespace Class"),
    ("Supervisor Namespace", "VPC"),
)


def _part(records: dict[str, dict], name: str) -> tuple[str, dict]:
    return next((p, r) for p, r in records.items() if p.endswith(name))


def _layout(records: dict[str, dict], obj: str) -> tuple[str, str, int, list[dict], list[str], str]:
    path, rec = _part(records, ".edges.json")
    by = {(e.get("from"), e.get("to")): e for e in rec.get("edges") or []}
    results, items = [], []
    # each unread part is named only while the declaration still carries it (f8's split moves both out)
    unread = []
    if "per boundary" in obj or "per team" in obj:
        unread.append("per boundary and per team (the layout review is manual)")
    if "bound at create" in obj:
        unread.append("bound at create (read only on 9.1.0)")
    for f, t in TENANCY_EDGES:
        e = by.get((f, t))
        if e is None or e.get("tier") == "not read":
            results.append("check_failed")
            unread.append(f"the {f} to {t} edge")
        elif e.get("holds") is None:
            unread.append(f"the {f} to {t} edge (nothing to count on this estate)")
        elif e.get("holds"):
            results.append("in_sync")
        else:
            results.append("drifted")
            items.append(
                {
                    "declared": {"edge": f"{f} to {t}", "cardinality": e.get("cardinality")},
                    "actual": {"toPerFrom": e.get("toPerFrom"), "fromPerTo": e.get("fromPerTo")},
                    "resolution": "open",
                }
            )
    return worst(results), CHECK_EDGES, len(results), items, unread, path


def _names(records: dict[str, dict], obj: str) -> tuple[str, str, int, list[dict], list[str], str]:
    path, rec = _part(records, ".naming.json")
    _s, std = _part(records, ".naming-standard.json")
    standard = {c["construct"]: c.get("pattern") for c in std.get("constructs") or []}
    audited = rec.get("constructs") or {}
    results, items, unread = [], [], []
    for construct, c in audited.items():
        if standard.get(construct) != c.get("pattern"):
            results.append("check_failed")
            unread.append(f"{construct} (audited against a pattern the standard does not hold)")
            continue
        off = (c.get("objects") or 0) - (c.get("conform") or 0)
        results += ["in_sync"] * (c.get("conform") or 0) + ["drifted"] * off
        if off:
            items.append(
                {
                    "declared": {"construct": construct, "pattern": c.get("pattern")},
                    "actual": {"objects": c.get("objects"), "conform": c.get("conform")},
                    "resolution": "open",
                }
            )
    never = [c for c in standard if c not in audited]
    if never:
        unread.append(f"no audit for {len(never)} constructs ({', '.join(never)})")
    declared = rec.get("audited_objects") if isinstance(rec.get("audited_objects"), int) else 0
    return worst(results), CHECK_NAMES, declared, items, unread, path


def lines(records: dict[str, dict], pol: Loaded, register: Register, capability: str) -> list[dict]:
    out = []
    for decl in next(c for c in register.capabilities if c.id == capability).declarations:
        obj = decl.object.lower()
        if "naming" in obj:
            reader = _names
        elif "tenancy edges" in obj or "tenancy layout" in obj:
            reader = _layout
        else:
            path, rec = _part(records, ".edges.json")
            out.append(
                unread_line(
                    capability=capability,
                    declaration=decl,
                    scope="organization",
                    read_at=utc(rec["captured_utc"]),
                    companion=COMPANION,
                    check=BOUNDARIES_WHY
                    if "tenancy boundaries" in obj
                    else "not read: no rule of the construct-model adapter reads this declaration",
                    record=path,
                    exit=None,
                    pol=pol,
                )
            )
            continue
        result, check, declared, items, unread, path = reader(records, obj)
        drifted = sum(
            (i["actual"].get("objects", 0) - i["actual"].get("conform", 0))
            if "conform" in i["actual"]
            else 1
            for i in items
        )
        out.append(
            line(
                capability=capability,
                declaration=decl,
                store="the repository" if decl.system == "repo" else "VCF Automation",
                declared_version=None,
                scope="organization",
                mode="detected",
                result=result,
                items_declared=declared,
                items_drifted=drifted,
                items=items,
                read_at=utc(records[path]["captured_utc"]),
                checked_at=None,
                companion=COMPANION,
                check=check + (f"; not read: {'; '.join(unread)}" if unread else ""),
                record=path,
                exit=None,
                pol=pol,
            )
        )
    return out
