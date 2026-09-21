#!/usr/bin/env python3
"""pathways.py: the same Day-2 change, made through each plane, and what each one leaves true.

Creating a machine is the small part. A machine is changed many times and deleted once, so the pathway you
take for Day-2 matters more than the one you took on day one. There are three planes that will accept a
change, and they do not behave alike:

  VCFA         a Day-2 action on the deployment. It writes the Supervisor's own spec field and then WAITS
               for the Supervisor to converge before reporting success.
  SUPERVISOR   a PATCH of the same field on the same object. Identical destination, no record involved.
  vCENTER      below the declarative layer. The call is accepted and the Supervisor reconciles it away.

So the interesting question is not which works. All three "work". It is what is still true afterwards, and
specifically whether the record that claims your machine is still describing it correctly.

What this script reports:

  1. the DRIFT AUDIT, read-only and the reason to run this at all: for every machine claimed by a deployment,
     the record's own declared manifest against the object the record last observed against the live object
     on the Supervisor. A record can be wrong in two different ways and only one of them is visible in the
     field operators watch;
  2. the TOMBSTONES: deployments that report DELETE_SUCCESSFUL and still hold a resource. These cannot be
     retired, and how they are made is a documented sequence rather than a mystery (see --probe-pathways);
  3. with --probe-pathways, the SAME CHANGE through VCFA and through the Supervisor on one machine this run
     builds, each timed, with the record read after each one.

Without --probe-pathways nothing here writes.

A DELIBERATE OMISSION, which is the most important line in this file. The probe always deletes its
deployment while the machine still exists. Removing the machine first and then deleting the deployment
produces a record that reports DELETE_SUCCESSFUL, keeps listing the missing resource, keeps offering actions
that fail, and CANNOT BE REMOVED through this API. That sequence is described on the chapter's plate 05 and
is deliberately not performed here, because a teaching script must not litter the estate it teaches on.

Estate names are replaced by stable placeholders and the script refuses to write a record in which one
survived. Field names, statuses, action ids and the platform's own error strings are the product's
vocabulary and are kept, because they are the lesson.

Run:
  export VCFA_HOST=<automation-fqdn> VCFA_ORG=<org>
  export VCFA_REFRESH_TOKEN_FILE=/path/to/refresh-token    # mode 0600
  export PATHWAYS_PROJECT=<project>                        # optional; first visible project otherwise
  export PATHWAYS_NAMESPACE=<namespace>                    # required for --probe-pathways
  export TLS_VERIFY=false                                  # only on a self-signed lab CA
  python3 pathways.py [--probe-pathways]
"""
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
PREFIX = "handbook-pathways"
# The spec fields worth comparing. A manifest may legitimately omit a field the platform then defaults, so
# comparing every key would report defaulting as drift. These are the ones an operator sets on purpose.
WATCHED = ("powerState", "className", "imageName", "storageClass", "bootDiskCapacity")


def ctx():
    verify = os.environ.get("TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")
    return ssl.create_default_context() if verify else ssl._create_unverified_context()


class Labels:
    """Estate names become placeholders. The product's own vocabulary never does."""

    RESERVED = {"admin", "default", "system", "none", "all", "VirtualMachine", "Namespace", "VM",
                "PoweredOn", "PoweredOff", "SUCCESS", "MISSING", "OK"}

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
    def __init__(self, host, org, refresh_token):
        self.host = host
        body = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": refresh_token}).encode()
        req = urllib.request.Request(
            f"https://{host}/oauth/tenant/{org}/token", data=body, method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
        with urllib.request.urlopen(req, context=ctx(), timeout=30) as r:
            self.bearer = json.loads(r.read())["access_token"]

    def call(self, url, method="GET", payload=None, ctype="application/json"):
        data = json.dumps(payload).encode() if payload is not None else None
        h = {"Authorization": f"Bearer {self.bearer}", "Accept": "application/json"}
        if data:
            h["Content-Type"] = ctype
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(url, data=data, method=method, headers=h),
                    context=ctx(), timeout=180) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, {}
        except (urllib.error.URLError, OSError):
            return None, {}

    def gw(self, p, m="GET", pl=None):
        return self.call(f"https://{self.host}{CCI}{p}", m, pl)

    def api(self, p, m="GET", pl=None):
        return self.call(f"https://{self.host}{p}", m, pl)

    def ns(self, endpoint, p, m="GET", pl=None, ctype="application/json"):
        return self.call(endpoint.rstrip("/") + p, m, pl, ctype)


# --------------------------------------------------------------------------- the drift audit

def watched(spec):
    """The fields an operator sets on purpose, so defaulting is not reported as drift."""
    out = {}
    for k in WATCHED:
        v = (spec or {}).get(k)
        if v is not None:
            out[k] = v
    # the platform restates the image as a structured reference; treat the two spellings as one field
    img = (spec or {}).get("image")
    if isinstance(img, dict) and img.get("name") and "imageName" not in out:
        out["imageName"] = img["name"]
    return out


def audit(e, L, endpoints):
    """Three views of every claimed machine, compared: declared, last observed, and live.

    A record can be wrong in two different ways. It can have lost its object entirely, which shows up in
    syncStatus, the field an operator would think to watch. Or it can still be holding a manifest that no
    longer describes the machine, which does NOT show up there: syncStatus reports on whether the record
    applied its manifest, not on whether the machine still matches it. The second kind is the one that
    matters, because the record goes on being cited as the description of a machine it no longer describes.
    """
    rows, tombstones = [], []
    st, dep = e.api("/deployment/api/deployments?size=200")
    for d in ((dep or {}).get("content") or []):
        st, rs = e.api(f"/deployment/api/deployments/{d['id']}/resources?size=200")
        res = (rs or {}).get("content") or []
        if str(d.get("status")) == "DELETE_SUCCESSFUL" and res:
            tombstones.append({"name": L.get("deployment", d.get("name")), "status": d.get("status"),
                               "resourcesStillListed": len(res),
                               "syncStatuses": sorted({r.get("syncStatus") for r in res if r.get("syncStatus")})})
        for r in res:
            p = r.get("properties") or {}
            man, obj = p.get("manifest") or {}, p.get("object") or {}
            if str(man.get("kind")) != "VirtualMachine":
                continue
            # Resolve the machine through the claim, never by name. Names are reused: a namespace can hold a
            # live machine with exactly the name a retired deployment still lists, and matching on the string
            # makes a dead record look healthy by comparing it against somebody else's machine.
            link = str(p.get("resourceLink") or "")
            m = re.match(r"^cci:([^:]+):([^:]+):[^:]+:VirtualMachine:(.+)$", link)
            claim_ns, name = (m.group(2), m.group(3)) if m else (None, (man.get("metadata") or {}).get("name"))
            L.get("machine", name)
            declared, observed = watched(man.get("spec")), watched(obj.get("spec"))
            live, reachable = None, False
            for _proj, ns, url in endpoints:
                if claim_ns and ns != claim_ns:
                    continue
                reachable = True
                stl, v = e.ns(url, f"/apis/{VMOP}/v1alpha5/namespaces/{ns}/virtualmachines/{name}")
                if stl == 200:
                    live = watched((v or {}).get("spec"))
                break
            # syncStatus MISSING is the record's own statement that its object is gone. Never overrule it with
            # a live read, because a live read can only have found a different machine wearing the same name.
            if r.get("syncStatus") == "MISSING":
                live = None
            drift_obs = sorted(k for k in declared if k in observed and declared[k] != observed[k])
            drift_live = sorted(k for k in declared if live and k in live and declared[k] != live[k])
            rows.append({
                "deployment": L.get("deployment", d.get("name")),
                "machine": L.get("machine", name),
                "deploymentStatus": d.get("status"),
                "syncStatus": r.get("syncStatus"),
                "state": r.get("state"),
                "declaredFields": len(declared),
                "claimNamespaceReachable": reachable,
                "foundLive": live is not None,
                "declaredVsObserved": drift_obs,
                "declaredVsLive": drift_live,
                "agrees": bool(live) and not drift_obs and not drift_live,
                "objectGone": r.get("syncStatus") == "MISSING",
            })
    return rows, tombstones


# --------------------------------------------------------------------------- the pathway probe

def read_spec(e, url, ns, name):
    st, v = e.ns(url, f"/apis/{VMOP}/v1alpha5/namespaces/{ns}/virtualmachines/{name}")
    if st != 200:
        return None
    return {"spec": (v.get("spec") or {}).get("powerState"),
            "status": (v.get("status") or {}).get("powerState")}


def record_view(e, dep, name):
    """What the record says about the machine right now: its sync flag and its declared power state."""
    st, rs = e.api(f"/deployment/api/deployments/{dep}/resources?size=50")
    r = next((x for x in ((rs or {}).get("content") or []) if x.get("type") == "CCI.Supervisor.Resource"), {})
    p = r.get("properties") or {}
    man, obj = p.get("manifest") or {}, p.get("object") or {}
    return {"syncStatus": r.get("syncStatus"), "state": r.get("state"),
            "declared": ((man.get("spec") or {}).get("powerState")),
            "observed": ((obj.get("spec") or {}).get("powerState"))}


def probe(e, L, project, ns, url, image, storage, vmclass):
    """One machine, the same change twice, once through each pathway that should be used.

    vCenter is not exercised here. It is a plane below the declarative one: the call is accepted and the
    Supervisor reconciles it away, which is a fact about where authority lives rather than a Day-2 option,
    and proving it needs a vCenter credential this script deliberately does not ask for.
    """
    name = f"{PREFIX}-d2"
    bpname = f"{PREFIX}-probe"
    out = {"vcfa": {}, "supervisor": {}, "teardown": {}}
    vms = f"/apis/{VMOP}/v1alpha5/namespaces/{ns}/virtualmachines"

    content = ("name: %s\nversion: 1.0.0\nformatVersion: 2\n"
               "inputs:\n  vm_name: {type: string, title: VM}\n"
               "resources:\n"
               "  Namespace:\n    type: CCI.Supervisor.Namespace\n"
               "    properties: {existing: true, name: %s}\n"
               "  VM:\n    type: CCI.Supervisor.Resource\n"
               "    properties:\n      context: ${resource.Namespace.id}\n"
               "      manifest:\n        apiVersion: %s/v1alpha5\n        kind: VirtualMachine\n"
               "        metadata:\n          name: ${input.vm_name}\n"
               "        spec:\n          className: %s\n          imageName: %s\n"
               "          storageClass: %s\n          bootDiskCapacity: 20Gi\n"
               "          powerState: PoweredOn\n") % (bpname, ns, VMOP, vmclass, image, storage)

    e.gw(f"/apis/{BP}/namespaces/{project}/blueprints", "POST",
         {"apiVersion": BP, "kind": "Blueprint", "metadata": {"name": bpname, "namespace": project},
          "spec": {"content": content, "description": "pathways probe, deleted by this run"}})
    e.gw(f"/apis/{BP}/namespaces/{project}/blueprintversions", "POST",
         {"apiVersion": BP, "kind": "BlueprintVersion", "metadata": {"name": f"{bpname}:1.0.0", "namespace": project},
          "spec": {"blueprintName": bpname, "version": "1.0.0", "publishToCatalog": True}})
    time.sleep(12)
    st, items = e.api("/catalog/api/items?size=200")
    item = next((i for i in ((items or {}).get("content") or []) if i.get("name") == bpname), None)
    st, projects = e.api("/project-service/api/projects?size=100")
    pid = next((p["id"] for p in ((projects or {}).get("content") or []) if p.get("name") == project), None)
    if not (item and pid):
        raise SystemExit("could not publish the probe blueprint to the catalog")
    st, r = e.api(f"/catalog/api/items/{item['id']}/request", "POST",
                  {"deploymentName": name, "projectId": pid, "version": "1.0.0",
                   "inputs": {"vm_name": name}})
    dep = r[0]["deploymentId"] if isinstance(r, list) and r else None
    for _ in range(40):
        time.sleep(10)
        st, d = e.api(f"/deployment/api/deployments/{dep}")
        if (d or {}).get("status") not in ("CREATE_INPROGRESS", None):
            break
    print(f"  built through the catalog: {(d or {}).get('status')}")

    # ---- pathway 1: the deployment's own Day-2 action
    st, acts = e.api(f"/deployment/api/deployments/{dep}/actions")
    po = next((a for a in (acts or []) if a.get("name") == "PowerOff"), None)
    t0 = time.time()
    st, rq = e.api(f"/deployment/api/deployments/{dep}/requests", "POST",
                   {"actionId": po.get("id"), "inputs": {}})
    rid = (rq or {}).get("id")
    spec_at = status_at = None
    for _ in range(30):
        time.sleep(10)
        s = read_spec(e, url, ns, name)
        if spec_at is None and s and s["spec"] == "PoweredOff":
            spec_at = round(time.time() - t0)
        if status_at is None and s and s["status"] == "PoweredOff":
            status_at = round(time.time() - t0)
        st, rr = e.api(f"/deployment/api/requests/{rid}")
        if (rr or {}).get("status") not in ("PENDING", "INPROGRESS", None):
            break
    out["vcfa"] = {"requestStatus": (rr or {}).get("status"),
                   "secondsToSupervisorSpecChanged": spec_at,
                   "secondsToMachineConverged": status_at,
                   "secondsToRequestSuccessful": round(time.time() - t0),
                   "recordAfter": record_view(e, dep, name)}
    print(f"  VCFA PowerOff: it wrote the Supervisor's own spec at ~{spec_at}s, the machine converged at "
          f"~{status_at}s, and only then did the request report {(rr or {}).get('status')} at "
          f"~{out['vcfa']['secondsToRequestSuccessful']}s")

    # ---- pathway 2: the same field, on the Supervisor
    t0 = time.time()
    st, _ = e.ns(url, f"{vms}/{name}", "PATCH", {"spec": {"powerState": "PoweredOn"}},
                 ctype="application/merge-patch+json")
    back = None
    for _ in range(18):
        time.sleep(10)
        s = read_spec(e, url, ns, name)
        if s and s["status"] == "PoweredOn":
            back = round(time.time() - t0)
            break
    time.sleep(20)          # give the record every chance to notice before reading it
    rv = record_view(e, dep, name)
    out["supervisor"] = {"patchStatus": st, "secondsToMachineConverged": back, "recordAfter": rv,
                         "recordStillDeclares": rv.get("declared"),
                         "machineActuallyIs": (read_spec(e, url, ns, name) or {}).get("status"),
                         "syncStatusSaysProblem": rv.get("syncStatus") not in ("SUCCESS", None)}
    print(f"  Supervisor PATCH: the machine converged at ~{back}s, and the record now declares "
          f"{rv.get('declared')} for a machine that is {out['supervisor']['machineActuallyIs']}, "
          f"with syncStatus reading {rv.get('syncStatus')}")

    # ---- teardown, deliberately while the machine still exists
    print("  tearing down with the machine STILL PRESENT, which is what lets the record retire")
    t0 = time.time()
    e.api(f"/deployment/api/deployments/{dep}", "DELETE")
    gone = None
    for _ in range(40):
        time.sleep(10)
        if e.api(f"/deployment/api/deployments/{dep}")[0] == 404:
            gone = round(time.time() - t0)
            break
    out["teardown"] = {"secondsToRecordRemoved": gone,
                       "recordRetired": gone is not None,
                       "note": "the probe never removes the machine first; see the docstring"}
    import urllib.parse as up
    e.gw(f"/apis/{BP}/namespaces/{project}/blueprintversions/{up.quote(bpname + ':1.0.0', safe='')}", "DELETE")
    time.sleep(6)
    e.gw(f"/apis/{BP}/namespaces/{project}/blueprints/{bpname}", "DELETE")
    st, left = e.ns(url, vms)
    out["residue"] = [v["metadata"]["name"] for v in ((left.get("items") or []) if st == 200 else [])
                      if v["metadata"]["name"].startswith(PREFIX)]
    print(f"  record retired at ~{gone}s; residue: {out['residue'] or 'none'}")
    return out


def main():
    host, org = os.environ["VCFA_HOST"], os.environ["VCFA_ORG"]
    refresh = open(os.environ["VCFA_REFRESH_TOKEN_FILE"], encoding="utf-8").read().strip()
    out_dir = os.environ.get("OUT_DIR", ".")
    want = "--probe-pathways" in sys.argv[1:]
    e = Estate(host, org, refresh)
    L = Labels()
    print("pathways.py: the same Day-2 change through each plane, and what stays true\n")

    st, pl = e.gw(f"/apis/{PROJ}/projects")
    projects = [p["metadata"]["name"] for p in ((pl.get("items") or []) if st == 200 else [])]
    if not projects:
        raise SystemExit("no project is visible to this identity")
    project = os.environ.get("PATHWAYS_PROJECT") or projects[0]
    L.get("project", project)

    endpoints = []
    for p in projects:
        st, nss = e.gw(f"/apis/{A3}/namespaces/{p}/supervisornamespaces")
        for n in ((nss.get("items") or []) if st == 200 else []):
            u = (n.get("status") or {}).get("namespaceEndpointURL")
            if u:
                L.get("namespace", n["metadata"]["name"])
                endpoints.append((p, n["metadata"]["name"], u))

    rows, tombstones = audit(e, L, endpoints)
    agree = sum(1 for r in rows if r["agrees"])
    missing = sum(1 for r in rows if r["syncStatus"] == "MISSING")
    # Drift that syncStatus does not report. Count BOTH comparisons, because the first needs only an
    # Automation credential: the record caches the object it last observed, so a manifest that no longer
    # matches that cached object is detectable without reaching the Supervisor at all.
    silent = [r for r in rows
              if (r["declaredVsLive"] or r["declaredVsObserved"]) and r["syncStatus"] in ("SUCCESS", None)]
    from_record_alone = [r for r in rows if r["declaredVsObserved"] and r["syncStatus"] in ("SUCCESS", None)]
    print(f"  DRIFT AUDIT: {len(rows)} machine(s) claimed by a deployment")
    print(f"     {agree} where the record's manifest, its cached object and the live machine all agree")
    print(f"     {missing} whose object is gone, which syncStatus does report")
    print(f"     {len(silent)} where the machine no longer matches the manifest AND syncStatus says nothing,")
    print(f"        of which {len(from_record_alone)} are provable from the record alone, with no Supervisor read")
    for r in rows:
        flag = "agrees" if r["agrees"] else ("object gone" if r["syncStatus"] == "MISSING"
                                             else ("DRIFT: " + ",".join(r["declaredVsLive"])
                                                   if r["declaredVsLive"] else "cached object differs"
                                                   if r["declaredVsObserved"] else "not on a reachable namespace"))
        print(f"       {r['machine']:<16} sync={str(r['syncStatus']):<8} {flag}")
    if tombstones:
        print(f"\n  TOMBSTONES: {len(tombstones)} deployment(s) report DELETE_SUCCESSFUL and still hold a resource")
        for t in tombstones:
            print(f"     {t['name']:<16} resources still listed: {t['resourcesStillListed']} "
                  f"{t['syncStatuses']}")
        print("     These cannot be retired through this API. Plate 05 documents the sequence that makes one.")

    probed = None
    if want:
        ns = os.environ.get("PATHWAYS_NAMESPACE")
        if not ns:
            raise SystemExit("--probe-pathways needs PATHWAYS_NAMESPACE set to a namespace you may build in")
        match = [(p, n, u) for (p, n, u) in endpoints if n == ns]
        if not match:
            raise SystemExit(f"namespace {ns!r} is not visible")
        _p, _n, url = match[0]
        st, imgs = e.ns(url, f"/apis/{VMOP}/v1alpha5/namespaces/{ns}/virtualmachineimages")
        images = [i["metadata"]["name"] for i in ((imgs.get("items") or []) if st == 200 else [])]
        if not images:
            raise SystemExit(f"no VM image is bound to {ns!r}; images are namespace scoped")
        st, cls = e.ns(url, f"/apis/{VMOP}/v1alpha5/namespaces/{ns}/virtualmachineclasses")
        classes = sorted(c["metadata"]["name"] for c in ((cls.get("items") or []) if st == 200 else []))
        storage = os.environ.get("PATHWAYS_STORAGE_CLASS")
        if not storage:
            st, vv = e.ns(url, f"/apis/{VMOP}/v1alpha5/namespaces/{ns}/virtualmachines")
            storage = next((s for s in [(v.get("spec") or {}).get("storageClass")
                                        for v in ((vv.get("items") or []) if st == 200 else [])] if s), None)
        if not storage:
            raise SystemExit("could not infer a storage class; set PATHWAYS_STORAGE_CLASS")
        L.get("storageclass", storage)
        print(f"\n  probe: one machine in {L.get('namespace', ns)}, changed through each pathway")
        probed = probe(e, L, project, ns, url, images[0],
                       storage, "best-effort-xsmall" if "best-effort-xsmall" in classes else classes[0])
    else:
        print("\n  probe: not run (pass --probe-pathways to make the same change through each pathway)")

    # G-166: a run that did not probe has nothing to say about the probe block, which is not the same as
    # having found it empty. The probe records a BEHAVIOUR of the platform rather than a measurement this
    # record compares against other measurements, so the right answer here is carry forward, not refuse.
    # The audit above is re-read every run and is never carried.
    _prior = {}
    _pp = os.path.join(out_dir, "pathways.json")
    if os.path.exists(_pp):
        try:
            _prior = json.load(open(_pp, encoding="utf-8")) or {}
        except ValueError:
            _prior = {}
    if probed is None and _prior.get("probe"):
        probed = _prior["probe"]
        print("  carrying forward the probe captured by an earlier run with the flag; this run did not "
              "re-probe it and has not erased it")

    payload = {"captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "project": L.get("project", project), "watchedFields": list(WATCHED),
               "audit": rows, "tombstones": tombstones,
               "auditTotals": {"claimed": len(rows), "agree": agree, "objectGone": missing,
                               "driftedSilently": len(silent),
                               "driftProvableFromTheRecordAlone": len(from_record_alone)},
               "probe": probed}
    text = L.scrub(UUID.sub("{{id}}", json.dumps(payload, indent=1, ensure_ascii=False)))
    for secret in (e.bearer, refresh, host, org, os.environ.get("PATHWAYS_NAMESPACE")):
        assert not secret or secret not in text, "an estate value reached the record"
    bare = re.sub(r"\{\{[^}]*\}\}", "", text)
    for fam, m in L.maps.items():
        for nm in m:
            if nm and re.search(r"(?<![A-Za-z0-9-])" + re.escape(nm) + r"(?![A-Za-z0-9-])", bare):
                shp = re.sub(r"[A-Za-z]", "a", re.sub(r"[0-9]", "9", nm))
                raise SystemExit(f"FATAL: a {fam} name ({len(nm)} characters, shape {shp}) reached the record")
    os.makedirs(out_dir, exist_ok=True)
    open(os.path.join(out_dir, "pathways.json"), "w", encoding="utf-8").write(text + "\n")
    print(f"\nwrote pathways.json ({len(rows)} claimed machine(s) audited, {len(tombstones)} tombstone(s)"
          f"{', probe included' if probed else ''}); every estate name replaced by a placeholder")


if __name__ == "__main__":
    main()
