#!/usr/bin/env python3
"""infra_policy.py: what does a VCF Automation infrastructure policy actually do on your build?

An infrastructure policy is a vCenter VM-Host affinity compute policy carried down four layers: the provider's policy,
an organization's region quota, a namespace that names it, and a ComputePolicy object in the Supervisor namespace. An
Optional policy then binds only a VM that lists that ComputePolicy, and its criteria decide whether the VM can be placed.
This script reads the layers, and with --probe proves the behaviour on objects it creates and deletes.

Read-only, by default (a provider token; vCenter's credential adds the vSphere side):
  1. every provider policy: mandatory or optional, whether it has criteria, how many of the region's zones it is
     compatible with, whether it is synced to vCenter;
  2. which organizations' region quotas list it: a policy on no quota applies to nothing;
  3. with VC_*: the compute policy it names (its kind, the hosts carrying its host tag per cluster, the VMs carrying its
     VM tag), vCenter's namespace-level copies with their enforcement modes, and how many namespaces list each policy.

  --probe --project <p> --like <project>/<namespace> --host-tag <category>/<tag>
  Writes, on objects it creates and deletes, all named probe-infra. In vCenter: a tag category, two VM tags, and two
  VM-Host affinity compute policies on the EXISTING host tag you name (no host is modified; only a VM carrying a new tag
  is bound). As the provider: two Optional policies on them, one whose criterion matches the probe's Ubuntu VMs (guest
  family Linux) and one that cannot (Windows), added to your organization's region quota, whose list is read first and
  put back exactly. As the tenant: a namespace shaped like the --like one (class, VPC, overrides) naming both, placed in
  a zone the policies are compatible with, and three VMs: one that does not opt in, one that opts in to the matching
  policy, one that opts in to the other. Then teardown, always, in reverse, and a residue read; the quota list is
  compared with what it was. A namespace in a zone the policy is not compatible with is tried too, when the region has
  one: it should be refused. The --like namespace and the host tag are read before anything is written.

Run:
  export VCFA_HOST=<automation-fqdn> TLS_VERIFY=false                          # only on a self-signed lab CA
  export VCFA_PROVIDER_REFRESH_TOKEN_FILE=~/.vcf/provider-token                # mode 0600: a provider API token
  export VC_HOST=<workload vCenter> VC_USER=<account> VC_PASSWORD_FILE=~/.vcf/vc-password    # mode 0600; optional for the read
  python3 infra_policy.py
  # the probe also needs a tenant session login, as an organization administrator:
  export VCFA_ORG=<organization> VCFA_USER=<account> VCFA_PASSWORD_FILE=~/.vcf/vcfa-password # mode 0600
  python3 infra_policy.py --probe --project <a project nobody depends on> --like <project>/<namespace> --host-tag <category>/<tag>

The records, infra.json and infra-probe.json (beside this script, or in OUT_DIR), and every printed line carry labels in
place of policy, organization, zone, cluster, host, tag and namespace names, and no object id.

Exit: 0 read, every policy available somewhere and synced (the probe: each of the three VMs behaved as the model says)
      1 a policy applies to nothing (on no quota, not synced, or its compute policy missing), or a probe case differed
      2 a setting is missing or a secret file is open to group or other · 3 a read or a write failed
      4 a record refused to write because a name survived · 5 an unknown argument
"""

from __future__ import annotations

import base64
import json
import os
import re
import secrets
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
API = "application/json;version=9.1.0"   # the policy plane answers 405 to older versions (G-787)
A3 = "infrastructure.cci.vmware.com/v1alpha3"
VMOP = "vmoperator.vmware.com/v1alpha5"
LIB = "imageregistry.vmware.com/v1alpha2"
CPK = "vsphere.policy.vmware.com/v1alpha1"
CAP = "com.vmware.vcenter.compute.policies.capabilities.vm_host_affinity"
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
PREFIX = "probe-infra"
MISMATCH_WAIT = 1200   # the VM that opts in to a policy it cannot match is watched this long; its condition is recorded


class Failed(Exception):
    """A step the answer depends on could not be done; exit 3 with the step named."""


def ctx():
    verify = os.environ.get("TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")
    return ssl.create_default_context() if verify else ssl._create_unverified_context()


def read_secret(var):
    """The value of a secret from <var>, a file of mode 0600; a file open to group or other is refused unread."""
    path = os.environ.get(var)
    if not path:
        return None
    with open(path, encoding="utf-8") as f:
        mode = os.fstat(f.fileno()).st_mode & 0o777
        if mode & 0o077 and os.name != "nt":
            raise PermissionError(f"{var} names a file of mode {mode:04o}, open to group or other: "
                                  f'run chmod 600 "${var}" and try again (the file was not read)')
        return f.read().strip()


def http(method, url, headers, body=None, form=None):
    data = urllib.parse.urlencode(form).encode() if form is not None else (json.dumps(body).encode() if body is not None else None)
    h = dict(headers)
    if body is not None and "Content-Type" not in h:
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, context=ctx(), timeout=120) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None), r.headers
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw), e.headers
        except ValueError:
            return e.code, {"message": raw.decode(errors="replace")[:400]}, e.headers
    except (urllib.error.URLError, OSError) as e:
        return None, {"message": type(e).__name__}, {}


def msg(body):
    return (body or {}).get("message", "")[:400] if isinstance(body, dict) else str(body)[:400]


class Labels:
    """Stable placeholders: the first policy met is policy-1. A name is replaced only as a whole word and only in a value,
    never in a key, because keys are the product's schema or this script's. The product's own words are never names: a
    host tag category called workload once turned vSphere's match key into a label (G-791)."""

    RESERVED = {"admin", "user", "users", "group", "owner", "default", "system", "all", "none",
                "workload", "guest", "guestFamily", "op", "And", "Or", "Not", "Equal", "NotEqual", "value",
                "Linux", "Windows", "LINUX", "WINDOWS", "Optional", "Mandatory", "OPTIONAL", "MANDATORY",
                "COMPLIANT", "NOT_APPLICABLE", "ComputePolicy", "VirtualMachine", "HostSystem", "READY", "SUCCESS"}
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
        """A string, or a structure whose string values are scrubbed and whose keys are kept as they are."""
        if isinstance(x, dict):
            return {k: self.scrub(v) for k, v in x.items()}
        if isinstance(x, (list, tuple)):   # a tuple too: a placement condition is kept as one, and it quotes names
            return [self.scrub(v) for v in x]
        if not isinstance(x, str):
            return x
        rx, known = self._rx()
        return UUID.sub("<id>", rx.sub(lambda mt: known[mt.group(1)], x) if rx else x)

    def survivors(self, text):
        rx, known = self._rx()
        return sorted({known[mt.group(1)] for mt in rx.finditer(text)}) if rx else []

    def kept(self, raw, scrubbed):
        """The product's vocabulary came through: the same keys at every level, and every reserved word as it was."""
        if isinstance(raw, dict):
            return isinstance(scrubbed, dict) and raw.keys() == scrubbed.keys() and all(self.kept(raw[k], scrubbed[k]) for k in raw)
        if isinstance(raw, (list, tuple)):
            return isinstance(scrubbed, list) and len(raw) == len(scrubbed) and all(map(self.kept, raw, scrubbed))
        return scrubbed == raw if isinstance(raw, str) and raw in self.RESERVED else True


L = Labels()
REC = {"capturedUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "steps": []}


def log(step, **kw):
    t = time.strftime("%H:%M:%SZ", time.gmtime())
    REC["steps"].append({"at": t, "step": step, **kw})
    print(f"[{t}] {L.scrub(step)} {json.dumps(L.scrub(kw)) if kw else ''}", flush=True)


def wait(fn, timeout, every=10):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = fn()
        if v:
            return v, round(time.time() - t0)
        time.sleep(every)
    return None, round(time.time() - t0)


# ---------------------------------------------------------------- the three seats
class Provider:
    def __init__(self, host, token):
        self.host = host
        st, tok, _ = http("POST", f"https://{host}/oauth/provider/token", {"Accept": "application/json",
                          "Content-Type": "application/x-www-form-urlencoded"}, form={"grant_type": "refresh_token", "refresh_token": token})
        if st != 200 or not (tok or {}).get("access_token"):
            raise Failed(f"the provider token exchange answered {st}")
        self.h = {"Authorization": f"Bearer {tok['access_token']}", "Accept": API}

    def call(self, method, path, body=None):
        h = dict(self.h)
        if body is not None:
            h["Content-Type"] = API
        st, b, _ = http(method, f"https://{self.host}{path}", h, body)
        return st, b

    def values(self, path):
        st, b = self.call("GET", path)
        if st != 200:
            raise Failed(f"{path} answered {st}")
        return (b or {}).get("values") or []


class VCenter:
    def __init__(self, host, user, password):
        self.host = host
        basic = base64.b64encode(f"{user}:{password}".encode()).decode()
        st, sid, _ = http("POST", f"https://{host}/api/session", {"Authorization": f"Basic {basic}"})
        if st not in (200, 201):
            raise Failed(f"the vCenter sign-in answered {st}")
        self.h = {"vmware-api-session-id": sid, "Accept": "application/json"}

    def call(self, method, path, body=None):
        st, b, _ = http(method, f"https://{self.host}{path}", self.h, body)
        return st, b

    def close(self):
        self.call("DELETE", "/api/session")


class Tenant:
    def __init__(self, host, org, user, password):
        self.host, self.gw = host, f"https://{host}/cci/kubernetes"
        basic = base64.b64encode(f"{user}@{org}:{password}".encode()).decode()
        st, _, hd = http("POST", f"https://{host}/cloudapi/1.0.0/sessions", {"Authorization": f"Basic {basic}", "Accept": API})
        token = next((v for k, v in (hd or {}).items() if k.lower() == "x-vmware-vcloud-access-token"), None) if st == 200 else None
        if not token:
            raise Failed(f"the tenant session login answered {st}")
        self.h = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    def call(self, method, url, body=None):
        st, b, _ = http(method, url, self.h, body)
        return st, b


# ---------------------------------------------------------------- the read
def read(p, vc):
    pols = p.values("/cloudapi/vcf/infraPolicies")
    zones = sorted(z["name"] for z in p.values("/cloudapi/vcf/zones"))
    quotas = p.values("/cloudapi/vcf/virtualDatacenters")
    on_quota = {}
    for q in quotas:
        org = (q.get("org") or {}).get("name")
        for item in p.values(f"/cloudapi/vcf/virtualDatacenters/{q['id']}/infraPolicies"):
            ref = item.get("infraPolicy") or {}
            on_quota.setdefault(ref.get("id"), []).append(L.get("org", org))
    v_cps, v_nspol, v_ns = {}, [], []
    if vc:
        st, cps = vc.call("GET", "/api/vcenter/compute/policies")
        v_cps = {c["name"]: c for c in cps or []} if st == 200 else {}
        st, v_nspol = vc.call("GET", "/api/vcenter/namespace-management/infrastructure-policies")
        if isinstance(v_nspol, dict):   # the list arrives wrapped, not bare
            v_nspol = v_nspol.get("items") or v_nspol.get("policies") or []
        v_nspol = v_nspol if st == 200 and isinstance(v_nspol, list) else []
        st, v_ns = vc.call("GET", "/api/vcenter/namespaces/instances")
        v_ns = v_ns if st == 200 else []
        clusters = sorted((vc.call("GET", "/api/vcenter/cluster")[1] or []), key=lambda c: c["name"])
    out = []
    for pol in pols:
        compat = {z["name"] for rz in pol.get("compatibleRegionZones") or [] for z in rz.get("zones") or []}
        row = {"policy": L.get("policy", pol["name"]), "mandatory": pol.get("isMandatory"), "hasCriteria": bool(pol.get("policyRule")),
               "creationStatus": pol.get("creationStatus"), "syncedToVCenters": pol.get("syncedToVCenters"),
               "compatibleZones": f"{len([z for z in zones if z in compat])} of {len(zones)}",
               "onQuotasOf": on_quota.get(pol["id"], [])}
        if vc:
            cp = v_cps.get(pol.get("vcComputePolicyName"))
            row["computePolicyFound"] = bool(cp)
            if cp:
                st, d = vc.call("GET", f"/api/vcenter/compute/policies/{cp['policy']}")
                row["computePolicyKind"] = (cp.get("capability") or "").rsplit(".", 1)[-1]
                host_objs = {o["id"] for o in (vc.call("POST", f"/api/cis/tagging/tag-association/{(d or {}).get('host_tag')}?action=list-attached-objects")[1] or []) if o.get("type") == "HostSystem"} if (d or {}).get("host_tag") else set()
                vm_objs = vc.call("POST", f"/api/cis/tagging/tag-association/{(d or {}).get('vm_tag')}?action=list-attached-objects")[1] or [] if (d or {}).get("vm_tag") else []
                per = []
                for i, c in enumerate(clusters):
                    hs = vc.call("GET", f"/api/vcenter/host?clusters={c['cluster']}")[1] or []
                    per.append(f"cluster {i + 1}: {sum(1 for h in hs if h['host'] in host_objs)} of {len(hs)}")
                row["hostsCarryingTheHostTag"] = per
                row["vmsCarryingTheVmTag"] = len(vm_objs)
            row["namespacesListingIt"] = sum(1 for n in v_ns if pol["name"] in json.dumps(vc.call("GET", f"/api/vcenter/namespaces/instances/{n['namespace']}")[1] or {}))
        row["appliesToNothing"] = (not row["onQuotasOf"]) or pol.get("syncedToVCenters") is False or (vc is not None and not row.get("computePolicyFound"))
        out.append(row)
        print(L.scrub(f"  {row['policy']}: {'mandatory' if row['mandatory'] else 'optional'}, criteria {row['hasCriteria']}, "
                      f"compatible zones {row['compatibleZones']}, on the quotas of {row['onQuotasOf'] or 'no organization'}"
                      + (f"; compute policy {row.get('computePolicyKind')}, host tag on {row.get('hostsCarryingTheHostTag')}, VM tag on {row.get('vmsCarryingTheVmTag')} VM(s), "
                         f"listed by {row.get('namespacesListingIt')} namespace(s)" if vc else "")
                      + ("  -> applies to nothing" if row["appliesToNothing"] else "")))
    nsmodes = sorted({x.get("enforcement_mode") for x in v_nspol}) if vc else []
    print(f"  vCenter's namespace-level policies: {len(v_nspol)} {nsmodes}" if vc else "  vCenter not read (set VC_HOST, VC_USER, VC_PASSWORD_FILE)")
    return {"policies": out, "zones": len(zones), "quotas": len(quotas), "vcenterNamespacePolicies": len(v_nspol), "enforcementModes": nsmodes}


# ---------------------------------------------------------------- the probe
def vm_spec(images, storage, cls=None, policy=None):
    """A probe VM's spec, from the namespace's Ubuntu images (the first is taken: imageName is one name, and a list is
    refused 500 by the VM Operator's webhook as "unrecognized type: string", G-793) and, to opt in, the ComputePolicy's name."""
    spec = {"className": cls or "best-effort-xsmall", "imageName": images[0], "storageClass": storage, "powerState": "PoweredOn"}
    if policy:
        spec["policies"] = [{"apiVersion": CPK, "kind": "ComputePolicy", "name": policy}]
    return spec


def settled_compliance(vc, vm, policy, timeout=420):
    """vCenter's compliance of a VM with a compute policy, once it has evaluated: a VM read right after power-on was UNKNOWN
    and COMPLIANT minutes later (G-792). Returns the status and the seconds it took, or UNKNOWN when it never settled."""
    def read():
        st, c = vc.call("GET", f"/api/vcenter/vm/{vm}/compute/policies/{policy}")
        status = c.get("status") if st == 200 and isinstance(c, dict) else None
        return status if status and status != "UNKNOWN" else None
    status, secs = wait(read, timeout, 15)
    return status or "UNKNOWN", secs


def probe(p, vc, t, opt):
    base = f"{PREFIX}-{secrets.token_hex(3)}"
    made = {"category": None, "tags": {}, "compute": {}, "policies": {}, "quota": None, "ns": None, "vms": []}
    snap = None
    verdict = {}
    try:
        cat, tag = opt["host-tag"].split("/", 1)
        L.get("tag", cat), L.get("tag", tag)
        st, cats = vc.call("GET", "/api/cis/tagging/category")
        cat_id = next((c for c in cats or [] if (vc.call("GET", f"/api/cis/tagging/category/{c}")[1] or {}).get("name") == cat), None)
        st, tags = vc.call("POST", "/api/cis/tagging/tag?action=list-tags-for-category", {"category_id": cat_id}) if cat_id else (None, [])
        host_tag = next((x for x in tags or [] if (vc.call("GET", f"/api/cis/tagging/tag/{x}")[1] or {}).get("name") == tag), None)
        if not host_tag:
            raise Failed("--host-tag names no tag in that category")
        tagged = [o for o in (vc.call("POST", f"/api/cis/tagging/tag-association/{host_tag}?action=list-attached-objects")[1] or []) if o.get("type") == "HostSystem"]
        if not tagged:
            raise Failed("--host-tag is on no host, so no zone can be compatible with a policy on it; nothing was written")
        lp, lns = opt["like"].split("/", 1)   # the template is read before any write, so a wrong one costs nothing
        L.get("project", lp), L.get("namespace", lns), L.get("project", opt["project"])
        st, like = t.call("GET", f"{t.gw}/apis/{A3}/namespaces/{lp}/supervisornamespaces/{lns}")
        if st != 200:
            raise Failed(f"the --like namespace was not read ({st}); nothing was written")
        if not ((like.get("spec") or {}).get("classConfigOverrides") or {}).get("zones"):
            raise Failed("the --like namespace names no zone in classConfigOverrides, so the probe cannot place its own; nothing was written")
        for z in sorted(z["name"] for z in p.values("/cloudapi/vcf/zones")):
            L.get("zone", z)
        for r in sorted(r["name"] for r in p.values("/cloudapi/vcf/regions")):   # a refusal quotes the region by name
            L.get("region", r)
        L.get("region", like["spec"].get("regionName"))
        org = os.environ["VCFA_ORG"]
        L.get("org", org)
        quota = next((q for q in p.values("/cloudapi/vcf/virtualDatacenters") if (q.get("org") or {}).get("name") == org), None)
        if not quota:
            raise Failed("your organization has no region quota")
        qpath = f"/cloudapi/vcf/virtualDatacenters/{quota['id']}/infraPolicies"
        before = p.values(qpath)
        snap = {"quota": before, "path": qpath}
        log("the organization's region quota read", policiesListed=len(before))
        st, cid = vc.call("POST", "/api/cis/tagging/category", {"name": base, "description": "throwaway: infra_policy.py probe",
                                                                "cardinality": "SINGLE", "associable_types": ["VirtualMachine"]})
        if st not in (200, 201):
            raise Failed(f"tag category create answered {st}")
        made["category"] = cid
        for fam in ("LINUX", "WINDOWS"):
            name = f"{base}-{fam.lower()}"
            st, tid = vc.call("POST", "/api/cis/tagging/tag", {"name": name, "description": "throwaway VM tag", "category_id": cid})
            made["tags"][fam] = tid if st in (200, 201) else None
            st2, pid = vc.call("POST", "/api/vcenter/compute/policies", {"capability": CAP, "name": name, "description": "throwaway",
                                                                        "vm_tag": tid, "host_tag": host_tag})
            if st2 not in (200, 201):
                raise Failed(f"compute policy create answered {st2}: {msg(pid)}")
            made["compute"][fam] = pid
        log("vCenter: a VM tag and a VM-Host affinity compute policy per case, on your host tag", created=len(made["compute"]))
        for fam in ("LINUX", "WINDOWS"):
            name = f"{base}-{fam.lower()}"
            L.get("policy", name)
            body = {"name": name, "description": "throwaway: infra_policy.py probe", "vcComputePolicyName": name, "isMandatory": False,
                    "policyRule": {"workloadPolicyRule": {"guestOsFamilyRule": {"operator": "IS_EQUAL", "value": fam}}}}
            def create(body=body):
                st, b = p.call("POST", "/cloudapi/vcf/infraPolicies", body)
                if st in (200, 201, 202):
                    return st
                if "does not exist" not in msg(b).lower():   # anything but the compute policy not yet synced is a failure
                    raise Failed(f"policy create answered {st}: {L.scrub(msg(b))}")
            res, secs = wait(create, 1500, 30)
            if not res:
                raise Failed("VCF Automation did not sync the compute policy in 25 minutes")
            pol, _ = wait(lambda name=name: next((x for x in p.values("/cloudapi/vcf/infraPolicies") if x["name"] == name and x.get("creationStatus") in ("SUCCESS", "FAILED")), None), 600)
            if not pol or pol["creationStatus"] != "SUCCESS":
                raise Failed("the policy did not create")
            made["policies"][fam] = pol
            log(f"provider: Optional policy, criterion guest family {fam}", secondsUntilTheComputePolicySynced=secs)
        st, b = p.call("PUT", qpath, {"values": before + [{"infraPolicy": {"id": made["policies"][f]["id"], "name": made["policies"][f]["name"]}} for f in ("LINUX", "WINDOWS")]})
        if st >= 300:
            raise Failed(f"the quota list answered {st}: {L.scrub(msg(b))}")
        made["quota"] = True
        log("provider: both policies added to your organization's region quota", status=st)
        time.sleep(30)
        mine = made["policies"]["LINUX"]["name"]   # read again: the create's own record is not where compatibility is kept
        fresh = next((x for x in p.values("/cloudapi/vcf/infraPolicies") if x["name"] == mine), made["policies"]["LINUX"])
        compat = sorted({z["name"] for rz in fresh.get("compatibleRegionZones") or [] for z in rz.get("zones") or []})
        if not compat:
            raise Failed("the policies are compatible with no zone of the region: the host tag's hosts back no zone's cluster")
        lz = [z["name"] for z in (like.get("status") or {}).get("zones") or []]
        zone = next((z for z in lz if z in compat), compat[0])   # the template gives the shape; the probe picks the zone
        sp = json.loads(json.dumps({k: v for k, v in like["spec"].items() if k in ("className", "regionName", "vpcName", "segName", "classConfigOverrides")}))
        sp["classConfigOverrides"]["zones"] = [dict(sp["classConfigOverrides"]["zones"][0], name=zone)]
        log("tenant: the namespace's zone, chosen from those the policies are compatible with",
            templateZones=[L.get("zone", z) for z in lz], compatible=[L.get("zone", z) for z in compat], chosen=L.get("zone", zone))
        sp.update(description="throwaway: infra_policy.py probe", infraPolicyNames=[made["policies"][f]["name"] for f in ("LINUX", "WINDOWS")])
        st, o = t.call("POST", f"{t.gw}/apis/{A3}/namespaces/{opt['project']}/supervisornamespaces",
                       {"apiVersion": A3, "kind": "SupervisorNamespace", "metadata": {"generateName": f"{PREFIX}-", "namespace": opt["project"]}, "spec": sp})
        if st >= 300:
            raise Failed(f"the namespace naming both policies answered {st}: {L.scrub(msg(o))}")
        ns = o["metadata"]["name"]
        L.get("namespace", ns)
        made["ns"] = {"name": ns, "born": time.time(), "ep": None}
        n, _ = wait(lambda: (lambda s, n: n if s == 200 and (n.get("status") or {}).get("namespaceEndpointURL") else None)(*t.call("GET", f"{t.gw}/apis/{A3}/namespaces/{opt['project']}/supervisornamespaces/{ns}")), 600)
        if not n:
            raise Failed("the namespace never reported an endpoint")
        ep = made["ns"]["ep"] = n["status"]["namespaceEndpointURL"].rstrip("/")
        log("tenant: a namespace naming both policies", created=True, listsBoth=len((n.get("spec") or {}).get("infraPolicyNames") or []) == 2)
        storage, _ = wait(lambda: next((c["name"] for c in ((t.call("GET", f"{t.gw}/apis/{A3}/namespaces/{opt['project']}/supervisornamespaces/{ns}")[1] or {}).get("status") or {}).get("storageClasses") or []), None), 300)
        image = wait(lambda: (lambda s, im: sorted(i["metadata"]["name"] for i in (im or {}).get("items", []) if ((i.get("status") or {}).get("osInfo") or {}).get("type", "").startswith("ubuntu")) or None)(*t.call("GET", f"{ep}/apis/{VMOP}/namespaces/{ns}/virtualmachineimages")), 60)[0]
        if not image:  # the organization's library is not attached to a namespace made through the API (G-663)
            st, lk = t.call("GET", f"{like['status']['namespaceEndpointURL'].rstrip('/')}/apis/{LIB}/namespaces/{lns}/contentlibraries")
            lib = ((lk or {}).get("items") or [None])[0]
            if not lib:
                raise Failed("no Ubuntu image, and the --like namespace carries no library to attach")
            d = vc.call("GET", f"/api/vcenter/namespaces/instances/{ns}")[1] or {}
            vss = dict(d.get("vm_service_spec") or {}); vss["content_libraries"] = sorted(set(vss.get("content_libraries") or []) | {lib["spec"]["id"]})
            vc.call("PATCH", f"/api/vcenter/namespaces/instances/{ns}", {"vm_service_spec": vss})
            image = wait(lambda: (lambda s, im: sorted(i["metadata"]["name"] for i in (im or {}).get("items", []) if ((i.get("status") or {}).get("osInfo") or {}).get("type", "").startswith("ubuntu")) or None)(*t.call("GET", f"{ep}/apis/{VMOP}/namespaces/{ns}/virtualmachineimages")), 600)[0]
            log("the namespace's library attached on vCenter's namespace setting (G-663)", image=bool(image))
        cps, _ = wait(lambda: (lambda s, c: (c or {}).get("items") if s == 200 and len((c or {}).get("items") or []) >= 2 else None)(*t.call("GET", f"{ep}/apis/{CPK}/namespaces/{ns}/computepolicies")), 300)
        by = {f: next((c for c in cps or [] if (c.get("spec") or {}).get("policyID") == made["compute"][f]), None) for f in ("LINUX", "WINDOWS")}
        log("the Supervisor namespace's ComputePolicies", found=sum(1 for v in by.values() if v),
            enforcementModes=sorted({(c.get("spec") or {}).get("enforcementMode") for c in by.values() if c}),
            linuxMatch=((by["LINUX"] or {}).get("spec") or {}).get("match"))
        cases = (("no opt-in", None), ("opts in, matching", "LINUX"), ("opts in, not matching", "WINDOWS"))
        for label, fam in cases:
            spec = vm_spec(image, storage, opt.get("class"), by[fam]["metadata"]["name"] if fam else None)
            vm = f"{PREFIX}-vm-{len(made['vms']) + 1}"
            st, vo = t.call("POST", f"{ep}/apis/{VMOP}/namespaces/{ns}/virtualmachines",
                            {"apiVersion": VMOP, "kind": "VirtualMachine", "metadata": {"name": vm, "namespace": ns}, "spec": spec})
            if st >= 300:
                raise Failed(f"VM create ({label}) answered {st}: {L.scrub(msg(vo))}")
            made["vms"].append((vm, label, fam))
        time.sleep(90)
        for vm, label, fam in made["vms"]:
            placed, secs = wait(lambda vm=vm: (lambda s, v: v if s == 200 and ((v.get("status") or {}).get("uniqueID")) and (v.get("status") or {}).get("powerState") == "PoweredOn" else None)(*t.call("GET", f"{ep}/apis/{VMOP}/namespaces/{ns}/virtualmachines/{vm}")), MISMATCH_WAIT if fam == "WINDOWS" else 600)
            if not placed:
                s, v = t.call("GET", f"{ep}/apis/{VMOP}/namespaces/{ns}/virtualmachines/{vm}")
                cond = next(((c.get("type"), c.get("reason"), (c.get("message") or "")[:600]) for c in ((v or {}).get("status") or {}).get("conditions") or [] if c.get("status") != "True" and "Placement" in (c.get("type") or "")), None)
                log(f"VM, {label}", placed=False, secondsWaited=secs, placementCondition=cond)
                verdict[label] = fam == "WINDOWS"
                continue
            stt = placed["status"]
            ref = made["compute"][fam or "LINUX"]
            tags = vc.call("POST", "/api/cis/tagging/tag-association?action=list-attached-tags", {"object_id": {"id": stt["uniqueID"], "type": "VirtualMachine"}})[1] or []
            compliance, csecs = settled_compliance(vc, stt["uniqueID"], ref)
            log(f"VM, {label}", placed=True, carriesThePolicysVmTag=made["tags"][fam or "LINUX"] in tags, compliance=compliance,
                secondsUntilComplianceSettled=csecs, statusPolicies=len(stt.get("policies") or []))
            verdict[label] = (compliance == "NOT_APPLICABLE") if fam is None else (compliance == "COMPLIANT" if fam == "LINUX" else False)
        zones = sorted(z["name"] for z in p.values("/cloudapi/vcf/zones"))
        incompatible = [z for z in zones if z not in compat]
        if incompatible:
            z = incompatible[0]
            L.get("zone", z)
            sp2 = json.loads(json.dumps(sp))
            for zz in (sp2.get("classConfigOverrides") or {}).get("zones") or []:
                zz["name"] = z
            st, o = t.call("POST", f"{t.gw}/apis/{A3}/namespaces/{opt['project']}/supervisornamespaces",
                           {"apiVersion": A3, "kind": "SupervisorNamespace", "metadata": {"generateName": f"{PREFIX}-", "namespace": opt["project"]}, "spec": sp2})
            if st < 300:  # it was not refused: delete it in teardown with the other
                made["ns2"] = {"name": o["metadata"]["name"], "born": time.time()}
            log("tenant: a namespace naming the policies in a zone they are not compatible with", status=st, refused=L.scrub(msg(o)) if st >= 300 else None)
            verdict["incompatible zone refused"] = st >= 300
        REC["verdict"] = verdict
        return 0 if verdict and all(verdict.values()) else 1
    finally:
        try:
            if made["ns"]:
                for vm, _, _ in made["vms"]:
                    st, _ = t.call("DELETE", f"{made['ns']['ep']}/apis/{VMOP}/namespaces/{made['ns']['name']}/virtualmachines/{vm}")
                    log("teardown VM", status=st)
                if made["vms"]:
                    wait(lambda: all(t.call("GET", f"{made['ns']['ep']}/apis/{VMOP}/namespaces/{made['ns']['name']}/virtualmachines/{vm}")[0] == 404 for vm, _, _ in made["vms"]), 600)
            for key in ("ns", "ns2"):
                e = made.get(key)
                if not e:
                    continue
                age = time.time() - e["born"]
                if age < 120:   # a namespace deleted during its post-create update was left stranded once (G-662)
                    time.sleep(120 - age)
                url = f"{t.gw}/apis/{A3}/namespaces/{opt['project']}/supervisornamespaces/{e['name']}"
                st, _ = t.call("DELETE", url)
                gone, _ = wait(lambda url=url: t.call("GET", url)[0] == 404, 180, 15)
                if not gone:
                    t.call("DELETE", url)
                    gone, _ = wait(lambda url=url: t.call("GET", url)[0] == 404, 720, 15)
                log("teardown namespace", status=st, gone=bool(gone))
            if made["quota"] and snap:
                st, b = p.call("PUT", snap["path"], {"values": snap["quota"]})
                log("teardown: the quota list put back as it was", status=st)
            for fam, pol in made["policies"].items():
                st, _ = p.call("DELETE", f"/cloudapi/vcf/infraPolicies/{pol['id']}")
                log(f"teardown policy ({fam})", status=st)
            if made["policies"]:
                wait(lambda: not any(x["name"].startswith(base) for x in p.values("/cloudapi/vcf/infraPolicies")), 600)
            for fam, pid in made["compute"].items():   # deleting the provider's policy leaves the compute policy (G-788)
                st, _ = vc.call("DELETE", f"/api/vcenter/compute/policies/{pid}")
                log(f"teardown compute policy ({fam})", status=st)
            for fam, tid in made["tags"].items():
                if tid:
                    vc.call("DELETE", f"/api/cis/tagging/tag/{tid}")
            if made["category"]:
                st, _ = vc.call("DELETE", f"/api/cis/tagging/category/{made['category']}")
                log("teardown tags and category", status=st)
        finally:
            res = {"probePolicies": sum(1 for x in p.values("/cloudapi/vcf/infraPolicies") if x["name"].startswith(PREFIX)),
                   "probeComputePolicies": sum(1 for c in (vc.call("GET", "/api/vcenter/compute/policies")[1] or []) if c["name"].startswith(PREFIX)),
                   "probeNamespaces": sum(1 for n in (t.call("GET", f"{t.gw}/apis/{A3}/namespaces/{opt['project']}/supervisornamespaces")[1] or {}).get("items") or [] if n["metadata"]["name"].startswith(f"{PREFIX}-"))}
            if snap:
                res["quotaAsBefore"] = p.values(snap["path"]) == snap["quota"]
            log("residue", **res)
            REC["residue"] = res


def args():
    a, out = sys.argv[1:], {"probe": False}
    takes = {"--project": "project", "--like": "like", "--host-tag": "host-tag", "--class": "class"}
    while a:
        k = a.pop(0)
        if k == "--probe":
            out["probe"] = True
        elif k in takes and a:
            out[takes[k]] = a.pop(0)
        else:
            print(f"unknown or incomplete argument {k!r}: --probe, --project, --like, --host-tag, --class", file=sys.stderr)
            sys.exit(5)
    if out["probe"] and not all(k in out for k in ("project", "like", "host-tag")):
        print("--probe writes: name --project, --like <project>/<namespace> and --host-tag <category>/<tag>", file=sys.stderr)
        sys.exit(5)
    if out["probe"] and ("/" not in out["like"] or "/" not in out["host-tag"]):
        print("--like takes <project>/<namespace> and --host-tag <category>/<tag>", file=sys.stderr)
        sys.exit(5)
    return out


def register_environment():
    """Hosts and accounts become labels before the first line is printed, so a refusal that echoes one is scrubbed too."""
    for k, fam in (("VCFA_HOST", "host"), ("VC_HOST", "host"), ("VCFA_USER", "user"), ("VC_USER", "user"), ("VCFA_ORG", "org")):
        if os.environ.get(k):
            L.get(fam, os.environ[k])


def write(name):
    rec = L.scrub(REC)
    text = json.dumps(rec, ensure_ascii=False)
    left = L.survivors(text)
    if left:
        print(f"FATAL: {name} still carries {left}; nothing written", file=sys.stderr)
        return False
    if not L.kept(REC, rec):
        print(f"FATAL: the scrub changed a key or a word of the product's in {name}; nothing written", file=sys.stderr)
        return False
    out = os.path.join(os.environ.get("OUT_DIR", HERE), name)
    with open(out, "w", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False, indent=1) + "\n")
    print(f"wrote {name}; no policy, organization, zone, cluster, host, tag or namespace name is recorded")
    return True


def main():
    opt = args()
    try:
        host = os.environ["VCFA_HOST"]
        token = read_secret("VCFA_PROVIDER_REFRESH_TOKEN_FILE")
        if not token:
            raise KeyError("VCFA_PROVIDER_REFRESH_TOKEN_FILE")
        vcp = read_secret("VC_PASSWORD_FILE")
        tpw = read_secret("VCFA_PASSWORD_FILE") if opt["probe"] else None
        if opt["probe"] and not (vcp and tpw and os.environ.get("VCFA_ORG") and os.environ.get("VCFA_USER") and os.environ.get("VC_HOST")):
            raise KeyError("the probe needs VC_HOST, VC_USER, VC_PASSWORD_FILE, VCFA_ORG, VCFA_USER and VCFA_PASSWORD_FILE")
    except (KeyError, PermissionError, OSError) as e:
        print(f"setting: {e}", file=sys.stderr)
        return 2
    register_environment()
    vc = None
    code = 3
    try:
        p = Provider(host, token)
        vc = VCenter(os.environ["VC_HOST"], os.environ["VC_USER"], vcp) if vcp and os.environ.get("VC_HOST") else None
        if opt["probe"]:
            t = Tenant(host, os.environ["VCFA_ORG"], os.environ["VCFA_USER"], tpw)
            print("infra_policy.py --probe: writes, on throwaway objects it deletes\n")
            code = probe(p, vc, t, opt)
            name = "infra-probe.json"
        else:
            print("infra_policy.py: the infrastructure policies, read from the provider" + (" and vCenter" if vc else "") + ", read-only\n")
            REC["read"] = read(p, vc)
            code = 1 if any(r["appliesToNothing"] for r in REC["read"]["policies"]) else 0
            name = "infra.json"
    except Failed as e:
        print(f"FAILED: {L.scrub(str(e))}", file=sys.stderr)
        REC["failed"] = L.scrub(str(e))
        name = "infra-probe.json" if opt["probe"] else "infra.json"
        code = 3
    finally:
        if vc:
            vc.close()
    if not write(name):
        return 4
    return code


if __name__ == "__main__":
    sys.exit(main())
