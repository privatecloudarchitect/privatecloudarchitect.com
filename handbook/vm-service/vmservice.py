#!/usr/bin/env python3
"""vmservice.py: every virtual machine on the workload plane, sorted by how it arrived.

The VM Service's lesson is that the arrival path decides what governs a machine, and the uncomfortable part is
that the machine does not record which path it took. So this does the join the platform will not do for you:

  1. the VOCABULARY: every kind the VM Service publishes at the group's preferred version, with the verbs each
     declares. It is not one primitive with a few helpers; it is a family;
  2. the PRIMITIVE: the spec and status fields of a real machine, including the two different ways it can name
     its image and the several separate fields that govern power behaviour, and how many machines hold a
     declared power state different from the observed one;
  3. the ARRIVAL JOIN: every virtual machine classified into one of three paths by reading objects rather than
     by trusting a naming convention. A controller owner means a cluster minted it. A deployment resource that
     links it, by namespace and name, means the catalog wrapped it. Neither means it was made by hand on the wire;
  4. the INVISIBILITY: whether a catalog-wrapped machine can be told from a hand-made one by looking at the
     machine's own labels and annotations;
  5. the CLASS READ, done carefully: a best-effort class publishes a resource-policy block whose values are all
     zero, so the presence of that block is not evidence of a reservation. The region's own summary carries the
     field that answers the question.

With --compare <earlier vmservice.json> it also sets the arrival counts beside an earlier record's, which is the
weekly check: a count of machines made directly on the wire that rises is the one to look at.

Everything here is read-only.

Sign-in, one of:
  VCFA_REFRESH_TOKEN_FILE   a refresh token minted for the organization, in a file of mode 0600
  VCFA_USER and VCFA_PASSWORD_FILE   a session login as user@org (the password from a file of mode 0600, or
                            VCFA_PASSWORD, the value itself, which lands in the shell's history)
A secret file open to group or other is refused before it is read.

Run:
  export VCFA_HOST=<automation-fqdn> VCFA_ORG=<org>
  export VCFA_USER=<account> VCFA_PASSWORD_FILE=~/.vcf/vcfa-password    # or VCFA_REFRESH_TOKEN_FILE
  export TLS_VERIFY=false                                               # only on a self-signed lab CA
  python3 vmservice.py                                   # writes vmservice.json
  python3 vmservice.py --compare last-week/vmservice.json

Exit: 0 written (with --compare, the direct-arrival count did not rise); 1 with --compare, it rose; 2 a call
failed or the sign-in was refused; 5 an unknown argument.
"""
import base64
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
I1 = "infrastructure.cci.vmware.com/v1alpha1"
PROJ = "project.cci.vmware.com/v1alpha2"
VMOP = "vmoperator.vmware.com"
BP = "blueprint.cci.vmware.com/v1alpha1"
# A deployment resource links a machine as cci:<segment>:<segment>:<segment>:VirtualMachine:<name>. The name alone
# is not a key: two namespaces may each hold a machine of that name, so the join takes the namespace segment too.
LINK = re.compile(r"^cci:([^:]*):([^:]*):([^:]*):VirtualMachine:(.+)$")
# Label and annotation keys under a product's own domain are vocabulary; any other key is the estate's own.
PRODUCT_KEY = re.compile(r"^([a-z0-9.-]*\.)?(vmware\.com|k8s\.io|kubernetes\.io)/")


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


def fail(msg):
    print(f"FATAL: {msg}")
    sys.exit(2)


class Labels:
    """Estate names become placeholders. The product's own vocabulary never does."""

    RESERVED = {"admin", "view", "edit", "user", "users", "group", "groups", "owner", "default", "system",
                "none", "all", "eth0", "user-data", "cloudInit", "VirtualMachine"}

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

    def key(self, k):
        """A label or annotation key as the record may carry it: a product's own key verbatim, any other a placeholder."""
        return k if PRODUCT_KEY.match(k) else self.get("key", k)

    def scrub(self, text):
        if not isinstance(text, str):
            return text
        known = [(real, label) for m in self.maps.values() for real, label in m.items()]
        for real, label in sorted(known, key=lambda kv: -len(kv[0])):
            text = re.sub(r"(?<![A-Za-z0-9-])" + re.escape(real) + r"(?![A-Za-z0-9-])",
                          "{{%s}}" % label, text)
        return UUID.sub("{{id}}", text)


class Estate:
    def __init__(self, host, org, refresh_token=None, user=None, password=None):
        """A tenant bearer, from the organization's refresh token or from a session login as user@org. A refused
        mint ends the run with the server's own answer: "invalid_grant" means the refresh token is dead, a 401 at
        the session means the login is."""
        self.host = host
        if refresh_token:
            self.kind = "refresh token"
            body = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": refresh_token}).encode()
            req = urllib.request.Request(
                f"https://{host}/oauth/tenant/{org}/token", data=body, method="POST",
                headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
        else:
            self.kind = "session login"
            basic = base64.b64encode(f"{user.split('@')[0]}@{org}:{password}".encode()).decode()
            req = urllib.request.Request(f"https://{host}/cloudapi/1.0.0/sessions", method="POST",
                                         headers={"Authorization": f"Basic {basic}", "Accept": "application/json;version=40.0"})
        try:
            with urllib.request.urlopen(req, context=ctx(), timeout=30) as r:
                self.bearer = (json.loads(r.read())["access_token"] if refresh_token
                               else r.headers.get("X-VMWARE-VCLOUD-ACCESS-TOKEN"))
        except urllib.error.HTTPError as e:
            fail(f"the {self.kind} answered HTTP {e.code}: {e.read().decode(errors='replace')[:200]}")
        except (urllib.error.URLError, OSError) as e:
            fail(f"the {self.kind} did not answer: {e}")
        if not self.bearer:
            fail(f"the {self.kind} answered without a bearer")

    def _get(self, base, path):
        req = urllib.request.Request(base.rstrip("/") + path,
                                     headers={"Authorization": f"Bearer {self.bearer}", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, context=ctx(), timeout=90) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, {}
        except (urllib.error.URLError, OSError):
            return None, {}

    def one(self, base, path):
        """One object or resource list; a refusal ends the run."""
        st, body = self._get(base, path)
        if st != 200 or not isinstance(body, dict):
            fail(f"GET {path} answered {st if st else 'nothing'}")
        return body

    def items(self, base, path):
        """Every item of a Kubernetes-style list, following its continue token; a list that fails ends the run."""
        out, token = [], None
        while True:
            body = self.one(base, path + (f"?continue={urllib.parse.quote(token)}" if token else ""))
            out += body.get("items") or []
            token = (body.get("metadata") or {}).get("continue")
            if not token:
                return out

    def classic(self, path, sort="id,asc"):
        """Every page of a classic list, sorted: at most 200 a page, and an unsorted read of several pages has no
        stable order (G-634). A deployment's resources answer HTTP 500 to sort=id,asc on 9.1.1 and accept a sort
        by name, which is unique within a deployment (G-645)."""
        out, number = [], 0
        while True:
            body = self.one(f"https://{self.host}", f"{path}{'&' if '?' in path else '?'}size=200&page={number}&sort={sort}")
            out += body.get("content") or []
            number += 1
            if body.get("last", True) or number >= (body.get("totalPages") or 0):
                return out


def refuse_unknown_args(known, takes_value=()):
    """Refuse any argument this script does not recognise, before a client opens. --help prints the usage above."""
    args = sys.argv[1:]
    if "-h" in args or "--help" in args:
        print(__doc__)
        sys.exit(0)
    unknown = [a for i, a in enumerate(args) if a not in known and not (i and args[i - 1] in takes_value)]
    if unknown or (args and args[-1] in takes_value):
        print(f"unknown or incomplete argument(s) {unknown or args[-1:]}: this script takes {', '.join(sorted(known))} "
              "(see --help)", file=sys.stderr)
        sys.exit(5)


def compare(earlier_path, arrivals):
    """The arrival counts now and in an earlier record. Returns True when the direct-arrival count rose."""
    try:
        then = (json.load(open(earlier_path, encoding="utf-8")) or {}).get("arrivals") or {}
    except (OSError, ValueError) as e:
        fail(f"--compare could not read {earlier_path}: {e}")
    print("\n  compared with the earlier record, arrivals then and now:")
    for k in ("total", "controllerOwned", "catalogWrapped", "rawOnTheWire"):
        flag = k == "rawOnTheWire" and arrivals[k] > then.get(k, 0)
        print(f"     {k:<16} {then.get(k, '?'):>4} then, {arrivals[k]:>4} now" + ("  ROSE" if flag else ""))
    return arrivals["rawOnTheWire"] > then.get("rawOnTheWire", 0)


def main():
    refuse_unknown_args({"--compare"}, takes_value=("--compare",))
    args = sys.argv[1:]
    earlier = args[args.index("--compare") + 1] if "--compare" in args else None
    host, org = os.environ["VCFA_HOST"], os.environ["VCFA_ORG"]
    try:
        refresh, password = secret("VCFA_REFRESH_TOKEN"), secret("VCFA_PASSWORD")
    except OSError as ex:   # a secret file that is missing, unreadable or open to group or other
        fail(ex)
    user = os.environ.get("VCFA_USER")
    if not refresh and not (user and password):
        fail("set VCFA_REFRESH_TOKEN_FILE, or VCFA_USER with VCFA_PASSWORD_FILE (see --help)")
    out_dir = os.environ.get("OUT_DIR", ".")
    e = Estate(host, org, refresh, None if refresh else user, None if refresh else password)
    gw = f"https://{host}{CCI}"
    L = Labels()
    print("vmservice.py: every machine on the workload plane, sorted by how it arrived\n")

    projects = [p["metadata"]["name"] for p in e.items(gw, f"/apis/{PROJ}/projects")]
    for p in projects:
        L.get("project", p)
    if not projects:
        fail("no project is visible to this identity")

    # namespaces and their own Kubernetes endpoints
    endpoints = []
    for p in projects:
        for n in e.items(gw, f"/apis/{A3}/namespaces/{p}/supervisornamespaces"):
            L.get("namespace", n["metadata"]["name"])
            url = (n.get("status") or {}).get("namespaceEndpointURL")
            if url:
                endpoints.append((p, n["metadata"]["name"], url))
    if not endpoints:
        fail("no namespace publishes an endpoint")

    # ---- 1. the vocabulary, at the version the group itself prefers
    _, _, first = endpoints[0]
    gv = e.one(first, f"/apis/{VMOP}")
    versions = sorted({v.get("version") for v in (gv.get("versions") or []) if v.get("version")})
    pref = (gv.get("preferredVersion") or {}).get("version")
    if not pref:
        fail(f"the {VMOP} group names no preferred version; this script will not guess one")
    rl = e.one(first, f"/apis/{VMOP}/{pref}")
    kinds = {r["name"]: sorted(r.get("verbs") or []) for r in (rl.get("resources") or []) if "/" not in r["name"]}
    vocab = sorted(kinds)
    creatable = [k for k in vocab if "create" in kinds[k]]
    print(f"  the VM Service publishes {len(vocab)} kind(s) at {pref} (versions served: {', '.join(versions)}); "
          f"{len(creatable)} declare create")
    print(f"     {', '.join(vocab)}")

    # ---- 2 and 3. the primitive, and the arrival join
    shape = None
    plane, services, classes_seen = {}, collections.Counter(), {}
    for _proj, ns, url in endpoints:
        for v in e.items(url, f"/apis/{VMOP}/{pref}/namespaces/{ns}/virtualmachines"):
            md, sp, stt = v["metadata"], (v.get("spec") or {}), (v.get("status") or {})
            L.get("vm", md["name"])
            L.reserve(sp.get("className"))
            owned = [o.get("kind") for o in (md.get("ownerReferences") or []) if o.get("controller")]
            keys = sorted(md.get("labels") or {}) + sorted(md.get("annotations") or {})
            plane[(ns, md["name"])] = {"namespace": ns, "name": md["name"], "class": sp.get("className"),
                                       "controllerOwner": owned[0] if owned else None,
                                       "specPowerState": sp.get("powerState"),
                                       "statusPowerState": stt.get("powerState"), "keys": keys}
            if shape is None:
                shape = {"apiVersion": pref, "specFields": sorted(sp.keys()), "statusFields": sorted(stt.keys()),
                         "namesImageTwoWays": bool("image" in sp and "imageName" in sp),
                         "powerFields": sorted(k for k in sp if "power" in k.lower() or k in
                                               ("restartMode", "suspendMode"))}
        for s_ in e.items(url, f"/apis/{VMOP}/{pref}/namespaces/{ns}/virtualmachineservices"):
            services[(s_.get("spec") or {}).get("type") or "?"] += 1
        for c in e.items(url, f"/apis/{VMOP}/{pref}/namespaces/{ns}/virtualmachineclasses"):
            name = c["metadata"]["name"]
            pol = ((c.get("spec") or {}).get("policies") or {}).get("resources") or {}
            vals = [str(x) for block in pol.values() if isinstance(block, dict) for x in block.values()]
            classes_seen.setdefault(name, {"name": name, "hasPolicyBlock": bool(pol),
                                           "allPolicyValuesZero": bool(vals) and all(x in ("0", "0Mi", "0M") for x in vals),
                                           "namespaces": 0})["namespaces"] += 1
            L.reserve(name)
    disagree = sum(1 for m in plane.values() if m["specPowerState"] and m["statusPowerState"]
                   and m["specPowerState"] != m["statusPowerState"])
    print(f"  power: {disagree} of {len(plane)} machine(s) hold a declared power state different from the observed one")

    links, wrapped_kinds, link_resources = set(), collections.Counter(), 0
    deployments = e.classic("/deployment/api/deployments")
    known_ns = {ns for _, ns, _ in endpoints}
    for d in deployments:
        for r in e.classic(f"/deployment/api/deployments/{d['id']}/resources", sort="name,asc"):
            props = r.get("properties") or {}
            m = LINK.match(str(props.get("resourceLink") or ""))
            if m:
                link_resources += 1
                ns = next((seg for seg in m.groups()[:3] if seg in known_ns), None)
                links.add((ns, m.group(4)))
            for k in set(re.findall(r'"kind"\s*:\s*"([A-Za-z]+)"', json.dumps(props))):
                wrapped_kinds[k] += 1

    nodes = {k for k, v in plane.items() if v["controllerOwner"]}
    catalog = {k for k in plane if k not in nodes and k in links}
    raw = set(plane) - nodes - catalog
    arrivals = {"total": len(plane), "controllerOwned": len(nodes), "catalogWrapped": len(catalog),
                "rawOnTheWire": len(raw), "claimedButAbsent": len(links - set(plane)),
                "linkResources": link_resources, "linksWithoutAKnownNamespace": sum(1 for ns, _ in links if ns is None)}
    print(f"\n  arrivals: {len(plane)} machine(s) = {len(nodes)} minted by a cluster controller, "
          f"{len(catalog)} linked by a deployment resource, {len(raw)} made directly on the wire")
    print(f"     {link_resources} deployment resource(s) link a machine, naming {len(links)} distinct machine(s); "
          f"{arrivals['claimedButAbsent']} of those are not on the plane")

    # ---- 4. can the machine tell you which?
    marker = re.compile(r"(?i)deploy|catalog|blueprint|instance|vra|automation")
    tell = {"catalogHaveAMarker": sum(1 for k in catalog if any(marker.search(x) for x in plane[k]["keys"])),
            "rawHaveAMarker": sum(1 for k in raw if any(marker.search(x) for x in plane[k]["keys"])),
            "keysInCommon": sorted(L.key(x) for x in set.intersection(*[set(plane[k]["keys"]) for k in (catalog | raw)]))
                            if (catalog | raw) else []}
    print(f"  of the {len(catalog)} catalog-wrapped machines, {tell['catalogHaveAMarker']} carry any label or "
          f"annotation naming a deployment; of the {len(raw)} hand-made ones, {tell['rawHaveAMarker']}")

    # ---- 5. what a blueprint may declare, and the class read done carefully
    types = sorted({r["metadata"]["name"] for p in projects for r in e.items(gw, f"/apis/{BP}/namespaces/{p}/blueprintresourcetypes")})
    published = e.items(gw, f"/apis/{I1}/regionvirtualmachineclasssummaries")
    need_res = [s for s in published if (s.get("spec") or {}).get("reservationRequired") is True]
    unstated = [s for s in published if "reservationRequired" not in (s.get("spec") or {})]
    classes = sorted(classes_seen.values(), key=lambda c: c["name"])
    print(f"\n  a blueprint may declare {len(types)} resource type(s): {', '.join(types)}")
    print(f"     a virtual machine is not one of them; the catalog reaches one through the supervisor resource, "
          f"which names the machine kind in {wrapped_kinds.get('VirtualMachine', 0)} deployment resource(s) here")
    print(f"  classes visible across {len(endpoints)} namespace(s): {len(classes)}, of which "
          f"{sum(1 for c in classes if c['hasPolicyBlock'])} publish a resource-policy block and "
          f"{sum(1 for c in classes if c['allPolicyValuesZero'])} have every value in it set to zero")
    print(f"  the region publishes {len(published)} class summaries, {len(need_res)} requiring a reservation"
          + (f" and {len(unstated)} not stating it" if unstated else "")
          + ". A policy block is not a reservation, and this is the field that answers it")
    print(f"  exposure: {dict(services)}")
    moved = compare(earlier, arrivals) if earlier else False

    machines = [{"name": L.get("vm", v["name"]), "namespace": L.get("namespace", v["namespace"]), "class": v["class"],
                 "controllerOwner": v["controllerOwner"], "specPowerState": v["specPowerState"],
                 "statusPowerState": v["statusPowerState"], "keys": [L.key(x) for x in v["keys"]],
                 "arrival": "controller" if k in nodes else "catalog" if k in catalog else "wire"}
                for k, v in sorted(plane.items())]
    payload = {"captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "signIn": e.kind,
               "vocabulary": vocab, "verbs": kinds, "apiVersions": versions, "preferred": pref, "primitive": shape,
               "powerDisagree": disagree, "arrivals": arrivals, "canTheMachineTell": tell, "machines": machines,
               "blueprintResourceTypes": types, "wrappedKinds": dict(wrapped_kinds),
               "classes": classes, "namespacesRead": len(endpoints), "publishedClasses": len(published),
               "requireReservation": len(need_res), "reservationUnstated": len(unstated),
               "exposure": dict(services), "deployments": len(deployments)}
    L.get("org", org)
    text = L.scrub(UUID.sub("{{id}}", json.dumps(payload, indent=1, ensure_ascii=False)))
    for value in (e.bearer, refresh, password, user, host):
        assert not value or value not in text, "an estate value reached the record"
    for word in vocab + types:
        assert word in text, f"the scrub replaced {word!r}, which is the product's own vocabulary"
    bare = re.sub(r"\{\{[^}]*\}\}", "", text)
    for fam, m in L.maps.items():
        for nm in m:
            if nm and re.search(r"(?<![A-Za-z0-9-])" + re.escape(nm) + r"(?![A-Za-z0-9-])", bare):
                shp = re.sub(r"[A-Za-z]", "a", re.sub(r"[0-9]", "9", nm))
                fail(f"a {fam} name ({len(nm)} characters, shape {shp}) reached the record; nothing was written")
    os.makedirs(out_dir, exist_ok=True)
    open(os.path.join(out_dir, "vmservice.json"), "w", encoding="utf-8").write(text + "\n")
    print(f"\nwrote vmservice.json ({len(vocab)} kinds, {arrivals['total']} machines sorted into "
          f"{arrivals['controllerOwned']}/{arrivals['catalogWrapped']}/{arrivals['rawOnTheWire']}); "
          f"every organization name replaced by a placeholder")
    sys.exit(1 if moved else 0)


if __name__ == "__main__":
    main()
