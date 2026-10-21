"""frameworks/cartography/flow/lib/_arbitrate - Phase 7: arbitration (the triangulation capstone).

Phases 4-6 each look through one lens: flow fan-in (shared services), the VM-to-VM graph (application
boundaries + tiers), and per-VM metadata + observed exposure (environment + security zone). No single
lens is sufficient: flows show who talks to whom but not what a thing is; names and NSX constructs show
intent but lie when stale. This phase applies the framework's central rule: a classification is
trustworthy only when two or more independent lenses agree, and a conflict is a finding, not noise.

For every VM it emits ONE ArbitratedClassification: a role (shared-service / application / unclustered
/ isolated), its app + tier + env + zone, a confidence that reflects how many independent lenses
corroborate it, and the conflicts that need a human's confirmation. The optional fourth lens is
DECLARED intent (the supervisor lens's export): authoritative where present, it names the app over an
auto-generated cluster id, sets the tier, and confirms env, but never the security zone.

Pure core: `arbitrate` merges three already-computed phase reports (plus the optional declared lens)
into an ArbitrationReport. No I/O; unit-tested with synthetic reports.

The hand-off, also pure: `apply_confirmations` folds a person's decisions into the report, so a review row a
person resolved stays resolved on the next run (`load_confirmations` reads them from a plain file);
`to_recommendations` turns the rows that need no review into the supervisor lens's recommendations schema,
which `../writeback_tags.py` reads. A row is marked approve only when a person or the workload's own label set
the value; every inferred value is marked confirm, so the write-back's approve file stays the gate.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from lib._boundaries import BoundariesReport, Tier
from lib._env_zone import Confidence, Env, EnvZoneClassification, EnvZoneReport, Zone
from lib._shared_services import SharedServicesReport

Role = Literal["shared-service", "application", "unclustered", "isolated"]

# Map a declared Kubernetes component label to the inferred-tier vocabulary. Declared intent is
# authoritative when it maps cleanly; otherwise the flow-derived tier stands.
_DECLARED_TIER: dict[str, Tier] = {
    "web": "web", "web-tier": "web", "frontend": "web", "presentation": "web", "ui": "web",
    "app": "app", "app-tier": "app", "backend": "app", "api": "app", "logic": "app", "middle": "app",
    "data": "data", "data-tier": "data", "db": "data", "database": "data", "datastore": "data",
}
_MAX_BASIS_CHARS = 200
_CONF_RANK: dict[Confidence, int] = {"low": 0, "none": 1, "medium": 2, "high": 3}
_ROLE_RANK: dict[Role, int] = {"application": 0, "shared-service": 1, "unclustered": 2, "isolated": 3}


class SupervisorClassification(BaseModel):
    """The declared lens: a workload's owner-stated app / tier / env, read from the supervisor lens's
    export (Supervisor Kubernetes labels). The authoritative fourth lens when present."""

    model_config = ConfigDict(frozen=True)
    vm: str
    app: str | None = None
    tier: str | None = None
    env: str = "unknown"


class ArbitratedClassification(BaseModel):
    """One VM's unified verdict across the lenses, with its evidence + open conflicts."""

    model_config = ConfigDict(frozen=True)

    vm: str
    role: Role
    app_id: str | None          # Phase 5, set when role == "application"
    tier: Tier | None           # Phase 5, web / app / data / unknown
    service_type: str | None    # Phase 4, e.g. "53/DNS, 389/LDAP" when role == "shared-service"
    env: Env                    # Phase 6
    zone: Zone                  # Phase 6
    confidence: Confidence      # aggregate: how many independent lenses agree
    lenses: tuple[str, ...]     # lenses that placed this VM: flow / identity / metadata / zone / declared / confirmed
    conflicts: tuple[str, ...]  # findings needing human confirmation (empty == clean)
    basis: str                  # one-line evidence summary
    app_source: str | None = None   # "declared" (owner label) / "derived" (flow cluster) / "confirmed" / None
    tier_source: str | None = None  # "derived" (served ports) / "declared" / "confirmed" / None
    env_source: str | None = None   # "metadata" (names, folders, segments) / "declared" / "confirmed" / None
    resolved: tuple[str, ...] = ()  # conflicts a person resolved with an accept confirmation

    @property
    def needs_review(self) -> bool:
        """A conflict, or too little corroboration to trust for automated tag write-back."""
        return bool(self.conflicts) or self.confidence in ("low", "none")


class ArbitrationReport(BaseModel):
    """The Phase-7 result: one classification per VM + estate-level rollups."""

    model_config = ConfigDict(frozen=True)

    window_hours: int
    total_vms: int
    role_distribution: dict[str, int]
    confidence_distribution: dict[str, int]
    needs_review: int
    classifications: tuple[ArbitratedClassification, ...]

    @property
    def review_queue(self) -> tuple[ArbitratedClassification, ...]:
        """The COMPLETE subset a human should confirm, the actionable output of the framework."""
        return tuple(c for c in self.classifications if c.needs_review)


def _declared_tier(component: str) -> Tier | None:
    return _DECLARED_TIER.get(component.strip().lower())


def _same_app_family(declared: str, observed: str) -> bool:
    """Whether a declared app name and an observed flow-cluster id name the SAME app, guarding the
    ``declared vs observed`` conflict against false positives from auto-generated cluster ids
    (``shop-platform`` declared vs a ``shop`` cluster is the same app; ``portal`` vs a ``store``
    cluster is a genuine divergence). Matches on equality, prefix, or token-subset."""
    d, o = declared.lower().strip(), observed.lower().strip()
    if d == o or d.startswith(o) or o.startswith(d):
        return True
    dt = set(d.replace("_", "-").split("-"))
    ot = set(o.replace("_", "-").split("-"))
    return dt <= ot or ot <= dt


def _confidence(lenses: set[str], has_conflict: bool) -> Confidence:
    """Aggregate confidence = independent-lens agreement. A conflict is never high-confidence (it is
    precisely the thing a human must resolve). The declared lens (owner-stated labels) and a person's
    confirmation are authoritative, so either alone is high-confidence; otherwise 2+ observed lenses is
    high, 1 is medium."""
    if has_conflict:
        return "low"
    if "declared" in lenses or "confirmed" in lenses:
        return "high"
    n = len(lenses)
    if n >= 2:
        return "high"
    if n == 1:
        return "medium"
    return "none"


def arbitrate(shared: SharedServicesReport, boundaries: BoundariesReport, env_zone: EnvZoneReport,
              supervisor: Sequence[SupervisorClassification] | None = None) -> ArbitrationReport:
    """Merge the phase reports into one confidence-scored classification per VM. Pure + deterministic:
    index each lens, then for every VM in the union of what the lenses saw, assign a role, overlay
    env/zone, count corroborating lenses, and surface conflicts. ``supervisor`` is the optional
    authoritative fourth lens (declared intent); ``None`` yields exactly the observed-lens result."""
    shared_by_dst = {c.destination: c for c in shared.candidates}
    quarantine = {c.destination for c in shared.quarantine}
    review_dests = {c.destination for c in shared.candidates if c.verdict == "review"}

    vm_to_app = {m.vm: app for app in boundaries.applications for m in app.members}
    vm_to_tier = {m.vm: m for app in boundaries.applications for m in app.members}
    singletons = set(boundaries.singletons)

    env_by_vm: dict[str, EnvZoneClassification] = {c.vm: c for c in env_zone.classifications}
    declared_by_vm: dict[str, SupervisorClassification] = {c.vm: c for c in (supervisor or ())}

    app_envs: dict[str, set[str]] = defaultdict(set)
    for app in boundaries.applications:
        for m in app.members:
            c = env_by_vm.get(m.vm)
            if c and c.env != "unknown":
                app_envs[app.app_id].add(c.env)

    universe = set(env_by_vm) | set(vm_to_app) | singletons | set(declared_by_vm) | quarantine

    results: list[ArbitratedClassification] = []
    for vm in sorted(universe):
        envc = env_by_vm.get(vm)
        env: Env = envc.env if envc else "unknown"
        zone: Zone = envc.zone if envc else "unknown"
        lenses: set[str] = set()
        conflicts: list[str] = []
        app_id: str | None = None
        app_source: str | None = None
        tier: Tier | None = None
        tier_source: str | None = None
        env_source: str | None = "metadata" if env != "unknown" else None
        service_type: str | None = None

        # role: what IS this VM (flow lens)
        if vm in quarantine:
            role: Role = "shared-service"
            cand = shared_by_dst[vm]
            service_type = ", ".join(cand.well_known) or None
            lenses.add("flow")
            if cand.component_role:
                lenses.add("identity")
                role_basis = (f"identified VCF component ({cand.component_role}), "
                              f"{cand.distinct_sources} distinct sources")
            else:
                role_basis = f"shared-service, {cand.distinct_sources} distinct sources"
        elif vm in vm_to_app:
            role = "application"
            app = vm_to_app[vm]
            app_id = app.app_id
            app_source = "derived"
            tier = vm_to_tier[vm].tier
            tier_source = "derived"
            lenses.add("flow")
            role_basis = f"app '{app_id}' / {tier} tier"
            if vm in review_dests:
                conflicts.append(f"ambiguous fan-in (Phase-4 'review') yet clustered into app "
                                 f"'{app_id}', shared front-end or app member?")
            if tier == "data" and zone == "dmz":
                conflicts.append("data-tier workload in dmz zone, verify exposure is intended")
            if len(app_envs.get(app_id, set())) > 1:
                conflicts.append(f"app '{app_id}' spans envs {sorted(app_envs[app_id])}, "
                                 "boundary or tagging inconsistency")
        elif vm in singletons:
            role = "unclustered"
            role_basis = "no qualifying VM-to-VM coupling (isolated after shared-service exclusion)"
        else:
            role = "isolated"
            role_basis = "in inventory but no flows observed in the window"

        # overlay: env + zone lenses (count only confident placements)
        if envc and env != "unknown" and envc.env_confidence in ("high", "medium"):
            lenses.add("metadata")
        if envc and zone != "unknown" and envc.zone_confidence in ("high", "medium"):
            lenses.add("zone")
        if envc and envc.conflict:
            conflicts.append("env/zone signals disagree, see the env/zone overlay")

        # declared intent (Supervisor labels), authoritative fourth lens, never sets zone
        decl = declared_by_vm.get(vm)
        if decl is not None and (decl.app or decl.tier or decl.env != "unknown"):
            lenses.add("declared")
            if decl.app:
                role = "application"
                observed = vm_to_app[vm].app_id if vm in vm_to_app else None
                app_id = decl.app
                app_source = "declared"
                conflicts = [c for c in conflicts if "ambiguous fan-in" not in c]
                if observed and not _same_app_family(decl.app, observed):
                    conflicts.append(f"declared app '{decl.app}' but flows couple this VM into a "
                                     f"different cluster '{observed}', network behaviour crosses the "
                                     "declared app boundary (verify the label or the traffic)")
                    role_basis = f"declared app '{decl.app}' (flows clustered as '{observed}')"
                else:
                    role_basis = f"declared app '{decl.app}'"
            mapped = _declared_tier(decl.tier) if decl.tier else None
            if mapped is not None:
                tier = mapped
                tier_source = "declared"
            if decl.env != "unknown":
                env = decl.env
                env_source = "declared"

        confidence = _confidence(lenses, bool(conflicts))
        basis = f"{role_basis} | env={env} | zone={zone}"[:_MAX_BASIS_CHARS]
        results.append(ArbitratedClassification(
            vm=vm, role=role, app_id=app_id, app_source=app_source, tier=tier, tier_source=tier_source,
            service_type=service_type, env=env, env_source=env_source, zone=zone, confidence=confidence,
            lenses=tuple(sorted(lenses)), conflicts=tuple(conflicts), basis=basis,
        ))
    return _report(shared.window_hours, results)


def _report(window_hours: int, results: list[ArbitratedClassification]) -> ArbitrationReport:
    results = sorted(results, key=lambda c: (not c.needs_review, _CONF_RANK[c.confidence], _ROLE_RANK[c.role], c.vm))
    return ArbitrationReport(
        window_hours=window_hours,
        total_vms=len(results),
        role_distribution=dict(Counter(c.role for c in results)),
        confidence_distribution=dict(Counter(c.confidence for c in results)),
        needs_review=sum(1 for c in results if c.needs_review),
        classifications=tuple(results),
    )


# ── the hand-off: a person's confirmations, and the write-back's input ─────────────────────────────

_CONFIRMABLE: dict[str, frozenset[str] | None] = {
    "app": None,  # an open registry: any name a person chooses
    "tier": frozenset({"web", "app", "data"}),
    "env": frozenset({"prod", "stage", "dev", "test", "dr", "lab"}),
    "zone": frozenset({"restricted", "dmz", "management", "internal"}),
}
_LAYER: dict[str, str] = {"web": "presentation", "app": "logic", "data": "data"}  # the taxonomy's app-layer values
_IPV4 = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")
CONFLICT_KINDS: tuple[tuple[str, str], ...] = (
    ("ambiguous fan-in", "ambiguous-fan-in"),
    ("data-tier workload in dmz", "data-tier-in-dmz"),
    ("spans envs", "app-spans-envs"),
    ("env/zone signals disagree", "env-zone-disagree"),
    ("flows couple this VM", "declared-app-vs-flows"),
)


class Confirmation(BaseModel):
    """One decision a person made about one workload's row: accept it as it stands (resolving its conflicts),
    or set one axis to a value."""

    model_config = ConfigDict(frozen=True)
    vm: str
    field: Literal["accept", "app", "tier", "env", "zone"]
    value: str | None = None


def conflict_kind(text: str) -> str:
    """The kind of a conflict, in the framework's own vocabulary: what a counts-only record may carry."""
    return next((kind for needle, kind in CONFLICT_KINDS if needle in text), "other")


def parse_confirmations(lines: Sequence[str]) -> list[Confirmation]:
    """`<vm> accept` or `<vm> <app|tier|env|zone> <value>`, one per line; blank lines and `#` comments skipped.
    A malformed line or an out-of-vocabulary value stops the run, naming the line."""
    out: list[Confirmation] = []
    for n, raw in enumerate(lines, start=1):
        words = raw.split("#", 1)[0].split()
        if not words:
            continue
        if len(words) == 2 and words[1] == "accept":
            out.append(Confirmation(vm=words[0], field="accept"))
            continue
        if len(words) != 3 or words[1] not in _CONFIRMABLE:
            raise ValueError(f"confirmations line {n}: expected '<vm> accept' or '<vm> <app|tier|env|zone> <value>'")
        allowed = _CONFIRMABLE[words[1]]
        if allowed is not None and words[2] not in allowed:
            raise ValueError(f"confirmations line {n}: {words[1]} must be one of {', '.join(sorted(allowed))}")
        out.append(Confirmation(vm=words[0], field=words[1], value=words[2]))
    return out


def load_confirmations(path: Path) -> list[Confirmation]:
    return parse_confirmations(path.read_text(encoding="utf-8").splitlines())


def apply_confirmations(report: ArbitrationReport, confirmations: Sequence[Confirmation]
                        ) -> tuple[ArbitrationReport, list[str]]:
    """Fold a person's decisions into the report. A value confirmation sets that axis and adds the `confirmed`
    lens; it resolves no conflict on its own. `accept` moves the row's conflicts to `resolved`. Confidence is
    recounted, so a row leaves the review queue only when no conflict is left. Returns the new report and the
    workloads a confirmation names that this run did not see (stale: surfaced, never silently dropped)."""
    by_vm: dict[str, list[Confirmation]] = defaultdict(list)
    for c in confirmations:
        by_vm[c.vm].append(c)
    seen = {c.vm for c in report.classifications}
    stale = sorted(set(by_vm) - seen)
    results: list[ArbitratedClassification] = []
    for c in report.classifications:
        mine = by_vm.get(c.vm)
        if not mine:
            results.append(c)
            continue
        upd: dict = {"lenses": tuple(sorted(set(c.lenses) | {"confirmed"}))}
        for f in mine:
            if f.field == "accept":
                upd["resolved"], upd["conflicts"] = c.resolved + c.conflicts, ()
            elif f.field == "app":
                upd.update(app_id=f.value, app_source="confirmed", role="application")
            elif f.field == "tier":
                upd.update(tier=f.value, tier_source="confirmed")
            elif f.field == "env":
                upd.update(env=f.value, env_source="confirmed")
            elif f.field == "zone":
                upd["zone"] = f.value
        conflicts = upd.get("conflicts", c.conflicts)
        upd["confidence"] = _confidence(set(upd["lenses"]), bool(conflicts))
        decided = ", ".join("accepted" if f.field == "accept" else f"{f.field}={f.value}" for f in mine)
        role_basis = c.basis.split(" | ", 1)[0]
        upd["basis"] = (f"{role_basis} | env={upd.get('env', c.env)} | zone={upd.get('zone', c.zone)} "
                        f"| confirmed: {decided}")[:_MAX_BASIS_CHARS]
        results.append(c.model_copy(update=upd))
    return _report(report.window_hours, results), stale


def to_recommendations(report: ArbitrationReport) -> dict:
    """The write-back's input: the supervisor lens's recommendations schema, built from every row that needs no
    review. Per row, one recommendation per axis the write-back governs: `app` (an application's id), `tier`
    (as the taxonomy's app-layer value) and `env` (the observed environment). Marked approve only when a person
    or the workload's own label set the value (app or tier declared or confirmed; env confirmed, since a declared
    environment is itself read from a namespace name); everything inferred is marked confirm. A review-queue
    workload contributes nothing, and is counted as held; an endpoint known only by its address is left out,
    since vCenter cannot resolve it to a VM."""
    recs: list[dict] = []
    address_only = 0
    for c in report.classifications:
        if c.needs_review:
            continue
        if _IPV4.match(c.vm):
            address_only += 1
            continue

        def rec(category: str, value: str, approve: bool, source: str | None) -> None:
            recs.append({"vm": c.vm, "namespace": None, "category": category, "value": value,
                         "confidence": "high" if approve else "medium", "recommended": approve,
                         "lenses": list(c.lenses), "justification": f"{category} from {source}; {c.basis}"[:_MAX_BASIS_CHARS]})

        if c.role == "application" and c.app_id:
            rec("app", c.app_id, c.app_source in ("declared", "confirmed"), c.app_source)
        if c.tier in _LAYER:
            rec("tier", _LAYER[c.tier], c.tier_source in ("declared", "confirmed"), c.tier_source)
        if c.env != "unknown":
            rec("env", c.env, c.env_source == "confirmed", c.env_source)
    order = {"app": 0, "tier": 1, "env": 2}
    recs.sort(key=lambda r: (not r["recommended"], r["vm"], order[r["category"]]))
    return {
        "source": "arbitration",
        "window_hours": report.window_hours,
        "total_vms": report.total_vms,
        "tag_ready_vms": len({r["vm"] for r in recs}),
        "held_for_review": report.needs_review,
        "address_only": address_only,
        "recommended_count": sum(1 for r in recs if r["recommended"]),
        "confirm_count": sum(1 for r in recs if not r["recommended"]),
        "category_distribution": dict(sorted(Counter(r["category"] for r in recs).items())),
        "recommendations": recs,
    }


def load_declared(path: Path) -> list[SupervisorClassification]:
    """Build the declared lens from the supervisor lens's exported recommendations
    (``classify_supervisor.py --export``): one SupervisorClassification per VM, its app / tier / env
    taken from the matching recommendation rows. The two lenses fuse without coupling their code."""
    data = json.loads(path.read_text())
    per_vm: dict[str, dict[str, str]] = defaultdict(dict)
    for r in data.get("recommendations", []):
        vm, cat, val = r.get("vm"), r.get("category"), r.get("value")
        if vm and cat and val:
            per_vm[vm][cat] = val
    return [SupervisorClassification(vm=vm, app=axes.get("app"), tier=axes.get("tier"),
                                     env=axes.get("env", "unknown"))
            for vm, axes in per_vm.items()]
