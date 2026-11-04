"""The reference portfolio's approvals, and the nodes they cover (40-BREADTH.md step 2; DEC-14).

A served strategy page shows a figure of the reference portfolio only in the form the operator approved (the served
projection, S1 to S4). This module holds what an approval is made of:

  approvable(portfolio)  every node an approval must cover, each once, by its address: each mapping whose `kind` is
                         `illustrative` or `input` (the file-level `approval` and the `approvals` themselves aside), each
                         policy override, `ownership` as one mapping, and each plain `unconverted` item. An initiative's
                         `commitment` and `rank`, which carry no kind, travel in the form of its `status` node.
  form(node)             a node as an approval records it: its fields as its model dumps them, `note` left out (no view
                         renders a note) and every child that carries its own `kind` left out (that child is a node of
                         its own); `None` kept.
  digest(form)           the first 16 hex digits of SHA-256 over the form's canonical JSON (sorted keys, no spaces).

An address is a tuple of strings from the portfolio's root: a mapping's key, or a list item's key under `KEYS`, the key
each list is held unique by (models.listed_once), so adding an item to a list moves no other item's address.

An approval records the digests its ask carried, never computed after the ruling; the one exception is D4-14's, recorded
once from the portfolio as it stood at `bd89fd1f` (`d4_14_nodes`), the file the ruling saw.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from .models import SCHEMA_VERSIONS, Portfolio, Register

Address = tuple[str, ...]

APPROVABLE_KINDS = ("illustrative", "input")

# The key each keyed list's items are addressed by, by the list's place (its parent's path with `*` for a keyed item).
KEYS: dict[tuple[str, ...], Any] = {
    ("departments",): lambda x: x["id"],
    ("assignments",): lambda x: f"{x['role']}:{x['scope']}",
    ("role_history",): lambda x: x["id"],
    ("capacity",): lambda x: x["role"],
    ("capabilities",): lambda x: x["id"],
    ("capabilities", "*", "state"): lambda x: x["scope"],
    ("capabilities", "*", "readings"): lambda x: x["id"],
    ("capabilities", "*", "exceptions"): lambda x: x["id"],
    ("conversion_rates",): lambda x: x["measure"],
    ("unconverted",): lambda x: x if isinstance(x, str) else x["measure"],
    ("initiatives",): lambda x: x["id"],
    ("initiatives", "*", "planning"): lambda x: x["id"],
    ("decision_log",): lambda x: x["id"],
    ("policy", "overrides"): lambda x: x["entry"],
    ("local_capabilities",): lambda x: x["id"],
    ("local_initiatives",): lambda x: x["id"],
    ("drivers",): lambda x: x["id"],
    ("trigger_events",): lambda x: x["id"],
    ("scans",): lambda x: x["id"],
}

# the parts of a portfolio an approval never covers: the approvals themselves, and an estate's own definitions, which
# are the register's kind of thing (an adopter's portfolio needs no approval, since it is never served)
NOT_APPROVED = (
    "approval",
    "approvals",
    "local_capabilities",
    "local_initiatives",
    "drivers",
    "trigger_events",
    "scans",
)


def _pattern(address: Address) -> tuple[str, ...]:
    """An address with each keyed item's key written `*`, the form `KEYS` is looked up by."""
    out: list[str] = []
    keyed = set(KEYS)
    for seg in address:
        if tuple(out) in keyed:
            out.append("*")
        else:
            out.append(seg)
    return tuple(out)


def address_of(text: str) -> Address:
    """An address written as a path, `capabilities/*/investment`: the segments between slashes, `*` standing for a
    keyed item (the form `KEYS` is looked up by). The one grammar every path a portfolio's node is named by is written
    in (3c's judgment of step 9): an import's `supplies`, an ask's node path, a withheld address."""
    parts = tuple(p for p in text.strip().strip("/").split("/") if p)
    if not parts:
        raise ValueError("an empty address")
    return parts


def under(address: Address, prefix: Address) -> bool:
    """Whether a node's address lies under a prefix: segment by segment, `*` in the prefix matching any one segment,
    the prefix no longer than the address."""
    if len(prefix) > len(address):
        return False
    return all(p in ("*", a) for p, a in zip(prefix, address, strict=False))


def _carries_kind(x: Any) -> bool:
    return isinstance(x, dict) and "kind" in x


def form(node: Any) -> Any:
    """A node as an approval records it: `note` left out, each child that carries its own kind left out."""
    if not isinstance(node, dict):
        return node
    return {k: v for k, v in node.items() if k != "note" and not _carries_kind(v)}


def digest(node_form: Any) -> str:
    """The first 16 hex digits of SHA-256 over a form's canonical JSON."""
    text = json.dumps(node_form, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def dumped(portfolio: Portfolio) -> dict:
    """A portfolio as its model dumps it, the form every address and every recorded node is read from."""
    return portfolio.model_dump(mode="json", by_alias=True)


def approvable(portfolio: Portfolio | dict) -> list[tuple[Address, Any]]:
    """Every node of a portfolio an approval must cover, each once, as (address, form)."""
    data = dumped(portfolio) if isinstance(portfolio, Portfolio) else portfolio
    out: list[tuple[Address, Any]] = []

    def walk(node: Any, address: Address) -> None:
        if isinstance(node, dict):
            if node.get("kind") in APPROVABLE_KINDS and address:
                out.append((address, form(node)))
            for k, v in node.items():
                walk(v, (*address, str(k)))
        elif isinstance(node, list):
            key = KEYS.get(_pattern(address))
            for item in node:
                if (
                    key is None
                ):  # a list no key addresses holds no approvable node (evidence, loops, stages)
                    continue
                walk(item, (*address, str(key(item))))

    for top, value in data.items():
        if top in NOT_APPROVED or top in ("policy", "ownership", "unconverted"):
            continue
        walk(value, (top,))
    for o in data["policy"]["overrides"]:
        out.append((("policy", "overrides", o["entry"]), form(o)))
    out.append((("ownership",), data["ownership"]))
    for x in data["unconverted"]:
        if isinstance(x, str):
            out.append((("unconverted", x), x))
        elif x.get("kind") in APPROVABLE_KINDS:
            out.append((("unconverted", x["measure"]), form(x)))
    # an initiative's kindless fields travel in its status node's form
    plans = {i["id"]: i for i in data["initiatives"]}
    out = [
        (a, dict(f, commitment=plans[a[1]]["commitment"], rank=plans[a[1]]["rank"]))
        if len(a) == 3 and a[0] == "initiatives" and a[2] == "status"
        else (a, f)
        for a, f in out
    ]
    seen: set[Address] = set()
    for a, _f in out:
        if a in seen:
            raise ValueError(f"the node {'/'.join(a)} is approvable twice")
        seen.add(a)
    return out


def record(
    portfolio: Portfolio | dict, date: str, decision: str, source: str, schema: int, ask: str | None
) -> dict:
    """An approval of every approvable node, each with its form and digest, in the form `models.NodeApproval` types."""
    return {
        "date": date,
        "decision": decision,
        "source": source,
        "schema": schema,
        "ask": ask,
        "nodes": [
            {"path": list(a), "node": f, "digest": digest(f)} for a, f in approvable(portfolio)
        ],
    }


# D4-14's approval (2026-10-28), the one recorded after its ruling: its nodes re-derived from the reference portfolio as
# it stood at bd89fd1f (blob 69948b36 of portfolio.example.yaml, frozen as the schema 1 migration fixture), migrated to
# the schema its record names; the record itself (its date, decision and source) is the portfolio's, never typed here
D4_14_FILE = "generator/fixtures/migrate/portfolio.schema1.yaml"  # under the layer's folder


def d4_14_nodes() -> list[dict]:
    """D4-14's approvable nodes re-derived from the frozen file the ruling saw, migrated to the current schema, each
    with its form and digest, as `record` writes them. The approval itself stays recorded at schema 3 (never
    rewritten); a test compares it to this list through `_carried_forward`, so a node a later schema retyped out of
    the approvable set (schema 4's typing of the plain `unconverted` id) is named there, not here."""
    from pathlib import Path

    from .migrate import upgrade
    from .policy import read_yaml

    layer = Path(__file__).resolve().parent.parent
    doc, _notes = upgrade("portfolio", read_yaml(layer / D4_14_FILE))
    return [
        {"path": list(a), "node": f, "digest": digest(f)}
        for a, f in approvable(Portfolio.model_validate(doc))
    ]


# ── the served projection (40-BREADTH.md step 2, S1 to S4) ─────────────────────────────────────────────────────────
# How a never-approved node is withheld, by the shape its address names (`*` a keyed segment). `remove`: the mapping
# entry or list item leaves; `stub`: the node is replaced by the form its model holds for a figure no record holds, so
# core computes exactly as it does on one (the address is recorded, so a page says "not yet published", never "not
# recorded"); `none`: an optional node is set to None; `placeholder`: a required node with no such form is filled with
# a measured placeholder no served view reads, its initiative taken off the board; `leave`: the initiative leaves the
# served views (its plan was never approved); `refuse`: a node the projection cannot withhold, which GATE-7's clause
# 7.6 refuses in the pre-push of the change that lands it, so no build meets one.
WITHHOLD: dict[tuple[str, ...], tuple[str, Any]] = {
    ("departments", "*"): ("remove", None),
    ("assignments", "*"): ("remove", None),
    ("role_history", "*"): ("remove", None),
    ("capacity", "*"): ("refuse", None),  # the board plans its constrained role's line (7.6)
    ("capabilities", "*", "target_grade"): (
        "refuse",
        None,
    ),  # a published capability's page shows it (7.6)
    ("capabilities", "*", "state", "*", "steps", "*"): (
        "stub",
        {"done": False, "kind": "not_recorded"},
    ),
    ("capabilities", "*", "readings", "*"): ("remove", None),
    ("capabilities", "*", "investment", "*"): ("stub", {"kind": "not_recorded"}),
    ("capabilities", "*", "effort", "*"): ("stub", {"kind": "not_recorded"}),
    ("capabilities", "*", "parameters", "*"): ("stub", {"kind": "not_recorded"}),  # schema 5
    ("capabilities", "*", "targets", "*"): ("remove", None),
    ("capabilities", "*", "exceptions", "*"): ("remove", None),
    ("conversion_rates", "*"): ("remove", None),
    ("unconverted", "*"): ("remove", None),
    ("estimate_adjustment",): ("refuse", None),
    ("ownership",): ("refuse", None),
    ("policy", "overrides", "*"): (
        "refuse",
        None,
    ),  # an override decides what every figure computes (7.6)
    ("initiatives", "*", "status"): ("leave", None),
    ("initiatives", "*", "applicability"): ("none", None),
    ("initiatives", "*", "cost_of_delay"): ("none", None),
    ("initiatives", "*", "cost_of_delay", "baseline"): ("stub", {"kind": "not_recorded"}),
    ("initiatives", "*", "cost_of_delay", "after"): ("none", None),
    ("initiatives", "*", "duration"): ("placeholder", None),
    ("initiatives", "*", "added_effort"): (
        "stub",
        {"loops": [], "change": None, "kind": "not_recorded"},
    ),
    ("initiatives", "*", "planning", "*"): ("remove", None),
    ("decision_log", "*"): ("remove", None),
}


def shape_of(address: Address) -> tuple[str, ...]:
    """The pattern an address matches in `WITHHOLD`: each keyed segment written `*`, a mapping's free key (an
    investment's step, a target's value) written `*` too."""
    pattern = _pattern(address)
    if pattern in WITHHOLD:
        return pattern
    for known in WITHHOLD:
        if len(known) == len(pattern) and all(
            k == "*" or k == p for k, p in zip(known, pattern, strict=True)
        ):
            return known
    raise ValueError(f"no withholding rule names the node {'/'.join(address)}")


def _get(data: Any, address: Address) -> tuple[Any, Any, Any]:
    """(the parent, the key or index in it, the node) at an address, or (None, None, None) when it is absent."""
    parent, slot, node, at = None, None, data, ()
    for seg in address:
        if isinstance(node, dict):
            if seg not in node:
                return None, None, None
            parent, slot, node = node, seg, node[seg]
        elif isinstance(node, list):
            key = KEYS.get(_pattern(at))
            hit = [i for i, x in enumerate(node) if key is not None and str(key(x)) == seg]
            if len(hit) != 1:
                return None, None, None
            parent, slot, node = node, hit[0], node[hit[0]]
        else:
            return None, None, None
        at = (*at, seg)
    return parent, slot, node


@dataclass(frozen=True)
class Projection:
    """The register and the reference portfolio as the served views may show them, and what the projection held back.

    `withheld` maps each withheld node's address to the keys that place it on a page (a reading's value, a figure's
    part), so a page says where it would have stood without reading it; `off_board` maps each kept initiative whose
    score core cannot compute from what is served to the reason; `not_yet_published` names each left-out capability the
    projection still names."""

    register: Register
    portfolio: Portfolio
    published: frozenset[str]
    carried: frozenset[str]
    not_yet_published: frozenset[str]
    withheld: dict[Address, dict] = field(default_factory=dict)
    approved_form: frozenset[Address] = frozenset()
    off_board: dict[str, dict] = field(
        default_factory=dict
    )  # {why, capability}: why its score is not shown


def _carried_forward(address: Address, node_form: Any, schema: int) -> list[tuple[Address, Any]]:
    """A recorded node carried to the current schema by the node migrations, in memory; a record is never rewritten."""
    from .migrate import NODE_MIGRATIONS

    out = [(address, node_form)]
    for start in range(schema, SCHEMA_VERSIONS["portfolio"]):
        step = []
        for a, f in out:
            fn = NODE_MIGRATIONS.get((shape_of(a), start))
            step += fn(a, f) if fn else [(a, f)]
        out = step
    return out


def approvals_in_force(portfolio: Portfolio) -> dict[Address, Any]:
    """Each approved node's form at the current schema, by address, the latest approval's where two name one node."""
    out: dict[Address, Any] = {}
    for a in sorted(portfolio.approvals, key=lambda x: x.date):
        for n in a.nodes:
            for address, node_form in _carried_forward(tuple(n.path), n.node, a.schema_):
                out[address] = node_form
    return out


def _restricted(current: Any, recorded: Any) -> Any:
    """Today's form restricted to the fields the recorded form holds: a field a later schema added is not compared."""
    if isinstance(current, dict) and isinstance(recorded, dict):
        return {k: v for k, v in current.items() if k in recorded}
    return current


def project(register: Register, portfolio: Portfolio, pol: Any) -> Projection:
    """The served projection of the register and the reference portfolio (40-BREADTH.md step 2, S1 to S3)."""
    from .models import InstrumentGap, resolve_value

    pages = set(pol.for_estate(portfolio.policy.overrides).get("strategy-pages"))
    written = [c.id for c in register.capabilities]
    published = frozenset(c for c in written if f"/strategy/{c}" in pages)
    carried = frozenset(
        c.id
        for c in register.capabilities
        if any(isinstance(v.instrument, InstrumentGap) for v in c.value)
    )
    left_out = set(written) - published
    gone = left_out - carried  # a left-out capability whose initiatives and figures leave with it
    owner = {v.id: c.id for c in register.capabilities for v in c.value}

    def owned_by(measure: str) -> str | None:
        try:
            return owner.get(resolve_value(register, measure).id)
        except ValueError:
            return None

    # each approvable node's state: approved as it stands, approved in another form, or never approved
    in_force = approvals_in_force(portfolio)
    state: dict[Address, str] = {}
    for address, node_form in approvable(portfolio):
        if address not in in_force:
            state[address] = "unapproved"
        elif _restricted(node_form, in_force[address]) == in_force[address]:
            state[address] = "approved"
        else:
            state[address] = "approved_form"

    planned = {i.id for i in portfolio.initiatives}

    def plan_approved(iid: str) -> bool:
        """An initiative is served only once the estate has planned it and its plan is approved: a register
        initiative with no plan in the portfolio is on no board (core's own rule), and one whose status node was
        never approved has a plan nobody has ruled on (S1)."""
        return (
            iid in planned and state.get(("initiatives", iid, "status"), "approved") != "unapproved"
        )

    def ids(xs: list[str]) -> set[str]:
        return {x.split(":", 1)[1] if ":" in x else x for x in xs}

    plans = {p.id: p for p in portfolio.initiatives}

    def effort_holders(d) -> set[str]:
        """The left-out capabilities whose loops the plan's added effort names (core.added_effort's scope: a loop is
        read on a capability the initiative establishes or improves). The closure per relation (S3) treats them as
        the cost rate's owner is treated: a gone holder takes the initiative with it; a carried one keeps it, off
        the board with the reason, its added effort left out of the served plan (a served view cannot sum a loop
        whose capability the projection does not hold)."""
        plan = plans.get(d.id)
        effort = getattr(plan, "added_effort", None) if plan else None
        scope = ids(d.establishes) | ids(d.improves)
        out: set[str] = set()
        for loop_id in list(getattr(effort, "loops", None) or []):
            out |= {
                c.id
                for c in register.capabilities
                if c.id in scope and c.id in left_out and any(lp.id == loop_id for lp in c.sustain)
            }
        return out

    kept = []
    effort_carried: dict[
        str, str
    ] = {}  # a kept initiative whose added effort rests on a carried capability
    for d in register.initiatives:
        touches = ids(d.establishes) | ids(d.improves)
        through = owned_by(d.cost_of_delay_through) if d.cost_of_delay_through else None
        if not plan_approved(d.id) or touches & gone or (through in gone):
            continue
        holders = effort_holders(d)
        if holders & gone:
            continue
        if holders:
            effort_carried[d.id] = sorted(holders)[0]
        kept.append(d.id)

    # the register, projected
    reg = register.model_dump(mode="json", by_alias=True)
    reg["capabilities"] = [c for c in reg["capabilities"] if c["id"] in published]
    reg["planned_capabilities"] += [
        x for x in sorted(left_out) if x not in reg["planned_capabilities"]
    ]
    reg["initiatives"] = [d for d in reg["initiatives"] if d["id"] in kept]
    for drv in reg["drivers"]:
        drv["stresses"] = [s for s in drv["stresses"] if s["capability"] not in left_out]

    # the portfolio, projected: what leaves with a left-out capability or initiative
    pf = dumped(portfolio)
    pf["capabilities"] = [c for c in pf["capabilities"] if c["id"] in published]
    pf["conversion_rates"] = [
        r for r in pf["conversion_rates"] if owned_by(r["measure"]) not in left_out
    ]
    pf["unconverted"] = [
        x
        for x in pf["unconverted"]
        if owned_by(x if isinstance(x, str) else x["measure"]) not in left_out
    ]
    pf["initiatives"] = [p for p in pf["initiatives"] if p["id"] in kept]
    for plan in pf["initiatives"]:
        if (
            plan["id"] in effort_carried
        ):  # its loops live on a carried capability: no loop to sum; off the board, below
            plan["added_effort"] = {**plan["added_effort"], "loops": []}
    pf["decision_log"] = [e for e in pf["decision_log"] if e.get("initiative") in (None, *kept)]
    pf["approvals"] = []  # a served view reads no approval; the projection has applied them

    withheld: dict[Address, dict] = {}
    approved_form: set[Address] = set()
    off_board: dict[str, dict] = {}
    # deepest first, so a child is settled before its parent is written over
    for address in sorted(state, key=len, reverse=True):
        parent, slot, node = _get(pf, address)
        if parent is None:
            continue  # left with its capability or initiative
        if state[address] == "approved":
            continue
        if state[address] == "approved_form":
            recorded = in_force[address]
            if isinstance(node, dict) and isinstance(recorded, dict):
                kids = {k: v for k, v in node.items() if isinstance(v, dict) and "kind" in v}
                rewritten = {
                    **recorded,
                    **kids,
                    **({"note": node["note"]} if "note" in node else {}),
                }
                if (
                    address[-1] == "status" and address[0] == "initiatives"
                ):  # commitment and rank live on the initiative
                    _p, _s, plan = _get(pf, address[:-1])
                    plan["commitment"], plan["rank"] = (
                        rewritten.pop("commitment"),
                        rewritten.pop("rank"),
                    )
                parent[slot] = rewritten
            else:
                parent[slot] = recorded
            approved_form.add(address)
            continue
        how, stub = WITHHOLD[shape_of(address)]
        if how == "refuse":
            raise ValueError(
                f"the node {'/'.join(address)} is required on the served views and no approval covers it (GATE-7, 7.6)"
            )
        if how == "leave":
            continue  # its initiative already left the projection (plan_approved)
        withheld[address] = {
            "value": node.get("value")
            if isinstance(node, dict) and address[2:3] == ("readings",)
            else None,
            "part": address[-1],
        }
        if how == "remove":
            if isinstance(parent, list):
                parent.pop(slot)
            else:
                parent.pop(slot)
        elif how == "stub":
            parent[slot] = dict(stub)
        elif how == "none":
            parent[slot] = None
        elif how == "placeholder":
            parent[slot] = {
                "value": 1.0,
                "unit": node.get("unit", "slice"),
                "kind": "measured",
                "source": None,
            }
            off_board[address[1]] = {"why": "duration", "capability": None}

    # a kept initiative whose score core cannot compute from what is served, because of what the projection held back,
    # goes off the board, never refused; a cost of delay simply missing is core's to refuse, as it always was
    for d in register.initiatives:
        if d.id not in kept or not d.cost_of_delay_through:
            continue
        through = resolve_value(register, d.cost_of_delay_through).id
        if owner.get(through) in carried:
            off_board[d.id] = {"why": "cost_through", "capability": owner[through]}
        elif ("initiatives", d.id, "cost_of_delay") in withheld:
            off_board[d.id] = {"why": "cost_of_delay", "capability": None}
        elif ("conversion_rates", through) in withheld:
            off_board[d.id] = {"why": "rate", "capability": None}
    for (
        iid,
        cap,
    ) in (
        effort_carried.items()
    ):  # the cost reasons above come first; the added effort's names its holder
        off_board.setdefault(iid, {"why": "added_effort", "capability": cap})

    # the left-out capabilities the projection still names
    named: set[str] = set()
    for d in register.initiatives:
        if d.id in kept:
            named |= (ids(d.requires) | ids(d.establishes) | ids(d.improves)) & left_out
            if d.cost_of_delay_through and owned_by(d.cost_of_delay_through) in carried:
                named.add(owned_by(d.cost_of_delay_through))
    for c in register.capabilities:
        if c.id in published:
            for s in c.establish:
                named |= {
                    x.split(":", 1)[1] for x in s.requires if x.startswith("capability:")
                } & left_out

    projected = Portfolio.model_validate(pf)
    # a state's establishment follows its projected steps, a kindless field derived where the code derives it: every
    # establish step the register lists done there (core.establishment's rule), set on the typed state
    for c in projected.capabilities:
        cap = next(x for x in register.capabilities if x.id == c.id)
        for st in c.state:
            st.established = all(
                st.steps.get(s.id) is not None and st.steps[s.id].done for s in cap.establish
            )
    return Projection(
        register=Register.model_validate(reg),
        portfolio=projected,
        published=published,
        carried=carried,
        not_yet_published=frozenset(named),
        withheld=withheld,
        approved_form=frozenset(approved_form),
        off_board=off_board,
    )


# ── S1: the slice each served page is rendered from ─────────────────────────────────────────────────────────────────
# A served page has one input, its slice: the parts of the projection it reads, every other required field filled with
# a constant placeholder, so its bytes and its digest move only when something it shows moves. The placeholders never
# vary, so they never move a digest, and the test that renders a page from its slice and from the whole projection holds
# the slice whole (40-BREADTH.md step 2, S1).
PLACEHOLDER_DAY = "1970-01-01"
PLACEHOLDER_TEXT = "slice"


@dataclass(frozen=True)
class Slice:
    view: str  # capability:<id>, costs, board, role:<id>, index, agents, drivers
    register: Register
    portfolio: Portfolio
    site: (
        dict  # the site's vocabulary the page reads: page titles, competencies, the foundation job
    )
    records: dict  # the pinned drift lines and the measure output the page reads
    withheld: dict
    not_yet_published: frozenset[str]
    off_board: dict


def _empty_register(reg: dict) -> dict:
    return dict(
        reg,
        fixed=PLACEHOLDER_DAY,
        roles=[],
        planned_capabilities=[],
        capabilities=[],
        initiatives=[],
        drivers=[],
        watch_list=[],
        signals=[],
        scans=[],
        trigger_events=[],
    )


def _empty_portfolio(pf: dict) -> dict:
    return dict(
        pf,
        approval={"kind": "measured", "status": PLACEHOLDER_TEXT, "source": None},
        approvals=[],
        departments=[],
        assignments=[],
        role_history=[],
        ownership={},
        capacity=[],
        capabilities=[],
        conversion_rates=[],
        unconverted=[],
        estimate_adjustment={
            "factor": 1.0,
            "applies_to": [],
            "method": PLACEHOLDER_TEXT,
            "kind": "measured",
            "source": None,
            "note": None,
        },
        initiatives=[],
        local_capabilities=[],
        local_initiatives=[],
        drivers=[],
        trigger_events=[],
        scans=[],
        decision_log=[],
    )


def _serving(reg: dict, cap_id: str) -> set[str]:
    """The initiatives that establish or improve a capability, as its page names them."""
    return {
        d["id"]
        for d in reg["initiatives"]
        if f"capability:{cap_id}" in [*d["establishes"], *d["improves"]]
    }


def _initiative_as_named(d: dict) -> dict:
    """An initiative as a page that only names it reads it: its id, its name and what it is costed through or who
    sponsors it; every other field a constant placeholder."""
    return {
        "id": d["id"],
        "name": d.get("name"),
        "summary": PLACEHOLDER_TEXT,
        "establishes": [],
        "improves": [],
        "requires": [],
        "sponsor": d["sponsor"],
        "from": "plan",
        "from_event": None,
        "from_scan": None,
        "cost_of_delay_through": d["cost_of_delay_through"],
        "guidance": [],
    }


def _roles_named(reg: dict, caps: list[dict], inits: list[dict]) -> list[dict]:
    named = set()
    for c in caps:
        named |= {c["accountable"]}
        named |= {d["writer"] for d in c["declarations"]}
        named |= {lp["runner"] for lp in c["sustain"]}
        named |= {v["target_owner"] for v in c["value"]}
    named |= {d["sponsor"] for d in inits}
    return [r for r in reg["roles"] if r["id"] in named]


def slice_of(view: str, p: Projection, site: dict, records: dict) -> Slice:
    """The slice of the projection one served view reads (40-BREADTH.md step 2, S1)."""
    reg = p.register.model_dump(mode="json", by_alias=True)
    pf = p.portfolio.model_dump(mode="json", by_alias=True)
    r, f = _empty_register(reg), _empty_portfolio(pf)
    f["policy"] = pf["policy"]  # the overrides every page made from the portfolio names
    kind, _, ident = view.partition(":")
    if kind == "capability":
        cap = next(c for c in reg["capabilities"] if c["id"] == ident)
        r["capabilities"] = [cap]
        r["roles"] = _roles_named(reg, [cap], [])
        # the initiatives that serve the capability, named with what they establish or improve, their plans' status
        # and commitment: the page's standing line reads them (step 10)
        serving = _serving(reg, ident)
        r["initiatives"] = [
            dict(_initiative_as_named(d), establishes=d["establishes"], improves=d["improves"])
            for d in reg["initiatives"]
            if d["id"] in serving
        ]
        node = next(c for c in pf["capabilities"] if c["id"] == ident)
        f["capabilities"] = [node]
        f["initiatives"] = [
            dict(_plan_placeholder(i), id=i["id"], status=i["status"], commitment=i["commitment"])
            for i in pf["initiatives"]
            if i["id"] in serving
        ]
        scopes = {st["scope"] for st in node["state"]}
        f["assignments"] = [
            a for a in pf["assignments"] if a["role"] == cap["accountable"] and a["scope"] in scopes
        ]
    elif kind == "costs":
        values = {v["id"] for c in reg["capabilities"] for v in c["value"]}
        costed = [d for d in reg["initiatives"] if d["cost_of_delay_through"] in values]
        r["capabilities"] = reg["capabilities"]
        r["initiatives"] = [_initiative_as_named(d) for d in costed]
        r["roles"] = _roles_named(reg, reg["capabilities"], [])
        f["capabilities"] = pf["capabilities"]
        f["estimate_adjustment"] = pf["estimate_adjustment"]
        f["initiatives"] = [
            dict(_plan_placeholder(i), id=i["id"], cost_of_delay=i["cost_of_delay"])
            for i in pf["initiatives"]
            if i["id"] in {d["id"] for d in costed}
        ]
    elif kind == "board":
        r = dict(
            reg,
            watch_list=[],
            signals=[],
            scans=[],
            trigger_events=[],
            drivers=[],
            fixed=PLACEHOLDER_DAY,
        )
        f = dict(pf, approvals=[], decision_log=[], role_history=[], departments=[], ownership={})
        f["approval"] = {"kind": "measured", "status": PLACEHOLDER_TEXT, "source": None}
    elif kind in ("role", "index"):
        r["capabilities"] = reg["capabilities"]
        r["initiatives"] = [_initiative_as_named(d) for d in reg["initiatives"]]
        r["roles"] = reg["roles"]
        r["watch_list"] = [
            {
                "id": w["id"],
                "name": w.get("name"),
                "source": None,
                "kind": PLACEHOLDER_TEXT,
                "reader": w["reader"],
                "every": w[
                    "every"
                ],  # a role brief prints each watch's interval and reader (step 10)
                "machine_readable": False,
                "last_read": None,
                "decided_by": [],
                "since": PLACEHOLDER_DAY,
            }
            for w in reg["watch_list"]
        ]
    elif kind == "agents":
        # the register's agent entries alone (40-BREADTH.md step 6): every served capability, since the page counts
        # them and links each by name; no initiative, driver or watch entry reaches it
        r["capabilities"] = reg["capabilities"]
    elif kind == "drivers":
        # the register's drivers as the projection holds them (step 6): each stress on a served capability, the
        # initiatives that serve it with their guidance assessments, and the planned ids a planned stress names
        r["capabilities"] = reg["capabilities"]
        r["initiatives"] = reg["initiatives"]
        r["drivers"] = reg["drivers"]
        r["planned_capabilities"] = reg["planned_capabilities"]
    else:
        raise ValueError(f"no slice is defined for the view {view!r}")
    return Slice(
        view=view,
        register=Register.model_validate(r),
        portfolio=Portfolio.model_validate(f),
        site=site,
        records=records,
        withheld={a: w for a, w in p.withheld.items() if _in_slice(kind, ident, a, p)},
        not_yet_published=_named_by(kind, ident, p),
        off_board=dict(p.off_board) if kind == "board" else {},
    )


def _named_by(kind: str, ident: str, p: Projection) -> frozenset[str]:
    """The capabilities not yet published that a view names, and so the share of the set its slice and digest hold:
    the board names each one an initiative requires or establishes; a capability's page, each its establish steps
    require; no other view names one."""
    if kind == "board":
        return p.not_yet_published
    if kind == "capability":
        cap = next(c for c in p.register.capabilities if c.id == ident)
        required = {
            x.split(":", 1)[1]
            for s in cap.establish
            for x in s.requires
            if x.startswith("capability:")
        }
        return frozenset(p.not_yet_published & required)
    return frozenset()


def _in_slice(kind: str, ident: str, address: Address, p: Projection) -> bool:
    """Whether a withheld node changes what a view shows, so it belongs in the view's slice and digest: a cell the view
    prints "not yet published" in, or a total it labels partial. A withheld reading shows only when no reading of its
    value is left to show; a withheld node a view never prints moves none of its bytes."""
    if kind == "capability":
        if address[:2] != ("capabilities", ident):
            if (
                address[0] == "initiatives"
            ):  # a serving initiative's status, which the standing line prints
                return address[1] in _serving(
                    p.register.model_dump(mode="json", by_alias=True), ident
                ) and (address[2:3] == ("status",))
            return address[0] == "assignments"
        if address[2] == "readings":
            value = p.withheld.get(address, {}).get("value")
            node = next(c for c in p.portfolio.capabilities if c.id == ident)
            return not any(r.value == value for r in node.readings)
        return address[2] in ("investment", "effort", "targets", "state")
    if kind == "costs":
        return (
            address[0] == "capabilities" and address[2] in ("investment", "effort", "targets")
        ) or (address[0] == "initiatives" and address[2:3] == ("cost_of_delay",))
    if kind == "board":
        return address[0] in ("initiatives", "conversion_rates", "unconverted") or (
            address[0] == "capabilities" and address[2] in ("effort", "state")
        )
    return False


def _plan_placeholder(plan: dict) -> dict:
    """A plan as a page that reads only its cost of delay reads it: every other required field a constant placeholder."""
    return {
        "id": plan["id"],
        "status": {"value": PLACEHOLDER_TEXT, "kind": "measured", "source": None, "note": None},
        "commitment": None,
        "rank": "derived",
        "applicability": None,
        "cost_of_delay": None,
        "duration": {
            "value": 1.0,
            "unit": PLACEHOLDER_TEXT,
            "kind": "measured",
            "source": None,
            "note": None,
        },
        "added_effort": {
            "loops": [],
            "change": None,
            "kind": "not_recorded",
            "source": None,
            "note": None,
        },
        "planning": [],
    }


def slice_digest(s: Slice, pol: Any, render_format: int) -> str:
    """A served page's inputs' digest: over its slice (its read parts and the constant placeholders), the slice's share
    of the projection's sets, the policy as the estate runs it, and the renderer's format version."""
    payload = {
        "view": s.view,
        "register": s.register.model_dump(mode="json", by_alias=True),
        "portfolio": s.portfolio.model_dump(mode="json", by_alias=True),
        "site": s.site,
        "records": s.records,
        "withheld": {"/".join(a): w for a, w in sorted(s.withheld.items())},
        "not_yet_published": sorted(s.not_yet_published),
        "off_board": dict(sorted(s.off_board.items())),
        "policy": pol.for_estate(s.portfolio.policy.overrides).model.model_dump(
            mode="json", by_alias=True
        ),
        "overrides": [
            o.model_dump(mode="json", by_alias=True) for o in s.portfolio.policy.overrides
        ],
        "format": render_format,
    }
    return digest(payload)


def whole(view: str, p: Projection, site: dict, records: dict) -> Slice:
    """A view's input as the whole projection, beside its slice: the test that renders a page from each holds the slice
    whole (a read the slice misses shows as a difference)."""
    kind = view.partition(":")[0]
    return Slice(
        view=view,
        register=p.register,
        portfolio=p.portfolio,
        site=site,
        records=records,
        withheld=dict(p.withheld),
        not_yet_published=p.not_yet_published,
        off_board=dict(p.off_board) if kind == "board" else {},
    )


def awaiting(portfolio: Portfolio) -> frozenset[Address]:
    """The approvable nodes of a portfolio no approval covers as they stand: never approved, or changed since. A review
    view marks each "awaiting approval"; a served one shows the approved form, or withholds the node."""
    in_force = approvals_in_force(portfolio)
    return frozenset(
        a
        for a, f in approvable(portfolio)
        if a not in in_force or _restricted(f, in_force[a]) != in_force[a]
    )


AWAITING_MARK = "<small>(awaiting approval)</small> "


def mark_awaiting(content: str, nodes: frozenset[Address]) -> str:
    """A review view with each figure whose node awaits approval marked, inside the figure's wrapper."""
    import html as _html
    import re as _re

    def mark(m: _re.Match) -> str:
        address = tuple(_html.unescape(m.group(1)).split("/"))
        return m.group(0) + (AWAITING_MARK if address in nodes else "")

    return _re.sub(r'<span data-node="([^"]*)" data-kind="[^"]*">', mark, content)


# ── the renderer's format, held (40-BREADTH.md step 2, S1) ──────────────────────────────────────────────────────────
FROZEN_VIEWS = (
    "capability:fleet-patch-window",
    "costs",
    "board",
    "role:platform-team",
    "index",
    "agents",
    "drivers",
)


def freeze(s: Slice, policy: dict) -> dict:
    """A slice and the policy it was rendered under, as plain data, so the served pages rendered from it can be held
    to the renderer's format version while the reference files move on."""
    return {
        "view": s.view,
        "register": s.register.model_dump(mode="json", by_alias=True),
        "portfolio": s.portfolio.model_dump(mode="json", by_alias=True),
        "site": s.site,
        "records": s.records,
        "withheld": [[list(a), w] for a, w in sorted(s.withheld.items())],
        "not_yet_published": sorted(s.not_yet_published),
        "off_board": s.off_board,
        "policy": policy,
    }


def thaw(data: dict) -> tuple[Slice, Any]:
    """A frozen slice and its policy, loaded back through the models; a slice frozen at an earlier schema is migrated
    first, as any file is, so the format lock outlives a schema change (charter section 5.12)."""
    from .migrate import upgrade
    from .models import Policy
    from .policy import Loaded

    register, _ = upgrade("register", data["register"])
    portfolio, _ = upgrade("portfolio", data["portfolio"])
    s = Slice(
        view=data["view"],
        register=Register.model_validate(register),
        portfolio=Portfolio.model_validate(portfolio),
        site=data["site"],
        records=data["records"],
        withheld={tuple(a): w for a, w in data["withheld"]},
        not_yet_published=frozenset(data["not_yet_published"]),
        off_board=data["off_board"],
    )
    return s, Loaded(Policy.model_validate(data["policy"]))


# ── the ask: what an approval is recorded from (40-BREADTH.md step 2) ───────────────────────────────────────────────
ASKS = "docs/design/enterprise-strategy-layer/records/asks"


def ask(portfolio: Portfolio, addresses: list[Address], decision: str, day: str) -> dict:
    """The nodes an ask puts to the operator, each with its form and digest as the ask shows them; an approval is
    recorded by copying these after the ruling, never by computing digests then."""
    have = dict(approvable(portfolio))
    missing = [a for a in addresses if a not in have]
    if missing:
        raise ValueError(f"no approvable node at {', '.join('/'.join(a) for a in missing)}")
    return {
        "date": day,
        "decision": decision,
        "nodes": [{"path": list(a), "node": have[a], "digest": digest(have[a])} for a in addresses],
    }


def main(argv: list[str]) -> int:
    """`python -m generator.served ask --decision <id> --day <YYYY-MM-DD> --node <a/b/c> [--node ...] [--write]`, with
    the layer's folder on the path: print the ask's nodes, forms and digests; with --write, also write it under
    records/asks/ as <day>-<decision>.json, the file an approval is recorded from."""
    import argparse
    import sys
    from pathlib import Path

    from .policy import load_portfolio

    parser = argparse.ArgumentParser(prog="served.py")
    sub = parser.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("ask")
    a.add_argument("--decision", required=True)
    a.add_argument(
        "--node", action="append", required=True, help="an address, its segments joined by /"
    )
    a.add_argument(
        "--day", required=True, help="the day the ask is put, YYYY-MM-DD (no page reads the clock)"
    )
    a.add_argument("--write", action="store_true")
    a.add_argument(
        "--label",
        default=None,
        help="a short suffix for the file's name, so two asks under one decision on one day keep both files "
        "(40-BREADTH.md step 4: a batch's figure set)",
    )
    args = parser.parse_args(argv)
    from .models import a_day

    a_day(args.day, "the ask's day")
    day = args.day
    record = ask(load_portfolio(), [tuple(n.split("/")) for n in args.node], args.decision, day)
    if args.label:
        if not re.fullmatch(r"[a-z0-9-]{1,40}", args.label):
            raise SystemExit("--label is lower-case letters, digits and hyphens, at most 40")
        record["label"] = args.label
    text = json.dumps(record, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    sys.stdout.write(text)
    if args.write:
        root = Path(__file__).resolve().parents[4]
        name = f"{day}-{args.decision}" + (f"-{args.label}" if args.label else "")
        out = root / ASKS / f"{name}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"wrote {out.relative_to(root)}", file=sys.stderr)
    return 0


if (
    __name__ == "__main__"
):  # run as a module: PYTHONPATH=docs/design/enterprise-strategy-layer python -m generator.served
    import sys

    sys.exit(main(sys.argv[1:]))
