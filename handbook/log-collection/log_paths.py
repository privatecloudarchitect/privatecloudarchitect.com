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
     own applications arriving (G-287).

Writes `log-paths.record.json` with every estate value replaced by a placeholder (and refuses to write if one
survived), and prints a summary. Not covered: the proxy-side data persistence settings
(`fqDataForwarder*` in the proxy's `collector.properties`), which only a root shell on the proxy can read, and Log
Management's replica count, which Fleet LCM does not report.

Environment (as the metrics harness): OPS_HOST, OPS_API_TOKEN; optional OPS_BROKER_HOST, OPS_REALM,
OPS_TLS_VERIFY. Usage: python3 log_paths.py [--out DIR] [--verify-sources [--minutes N]]
"""

from __future__ import annotations

import argparse
import json
import sys
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

from opslib import _ctx, bearer, ops  # noqa: E402
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=Path.cwd())
    parser.add_argument(
        "--verify-sources", action="store_true", help="prove each ESX host's own logs arrive"
    )
    parser.add_argument("--minutes", type=int, default=60, help="window for --verify-sources")
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
            scrub.add_host((inst.get("resourceKey") or {}).get("name"), "adapter")
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
    args.out.mkdir(parents=True, exist_ok=True)
    scrub.write(args.out / "log-paths.record.json", record)

    def say(line: str) -> None:
        """The console gets the same placeholders as the record."""
        print(scrub.scrub(line))

    say(f"read at {read_at}")
    for col in collectors:
        say(f"  collector {col['type']:<20} data persistence {col['data_persistence']}")
    carrying = sum(n for n in tally.values())
    say(f"  {carrying} of {len(instances)} adapter instances carry LOG_COLLECTION:")
    for (kind, path), n in sorted(tally.items()):
        say(f"    {kind:<20} {path:<12} x{n}")
    for comp in components:
        say(
            f"  {comp['type']:<8} deployment {comp['deployment']}, {comp['version']}, size {comp['size']}, "
            f"{comp['nodes']} node(s) listed"
        )
    if args.verify_sources:
        hosts = record["source_proof"]["hosts"]
        delivered = [h for h in hosts if h["own_events"]]
        say(
            f"  source proof, last {args.minutes} min: {len(delivered)} of {len(hosts)} ESX hosts delivered their own logs"
        )
        for h in hosts:
            say(
                f"    {h['host']:<34} own events {h['own_events']:>6}  via {', '.join(h['forwarders']) or '-'}"
            )
    say(f"  record: {args.out / 'log-paths.record.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
