#!/usr/bin/env python3
"""doors.py: the same virtual machine, built through each door the platform offers, and what each leaves behind.

There are two mechanisms for putting a VM on a VCF Supervisor, and three doors, because one mechanism has two
request surfaces:

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
     catalog, read back field by field and compared. Everything it creates it deletes, even when a step fails,
     and it reads back the machines, the deployment, the blueprint, the version and both catalogs afterwards;
  3. what the deployment record CLAIMS and what that claim BUYS: the Day-2 action catalogue that exists on a
     claimed machine and does not exist on an unclaimed one, plus the owner, the lease and the provenance;
  4. the TEARDOWN of each, timed, because the coupling shows up there more plainly than anywhere else.

With --probe-vcenter it also makes one machine straight in vCenter, the door that is not one of the three, and
measures what the tenancy above it sees of it. Add --dry-run to either probe and it prints every object it would
create, where and with what, and writes nothing.

Without a probe flag nothing here writes. Estate names are replaced by stable placeholders and the script refuses
to write a record in which one survived. Field names, verbs, action ids, HTTP statuses and the platform's own error
strings are the product's vocabulary and are kept, because they are the lesson.

Sign-in to VCF Automation, one of:
  VCFA_REFRESH_TOKEN_FILE   a refresh token minted for the organization, in a file of mode 0600
  VCFA_USER and VCFA_PASSWORD_FILE   a session login as user@org (the password from a file of mode 0600, or
                            VCFA_PASSWORD, the value itself, which lands in the shell's history)
vCenter, for the credential row and --probe-vcenter: VC_HOST, with VCENTER_USER and VCENTER_PASSWORD_FILE or
VC_SESSION_FILE holding a vmware-api-session-id. A secret file open to group or other is refused before it is read.

Run:
  export VCFA_HOST=<automation-fqdn> VCFA_ORG=<org>
  export VCFA_USER=<account> VCFA_PASSWORD_FILE=~/.vcf/vcfa-password    # or VCFA_REFRESH_TOKEN_FILE
  export DOORS_PROJECT=<project>             # optional; else the first project that hosts a namespace
  export TLS_VERIFY=false                    # only on a self-signed lab CA
  python3 doors.py                                            # read-only
  DOORS_NAMESPACE=<ns> python3 doors.py --probe-doors --dry-run   # what the probe would create
  DOORS_NAMESPACE=<ns> python3 doors.py --probe-doors             # build, compare, delete, read back

The probe needs a namespace that can name a general-purpose VM image (bound to it, or cluster-scoped from a library
attached to the whole Supervisor) and storage quota left. Both are checked before
anything is created, and it says which one is missing rather than letting an admission webhook say it later.

Exit: 0 written; 2 a call failed, a sign-in was refused, or a probe's precondition was not met; 3 a probe left
something behind; 5 an unknown argument.
"""
import base64
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
PLACEHOLDER = re.compile(r"(\{\{[^}]*\}\})")
CCI = "/cci/kubernetes"
A3 = "infrastructure.cci.vmware.com/v1alpha3"
PROJ = "project.cci.vmware.com/v1alpha2"
VMOP = "vmoperator.vmware.com"
BP = "blueprint.cci.vmware.com/v1alpha1"
CATG = "catalog.cci.vmware.com/v1alpha1"
PREFIX = "handbook-doors"
SUFFIX = {"Ki": 1024, "Mi": 1024 ** 2, "Gi": 1024 ** 3, "Ti": 1024 ** 4,
          "K": 1000, "k": 1000, "M": 1000 ** 2, "G": 1000 ** 3, "T": 1000 ** 4}
# A deployment resource links a machine as cci:<project>:<namespace>:<group>/<version>:VirtualMachine:<name>.
LINK = re.compile(r"^cci:([^:]+):([^:]+):[^:]+:VirtualMachine:(.+)$")
MARKER = re.compile(r"(?i)deploy|catalog|blueprint|vra|automation")
# A Kubernetes release's node image names its release and build: ob-<n>-ubuntu-<n>-amd64-v1.30.1---vmware.1-vkr.1.
K8S_RELEASE_LABEL = "services.supervisor.vmware.com/kubernetes.vmware.com"
NODE_IMAGE = re.compile(r"v\d+\.\d+\.\d+(\+[\w.]+)?---vmware\.")


def ctx():
    verify = os.environ.get("TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")
    return ssl.create_default_context() if verify else ssl._create_unverified_context()


def qty(v):
    """A Kubernetes quantity, which on this object arrives in three different notations: a bare byte count,
    '268Gi', and a bare number in neither unit. Parse the suffix when there is one and treat a bare number as
    bytes, which is what the authoritative `total` array uses. None when it is not a quantity at all."""
    m = re.match(r"^(\d+(?:\.\d+)?)([A-Za-z]*)$", str(v).strip())
    if not m or (m.group(2) and m.group(2) not in SUFFIX):
        return None
    return int(float(m.group(1)) * SUFFIX.get(m.group(2), 1))


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


def fail(msg_):
    print(f"FATAL: {msg_}")
    sys.exit(2)


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
        """Replace every registered name, never inside a placeholder already written: an estate can name a project
        exactly what a placeholder says, and a scrub that reaches into one rewrites it (G-646)."""
        if not isinstance(text, str):
            return text
        # One pass with every name in a single pattern, longest first, so a placeholder written in this pass is
        # never scanned again: replacing one name at a time lets a project named project-2 match inside the
        # "{{project-2}}" just written for the project named project-1.
        label = {real: lab for m in self.maps.values() for real, lab in m.items()}
        names = sorted(label, key=len, reverse=True)
        rx = re.compile(r"(?<![A-Za-z0-9-])(" + "|".join(map(re.escape, names)) + r")(?![A-Za-z0-9-])") if names else None
        parts = PLACEHOLDER.split(text)
        for i in range(0, len(parts), 2):   # the even parts are outside any placeholder
            if rx:
                parts[i] = rx.sub(lambda mt: "{{%s}}" % label[mt.group(1)], parts[i])
            parts[i] = UUID.sub("{{id}}", parts[i])
        return "".join(parts)


class Estate:
    """One bearer, three base URLs: the org gateway, the classic API, and each namespace's own endpoint."""

    def __init__(self, host, org, refresh_token=None, user=None, password=None):
        """A tenant bearer, from the organization's refresh token or from a session login as user@org. A refused
        mint ends the run with the server's own answer."""
        self.host = host
        if refresh_token:
            self.kind = "refresh token"
            body = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": refresh_token}).encode()
            req = urllib.request.Request(f"https://{host}/oauth/tenant/{org}/token", data=body, method="POST",
                                         headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
        else:
            self.kind = "session login"
            basic = base64.b64encode(f"{user.split('@')[0]}@{org}:{password}".encode()).decode()
            req = urllib.request.Request(f"https://{host}/cloudapi/1.0.0/sessions", method="POST",
                                         headers={"Authorization": f"Basic {basic}", "Accept": "application/json;version=40.0"})
        try:
            with urllib.request.urlopen(req, context=ctx(), timeout=30) as r:
                self.bearer = json.loads(r.read())["access_token"] if refresh_token else r.headers.get("X-VMWARE-VCLOUD-ACCESS-TOKEN")
        except urllib.error.HTTPError as ex:
            fail(f"the {self.kind} answered HTTP {ex.code}: {ex.read().decode(errors='replace')[:200]}")
        except (urllib.error.URLError, OSError) as ex:
            fail(f"the {self.kind} did not answer: {ex}")
        if not self.bearer:
            fail(f"the {self.kind} answered without a bearer")

    def call(self, url, method="GET", payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {self.bearer}", "Accept": "application/json",
            **({"Content-Type": "application/json"} if data else {})})
        try:
            with urllib.request.urlopen(req, context=ctx(), timeout=180) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as ex:
            raw = ex.read()
            try:
                return ex.code, json.loads(raw)
            except ValueError:
                return ex.code, {}
        except (urllib.error.URLError, OSError):
            return None, {}

    def gw(self, path, method="GET", payload=None):
        return self.call(f"https://{self.host}{CCI}{path}", method, payload)

    def api(self, path, method="GET", payload=None):
        return self.call(f"https://{self.host}{path}", method, payload)

    def ns(self, endpoint, path, method="GET", payload=None):
        return self.call(endpoint.rstrip("/") + path, method, payload)

    def items(self, base, path):
        """Every item of a Kubernetes-style list, following its continue token; a list that fails ends the run."""
        out, token = [], None
        while True:
            st, body = self.call(base.rstrip("/") + path + (f"?continue={urllib.parse.quote(token)}" if token else ""))
            if st != 200 or not isinstance(body, dict):
                fail(f"GET {path} answered {st if st else 'nothing'}")
            out += body.get("items") or []
            token = (body.get("metadata") or {}).get("continue")
            if not token:
                return out

    def classic(self, path, sort="id,asc"):
        """Every page of a classic list, sorted (G-634); a deployment's resources take sort=name,asc (G-645)."""
        out, number = [], 0
        while True:
            st, body = self.api(f"{path}{'&' if '?' in path else '?'}size=200&page={number}&sort={sort}")
            if st != 200 or not isinstance(body, dict):
                fail(f"GET {path} answered {st if st else 'nothing'}")
            out += body.get("content") or []
            number += 1
            if body.get("last", True) or number >= (body.get("totalPages") or 0):
                return out


def msg(r):
    if isinstance(r, dict):
        return " ".join(str(r.get("message") or r.get("detail") or r.get("error") or "").split())
    return ""


def gateway(e):
    return f"https://{e.host}{CCI}"


# --------------------------------------------------------------------------- what each door needs

def quota(e, url, name):
    """A namespace's storage limit and use in bytes, and whether the limit is stated at all. An unstated limit is
    not zero room; it is a namespace this script cannot judge, and it says so (G-640)."""
    lim, used, stated = 0, 0, False
    for item in e.items(url, f"/apis/cns.vmware.com/v1alpha1/namespaces/{name}/storagepolicyquotas"):
        conv = json.loads((item.get("metadata") or {}).get("annotations", {}).get("cns.vmware.com/conversion", "{}") or "{}")
        stt = conv.get("status") or {}
        limit = qty(stt.get("appliedLimit") or (item.get("spec") or {}).get("limit") or "")
        if limit is not None:
            lim, stated = lim + limit, True
        used += sum(qty(t["scQuotaUsage"]["used"]) or 0 for t in (stt.get("total") or []))
    return lim, used, stated


def survey(e, L, project):
    """What has to exist before each door will open, read rather than listed from memory.

    This is the half of the comparison nobody writes down. Both doors end at the same object, so the honest
    difference is in the prerequisites, and every one of them is a thing that can be missing.
    """
    needs = {"direct": [], "automation": []}
    spaces = e.items(gateway(e), f"/apis/{A3}/namespaces/{project}/supervisornamespaces")
    with_endpoint = [n for n in spaces if (n.get("status") or {}).get("namespaceEndpointURL")]
    needs["direct"].append({"need": "a Supervisor namespace, vended to you", "kind": "SupervisorNamespace",
                            "present": len(spaces), "usable": len(with_endpoint),
                            "note": "usable means it publishes its own namespaceEndpointURL; that URL is the door"})
    per_ns, seen = [], []
    # A library attached to the whole Supervisor lands its images in every namespace as cluster-scoped images, so a
    # namespace with nothing bound can still name one. The cluster list is mostly Kubernetes node images on an estate
    # that runs clusters, so only the general-purpose ones count.
    general = general_cluster_images(e, with_endpoint[0]["status"]["namespaceEndpointURL"]) if with_endpoint else []
    for n in with_endpoint:
        name, url = n["metadata"]["name"], (n.get("status") or {}).get("namespaceEndpointURL")
        L.get("namespace", name)
        bound = e.items(url, f"/apis/{VMOP}/v1alpha5/namespaces/{name}/virtualmachineimages")
        images = len(bound)
        seen += [(i["metadata"]["name"], str((i.get("status") or {}).get("name") or "")) for i in bound]
        lim, used, stated = quota(e, url, name)
        classes = len(e.items(url, f"/apis/{VMOP}/v1alpha5/namespaces/{name}/virtualmachineclasses"))
        # Register every machine name that exists here: a VM name turns up inside a deployment's resourceLink,
        # a single opaque string, and a scrubber only replaces what it was told about.
        for v in e.items(url, f"/apis/{VMOP}/v1alpha5/namespaces/{name}/virtualmachines"):
            L.get("machine", v["metadata"]["name"])
        per_ns.append({"namespace": L.get("namespace", name), "imagesBound": images, "imagesCluster": len(general),
                       "classes": classes,
                       "quotaStated": stated, "quotaGiB": round(lim / SUFFIX["Gi"], 1) if stated else None,
                       "usedGiB": round(used / SUFFIX["Gi"], 1), "freeGiB": round((lim - used) / SUFFIX["Gi"], 1) if stated else None,
                       "couldBuildAVm": (images + len(general) > 0 and (lim - used) > 20 * SUFFIX["Gi"]) if stated else None})
    needs["direct"].append({"need": "a VM image THAT namespace can name", "kind": "VirtualMachineImage",
                            "present": sum(1 for x in per_ns if x["imagesBound"] + x["imagesCluster"]), "usable": len(per_ns),
                            "note": "bound to the namespace, or cluster-scoped from a library attached to the Supervisor; "
                                    "the Kubernetes node images in the cluster list do not count"})
    needs["direct"].append({"need": "storage quota with room for the boot disk", "kind": "StoragePolicyQuota",
                            "present": sum(1 for x in per_ns if x["freeGiB"] is not None and x["freeGiB"] > 20),
                            "usable": len(per_ns),
                            "note": "the refusal arrives from an admission webhook at the create call and names the reason"})
    bps = e.items(gateway(e), f"/apis/{BP}/namespaces/{project}/blueprints")
    vers = e.items(gateway(e), f"/apis/{BP}/namespaces/{project}/blueprintversions")
    its = e.items(gateway(e), f"/apis/{CATG}/namespaces/{project}/catalogitems")
    needs["automation"] = [
        {"need": "everything the direct door needs, unchanged", "kind": "-", "present": None, "usable": None,
         "note": "the blueprint applies the same object into the same namespace; nothing above goes away"},
        {"need": "a project you are a member of", "kind": "Project", "present": 1, "usable": 1,
         "note": "the deployment is scoped to it and the catalog item is published to it"},
        {"need": "a blueprint holding the manifest", "kind": "Blueprint", "present": len(bps), "usable": None,
         "note": "authoring changes nothing; it is a document until a version is released"},
        {"need": "a released version", "kind": "BlueprintVersion", "present": len(vers), "usable": None,
         "note": "the version object's name is derived, not chosen: it must equal '<blueprint>:<version>'"},
        {"need": "a catalog item, for the catalog door only", "kind": "CatalogItem", "present": len(its), "usable": None,
         "note": "released with publishToCatalog true; the API door does not need this one"},
    ]
    return needs, per_ns, image_scope(e, with_endpoint, seen)


def general_cluster_images(e, url):
    """(id, display name) of every cluster-scoped image that is not a Kubernetes node image."""
    path = f"/apis/{VMOP}/v1alpha5/clustervirtualmachineimages"
    st, _ = e.ns(url, path)
    if st != 200:
        return []
    return [(i["metadata"]["name"], str((i.get("status") or {}).get("name") or "")) for i in e.items(url, path)
            if not NODE_IMAGE.search(str((i.get("status") or {}).get("name") or ""))
            and K8S_RELEASE_LABEL not in ((i.get("metadata") or {}).get("labels") or {})]


def image_scope(e, spaces, seen):
    """The two places a VM image lives, compared, in counts: the images bound to the namespaces against the
    cluster-scoped list, by id and by display name, and how many of the cluster images are Kubernetes node images
    by the release their name carries. The cluster list is the longer one, and on an estate that runs Kubernetes
    clusters it is mostly node images, which is why the namespace's own list is the one to read first (G-196)."""
    if not spaces:
        return None
    url = spaces[0]["status"]["namespaceEndpointURL"]
    path = f"/apis/{VMOP}/v1alpha5/clustervirtualmachineimages"
    st, _ = e.ns(url, path)
    if st != 200:
        return {"clusterListStatus": st}
    cluster = [(i["metadata"]["name"], str((i.get("status") or {}).get("name") or ""),
                str(((i.get("status") or {}).get("osInfo") or {}).get("type") or "")) for i in e.items(url, path)]
    ubuntu = [c for c in cluster if "ubuntu" in (c[1] + " " + c[2]).lower()]
    general = general_cluster_images(e, url)
    return {"clusterListStatus": st, "clusterImages": len(cluster), "namespaceImages": len({s[0] for s in seen}),
            "clusterGeneral": len(general),
            "sharedById": len({s[0] for s in seen} & {c[0] for c in cluster}),
            "sharedByDisplayName": len({s[1] for s in seen if s[1]} & {c[1] for c in cluster if c[1]}),
            "clusterNodeImages": sum(1 for c in cluster if NODE_IMAGE.search(c[1])),
            "clusterUbuntu": len(ubuntu), "clusterUbuntuNodeImages": sum(1 for c in ubuntu if NODE_IMAGE.search(c[1]))}


# --------------------------------------------------------------------------- what a claim buys

def claims(e, L):
    """Read an existing deployment's action catalogue: what a claimed machine can be asked to do.

    A Day-2 action is not a property of the virtual machine. It is a property of the RECORD that claims it, so
    it is readable only from the deployment side, and an identical machine with no record has none of them.
    """
    deployments = e.classic("/deployment/api/deployments")
    fields = sorted(deployments[0].keys()) if deployments else []
    found = None
    for d in deployments:
        rows = e.classic(f"/deployment/api/deployments/{d['id']}/resources", sort="name,asc")
        vm = next((r for r in rows if r.get("type") == "CCI.Supervisor.Resource"
                   and "VirtualMachine" in str((r.get("properties") or {}).get("resourceLink") or "")), None)
        if not vm:
            continue
        _, da = e.api(f"/deployment/api/deployments/{d['id']}/actions")
        _, ra = e.api(f"/deployment/api/deployments/{d['id']}/resources/{vm['id']}/actions")
        # Register every name the link carries before it is scrubbed: the project, the namespace and the machine
        # (G-637). A retired record can name a machine the survey never saw, and a project the run did not choose.
        link = str((vm.get("properties") or {}).get("resourceLink") or "")
        m = LINK.match(link)
        if m:
            L.get("project", m.group(1)); L.get("namespace", m.group(2)); L.get("machine", m.group(3))
        found = {"deploymentActions": sorted(a.get("name") for a in (da or []) if a.get("name")),
                 "resourceActions": sorted(a.get("name") for a in (ra or []) if a.get("name")),
                 "linkShape": L.scrub(link), "recordFields": fields}
        break
    return found or {"deploymentActions": [], "resourceActions": [], "linkShape": None, "recordFields": fields}


def credentials(e, project, vc_host=None):
    """One credential, presented to every door, with what each one answers. The shape of the one refusal is the
    finding, so it is recorded rather than described."""
    rows = []
    st, _ = e.api("/deployment/api/deployments?size=1")
    rows.append({"door": "VCF Automation, API", "surface": "/deployment/api", "answeredTheTenantBearer": st})
    st, _ = e.api("/catalog/api/items?size=1")
    rows.append({"door": "VCF Automation, catalog", "surface": "/catalog/api", "answeredTheTenantBearer": st})
    eps = _endpoints(e, project)
    st = None
    if eps:
        _p, ns, url = eps[0]
        st, _ = e.ns(url, f"/apis/{VMOP}/v1alpha5/namespaces/{ns}/virtualmachines")
    rows.append({"door": "Supervisor, direct", "surface": "the namespace's own Kubernetes endpoint", "answeredTheTenantBearer": st})
    if vc_host:
        code = None
        try:
            req = urllib.request.Request(f"https://{vc_host}/api/vcenter/vm", headers={"Authorization": f"Bearer {e.bearer}"})
            with urllib.request.urlopen(req, context=ctx(), timeout=45) as r:
                code = r.status
        except urllib.error.HTTPError as ex:
            code = ex.code
        except (urllib.error.URLError, OSError):
            code = None
        rows.append({"door": "vCenter", "surface": "/api/vcenter", "answeredTheTenantBearer": code,
                     "takesInstead": "a session id from POST /api/session, or Basic, as a vCenter single sign-on principal"})
    same = sum(1 for r in rows if r["answeredTheTenantBearer"] == 200)
    print(f"  one credential, {len(rows)} door(s): {same} answered it, "
          + ", ".join(f"{r['door']} {r['answeredTheTenantBearer']}" for r in rows))
    return {"credentialHeld": f"a tenant bearer, from a {e.kind}", "doors": rows, "doorsThatTakeIt": same,
            "note": "a door answering 200 here is answering this identity; what it then PERMITS is the "
                    "project role tier and the four dials, which the access-control chapter covers"}


def _endpoints(e, project):
    """Every namespace in the project that publishes its own Kubernetes endpoint."""
    return [(project, n["metadata"]["name"], (n.get("status") or {}).get("namespaceEndpointURL"))
            for n in e.items(gateway(e), f"/apis/{A3}/namespaces/{project}/supervisornamespaces")
            if (n.get("status") or {}).get("namespaceEndpointURL")]


# --------------------------------------------------------------------------- the fourth door

def vcenter_session(vc_host):
    """A vCenter session: VC_SESSION_FILE as given, or one opened from VCENTER_USER and VCENTER_PASSWORD_FILE."""
    sid = secret("VC_SESSION")
    if sid:
        return sid, False
    user, password = os.environ.get("VCENTER_USER"), secret("VCENTER_PASSWORD")
    if not (user and password):
        return None, False
    basic = base64.b64encode(f"{user}:{password}".encode()).decode()
    req = urllib.request.Request(f"https://{vc_host}/api/session", method="POST", headers={"Authorization": f"Basic {basic}"})
    try:
        with urllib.request.urlopen(req, context=ctx(), timeout=30) as r:
            return json.loads(r.read()), True
    except (urllib.error.URLError, OSError, ValueError) as ex:
        fail(f"vCenter refused the session: {ex}")


def probe_vcenter(e, L, vc_host, session, namespaces, dry_run=False):
    """The door this chapter does not count as one of the three, because it does not reach the same machine.

    A virtual machine created straight in vCenter is not a VirtualMachine object. Nothing above vCenter declares
    it, counts it, or claims it, which is not a governance failure but a statement about where the tenancy model
    begins. This measures each of those absences rather than asserting them, and deletes what it made.
    """
    name = f"{PREFIX}-vcenter-native"

    def vc(path, method="GET", payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        h = {"vmware-api-session-id": session, "Accept": "application/json"}
        if data:
            h["Content-Type"] = "application/json"
        try:
            with urllib.request.urlopen(urllib.request.Request(f"https://{vc_host}{path}", data=data, method=method, headers=h),
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

    def used_bytes():
        return sum(quota(e, url, ns)[1] for _p, ns, url in namespaces)

    # Not just any VM folder. The Supervisor owns some, and vCenter refuses a hand-made machine there; the folder
    # named "Namespaces" and the per-service folders are the Supervisor's, so they are left out.
    _, folders = vc("/api/vcenter/folder")
    owned = ("Namespaces", "vSpherePods")
    cand = [f for f in (folders or []) if f.get("type") == "VIRTUAL_MACHINE"
            and f.get("name") not in owned and not str(f.get("name", "")).startswith("svc-")]
    folder = next((f["folder"] for f in cand if f.get("name") == "Discovered virtual machine"), cand[0]["folder"] if cand else None)
    # One cluster's root pool, and a datastore that a machine already in that cluster uses, so the pool and the
    # datastore always belong to one cluster. Picking each on its own (the first pool, the emptiest datastore) can
    # pair one cluster's pool with storage only another cluster mounts.
    _, stores = vc("/api/vcenter/datastore")
    by_name = {d["name"]: d["datastore"] for d in (stores or [])}
    for nm in by_name:
        L.get("datastore", nm)
    _, clusters = vc("/api/vcenter/cluster")
    pool = store = None
    for cl in clusters or []:
        L.get("cluster", cl.get("name"))
        _, roots = vc(f"/api/vcenter/resource-pool?clusters={cl['cluster']}&names=Resources")
        _, members = vc(f"/api/vcenter/vm?clusters={cl['cluster']}")
        for m in (members or [])[:5]:
            _, detail = vc(f"/api/vcenter/vm/{m['vm']}")
            files = [((dk.get("backing") or {}).get("vmdk_file") or "") for dk in ((detail or {}).get("disks") or {}).values()]
            store = next((by_name[f[1:f.index("]")]] for f in files if f.startswith("[") and "]" in f
                          and f[1:f.index("]")] in by_name), None)
            if store:
                break
        if roots and store:
            pool = roots[0]["resource_pool"]
            break
        store = None
    if not (folder and pool and store):
        fail("the fourth door: could not resolve a folder, and one cluster's root pool with a datastore it uses")
    spec = {"name": name, "guest_OS": "UBUNTU_64", "placement": {"folder": folder, "resource_pool": pool, "datastore": store},
            "cpu": {"count": 1}, "memory": {"size_MiB": 512}, "disks": [{"new_vmdk": {"capacity": 1073741824}}]}
    if dry_run:
        print(f"  DRY RUN, the fourth door would create in vCenter: a machine named {name}, 1 vCPU, 512 MiB, a 1 GiB disk, "
              f"in a folder the Supervisor does not own, on one cluster's root pool and a datastore that cluster's machines "
              f"use, then delete it and read it back. Nothing was created.")
        return None
    out = {"probedUtc": None, "created": None, "declaredByANamespace": None, "claimedByADeployment": None,
           "tenantQuotaDeltaBytes": None, "deleted": None}
    before = used_bytes()
    st, r = vc("/api/vcenter/vm", "POST", spec)
    out["created"] = st
    if st not in (200, 201):
        why = " ".join(m.get("default_message", "") for m in ((r or {}).get("messages") or []) if isinstance(m, dict))
        out["refusal"] = {"errorType": (r or {}).get("error_type"), "message": " ".join(why.split())[:300]}
        print(f"  fourth door: vCenter refused the create (HTTP {st}, {out['refusal']['errorType']}): {L.scrub(out['refusal']['message'])}")
        return out
    moid = r if isinstance(r, str) else (r or {}).get("value")
    try:
        asked = [e.ns(url, f"/apis/{VMOP}/v1alpha5/namespaces/{ns}/virtualmachines/{name}")[0] for _p, ns, url in namespaces]
        out["declaredByANamespace"] = any(a == 200 for a in asked)
        out["namespacesAsked"] = len(asked)
        out["claimedByADeployment"] = any(
            name in json.dumps(res.get("properties") or {})
            for d in e.classic("/deployment/api/deployments")
            for res in e.classic(f"/deployment/api/deployments/{d['id']}/resources", sort="name,asc"))
        out["tenantQuotaDeltaBytes"] = used_bytes() - before
    finally:
        st, _ = vc(f"/api/vcenter/vm/{moid}", "DELETE")
        stg, _ = vc(f"/api/vcenter/vm/{moid}")
        out["deleted"] = (st, stg == 404)
        out["probedUtc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    print(f"  fourth door: created straight in vCenter, declared by {sum(1 for a in asked if a == 200)} of {len(asked)} "
          f"namespace(s), claimed by {'a' if out['claimedByADeployment'] else 'no'} deployment, and it moved the tenant "
          f"storage quota by {out['tenantQuotaDeltaBytes']} bytes. Deleted, and gone: {stg == 404}")
    return out


# --------------------------------------------------------------------------- the probe

def release_and_request(e, project, bpname, content, deployment_name, inputs, version="1.0.0"):
    """The three calls behind the catalog form, which are the three calls a pipeline makes. The version object's
    name is DERIVED: it must equal "<blueprint>:<version>". And the catalog item appears asynchronously after the
    release, so a request issued immediately finds nothing to request."""
    out = {}
    st, _ = e.gw(f"/apis/{BP}/namespaces/{project}/blueprints", "POST",
                 {"apiVersion": BP, "kind": "Blueprint", "metadata": {"name": bpname, "namespace": project},
                  "spec": {"content": content, "description": "created by doors.py, deleted by the same run"}})
    out["blueprintStatus"] = st
    st, _ = e.gw(f"/apis/{BP}/namespaces/{project}/blueprintversions", "POST",
                 {"apiVersion": BP, "kind": "BlueprintVersion", "metadata": {"name": f"{bpname}:{version}", "namespace": project},
                  "spec": {"blueprintName": bpname, "version": version, "publishToCatalog": True}})
    out["releaseStatus"] = st
    item = None
    for _ in range(12):     # the catalog item is published asynchronously; poll rather than guess a wait
        time.sleep(5)
        item = next((i for i in e.classic("/catalog/api/items") if i.get("name") == bpname), None)
        if item:
            break
    # The classic project list refuses a sort= parameter (G-645); unsorted it is one page here.
    st, projects = e.api("/project-service/api/projects?size=200&page=0")
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
    promo = next((c for c in (stt.get("conditions") or []) if c.get("type") == "VirtualMachineDiskPromotionSynced"), {})
    return {"labelKeys": sorted((md.get("labels") or {}).keys()), "annotationKeys": sorted((md.get("annotations") or {}).keys()),
            "ownerReferences": [o.get("kind") for o in (md.get("ownerReferences") or [])],
            "powerState": stt.get("powerState"), "specKeys": sorted((v.get("spec") or {}).keys()),
            "promoteDisksMode": (v.get("spec") or {}).get("promoteDisksMode"),
            "diskPromotion": promo.get("reason") if promo else None, "deleting": bool(md.get("deletionTimestamp"))}


def wait_for(fn, ok, limit=40, every=10):
    for i in range(limit):
        v = fn()
        if ok(v):
            return (i + 1) * every, v
        time.sleep(every)
    return None, fn()


def taken_names(e, project, url, vms, bpname):
    """Every object this probe would create that already exists: a machine, the blueprint or its version, a catalog
    item in either catalog, or a deployment, by the probe's prefix or exact name."""
    enc = urllib.parse.quote(f"{bpname}:1.0.0", safe="")
    found = [v["metadata"]["name"] for v in e.items(url, vms) if v["metadata"]["name"].startswith(PREFIX)]
    found += [bpname] if e.gw(f"/apis/{BP}/namespaces/{project}/blueprints/{bpname}")[0] == 200 else []
    found += [f"{bpname}:1.0.0"] if e.gw(f"/apis/{BP}/namespaces/{project}/blueprintversions/{enc}")[0] == 200 else []
    found += [i["metadata"]["name"] for i in e.items(gateway(e), f"/apis/{CATG}/namespaces/{project}/catalogitems")
              if i["metadata"]["name"].startswith(PREFIX)]
    found += [i.get("name") for i in e.classic("/catalog/api/items") if str(i.get("name", "")).startswith(PREFIX)]
    found += [d.get("name") for d in e.classic("/deployment/api/deployments") if str(d.get("name", "")).startswith(PREFIX)]
    return found


def probe(e, L, project, ns, url, image, storage, vmclass):
    """Build the same machine through two doors, compare them, and delete both. Nothing pre-existing is touched.

    Every name is prefixed and created by this run. Cleanup runs even when a step fails, and the residue check
    reads back the machines, the deployment, the blueprint and version, and both catalogs.
    """
    vms = f"/apis/{VMOP}/v1alpha5/namespaces/{ns}/virtualmachines"
    a_name, c_name, bpname = f"{PREFIX}-direct", f"{PREFIX}-catalog", f"{PREFIX}-probe"
    out = {"probedUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "direct": {}, "catalog": {},
           "identical": None, "teardown": {}}
    manifest_spec = {"className": vmclass, "imageName": image, "storageClass": storage, "powerState": "PoweredOn"}
    dep_id = None
    # The teardown below deletes by name, so every name this run would create is checked first: if one is taken,
    # the object holding it is somebody else's and the run stops before creating anything.
    taken = taken_names(e, project, url, vms, bpname)
    if taken:
        fail(f"{len(taken)} object(s) already carry this probe's names ({PREFIX}-*); nothing was created and nothing "
             f"was deleted. Remove them, or run in another namespace or project")
    try:
        # ---- door 1: straight at the namespace endpoint, which is what kubectl apply does
        st, r = e.ns(url, vms, "POST", {
            "apiVersion": f"{VMOP}/v1alpha5", "kind": "VirtualMachine",
            "metadata": {"name": a_name, "namespace": ns, "labels": {"app.kubernetes.io/name": a_name, "handbook-probe": "three-doors"}},
            "spec": dict(manifest_spec)})
        out["direct"]["createStatus"] = st
        if st not in (200, 201):
            out["direct"]["refusal"] = msg(r)[:400]
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
                   "        spec:\n%s\n") % (bpname, VMOP, "\n".join(f"          {k}: {v}" for k, v in manifest_spec.items()))
        statuses, dep_id = release_and_request(e, project, bpname, content, c_name, {"target_namespace_name": ns, "vm_name": c_name})
        out["catalog"].update(statuses)
        if dep_id:
            secs, _ = wait_for(lambda: e.api(f"/deployment/api/deployments/{dep_id}")[1],
                               lambda d: (d or {}).get("status") not in ("CREATE_INPROGRESS", None, "?"))
            out["catalog"]["secondsToCreateSuccessful"] = secs
            secs2, _ = wait_for(lambda: read_vm(e, url, ns, c_name), lambda v: v and v["powerState"] == "PoweredOn")
            out["catalog"]["secondsToPoweredOn"] = secs2
            out["catalog"]["machine"] = read_vm(e, url, ns, c_name)
            vm_res = next((r for r in e.classic(f"/deployment/api/deployments/{dep_id}/resources", sort="name,asc")
                           if r.get("type") == "CCI.Supervisor.Resource"), None)
            if vm_res:
                out["catalog"]["claimedBy"] = str((vm_res.get("properties") or {}).get("resourceLink") or "")
            print(f"  CATALOG     requested, deployment settled in ~{secs}s, machine PoweredOn")

        # ---- the comparison this script exists for: owner references and markers decide it (G-643)
        a, c = out["direct"].get("machine"), out["catalog"].get("machine")
        if a and c:
            owners = a["ownerReferences"] + c["ownerReferences"]
            markers = sorted({k for k in a["annotationKeys"] + a["labelKeys"] + c["annotationKeys"] + c["labelKeys"] if MARKER.search(k)})
            out["identical"] = {"ownerReferencesBoth": owners, "markerOnEither": markers,
                                "annotationKeysEqual": a["annotationKeys"] == c["annotationKeys"],
                                "annotationCount": len(a["annotationKeys"]), "specKeysEqual": a["specKeys"] == c["specKeys"],
                                "indistinguishable": not owners and not markers}
            print(f"\n  the two machines are {'INDISTINGUISHABLE' if out['identical']['indistinguishable'] else 'DIFFERENT'}: "
                  f"{len(owners)} owner reference(s) between them, {len(markers)} marker(s) naming a door; "
                  f"annotation sets {'equal' if out['identical']['annotationKeysEqual'] else 'not equal'}")
    finally:
        # ---- teardown, timed, and run whatever happened above
        if dep_id:
            out["teardown"]["catalogDiskPromotionAtDelete"] = (read_vm(e, url, ns, c_name) or {}).get("diskPromotion")
            t0 = time.time()
            e.api(f"/deployment/api/deployments/{dep_id}", "DELETE")
            vm_gone = dep_gone = None
            for _ in range(60):
                time.sleep(10)
                if vm_gone is None and read_vm(e, url, ns, c_name) is None:
                    vm_gone = round(time.time() - t0)
                if e.api(f"/deployment/api/deployments/{dep_id}")[0] == 404:
                    dep_gone = round(time.time() - t0)
                    break
            out["teardown"]["catalogSecondsToVmGone"] = vm_gone
            out["teardown"]["catalogSecondsToDeploymentGone"] = dep_gone
        out["teardown"]["directDiskPromotionAtDelete"] = (read_vm(e, url, ns, a_name) or {}).get("diskPromotion")
        t0 = time.time()
        e.ns(url, f"{vms}/{a_name}", "DELETE")
        # As long as the deployment gets. On 9.1.1 a machine deleted while its disk promotion was still running took
        # over five minutes to go, and the record keeps that state so a slow delete can be read rather than guessed (G-647).
        secs, _ = wait_for(lambda: read_vm(e, url, ns, a_name), lambda v: v is None, limit=60)
        out["teardown"]["directSecondsToVmGone"] = secs
        enc = urllib.parse.quote(f"{bpname}:1.0.0", safe="")
        e.gw(f"/apis/{BP}/namespaces/{project}/blueprintversions/{enc}", "DELETE")
        time.sleep(6)
        e.gw(f"/apis/{BP}/namespaces/{project}/blueprints/{bpname}", "DELETE")
        time.sleep(8)
        # ---- residue: everything this run could have made, read back
        machines = [v["metadata"]["name"] for v in e.items(url, vms) if v["metadata"]["name"].startswith(PREFIX)]
        cci_items = [i["metadata"]["name"] for i in e.items(gateway(e), f"/apis/{CATG}/namespaces/{project}/catalogitems")
                     if i["metadata"]["name"].startswith(PREFIX)]
        classic_items = [i.get("name") for i in e.classic("/catalog/api/items") if str(i.get("name", "")).startswith(PREFIX)]
        bp_left = e.gw(f"/apis/{BP}/namespaces/{project}/blueprints/{bpname}")[0] == 200
        ver_left = e.gw(f"/apis/{BP}/namespaces/{project}/blueprintversions/{enc}")[0] == 200
        dep_left = bool(dep_id) and e.api(f"/deployment/api/deployments/{dep_id}")[0] != 404
        out["residue"] = {"machines": machines, "catalogItems": cci_items, "classicCatalogItems": classic_items,
                          "blueprint": bp_left, "version": ver_left, "deployment": dep_left}
        out["clean"] = not (machines or cci_items or classic_items or bp_left or ver_left or dep_left)
        print(f"  teardown    direct ~{secs}s (disk promotion at delete: {out['teardown'].get('directDiskPromotionAtDelete')}); through the deployment ~{out['teardown'].get('catalogSecondsToDeploymentGone')}s "
              f"(its machine gone at ~{out['teardown'].get('catalogSecondsToVmGone')}s)")
        print(f"  residue     {'nothing this run created is still here' if out['clean'] else 'SOMETHING REMAINS, see the record'}")
    return out


def refuse_unknown_args(known):
    """Refuse any argument this script does not recognise, before a client opens: a stray flag must never reach a
    write. --help prints the usage above."""
    args = sys.argv[1:]
    if "-h" in args or "--help" in args:
        print(__doc__)
        sys.exit(0)
    unknown = [a for a in args if a not in known]
    if unknown:
        print(f"unknown argument(s) {unknown}: this script takes {', '.join(sorted(known))} (see --help)", file=sys.stderr)
        sys.exit(5)


def main():
    refuse_unknown_args({"--probe-doors", "--probe-vcenter", "--dry-run"})
    args = sys.argv[1:]
    want_probe, want_vc, dry_run = "--probe-doors" in args, "--probe-vcenter" in args, "--dry-run" in args
    if dry_run and not (want_probe or want_vc):
        print("--dry-run goes with --probe-doors or --probe-vcenter", file=sys.stderr)
        sys.exit(5)
    host, org = os.environ["VCFA_HOST"], os.environ["VCFA_ORG"]
    try:
        refresh, password = secret("VCFA_REFRESH_TOKEN"), secret("VCFA_PASSWORD")
    except OSError as ex:
        fail(ex)
    user = os.environ.get("VCFA_USER")
    if not refresh and not (user and password):
        fail("set VCFA_REFRESH_TOKEN_FILE, or VCFA_USER with VCFA_PASSWORD_FILE (see --help)")
    out_dir = os.environ.get("OUT_DIR", ".")
    e = Estate(host, org, refresh, None if refresh else user, None if refresh else password)
    L = Labels()
    print("doors.py: the same machine, through each door, and what each leaves behind\n")

    projects = [p["metadata"]["name"] for p in e.items(gateway(e), f"/apis/{PROJ}/projects")]
    if not projects:
        fail("no project is visible to this identity")
    for p in projects:
        L.get("project", p)
    project = os.environ.get("DOORS_PROJECT") or next((p for p in projects if _endpoints(e, p)), projects[0])
    if project not in projects:
        fail("DOORS_PROJECT is not a project this sign-in can see")

    needs, per_ns, scope = survey(e, L, project)
    print(f"  in {L.get('project', project)}, what the DIRECT door needs, on this estate:")
    for n in needs["direct"]:
        print(f"     {n['need']:46s} {n['present']}" + (f" of {n['usable']}" if n["usable"] is not None else ""))
    print("  what the AUTOMATION doors need on top:")
    for n in needs["automation"][1:]:
        print(f"     {n['need']:46s} {n['present']}")
    ready = [x for x in per_ns if x["couldBuildAVm"]]
    unknown = [x for x in per_ns if x["couldBuildAVm"] is None]
    print(f"\n  {len(ready)} of {len(per_ns)} namespace(s) could build a VM today (an image they can name and room for a "
          f"20Gi boot disk)" + (f"; {len(unknown)} state no storage limit, so this script cannot judge them" if unknown else ""))
    for x in per_ns:
        room = f"free {x['freeGiB']:>7.1f} GiB of {x['quotaGiB']:.1f}" if x["quotaStated"] else "no storage limit stated"
        verdict = {True: "can build", False: "cannot build here", None: "cannot judge"}[x["couldBuildAVm"]]
        print(f"     {x['namespace']:22s} images {x['imagesBound']:>2} bound {x['imagesCluster']:>2} cluster  classes {x['classes']:>2}  {room}  {verdict}")
    if scope and scope.get("clusterListStatus") == 200:
        print(f"  images: {scope['namespaceImages']} bound to these namespaces, {scope['clusterImages']} cluster-scoped "
              f"({scope['clusterGeneral']} general-purpose), sharing "
              f"{scope['sharedById']} by id and {scope['sharedByDisplayName']} by name; {scope['clusterNodeImages']} of the "
              f"cluster-scoped are Kubernetes node images, {scope['clusterUbuntuNodeImages']} of the {scope['clusterUbuntu']} "
              f"that are Ubuntu")
    elif scope:
        print(f"  images: the cluster-scoped list answered HTTP {scope['clusterListStatus']} to this sign-in")

    buys = claims(e, L)
    vc_host = os.environ.get("VC_HOST")
    creds = credentials(e, project, vc_host)
    print("\n  what a deployment record CLAIMS and what the claim BUYS")
    print(f"     the claim is one string: {L.scrub(buys['linkShape'] or '') or 'no claimed machine on this estate to read'}")
    print(f"     {len(buys['deploymentActions'])} deployment-level and {len(buys['resourceActions'])} "
          f"resource-level Day-2 action(s) exist on a claimed machine")
    if buys["resourceActions"]:
        print(f"     {', '.join(buys['resourceActions'][:6])}{' ...' if len(buys['resourceActions']) > 6 else ''}")
    print(f"     the record carries {len(buys['recordFields'])} field(s), including who asked and what they typed")

    fourth = None
    if want_vc:
        session, owned = vcenter_session(vc_host) if vc_host else (None, False)
        if not session:
            fail("--probe-vcenter needs VC_HOST with VCENTER_USER and VCENTER_PASSWORD_FILE, or VC_SESSION_FILE")
        print("\n  the fourth door: a machine made straight in vCenter, which is not one of the three")
        try:
            fourth = probe_vcenter(e, L, vc_host, session, _endpoints(e, project), dry_run)
        finally:
            if owned:   # a session this run opened is closed by it; one handed in stays the caller's
                try:
                    urllib.request.urlopen(urllib.request.Request(f"https://{vc_host}/api/session", method="DELETE",
                                           headers={"vmware-api-session-id": session}), context=ctx(), timeout=30)
                except (urllib.error.URLError, OSError):
                    pass

    probed = None
    if want_probe:
        ns = os.environ.get("DOORS_NAMESPACE")
        if not ns:
            fail("--probe-doors needs DOORS_NAMESPACE set to a namespace you may build in")
        match = [(p, n, u) for (p, n, u) in _endpoints(e, project) if n == ns]
        if not match:
            fail("DOORS_NAMESPACE is not a namespace with an endpoint in the chosen project")
        url = match[0][2]
        images = [i["metadata"]["name"] for i in e.items(url, f"/apis/{VMOP}/v1alpha5/namespaces/{ns}/virtualmachineimages")] \
            + [g[0] for g in general_cluster_images(e, url)]
        classes = sorted(c["metadata"]["name"] for c in e.items(url, f"/apis/{VMOP}/v1alpha5/namespaces/{ns}/virtualmachineclasses"))
        row = next((x for x in per_ns if x["namespace"] == L.get("namespace", ns)), None)
        if not images:
            fail("that namespace can name no general-purpose VM image, bound or cluster-scoped; the direct door cannot "
                 "open there. The Kubernetes node images in the cluster list do not help.")
        if not row or not row["quotaStated"] or row["freeGiB"] <= 20:
            fail("that namespace has no stated storage limit or under 20 GiB left; the probe needs 20 GiB for a boot disk")
        storage = os.environ.get("DOORS_STORAGE_CLASS") or next(
            (s for s in ((v.get("spec") or {}).get("storageClass") for v in e.items(url, f"/apis/{VMOP}/v1alpha5/namespaces/{ns}/virtualmachines")) if s), None)
        if not storage:
            fail("could not infer a storage class; set DOORS_STORAGE_CLASS")
        vmclass = "best-effort-xsmall" if "best-effort-xsmall" in classes else (classes[0] if classes else None)
        L.get("storageclass", storage)
        if dry_run:
            taken = taken_names(e, project, url, f"/apis/{VMOP}/v1alpha5/namespaces/{ns}/virtualmachines", f"{PREFIX}-probe")
            print(f"\n  DRY RUN, the probe would create in {L.get('namespace', ns)}: a VirtualMachine named {PREFIX}-direct "
                  f"(class {vmclass}, the first image it can name, storage class {L.get('storageclass', storage)}); a blueprint "
                  f"{PREFIX}-probe and its version {PREFIX}-probe:1.0.0 released to the catalog in {L.get('project', project)}; "
                  f"and a catalog request for a deployment and machine named {PREFIX}-catalog. It would then delete all of "
                  f"them and read back the machines, the deployment, the blueprint, the version and both catalogs. "
                  + (f"{len(taken)} object(s) already carry these names, so a real run would stop before creating "
                     f"anything. " if taken else "No name it would use is taken. ") + "Nothing was created.")
        else:
            print(f"\n  probe: building the same machine twice in {L.get('namespace', ns)}, then deleting both and reading back")
            probed = probe(e, L, project, ns, url, images[0], storage, vmclass)
    else:
        print("\n  probe: not run (pass --probe-doors to build the same machine through two doors and compare)")

    # A run writes only what it read. An earlier run's probe stays in its own record (records/), never carried
    # forward under this run's date (G-639).
    payload = {"captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "signIn": e.kind,
               "project": L.get("project", project), "needs": needs, "namespaces": per_ns, "imageScope": scope,
               "claimBuys": buys, "credentials": creds, "probe": probed, "fourthDoor": fourth}
    L.get("org", org)
    text = L.scrub(json.dumps(payload, indent=1, ensure_ascii=False))
    for value in (e.bearer, refresh, password, user, host, os.environ.get("DOORS_NAMESPACE"), vc_host):
        assert not value or value not in text, "an estate value reached the record"
    assert "{{{{" not in text, "a placeholder was scrubbed twice"
    assert not re.search(r"VirtualMachine:[A-Za-z0-9]", (buys or {}).get("linkShape") or ""), \
        "a machine name survived inside the deployment claim; register machine names before scrubbing"
    bare = PLACEHOLDER.sub("", text)
    for fam, m in L.maps.items():
        for nm in m:
            if nm and re.search(r"(?<![A-Za-z0-9-])" + re.escape(nm) + r"(?![A-Za-z0-9-])", bare):
                shp = re.sub(r"[A-Za-z]", "a", re.sub(r"[0-9]", "9", nm))
                fail(f"a {fam} name ({len(nm)} characters, shape {shp}) reached the record; nothing was written")
    os.makedirs(out_dir, exist_ok=True)
    open(os.path.join(out_dir, "doors.json"), "w", encoding="utf-8").write(text + "\n")
    print(f"\nwrote doors.json ({len(per_ns)} namespace(s), {len(buys['deploymentActions']) + len(buys['resourceActions'])} "
          f"Day-2 action(s) counted{', probe included' if probed else ''}); every estate name replaced by a placeholder")
    if (probed and not probed.get("clean", True)) or (fourth and fourth.get("deleted") and not fourth["deleted"][1]):
        sys.exit(3)
    sys.exit(0)


if __name__ == "__main__":
    main()
