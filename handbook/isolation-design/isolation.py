#!/usr/bin/env python3
"""isolation.py: the assembled isolation design, checked against the platform rather than described.

The design this chapter assembles is five settings and no per-user objects. Every one of those settings is
readable, and most of them are checkable, so this asks:

  1. the ROLES: the project roles the platform publishes, with the description each ships. The set is small and
     closed, which is what makes a tenancy model expressible in it at all;
  2. the BINDINGS: every project role binding that exists, and the naming rule derived from them. The rule is
     strict, the platform's error message about it is misleading, and a manifest that gets it wrong is refused;
  3. the REVIEW SURFACE: the four access-review kinds the interface declares, and which of them actually answer
     this identity. This decides whether an isolation matrix can be computed from one seat or has to be gathered
     by authenticating as each principal;
  4. the SELF RULES: what this identity may do in a project, exhaustively, as the platform computes it;
  5. the VISIBILITY FLOOR: how many deployments this identity sees and how many of them it owns. Isolation is a
     property of principals below the organization-administrator role, and this is what that looks like from
     above it;
  6. the SILENT NO-OP: the REST project membership arrays accept a write, answer 200, and persist nothing. This
     sends one and reads it back, restoring anything that did persist;
  7. with --probe-writes, the NAMING RULE proved: bindings created under each candidate name shape against a
     principal that exists in no identity provider, so the platform answers on format alone, and deleted again.

Without --probe-writes the only write is the membership-array no-op in step 6, which is restored either way.
Organization-specific names are replaced by stable placeholders and the script refuses to write a record in
which one survived. Field names, verbs, HTTP statuses and the platform's own error strings are kept.

Run:
  export VCFA_HOST=<automation-fqdn> VCFA_ORG=<org>
  export VCFA_REFRESH_TOKEN_FILE=/path/to/refresh-token    # mode 0600
  export TLS_VERIFY=false                                  # only on a self-signed lab CA
  python3 isolation.py
  python3 isolation.py --probe-writes
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
AUTHZ = "authorization.cci.vmware.com/v1alpha1"
K8SAUTHZ = "authorization.k8s.io/v1"
PROJ = "project.cci.vmware.com/v1alpha2"


def ctx():
    verify = os.environ.get("TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")
    return ssl.create_default_context() if verify else ssl._create_unverified_context()


class Labels:
    """Estate names become placeholders. The product's own vocabulary never does.

    A principal can be called exactly what a product object is called. On this estate a user is named ``admin``
    and so is a project role, and registering the user taught the scrubber to replace every standalone
    ``admin`` in the record, including the role. The record then published a role named ``{{user-3}}``.

    So the scrubber holds a RESERVED set, filled from what the platform itself publishes (role names, verbs,
    kinds) plus the generic account names that collide with them. A name in that set is not registered and not
    replaced: it is the product's word, it identifies no estate, and blanking it destroys the record's meaning.
    """

    RESERVED = {"admin", "view", "edit", "user", "users", "group", "groups", "owner", "auditor", "auditors",
                "administrator", "administrators", "default", "system", "none", "all"}

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
        # Longest first so a contained name cannot corrupt a longer one, and on a WORD BOUNDARY so a short
        # name is not replaced inside an unrelated word. A principal really can be called "admin", and a naive
        # replace turns the field name "administrators" into "{{user-3}}istrators". The leak check below uses
        # the same boundary, so what the scrub replaces and what the check looks for are one rule.
        for real, label in sorted(known, key=lambda kv: -len(kv[0])):
            text = re.sub(r"(?<![A-Za-z0-9-])" + re.escape(real) + r"(?![A-Za-z0-9-])",
                          "{{%s}}" % label, text)
        return UUID.sub("{{id}}", text)


class Vcfa:
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
        return self._send(method, f"https://{self.host}{CCI}{path}", body)

    def api(self, method, path, body=None):
        return self._send(method, f"https://{self.host}{path}", body)

    def items(self, group, resource, project=None):
        p = f"/apis/{group}/namespaces/{project}/{resource}" if project else f"/apis/{group}/{resource}"
        st, body = self.k8s("GET", p)
        return st, ((body.get("items") or []) if st == 200 and isinstance(body, dict) else [])


def msg(r):
    if isinstance(r, dict):
        return r.get("message") or ""
    return str(r or "")


def probe_writes(c, L, project):
    """Prove the binding naming rule instead of quoting it.

    Every candidate names a principal that exists in no identity provider, so a create that gets past the format
    check fails on identity rather than granting anything. That is the signal: *format accepted* is the answer
    'the platform validated the name and moved on', and it is the only way to tell a correct name from a wrong
    one without binding a real person to a real project.
    """
    base = {"apiVersion": AUTHZ, "kind": "ProjectRoleBinding",
            "roleRef": {"apiGroup": "authorization.cci.vmware.com", "kind": "ProjectRole", "name": "view"}}
    cases = [
        ("name = cci:user:<subject>, exactly", "cci:user:ProbeNoSuchUser", "User", "ProbeNoSuchUser"),
        ("name = cci:group:<subject minus its trailing @>", "cci:group:ProbeNoSuchGroup", "Group", "ProbeNoSuchGroup@"),
        ("name keeps the group's trailing @", "cci:group:ProbeNoSuchGroup@", "Group", "ProbeNoSuchGroup@"),
        ("name lowercased, subject mixed case", "cci:group:probenosuchgroup", "Group", "ProbeNoSuchGroup@"),
        ("name has the four segments the error advertises", "cci:group:example.invalid:ProbeNoSuchGroup",
         "Group", "ProbeNoSuchGroup@"),
    ]
    out, made = [], []
    print("\n  the naming rule, proved against a principal that exists nowhere")
    for label, name, kind, subject in cases:
        body = dict(base, metadata={"name": name, "namespace": project},
                    subjects=[{"kind": kind, "name": subject}])
        st, r = c.k8s("POST", f"/apis/{AUTHZ}/namespaces/{project}/projectrolebindings", body)
        m = msg(r)
        verdict = ("created" if st in (200, 201)
                   else "format accepted, refused later because the principal is in no identity provider"
                   if "not present in the Iden" in m
                   else "format refused")
        out.append({"case": label, "nameShape": name.replace("ProbeNoSuchUser", "<subject>").replace("ProbeNoSuchGroup", "<subject>").replace("probenosuchgroup", "<subject lowercased>"),
                    "status": st, "verdict": verdict, "message": L.scrub(m)})
        print(f"     {label:<48} HTTP {st}  {verdict}")
        if st in (200, 201):
            made.append(name)

    # a client-side apply writes this annotation; CCI admission refuses it outright
    ann = dict(base, metadata={"name": "cci:user:ProbeNoSuchUser", "namespace": project,
                               "annotations": {"kubectl.kubernetes.io/last-applied-configuration": "{}"}},
               subjects=[{"kind": "User", "name": "ProbeNoSuchUser"}])
    st, r = c.k8s("POST", f"/apis/{AUTHZ}/namespaces/{project}/projectrolebindings", ann)
    out.append({"case": "the annotation a client-side apply writes", "nameShape": "cci:user:<subject>",
                "status": st, "verdict": "format refused" if st >= 400 else "created", "message": L.scrub(msg(r))})
    print(f"     {'the annotation a client-side apply writes':<48} HTTP {st}  {msg(r)[:60]}")
    if st in (200, 201):
        made.append("cci:user:ProbeNoSuchUser")

    for name in made:
        c.k8s("DELETE", f"/apis/{AUTHZ}/namespaces/{project}/projectrolebindings/{urllib.parse.quote(name, safe='')}")
    st, left = c.items(AUTHZ, "projectrolebindings", project)
    residue = [b["metadata"]["name"] for b in left if "probe" in b["metadata"]["name"].lower()]
    print(f"     {'cleanup':<48} {len(made)} created, {len(residue)} left behind")
    if residue:
        print("     WARNING: a probe binding is still present; remove it before trusting the list above.")
    return {"cases": out, "created": len(made), "residue": residue}


def main():
    host, org = os.environ["VCFA_HOST"], os.environ["VCFA_ORG"]
    refresh = open(os.environ["VCFA_REFRESH_TOKEN_FILE"], encoding="utf-8").read().strip()
    out_dir = os.environ.get("OUT_DIR", ".")
    c = Vcfa(host, org, refresh)
    L = Labels()
    print("isolation.py: the assembled design, checked rather than described\n")

    st, projects = c.k8s("GET", f"/apis/{PROJ}/projects")
    projects = [p["metadata"]["name"] for p in ((projects.get("items") or []) if st == 200 else [])]
    for p in projects:
        L.get("project", p)
    if not projects:
        raise SystemExit("no project is visible to this identity")
    home = projects[0]

    # ---- 1. the roles, and the description each ships
    st, roles = c.items(AUTHZ, "projectroles")
    L.reserve(*(r["metadata"]["name"] for r in roles))   # a role name is vocabulary, never an estate name
    role_rows = [{"name": r["metadata"]["name"],
                  "description": ((r.get("spec") or {}).get("description") or ""),
                  "carriesRules": bool(r.get("rules") or (r.get("spec") or {}).get("rules"))}
                 for r in roles]
    desc = collections.Counter(r["description"] for r in role_rows)
    shared = sorted({r["name"] for r in role_rows if desc[r["description"]] > 1})
    print(f"  roles: {len(role_rows)} project role(s), cluster-scoped and read-only")
    for r in role_rows:
        print(f"     {r['name']:<10} carries its rules: {r['carriesRules']}   \"{r['description']}\"")
    if shared:
        print(f"     NOTE: {' and '.join(shared)} ship the identical description, so the object cannot tell them apart")

    # ---- 2. the bindings that exist, and the rule they follow
    bindings, rule_holds = [], []
    for p in projects:
        st, bs = c.items(AUTHZ, "projectrolebindings", p)
        for b in bs:
            name = b["metadata"]["name"]
            sub = (b.get("subjects") or [{}])[0]
            sname, skind = str(sub.get("name") or ""), str(sub.get("kind") or "")
            seg = name.split(":", 2)
            third = seg[2] if len(seg) > 2 else ""
            expect = sname[:-1] if sname.endswith("@") else sname
            rule_holds.append(len(seg) == 3 and seg[0] == "cci" and seg[1] == skind.lower() and third == expect)
            for fam, v in (("group" if skind == "Group" else "user", sname),):
                L.get(fam, v)
            bindings.append({"project": L.scrub(p), "role": (b.get("roleRef") or {}).get("name"),
                             "subjectKind": skind, "subjectEndsWithAt": sname.endswith("@"),
                             "nameSegments": len(seg), "nameFollowsRule": rule_holds[-1]})
    print(f"\n  bindings: {len(bindings)} across {len(projects)} project(s); "
          f"every name is cci:<kind>:<subject minus a trailing @>: {all(rule_holds) if rule_holds else 'n/a'}")
    byrole = collections.Counter(b["role"] for b in bindings)
    print(f"     by role: {dict(byrole)}; group subjects carry a trailing @: "
          f"{all(b['subjectEndsWithAt'] for b in bindings if b['subjectKind'] == 'Group')}")

    # ---- 3. which access reviews actually answer
    st, rl = c.k8s("GET", f"/apis/{K8SAUTHZ}")
    declared = sorted(r["name"] for r in (rl.get("resources") or []))
    review = []
    probes = [
        ("selfsubjectrulesreviews", {"spec": {"namespace": home}}, None),
        ("selfsubjectaccessreviews",
         {"spec": {"resourceAttributes": {"namespace": home, "group": "catalog.cci.vmware.com",
                                          "resource": "instances", "verb": "create"}}}, None),
        ("subjectaccessreviews",
         {"spec": {"user": "someone-else", "resourceAttributes": {"namespace": home,
                                                                  "group": "catalog.cci.vmware.com",
                                                                  "resource": "instances", "verb": "create"}}}, None),
        ("localsubjectaccessreviews",
         {"spec": {"user": "someone-else", "resourceAttributes": {"namespace": home,
                                                                  "group": "catalog.cci.vmware.com",
                                                                  "resource": "instances", "verb": "create"}}}, home),
    ]
    print(f"\n  access reviews: the interface declares {len(declared)} -> {declared}")
    self_rules = None
    for res, body, ns in probes:
        kind = "".join(w.capitalize() for w in
                       res[:-1].replace("selfsubject", "self-subject-").replace("localsubject", "local-subject-")
                       .replace("accessreview", "access-review").replace("rulesreview", "rules-review").split("-"))
        payload = dict(body, apiVersion=K8SAUTHZ, kind=kind)
        path = (f"/apis/{K8SAUTHZ}/namespaces/{ns}/{res}" if ns else f"/apis/{K8SAUTHZ}/{res}")
        st, r = c.k8s("POST", path, payload)
        answered = st in (200, 201) and isinstance(r, dict) and isinstance(r.get("status"), dict)
        for who in re.findall(r'User "([^"]+)"', msg(r)):
            L.get("user", who)
        review.append({"kind": res, "status": st, "answers": answered,
                       "asksAbout": "itself" if res.startswith("self") else "another principal",
                       "message": L.scrub(msg(r))[:160] if not answered else ""})
        print(f"     {res:<28} about {'itself' if res.startswith('self') else 'another principal':<18} "
              f"HTTP {st}  {'answers' if answered else 'refused'}")
        if answered and res == "selfsubjectrulesreviews":
            self_rules = r["status"]

    # ---- 4. what this identity may do, as the platform computes it
    rules_summary = None
    if self_rules:
        rules = self_rules.get("resourceRules") or []
        bygroup = collections.Counter()
        for rr in rules:
            for g in (rr.get("apiGroups") or ["core"]):
                bygroup[g or "core"] += len(rr.get("resources") or [])
        rules_summary = {"rules": len(rules), "incomplete": bool(self_rules.get("incomplete")),
                         "byGroup": dict(bygroup.most_common(10))}
        print(f"\n  self rules: {len(rules)} rule(s), incomplete={self_rules.get('incomplete')}; "
              f"widest group is {bygroup.most_common(1)[0][0]} with {bygroup.most_common(1)[0][1]} resource grants")

    # ---- 5. the visibility floor
    st, dep = c.api("GET", "/deployment/api/deployments?size=200")
    deps = (dep.get("content") or []) if st == 200 and isinstance(dep, dict) else []
    owners = collections.Counter(d.get("ownedBy") for d in deps)
    for o in owners:
        L.get("user", str(o))
    me = collections.Counter(d.get("ownedBy") for d in deps).most_common(1)
    visibility = {"deploymentsVisible": len(deps), "distinctOwners": len(owners),
                  "projectsSpanned": len({d.get("projectId") for d in deps}),
                  "largestOwnerShare": me[0][1] if me else 0}
    print(f"\n  visibility floor: this identity sees {len(deps)} deployment(s) owned by {len(owners)} distinct "
          f"principal(s). Isolation is a property of principals below this role, not of the platform")

    # ---- 6. the silent no-op on the REST membership arrays
    ARRAYS = ("administrators", "users", "auditors", "advancedUsers")
    noop = None
    st, rp = c.api("GET", "/project-service/api/projects?size=50")
    content = (rp.get("content") or []) if st == 200 and isinstance(rp, dict) else []
    if content:
        p0 = content[0]
        before = {k: list(p0.get(k) or []) for k in ARRAYS}
        probe = "probe-isolation-nonexistent@example.invalid"
        st_p, rq = c.api("PATCH", f"/project-service/api/projects/{p0['id']}",
                         {"auditors": before["auditors"] + [{"email": probe, "type": "user"}]})
        time.sleep(4)
        st_g, rg = c.api("GET", f"/project-service/api/projects/{p0['id']}")
        after = {k: list((rg or {}).get(k) or []) for k in ARRAYS}
        persisted = probe in json.dumps(after)
        noop = {"patchStatus": st_p, "persisted": persisted,
                "lengthsBefore": {k: len(v) for k, v in before.items()},
                "lengthsAfter": {k: len(v) for k, v in after.items()}}
        print(f"\n  the membership arrays: PATCH answered HTTP {st_p} and persisted: {persisted}")
        if persisted:
            c.api("PATCH", f"/project-service/api/projects/{p0['id']}", {"auditors": before["auditors"]})
            st_g2, rg2 = c.api("GET", f"/project-service/api/projects/{p0['id']}")
            noop["restored"] = {k: len(list((rg2 or {}).get(k) or [])) for k in ARRAYS} == noop["lengthsBefore"]
            print(f"     it persisted, so it was restored: {noop['restored']}")
        else:
            print("     a write that answers success and changes nothing is the read-only projection to avoid")

    # ---- 7. the naming rule, proved
    naming = probe_writes(c, L, home) if "--probe-writes" in sys.argv else None
    if naming is None:
        print("\n  naming rule: not probed; pass --probe-writes to have the platform judge each name shape "
              "(it binds a principal that exists nowhere, then deletes)")

    payload = {"captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "roles": role_rows, "rolesSharingADescription": shared,
               "bindings": bindings, "bindingNameRuleHolds": all(rule_holds) if rule_holds else None,
               "reviewKinds": review, "selfRules": rules_summary, "visibility": visibility,
               "membershipArrays": noop, "naming": naming}
    # Scrub the WHOLE serialized record, not field by field. A name registered anywhere can surface in a
    # message written by the platform (an authorization refusal quotes the calling user), and a per-field
    # scrub only reaches the fields you remembered to pass through it.
    text = L.scrub(UUID.sub("{{id}}", json.dumps(payload, indent=1, ensure_ascii=False)))
    for secret in (c.bearer, refresh, host, org):
        assert secret not in text, "an estate value reached the record"
    # The scrub can fail the other way too: over-match and blank a word the product owns. A page-level check
    # cannot tell that from a sanitized name shown on purpose, but here the vocabulary is known, so assert it
    # survived. This is the check that would have caught a role rendered as {{user-3}}.
    for word in sorted(r["name"] for r in role_rows):
        assert re.search(r"(?<![A-Za-z0-9-])" + re.escape(word) + r"(?![A-Za-z0-9-])", text), (
            f"the scrub replaced the project role {word!r}, which is the product's word and not an estate name; "
            f"add it to Labels.RESERVED")
    bare = re.sub(r"\{\{[^}]*\}\}", "", text)
    for fam, m in L.maps.items():
        for nm in m:
            if nm and re.search(r"(?<![A-Za-z0-9-])" + re.escape(nm) + r"(?![A-Za-z0-9-])", bare):
                shape = re.sub(r"[A-Za-z]", "a", re.sub(r"[0-9]", "9", nm))
                raise SystemExit(f"FATAL: a {fam} name ({len(nm)} characters, shape {shape}) reached the record")
    os.makedirs(out_dir, exist_ok=True)
    open(os.path.join(out_dir, "isolation.json"), "w", encoding="utf-8").write(text + "\n")
    print(f"\nwrote isolation.json ({len(role_rows)} roles, {len(bindings)} bindings, "
          f"{sum(1 for r in review if r['answers'])} of {len(review)} access reviews answering); "
          f"every organization name replaced by a placeholder")


if __name__ == "__main__":
    main()
