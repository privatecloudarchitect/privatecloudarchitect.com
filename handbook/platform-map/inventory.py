#!/usr/bin/env python3
"""inventory.py - your own VCF estate placed on the platform map, read-only.

The platform-map chapter draws one estate. This reads yours from the same two services, so the picture you hold
is your own:

  1  every SDDC Manager you name (one per VCF instance): its domains with their type and status, each domain's
     clusters and hosts, and the vCenter and NSX manager each domain brings (GET /v1/domains, /v1/clusters,
     /v1/hosts, /v1/vcenters, /v1/nsxt-clusters)
  2  the fleet: VCF Operations exchanges its session for the Fleet lifecycle service's key (GET
     /suite-api/api/integrations/services, the entry of type VCF_FLEET_LCM; POST /suite-api/api/auth/token/exchange),
     then GET /fleet-lcm/v1/components at the address that entry names: each component's type, how it is hosted
     (an appliance from an OVA, or a service on the VCF services runtime), its scope, size and nodes, and the
     instance it belongs to, matched through its vCenter to the SDDC Managers read in step 1
  3  the placement checks plate 01 and plate 02 teach: one management domain per instance, a vCenter and an NSX
     manager for every domain, and where the services runtime and its nodes are

Read-only throughout. No token value is printed. With --record FILE it also writes the counts and types it read,
with every host name, identifier and object name left out, which is the shape of the record the chapter renders.

Env:  SDDC_HOSTS (comma-separated, one SDDC Manager per instance), SDDC_USER, SDDC_PASSWORD
      OPS_HOST, OPS_API_TOKEN (OPS_BROKER_HOST and OPS_REALM optional), for the fleet; omit them to skip it
      TLS_VERIFY=false on a self-signed lab CA
Exit: 0 every read answered and every check held · 1 a check differs · 2 a read failed
"""

import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone

GRANT = "urn:custom:vcf:params:oauth:grant-type:api-token"


def ctx():
    verify = os.environ.get("TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")
    return ssl.create_default_context() if verify else ssl._create_unverified_context()


def call(method, url, headers, body=None, form=None):
    data = urllib.parse.urlencode(form).encode() if form else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, context=ctx(), timeout=60) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, None


def need(status, body, what):
    if status != 200 or body is None:
        print(f"\nFAILED: {what} answered HTTP {status}; nothing below it was read")
        sys.exit(2)
    return body


def elements(host, path, bearer):
    """Every element of an SDDC Manager collection, refusing a short read against the total it declares."""
    out, page = [], 0
    while True:
        b = need(*call("GET", f"https://{host}{path}?page={page}&size=100",
                       {"Authorization": "Bearer " + bearer, "Accept": "application/json"}), f"GET {path}")
        out += b.get("elements") or []
        meta = b.get("pageMetadata") or {}
        total, pages = meta.get("totalElements"), int(meta.get("totalPages") or 1)
        page += 1
        if page >= pages:
            break
    if total is not None and len(out) != int(total):
        print(f"\nFAILED: {path} collected {len(out)} of a declared {total}")
        sys.exit(2)
    return out


def read_instance(host, user, password):
    st, tok = call("POST", f"https://{host}/v1/tokens", {"Content-Type": "application/json", "Accept": "application/json"},
                   body={"username": user, "password": password})
    bearer = need(st, tok, f"the token request at {host}").get("accessToken")
    if not bearer:
        print(f"\nFAILED: {host} answered the token request without an accessToken"); sys.exit(2)
    domains = elements(host, "/v1/domains", bearer)
    clusters = elements(host, "/v1/clusters", bearer)
    hosts = elements(host, "/v1/hosts", bearer)
    vcenters = elements(host, "/v1/vcenters", bearer)
    nsx = elements(host, "/v1/nsxt-clusters", bearer)
    rows = []
    for d in domains:
        did = d.get("id")
        rows.append({
            "type": d.get("type"), "status": d.get("status"),
            "clusters": sorted((sum(1 for h in hosts if (h.get("cluster") or {}).get("id") == c.get("id")))
                               for c in clusters if (c.get("domain") or {}).get("id") == did),
            "hosts": sum(1 for h in hosts if (h.get("domain") or {}).get("id") == did),
            "vcenters": sum(1 for v in vcenters if (v.get("domain") or {}).get("id") == did),
            "nsx": sum(1 for n in nsx if did in [x.get("id") for x in (n.get("domains") or [])]),
        })
    names = {str(x) for d in (domains, clusters, hosts, vcenters, nsx) for o in d for x in (o.get("id"), o.get("name"), o.get("fqdn"), o.get("vipFqdn")) if x}
    names.add(host)
    return {"domains": rows, "vcenter_fqdns": {v.get("fqdn") for v in vcenters}}, names


def ops_bearer():
    host = os.environ["OPS_HOST"]
    broker, realm = os.environ.get("OPS_BROKER_HOST", host), os.environ.get("OPS_REALM", "CUSTOMER")
    st, b = call("POST", f"https://{broker}/acs/t/{realm}/token", {"Content-Type": "application/x-www-form-urlencoded"},
                 form={"grant_type": GRANT, "api_token": os.environ["OPS_API_TOKEN"]})
    return need(st, b, "the identity broker's api-token exchange")["access_token"]


def read_fleet(instances):
    host = os.environ["OPS_HOST"]
    h = {"Authorization": "Bearer " + ops_bearer(), "Accept": "application/json", "Content-Type": "application/json"}
    services = need(*call("GET", f"https://{host}/suite-api/api/integrations/services", h), "the registered services")
    entry = next((s for s in services.get("servicesDetails") or [] if s.get("type") == "VCF_FLEET_LCM"), None)
    if not entry:
        print("\nFAILED: VCF Operations lists no service of type VCF_FLEET_LCM; the fleet was not read"); sys.exit(2)
    jwt = need(*call("POST", f"https://{host}/suite-api/api/auth/token/exchange", h, body={"serviceKeys": [entry["key"]]}),
               "the service key exchange").get("jwtToken")
    base = (entry.get("basePath") or "/fleet-lcm").rstrip("/")
    if not base.endswith("/fleet-lcm"):
        base = "/fleet-lcm"
    body = need(*call("GET", f"https://{entry['address']}{base}/v1/components",
                      {"Authorization": "Bearer " + jwt, "Accept": "application/json"}), "the fleet's component list")
    comps = body.get("components") or []
    declared = (body.get("pageMetadata") or {}).get("totalElements")
    if declared is not None and len(comps) != int(declared):
        print(f"\nFAILED: the component list carried {len(comps)} of a declared {declared}"); sys.exit(2)
    rows = []
    for c in comps:
        vc = (c.get("vcenter") or {}).get("fqdn")
        where = next((i for i, inst in enumerate(instances, start=1) if vc in inst["vcenter_fqdns"]), None)
        rows.append({"type": c.get("componentType"), "what": c.get("componentTypeDescription"),
                     "deployment": c.get("deploymentType"), "scope": c.get("scope"), "size": c.get("size"),
                     "nodes": dict(Counter(n.get("nodeType") for n in c.get("nodes") or [])), "instance": where})
    names = {str(x) for c in comps for x in (c.get("id"), c.get("fqdn"), c.get("sddcLcmId"), (c.get("vcenter") or {}).get("fqdn"),
                                            (c.get("vcenter") or {}).get("id")) if x}
    names |= {str(x) for c in comps for n in c.get("nodes") or [] for x in (n.get("fqdn"), n.get("name"), n.get("ipAddress"), n.get("id")) if x}
    names |= {entry.get("address", ""), host}
    return rows, names


def main():
    record = None
    if "--record" in sys.argv:
        record = sys.argv[sys.argv.index("--record") + 1]
    sddc = [h.strip() for h in os.environ.get("SDDC_HOSTS", "").split(",") if h.strip()]
    if not sddc:
        print("set SDDC_HOSTS to one SDDC Manager per instance"); sys.exit(2)
    user, password = os.environ["SDDC_USER"], os.environ["SDDC_PASSWORD"]
    print("inventory.py: your estate on the platform map, read-only\n")
    instances, seen = [], set()
    for i, host in enumerate(sddc, start=1):
        inst, names = read_instance(host, user, password)
        instances.append(inst); seen |= names
        print(f"instance {i}  (SDDC Manager {host})")
        for d in inst["domains"]:
            print(f"  domain  {str(d['type']):<11} {str(d['status']):<8} clusters {len(d['clusters'])} (hosts per cluster: "
                  f"{', '.join(map(str, d['clusters'])) or '-'})  hosts {d['hosts']}  vCenter {d['vcenters']}  NSX {d['nsx']}")
    fleet = []
    if os.environ.get("OPS_HOST") and os.environ.get("OPS_API_TOKEN"):
        fleet, names = read_fleet(instances); seen |= names
        print("\nfleet  (the Fleet lifecycle service's component list)")
        print(f"  {'component':<22} {'hosted as':<10} {'scope':<9} {'size':<12} {'nodes':<36} instance")
        for c in sorted(fleet, key=lambda c: (c["instance"] or 0, c["scope"] or "", c["type"] or "")):
            nodes = ", ".join(f"{n} {k}" for k, n in sorted(c["nodes"].items())) or "-"
            print(f"  {str(c['type']):<22} {str(c['deployment']):<10} {str(c['scope']):<9} {str(c['size']):<12} {nodes:<36} {c['instance'] or '?'}")
        per = Counter(c["instance"] for c in fleet); scope = Counter(c["scope"] for c in fleet); dep = Counter(c["deployment"] for c in fleet)
        print(f"  {len(fleet)} components: " + ", ".join(f"{per[i]} on instance {i}" for i in sorted(k for k in per if k)) +
              f"; {scope.get('FLEET', 0)} at fleet scope, {scope.get('INSTANCE', 0)} at instance scope; "
              f"{dep.get('OVA', 0)} appliances from an OVA, {dep.get('VSP', 0)} on the services runtime")
    else:
        print("\nfleet  skipped: set OPS_HOST and OPS_API_TOKEN to read it")
    # ---- the checks a map makes possible
    checks = []
    for i, inst in enumerate(instances, start=1):
        mgmt = [d for d in inst["domains"] if d["type"] == "MANAGEMENT"]
        work = [d for d in inst["domains"] if d["type"] != "MANAGEMENT"]
        checks.append((len(mgmt) == 1, f"instance {i} has one management domain" + ("" if len(mgmt) == 1 else f": it has {len(mgmt)}")))
        checks.append((True, f"instance {i} has {len(work)} workload domain(s)" + (": management only" if not work else "")))
        for d in inst["domains"]:
            checks.append((d["vcenters"] == 1 and d["nsx"] >= 1, f"instance {i}, {d['type']} domain: its own vCenter ({d['vcenters']}) and an NSX manager ({d['nsx']})"))
    if fleet:
        unmatched = [c["type"] for c in fleet if not c["instance"]]
        checks.append((not unmatched, "every fleet component matched to an instance" + (f"; not matched: {unmatched}" if unmatched else "")))
        rt = [c for c in fleet if c["type"] == "VSP"]
        checks.append((len(rt) == len(instances), f"one services runtime per instance ({len(rt)} for {len(instances)})"))
    print("\nchecks")
    for ok, what in checks:
        print(f"  {'ok     ' if ok else 'DIFFERS'} {what}")
    if record:
        out = {"captured": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "instances": [{"domains": inst["domains"]} for inst in instances], "fleet": fleet,
               "checks": [{"ok": ok, "check": what} for ok, what in checks]}
        text = json.dumps(out, indent=1)
        leaked = sorted(n for n in seen if n and len(n) > 3 and n in text)
        assert not leaked, f"an estate name reached the record ({len(leaked)}); nothing was written"
        with open(record, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print(f"\nwrote {record}: counts and types only, no host name, identifier or object name")
    sys.exit(0 if all(ok for ok, _ in checks) else 1)


if __name__ == "__main__":
    main()
