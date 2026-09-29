#!/usr/bin/env python3
"""ladder.py: walk the capacity ladder on a VCF 9.1 estate and report each layer's gate and its residue.

Capacity sits in seven layers of custody, from host to workload, and every layer has one way in and one way out.
This reads the four layers a platform team owns directly, prints each one's gate (the read that proves a join
landed, and the same read run in reverse before a leave), and reports the residue that blocks the next step:

  L1  WORKLOAD DOMAINS on SDDC Manager: type, status, clusters, the NSX Manager behind each, and whether each
      domain shares the management domain's SSO domain (a domain that does not can change owner more cleanly);
  L3  SUPERVISORS on vCenter: status, zones bound, service namespaces against tenant namespaces, and who holds
      the Supervisor's external identity provider slot. A Supervisor takes one, and when a region is built
      over it, Automation takes it;
  L4  the AUTOMATION PROVIDER plane: registered SDDC Managers, vCenters and NSX Managers, regions with their
      one NSX Manager, zones, provider gateways and IP blocks;
  L5  TENANCY: organizations, each one's quota per region (a virtual datacenter), regional networking, default
      VPCs and namespaces. An organization that is disabled but still holds any of those is residue: it keeps
      a Supervisor pinned in its region, and nothing on the tenant side looks unfinished;
  L6  the UNMANAGED VM list Automation offers for each vCenter, counted against the platform's own machines by
      name, because that list is not a candidate list for import.

Read-only throughout. Nothing here imports, drains, unbinds or deletes anything. Estate-specific names are
replaced by stable placeholders and the script refuses to write a record in which one survived. Product
vocabulary (statuses, types, layer names) is kept, because it is the lesson.

Exit code: 0 when every gate reads true and no residue was found, 2 when either is not the case, 1 on error.

Run:
  export SDDC_HOST=<sddc-manager-fqdn>        SDDC_TOKEN_FILE=/path/to/bearer         # mode 0600
  export VCENTER_HOSTS=<vcenter-fqdn>[,<vcenter-fqdn>...]
  export VCENTER_USER=<user>                  VCENTER_PASSWORD_FILE=/path/to/password # mode 0600
  #   or, instead of user and password, an existing session: VCENTER_SESSION_FILE=/path/to/session-id
  export VCFA_HOST=<automation-fqdn>          VCFA_PROVIDER_TOKEN_FILE=/path/to/bearer # a provider administrator
  export TLS_VERIFY=false                                                              # only on a self-signed lab CA
  python3 ladder.py            # prints the ladder, writes ladder.json to OUT_DIR (default .)
"""
import base64
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
PLATFORM_NAMES = [("Supervisor control plane", re.compile(r"^SupervisorControlPlaneVM")),
                  ("load balancer service engine", re.compile(r"(?i)(^|[_-])avi[_-]se[_-]")),
                  ("NSX Edge", re.compile(r"(?i)edge\d*$"))]


def ctx():
    verify = os.environ.get("TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")
    return ssl.create_default_context() if verify else ssl._create_unverified_context()


def secret(var):
    return open(os.environ[var], encoding="utf-8").read().strip()


class Labels:
    """Stable placeholders for estate names. The product's own words are reserved and never replaced."""
    RESERVED = {"MANAGEMENT", "VI", "ACTIVE", "READY", "RUNNING", "REALIZED", "CONFIGURED", "NOT_READY",
                "ERROR", "FAILED", "DELETING", "NSX_TIER0", "NSX_REGISTERED_AVI", "IAAS", "SDDC", "MIXED",
                "LICENSED", "CONNECTED", "WORKLOAD", "System", "default", "none", "all", "vsphere.local"}

    def __init__(self):
        self.maps = {}

    def get(self, family, name):
        if name is None or str(name) in self.RESERVED:
            return name
        m = self.maps.setdefault(family, {})
        if name not in m:
            m[name] = f"{family}-{len(m) + 1}"
        return "{{%s}}" % m[name]

    def raw(self):
        return [r for m in self.maps.values() for r in m]


class Client:
    def __init__(self, base, headers):
        self.base, self.headers = base, headers

    def call(self, method, path, body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        rq = urllib.request.Request(self.base + path, data=data, method=method,
                                    headers={**self.headers, **(headers or {})})
        try:
            with urllib.request.urlopen(rq, context=ctx(), timeout=90) as r:
                raw = r.read()
                return r.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, raw.decode(errors="replace")[:300]

    def get(self, path):
        return self.call("GET", path)

    def pages(self, path):
        """Every value of a paged Automation list."""
        out, page = [], 1
        while True:
            sep = "&" if "?" in path else "?"
            st, b = self.get(f"{path}{sep}page={page}&pageSize=100")
            if st != 200 or not isinstance(b, dict):
                return out if out else None
            out += b.get("values") or []
            if page >= (b.get("pageCount") or 1):
                return out
            page += 1


def gate(name, ok, detail):
    return {"gate": name, "status": "PASS" if ok else "FAIL", "detail": detail}


def read_domains(L):
    host = os.environ["SDDC_HOST"]
    c = Client(f"https://{host}", {"Authorization": f"Bearer {secret('SDDC_TOKEN_FILE')}", "Accept": "application/json"})
    st, b = c.get("/v1/domains")
    if st != 200:
        raise SystemExit(f"SDDC Manager answered {st} for /v1/domains")
    doms = []
    for d in b.get("elements", []):
        doms.append({"name": L.get("domain", d.get("name")), "type": d.get("type"), "status": d.get("status"),
                     "clusters": len(d.get("clusters") or []),
                     "nsx": L.get("nsx", (d.get("nsxtCluster") or {}).get("vipFqdn")),
                     "sharesManagementSso": bool(d.get("isManagementSsoDomain"))})
    gates = [gate("every domain ACTIVE", all(d["status"] == "ACTIVE" for d in doms),
                  f"{sum(d['status'] == 'ACTIVE' for d in doms)} of {len(doms)} domains ACTIVE")]
    return {"domains": doms, "gates": gates}


def vcenter_client(host):
    base = f"https://{host}"
    if os.environ.get("VCENTER_SESSION_FILE"):
        return Client(base, {"vmware-api-session-id": secret("VCENTER_SESSION_FILE"), "Accept": "application/json"}), False
    basic = base64.b64encode(f"{os.environ['VCENTER_USER']}:{secret('VCENTER_PASSWORD_FILE')}".encode()).decode()
    st, sid = Client(base, {"Authorization": f"Basic {basic}"}).call("POST", "/api/session")
    if st not in (200, 201) or not isinstance(sid, str):
        raise SystemExit(f"vCenter {host} refused the session ({st})")
    return Client(base, {"vmware-api-session-id": sid, "Accept": "application/json"}), True


def read_supervisors(L, vcfa_host):
    out, gates = [], []
    for host in [h.strip() for h in os.environ["VCENTER_HOSTS"].split(",") if h.strip()]:
        c, owned = vcenter_client(host)
        try:
            st, sums = c.get("/api/vcenter/namespace-management/supervisors/summaries")
            sups = (sums or {}).get("items", []) if st == 200 else []
            st, nss = c.get("/api/vcenter/namespaces/instances/v2")
            nss = nss if st == 200 and isinstance(nss, list) else []
            for s in sups:
                sid, info = s["supervisor"], s.get("info", {})
                st, binds = c.get(f"/api/vcenter/namespace-management/supervisors/{sid}/zones/bindings")
                st, provs = c.get(f"/api/vcenter/namespace-management/supervisors/{sid}/identity/providers")
                provs = provs if isinstance(provs, list) else []
                issuers = []
                for p in provs:
                    st, det = c.get(f"/api/vcenter/namespace-management/supervisors/{sid}/identity/providers/{p['provider']}")
                    issuers.append((det or {}).get("issuer_URL", "") if isinstance(det, dict) else "")
                mine = [n for n in nss if n.get("supervisor") == sid]
                svc = [n for n in mine if n.get("namespace", "").startswith(("svc-", "vmware-system"))]
                is_svc = lambda name: name.startswith(("svc-", "vmware-system"))
                zones = [{"zone": L.get("zone", z.get("zone")), "type": z.get("type"), "status": z.get("status"),
                          "markedForRemoval": bool(z.get("marked_for_removal")),
                          "tenantNamespaces": sum(1 for n in z.get("namespaces") or [] if not is_svc(n)),
                          "serviceNamespaces": sum(1 for n in z.get("namespaces") or [] if is_svc(n))}
                         for z in ((binds or {}).get("zones") or [] if isinstance(binds, dict) else [])]
                held_by_automation = sum(1 for i in issuers if vcfa_host and f"//{vcfa_host}/" in i + "/")
                out.append({"vcenter": L.get("vcenter", host), "supervisor": L.get("supervisor", info.get("name")),
                            "config_status": info.get("config_status"), "kubernetes_status": info.get("kubernetes_status"),
                            "zones": zones,
                            "identityProviders": len(provs), "identityHeldByAutomation": held_by_automation,
                            "serviceNamespaces": len(svc), "tenantNamespaces": len(mine) - len(svc)})
        finally:
            if owned:
                c.call("DELETE", "/api/session")
    for s in out:
        gates.append(gate(f"{s['supervisor']} RUNNING and READY", s["config_status"] == "RUNNING" and s["kubernetes_status"] == "READY",
                          f"{s['config_status']} / {s['kubernetes_status']}, {len(s['zones'])} zone(s) bound "
                          f"({sum(z['type'] == 'MANAGEMENT' for z in s['zones'])} management)"))
        draining = [z for z in s["zones"] if z["markedForRemoval"]]
        gates.append(gate(f"{s['supervisor']} no zone left half-drained",
                          not any(z["tenantNamespaces"] for z in draining),
                          f"{len(draining)} zone(s) marked for removal, "
                          f"{sum(z['tenantNamespaces'] for z in draining)} tenant namespace(s) still on them"))
        gates.append(gate(f"{s['supervisor']} identity slot held by Automation or empty",
                          s["identityProviders"] == s["identityHeldByAutomation"],
                          f"{s['identityProviders']} external provider(s), {s['identityHeldByAutomation']} of them this Automation"))
    return {"supervisors": out, "gates": gates}


def read_provider(L, host):
    c = Client(f"https://{host}/cloudapi", {"Authorization": f"Bearer {secret('VCFA_PROVIDER_TOKEN_FILE')}",
                                            "Accept": "application/json;version=9.0.0"})
    need = {k: c.pages(p) for k, p in {
        "sddcs": "/1.0.0/vcfInfraEndpoints", "vcenters": "/1.0.0/virtualCenters", "nsx": "/v1/nsxManagers",
        "regions": "/v1/regions", "zones": "/v1/supervisorZones", "gateways": "/v1/providerGateways",
        "ipblocks": "/v1/ipSpaces", "orgs": "/1.0.0/orgs", "vdcs": "/v1/virtualDatacenters",
        "rns": "/v1/regionalNetworkingSettings", "vpcs": "/v1/vpcs", "namespaces": "/v1/namespaceSummaries"}.items()}
    missing = [k for k, v in need.items() if v is None]
    if missing:
        raise SystemExit("the Automation provider plane refused: " + ", ".join(missing) + " (a provider administrator's bearer is required)")
    for r in need["regions"]:
        L.get("region", r.get("name"))
    vcs = [{"name": L.get("vcenter", (v.get("url") or "").split("//")[-1].strip("/")),
            "linkedToSddcManager": bool(v.get("sddcManager")), "classicOnly": bool(v.get("isDedicatedForClassicTenants")),
            "connected": bool(v.get("isConnected")), "licenseStatus": v.get("licenseStatus"), "urn": v.get("vcId")} for v in need["vcenters"]]
    regions = [{"name": L.get("region", r.get("name")), "status": r.get("status"),
                "nsx": L.get("nsx", ((r.get("nsxManager") or {}).get("name"))),
                "supervisors": len(r.get("supervisors") or []), "storagePolicies": len(r.get("storagePolicies") or [])} for r in need["regions"]]
    orgs = []
    for o in need["orgs"]:
        if o.get("name") == "System":
            continue
        oid = o.get("id")
        held = {
            "quotas": sum(1 for v in need["vdcs"] if (v.get("org") or {}).get("id") == oid),
            "regionalNetworking": sum(1 for v in need["rns"] if (v.get("orgRef") or {}).get("id") == oid),
            "vpcs": sum(1 for v in need["vpcs"] if (v.get("orgRef") or {}).get("id") == oid),
            "namespaces": sum(1 for v in need["namespaces"] if (v.get("organization") or {}).get("id") == oid)}
        orgs.append({"name": L.get("org", o.get("name")), "enabled": bool(o.get("isEnabled")), "holds": held})
    residue = [o for o in orgs if not o["enabled"] and any(o["holds"].values())]
    gates = [gate("every region READY", all(r["status"] == "READY" for r in regions),
                  f"{sum(r['status'] == 'READY' for r in regions)} of {len(regions)} region(s) READY"),
             gate("no disabled organization still holding capacity or networking", not residue,
                  f"{len(residue)} disabled organization(s) still hold quota, networking, VPCs or namespaces")]
    return {"provider": {"sddcManagers": len(need["sddcs"]), "vcenters": [{k: v for k, v in x.items() if k != "urn"} for x in vcs],
                         "nsxManagers": len(need["nsx"]), "regions": regions, "zones": len(need["zones"]),
                         "providerGateways": len(need["gateways"]), "ipBlocks": len(need["ipblocks"])},
            "tenancy": {"organizations": orgs, "residue": [o["name"] for o in residue]},
            "gates": gates, "_client": c, "_vcs": vcs}


def read_unmanaged(c, vcs, L):
    out = []
    for v in vcs:
        vals = c.pages(f"/1.0.0/virtualCenters/{v['urn']}/unmanagedVirtualMachines")
        if vals is None:
            continue
        kinds = {label: sum(1 for x in vals if rx.search(x.get("name") or "")) for label, rx in PLATFORM_NAMES}
        out.append({"vcenter": v["name"], "records": len(vals), "platformByName": kinds,
                    "fieldsPerRecord": sorted({k for x in vals for k in x})})
    return out


def main():
    L = Labels()
    vcfa_host = os.environ["VCFA_HOST"]
    rec = {"captured": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "layers": {}}
    L.get("automation", vcfa_host)
    d = read_domains(L)
    s = read_supervisors(L, vcfa_host)
    p = read_provider(L, vcfa_host)
    c, vcs = p.pop("_client"), p.pop("_vcs")
    rec["layers"] = {
        "L1 workload domains": {"domains": d["domains"], "gates": d["gates"]},
        "L3 Supervisors": {"supervisors": s["supervisors"], "gates": s["gates"]},
        "L4 provider plane": {**p["provider"], "gates": [g for g in p["gates"] if "region" in g["gate"]]},
        "L5 tenancy": {**p["tenancy"], "gates": [g for g in p["gates"] if "organization" in g["gate"]]},
        "L6 unmanaged VM lists": {"lists": read_unmanaged(c, vcs, L)},
    }
    text = json.dumps(rec, indent=2, sort_keys=False)
    text = UUID.sub("{{id}}", text)
    for real in sorted(L.raw(), key=len, reverse=True):
        if real and real in text:
            raise SystemExit(f"refusing to write the record: an estate name survived scrubbing ({len(real)} chars)")

    print(f"capacity ladder, read {rec['captured']}\n")
    failed = 0
    for layer, body in rec["layers"].items():
        print(layer)
        for g in body.get("gates", []):
            failed += g["status"] != "PASS"
            print(f"  [{g['status']}] {g['gate']}: {g['detail']}")
        if layer.startswith("L5") and body["residue"]:
            print("  residue: " + ", ".join(body["residue"]))
        if layer.startswith("L6"):
            for x in body["lists"]:
                named = sum(x["platformByName"].values())
                print(f"  {x['vcenter']}: {x['records']} unmanaged records, {named} of them the platform's own machines by name; "
                      f"fields per record: {', '.join(x['fieldsPerRecord'])}")
        print()
    out_dir = os.environ.get("OUT_DIR", ".")
    with open(os.path.join(out_dir, "ladder.json"), "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(f"wrote {os.path.join(out_dir, 'ladder.json')}; {failed} gate(s) not passing")
    return 2 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
