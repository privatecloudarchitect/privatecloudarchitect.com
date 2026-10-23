#!/usr/bin/env python3
"""maximums.py: how close is your VCF 9.1 estate to the configuration maximums that bind it first?

Broadcom publishes the maximums in its Configuration Maximums tool, one CSV export per product. This script reads the
exports you downloaded, picks the caps that bound a private cloud's construct ladder (fleet, instance, workload domain,
vCenter, Supervisor, NSX, VCF Automation) for the sizes you deployed, and, for each plane whose settings you give it, reads
the estate's own counts and prints how much of each cap is used. Read-only, always: every call is a GET, apart from opening
and closing a vCenter session and exchanging the Automation provider token.

  python3 maximums.py --exports DIR [--fleet simple] [--nsx medium-singleton] [--edge medium] [--vcfa medium] [--warn 70]

  --exports  the folder of CSV exports, one per product (the file name may be anything; the product is read from it)
  --fleet    the VCF Installer deployment model your fleet's management components were sized for: simple|medium-ha|large-ha
  --nsx      your NSX Manager size and mode, as the export names it: medium|large|extra-large and singleton|clustered
  --edge     your Edge node size: medium|large|extra-large|bare-metal
  --vcfa     your VCF Automation profile: medium|large (the export lists no other)
  --warn     the share of a cap, in percent, at which the run exits 1 (default 70)

Each plane is read only when its settings are present (secret files of mode 0600, refused unread when open to others):
  SDDC Manager     SDDC_HOSTS=<fqdn>,<fqdn>  SDDC_TOKEN_FILES=<file>,<file>   one bearer per instance, in the same order
  vCenter          VC_HOSTS=<fqdn>,<fqdn>    VC_USER=<account>  VC_PASSWORD_FILE=<file>   or one of each per host, in order
  NSX Manager      NSX_HOSTS=<fqdn>,<fqdn>   NSX_TOKEN_FILES=<file>,<file>   a bearer per manager, in the same order
  VCF Automation   VCFA_HOST=<fqdn>          VCFA_PROVIDER_REFRESH_TOKEN_FILE=<file>   a provider API token
  TLS_VERIFY=false only on a self-signed lab CA. The record, maximums.json, carries labels in place of every host, and counts.

Exit: 0 every cap read is under --warn (caps the exports do not list for your sizes are printed, not failed) · 1 a cap at or over --warn
      2 a setting is missing or a secret file is open to group or other · 3 a read failed
      4 the record refused to write because a name survived · 5 an unknown or incomplete argument
"""

from __future__ import annotations

import base64
import csv
import glob
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

# The products the tool exports, recognized from the file's name as the tool writes it (a renamed file still works when it
# keeps the product's word). The release and the time of the download are read from the file's own last lines.
PRODUCTS = {"SDDC": "SDDC", "vCenter": "vCenter", "ESX": "ESX", "NSX": "NSX", "VCFA": "VCFA", "vSAN": "vSAN",
            "VCF-Ops": "VCF-Ops", "vIDB": "vIDB", "Ops-for-Net": "Ops-for-Net", "HCX": "HCX", "SRM": "SRM"}

# The caps this script reads against, each named by the export's own words: the product, the column the tool calls Attribute
# Header where it groups by size (NSX, Edge), the row's name, and for VCF Automation the profile it is listed under. {nsx},
# {edge} and {vcfa} are filled from the sizes you give. "count" names the estate read that answers it, or None.
CAPS = [
    # fleet and instance (SDDC Manager)
    {"id": "fleet-hosts", "layer": "fleet", "product": "SDDC", "name": "Number of Hosts in a VCF Fleet", "count": "fleet_hosts"},
    {"id": "fleet-model-hosts", "layer": "fleet", "product": "SDDC", "sub": "{fleet}", "name": "Number of Hosts", "count": "fleet_hosts"},
    {"id": "fleet-model-vms", "layer": "fleet", "product": "SDDC", "sub": "{fleet}", "name": "Number of VMs", "count": "fleet_vms"},
    {"id": "instance-hosts", "layer": "instance", "product": "SDDC", "sub": "Per VCF Instance", "name": "ESXi Hosts", "count": "instance_hosts"},
    {"id": "instance-vcenters", "layer": "instance", "product": "SDDC", "sub": "Per VCF Instance", "name": "vCenter Servers", "count": "instance_vcenters"},
    {"id": "instance-vi-domains", "layer": "instance", "product": "SDDC", "sub": "Per VCF Instance", "name": "VI Workload Domains", "count": "instance_vi_domains"},
    {"id": "domain-hosts", "layer": "workload domain", "product": "SDDC", "sub": "Per VI Workload Domain", "name": "ESXi Hosts", "count": "domain_hosts"},
    # vCenter
    {"id": "vcenter-hosts", "layer": "vCenter", "product": "vCenter", "name": "Hosts per vCenter Server", "count": "vcenter_hosts"},
    {"id": "vcenter-hosts-vlcm", "layer": "vCenter", "product": "vCenter", "name": "Hosts per vCenter Server managed by vSphere Lifecycle Manager", "count": "vcenter_hosts"},
    {"id": "vcenter-vms-on", "layer": "vCenter", "product": "vCenter", "name": "Powered-on virtual machines per vCenter Server", "count": "vcenter_vms_on"},
    {"id": "vcenter-vms", "layer": "vCenter", "product": "vCenter", "name": "Registered virtual machines per vCenter Server", "count": "vcenter_vms"},
    # Supervisor
    {"id": "vcenter-supervisor-clusters", "layer": "Supervisor", "product": "vCenter", "name": "Maximum number of ESXi clusters enabled with vSphere with Kubernetes per vCenter", "count": "vcenter_supervisors"},
    {"id": "vcenter-namespaces", "layer": "Supervisor", "product": "vCenter", "name": "Maximum number of Namespace per vCenter", "count": "vcenter_namespaces"},
    {"id": "supervisor-zones", "layer": "Supervisor", "product": "vCenter", "name": "Maximum number of vSphere Zones per Supervisor", "count": "supervisor_zones"},
    {"id": "namespace-zones", "layer": "Supervisor", "product": "vCenter", "name": "Maximum number of vSphere Zones per Supervisor namespace", "count": None},
    {"id": "supervisor-hosts", "layer": "Supervisor", "product": "vCenter", "name": "Maximum number of hosts per WCP enabled cluster", "count": None},
    {"id": "kubernetes-workers", "layer": "Supervisor", "product": "vCenter", "name": "Maximum number of worker nodes in a single vSphere Kubernetes cluster", "count": None},
    {"id": "vks-per-namespace", "layer": "Supervisor", "product": "vCenter", "name": "Maximum number of vSphere Kubernetes clusters per Supervisor namespace", "count": None},
    {"id": "vks-per-supervisor", "layer": "Supervisor", "product": "vCenter", "name": "Maximum number of vSphere Kubernetes clusters that can be created per Supervisor", "count": None},
    # NSX, by Manager size and Edge size
    {"id": "nsx-projects", "layer": "NSX", "product": "NSX", "group": "{nsx}", "name": "Projects", "count": "nsx_projects"},
    {"id": "nsx-vpcs", "layer": "NSX", "product": "NSX", "group": "{nsx}", "name": "System Wide VPCs", "count": "nsx_vpcs"},
    {"id": "nsx-subnets", "layer": "NSX", "product": "NSX", "group": "{nsx}", "name": "Subnets", "count": "nsx_subnets"},
    {"id": "nsx-subnets-per-vpc", "layer": "NSX", "product": "NSX", "group": "{nsx}", "name": "Subnets per VPC", "count": "nsx_subnets_per_vpc"},
    {"id": "nsx-transit-gateways", "layer": "NSX", "product": "NSX", "group": "{nsx}", "name": "Transit Gateways", "count": "nsx_tgws"},
    {"id": "edge-vpcs-per-tgw", "layer": "NSX", "product": "NSX", "group": "{edge}", "name": "VPC per Transit Gateway", "count": None},
    # VCF Automation, by profile
    {"id": "vcfa-orgs", "layer": "VCF Automation", "product": "VCFA", "cat": "{vcfa}", "name": "Organizations", "count": "vcfa_orgs"},
    {"id": "vcfa-projects", "layer": "VCF Automation", "product": "VCFA", "cat": "{vcfa}", "name": "Projects across Organizations", "count": None},
    {"id": "vcfa-namespaces", "layer": "VCF Automation", "product": "VCFA", "cat": "{vcfa}", "name": "Namespaces Across Organizations", "count": "vcfa_namespaces"},
    {"id": "vcfa-vpcs", "layer": "VCF Automation", "product": "VCFA", "cat": "{vcfa}", "name": "Virtual Private Clouds", "count": "vcfa_vpcs"},
    {"id": "vcfa-region-quotas", "layer": "VCF Automation", "product": "VCFA", "cat": "{vcfa}", "name": "Region quota", "count": "vcfa_quotas"},
    {"id": "vcfa-regions-per-org", "layer": "VCF Automation", "product": "VCFA", "cat": "{vcfa}", "name": "Regions per Organization", "count": "vcfa_regions_per_org"},
    {"id": "vcfa-users-per-org", "layer": "VCF Automation", "product": "VCFA", "cat": "{vcfa}", "name": "Users (max Users per Organization)", "count": None},
]
SIZES = {"nsx": {"medium-singleton": "Medium NSX Manager - Singleton", "medium-clustered": "Medium NSX Manager - Clustered",
                 "large-singleton": "Large NSX Manager - Singleton", "large-clustered": "Large NSX Manager - Clustered",
                 "extra-large-singleton": "Extra Large NSX Manager - Singleton", "extra-large-clustered": "Extra Large NSX Manager - Clustered"},
         "edge": {"medium": "Medium Edge Node", "large": "Large Edge Node", "extra-large": "Extra Large Edge Node", "bare-metal": "Bare-Metal Edge Node"},
         "vcfa": {"medium": "Medium Profile", "large": "Large Profile"},
         "fleet": {"simple": "VCF Installer Simple Deployment", "medium-ha": "VCF Installer Medium HA Deployment",
                   "large-ha": "VCF Installer Large HA Deployment"}}


class Failed(Exception):
    """A read the answer depends on failed; exit 3 with the read named."""


def ctx():
    verify = os.environ.get("TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")
    return ssl.create_default_context() if verify else ssl._create_unverified_context()


def read_secret(path, var):
    """The value of a secret from a file of mode 0600; a file open to group or other is refused unread."""
    with open(path, encoding="utf-8") as f:
        mode = os.fstat(f.fileno()).st_mode & 0o777
        if mode & 0o077 and os.name != "nt":
            raise PermissionError(f"{var} names a file of mode {mode:04o}, open to group or other: run chmod 600 on it and try again (the file was not read)")
        return f.read().strip()


def secrets_of(var):
    return [read_secret(p.strip(), var) for p in os.environ.get(var, "").split(",") if p.strip()]


def http(method, url, headers, body=None, form=None):
    data = urllib.parse.urlencode(form).encode() if form is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, context=ctx(), timeout=120) as r:
            raw = r.read()
            try:
                return r.status, (json.loads(raw) if raw else None)
            except ValueError:
                return r.status, raw.decode(errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, None
    except (urllib.error.URLError, OSError) as e:
        return None, type(e).__name__


class Labels:
    """Stable placeholders: the first host met is host-1. A name is replaced only as a whole word and only in a value, never
    in a key; the product's own words are never names (CHAPTER-DOCTRINE section 5)."""

    RESERVED = {"admin", "user", "default", "system", "all", "none", "Medium", "Large", "Small", "Singleton", "Clustered"}
    EDGE = "A-Za-z0-9_-"

    def __init__(self):
        self.maps = {}

    def get(self, family, name):
        if not name or str(name) in self.RESERVED:
            return name
        m = self.maps.setdefault(family, {})
        if name not in m:
            m[name] = f"{family}-{len(m) + 1}"
        return m[name]

    def _rx(self):
        known = {r: lab for m in self.maps.values() for r, lab in m.items()}
        if not known:
            return None, known
        alt = "|".join(re.escape(r) for r in sorted(known, key=len, reverse=True))
        return re.compile(rf"(?<![{self.EDGE}])({alt})(?![{self.EDGE}])"), known

    def scrub(self, x):
        if isinstance(x, dict):
            return {k: self.scrub(v) for k, v in x.items()}
        if isinstance(x, (list, tuple)):
            return [self.scrub(v) for v in x]
        if not isinstance(x, str):
            return x
        rx, known = self._rx()
        return UUID.sub("<id>", rx.sub(lambda mt: known[mt.group(1)], x) if rx else x)

    def survivors(self, text):
        rx, known = self._rx()
        return sorted({known[mt.group(1)] for mt in rx.finditer(text)}) if rx else []


L = Labels()


# ---------------------------------------------------------------- the exports
def load_exports(folder):
    """{product: {release, downloaded, file, rows}} from every CSV in the folder. A row's last field is its limit, the field
    before it its name, and on a row of five fields the third is the tool's Attribute Header (the size, for NSX and Edge)."""
    out = {}
    for path in sorted(glob.glob(os.path.join(folder, "*.csv"))):
        base = os.path.basename(path)
        product = next((p for key, p in sorted(PRODUCTS.items(), key=lambda kv: -len(kv[0])) if re.search(rf"(?<![A-Za-z]){re.escape(key)}(?![A-Za-z])", base)), None)
        if not product:
            continue
        with open(path, encoding="utf-8-sig", newline="") as f:
            rows = [[c.strip() for c in r] for r in csv.reader(f) if any(c.strip() for c in r)]
        if not rows or rows[0][:2] != ["Category", "Subcategory"]:
            continue
        body = rows[1:]
        release = next((r[2] for r in body if len(r) > 2 and not r[0] and r[1] == "Limit"), None)
        downloaded = next((r[1] for r in body if r[0].startswith("Report Downloaded")), None)
        data = [{"cat": r[0], "sub": r[1], "group": r[2] if len(r) >= 5 else None, "name": r[-2], "limit": r[-1]}
                for r in body if r[0] and not r[0].startswith("Report Downloaded") and len(r) >= 4]
        out[product] = {"release": release, "downloaded": downloaded, "file": base, "rows": data}
    return out


def number(limit):
    """The leading count of a limit as an integer ("10,000" -> 10000, "300000 virtual machines" -> 300000), or None."""
    m = re.match(r"\s*([\d,]+)(?:\s|$)", limit or "")
    return int(m.group(1).replace(",", "")) if m else None


def select_caps(exports, sizes):
    out = []
    for c in CAPS:
        want = {k: c[k].format(**{s: SIZES[s][v] for s, v in sizes.items()}) if isinstance(c.get(k), str) else c.get(k)
                for k in ("cat", "sub", "group", "name")}
        exp = exports.get(c["product"])
        row = None
        if exp:
            row = next((r for r in exp["rows"] if r["name"].lower() == want["name"].lower()
                        and all(want[k] is None or (r[k] or "").lower() == want[k].lower() for k in ("cat", "sub", "group"))), None)
        out.append({"id": c["id"], "layer": c["layer"], "product": c["product"], "name": want["name"],
                    "for": want.get("group") or want.get("cat"), "limit": row["limit"] if row else None,
                    "value": number(row["limit"]) if row else None,
                    "release": exp["release"] if exp else None, "count": c["count"],
                    "missing": None if row else ("no export for this product" if not exp else "not listed for this size")})
    return out


# ---------------------------------------------------------------- the estate, read-only
def read_sddc():
    hosts, toks = [h.strip() for h in os.environ.get("SDDC_HOSTS", "").split(",") if h.strip()], secrets_of("SDDC_TOKEN_FILES")
    if not hosts:
        return None
    if len(toks) != len(hosts):
        raise KeyError("SDDC_TOKEN_FILES: one bearer file per SDDC_HOSTS entry, in the same order")
    instances = []
    for host, tok in zip(hosts, toks):
        h = {"Authorization": f"Bearer {tok}", "Accept": "application/json"}
        st, doms = http("GET", f"https://{host}/v1/domains", h)
        st2, hs = http("GET", f"https://{host}/v1/hosts", h)
        if st != 200 or st2 != 200:
            raise Failed(f"SDDC Manager {L.get('instance', host)} answered {st} for its domains and {st2} for its hosts")
        doms, hs = (doms or {}).get("elements") or [], (hs or {}).get("elements") or []
        per = {}
        for x in hs:
            d = (x.get("domain") or {}).get("id")
            per[d] = per.get(d, 0) + 1
        instances.append({"instance": L.get("instance", host), "hosts": len(hs), "domains": len(doms),
                          "viDomains": sum(1 for d in doms if d.get("type") == "VI"),
                          "mostHostsInADomain": max(per.values()) if per else 0})
    return instances


def read_vcenters():
    hosts = [h.strip() for h in os.environ.get("VC_HOSTS", "").split(",") if h.strip()]
    if not hosts:
        return None
    users, pws = [u.strip() for u in os.environ.get("VC_USER", "").split(",") if u.strip()], secrets_of("VC_PASSWORD_FILE")
    if not users or len(pws) != len(users) or len(users) not in (1, len(hosts)):
        raise KeyError("VC_USER and VC_PASSWORD_FILE: one account and one password file for every vCenter, or one of each per VC_HOSTS entry")
    out = []
    for i, host in enumerate(hosts):
        user, pw = (users[0], pws[0]) if len(users) == 1 else (users[i], pws[i])
        basic = base64.b64encode(f"{user}:{pw}".encode()).decode()
        st, sid = http("POST", f"https://{host}/api/session", {"Authorization": f"Basic {basic}"})
        if st not in (200, 201) or not isinstance(sid, str):
            raise Failed(f"vCenter {L.get('vcenter', host)} refused the session ({st})")
        h = {"vmware-api-session-id": sid, "Accept": "application/json"}
        try:
            g = lambda path: http("GET", f"https://{host}{path}", h)
            _, hs = g("/api/vcenter/host")
            _, vms = g("/api/vcenter/vm")
            _, on = g("/api/vcenter/vm?power_states=POWERED_ON")
            st, sups = g("/api/vcenter/namespace-management/supervisors/summaries")
            sups = (sups or {}).get("items", []) if st == 200 and isinstance(sups, dict) else []
            _, nss = g("/api/vcenter/namespaces/instances/v2")
            zones = []
            for s in sups:
                _, b = g(f"/api/vcenter/namespace-management/supervisors/{s['supervisor']}/zones/bindings")
                zones.append(len((b or {}).get("zones") or []) if isinstance(b, dict) else 0)
            out.append({"vcenter": L.get("vcenter", host), "hosts": len(hs or []), "vms": len(vms or []), "vmsOn": len(on or []),
                        "supervisors": len(sups), "namespaces": len(nss) if isinstance(nss, list) else 0,
                        "mostZonesOnASupervisor": max(zones) if zones else 0})
        finally:
            http("DELETE", f"https://{host}/api/session", h)
    return out


def read_nsx():
    hosts, toks = [h.strip() for h in os.environ.get("NSX_HOSTS", "").split(",") if h.strip()], secrets_of("NSX_TOKEN_FILES")
    if not hosts:
        return None
    if len(toks) != len(hosts):
        raise KeyError("NSX_TOKEN_FILES: one bearer file per NSX_HOSTS entry, in the same order")
    out = []
    for host, tok in zip(hosts, toks):
        h = {"Authorization": f"Bearer {tok}", "Accept": "application/json"}
        g = lambda path: http("GET", f"https://{host}/policy/api/v1{path}", h)
        st, prj = g("/orgs/default/projects")
        if st != 200:
            raise Failed(f"NSX Manager {L.get('nsx', host)} answered {st} for its projects")
        projects = (prj or {}).get("results") or []
        vpcs = tgws = subnets = most = 0
        for p in projects:
            _, v = g(f"/orgs/default/projects/{p['id']}/vpcs")
            for vpc in (v or {}).get("results") or []:
                vpcs += 1
                _, sn = g(f"/orgs/default/projects/{p['id']}/vpcs/{vpc['id']}/subnets")
                n = len((sn or {}).get("results") or [])
                subnets += n
                most = max(most, n)
            _, t = g(f"/orgs/default/projects/{p['id']}/transit-gateways")
            tgws += len((t or {}).get("results") or [])
        out.append({"nsx": L.get("nsx", host), "projects": len(projects), "vpcs": vpcs, "subnets": subnets,
                    "mostSubnetsInAVpc": most, "transitGateways": tgws})
    return out


def read_vcfa():
    host = os.environ.get("VCFA_HOST")
    if not host:
        return None
    tok = secrets_of("VCFA_PROVIDER_REFRESH_TOKEN_FILE")
    if not tok:
        raise KeyError("VCFA_PROVIDER_REFRESH_TOKEN_FILE")
    st, b = http("POST", f"https://{host}/oauth/provider/token", {"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
                 form={"grant_type": "refresh_token", "refresh_token": tok[0]})
    if st != 200 or not isinstance(b, dict) or not b.get("access_token"):
        raise Failed(f"the provider token exchange answered {st}")
    h = {"Authorization": f"Bearer {b['access_token']}", "Accept": "application/json;version=9.0.0"}

    def pages(path):
        items, page = [], 1
        while True:
            st, body = http("GET", f"https://{host}/cloudapi{path}{'&' if '?' in path else '?'}page={page}&pageSize=128", h)
            if st != 200:
                raise Failed(f"the provider plane answered {st} for {path}")
            items += (body or {}).get("values") or []
            if page >= ((body or {}).get("pageCount") or 1):
                return items
            page += 1
    orgs = [o for o in pages("/1.0.0/orgs") if o.get("name") != "System"]
    quotas = pages("/v1/virtualDatacenters")
    per_org = {}
    for q in quotas:
        per_org.setdefault((q.get("org") or {}).get("id"), set()).add((q.get("region") or {}).get("id"))
    return {"orgs": len(orgs), "namespaces": len(pages("/v1/namespaceSummaries")), "vpcs": len(pages("/v1/vpcs")),
            "regionQuotas": len(quotas), "mostRegionsInAnOrg": max((len(v) for v in per_org.values()), default=0)}


def counts(estate):
    """Each cap's count from the reads: the largest over the instances, vCenters or managers read, and where it is."""
    s, v, n, a = (estate.get(k) for k in ("sddc", "vcenters", "nsx", "vcfa"))
    def most(items, key, label):
        if not items:
            return None
        top = max(items, key=lambda x: x[key])
        return {"count": top[key], "where": top[label], "of": len(items)}
    return {
        "fleet_hosts": {"count": sum(i["hosts"] for i in s), "where": f"{len(s)} instance(s) read", "of": len(s)} if s else None,
        "fleet_vms": {"count": sum(x["vms"] for x in v), "where": f"{len(v)} vCenter(s) read", "of": len(v)} if v else None,
        "instance_hosts": most(s, "hosts", "instance"), "instance_vcenters": most(s, "domains", "instance"),
        "instance_vi_domains": most(s, "viDomains", "instance"), "domain_hosts": most(s, "mostHostsInADomain", "instance"),
        "vcenter_hosts": most(v, "hosts", "vcenter"), "vcenter_vms_on": most(v, "vmsOn", "vcenter"), "vcenter_vms": most(v, "vms", "vcenter"),
        "vcenter_supervisors": most(v, "supervisors", "vcenter"), "vcenter_namespaces": most(v, "namespaces", "vcenter"),
        "supervisor_zones": most(v, "mostZonesOnASupervisor", "vcenter"),
        "nsx_projects": most(n, "projects", "nsx"), "nsx_vpcs": most(n, "vpcs", "nsx"), "nsx_subnets": most(n, "subnets", "nsx"),
        "nsx_subnets_per_vpc": most(n, "mostSubnetsInAVpc", "nsx"), "nsx_tgws": most(n, "transitGateways", "nsx"),
        "vcfa_orgs": {"count": a["orgs"], "where": "the provider", "of": 1} if a else None,
        "vcfa_namespaces": {"count": a["namespaces"], "where": "the provider", "of": 1} if a else None,
        "vcfa_vpcs": {"count": a["vpcs"], "where": "the provider", "of": 1} if a else None,
        "vcfa_quotas": {"count": a["regionQuotas"], "where": "the provider", "of": 1} if a else None,
        "vcfa_regions_per_org": {"count": a["mostRegionsInAnOrg"], "where": "the provider", "of": 1} if a else None,
    }


# ---------------------------------------------------------------- run
def args():
    a, out = sys.argv[1:], {"nsx": "medium-singleton", "edge": "medium", "vcfa": "medium", "fleet": "simple", "warn": 70.0}
    while a:
        k = a.pop(0)
        if k in ("--exports", "--nsx", "--edge", "--vcfa", "--fleet", "--warn") and a:
            v = a.pop(0)
            key = k[2:]
            if key in SIZES and v not in SIZES[key]:
                print(f"{k} takes one of: {', '.join(SIZES[key])}", file=sys.stderr)
                sys.exit(5)
            if key == "warn":
                try:
                    v = float(v)
                except ValueError:
                    print("--warn takes a percentage, such as 70", file=sys.stderr)
                    sys.exit(5)
            out[key] = v
        else:
            print(f"unknown or incomplete argument {k!r}: --exports, --nsx, --edge, --vcfa, --fleet, --warn", file=sys.stderr)
            sys.exit(5)
    if "exports" not in out:
        print("--exports names the folder of your ConfigMax CSV exports", file=sys.stderr)
        sys.exit(5)
    return out


def register_environment():
    for var, fam in (("SDDC_HOSTS", "instance"), ("VC_HOSTS", "vcenter"), ("NSX_HOSTS", "nsx"), ("VCFA_HOST", "automation"), ("VC_USER", "user")):
        for h in os.environ.get(var, "").split(","):
            if h.strip():
                L.get(fam, h.strip())


def main():
    opt = args()
    exports = load_exports(os.path.expanduser(opt["exports"]))
    if not exports:
        print(f"no ConfigMax CSV export was found in {opt['exports']}", file=sys.stderr)
        return 2
    sizes = {k: opt[k] for k in SIZES}
    register_environment()
    try:
        estate = {"sddc": read_sddc(), "vcenters": read_vcenters(), "nsx": read_nsx(), "vcfa": read_vcfa()}
    except (KeyError, PermissionError, OSError) as e:
        print(f"setting: {e}", file=sys.stderr)
        return 2
    except Failed as e:
        print(f"FAILED: {L.scrub(str(e))}", file=sys.stderr)
        return 3
    caps, cnt = select_caps(exports, sizes), counts(estate)
    print(f"maximums.py: {len(exports)} export(s), sizes {SIZES['fleet'][sizes['fleet']]}, NSX {SIZES['nsx'][sizes['nsx']]}, Edge {SIZES['edge'][sizes['edge']]}, "
          f"VCF Automation {SIZES['vcfa'][sizes['vcfa']]}; planes read: {', '.join(k for k, v in estate.items() if v is not None) or 'none'}\n")
    print(f"  {'layer':16}{'cap':62}{'limit':>12}  {'release':8}{'read':>8}  used")
    over, missing = [], []
    for c in caps:
        got = cnt.get(c["count"]) if c["count"] else None
        c["read"] = got
        c["usedPercent"] = round(100 * got["count"] / c["value"], 2) if got and c["value"] else None
        if c["missing"]:
            missing.append(c["id"])
        if c["usedPercent"] is not None and c["usedPercent"] >= opt["warn"]:
            over.append(c["id"])
        shown = c["limit"] if c["limit"] is not None else f"({c['missing']})"
        print(f"  {c['layer']:16}{c['name'][:61]:62}{shown[:30]:>12}  {c['release'] or '':8}"
              f"{got['count'] if got else '':>8}  {str(c['usedPercent']) + '%' if c['usedPercent'] is not None else ''}".rstrip())
    print(f"\n  releases: " + ", ".join(f"{p} {e['release']}" for p, e in sorted(exports.items())))
    rec = {"capturedUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "sizes": sizes, "warnPercent": opt["warn"],
           "exports": {p: {"release": e["release"], "downloaded": e["downloaded"], "rows": len(e["rows"])} for p, e in exports.items()},
           "estate": estate, "caps": caps, "over": over, "missing": missing}
    text = json.dumps(L.scrub(rec), ensure_ascii=False)
    left = L.survivors(text)
    if left:
        print(f"FATAL: maximums.json still carries {left}; nothing written", file=sys.stderr)
        return 4
    with open(os.path.join(os.environ.get("OUT_DIR", HERE), "maximums.json"), "w", encoding="utf-8") as f:
        f.write(json.dumps(json.loads(text), indent=1) + "\n")
    print("wrote maximums.json; no host or object name is recorded")
    if over:
        print(f"  at or over {opt['warn']}%: {over}")
    if missing:
        print(f"  not in your exports for these sizes: {missing}")
    return 1 if over else 0


if __name__ == "__main__":
    sys.exit(main())
