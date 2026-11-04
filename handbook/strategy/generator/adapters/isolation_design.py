"""The isolation-design adapter: tenant-isolation, read from isolation.py's read of the bindings and the action regime.
verify.py's matrix is a writing proof and feeds no line (R5). f8's rules R1 to R6 apply (adapters/__init__.py).

Two lines, scope `organization`; a project's placeholder follows listing order, so it names an item and keys no line
(R6) until isolation.py's placeholders are stable (f8's queue).

- The tenant group's edit binding per project. Each project the bindings name is an item: it is in sync when an `edit`
  binding names a Group, no binding of any role names a User (the design is "five settings, and not one of them is a
  per-user object": the tenant is a group from the identity provider, and membership there is the only per-user input,
  f8), and every binding's name follows the rule. User bindings matching the proof's test principals are drift all the
  same: the record cannot tell them apart (subjects are scrubbed), and the fix is a declaration naming proof projects by
  a stable key (R6), not a looser rule. A failed listing reads as no binding, which is drift and fails loud (f8); a
  project with no binding at all is invisible to the record. Which group is the tenant's is not on the record (subjects
  are scrubbed), and "applied server-side" is carried from the 9.1 reading, so neither is judged.
- The isolation policies: the declared pair, the tenant's grant and the operators' grant, each an all-actions policy
  that must be HARD. Two all-actions HARD policies naming two different groups are the pair present; fewer is drift.
  Which group is whose is not on the record. Any further policy is an extra, listed in the check text, never drift (f8).
  Both grants of the pair are taken to be all-actions, the assumption scrubbed subjects force: it holds on today's
  record (two HARD all-actions grants and one extra), and on an estate whose tenant grant lists its actions the line
  would read drifted falsely (f8), until the record says which grant is whose.

The mode is `detected`; the record stores no platform evaluation time and no exit code.
"""

from __future__ import annotations

from ..drift import line
from ..models import Register
from ..policy import Loaded
from . import utc, worst

COMPANION = "handbook/isolation-design"
CHECK = "the bindings and their names against the rule, and the action regime (isolation.py)"


def _bindings(rec: dict) -> tuple[str, int, list[dict], list[str]]:
    by: dict[str, list[dict]] = {}
    for b in rec.get("bindings") or []:
        by.setdefault(b.get("project"), []).append(b)
    if not by:
        return "drifted", 0, [], ["no binding was listed, which a failed listing also gives"]
    results, items = [], []
    for project, bs in by.items():
        group_edit = any(b.get("role") == "edit" and b.get("subjectKind") == "Group" for b in bs)
        user_bound = sum(1 for b in bs if b.get("subjectKind") == "User")
        off_rule = sum(1 for b in bs if not b.get("nameFollowsRule"))
        if group_edit and not user_bound and not off_rule:
            results.append("in_sync")
            continue
        results.append("drifted")
        items.append(
            {
                "declared": {
                    "project": project,
                    "edit binding": "to a Group",
                    "bindings to a User": 0,
                    "names": "follow the rule",
                },
                "actual": {
                    "project": project,
                    "edit binding to a Group": group_edit,
                    "bindings to a User": user_bound,
                    "names off the rule": off_rule,
                },
                "resolution": "open",
            }
        )
    return (
        worst(results),
        len(by),
        items,
        [
            "which group is the tenant's (subjects are scrubbed)",
            "whether a User binding is the proof's test principal (subjects are scrubbed; no declaration names proof projects)",
        ],
    )


def _policies(rec: dict) -> tuple[str, int, list[dict], list[str]]:
    regime = rec.get("actionRegime")
    if regime is None:
        return "check_failed", 2, [], ["the action regime was not read"]
    grants = [p for p in regime if p.get("actions") == "all"]
    hard = {
        n.get("subject")
        for p in grants
        if p.get("enforcement") == "HARD"
        for n in p.get("names") or []
    }
    soft = [p for p in grants if p.get("enforcement") != "HARD"]
    extras = [p for p in regime if p.get("actions") != "all"]
    unread = [
        "which group's grant is the tenant's and which the operators' (subjects are scrubbed)"
    ]
    if extras:
        unread.append(
            f"{len(extras)} further policy, an extra, not judged"
            if len(extras) == 1
            else f"{len(extras)} further policies, extras, not judged"
        )
    items = []
    if len(hard) < 2:
        items.append(
            {
                "declared": "the tenant's and the operators' grants, all actions, HARD",
                "actual": f"{len(hard)} group(s) named by an all-actions HARD policy",
                "resolution": "open",
            }
        )
    for p in soft:
        items.append(
            {
                "declared": "HARD",
                "actual": {"scope": p.get("scope"), "enforcement": p.get("enforcement")},
                "resolution": "open",
            }
        )
    return ("drifted" if items else "in_sync"), 2, items, unread


def lines(records: dict[str, dict], pol: Loaded, register: Register, capability: str) -> list[dict]:
    ((record_path, rec),) = records.items()
    out = []
    for decl in next(c for c in register.capabilities if c.id == capability).declarations:
        reader = _policies if "polic" in decl.object else _bindings
        result, declared, items, unread = reader(rec)
        out.append(
            line(
                capability=capability,
                declaration=decl,
                store="VCF Automation",
                declared_version=None,
                scope="organization",
                mode="detected",
                result=result,
                items_declared=declared,
                items_drifted=len(items),
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
