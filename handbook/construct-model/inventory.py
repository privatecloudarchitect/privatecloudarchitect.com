#!/usr/bin/env python3
"""inventory.py - the construct model, read from your own estate.

Records, all read-only, through the Cloud Consumption Interface with an organization's bearer:

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
  edges.json      the edge map: every relationship between constructs, one row each, with its declared cardinality,
                  the field that establishes it, how many objects stood on each side, and whether the estate bore the
                  cardinality out. The provider edges (regions, Supervisors, zones, content libraries, regional
                  networking) are read through the Tenant Manager when VCFA_PROVIDER_BEARER_FILE is set. Counts only

Every name that belongs to your estate is replaced by a stable placeholder on the way into the records
({{project-1}}, {{namespace-2}}, {{region-1}}, {{zone-2}}, {{class-1}}, {{vpc-1}}, {{org}}, {{id}}), so the records
can be published and diffed; the script refuses to write a record in which any estate name survived. Stdlib only. No token is printed or written.

Env:  VCFA_HOST, VCFA_ORG, and either VCFA_REFRESH_TOKEN_FILE (an api-token minted for that org, mode 0600) or
      VCFA_USER with VCFA_PASSWORD_FILE (a session login as user@org, which needs nothing pre-minted; the password
      from a file of mode 0600, or VCFA_PASSWORD, the value itself, which lands in the shell's history); a secret
      file open to group or other is refused before it is read; TLS_VERIFY=false on a self-signed lab CA; OUT_DIR
      (default .); VCFA_PROVIDER_BEARER_FILE (optional, mode 0600) for the provider edges
Exit: 0 the records were written · 1 the mint or the discovery failed
"""

import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

CCI = "/cci/kubernetes"
INFRA = "infrastructure.cci.vmware.com/v1alpha3"
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
# The namespace spec on VCF 9.1.1, as the interface declares it (9.1.1 added `sharedSubnets` and `infraPolicyNames`
# beside the 9.1 fields). `zoneName` and a top-level `storageClasses`
# and `vmClasses` are NOT here: the zone is named inside classConfigOverrides.zones[].name, the storage limit
# inside classConfigOverrides.storageClasses[], and the effective class sets are reported in status. The field
# was `initialClassConfigOverrides` on an earlier build; reading the removed name returns nothing and prints as
# an empty binding, which reads exactly like a namespace that bound nothing.
NS_FIELDS = ("regionName", "className", "vpcName", "segName", "classConfigOverrides", "sharedSubnets", "infraPolicyNames", "description")
NS_STATUS_FIELDS = ("storageClasses", "vmClasses", "zones")


def ctx():
    verify = os.environ.get("TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")
    return ssl.create_default_context() if verify else ssl._create_unverified_context()


PLACEHOLDER = re.compile(r"(\{\{[^}]*\}\})")


def one_pass(text, known, edge="A-Za-z0-9-"):
    """Replace every (real, label) pair in one pass, the longest real name first, on a boundary of `edge` characters
    (none when empty), and never inside a placeholder already written. Replacing one name at a time lets a project
    named project-2 match inside the {{project-2}} just written for the project named project-1 (G-646). When a name
    is given twice, its first label wins."""
    label_of = {}
    for real, label in known:
        label_of.setdefault(real, label)
    if not label_of:
        return text
    names = "|".join(map(re.escape, sorted(label_of, key=len, reverse=True)))
    rx = re.compile(rf"(?<![{edge}])({names})(?![{edge}])" if edge else f"({names})")
    return "".join(part if i % 2 else rx.sub(lambda m: "{{%s}}" % label_of[m.group(1)], part)
                   for i, part in enumerate(PLACEHOLDER.split(text)))


class Labels:
    """Stable labels for estate names: the first region seen is {{region-1}}, the second project is project-2."""
    # The product's own vocabulary is never an estate name. A principal can be called exactly what a platform
    # object is called (this estate has a user named "admin" and a project role named "admin"), and registering
    # one teaches the scrubber to blank the other. A name in RESERVED identifies no estate and is left alone.
    RESERVED = {"admin", "view", "edit", "user", "users", "group", "groups", "owner", "auditor", "auditors",
                "administrator", "administrators", "default", "system", "none", "all"}

    def __init__(self):
        self.maps = {}

    def scrub(self, text, edge="A-Za-z0-9-"):
        """Every registered name replaced in one pass (one_pass), then every id; a non-string passes through."""
        if not isinstance(text, str):
            return text
        return UUID.sub("{{id}}", one_pass(text, [(r, lab) for m in self.maps.values() for r, lab in m.items()], edge))

    def get(self, family, name, braces=True):
        m = self.maps.setdefault(family, {})
        if name not in m:
            m[name] = f"{family}-{len(m) + 1}"
        return "{{%s}}" % m[name] if braces else m[name]


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


class Cci:
    def __init__(self, host, org, refresh_token=None, user=None, password=None):
        """A tenant bearer, from the org's refresh token or from a session login. Either way the server's own answer to a
        refused mint is printed: "invalid_grant" means the grant is dead, a 401 at the session means the login is."""
        self.host = host
        if refresh_token:
            self.kind = "oauth"
            body = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": refresh_token}).encode()
            req = urllib.request.Request(f"https://{host}/oauth/tenant/{org}/token", data=body, method="POST",
                                         headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
        else:
            self.kind = "session"
            basic = __import__("base64").b64encode(f"{user.split('@')[0]}@{org}:{password}".encode()).decode()
            req = urllib.request.Request(f"https://{host}/cloudapi/1.0.0/sessions", method="POST",
                                         headers={"Authorization": f"Basic {basic}", "Accept": "application/json;version=40.0"})
        try:
            with urllib.request.urlopen(req, context=ctx(), timeout=30) as r:
                self.bearer = json.loads(r.read())["access_token"] if refresh_token else r.headers.get("X-VMWARE-VCLOUD-ACCESS-TOKEN")
        except urllib.error.HTTPError as e:
            raise SystemExit(f"FATAL: the {self.kind} mint answered HTTP {e.code}: {e.read().decode(errors='replace')[:200]}")
        if not self.bearer:
            raise SystemExit(f"FATAL: the {self.kind} mint answered without a bearer")

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

    def send(self, method, path, body, ctype="application/json"):
        """Only ever used for attempts the server is expected to refuse; see probe_bindings."""
        req = urllib.request.Request(f"https://{self.host}{CCI}{path}", data=json.dumps(body).encode(), method=method,
                                     headers={"Authorization": f"Bearer {self.bearer}", "Accept": "application/json", "Content-Type": ctype})
        try:
            with urllib.request.urlopen(req, context=ctx(), timeout=60) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, raw.decode(errors="replace")[:400]
        except (urllib.error.URLError, OSError) as e:
            return None, str(e)



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
        # Some kinds are presented as colon-scoped paths (a subnet reads "<project>:<vpc>:<subnet>"), and the
        # operator only ever chooses the last segment. A colon cannot appear in a conforming name, so taking the
        # last segment is safe for every construct and is the only fair thing to lint.
        conform = sum(1 for n in names if rx.match(n.rsplit(":", 1)[-1]))
        out[construct] = {"objects": len(names), "conform": conform, "convention": rule["convention"],
                          "example": rule["example"], "pattern": rule["pattern"],
                          "verdict": "keep" if conform == len(names) else ("refine" if conform else "rename")}
    return out



# ---- the bindings a namespace makes at create: asked of the platform, not inferred
#
# Every request below is one the server refuses by design, and each carries a value no server can apply:
#   * a class, region, and VPC name that exist nowhere ("zz-probe-..."), so even an accepted edit has nothing to bind to;
#   * a parent project taken from the estate, sent in the body while the URL still addresses the real parent, which is
#     the shape a Kubernetes API server rejects as a namespace mismatch rather than a move.
# The one thing this function must never send is a patch whose value IS applicable. A patch of any spec field with a
# value the server accepts (even the field's current value) dispatches a real tenant-manager edit task on the namespace,
# after which the next attempt answers HTTP 409 "edit in progress" instead of the question you asked. The function
# reads the namespace before and after and refuses to write a record if one byte of its spec moved.
SENTINEL = "zz-probe-value-that-exists-nowhere"
IMMUTABLE_FIELDS = ("className", "regionName", "vpcName")


# ---- the edge map: every relationship between constructs, with the field that proves it, read rather than drawn
#
# Every pair is (From, To). "a : b" says how many From each To has (a) and how many To each From has (b): in
# "Supervisor Namespace N : 1 Region" each namespace names exactly one region and a region holds many namespaces.
# "0+" allows none. A cardinality is a claim about the model, so the record keeps it beside what the run observed
# and says whether the estate bears it out, instead of publishing the claim on its own.
CARDINALITY = {   # (From per To, To per From), each as (minimum, maximum or None)
    "1 : 1": ((1, 1), (1, 1)), "1 : N": ((1, 1), (1, None)), "1 : 0+": ((1, 1), (0, None)),
    "N : 1": ((1, None), (1, 1)), "N : N": ((1, None), (1, None)),
}


def edge(frm, card, to, field, surface, pairs, froms=None, read=True, why=None):
    """One edge. `pairs` is every (From, To) the run read for it; `froms` is every From there is, so a From with no
    To still counts where the cardinality allows none. Names stay in memory: the row carries counts only. A row the
    run could not read says so and why; a row read with no instance on this estate says that, rather than looking
    empty."""
    row = {"from": frm, "cardinality": card, "to": to, "field": field, "surface": surface}
    if not read:
        return {**row, "tier": "not read", "why": why}
    pairs = sorted({(str(x), str(y)) for x, y in pairs if x and y})
    xs = sorted(set(map(str, froms or [])) | {x for x, _ in pairs})
    ys = sorted({y for _, y in pairs})
    to_per_from = [sum(1 for x, _ in pairs if x == f) for f in xs]
    from_per_to = [sum(1 for _, y in pairs if y == t) for t in ys]
    span = lambda v: [min(v), max(v)] if v else None
    (fmin, fmax), (tmin, tmax) = CARDINALITY[card]
    within = lambda v, lo, hi: all(lo <= n and (hi is None or n <= hi) for n in v)
    holds = (within(from_per_to, fmin, fmax) and within(to_per_from, tmin, tmax)) if pairs else None
    return {**row, "tier": "live" if pairs else "none here", "fromCount": len(xs), "toCount": len(ys),
            "toPerFrom": span(to_per_from), "fromPerTo": span(from_per_to), "holds": holds}


def edge_map(org, projects, namespaces, regions, zones, vpcs, vmcs, workloads, provider):
    """The construct edges, from what the run already read. `namespaces` is (project, namespace object);
    `workloads` maps a namespace to its machines, VKS clusters and VirtualMachineServices; `provider` is the
    Tenant Manager read, or the reason there is none. The access-control edges (roles, rights, groups) are the
    access-control chapter's; the overlay above the VPC is the network plane's."""
    T, P = "tenant, Cloud Consumption Interface", "provider, Tenant Manager"
    name = lambda o: o["metadata"]["name"]
    sp = lambda o: o.get("spec") or {}
    stt = lambda o: o.get("status") or {}
    labels = lambda o: (o.get("metadata") or {}).get("labels") or {}
    nss = [n for _, n in namespaces]
    vms = [(ns, v) for ns, w in workloads.items() for v in w["vms"]]
    clusters = [(ns, k) for ns, w in workloads.items() for k in w["clusters"]]
    services = [(ns, x) for ns, w in workloads.items() for x in w["services"]]
    vm_id = lambda ns, v: ns + "/" + name(v)
    region_names = [name(r) for r in regions]
    rows = [
        edge("Organization", "1 : 0+", "Project", "the project lives in the organization the sign-in is scoped to", T,
             [(org, p) for p in projects], froms=[org]),
        edge("Project", "1 : 0+", "Supervisor Namespace", "the namespace is listed under its project (metadata.namespace)", T,
             [(p, name(n)) for p, n in namespaces], froms=projects),
        edge("Supervisor Namespace", "N : 1", "Region", "spec.regionName", T, [(name(n), sp(n).get("regionName")) for n in nss]),
        edge("Supervisor Namespace", "N : 1", "Namespace Class", "spec.className", T, [(name(n), sp(n).get("className")) for n in nss]),
        edge("Supervisor Namespace", "N : 1", "VPC", "spec.vpcName", T,
             [(name(n), sp(n).get("vpcName") or stt(n).get("vpcName")) for n in nss]),
        edge("Supervisor Namespace", "N : N", "Zone", "status.zones[].name", T,
             [(name(n), z.get("name")) for n in nss for z in stt(n).get("zones") or []]),
        edge("Supervisor Namespace", "N : N", "Storage Class", "status.storageClasses[].name", T,
             [(name(n), x.get("name")) for n in nss for x in stt(n).get("storageClasses") or []]),
        edge("Supervisor Namespace", "N : N", "VM Class", "status.vmClasses[].name", T,
             [(name(n), x.get("name")) for n in nss for x in stt(n).get("vmClasses") or []]),
        edge("Supervisor Namespace", "1 : 0+", "VirtualMachine", "metadata.namespace, behind the namespace's endpoint", T,
             [(ns, vm_id(ns, v)) for ns, v in vms], froms=list(workloads)),
        edge("Supervisor Namespace", "1 : 0+", "VKS Cluster", "metadata.namespace, behind the namespace's endpoint", T,
             [(ns, vm_id(ns, k)) for ns, k in clusters], froms=list(workloads)),
        edge("Region", "1 : N", "Zone", "Zone spec.regionName", T,
             [(sp(z).get("regionName"), sp(z).get("zoneName") or name(z)) for z in zones], froms=region_names),
        edge("Region", "1 : 0+", "VPC", "VPC spec.regionName", T, [(sp(v).get("regionName"), name(v)) for v in vpcs], froms=region_names),
        edge("Region", "1 : 0+", "VM Class", "RegionVirtualMachineClassSummary spec.regionName", T,
             [(sp(m).get("regionName"), sp(m).get("vmClassName") or name(m)) for m in vmcs], froms=region_names),
        edge("VirtualMachine", "N : 1", "VM Class", "spec.className", T, [(vm_id(ns, v), sp(v).get("className")) for ns, v in vms]),
        edge("VirtualMachine", "N : 1", "VM Image", "spec.imageName", T,
             [(vm_id(ns, v), sp(v).get("imageName") or (sp(v).get("image") or {}).get("name")) for ns, v in vms]),
        edge("VirtualMachine", "N : 1", "Storage Class", "spec.storageClass", T, [(vm_id(ns, v), sp(v).get("storageClass")) for ns, v in vms]),
        edge("VirtualMachine", "N : N", "Network", "spec.network.interfaces[].network.name", T,
             [(vm_id(ns, v), (i.get("network") or {}).get("name")) for ns, v in vms for i in (sp(v).get("network") or {}).get("interfaces") or []]),
        edge("VirtualMachine", "N : 1", "Zone", "label topology.kubernetes.io/zone", T,
             [(vm_id(ns, v), labels(v).get("topology.kubernetes.io/zone")) for ns, v in vms]),
        edge("VKS Cluster", "1 : N", "Node VirtualMachine", "label cluster.x-k8s.io/cluster-name on each node", T,
             [(ns + "/" + labels(v)["cluster.x-k8s.io/cluster-name"], vm_id(ns, v)) for ns, v in vms if labels(v).get("cluster.x-k8s.io/cluster-name")],
             froms=[vm_id(ns, k) for ns, k in clusters]),
        edge("VirtualMachineService", "N : N", "VirtualMachine", "spec.selector matched against each machine's labels", T,
             [(vm_id(ns, x), vm_id(ns, v)) for ns, x in services for ns2, v in vms if ns2 == ns and sp(x).get("selector")
              and all(labels(v).get(k) == val for k, val in sp(x)["selector"].items())],
             froms=[vm_id(ns, x) for ns, x in services]),
        edge("VirtualMachineService", "1 : 0+", "Load balancer address", "status.loadBalancer.ingress[].ip", T,
             [(vm_id(ns, x), i.get("ip")) for ns, x in services for i in ((stt(x).get("loadBalancer") or {}).get("ingress") or [])],
             froms=[vm_id(ns, x) for ns, x in services]),
    ]
    if isinstance(provider, str):
        return rows + [edge(f, c, t, fld, P, [], read=False, why=provider) for f, c, t, fld in PROVIDER_EDGES]
    ref = lambda o, k: (o.get(k) or {}).get("id") if isinstance(o.get(k), dict) else None
    regs, sups, szs, libs, nets, rsps = (provider[k] for k in ("regions", "supervisors", "zones", "libraries", "networking", "storagePolicies"))
    pairs = {
        "Region.supervisors[]": ([(r["id"], x.get("id") if isinstance(x, dict) else x) for r in regs for x in r.get("supervisors") or []], [r["id"] for r in regs]),
        "Supervisor.region": ([(x.get("supervisorId"), ref(x, "region")) for x in sups], None),
        "Region.nsxManager": ([(r["id"], ref(r, "nsxManager")) for r in regs], None),
        "RegionStoragePolicy.region": ([(ref(x, "region"), x["id"]) for x in rsps], [r["id"] for r in regs]),
        "Supervisor.virtualCenter": ([(x.get("supervisorId"), ref(x, "virtualCenter")) for x in sups], None),
        "SupervisorZone.supervisor": ([(ref(z, "supervisor"), z["id"]) for z in szs], [x.get("supervisorId") for x in sups]),
        "SupervisorZone.zone": ([(z["id"], ref(z, "zone")) for z in szs], None),
        "ContentLibrary.org": ([(ref(lib, "org"), lib["id"]) for lib in libs], None),
        "RegionalNetworkingSetting.orgRef and regionRef": ([(ref(x, "orgRef"), ref(x, "regionRef")) for x in nets], None),
        "RegionalNetworkingSetting.providerGatewayRef": ([(x["id"], ref(x, "providerGatewayRef")) for x in nets], None),
    }
    return rows + [edge(f, c, t, fld, P, pairs[fld][0], froms=pairs[fld][1]) for f, c, t, fld in PROVIDER_EDGES]


PROVIDER_EDGES = (   # (From, cardinality, To, the field that proves it), read through the Tenant Manager
    ("Region", "1 : N", "Supervisor", "Region.supervisors[]"),
    ("Supervisor", "N : 1", "Region", "Supervisor.region"),
    ("Region", "1 : 1", "NSX Manager", "Region.nsxManager"),
    ("Region", "1 : N", "Storage Policy", "RegionStoragePolicy.region"),
    ("Supervisor", "N : 1", "vCenter", "Supervisor.virtualCenter"),
    ("Supervisor", "1 : N", "Supervisor Zone", "SupervisorZone.supervisor"),
    ("Supervisor Zone", "1 : 1", "vSphere Zone", "SupervisorZone.zone"),
    ("Organization", "1 : 0+", "Content Library", "ContentLibrary.org"),
    ("Organization", "N : N", "Region", "RegionalNetworkingSetting.orgRef and regionRef"),
    ("Regional networking", "N : 1", "Provider Gateway", "RegionalNetworkingSetting.providerGatewayRef"),
)


def read_provider(host, bearer):
    """The provider side of the map, through the Tenant Manager with a provider bearer, read-only. Each list is read
    to its end. The vCenter list is never read: it carries its connection's username and password."""
    def page(path):
        out, n = [], 1
        while True:
            req = urllib.request.Request(f"https://{host}/cloudapi{path}?page={n}&pageSize=128",
                                         headers={"Authorization": f"Bearer {bearer}", "Accept": "application/json;version=40.0"})
            with urllib.request.urlopen(req, context=ctx(), timeout=60) as r:
                body = json.loads(r.read())
            out += body.get("values") or []
            if n >= (body.get("pageCount") or 1):
                return out
            n += 1
    try:
        return {"regions": page("/v1/regions"), "supervisors": page("/v1/supervisors"), "zones": page("/v1/supervisorZones"),
                "libraries": page("/v1/contentLibraries"), "networking": page("/v1/regionalNetworkingSettings"),
                "storagePolicies": page("/v1/regionStoragePolicies")}
    except urllib.error.HTTPError as e:
        return f"the Tenant Manager answered HTTP {e.code}"
    except (urllib.error.URLError, OSError, ValueError) as e:
        return f"the Tenant Manager did not answer ({type(e).__name__})"


def probe_bindings(c, project, namespace, other_project, L):
    """Ask the interface whether the create-time bindings and the parent project can be changed."""
    base = f"/apis/{INFRA}/namespaces/{project}/supervisornamespaces/{namespace}"
    st, before = c.get(base)
    if st != 200:
        return None, f"the namespace could not be read back (HTTP {st})"
    frozen = json.dumps(before.get("spec"), sort_keys=True)
    asked = []

    def scrub(text):
        """The server quotes the namespace and the projects back at you; those are estate names.

        One pass, longest name first. Family-by-family replacement is wrong here: a namespace name can contain a
        project name, so replacing projects first breaks the namespace name before it can be matched as a whole.
        """
        # Longest first so a contained name cannot corrupt a longer one, and on a WORD BOUNDARY so a short
        # name is not replaced inside an unrelated word. A principal really can be called "admin", and a naive
        # replace turns the field name "administrators" into "{{user-3}}istrators". The leak check below uses
        # the same boundary, so what the scrub replaces and what the check looks for are one rule.
        return L.scrub(text)

    def record(question, method, sent, st, body):
        answer = body.get("message") if isinstance(body, dict) else body
        asked.append({"question": question, "method": method, "sent": sent, "status": st,
                      "answer": scrub(answer.strip()) if isinstance(answer, str) else answer})

    def patient(fn, tries=20):
        """A 409 means an edit is already in flight on this namespace; it is not an answer to the question."""
        for i in range(tries):
            st, body = fn()
            if st != 409:
                return st, body
            time.sleep(15)
        return st, body

    for field in IMMUTABLE_FIELDS:
        st, body = patient(lambda f=field: c.send("PATCH", base, {"spec": {f: SENTINEL}}, "application/merge-patch+json"))
        record(f"can spec.{field} be changed after create?", "PATCH", f"spec.{field} = a value that exists nowhere", st, body)

    st, body = patient(lambda: c.send("PATCH", base, {"metadata": {"namespace": SENTINEL}}, "application/merge-patch+json"))
    record("can the parent project be changed by patching metadata.namespace?", "PATCH", "metadata.namespace = a project that does not exist", st, body)

    if other_project:
        moved = json.loads(json.dumps(before)); moved["metadata"]["namespace"] = other_project
        st, body = patient(lambda: c.send("PUT", base, moved))
        record("can the namespace be re-parented into another project that really exists?", "PUT",
               "the whole object, body.metadata.namespace = a sibling project, URL unchanged", st, body)

    st, after = c.get(base)
    if st != 200 or json.dumps(after.get("spec"), sort_keys=True) != frozen:
        raise SystemExit("FATAL: the namespace's spec is not what it was before these attempts; not writing a record")
    health = {cnd.get("type"): cnd.get("status") for cnd in (after.get("status", {}).get("conditions") or [])}
    return {"namespace": L.get("namespace", namespace), "phase": after.get("status", {}).get("phase"),
            "conditions": health, "spec_unchanged": True, "attempts": asked}, None



# ---- the second surface: the Tenant Manager, whose namespace body carries the project assignment
#
# The Cloud Consumption Interface has no project field to change, so its refusal is structural and says nothing
# about the platform's intent. The Tenant Manager's own namespace API is the one place the assignment IS a field
# in the update body, which makes it the only surface that can answer the question in words. Writing there needs a
# right a project team does not have, so this runs only when you supply a bearer that holds it.
TM_VER = "application/json;version=9.1.0"


def probe_tenant_manager(host, bearer, namespace_name, scrub):
    """Ask the Tenant Manager whether a namespace's project assignment can change. Every attempt is refused.

    The organization is resolved by looking for the one that actually holds the namespace we probed, because the
    identifier the token endpoint takes is not the identifier this API's tenant context takes.
    """
    ctx_org = {"v": None}

    def tm(method, path, body=None):
        h = {"Authorization": f"Bearer {bearer}", "Accept": TM_VER}
        if ctx_org["v"]:
            h["X-VMWARE-VCLOUD-TENANT-CONTEXT"] = ctx_org["v"].rsplit(":", 1)[-1]
        if body is not None:
            h["Content-Type"] = "application/json"
        req = urllib.request.Request(f"https://{host}{path}", data=json.dumps(body).encode() if body is not None else None,
                                     method=method, headers=h)
        try:
            with urllib.request.urlopen(req, context=ctx(), timeout=90) as r:
                raw = r.read()
                try:
                    return r.status, json.loads(raw or b"null")
                except ValueError:
                    return r.status, None
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, raw.decode(errors="replace")[:300]
        except (urllib.error.URLError, OSError) as e:
            return None, str(e)

    st0, orgs = tm("GET", "/cloudapi/1.0.0/orgs")
    if st0 != 200:
        return None, f"the Tenant Manager refused this bearer (HTTP {st0}); it needs one that can manage namespaces"
    sub = None
    for o in (orgs.get("values") or []):
        ctx_org["v"] = o["id"]
        stx, nsx = tm("GET", "/cloudapi/v1/namespaceSummaries")
        if stx == 200:
            sub = next((v for v in (nsx.get("values") or []) if v["name"] == namespace_name), None)
            if sub:
                break
    if not sub:
        return None, "the namespace this run probed is not visible on the Tenant Manager under any organization"
    st, pas = tm("GET", "/cloudapi/v1/projectAssignments")
    if st != 200:
        return None, f"project assignments answered HTTP {st}"
    assignments = pas.get("values") or []
    st3, full = tm("GET", f"/cloudapi/v1/namespaces/{sub['id']}")
    if st3 != 200:
        return None, f"the namespace could not be read back (HTTP {st3})"
    mine = full["projectAssignment"]["id"]
    sibling = next((a for a in assignments if a["id"] != mine), None)
    asked, before = [], json.dumps(full.get("projectAssignment"), sort_keys=True)

    def ask(question, sent, body):
        st4, r4 = tm("PUT", f"/cloudapi/v1/namespaces/{sub['id']}", body)
        answer = r4.get("message") if isinstance(r4, dict) else r4
        asked.append({"question": question, "method": "PUT", "sent": sent, "status": st4,
                      "answer": scrub(answer.strip()) if isinstance(answer, str) else answer})

    if sibling:
        ask("can the project assignment be changed to another project?",
            "the whole object, projectAssignment = a sibling project",
            {**json.loads(json.dumps(full)), "projectAssignment": {"id": sibling["id"], "name": sibling.get("name")}})
    ask("can a namespace be detached from its project?", "the whole object, projectAssignment = null",
        {**json.loads(json.dumps(full)), "projectAssignment": None})

    # the other way a namespace could arrive in a project: adopting one that already exists on the Supervisor.
    # The name below exists nowhere, so nothing can be imported; what comes back is whether the path is open at all.
    stv, vcs = tm("GET", "/cloudapi/1.0.0/virtualCenters")
    vc = next((v for v in (vcs.get("values") or []) if v.get("vcId")), None) if stv == 200 else None
    if vc and ctx_org["v"]:
        body = {"name": "zz-probe-namespace-that-exists-nowhere",
                "org": {"id": ctx_org["v"]},
                "projectAssignment": {"id": mine},
                "vcenter": {"id": vc["vcId"], "name": vc.get("name")}}
        sti, ri = tm("POST", "/cloudapi/v1/namespaces/import", body)
        answer = ri.get("message") if isinstance(ri, dict) else ri
        asked.append({"question": "can a namespace created on the Supervisor be adopted into a project?",
                      "method": "POST", "sent": "an import naming a namespace that exists nowhere", "status": sti,
                      "answer": scrub(answer.strip()) if isinstance(answer, str) else answer})

    st5, after = tm("GET", f"/cloudapi/v1/namespaces/{sub['id']}")
    if st5 != 200 or json.dumps(after.get("projectAssignment"), sort_keys=True) != before:
        raise SystemExit("FATAL: the namespace's project assignment is not what it was; not writing a record")
    return {"namespace": scrub(sub["name"]), "attempts": asked}, None


def refuse_unknown_args(known, takes_value=()):
    """Refuse any argument this script does not recognise, before a client opens: a stray flag such as --check
    must never reach a write. --help prints the usage above."""
    args = sys.argv[1:]
    if "-h" in args or "--help" in args:
        print(__doc__)
        sys.exit(0)
    unknown = [a for i, a in enumerate(args) if a not in known and not (i and args[i - 1] in takes_value)]
    if unknown:
        sys.exit(f"unknown argument(s) {unknown}: this script takes {', '.join(sorted(known))} (see --help)")


def main():
    refuse_unknown_args({"--probe-bindings"})
    host, org = os.environ["VCFA_HOST"], os.environ["VCFA_ORG"]
    try:
        refresh, password = secret("VCFA_REFRESH_TOKEN"), secret("VCFA_PASSWORD")
    except OSError as e:   # a secret file that is missing, unreadable or open to group or other
        raise SystemExit(f"FATAL: {e}") from None
    user = os.environ.get("VCFA_USER")
    if not refresh and not (user and password):
        raise SystemExit("set VCFA_REFRESH_TOKEN_FILE, or VCFA_USER with VCFA_PASSWORD_FILE for a session login")
    out_dir = os.environ.get("OUT_DIR", ".")
    c = Cci(host, org, refresh, user, password); L = Labels(); observed = {}
    secrets = tuple(s for s in (c.bearer, refresh, password, user, host, org) if s)
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
    # Count distinct kinds, not entries: a kind served in two API versions is listed once per version.
    kinds = sorted({(e["group"], e["kind"]) for e in taxonomy})
    top = {(e["group"], e["kind"]) for e in taxonomy if not e["namespaced"]}
    under = {(e["group"], e["kind"]) for e in taxonomy if e["namespaced"]}
    print(f"  taxonomy: {len({e['group'] for e in taxonomy})} VMware API groups, {len(kinds)} kinds; "
          f"{len(top)} published at the top level, {len(under)} under a project")
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
        # Label a zone by the readable name in its spec, not by its object name. The object name is an
        # opaque identifier and the name every other object refers to a zone by is spec.zoneName; labelling
        # by the object name gives the same zone two different placeholders in one record.
        "zones": [{"name": L.get("zone", (z.get("spec") or {}).get("zoneName") or z["metadata"]["name"]), "region": L.get("region", (z.get("spec") or {}).get("regionName", "")), "cpuLimit": (z.get("spec") or {}).get("cpuLimit"), "memoryLimit": (z.get("spec") or {}).get("memoryLimit"), "cpuUsed": (z.get("status") or {}).get("cpuUsed"), "memoryUsed": (z.get("status") or {}).get("memoryUsed")} for z in zones],
        "namespace_classes": [{"name": L.get("class", k["metadata"]["name"])} for k in classes],
        "vpcs": [{"name": L.get("vpc", v["metadata"]["name"]), "region": L.get("region", (v.get("spec") or {}).get("regionName", "")), "privateIPs": len((v.get("spec") or {}).get("privateIPs") or [])} for v in vpcs],
        "subnets": len(subnets), "storage_class_quotas": len(scq), "vm_class_summaries": len(vmcs),
    }
    print(f"  published: {len(regions)} region(s), {len(zones)} zone(s), {len(classes)} namespace class(es), {len(vpcs)} VPC(s), {len(subnets)} subnet(s), {len(scq)} storage-class quota(s), {len(vmcs)} VM class summaries")
    # ---- 3. the projects and their contents
    st, projects = c.items("/apis/project.cci.vmware.com/v1alpha2/projects")
    observed["projects"] = [p["metadata"]["name"] for p in projects]
    observed["namespaces"], observed["virtual-machines"], observed["vks-clusters"] = [], [], []
    first_ns = None
    all_ns, workloads = [], {}   # for the edge map: (project, namespace object), and each namespace's workload objects
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
        st, nss = c.items(f"/apis/{INFRA}/namespaces/{pname}/supervisornamespaces")
        observed["namespaces"] += [n["metadata"]["name"] for n in nss]
        if nss and first_ns is None:
            first_ns = (pname, nss[0]["metadata"]["name"])
        for n in nss:
            all_ns.append((pname, n))
            sp, stt = n.get("spec") or {}, n.get("status") or {}
            ns = {"name": L.get("namespace", n["metadata"]["name"]), "phase": stt.get("phase"),
                  "bound": {"region": L.get("region", sp["regionName"]) if sp.get("regionName") else None,
                            "zone": L.get("zone", ((sp.get("classConfigOverrides") or {}).get("zones") or [{}])[0].get("name")) if ((sp.get("classConfigOverrides") or {}).get("zones") or [{}])[0].get("name") else None,
                            "class": L.get("class", sp["className"]) if sp.get("className") else None, "vpc": L.get("vpc", sp["vpcName"]) if sp.get("vpcName") else None,
                            "storageClasses": len((stt.get("storageClasses") or [])), "vmClasses": len((stt.get("vmClasses") or [])), "classOverrides": bool(sp.get("classConfigOverrides")),
                            "sharedSubnets": len(sp.get("sharedSubnets") or []), "infraPolicies": len(sp.get("infraPolicyNames") or [])},
                  "specFields": sorted(sp.keys()), "workloads": {}}
            ep = stt.get("namespaceEndpointURL")
            if ep:
                supervisor_ns = n["metadata"]["name"]
                held = workloads.setdefault(supervisor_ns, {"vms": [], "clusters": [], "services": []})
                for wl, family, path in (("virtualMachines", "virtual-machines", f"/apis/vmoperator.vmware.com/v1alpha5/namespaces/{supervisor_ns}/virtualmachines"),
                                         ("vksClusters", "vks-clusters", f"/apis/cluster.x-k8s.io/v1beta1/namespaces/{supervisor_ns}/clusters"),
                                         ("vmServices", None, f"/apis/vmoperator.vmware.com/v1alpha5/namespaces/{supervisor_ns}/virtualmachineservices")):
                    st, items = c.items(ep.rstrip("/") + path, absolute=True)
                    ns["workloads"][wl] = len(items) if st == 200 else f"HTTP {st}"
                    if st == 200:
                        held[{"virtualMachines": "vms", "vksClusters": "clusters", "vmServices": "services"}[wl]] = items
                        if family:
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

    # ---- 4a. the edge map: tenant edges from what was read above, provider edges when a provider bearer is given
    try:
        prov_bearer = secret("VCFA_PROVIDER_BEARER")
    except OSError as e:
        raise SystemExit(f"FATAL: {e}") from None
    provider = read_provider(host, prov_bearer) if prov_bearer else "no provider bearer was given (VCFA_PROVIDER_BEARER_FILE)"
    edges = edge_map(org, [p["metadata"]["name"] for p in projects], all_ns, regions, zones, vpcs, vmcs, workloads, provider)
    live = [e for e in edges if e["tier"] == "live"]
    broken = [e for e in edges if e.get("holds") is False]
    print(f"\n  edges: {len(edges)} read, {len(live)} with instances on this estate, "
          f"{sum(1 for e in edges if e['tier'] == 'none here')} with none, {sum(1 for e in edges if e['tier'] == 'not read')} not read"
          + (f"; {len(broken)} whose cardinality the estate contradicts" if broken else "; every observed cardinality holds"))
    for e in edges:
        seen = (f"{e['fromCount']} -> {e['toCount']}; to per from {e['toPerFrom']}, from per to {e['fromPerTo']}"
                + ("" if e["holds"] is not False else "; NOT AS DECLARED") if e["tier"] != "not read" else e["why"])
        print(f"     {e['from']:<22} {e['cardinality']:<7} {e['to']:<22} {e['tier']:<9} {seen}")

    # ---- 4b. optional: ask whether the bindings and the parent can be changed (every attempt is one the server refuses)
    bindings = None
    if "--probe-bindings" in sys.argv:
        if not first_ns:
            print("\n  bindings: skipped (no namespace to ask about)")
        else:
            pname, nsname = first_ns
            sibling = next((q["metadata"]["name"] for q in projects if q["metadata"]["name"] != pname), None)
            print(f"\n  bindings: asking {L.get('namespace', nsname, braces=False)} whether its create-time bindings and its parent can be changed")
            bindings, why = probe_bindings(c, pname, nsname, sibling, L)
            if bindings is None:
                print(f"     skipped: {why}")
            else:
                for a in bindings["attempts"]:
                    print(f"     {a['method']:<5} {a['sent']:<62} HTTP {a['status']}")
                    if a["answer"]:
                        print(f"           {a['answer'][:170]}")
                print(f"     the namespace is unchanged: phase {bindings['phase']}, conditions {bindings['conditions']}")
            if bindings is not None and prov_bearer:
                def scrub_all(text):
                    # No boundary here: the Tenant Manager's answers carry names inside longer tokens, and a name
                    # left inside one is a leak. One pass all the same, so no placeholder is rewritten (G-646).
                    return L.scrub(text, edge="")
                tm_rec, why = probe_tenant_manager(host, prov_bearer, first_ns[1], scrub_all)
                if tm_rec is None:
                    print(f"     the Tenant Manager surface: skipped ({why})")
                else:
                    print("     the Tenant Manager surface, where the project assignment IS a field:")
                    for a in tm_rec["attempts"]:
                        print(f"       {a['method']:<5} {a['sent']:<58} HTTP {a['status']}")
                        if a["answer"]:
                            print(f"             {a['answer'][:150]}")
                    bindings["tenant_manager"] = tm_rec
            elif bindings is not None:
                print("     the Tenant Manager surface: not asked (set VCFA_PROVIDER_BEARER_FILE; see the README)")
    elif first_ns:
        print("\n  bindings: not asked (pass --probe-bindings to send the refused attempts; see the README)")

    # ---- 5. write, sanitized
    stamp = __import__("time").strftime("%Y-%m-%dT%H:%M:%SZ", __import__("time").gmtime())
    text = json.dumps({"captured_utc": stamp, "taxonomy": taxonomy}, indent=1, ensure_ascii=False)
    text2 = json.dumps({"captured_utc": stamp, "acquired_by": c.kind, **estate}, indent=1, ensure_ascii=False)
    text2 = UUID.sub("{{id}}", text2)
    for value in secrets:
        assert value not in text and value not in text2, "an estate value reached a record"
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
    wrote = "taxonomy.json (%d kinds) and estate.json (%d project(s))" % (len({(e["group"], e["kind"]) for e in taxonomy}), len(projects))
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
    keys = {"from", "cardinality", "to", "field", "surface", "tier", "why", "fromCount", "toCount", "toPerFrom", "fromPerTo", "holds"}
    for e in edges:
        assert set(e) <= keys and e["tier"] in ("live", "none here", "not read"), e
        assert all(isinstance(e.get(k), int) for k in ("fromCount", "toCount") if k in e), e
    text5 = json.dumps({"captured_utc": stamp, "cardinality": {k: {"fromPerTo": list(v[0]), "toPerFrom": list(v[1])} for k, v in CARDINALITY.items()},
                        "edges": edges}, indent=1, ensure_ascii=False)
    for value in secrets + ((prov_bearer,) if prov_bearer else ()):
        assert value not in text5, "an estate value reached the edge record"
    for fam, m in L.maps.items():
        for name in m:
            assert not re.search(r"(?<![A-Za-z0-9-])" + re.escape(name) + r"(?![A-Za-z0-9-])", text5), f"a {fam} name reached the edge record"
    open(os.path.join(out_dir, "edges.json"), "w", encoding="utf-8").write(text5 + "\n")
    wrote += " and edges.json (%d edges, counts only)" % len(edges)
    if bindings is not None:
        text4 = UUID.sub("{{id}}", json.dumps({"captured_utc": stamp, **bindings}, indent=1, ensure_ascii=False))
        for value in secrets:
            assert value not in text4, "an estate value reached the bindings record"
        for fam, m in L.maps.items():
            for name in m:
                assert not re.search(r"(?<![A-Za-z0-9-])" + re.escape(name) + r"(?![A-Za-z0-9-])", re.sub(r"\{\{[^}]*\}\}", "", text4)), f"a {fam} name reached the bindings record"
        open(os.path.join(out_dir, "bindings.json"), "w", encoding="utf-8").write(text4 + "\n")
        n_tm = len((bindings.get("tenant_manager") or {}).get("attempts") or [])
        wrote += " and bindings.json (%d refused attempts%s)" % (len(bindings["attempts"]), f" plus {n_tm} on the Tenant Manager" if n_tm else "")
    print(f"\nwrote {wrote}; every estate name replaced by a stable label")


if __name__ == "__main__":
    main()
