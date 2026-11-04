"""The gate split, as data: one owner per clause (3c's judgment of step 9, S1).

Every clause of the charter's section 8 (gates.CLAUSES) is judged by exactly one of two runs. The companion judges a
clause that reads the portfolio, the register as mirrored and the policy (`covered`); it reports every other clause by
id, with its reason, as not covered, on every run, the checkout included, so no clause has two judges: a clause that
judges a served view or the reference portfolio's approvals, which an adopter's run has none of (`not_applicable`), and
a clause that judges the register against the site, the code against git, or the layer's own scheduled reads
(`repository`). P-027 holds as one sentence: not covered is never passed.
"""

from __future__ import annotations

from generator.gates import CLAUSES

NOT_APPLICABLE: dict[str, str] = {
    "3.5": "judges the capabilities `strategy-pages` publishes; a run publishes nothing",
    "3.6": "lists the carried values of capabilities `strategy-pages` does not publish; a run publishes nothing",
    "7.2": "judges a public view; a run's views are private",
    "7.3": "judges a public view; a run's views are private",
    "7.6": "judges the reference portfolio's approvals; an adopter's portfolio is never served, so none applies",
    "7.7": "judges the reference portfolio's approvals; an adopter's portfolio is never served, so none applies",
}

_REPOSITORY_GATES = {
    "GATE-2": "the register against the site's vocabulary and the catalog's map",
    "GATE-5": "the register's prerequisites and the ladder charter",
    "GATE-6": "the register's citations, verified in this repository",
    "GATE-9": "the committed views against what the generator emits and the site's rules",
    "GATE-10": "typed facts in the renderer's code",
    "GATE-12": "the register's hand-offs against the published pages",
}
_REPOSITORY_CLAUSES: dict[str, str] = {
    "3.4": "names companions in the companion repository's staging, which a run does not hold",
    "13.3": "the layer's own watch reads, recorded in this repository",
    "13.4": "the strategy check's own recorded runs",
    "13.5": "the lanes against the open registry, this repository's files",
    "13.6": "the jobs against the written capabilities, judged where the register is written",
    "13.7": "the catalog's map, this repository's file",
    "13.8": "the layer's own watch reads, recorded in this repository",
    "13.9": "the vocabulary file's freshness against the site files, which a run does not hold",
    "14.1": "the layer's code against the policy, judged where the code is written",
    "14.2": "a view's raw policy values; the companion's views are judged here in this repository by the same gate",
    "14.6": "method versions against their pinned definitions and golden tests, a git and test lookup",
    "14.7": "the models' structural fingerprint against its lock, this repository's files",
}

GATES_RUN = ("GATE-1", "GATE-3", "GATE-4", "GATE-7", "GATE-8", "GATE-11", "GATE-14")
DATE_CLAUSES = (
    "13.1",
    "13.2",
)  # judged by the date run (check.gate_13 at --day), not by a gate of GATES_RUN


def owner(clause: str) -> tuple[str, str]:
    """Which run judges a clause: ("covered", "") for the companion; ("not_applicable", why) or ("repository", why)
    otherwise."""
    if clause in NOT_APPLICABLE:
        return "not_applicable", NOT_APPLICABLE[clause]
    if clause in _REPOSITORY_CLAUSES:
        return "repository", _REPOSITORY_CLAUSES[clause]
    gate = CLAUSES[clause][0]
    if gate in _REPOSITORY_GATES:
        return "repository", _REPOSITORY_GATES[gate]
    if gate == "GATE-13":
        if clause in DATE_CLAUSES:
            return "covered", ""
        return "repository", "the strategy check's own reads"
    if (
        gate not in GATES_RUN
    ):  # a gate the split does not name has no judge here, and is never covered by default (3c)
        raise ValueError(
            f"{clause}'s gate {gate} is in neither GATES_RUN nor the repository's gates: route it"
        )
    return "covered", ""


def partition() -> tuple[set[str], set[str], set[str]]:
    """The three sets, each clause in exactly one."""
    covered, not_applicable, repository = set(), set(), set()
    for clause in CLAUSES:
        kind, _ = owner(clause)
        {"covered": covered, "not_applicable": not_applicable, "repository": repository}[kind].add(
            clause
        )
    assert covered | not_applicable | repository == set(CLAUSES)
    assert (
        not (covered & not_applicable)
        and not (covered & repository)
        and not (not_applicable & repository)
    )
    return covered, not_applicable, repository


def report(results, date_found, date_listed, date_judged: bool = True) -> dict:
    """gates.json: each covered clause's findings, and every other clause named with why it is not covered here. A
    covered clause whose gate could not judge (the gate's result is not covered: a precondition raised, or the files
    did not type), whose gate produced no result at all (dropped from the run), or, for the date clauses, whose date
    run did not happen, is `not_judged` with the reason, never passed (P-027); the run exits 3 on one."""
    covered, _n, _r = partition()
    unjudged: dict[str, dict] = {}  # by gate: why, and where
    for r in results:
        if r.state == "not_covered":
            unjudged[r.gate] = {
                "why": r.why or "the gate did not judge",
                "at": f"{r.at[0]}:{r.at[1]}" if r.at else None,
            }
    ran = {r.gate for r in results}
    for gate in GATES_RUN:
        if gate not in ran:
            unjudged[gate] = {"why": "the gate did not run", "at": None}
    if not date_judged:
        unjudged["GATE-13"] = {"why": "the date run did not happen", "at": None}
    found: dict[str, list[dict]] = {}
    for r in results:
        for f in [*r.findings, *r.listed]:
            if f.clause in covered:
                found.setdefault(f.clause, []).append(
                    {
                        "file": f.file,
                        "line": f.line,
                        "what": f.what,
                        "edit": f.edit,
                        "listed": f.listed,
                    }
                )
    for f in [*date_found, *date_listed]:
        if f.clause in covered:
            found.setdefault(f.clause, []).append(
                {"file": f.file, "line": f.line, "what": f.what, "edit": f.edit, "listed": f.listed}
            )
    clauses = {}
    for clause, (gate, text) in sorted(
        CLAUSES.items(), key=lambda kv: [int(x) for x in kv[0].split(".")]
    ):
        kind, why = owner(clause)
        entry = {"gate": gate, "text": text, "owner": kind}
        if kind == "covered" and gate in unjudged:
            entry["findings"] = found.get(clause, [])
            entry["state"] = "not_judged"
            entry.update(unjudged[gate])
        elif kind == "covered":
            entry["findings"] = found.get(clause, [])
            entry["state"] = (
                "refused" if any(not x["listed"] for x in entry["findings"]) else "passed"
            )
        else:
            entry["state"] = "not_covered"
            entry["why"] = why
        clauses[clause] = entry
    refused = sum(1 for c in clauses.values() if c["state"] == "refused")
    return {
        "clauses": clauses,
        "refused": refused,
        "not_covered": sum(1 for c in clauses.values() if c["state"] == "not_covered"),
        "not_judged": sum(1 for c in clauses.values() if c["state"] == "not_judged"),
    }
