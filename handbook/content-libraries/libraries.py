#!/usr/bin/env python3
"""libraries.py: can each namespace see the VM images it needs, through which attachment, and do your pins resolve?

A VM names its image by an id (vmi-...), and the id resolves only if the namespace can list an image carrying it. An
image reaches a namespace by one of three attachments, and each lives on a different layer:

  * SUPERVISOR-WIDE: the library's vCenter copy sits in the Supervisor's own library list, every namespace holds a
    ClusterContentLibrary for it, and its images are ClusterVirtualMachineImages in every namespace. A provider
    library in VCF Automation attaches this way; nothing appears in any namespace's own vCenter setting.
  * PER NAMESPACE: a ContentLibrary object in the namespace (libraryType ContentLibrary) and an entry in that
    namespace's vCenter setting. An organization library with auto-attach on is written into every namespace
    this way by VCF Automation; a hand-made attach looks the same.
  * PROJECT FOLDER: a ContentLibrary object of libraryType Inventory, backed by a vSphere folder rather than a
    content library, in each namespace of the project the library is scoped to.

This reads all three from the namespace's own endpoint, attributes every image to the library that delivered it
(image -> its library item -> the item's library), and tells you, per namespace: how many general-purpose images it
can name and where they come from, the Kubernetes release images apart, and any attachment that is not ready.

  --pins PATH        also check every image pin in the YAML/JSON files under PATH (vmi-... ids and imageName values)
                     against each namespace's images: an id resolves directly, a display name only when one image
                     carries it. A library rebuild gives every image a new id, which is what this catches.
  --namespace NAME   read one namespace instead of every namespace the account can list
  --vcenter          also read the provider side from vCenter: the Supervisor's library list and each namespace's
                     own library setting (VC_HOST, VC_USER, VC_PASSWORD_FILE)

Everything here is read-only. The record (libraries.json, or OUT_DIR) carries placeholders for every organization,
project, namespace, library, image and file name, and for image ids; it refuses to write if one survived.

Sign-in, one of:
  VCFA_REFRESH_TOKEN_FILE            a refresh token minted for the organization, in a file of mode 0600
  VCFA_USER and VCFA_PASSWORD_FILE   a session login as user@org, the password in a file of mode 0600
A secret file open to group or other is refused before it is read.

Run:
  export VCFA_HOST=<automation-fqdn> VCFA_ORG=<org>
  export VCFA_USER=<account> VCFA_PASSWORD_FILE=~/.vcf/vcfa-password    # or VCFA_REFRESH_TOKEN_FILE
  export TLS_VERIFY=false                                               # only on a self-signed lab CA
  python3 libraries.py                                  # every namespace
  python3 libraries.py --pins ./blueprints              # and every pin under ./blueprints

Exit: 0 every namespace read can name a general-purpose image, no attachment is unready and every pin resolves;
      1 a finding (a namespace with no general-purpose image, an unready attachment, a pin that resolves nowhere);
      2 a setting is missing, a secret file is open, or the sign-in was refused; 3 a namespace could not be read
      (its endpoint did not answer), which is not a finding; 4 the record refused to write because an estate value
      survived; 5 an unknown argument.
"""

import base64
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
A3 = "infrastructure.cci.vmware.com/v1alpha3"
VMOP = "vmoperator.vmware.com/v1alpha5"
IREG = "imageregistry.vmware.com/v1alpha2"
K8S_RELEASE_LABEL = "services.supervisor.vmware.com/kubernetes.vmware.com"
VMI = re.compile(r"\bvmi-[0-9a-f]{12,20}\b")
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
# A display-name pin is only read from an imageName key at the start of a line (a VM manifest's own field); an id
# pin (vmi-...) is read wherever it appears, including a blueprint input's default.
IMAGE_NAME = re.compile(
    r"""^\s*(?:-\s*)?["']?imageName["']?\s*:\s*["']?([A-Za-z0-9][A-Za-z0-9._-]{2,80})"""
)
PLACEHOLDER = re.compile(r"(\{\{[^}]*\}\})")


def ctx():
    verify = os.environ.get("TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")
    return ssl.create_default_context() if verify else ssl._create_unverified_context()


def secret(name):
    """The value in the file NAME_FILE names (mode 0600), or None. A file open to group or other is refused unread."""
    path = os.environ.get(f"{name}_FILE")
    if not path:
        return None
    with open(os.path.expanduser(path), encoding="utf-8") as f:
        mode = os.fstat(f.fileno()).st_mode & 0o777
        if mode & 0o077 and os.name != "nt":
            raise PermissionError(
                f"{name}_FILE names a file of mode {mode:04o}, open to group or other: "
                f'run chmod 600 "${name}_FILE" and try again (the file was not read)'
            )
        return f.read().strip()


def stop(code, msg):
    print(f"FATAL: {msg}")
    sys.exit(code)


def one_pass(text, known):
    """Replace every (real, label) pair in one pass, longest first, on a name boundary, never inside a placeholder."""
    label_of = {}
    for real, label in known:
        label_of.setdefault(real, label)
    if not label_of:
        return text
    names = "|".join(map(re.escape, sorted(label_of, key=len, reverse=True)))
    rx = re.compile(rf"(?<![A-Za-z0-9-])({names})(?![A-Za-z0-9-])")
    return "".join(
        part if i % 2 else rx.sub(lambda m: "{{%s}}" % label_of[m.group(1)], part)
        for i, part in enumerate(PLACEHOLDER.split(text))
    )


class Labels:
    """Estate names become placeholders; the product's vocabulary never does."""

    RESERVED = {
        "default",
        "system",
        "none",
        "all",
        "cluster",
        "namespace",
        "ContentLibrary",
        "Inventory",
        "PreferItemSourceID",
        "FromItemID",
        "PROVIDER",
        "TENANT",
        "OVF",
        "ISO",
    }

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
        text = one_pass(text, [(r, lab) for m in self.maps.values() for r, lab in m.items()])
        return UUID.sub("{{id}}", VMI.sub(lambda m: self.get("image-id", m.group(0)), text))


class Tenant:
    """A tenant bearer from a refresh token or a session login; GETs only."""

    def __init__(self, host, org, refresh_token=None, user=None, password=None):
        self.host = host
        if refresh_token:
            body = urllib.parse.urlencode(
                {"grant_type": "refresh_token", "refresh_token": refresh_token}
            ).encode()
            req = urllib.request.Request(
                f"https://{host}/oauth/tenant/{org}/token",
                data=body,
                method="POST",
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
            )
        else:
            basic = base64.b64encode(f"{user.split('@')[0]}@{org}:{password}".encode()).decode()
            req = urllib.request.Request(
                f"https://{host}/cloudapi/1.0.0/sessions",
                method="POST",
                headers={
                    "Authorization": f"Basic {basic}",
                    "Accept": "application/json;version=40.0",
                },
            )
        try:
            with urllib.request.urlopen(req, context=ctx(), timeout=30) as r:
                self.bearer = (
                    json.loads(r.read())["access_token"]
                    if refresh_token
                    else r.headers.get("X-VMWARE-VCLOUD-ACCESS-TOKEN")
                )
        except urllib.error.HTTPError as e:
            stop(
                2, f"the sign-in answered HTTP {e.code}: {e.read().decode(errors='replace')[:200]}"
            )
        except (urllib.error.URLError, OSError) as e:
            stop(2, f"the sign-in did not answer: {e}")
        if not self.bearer:
            stop(2, "the sign-in answered without a bearer")

    def get(self, url, accept="application/json", tries=4):
        """(status, body). A 503 from a namespace endpoint that has just come up is retried, never read as empty."""
        for attempt in range(tries):
            req = urllib.request.Request(
                url, headers={"Authorization": f"Bearer {self.bearer}", "Accept": accept}
            )
            try:
                with urllib.request.urlopen(req, context=ctx(), timeout=90) as r:
                    return r.status, json.loads(r.read() or b"null")
            except urllib.error.HTTPError as e:
                if e.code == 503 and attempt < tries - 1:
                    time.sleep(5)
                    continue
                return e.code, None
            except (urllib.error.URLError, OSError):
                return None, None
        return None, None

    def items(self, base, path):
        """Every item of a list, following continue tokens; None when the list could not be read."""
        out, cont = [], ""
        while True:
            st, body = self.get(
                base.rstrip("/") + path + (f"?continue={urllib.parse.quote(cont)}" if cont else "")
            )
            if st != 200 or not isinstance(body, dict):
                return None
            out += body.get("items") or []
            cont = (body.get("metadata") or {}).get("continue") or ""
            if not cont:
                return out


def org_libraries(t):
    """VCF Automation's own record of the libraries this organization can use (provider and its own)."""
    st, body = t.get(
        f"https://{t.host}/cloudapi/v1/contentLibraries?pageSize=100",
        accept="application/json;version=9.1.0",
    )
    if st != 200:
        return None
    return [
        {
            "name": v.get("name"),
            "kind": v.get("libraryType"),
            "autoAttach": v.get("autoAttach"),
            "projectScoped": bool(v.get("isProjectScoped")),
            "status": v.get("status"),
            "subscribed": bool(v.get("isSubscribed")),
            "regions": len(
                {(s.get("region") or {}).get("id") for s in v.get("storageClasses") or []}
            ),
        }
        for v in (body or {}).get("values") or []
    ]


def read_namespace(t, ep, ns):
    """What one namespace can name, attributed to the library and the attachment that delivered it."""
    cimg = t.items(ep, f"/apis/{VMOP}/clustervirtualmachineimages")
    nimg = t.items(ep, f"/apis/{VMOP}/namespaces/{ns}/virtualmachineimages")
    ccl = t.items(ep, f"/apis/{IREG}/clustercontentlibraries")
    ncl = t.items(ep, f"/apis/{IREG}/namespaces/{ns}/contentlibraries")
    citem = t.items(ep, f"/apis/{IREG}/clustercontentlibraryitems")
    nitem = t.items(ep, f"/apis/{IREG}/namespaces/{ns}/contentlibraryitems")
    if any(x is None for x in (cimg, nimg, ccl, ncl, citem, nitem)):
        return None
    libs = {}
    for scope, objs in (("cluster", ccl), ("namespace", ncl)):
        for o in objs:
            spec, stt = o.get("spec") or {}, o.get("status") or {}
            via = (
                "supervisor"
                if scope == "cluster"
                else ("project-folder" if spec.get("libraryType") == "Inventory" else "namespace")
            )
            ready = any(
                c.get("type") == "Ready" and c.get("status") == "True"
                for c in stt.get("conditions") or []
            )
            libs[(scope, o["metadata"]["name"])] = {
                "name": stt.get("name"),
                "via": via,
                "type": spec.get("libraryType"),
                "naming": spec.get("resourceNamingStrategy"),
                "ready": ready,
                "images": 0,
                "kubernetes": 0,
            }
    item_lib = {
        i["metadata"]["name"]: ("cluster", (i.get("spec") or {}).get("libraryName")) for i in citem
    }
    item_lib.update(
        {
            i["metadata"]["name"]: ("namespace", (i.get("spec") or {}).get("libraryName"))
            for i in nitem
        }
    )
    images = []
    for scope, objs in (("cluster", cimg), ("namespace", nimg)):
        for i in objs:
            st = i.get("status") or {}
            k8s = K8S_RELEASE_LABEL in (i["metadata"].get("labels") or {})
            lib = libs.get(
                item_lib.get(
                    ((i.get("spec") or {}).get("providerRef") or {}).get("name"), (None, None)
                )
            )
            if lib:
                lib["kubernetes" if k8s else "images"] += 1
            if not k8s:
                images.append(
                    {
                        "id": i["metadata"]["name"],
                        "name": st.get("name"),
                        "scope": scope,
                        "os": (st.get("osInfo") or {}).get("type"),
                        "contentVersion": st.get("providerContentVersion"),
                        "ready": any(
                            c.get("type") == "Ready" and c.get("status") == "True"
                            for c in st.get("conditions") or []
                        ),
                        "library": lib["name"] if lib else None,
                        "via": lib["via"] if lib else None,
                    }
                )
    k8s_count = sum(
        1 for i in cimg + nimg if K8S_RELEASE_LABEL in (i["metadata"].get("labels") or {})
    )
    return {"images": images, "kubernetesImages": k8s_count, "attachments": list(libs.values())}


def find_pins(path):
    """(file, line, value) for every vmi id and every image-name value in the YAML/JSON files under path."""
    files = (
        [path]
        if os.path.isfile(path)
        else [
            os.path.join(d, f)
            for d, _, fs in os.walk(path)
            for f in fs
            if f.endswith((".yaml", ".yml", ".json"))
        ]
    )
    out = []
    for f in sorted(files):
        try:
            text = open(f, encoding="utf-8").read()
        except (OSError, UnicodeDecodeError):
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            vals = set(VMI.findall(line))
            m = IMAGE_NAME.match(line)
            if m and not VMI.match(m.group(1)) and not m.group(1).startswith("$"):
                vals.add(m.group(1))
            for v in sorted(vals):
                out.append((f, n, v))
    return out


def resolve(pin, images):
    """How admission would read a pin: an id directly, a display name only when exactly one image carries it."""
    if pin.startswith("vmi-"):
        hit = [i for i in images if i["id"] == pin]
        return ("id", hit[0]["scope"]) if hit else (None, None)
    hit = [i for i in images if i["name"] == pin]
    if len(hit) == 1:
        return ("name", hit[0]["scope"])
    return ("ambiguous", None) if hit else (None, None)


def vcenter_side(names):
    """The provider side, read from vCenter: the Supervisor's library list and each namespace's own setting."""
    host, user, pw = os.environ.get("VC_HOST"), os.environ.get("VC_USER"), secret("VC_PASSWORD")
    if not (host and user and pw):
        stop(2, "--vcenter needs VC_HOST, VC_USER and VC_PASSWORD_FILE")
    basic = base64.b64encode(f"{user}:{pw}".encode()).decode()
    del pw
    req = urllib.request.Request(
        f"https://{host}/api/session", method="POST", headers={"Authorization": f"Basic {basic}"}
    )
    with urllib.request.urlopen(req, context=ctx(), timeout=60) as r:
        sid = json.loads(r.read())

    def get(path):
        q = urllib.request.Request(
            f"https://{host}{path}",
            headers={"vmware-api-session-id": sid, "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(q, context=ctx(), timeout=60) as r:
                return json.loads(r.read() or b"null")
        except urllib.error.HTTPError:
            return None

    try:
        names_of = {}
        for lid in get("/api/content/library") or []:
            lib = get(f"/api/content/library/{lid}") or {}
            names_of[lid] = (lib.get("name"), lib.get("type"))
        sups = []
        for c in get("/api/vcenter/namespace-management/clusters") or []:
            cl = get(f"/api/vcenter/namespace-management/clusters/{c.get('cluster')}") or {}
            sups.append(
                [
                    {
                        "library": names_of.get(e.get("content_library"), (None, None))[0],
                        "type": names_of.get(e.get("content_library"), (None, None))[1],
                        "services": e.get("supervisor_services") or [],
                        "naming": e.get("resource_naming_strategy"),
                        "exists": e.get("content_library") in names_of,
                    }
                    for e in cl.get("content_libraries") or []
                ]
            )
        per_ns = {}
        for n in names:
            inst = get(f"/api/vcenter/namespaces/instances/{n}") or {}
            ids = (inst.get("vm_service_spec") or {}).get("content_libraries") or []
            per_ns[n] = {
                "entries": len(ids),
                "namingNothing": sum(1 for i in ids if i not in names_of),
            }
        return {"supervisors": sups, "perNamespace": per_ns}
    finally:
        urllib.request.urlopen(
            urllib.request.Request(
                f"https://{host}/api/session",
                method="DELETE",
                headers={"vmware-api-session-id": sid},
            ),
            context=ctx(),
            timeout=30,
        )


def report(rec):
    """The printed report, from the record alone (so the page can read it from the tool)."""
    lines = [f"libraries.py, read {rec['capturedUtc']}"]
    if rec.get("orgLibraries") is not None:
        lines.append(
            f"VCF Automation: {len(rec['orgLibraries'])} librar{'y' if len(rec['orgLibraries']) == 1 else 'ies'} this organization can use"
        )
        for lb in rec["orgLibraries"]:
            kind = (
                "provider"
                if lb["kind"] == "PROVIDER"
                else ("project" if lb["projectScoped"] else "organization")
            )
            lines.append(
                f"  {lb['name']:<22} {kind:<12} auto-attach {str(lb['autoAttach']).lower():<5} "
                f"{lb['status']:<10} {'subscribed' if lb['subscribed'] else 'local'}"
            )
    for n in rec["namespaces"]:
        if n.get("unread"):
            lines.append(f"{n['name']}: NOT READ ({n['unread']})")
            continue
        gen = n["images"]
        by_via = {}
        for i in gen:
            by_via[i["via"] or "unattributed"] = by_via.get(i["via"] or "unattributed", 0) + 1
        lines.append(
            f"{n['name']}: {len(gen)} general-purpose image(s) "
            f"({', '.join(f'{v} via {k}' for k, v in sorted(by_via.items())) or 'none'}), "
            f"{n['kubernetesImages']} Kubernetes release image(s)"
        )
        for a in n["attachments"]:
            what = f"{a['images']} image(s)" + (
                f", {a['kubernetes']} Kubernetes release image(s)" if a["kubernetes"] else ""
            )
            lines.append(
                f"  attached {a['via']:<14} {str(a['name']):<22} {what}{'' if a['ready'] else '  NOT READY'}"
            )
    pins = {}
    for n in rec["namespaces"]:
        for p in n.get("pins", []):
            pins.setdefault((p["pin"], p["file"], p["line"]), []).append(
                (p["resolves"], p["scope"])
            )
    read = sum(1 for n in rec["namespaces"] if not n.get("unread"))
    for (pin, f, line), res in sorted(pins.items()):
        ok = [r for r in res if r[0] in ("id", "name")]
        how = (
            f"resolves by {'id' if ok[0][0] == 'id' else 'display name'} at {ok[0][1]} scope"
            if ok
            else "AMBIGUOUS: several images carry this name"
            if any(r[0] == "ambiguous" for r in res)
            else "RESOLVES NOWHERE"
        )
        lines.append(f"pin {pin:<26} {f}:{line}  {how}, in {len(ok)} of {read} namespace(s)")
    if rec.get("vcenter"):
        v = rec["vcenter"]
        for s in v["supervisors"]:
            lines.append(
                "vCenter, the Supervisor's library list: "
                + "; ".join(
                    f"{e['library']} ({'Kubernetes releases' if e['services'] else 'VM images'}"
                    f"{', ' + e['naming'] if e['naming'] else ''})"
                    for e in s
                )
            )
        lines.append(
            "vCenter, each namespace's own setting: "
            + ", ".join(
                f"{k} {d['entries']}"
                + (f" ({d['namingNothing']} naming no library)" if d["namingNothing"] else "")
                for k, d in v["perNamespace"].items()
            )
        )
    lines.append("findings: " + ("; ".join(rec["findings"]) if rec["findings"] else "none"))
    return "\n".join(lines)


def run(argv):
    known = {"--pins": True, "--namespace": True, "--vcenter": False, "--help": False, "-h": False}
    opt, a = {}, list(argv)
    while a:
        k = a.pop(0)
        if k not in known:
            print(f"unknown argument {k!r}: use --pins PATH, --namespace NAME, --vcenter")
            return 5
        if k in ("--help", "-h"):
            print(__doc__)
            return 0
        opt[k] = a.pop(0) if known[k] and a else True
    host, org = os.environ.get("VCFA_HOST"), os.environ.get("VCFA_ORG")
    if not (host and org):
        stop(2, "set VCFA_HOST and VCFA_ORG")
    try:
        token, password = secret("VCFA_REFRESH_TOKEN"), secret("VCFA_PASSWORD")
    except PermissionError as e:
        stop(2, str(e))
    if not token and not (os.environ.get("VCFA_USER") and password):
        stop(2, "set VCFA_REFRESH_TOKEN_FILE, or VCFA_USER with VCFA_PASSWORD_FILE")
    t = Tenant(host, org, refresh_token=token, user=os.environ.get("VCFA_USER"), password=password)
    del token, password
    rec = {
        "capturedUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "orgLibraries": org_libraries(t),
        "namespaces": [],
        "findings": [],
    }
    nss = t.items(f"https://{host}{CCI}", f"/apis/{A3}/supervisornamespaces")
    if nss is None:
        stop(3, "the organization's namespace list could not be read")
    if opt.get("--namespace"):
        nss = [n for n in nss if n["metadata"]["name"] == opt["--namespace"]]
    pins = find_pins(opt["--pins"]) if opt.get("--pins") else []
    unread = 0
    for n in sorted(nss, key=lambda n: n["metadata"]["name"]):
        name, ep = (
            n["metadata"]["name"],
            ((n.get("status") or {}).get("namespaceEndpointURL") or "").rstrip("/"),
        )
        row = {"name": name, "project": n["metadata"].get("namespace")}
        got = read_namespace(t, ep, name) if ep else None
        if got is None:
            row["unread"] = "its endpoint did not answer the image lists"
            unread += 1
            rec["namespaces"].append(row)
            continue
        row.update(got)
        if not got["images"]:
            rec["findings"].append(f"{name} can name no general-purpose image")
        for a2 in got["attachments"]:
            if not a2["ready"]:
                rec["findings"].append(
                    f"{name}: the {a2['via']} attachment of {a2['name']} is not ready"
                )
        row["pins"] = []
        for f, line, pin in pins:
            how, scope = resolve(pin, got["images"])
            rel = (
                os.path.relpath(f, opt["--pins"])
                if os.path.isdir(opt["--pins"])
                else os.path.basename(f)
            )
            row["pins"].append(
                {"file": rel, "line": line, "pin": pin, "resolves": how, "scope": scope}
            )
            if how in (None, "ambiguous"):
                rec["findings"].append(
                    f"{name}: pin {pin} ({rel}:{line}) "
                    f"{'is ambiguous' if how else 'resolves nowhere'}"
                )
        rec["namespaces"].append(row)
    if opt.get("--vcenter"):
        try:
            rec["vcenter"] = vcenter_side([n["name"] for n in rec["namespaces"]])
        except PermissionError as e:
            stop(2, str(e))
        for s in rec["vcenter"]["supervisors"]:
            for e in s:
                if not e["exists"]:
                    rec["findings"].append(
                        "the Supervisor's library list names a library vCenter does not hold"
                    )
    print(report(scrub_record(rec)))
    out = os.path.join(
        os.environ.get("OUT_DIR") or os.path.dirname(os.path.abspath(__file__)), "libraries.json"
    )
    clean = scrub_record(rec)
    if leaked(clean, rec):
        print("FATAL: the record still carries an estate value; nothing was written")
        return 4
    with open(out, "w", encoding="utf-8") as f:
        json.dump(clean, f, indent=1)
        f.write("\n")
    print(f"record: {out}")
    if unread:
        return 3
    return 1 if rec["findings"] else 0


_LABELS = Labels()


def scrub_record(rec):
    """Every estate name the record carries becomes a placeholder, the same one each time it appears."""
    L = _LABELS
    for lb in rec.get("orgLibraries") or []:
        L.get("library", lb["name"])
    for n in rec["namespaces"]:
        L.get("project", n.get("project"))
        L.get("namespace", n["name"])
        for a in n.get("attachments") or []:
            L.get("library", a["name"])
        for i in n.get("images") or []:
            L.get("image", i["name"])
            L.get("image-id", i["id"])
        for p in n.get("pins") or []:
            L.get("file", p["file"])
            (
                L.get("image-id", p["pin"])
                if p["pin"].startswith("vmi-")
                else L.get("image", p["pin"])
            )
    for s in (rec.get("vcenter") or {}).get("supervisors") or []:
        for e in s:
            L.get("library", e["library"])
    for k in (
        os.environ.get("VCFA_ORG", ""),
        os.environ.get("VCFA_HOST", ""),
        os.environ.get("VC_HOST", ""),
    ):
        L.get("estate", k)
    return json.loads(L.scrub(json.dumps(rec)))


def leaked(clean, raw):
    """True when any estate value the run saw survives in the scrubbed record."""
    text = json.dumps(clean)
    values = {v for m in _LABELS.maps.values() for v in m}
    return any(
        re.search(rf"(?<![A-Za-z0-9-]){re.escape(v)}(?![A-Za-z0-9-])", text) for v in values if v
    )


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
