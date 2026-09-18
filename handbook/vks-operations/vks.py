#!/usr/bin/env python3
"""vks.py: the Kubernetes estate read from both places it answers from, and the chain that proves a node is an output.

A VKS cluster answers on two surfaces and they are not the same surface. The organization gateway carries a
fleet projection: one object per cluster, health and capacity, readable without entering any cluster. The
Supervisor namespace endpoint carries the declared cluster itself, a Cluster API object whose topology is what
day-2 actually edits. This reads both and reports where they differ:

  1. the FLEET SURFACE: the estate-management kinds at the org gateway, the verbs each DECLARES, and the verbs
     this identity is actually ALLOWED. Those are different answers and the gap is the point: the fleet kinds
     declare a full write set and permit only reads;
  2. the FLEET CONTENT: what one cluster object carries, which is allocatable against requested, per-component
     control-plane health, and a phase. This is the triage read, and it needs no kubeconfig;
  3. the DECLARED CLUSTER at the namespace endpoint: its cluster class, its Kubernetes version, the replica
     counts, and the variables its topology carries;
  4. the OWNERSHIP CHAIN: every node virtual machine walked back through its controller owner to the cluster.
     This is the chapter's central claim made structural rather than asserted: a node is an output, and a
     controller owns it;
  5. the SCOPE TRAP: the same list refused at cluster scope and served under a namespace, because the first
     reading of that refusal is "I am not allowed" and the correct one is "I asked in the wrong place".

Everything here is read-only. There is no probe flag and no write of any kind: this plane runs live workload
clusters, and the questions worth asking about it are all answerable by reading.

Run:
  export VCFA_HOST=<automation-fqdn> VCFA_ORG=<org>
  export VCFA_REFRESH_TOKEN_FILE=/path/to/refresh-token    # mode 0600
  export TLS_VERIFY=false                                  # only on a self-signed lab CA
  python3 vks.py
"""
import collections
import http.client
import json
import os
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

http.client._MAXHEADERS = 1000
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
CCI = "/cci/kubernetes"
CORE = "core.management.kubernetes.vmware.com/v1alpha1"
DP = "dataprotection.management.kubernetes.vmware.com/v1alpha1"
POL = "policy.management.kubernetes.vmware.com/v1alpha1"
CAPI = "cluster.x-k8s.io/v1beta1"
A3 = "infrastructure.cci.vmware.com/v1alpha3"
PROJ = "project.cci.vmware.com/v1alpha2"
K8SAUTHZ = "authorization.k8s.io/v1"
FLEET_GROUPS = ("core.management.kubernetes.vmware.com", "dataprotection.management.kubernetes.vmware.com",
                "policy.management.kubernetes.vmware.com")


def ctx():
    verify = os.environ.get("TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")
    return ssl.create_default_context() if verify else ssl._create_unverified_context()


class Labels:
    """Estate names become placeholders. The product's own vocabulary never does."""

    RESERVED = {"admin", "view", "edit", "user", "users", "group", "groups", "owner", "default", "system",
                "none", "all", "node-pool", "control-plane", "worker"}

    def __init__(self):
        self.maps = {}

    def reserve(self, *names):
        for n in names:
            if n:
                self.RESERVED = self.RESERVED | {str(n)}

    def get(self, family, name):
        if not name or str(name) in self.RESERVED:
            return name
        m = self.maps.setdefault(family, {})
        if name not in m:
            m[name] = f"{family}-{len(m) + 1}"
        return "{{%s}}" % m[name]

    def scrub(self, text):
        if not isinstance(text, str):
            return text
        known = [(real, label) for m in self.maps.values() for real, label in m.items()]
        for real, label in sorted(known, key=lambda kv: -len(kv[0])):
            text = re.sub(r"(?<![A-Za-z0-9-])" + re.escape(real) + r"(?![A-Za-z0-9-])",
                          "{{%s}}" % label, text)
        return UUID.sub("{{id}}", text)


class Surface:
    """One bearer, two endpoints: the org gateway, and a Supervisor namespace's own Kubernetes endpoint."""

    def __init__(self, host, org, refresh_token):
        self.host = host
        body = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": refresh_token}).encode()
        req = urllib.request.Request(
            f"https://{host}/oauth/tenant/{org}/token", data=body, method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
        with urllib.request.urlopen(req, context=ctx(), timeout=30) as r:
            self.bearer = json.loads(r.read())["access_token"]

    def send(self, base, method, path, body=None):
        headers = {"Authorization": f"Bearer {self.bearer}", "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(base.rstrip("/") + path, method=method, headers=headers,
                                     data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(req, context=ctx(), timeout=90) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, raw.decode(errors="replace")[:250]
        except (urllib.error.URLError, OSError) as e:
            return None, str(e)[:200]

    def gw(self, method, path, body=None):
        return self.send(f"https://{self.host}{CCI}", method, path, body)

    def ns(self, endpoint, method, path, body=None):
        return self.send(endpoint, method, path, body)

    def may(self, base, namespace, group, resource, verb):
        st, r = self.send(base, "POST", f"/apis/{K8SAUTHZ}/selfsubjectaccessreviews",
                          {"apiVersion": K8SAUTHZ, "kind": "SelfSubjectAccessReview",
                           "spec": {"resourceAttributes": {"namespace": namespace, "group": group,
                                                           "resource": resource, "verb": verb}}})
        s = (r.get("status") or {}) if isinstance(r, dict) else {}
        return bool(s.get("allowed")), str(s.get("reason") or "")


def main():
    host, org = os.environ["VCFA_HOST"], os.environ["VCFA_ORG"]
    refresh = open(os.environ["VCFA_REFRESH_TOKEN_FILE"], encoding="utf-8").read().strip()
    out_dir = os.environ.get("OUT_DIR", ".")
    s = Surface(host, org, refresh)
    L = Labels()
    GW = f"https://{host}{CCI}"
    print("vks.py: the Kubernetes estate, read from both places it answers from\n")

    st, pl = s.gw("GET", f"/apis/{PROJ}/projects")
    projects = [p["metadata"]["name"] for p in ((pl.get("items") or []) if st == 200 else [])]
    for p in projects:
        L.get("project", p)
    if not projects:
        raise SystemExit("no project is visible to this identity")

    # ---- 1. the fleet surface: what it declares against what it permits
    st, groups = s.gw("GET", "/apis")
    fleet = []
    for g in (groups.get("groups") or []):
        gv = g["preferredVersion"]["groupVersion"]
        if not any(gv.startswith(f) for f in FLEET_GROUPS):
            continue
        st, rl = s.gw("GET", f"/apis/{gv}")
        for r in (rl.get("resources") or []):
            if "/" in r["name"]:
                continue
            declared = sorted(r.get("verbs") or [])
            allowed = [v for v in ("get", "create", "update", "patch", "delete")
                       if s.may(GW, projects[0], gv.split("/")[0], r["name"], v)[0]]
            fleet.append({"group": gv.split("/")[0], "resource": r["name"], "declared": declared,
                          "allowed": allowed,
                          "declaresWrite": bool({"create", "update", "patch", "delete"} & set(declared)),
                          "permitsWrite": bool({"create", "update", "patch", "delete"} & set(allowed))})
    misleading = [f for f in fleet if f["declaresWrite"] and not f["permitsWrite"]]
    print(f"  fleet surface: {len(fleet)} kind(s); {sum(1 for f in fleet if f['declaresWrite'])} declare a write "
          f"verb and {sum(1 for f in fleet if f['permitsWrite'])} actually permit one")
    print(f"     kinds whose declaration promises more than the plane allows: {len(misleading)}")
    for f in fleet[:6]:
        print(f"       {f['resource']:<34} declares {','.join(f['declared'])[:34]:<36} allows {','.join(f['allowed'])}")

    # ---- 2. the fleet content
    clusters, addons = [], 0
    for p in projects:
        st, cl = s.gw("GET", f"/apis/{CORE}/namespaces/{p}/clusters")
        st2, cr = s.gw("GET", f"/apis/{CORE}/namespaces/{p}/clusterresources")
        addons += len((cr.get("items") or []) if isinstance(cr, dict) else [])
        for c in ((cl.get("items") or []) if isinstance(cl, dict) else []):
            stt = c.get("status") or {}
            cpu, mem = stt.get("allocatedCpu") or {}, stt.get("allocatedMemory") or {}
            health = stt.get("health") or {}
            comps = sorted(k for k in health if k.endswith("Health"))
            clusters.append({"project": L.scrub(p), "phase": stt.get("phase"), "state": stt.get("state"),
                             "cpu": {k: cpu.get(k) for k in ("allocatable", "requested", "allocatedPercentage")},
                             "memory": {k: mem.get(k) for k in ("allocatable", "requested", "allocatedPercentage")},
                             "healthComponents": comps, "healthMessage": health.get("message"),
                             "statusKeys": sorted(stt.keys()), "specKeys": sorted((c.get("spec") or {}).keys())})
    print(f"\n  fleet content: {len(clusters)} cluster(s) projected, {addons} managed component(s) listed")
    for c in clusters:
        print(f"     phase={c['phase']} state={c['state']} cpu {c['cpu']['requested']}/{c['cpu']['allocatable']} "
              f"({c['cpu']['allocatedPercentage']}%) memory {c['memory']['requested']}/{c['memory']['allocatable']} "
              f"({c['memory']['allocatedPercentage']}%) components={c['healthComponents']}")

    # ---- 3 + 4 + 5. the namespace endpoint
    declared, chain, scope = [], {"machines": 0, "vms": 0, "vmsOwned": 0, "owners": {}}, None
    rules = {}
    for p in projects:
        st, nss = s.gw("GET", f"/apis/{A3}/namespaces/{p}/supervisornamespaces")
        for n in ((nss.get("items") or []) if st == 200 else []):
            ep = (n.get("status") or {}).get("namespaceEndpointURL")
            nsname = n["metadata"]["name"]
            if not ep:
                continue
            L.get("namespace", nsname)
            if scope is None:
                st_c, rc = s.ns(ep, "GET", f"/apis/{CAPI}/clusters")
                st_n, rn = s.ns(ep, "GET", f"/apis/{CAPI}/namespaces/{nsname}/clusters")
                raw = (rc.get("message") if isinstance(rc, dict) else "") or ""
                # The platform names the CALLER back at you in an authorization refusal. Register it before
                # scrubbing, or a real person's username ships in the record; the publication kill list
                # catches this, which is how it was found, but the scrub is where it belongs.
                for who in re.findall(r'User "([^"]+)"', raw):
                    L.get("user", who)
                scope = {"clusterScoped": st_c, "namespaced": st_n, "message": L.scrub(raw)}
                st_r, rr = s.ns(ep, "POST", f"/apis/{K8SAUTHZ}/selfsubjectrulesreviews",
                                {"apiVersion": K8SAUTHZ, "kind": "SelfSubjectRulesReview",
                                 "spec": {"namespace": nsname}})
                sr = (rr.get("status") or {}) if isinstance(rr, dict) else {}
                rules["namespaceEndpoint"] = {"rules": len(sr.get("resourceRules") or []),
                                              "incomplete": bool(sr.get("incomplete"))}
            st_n, rn = s.ns(ep, "GET", f"/apis/{CAPI}/namespaces/{nsname}/clusters")
            for c in ((rn.get("items") or []) if st_n == 200 else []):
                sp, stt = c.get("spec") or {}, c.get("status") or {}
                topo = sp.get("topology") or {}
                wk = (topo.get("workers") or {}).get("machineDeployments") or []
                L.reserve(topo.get("class"), topo.get("version"))
                declared.append({
                    "namespace": L.scrub(nsname), "class": topo.get("class"), "version": topo.get("version"),
                    "controlPlaneReplicas": (topo.get("controlPlane") or {}).get("replicas"),
                    "workerPools": [{"class": w.get("class"), "replicas": w.get("replicas")} for w in wk],
                    "variables": sorted(v.get("name") for v in (topo.get("variables") or [])),
                    "phase": stt.get("phase"), "specKeys": sorted(sp.keys()),
                    "generation": c["metadata"].get("generation"),
                    "observedGeneration": stt.get("observedGeneration"),
                    "controlPlaneEndpointPort": (sp.get("controlPlaneEndpoint") or {}).get("port"),
                    "mayEdit": {v: s.may(ep, nsname, "cluster.x-k8s.io", "clusters", v)[0]
                                for v in ("get", "patch", "update", "delete")}})
            st_m, rm = s.ns(ep, "GET", f"/apis/{CAPI}/namespaces/{nsname}/machines")
            for m in ((rm.get("items") or []) if st_m == 200 else []):
                chain["machines"] += 1
                for o in (m["metadata"].get("ownerReferences") or []):
                    if o.get("controller"):
                        chain["owners"][o.get("kind")] = chain["owners"].get(o.get("kind"), 0) + 1
            for ver in ("v1alpha4", "v1alpha3", "v1alpha2"):
                st_v, rv = s.ns(ep, "GET", f"/apis/vmoperator.vmware.com/{ver}/namespaces/{nsname}/virtualmachines")
                if st_v == 200:
                    break
            for v in ((rv.get("items") or []) if st_v == 200 else []):
                chain["vms"] += 1
                if any(o.get("controller") for o in (v["metadata"].get("ownerReferences") or [])):
                    chain["vmsOwned"] += 1
    st_r, rr = s.gw("POST", f"/apis/{K8SAUTHZ}/selfsubjectrulesreviews",
                    {"apiVersion": K8SAUTHZ, "kind": "SelfSubjectRulesReview", "spec": {"namespace": projects[0]}})
    sr = (rr.get("status") or {}) if isinstance(rr, dict) else {}
    rules["orgGateway"] = {"rules": len(sr.get("resourceRules") or []), "incomplete": bool(sr.get("incomplete"))}

    print(f"\n  declared clusters at the namespace endpoints: {len(declared)}")
    for d in declared:
        print(f"     class={d['class']} version={d['version']} controlPlane={d['controlPlaneReplicas']} "
              f"workers={[w['replicas'] for w in d['workerPools']]} variables={d['variables']} phase={d['phase']}")
    print(f"\n  ownership: {chain['machines']} machine(s) owned by {chain['owners']}; "
          f"{chain['vmsOwned']} of {chain['vms']} virtual machines carry a controller owner")
    print(f"  the scope trap: the same list answers HTTP {scope['clusterScoped']} at cluster scope and "
          f"HTTP {scope['namespaced']} under a namespace")
    print(f"  self-rules: org gateway {rules['orgGateway']['rules']} rules "
          f"(incomplete={rules['orgGateway']['incomplete']}); namespace endpoint "
          f"{rules['namespaceEndpoint']['rules']} rules (incomplete={rules['namespaceEndpoint']['incomplete']})")

    payload = {"captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "fleetKinds": fleet, "misleadingDeclarations": len(misleading), "fleetClusters": clusters,
               "managedComponents": addons, "declaredClusters": declared, "ownership": chain,
               "scope": scope, "selfRules": rules}
    text = L.scrub(UUID.sub("{{id}}", json.dumps(payload, indent=1, ensure_ascii=False)))
    for secret in (s.bearer, refresh, host, org):
        assert secret not in text, "an estate value reached the record"
    for word in {d["class"] for d in declared} | {d["version"] for d in declared}:
        if word:
            assert word in text, f"the scrub replaced {word!r}, which is the product's own vocabulary"
    bare = re.sub(r"\{\{[^}]*\}\}", "", text)
    for fam, m in L.maps.items():
        for nm in m:
            if nm and re.search(r"(?<![A-Za-z0-9-])" + re.escape(nm) + r"(?![A-Za-z0-9-])", bare):
                shape = re.sub(r"[A-Za-z]", "a", re.sub(r"[0-9]", "9", nm))
                raise SystemExit(f"FATAL: a {fam} name ({len(nm)} characters, shape {shape}) reached the record")
    os.makedirs(out_dir, exist_ok=True)
    open(os.path.join(out_dir, "vks.json"), "w", encoding="utf-8").write(text + "\n")
    print(f"\nwrote vks.json ({len(fleet)} fleet kinds, {len(clusters)} projected cluster(s), "
          f"{len(declared)} declared cluster(s)); every organization name replaced by a placeholder")


if __name__ == "__main__":
    main()
