#!/usr/bin/env python3
"""elevation.py: what a VCF Automation 9.1 organization can and cannot time-box, asked rather than assumed.

Temporary elevation is a design built on top of a platform that has no primitive for it. That claim is the
whole reason the design exists, so this checks it instead of repeating it:

  1. the TIME-BOX INVENTORY: every policy type the plane declares, with whether its schema carries any
     time-bounded field at all, and the complete field list of the objects that grant access. A lease does
     exist on this platform. It bounds a deployment's life, not a person's reach, and the difference is the
     chapter;
  2. the ACCESS OBJECTS: what a ProjectRoleBinding and a ProjectRole actually carry, field by field, so
     "there is nowhere to put an expiry" is an enumeration rather than an impression;
  3. the SCOPE-AXIS MECHANISM (with --probe-elevation NAME): whether a binding's role can be changed in
     place and changed back, which decides whether a guaranteed revert is possible at all. This ELEVATES A
     REAL BINDING for a few seconds and puts it back. It refuses to run without a binding named explicitly,
     captures the prior role, restores it, and verifies the restore with a direct read of the object rather
     than a listing;
  4. the REHEARSAL CHECK, in the same pass: whether this plane honours a server-side dry run. It does not,
     and it does not refuse one either, which is the most expensive fact in this chapter.

Without --probe-elevation nothing here writes.

Run:
  export VCFA_HOST=<automation-fqdn> VCFA_ORG=<org>
  export VCFA_REFRESH_TOKEN_FILE=/path/to/refresh-token    # mode 0600
  export TLS_VERIFY=false                                  # only on a self-signed lab CA
  python3 elevation.py
  python3 elevation.py --probe-elevation cci:group:SomeTestGroup   # elevates that binding and reverts it
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
AUTHZ = "authorization.cci.vmware.com/v1alpha1"
PROJ = "project.cci.vmware.com/v1alpha2"
TIMEISH = re.compile(r"(?i)expir|ttl|lease|until|duration|deadline|grace|valid")


def ctx():
    verify = os.environ.get("TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")
    return ssl.create_default_context() if verify else ssl._create_unverified_context()


class Labels:
    """Estate names become placeholders. The product's own vocabulary never does."""

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

    def _send(self, method, url, body=None, ctype=None):
        headers = {"Authorization": f"Bearer {self.bearer}", "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = ctype or "application/json"
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

    def k8s(self, method, path, body=None, ctype=None):
        return self._send(method, f"https://{self.host}{CCI}{path}", body, ctype)

    def api(self, method, path, body=None):
        return self._send(method, f"https://{self.host}{path}", body)

    def items(self, group, resource, project=None):
        p = f"/apis/{group}/namespaces/{project}/{resource}" if project else f"/apis/{group}/{resource}"
        st, body = self.k8s("GET", p)
        return st, ((body.get("items") or []) if st == 200 and isinstance(body, dict) else [])


def msg(r):
    return (r.get("message") or "") if isinstance(r, dict) else str(r or "")


def probe_elevation(c, L, project, target):
    """Elevate one named binding, read it back, revert it, and verify the revert with a direct read.

    This writes to a live access object, which is why it takes the binding's name as an argument rather than
    choosing one: the operator decides what may be elevated for a few seconds, not this script. It also
    answers the rehearsal question in the same pass, because the only way to find out whether a dry run is
    honoured is to send one and look at the object afterwards.

    The revert is verified by a direct GET of the object. A listing is not good enough: on this plane a
    listing was observed serving a stale value while a direct read of the same object showed the change.
    """
    enc = urllib.parse.quote(target, safe="")
    st, before = c.k8s("GET", f"/apis/{AUTHZ}/namespaces/{project}/projectrolebindings/{enc}")
    if st != 200:
        print(f"\n  elevation: no binding named as given in this project (HTTP {st}); nothing attempted")
        return None
    base_role = (before.get("roleRef") or {}).get("name")
    st, roles = c.items(AUTHZ, "projectroles")
    ladder = [r["metadata"]["name"] for r in roles]
    higher = next((r for r in ("edit_adv", "admin") if r in ladder and r != base_role), None)
    if not higher:
        print(f"\n  elevation: binding already at {base_role!r}, nothing higher to move to; skipped")
        return None

    def role_now():
        s, g = c.k8s("GET", f"/apis/{AUTHZ}/namespaces/{project}/projectrolebindings/{enc}")
        return ((g.get("roleRef") or {}).get("name") if s == 200 else None), g

    def put(role, query=""):
        s, g = role_now()
        body = {"apiVersion": AUTHZ, "kind": "ProjectRoleBinding",
                "metadata": {"name": target, "namespace": project},
                "roleRef": dict(g["roleRef"], name=role), "subjects": g["subjects"]}
        return c.k8s("PATCH", f"/apis/{AUTHZ}/namespaces/{project}/projectrolebindings/{enc}"
                     f"?fieldManager=elevation-probe&force=true{query}", body,
                     "application/apply-patch+yaml")

    out = {"baseRole": base_role, "elevatedTo": higher, "steps": []}
    print(f"\n  elevation: moving one named binding {base_role!r} -> {higher!r} and back")

    # 1. the rehearsal that is not one
    st_d, r_d = put(higher, "&dryRun=All")
    seen, _ = role_now()
    out["steps"].append({"step": "server-side apply carrying dryRun=All", "status": st_d,
                         "roleAfter": seen, "rehearsed": seen == base_role})
    print(f"     apply with ?dryRun=All      HTTP {st_d}  role now {seen!r}  -> "
          f"{'rehearsed, nothing changed' if seen == base_role else 'THE DRY RUN APPLIED THE CHANGE'}")

    # 2. the elevation proper (a no-op if the dry run already did it)
    st_u, r_u = put(higher)
    seen, _ = role_now()
    out["steps"].append({"step": "elevate", "status": st_u, "roleAfter": seen, "took": seen == higher})
    print(f"     elevate                     HTTP {st_u}  role now {seen!r}")

    # 3. the revert, and a direct read to prove it
    st_r, r_r = put(base_role)
    time.sleep(3)
    seen, _ = role_now()
    out["steps"].append({"step": "revert", "status": st_r, "roleAfter": seen, "restored": seen == base_role})
    print(f"     revert                      HTTP {st_r}  role now {seen!r}  -> "
          f"{'restored' if seen == base_role else 'NOT RESTORED'}")
    out["restored"] = seen == base_role
    out["inPlaceMutable"] = bool(out["steps"][1]["took"] and out["steps"][2]["restored"])
    if not out["restored"]:
        print(f"     WARNING: the binding is at {seen!r} and was {base_role!r}. Put it back before doing "
              f"anything else.")
    return out


def main():
    host, org = os.environ["VCFA_HOST"], os.environ["VCFA_ORG"]
    refresh = open(os.environ["VCFA_REFRESH_TOKEN_FILE"], encoding="utf-8").read().strip()
    out_dir = os.environ.get("OUT_DIR", ".")
    c = Vcfa(host, org, refresh)
    L = Labels()
    print("elevation.py: what this platform can and cannot time-box\n")

    st, projects = c.k8s("GET", f"/apis/{PROJ}/projects")
    projects = [p["metadata"]["name"] for p in ((projects.get("items") or []) if st == 200 else [])]
    for p in projects:
        L.get("project", p)
    if not projects:
        raise SystemExit("no project is visible to this identity")
    home = projects[0]

    # ---- 1. the time-box inventory
    st, pt = c.api("GET", "/policy/api/policyTypes?size=100")
    ptypes = (pt.get("content") or []) if isinstance(pt, dict) else []
    types = []
    for t in ptypes:
        tid = t.get("id")
        st2, full = c.api("GET", f"/policy/api/policyTypes/{tid}")
        blob = json.dumps((full or {}).get("schema") or {})
        fields = sorted(set(re.findall(r'"([A-Za-z][A-Za-z0-9_]*)"\s*:\s*\{', blob)))
        # Name what each type governs from its own id rather than bucketing the ones we did not anticipate
        # into "other": a published table that says "other" twice is a table that stopped reading.
        tail = str(tid).replace("com.vmware.policy.", "")
        governs = {"deployment.action": "what a principal may do to a deployment",
                   "deployment.lease": "how long a deployment lives",
                   "approval": "whether a request needs a human",
                   "supervisor.iaas": "what the supervisor plane will accept"}.get(tail, tail)
        types.append({"id": tid, "timeBoundedFields": [f for f in fields if TIMEISH.search(f)],
                      "governs": governs})
    print(f"  policy types: {len(types)} declared")
    for t in types:
        print(f"     {str(t['id']):<46} time-bounded fields: {t['timeBoundedFields'] or 'none'}")

    # ---- 2. the access objects, field by field
    st, rb = c.items(AUTHZ, "projectrolebindings", home)
    st, roles = c.items(AUTHZ, "projectroles")
    L.reserve(*(r["metadata"]["name"] for r in roles))
    binding_fields = sorted({k for b in rb for k in b if k not in ("apiVersion", "kind")})
    meta_fields = sorted({k for b in rb for k in (b.get("metadata") or {})})
    role_fields = sorted({k for r in roles for k in r if k not in ("apiVersion", "kind")})
    access = {"projectRoleBindingFields": binding_fields, "projectRoleBindingMetadataFields": meta_fields,
              "projectRoleFields": role_fields,
              "anyExpiryField": sorted(f for f in binding_fields + meta_fields + role_fields if TIMEISH.search(f)),
              "bindings": len(rb), "roles": [r["metadata"]["name"] for r in roles]}
    print(f"\n  a ProjectRoleBinding carries {binding_fields}, whose metadata carries {meta_fields}")
    print(f"  a ProjectRole carries {role_fields}")
    print(f"  fields on any of them that could hold a time bound: {access['anyExpiryField'] or 'NONE'}")

    # ---- 3. where a lease does exist
    st, dep = c.api("GET", "/deployment/api/deployments?size=5")
    d = ((dep.get("content") or [{}])[0]) if isinstance(dep, dict) else {}
    lease_fields = sorted(k for k in d if TIMEISH.search(k))
    print(f"\n  a deployment carries {lease_fields or 'no time-bounded field'}, so this platform can time-box "
          f"a THING and not a PERSON")

    # ---- 4. the elevation mechanism
    elevation = None
    flag = "--probe-elevation"
    if flag in sys.argv:
        i = sys.argv.index(flag)
        target = sys.argv[i + 1] if len(sys.argv) > i + 1 else None
        if not target:
            raise SystemExit(f"{flag} needs the name of the binding to elevate, for example "
                             f"{flag} cci:group:SomeTestGroup. This script will not choose one for you.")
        elevation = probe_elevation(c, L, home, target)
    else:
        print(f"\n  elevation: not probed. Pass {flag} <binding name> to move ONE binding up a role and back, "
              f"which is the only way to learn whether a revert is possible. It writes to a live access "
              f"object, so it takes the name from you.")

    payload = {"captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "policyTypes": types, "access": access, "deploymentLeaseFields": lease_fields,
               "elevation": elevation}
    text = L.scrub(UUID.sub("{{id}}", json.dumps(payload, indent=1, ensure_ascii=False)))
    for secret in (c.bearer, refresh, host, org):
        assert secret not in text, "an estate value reached the record"
    for word in sorted(access["roles"]):
        assert re.search(r"(?<![A-Za-z0-9-])" + re.escape(word) + r"(?![A-Za-z0-9-])", text), (
            f"the scrub replaced the project role {word!r}, which is the product's word; add it to RESERVED")
    bare = re.sub(r"\{\{[^}]*\}\}", "", text)
    for fam, m in L.maps.items():
        for nm in m:
            if nm and re.search(r"(?<![A-Za-z0-9-])" + re.escape(nm) + r"(?![A-Za-z0-9-])", bare):
                shape = re.sub(r"[A-Za-z]", "a", re.sub(r"[0-9]", "9", nm))
                raise SystemExit(f"FATAL: a {fam} name ({len(nm)} characters, shape {shape}) reached the record")
    os.makedirs(out_dir, exist_ok=True)
    open(os.path.join(out_dir, "elevation.json"), "w", encoding="utf-8").write(text + "\n")
    print(f"\nwrote elevation.json ({len(types)} policy types, {len(access['anyExpiryField'])} expiry field(s) "
          f"anywhere on the access objects); every organization name replaced by a placeholder")


if __name__ == "__main__":
    main()
