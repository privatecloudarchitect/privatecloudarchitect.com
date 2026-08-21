"""frameworks/cartography/flow/lib/_boundaries - Phase 5: application-boundary + tier discovery.

With shared services quarantined (Phase 4), the remaining VM-to-VM flow graph decomposes into
applications: densely-coupled clusters with sparse coupling to the rest. Each cluster is a candidate
application; within it, a VM's tier is inferred from the ports it SERVES: data (SQL/NoSQL), web
(80/443), or app (everything else).

Functional core, no I/O: `build_graph` reduces flows to a weighted VM<->VM graph (shared services and
non-VM endpoints excluded); `connected_components` is a dependency-free union-find; `build_boundaries`
assembles, tiers, and names the clusters. Every application carries its member VMs with per-VM tier +
the ports that justify it, so the boundary is a defensible candidate for confirmation, not an opaque
partition.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Literal

from pydantic import BaseModel, ConfigDict

from lib._shared_services import FlowProjection

# Data-tier service ports (a VM serving one of these is the data tier).
DATA_PORTS: dict[int, str] = {
    3306: "MySQL", 5432: "Postgres", 1433: "MSSQL", 1521: "Oracle", 1830: "Oracle",
    27017: "Mongo", 6379: "Redis", 9042: "Cassandra", 5984: "CouchDB", 11211: "Memcached",
    9200: "Elasticsearch", 8086: "InfluxDB", 5433: "Greenplum", 50000: "DB2",
}
# Presentation tier = the classic public-facing HTTP/S ports only. Higher HTTP-ish ports (8080/8443)
# are typically app-server / mgmt-UI ports, so they fall through to the app tier. Named
# PRESENTATION_PORTS (not WEB_PORTS): Phase 4's AMBIGUOUS_WEB_PORTS means something else.
PRESENTATION_PORTS: dict[int, str] = {80: "HTTP", 443: "HTTPS"}

_MAX_TIER_PORTS = 6  # app-tier served-port sample cap
_MAX_SINGLETONS = 50  # unclustered VMs listed in the report

Tier = Literal["web", "app", "data", "unknown"]


# ── domain models ───────────────────────────────────────────────────────────────────


class TieredVM(BaseModel):
    model_config = ConfigDict(frozen=True)
    vm: str
    tier: Tier
    serves_ports: tuple[int, ...]  # the ports (this VM as destination) that justify the tier


class ApplicationBoundary(BaseModel):
    model_config = ConfigDict(frozen=True)
    app_id: str  # suggested name (common member stem) or app-cluster-N
    size: int  # member VM count
    internal_edges: int  # VM<->VM edges wholly inside this app
    tiers: dict[str, int]  # tier -> member count
    members: tuple[TieredVM, ...]


class BoundariesReport(BaseModel):
    model_config = ConfigDict(frozen=True)
    window_hours: int
    total_flows: int
    vm_flows: int  # VM<->VM flows kept after exclusions
    shared_services_excluded: int
    min_edge_weight: int
    applications: tuple[ApplicationBoundary, ...]
    singletons: tuple[str, ...]  # VMs with no qualifying coupling (isolated after exclusions)


# ── pure core ───────────────────────────────────────────────────────────────────────


def build_graph(flows: list[FlowProjection], *, shared_services: set[str],
                min_edge_weight: int = 1
                ) -> tuple[set[str], set[frozenset[str]], dict[str, set[int]], int]:
    """Reduce flows to a weighted, undirected VM<->VM graph. Only flows where BOTH endpoints are VMs
    and NEITHER is a shared service count. Returns (vms, edges, served_ports, kept)."""
    pair_weight: dict[frozenset[str], int] = defaultdict(int)
    served: dict[str, set[int]] = defaultdict(set)
    vms: set[str] = set()
    kept = 0
    for f in flows:
        # Tiering signal: EVERY inbound flow to a non-shared VM counts toward its served ports,
        # including from external LBs/clients (a web tier is defined by inbound :443 from outside),
        # which are not VM<->VM edges.
        if f.destination_is_vm and f.destination not in shared_services:
            served[f.destination].update(f.ports)
        # Graph edges: VM<->VM only, neither endpoint shared, no self-loops.
        if not (f.source_is_vm and f.destination_is_vm):
            continue
        if f.source in shared_services or f.destination in shared_services:
            continue
        if f.source == f.destination:
            continue
        kept += 1
        vms.add(f.source)
        vms.add(f.destination)
        pair_weight[frozenset((f.source, f.destination))] += 1
    edges = {edge for edge, weight in pair_weight.items() if weight >= min_edge_weight}
    return vms, edges, served, kept


def connected_components(vms: set[str], edges: set[frozenset[str]]) -> list[set[str]]:
    """Dependency-free union-find. Each returned set is one connected component."""
    parent: dict[str, str] = {v: v for v in vms}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]  # path halving
            x = parent[x]
        return x

    for edge in edges:
        if len(edge) != 2:  # defensive: build_graph only emits 2-sets; this fn is public
            continue
        a, b = tuple(edge)
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    groups: dict[str, set[str]] = defaultdict(set)
    for v in vms:
        groups[find(v)].add(v)
    return list(groups.values())


def assign_tier(served_ports: set[int]) -> tuple[Tier, list[int]]:
    """Infer a VM's tier from the ports it SERVES. data > web > app (a DB is a DB even if it also
    exposes a mgmt web UI). Returns (tier, the justifying ports)."""
    data = sorted(p for p in served_ports if p in DATA_PORTS)
    if data:
        return "data", data
    web = sorted(p for p in served_ports if p in PRESENTATION_PORTS)
    if web:
        return "web", web
    if served_ports:
        return "app", sorted(served_ports)[:_MAX_TIER_PORTS]
    return "unknown", []


def suggest_app_id(members: list[str], index: int) -> str:
    """Name the app from the dominant leading token among member VM names (e.g. shop-web-01 /
    shop-db-01 -> 'shop'); else 'app-cluster-N'."""
    tokens = [re.split(r"[-_.]", m)[0] for m in members if m]
    if tokens:
        common, count = Counter(tokens).most_common(1)[0]
        if len(common) >= 3 and count >= max(2, (len(members) + 1) // 2):
            return common
    return f"app-cluster-{index}"


def build_boundaries(flows: list[FlowProjection], *, shared_services: set[str], total_flows: int,
                     window_hours: int, min_edge_weight: int = 1,
                     limit: int | None = None) -> BoundariesReport:
    """Pure Phase-5 assembly: graph -> components -> tiered, named applications. Returns the COMPLETE
    set by default; ``limit`` is an optional cap (display is a caller concern)."""
    vms, edges, served, kept = build_graph(
        flows, shared_services=shared_services, min_edge_weight=min_edge_weight)
    # Deterministic component order (independent of set-hash order) so app-ids + collision suffixes
    # are reproducible run-to-run.
    comps = sorted(connected_components(vms, edges), key=lambda c: (-len(c), sorted(c)))
    vm_comp = {v: i for i, c in enumerate(comps) for v in c}
    # Single pass: internal-edge count per component (O(edges), not O(edges x components)).
    internal_counts: dict[int, int] = defaultdict(int)
    for edge in edges:
        internal_counts[vm_comp[next(iter(edge))]] += 1

    apps: list[ApplicationBoundary] = []
    singletons: list[str] = []
    used_ids: dict[str, int] = defaultdict(int)
    for i, comp in enumerate(comps):
        if len(comp) < 2:
            singletons.append(next(iter(comp)))
            continue
        tier_counts: dict[str, int] = defaultdict(int)
        members: list[TieredVM] = []
        for vm in sorted(comp):
            tier, ports = assign_tier(served.get(vm, set()))
            tier_counts[tier] += 1
            members.append(TieredVM(vm=vm, tier=tier, serves_ports=ports))
        members.sort(key=lambda m: ({"data": 0, "web": 1, "app": 2, "unknown": 3}[m.tier], m.vm))
        app_id = suggest_app_id([m.vm for m in members], i + 1)
        used_ids[app_id] += 1
        if used_ids[app_id] > 1:  # de-collide ids so consumers keying by app_id are safe
            app_id = f"{app_id}-{used_ids[app_id]}"
        apps.append(ApplicationBoundary(
            app_id=app_id,
            size=len(comp),
            internal_edges=internal_counts[i],
            tiers=dict(tier_counts),
            members=members,
        ))
    apps.sort(key=lambda a: (-a.size, a.app_id))
    return BoundariesReport(
        window_hours=window_hours,
        total_flows=total_flows,
        vm_flows=kept,
        shared_services_excluded=len(shared_services),
        min_edge_weight=min_edge_weight,
        applications=apps if limit is None else apps[:limit],
        singletons=sorted(singletons)[:_MAX_SINGLETONS],
    )
