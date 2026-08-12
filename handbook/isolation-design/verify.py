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

Configuration is environment-only; nothing secret touches disk:
  VCFA_HOST              VCF Automation FQDN
  VCFA_ORG               organization name
  VCFA_ORG_ID            organization id, bare UUID, not the urn: form (flip-on needs it)
  VCFA_PROJECT_ID        project id, bare UUID (deploy and flip-on need it)
  VCFA_NAMESPACE         Supervisor Namespace deployments land in
  VCFA_CATALOG_ITEM      catalog item name (default: isolation-proof)
  VCFA_TEST_USERS        comma list (default: user1,user2,user3,user4, whose roles
                         mirror manifests/10-rolebindings.yaml: edit, edit, edit_adv, admin)
  VCFA_TEST_PASSWORD     the test users' shared password
  VCFA_OPERATOR_USER     a member of the operators group; runs flip-on/flip-off and
                         appears as the matrix's last row (optional for matrix)
  VCFA_OPERATOR_PASSWORD the operator's password
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
import ssl
import urllib.error
import urllib.request

HOST = os.environ.get("VCFA_HOST")
ORG = os.environ.get("VCFA_ORG")
ORG_ID = os.environ.get("VCFA_ORG_ID")
PROJECT_ID = os.environ.get("VCFA_PROJECT_ID")
NS = os.environ.get("VCFA_NAMESPACE")
ITEM = os.environ.get("VCFA_CATALOG_ITEM", "isolation-proof")
USERS = [u.strip() for u in os.environ.get("VCFA_TEST_USERS", "user1,user2,user3,user4").split(",") if u.strip()]
TEST_PASSWORD = os.environ.get("VCFA_TEST_PASSWORD")
OPERATOR_USER = os.environ.get("VCFA_OPERATOR_USER")
OPERATOR_PASSWORD = os.environ.get("VCFA_OPERATOR_PASSWORD")
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
    _require({"VCFA_HOST": HOST, "VCFA_ORG": ORG, "VCFA_TEST_PASSWORD": TEST_PASSWORD})
    for u in USERS:
        print(f"[login] {u} role={ROLE[u]:16s} whoami={whoami(login(u, TEST_PASSWORD))}")


def cmd_deploy():
    _require({"VCFA_HOST": HOST, "VCFA_ORG": ORG, "VCFA_TEST_PASSWORD": TEST_PASSWORD,
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


def cmd_matrix():
    _require({"VCFA_HOST": HOST, "VCFA_ORG": ORG, "VCFA_TEST_PASSWORD": TEST_PASSWORD})
    deps = json.load(open(DEPS_FILE))
    tg = [(a, deps[a]["owner"], deps[a]["id"]) for a in ("alpha", "beta") if deps[a]["id"]]
    print("targets: " + ", ".join(f"{a}(owner={o})" for a, o, _ in tg))
    print(f"\n{'actor':12s} {'role/group':18s} | " + " | ".join(f"{a}(own={o})" for a, o, _ in tg))
    print("-" * 78)
    rows = [(u, ROLE[u], login(u, TEST_PASSWORD)) for u in USERS]
    if OPERATOR_USER and OPERATOR_PASSWORD:
        rows.append((OPERATOR_USER, OPERATORS_GROUP or "operator", operator_login()))
    for name, role, tok in rows:
        print(f"{name:12s} {role:18s} | " + " | ".join(_cell(tok, i) for _a, _o, i in tg))


def cmd_flip_on():
    _require({"VCFA_HOST": HOST, "VCFA_ORG": ORG, "VCFA_ORG_ID": ORG_ID, "VCFA_PROJECT_ID": PROJECT_ID,
              "VCFA_OPERATOR_USER": OPERATOR_USER, "VCFA_OPERATOR_PASSWORD": OPERATOR_PASSWORD,
              "VCFA_OPERATORS_GROUP": OPERATORS_GROUP})
    os.makedirs(CAP, exist_ok=True)
    st, pid = create_policy(operator_login())
    print(f"flip-on: HARD allow-{OPERATORS_GROUP}-only policy -> HTTP {st} id={pid}")
    if st in (200, 201):
        open(POLICY_FILE, "w").write(pid)
        print("  wait ~20s (propagation) before re-running matrix.")


def cmd_flip_off():
    _require({"VCFA_HOST": HOST, "VCFA_ORG": ORG,
              "VCFA_OPERATOR_USER": OPERATOR_USER, "VCFA_OPERATOR_PASSWORD": OPERATOR_PASSWORD})
    pid = open(POLICY_FILE).read().strip() if os.path.exists(POLICY_FILE) else ""
    if not pid:
        print("flip-off: no policy id recorded")
        return
    st, _, _ = _req("DELETE", f"/policy/api/policies/{pid}", token=operator_login())
    print(f"flip-off: DELETE policy {pid[:8]} -> HTTP {st}  (wait ~20s for the permissive default to return)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["login", "deploy", "matrix", "flip-on", "flip-off"])
    a = ap.parse_args()
    dispatch = {"login": cmd_login, "deploy": cmd_deploy, "matrix": cmd_matrix,
                "flip-on": cmd_flip_on, "flip-off": cmd_flip_off}
    dispatch[a.cmd]()
