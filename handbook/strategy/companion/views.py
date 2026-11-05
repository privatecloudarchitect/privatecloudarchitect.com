"""The companion's views, each in its own layout with its provenance (GATE-14, 14.5): the role-by-role adoption view
against the bar, the drift and exceptions, the ranked board, the index, and the private department brief. Every figure
comes from the generator's report, the drift lines, the portfolio or the policy, never typed here (GATE-10); the
expiry and the renewal cap are read from the policy's `exception-expiry` entry (3c's F3)."""

from __future__ import annotations

from generator.models import parse_day
from generator.policy import add
from generator.render import NAME

from . import grades as _grades
from .layout import E, kind, page, table

NAV = [
    (f"{NAME} companion", "index.html"),
    ("Adoption", "adoption.html"),
    ("Drift", "drift.html"),
    ("Board", "board.html"),
]


def provenance_text(prov: dict, day: str, layout: str, extra: str = "") -> str:
    methods = "; ".join(
        f"{m} version {v['version']} ({v['status']})" for m, v in sorted(prov["methods"].items())
    )
    return (
        f"Generated {prov['generated_at']} by {methods or 'no method'}, under policy version {prov['policy_version']}; "
        f"schemas policy {prov['schemas']['policy']}, portfolio {prov['schemas']['portfolio']}, register "
        f"{prov['schemas']['register']}; drift-read contract {', '.join(str(c) for c in prov['contracts']) or 'none'}; "
        f"inputs {prov['input_digest']}, overrides {prov['overrides_digest']}; judged at {day}; {layout}.{extra}"
    )


def _exceptions(portfolio, pol, day: str) -> list[dict]:
    """Each exception with its expiry derived from the policy, and whether it counts as drift today."""
    expiry = pol.get("exception-expiry")
    cycle = pol.get("cycle")
    out = []
    judged = parse_day(day)
    for c in portfolio.capabilities:
        for x in c.exceptions:
            ends = parse_day(x.granted)
            for _ in range(expiry["expires_after_cycles"]):
                ends = add(ends, cycle["length"])
            past_cap = x.renewals > expiry["max_consecutive_renewals"]
            out.append(
                {
                    "capability": c.id,
                    "id": x.id,
                    "part": x.part,
                    "granted": x.granted,
                    "expires": ends.isoformat(),
                    "renewals": x.renewals,
                    "cap": expiry["max_consecutive_renewals"],
                    "expired": judged > ends,
                    "past_cap": past_cap,
                    "counts_as_drift": judged > ends or past_cap,
                    "kind": x.kind,
                }
            )
    return out


def adoption(
    report: dict, register, portfolio, pol, lines: list[dict], prov: str, source: str
) -> str:
    roles = _grades.fold(report, register, pol)
    rows = []
    for r in roles:
        label = E(r["label"]) if r["grade"] else f'<span class="warn">{E(r["label"])}</span>'
        if r["illustrative"]:
            label += ' <span class="ill">(illustrative)</span>'
        dist = ", ".join(f"{E(k)} {v}" for k, v in sorted(r["distribution"].items())) or "none"
        caps = "; ".join(
            f"<code>{E(c['capability'])}</code> {E(c['level'])}"
            + (f" ({kind(c['basis'])})" if c["basis"] != "measured" else "")
            for c in r["capabilities"]
        )
        rows.append([E(r["name"]), E(r["scope"]), label, E(r["world_class"]), dist, caps or "none"])
    body = "<h2>Each role against the bar</h2>" + table(
        ["Role", "Scope", "Grade", "The bar", "Distribution", "Capabilities, each at its level"],
        rows,
    )
    depts = _grades.departments(portfolio, roles)
    rows = [
        [
            E(d["department"]),
            "; ".join(f"{E(x['role'])} ({E(x['scope'])}, {kind(x['kind'])})" for x in d["roles"])
            or "no role assigned",
        ]
        for d in depts
    ]
    body += (
        "<h2>Departments and the roles they hold</h2><p>Never ranked against each other.</p>"
        + table(["Department", "Roles held, per scope"], rows)
    )
    judged = sum(1 for x in lines if x["result"] in ("in_sync", "drifted"))
    body += (
        f"<h2>Drift reads</h2><p>{len(lines)} declarations read; {judged} judged "
        f"({sum(1 for x in lines if x['result'] == 'in_sync')} in sync, {sum(1 for x in lines if x['result'] == 'drifted')} drifted); "
        f"{sum(1 for x in lines if x['result'] == 'check_failed')} check failed; {sum(1 for x in lines if x['result'] == 'not_covered')} not covered.</p>"
    )
    return page(
        "Adoption, role by role",
        f"The {E(portfolio.estate)} estate's roles against the adoption bar, from the recorded steps, the assignments and the drift reads",
        body,
        prov,
        source,
        NAV,
    )


def drift(lines: list[dict], portfolio, pol, day: str, prov: str, source: str) -> str:
    rows = []
    for x in sorted(lines, key=lambda x: (x["capability"], x["declaration"]["object"])):
        cls = {"in_sync": "ok", "drifted": "bad", "check_failed": "warn", "not_covered": "ill"}[
            x["result"]
        ]
        rows.append(
            [
                f"<code>{E(x['capability'])}</code>",
                E(x["declaration"]["object"]),
                E(x["declaration"]["writer"] or ""),
                f'<span class="{cls}">{E(x["result"])}</span>',
                f"{x['items_drifted']} of {x['items_declared']}",
                E(x["source"]["check"]),
                E(x["read_at"]),
            ]
        )
    body = "<h2>Every declaration, as last read</h2>" + table(
        [
            "Capability",
            "Declaration",
            "Writer",
            "Result",
            "Drifted of declared",
            "The check",
            "Read at",
        ],
        rows,
    )
    exc = _exceptions(portfolio, pol, day)
    rows = [
        [
            f"<code>{E(x['capability'])}</code>",
            E(x["id"]),
            E(x["part"]),
            E(x["granted"]),
            E(x["expires"]),
            f"{x['renewals']} of {x['cap']}",
            '<span class="bad">counts as drift</span>'
            if x["counts_as_drift"]
            else '<span class="ok">covers its gap</span>',
            kind(x["kind"]),
        ]
        for x in exc
    ]
    body += (
        "<h2>Exceptions</h2><p>Expiry and the renewal cap come from the policy's exception rule.</p>"
        + (
            table(
                [
                    "Capability",
                    "Exception",
                    "Part",
                    "Granted",
                    "Expires",
                    "Renewals",
                    "Today",
                    "Kind",
                ],
                rows,
            )
            if rows
            else "<p>No exception is recorded.</p>"
        )
    )
    return page(
        "Drift and exceptions",
        f"The {E(portfolio.estate)} estate's declarations against what runs, and the exceptions beside the drift they explain",
        body,
        prov,
        source,
        NAV,
    )


def board(report: dict, portfolio, pol, prov: str, source: str) -> str:
    b = report["board"]
    rows = []
    for i, r in enumerate(b["ranked"], 1):
        rows.append(
            [
                str(i),
                f"<code>{E(r['id'])}</code>",
                f"{r['score']} ({kind(r['score_kind'])})",
                f"{r['own_cd3']}",
                ", ".join(f"<code>{E(x)}</code>" for x in r["chain"]),
                f"{r['duration']} {E(r['duration_unit'])} ({kind(r['duration_kind'])})",
            ]
        )
    body = "<h2>The ranked board</h2>" + table(
        ["Rank", "Initiative", "Score", "Own CD3", "Chain", "Duration"], rows
    )
    if b.get("unranked"):
        body += (
            "<h2>Not ranked</h2><ul>"
            + "".join(
                f"<li><code>{E(str(u.get('id', u)))}</code> {E(str(u.get('why', '')))}</li>"
                if isinstance(u, dict)
                else f"<li><code>{E(str(u))}</code></li>"
                for u in b["unranked"]
            )
            + "</ul>"
        )
    cap = b.get("capacity")
    if cap:
        body += f"<h2>Capacity</h2><p>{E(str(cap))}</p>"
    return page(
        "What the estate funds first",
        f"The {E(portfolio.estate)} estate's initiatives ranked by the cost of delay, within capacity: what to fund first",
        body,
        prov,
        source,
        NAV,
    )


def index(portfolio, departments: list[dict], gates_report: dict, prov: str, source: str) -> str:
    body = (
        "<h2>Views</h2><ul>"
        + "".join(f'<li><a href="{E(h)}">{E(t)}</a></li>' for t, h in NAV[1:])
        + "</ul>"
    )
    body += (
        "<h2>Department briefs (private, under private/briefs/)</h2><ul>"
        + "".join(
            f"<li>{E(d['department'])}: <code>private/briefs/{E(d['department'])}.html</code></li>"
            for d in departments
        )
        + "</ul>"
    )
    body += (
        f"<h2>Gates</h2><p>{gates_report['refused']} clause(s) refused; {gates_report['not_covered']} not covered here; "
        f"{gates_report['not_judged']} not judged (each named with its reason in gates.json).</p>"
    )
    return page(
        f"{NAME} companion for the {portfolio.estate} estate",
        "Adoption against the bar, drift and exceptions, the board, and a brief per department",
        body,
        prov,
        source,
        NAV,
    )


def brief(
    department: str,
    roles: list[dict],
    portfolio,
    register,
    report: dict,
    lines: list[dict],
    pol,
    day: str,
    prov: str,
    source: str,
) -> str:
    held = {r["role"] for r in roles}
    caps = [c for c in register.capabilities if c.accountable in held]
    by_id = {c.id: c for c in portfolio.capabilities}
    grades = {(g["capability"], g["scope"]): g for g in report["grades"]}
    rows = []
    for c in caps:
        pc = by_id.get(c.id)
        for st in pc.state if pc else []:
            g = grades.get((c.id, st.scope))
            drifts = [x for x in lines if x["capability"] == c.id]
            effort = "; ".join(
                f"{k} {v.value if v.value is not None else 'not recorded'} ({kind(v.kind)})"
                for k, v in (pc.effort or {}).items()
            )
            rows.append(
                [
                    f"<code>{E(c.id)}</code>",
                    E(c.accountable),
                    E(st.scope),
                    E(g["level"] if g else "none graded"),
                    f"{sum(1 for x in drifts if x['result'] == 'drifted')} drifted of {len(drifts)} read",
                    effort or "none recorded",
                    "; ".join(
                        f"{E(t)} {E(str(v.value))} {E(v.target_kind)}"
                        for t, v in (pc.targets or {}).items()
                    )
                    or "none",
                ]
            )
    body = f"<h2>What {E(department)} holds</h2>" + table(
        ["Capability", "Role", "Scope", "Grade", "Drift", "Recurring effort", "Targets"], rows
    )
    exc = [x for x in _exceptions(portfolio, pol, day) if x["capability"] in {c.id for c in caps}]
    body += "<h2>Exceptions</h2>" + (
        table(
            ["Capability", "Exception", "Expires", "Today"],
            [
                [
                    E(x["capability"]),
                    E(x["id"]),
                    E(x["expires"]),
                    "counts as drift" if x["counts_as_drift"] else "covers its gap",
                ]
                for x in exc
            ],
        )
        if exc
        else "<p>None recorded.</p>"
    )
    sponsored = [
        r
        for r in report["board"]["ranked"]
        if any(i.sponsor == role for i in register.initiatives if i.id == r["id"] for role in held)
    ]
    body += "<h2>Initiatives its roles sponsor</h2>" + (
        table(
            ["Initiative", "Score", "Chain"],
            [
                [f"<code>{E(r['id'])}</code>", str(r["score"]), ", ".join(r["chain"])]
                for r in sponsored
            ],
        )
        if sponsored
        else "<p>None ranked.</p>"
    )
    return page(
        f"{department}: the department brief",
        f"Private: the {E(portfolio.estate)} estate's {E(department)} department, its roles' capabilities, drift, effort, targets, exceptions and initiatives",
        body,
        prov,
        source,
        [(f"{NAME} companion", "../../index.html")],
    )
