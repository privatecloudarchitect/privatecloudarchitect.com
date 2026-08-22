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
"""
from __future__ import annotations

import json
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
    lenses: tuple[str, ...]     # lenses that placed this VM: flow / identity / metadata / zone / declared
    conflicts: tuple[str, ...]  # findings needing human confirmation (empty == clean)
    basis: str                  # one-line evidence summary
    app_source: str | None = None  # "declared" (owner label) / "derived" (flow cluster) / None

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
    precisely the thing a human must resolve). The declared lens (owner-stated labels) is
    authoritative, so its presence alone is high-confidence; otherwise 2+ observed lenses is high, 1
    is medium."""
    if has_conflict:
        return "low"
    if "declared" in lenses:
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
            if decl.env != "unknown":
                env = decl.env

        confidence = _confidence(lenses, bool(conflicts))
        basis = f"{role_basis} | env={env} | zone={zone}"[:_MAX_BASIS_CHARS]
        results.append(ArbitratedClassification(
            vm=vm, role=role, app_id=app_id, app_source=app_source, tier=tier,
            service_type=service_type, env=env, zone=zone, confidence=confidence,
            lenses=tuple(sorted(lenses)), conflicts=tuple(conflicts), basis=basis,
        ))

    results.sort(key=lambda c: (not c.needs_review, _CONF_RANK[c.confidence], _ROLE_RANK[c.role], c.vm))
    return ArbitrationReport(
        window_hours=shared.window_hours,
        total_vms=len(results),
        role_distribution=dict(Counter(c.role for c in results)),
        confidence_distribution=dict(Counter(c.confidence for c in results)),
        needs_review=sum(1 for c in results if c.needs_review),
        classifications=tuple(results),
    )


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
