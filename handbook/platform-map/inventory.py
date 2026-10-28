#!/usr/bin/env python3
"""inventory.py - your own VCF estate placed on the platform map, with the release each component runs, read-only.

The platform-map chapter draws one estate. This reads yours from the services that hold the answers, so the picture
you hold is your own:

  1  every SDDC Manager you name (one per VCF instance): its own version, and each domain's type and status, its
     clusters and hosts with the ESX version they run, and the vCenter and NSX manager it brings with theirs
     (GET /v1/sddc-managers, /v1/domains, /v1/clusters, /v1/hosts, /v1/vcenters, /v1/nsxt-clusters)
  2  every vCenter those SDDC Managers list, signed in as the same user: its Supervisors and the version each runs,
     its vSphere zones and the clusters each holds, the Supervisor services installed, and how many of its
     namespaces are the platform's own (GET /api/vcenter/namespace-management/supervisors/summaries,
     .../namespace-management/software/clusters, /api/vcenter/consumption-domains/zones,
     .../zones/cluster/{zone}/associations, .../supervisors/{id}/supervisor-services, /api/vcenter/namespaces/instances);
     and what runs there as an appliance: every VM's product as its OVF names it (GET /api/vcenter/vm, then
     /sdk/vim25/{release}/VirtualMachine/{vm}/summary through the vSphere API's JSON form on the same session), counted
     per product name for the platform's vendors only, without the OVF's version, which is the deployed one
  3  the fleet: VCF Operations exchanges its session for the Fleet lifecycle service's key (GET
     /suite-api/api/integrations/services, the entry of type VCF_FLEET_LCM; POST /suite-api/api/auth/token/exchange),
     then GET /fleet-lcm/v1/components at the address that entry names: each component's type, version, how it is
     hosted (an appliance from an OVA, or a service on the VCF services runtime), its scope, size and nodes, the
     instance it belongs to, matched through its vCenter, and the runtime it runs on by group and type (a CONSUMPTION
     runtime the list carries no component for is VCF Automation's); and where VCF Operations collects (GET
     /suite-api/api/collectors, /suite-api/api/adapters): adapter instances on its cloud proxies, and on the
     analytics node's own collector
  4  optionally, the standalone VCF Operations orchestrator appliances you name (GET /vco/api/about, which needs no
     sign-in): neither SDDC Manager nor the fleet list carries one, so nothing else here would see its version
  5  the checks the chapter teaches: one management domain per instance, a vCenter and an NSX manager for every
     domain, a Supervisor only in a workload domain, one services runtime per instance, one release across every
     component read, and with --bom FILE every component against that release's bill of materials, every row of
     the bill reported read (its version compared), seen deployed (an appliance or a Supervisor service it names) or not
     read here

Read-only throughout. No token or password value is printed. With --record FILE it also writes what it read, with
every host name, identifier and object name left out, which is the shape of the record the chapter renders.

Env:   SDDC_HOSTS (comma-separated, one SDDC Manager per instance), SDDC_USER, SDDC_PASSWORD
       OPS_HOST, OPS_API_TOKEN_FILE (a file of mode 0600 holding the api-token; or OPS_API_TOKEN, the value),
       OPS_BROKER_HOST and OPS_REALM optional, for the fleet; omit them to skip it
       VCFO_HOSTS (comma-separated, optional): standalone VCF Operations orchestrator appliances
       TLS_VERIFY=false on a self-signed lab CA
Flags: --record FILE    write the record
       --bom FILE       compare every component with a bill of materials and account for every row of it
                        (bom-9.1.1.json ships beside this script: all 56 rows of the 9.1.1 bill)
       --no-vcenter     skip step 2
Exit:  0 every read answered and every check held · 1 a check differs · 2 a read failed
"""

import base64
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone

GRANT = "urn:custom:vcf:params:oauth:grant-type:api-token"
DOMAIN_ADAPTERS = ("VMWARE", "NSXTAdapter", "VirtualAndPhysicalSANAdapter")   # vCenter, NSX and vSAN collection
# An appliance names its product and vendor in its OVF (summary.config.product). Only these vendors' products reach the
# output: the platform's own appliances are its vocabulary, another vendor's product is the estate's choice and stays out.
VENDORS = re.compile(r"\b(vmware|broadcom|avi networks)\b", re.I)


def ctx():
    verify = os.environ.get("TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")
    return ssl.create_default_context() if verify else ssl._create_unverified_context()


def secret(name):
    """A secret from NAME_FILE (a file, mode 0600, its value stripped) or else NAME itself; None when neither is set.
    The file keeps a tier-0 token out of the shell's history and the process list. A file open to group or other is
    refused before it is read; the refusal names the variable and the fix, never the file's content."""
    path = os.environ.get(f"{name}_FILE")
    if path:
        with open(path, encoding="utf-8") as f:
            mode = os.fstat(f.fileno()).st_mode & 0o777
            # Windows makes the mode from the read-only flag alone, so it has no group or other bits to judge.
            if mode & 0o077 and os.name != "nt":
                raise PermissionError(f"{name}_FILE names a file of mode {mode:04o}, open to group or other: "
                                      f'run chmod 600 "${name}_FILE" and try again (the file was not read)')
            return f.read().strip()
    return os.environ.get(name) or None


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
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        return type(e).__name__, None


def need(status, body, what):
    if status not in (200, 201) or body is None:
        print(f"\nFAILED: {what} answered {status}; nothing below it was read")
        sys.exit(2)
    return body


def listed(body, key):
    """A vCenter list endpoint answers a bare array on some paths and wraps it under one key on others."""
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        return body.get(key) or []
    return []


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


# ---------------------------------------------------------------- versions
def release(v):
    """9.1.1 from 9.1.1.0.25713928, 9.1.1.0100.25761871, or a Supervisor's v1.34.9+vmware.1-vsc9.1.1.0-25712839."""
    m = re.search(r"vsc(\d+\.\d+\.\d+)", str(v or "")) or re.match(r"(\d+\.\d+\.\d+)", str(v or ""))
    return m.group(1) if m else None


def patch(v):
    m = re.match(r"\d+\.\d+\.\d+\.(\d+)", str(v or ""))
    return m.group(1) if m else None


def build(v):
    m = re.search(r"[.-](\d{6,})$", str(v or ""))
    return m.group(1) if m else None


# ---------------------------------------------------------------- step 1: SDDC Manager
def read_instance(host, user, password):
    st, tok = call("POST", f"https://{host}/v1/tokens", {"Content-Type": "application/json", "Accept": "application/json"},
                   body={"username": user, "password": password})
    bearer = need(st, tok, f"the token request at {host}").get("accessToken")
    if not bearer:
        print(f"\nFAILED: {host} answered the token request without an accessToken"); sys.exit(2)
    managers = elements(host, "/v1/sddc-managers", bearer)
    domains = elements(host, "/v1/domains", bearer)
    clusters = elements(host, "/v1/clusters", bearer)
    hosts = elements(host, "/v1/hosts", bearer)
    vcenters = elements(host, "/v1/vcenters", bearer)
    nsx = elements(host, "/v1/nsxt-clusters", bearer)
    rows = []
    for d in domains:
        did = d.get("id")
        vcs = [v for v in vcenters if (v.get("domain") or {}).get("id") == did]
        nx = [n for n in nsx if did in [x.get("id") for x in (n.get("domains") or [])]]
        rows.append({
            "type": d.get("type"), "status": d.get("status"),
            "clusters": sorted((sum(1 for h in hosts if (h.get("cluster") or {}).get("id") == c.get("id")))
                               for c in clusters if (c.get("domain") or {}).get("id") == did),
            "hosts": sum(1 for h in hosts if (h.get("domain") or {}).get("id") == did),
            "esx": dict(Counter(str(h.get("esxiVersion")) for h in hosts if (h.get("domain") or {}).get("id") == did)),
            "vcenters": len(vcs), "vcenter_version": vcs[0].get("version") if vcs else None,
            "nsx": len(nx), "nsx_version": nx[0].get("version") if nx else None,
            "_vcenter_fqdn": vcs[0].get("fqdn") if vcs else None,
        })
    names = {str(x) for d in (managers, domains, clusters, hosts, vcenters, nsx) for o in d
             for x in (o.get("id"), o.get("name"), o.get("fqdn"), o.get("vipFqdn"), o.get("ipAddress")) if x}
    names.add(host)
    return {"sddc_manager": managers[0].get("version") if managers else None, "domains": rows,
            "vcenter_fqdns": {v.get("fqdn") for v in vcenters}}, names


# ---------------------------------------------------------------- step 2: vCenter
def read_vcenter(fqdn, user, password):
    """The Supervisor rungs of one vCenter: counts, versions and product names only."""
    auth = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()
    st, sid = call("POST", f"https://{fqdn}/api/session", {"Authorization": auth})
    if st not in (200, 201) or not isinstance(sid, str):
        return {"read": f"refused ({st})"}, set()
    h = {"vmware-api-session-id": sid, "Accept": "application/json"}
    names = set()
    st, sups = call("GET", f"https://{fqdn}/api/vcenter/namespace-management/supervisors/summaries", h)
    sup_items = listed(sups, "items")
    st, sw = call("GET", f"https://{fqdn}/api/vcenter/namespace-management/software/clusters", h)
    versions = [c.get("current_version") for c in listed(sw, "items")]
    st, reg = call("GET", f"https://{fqdn}/api/vcenter/namespace-management/supervisor-services", h)
    display = {s.get("supervisor_service"): s.get("display_name") for s in listed(reg, "items")}   # the platform's own names
    supervisors, services = [], {}
    for i, s in enumerate(sup_items):
        info = s.get("info") or {}
        names |= {str(x) for x in (s.get("supervisor"), info.get("name"), info.get("APIEndpoint")) if x}
        supervisors.append({"status": info.get("kubernetes_status"), "config": info.get("config_status"),
                            # software/clusters answers per cluster, not per Supervisor: pair them only when the counts agree
                            "version": versions[i] if len(versions) == len(sup_items) else None})
        st, raw = call("GET", f"https://{fqdn}/api/vcenter/namespace-management/supervisors/{s.get('supervisor')}/supervisor-services", h)
        for svc in listed(raw, "supervisor_services"):
            sid = svc.get("supervisor_service")
            services[sid] = {"name": display.get(sid) or sid, "version": svc.get("current_version")}
    st, zs = call("GET", f"https://{fqdn}/api/vcenter/consumption-domains/zones", h)
    zones = []
    for z in listed(zs, "items"):
        names.add(str(z.get("zone")))
        st, assoc = call("GET", f"https://{fqdn}/api/vcenter/consumption-domains/zones/cluster/{urllib.parse.quote(str(z.get('zone')))}/associations", h)
        members = assoc if isinstance(assoc, list) else []
        names |= {str(c) for c in members}
        zones.append(len(members))
    st, ns = call("GET", f"https://{fqdn}/api/vcenter/namespaces/instances", h)
    nsl = listed(ns, "items")
    names |= {str(n.get("namespace")) for n in nsl if n.get("namespace")}
    appliances = read_appliances(fqdn, h)
    call("DELETE", f"https://{fqdn}/api/session", h)   # ends this read's own session, nothing else
    return {"read": "ok", "supervisors": supervisors, "zones": sorted(zones), "services": dict(sorted(services.items())),
            "namespaces": {"total": len(nsl), "system": sum(1 for n in nsl if str(n.get("namespace", "")).startswith("svc-"))},
            "appliances": appliances}, names


def vim_release(fqdn):
    """The vSphere API release this vCenter serves (/sdk/vimServiceVersions.xml, no sign-in), which its JSON form is keyed by."""
    req = urllib.request.Request(f"https://{fqdn}/sdk/vimServiceVersions.xml")
    try:
        with urllib.request.urlopen(req, context=ctx(), timeout=60) as r:
            raw = r.read()
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return None
    m = re.search(rb"<name>urn:vim25</name>\s*<version>([^<]+)</version>", raw)
    return m.group(1).decode() if m else None


def read_appliances(fqdn, h):
    """What runs in this vCenter as an appliance: each VM's product as its OVF names it (summary.config.product, read
    through the vSphere API's JSON form on this read's REST session), counted per product name, the platform's vendors
    only. The OVF's version is the one the appliance was deployed at, not the one it runs, so it is not kept; a VM with
    no product, or another vendor's, is counted and not named."""
    st, vms = call("GET", f"https://{fqdn}/api/vcenter/vm", h)
    rel = vim_release(fqdn)
    if st != 200 or not isinstance(vms, list) or not rel:
        return {"read": f"refused (VM list {st}, vSphere API release {rel or 'unread'})"}
    products, other, failed = Counter(), 0, 0
    for vm in vms:
        s, summ = call("GET", f"https://{fqdn}/sdk/vim25/{rel}/VirtualMachine/{urllib.parse.quote(str(vm.get('vm')))}/summary", h)
        if s != 200 or not isinstance(summ, dict):
            failed += 1
            continue
        p = (summ.get("config") or {}).get("product") or {}
        name = str(p.get("name") or "").strip()
        if name and VENDORS.search(str(p.get("vendor") or "")):
            products[name] += 1
        else:
            other += 1
    return {"read": "ok" if not failed else f"partial ({failed} of {len(vms)} unread)", "vms": len(vms),
            "products": dict(sorted(products.items())), "other": other}


# ---------------------------------------------------------------- step 3: the fleet and collection
def ops_bearer():
    host = os.environ["OPS_HOST"]
    broker, realm = os.environ.get("OPS_BROKER_HOST", host), os.environ.get("OPS_REALM", "CUSTOMER")
    st, b = call("POST", f"https://{broker}/acs/t/{realm}/token", {"Content-Type": "application/x-www-form-urlencoded"},
                 form={"grant_type": GRANT, "api_token": secret("OPS_API_TOKEN")})
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
        rows.append({"type": c.get("componentType"), "what": c.get("componentTypeDescription"), "version": c.get("version"),
                     "deployment": c.get("deploymentType"), "scope": c.get("scope"), "size": c.get("size"),
                     "nodes": dict(Counter(n.get("nodeType") for n in c.get("nodes") or [])),
                     "node_sizes": dict(Counter(n.get("size") for n in c.get("nodes") or [])), "instance": where})
    # which components answer on one shared name: a group number, in order of first appearance, never the name itself
    order = list(dict.fromkeys(c.get("fqdn") for c in comps))
    for row, c in zip(rows, comps):
        row["name_group"] = order.index(c.get("fqdn")) + 1
        row["shares_name"] = sum(1 for x in comps if x.get("fqdn") == c.get("fqdn")) > 1
    place_runtimes(rows, comps)
    names = {str(x) for c in comps for x in (c.get("id"), c.get("fqdn"), c.get("sddcLcmId"), (c.get("vcenter") or {}).get("fqdn"),
                                            (c.get("vcenter") or {}).get("id"), (c.get("vspCluster") or {}).get("id")
                                            if isinstance(c.get("vspCluster"), dict) else c.get("vspCluster")) if x}
    names |= {str(x) for c in comps for n in c.get("nodes") or [] for x in (n.get("fqdn"), n.get("name"), n.get("ipAddress"), n.get("id")) if x}
    names |= {entry.get("address", ""), host}
    # where VCF Operations collects: the analytics node's own collector reads INTERNAL, every other type is remote
    st, col = call("GET", f"https://{host}/suite-api/api/collectors", h)
    st2, ad = call("GET", f"https://{host}/suite-api/api/adapters", h)
    collection = None
    if st == 200 and st2 == 200:
        ctype = {str(c.get("id")): c.get("type") for c in (col or {}).get("collector") or []}
        names |= {str(x) for c in (col or {}).get("collector") or [] for x in (c.get("name"), c.get("hostName"), c.get("uuId")) if x}
        inst = (ad or {}).get("adapterInstancesInfoDto") or []
        names |= {str(x) for a in inst for x in ((a.get("resourceKey") or {}).get("name"), a.get("id")) if x}
        def kind(a):
            return (a.get("resourceKey") or {}).get("adapterKindKey")
        own = [a for a in inst if ctype.get(str(a.get("collectorId"))) == "INTERNAL"]
        remote = [a for a in inst if ctype.get(str(a.get("collectorId"))) not in (None, "INTERNAL")]
        collection = {
            "remote_collectors": dict(Counter(t for t in ctype.values() if t != "INTERNAL")),
            "on_remote": len(remote), "on_analytics_node": len(own), "unassigned": len(inst) - len(own) - len(remote),
            "domain_adapters_remote": sum(1 for a in remote if kind(a) in DOMAIN_ADAPTERS),
            "domain_adapters_on_analytics_node": sum(1 for a in own if kind(a) in DOMAIN_ADAPTERS),
            # custom Management Pack Builder kinds (mpb_*) are named by whoever built them, so they are counted, not named
            "kinds_on_analytics_node": sorted({kind(a) for a in own if kind(a) and not kind(a).startswith("mpb_")}),
        }
    return rows, collection, names


def place_runtimes(rows, comps):
    """Which services runtime each service runs on: a group number and the cluster's type (MANAGEMENT, CONSUMPTION), never
    its identifier. A runtime component (type VSP) is its own group, so a group no VSP row owns is a runtime the list
    does not carry as a component: on 9.1.1, VCF Automation's."""
    def runtime_id(c):
        v = c.get("vspCluster")
        return str(v.get("id")) if isinstance(v, dict) else None
    rts = list(dict.fromkeys([str(c.get("id")) for c in comps if c.get("componentType") == "VSP"] + [x for x in map(runtime_id, comps) if x]))
    for row, c in zip(rows, comps):
        if c.get("componentType") == "VSP":
            row["runtime"] = {"group": rts.index(str(c.get("id"))) + 1, "is_runtime": True,
                              "type": (c.get("vspCluster") or {}).get("type") if isinstance(c.get("vspCluster"), dict) else None}
        elif runtime_id(c):
            row["runtime"] = {"group": rts.index(runtime_id(c)) + 1, "is_runtime": False, "type": c["vspCluster"].get("type")}
    listed_rt = {r["runtime"]["group"] for r in rows if (r.get("runtime") or {}).get("is_runtime")}
    for r in rows:
        if r.get("runtime"):
            r["runtime"]["listed"] = r["runtime"]["group"] in listed_rt


def read_standalone(hosts):
    rows, names = [], set()
    for host in hosts:
        st, about = call("GET", f"https://{host}/vco/api/about", {"Accept": "application/json"})
        names.add(host)
        rows.append({"what": "VCF Operations orchestrator", "version": (about or {}).get("version") if st == 200 else None,
                     "read": "ok" if st == 200 else f"failed ({st})"})
    return rows, names


# ---------------------------------------------------------------- the version rows every check reads
def version_rows(instances, fleet, standalone):
    """(what, version, where) for every component whose version is on the VCF release line."""
    rows = []
    for i, inst in enumerate(instances, start=1):
        rows.append(("SDDC Manager", inst["sddc_manager"], f"instance {i}"))
        for d in inst["domains"]:
            where = f"instance {i} {d['type']}"
            rows += [("vCenter", d["vcenter_version"], where), ("NSX", d["nsx_version"], where)]
            rows += [("ESX", v, where) for v in d["esx"]]
            for s in (d.get("vc") or {}).get("supervisors") or []:
                rows.append(("Supervisor", s["version"], where))
    rows += [(c["what"], c["version"], f"instance {c['instance'] or '?'}") for c in fleet]
    rows += [(s["what"], s["version"], "standalone") for s in standalone if s["version"]]
    return [r for r in rows if r[1]]


def bom_row_for(bom, what):
    """The bill's row a version reading compares with: the row whose read_as names what this script prints."""
    return next((r for r in bom["rows"] if what in (r.get("read_as") or [])), None)


def compare_bom(rows, bom):
    """Each version row against the bill of materials: at its build, a later patch of the release, or behind it."""
    out = []
    for what, ver, where in rows:
        b = bom_row_for(bom, what)
        if not b:
            continue
        if what == "Supervisor":   # its version string carries the vCenter build, so only the release compares
            status = "release" if release(ver) == bom["release"] else "behind"
        elif build(ver) == b["build"]:
            status = "build"
        elif release(ver) == bom["release"] and int(patch(ver) or 0) > int(patch(b["version"]) or 0):
            status = "later patch"
        elif tuple(map(int, (release(ver) or "0.0.0").split("."))) < tuple(map(int, bom["release"].split("."))):
            status = "behind"
        else:
            status = "differs"
        out.append({"what": what, "where": where, "version": ver, "bom": f"{b['version']}.{b['build']}", "status": status})
    return out


def bom_coverage(bom, bom_rows, instances):
    """Every row of the bill, in three states: read (a version above compared with it), seen (deployed, its running
    version not compared here) or unread (nothing here read it, so nothing here says whether it is
    deployed). Seen is an appliance it names in a vCenter, or a Supervisor service it names installed. The bill is the
    release's own list, so a row this script cannot read is reported, never dropped."""
    read_names = {r["what"] for r in bom_rows}
    seen, services = Counter(), set()
    for inst in instances:
        for d in inst["domains"]:
            for name, n in (((d.get("vc") or {}).get("appliances") or {}).get("products") or {}).items():
                seen[name] += n
            services |= set(((d.get("vc") or {}).get("services") or {}))
    out = []
    for r in bom["rows"]:
        if read_names & set(r.get("read_as") or []):
            state = "read"
        elif any(seen.get(a) for a in r.get("appliance") or []) or services & set(r.get("service") or []):
            state = "seen"
        else:
            state = "unread"
        out.append({"table": r["table"], "bom_name": r["bom_name"], "state": state})
    return out


def main():
    record = sys.argv[sys.argv.index("--record") + 1] if "--record" in sys.argv else None
    bom_file = sys.argv[sys.argv.index("--bom") + 1] if "--bom" in sys.argv else None
    sddc = [h.strip() for h in os.environ.get("SDDC_HOSTS", "").split(",") if h.strip()]
    if not sddc:
        print("set SDDC_HOSTS to one SDDC Manager per instance"); sys.exit(2)
    user, password = os.environ["SDDC_USER"], os.environ["SDDC_PASSWORD"]
    try:
        ops_token = secret("OPS_API_TOKEN") if os.environ.get("OPS_HOST") else None
    except OSError as e:   # a token file that is missing, unreadable or open to group or other
        print(f"FAILED: {e}"); sys.exit(2)
    print("inventory.py: your estate on the platform map, read-only\n")
    instances, seen = [], set()
    for host in sddc:
        inst, names = read_instance(host, user, password)
        instances.append(inst); seen |= names
    if "--no-vcenter" not in sys.argv:
        for inst in instances:
            for d in inst["domains"]:
                if d["_vcenter_fqdn"]:
                    d["vc"], names = read_vcenter(d["_vcenter_fqdn"], user, password)
                    seen |= names
    for i, (host, inst) in enumerate(zip(sddc, instances), start=1):
        print(f"instance {i}  SDDC Manager {inst['sddc_manager']}  ({host})")
        for d in inst["domains"]:
            esx = ", ".join(f"{n} on ESX {v}" for v, n in sorted(d["esx"].items()))
            print(f"  domain  {str(d['type']):<11} {str(d['status']):<8} clusters {len(d['clusters'])} (hosts per cluster: "
                  f"{', '.join(map(str, d['clusters'])) or '-'})  hosts {esx or 0}")
            print(f"          vCenter {d['vcenters']} ({d['vcenter_version']})  NSX {d['nsx']} ({d['nsx_version']})")
            vc = d.get("vc")
            if not vc:
                continue
            if vc["read"] != "ok":
                print(f"          vCenter read: {vc['read']}")
                continue
            ap = vc.get("appliances") or {}
            if ap.get("products") is not None:
                print(f"          appliances  {ap['vms']} VMs; by their OVF product (version not kept: it is the deployed one): "
                      + ("; ".join(f"{n} {k}" for k, n in ap["products"].items()) or "none named")
                      + f"; {ap['other']} with no product or another vendor's" + ("" if ap["read"] == "ok" else f" ({ap['read']})"))
            else:
                print(f"          appliances  {ap.get('read', 'not read')}")
            if not vc["supervisors"]:
                print("          Supervisor: none")
                continue
            for s in vc["supervisors"]:
                print(f"          Supervisor {s['status']}, {s['version']}; {len(vc['zones'])} vSphere zone(s), clusters per zone: "
                      f"{', '.join(map(str, vc['zones'])) or '-'}")
            print(f"          Supervisor services {len(vc['services'])}: " + ", ".join(f"{v['name']} {v['version']}" for v in vc["services"].values()))
            print(f"          namespaces {vc['namespaces']['total']}, {vc['namespaces']['system']} of them the platform's own (svc-)")
    fleet, collection = [], None
    if ops_token:
        fleet, collection, names = read_fleet(instances); seen |= names
        print("\nfleet  (the Fleet lifecycle service's component list)")
        print(f"  {'component':<20} {'version':<21} {'hosted as':<9} {'scope':<9} {'size':<12} {'nodes':<36} {'instance':<9} runtime")
        for c in sorted(fleet, key=lambda c: (c["instance"] or 0, c["scope"] or "", c["type"] or "")):
            nodes = ", ".join(f"{n} {k}" for k, n in sorted(c["nodes"].items())) or "-"
            rt = c.get("runtime") or {}
            rtl = (f"{'is ' if rt.get('is_runtime') else ''}#{rt['group']} {rt.get('type') or '?'}" + ("" if rt.get("listed", True) else ", not listed")) if rt else "-"
            print(f"  {str(c['type']):<20} {str(c['version']):<21} {str(c['deployment']):<9} {str(c['scope']):<9} {str(c['size']):<12} {nodes:<36} {str(c['instance'] or '?'):<9} {rtl}")
        per = Counter(c["instance"] for c in fleet); scope = Counter(c["scope"] for c in fleet); dep = Counter(c["deployment"] for c in fleet)
        print(f"  {len(fleet)} components: " + ", ".join(f"{per[i]} on instance {i}" for i in sorted(k for k in per if k)) +
              f"; {scope.get('FLEET', 0)} at fleet scope, {scope.get('INSTANCE', 0)} at instance scope; "
              f"{dep.get('OVA', 0)} appliances from an OVA, {dep.get('VSP', 0)} on the services runtime")
        unlisted = sorted({(c["runtime"]["group"], c["runtime"].get("type")) for c in fleet if c.get("runtime") and not c["runtime"]["listed"]})
        for g, t in unlisted:
            on = sorted({c["what"] for c in fleet if (c.get("runtime") or {}).get("group") == g})
            print(f"  services runtime #{g} ({t}) carries {', '.join(on)}; the list carries no component for that runtime itself")
        if collection:
            rc = ", ".join(f"{n} {t}" for t, n in sorted(collection["remote_collectors"].items())) or "none"
            print(f"  where VCF Operations collects: {collection['on_remote']} adapter instances on its remote collectors ({rc}), "
                  f"{collection['on_analytics_node']} on the analytics node's own collector; vCenter, NSX and vSAN adapters: "
                  f"{collection['domain_adapters_remote']} remote, {collection['domain_adapters_on_analytics_node']} on the analytics node")
    else:
        print("\nfleet  skipped: set OPS_HOST and OPS_API_TOKEN_FILE to read it")
    standalone = []
    vcfo = [h.strip() for h in os.environ.get("VCFO_HOSTS", "").split(",") if h.strip()]
    if vcfo:
        standalone, names = read_standalone(vcfo); seen |= names
        print("\nstandalone  (named in VCFO_HOSTS; neither SDDC Manager nor the fleet list carries these)")
        for i, s in enumerate(standalone, start=1):
            print(f"  {s['what']} {i}: {s['version'] or s['read']}")
    # ---- releases, and the bill of materials
    rows = version_rows(instances, fleet, standalone)
    rel = Counter(release(v) for _, v, _ in rows)
    print("\nreleases  (every version on the VCF release line read above)")
    for r, n in sorted(rel.items(), key=lambda x: str(x[0])):
        odd = sorted({f"{w} {v}" for w, v, _ in rows if release(v) == r}) if len(rel) > 1 and n <= 3 else []
        print(f"  {r}: {n} component reading(s)" + (f": {'; '.join(odd)}" if odd else ""))
    bom_rows, coverage = [], []
    if bom_file:
        with open(bom_file, encoding="utf-8") as f:
            bom = json.load(f)
        bom_rows = compare_bom(rows, bom)
        coverage = bom_coverage(bom, bom_rows, instances)
        state = Counter(c["state"] for c in coverage)
        print(f"\nbill of materials {bom['release']}  ({os.path.basename(bom_file)}, read {bom['read']}): {len(coverage)} rows, "
              f"{state.get('read', 0)} read here, {state.get('seen', 0)} seen deployed (an appliance or a Supervisor service), {state.get('unread', 0)} not read here")
        for status in ("build", "release", "later patch", "behind", "differs"):
            hit = [r for r in bom_rows if r["status"] == status]
            if hit:
                label = {"build": "at its build", "release": "on its release", "later patch": "a later patch",
                         "behind": "behind", "differs": "differs"}[status]
                shown = sorted({f"{r['what']} {r['version']}" + (f" (the bill lists {r['bom']})" if status in ("behind", "differs") else "")
                                for r in hit})
                count = f"{len(shown)}" + (f" ({len(hit)} readings)" if len(hit) != len(shown) else "")
                print(f"  {label:<14} {count}: " + "; ".join(shown))
        for st_, label in (("seen", "seen, version unread"), ("unread", "not read here")):
            names = [f"{c['bom_name']}" for c in coverage if c["state"] == st_]
            if names:
                print(f"  {label:<14} {len(names)}: " + "; ".join(names))
    # ---- the checks a map makes possible
    checks = []
    for i, inst in enumerate(instances, start=1):
        mgmt = [d for d in inst["domains"] if d["type"] == "MANAGEMENT"]
        work = [d for d in inst["domains"] if d["type"] != "MANAGEMENT"]
        checks.append((len(mgmt) == 1, f"instance {i} has one management domain" + ("" if len(mgmt) == 1 else f": it has {len(mgmt)}")))
        checks.append((True, f"instance {i} has {len(work)} workload domain(s)" + (": management only" if not work else "")))
        for d in inst["domains"]:
            checks.append((d["vcenters"] == 1 and d["nsx"] >= 1, f"instance {i}, {d['type']} domain: its own vCenter ({d['vcenters']}) and an NSX manager ({d['nsx']})"))
            vc = d.get("vc") or {}
            if vc.get("read") == "ok" and d["type"] == "MANAGEMENT":
                checks.append((not vc["supervisors"], f"instance {i}, MANAGEMENT domain: no Supervisor ({len(vc['supervisors'])})"))
    if fleet:
        unmatched = [c["type"] for c in fleet if not c["instance"]]
        checks.append((not unmatched, "every fleet component matched to an instance" + (f"; not matched: {unmatched}" if unmatched else "")))
        rt = [c for c in fleet if c["type"] == "VSP"]
        checks.append((len(rt) == len(instances), f"one services runtime per instance ({len(rt)} for {len(instances)})"))
    checks.append((len(rel) == 1, "one release across every component read" + (f": {next(iter(rel))}" if len(rel) == 1 else
                                                                               f": {len(rel)} releases ({', '.join(sorted(map(str, rel)))})")))
    if bom_rows:
        off = [r for r in bom_rows if r["status"] in ("behind", "differs")]
        checks.append((not off, "no component behind the bill of materials" + (f": {len(off)} ({', '.join(sorted({r['what'] for r in off}))})" if off else "")))
    print("\nchecks")
    for ok, what in checks:
        print(f"  {'ok     ' if ok else 'DIFFERS'} {what}")
    if record:
        out = {"captured": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "instances": [{"sddc_manager": inst["sddc_manager"],
                              "domains": [{k: v for k, v in d.items() if not k.startswith("_")} for d in inst["domains"]]}
                             for inst in instances],
               "fleet": fleet, "collection": collection, "standalone": standalone,
               "releases": {str(k): v for k, v in rel.items()},
               "bom": {"release": bom["release"], "read": bom["read"], "rows": bom_rows, "coverage": coverage} if bom_file else None,
               "checks": [{"ok": ok, "check": what} for ok, what in checks]}
        text = json.dumps(out, indent=1)
        # the product's own vocabulary is what the record is for; an object an operator happened to name after it is not a leak
        reserved = {str(x) for c in fleet for x in (c["type"], c["what"], c["deployment"], c["scope"], c["size"], *c["nodes"], *c["node_sizes"])}
        reserved |= set((collection or {}).get("kinds_on_analytics_node") or []) | set((collection or {}).get("remote_collectors") or {})
        reserved |= {str(x) for inst in instances for d in inst["domains"] for x in (d["type"], d["status"], *((d.get("vc") or {}).get("services") or {}),
                                                                                *(s["name"] for s in ((d.get("vc") or {}).get("services") or {}).values()))}
        reserved |= {s["what"] for s in standalone} | {"INTERNAL"}
        reserved |= {str(p) for inst in instances for d in inst["domains"] for p in (((d.get("vc") or {}).get("appliances") or {}).get("products") or {})}
        reserved |= {c["bom_name"] for c in coverage}
        leaked = sorted(n for n in seen - reserved if n and len(n) > 3 and re.search(r"(?<![\w.-])" + re.escape(n) + r"(?![\w-])", text))
        assert not leaked, f"an estate name reached the record ({len(leaked)}); nothing was written"
        with open(record, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print(f"\nwrote {record}: versions, counts and types only, no host name, identifier or object name")
    sys.exit(0 if all(ok for ok, _ in checks) else 1)


if __name__ == "__main__":
    main()
