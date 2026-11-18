#!/usr/bin/env python3
"""delegation.py: give a team scoped visibility and Day-2 actions on its own VMs through VCF Operations, prove the
boundary from inside it, and read who acted.

A team reaches VCF Operations through its directory group in VCF single sign-on. The group gets a VCF Operations role
(what its members may do) and a scope (on which objects), and nothing in vCenter: an action runs as the vCenter
integration's own account, so vCenter's events name that account and VCF Operations' action status names the person.
One subcommand per step:

  plan    read-only: whether VCF SSO shows the group, whether VCF Operations has imported it and with what, whether
          the group holds a VCF role (which overrides the scope), the role against the recipe (ReadOnly's privileges,
          the actions you name, Recent Tasks, and with --api the REST write privilege), the scope against the objects
          you name, and what apply would write
  apply   dry run unless --execute: the role, the scope, the group's import and its permission, each created or
          brought to the recipe and read back after. It changes a role or a scope only when its description carries
          this script's mark, and on a group it did not import it adds or replaces only this role's permission
  check   as a member of the team; writes nothing and runs no action: each named object readable, each --outside
          object invisible and an action query on it refused, an action query on each named object answered
  act     as the member, dry run unless --execute: one named action on one named object, the documented way (the
          action's query, then the body the query returns), and the task's status read back. It refuses an object
          that is not one of --objects
  who     read-only: who submitted each action task, from VCF Operations' action status
  revoke  dry run unless --execute: this role's permission off the group, the group's import when apply made it,
          and the role and the scope when they carry the mark, then a read that nothing marked is left

Settings (environment; the host, broker, realm and TLS settings are opslib.py's):
  OPS_HOST, OPS_BROKER_HOST, OPS_REALM, OPS_TLS_VERIFY
  OPS_API_TOKEN_FILE        the administrator's api token, mode 0600 (or OPS_TOKEN_FILE, an exchanged bearer)
  OPS_MEMBER_API_TOKEN_FILE a member's api token, mode 0600, for check and act (or OPS_MEMBER_TOKEN_FILE, a bearer)
  OUT                       the directory each subcommand's record is written to (default: the current directory)

Arguments:
  --team NAME          the role is NAME-act and the scope NAME-scope (letters, digits, - and _)
  --group NAME@DOMAIN  the team's group as VCF SSO shows it
  --objects A,B        the VMs the team owns, by their names in VCF Operations
  --outside C,D        (check) VMs the team must not see
  --actions LIST       the VM actions the team may run, comma separated (default "Power Off VM,Power On VM")
  --api                the team also acts through the API, so the role gets All other Read, Write APIs
  --source NAME        the VCF Operations auth source the group comes from (default "VCF SSO")
  --object, --action   (act) the one object and the one action
  --task ID,ID         (who) the task ids act or the console printed
  --execute            (apply, act, revoke) send the writes; without it each prints what it would send

Run:
  export OPS_HOST=<operations-fqdn> OPS_BROKER_HOST=<identity-broker-fqdn>
  export OPS_API_TOKEN_FILE=<administrator api token file>
  python3 delegation.py plan  --team payments --group payments-ops@example.com --objects pay-web-01,pay-db-01
  python3 delegation.py apply --team payments --group payments-ops@example.com --objects pay-web-01,pay-db-01 --execute
  export OPS_MEMBER_API_TOKEN_FILE=<a member's api token file>
  python3 delegation.py check --team payments --group payments-ops@example.com --objects pay-web-01 --outside hr-db-01
Exit: 0 done, and every check held · 1 a check did not hold (a boundary, the recipe, a read back, an action) · 2 an
      argument or setting is missing or wrong, or a secret file is open to group or other · 3 the sign-in or a read
      failed · 4 the record was not written because an estate value survived the scrub · 5 apply or revoke refused to
      change an object this script did not mark
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import opslib  # noqa: E402

MARK = "managed by delegation.py"
DEFAULT_ACTIONS = ("Power Off VM", "Power On VM")
RECENT_TASKS = "administration.recenttasks_manage"
API_WRITE = "administration.api_access"
TRAVERSAL = {"name": "vSphere Hosts and Clusters", "adapterKind": "VMWARE", "resourceKind": "vSphere World"}
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,48}$")
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
MOID = re.compile(r"(?<![A-Za-z0-9-])vm-\d+(?![A-Za-z0-9])")
PLACEHOLDER = re.compile(r"\{\{[a-z]+(?:-[a-z]+)*-\d+\}\}")
POLL_SECONDS, POLL_TRIES = 5, 36
OK, NOT_HELD, USAGE, READ_FAILED, RECORD_REFUSED, UNMARKED = 0, 1, 2, 3, 4, 5


class Stop(Exception):
    """A run that cannot go on: its exit code and the sentence that says why."""

    def __init__(self, code, why):
        super().__init__(why)
        self.code = code


def action_privilege(action):
    """The privilege key VCF Operations gives a VM action: the action's name, the adapter kind, the resource kind."""
    return f"{action}-VMWARE-VirtualMachine"


def count(n, word):
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def action_path(action):
    return "/api/actions/" + urllib.parse.quote("VMWARE-" + action)


def recipe(readonly, actions, api):
    """The act role: everything ReadOnly may see, each named action, Recent Tasks (so a member can read the result of
    its own action), and the REST write privilege only for a team that acts through the API."""
    return sorted(set(readonly) | {action_privilege(a) for a in actions} | {RECENT_TASKS} | ({API_WRITE} if api else set()))


def message(body):
    """The sentence a VCF Operations refusal carries: its errorMessage, else its message, else the start of the page."""
    if not isinstance(body, dict):
        return None
    for m in body.get("moreInformation") or []:
        if m.get("name") == "errorMessage":
            return m.get("value")
    if body.get("message"):
        return body["message"]
    raw = body.get("raw") or ""
    return "a servlet error page, not the API's JSON error" if raw.lstrip().lower().startswith("<!doctype html") else raw[:160] or None


def offered(query_status, query_body, rid):
    """Whether VCF Operations offers the action for this object now. The query names every object it is asked about;
    the object is offered only when the query's parameterGroup carries it. An object VCF Operations has not yet
    collected in the state the action needs (a VM powered off moments ago, for Power On) gets an empty parameterGroup,
    and an execute of that body answers 500 'No resources provided to run action on'."""
    body = (query_body or {}).get("action-execution") if query_status == 200 else None
    return bool(body) and rid in [g.get("resourceId") for g in body.get("parameterGroup") or []]


def html_refusal(status, body):
    """A 403 that is a servlet page rather than the API's JSON: the caller's role lacks the REST write privilege."""
    return status == 403 and isinstance(body, dict) and (body.get("raw") or "").lstrip().lower().startswith("<!doctype html")


# ---------------------------------------------------------------- sign-in


def exchange(api_token):
    """An api token traded at the identity broker for a bearer, the same grant opslib.bearer() sends."""
    host = os.environ["OPS_HOST"]
    broker = os.environ.get("OPS_BROKER_HOST", host)
    realm = os.environ.get("OPS_REALM", "CUSTOMER")
    data = urllib.parse.urlencode({"grant_type": opslib.GRANT, "api_token": api_token}).encode()
    req = urllib.request.Request(f"https://{broker}/acs/t/{realm}/token", data=data, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, context=opslib._ctx(), timeout=30) as r:
        return json.loads(r.read())["access_token"]


def session(prefix):
    """A signed-in caller for OPS_<prefix>TOKEN_FILE (a bearer) or OPS_<prefix>API_TOKEN_FILE (an api token)."""
    if not os.environ.get("OPS_HOST"):
        raise Stop(USAGE, "OPS_HOST is not set")
    try:
        bearer = opslib.secret(f"OPS_{prefix}TOKEN")
        if not bearer:
            api_token = opslib.secret(f"OPS_{prefix}API_TOKEN")
            if not api_token:
                raise Stop(USAGE, f"set OPS_{prefix}API_TOKEN_FILE (an api token) or OPS_{prefix}TOKEN_FILE (a bearer)")
            bearer = exchange(api_token)
            del api_token
    except PermissionError as e:
        raise Stop(USAGE, str(e)) from None
    except (urllib.error.URLError, KeyError, ValueError) as e:
        raise Stop(READ_FAILED, f"the sign-in for OPS_{prefix}API_TOKEN failed: {type(e).__name__}") from None
    return lambda method, path, body=None, params=None: opslib.ops(method, path, bearer, body=body, params=params)


# ---------------------------------------------------------------- reads


def need(call, method, path, body=None, params=None, ok=(200,)):
    s, b = call(method, path, body=body, params=params)
    if s not in ok:
        raise Stop(READ_FAILED, f"{method} {path} answered {s}: {message(b) or 'no message'}")
    return b


def resolve(call, names):
    """Each VM name to its VCF Operations resource id, by exact name; a name no VM has, or two VMs share, stops."""
    ids = {}
    for name in names:
        b = need(call, "GET", "/api/resources", params={"name": name, "resourceKind": "VirtualMachine", "adapterKind": "VMWARE"})
        hits = [r for r in (b or {}).get("resourceList") or [] if (r.get("resourceKey") or {}).get("name") == name]
        if len(hits) != 1:
            raise Stop(USAGE, f"VCF Operations holds {len(hits)} VMs named {name!r}: name one it holds exactly once")
        ids[name] = hits[0]["identifier"]
    return ids


def source_id(call, name):
    b = need(call, "GET", "/api/auth/sources")
    hits = [s for s in (b or {}).get("sources") or [] if s.get("name") == name]
    if not hits:
        raise Stop(USAGE, f"VCF Operations has no auth source named {name!r}")
    return hits[0]["id"]


def privileges(call, role):
    b = need(call, "GET", f"/api/auth/roles/{urllib.parse.quote(role)}/privileges")
    return sorted({p.get("key") for p in (b or {}).get("privileges") or [] if p.get("key")})


def role_state(call, name):
    s, b = call("GET", f"/api/auth/roles/{urllib.parse.quote(name)}")
    if s == 404:
        return {"exists": False}
    if s != 200:
        raise Stop(READ_FAILED, f"GET /api/auth/roles/{name} answered {s}: {message(b) or 'no message'}")
    return {"exists": True, "marked": MARK in (b.get("description") or ""), "privileges": privileges(call, name)}


def scope_state(call, name):
    b = need(call, "GET", "/api/auth/scopes")
    hits = [s for s in (b or {}).get("scopesDetails") or [] if s.get("name") == name]
    if not hits:
        return {"exists": False}
    s = hits[0]
    ids = sorted({i for t in s.get("traversalSpecInstances") or [] for sel in t.get("resourceSelection") or []
                  for i in sel.get("resourceId") or []})
    every = any(t.get("selectAllResources") for t in s.get("traversalSpecInstances") or [])
    return {"exists": True, "id": s["id"], "marked": MARK in (s.get("description") or ""), "ids": ids, "all": every}


def group_state(call, group):
    b = need(call, "GET", "/api/auth/usergroups")
    hits = [g for g in (b or {}).get("userGroups") or [] if (g.get("name") or "").lower() == group.lower()]
    if not hits:
        return {"imported": False}
    g = hits[0]
    perms = need(call, "GET", f"/api/auth/usergroups/{g['id']}/permissions")
    return {"imported": True, "id": g["id"], "marked": MARK in (g.get("description") or ""),
            "permissions": [{"roleName": p.get("roleName"), "scopeId": p.get("scopeId"), "allowAllObjects": p.get("allowAllObjects")}
                            for p in (perms or {}).get("permissions") or []]}


def in_source(call, src, group):
    local, _, domain = group.partition("@")
    s, b = call("POST", f"/api/auth/sources/{src}/usergroups/search", body={"name": local, "domain": domain})
    if s != 200:
        return None
    return [g for g in (b or {}).get("usergroup-search-response") or [] if (g.get("name") or "").lower() == group.lower()]


def vcf_roles(call, group):
    """The VCF roles the realm gives the group, or None when this identity cannot read the realm. A VCF role on the
    group overrides the scope: its members see every object the role reaches, in VCF Operations and beyond."""
    s, realms = call("GET", "/api/fleet-management/iam/ssorealms")
    if s != 200:
        return None
    rows = realms if isinstance(realms, list) else (realms or {}).get("ssoRealms") or (realms or {}).get("content") or []
    if not rows:
        return None
    rid = rows[0].get("id") or rows[0].get("ssoRealmId")
    s, b = call("POST", f"/api/fleet-management/iam/ssorealms/{rid}/groups/query", body={}, params={"page": 0, "pageSize": 1000})
    if s != 200:
        return None
    local = group.partition("@")[0].lower()
    hits = [g for g in (b or {}).get("vidbGroups") or [] if (g.get("groupName") or "").lower() in (local, group.lower())]
    return sorted({r for g in hits for r in g.get("roles") or []}) if hits else []


# ---------------------------------------------------------------- the team, as it is and as it should be


def names(a):
    team = a["team"]
    if not team or not NAME.match(team):
        raise Stop(USAGE, "--team takes letters, digits, - and _ (the role is <team>-act, the scope <team>-scope)")
    return f"{team}-act", f"{team}-scope"


def survey(call, a):
    """Everything plan, apply and revoke decide from, read in one pass."""
    role, scope = names(a)
    objects = resolve(call, a["objects"])
    readonly = privileges(call, "ReadOnly")
    want = recipe(readonly, a["actions"], a["api"])
    known = {p.get("key") for p in (need(call, "GET", "/api/auth/privileges") or {}).get("privileges") or []}
    unknown = [a_ for a_ in a["actions"] if action_privilege(a_) not in known]
    if unknown:
        raise Stop(USAGE, f"VCF Operations has no VM action privilege for {', '.join(unknown)} (its key would be "
                          f"'<action>-VMWARE-VirtualMachine'): name actions as the console lists them")
    src = source_id(call, a["source"])
    return {"role_name": role, "scope_name": scope, "objects": objects, "want": want, "source": src,
            "role": role_state(call, role), "scope": scope_state(call, scope), "group": group_state(call, a["group"]),
            "in_source": in_source(call, src, a["group"]), "vcf_roles": vcf_roles(call, a["group"])}


def judge(sv, a):
    """What is missing, what apply would write, and the findings a reader acts on."""
    findings, would = [], []
    r, sc, g = sv["role"], sv["scope"], sv["group"]
    if not r["exists"]:
        would.append(f"create role {sv['role_name']} ({len(sv['want'])} privileges: ReadOnly's, the actions, Recent Tasks"
                     f"{', All other Read, Write APIs' if a['api'] else ''})")
    else:
        missing, extra = sorted(set(sv["want"]) - set(r["privileges"])), sorted(set(r["privileges"]) - set(sv["want"]))
        if missing or extra:
            would.append(f"set role {sv['role_name']}'s privileges to the recipe ({len(missing)} to add, {len(extra)} to remove)")
            if not r["marked"]:
                findings.append(f"role {sv['role_name']} exists without this script's mark; apply will not change it")
        if RECENT_TASKS in missing:
            findings.append("the role lacks Recent Tasks: a member cannot read the status of its own action (it reads 404)")
        if API_WRITE in missing:
            findings.append("the role lacks All other Read, Write APIs: an action sent through the API answers a bare HTML 403")
    want_ids = sorted(sv["objects"].values())
    if not sc["exists"]:
        would.append(f"create scope {sv['scope_name']} (SPECIFIC: {count(len(want_ids), 'VM')})")
    elif sc["ids"] != want_ids or sc["all"]:
        would.append(f"set scope {sv['scope_name']} to the {count(len(want_ids), 'VM')} named")
        if not sc["marked"]:
            findings.append(f"scope {sv['scope_name']} exists without this script's mark; apply will not change it")
    if sc.get("all"):
        findings.append(f"scope {sv['scope_name']} selects all resources: the team sees every object in it")
    if not g["imported"]:
        if not sv["in_source"]:
            findings.append(f"the {a['source']} source does not show {a['group']}: add the group to the identity "
                            "provider's sync profile and sync, then plan again")
        would.append(f"import {a['group']} from {a['source']} with role {sv['role_name']} on scope {sv['scope_name']}")
    else:
        mine = [p for p in g["permissions"] if p["roleName"] == sv["role_name"]]
        if not mine or mine[0]["scopeId"] != sc.get("id") or mine[0]["allowAllObjects"]:
            would.append(f"give {a['group']} role {sv['role_name']} on scope {sv['scope_name']}")
        others = [p["roleName"] for p in g["permissions"] if p["roleName"] != sv["role_name"]]
        if others:
            findings.append(f"the group also holds {', '.join(sorted(others))} in VCF Operations; apply leaves them alone")
    if sv["vcf_roles"]:
        findings.append(f"the group holds the VCF {'role' if len(sv['vcf_roles']) == 1 else 'roles'} {', '.join(sv['vcf_roles'])}: a VCF role overrides this scope, "
                        "so its members see beyond it; keep VCF roles off a scoped group")
    elif sv["vcf_roles"] is None:
        findings.append("the realm's VCF roles were not readable with this identity: check the group's VCF roles in the console")
    return would, findings


# ---------------------------------------------------------------- writes


def apply_writes(call, sv, a):
    """Create or bring to the recipe each object, refusing one this script did not mark, and read each back."""
    sent, r, sc, g = [], sv["role"], sv["scope"], sv["group"]
    want_ids = sorted(sv["objects"].values())
    if r["exists"] and not r["marked"] and set(r["privileges"]) != set(sv["want"]):
        raise Stop(UNMARKED, f"role {sv['role_name']} exists without the mark '{MARK}': rename the team or fix the role by hand")
    if sc["exists"] and not sc["marked"] and (sc["ids"] != want_ids or sc["all"]):
        raise Stop(UNMARKED, f"scope {sv['scope_name']} exists without the mark '{MARK}': rename the team or fix the scope by hand")
    role_body = {"name": sv["role_name"], "displayName": sv["role_name"], "privilege-keys": sv["want"],
                 "description": f"{a['team']}: act on its own VMs ({MARK})"}
    if not r["exists"]:
        sent.append(["POST /api/auth/roles", need(call, "POST", "/api/auth/roles", role_body, ok=(200, 201)) and 201])
    elif set(r["privileges"]) != set(sv["want"]):
        sent.append(["PUT /api/auth/roles", need(call, "PUT", "/api/auth/roles", role_body, ok=(200, 204)) and 200])
    selection = [{**TRAVERSAL, "selectAllResources": False, "resourceSelection": [{"type": "SPECIFIC", "resourceId": want_ids}]}]
    scope_body = {"name": sv["scope_name"], "description": f"{a['team']}: its own VMs ({MARK})", "traversalSpecInstances": selection}
    if not sc["exists"]:
        sent.append(["POST /api/auth/scopes", need(call, "POST", "/api/auth/scopes", scope_body, ok=(200, 201)) and 201])
    elif sc["ids"] != want_ids or sc["all"]:
        sent.append(["PUT /api/auth/scopes", need(call, "PUT", "/api/auth/scopes", {**scope_body, "id": sc["id"]}, ok=(200, 204)) and 200])
    scope = scope_state(call, sv["scope_name"])
    perm = {"roleName": sv["role_name"], "scopeId": scope.get("id"), "allowAllObjects": False}
    if not g["imported"]:
        hits = sv["in_source"] or []
        if not hits:
            raise Stop(NOT_HELD, f"the {a['source']} source does not show {a['group']}: sync it into VCF SSO first")
        body = {"name": hits[0]["name"], "displayName": hits[0]["name"], "authSourceId": sv["source"],
                "externalId": hits[0].get("externalId"), "description": f"{a['team']} ({MARK})", "role-permissions": [perm]}
        sent.append(["POST /api/auth/usergroups", need(call, "POST", "/api/auth/usergroups", body, ok=(200, 201)) and 201])
    else:
        mine = [p for p in g["permissions"] if p["roleName"] == sv["role_name"]]
        if not mine or mine[0]["scopeId"] != perm["scopeId"] or mine[0]["allowAllObjects"]:
            sent.append([f"PUT /api/auth/usergroups/<group>/permissions ({sv['role_name']} only)",
                         need(call, "PUT", f"/api/auth/usergroups/{g['id']}/permissions", perm) and 200])
    after = {"role": role_state(call, sv["role_name"]), "scope": scope, "group": group_state(call, a["group"])}
    held = {"role_is_recipe": set(after["role"].get("privileges") or []) == set(sv["want"]),
            "scope_is_the_objects": after["scope"].get("ids") == want_ids and not after["scope"].get("all"),
            "group_has_the_permission": any(p["roleName"] == sv["role_name"] and p["scopeId"] == perm["scopeId"]
                                            and not p["allowAllObjects"] for p in after["group"].get("permissions") or [])}
    return sent, after, held


def revoke_writes(call, sv, a):
    """This role's permission off the group; the group's import when the mark says apply made it; the role and the
    scope when they carry the mark. The order matters: a role still assigned is not deleted."""
    sent, r, sc, g = [], sv["role"], sv["scope"], sv["group"]
    for kind, state in (("role", r), ("scope", sc)):
        if state["exists"] and not state["marked"]:
            raise Stop(UNMARKED, f"{kind} {sv[kind + '_name']} exists without the mark '{MARK}': revoke leaves it to you")
    if g["imported"]:
        if g["marked"]:
            sent.append(["DELETE /api/auth/usergroups/<group>", call("DELETE", f"/api/auth/usergroups/{g['id']}")[0]])
        elif any(p["roleName"] == sv["role_name"] for p in g["permissions"]):
            sent.append([f"DELETE /api/auth/usergroups/<group>/permissions/{sv['role_name']}",
                         call("DELETE", f"/api/auth/usergroups/{g['id']}/permissions/{urllib.parse.quote(sv['role_name'])}")[0]])
    if r["exists"]:
        sent.append([f"DELETE /api/auth/roles/{sv['role_name']}", call("DELETE", f"/api/auth/roles/{urllib.parse.quote(sv['role_name'])}")[0]])
    if sc["exists"]:
        sent.append(["DELETE /api/auth/scopes", call("DELETE", "/api/auth/scopes", body={"uuids": [sc["id"]]})[0]])
    after = {"role": role_state(call, sv["role_name"]), "scope": scope_state(call, sv["scope_name"]), "group": group_state(call, a["group"])}
    held = {"role_gone": not after["role"]["exists"], "scope_gone": not after["scope"]["exists"],
            "group_without_the_role": not any(p["roleName"] == sv["role_name"] for p in after["group"].get("permissions") or [])}
    return sent, after, held


# ---------------------------------------------------------------- as a member


def check(member, admin, a):
    """The boundary as the member meets it. Nothing is written and no action runs: an action's query only populates."""
    role, _scope = names(a)
    inside, outside = resolve(admin, a["objects"]), resolve(admin, a["outside"])
    me = need(member, "GET", "/api/auth/currentuser")
    group = group_state(admin, a["group"])
    rows = [{"check": "the member's record lists the team's group", "expected": "listed",
             "got": "listed" if group.get("id") in (me.get("groupIds") or []) else "not listed",
             "held": group.get("id") in (me.get("groupIds") or [])},
            {"check": "the member holds no permission of its own", "expected": "none",
             "got": f"{len(me.get('role-permissions') or [])} of its own", "held": not me.get("role-permissions")}]
    probe = a["actions"][0]
    for name, rid in inside.items():
        s, _b = member("GET", f"/api/resources/{rid}")
        rows.append({"check": "a named object is readable", "object": name, "expected": 200, "got": s, "held": s == 200})
        s, b = member("POST", action_path(probe) + "/query", body={"contextResourceId": [rid]})
        rows.append({"check": f"its {probe} query is answered", "object": name, "expected": 200, "got": s, "held": s == 200,
                     "message": None if s == 200 else message(b)})
    for name, rid in outside.items():
        s, b = member("GET", f"/api/resources/{rid}")
        rows.append({"check": "an object outside the scope is invisible", "object": name, "expected": 404, "got": s,
                     "held": s == 404, "message": message(b)})
        s, b = member("POST", action_path(probe) + "/query", body={"contextResourceId": [rid]})
        rows.append({"check": f"its {probe} query is refused", "object": name, "expected": "refused", "got": s,
                     "held": not offered(s, b, rid), "message": message(b)})
    return {"member": me.get("username"), "role": role, "rows": rows}


def act(member, admin, a):
    """One action, the documented way: the query populates the body, the execute sends it, the status says who."""
    if a["object"] not in a["objects"]:
        raise Stop(USAGE, f"act runs only on one of --objects; {a['object']!r} is not one of them")
    if a["action"] not in a["actions"]:
        raise Stop(USAGE, f"act runs only one of --actions; {a['action']!r} is not one of them")
    rid = resolve(admin, [a["object"]])[a["object"]]
    s, q = member("POST", action_path(a["action"]) + "/query", body={"contextResourceId": [rid]})
    body = (q or {}).get("action-execution") if s == 200 else None
    out = {"object": a["object"], "action": a["action"], "query": s}
    if not offered(s, q, rid):
        out["offered"] = False
        out["why"] = message(q) if s != 200 else ("VCF Operations does not offer this action for the object now: its "
                                                 "query left the object out of parameterGroup, because VCF Operations "
                                                 "decides from its last collection (a VM powered off moments ago is "
                                                 "offered Power On after the next cycle)")
        return out
    out["offered"] = True
    if not a["execute"]:
        out["would_send"] = f"POST {action_path(a['action'])} with the body the query returned"
        return out
    s, b = member("POST", action_path(a["action"]), body=body)
    out["execute"] = s
    if html_refusal(s, b):
        out["why"] = "a bare HTML 403: the role lacks All other Read, Write APIs (administration.api_access); apply --api"
        return out
    task = ((b or {}).get("values") or [None])[0] if s == 200 else None
    out["task"] = task
    if not task:
        out["why"] = message(b)
        return out
    status = None
    for _ in range(POLL_TRIES):
        time.sleep(POLL_SECONDS)
        st, status = member("GET", f"/api/actions/{task}/status", params={"detail": "true"})
        if st == 404:
            out["why"] = ("the status answered 404 to the member: the role lacks Recent Tasks; the task was accepted, "
                          "and who reads it as an administrator")
            status = None
            break
        if st == 200 and str((status or {}).get("state") or "").startswith(("COMPLETED", "FAILED", "ERROR")):
            break
    out["status"] = {k: (status or {}).get(k) for k in ("state", "submittedBy", "authSource")} if status else None
    return out


def who(call, tasks):
    rows = []
    for t in tasks:
        s, b = call("GET", f"/api/actions/{t}/status", params={"detail": "true"})
        if s != 200:
            rows.append({"task": t, "read": s, "why": message(b)})
            continue
        target = next((m.group(1) for x in b.get("messages") or []
                       for m in [re.search(r"targetResourceId='([^']+)'", x.get("message") or "")] if m), None)
        name = None
        if target:
            s2, r = call("GET", f"/api/resources/{target}")
            name = ((r or {}).get("resourceKey") or {}).get("name") if s2 == 200 else None
        rows.append({"task": t, "read": 200, "action": b.get("name"), "state": b.get("state"),
                     "submittedBy": b.get("submittedBy"), "authSource": b.get("authSource"),
                     "started": b.get("startDate"), "completed": b.get("completeDate"), "object": name})
    return rows


# ---------------------------------------------------------------- the record


def estate_values(a, extra=()):
    """Every name this run read or was given, each with its kind; ids and VM managed-object ids are found by shape."""
    table = {}

    def add(value, kind):
        if value and isinstance(value, str) and len(value) > 2 and value.lower() not in {v.lower() for v in table}:
            table[value] = f"{{{{{kind}-{sum(1 for p in table.values() if p.startswith('{{' + kind + '-')) + 1}}}}}"
    for host in (os.environ.get("OPS_HOST"), os.environ.get("OPS_BROKER_HOST")):
        add(host, "host")
    add(a.get("group"), "group")
    local, _, domain = (a.get("group") or "").partition("@")
    add(local, "group")
    add(domain, "domain")
    if a.get("team"):
        add(f"{a['team']}-act", "role")
        add(f"{a['team']}-scope", "scope")
        add(a["team"], "team")
    for n in list(a.get("objects") or []) + list(a.get("outside") or []):
        add(n, "vm")
    for value, kind in extra:
        add(value, kind)
    return table


def scrub(obj, table):
    """Values only, never keys; registered names longest first, on a word boundary, outside existing placeholders;
    then anything shaped like an id or a VM managed-object id."""
    alt = "|".join(re.escape(v) for v in sorted(table, key=len, reverse=True))
    rx = re.compile(rf"(?<![A-Za-z0-9])(?:{alt})(?![A-Za-z0-9])", re.I) if alt else None
    label = {k.lower(): v for k, v in table.items()}
    ids, moids = {}, {}

    def outside(s, fn):
        """fn applied to the text between placeholders only, so no pass rewrites a placeholder an earlier pass wrote."""
        return "".join(p if i % 2 else fn(p) for i, p in enumerate(re.split(f"({PLACEHOLDER.pattern})", s)))

    def text(s):
        if rx:
            s = outside(s, lambda p: rx.sub(lambda m: label[m.group(0).lower()], p))
        s = outside(s, lambda p: UUID.sub(lambda m: ids.setdefault(m.group(0).lower(), f"{{{{id-{len(ids) + 1}}}}}"), p))
        return outside(s, lambda p: MOID.sub(lambda m: moids.setdefault(m.group(0), f"{{{{moid-{len(moids) + 1}}}}}"), p))

    def walk(o):
        if isinstance(o, dict):
            return {k: walk(v) for k, v in o.items()}
        if isinstance(o, list):
            return [walk(v) for v in o]
        return text(o) if isinstance(o, str) else o

    return walk(obj)


def leaks(obj, table):
    """The kind of every estate value still in a scrubbed record."""
    found = []

    def walk(o):
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, str):
            rest = PLACEHOLDER.sub(" ", o)
            for value, placeholder in table.items():
                if re.search(rf"(?<![A-Za-z0-9]){re.escape(value)}(?![A-Za-z0-9])", rest, re.I):
                    found.append(placeholder.strip("{}").rsplit("-", 1)[0])
            if UUID.search(rest):
                found.append("id")
            if MOID.search(rest):
                found.append("moid")
    walk(obj)
    return found


def write_record(command, body, a, extra=()):
    table = estate_values(a, extra)
    record = scrub({"captured": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "command": command, **body}, table)
    left = leaks(record, table)
    path = os.path.join(os.environ.get("OUT") or ".", f"{command}.json")
    if left:
        raise Stop(RECORD_REFUSED, f"{path} not written: {len(left)} estate value(s) survived the scrub ({', '.join(sorted(set(left)))})")
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(record, indent=1, ensure_ascii=False) + "\n")
    return path


# ---------------------------------------------------------------- the command line


def parse(argv):
    if not argv or argv[0] not in ("plan", "apply", "check", "act", "who", "revoke"):
        raise Stop(USAGE, "name a subcommand: plan, apply, check, act, who or revoke (see the docstring)")
    a = {"command": argv[0], "team": None, "group": None, "objects": [], "outside": [], "actions": list(DEFAULT_ACTIONS),
         "api": False, "source": "VCF SSO", "object": None, "action": None, "tasks": [], "execute": False}
    lists = {"--objects": "objects", "--outside": "outside", "--actions": "actions", "--task": "tasks"}
    single = {"--team": "team", "--group": "group", "--source": "source", "--object": "object", "--action": "action"}
    rest = list(argv[1:])
    while rest:
        k = rest.pop(0)
        if k in ("--api", "--execute"):
            a[k[2:]] = True
        elif k in lists or k in single:
            if not rest:
                raise Stop(USAGE, f"{k} needs a value")
            v = rest.pop(0)
            if k in lists:
                a[lists[k]] = [x.strip() for x in v.split(",") if x.strip()]
            else:
                a[single[k]] = v
        else:
            raise Stop(USAGE, f"unknown argument {k!r}")
    if a["command"] == "who":
        if not a["tasks"]:
            raise Stop(USAGE, "who needs --task ID[,ID]")
        return a
    for k in ("team", "group"):
        if not a[k]:
            raise Stop(USAGE, f"--{k} is required")
    if "@" not in a["group"]:
        raise Stop(USAGE, "--group takes the name VCF SSO shows, NAME@DOMAIN")
    if not a["objects"]:
        raise Stop(USAGE, "--objects names at least one VM")
    if a["command"] == "check" and not a["outside"]:
        raise Stop(USAGE, "check needs --outside: one VM the team must not see, or the boundary is not tested")
    if a["command"] == "act" and not (a["object"] and a["action"]):
        raise Stop(USAGE, "act needs --object and --action")
    if set(a["objects"]) & set(a["outside"]):
        raise Stop(USAGE, "a VM cannot be in both --objects and --outside")
    return a


def main(argv, admin=None, member=None):
    try:
        a = parse(argv)
        cmd = a["command"]
        admin = admin or session("")
        if cmd in ("plan", "apply", "revoke"):
            sv = survey(admin, a)
            would, findings = judge(sv, a)
            print(f"{cmd}: team {a['team']}, group {a['group']}, {count(len(sv['objects']), 'VM')}, role {sv['role_name']}, scope {sv['scope_name']}")
            for f in findings:
                print(f"  finding: {f}")
            body = {"role": {k: v for k, v in sv["role"].items() if k != "privileges"} | {"privileges": len(sv["role"].get("privileges") or [])},
                    "recipe": {"privileges": len(sv["want"]), "actions": [action_privilege(x) for x in a["actions"]],
                               "recent_tasks": True, "api_write": a["api"]},
                    "scope": sv["scope"], "group": sv["group"], "in_source": bool(sv["in_source"]),
                    "vcf_roles": sv["vcf_roles"], "findings": findings}
            code = OK
            if cmd == "plan":
                for w in would:
                    print(f"  apply would: {w}")
                body["would"] = would
            elif cmd == "apply":
                if not a["execute"]:
                    for w in would:
                        print(f"  would: {w}")
                    print("  dry run: nothing sent; add --execute to send it")
                    body["would"] = would
                else:
                    sent, after, held = apply_writes(admin, sv, a)
                    for s in sent:
                        print(f"  sent: {s[0]} -> {s[1]}")
                    for k, v in held.items():
                        print(f"  {'held' if v else 'NOT HELD'}: {k.replace('_', ' ')}")
                    body.update({"sent": sent, "after": after, "held": held})
                    code = OK if all(held.values()) else NOT_HELD
            else:
                if not a["execute"]:
                    print(f"  would remove: this role's permission from the group{', the group import' if sv['group'].get('marked') else ''}, "
                          f"{'the role, ' if sv['role']['exists'] else ''}{'the scope' if sv['scope']['exists'] else ''}")
                    print("  dry run: nothing sent; add --execute to send it")
                else:
                    sent, after, held = revoke_writes(admin, sv, a)
                    for s in sent:
                        print(f"  sent: {s[0]} -> {s[1]}")
                    for k, v in held.items():
                        print(f"  {'held' if v else 'NOT HELD'}: {k.replace('_', ' ')}")
                    body.update({"sent": sent, "after": after, "held": held})
                    code = OK if all(held.values()) else NOT_HELD
            print(f"  record: {write_record(cmd, body, a)}")
            return code
        if cmd == "who":
            rows = who(admin, a["tasks"])
            for r in rows:
                print(f"  {r['task']}: {r.get('action')} {r.get('state')} by {r.get('submittedBy')} ({r.get('authSource')}) "
                      f"on {r.get('object')}" if r["read"] == 200 else f"  {r['task']}: read {r['read']}: {r.get('why')}")
            extra = [(r.get("submittedBy"), "person") for r in rows] + [(r.get("object"), "vm") for r in rows]
            print(f"  record: {write_record('who', {'tasks': rows}, a, extra)}")
            return OK if all(r["read"] == 200 for r in rows) else READ_FAILED
        member = member or session("MEMBER_")
        if cmd == "check":
            res = check(member, admin, a)
            for r in res["rows"]:
                print(f"  {'held' if r['held'] else 'NOT HELD'}: {r['check']}{' (' + r['object'] + ')' if r.get('object') else ''}: "
                      f"expected {r['expected']}, got {r['got']}{'; ' + r['message'] if r.get('message') and not r['held'] else ''}")
            print(f"  record: {write_record('check', res, a, [(res.get('member'), 'person')])}")
            return OK if all(r["held"] for r in res["rows"]) else NOT_HELD
        res = act(member, admin, a)
        print(f"  {a['action']} on {a['object']}: query {res['query']}, offered {res['offered']}"
              + (f", execute {res['execute']}, task {res.get('task')}" if "execute" in res else "")
              + (f", {res['status']['state']} by {res['status']['submittedBy']}" if res.get("status") else "")
              + (f"; {res['why']}" if res.get("why") else ""))
        if res.get("would_send"):
            print(f"  dry run: would send {res['would_send']}; add --execute to send it")
        extra = [((res.get("status") or {}).get("submittedBy"), "person")]
        print(f"  record: {write_record('act', res, a, extra)}")
        return OK if res["offered"] and (not a["execute"] or (res.get("status") or {}).get("state", "").startswith("COMPLETED")) else NOT_HELD
    except Stop as e:
        print(f"stopped: {e}", file=sys.stderr)
        return e.code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
