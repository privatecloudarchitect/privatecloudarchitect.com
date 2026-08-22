"""frameworks/cartography/flow/lib/_env_zone - Phase 6: environment + security-zone overlay.

The two axes orthogonal to application identity: a VM is also prod/stage/dev and also in some security
zone (dmz / internal / restricted / management). This classifies each VM on both, from per-VM metadata
plus observed reachability:

  * env: the VM name, its folder / resource-pool / VLAN-segment names, and tags, matched against
    environment markers (prod/prd, dev, stage/stg, test/qa/uat, dr, lab).
  * zone: security groups + security tags + L2-segment names matched against zone markers, PLUS
    observed internet exposure (destination of a flow from a public source IP becomes dmz). Zones rank
    by sensitivity: restricted > dmz > management > internal.

Functional core, no I/O: `VmMetadata.from_raw` is the typed boundary; `classify_env` / `classify_zone`
are pure and explained (verdict + basis + confidence); `compute_internet_exposure` is flow-derived.
Classifications are defensible candidates, and CONFLICTS (a "prod" name in a dev folder) are surfaced,
never silently resolved: they are the arbitration signal.
"""
from __future__ import annotations

import ipaddress
import re
from collections import Counter, defaultdict
from typing import Literal, NamedTuple, cast

from pydantic import BaseModel, ConfigDict

from lib._client import VrniSession
from lib._shared_services import FlowProjection

# Whole-token markers (matched against delimiter-split, lowercased tokens; a marker also matches
# "<marker><digits>" e.g. prod01). Order within a category does not matter.
ENV_MARKERS: dict[str, tuple[str, ...]] = {
    "prod": ("prod", "prd", "production"),
    "stage": ("stage", "stg", "staging", "preprod"),
    "dev": ("dev", "dvl", "develop", "development"),
    "test": ("test", "tst", "qa", "uat", "sit"),
    "dr": ("dr", "recovery"),
    "lab": ("lab", "sandbox", "sbx"),
}
ZONE_MARKERS: dict[str, tuple[str, ...]] = {
    "restricted": ("pci", "restricted", "secure", "hipaa", "cde", "pii"),
    "dmz": ("dmz", "perimeter", "edge", "external", "untrust", "public"),
    "management": ("mgmt", "management", "infra", "admin"),
    "internal": ("internal", "trust", "intranet", "private"),
}
# Zone sensitivity order for conflict resolution (most restrictive wins).
ZONE_PRECEDENCE = ("restricted", "dmz", "management", "internal")

Env = Literal["prod", "stage", "dev", "test", "dr", "lab", "unknown"]
Zone = Literal["restricted", "dmz", "management", "internal", "unknown"]
Confidence = Literal["high", "medium", "low", "none"]

_MAX_BASIS_CHARS = 220


class EnvResult(NamedTuple):
    env: Env
    basis: str
    confidence: Confidence
    conflict: bool


class ZoneResult(NamedTuple):
    zone: Zone
    basis: str
    confidence: Confidence
    conflict: bool


class VmMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    subnets: tuple[str, ...] = ()   # network_address CIDRs, e.g. "10.0.0.0/24"
    security_groups: tuple[str, ...] = ()
    security_tags: tuple[str, ...] = ()
    l2_networks: tuple[str, ...] = ()
    folders: tuple[str, ...] = ()
    resource_pool: str | None = None
    vcenter_tags: tuple[str, ...] = ()
    cluster: str | None = None

    @classmethod
    def from_raw(cls, raw: dict) -> "VmMetadata | None":
        name = raw.get("name")
        if not isinstance(name, str) or not name:
            return None
        return cls(
            name=name,
            subnets=tuple(ip["network_address"] for ip in raw.get("ip_addresses", [])
                          if isinstance(ip, dict) and ip.get("network_address")),
            security_groups=_names(raw.get("security_groups")),
            security_tags=_names(raw.get("security_tags")),
            l2_networks=_names(raw.get("layer2_networks")),
            folders=_names(raw.get("folders")),
            resource_pool=_name(raw.get("resource_pool")),
            vcenter_tags=_tag_strings(raw.get("tag_key_values")),
            cluster=_name(raw.get("cluster")),
        )

    @property
    def has_private_subnet(self) -> bool:
        for cidr in self.subnets:
            try:
                if ipaddress.ip_network(cidr, strict=False).is_private:
                    return True
            except ValueError:
                continue
        return False


class EnvZoneClassification(BaseModel):
    model_config = ConfigDict(frozen=True)
    vm: str
    env: Env
    env_basis: str
    env_confidence: Confidence
    zone: Zone
    zone_basis: str
    zone_confidence: Confidence
    conflict: bool = False


class EnvZoneReport(BaseModel):
    model_config = ConfigDict(frozen=True)
    window_hours: int
    total_vms: int
    internet_exposed_vms: int
    env_distribution: dict[str, int]
    zone_distribution: dict[str, int]
    conflicts: int
    classifications: tuple[EnvZoneClassification, ...]


def _names(items: object) -> tuple[str, ...]:
    if not isinstance(items, list):
        return ()
    return tuple(i["entity_name"] for i in items if isinstance(i, dict) and i.get("entity_name"))


def _name(item: object) -> str | None:
    return item.get("entity_name") if isinstance(item, dict) and item.get("entity_name") else None


def _tag_strings(items: object) -> tuple[str, ...]:
    """vCenter tags arrive as plain strings OR as ``{entity_name}`` / ``{key, value}`` dicts; extract a
    usable string from either shape (never stringify a raw dict)."""
    if not isinstance(items, list):
        return ()
    out: list[str] = []
    for t in items:
        if isinstance(t, str) and t:
            out.append(t)
        elif isinstance(t, dict):
            val = t.get("entity_name") or t.get("value") or t.get("name") or t.get("key")
            if val:
                out.append(str(val))
    return tuple(out)


def _tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", text.lower()) if t}


def _token_hits(text: str, markers: tuple[str, ...]) -> bool:
    for tok in _tokens(text):
        for m in markers:
            if tok == m or (tok.startswith(m) and tok[len(m):].isdigit()):
                return True
    return False


def _match_categories(text: str, marker_map: dict[str, tuple[str, ...]]) -> set[str]:
    return {cat for cat, markers in marker_map.items() if _token_hits(text, markers)}


def is_public_ip(value: str) -> bool:
    try:
        return ipaddress.ip_address(value.strip()).is_global
    except ValueError:
        return False


def classify_env(meta: VmMetadata) -> EnvResult:
    """Env from the VM name + folder / resource-pool / VLAN-segment / tag markers."""
    hits: list[tuple[str, str]] = []
    sources: list[tuple[str, str]] = [("name", meta.name)]
    sources += [("folder", f) for f in meta.folders]
    sources += [("resource-pool", meta.resource_pool)] if meta.resource_pool else []
    sources += [("segment", n) for n in meta.l2_networks]
    sources += [("vc-tag", t) for t in meta.vcenter_tags]
    for kind, text in sources:
        for cat in _match_categories(text, ENV_MARKERS):
            hits.append((cat, f"{kind} '{text}'"))

    cats = {c for c, _ in hits}
    if not cats:
        return EnvResult("unknown",
                         "no env markers in name / folder / resource-pool / segment / tags",
                         "none", False)
    if len(cats) == 1:
        cat = cast(Env, next(iter(cats)))
        distinct = sorted({src for _, src in hits})
        conf: Confidence = "high" if len(distinct) >= 2 else "medium"
        return EnvResult(cat, "; ".join(distinct)[:_MAX_BASIS_CHARS], conf, False)
    counts = Counter(c for c, _ in hits)
    top = cast(Env, counts.most_common(1)[0][0])
    return EnvResult(top, f"CONFLICT {dict(counts)}, took most-supported '{top}'", "low", True)


def classify_zone(meta: VmMetadata, *, internet_exposed: bool) -> ZoneResult:
    """Zone from security groups/tags + segment names + observed internet exposure."""
    hits: list[tuple[str, str]] = []
    sources: list[tuple[str, str]] = []
    sources += [("NSX group", g) for g in meta.security_groups]
    sources += [("NSX tag", t) for t in meta.security_tags]
    sources += [("segment", n) for n in meta.l2_networks]
    sources += [("vc-tag", t) for t in meta.vcenter_tags]
    for kind, text in sources:
        for cat in _match_categories(text, ZONE_MARKERS):
            hits.append((cat, f"{kind} '{text}'"))
    if internet_exposed:
        hits.append(("dmz", "observed inbound from a public source IP"))

    cats = {c for c, _ in hits}
    if not cats:
        if meta.has_private_subnet:
            return ZoneResult("internal",
                              "no zone markers/exposure; private subnet, east-west only, default internal",
                              "low", False)
        return ZoneResult("unknown", "no zone markers or exposure observed", "none", False)
    chosen = cast(Zone, next(z for z in ZONE_PRECEDENCE if z in cats))  # most-restrictive wins
    basis = "; ".join(sorted({src for cat, src in hits if cat == chosen}))[:_MAX_BASIS_CHARS]
    conflict = len(cats) > 1
    conf: Confidence = "medium" if conflict else "high"
    if conflict:
        basis = f"zones {sorted(cats)}, took most-restrictive '{chosen}': {basis}"
    return ZoneResult(chosen, basis, conf, conflict)


def classify_all(vms: list[VmMetadata], internet_exposed: set[str]) -> list[EnvZoneClassification]:
    out: list[EnvZoneClassification] = []
    for meta in vms:
        env = classify_env(meta)
        zone = classify_zone(meta, internet_exposed=meta.name in internet_exposed)
        out.append(EnvZoneClassification(
            vm=meta.name, env=env.env, env_basis=env.basis, env_confidence=env.confidence,
            zone=zone.zone, zone_basis=zone.basis, zone_confidence=zone.confidence,
            conflict=env.conflict or zone.conflict,
        ))
    return out


def compute_internet_exposure(flows: list[FlowProjection]) -> set[str]:
    """VMs that are the destination of a flow whose source is a public (internet) IP."""
    exposed: set[str] = set()
    for f in flows:
        if f.destination_is_vm and not f.source_is_vm and is_public_ip(f.source):
            exposed.add(f.destination)
    return exposed


def build_env_zone_report(vms: list[VmMetadata], internet_exposed: set[str], *,
                          window_hours: int, limit: int | None = None) -> EnvZoneReport:
    """Pure Phase-6 assembly: classify every VM on env + zone, rank conflicts / low-confidence first,
    and tally the distributions."""
    classifications = classify_all(vms, internet_exposed)
    env_dist: dict[str, int] = defaultdict(int)
    zone_dist: dict[str, int] = defaultdict(int)
    for c in classifications:
        env_dist[c.env] += 1
        zone_dist[c.zone] += 1
    conf_rank = {"low": 0, "medium": 1, "none": 2, "high": 3}
    ranked = sorted(classifications, key=lambda c: (
        not c.conflict, conf_rank[c.env_confidence] + conf_rank[c.zone_confidence], c.vm))
    return EnvZoneReport(
        window_hours=window_hours, total_vms=len(vms),
        internet_exposed_vms=len(internet_exposed),
        env_distribution=dict(env_dist), zone_distribution=dict(zone_dist),
        conflicts=sum(1 for c in classifications if c.conflict),
        classifications=ranked if limit is None else ranked[:limit],
    )


def collect_vm_details(client: VrniSession, *, hours: int = 24, page_size: int = 500,
                       max_vms: int = 5000) -> list[dict]:
    """Search + batch-fetch VirtualMachine entity details (raw dicts). Read-only."""
    refs, _total = client.search("VirtualMachine", hours=hours, size=max_vms)
    ids = [r.get("entity_id") for r in refs if isinstance(r, dict) and r.get("entity_id")]
    out: list[dict] = []
    for start in range(0, len(ids), page_size):
        out.extend(client.fetch("VirtualMachine", ids[start:start + page_size]))
    return out
