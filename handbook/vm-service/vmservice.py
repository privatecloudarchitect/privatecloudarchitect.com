#!/usr/bin/env python3
"""vmservice.py: every virtual machine on the workload plane, sorted by how it arrived.

The VM Service's lesson is that the arrival path decides what governs a machine, and the uncomfortable part is
that the machine does not record which path it took. So this does the join the platform will not do for you:

  1. the VOCABULARY: every kind the VM Service publishes. It is not one primitive with a few helpers; it is a
     family, and knowing its size changes what you think a namespace holder can do;
  2. the PRIMITIVE: the spec and status fields of a real machine, including the two different ways it can name
     its image and the several separate fields that govern power behaviour;
  3. the ARRIVAL JOIN: every virtual machine classified into one of three paths by reading objects rather than
     by trusting a naming convention. A controller owner means a cluster minted it. A deployment that claims it
     by resource link means the catalog wrapped it. Neither means it was made by hand on the wire;
  4. the INVISIBILITY: whether a catalog-wrapped machine can be told from a hand-made one by looking at the
     machine. It cannot, and that is the finding worth carrying;
  5. the CLASS READ, done carefully: a best-effort class publishes a resource-policy block whose values are all
     zero, so the presence of that block is not evidence of a reservation. The region's own summary carries the
     field that answers the question.

Everything here is read-only.

Run:
  export VCFA_HOST=<automation-fqdn> VCFA_ORG=<org>
  export VCFA_REFRESH_TOKEN_FILE=/path/to/refresh-token    # mode 0600
  export TLS_VERIFY=false                                  # only on a self-signed lab CA
  python3 vmservice.py
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
A3 = "infrastructure.cci.vmware.com/v1alpha3"
I1 = "infrastructure.cci.vmware.com/v1alpha1"
PROJ = "project.cci.vmware.com/v1alpha2"
VMOP = "vmoperator.vmware.com"
BP = "blueprint.cci.vmware.com/v1alpha1"
LINK = re.compile(r"^cci:[^:]+:[^:]+:[^:]+:VirtualMachine:(.+)$")


def ctx():
    verify = os.environ.get("TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")
    return ssl.create_default_context() if verify else ssl._create_unverified_context()


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

    def scrub(self, text):
        if not isinstance(text, str):
            return text
        known = [(real, label) for m in self.maps.values() for real, label in m.items()]
        for real, label in sorted(known, key=lambda kv: -len(kv[0])):
            text = re.sub(r"(?<![A-Za-z0-9-])" + re.escape(real) + r"(?![A-Za-z0-9-])",
                          "{{%s}}" % label, text)
        return UUID.sub("{{id}}", text)


class Estate:
    def __init__(self, host, org, refresh_token):
        self.host = host
        body = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": refresh_token}).encode()
        req = urllib.request.Request(
            f"https://{host}/oauth/tenant/{org}/token", data=body, method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
        with urllib.request.urlopen(req, context=ctx(), timeout=30) as r:
            self.bearer = json.loads(r.read())["access_token"]

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

    def gw(self, path):
        return self._get(f"https://{self.host}{CCI}", path)

    def api(self, path):
        return self._get(f"https://{self.host}", path)

    def ns(self, endpoint, path):
        return self._get(endpoint, path)


def main():
    host, org = os.environ["VCFA_HOST"], os.environ["VCFA_ORG"]
    refresh = open(os.environ["VCFA_REFRESH_TOKEN_FILE"], encoding="utf-8").read().strip()
    out_dir = os.environ.get("OUT_DIR", ".")
    e = Estate(host, org, refresh)
    L = Labels()
    print("vmservice.py: every machine on the workload plane, sorted by how it arrived\n")

    st, pl = e.gw(f"/apis/{PROJ}/projects")
    projects = [p["metadata"]["name"] for p in ((pl.get("items") or []) if st == 200 else [])]
    for p in projects:
        L.get("project", p)
    if not projects:
        raise SystemExit("no project is visible to this identity")

    # namespaces and their own Kubernetes endpoints
    endpoints = []
    for p in projects:
        st, nss = e.gw(f"/apis/{A3}/namespaces/{p}/supervisornamespaces")
        for n in ((nss.get("items") or []) if st == 200 else []):
            url = (n.get("status") or {}).get("namespaceEndpointURL")
            if url:
                L.get("namespace", n["metadata"]["name"])
                endpoints.append((p, n["metadata"]["name"], url))
    if not endpoints:
        raise SystemExit("no namespace publishes an endpoint")

    # ---- 1. the vocabulary
    _, _, first = endpoints[0]
    st, gv = e.ns(first, f"/apis/{VMOP}")
    versions = sorted({v.get("version") for v in (gv.get("versions") or []) if v.get("version")})
    pref = (gv.get("preferredVersion") or {}).get("version") or (versions[-1] if versions else "v1alpha4")
    st, rl = e.ns(first, f"/apis/{VMOP}/{pref}")
    vocab = sorted(r["name"] for r in (rl.get("resources") or []) if "/" not in r["name"])
    print(f"  the VM Service publishes {len(vocab)} kind(s) at {pref} (versions served: {', '.join(versions)})")
    print(f"     {', '.join(vocab)}")

    # ---- 2. the primitive
    shape = None
    # ---- 3. the arrival join
    plane, services = {}, collections.Counter()
    for proj, ns, url in endpoints:
        st, vms = e.ns(url, f"/apis/{VMOP}/{pref}/namespaces/{ns}/virtualmachines")
        for v in ((vms.get("items") or []) if st == 200 else []):
            md, sp, stt = v["metadata"], (v.get("spec") or {}), (v.get("status") or {})
            L.get("vm", md["name"])
            L.reserve(sp.get("className"))
            owned = [o.get("kind") for o in (md.get("ownerReferences") or []) if o.get("controller")]
            plane[md["name"]] = {"namespace": L.scrub(ns), "class": sp.get("className"),
                                 "controllerOwner": owned[0] if owned else None,
                                 "specPowerState": sp.get("powerState"),
                                 "statusPowerState": stt.get("powerState"),
                                 "labelKeys": sorted(md.get("labels") or {}),
                                 "annotationKeys": sorted(md.get("annotations") or {})}
            if shape is None:
                shape = {"apiVersion": pref, "specFields": sorted(sp.keys()), "statusFields": sorted(stt.keys()),
                         "namesImageTwoWays": bool("image" in sp and "imageName" in sp),
                         "powerFields": sorted(k for k in sp if "power" in k.lower() or k in
                                               ("restartMode", "suspendMode")),
                         "powerDeclaredEqualsObserved": sp.get("powerState") == stt.get("powerState")}
        st, sv = e.ns(url, f"/apis/{VMOP}/{pref}/namespaces/{ns}/virtualmachineservices")
        for s_ in ((sv.get("items") or []) if st == 200 else []):
            services[(s_.get("spec") or {}).get("type") or "?"] += 1

    claimed, wrapped_kinds = set(), collections.Counter()
    st, dep = e.api("/deployment/api/deployments?size=200")
    deployments = (dep.get("content") or []) if isinstance(dep, dict) else []
    for d in deployments:
        st, rs = e.api(f"/deployment/api/deployments/{d['id']}/resources?size=200")
        for r in ((rs.get("content") or []) if isinstance(rs, dict) else []):
            props = r.get("properties") or {}
            m = LINK.match(str(props.get("resourceLink") or ""))
            if m:
                claimed.add(m.group(1))
            for k in set(re.findall(r'"kind"\s*:\s*"([A-Za-z]+)"', json.dumps(props))):
                wrapped_kinds[k] += 1

    nodes = {k for k, v in plane.items() if v["controllerOwner"]}
    catalog = {k for k in plane if k not in nodes and k in claimed}
    raw = set(plane) - nodes - catalog
    arrivals = {"total": len(plane), "controllerOwned": len(nodes), "catalogWrapped": len(catalog),
                "rawOnTheWire": len(raw),
                "claimedButAbsent": len(claimed - set(plane))}
    print(f"\n  arrivals: {len(plane)} machine(s) = {len(nodes)} minted by a cluster controller, "
          f"{len(catalog)} claimed by a deployment, {len(raw)} made directly on the wire")

    # ---- 4. can the machine tell you which?
    marker = re.compile(r"(?i)deploy|catalog|blueprint|instance|vra|automation")
    tell = {"catalogHaveAMarker": sum(1 for k in catalog
                                      if any(marker.search(x) for x in plane[k]["labelKeys"] + plane[k]["annotationKeys"])),
            "rawHaveAMarker": sum(1 for k in raw
                                  if any(marker.search(x) for x in plane[k]["labelKeys"] + plane[k]["annotationKeys"])),
            "keysInCommon": sorted(set.intersection(*[set(plane[k]["labelKeys"] + plane[k]["annotationKeys"])
                                                      for k in (catalog | raw)]) if (catalog | raw) else [])}
    print(f"  of the {len(catalog)} catalog-wrapped machines, {tell['catalogHaveAMarker']} carry any label or "
          f"annotation naming a deployment; of the {len(raw)} hand-made ones, {tell['rawHaveAMarker']}")

    # ---- 5. what a blueprint may declare, and the class read done carefully
    st, rts = e.gw(f"/apis/{BP}/namespaces/{projects[0]}/blueprintresourcetypes")
    types = sorted(r["metadata"]["name"] for r in ((rts.get("items") or []) if st == 200 else []))
    st, cls = e.ns(first, f"/apis/{VMOP}/{pref}/namespaces/{endpoints[0][1]}/virtualmachineclasses")
    classes = []
    for c in ((cls.get("items") or []) if st == 200 else []):
        pol = ((c.get("spec") or {}).get("policies") or {}).get("resources") or {}
        vals = [str(v) for block in pol.values() if isinstance(block, dict) for v in block.values()]
        classes.append({"name": c["metadata"]["name"], "hasPolicyBlock": bool(pol),
                        "allPolicyValuesZero": bool(vals) and all(v in ("0", "0Mi", "0M") for v in vals)})
        L.reserve(c["metadata"]["name"])
    st, sums = e.gw(f"/apis/{I1}/regionvirtualmachineclasssummaries")
    published = (sums.get("items") or []) if isinstance(sums, dict) else []
    need_res = [s for s in published if ((s.get("spec") or {}).get("reservationRequired"))]
    print(f"\n  a blueprint may declare {len(types)} resource type(s): {', '.join(types)}")
    print(f"     a virtual machine is not one of them; the catalog reaches one through the supervisor resource, "
          f"which wrapped {wrapped_kinds.get('VirtualMachine', 0)} of them here")
    print(f"  classes visible in the namespace: {len(classes)}, of which "
          f"{sum(1 for c in classes if c['hasPolicyBlock'])} publish a resource-policy block and "
          f"{sum(1 for c in classes if c['allPolicyValuesZero'])} have every value in it set to zero")
    print(f"  the region publishes {len(published)} class summaries, {len(need_res)} requiring a reservation. "
          f"A policy block is not a reservation, and this is the field that answers it")
    print(f"  exposure: {dict(services)}")

    payload = {"captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "vocabulary": vocab, "apiVersions": versions, "preferred": pref, "primitive": shape,
               "arrivals": arrivals, "canTheMachineTell": tell,
               "machines": [dict(v, name=L.scrub(k)) for k, v in plane.items()],
               "blueprintResourceTypes": types, "wrappedKinds": dict(wrapped_kinds),
               "classes": classes, "publishedClasses": len(published), "requireReservation": len(need_res),
               "exposure": dict(services), "deployments": len(deployments)}
    text = L.scrub(UUID.sub("{{id}}", json.dumps(payload, indent=1, ensure_ascii=False)))
    for secret in (e.bearer, refresh, host, org):
        assert secret not in text, "an estate value reached the record"
    for word in vocab + types:
        assert word in text, f"the scrub replaced {word!r}, which is the product's own vocabulary"
    bare = re.sub(r"\{\{[^}]*\}\}", "", text)
    for fam, m in L.maps.items():
        for nm in m:
            if nm and re.search(r"(?<![A-Za-z0-9-])" + re.escape(nm) + r"(?![A-Za-z0-9-])", bare):
                shp = re.sub(r"[A-Za-z]", "a", re.sub(r"[0-9]", "9", nm))
                raise SystemExit(f"FATAL: a {fam} name ({len(nm)} characters, shape {shp}) reached the record")
    os.makedirs(out_dir, exist_ok=True)
    open(os.path.join(out_dir, "vmservice.json"), "w", encoding="utf-8").write(text + "\n")
    print(f"\nwrote vmservice.json ({len(vocab)} kinds, {arrivals['total']} machines sorted into "
          f"{arrivals['controllerOwned']}/{arrivals['catalogWrapped']}/{arrivals['rawOnTheWire']}); "
          f"every organization name replaced by a placeholder")


if __name__ == "__main__":
    main()
