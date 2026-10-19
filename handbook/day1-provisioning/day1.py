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

  --lookup <name> [--project <project>]   read-only, and on its own: every blueprint of that exact name in every
     project you can see, with its id, project and creator. Key automation on the id it prints; it refuses when
     the name also matches outside your project, which is how a publish flow updates a colleague's template.

Without --probe-release nothing here writes. Organization-specific names are replaced by stable placeholders
and the script refuses to write a record in which one survived. Field names, verbs, HTTP statuses and the
platform's own error strings are the product's vocabulary and are kept, because they are the lesson.

Sign-in, one of:
  VCFA_REFRESH_TOKEN_FILE   a file holding a refresh token minted for the organization, mode 0600
  VCFA_USER and VCFA_PASSWORD_FILE   a session login as user@org (the password from a file of mode 0600, or
                            VCFA_PASSWORD, the value itself, which lands in the shell's history)
A file open to group or other is refused before it is read.

Run:
  export VCFA_HOST=<automation-fqdn> VCFA_ORG=<org>
  export VCFA_USER=<account> VCFA_PASSWORD_FILE=~/.vcf/vcfa-password    # or VCFA_REFRESH_TOKEN_FILE
  export TLS_VERIFY=false                                               # only on a self-signed lab CA
  python3 day1.py
  python3 day1.py --probe-release   # also creates and deletes a throwaway blueprint, see step 5

Exit: 0 read (for --lookup: one match, in your project, or the only one when no project is named); 1 --lookup
      found no blueprint of that name; 2 a call failed or the sign-in was refused; 3 --lookup found the name
      outside your project or more than once: key on the id, never update by name; 5 an unknown argument.
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

    # The product's own vocabulary is never an estate name. A principal can be called exactly what a platform
    # object is called (this estate has a user named "admin" and a project role named "admin"), and registering
    # one teaches the scrubber to blank the other. A name in RESERVED identifies no estate and is left alone.
    RESERVED = {"admin", "view", "edit", "user", "users", "group", "groups", "owner", "auditor", "auditors",
                "administrator", "administrators", "default", "system", "none", "all"}

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
        # Longest first so a contained name cannot corrupt a longer one, and on a WORD BOUNDARY so a short
        # name is not replaced inside an unrelated word. A principal really can be called "admin", and a naive
        # replace turns the field name "administrators" into "{{user-3}}istrators". The leak check below uses
        # the same boundary, so what the scrub replaces and what the check looks for are one rule.
        for real, label in sorted(known, key=lambda kv: -len(kv[0])):
            text = re.sub(r"(?<![A-Za-z0-9-])" + re.escape(real) + r"(?![A-Za-z0-9-])",
                          "{{%s}}" % label, text)
        return UUID.sub("{{id}}", text)


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


class Vcfa:
    """One bearer, two faces: the CCI gateway under /cci/kubernetes and the classic API at the root."""

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
            print(f"FATAL: the {self.kind} answered HTTP {e.code}: {e.read().decode(errors='replace')[:200]}")
            sys.exit(2)
        except (urllib.error.URLError, OSError) as e:
            print(f"FATAL: the {self.kind} did not answer: {e}")
            sys.exit(2)
        if not self.bearer:
            print(f"FATAL: the {self.kind} answered without a bearer")
            sys.exit(2)

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

    def api_all(self, path):
        """Every page of a classic list, sorted by id: a page holds at most 200 entries, and a list read without a
        sort has no stable order across pages (G-634)."""
        out, number = [], 0
        while True:
            st, body = self.api("GET", f"{path}{'&' if '?' in path else '?'}size=200&page={number}&sort=id,asc")
            if st != 200 or not isinstance(body, dict):
                return st, out
            out += body.get("content") or []
            number += 1
            if body.get("last", True) or number >= (body.get("totalPages") or 0):
                return st, out

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


def lookup(c, name, project=None):
    """Every blueprint named exactly ``name`` across the projects this identity can see, from the classic face, which
    carries the id, the project and the creator; one search, one page (a name is unique within a project)."""
    st, body = c.api("GET", f"/blueprint/api/blueprints?search={urllib.parse.quote(name)}&size=200")
    if st != 200 or not isinstance(body, dict):
        print(f"FATAL: the blueprint search answered HTTP {st}")
        return 2
    found = [b for b in (body.get("content") or []) if b.get("name") == name]
    print(f"day1.py: blueprints named {name!r} in every project this identity can see: {len(found)}")
    for b in found:
        print(f"  id {b.get('id')}  project {b.get('projectName')}  created by {b.get('createdBy')}")
    if not found:
        print("  none: a create under that name collides with nothing")
        return 1
    mine = [b for b in found if project is None or b.get("projectName") == project]
    if len(found) == 1 and mine:
        print(f"  one match{' in ' + project if project else ''}: key on id {found[0].get('id')}, never on the name")
        return 0
    print("  the name is not a key here: it matches " + (f"outside {project}" if project and len(mine) < len(found)
                                                          else "more than once") +
          "; update only by the id of the one you own, and refuse a match by name alone")
    return 3


def refuse_unknown_args(known, takes_value=()):
    """Refuse any argument this script does not recognise, before a client opens: a stray flag such as --check
    must never reach a write. --help prints the usage above."""
    args = sys.argv[1:]
    if "-h" in args or "--help" in args:
        print(__doc__)
        sys.exit(0)
    unknown = [a for i, a in enumerate(args) if a not in known and not (i and args[i - 1] in takes_value)]
    if unknown:
        print(f"unknown argument(s) {unknown}: this script takes {', '.join(sorted(known))} (see --help)", file=sys.stderr)
        sys.exit(5)


def main():
    refuse_unknown_args({"--probe-release", "--lookup", "--project"}, takes_value=("--lookup", "--project"))
    for flag in ("--lookup", "--project"):
        if flag in sys.argv and sys.argv.index(flag) + 1 >= len(sys.argv):
            print(f"{flag} takes a value (see --help)", file=sys.stderr)
            sys.exit(5)
    host, org = os.environ["VCFA_HOST"], os.environ["VCFA_ORG"]
    try:
        refresh, password = secret("VCFA_REFRESH_TOKEN"), secret("VCFA_PASSWORD")
    except OSError as e:   # a secret file that is missing, unreadable or open to group or other
        print(f"FATAL: {e}")
        sys.exit(2)
    user = os.environ.get("VCFA_USER")
    if not refresh and not (user and password):
        print("FATAL: set VCFA_REFRESH_TOKEN_FILE, or VCFA_USER with VCFA_PASSWORD_FILE (see --help)")
        sys.exit(2)
    out_dir = os.environ.get("OUT_DIR", ".")
    c = Vcfa(host, org, refresh, None if refresh else user, None if refresh else password)
    if "--lookup" in sys.argv:
        proj = sys.argv[sys.argv.index("--project") + 1] if "--project" in sys.argv else None
        sys.exit(lookup(c, sys.argv[sys.argv.index("--lookup") + 1], proj))
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
    st, classic = c.api_all("/deployment/api/deployments")
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
                "classicDeploymentsWithoutAnOwner": sum(1 for d in classic if not d.get("ownedBy")),
                "classicFields": sorted(classic_keys), "cciFields": sorted(cci_keys),
                "onlyOnClassic": only_classic, "onlyOnCci": sorted(cci_keys - classic_keys),
                "identityFieldsOnlyOnClassic": who}
    print(f"\n  the same deployments, both faces: classic returns {len(classic)}, CCI returns {len(inst)}")
    print(f"     fields on the classic object only: {len(only_classic)} -> {only_classic}")
    print(f"     of those, the ones naming a person: {who}")
    print(f"     classic deployments with no owner: {surfaces['classicDeploymentsWithoutAnOwner']} of {len(classic)}")
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
            # A version names its blueprint by display name, which need not be the object's name; register it so
            # the scrub replaces it and the leak check below looks for it.
            L.get("blueprint", sp.get("blueprintName"))
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
    st, cl_items = c.api_all("/catalog/api/items")
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
        if release is not None:
            release["probedUtc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    else:
        print("\n  release semantics: not probed; pass --probe-release to ask each face what a delete does "
              "(it creates a throwaway blueprint and deletes it again)")

    # ---- write, sanitized
    payload = {"captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "signIn": c.kind,
               "vocabulary": vocab, "surfaces": surfaces, "tree": tree, "catalogScoping": scoping,
               "schema": schema_shape, "resourceTypes": types, "images": images, "release": release}

    # G-166, generically: an optional probe writes a section of a record, and it does not get to delete
    # one. A run without the probe flag leaves those keys None, and writing them would erase what a
    # flagged run captured. Carry forward any key this run has nothing to say about.
    _prior_path = os.path.join(out_dir, "day1.json")
    if os.path.exists(_prior_path):
        try:
            _prior = json.load(open(_prior_path, encoding="utf-8")) or {}
        except ValueError:
            _prior = {}
        for _k, _v in list(payload.items()):
            if _v is None and _prior.get(_k) is not None:
                payload[_k] = _prior[_k]
                print(f"  carrying forward {_k!r} from an earlier run with the probe flag; "
                      f"this run did not re-probe it and has not erased it")

    text = UUID.sub("{{id}}", json.dumps(payload, indent=1, ensure_ascii=False))
    for value in (c.bearer, refresh, password, user, host, org):
        assert not value or value not in text, "an estate value reached the record"
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
