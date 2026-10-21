#!/usr/bin/env python3
"""reprobe.py - the writes behind this chapter's findings, re-asked on your build, each on a throwaway.

whoami.py reads; this writes, and only what a probe names. Each probe touches objects it creates under a fixed
prefix, reads back what the write did, removes it, and checks that nothing is left:

  --probe-import GROUP     a directory group, imported twice: first under the automation grant (a refresh token
                           traded at /oauth), then under an interactive session login (POST /cloudapi/1.0.0/sessions),
                           each as Organization User; read back, its members counted, deleted, and looked for again.
                           GROUP must exist in the directory and must not be imported yet; pick one with no members.
  --probe-project-scope    as a project administrator: the access review for creating, updating and deleting a
                           project, then a project create under a throwaway name, and an update of the spec and a delete of a
                           project it does not belong to, both sent as dry runs so nothing can change there (the
                           platform refuses a change outside the spec before it asks who you are).
  --probe-namespace        a throwaway Supervisor namespace in PROJECT, its spec copied from TEMPLATE_NAMESPACE: the
                           advanced member's create (the role reads namespaces but does not create them), the project
                           administrator's create, then on the namespace's own endpoint two members each create a
                           ConfigMap, edit and delete the other's, and a plain member asks to read them; the namespace is
                           deleted and waited out.

Every probe needs at least one flag; with none the script does nothing. It writes reprobe.json: statuses, verdicts,
counts, and platform messages with every estate name replaced; it refuses to write a record in which a name
survived. Stdlib only; no secret is printed or written; every password and token comes from a file of mode 0600.

Env:  VCFA_HOST, VCFA_ORG; VCFA_USER and VCFA_PASSWORD_FILE (an organization administrator, for the session login,
      the reads and the cleanup); VCFA_REFRESH_TOKEN_FILE (the automation grant, for --probe-import; without it that leg is recorded as not asked);
      VCFA_TEST_USERS (member,advanced,admin: three directory users bound edit, edit_adv and admin in PROJECT) and
      VCFA_TEST_PASSWORD_FILE; PROJECT, FOREIGN_PROJECT (one the admin is not bound in), TEMPLATE_NAMESPACE;
      TLS_VERIFY=false on a self-signed lab CA; OUT (reprobe.json)
Exit: 0 recorded · 1 the record would carry an estate value, so it was not written · 2 a precondition refused the
      run, nothing written · 3 a call failed · 5 usage: no probe, an unknown option, an unset variable, or a credential
      file missing or open to group or other
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
AUTHZ = "authorization.cci.vmware.com/v1alpha1"
PROJ = "project.cci.vmware.com/v1alpha2"
INFRA = "infrastructure.cci.vmware.com/v1alpha3"
CLOUDAPI = "application/json;version=9.1.0"
GROUPS_API = "application/json;version=10.0.0.0-alpha"
FLAGS = {"--probe-import", "--probe-project-scope", "--probe-namespace"}
PREFIX = "pca-reprobe"


def ctx():
    verify = os.environ.get("TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")
    return ssl.create_default_context() if verify else ssl._create_unverified_context()


def read_secret(var):
    """The secret in the file VAR names. A file open to group or other is refused before it is read; the refusal
    names the variable and the fix, never the file's content."""
    with open(os.environ[var], encoding="utf-8") as f:
        mode = os.fstat(f.fileno()).st_mode & 0o777
        # Windows makes the mode from the read-only flag alone, so it has no group or other bits to judge.
        if mode & 0o077 and os.name != "nt":
            raise PermissionError(f"{var} names a file of mode {mode:04o}, open to group or other: "
                                  f'run chmod 600 "${var}" and try again (the file was not read)')
        return f.read().strip()


class Refused(Exception):
    """A precondition the run will not cross; nothing has been written when it is raised."""


class Http:
    def __init__(self, host):
        self.host = host

    def call(self, method, url, bearer=None, basic=None, body=None, accept="application/json", headers=None,
             ctype="application/json"):
        h = {"Accept": accept, **(headers or {})}
        if bearer:
            h["Authorization"] = f"Bearer {bearer}"
        if basic:
            h["Authorization"] = "Basic " + base64.b64encode(basic.encode()).decode()
        data = None
        if body is not None:
            data, h["Content-Type"] = json.dumps(body).encode(), ctype
        full = url if url.startswith("https://") else f"https://{self.host}{url}"
        req = urllib.request.Request(full, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, context=ctx(), timeout=60) as r:
                raw, st, hd = r.read(), r.status, dict(r.headers)
        except urllib.error.HTTPError as e:
            raw, st, hd = e.read(), e.code, dict(e.headers)
        try:
            out = json.loads(raw or b"null")
        except ValueError:
            out = raw.decode(errors="replace")[:300]
        return st, out, hd

    def session(self, user, org, password):
        st, body, hd = self.call("POST", "/cloudapi/1.0.0/sessions", basic=f"{user}@{org}:{password}", accept=CLOUDAPI)
        token = next((v for k, v in hd.items() if k.lower() == "x-vmware-vcloud-access-token"), None)
        if st != 200 or not token:
            raise RuntimeError(f"session login for one identity answered HTTP {st}")
        return token, body

    def grant(self, org, refresh):
        body = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": refresh}).encode()
        req = urllib.request.Request(f"https://{self.host}/oauth/tenant/{org}/token", data=body, method="POST",
                                     headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
        with urllib.request.urlopen(req, context=ctx(), timeout=30) as r:
            return json.loads(r.read())["access_token"]


class Scrub:
    """Every estate name the run meets, replaced in one pass, longest first (G-646)."""

    def __init__(self):
        self.known = {}

    def add(self, real, label):
        if real and real not in self.known:
            self.known[real] = "{{%s}}" % label

    def __call__(self, text):
        if not isinstance(text, str) or not self.known:
            return text
        pattern = re.compile("|".join(re.escape(k) for k in sorted(self.known, key=len, reverse=True)))
        return pattern.sub(lambda m: self.known[m.group(0)], text)


def message(body):
    if isinstance(body, dict):
        return body.get("message") or body.get("reason") or ""
    return str(body or "")[:200]


def items(http, path, bearer):
    st, body, _ = http.call("GET", CCI + path, bearer=bearer)
    return st, (body.get("items") or []) if st == 200 and isinstance(body, dict) else []


def wait_gone(http, path, bearer, name, rounds=40, every=15):
    """Deletion is asynchronous on the CCI plane; wait for the object to stop answering, re-issuing the delete."""
    for n in range(rounds):
        st, _, _ = http.call("GET", f"{CCI}{path}/{name}", bearer=bearer)
        if st == 404:
            return n * every
        if n and n % 8 == 0:
            http.call("DELETE", f"{CCI}{path}/{name}", bearer=bearer)
        time.sleep(every)
    return None


# ---------------------------------------------------------------- G-094: the import, by grant and by session
def probe_import(http, env, scrub, group):
    org, admin = env["org"], env["admin"]
    tok, sess = http.session(admin["user"], org, admin["password"])
    org_uuid = ((sess.get("org") or {}).get("id") or "").split(":")[-1]
    tenant = {"X-VMWARE-VCLOUD-TENANT-CONTEXT": org_uuid}
    scrub.add(group, "group")
    q = urllib.parse.quote(f"name=={group}")
    st, found, _ = http.call("GET", f"/cloudapi/1.0.0/groups?filter={q}", bearer=tok, accept=CLOUDAPI, headers=tenant)
    if st != 200:
        raise RuntimeError(f"the imported-group list answered HTTP {st}")
    if found.get("values"):
        raise Refused("the group is already imported; pick one that is not, so the probe removes only what it adds")
    st, directory, _ = http.call("GET", f"/cloudapi/1.0.0/ldap/search/group?q={urllib.parse.quote(group)}",
                                 bearer=tok, accept=CLOUDAPI, headers=tenant)
    if st != 200 or not any(d.get("name") == group for d in (directory if isinstance(directory, list) else [])):
        raise Refused("the directory search does not return that group by name")
    st, roles, _ = http.call("GET", "/cloudapi/1.0.0/roles?filter=" + urllib.parse.quote("name==Organization User"),
                             bearer=tok, accept=CLOUDAPI, headers=tenant)
    role = next(iter(roles.get("values") or []), None) if st == 200 else None
    if not role:
        raise RuntimeError("the Organization User role was not found")
    body = {"name": group, "providerType": "LDAP", "description": f"{PREFIX}: imported and removed by one run",
            "roleEntityRefs": [{"id": role["id"], "name": role["name"]}]}
    out = {"role": "Organization User"}
    made = []

    bearer = None
    if env.get("refresh"):
        try:
            bearer = http.grant(org, env["refresh"])
        except urllib.error.HTTPError as e:
            out["automation_grant"] = {"status": None, "note": f"the refresh token was refused at /oauth (HTTP {e.code})"}
    else:
        out["automation_grant"] = {"status": None, "note": "not asked: no refresh token was given"}
    if bearer:
        st, b, _ = http.call("POST", "/cloudapi/1.0.0/groups", bearer=bearer, body=body, accept=GROUPS_API, headers=tenant)
        out["automation_grant"] = {"status": st, "message": scrub(message(b)) if st >= 400 else ""}
        if st in (200, 201) and isinstance(b, dict) and b.get("id"):
            made.append(b["id"])
    print(f"  import under the automation grant:   {out['automation_grant'].get('status') or out['automation_grant'].get('note')}")

    st, b, _ = http.call("POST", "/cloudapi/1.0.0/groups", bearer=tok, body=body, accept=GROUPS_API, headers=tenant)
    out["session_login"] = {"status": st, "message": scrub(message(b)) if st >= 400 else ""}
    if st in (200, 201) and isinstance(b, dict) and b.get("id"):
        made.append(b["id"])
    print(f"  import under a session login:        HTTP {st}")

    for gid in dict.fromkeys(made):
        st, g, _ = http.call("GET", f"/cloudapi/1.0.0/groups/{gid}", bearer=tok, accept=CLOUDAPI, headers=tenant)
        st_u, users, _ = http.call("GET", f"/cloudapi/1.0.0/groups/{gid}/users", bearer=tok, accept=CLOUDAPI, headers=tenant)
        out["read_back"] = {"status": st, "providerType": (g or {}).get("providerType") if st == 200 else None,
                            "roles": [r.get("name") for r in ((g or {}).get("roleEntityRefs") or [])] if st == 200 else None,
                            "members_status": st_u,
                            "members": (users or {}).get("resultTotal") if st_u == 200 else None}
        st_d, b, _ = http.call("DELETE", f"/cloudapi/1.0.0/groups/{gid}", bearer=tok, accept=CLOUDAPI, headers=tenant)
        out["delete"] = {"status": st_d}
        print(f"  read back HTTP {st}, members {out['read_back']['members']}; deleted HTTP {st_d}")
    st, found, _ = http.call("GET", f"/cloudapi/1.0.0/groups?filter={q}", bearer=tok, accept=CLOUDAPI, headers=tenant)
    out["absent_after"] = st == 200 and not found.get("values")
    print(f"  absent afterwards: {out['absent_after']}")
    return out


# ---------------------------------------------------------------- G-126: what a project administrator may do to projects
def ssar(http, bearer, verb, name=None):
    attrs = {"group": "project.cci.vmware.com", "resource": "projects", "verb": verb}
    if name:
        attrs["name"] = name
    st, b, _ = http.call("POST", f"{CCI}/apis/authorization.k8s.io/v1/selfsubjectaccessreviews", bearer=bearer,
                         body={"apiVersion": "authorization.k8s.io/v1", "kind": "SelfSubjectAccessReview",
                               "spec": {"resourceAttributes": attrs}})
    return (b.get("status") or {}).get("allowed") if st == 201 and isinstance(b, dict) else f"HTTP {st}"


def bound_roles(http, bearer, project):
    st, rbs = items(http, f"/apis/{AUTHZ}/namespaces/{project}/projectrolebindings", bearer)
    if st != 200:
        raise RuntimeError(f"the bindings in a project answered HTTP {st}")
    roles = {}
    for rb in rbs:
        for s in rb.get("subjects") or []:
            if s.get("kind") == "User":
                roles[s.get("name")] = (rb.get("roleRef") or {}).get("name")
    return roles


def probe_project_scope(http, env, scrub):
    org, admin, t = env["org"], env["admin"], env["test"]
    otok, _ = http.session(admin["user"], org, admin["password"])
    project, foreign = env["project"], env["foreign"]
    if bound_roles(http, otok, project).get(t["admin"]) != "admin":
        raise Refused("the test administrator is not bound admin in PROJECT")
    if t["admin"] in bound_roles(http, otok, foreign):
        raise Refused("the test administrator is bound in FOREIGN_PROJECT; pick a project it does not belong to")
    st, before, _ = http.call("GET", f"{CCI}/apis/{PROJ}/projects/{foreign}", bearer=otok)
    if st != 200:
        raise RuntimeError(f"reading the foreign project answered HTTP {st}")
    tok, _ = http.session(t["admin"], org, t["password"])
    out = {"access_review": {"create any": ssar(http, tok, "create"),
                             "update the foreign project": ssar(http, tok, "update", foreign),
                             "delete the foreign project": ssar(http, tok, "delete", foreign)}}
    print(f"  access reviews as the project administrator: {out['access_review']}")
    name = f"{PREFIX}-{int(time.time())}"
    scrub.add(name, "throwaway-project")
    st, b, _ = http.call("POST", f"{CCI}/apis/{PROJ}/projects", bearer=tok,
                         body={"apiVersion": PROJ, "kind": "Project", "metadata": {"name": name},
                               "spec": {"description": f"{PREFIX}: created and removed by one run"}})
    out["create"] = {"status": st, "message": scrub(message(b)) if st >= 400 else ""}
    if st in (200, 201):
        st_d, _, _ = http.call("DELETE", f"{CCI}/apis/{PROJ}/projects/{name}", bearer=otok)
        out["create"]["deleted"] = st_d
        out["create"]["gone_after_s"] = wait_gone(http, f"/apis/{PROJ}/projects", otok, name)
    print(f"  project create:                      HTTP {st}")
    st, b, _ = http.call("PATCH", f"{CCI}/apis/{PROJ}/projects/{foreign}?dryRun=All", bearer=tok,
                         body={"spec": {"description": f"{PREFIX}: a dry run"}}, ctype="application/merge-patch+json")
    out["update_foreign_dry_run"] = {"status": st, "message": scrub(message(b)) if st >= 400 else ""}
    print(f"  update of the foreign project, dry:  HTTP {st}")
    st, b, _ = http.call("DELETE", f"{CCI}/apis/{PROJ}/projects/{foreign}?dryRun=All", bearer=tok)
    out["delete_foreign_dry_run"] = {"status": st, "message": scrub(message(b)) if st >= 400 else ""}
    print(f"  delete of the foreign project, dry:  HTTP {st}")
    st, after, _ = http.call("GET", f"{CCI}/apis/{PROJ}/projects/{foreign}", bearer=otok)
    rv = lambda o: (o.get("metadata") or {}).get("resourceVersion") if isinstance(o, dict) else None
    out["foreign_unchanged"] = st == 200 and rv(after) == rv(before)
    print(f"  the foreign project unchanged afterwards: {out['foreign_unchanged']}")
    return out


# ---------------------------------------------------------------- G-127 and the management ladder: a throwaway namespace
def probe_namespace(http, env, scrub):
    org, admin, t, project = env["org"], env["admin"], env["test"], env["project"]
    otok, _ = http.session(admin["user"], org, admin["password"])
    roles = bound_roles(http, otok, project)
    if roles.get(t["advanced"]) != "edit_adv" or roles.get(t["admin"]) != "admin":
        raise Refused("the test users' roles in PROJECT are not edit_adv and admin as VCFA_TEST_USERS orders them")
    path = f"/apis/{INFRA}/namespaces/{project}/supervisornamespaces"
    st, tmpl, _ = http.call("GET", f"{CCI}{path}/{env['template']}", bearer=otok)
    if st != 200:
        raise RuntimeError(f"reading the template namespace answered HTTP {st}")
    spec = tmpl.get("spec") or {}
    for key, label in (("className", "class"), ("regionName", "region"), ("vpcName", "vpc"), ("segName", "seg")):
        scrub.add(spec.get(key), label)
    for i, z in enumerate((spec.get("classConfigOverrides") or {}).get("zones") or []):
        scrub.add(z.get("name"), f"zone-{i + 1}")

    def create(bearer, stem):
        body = {"apiVersion": INFRA, "kind": "SupervisorNamespace",
                "metadata": {"generateName": f"{PREFIX}-{stem}-", "namespace": project},
                "spec": {k: spec.get(k) for k in ("className", "regionName", "vpcName", "segName", "classConfigOverrides")
                         if spec.get(k)}}
        body["spec"]["description"] = f"{PREFIX}: created and removed by one run"
        st, b, _ = http.call("POST", f"{CCI}{path}", bearer=bearer, body=body)
        name = (b.get("metadata") or {}).get("name") if st in (200, 201) and isinstance(b, dict) else None
        scrub.add(name, f"throwaway-namespace-{stem}")
        return st, b, name

    out, made = {}, []
    # The conditions a create meets, read before it: how many namespace classes are bound to the project, and
    # whether each creator can list the cluster's classes. A refusal is reported beside them, not explained by them.
    st, binds = items(http, f"/apis/infrastructure.cci.vmware.com/v1alpha1/namespaces/{project}/supervisornamespaceclassbindings", otok)
    dtok_read, _ = http.session(t["admin"], org, t["password"])
    classes = "/cci/kubernetes/apis/infrastructure.cci.vmware.com/v1alpha2/supervisornamespaceclasses"
    st_o, cls_o, _ = http.call("GET", classes, bearer=otok)
    st_a, _, _ = http.call("GET", classes, bearer=dtok_read)
    out["conditions"] = {"class_bindings_in_project": len(binds) if st == 200 else f"HTTP {st}",
                         "classes_listed_by_org_admin": len((cls_o or {}).get("items") or []) if st_o == 200 else f"HTTP {st_o}",
                         "class_list_as_project_admin": st_a}
    print(f"  conditions: {out['conditions']}")
    atok, _ = http.session(t["advanced"], org, t["password"])
    st, b, name = create(atok, "adv")
    out["create_as_edit_adv"] = {"status": st, "message": scrub(message(b)) if st >= 400 else ""}
    if name:
        made.append(name)
    print(f"  namespace create as edit_adv:        HTTP {st}")
    dtok, _ = http.session(t["admin"], org, t["password"])
    st, b, name = create(dtok, "admin")
    out["create_as_admin"] = {"status": st, "message": scrub(message(b)) if st >= 400 else ""}
    print(f"  namespace create as admin:           HTTP {st}")
    if not name:
        # The workload-plane half needs a namespace in the project, not this creator: both members reach any
        # namespace through the project. When the project administrator's create is refused, the organization
        # administrator makes the throwaway instead, and the record says so.
        st, b, name = create(otok, "org")
        out["create_as_org_admin"] = {"status": st, "message": scrub(message(b)) if st >= 400 else ""}
        print(f"  namespace create as the org admin:   HTTP {st}")
    if name:
        made.append(name)
        endpoint, began = None, time.time()
        for _ in range(48):
            st, ns, _ = http.call("GET", f"{CCI}{path}/{name}", bearer=otok)
            endpoint = ((ns or {}).get("status") or {}).get("namespaceEndpointURL") if st == 200 else None
            if endpoint:
                break
            time.sleep(10)
        out["endpoint_after_s"] = round(time.time() - began) if endpoint else None
        if endpoint:
            out["workload_plane"] = workload_plane(http, endpoint.rstrip("/"), name, t, org, scrub)
        else:
            print("  the namespace published no endpoint in eight minutes; the workload plane was not asked")
    for nm in made:
        http.call("DELETE", f"{CCI}{path}/{nm}", bearer=otok)
    out["teardown_s"] = {f"namespace {i + 1}": wait_gone(http, path, otok, nm) for i, nm in enumerate(made)}
    st, left = items(http, path, otok)
    out["residue"] = sum(1 for n in left if (n.get("metadata") or {}).get("name", "").startswith(PREFIX)) if st == 200 else None
    print(f"  teardown: {out['teardown_s']}; probe namespaces left in the project: {out['residue']}")
    return out


def workload_plane(http, ep, ns, t, org, scrub):
    toks = {who: http.session(t[who], org, t["password"])[0] for who in ("member", "advanced", "admin")}
    cm = lambda who: f"{PREFIX}-{who}"
    base = f"{ep}/api/v1/namespaces/{ns}/configmaps"
    res = {}
    # A new namespace's grants settle after its endpoint appears; until the administrator can read, a refusal
    # would measure propagation, not the role. Wait for that read before asking anything else.
    began = time.time()
    for _ in range(18):
        if http.call("GET", base, bearer=toks["admin"])[0] == 200:
            break
        time.sleep(10)
    res["admin can read after_s"] = round(time.time() - began)
    for who in ("advanced", "admin"):
        st, b, _ = http.call("POST", base, bearer=toks[who], body={"apiVersion": "v1", "kind": "ConfigMap",
                             "metadata": {"name": cm(who)}, "data": {"made-by": who}})
        res[f"{who} creates its own"] = st
    for who, other in (("advanced", "admin"), ("admin", "advanced")):
        st, b, _ = http.call("PATCH", f"{base}/{cm(other)}", bearer=toks[who], body={"data": {"edited-by": who}},
                             ctype="application/merge-patch+json")
        res[f"{who} edits the {other}'s"] = st
    st, b, _ = http.call("GET", base, bearer=toks["member"])
    res["member lists them"] = st
    for who, other in (("advanced", "admin"), ("admin", "advanced")):
        st, b, _ = http.call("DELETE", f"{base}/{cm(other)}", bearer=toks[who])
        res[f"{who} deletes the {other}'s"] = st
    for who in ("advanced", "admin"):
        st, _, _ = http.call("GET", f"{base}/{cm(who)}", bearer=toks["admin"])
        res[f"the {who}'s afterwards"] = st
    for k, v in res.items():
        print(f"    {k:<34} {v} s" if k.endswith("after_s") else f"    {k:<34} HTTP {v}")
    return res


def write_record(path, rec, scrub, secrets):
    text = json.dumps(rec, indent=1)
    leaked = [k for k in scrub.known if k and re.search(r"(?<![\w.-])" + re.escape(k) + r"(?![\w.-])", text)]
    if leaked or any(s and s in text for s in secrets):
        raise SystemExit("FATAL: an estate value reached the record; not writing it")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(f"\n  wrote {path} (statuses, counts and scrubbed messages)")


def main():
    argv = sys.argv[1:]
    group = None
    if "--probe-import" in argv:
        i = argv.index("--probe-import")
        if i + 1 >= len(argv) or argv[i + 1].startswith("--"):
            print("usage: --probe-import GROUP", file=sys.stderr)
            sys.exit(5)
        group = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    unknown = [a for a in argv if a not in FLAGS]
    if unknown:
        print(f"reprobe.py: unknown option {unknown[0]}; it takes {', '.join(sorted(FLAGS))}", file=sys.stderr)
        sys.exit(5)
    if not (group or argv):
        print("reprobe.py: name at least one probe; with none it does nothing", file=sys.stderr)
        sys.exit(5)
    try:
        host, org = os.environ["VCFA_HOST"], os.environ["VCFA_ORG"]
        users = [u.strip() for u in os.environ.get("VCFA_TEST_USERS", "").split(",") if u.strip()]
        env = {"org": org, "project": os.environ.get("PROJECT"), "foreign": os.environ.get("FOREIGN_PROJECT"),
               "template": os.environ.get("TEMPLATE_NAMESPACE"),
               "admin": {"user": os.environ["VCFA_USER"], "password": read_secret("VCFA_PASSWORD_FILE")}}
        if group and os.environ.get("VCFA_REFRESH_TOKEN_FILE"):
            env["refresh"] = read_secret("VCFA_REFRESH_TOKEN_FILE")
        if "--probe-project-scope" in argv or "--probe-namespace" in argv:
            if len(users) != 3 or not env["project"]:
                raise Refused("VCFA_TEST_USERS (member,advanced,admin) and PROJECT are required")
            env["test"] = dict(zip(("member", "advanced", "admin"), users), password=read_secret("VCFA_TEST_PASSWORD_FILE"))
        if "--probe-project-scope" in argv and not env["foreign"]:
            raise Refused("FOREIGN_PROJECT is required for --probe-project-scope")
        if "--probe-namespace" in argv and not env["template"]:
            raise Refused("TEMPLATE_NAMESPACE is required for --probe-namespace")
    except KeyError as e:
        print(f"reprobe.py: {e.args[0]} is not set", file=sys.stderr)
        sys.exit(5)
    except Refused as e:
        print(f"reprobe.py: {e}; nothing was written", file=sys.stderr)
        sys.exit(2)

    http, scrub = Http(host), Scrub()
    for real, label in ((host, "host"), (org, "org"), (env["project"], "project"), (env["foreign"], "foreign-project"),
                        (env["template"], "template-namespace"), (env["admin"]["user"], "org-admin")):
        scrub.add(real, label)
    for role, user in (env.get("test") or {}).items():
        if role != "password":
            scrub.add(user, f"test-{role}")
    rec = {"captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    print("reprobe.py: each write on a throwaway, read back, removed\n")
    try:
        if group:
            print("G-094, the group import:")
            rec["import"] = probe_import(http, env, scrub, group)
        if "--probe-project-scope" in argv:
            print("\nG-126, a project administrator and projects:")
            rec["project_scope"] = probe_project_scope(http, env, scrub)
        if "--probe-namespace" in argv:
            print("\nG-127 and the management ladder, in a throwaway namespace:")
            rec["namespace"] = probe_namespace(http, env, scrub)
    except Refused as e:
        print(f"reprobe.py: {e}; nothing was written", file=sys.stderr)
        sys.exit(2)
    except (RuntimeError, urllib.error.URLError, OSError) as e:
        print(f"reprobe.py: a call failed: {scrub(str(e))}", file=sys.stderr)
        sys.exit(3)
    secrets = [env["admin"]["password"], env.get("refresh"), (env.get("test") or {}).get("password")]
    write_record(os.environ.get("OUT", "reprobe.json"), rec, scrub, secrets)


if __name__ == "__main__":
    try:
        main()
    except (PermissionError, FileNotFoundError) as e:   # a credential file missing or open to group or other
        print(f"reprobe.py: {e}", file=sys.stderr)
        sys.exit(5)
    except (urllib.error.URLError, OSError) as e:
        print(f"reprobe.py: a call failed: {type(e).__name__}", file=sys.stderr)
        sys.exit(3)
