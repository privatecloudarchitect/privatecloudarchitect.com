#!/usr/bin/env python3
"""doors.py: the same virtual machine, built through each door the platform offers, and what each leaves behind.

There are two mechanisms for putting a VM on a VCF 9.1 Supervisor, and three doors, because one mechanism has
two request surfaces:

  DIRECT       a VirtualMachine object POSTed to the namespace's own Kubernetes endpoint. This is what
               ``kubectl apply -f <file>.vm.yaml`` does; the CLI is a convenience over this call.
  API          a VCF Automation blueprint that wraps that same VirtualMachine in a CCI.Supervisor.Resource,
               released as a version and deployed by a programmatic request.
  CATALOG      the identical released version, requested from the project's catalog. Same mechanism as API,
               different request surface: one is a pipeline, the other is a person filling a form.

The question this script answers is not which is faster. It is **what is different afterwards**, because that
is what a design decision actually turns on. It reports four things:

  1. the DOORS that are open on this estate at all, and what each one needs before it will open;
  2. with --probe-doors, the SAME MACHINE built twice, once through the direct door and once through the
     catalog, read back field by field and compared. Everything it creates it deletes, and it verifies removal;
  3. what the deployment record CLAIMS and what that claim BUYS: the Day-2 action catalogue that exists on a
     claimed machine and does not exist on an unclaimed one, plus the owner, the lease and the provenance;
  4. the TEARDOWN of each, timed, because the coupling shows up there more plainly than anywhere else.

Without --probe-doors nothing here writes: it inventories the doors and reads an existing deployment's action
catalogue. Estate names are replaced by stable placeholders and the script refuses to write a record in which
one survived. Field names, verbs, action ids, HTTP statuses and the platform's own error strings are the
product's vocabulary and are kept, because they are the lesson.

Run:
  export VCFA_HOST=<automation-fqdn> VCFA_ORG=<org>
  export VCFA_REFRESH_TOKEN_FILE=/path/to/refresh-token     # mode 0600
  export DOORS_PROJECT=<project>                            # optional; first visible project otherwise
  export DOORS_NAMESPACE=<supervisor-namespace>             # required for --probe-doors
  export TLS_VERIFY=false                                   # only on a self-signed lab CA
  python3 doors.py [--probe-doors]

The probe needs a namespace that has a VM image bound to it and storage quota left. Both are checked before
anything is created, and it says which one is missing rather than letting an admission webhook say it later.
"""
import collections
import http.client
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

http.client._MAXHEADERS = 1000
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
CCI = "/cci/kubernetes"
A3 = "infrastructure.cci.vmware.com/v1alpha3"
PROJ = "project.cci.vmware.com/v1alpha2"
VMOP = "vmoperator.vmware.com"
BP = "blueprint.cci.vmware.com/v1alpha1"
CATG = "catalog.cci.vmware.com/v1alpha1"
PREFIX = "handbook-doors"
SUFFIX = {"Ki": 1024, "Mi": 1024 ** 2, "Gi": 1024 ** 3, "Ti": 1024 ** 4,
          "K": 1000, "M": 1000 ** 2, "G": 1000 ** 3, "T": 1000 ** 4}


def ctx():
    verify = os.environ.get("TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")
    return ssl.create_default_context() if verify else ssl._create_unverified_context()


def qty(v):
    """A Kubernetes quantity, which on this object arrives in three different notations.

    The same StoragePolicyQuota reports one extension's usage as a bare byte count, another's as '268Gi', and
    a third's as a bare number in neither unit. Parse the suffix when there is one and treat a bare number as
    bytes, which is what the authoritative `total` array uses.
    """
    m = re.match(r"^(\d+(?:\.\d+)?)([A-Za-z]*)$", str(v).strip())
    return int(float(m.group(1)) * SUFFIX.get(m.group(2), 1)) if m else 0


class Labels:
    """Estate names become placeholders. The product's own vocabulary never does."""

    RESERVED = {"admin", "view", "edit", "user", "owner", "default", "system", "none", "all",
                "VirtualMachine", "Namespace", "VM", "Delete", "PowerOn", "PowerOff"}

    def __init__(self):
        self.maps = {}

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
            text = re.sub(r"(?<![A-Za-z0-9-])" + re.escape(real) + r"(?![A-Za-z0-9-])", "{{%s}}" % label, text)
        return UUID.sub("{{id}}", text)


class Estate:
    """One bearer, three base URLs: the org gateway, the classic API, and each namespace's own endpoint."""

    def __init__(self, host, org, refresh_token):
        self.host = host
        body = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": refresh_token}).encode()
        req = urllib.request.Request(
            f"https://{host}/oauth/tenant/{org}/token", data=body, method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
        with urllib.request.urlopen(req, context=ctx(), timeout=30) as r:
            self.bearer = json.loads(r.read())["access_token"]

    def call(self, url, method="GET", payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {self.bearer}", "Accept": "application/json",
            **({"Content-Type": "application/json"} if data else {})})
        try:
            with urllib.request.urlopen(req, context=ctx(), timeout=180) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, {}
        except (urllib.error.URLError, OSError):
            return None, {}

    def gw(self, path, method="GET", payload=None):
        return self.call(f"https://{self.host}{CCI}{path}", method, payload)

    def api(self, path, method="GET", payload=None):
        return self.call(f"https://{self.host}{path}", method, payload)

    def ns(self, endpoint, path, method="GET", payload=None):
        return self.call(endpoint.rstrip("/") + path, method, payload)


def msg(r):
    if isinstance(r, dict):
        return str(r.get("message") or r.get("detail") or r.get("error") or "")
    return ""


# --------------------------------------------------------------------------- what each door needs

def survey(e, L, project):
    """What has to exist before each door will open, read rather than listed from memory.

    This is the half of the comparison nobody writes down. Both doors end at the same object, so the honest
    difference is in the prerequisites, and every one of them is a thing that can be missing.
    """
    needs = {"direct": [], "automation": []}

    st, nss = e.gw(f"/apis/{A3}/namespaces/{project}/supervisornamespaces")
    spaces = (nss.get("items") or []) if st == 200 else []
    with_endpoint = [n for n in spaces if (n.get("status") or {}).get("namespaceEndpointURL")]
    needs["direct"].append({"need": "a Supervisor namespace, vended to you", "kind": "SupervisorNamespace",
                            "present": len(spaces), "usable": len(with_endpoint),
                            "note": "usable means it publishes its own namespaceEndpointURL; that URL is the door"})

    per_ns = []
    for n in with_endpoint:
        name, url = n["metadata"]["name"], (n.get("status") or {}).get("namespaceEndpointURL")
        L.get("namespace", name)
        st, imgs = e.ns(url, f"/apis/{VMOP}/v1alpha5/namespaces/{name}/virtualmachineimages")
        images = len((imgs.get("items") or []) if st == 200 else [])
        st, q = e.ns(url, f"/apis/cns.vmware.com/v1alpha1/namespaces/{name}/storagepolicyquotas")
        lim = used = 0
        for item in ((q.get("items") or []) if st == 200 else []):
            conv = json.loads((item.get("metadata") or {}).get("annotations", {})
                              .get("cns.vmware.com/conversion", "{}") or "{}")
            stt = conv.get("status") or {}
            lim += qty(stt.get("appliedLimit") or (item.get("spec") or {}).get("limit") or 0)
            used += sum(qty(t["scQuotaUsage"]["used"]) for t in (stt.get("total") or []))
        st, cls = e.ns(url, f"/apis/{VMOP}/v1alpha5/namespaces/{name}/virtualmachineclasses")
        # Register every machine name that exists here. A VM name is an estate identifier and it turns up in
        # places the scrubber would otherwise never see it, notably inside a deployment's resourceLink, which
        # is a single opaque string. A scrubber only replaces what it was told about.
        st_v, vms_ = e.ns(url, f"/apis/{VMOP}/v1alpha5/namespaces/{name}/virtualmachines")
        for v in ((vms_.get("items") or []) if st_v == 200 else []):
            L.get("machine", v["metadata"]["name"])
        per_ns.append({"namespace": L.get("namespace", name), "imagesBound": images,
                       "classes": len((cls.get("items") or []) if st == 200 else []),
                       "quotaGiB": round(lim / SUFFIX["Gi"], 1), "usedGiB": round(used / SUFFIX["Gi"], 1),
                       "freeGiB": round((lim - used) / SUFFIX["Gi"], 1),
                       "couldBuildAVm": images > 0 and (lim - used) > 20 * SUFFIX["Gi"]})
    needs["direct"].append({"need": "a VM image bound to THAT namespace", "kind": "VirtualMachineImage",
                            "present": sum(1 for x in per_ns if x["imagesBound"]), "usable": len(per_ns),
                            "note": "images are namespace scoped here, so a namespace with none cannot build a "
                                    "VM even though the cluster catalogue is large"})
    needs["direct"].append({"need": "storage quota with room for the boot disk", "kind": "StoragePolicyQuota",
                            "present": sum(1 for x in per_ns if x["freeGiB"] > 20), "usable": len(per_ns),
                            "note": "the refusal arrives from an admission webhook at the create call and names "
                                    "the reason"})

    st, bps = e.gw(f"/apis/{BP}/namespaces/{project}/blueprints")
    st2, vers = e.gw(f"/apis/{BP}/namespaces/{project}/blueprintversions")
    st3, its = e.gw(f"/apis/{CATG}/namespaces/{project}/catalogitems")
    needs["automation"] = [
        {"need": "everything the direct door needs, unchanged", "kind": "-", "present": None, "usable": None,
         "note": "the blueprint applies the same object into the same namespace; nothing above goes away"},
        {"need": "a project you are a member of", "kind": "Project", "present": 1, "usable": 1,
         "note": "the deployment is scoped to it and the catalog item is published to it"},
        {"need": "a blueprint holding the manifest", "kind": "Blueprint",
         "present": len((bps.get("items") or []) if st == 200 else []), "usable": None,
         "note": "authoring changes nothing; it is a document until a version is released"},
        {"need": "a released version", "kind": "BlueprintVersion",
         "present": len((vers.get("items") or []) if st2 == 200 else []), "usable": None,
         "note": "the version object's name is derived, not chosen: it must equal '<blueprint>:<version>'"},
        {"need": "a catalog item, for the catalog door only", "kind": "CatalogItem",
         "present": len((its.get("items") or []) if st3 == 200 else []), "usable": None,
         "note": "released with publishToCatalog true; the API door does not need this one"},
    ]
    return needs, per_ns


# --------------------------------------------------------------------------- what a claim buys

def claims(e, L):
    """Read an existing deployment's action catalogue: what a claimed machine can be asked to do.

    A Day-2 action is not a property of the virtual machine. It is a property of the RECORD that claims it, so
    it is readable only from the deployment side, and an identical machine with no record has none of them.
    """
    st, dep = e.api("/deployment/api/deployments?size=200")
    deployments = (dep.get("content") or []) if isinstance(dep, dict) else []
    fields = sorted(deployments[0].keys()) if deployments else []
    found = None
    for d in deployments:
        st, rs = e.api(f"/deployment/api/deployments/{d['id']}/resources?size=200")
        rows = (rs.get("content") or []) if isinstance(rs, dict) else []
        vm = next((r for r in rows if r.get("type") == "CCI.Supervisor.Resource"
                   and "VirtualMachine" in str((r.get("properties") or {}).get("resourceLink") or "")), None)
        if not vm:
            continue
        st, da = e.api(f"/deployment/api/deployments/{d['id']}/actions")
        st, ra = e.api(f"/deployment/api/deployments/{d['id']}/resources/{vm['id']}/actions")
        # Register the machine named by the claim before scrubbing it. Do not rely on the survey having seen
        # it: the survey lists LIVE machines, and a deployment can still claim one that no longer exists, so
        # the name a retired record carries would otherwise reach the file unreplaced.
        _link = str((vm.get("properties") or {}).get("resourceLink") or "")
        _m = re.match(r"^cci:([^:]+):([^:]+):[^:]+:VirtualMachine:(.+)$", _link)
        if _m:
            L.get("machine", _m.group(3))
        found = {"deploymentActions": sorted(a.get("name") for a in (da or []) if a.get("name")),
                 "resourceActions": sorted(a.get("name") for a in (ra or []) if a.get("name")),
                 "linkShape": L.scrub(_link),
                 "recordFields": fields}
        break
    return found or {"deploymentActions": [], "resourceActions": [], "linkShape": None, "recordFields": fields}


def credentials(e, L, project, vc_host=None):
    """One credential, presented to every door, with what each one answers.

    The question "what identity do I need for this" is usually answered from documentation. It does not have
    to be: this holds a single tenant bearer and presents it to each door in turn. Three of the four take it.
    The fourth does not, and the shape of that refusal is the whole point, so it is recorded rather than
    described.
    """
    rows = []
    st, _ = e.api("/deployment/api/deployments?size=1")
    rows.append({"door": "VCF Automation, API", "surface": "/deployment/api",
                 "answeredTheTenantBearer": st, "identityDomain": "the organization's identity provider"})
    st, _ = e.api("/catalog/api/items?size=1")
    rows.append({"door": "VCF Automation, catalog", "surface": "/catalog/api",
                 "answeredTheTenantBearer": st, "identityDomain": "the organization's identity provider"})
    eps = _endpoints(e, project)
    st = None
    if eps:
        _p, ns, url = eps[0]
        st, _ = e.ns(url, f"/apis/{VMOP}/v1alpha5/namespaces/{ns}/virtualmachines")
    rows.append({"door": "Supervisor, direct", "surface": "the namespace's own Kubernetes endpoint",
                 "answeredTheTenantBearer": st, "identityDomain": "the organization's identity provider"})
    if vc_host:
        code = None
        try:
            req = urllib.request.Request(f"https://{vc_host}/api/vcenter/vm",
                                         headers={"Authorization": f"Bearer {e.bearer}"})
            with urllib.request.urlopen(req, context=ctx(), timeout=45) as r:
                code = r.status
        except urllib.error.HTTPError as ex:
            code = ex.code
        except Exception:
            code = None
        rows.append({"door": "vCenter", "surface": "/api/vcenter", "answeredTheTenantBearer": code,
                     "identityDomain": "vSphere SSO, a different directory",
                     "takesInstead": "a session id from POST /api/session, or Basic, as an SSO principal"})
    same = sum(1 for r in rows if r["answeredTheTenantBearer"] == 200)
    print(f"  one credential, {len(rows)} door(s): {same} answered it, "
          + ", ".join(f"{r['door']} {r['answeredTheTenantBearer']}" for r in rows))
    return {"credentialHeld": "a tenant bearer, minted from a refresh token at /oauth/tenant/<org>/token",
            "doors": rows, "doorsThatTakeIt": same,
            "note": "a door answering 200 here is answering this identity; what it then PERMITS is the "
                    "project role tier and the four dials, which the access-control chapter covers"}


def _endpoints(e, project):
    """Every namespace in the project that publishes its own Kubernetes endpoint."""
    out = []
    st, nss = e.gw(f"/apis/{A3}/namespaces/{project}/supervisornamespaces")
    for n in ((nss.get("items") or []) if st == 200 else []):
        u = (n.get("status") or {}).get("namespaceEndpointURL")
        if u:
            out.append((project, n["metadata"]["name"], u))
    return out


# --------------------------------------------------------------------------- the fourth door

def probe_vcenter(e, L, vc_host, session, namespaces):
    """The door this chapter does not count as one of the three, because it does not reach the same machine.

    A virtual machine created straight in vCenter is not a VirtualMachine object. Nothing above vCenter
    declares it, counts it, or claims it, which is not a governance failure but a statement about where the
    tenancy model begins. This measures each of those absences rather than asserting them, and deletes what
    it made.

    Needs a vCenter session credential, which is a DIFFERENT identity from the one the rest of this script
    uses; that difference is the finding on the access side.
    """
    name = f"{PREFIX}-vcenter-native"

    def vc(path, method="GET", payload=None):
        """vCenter's own caller. The bearer the rest of this script holds answers 401 here, which is the
        point: these are two identity domains, not two tiers of one."""
        data = json.dumps(payload).encode() if payload is not None else None
        h = {"vmware-api-session-id": session, "Accept": "application/json"}
        if data:
            h["Content-Type"] = "application/json"
        try:
            with urllib.request.urlopen(urllib.request.Request(f"https://{vc_host}{path}", data=data,
                                                               method=method, headers=h),
                                        context=ctx(), timeout=180) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as ex:
            try:
                return ex.code, json.loads(ex.read())
            except ValueError:
                return ex.code, {}
        except (urllib.error.URLError, OSError):
            return None, {}
    out = {"created": None, "declaredByANamespace": None, "claimedByADeployment": None,
           "tenantQuotaDeltaBytes": None, "deleted": None}

    def quota():
        total = 0
        for _p, ns, url in namespaces:
            st, q = e.ns(url, f"/apis/cns.vmware.com/v1alpha1/namespaces/{ns}/storagepolicyquotas")
            for item in ((q.get("items") or []) if st == 200 else []):
                conv = json.loads((item.get("metadata") or {}).get("annotations", {})
                                  .get("cns.vmware.com/conversion", "{}") or "{}")
                for t in ((conv.get("status") or {}).get("total") or []):
                    used = str(t.get("scQuotaUsage", {}).get("used", ""))
                    if used.isdigit():
                        total += int(used)
        return total

    before = quota()
    # Not just any VM folder. The Supervisor owns some of them, and vCenter refuses a hand-made machine
    # there with HTTP 403: the folder named "Namespaces" and the per-service folders are the Supervisor's,
    # which is a small piece of good news and the only place the two planes visibly defend a boundary.
    st, folders = vc("/api/vcenter/folder")
    OWNED = ("Namespaces", "vSpherePods")
    cand = [f for f in (folders or []) if f.get("type") == "VIRTUAL_MACHINE"
            and f.get("name") not in OWNED and not str(f.get("name", "")).startswith("svc-")]
    folder = next((f["folder"] for f in cand if f.get("name") == "Discovered virtual machine"),
                  cand[0]["folder"] if cand else None)
    st, pools = vc("/api/vcenter/resource-pool")
    pool = next((r["resource_pool"] for r in (pools or []) if r.get("name") == "Resources"), None)
    st, stores = vc("/api/vcenter/datastore")
    store = max((d for d in (stores or [])), key=lambda d: d.get("free_space", 0), default={}).get("datastore")
    if not (folder and pool and store):
        print("  fourth door: could not resolve a folder, pool and datastore to place a machine; skipped")
        return None

    spec = {"name": name, "guest_OS": "UBUNTU_64",
            "placement": {"folder": folder, "resource_pool": pool, "datastore": store},
            "cpu": {"count": 1}, "memory": {"size_MiB": 512},
            "disks": [{"new_vmdk": {"capacity": 1073741824}}]}
    st, r = vc("/api/vcenter/vm", "POST", spec)
    out["created"] = st
    if st not in (200, 201):
        print(f"  fourth door: vCenter refused the create (HTTP {st}); skipped")
        return out
    moid = r if isinstance(r, str) else (r or {}).get("value")

    asked = []
    for _p, ns, url in namespaces:
        stn, _ = e.ns(url, f"/apis/{VMOP}/v1alpha5/namespaces/{ns}/virtualmachines/{name}")
        asked.append(stn)
    out["declaredByANamespace"] = any(a == 200 for a in asked)
    out["namespacesAsked"] = len(asked)

    claimed = False
    st, dep = e.api("/deployment/api/deployments?size=200")
    for d in ((dep or {}).get("content") or []):
        st, rs = e.api(f"/deployment/api/deployments/{d['id']}/resources?size=50")
        for res in ((rs or {}).get("content") or []):
            if name in json.dumps(res.get("properties") or {}):
                claimed = True
    out["claimedByADeployment"] = claimed
    out["tenantQuotaDeltaBytes"] = quota() - before

    st, _ = vc(f"/api/vcenter/vm/{moid}", "DELETE")
    stg, _ = vc(f"/api/vcenter/vm/{moid}")
    out["deleted"] = (st, stg == 404)
    print(f"  fourth door: created straight in vCenter, declared by {sum(1 for a in asked if a == 200)} of "
          f"{len(asked)} namespace(s), claimed by {'a' if claimed else 'no'} deployment, and it moved the "
          f"tenant storage quota by {out['tenantQuotaDeltaBytes']} bytes. Deleted, and gone: {stg == 404}")
    return out


# --------------------------------------------------------------------------- the probe

def release_and_request(e, project, bpname, content, deployment_name, inputs, version="1.0.0"):
    """The three calls behind the catalog form, which are the three calls a pipeline makes.

    Authoring a blueprint changes nothing; releasing a version is what publishes it; requesting the item is
    what builds infrastructure. Two details bite. The version object's name is DERIVED, not chosen: it must
    equal "<blueprint>:<version>" and the interface refuses anything else with a 422. And the catalog item
    appears asynchronously after the release, so a request issued immediately finds nothing to request.

    Returns the three statuses and the deployment id, or None if the item never appeared.
    """
    out = {}
    st, _ = e.gw(f"/apis/{BP}/namespaces/{project}/blueprints", "POST",
                 {"apiVersion": BP, "kind": "Blueprint",
                  "metadata": {"name": bpname, "namespace": project},
                  "spec": {"content": content, "description": "created by doors.py, deleted by the same run"}})
    out["blueprintStatus"] = st

    st, _ = e.gw(f"/apis/{BP}/namespaces/{project}/blueprintversions", "POST",
                 {"apiVersion": BP, "kind": "BlueprintVersion",
                  "metadata": {"name": f"{bpname}:{version}", "namespace": project},
                  "spec": {"blueprintName": bpname, "version": version, "publishToCatalog": True}})
    out["releaseStatus"] = st
    time.sleep(10)          # the catalog item is published asynchronously; requesting too early finds nothing

    st, items = e.api("/catalog/api/items?size=200")
    item = next((i for i in ((items or {}).get("content") or []) if i.get("name") == bpname), None)
    st, projects = e.api("/project-service/api/projects?size=100")
    pid = next((p["id"] for p in ((projects or {}).get("content") or []) if p.get("name") == project), None)
    if not (item and pid):
        return out, None

    st, r = e.api(f"/catalog/api/items/{item['id']}/request", "POST",
                  {"deploymentName": deployment_name, "projectId": pid, "version": version, "inputs": inputs})
    out["requestStatus"] = st
    return out, (r[0].get("deploymentId") if isinstance(r, list) and r else None)



def read_vm(e, url, ns, name):
    st, v = e.ns(url, f"/apis/{VMOP}/v1alpha5/namespaces/{ns}/virtualmachines/{name}")
    if st != 200:
        return None
    md, stt = v.get("metadata") or {}, v.get("status") or {}
    return {"labelKeys": sorted((md.get("labels") or {}).keys()),
            "annotationKeys": sorted((md.get("annotations") or {}).keys()),
            "ownerReferences": [o.get("kind") for o in (md.get("ownerReferences") or [])],
            "powerState": stt.get("powerState"),
            "specKeys": sorted((v.get("spec") or {}).keys())}


def wait_for(fn, ok, limit=40, every=10):
    for i in range(limit):
        v = fn()
        if ok(v):
            return (i + 1) * every, v
        time.sleep(every)
    return None, fn()


def probe(e, L, project, ns, url, image, storage, vmclass):
    """Build the same machine through two doors, compare them, and delete both. Nothing pre-existing is touched.

    Both names are prefixed, both are created by this run, and the residue check at the end reads the namespace
    back. The comparison is the point: if the two machines differ, the difference is what the door costs you.
    """
    vms = f"/apis/{VMOP}/v1alpha5/namespaces/{ns}/virtualmachines"
    a_name, c_name = f"{PREFIX}-direct", f"{PREFIX}-catalog"
    bpname = f"{PREFIX}-probe"
    out = {"direct": {}, "catalog": {}, "identical": None, "teardown": {}}

    manifest_spec = {"className": vmclass, "imageName": image, "storageClass": storage,
                     "bootDiskCapacity": "20Gi", "powerState": "PoweredOn"}

    # ---- door 1: straight at the namespace endpoint, which is what kubectl apply does
    st, r = e.ns(url, vms, "POST", {
        "apiVersion": f"{VMOP}/v1alpha5", "kind": "VirtualMachine",
        "metadata": {"name": a_name, "namespace": ns,
                     "labels": {"app.kubernetes.io/name": a_name, "handbook-probe": "three-doors"}},
        "spec": dict(manifest_spec)})
    out["direct"]["createStatus"] = st
    if st not in (200, 201):
        out["direct"]["refusal"] = L.scrub(msg(r))[:400]
        print(f"  DIRECT      refused at create: HTTP {st}  {msg(r)[:160]}")
        return out
    secs, _ = wait_for(lambda: read_vm(e, url, ns, a_name), lambda v: v and v["powerState"] == "PoweredOn")
    out["direct"]["secondsToPoweredOn"] = secs
    out["direct"]["machine"] = read_vm(e, url, ns, a_name)
    print(f"  DIRECT      created and PoweredOn in ~{secs}s")

    # ---- door 3: the same manifest, wrapped, released, and requested from the catalog
    content = ("name: %s\nversion: 1.0.0\nformatVersion: 2\n"
               "inputs:\n  target_namespace_name: {type: string, title: Namespace}\n"
               "  vm_name: {type: string, title: VM name}\n"
               "resources:\n"
               "  Namespace:\n    type: CCI.Supervisor.Namespace\n"
               "    properties:\n      existing: true\n      name: ${input.target_namespace_name}\n"
               "  VM:\n    type: CCI.Supervisor.Resource\n"
               "    properties:\n      context: ${resource.Namespace.id}\n"
               "      manifest:\n        apiVersion: %s/v1alpha5\n        kind: VirtualMachine\n"
               "        metadata:\n          name: ${input.vm_name}\n"
               "          labels:\n            app.kubernetes.io/name: ${input.vm_name}\n"
               "            handbook-probe: three-doors\n"
               "        spec:\n%s\n") % (
        bpname, VMOP, "\n".join(f"          {k}: {v}" for k, v in manifest_spec.items()))

    statuses, dep_id = release_and_request(e, project, bpname, content, c_name,
                                          {"target_namespace_name": ns, "vm_name": c_name})
    out["catalog"].update(statuses)
    if dep_id:
        secs, _ = wait_for(lambda: e.api(f"/deployment/api/deployments/{dep_id}")[1],
                           lambda d: (d or {}).get("status") not in ("CREATE_INPROGRESS", None, "?"))
        out["catalog"]["secondsToCreateSuccessful"] = secs
        secs2, _ = wait_for(lambda: read_vm(e, url, ns, c_name), lambda v: v and v["powerState"] == "PoweredOn")
        out["catalog"]["secondsToPoweredOn"] = secs2
        out["catalog"]["machine"] = read_vm(e, url, ns, c_name)
        st, rs = e.api(f"/deployment/api/deployments/{dep_id}/resources?size=100")
        vm_res = next((r for r in ((rs or {}).get("content") or [])
                       if r.get("type") == "CCI.Supervisor.Resource"), None)
        if vm_res:
            out["catalog"]["claimedBy"] = L.scrub(str((vm_res.get("properties") or {}).get("resourceLink") or ""))
        print(f"  CATALOG     requested, deployment CREATE_SUCCESSFUL in ~{secs}s, machine PoweredOn")

    # ---- the comparison this script exists for
    a, c = out["direct"].get("machine"), out["catalog"].get("machine")
    if a and c:
        strip = lambda ks, n: [k for k in ks if n not in k]
        out["identical"] = {
            "annotationKeys": a["annotationKeys"] == c["annotationKeys"],
            "annotationCount": len(a["annotationKeys"]),
            "labelKeysIgnoringName": strip(a["labelKeys"], "doors") == strip(c["labelKeys"], "doors"),
            "ownerReferencesBoth": a["ownerReferences"] + c["ownerReferences"],
            "specKeys": a["specKeys"] == c["specKeys"],
            "markerOnEither": sorted({k for k in a["annotationKeys"] + a["labelKeys"]
                                      + c["annotationKeys"] + c["labelKeys"]
                                      if re.search(r"(?i)deploy|catalog|blueprint|vra|automation", k)}),
        }
        same = (out["identical"]["annotationKeys"] and out["identical"]["labelKeysIgnoringName"]
                and not out["identical"]["ownerReferencesBoth"] and not out["identical"]["markerOnEither"])
        print(f"\n  the two machines are {'INDISTINGUISHABLE' if same else 'DIFFERENT'}: "
              f"{len(a['annotationKeys'])} annotations each, identical sets, "
              f"{len(out['identical']['ownerReferencesBoth'])} owner reference(s) between them, "
              f"{len(out['identical']['markerOnEither'])} marker(s) naming a door")

    # ---- teardown, timed, because the coupling is plainest here
    if dep_id:
        t0 = time.time()
        e.api(f"/deployment/api/deployments/{dep_id}", "DELETE")
        vm_gone, dep_gone = None, None
        for i in range(40):
            time.sleep(10)
            if vm_gone is None and read_vm(e, url, ns, c_name) is None:
                vm_gone = round(time.time() - t0)
            if e.api(f"/deployment/api/deployments/{dep_id}")[0] == 404:
                dep_gone = round(time.time() - t0)
                break
        out["teardown"]["catalogSecondsToVmGone"] = vm_gone
        out["teardown"]["catalogSecondsToDeploymentGone"] = dep_gone
    t0 = time.time()
    e.ns(url, f"{vms}/{a_name}", "DELETE")
    secs, _ = wait_for(lambda: read_vm(e, url, ns, a_name), lambda v: v is None, limit=18)
    out["teardown"]["directSecondsToVmGone"] = secs
    print(f"  teardown    direct ~{secs}s; through the deployment "
          f"~{out['teardown'].get('catalogSecondsToDeploymentGone')}s "
          f"(its machine gone at ~{out['teardown'].get('catalogSecondsToVmGone')}s)")

    # ---- put the content tree back
    enc = urllib.parse.quote(f"{bpname}:1.0.0", safe="")
    e.gw(f"/apis/{BP}/namespaces/{project}/blueprintversions/{enc}", "DELETE")
    time.sleep(6)
    e.gw(f"/apis/{BP}/namespaces/{project}/blueprints/{bpname}", "DELETE")
    time.sleep(8)

    # ---- residue: read the namespace and the catalog back, and say what is left
    st, left = e.ns(url, vms)
    names = [v["metadata"]["name"] for v in ((left.get("items") or []) if st == 200 else [])]
    st, its = e.gw(f"/apis/{CATG}/namespaces/{project}/catalogitems")
    cat_names = [i["metadata"]["name"] for i in ((its.get("items") or []) if st == 200 else [])]
    out["residue"] = {"machinesNamedByThisRun": [n for n in names if n.startswith(PREFIX)],
                      "catalogItemsNamedByThisRun": [n for n in cat_names if n.startswith(PREFIX)]}
    clean = not out["residue"]["machinesNamedByThisRun"] and not out["residue"]["catalogItemsNamedByThisRun"]
    print(f"  residue     {'nothing this run created is still here' if clean else 'SOMETHING REMAINS, see the record'}")
    return out


def main():
    host, org = os.environ["VCFA_HOST"], os.environ["VCFA_ORG"]
    refresh = open(os.environ["VCFA_REFRESH_TOKEN_FILE"], encoding="utf-8").read().strip()
    out_dir = os.environ.get("OUT_DIR", ".")
    want_probe = "--probe-doors" in sys.argv[1:]
    e = Estate(host, org, refresh)
    L = Labels()
    print("doors.py: the same machine, through each door, and what each leaves behind\n")

    st, pl = e.gw(f"/apis/{PROJ}/projects")
    projects = [p["metadata"]["name"] for p in ((pl.get("items") or []) if st == 200 else [])]
    if not projects:
        raise SystemExit("no project is visible to this identity")
    project = os.environ.get("DOORS_PROJECT") or projects[0]
    L.get("project", project)

    needs, per_ns = survey(e, L, project)
    print(f"  what the DIRECT door needs, on this estate:")
    for n in needs["direct"]:
        print(f"     {n['need']:46s} {n['present']}"
              + (f" of {n['usable']}" if n["usable"] is not None else ""))
    print(f"  what the AUTOMATION doors need on top:")
    for n in needs["automation"][1:]:
        print(f"     {n['need']:46s} {n['present']}")
    ready = [x for x in per_ns if x["couldBuildAVm"]]
    print(f"\n  {len(ready)} of {len(per_ns)} namespace(s) could build a VM today "
          f"(an image bound to them and room for a 20Gi boot disk)")
    for x in per_ns:
        print(f"     {x['namespace']:22s} images {x['imagesBound']:>2}  classes {x['classes']:>2}  "
              f"free {x['freeGiB']:>7.1f} GiB of {x['quotaGiB']:.1f}  "
              f"{'can build' if x['couldBuildAVm'] else 'cannot build here'}")

    buys = claims(e, L)
    creds = credentials(e, L, project, os.environ.get("VC_HOST"))
    print(f"\n  what a deployment record CLAIMS and what the claim BUYS")
    print(f"     the claim is one string: {buys['linkShape'] or 'no claimed machine on this estate to read'}")
    print(f"     {len(buys['deploymentActions'])} deployment-level and {len(buys['resourceActions'])} "
          f"resource-level Day-2 action(s) exist on a claimed machine")
    if buys["resourceActions"]:
        print(f"     {', '.join(buys['resourceActions'][:6])}{' ...' if len(buys['resourceActions']) > 6 else ''}")
    print(f"     the record carries {len(buys['recordFields'])} field(s), including who asked and what they typed")

    fourth = None
    want_vc = "--probe-vcenter" in sys.argv[1:]
    vc_host, vc_sess = os.environ.get("VC_HOST"), os.environ.get("VC_SESSION_FILE")
    if want_vc and vc_host and vc_sess and os.path.exists(vc_sess):
        print(f"\n  the fourth door: a machine made straight in vCenter, which is not one of the three")
        fourth = probe_vcenter(e, L, vc_host, open(vc_sess, encoding="utf-8").read().strip(),
                               [(p, n, u) for (p, n, u) in
                                [(x[0], x[1], x[2]) for x in _endpoints(e, project)]])
    elif want_vc:
        print("\n  the fourth door: not probed (needs VC_HOST and VC_SESSION_FILE)")

    probed = None
    if want_probe:
        ns = os.environ.get("DOORS_NAMESPACE")
        if not ns:
            raise SystemExit("--probe-doors needs DOORS_NAMESPACE set to a namespace you may build in")
        st, nss = e.gw(f"/apis/{A3}/namespaces/{project}/supervisornamespaces")
        match = [n for n in ((nss.get("items") or []) if st == 200 else []) if n["metadata"]["name"] == ns]
        if not match:
            raise SystemExit(f"namespace {ns!r} is not visible in project {project!r}")
        url = (match[0].get("status") or {}).get("namespaceEndpointURL")
        st, imgs = e.ns(url, f"/apis/{VMOP}/v1alpha5/namespaces/{ns}/virtualmachineimages")
        images = [i["metadata"]["name"] for i in ((imgs.get("items") or []) if st == 200 else [])]
        st, cls = e.ns(url, f"/apis/{VMOP}/v1alpha5/namespaces/{ns}/virtualmachineclasses")
        classes = sorted(c["metadata"]["name"] for c in ((cls.get("items") or []) if st == 200 else []))
        row = next((x for x in per_ns if x["namespace"] == L.get("namespace", ns)), None)
        if not images:
            raise SystemExit(f"no VM image is bound to {ns!r}; the direct door cannot open there. "
                             f"Images are namespace scoped, so a large cluster catalogue does not help.")
        if row and row["freeGiB"] <= 20:
            raise SystemExit(f"{ns!r} has {row['freeGiB']} GiB of storage quota left and the probe needs 20 GiB "
                             f"for a boot disk. An admission webhook would refuse this at the create call.")
        storage = os.environ.get("DOORS_STORAGE_CLASS")
        if not storage:
            st, vms_ = e.ns(url, f"/apis/{VMOP}/v1alpha5/namespaces/{ns}/virtualmachines")
            seen = [(v.get("spec") or {}).get("storageClass") for v in ((vms_.get("items") or []) if st == 200 else [])]
            storage = next((s for s in seen if s), None)
        if not storage:
            raise SystemExit("could not infer a storage class; set DOORS_STORAGE_CLASS")
        vmclass = "best-effort-xsmall" if "best-effort-xsmall" in classes else (classes[0] if classes else None)
        L.get("storageclass", storage)
        print(f"\n  probe: building the same machine twice in {L.get('namespace', ns)}, "
              f"then deleting both and reading the namespace back")
        probed = probe(e, L, project, ns, url, images[0], storage, vmclass)
    else:
        print("\n  probe: not run (pass --probe-doors to build the same machine through two doors and compare)")

    payload = {"captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "project": L.get("project", project), "needs": needs, "namespaces": per_ns,
               "claimBuys": buys, "credentials": creds, "probe": probed, "fourthDoor": fourth}
    _pp = os.path.join(out_dir, "doors.json")
    if os.path.exists(_pp):
        try:
            _prior = json.load(open(_pp, encoding="utf-8")) or {}
        except ValueError:
            _prior = {}
        for _k in ("probe", "fourthDoor"):
            if payload.get(_k) is None and _prior.get(_k):
                payload[_k] = _prior[_k]
                print(f"  carrying forward {_k!r} captured by an earlier run with the flag; this run did "
                      f"not re-probe it and has not erased it")
    text = L.scrub(UUID.sub("{{id}}", json.dumps(payload, indent=1, ensure_ascii=False)))
    for secret in (e.bearer, refresh, host, org, os.environ.get("DOORS_NAMESPACE")):
        assert not secret or secret not in text, "an estate value reached the record"
    bare = re.sub(r"\{\{[^}]*\}\}", "", text)
    link = (buys or {}).get("linkShape") or ""
    assert not re.search(r"VirtualMachine:[A-Za-z0-9]", link), (
        "a machine name survived inside the deployment claim; register machine names before scrubbing")
    for fam, m in L.maps.items():
        for nm in m:
            if nm and re.search(r"(?<![A-Za-z0-9-])" + re.escape(nm) + r"(?![A-Za-z0-9-])", bare):
                shp = re.sub(r"[A-Za-z]", "a", re.sub(r"[0-9]", "9", nm))
                raise SystemExit(f"FATAL: a {fam} name ({len(nm)} characters, shape {shp}) reached the record")
    os.makedirs(out_dir, exist_ok=True)
    open(os.path.join(out_dir, "doors.json"), "w", encoding="utf-8").write(text + "\n")
    print(f"\nwrote doors.json ({len(per_ns)} namespace(s), "
          f"{len(buys['deploymentActions']) + len(buys['resourceActions'])} Day-2 action(s) counted"
          f"{', probe included' if probed else ''}); every estate name replaced by a placeholder")


if __name__ == "__main__":
    main()
