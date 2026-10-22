#!/usr/bin/env python3
"""log_paths.py: which path each log source takes, what the proxies keep, and where Log Management runs.

Read-only. Every call is a GET, plus the token exchanges the platform requires to issue a read token (the
broker's api-token exchange and the suite API's service-JWT exchange), which change nothing.

  1. `GET /suite-api/api/collectors`: each collector's type and its data persistence flag.
  2. `GET /suite-api/api/adapters`: the `LOG_COLLECTION` identifier (`CLOUD_PROXY` or `DIRECT`) on every adapter
     instance that carries one, tallied by adapter kind.
  3. `GET /fleet-lcm/v1/components` (service JWT for `VCF_FLEET_LCM`, found through
     `GET /suite-api/api/integrations/services`): Log Management's deployment type, version, size and node count,
     beside VCF Operations' own.

  4. With `--verify-sources`: for every ESX host VCF Operations knows (`GET /suite-api/api/resources`, kind
     `HostSystem`), the host's **own** application events in Log Management over the last N minutes
     (`POST /api/v2/logs/search` on `:9543`, service JWT for `VCF_OPS_LI`), and the `forwarder` that relayed them.
     Events that only carry the host's name (vCenter writes them) do not count: a log path is proved by the source's
     own applications arriving (G-287). Log Management's search caps a count at 10,000 per query, so a count is a
     floor, and the proof needs only one event.
  5. With `--verify-config`: Log Management's stored log collection configuration for vCenters
     (`GET /api/v2/log-configs/config/vc`) beside its recommended one (`.../recommended-config/vc`): per vCenter
     whether collection is on, the protocol and whether TLS is set. This is the owner's setting the forwarder
     applies to every host (G-287). It needs a role that can read Log Management's configuration; a viewer is refused
     (403). Each entry's credentials are dropped unread.
  6. With `--verify-trust` (needs VC_HOSTS, VC_USER, VC_PASSWORD_FILE and pyVmomi): for every ESX host of those
     vCenters, its syslog target (`Syslog.global.logHost`) and its trusted CAs
     (`certificateManager.ListCACertificates`), and then the host's own check replayed from here: a TLS handshake to
     the target, verified against exactly that host's CAs. A host that would not trust its target's certificate goes
     silent at its next reconnect, while its open session still delivers, so the source proof alone cannot see it
     coming. vCenter's push of its trusted roots replaces a host's CAs, so the forwarder's root belongs in vCenter's
     trusted roots (G-690). The replay checks the chain against the host's CAs, not the certificate's names.

Run both proofs on a schedule, not only after a change you made: vCenter replaces every host's CAs whenever its own
trusted roots change, whoever changed them. Exit status: 0 when every read completed and nothing was found; 1 when a
host delivered none of its own events in the window, would fail its TLS check, or sits under an enabled vCenter whose
stored TLS setting differs from the recommended one (each printed under "findings"); 2 when the read did not complete
(a setting, a secret, a sign-in or the scrubber stopped it).

Writes `log-paths.record.json` with every estate value replaced by a placeholder (and refuses to write if one
survived), and prints a summary. Not covered: the proxy-side data persistence settings
(`fqDataForwarder*` in the proxy's `collector.properties`), which only a root shell on the proxy can read, and Log
Management's replica count, which Fleet LCM does not report.

Environment (as the metrics harness): OPS_HOST, OPS_API_TOKEN_FILE (or OPS_API_TOKEN); optional OPS_BROKER_HOST, OPS_REALM,
OPS_TLS_VERIFY. For --verify-trust: VC_HOSTS (comma-separated vCenter FQDNs), VC_USER and VC_PASSWORD_FILE (mode 0600;
or VC_PASSWORD). Usage: python3 log_paths.py [--out DIR] [--verify-sources [--minutes N]] [--verify-config] [--verify-trust]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import ssl
import sys
import urllib.error
import urllib.request
from collections import Counter
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

from opslib import _ctx, bearer, ops, secret  # noqa: E402
from rtmlib import service_jwt  # noqa: E402
from scrub import Scrubber  # noqa: E402


def identifiers(instance: dict) -> dict[str, str]:
    key = instance.get("resourceKey") or {}
    return {
        (i.get("identifierType") or {}).get("name"): i.get("value")
        for i in key.get("resourceIdentifiers") or []
    }


def fleet_components(tok: str) -> list[dict]:
    st, body = ops("GET", "/api/integrations/services", tok)
    entry = next(
        (s for s in (body or {}).get("servicesDetails", []) if s.get("type") == "VCF_FLEET_LCM"),
        None,
    )
    if st != 200 or entry is None:
        return []
    jwt = service_jwt(tok, "VCF_FLEET_LCM")
    base = "/" + (entry.get("basePath") or "fleet-lcm").strip("/")
    req = urllib.request.Request(
        f"https://{entry['address']}{base}/v1/components",
        headers={"Authorization": f"Bearer {jwt}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, context=_ctx(), timeout=60) as r:
        data = json.loads(r.read())
    return (
        data
        if isinstance(data, list)
        else next((v for v in data.values() if isinstance(v, list)), [])
    )


ESX_APPS = ("Hostd", "Vpxa", "vmkernel", "vobd", "Fdm")


def li_search(address: str, jwt: str, body: dict) -> dict:
    req = urllib.request.Request(
        f"https://{address}:9543/api/v2/logs/search",
        data=json.dumps(body).encode(),
        method="POST",
        headers={
            "X-JWT-Token": jwt,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, context=_ctx(), timeout=120) as r:
        return json.loads(r.read()).get("events") or {}


def source_proof(tok: str, minutes: int, scrub: Scrubber) -> list[dict]:
    """Each ESX host's own application events over the window, and who relayed them."""
    st, body = ops("GET", "/api/integrations/services", tok)
    entry = next(
        (s for s in (body or {}).get("servicesDetails", []) if s.get("type") == "VCF_OPS_LI"), None
    )
    if st != 200 or entry is None:
        return []
    jwt = service_jwt(tok, "VCF_OPS_LI")
    st, body = ops(
        "GET",
        "/api/resources",
        tok,
        params={"adapterKind": "VMWARE", "resourceKind": "HostSystem", "pageSize": 1000},
    )
    hosts = sorted(
        (r.get("resourceKey") or {}).get("name") for r in (body or {}).get("resourceList", [])
    )
    now = int(datetime.now(UTC).timestamp() * 1000)
    proof = []
    for host in hosts:
        own, forwarders = 0, set()
        for app in ESX_APPS:
            ev = li_search(
                entry["address"],
                jwt,
                {
                    "query": {
                        "bool": {
                            "must": [{"term": {"appname": app}}, {"term": {"hostname": host}}],
                            "filter": [
                                {"range": {"timestamp": {"gte": now - minutes * 60000, "lte": now}}}
                            ],
                        }
                    },
                    "size": 5,
                },
            )
            own += ev.get("total") or 0
            for hit in ev.get("hits") or []:
                fields = {
                    f.get("internalName"): f.get("value")
                    for f in hit.get("msgContent", {}).get("fields") or []
                }
                if fields.get("forwarder"):
                    forwarders.add(fields["forwarder"])
        scrub.add_host(host, "esx")
        for f in forwarders:
            scrub.add(f, "address")
        proof.append({"host": host, "own_events": own, "forwarders": sorted(forwarders)})
    return proof


def li_get(address: str, jwt: str, path: str) -> tuple[int, object]:
    req = urllib.request.Request(
        f"https://{address}:9543{path}", headers={"X-JWT-Token": jwt, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, context=_ctx(), timeout=60) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, None


def config_rows(stored: dict, recommended: dict) -> dict:
    """The owner's setting per vCenter, credentials dropped: collection on, protocol, TLS; beside the recommendation."""
    rows = [
        {
            "vcenter": c.get("componentHost"),
            "enabled": c.get("enabled"),
            "protocol": c.get("protocol"),
            "ssl_enabled": c.get("sslEnabled"),
            "esx_logs": (c.get("extensions") or {}).get("enableESXILogCollection"),
        }
        for c in (stored or {}).get("configs") or []
    ]
    rec = recommended or {}
    return {
        "vcenters": rows,
        "recommended": {"protocol": rec.get("protocol"), "ssl_enabled": rec.get("sslEnabled")},
    }


def stored_config(tok: str, scrub: Scrubber) -> dict:
    st, body = ops("GET", "/api/integrations/services", tok)
    entry = next(
        (s for s in (body or {}).get("servicesDetails", []) if s.get("type") == "VCF_OPS_LI"), None
    )
    if st != 200 or entry is None:
        return {"read": "not read: Log Management is not among the instance's services"}
    jwt = service_jwt(tok, "VCF_OPS_LI")
    st, stored = li_get(entry["address"], jwt, "/api/v2/log-configs/config/vc")
    if st != 200:
        return {"read": f"refused ({st}): the token's role cannot read Log Management's configuration"}
    _, rec = li_get(entry["address"], jwt, "/api/v2/log-configs/recommended-config/vc")
    out = config_rows(stored, rec if isinstance(rec, dict) else {})
    for row in out["vcenters"]:
        scrub.add_host(row["vcenter"], "vcenter")
    out["read"] = "read"
    return out


def parse_target(log_host: str) -> dict:
    """Syslog.global.logHost's first target: scheme, host and port (ssl://h:1514?formatter=... -> ssl, h, 1514)."""
    first = (log_host or "").split(",")[0].strip()
    if "://" not in first:
        return {"scheme": None, "host": None, "port": None}
    scheme, rest = first.split("://", 1)
    hostport = rest.split("?")[0].rstrip("/")
    host, _, port = hostport.rpartition(":")
    if not host:
        host, port = hostport, ""
    default = {"ssl": 1514, "tcp": 514, "udp": 514}.get(scheme.lower())
    return {"scheme": scheme.lower(), "host": host, "port": int(port) if port.isdigit() else default}


def trusts(target_host: str, port: int, ca_pems: list[str]) -> tuple[bool, str]:
    """Replay a host's TLS check from here: verify the target's chain against exactly that host's trusted CAs."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False  # the replay proves the chain to the host's own CAs; it does not test the names
    ctx.verify_mode = ssl.CERT_REQUIRED
    if not ca_pems:
        return False, "the host holds no trusted CAs"
    ctx.load_verify_locations(cadata="\n".join(ca_pems))
    try:
        with socket.create_connection((target_host, port), timeout=10) as s, ctx.wrap_socket(s) as t:
            t.getpeercert()
        return True, "verified"
    except ssl.SSLCertVerificationError as e:
        return False, getattr(e, "verify_message", None) or "certificate verify failed"
    except OSError as e:
        return False, f"no TLS session: {type(e).__name__}"


def trust_proof(scrub: Scrubber) -> dict:
    hosts_env = [h.strip() for h in os.environ.get("VC_HOSTS", "").split(",") if h.strip()]
    if not hosts_env:
        return {"read": "not read: VC_HOSTS not set"}
    try:
        from pyVim.connect import Disconnect, SmartConnect
        from pyVmomi import vim
    except ImportError:
        return {"read": "not read: pyVmomi is not installed"}
    password = secret("VC_PASSWORD")
    if not password:
        raise SystemExit("FATAL: VC_PASSWORD_FILE (or VC_PASSWORD) is not set")
    rows, cache = [], {}
    for vc in hosts_env:
        scrub.add_host(vc, "vcenter")
        si = SmartConnect(host=vc, user=os.environ["VC_USER"], pwd=password, sslContext=_ctx())
        try:
            content = si.RetrieveContent()
            view = content.viewManager.CreateContainerView(content.rootFolder, [vim.HostSystem], True)
            for h in sorted(view.view, key=lambda x: x.name):
                scrub.add_host(h.name, "esx")
                log_host = next(
                    (o.value for o in h.configManager.advancedOption.QueryOptions("Syslog.global.logHost")), ""
                )
                target = parse_target(str(log_host or ""))
                if target["host"]:
                    scrub.add_host(target["host"], "collector-host")
                pems = list(h.configManager.certificateManager.ListCACertificates() or [])
                if target["scheme"] != "ssl":
                    ok, why = None, "the target is not TLS"
                else:
                    key = (target["host"], target["port"], hashlib.sha256("".join(sorted(pems)).encode()).hexdigest())
                    if key not in cache:
                        cache[key] = trusts(target["host"], target["port"], pems)
                    ok, why = cache[key]
                rows.append(
                    {
                        "host": h.name,
                        "target": f"{target['scheme']}://{target['host']}:{target['port']}" if target["host"] else None,
                        "trusted_cas": len(pems),
                        "trusts_target": ok,
                        "why": why,
                    }
                )
        finally:
            Disconnect(si)
    return {"read": "read", "hosts": rows}


def findings(record: dict) -> list[str]:
    """What a scheduled run alarms on: a host at zero, a host that would fail its TLS check, a vCenter off the
    recommended TLS setting. Reads the record as the run built it; an unread block finds nothing."""
    out = []
    for h in (record.get("source_proof") or {}).get("hosts", []):
        if not h["own_events"]:
            out.append(f"{h['host']} delivered none of its own events in the window")
    tp = record.get("trust_proof") or {}
    for r in tp.get("hosts", []) if tp.get("read") == "read" else []:
        if r["trusts_target"] is False:
            out.append(f"{r['host']} would fail its TLS check at its next connect: {r['why']}")
    sc = record.get("stored_config") or {}
    if sc.get("read") == "read":
        want = sc["recommended"]["ssl_enabled"]
        for row in sc["vcenters"]:
            if row["enabled"] and row["ssl_enabled"] != want:
                out.append(f"{row['vcenter']} is stored with TLS {row['ssl_enabled']}, recommended {want}")
    return out


def report(record: dict, record_path: Path | str) -> list[str]:
    """What a run prints, built from its scrubbed record, so a transcript can be rebuilt from a record exactly."""
    out = [f"read at {record['read_at']}"]
    for col in record["collectors"]:
        out.append(f"  collector {col['type']:<20} data persistence {col['data_persistence']}")
    rows = record["log_collection"]
    carrying = sum(r["instances"] for r in rows)
    out.append(f"  {carrying} of {record['adapter_instances']} adapter instances carry LOG_COLLECTION:")
    for r in rows:
        out.append(f"    {r['adapter_kind']:<20} {r['path']:<12} x{r['instances']}")
    for comp in record["components"]:
        out.append(
            f"  {comp['type']:<8} deployment {comp['deployment']}, {comp['version']}, size {comp['size']}, "
            f"{comp['nodes']} node(s) listed"
        )
    sp = record.get("source_proof")
    if sp:
        hosts = sp["hosts"]
        delivered = [h for h in hosts if h["own_events"]]
        out.append(
            f"  source proof, last {sp['window_minutes']} min: {len(delivered)} of {len(hosts)} ESX hosts "
            "delivered their own logs"
        )
        for h in hosts:
            out.append(f"    {h['host']:<14} own events {h['own_events']:>6}  via {', '.join(h['forwarders']) or '-'}")
    sc = record.get("stored_config")
    if sc and sc.get("read") != "read":
        out.append(f"  stored configuration: {sc['read']}")
    elif sc:
        rec = sc["recommended"]
        out.append(f"  stored configuration, vCenters (recommended: {rec['protocol']}, TLS {rec['ssl_enabled']}):")
        for row in sc["vcenters"]:
            out.append(
                f"    {row['vcenter']:<14} collection {row['enabled']!s:<5}  {row['protocol']}  "
                f"TLS {row['ssl_enabled']!s:<5}  ESX logs {row['esx_logs']}"
            )
    tp = record.get("trust_proof")
    if tp and tp.get("read") != "read":
        out.append(f"  trust proof: {tp['read']}")
    elif tp:
        tls = [r for r in tp["hosts"] if r["trusts_target"] is not None]
        good = [r for r in tls if r["trusts_target"]]
        out.append(f"  trust proof: {len(good)} of {len(tls)} TLS hosts would trust their target's certificate on reconnect")
        for r in tp["hosts"]:
            verdict = "-" if r["trusts_target"] is None else ("trusts" if r["trusts_target"] else "WOULD FAIL")
            out.append(f"    {r['host']:<14} {r['trusted_cas']:>2} CAs  {verdict:<10}  {r['why']}")
    found = findings(record)
    out.append(f"  findings: {len(found)}")
    out.extend(f"    {line}" for line in found)
    out.append(f"  record: {record_path}")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=Path.cwd())
    parser.add_argument(
        "--verify-sources", action="store_true", help="prove each ESX host's own logs arrive"
    )
    parser.add_argument("--minutes", type=int, default=60, help="window for --verify-sources")
    parser.add_argument(
        "--verify-config", action="store_true", help="read the owner's log collection setting per vCenter"
    )
    parser.add_argument(
        "--verify-trust", action="store_true", help="replay each host's TLS check against its own trusted CAs"
    )
    args = parser.parse_args(argv)
    scrub = Scrubber()
    tok = bearer()
    read_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    st, body = ops("GET", "/api/collectors", tok)
    collectors = []
    for col in (body or {}).get("collector", []) if st == 200 else []:
        scrub.add_host(col.get("hostName"), "collector-host")
        collectors.append(
            {
                "name": scrub.add(col.get("name"), "collector"),
                "type": col.get("type"),
                "data_persistence": col.get("dataPersistenceEnabled"),
                "state": col.get("state"),
            }
        )

    st, body = ops("GET", "/api/adapters", tok, params={"_no_links": "true"})
    instances = (body or {}).get("adapterInstancesInfoDto", []) if st == 200 else []
    tally: Counter[tuple[str, str]] = Counter()
    for inst in instances:
        idents = identifiers(inst)
        if "LOG_COLLECTION" in idents:
            scrub.add_host((inst.get("resourceKey") or {}).get("name"), "source")
            tally[
                ((inst.get("resourceKey") or {}).get("adapterKindKey"), idents["LOG_COLLECTION"])
            ] += 1

    components = []
    for comp in fleet_components(tok):
        if comp.get("componentType") not in ("OPS_LOGS", "OPS"):
            continue
        scrub.add_host(comp.get("fqdn"), "component")
        for node in comp.get("nodes") or []:
            scrub.add_host(node.get("fqdn"), "node")
            scrub.add(node.get("ipAddress"), "address")
            scrub.add(node.get("name"), "node-name")
        components.append(
            {
                "type": comp.get("componentType"),
                "deployment": comp.get("deploymentType"),
                "version": comp.get("version"),
                "size": comp.get("size"),
                "nodes": len(comp.get("nodes") or []),
                "scope": comp.get("scope"),
                "fqdn": comp.get("fqdn"),
            }
        )

    record = {
        "harness": "log_paths.py",
        "read_at": read_at,
        "collectors": collectors,
        "adapter_instances": len(instances),
        "log_collection": [
            {"adapter_kind": kind, "path": path, "instances": n}
            for (kind, path), n in sorted(tally.items())
        ],
        "components": components,
    }
    if args.verify_sources:
        record["source_proof"] = {
            "window_minutes": args.minutes,
            "applications": list(ESX_APPS),
            "hosts": source_proof(tok, args.minutes, scrub),
        }
    if args.verify_config:
        record["stored_config"] = stored_config(tok, scrub)
    if args.verify_trust:
        record["trust_proof"] = trust_proof(scrub)
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / "log-paths.record.json"
    scrubbed = json.loads(scrub.write(path, record))
    for line in report(scrubbed, path):
        print(scrub.scrub(line))  # the record is scrubbed already; a second guard on the console
    return 1 if findings(scrubbed) else 0


def run(argv: list[str] | None = None) -> int:
    """main() with the exit contract: 2 when the read did not complete."""
    try:
        return main(argv)
    except SystemExit as e:
        if isinstance(e.code, str):
            print(e.code, file=sys.stderr)
            return 2
        raise
    except (KeyError, PermissionError, OSError) as e:
        print(f"FATAL: {type(e).__name__}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(run())
