"""frameworks/cartography/flow/lib/_identity - the VCF component identity anchor (the certainty anchor).

A port number is a hint, not proof. 8000 is vMotion or a dev server; 179 is NSX BGP or a Calico CNI
worker; 2379 is etcd for any Kubernetes. In a sprawling estate those collide. The certainty that a
flow endpoint is VCF infrastructure comes not from its port but from its authoritative entity
identity, and vRNI types its own inventory: Host (ESXi), VCenterManager, NSXTManager, NSXTEdgeCluster,
NSXTTransportNode, each carrying its management IP(s). This lens resolves a flow endpoint (a name or an
IP) to that identity, so a port only ever corroborates a role the inventory has already proven. A
workload VM can never be an ESXi Host, so an endpoint on port 8000 that vRNI types as a Host is
certainly vMotion, and the same port on a plain VM is not.

Functional core: `build_inventory` folds `(vrni_type, name, ips)` records into a resolver;
`role_of` looks one up. Shell: `collect_vcf_components` reads the vRNI entity API and degrades
gracefully, an entity type this vRNI build does not support is skipped, so the anchor falls back to an
empty inventory (and the caller to port-only heuristics) rather than failing.
"""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, ConfigDict

from lib._client import HttpError, VrniSession

VcfRole = Literal["vcenter", "nsx-manager", "nsx-edge", "esxi-host", "nsx-transport-node"]

# vRNI entity type -> (role, precedence). Lower precedence WINS when one endpoint matches several
# types (a Host is also a Transport Node; keep the more-specific physical/appliance role). The
# host-data-plane roles are the ones for which collision-prone ports (vMotion/BGP/iSCSI) are real.
_TYPE_ROLE: dict[str, tuple[VcfRole, int]] = {
    "VCenterManager": ("vcenter", 0),
    "NSXTManager": ("nsx-manager", 1),
    "NSXTEdgeCluster": ("nsx-edge", 2),
    "Host": ("esxi-host", 3),
    "NSXTTransportNode": ("nsx-transport-node", 4),
}
INFRA_ENTITY_TYPES: tuple[str, ...] = tuple(_TYPE_ROLE)
HOST_DATA_PLANE_ROLES: frozenset[VcfRole] = frozenset({"esxi-host", "nsx-transport-node", "nsx-edge"})

_IPV4 = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")
_FETCH_BATCH = 100


class VcfComponentInventory(BaseModel):
    """A resolver: a flow endpoint (name or IP) -> the VCF role vRNI authoritatively typed it as."""

    model_config = ConfigDict(frozen=True)

    by_key: dict[str, VcfRole]   # lowercased FQDN + short name + each management IP -> role
    role_counts: dict[str, int]  # role -> number of distinct components

    @property
    def total(self) -> int:
        return sum(self.role_counts.values())

    def role_of(self, endpoint: str) -> "VcfRole | None":
        """Resolve an endpoint (VM name, host FQDN, or IP) to its VCF role, or None."""
        key = endpoint.strip().lower()
        return self.by_key.get(key) or self.by_key.get(key.split(".", 1)[0])


def build_inventory(entities: Iterable[tuple[str, str, list[str]]]) -> VcfComponentInventory:
    """Fold ``(vrni_entity_type, name, ips)`` records into a resolver. Pure. Every component
    contributes its FQDN, its short name, and each management IP as a lookup key; when a key matches
    more than one type the most-specific role wins."""
    best: dict[str, tuple[int, VcfRole]] = {}
    identified: set[tuple[VcfRole, str]] = set()
    for vtype, name, ips in entities:
        mapping = _TYPE_ROLE.get(vtype)
        if mapping is None:
            continue
        role, rank = mapping
        identified.add((role, name or (ips[0] if ips else vtype)))
        keys: set[str] = set()
        if name:
            keys.add(name.strip().lower())
            keys.add(name.strip().lower().split(".", 1)[0])
        keys.update(ip for ip in ips if _IPV4.match(ip) and not ip.endswith(".0"))
        for k in keys:
            current = best.get(k)
            if current is None or rank < current[0]:
                best[k] = (rank, role)
    by_key = {k: role for k, (_, role) in best.items()}
    counts: Counter = Counter(role for role, _ in identified)
    return VcfComponentInventory(by_key=by_key, role_counts=dict(counts))


def _ips_from(value: object) -> list[str]:
    """The IPv4 string(s) in a vRNI ip field, which may be a bare string, an ``{ip_address}`` object,
    or a list of either (Host ``ip_addresses`` vs the appliance ``ip_address`` object)."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        inner = value.get("ip_address")
        return [inner] if isinstance(inner, str) else []
    if isinstance(value, list):
        return [ip for item in value for ip in _ips_from(item)]
    return []


def _extract_ips(raw: dict) -> list[str]:
    """Pull the management IPv4s from a vRNI entity's raw payload, dropping subnet/network addresses
    (``.0``), duplicates, and non-IPv4 values."""
    out = _ips_from(raw.get("ip_address")) + _ips_from(raw.get("ip_addresses"))
    return [ip for ip in dict.fromkeys(out) if _IPV4.match(ip) and not ip.endswith(".0")]


def collect_vcf_components(client: VrniSession, *, hours: int = 24,
                          max_per_type: int = 5000) -> VcfComponentInventory:
    """Build the identity inventory from vRNI's authoritative entity types. Read-only I/O shell.
    Graceful: an entity type this vRNI build does not support is skipped, so the anchor degrades to an
    empty inventory rather than failing, and the caller falls back to port-only heuristics."""
    records: list[tuple[str, str, list[str]]] = []
    for vtype in INFRA_ENTITY_TYPES:
        try:
            refs, _total = client.search(vtype, hours=hours, size=max_per_type)
        except HttpError:
            continue
        ids = [r.get("entity_id") for r in refs if isinstance(r, dict) and r.get("entity_id")]
        for start in range(0, len(ids), _FETCH_BATCH):
            try:
                raws = client.fetch(vtype, ids[start:start + _FETCH_BATCH])
            except HttpError:
                continue
            for raw in raws:
                records.append((vtype, raw.get("name") or "", _extract_ips(raw)))
    return build_inventory(records)
