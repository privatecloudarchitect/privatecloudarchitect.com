#!/usr/bin/env python3
"""Isolation-matrix verifier for the assembled isolation design.

Runs against your own VCF Automation 9.1 (All Apps) organization and proves,
with live calls under each principal's own session, that the design published
at https://privatecloudarchitect.com/handbook/isolation-design holds on your
build: edit users hold full Day-2 on their own deployments and receive a hard
404 on each other's, edit_adv sees project-wide, and the operators' group
keeps reach through its own policy.

Subcommands:
  login    - session-login each user and print whoami (identity sanity check)
  deploy   - as user1 deploy 'alpha', as user2 deploy 'beta' (each owns theirs)
  matrix   - actor x target: not-visible(404) / 0-actions(DENY) / N-actions(ALLOW)
  flip-on  - create the HARD policy allowing all actions only for the operators group
  flip-off - delete that policy

Configuration is environment-only; each password comes from a file of mode 0600, and a file open to
group or other is refused before it is read. `matrix --record matrix.json` also writes the matrix with
the actors named by role, never by user, and no deployment id:
  VCFA_HOST              VCF Automation FQDN
  VCFA_ORG               organization name
  VCFA_ORG_ID            organization id, bare UUID, not the urn: form (flip-on needs it)
  VCFA_PROJECT_ID        project id, bare UUID (deploy and flip-on need it)
  VCFA_NAMESPACE         Supervisor Namespace deployments land in
  VCFA_CATALOG_ITEM      catalog item name (default: isolation-proof)
  VCFA_TEST_USERS        comma list (default: user1,user2,user3,user4, whose roles
                         mirror manifests/10-rolebindings.yaml: edit, edit, edit_adv, admin)
  VCFA_TEST_PASSWORD_FILE the test users' shared password, in a file of mode 0600
                         (VCFA_TEST_PASSWORD, the value itself, is still read when no file is named)
  VCFA_OPERATOR_USER     a member of the operators group; runs flip-on/flip-off and
                         appears as the matrix's last row (optional for matrix)
  VCFA_OPERATOR_PASSWORD_FILE the operator's password, in a file of mode 0600 (or VCFA_OPERATOR_PASSWORD)
  VCFA_OPERATORS_GROUP   the group the flip policy allows (for example: Platform Operators)
  VCFA_INSECURE          set to 1 only for estates on a self-signed CA

Watch point, propagation: Day-2 policy effects settle in roughly 16 to 20
seconds. Read the matrix only after that window; a sooner read reports the
previous regime and produces the wrong conclusion.

Every cell is a live HTTP call as that principal; nothing is asserted or
hard-coded. Read-only except deploy / flip-on / flip-off.
"""
import argparse
import base64
import json
import os
import re
import ssl
import time
import urllib.error
import urllib.request

HOST = os.environ.get("VCFA_HOST")
ORG = os.environ.get("VCFA_ORG")
ORG_ID = os.environ.get("VCFA_ORG_ID")
PROJECT_ID = os.environ.get("VCFA_PROJECT_ID")
NS = os.environ.get("VCFA_NAMESPACE")
ITEM = os.environ.get("VCFA_CATALOG_ITEM", "isolation-proof")
USERS = [u.strip() for u in os.environ.get("VCFA_TEST_USERS", "user1,user2,user3,user4").split(",") if u.strip()]
def secret(name):
    """A secret from NAME_FILE (a file, mode 0600, its value stripped) or else NAME itself; None when neither is set.
    A file open to group or other is refused before it is read; the refusal names the variable and the fix."""
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


TEST_PASSWORD = secret("VCFA_TEST_PASSWORD")
OPERATOR_USER = os.environ.get("VCFA_OPERATOR_USER")
OPERATOR_PASSWORD = secret("VCFA_OPERATOR_PASSWORD")
OPERATORS_GROUP = os.environ.get("VCFA_OPERATORS_GROUP")

CLOUDAPI_ACCEPT = "application/json;version=9.1.0"
# The VCF Automation 9.1 Day-2 action policy type. The vRA-8 resourceAction type
# is not registered on 9.1 and fails identically to an unknown type.
POLICY_TYPE = "com.vmware.policy.deployment.action"
_BENCH = ["edit", "edit", "edit_adv", "admin"]  # mirrors manifests/10-rolebindings.yaml
ROLE = {u: (_BENCH[i] if i < len(_BENCH) else "user") for i, u in enumerate(USERS)}
CAP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "captures")
DEPS_FILE = os.path.join(CAP, "deps.json")
POLICY_FILE = os.path.join(CAP, "policy_id.txt")


def _require(pairs):
    missing = [k for k, v in pairs.items() if not v]
    if missing:
        raise SystemExit("missing required environment: " + ", ".join(missing))


def _ctx():
    if os.environ.get("VCFA_INSECURE") == "1":
        c = ssl.create_default_context()
        c.check_hostname = False
        c.verify_mode = ssl.CERT_NONE
        return c
    return ssl.create_default_context()


def _req(method, path, token=None, basic=None, accept="application/json", body=None):
    headers = {"Accept": accept}
    if basic:
        headers["Authorization"] = "Basic " + basic
    elif token:
        headers["Authorization"] = "Bearer " + token
    data = json.dumps(body).encode() if body is not None else None
    if data:
        headers["Content-Type"] = "application/json"
    r = urllib.request.Request(f"https://{HOST}{path}", data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(r, context=_ctx(), timeout=60) as resp:
            return resp.status, resp.read().decode(), {k.lower(): v for k, v in resp.headers.items()}
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), {k.lower(): v for k, v in e.headers.items()}
    except Exception as e:  # noqa: BLE001
        return 0, str(e), {}


def login(user, pw):
    basic = base64.b64encode(f"{user}@{ORG}:{pw}".encode()).decode()
    _st, _raw, hdrs = _req("POST", "/cloudapi/1.0.0/sessions", basic=basic, accept=CLOUDAPI_ACCEPT)
    return hdrs.get("x-vmware-vcloud-access-token")


def operator_login():
    return login(OPERATOR_USER, OPERATOR_PASSWORD)


def whoami(token):
    st, raw, _ = _req("GET", "/cloudapi/1.0.0/sessions/current", token=token, accept=CLOUDAPI_ACCEPT)
    return (json.loads(raw).get("user") or {}).get("name") if st == 200 else f"?({st})"


def _content(raw):
    d = json.loads(raw)
    return d.get("content", []) if isinstance(d, dict) else (d if isinstance(d, list) else [])


def catalog_item_id(token):
    st, raw, _ = _req("GET", f"/catalog/api/items?search={ITEM}", token=token)
    return next((it.get("id") for it in _content(raw) if it.get("name") == ITEM), None) if st == 200 else None


def request_deploy(token, item_id, dep_name, app):
    body = {"deploymentName": dep_name, "projectId": PROJECT_ID,
            "reason": "isolation-design proof", "inputs": {"target_namespace_name": NS, "app_name": app}}
    st, raw, _ = _req("POST", f"/catalog/api/items/{item_id}/request", token=token, body=body)
    try:
        d = json.loads(raw)
        return st, (d[0].get("deploymentId") if isinstance(d, list) else d.get("deploymentId") or d.get("id"))
    except Exception:  # noqa: BLE001
        return st, None


def actions(token, dep_id):
    st, raw, _ = _req("GET", f"/deployment/api/deployments/{dep_id}/actions", token=token)
    return (st, sorted({a.get("name") for a in _content(raw) if a.get("name")})) if st == 200 else (st, None)


def create_policy(operator_token):
    """The HARD Day-2 action policy allowing ALL actions ONLY for the operators group.
    Its presence flips every unmatched principal in scope to default-deny."""
    body = {"name": f"Members: (Group) {OPERATORS_GROUP} | Action Scope: ALL | Visibility: per role",
            "typeId": POLICY_TYPE, "enforcementType": "HARD",
            "orgId": ORG_ID, "projectId": PROJECT_ID,
            "definition": {"allowedActions": [{"actions": ["*"], "authorities": [f"GROUP:{OPERATORS_GROUP}@"]}]}}
    st, raw, _ = _req("POST", "/policy/api/policies", token=operator_token, body=body)
    return st, (json.loads(raw).get("id") if st in (200, 201) else raw[:200])


def cmd_login():
    _require({"VCFA_HOST": HOST, "VCFA_ORG": ORG, "VCFA_TEST_PASSWORD_FILE": TEST_PASSWORD})
    for u in USERS:
        print(f"[login] {u} role={ROLE[u]:16s} whoami={whoami(login(u, TEST_PASSWORD))}")


def cmd_deploy():
    _require({"VCFA_HOST": HOST, "VCFA_ORG": ORG, "VCFA_TEST_PASSWORD_FILE": TEST_PASSWORD,
              "VCFA_PROJECT_ID": PROJECT_ID, "VCFA_NAMESPACE": NS})
    os.makedirs(CAP, exist_ok=True)
    out = {}
    for user, app in [(USERS[0], "alpha"), (USERS[1], "beta")]:
        tok = login(user, TEST_PASSWORD)
        st, dep_id = request_deploy(tok, catalog_item_id(tok), f"isolation-proof-{app}-{user}", app)
        print(f"[deploy] {user} app={app} HTTP={st} deploymentId={dep_id}")
        out[app] = {"owner": user, "id": dep_id}
    json.dump(out, open(DEPS_FILE, "w"), indent=2)


def _cell(tok, dep):
    st, acts = actions(tok, dep)
    if st == 404:
        return "not-visible(404)"
    if st == 200 and not acts:
        return "0-actions(DENY)"
    if st == 200:
        return f"{len(acts)}-actions(ALLOW)"
    return f"HTTP{st}"


def cmd_matrix(record=None):
    _require({"VCFA_HOST": HOST, "VCFA_ORG": ORG, "VCFA_TEST_PASSWORD_FILE": TEST_PASSWORD})
    deps = json.load(open(DEPS_FILE))
    tg = [(a, deps[a]["owner"], deps[a]["id"]) for a in ("alpha", "beta") if deps[a]["id"]]
    print("targets: " + ", ".join(f"{a}(owner={o})" for a, o, _ in tg))
    print(f"\n{'actor':12s} {'role/group':18s} | " + " | ".join(f"{a}(own={o})" for a, o, _ in tg))
    print("-" * 78)
    rows = [(u, ROLE[u], login(u, TEST_PASSWORD)) for u in USERS]
    if OPERATOR_USER and OPERATOR_PASSWORD:
        rows.append((OPERATOR_USER, OPERATORS_GROUP or "operator", operator_login()))
    table = []
    for name, role, tok in rows:
        cells = [_cell(tok, i) for _a, _o, i in tg]
        table.append((name, role, cells))
        print(f"{name:12s} {role:18s} | " + " | ".join(cells))
    if record:
        write_matrix(record, tg, table)


def write_matrix(path, tg, table):
    """The matrix with every actor named by its role and every target by its owner's role: no user name, no
    deployment id. The same two edit users become edit-1 and edit-2, in the order the run took them."""
    roles = set(ROLE.values())
    kind = {name: (role if role in roles else "operator") for name, role, _ in table}   # a group name is the estate's
    seen, label = {}, {}
    for name, _, _ in table:
        r = kind[name]
        seen[r] = seen.get(r, 0) + 1
        label[name] = r if list(kind.values()).count(r) == 1 else f"{r}-{seen[r]}"
    rec = {"captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "targets": {a: f"owned by {label.get(o, ROLE.get(o, 'a member'))}" for a, o, _ in tg},
           "rows": [{"actor": label[name], "cells": dict(zip([a for a, _, _ in tg], cells))} for name, _, cells in table]}
    text = json.dumps(rec, indent=1)
    for real in [n for n, _, _ in table] + [i for _, _, i in tg] + [ORG, HOST, OPERATORS_GROUP]:
        if real and real not in ROLE.values() and re.search(r"(?<![\w.-])" + re.escape(real) + r"(?![\w.-])", text):
            raise SystemExit("FATAL: a user name, an id or an estate value reached the matrix record; not writing it")
    open(path, "w", encoding="utf-8").write(text + "\n")
    print(f"\nwrote {path}: the matrix by role, no user name and no id")


def cmd_flip_on():
    _require({"VCFA_HOST": HOST, "VCFA_ORG": ORG, "VCFA_ORG_ID": ORG_ID, "VCFA_PROJECT_ID": PROJECT_ID,
              "VCFA_OPERATOR_USER": OPERATOR_USER, "VCFA_OPERATOR_PASSWORD_FILE": OPERATOR_PASSWORD,
              "VCFA_OPERATORS_GROUP": OPERATORS_GROUP})
    os.makedirs(CAP, exist_ok=True)
    st, pid = create_policy(operator_login())
    print(f"flip-on: HARD allow-{OPERATORS_GROUP}-only policy -> HTTP {st} id={pid}")
    if st in (200, 201):
        open(POLICY_FILE, "w").write(pid)
        print("  wait ~20s (propagation) before re-running matrix.")


def cmd_flip_off():
    _require({"VCFA_HOST": HOST, "VCFA_ORG": ORG,
              "VCFA_OPERATOR_USER": OPERATOR_USER, "VCFA_OPERATOR_PASSWORD_FILE": OPERATOR_PASSWORD})
    pid = open(POLICY_FILE).read().strip() if os.path.exists(POLICY_FILE) else ""
    if not pid:
        print("flip-off: no policy id recorded")
        return
    st, _, _ = _req("DELETE", f"/policy/api/policies/{pid}", token=operator_login())
    print(f"flip-off: DELETE policy {pid[:8]} -> HTTP {st}  (wait ~20s for the permissive default to return)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["login", "deploy", "matrix", "flip-on", "flip-off"])
    ap.add_argument("--record", help="with matrix: write the matrix by role to this file")
    a = ap.parse_args()
    if a.record and a.cmd != "matrix":
        ap.error("--record belongs to matrix")
    dispatch = {"login": cmd_login, "deploy": cmd_deploy, "matrix": lambda: cmd_matrix(a.record),
                "flip-on": cmd_flip_on, "flip-off": cmd_flip_off}
    dispatch[a.cmd]()
