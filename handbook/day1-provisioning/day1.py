#!/usr/bin/env python3
"""day1.py: the Day-1 provisioning plane of a VCF Automation 9.1 organization, read through both of its faces.

Day-1 has two interfaces over the same objects: the Kubernetes-style Cloud Consumption Interface kinds
(``blueprint.cci.vmware.com``, ``catalog.cci.vmware.com``, ``image.cci.vmware.com``) and the classic VCF
Automation API (``/blueprint/api``, ``/catalog/api``, ``/deployment/api``). They are not two spellings of one
thing. This script puts them side by side and reports where they disagree:

  1. the VOCABULARY: every Day-1 kind each group declares, with the verbs the interface says you may use. The
     split between what a tenant may write and what it may only read is most of the plane's design;
  2. the FIELD COMPARISON: the same deployments read through both faces, field by field, and specifically which
     fields exist on one and not the other. Every field naming a person is on one side only;
  3. the CONTENT TREE: blueprints, their versions, and the catalog items a release produces, including the rule
     the interface enforces on a version object's name;
  4. the INGREDIENTS: the resource types a blueprint may declare, and the image catalog it draws on;
  5. with --probe-release, the DELETE SEMANTICS: what each face actually does when you ask it to remove a
     version. This creates a throwaway blueprint, releases a version, asks both faces to delete it, reads back
     what changed, and removes the blueprint again. It never touches content it did not create.

Without --probe-release nothing here writes. Organization-specific names are replaced by stable placeholders
and the script refuses to write a record in which one survived. Field names, verbs, HTTP statuses and the
platform's own error strings are the product's vocabulary and are kept, because they are the lesson.

Run:
  export VCFA_HOST=<automation-fqdn> VCFA_ORG=<org>
  export VCFA_REFRESH_TOKEN_FILE=/path/to/refresh-token    # mode 0600
  export TLS_VERIFY=false                                  # only on a self-signed lab CA
  python3 day1.py
  python3 day1.py --probe-release   # also creates and deletes a throwaway blueprint, see step 5
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
BP = "blueprint.cci.vmware.com/v1alpha1"
CAT = "catalog.cci.vmware.com/v1alpha1"
IMG = "image.cci.vmware.com/v1alpha1"
PROJ = "project.cci.vmware.com/v1alpha2"
DAY1_GROUPS = ("blueprint.cci.vmware.com", "catalog.cci.vmware.com", "image.cci.vmware.com")


def ctx():
    verify = os.environ.get("TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")
    return ssl.create_default_context() if verify else ssl._create_unverified_context()


class Labels:
    """Every estate name becomes a stable placeholder, longest first so a contained name cannot corrupt a longer one."""

    def __init__(self):
        self.maps = {}

    def get(self, family, name):
        if not name:
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
            text = text.replace(real, "{{%s}}" % label)
        return UUID.sub("{{id}}", text)


class Vcfa:
    """One bearer, two faces: the CCI gateway under /cci/kubernetes and the classic API at the root."""

    def __init__(self, host, org, refresh_token):
        self.host = host
        body = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": refresh_token}).encode()
        req = urllib.request.Request(
            f"https://{host}/oauth/tenant/{org}/token", data=body, method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
        with urllib.request.urlopen(req, context=ctx(), timeout=30) as r:
            self.bearer = json.loads(r.read())["access_token"]

    def _send(self, method, url, body=None):
        headers = {"Authorization": f"Bearer {self.bearer}", "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, method=method, headers=headers,
                                     data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(req, context=ctx(), timeout=120) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, raw.decode(errors="replace")[:300]
        except (urllib.error.URLError, OSError) as e:
            return None, str(e)

    def k8s(self, method, path, body=None):
        """The Cloud Consumption Interface face."""
        return self._send(method, f"https://{self.host}{CCI}{path}", body)

    def api(self, method, path, body=None):
        """The classic VCF Automation face."""
        return self._send(method, f"https://{self.host}{path}", body)

    def items(self, group, resource, project=None):
        p = f"/apis/{group}/namespaces/{project}/{resource}" if project else f"/apis/{group}/{resource}"
        st, body = self.k8s("GET", p)
        return st, ((body.get("items") or []) if st == 200 and isinstance(body, dict) else [])


def msg(r):
    return (r.get("message") or "") if isinstance(r, dict) else str(r or "")


def probe_release(c, L, project, model_content):
    """Ask each face what it actually does when told to remove a released version.

    A verb is a promise. This checks the promise, because the two faces answer the same request differently and
    one of them answers success for something it did not do. Everything created here is deleted here; the
    blueprint name is prefixed so nothing pre-existing can be matched by accident.
    """
    name = "probe-day1-release"
    results = []

    def cat_items():
        st, its = c.items(CAT, "catalogitems", project)
        return [i["metadata"]["name"] for i in its]

    st, r = c.k8s("POST", f"/apis/{BP}/namespaces/{project}/blueprints",
                  {"apiVersion": BP, "kind": "Blueprint", "metadata": {"name": name, "namespace": project},
                   "spec": {"content": model_content, "description": "handbook probe, deleted by the same run"}})
    if st not in (200, 201):
        print(f"\n  release semantics: could not create a throwaway blueprint (HTTP {st}); skipped")
        return None

    # The version object's name is not free: the interface derives it and refuses anything else.
    st, r = c.k8s("POST", f"/apis/{BP}/namespaces/{project}/blueprintversions",
                  {"apiVersion": BP, "kind": "BlueprintVersion", "metadata": {"name": "wrong-name", "namespace": project},
                   "spec": {"blueprintName": name, "version": "1.0.0", "publishToCatalog": True}})
    results.append({"case": "a version object under a name of your choosing", "face": "cci", "status": st,
                    "outcome": "refused", "message": L.scrub(msg(r))})
    print(f"\n  release semantics, on a throwaway blueprint this run creates and deletes")
    print(f"     naming a version freely                 HTTP {st}  {msg(r)[:110]}")

    vname = f"{name}:1.0.0"
    enc = urllib.parse.quote(vname, safe="")
    before = cat_items()
    st, r = c.k8s("POST", f"/apis/{BP}/namespaces/{project}/blueprintversions",
                  {"apiVersion": BP, "kind": "BlueprintVersion", "metadata": {"name": vname, "namespace": project},
                   "spec": {"blueprintName": name, "version": "1.0.0", "publishToCatalog": True}})
    time.sleep(6)
    after = cat_items()
    results.append({"case": "release a version with publishToCatalog true", "face": "cci", "status": st,
                    "outcome": "accepted" if st in (200, 201) else "refused",
                    "catalogItemsBefore": len(before), "catalogItemsAfter": len(after)})
    print(f"     release version 1.0.0                   HTTP {st}  catalog items {len(before)} -> {len(after)}")

    st_d, _ = c.k8s("DELETE", f"/apis/{BP}/namespaces/{project}/blueprintversions/{enc}")
    time.sleep(6)
    st_g, g = c.k8s("GET", f"/apis/{BP}/namespaces/{project}/blueprintversions/{enc}")
    still = st_g == 200
    flag = ((g.get("spec") or {}).get("publishToCatalog")) if still else None
    now = cat_items()
    results.append({"case": "DELETE the version object", "face": "cci", "status": st_d, "outcome": "accepted",
                    "versionStillExists": still, "publishToCatalogAfter": flag,
                    "catalogItemsAfter": len(now),
                    "verdict": "the object survives and publishToCatalog flips to false: this is an unrelease"
                               if still and flag is False else "the object was removed"})
    print(f"     CCI     DELETE the version              HTTP {st_d}  version still present: {still}, "
          f"publishToCatalog now {flag}, catalog items {len(now)}")

    st_b, rb = c.api("GET", f"/blueprint/api/blueprints?search={urllib.parse.quote(name)}")
    mine = [b for b in ((rb.get("content") or []) if isinstance(rb, dict) else []) if b.get("name") == name]
    if mine:
        bid = mine[0]["id"]
        c.api("POST", f"/blueprint/api/blueprints/{bid}/versions/1.0.0/actions/release", {})
        time.sleep(6)
        st_c, rc = c.api("DELETE", f"/blueprint/api/blueprints/{bid}/versions/1.0.0")
        results.append({"case": "DELETE the same version", "face": "classic", "status": st_c,
                        "outcome": "refused", "message": L.scrub(msg(rc))})
        print(f"     classic DELETE the same version         HTTP {st_c}  {msg(rc)[:110]}")
        st_u, ru = c.api("POST", f"/blueprint/api/blueprints/{bid}/versions/1.0.0/actions/unrelease", {})
        results.append({"case": "unrelease the same version, by its own name", "face": "classic", "status": st_u,
                        "outcome": "accepted" if st_u in (200, 204) else "refused", "message": L.scrub(msg(ru))})
        print(f"     classic unrelease, the named action     HTTP {st_u}  "
              f"{'accepted, which is what the CCI delete did' if st_u in (200, 204) else msg(ru)[:80]}")

    st, bs = c.items(BP, "blueprints", project)
    for b in bs:
        if b["metadata"]["name"].startswith("probe-day1"):
            st_x, _ = c.k8s("DELETE", f"/apis/{BP}/namespaces/{project}/blueprints/{b['metadata']['name']}")
            results.append({"case": "DELETE the blueprint object", "face": "cci", "status": st_x,
                            "outcome": "accepted" if st_x in (200, 204) else "refused"})
            print(f"     CCI     DELETE the blueprint object     HTTP {st_x}  (this is the one that cascades)")
    time.sleep(6)
    st, bs = c.items(BP, "blueprints", project)
    st, vs = c.items(BP, "blueprintversions", project)
    residue = [x["metadata"]["name"] for x in bs + vs if x["metadata"]["name"].startswith("probe-day1")]
    residue += [n for n in cat_items() if n.startswith("probe-day1")]
    print(f"     cleanup: probe residue on the estate    {residue or 'none'}")
    if residue:
        print("     WARNING: something the probe created is still present; remove it before trusting the counts above.")
    return {"cases": results, "residue": residue}


def main():
    host, org = os.environ["VCFA_HOST"], os.environ["VCFA_ORG"]
    refresh = open(os.environ["VCFA_REFRESH_TOKEN_FILE"], encoding="utf-8").read().strip()
    out_dir = os.environ.get("OUT_DIR", ".")
    c = Vcfa(host, org, refresh)
    L = Labels()
    print("day1.py: the Day-1 plane, read through both of its faces\n")

    # ---- 1. the vocabulary, and the verbs each kind allows
    st, groups = c.k8s("GET", "/apis")
    vocab = []
    for g in (groups.get("groups") or []):
        gv = g["preferredVersion"]["groupVersion"]
        if not any(gv.startswith(d) for d in DAY1_GROUPS):
            continue
        st, rl = c.k8s("GET", f"/apis/{gv}")
        for r in (rl.get("resources") or []):
            if "/" in r["name"]:
                continue
            verbs = sorted(r.get("verbs") or [])
            vocab.append({"group": gv, "resource": r["name"], "kind": r["kind"],
                          "namespaced": bool(r["namespaced"]), "verbs": verbs,
                          "writable": bool({"create", "update", "patch", "delete"} & set(verbs))})
    writable = [v for v in vocab if v["writable"]]
    print(f"  vocabulary: {len(vocab)} Day-1 kind(s) across {len({v['group'] for v in vocab})} group(s); "
          f"{len(writable)} accept a write, {len(vocab) - len(writable)} are read-only")
    for v in vocab:
        print(f"     {v['group'].split('.')[0]:<10} {v['resource']:<24} {'write' if v['writable'] else 'read '}  {','.join(v['verbs'])}")

    st, projects = c.k8s("GET", f"/apis/{PROJ}/projects")
    projects = [p["metadata"]["name"] for p in ((projects.get("items") or []) if st == 200 else [])]
    for p in projects:
        L.get("project", p)
    if not projects:
        raise SystemExit("no project is visible to this identity")
    home = projects[0]

    # ---- 2. the same deployments, both faces, field by field
    st, dep = c.api("GET", "/deployment/api/deployments?size=50")
    classic = (dep.get("content") or []) if st == 200 and isinstance(dep, dict) else []
    st, inst = c.items(CAT, "instances", home)
    cci_keys = set()
    for i in inst:
        cci_keys |= set(i.get("spec") or {}) | set(i.get("status") or {}) | set(i.get("metadata") or {})
    classic_keys = set()
    for d in classic:
        classic_keys |= set(d)
    only_classic = sorted(classic_keys - cci_keys)
    who = sorted(k for k in only_classic if re.search(r"(?i)(by|owner)", k))
    surfaces = {"classicDeployments": len(classic), "cciInstances": len(inst),
                "classicFields": sorted(classic_keys), "cciFields": sorted(cci_keys),
                "onlyOnClassic": only_classic, "onlyOnCci": sorted(cci_keys - classic_keys),
                "identityFieldsOnlyOnClassic": who}
    print(f"\n  the same deployments, both faces: classic returns {len(classic)}, CCI returns {len(inst)}")
    print(f"     fields on the classic object only: {len(only_classic)} -> {only_classic}")
    print(f"     of those, the ones naming a person: {who}")
    print(f"     fields on the CCI object only:     {sorted(cci_keys - classic_keys)}")

    # ---- 3. the content tree
    tree, naming_rule = [], None
    for p in projects:
        st, bs = c.items(BP, "blueprints", p)
        st, vs = c.items(BP, "blueprintversions", p)
        st_ci, ci = c.items(CAT, "catalogitems", p)
        for b in bs:
            L.get("blueprint", b["metadata"]["name"])
        for i in ci:
            L.get("catalogitem", i["metadata"]["name"])
        byname = {}
        for v in vs:
            sp = v.get("spec") or {}
            byname.setdefault(sp.get("blueprintName"), []).append(
                {"version": sp.get("version"), "publishToCatalog": bool(sp.get("publishToCatalog")),
                 "objectName": L.scrub(v["metadata"]["name"])})
        tree.append({"project": L.scrub(p), "blueprints": len(bs), "versions": len(vs), "catalogItems": len(ci),
                     "versionsByBlueprint": {L.scrub(str(k)): sorted(x["version"] or "" for x in vv)
                                             for k, vv in byname.items()},
                     "versionObjectNamesJoinWith": ":" if any(":" in (x["objectName"] or "") for vv in byname.values() for x in vv) else "?"})
    # is the catalog list actually filtered by the project in the path?
    sets = []
    for p in projects:
        st, ci = c.items(CAT, "catalogitems", p)
        sets.append({i["metadata"]["name"] for i in ci})
    same_everywhere = len(sets) > 1 and all(s == sets[0] for s in sets)
    st, cat_classic = c.api("GET", "/catalog/api/items?size=50")
    cl_items = (cat_classic.get("content") or []) if st == 200 and isinstance(cat_classic, dict) else []
    scoping = {"identicalAcrossProjects": same_everywhere, "projectsCompared": len(projects),
               "itemsPerProject": [len(s) for s in sets],
               "markedGlobal": sum(1 for i in cl_items if i.get("global")),
               "carryingAProjectList": sum(1 for i in cl_items if i.get("projectIds")),
               "total": len(cl_items)}
    print(f"\n  the content tree: {sum(t['blueprints'] for t in tree)} blueprint(s), "
          f"{sum(t['versions'] for t in tree)} version(s)")
    print(f"     catalog items are identical in every project read: {same_everywhere} "
          f"({scoping['itemsPerProject']}), yet {scoping['markedGlobal']} of {len(cl_items)} are marked global "
          f"and {scoping['carryingAProjectList']} carry a project list")
    schema_shape = None
    st, ci = c.items(CAT, "catalogitems", home)
    if ci:
        sch = (ci[0].get("spec") or {}).get("schema") or {}
        schema_shape = {"keys": sorted(sch.keys()), "properties": len(sch.get("properties") or {}),
                        "required": len(sch.get("required") or []),
                        "carriesTheTemplate": "content" in (ci[0].get("spec") or {})}
        print(f"     a catalog item's spec carries a schema of {schema_shape['properties']} typed input(s); "
              f"it carries the blueprint content: {schema_shape['carriesTheTemplate']}")

    # ---- 4. the ingredients
    st, rts = c.items(BP, "blueprintresourcetypes", home)
    types = sorted(r["metadata"]["name"] for r in rts)
    st, ims = c.items(IMG, "images", home)
    images = {"count": len(ims),
              "objectNameIsTheDisplayName": any(i["metadata"]["name"] == (i.get("spec") or {}).get("displayName") for i in ims),
              "objectNameIsAUuid": all(bool(UUID.fullmatch(i["metadata"]["name"])) for i in ims) if ims else None,
              "specFields": sorted((ims[0].get("spec") or {}).keys()) if ims else [],
              "statusFields": sorted((ims[0].get("status") or {}).keys()) if ims else []}
    print(f"\n  the ingredients: {len(types)} deployable resource type(s) -> {types}")
    print(f"     images: {images['count']}; the object name equals the display name: "
          f"{images['objectNameIsTheDisplayName']}; spec {images['specFields']}")

    # ---- 5. what a delete actually does
    release = None
    if "--probe-release" in sys.argv:
        st, bs = c.items(BP, "blueprints", home)
        model = min(((b.get("spec") or {}).get("content") or "") for b in bs) if bs else ""
        content = ("name: probe-day1-release\nversion: 1\n"
                   "description: Throwaway blueprint for a handbook probe. Provisions nothing.\n"
                   "resources:\n  Secret:\n    type: Util.PasswordEntry\n    properties:\n      length: 12\n")
        release = probe_release(c, L, home, content)
    else:
        print("\n  release semantics: not probed; pass --probe-release to ask each face what a delete does "
              "(it creates a throwaway blueprint and deletes it again)")

    # ---- write, sanitized
    payload = {"captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "vocabulary": vocab, "surfaces": surfaces, "tree": tree, "catalogScoping": scoping,
               "schema": schema_shape, "resourceTypes": types, "images": images, "release": release}
    text = UUID.sub("{{id}}", json.dumps(payload, indent=1, ensure_ascii=False))
    for secret in (c.bearer, refresh, host, org):
        assert secret not in text, "an estate value reached the record"
    bare = re.sub(r"\{\{[^}]*\}\}", "", text)
    for fam, m in L.maps.items():
        for nm in m:
            if nm and re.search(r"(?<![A-Za-z0-9-])" + re.escape(nm) + r"(?![A-Za-z0-9-])", bare):
                shape = re.sub(r"[A-Za-z]", "a", re.sub(r"[0-9]", "9", nm))
                raise SystemExit(f"FATAL: a {fam} name ({len(nm)} characters, shape {shape}) reached the record")
    os.makedirs(out_dir, exist_ok=True)
    open(os.path.join(out_dir, "day1.json"), "w", encoding="utf-8").write(text + "\n")
    print(f"\nwrote day1.json ({len(vocab)} kinds, {len(only_classic)} fields on the classic deployment alone); "
          f"every organization name replaced by a placeholder")


if __name__ == "__main__":
    main()
