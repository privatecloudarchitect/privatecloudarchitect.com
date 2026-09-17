#!/usr/bin/env python3
"""inventory.py - the construct model, read from your own estate.

Two records, both read-only through the Cloud Consumption Interface with an organization's OAuth bearer:

  taxonomy.json   what the interface declares: every VMware API group, its kinds, whether a kind is published
                  at the top level (cluster-scoped) or lives under a project (namespaced), the verbs it allows,
                  and how many of each cluster-scoped kind this organization can see
  naming.json     an audit of every name above against the naming standard shipped beside this script
                  (naming-standard.json): per construct, how many of your objects conform to the convention,
                  and the grammar each one should follow. Counts and verdicts only, never a name

  estate.json     the containment tree as it stands: the organization, its projects, what each project is bound
                  to (regions, classes, VPCs, subnets, service engine groups, infra policies), its role bindings,
                  its Supervisor namespaces with the fields each one bound at create (region, zone, class, VPC,
                  storage classes, VM classes) and its phase, and behind each namespace's endpoint the virtual
                  machines and VKS clusters it holds

Every name that belongs to your estate is replaced by a stable placeholder on the way into the records
({{project-1}}, {{namespace-2}}, {{region-1}}, {{zone-2}}, {{class-1}}, {{vpc-1}}, {{org}}, {{id}}), so the records
can be published and diffed; the script refuses to write a record in which any estate name survived. Stdlib only. No token is printed or written.

Env:  VCFA_HOST, VCFA_ORG, VCFA_REFRESH_TOKEN_FILE; TLS_VERIFY=false on a self-signed lab CA; OUT_DIR (default .)
Exit: 0 the records were written · 1 the mint or the discovery failed
"""

import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

CCI = "/cci/kubernetes"
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
NS_FIELDS = ("regionName", "zoneName", "className", "vpcName", "segName", "storageClasses", "vmClasses", "initialClassConfigOverrides", "description")


def ctx():
    verify = os.environ.get("TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")
    return ssl.create_default_context() if verify else ssl._create_unverified_context()


class Labels:
    """Stable labels for estate names: the first region seen is {{region-1}}, the second project is project-2."""
    def __init__(self):
        self.maps = {}

    def get(self, family, name, braces=True):
        m = self.maps.setdefault(family, {})
        if name not in m:
            m[name] = f"{family}-{len(m) + 1}"
        return "{{%s}}" % m[name] if braces else m[name]


class Cci:
    def __init__(self, host, org, refresh_token):
        self.host = host
        body = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": refresh_token}).encode()
        req = urllib.request.Request(f"https://{host}/oauth/tenant/{org}/token", data=body, method="POST", headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
        with urllib.request.urlopen(req, context=ctx(), timeout=30) as r:
            self.bearer = json.loads(r.read())["access_token"]

    def get(self, path, absolute=False):
        url = path if absolute else f"https://{self.host}{CCI}{path}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {self.bearer}", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, context=ctx(), timeout=60) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, raw.decode(errors="replace")[:200]
        except (urllib.error.URLError, OSError) as e:
            return None, str(e)

    def items(self, path, absolute=False):
        st, body = self.get(path, absolute)
        if st == 200 and isinstance(body, dict):
            return st, body.get("items", [])
        return st, []


# ---- the naming audit: the names above, against the standard shipped beside this script
STANDARD_FILE = "naming-standard.json"
# which construct each family of discovered object is named as
AUDIT_MAP = (
    ("project", "projects"), ("supervisor-namespace", "namespaces"), ("region", "regions"), ("supervisor-zone", "zones"),
    ("namespace-class", "namespace-classes"), ("vpc", "vpcs"), ("vpc-subnet", "subnets"), ("vm-class", "vm-classes"),
    ("virtualmachine", "virtual-machines"), ("vks-cluster", "vks-clusters"),
)


def load_standard():
    """The naming standard as published beside this script; absent means the audit is skipped."""
    here = os.path.dirname(os.path.abspath(__file__))
    for path in (os.path.join(here, STANDARD_FILE), STANDARD_FILE):
        if os.path.exists(path):
            return {r["construct"]: r for r in json.load(open(path, encoding="utf-8"))["constructs"]}
    return None


def audit_names(standard, observed):
    """Count conformance per construct. Takes real names, returns counts and grammars: no name is kept."""
    out = {}
    for construct, family in AUDIT_MAP:
        names = observed.get(family) or []
        rule = standard.get(construct)
        if not names or not rule:
            continue
        rx = re.compile(rule["pattern"])
        conform = sum(1 for n in names if rx.match(n))
        out[construct] = {"objects": len(names), "conform": conform, "convention": rule["convention"],
                          "example": rule["example"], "pattern": rule["pattern"],
                          "verdict": "keep" if conform == len(names) else ("refine" if conform else "rename")}
    return out


def main():
    host, org = os.environ["VCFA_HOST"], os.environ["VCFA_ORG"]
    refresh = open(os.environ["VCFA_REFRESH_TOKEN_FILE"], encoding="utf-8").read().strip()
    out_dir = os.environ.get("OUT_DIR", ".")
    c = Cci(host, org, refresh); L = Labels(); observed = {}
    print("inventory.py: the construct model read through the Cloud Consumption Interface, read-only\n")
    # ---- 1. the taxonomy, from discovery
    st, groups = c.get("/apis")
    if st != 200:
        print(f"FATAL: discovery answered HTTP {st}"); sys.exit(1)
    taxonomy = []
    for g in groups.get("groups", []):
        if "vmware.com" not in g["name"]:
            continue
        for v in g.get("versions", []):
            st, rl = c.get(f"/apis/{v['groupVersion']}")
            if st != 200:
                continue
            for res in rl.get("resources", []):
                if "/" in res["name"]:
                    continue
                entry = {"group": g["name"], "version": v["version"], "kind": res.get("kind"), "resource": res["name"], "namespaced": bool(res.get("namespaced")), "verbs": res.get("verbs", [])}
                if "list" in entry["verbs"] and not entry["namespaced"]:
                    st2, items = c.items(f"/apis/{v['groupVersion']}/{res['name']}")
                    entry["count"] = len(items) if st2 == 200 else f"HTTP {st2}"
                taxonomy.append(entry)
    kinds = sorted({(e["group"], e["kind"]) for e in taxonomy})
    print(f"  taxonomy: {len({e['group'] for e in taxonomy})} VMware API groups, {len(kinds)} kinds; "
          f"{sum(1 for e in taxonomy if not e['namespaced'])} published at the top level, {sum(1 for e in taxonomy if e['namespaced'])} under a project")
    # ---- 2. the estate: published objects
    def count(entry_resource):
        for e in taxonomy:
            if e["resource"] == entry_resource and isinstance(e.get("count"), int):
                return e["count"]
        return None
    estate = {"organization": "{{org}}", "published": {}, "projects": []}
    st, regions = c.items("/apis/topology.cci.vmware.com/v1alpha2/regions")
    st, zones = c.items("/apis/topology.cci.vmware.com/v1alpha1/zones")
    st, classes = c.items("/apis/infrastructure.cci.vmware.com/v1alpha2/supervisornamespaceclasses")
    st, vpcs = c.items("/apis/vpc.nsx.vmware.com/v1alpha1/vpcs")
    st, subnets = c.items("/apis/vpc.nsx.vmware.com/v1alpha1/subnets")
    st, scq = c.items("/apis/infrastructure.cci.vmware.com/v1alpha1/regionstorageclassquotas")
    st, vmcs = c.items("/apis/infrastructure.cci.vmware.com/v1alpha1/regionvirtualmachineclasssummaries")
    observed["regions"] = [r["metadata"]["name"] for r in regions]
    observed["zones"] = [z["metadata"]["name"] for z in zones]
    observed["namespace-classes"] = [k["metadata"]["name"] for k in classes]
    observed["vpcs"] = [v["metadata"]["name"] for v in vpcs]
    observed["subnets"] = [s["metadata"]["name"] for s in subnets]
    observed["vm-classes"] = [m["metadata"]["name"] for m in vmcs]
    estate["published"] = {
        "regions": [{"name": L.get("region", r["metadata"]["name"]), "loadBalancerType": (r.get("status") or {}).get("loadBalancerType")} for r in regions],
        "zones": [{"name": L.get("zone", z["metadata"]["name"]), "region": L.get("region", (z.get("spec") or {}).get("regionName", "")), "cpuLimit": (z.get("spec") or {}).get("cpuLimit"), "memoryLimit": (z.get("spec") or {}).get("memoryLimit"), "cpuUsed": (z.get("status") or {}).get("cpuUsed"), "memoryUsed": (z.get("status") or {}).get("memoryUsed")} for z in zones],
        "namespace_classes": [{"name": L.get("class", k["metadata"]["name"])} for k in classes],
        "vpcs": [{"name": L.get("vpc", v["metadata"]["name"]), "region": L.get("region", (v.get("spec") or {}).get("regionName", "")), "privateIPs": len((v.get("spec") or {}).get("privateIPs") or [])} for v in vpcs],
        "subnets": len(subnets), "storage_class_quotas": len(scq), "vm_class_summaries": len(vmcs),
    }
    print(f"  published: {len(regions)} region(s), {len(zones)} zone(s), {len(classes)} namespace class(es), {len(vpcs)} VPC(s), {len(subnets)} subnet(s), {len(scq)} storage-class quota(s), {len(vmcs)} VM class summaries")
    # ---- 3. the projects and their contents
    st, projects = c.items("/apis/project.cci.vmware.com/v1alpha2/projects")
    observed["projects"] = [p["metadata"]["name"] for p in projects]
    observed["namespaces"], observed["virtual-machines"], observed["vks-clusters"] = [], [], []
    for p in projects:
        pname = p["metadata"]["name"]; label = L.get("project", pname)
        proj = {"name": label, "bindings": {}, "roleBindings": None, "namespaces": []}
        for family, path in (("regions", "topology.cci.vmware.com/v1alpha1/namespaces/%s/regionbindings"), ("classes", "infrastructure.cci.vmware.com/v1alpha1/namespaces/%s/supervisornamespaceclassbindings"),
                             ("vpcs", "vpc.nsx.vmware.com/v1alpha1/namespaces/%s/vpcbindings"), ("subnets", "vpc.nsx.vmware.com/v1alpha1/namespaces/%s/subnetbindings"),
                             ("serviceEngineGroups", "avi.vmware.com/v1alpha1/namespaces/%s/segbindings"), ("infraPolicies", "infrastructure.cci.vmware.com/v1alpha1/namespaces/%s/regioninfrapolicybindings")):
            st, items = c.items("/apis/" + path % pname)
            proj["bindings"][family] = len(items) if st == 200 else f"HTTP {st}"
        st, rbs = c.items(f"/apis/authorization.cci.vmware.com/v1alpha1/namespaces/{pname}/projectrolebindings")
        def role_of(b):
            sp = b.get("spec") or {k: v for k, v in b.items() if k not in ("metadata", "apiVersion", "kind")}
            for k in ("projectRoleName", "projectRole", "role", "roleName"):
                if isinstance(sp.get(k), str):
                    return sp[k]
            ref = sp.get("roleRef") or sp.get("projectRoleRef") or {}
            return ref.get("name") if isinstance(ref, dict) else None
        proj["roleBindings"] = {"count": len(rbs), "roles": sorted({role_of(b) or "?" for b in rbs}), "fields": sorted(k for k in rbs[0].keys() if k not in ("metadata", "apiVersion", "kind")) if rbs else []} if st == 200 else f"HTTP {st}"
        st, imgs = c.items(f"/apis/image.cci.vmware.com/v1alpha1/namespaces/{pname}/images")
        proj["images"] = len(imgs) if st == 200 else f"HTTP {st}"
        st, cats = c.items(f"/apis/catalog.cci.vmware.com/v1alpha1/namespaces/{pname}/catalogitems")
        proj["catalogItems"] = len(cats) if st == 200 else f"HTTP {st}"
        st, nss = c.items(f"/apis/infrastructure.cci.vmware.com/v1alpha3/namespaces/{pname}/supervisornamespaces")
        observed["namespaces"] += [n["metadata"]["name"] for n in nss]
        for n in nss:
            sp, stt = n.get("spec") or {}, n.get("status") or {}
            ns = {"name": L.get("namespace", n["metadata"]["name"]), "phase": stt.get("phase"),
                  "bound": {"region": L.get("region", sp["regionName"]) if sp.get("regionName") else None, "zone": L.get("zone", sp["zoneName"]) if sp.get("zoneName") else None,
                            "class": L.get("class", sp["className"]) if sp.get("className") else None, "vpc": L.get("vpc", sp["vpcName"]) if sp.get("vpcName") else None,
                            "storageClasses": len(sp.get("storageClasses") or []), "vmClasses": len(sp.get("vmClasses") or []), "classOverrides": bool(sp.get("initialClassConfigOverrides"))},
                  "specFields": sorted(sp.keys()), "workloads": {}}
            ep = stt.get("namespaceEndpointURL")
            if ep:
                supervisor_ns = n["metadata"]["name"]
                for wl, family, path in (("virtualMachines", "virtual-machines", f"/apis/vmoperator.vmware.com/v1alpha5/namespaces/{supervisor_ns}/virtualmachines"),
                                         ("vksClusters", "vks-clusters", f"/apis/cluster.x-k8s.io/v1beta1/namespaces/{supervisor_ns}/clusters")):
                    st, items = c.items(ep.rstrip("/") + path, absolute=True)
                    ns["workloads"][wl] = len(items) if st == 200 else f"HTTP {st}"
                    if st == 200:
                        observed[family] += [i["metadata"]["name"] for i in items]
            proj["namespaces"].append(ns)
        estate["projects"].append(proj)
        print(f"  {label}: bindings {proj['bindings']}; role bindings {proj['roleBindings']}; images {proj['images']}; catalog items {proj['catalogItems']}; namespaces {len(nss)}")
        for ns in proj["namespaces"]:
            print(f"     {ns['name']}: phase {ns['phase']}; bound {ns['bound']}; workloads {ns['workloads']}")
    # ---- 4. the naming audit, on the real names, keeping only counts
    standard = load_standard(); naming = None
    if standard:
        naming = audit_names(standard, observed)
        total = sum(v["objects"] for v in naming.values()); ok = sum(v["conform"] for v in naming.values())
        print(f"\n  naming: {ok} of {total} names conform to the standard, across {len(naming)} constructs")
        for construct, v in naming.items():
            print(f"     {construct:<22} {v['conform']:>3} of {v['objects']:<3} {v['verdict']:<7} {v['convention']}  e.g. {v['example']}")
    else:
        print(f"\n  naming: skipped ({STANDARD_FILE} is not beside this script)")

    # ---- 5. write, sanitized
    stamp = __import__("time").strftime("%Y-%m-%dT%H:%M:%SZ", __import__("time").gmtime())
    text = json.dumps({"captured_utc": stamp, "taxonomy": taxonomy}, indent=1, ensure_ascii=False)
    text2 = json.dumps({"captured_utc": stamp, **estate}, indent=1, ensure_ascii=False)
    text2 = UUID.sub("{{id}}", text2)
    for secret in (c.bearer, refresh, host, org):
        assert secret not in text and secret not in text2, "an estate value reached a record"
    bare = re.sub(r"\{\{[^}]*\}\}", "", text2)   # the placeholders themselves are not leaks, even when a real name happens to match one
    for fam, m in L.maps.items():
        for name in m:
            m2 = re.search(r"(?<![A-Za-z0-9-])" + re.escape(name) + r"(?![A-Za-z0-9-])", bare)
            if m2:
                shape = re.sub(r"[A-Za-z]", "a", re.sub(r"[0-9]", "9", name)); around = bare[max(0, m2.start() - 60):m2.start()].replace(name, "*" * len(name))
                raise SystemExit(f"FATAL: a {fam} name ({len(name)} characters, shape {shape}) reached the estate record near ...{around!r}; not writing it")
    os.makedirs(out_dir, exist_ok=True)
    open(os.path.join(out_dir, "taxonomy.json"), "w", encoding="utf-8").write(text + "\n")
    open(os.path.join(out_dir, "estate.json"), "w", encoding="utf-8").write(text2 + "\n")
    wrote = "taxonomy.json (%d kinds) and estate.json (%d project(s))" % (len(taxonomy), len(projects))
    if naming is not None:
        # The naming record may only carry values that came from the published standard, plus counts. Checking that
        # by whitelist rather than by scanning for estate names is strictly stronger, and it does not misfire when an
        # object is named after a word the grammar itself uses (a class literally called "large", say).
        for construct, v in naming.items():
            rule = standard[construct]
            assert set(v) == {"objects", "conform", "convention", "example", "pattern", "verdict"}, construct
            assert isinstance(v["objects"], int) and isinstance(v["conform"], int), construct
            assert v["verdict"] in ("keep", "refine", "rename"), construct
            for field in ("convention", "example", "pattern"):
                assert v[field] == rule[field], f"{construct}: {field} is not the standard's own value"
        text3 = json.dumps({"captured_utc": stamp, "audited_objects": sum(v["objects"] for v in naming.values()), "constructs": naming}, indent=1, ensure_ascii=False)
        open(os.path.join(out_dir, "naming.json"), "w", encoding="utf-8").write(text3 + "\n")
        wrote += " and naming.json (counts only)"
    print(f"\nwrote {wrote}; every estate name replaced by a stable label")


if __name__ == "__main__":
    main()
