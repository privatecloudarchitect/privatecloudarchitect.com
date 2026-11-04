"""The role grade: a view-level fold over the adoption method's rows, as the `world-class-bar` entry rules it.

No method version: core.grade (adoption-levels) grades each capability per scope; a role's grade in a scope is the
minimum over the capabilities it is accountable for (`role_grade: minimum`), shown with the distribution
(`show_distribution`), departments never ordered against each other (`rank_departments: false`), and a grade resting on
an illustrative figure shown as illustrative (`illustrative_evidence`). A role with no graded capability in a scope reads
"none graded", never the minimum of nothing (3c's F5).
"""

from __future__ import annotations

NONE_GRADED = "none graded"


def fold(report: dict, register, pol) -> list[dict]:
    """One row per role per scope: the grade, its ordinal, the distribution of levels, whether it rests on an
    illustrative figure, and the capabilities graded, each with its level."""
    bar = pol.get("world-class-bar")
    if (
        bar.get("role_grade") != "minimum"
    ):  # the policy's rule, read and refused when it is not the one implemented
        raise ValueError(
            f"world-class-bar.role_grade is {bar.get('role_grade')!r}: the fold implements the minimum; another rule "
            "needs its own fold"
        )
    accountable = {c.id: c.accountable for c in register.capabilities}
    by_role_scope: dict[tuple[str, str], list[dict]] = {}
    for g in report["grades"]:
        role = accountable.get(g["capability"])
        if role is None:
            continue
        by_role_scope.setdefault((role, g["scope"]), []).append(g)
    names = {r.id: r.name for r in register.roles}
    out = []
    for role in sorted(names):
        scopes = sorted({scope for (r, scope) in by_role_scope if r == role}) or ["estate"]
        for scope in scopes:
            rows = by_role_scope.get((role, scope), [])
            if not rows:
                out.append(
                    {
                        "role": role,
                        "name": names[role],
                        "scope": scope,
                        "grade": None,
                        "ordinal": None,
                        "label": NONE_GRADED,
                        "distribution": {},
                        "illustrative": False,
                        "capabilities": [],
                        "world_class": bar["world_class_level"],
                    }
                )
                continue
            lowest = min(rows, key=lambda g: g["ordinal"])
            distribution: dict[str, int] = {}
            for g in rows:
                distribution[g["level"]] = distribution.get(g["level"], 0) + 1
            out.append(
                {
                    "role": role,
                    "name": names[role],
                    "scope": scope,
                    "grade": lowest["level"],
                    "ordinal": lowest["ordinal"],
                    "label": lowest["level"],
                    "distribution": distribution,
                    "illustrative": any(g["basis"] == "illustrative" for g in rows),
                    "capabilities": [
                        {
                            "capability": g["capability"],
                            "level": g["level"],
                            "basis": g["basis"],
                            "target": g["target"],
                        }
                        for g in sorted(rows, key=lambda g: (g["ordinal"], g["capability"]))
                    ],
                    "world_class": bar["world_class_level"],
                }
            )
    return out


def departments(portfolio, roles: list[dict]) -> list[dict]:
    """Each department with the roles assigned to it per scope, in the portfolio's order, never ranked."""
    held: dict[str, list[dict]] = {d.id: [] for d in portfolio.departments}
    for a in portfolio.assignments:
        held.setdefault(a.department, []).append({"role": a.role, "scope": a.scope, "kind": a.kind})
    return [{"department": d, "roles": rs} for d, rs in held.items()]
