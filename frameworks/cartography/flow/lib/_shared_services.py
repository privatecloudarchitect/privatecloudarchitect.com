"""frameworks/cartography/flow/lib/_shared_services - Phase 4: shared-services extraction by fan-in.

A shared service is a destination reached by many DISTINCT sources on well-known infrastructure
ports (DNS, AD/LDAP, Kerberos, NTP, DHCP, syslog, NFS, SMTP, and the VCF platform itself): the
high-fan-in nodes that must be quarantined BEFORE application-boundary detection (Phase 5), or every
application appears connected to every other through them.

Functional core, no I/O: `project_flows` reduces raw vRNI flows to typed projections; `analyze`
computes the fan-in ranking into a ranked report. Every candidate carries its basis (fan-in count +
the infra ports served) and a verdict: `shared-service` (high fan-in on infrastructure ports),
`review` (high fan-in but only on ambiguous web ports, a shared service or a popular front-end), or
`application-private` (low fan-in). A classification is a defensible candidate for confirmation,
never an opaque auto-decision.

This estate uses port-only heuristics. The pca `vcf-opsnet` CLI adds an identity anchor (vRNI's own
authoritative entity typing) that turns a host-data-plane port guess into a proven VCF-component
role; folding that in is a documented enhancement, and `analyze` degrades to exactly this port-only
behaviour without it.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, ConfigDict

from lib._identity import HOST_DATA_PLANE_ROLES, VcfComponentInventory

# Generic directory / auth / time / logging / storage services a service many clients DEPEND on.
# (IANA well-known; provider-agnostic.)
INFRA_PORTS: dict[int, str] = {
    53: "DNS", 5353: "mDNS",
    389: "LDAP", 636: "LDAPS", 3268: "GC-LDAP", 3269: "GC-LDAPS",
    88: "Kerberos", 464: "kpasswd",
    445: "SMB", 135: "MSRPC", 139: "NetBIOS",
    49: "TACACS+", 1812: "RADIUS", 1813: "RADIUS-acct",
    123: "NTP", 67: "DHCP", 68: "DHCP", 546: "DHCPv6", 547: "DHCPv6",
    25: "SMTP", 587: "SMTP", 465: "SMTPS",
    514: "syslog", 6514: "syslog-tls", 1514: "syslog-tls",
    161: "SNMP", 162: "SNMP-trap",
    2049: "NFS", 111: "RPC", 20048: "NFS-mountd",
}

# VCF 9.1 platform infrastructure: ports on which VCF products talk to each other (source: the
# VMware Cloud Foundation 9.1 Ports & Protocols reference). A VCF-platform destination reached by
# many hosts is infrastructure, not a workload app, so these join INFRA_PORTS in DRIVING the
# shared-service verdict (this is what stops vCenter/NSX/ESXi/vSAN polluting the app-boundary graph).
# Workload-overlapping K8s/overlay ports are DELIBERATELY excluded here (see MGMT_LABEL_PORTS).
VCF_PLATFORM_PORTS: dict[int, str] = {
    902: "ESXi-NFC", 4791: "RDMA", 319: "PTP", 320: "PTP",
    8100: "vSphere-FT", 8200: "vSphere-FT", 8300: "vSphere-FT", 5696: "KMIP",
    2233: "vSAN-RDT", 12321: "vSAN-unicast", 1443: "vSAN-SPS",
    1564: "vSAN-VDFS", 1565: "vSAN-VDFS", 875: "vSAN-File",
    500: "IKE", 4500: "IPSEC-NAT", 1234: "NSX-RPC", 1235: "NSX-CCP", 1236: "NSX-Federation",
    3784: "NSX-BFD", 3785: "NSX-BFD", 4784: "NSX-BFD-mh", 5671: "NSX-AMQP",
    2480: "NSX-Nestdb", 1167: "NSX-EdgeDHCP-HA",
    2012: "vCenter-SSO", 7444: "vCenter-SSO", 2014: "VMCA", 7476: "VMCA-API",
    2016: "vmware-authfw", 2020: "VMAFD",
    1492: "VLCR-repl", 31031: "vSphere-Replication", 44046: "vSphere-Replication",
    2055: "IPFIX", 6343: "sFlow", 4505: "Salt-pub", 4506: "Salt-ret",
}

# WEB ports are AMBIGUOUS for fan-in (a shared service OR a popular app front-end). Named distinctly
# from Phase 5's PRESENTATION_PORTS so the same identifier never means two things.
AMBIGUOUS_WEB_PORTS: dict[int, str] = {80: "HTTP", 443: "HTTPS", 8080: "HTTP-alt", 8443: "HTTPS-alt"}

# Labelled for the reader but NOT shared-service-defining. Management/admin access (SSH/RDP/FTP) is
# inbound CONTROL, not a dependency; K8s/overlay ports overlap WORKLOADS (VKS workers serve them), so
# quarantining a destination on them would wrongly pull workers out of the app graph. Label only.
MGMT_LABEL_PORTS: dict[int, str] = {
    22: "SSH", 23: "telnet", 3389: "RDP", 21: "FTP", 990: "FTPS", 69: "TFTP",
    143: "IMAP", 993: "IMAPS", 110: "POP3", 995: "POP3S",
    6081: "Geneve/overlay", 6443: "kubernetes-API", 10250: "kubelet", 2379: "etcd", 2380: "etcd-peer",
}

# COLLISION-PRONE ports: a workload can plausibly serve these too (8000 = dev HTTP-alt, 179 = Calico
# CNI BGP, 3260 = a workload iSCSI target). Port-only, they are label-only and never drive the
# verdict; the pca CLI's identity anchor promotes them to infrastructure only when it confirms a
# host-data-plane role.
HOST_SENSITIVE_PORTS: dict[int, str] = {8000: "vMotion", 179: "BGP", 3260: "iSCSI"}

# The verdict-driving set vs. the full labelling vocabulary.
_INFRA_ALL: dict[int, str] = {**INFRA_PORTS, **VCF_PLATFORM_PORTS}
_INFRA_LABELS: dict[int, str] = {**_INFRA_ALL, **HOST_SENSITIVE_PORTS}
WELL_KNOWN_PORTS: dict[int, str] = {**_INFRA_LABELS, **AMBIGUOUS_WEB_PORTS, **MGMT_LABEL_PORTS}

_SAMPLE_SOURCES = 5  # sample sources shown per candidate

Verdict = Literal["shared-service", "review", "application-private"]


# ── domain models (typed boundary) ──────────────────────────────────────────────────


class FlowProjection(BaseModel):
    """A flow reduced to what fan-in analysis needs: who to whom, on which service ports."""

    model_config = ConfigDict(frozen=True)

    source: str
    destination: str
    ports: tuple[int, ...] = ()
    protocol: str | None = None
    source_is_vm: bool = False
    destination_is_vm: bool = False

    @classmethod
    def from_raw(cls, raw: dict) -> "FlowProjection | None":
        """Project a raw vRNI Flow entity. Returns None for unresolvable or within-endpoint flows
        (no source/destination identity, or source == destination)."""
        src = resolve_endpoint(raw, "source_vm", "source_ip")
        dst = resolve_endpoint(raw, "destination_vm", "destination_ip")
        if not src or not dst or src == dst:
            return None
        proto = raw.get("protocol")
        return cls(
            source=src,
            destination=dst,
            source_is_vm=endpoint_is_vm(raw, "source_vm"),
            destination_is_vm=endpoint_is_vm(raw, "destination_vm"),
            ports=tuple(sorted(set(parse_ports(raw.get("port"))))),
            protocol=proto if isinstance(proto, str) else None,
        )


class SharedServiceCandidate(BaseModel):
    """One destination, scored + explained."""

    model_config = ConfigDict(frozen=True)

    destination: str
    distinct_sources: int
    ports: tuple[int, ...]
    well_known: tuple[str, ...]  # e.g. ("53/DNS", "389/LDAP")
    verdict: Verdict
    basis: str  # why this verdict, the defensible explanation
    sample_sources: tuple[str, ...]
    # the VCF role vRNI authoritatively typed this destination as (esxi-host / vcenter / nsx-*), or
    # None when it is not a known VCF component or the identity anchor is off. IDENTITY, not a guess.
    component_role: str | None = None


class SharedServicesReport(BaseModel):
    """The Phase-4 result: the ranked candidates + the estate context."""

    model_config = ConfigDict(frozen=True)

    window_hours: int
    total_flows: int  # raw flows fetched
    projected_flows: int  # flows that resolved to a src->dst edge
    distinct_destinations: int
    distinct_sources: int
    min_fan_in: int
    candidates: tuple[SharedServiceCandidate, ...]

    @property
    def quarantine(self) -> tuple[SharedServiceCandidate, ...]:
        """The confident shared services to pull out before boundary detection, the COMPLETE set."""
        return tuple(c for c in self.candidates if c.verdict == "shared-service")


# ── pure helpers ────────────────────────────────────────────────────────────────────


def resolve_endpoint(raw: dict, vm_key: str, ip_key: str) -> str | None:
    """Resolve a flow endpoint to a stable identity: the VM name when known, else the IP. Handles
    vRNI's shapes, a ``{entity_name}`` object, a bare IP string, or an IP object."""
    vm = raw.get(vm_key)
    if isinstance(vm, dict) and vm.get("entity_name"):
        return str(vm["entity_name"])
    ip = raw.get(ip_key)
    if isinstance(ip, str) and ip:
        return ip
    if isinstance(ip, dict):
        return str(ip.get("entity_name") or ip.get("ip_address") or ip.get("name") or "") or None
    if isinstance(ip, list) and ip:
        first = ip[0]
        if isinstance(first, str) and first:
            return first
        if isinstance(first, dict):
            return str(first.get("entity_name") or first.get("ip_address") or "") or None
    return None


def endpoint_is_vm(raw: dict, vm_key: str) -> bool:
    """True when this endpoint resolved to a named VirtualMachine (not a bare IP / external)."""
    vm = raw.get(vm_key)
    return isinstance(vm, dict) and bool(vm.get("entity_name"))


def parse_ports(value: object, *, max_expand: int = 32) -> list[int]:
    """vRNI's ``port`` is a range object ``{start, end, display, iana_name}``, a list of them, or
    (rarely) a scalar. Expand small ranges; collapse large ones to their start."""
    if isinstance(value, dict):
        start = value.get("start")
        if isinstance(start, int):
            end = value.get("end", start)
            if isinstance(end, int) and end != start and 0 < end - start <= max_expand:
                return list(range(start, end + 1))
            return [start]
        disp = value.get("display")
        return [int(disp)] if isinstance(disp, str) and disp.isdecimal() else []
    if isinstance(value, list):
        out: list[int] = []
        for item in value:
            out.extend(parse_ports(item, max_expand=max_expand))
        return out
    # isdecimal (not isdigit): superscripts are isdigit True but int() raises.
    if isinstance(value, (int, str)) and str(value).isdecimal():
        return [int(value)]
    return []


def project_flows(raw_flows: Iterable[dict]) -> list[FlowProjection]:
    """Reduce raw vRNI flows to typed projections, dropping unresolvable/within-endpoint ones."""
    projected = (FlowProjection.from_raw(raw) for raw in raw_flows)
    return [p for p in projected if p is not None]


def _classify(distinct_sources: int, infra_ports: list[int], web_ports: list[int],
              min_fan_in: int, component_role: str | None = None) -> tuple[Verdict, str]:
    if component_role is not None:
        # IDENTITY is certain: a destination vRNI authoritatively typed as a VCF component is
        # infrastructure regardless of port or fan-in, so quarantine it. A port guess becomes a role.
        port_note = (f" on {', '.join(f'{p}/{_INFRA_LABELS[p]}' for p in infra_ports)}"
                     if infra_ports else "")
        return "shared-service", (f"identified VCF component ({component_role}); "
                                  f"{distinct_sources} distinct source(s){port_note}")
    if distinct_sources < min_fan_in:
        return "application-private", f"only {distinct_sources} distinct source(s) (< {min_fan_in})"
    if infra_ports:
        names = ", ".join(f"{p}/{_INFRA_LABELS[p]}" for p in infra_ports)
        return "shared-service", f"{distinct_sources} distinct sources on infrastructure port(s) {names}"
    if web_ports:
        return "review", (
            f"{distinct_sources} distinct sources but only on web port(s) "
            f"{', '.join(f'{p}/{AMBIGUOUS_WEB_PORTS[p]}' for p in web_ports)}, a shared service "
            "or a popular app front-end; confirm against application boundaries"
        )
    return "review", f"{distinct_sources} distinct sources on non-standard port(s), confirm"


def analyze(flows: list[FlowProjection], *, total_flows: int, window_hours: int,
            min_fan_in: int = 5, limit: int | None = None,
            component_inventory: VcfComponentInventory | None = None) -> SharedServicesReport:
    """Pure fan-in analysis: rank destinations by distinct-source count and classify each. Returns
    the COMPLETE ranked set by default; ``limit`` is an optional cap. Display truncation is a caller
    concern, so the report (and ``.quarantine``) stay complete."""
    dst_srcs: dict[str, set[str]] = defaultdict(set)
    dst_ports: dict[str, set[int]] = defaultdict(set)
    all_sources: set[str] = set()
    for f in flows:
        dst_srcs[f.destination].add(f.source)
        dst_ports[f.destination].update(f.ports)
        all_sources.add(f.source)

    candidates: list[SharedServiceCandidate] = []
    for dst, srcs in dst_srcs.items():
        ports = sorted(dst_ports[dst])
        role = component_inventory.role_of(dst) if component_inventory else None
        infra = [p for p in ports if p in _INFRA_ALL]
        # collision-prone ports (vMotion/BGP/iSCSI) are infrastructure ONLY when identity confirms a
        # host-data-plane role; port-only, they stay label-only and never drive the verdict.
        if role in HOST_DATA_PLANE_ROLES:
            infra += [p for p in ports if p in HOST_SENSITIVE_PORTS]
        web = [p for p in ports if p in AMBIGUOUS_WEB_PORTS]
        verdict, basis = _classify(len(srcs), sorted(set(infra)), web, min_fan_in, role)
        candidates.append(SharedServiceCandidate(
            destination=dst,
            distinct_sources=len(srcs),
            ports=ports,
            well_known=[f"{p}/{WELL_KNOWN_PORTS[p]}" for p in ports if p in WELL_KNOWN_PORTS],
            verdict=verdict,
            basis=basis,
            sample_sources=sorted(srcs)[:_SAMPLE_SOURCES],
            component_role=role,
        ))

    rank = {"shared-service": 0, "review": 1, "application-private": 2}
    candidates.sort(key=lambda c: (rank[c.verdict], -c.distinct_sources, c.destination))
    return SharedServicesReport(
        window_hours=window_hours,
        total_flows=total_flows,
        projected_flows=len(flows),
        distinct_destinations=len(dst_srcs),
        distinct_sources=len(all_sources),
        min_fan_in=min_fan_in,
        candidates=candidates if limit is None else candidates[:limit],
    )
