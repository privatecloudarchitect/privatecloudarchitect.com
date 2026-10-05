#!/usr/bin/env python3
"""flow_paths.py: which collector receives the estate's flows, which sources export them, and how.

Read-only. Every call is a GET, plus Operations for Networks' token request, a flow search and a flow fetch
(POSTs that read), and a vSphere login that this script closes before it exits.

  1. Operations for Networks (`/api/ni`): its node list (collector type, version, health), every vCenter and NSX
     data source with its IPFIX state (allow-listed fields only; a data source record also carries
     credentials, which are never read), the number of flows seen in the last hour, and those flows counted by
     the host each endpoint runs on (`POST /search` for the hour's flows, then `POST /entities/fetch` in batches
     of 100 for each flow's source and destination host; a flow counts once for each host it names). A flow
     names where its endpoints run, never the host that exported it.
  2. NSX (`/policy/api/v1/infra/ipfix-*`), when NSX_HOSTS is set: the IPFIX collector and switch profiles.
  3. vSphere (pyVmomi, when installed and VC_HOSTS is set): each distributed switch's own IPFIX settings
     (collector address and port, sampling rate, timeouts, internal flows only), how many of its port
     groups export, and its member hosts, each with the hour's flows that name an endpoint on it. A host at zero
     has no named workloads: it may export nothing, or Operations for Networks may be unable to name its VMs.
     The collector's own exporter list tells the two apart.

Writes `flow-paths.record.json` with every estate value replaced by a placeholder (and refuses to write if one
survived), and prints a summary. Not covered: which hosts export (the collector's exporter list) and the
collector's on-disk buffer use, both of which need a root shell on the collector VM.

Environment:
  NI_HOST, NI_USER, NI_PASSWORD   Operations for Networks; NI_DOMAIN_TYPE LOCAL (default) or LDAP, NI_DOMAIN for LDAP
  NSX_HOSTS, NSX_USER, NSX_PASSWORD   optional, comma-separated NSX Manager FQDNs
  VC_HOSTS, VC_USER, VC_PASSWORD      optional, comma-separated vCenter FQDNs (needs pyVmomi)
  OPS_TLS_VERIFY                      TLS verification, on by default; false for a self-signed CA
Usage: python3 flow_paths.py [--out DIR]
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
# The Operations plumbing is the metrics harness's, imported rather than copied (one source of the auth flow). It sits
# beside this folder in the companion repository (handbook/metrics-collection/harness) and under the companion staging
# tree in the private one; the first that carries opslib.py is used.
LIB = next(
    (
        p
        for p in (
            HERE.parent / "metrics-collection" / "harness",
            HERE.parents[3]
            / "deploy/privatecloudarchitect/companion/staging/handbook/metrics-collection/harness",
        )
        if (p / "opslib.py").is_file()
    ),
    None,
)
if LIB is None:
    raise SystemExit(
        "FATAL: the metrics-collection harness (opslib.py) is not beside this folder; "
        "run from the companion repository's handbook/ tree"
    )
sys.path.insert(0, str(LIB))
sys.path.insert(0, str(HERE))

from opslib import _ctx  # noqa: E402
from scrub import Scrubber  # noqa: E402

NI_SAFE = {
    "entity_id",
    "entity_type",
    "fqdn",
    "nickname",
    "enabled",
    "proxy_id",
    "ipfix_enabled",
    "is_vmc",
}


def http(method: str, url: str, headers: dict, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Accept": "application/json", "Content-Type": "application/json", **headers},
    )
    try:
        with urllib.request.urlopen(req, context=_ctx(), timeout=60) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        return e.code, {}


def ni_session() -> tuple[str, dict]:
    host = os.environ["NI_HOST"]
    domain = {"domain_type": os.environ.get("NI_DOMAIN_TYPE", "LOCAL").upper()}
    if domain["domain_type"] == "LDAP":
        domain["value"] = os.environ["NI_DOMAIN"]
    st, body = http(
        "POST",
        f"https://{host}/api/ni/auth/token",
        {},
        {
            "username": os.environ["NI_USER"],
            "password": os.environ["NI_PASSWORD"],
            "domain": domain,
        },
    )
    if st != 200 or "token" not in body:
        raise SystemExit(f"FATAL: Operations for Networks token request -> HTTP {st}")
    return f"https://{host}/api/ni", {"Authorization": f"NetworkInsight {body['token']}"}


def read_ni(scrub: Scrubber) -> dict:
    base, auth = ni_session()
    scrub.add_host(os.environ["NI_HOST"], "ni-platform")
    out: dict = {"nodes": [], "sources": []}
    _, nodes = http("GET", f"{base}/infra/nodes", auth)
    for ref in nodes.get("results", []):
        _, node = http("GET", f"{base}/infra/nodes/{ref.get('id')}", auth)
        scrub.add(node.get("name"), "ni-node")
        scrub.add(node.get("ip_address"), "address")
        scrub.add(node.get("node_id"), "ni-node-id")
        out["nodes"].append(
            {
                "name": node.get("name"),
                "node_type": node.get("node_type"),
                "version": node.get("version"),
                "health": (node.get("health") or {}).get("health_status"),
                "physical_flow_collector": node.get("is_physical_flow_collector"),
            }
        )
    for kind in ("vcenters", "nsxt-managers"):
        _, refs = http("GET", f"{base}/data-sources/{kind}", auth)
        for ref in refs.get("results", []):
            _, src = http("GET", f"{base}/data-sources/{kind}/{ref.get('entity_id')}", auth)
            scrub.add_host(src.get("fqdn"), "source")
            scrub.add(src.get("nickname"), "source-nickname")
            scrub.add(src.get("entity_id"), "source-id")
            scrub.add(src.get("proxy_id"), "collector-id")
            safe = {k: v for k, v in src.items() if k in NI_SAFE}
            ipfix = src.get("ipfix_response") or {}
            if ipfix:
                scrub.add(ipfix.get("ipfix_enabled_for"), "switch-moid")
                safe["ipfix_enabled_for"] = ipfix.get("ipfix_enabled_for")
            if "antrea_ipfix_response" in src:
                safe["antrea_ipfix"] = (src.get("antrea_ipfix_response") or {}).get(
                    "ipfix_enabled_status"
                )
            out["sources"].append(safe)
    now = int(time.time())
    st, found = http(
        "POST",
        f"{base}/search",
        auth,
        {
            "entity_type": "Flow",
            "size": 1,
            "time_range": {"start_time": now - 3600, "end_time": now},
        },
    )
    out["flows_last_hour"] = found.get("total_count") if st == 200 else None
    window = {"start_time": now - 3600, "end_time": now}
    out["flows_by_host"], out["flows_read"], out["flows_without_host"] = flows_by_host(
        base, auth, window, scrub
    )
    return out


FLOW_PAGE = 10000


def flows_by_host(base: str, auth: dict, window: dict, scrub: Scrubber) -> tuple[dict, int, int]:
    """The hour's flows counted by the host each endpoint runs on, each flow once per host it names."""
    st, found = http(
        "POST",
        f"{base}/search",
        auth,
        {"entity_type": "Flow", "size": FLOW_PAGE, "time_range": window},
    )
    ids = (
        [r.get("entity_id") for r in (found.get("results") or []) if r.get("entity_id")]
        if st == 200
        else []
    )
    by_host: dict[str, int] = {}
    without = 0
    for i in range(0, len(ids), 100):
        batch = [{"entity_id": e, "entity_type": "Flow"} for e in ids[i : i + 100]]
        st, body = http("POST", f"{base}/entities/fetch", auth, {"entity_ids": batch})
        for item in (body.get("results") or body.get("entities") or []) if st == 200 else []:
            flow = item.get("entity") if isinstance(item.get("entity"), dict) else item
            hosts = {
                ((flow.get(f"{side}_host") or {}).get("entity_name") or "").strip()
                for side in ("source", "destination")
            } - {""}
            if not hosts:
                without += 1
            for h in hosts:
                scrub.add_host(h, "esx")
                by_host[h] = by_host.get(h, 0) + 1
    return by_host, len(ids), without


def read_nsx(scrub: Scrubber) -> list[dict]:
    hosts = [h.strip() for h in os.environ.get("NSX_HOSTS", "").split(",") if h.strip()]
    if not hosts:
        return []
    basic = base64.b64encode(
        f"{os.environ['NSX_USER']}:{os.environ['NSX_PASSWORD']}".encode()
    ).decode()
    auth = {"Authorization": f"Basic {basic}"}
    out = []
    for host in hosts:
        scrub.add_host(host, "nsx")
        entry: dict = {"nsx": host}
        for kind in (
            "ipfix-l2-collector-profiles",
            "ipfix-dfw-collector-profiles",
            "ipfix-l2-profiles",
            "ipfix-dfw-profiles",
        ):
            st, body = http("GET", f"https://{host}/policy/api/v1/infra/{kind}", auth)
            items = body.get("results", []) if st == 200 else []
            rows = []
            for it in items:
                scrub.add(it.get("_create_user"), "service-account")
                for col in it.get("collectors") or []:
                    scrub.add(col.get("collector_ip_address"), "address")
                rows.append(
                    {
                        k: it.get(k)
                        for k in (
                            "display_name",
                            "collectors",
                            "packet_sample_probability",
                            "export_overlay_flow",
                            "active_flow_export_timeout",
                            "idle_timeout_for_flow",
                            "_create_user",
                        )
                        if k in it
                    }
                )
            entry[kind] = {"status": st, "profiles": rows}
        out.append(entry)
    return out


def read_vsphere(scrub: Scrubber) -> list[dict] | str:
    hosts = [h.strip() for h in os.environ.get("VC_HOSTS", "").split(",") if h.strip()]
    if not hosts:
        return "not read: VC_HOSTS not set"
    try:
        from pyVim.connect import Disconnect, SmartConnect
        from pyVmomi import vim
    except ImportError:
        return "not read: pyVmomi is not installed"
    out = []
    for host in hosts:
        scrub.add_host(host, "vcenter")
        si = SmartConnect(
            host=host, user=os.environ["VC_USER"], pwd=os.environ["VC_PASSWORD"], sslContext=_ctx()
        )
        try:
            content = si.RetrieveContent()
            view = content.viewManager.CreateContainerView(
                content.rootFolder, [vim.DistributedVirtualSwitch], True
            )
            try:
                for dvs in view.view:
                    scrub.add(dvs.name, "switch")
                    scrub.add(dvs._moId, "switch-moid")
                    ipfix = getattr(dvs.config, "ipfixConfig", None)
                    groups = [pg for pg in dvs.portgroup if pg.config is not None]
                    exporting = [
                        pg
                        for pg in groups
                        if getattr(
                            getattr(pg.config.defaultPortConfig, "ipfixEnabled", None),
                            "value",
                            False,
                        )
                    ]
                    scrub.add(getattr(ipfix, "collectorIpAddress", None), "address")
                    members = sorted(
                        m.name for m in (getattr(dvs.summary, "hostMember", None) or [])
                    )
                    for m in members:
                        scrub.add_host(m, "esx")
                    out.append(
                        {
                            "vcenter": host,
                            "switch": dvs.name,
                            "moid": dvs._moId,
                            "collector_address": getattr(ipfix, "collectorIpAddress", None),
                            "collector_port": getattr(ipfix, "collectorPort", None),
                            "sampling_rate": getattr(ipfix, "samplingRate", None),
                            "active_flow_timeout": getattr(ipfix, "activeFlowTimeout", None),
                            "idle_flow_timeout": getattr(ipfix, "idleFlowTimeout", None),
                            "internal_flows_only": getattr(ipfix, "internalFlowsOnly", None),
                            "port_groups": len(groups),
                            "port_groups_exporting": len(exporting),
                            "uplink_groups_exporting": sum(
                                1 for pg in exporting if getattr(pg.config, "uplink", False)
                            ),
                            "hosts": [{"host": m} for m in members],
                        }
                    )
            finally:
                view.Destroy()
        finally:
            Disconnect(si)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    scrub = Scrubber()
    read_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    record = {
        "harness": "flow_paths.py",
        "read_at": read_at,
        "operations_for_networks": read_ni(scrub),
        "nsx": read_nsx(scrub),
        "switches": read_vsphere(scrub),
    }

    # Join each switch's hosts to the hour's flows by short host name, before anything is scrubbed: vCenter and
    # Operations for Networks may name the same host differently.
    def short(name: str) -> str:
        return name.split(".")[0].lower()

    seen: dict[str, int] = {}
    for name, n in record["operations_for_networks"]["flows_by_host"].items():
        seen[short(name)] = seen.get(short(name), 0) + n
    if isinstance(record["switches"], list):
        for sw in record["switches"]:
            for h in sw["hosts"]:
                h["flows_last_hour"] = seen.get(short(h["host"]), 0)
    args.out.mkdir(parents=True, exist_ok=True)
    scrub.write(args.out / "flow-paths.record.json", record)

    def say(line: str) -> None:
        """The console gets the same placeholders as the record."""
        print(scrub.scrub(line))

    ni = record["operations_for_networks"]
    say(f"read at {read_at}")
    for node in ni["nodes"]:
        say(
            f"  node {node['node_type']:<10} {node['version']}  health {node['health']}  "
            f"physical flow collector {node['physical_flow_collector']}"
        )
    collectors = {s.get("proxy_id") for s in ni["sources"]}
    say(f"  {len(ni['sources'])} data sources over {len(collectors)} collector(s)")
    for s in ni["sources"]:
        state = s.get("ipfix_enabled_for") or s.get("ipfix_enabled")
        say(f"    {s.get('entity_type'):<22} IPFIX: {state}")
    say(f"  flows in the last hour: {ni['flows_last_hour']}")
    say(
        f"  flows read for the host tally: {ni['flows_read']}, naming an endpoint on {len(ni['flows_by_host'])} "
        f"host(s), {ni['flows_without_host']} naming no host"
    )
    for entry in record["nsx"]:
        counts = {k: len(v["profiles"]) for k, v in entry.items() if k != "nsx"}
        say(f"  NSX IPFIX profiles: {counts}")
    switches = record["switches"]
    if isinstance(switches, str):
        say(f"  switches: {switches}")
    else:
        for sw in switches:
            say(
                f"  switch: collector set {bool(sw['collector_address'])}, port {sw['collector_port']}, "
                f"sampling {sw['sampling_rate']}, {sw['port_groups_exporting']} of {sw['port_groups']} "
                f"port groups exporting ({sw['uplink_groups_exporting']} uplink)"
            )
            if sw["hosts"]:
                say(
                    "    hosts, by flows naming an endpoint there: "
                    + ", ".join(f"{h['host']} {h['flows_last_hour']}" for h in sw["hosts"])
                )
    say(f"  record: {args.out / 'flow-paths.record.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
