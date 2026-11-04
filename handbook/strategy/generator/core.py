"""The generator's core (20-PILOT.md step 5): the register, a portfolio and the policy in, a typed board out.

Three methods, each the implementation of one version `policy.yaml` registers, each reading every parameter through
the policy loader and holding none (charter section 5.12, GATE-14):

  cd3-chain 1         the prioritization rule, the chain rule, capacity and total cost (charter section 5.9)
  adoption-levels 1   the adoption bar, graded on evidence (charter section 5.9)
  planning-horizon 1  each planning assessment's tier and review-by date, derived (charter section 5.7)

Every output carries its provenance: each method with its version and status, the policy version, the schema version
of each file, a digest of the portfolio's overrides and of the inputs, and when it was generated.
"""

from __future__ import annotations

import functools
import hashlib
import itertools
import json
from collections.abc import Callable
from datetime import UTC, datetime

from .models import SCHEMA_VERSIONS, Portfolio, Register, parse_day
from .policy import Loaded, PolicyError, add, months

# ── method versions: one implementation per version, selected by the policy (charter section 5.12) ──────────────────
METHODS: dict[tuple[str, int], Callable] = {}


def implements(method_id: str, version: int):
    """Register a function as the implementation of one method version. A version is never edited once ratified; a new
    one registers beside it, runs in shadow (generator/shadow.py), and is selected only by a ruling."""

    def register(fn: Callable) -> Callable:
        if (method_id, version) in METHODS:
            raise PolicyError(f"two implementations of {method_id} version {version}")

        @functools.wraps(fn)
        def as_the_estate_runs_it(register_, portfolio, pol, *args):
            # every caller, run_method, the shadow run or a direct call, reads the estate's view (Loaded.for_estate)
            return fn(register_, portfolio, pol.for_estate(portfolio.policy.overrides), *args)

        METHODS[(method_id, version)] = as_the_estate_runs_it
        return as_the_estate_runs_it

    return register


def run_method(entry_id: str, register: Register, portfolio: Portfolio, pol: Loaded, *args):
    """The output of the method version an entry selects, as the estate runs the policy (its overrides applied)."""
    pol = pol.for_estate(portfolio.policy.overrides)
    m = pol.selected(entry_id)
    try:
        fn = METHODS[(m.id, m.version)]
    except KeyError:
        raise PolicyError(
            f"{entry_id} selects {m.id} version {m.version}, which no code implements"
        ) from None
    return fn(register, portfolio, pol, *args)


def adjusts(pol: Loaded, portfolio: Portfolio, what: str) -> bool:
    """Whether the estimate adjustment applies to a kind of estimate (`duration`, `investment`): the policy's rule, or
    the estate's override of it. The factor is the portfolio's own."""
    return (
        what in pol.for_estate(portfolio.policy.overrides).get("estimate-adjustment")["applies_to"]
    )


# ── shared ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def _digest(*objs) -> str:
    return hashlib.sha256(
        json.dumps(
            [o.model_dump(by_alias=True) if hasattr(o, "model_dump") else o for o in objs],
            sort_keys=True,
            default=str,
        ).encode()
    ).hexdigest()[:16]


def provenance(
    pol: Loaded,
    used: list[tuple[str, int]],
    register: Register,
    portfolio: Portfolio,
    lines: list[dict] | None = None,
) -> dict:
    return {
        "methods": {m: {"version": v, "status": pol.method(m, v).status} for m, v in used},
        "policy_version": pol.model.policy_version,
        "schemas": {k: SCHEMA_VERSIONS[k] for k in ("register", "portfolio", "policy")},
        "contracts": sorted({line["contract_version"] for line in lines or []}),
        "overrides_digest": _digest(portfolio.policy.overrides),
        "input_digest": _digest(register, portfolio, pol.model),
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def established(register: Register, portfolio: Portfolio) -> set[str]:
    """The capabilities a portfolio records as established in some scope. A state is recorded only for a capability the
    register defines, the set every reader of establishment walks (its steps, its kind, the board's illustrative
    inputs), so no establishment decides a rank unnamed; a state for any other id is refused."""
    defined = {c.id for c in register.capabilities}
    unknown = sorted(c.id for c in portfolio.capabilities if c.id not in defined)
    if unknown:
        raise ValueError(
            f"the portfolio records a state for {', '.join(unknown)}, which the register does not define as a "
            "capability; record a state only for a capability the register defines, with the steps it lists"
        )
    return {c.id for c in portfolio.capabilities if any(s.established for s in c.state)}


_established = established  # the name the board's locals shadow


def establishment(register: Register, portfolio: Portfolio) -> dict[str, dict]:
    """Each capability's establishment as the portfolio records it, held to its steps and said with their kind: a
    state's `established` must be what its steps bear out (every establish step the register lists done there), or the
    board refuses to rank on it; its kind is combine over the recorded steps of its states; a capability with no state
    is not established, and not recorded (DEC-14, GATE-7)."""
    for cap in register.capabilities:
        pc = next((c for c in portfolio.capabilities if c.id == cap.id), None)
        for st in pc.state if pc else []:
            done = all(
                st.steps.get(s.id) is not None and st.steps[s.id].done for s in cap.establish
            )
            if st.established != done:
                raise ValueError(
                    f"{cap.id} ({st.scope}) records established: {st.established}, but its establish steps "
                    f"{'are' if done else 'are not'} all done; record what the steps bear out"
                )
    return establishment_kinds(register, portfolio)


def establishment_kinds(register: Register, portfolio: Portfolio) -> dict[str, dict]:
    """Each capability's establishment's kind: combine over the recorded steps of its states (DEC-14)."""
    out = {}
    for cap in register.capabilities:
        pc = next((c for c in portfolio.capabilities if c.id == cap.id), None)
        recorded = [
            (s.kind, s.source)
            for st in (pc.state if pc else [])
            for s in st.steps.values()
            if s.kind != "not_recorded"
        ]
        out[cap.id] = dict(zip(("kind", "source"), combine(*recorded), strict=True))
    return out


def _ref(x: str) -> str:
    return x.split(":", 1)[1] if ":" in x else x


# ── cd3-chain ───────────────────────────────────────────────────────────────────────────────────────────────────────
def _items(
    register: Register, portfolio: Portfolio, rates: dict[str, float], factor: float
) -> dict[str, dict]:
    plans = {i.id: i for i in portfolio.initiatives}
    out = {}
    for d in register.initiatives:
        if d.id not in plans:  # an initiative this estate has not planned is not on its board
            continue
        p = plans[d.id]
        through = d.cost_of_delay_through
        if through is not None and (p.cost_of_delay is None or p.cost_of_delay.delta is None):
            raise ValueError(
                f"{d.id}'s cost of delay is converted through {through}, and the portfolio records none; record "
                "it, so the board never ranks it as zero"
            )
        if through is not None and through not in rates:
            raise ValueError(
                f"{d.id}'s cost of delay is converted through {through}, and the portfolio states no conversion rate "
                "for it; add one, with its method and range"
            )
        cod = (
            0.0
            if through is None or p.cost_of_delay is None
            else p.cost_of_delay.delta * rates[through]
        )
        out[d.id] = {
            "id": d.id,
            "cod": cod,
            "duration": p.duration.value * factor,
            "establishes": {_ref(x) for x in d.establishes},
            "requires": {_ref(x) for x in d.requires},
        }
    return out


def _structure(items: dict[str, dict], established: set[str]) -> dict[str, list[str]]:
    """The part of the chain rule that no rate moves: which initiatives are rankable (no unestablished prerequisite
    they do not establish), and, for each, the dependents it alone unblocks, in the items' order. Computed once per
    board and reused across the sensitivity's sweep, where only the costs of delay change (step 4, batch 2: the
    ceiling test at 47 capabilities spent its time rebuilding this per step)."""
    missing = {k: {c for c in i["requires"] if c not in established} for k, i in items.items()}
    return {
        k: [kj for kj, jm in missing.items() if kj != k and jm and jm <= i["establishes"]]
        for k, i in items.items()
        if not missing[k]
    }


def _rank(
    items: dict[str, dict], established: set[str], structure: dict[str, list[str]] | None = None
) -> list[dict]:
    """The chain rule over the graph: an initiative blocked by a prerequisite it does not establish is not ranked
    alone; one that establishes a capability scores the higher of its own CD3 and its best chain with the dependents it
    alone unblocks, added in descending order of their own CD3, the best prefix taken."""
    structure = structure if structure is not None else _structure(items, established)
    ranked = [
        {
            "id": i["id"],
            "score": best,
            "own": own,
            "chain": chain,
            "considered": [i["id"], *(j["id"] for j in deps)],
        }
        for i, own, best, chain, deps in _scored(items, structure)
    ]
    ranked.sort(key=lambda r: (-r["score"], r["id"]))
    return ranked


def _scored(items: dict[str, dict], structure: dict[str, list[str]]):
    """Each rankable initiative scored by the chain rule (`_rank`): the item, its own CD3, its score, the chain that
    scores it and its dependents in descending order of their own CD3. One definition, read by the rank and by the
    sensitivity's sweep, which needs only the top."""
    for k, dep_ids in structure.items():
        i = items[k]
        own = i["cod"] / i["duration"]
        deps = sorted(
            (items[kj] for kj in dep_ids), key=lambda j: j["cod"] / j["duration"], reverse=True
        )
        best, chain = own, [i["id"]]
        cod, dur, ids = i["cod"], i["duration"], [i["id"]]
        for j in deps:
            cod, dur, ids = cod + j["cod"], dur + j["duration"], [*ids, j["id"]]
            if cod / dur > best:
                best, chain = cod / dur, list(ids)
        yield i, own, best, chain, deps


def _top_of(items: dict[str, dict], structure: dict[str, list[str]]) -> str:
    """The id on top of the rank: the highest score, ties to the first id, as `_rank` orders them, without building or
    sorting the rank (the sensitivity's sweep asks thousands of times per report)."""
    return min((-best, i["id"]) for i, _own, best, _chain, _deps in _scored(items, structure))[1]


def _rates(portfolio: Portfolio, pol: Loaded) -> dict[str, float]:
    method = pol.for_estate(portfolio.policy.overrides).selected("prioritization")
    need = method.parameters["rate_requires"]
    rates = {}
    for r in portfolio.conversion_rates:
        missing = [k for k in need if getattr(r, k, None) in (None, "")]
        if missing:
            raise ValueError(
                f"the conversion rate for {r.measure} lacks {missing} ({method.id} {method.version})"
            )
        rates[r.measure] = r.rate
    return rates


KINDS = {
    "illustrative",
    "input",
    "measured",
    "not_recorded",
}  # the kinds combine orders, by meaning


def combine(*figs: tuple[str | None, str | None]) -> tuple[str, str | None]:
    """The kind of a figure made from others, with its suppliers: illustrative if any part is; otherwise an input naming
    every input part's supplier, and saying so when a part is measured; measured if every part is; not recorded
    otherwise (DEC-14, GATE-7)."""
    kinds = [k for k, _s in figs if k]
    unknown = sorted(set(kinds) - KINDS)
    if unknown:
        raise ValueError(
            f"no order to combine the kind {unknown[0]!r} in; a new kind is a method change (DEC-14)"
        )
    if "illustrative" in kinds:
        return "illustrative", None
    if "input" in kinds:
        named = "; ".join(sorted({s for k, s in figs if k == "input" and s}))
        return "input", named + ("; part measured" if "measured" in kinds else "")
    if kinds and all(k == "measured" for k in kinds):
        return "measured", None
    return "not_recorded", None


def initiative_loops(register: Register, initiative_id: str, names: set[str]) -> dict[str, str]:
    """Each loop id an initiative's added effort names, resolved to the one capability that holds it among the
    capabilities the initiative establishes or improves (the loops it brings into being, charter section 5.9). A loop
    id is unique within a capability only (listed_once), and step 4's batches share ids across capabilities
    (drift-read, instrument-upkeep), so a bare id is read in the initiative's own scope: one the scope does not hold,
    or holds twice, is refused by name, never summed from another capability's loop."""
    d = next(i for i in register.initiatives if i.id == initiative_id)
    scope = {_ref(x) for x in [*d.establishes, *d.improves]}
    out: dict[str, str] = {}
    for loop_id in sorted(names):
        holders = [
            cap.id
            for cap in register.capabilities
            if cap.id in scope and any(lp.id == loop_id for lp in cap.sustain)
        ]
        if len(holders) != 1:
            raise ValueError(
                f"{initiative_id}'s added effort names the loop {loop_id!r}, which "
                + (
                    f"{len(holders)} of the capabilities it establishes or improves hold ({', '.join(holders)})"
                    if holders
                    else "none of the capabilities it establishes or improves holds"
                )
                + "; name a loop of one capability the initiative brings into being"
            )
        out[loop_id] = holders[0]
    return out


def _effort_names(plan) -> set[str]:
    return set(plan.added_effort.loops) | (
        {plan.added_effort.change.loop} if plan.added_effort.change else set()
    )


def _added_effort_kind(
    register: Register, portfolio: Portfolio, initiative_id: str
) -> tuple[str, str | None]:
    """The kind and supplier of an initiative's added effort: illustrative if its own figure, or the effort of any loop
    it adds, is (DEC-14)."""
    plan = next(i for i in portfolio.initiatives if i.id == initiative_id)
    owner = initiative_loops(register, initiative_id, set(plan.added_effort.loops))
    efforts = {c.id: c.effort for c in portfolio.capabilities}
    figs = [
        efforts[cap_id][loop_id]
        for loop_id, cap_id in owner.items()
        if loop_id in efforts.get(cap_id, {})
    ]
    return combine(
        (plan.added_effort.kind, plan.added_effort.source), *[(f.kind, f.source) for f in figs]
    )


def _added_effort_unit(register: Register, portfolio: Portfolio, initiative_id: str) -> str | None:
    """The unit added effort is reported in: its loops' effort unit, a quarter's taken per month as the sum does."""
    plan = next(i for i in portfolio.initiatives if i.id == initiative_id)
    owner = initiative_loops(register, initiative_id, _effort_names(plan))
    units = {
        (_months(loop.effort_unit) and loop.effort_unit.replace("per quarter", "per month"))
        for cap in register.capabilities
        for loop in cap.sustain
        if owner.get(loop.id) == cap.id
    }
    return units.pop() if len(units) == 1 else None


PERIODS = {"per month": 1, "per quarter": 3}  # the effort periods the core converts to a month


def _months(unit: str) -> int:
    """The months an effort unit's period spans; a period the core cannot convert is refused, never added as a month."""
    for period, span in PERIODS.items():
        if unit.endswith(period):
            return span
    raise ValueError(
        f"the effort unit {unit!r} has no period the core converts to a month ({', '.join(PERIODS)})"
    )


def _base_unit(unit: str) -> str:
    """An effort unit without its period: person-hours per month is person-hours."""
    for period in PERIODS:
        if unit.endswith(period):
            return unit[: -len(period)].strip()
    return unit


def _added_effort(register: Register, portfolio: Portfolio, initiative_id: str) -> float | None:
    plan = next(i for i in portfolio.initiatives if i.id == initiative_id)
    if plan.added_effort.kind == "not_recorded":
        return None
    names = _effort_names(plan)
    owner = initiative_loops(register, initiative_id, names)
    # every recorded effort converted to a month (a period the core cannot convert is refused wherever it is written),
    # and the sum taken over the initiative's own loops only, each read from the capability that holds it
    per_month: dict[tuple[str, str], float] = {}
    for c in portfolio.capabilities:
        units = {
            loop.id: loop.effort_unit
            for cap in register.capabilities
            if cap.id == c.id
            for loop in cap.sustain
        }
        for loop_id, fig in c.effort.items():
            if fig.value is not None:
                per_month[(c.id, loop_id)] = fig.value / _months(units.get(loop_id, ""))
    if any((owner[x], x) not in per_month for x in plan.added_effort.loops):
        return None  # a loop it adds has no recorded effort: the sum is not recorded, never short
    bases = {
        _base_unit(lp.effort_unit)
        for cap in register.capabilities
        for lp in cap.sustain
        if owner.get(lp.id) == cap.id
    }
    if len(bases) > 1:
        raise ValueError(
            f"{initiative_id}'s added effort sums loops in different units ({', '.join(sorted(bases))}); record "
            "them in one unit"
        )
    total = sum(per_month[(owner[x], x)] for x in plan.added_effort.loops)
    change = plan.added_effort.change
    if change is None:
        return total
    unit = next(
        (
            lp.effort_unit
            for cap in register.capabilities
            for lp in cap.sustain
            if lp.id == change.loop and owner.get(lp.id) == cap.id
        ),
        "",
    )
    return total + change.value / _months(
        unit
    )  # a change is in its loop's period, converted as its effort is


def _rank_parts(
    register: Register, portfolio: Portfolio, ids: set[str], applies: bool
) -> list[tuple[str, str | None]]:
    """The figures a score over these initiatives is computed from, each as (kind, source): each one's duration, its
    cost of delay and the conversion rate it is converted through, and the estimate adjustment where one applies. A
    planning assessment, an added effort and a capacity feed no score, so none is a part (DEC-14, GATE-7)."""
    plans = {p.id: p for p in portfolio.initiatives}
    rates = {r.measure: r for r in portfolio.conversion_rates}
    adj = portfolio.estimate_adjustment
    out = (
        [(adj.kind, adj.source)] if applies else []
    )  # where the rule applies it, whatever its factor
    for d in register.initiatives:
        if d.id not in ids or d.id not in plans:
            continue
        p = plans[d.id]
        out.append((p.duration.kind, p.duration.source))
        if d.cost_of_delay_through is not None and p.cost_of_delay is not None:
            r = rates[d.cost_of_delay_through]
            out += [(p.cost_of_delay.kind, p.cost_of_delay.source), (r.kind, r.source)]
    return out


@implements("cd3-chain", 1)
def board(register: Register, portfolio: Portfolio, pol: Loaded) -> dict:
    """The ranked board of the cd3-chain method the policy selects, with the capacity line, the total cost beside each
    rank, and the rank across each conversion rate's range."""
    pol = pol.for_estate(
        portfolio.policy.overrides
    )  # capacity and the method as the estate runs them
    method = pol.selected("prioritization")
    rates = _rates(portfolio, pol)
    applies = adjusts(
        pol, portfolio, "duration"
    )  # the policy's rule decides, never the factor's value
    factor = portfolio.estimate_adjustment.factor if applies else 1.0
    established = _established(register, portfolio)
    items = _items(register, portfolio, rates, factor)
    ranked = _rank(items, established)
    cap_entry = pol.get("capacity")
    capacity = {c.role: c.value for c in portfolio.capacity}
    role = next(iter(capacity))  # the constrained role this portfolio plans
    # every figure the board shows takes its kind from combine over the parts it is computed from (DEC-14, GATE-7)
    parts = {p.id: _rank_parts(register, portfolio, {p.id}, applies) for p in portfolio.initiatives}
    adj = portfolio.estimate_adjustment
    dur_parts = {  # a duration shown is the estimate times the adjustment where one applies
        p.id: [(p.duration.kind, p.duration.source)] + ([(adj.kind, adj.source)] if applies else [])
        for p in portfolio.initiatives
    }
    shown = {i: combine(*ps) for i, ps in dur_parts.items()}
    kind = {i: k for i, (k, _s) in shown.items()}
    supplied = {i: s for i, (_k, s) in shown.items()}
    scored = {r["id"]: combine(*[f for x in r["chain"] for f in parts.get(x, [])]) for r in ranked}
    unit = {p.id: p.duration.unit for p in portfolio.initiatives}
    cap_fig = next(c for c in portfolio.capacity if c.role == role)
    used, used_parts, funded = 0.0, [], []
    for r in ranked:
        for x in r["chain"]:
            d = items[x]["duration"]
            fits = used + d <= capacity[role]
            cum_kind, cum_source = combine(*used_parts, *dur_parts[x])
            fund_kind, fund_source = combine(
                *used_parts, *dur_parts[x], (cap_fig.kind, cap_fig.source)
            )
            funded.append(
                {
                    "id": x,
                    "duration": round(d, 2),
                    "duration_kind": kind[x],
                    "duration_source": supplied[x],
                    "duration_unit": unit[x],
                    "cumulative": round(used + d, 2),
                    "cumulative_kind": cum_kind,
                    "cumulative_source": cum_source,
                    "period": "this period" if fits else cap_entry["beyond_the_line"],
                    "period_kind": fund_kind,
                    "period_source": fund_source,
                }
            )
            if fits:
                used += d
                used_parts += dur_parts[x]
    blocked = sorted(i for i in items if i not in {x for r in ranked for x in r["chain"]})
    held = establishment(register, portfolio)
    not_held = {"kind": "not_recorded", "source": None}  # a planned capability no state records
    return {
        "method": {"id": method.id, "version": method.version},
        "ranked": [
            {
                "id": r["id"],
                "score": round(r["score"], 2),
                "score_kind": scored[r["id"]][0],
                "score_source": scored[r["id"]][1],
                "own_cd3": round(r["own"], 2),
                "chain": r["chain"],
                "duration": round(items[r["id"]]["duration"], 2),
                "duration_kind": kind[r["id"]],
                "duration_source": supplied[r["id"]],
                "duration_unit": unit[r["id"]],
                "added_effort_kind": _added_effort_kind(register, portfolio, r["id"])[0],
                "added_effort_source": _added_effort_kind(register, portfolio, r["id"])[1],
                "added_effort_unit": _added_effort_unit(register, portfolio, r["id"]),
                "added_effort_per_month": (lambda e: None if e is None else round(e, 2))(
                    _added_effort(register, portfolio, r["id"])
                ),
            }
            for r in ranked
        ],
        "unranked": [
            {
                "id": b,
                "blocked_by": [
                    {"capability": c} | held.get(c, not_held)
                    for c in sorted(c for c in items[b]["requires"] if c not in established)
                ],
            }
            for b in blocked
            if any(c not in established for c in items[b]["requires"])
        ],
        "capacity": {
            "role": role,
            "per_period": capacity[role],
            "unit": next(c.unit for c in portfolio.capacity if c.role == role),
            "kind": next(c.kind for c in portfolio.capacity if c.role == role),
            "source": next(c.source for c in portfolio.capacity if c.role == role),
            "period": cap_entry["period"],
            "funded": funded,
            "funded_total": round(used, 2),
        },
        "unconverted": [
            u.model_dump(mode="json") for u in portfolio.unconverted
        ],  # typed items (schema 4), as plain data so the report serializes
        "illustrative_inputs": illustrative_inputs(portfolio, register),
        "derived": rank_kind(
            register, portfolio, applies, {x for r in ranked for x in r["considered"]}
        ),
        "sensitivity": sensitivity(register, portfolio, pol),
        "provenance": provenance(pol, [(method.id, method.version)], register, portfolio),
    }


def _top(register, portfolio, rates, factor, established) -> tuple[str, float]:
    r = _rank(_items(register, portfolio, rates, factor), established)
    return r[0]["id"], r[0]["score"]


def illustrative_inputs(portfolio: Portfolio, register: Register) -> list[str]:
    """Every input of the board that is illustrative, named, so a view labels each one (DEC-14, GATE-7): each figure
    the rank computes with, and each establishment that decides which initiatives the rank considers."""
    out = [
        f"conversion rate: {r.measure}"
        for r in portfolio.conversion_rates
        if r.kind == "illustrative"
    ]
    for p in portfolio.initiatives:
        if p.duration.kind == "illustrative":
            out.append(f"duration: {p.id}")
        if (
            p.added_effort.kind != "not_recorded"
            and _added_effort_kind(register, portfolio, p.id)[0] == "illustrative"
        ):
            out.append(f"added effort: {p.id}")
        if any(a.kind == "illustrative" for a in p.planning):
            out.append(f"planning: {p.id}")
        if p.cost_of_delay is not None and p.cost_of_delay.kind == "illustrative":
            out.append(f"cost of delay: {p.id}")
    out += [f"capacity: {c.role}" for c in portfolio.capacity if c.kind == "illustrative"]
    if portfolio.estimate_adjustment.kind == "illustrative":
        out.append("estimate adjustment")
    planned = {p.id for p in portfolio.initiatives}
    required = sorted(
        {_ref(x) for d in register.initiatives if d.id in planned for x in d.requires}
    )
    held = establishment_kinds(register, portfolio)
    out += [
        f"establishment: {c}" for c in required if held.get(c, {}).get("kind") == "illustrative"
    ]
    # an override decides what the board computes (whether the adjustment applies, say): named when illustrative
    out += [f"override: {o.entry}" for o in portfolio.policy.overrides if o.kind == "illustrative"]
    return out


def rank_kind(register: Register, portfolio: Portfolio, applies: bool, ids: set[str]) -> dict:
    """The kind of a figure the board derives from the whole rank (a crossing, a joint extreme): combine over the score
    parts of every initiative the rank's arithmetic considers (each one ranked, and each dependent it could carry; a
    blocked one is never scored, and no rate moves which are blocked) and every conversion rate, each rate being moved
    (DEC-14, GATE-7)."""
    kind, source = combine(
        *_rank_parts(register, portfolio, ids, applies),
        *[(r.kind, r.source) for r in portfolio.conversion_rates],
    )
    return {"kind": kind, "source": source}


def sensitivity(register: Register, portfolio: Portfolio, pol: Loaded) -> dict:
    """Where the top of the rank changes: each rate moved alone from its value, down to zero and up to ten times its
    high, in steps of 0.01 (the first value at which another initiative is on top, or None); and every rate at its low
    or its high together (the joint extremes)."""
    base = _rates(portfolio, pol)
    factor = portfolio.estimate_adjustment.factor if adjusts(pol, portfolio, "duration") else 1.0
    established = _established(register, portfolio)
    # the items and the chain structure once; a step of the sweep moves one rate, so only the costs of delay converted
    # through that measure change, and the rank is recomputed over the same structure (the same answer as ranking the
    # items rebuilt at that rate, which is what the method defines)
    items0 = _items(register, portfolio, base, factor)
    structure = _structure(items0, established)
    plans = {i.id: i for i in portfolio.initiatives}
    deltas = {
        d.id: (d.cost_of_delay_through, plans[d.id].cost_of_delay.delta)
        for d in register.initiatives
        if d.id in items0 and d.cost_of_delay_through is not None
    }

    def top_at(measure: str, x: float) -> str:
        items = {
            **items0,
            **{k: dict(items0[k], cod=d * x) for k, (m, d) in deltas.items() if m == measure},
        }
        return _top_of(items, structure)

    top0 = _top(register, portfolio, base, factor, established)[0]

    def first_change(measure: str, start: float, stop: float, step: float) -> float | None:
        x = start
        while (x - stop) * (1 if step > 0 else -1) <= 0 and x > 0:
            if top_at(measure, x) != top0:
                return round(x, 2)
            x = round(x + step, 2)
        return None

    crossings = {
        r.measure: {
            "rate": r.rate,
            "kind": r.kind,
            "source": r.source,
            "low": r.low,
            "high": r.high,
            "top_changes_below": first_change(r.measure, r.rate, 0.01, -0.01),
            "top_changes_above": first_change(r.measure, r.rate, 10 * r.high, 0.01),
            "searched": {"down_to": 0.01, "up_to": round(10 * r.high, 2)},
        }
        for r in portfolio.conversion_rates
    }
    # the joint extremes over the rates that feed a ranked score: a rate converting only blocked initiatives' costs
    # moves no score, so enumerating it would print every outcome twice (step 5; the equivalence test holds the distinct
    # tops equal to the full enumeration's)
    considered = set(structure) | {kj for deps in structure.values() for kj in deps}
    feeding = {m for k, (m, _d) in deltas.items() if k in considered}
    scored = [r for r in portfolio.conversion_rates if r.measure in feeding]
    joints = []
    for combo in itertools.product(*[(r.low, r.high) for r in scored]):
        rates = dict(base, **{r.measure: v for r, v in zip(scored, combo, strict=True)})
        top, score = _top(register, portfolio, rates, factor, established)
        joints.append({"rates": rates, "top": top, "score": round(score, 2)})

    # the top initiative's duration crossing: the duration, in the plan's own unit, at which the top changes, swept
    # upward in steps of 0.01 (step 5: a tie within rounding is pinned with the input that decides it, 3c's judgment)
    def top_at_duration(x: float) -> str:
        items = {**items0, top0: dict(items0[top0], duration=x * factor)}
        return _top_of(items, structure)

    dur = plans[top0].duration
    x, stop, above = round(dur.value, 2), round(10 * dur.value, 2), None
    while x <= stop:
        if top_at_duration(x) != top0:
            above = round(x, 2)
            break
        x = round(x + 0.01, 2)
    duration_crossing = {
        "initiative": top0,
        "duration": dur.value,
        "unit": dur.unit,
        "kind": dur.kind,
        "source": dur.source,
        "top_changes_above": above,
        "searched": {"up_to": stop},
    }
    return {
        "top": top0,
        "crossings": crossings,
        "joint_extremes": joints,
        "duration_crossing": duration_crossing,
    }


# ── adoption-levels ─────────────────────────────────────────────────────────────────────────────────────────────────
@implements("adoption-levels", 1)
def grade(
    register: Register, portfolio: Portfolio, pol: Loaded, drift_lines: list[dict] | None = None
) -> list[dict]:
    """Each capability's level in each scope, the highest whose criteria all hold on recorded evidence, and whether a
    level rests on an illustrative figure (then shown as illustrative)."""
    method = pol.selected("adoption-method")
    levels = sorted(method.levels, key=lambda lv: lv.ordinal)
    bar = pol.get("world-class-bar")
    out = []
    for cap in register.capabilities:
        pc = next((c for c in portfolio.capabilities if c.id == cap.id), None)
        for st in pc.state if pc else []:
            steps = [st.steps.get(s.id) for s in cap.establish]
            established = all(s is not None and s.done for s in steps)
            # what the grade rests on: every recorded step, done or not, its kind through combine (DEC-14); the
            # steps no record holds are counted beside it, never graded on
            recorded = [s for s in steps if s is not None and s.kind != "not_recorded"]
            basis, basis_source = combine(*[(s.kind, s.source) for s in recorded])
            assigned = [
                a
                for a in portfolio.assignments
                if a.role == cap.accountable and a.scope == st.scope
            ]
            # a read in place is one that judged (in sync or drifted); a failed or uncovered check is never a pass
            drift_in_place = any(
                line.get("capability") == cap.id and line.get("result") in ("in_sync", "drifted")
                for line in drift_lines or []
            )
            reached = levels[0]
            if established:
                reached = levels[1]
                if (
                    len(assigned) == 1
                    and all(d.writer for d in cap.declarations)
                    and drift_in_place
                ):
                    reached = levels[
                        2
                    ]  # levels 3 and 4 need a full cycle's evidence, which PH2 does not hold
                    # level two rests on the assignment and the drift read as well as the steps (DEC-14)
                    basis, basis_source = combine(
                        *[(s.kind, s.source) for s in recorded],
                        *[(a.kind, a.source) for a in assigned],
                        ("measured", None),
                    )
            out.append(
                {
                    "capability": cap.id,
                    "scope": st.scope,
                    "level": reached.id,
                    "ordinal": reached.ordinal,
                    "basis": basis,
                    "basis_source": basis_source,
                    "steps_done": sum(1 for s in steps if s is not None and s.done),
                    "steps_recorded": len(recorded),
                    "steps": len(steps),
                    "world_class": bar["world_class_level"],
                    # the bar's place among the method's levels, so a page can speak of levels by their order
                    "world_class_ordinal": next(
                        lv.ordinal for lv in levels if lv.id == bar["world_class_level"]
                    ),
                    "levels": len(levels),
                    "ladder": [
                        lv.id for lv in levels
                    ],  # the method's levels in order, for a page to name them
                    "target": pc.target_grade.level if pc else None,
                }
            )
    return out


# ── planning-horizon ────────────────────────────────────────────────────────────────────────────────────────────────


def tier_of(horizon: str, pol: Loaded) -> str:
    h = months(horizon)
    for t in pol.get("planning-tiers"):
        lo, hi = months(t["from"]), (months(t["to"]) if t["to"] else None)
        if h >= lo and (hi is None or h < hi):
            return t["id"]
    raise ValueError(f"no planning tier covers {horizon}")


@implements("planning-horizon", 1)
def planning(register: Register, portfolio: Portfolio, pol: Loaded) -> list[dict]:
    """Each planning assessment's tiers and review-by date, derived: the tier from the recorded horizon and the policy's
    bounds; the review-by date from the assessment date and the interval of the initiative's latest guidance tier."""
    method = pol.selected("planning-horizon")
    intervals = pol.get("review-intervals")
    planned = {p.id for p in portfolio.initiatives}
    guidance = {}
    for i in register.initiatives:
        if (
            i.id not in planned
        ):  # an initiative the estate has not planned is never a reason for the board to fail
            continue
        if not i.guidance:
            raise ValueError(
                f"{i.id} is planned, and the register holds no guidance for it to review by"
            )
        guidance[i.id] = i.guidance[newest_index(i.guidance, day=lambda g: g.assessed)]
    out = []
    for plan in portfolio.initiatives:
        for a in plan.planning:
            g = guidance[plan.id]
            review = add(
                parse_day(a.assessed), intervals[g.half_life]
            )  # weeks and days kept, as the check adds
            out.append(
                {
                    "initiative": plan.id,
                    "assessed": a.assessed,
                    "full_value_in": a.full_value_in,
                    "first_value_in": a.first_value_in,
                    "tier": tier_of(a.full_value_in, pol),
                    "first_value_tier": tier_of(a.first_value_in, pol),
                    "half_life": g.half_life,
                    "review_by": review.isoformat(),
                    "confidence": a.confidence,
                    "kind": a.kind,
                    "source": a.source,
                    "method": {"id": method.id, "version": method.version},
                }
            )
    return out


def newest_index(items: list, day=lambda a: a["assessed"]) -> int | None:
    """The newest of a list of dated items (an initiative's assessments, a value's readings), by its day, a stamp's day
    being its first ten characters and its time not read; of two on one day, the later in the list. The one rule every
    reader picks the newest by: the board, the readiness and forecast rules, a capability's page, GATE-6 and the date
    gate."""
    return max(range(len(items)), key=lambda k: (str(day(items[k]))[:10], k), default=None)


def newest_assessments(plans: list[dict]) -> list[dict]:
    """Each initiative's newest planning assessment, by date, never by its place in the list: the one the readiness
    and forecast rules judge and the board shows; an older one is superseded."""
    by_initiative: dict[str, list[dict]] = {}
    for p in plans:
        by_initiative.setdefault(p["initiative"], []).append(p)
    keep = {id(group[newest_index(group)]) for group in by_initiative.values()}
    return [p for p in plans if id(p) in keep]


COMMITTED = {"committed", "delivering"}  # a plan past the committed line (charter section 5.7)


def readiness_problems(register: Register, portfolio: Portfolio, pol: Loaded) -> list[dict]:
    """GATE-8 and GATE-6 over the derived tiers, as data: an initiative nearer than the tier of the initiative that
    establishes one of its unestablished prerequisites (`nearer`; the nearest committed establisher, or else the
    nearest, charter section 5.7), and one whose prerequisite is neither established nor established by a committed
    initiative and whose tier is not labelled a forecast (`unconstrained`, with the uncommitted `makers` named): a
    horizon that rests on a decision nobody has made is a forecast (40-BREADTH.md step 5, 3c's judgment)."""
    order = [t["id"] for t in pol.get("planning-tiers")]
    # each initiative judged on its newest planning assessment, by date, never by its place in the list
    plans = newest_assessments(run_method("planning-horizon", register, portfolio, pol))
    tiers = {p["initiative"]: p["tier"] for p in plans}
    confidence = {p["initiative"]: p["confidence"] for p in plans}
    done = established(register, portfolio)
    committed = {p.id for p in portfolio.initiatives if p.status.value in COMMITTED}
    by_cap = {}
    for d in register.initiatives:
        for c in d.establishes:
            by_cap.setdefault(_ref(c), []).append(d.id)
    problems = []
    for d in register.initiatives:
        if d.id not in tiers:  # not planned by this estate, so no tier to judge
            continue
        for c in (_ref(x) for x in d.requires):
            if c in done:
                continue
            makers = [m for m in by_cap.get(c, []) if m != d.id and m in tiers]
            committed_makers = [m for m in makers if m in committed]
            if not committed_makers and confidence[d.id] != "forecast":
                problems.append(
                    {"kind": "unconstrained", "initiative": d.id, "requires": c, "makers": makers}
                )
            if not makers:
                continue
            nearest = min(committed_makers or makers, key=lambda m: order.index(tiers[m]))
            if order.index(tiers[d.id]) < order.index(tiers[nearest]):
                problems.append(
                    {
                        "kind": "nearer",
                        "initiative": d.id,
                        "requires": c,
                        "tier": tiers[d.id],
                        "nearest": nearest,
                        "nearest_tier": tiers[nearest],
                    }
                )
    return problems


def readiness(register: Register, portfolio: Portfolio, pol: Loaded) -> list[str]:
    """The readiness problems, as the report states them."""
    return [
        f"{p['initiative']}: requires {p['requires']}, which no {'committed ' if p.get('makers') else ''}initiative "
        "establishes, yet its tier is not a forecast"
        if p["kind"] == "unconstrained"
        else f"{p['initiative']}: its tier {p['tier']} is nearer than {p['nearest']}'s {p['nearest_tier']}, which "
        f"establishes {p['requires']}"
        for p in readiness_problems(register, portfolio, pol)
    ]


# ── the views over the ledgers: V-03, and the public role briefs (section 6) ─────────────────────────────────────────
def _figure(fig, unit: str) -> dict:
    if fig is None:
        return {"value": None, "unit": unit, "kind": "not_recorded", "source": None}
    return {"value": fig.value, "unit": unit, "kind": fig.kind, "source": fig.source}


def _totals(figures: list[dict], *extra: tuple[str, str | None]) -> list[dict]:
    """Recorded figures summed per unit, never across units; each total's kind from combine over its parts, and over
    any further part it is made with (the estimate adjustment), so it names every supplier (DEC-14, GATE-7)."""
    out: dict[str, dict] = {}
    for f in figures:
        if f["value"] is None:
            continue
        t = out.setdefault(f["unit"], {"value": 0.0, "unit": f["unit"], "parts": []})
        t["value"] = round(t["value"] + f["value"], 2)
        t["parts"].append((f["kind"], f["source"]))
    return [
        {"value": t["value"], "unit": t["unit"]}
        | dict(zip(("kind", "source"), combine(*t["parts"], *extra), strict=True))
        for t in out.values()
    ]


def costs_and_value(register: Register, portfolio: Portfolio, pol: Loaded) -> list[dict]:
    """V-03's view over the ledgers: for each capability, what it costs once (its establish steps' investment), what it
    costs to keep (its sustain loops' effort), what it returns (each value's target) and what waiting costs (the cost
    of delay of the initiatives whose `cost_of_delay_through` is one of its values). Units are the register's, summed
    only within a unit; the estimate adjustment is applied where the portfolio says it applies, and named."""
    adjust = portfolio.estimate_adjustment
    plans = {p.id: p for p in portfolio.initiatives}
    out = []
    for cap in register.capabilities:
        pc = next((c for c in portfolio.capabilities if c.id == cap.id), None)
        once = [
            dict(_figure(pc.investment.get(s.id) if pc else None, s.investment_unit), part=s.id)
            for s in cap.establish
        ]
        keep = [
            dict(_figure(pc.effort.get(lp.id) if pc else None, lp.effort_unit), part=lp.id)
            for lp in cap.sustain
        ]
        units = {v.id: v.unit for v in cap.value}
        returns = []
        for v in cap.value:
            tgt = pc.targets.get(v.id) if pc else None
            returns.append(
                {
                    "value": v.id,
                    "unit": v.unit,
                    "target": None if tgt is None else tgt.value,
                    "target_kind": None if tgt is None else tgt.target_kind,
                    "window": None if tgt is None else tgt.window,
                    "kind": "not_recorded" if tgt is None else tgt.kind,
                    "source": None if tgt is None else tgt.source,
                }
            )
        waiting = [
            {
                "initiative": d.id,
                "through": d.cost_of_delay_through,
                "delta": plans[d.id].cost_of_delay.delta,
                "unit": units[d.cost_of_delay_through],
                "kind": plans[d.id].cost_of_delay.kind,
                "source": plans[d.id].cost_of_delay.source,
            }
            for d in register.initiatives
            if d.cost_of_delay_through in units and d.id in plans and plans[d.id].cost_of_delay
        ]
        once_total = _totals(once)
        out.append(
            {
                "capability": cap.id,
                "accountable": cap.accountable,
                "once": once,
                "once_total": once_total,
                "once_adjusted": [
                    dict(t, value=round(t["value"] * adjust.factor, 2), factor=adjust.factor)
                    for t in _totals(once, (adjust.kind, adjust.source))
                ]
                if adjusts(pol, portfolio, "investment")
                else [],
                "not_recorded_once": [f["part"] for f in once if f["value"] is None],
                "not_recorded_keep": [f["part"] for f in keep if f["value"] is None],
                "keep": keep,
                "keep_total": _totals(keep),
                "returns": returns,
                "waiting": waiting,
            }
        )
    return out


def role_briefs(register: Register) -> list[dict]:
    """The public brief of each role (section 6), from the register alone: what it is accountable for, what it writes,
    what it runs, the measures it owns, what it sponsors and reads, and the companion reads of its drift."""
    out = []
    for role in register.roles:
        caps = [c for c in register.capabilities if c.accountable == role.id]
        out.append(
            {
                "role": role.id,
                "name": role.name,
                "owns": role.owns,
                "accountable_for": [c.id for c in caps],
                "establishes": [
                    {"capability": c.id, "steps": [s.id for s in c.establish]} for c in caps
                ],
                "writes": [
                    {"capability": c.id, "system": d.system, "object": d.object}
                    for c in register.capabilities
                    for d in c.declarations
                    if d.writer == role.id
                ],
                "runs": [
                    {"capability": c.id, "loop": lp.id, "cadence": lp.cadence}
                    for c in register.capabilities
                    for lp in c.sustain
                    if lp.runner == role.id
                ],
                "measures": [
                    {"capability": c.id, "value": v.id, "unit": v.unit}
                    for c in register.capabilities
                    for v in c.value
                    if v.target_owner == role.id
                ],
                "drift_reads": [
                    {
                        "capability": c.id,
                        "companion": c.drift_read.companion,
                        "check": c.drift_read.check,
                        "not_covered": c.drift_read.not_covered,  # schema 3: a read no companion makes yet
                    }
                    for c in caps
                ],
                "sponsors": [d.id for d in register.initiatives if d.sponsor == role.id],
                "reads": [w.id for w in register.watch_list if w.reader == role.id],
            }
        )
    return out


# ── the report: every method's output, one provenance ───────────────────────────────────────────────────────────────
def agent_rows(register: Register) -> list[dict]:
    """The agentic page's rows, from the register's `agent_entries` alone (40-BREADTH.md step 6; charter section 5.10):
    one row per (stack, layer) pair, the stacks in the order they first appear in the register and, within a stack,
    the layers in their order of first appearance; each row with its distinct `acts` texts in that order and the
    capabilities that carry the pair. No order and no text is typed here: a layer or an entry the register adds is a row."""
    stacks: list[str] = []
    rows: dict[tuple[str, str], dict] = {}
    for c in register.capabilities:
        for e in c.agent_entries:
            if e.stack not in stacks:
                stacks.append(e.stack)
            row = rows.setdefault(
                (e.stack, e.layer),
                {"stack": e.stack, "layer": e.layer, "acts": [], "capabilities": []},
            )
            if e.acts not in row["acts"]:
                row["acts"].append(e.acts)
            if c.id not in row["capabilities"]:
                row["capabilities"].append(c.id)
    return [row for s in stacks for (stack, _layer), row in rows.items() if stack == s]


def driver_reopens(
    register: Register, portfolio: Portfolio | None = None, draft=None
) -> dict[str, list[dict]]:
    """What a driver re-opens, derived, never typed (40-BREADTH.md step 5): for each driver, each capability its
    stresses name (the register's drivers, or DEC-19's draft when given; planned ids included; two entries on one
    capability merge into one), the initiatives whose `establishes` or `improves` names it, each with the index of its
    newest guidance assessment and, when a portfolio is given, the id of its newest planning assessment there; `served`
    false where no initiative serves the capability. Step 6 renders the drivers' view from it."""
    plans = {p.id: p for p in portfolio.initiatives} if portfolio is not None else {}
    planned = set(register.planned_capabilities)
    out: dict[str, list[dict]] = {}
    for d in draft.drivers if draft is not None else register.drivers:
        caps: list[str] = []
        for c in [*(s.capability for s in d.stresses), *d.stresses_planned]:
            if c not in caps:
                caps.append(c)
        rows = []
        for c in caps:
            inits = []
            for i in register.initiatives:
                if c not in {_ref(x) for x in [*i.establishes, *i.improves]}:
                    continue
                plan = plans.get(i.id)
                k = (
                    newest_index(plan.planning, day=lambda a: a.assessed)
                    if plan and plan.planning
                    else None
                )
                inits.append(
                    {
                        "id": i.id,
                        "guidance": newest_index(i.guidance, day=lambda g: g.assessed),
                        "planning": plan.planning[k].id if k is not None else None,
                    }
                )
            rows.append(
                {
                    "capability": c,
                    "planned": c in planned,
                    "initiatives": inits,
                    "served": bool(inits),
                }
            )
        out[d.id] = rows
    return out


def report(
    register: Register, portfolio: Portfolio, pol: Loaded, drift_lines: list[dict] | None = None
) -> dict:
    """The pilot's generated output: the board, the planning tiers, the grades and the readiness check, stamped with
    each method it used (its version and status), the policy and schema versions, and the digests."""
    pol = pol.for_estate(portfolio.policy.overrides)
    used = [
        (pol.selected("prioritization").id, pol.selected("prioritization").version),
        (pol.selected("adoption-method").id, pol.selected("adoption-method").version),
        (pol.selected("planning-horizon").id, pol.selected("planning-horizon").version),
    ]
    out = {
        "board": run_method("prioritization", register, portfolio, pol),
        "planning": run_method("planning-horizon", register, portfolio, pol),
        "grades": run_method("adoption-method", register, portfolio, pol, drift_lines),
        "readiness": readiness(register, portfolio, pol),
        "costs_and_value": costs_and_value(register, portfolio, pol),
        "roles": role_briefs(register),
        "drift_lines": len(drift_lines or []),
        "estate": portfolio.estate,  # the views name the estate from here, never typing it
        # the methods each view's figures come from, so a page's provenance names the methods it used and no other
        "view_methods": {
            "board": [pol.selected("prioritization").id, pol.selected("planning-horizon").id],
            "capability": [pol.selected("adoption-method").id],
            "costs": [],
            "register": [],
        },
        # every override the estate applies, with its kind and the decision that supplied it: a page made from the
        # portfolio names them all, whatever entry each overrides and whichever method reads it
        "overrides": [
            {"entry": o.entry, "kind": o.kind, "decided_by": o.decided_by}
            for o in portfolio.policy.overrides
            if o.entry in pol.overrides
        ],
        "provenance": provenance(pol, used, register, portfolio, drift_lines),
    }
    out["board"].pop("provenance")  # one provenance for the whole output
    return out


# ── where each part of a figure comes from (40-BREADTH.md step 2; no method calls these) ─────────────────────────────
# A served board says a figure is partial when a part of it was withheld (render._effort_held). This helper returns
# each part's address in the portfolio, selecting the same parts as the method's own helper (`_added_effort_kind`), which
# a test holds it to on every fixture; the registered methods are not edited.
def added_effort_addresses(
    register: Register, portfolio: Portfolio, initiative_id: str
) -> list[tuple[str, ...]]:
    """The addresses of the parts `_added_effort_kind` reads for an initiative: its own figure, then each loop's
    effort, in its order."""
    plan = next(i for i in portfolio.initiatives if i.id == initiative_id)
    owner = initiative_loops(register, initiative_id, set(plan.added_effort.loops))
    efforts = {c.id: c.effort for c in portfolio.capabilities}
    # the loops in the order `_added_effort_kind` reads them (initiative_loops' order), so the parts and their
    # addresses line up one to one (step 5, B 5)
    return [("initiatives", initiative_id, "added_effort")] + [
        ("capabilities", cap_id, "effort", loop_id)
        for loop_id, cap_id in owner.items()
        if loop_id in efforts.get(cap_id, {})
    ]
