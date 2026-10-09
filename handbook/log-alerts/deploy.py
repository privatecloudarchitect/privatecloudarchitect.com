#!/usr/bin/env python3
"""deploy.py: put a bundle of log alerts on VCF Operations 9.1.1, switched on for one custom group only.

  python3 deploy.py plan     --scope scope.json [--bundle FILE] [--only SP-02,SP-08]
  python3 deploy.py apply    --scope scope.json [--bundle FILE] [--only IDS] --yes
  python3 deploy.py status   --scope scope.json [--bundle FILE] [--out DIR]
  python3 deploy.py teardown --scope scope.json [--bundle FILE] [--all] --yes

`plan` writes nothing: it checks the bundle against the rules the 9.1.1 API enforces and prints every request.
`apply` is idempotent by name. It creates the scope's custom group (the hosts under the clusters the scope names)
and a policy that inherits from the scope's parent, so the members keep every other setting; then the log symptoms
the chosen alerts need; waits until Log Management lists a monitor for each; creates the alerts; switches each one on
in the scope's policy, and off in any policy the scope lists under `disableIn`; and reads each alert's monitors back,
switching the alert off and on until they read enabled. A second run changes nothing and says so. `status` reads the
group, the policy, every alert and its monitors, and how many alerts each has raised. `teardown` removes the scope's
policy and group; with `--all` it also deletes the bundle's alert and symptom definitions, which every scope shares.

Why the read-back: on 9.1.1 the first switch-on of a new alert has left the monitors of its new symptoms disabled,
even with every monitor already built, and they stay disabled while VCF Operations reads the alert as enabled; one
switch off and on enabled them. A policy that shows an alert enabled is not proof it can fire; an enabled monitor is.

Writes refuse to run without --yes. Names follow `<Owner> - <Bundle> - <Kind> - <Condition>` for definitions and
`<Owner> - <Bundle> - <Scope>` for the policy, with the owner from the scope file. Standard library only; the
environment is lmlib.py's.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUNDLE = HERE / "bundle" / "storage-path-health.json"
STRING_FIELDS = {"vc_event_type", "appname", "text", "hostname", "vmw_cluster", "vmw_vcenter", "vmw_datacenter"}
WINDOWS = (5, 15, 30, 60, 360)
SEVERITY = {"CRITICAL": "CRITICAL", "IMMEDIATE": "IMMEDIATE", "WARNING": "WARNING", "INFORMATION": "INFORMATION",
            "SYMPTOM_BASED": "AUTO"}


# ---------------------------------------------------------------- the bundle, as data (no network)
def load(path: Path = BUNDLE) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def definition_name(b: dict, owner: str, condition: str) -> str:
    return f"{owner} - {b['bundle']} - {b['kind']['label']} - {condition}"


def scope_names(b: dict, scope: dict) -> tuple[str, str]:
    """The scope's custom group and policy: `<Owner> - <Bundle> - <Scope> (Hosts)` and `<Owner> - <Bundle> - <Scope>`."""
    base = f"{scope['owner']} - {b['bundle']} - {scope['scope']}"
    return f"{base} ({b['kind']['label']}s)", base


def check(b: dict) -> list[str]:
    """The ways a bundle breaks what the 9.1.1 API accepts or what fires on it. An empty list means it passes."""
    out: list[str] = []
    keys = {s["key"] for s in b["symptoms"]}
    used: set[str] = set()
    for a in b["alerts"]:
        refs = a.get("anyOf") or [k for group in a.get("allOf") or [] for k in group]
        if not refs:
            out.append(f"{a['id']}: names no symptom")
        for k in refs:
            if k not in keys:
                out.append(f"{a['id']}: names {k}, which the bundle does not declare")
        used |= set(refs)
    for s in b["symptoms"]:
        k, fields = s["key"], {f["field"] for f in s["filters"]}
        if k not in used:
            out.append(f"{k}: no alert uses it")
        for f in s["filters"]:
            if f["field"] in STRING_FIELDS and f["operator"] != "CONTAINS":
                out.append(f"{k}: {f['operator']} on {f['field']}; 9.1.1 refuses EQUAL on a string field, so the exact "
                           "form is CONTAINS with the complete value")
            if not f["values"] or any(not str(v).strip() for v in f["values"]):
                out.append(f"{k}: an empty value on {f['field']}")
        if "hostname" in fields:
            out.append(f"{k}: a hostname condition; scope by policy and inventory fields, never by names")
        if "text" in fields and "appname" not in fields:
            out.append(f"{k}: a text condition with no appname; words and identifiers collide across products")
        t = s["trigger"]
        if (t["function"], t["operator"]) != ("COUNT", "GREATER_THAN"):
            out.append(f"{k}: {t['function']} {t['operator']}; on 9.1.1 a COUNT below a threshold never raised and a "
                       "UNIQUE_COUNT symptom got no monitor; only COUNT above a threshold fires")
        if t["windowMinutes"] not in WINDOWS:
            out.append(f"{k}: a {t['windowMinutes']}-minute window; the trigger takes 5, 15, 30, 60 or 360")
    if int(b.get("autoCancelMinutes", 0)) < 1:
        out.append("autoCancelMinutes: a log symptom is refused unless it is at least 1")
    return out


def symptom_body(b: dict, s: dict, owner: str) -> dict:
    """`POST /api/symptomdefinitions` for one log symptom (a CONDITION_LOG condition on the bundle's object kind).

    A log symptom carries no wait or cancel cycles (9.1.1 refuses any) and an autoCancelTime of at least 1."""
    t = s["trigger"]
    return {
        "name": definition_name(b, owner, s["condition"]),
        "adapterKindKey": b["kind"]["adapterKind"],
        "resourceKindKey": b["kind"]["resourceKind"],
        "waitCycles": None,
        "cancelCycles": None,
        "state": {
            "severity": s["severity"],
            "condition": {
                "type": "CONDITION_LOG",
                "logQueryFilters": {
                    "logQueryFiltersOperator": "AND",
                    "logQueryFilterConditions": [
                        {"conditionField": f["field"], "queryFilterConditionOperatorType": f["operator"],
                         "conditionValues": list(f["values"])}
                        for f in s["filters"]
                    ],
                },
                "logTriggerCondition": {
                    "functionType": t["function"],
                    "operatorType": t["operator"],
                    "value": float(t["value"]),
                    "timeInterval": int(t["windowMinutes"]),
                    "groupBy": list(t.get("groupBy") or []),
                },
                "queryTexts": [],
                "autoCancelTime": int(b["autoCancelMinutes"]),
            },
        },
    }


def _symptom_set(ids: list[str]) -> dict:
    return {"type": "SYMPTOM_SET", "relation": "SELF", "aggregation": "ALL", "symptomSetOperator": "OR",
            "symptomDefinitionIds": ids}


def alert_body(b: dict, a: dict, ids: dict[str, str], owner: str) -> dict:
    """`POST /api/alertdefinitions`: `anyOf` is one OR set of symptoms; `allOf` is an AND of OR sets, all on one object."""
    if a.get("anyOf"):
        base = _symptom_set([ids[k] for k in a["anyOf"]])
    else:
        base = {"type": "SYMPTOM_SET_COMPOSITE", "operator": "AND",
                "symptom-sets": [_symptom_set([ids[k] for k in group]) for group in a["allOf"]]}
    return {
        "name": definition_name(b, owner, a["condition"]),
        "description": f"{a['detects'][0].upper()}{a['detects'][1:]}. Log based; runbook {b['runbook']}, section "
                       f"{a['runbook']}. This alert informs; it does not act.",
        "adapterKindKey": b["kind"]["adapterKind"],
        "resourceKindKey": b["kind"]["resourceKind"],
        "waitCycles": 1,
        "cancelCycles": 1,
        "type": 18,
        "subType": 18,
        "states": [{"severity": SEVERITY[a["criticality"]], "base-symptom-set": base,
                    "impact": {"impactType": "BADGE", "detail": "health"}}],
    }


def group_body(b: dict, scope: dict) -> dict:
    """`POST /api/resources/groups`: every object of the bundle's kind under the clusters the scope names."""
    kind = {"resourceKind": b["kind"]["resourceKind"], "adapterKind": b["kind"]["adapterKind"]}
    return {
        "resourceKey": {"name": scope_names(b, scope)[0], "adapterKindKey": "Container",
                        "resourceKindKey": "Environment", "resourceIdentifiers": []},
        "autoResolveMembership": True,
        "membershipDefinition": {
            "includedResources": [], "excludedResources": [],
            "rules": [{"resourceKindKey": kind, "statConditionRules": [], "propertyConditionRules": [],
                       "resourceNameConditionRules": [], "resourceTagConditionRules": [],
                       "relationshipConditionRules": [{"relation": "DESCENDANT", "name": c, "compareOperator": "EQ"}]}
                      for c in scope["clusters"]],
        },
    }


def chosen(b: dict, only: set[str] | None) -> list[dict]:
    alerts = [a for a in b["alerts"] if only is None or a["id"] in only]
    unknown = (only or set()) - {a["id"] for a in b["alerts"]}
    if unknown:
        raise SystemExit(f"unknown alert ids: {sorted(unknown)}")
    return alerts


def needed(alerts: list[dict]) -> list[str]:
    keys: list[str] = []
    for a in alerts:
        for k in a.get("anyOf") or [x for g in a.get("allOf") or [] for x in g]:
            if k not in keys:
                keys.append(k)
    return keys


# ---------------------------------------------------------------- the platform
def find(s, kind: str, name: str) -> dict | None:
    """The group, policy or symptom definition with exactly this name, or None (alerts: `alert_index`)."""
    if kind == "group":
        groups = s.must("GET", "/api/resources/groups", params={"includePolicy": "false", "_no_links": "true"})
        return next((g for g in groups.get("groups") or [] if g["resourceKey"]["name"] == name), None)
    if kind == "policy":
        policies = s.must("GET", "/api/policies", params={"_no_links": "true"}).get("policySummaries") or []
        return next((p for p in policies if p["name"] == name), None)
    if kind == "symptom":  # the name parameter narrows on the server (a substring); the match here is exact
        return next((x for x in s.paged("/api/symptomdefinitions", "symptomDefinitions", {"name": name})
                     if x["name"] == name), None)
    raise ValueError(kind)


def alert_index(s, b: dict) -> dict[str, dict]:
    """Every alert definition of the bundle's object kind, by name: one read of every page, not one per alert."""
    return {x["name"]: x for x in s.paged("/api/alertdefinitions", "alertDefinitions",
                                         {"adapterKind": b["kind"]["adapterKind"], "resourceKind": b["kind"]["resourceKind"]})}


def wait_for_monitors(s, names: list[str], *, enabled: bool | None, timeout_s: int = 180) -> dict[str, bool | None]:
    """Poll Log Management until every named monitor exists (and, if `enabled` is set, reads that state)."""
    deadline = time.time() + timeout_s
    while True:
        mons = s.monitors()
        if all(n in mons and (enabled is None or mons[n] is enabled) for n in names) or time.time() > deadline:
            return {n: mons.get(n) for n in names}
        time.sleep(10)


def switch(s, alert_id: str, policy_id: str, on: bool) -> None:
    """Switch one alert on or off in one policy. The state lives in each policy; this is the only alert toggle."""
    s.must("PUT", f"/api/alertdefinitions/{alert_id}/{'enable' if on else 'disable'}", params={"policyId": policy_id})


def switch_on_until_monitors_enabled(s, alert_id: str, policy_id: str, monitor_names: list[str]) -> int:
    """Switch the alert on, then read its monitors; off and on again until they read enabled. Returns the attempt."""
    switch(s, alert_id, policy_id, True)
    for attempt in range(1, 4):
        state = wait_for_monitors(s, monitor_names, enabled=True, timeout_s=90)
        if all(state.values()):
            return attempt
        print(f"  monitors not enabled {state}; switching the alert off and on")
        switch(s, alert_id, policy_id, False)
        time.sleep(15)
        switch(s, alert_id, policy_id, True)
    raise SystemExit("the monitors never read enabled; stop and check Log Management before going further")


def apply(s, b: dict, scope: dict, alerts: list[dict]) -> dict:
    owner = scope["owner"]
    group_name, policy_name = scope_names(b, scope)
    made = {"created": 0, "unchanged": 0}

    alerts_now = alert_index(s, b)

    def ensure(kind: str, name: str, create) -> dict:
        found = alerts_now.get(name) if kind == "alert" else find(s, kind, name)
        if found:
            made["unchanged"] += 1
            return found
        made["created"] += 1
        print(f"create {kind} {name}")
        return create()

    parent = find(s, "policy", scope["parentPolicy"])
    if parent is None:
        raise SystemExit(f"the parent policy {scope['parentPolicy']!r} does not exist")
    group = ensure("group", group_name, lambda: s.must("POST", "/api/resources/groups", group_body(b, scope)))
    members = s.paged(f"/api/resources/groups/{group['id']}/members", "resourceList")
    print(f"group {group_name}: {len(members)} members")
    if not members:
        raise SystemExit("the group resolved no members; check the scope's cluster names before going further")
    policy = ensure("policy", policy_name, lambda: s.must(
        "POST", "/api/policies", {"name": policy_name, "description": f"{b['bundle']} log alerts, scope {scope['scope']}",
                                  "parentPolicy": parent["id"]}))
    s.must("PUT", f"/api/policies/{policy['id']}/assign", {"groupIds": [group["id"]]})
    keyed = {x["key"]: x for x in b["symptoms"]}
    ids: dict[str, str] = {}
    for k in needed(alerts):
        body = symptom_body(b, keyed[k], owner)
        ids[k] = ensure("symptom", body["name"], lambda body=body: s.must("POST", "/api/symptomdefinitions", body))["id"]
    monitor = {k: definition_name(b, owner, keyed[k]["condition"]) for k in ids}
    present = wait_for_monitors(s, list(monitor.values()), enabled=None)
    print(f"monitors present: {sum(v is not None for v in present.values())} of {len(present)}")
    policies = {p["name"]: p for p in s.must("GET", "/api/policies", params={"_no_links": "true"}).get("policySummaries") or []}
    for a in alerts:
        body = alert_body(b, a, ids, owner)
        alert = ensure("alert", body["name"], lambda body=body: s.must("POST", "/api/alertdefinitions", body))
        for name in scope.get("disableIn") or []:
            switch(s, alert["id"], policies[name]["id"], False)
        mine = [monitor[k] for k in a.get("anyOf") or [x for g in a.get("allOf") or [] for x in g]]
        attempt = switch_on_until_monitors_enabled(s, alert["id"], policy["id"], mine)
        print(f"{a['id']}: on in {policy_name}, monitors enabled {len(mine)} of {len(mine)} (attempt {attempt})")
    print(f"apply: {made['created']} created, {made['unchanged']} unchanged")
    return made


def status(s, b: dict, scope: dict, alerts: list[dict]) -> dict:
    owner = scope["owner"]
    group_name, policy_name = scope_names(b, scope)
    group, policy = find(s, "group", group_name), find(s, "policy", policy_name)
    members = len(s.paged(f"/api/resources/groups/{group['id']}/members", "resourceList")) if group else 0
    print(f"group {group_name}: {'present, ' + str(members) + ' members' if group else 'absent'}")
    print(f"policy {policy_name}: {'present' if policy else 'absent'}")
    mons = s.monitors()
    keyed = {x["key"]: x for x in b["symptoms"]}
    rows, index = [], alert_index(s, b)
    for a in alerts:
        found = index.get(definition_name(b, owner, a["condition"]))
        mine = [definition_name(b, owner, keyed[k]["condition"]) for k in a.get("anyOf") or [x for g in a.get("allOf") or [] for x in g]]
        on = sum(1 for n in mine if mons.get(n) is True)
        raised = 0
        if found:
            q = s.must("POST", "/api/alerts/query", {"alertDefinitionId": [found["id"]], "activeOnly": False},
                       params={"page": 0, "pageSize": 1})
            raised = int(((q or {}).get("pageInfo") or {}).get("totalCount", 0))
        rows.append({"id": a["id"], "present": bool(found), "monitors": len(mine), "monitorsEnabled": on, "raised": raised})
        print(f"{a['id']}: {'present' if found else 'absent'}, monitors enabled {on} of {len(mine)}, alerts raised {raised} (any status)")
    return {"group": bool(group), "members": members, "policy": bool(policy), "alerts": rows}


def teardown(s, b: dict, scope: dict, everything: bool) -> dict:
    owner = scope["owner"]
    group_name, policy_name = scope_names(b, scope)
    done: dict[str, int] = {"deleted": 0, "absent": 0}

    def gone(found, path: str, label: str) -> None:
        if not found:
            done["absent"] += 1
            return
        st, _ = s.ops("DELETE", path.format(id=found["id"]))
        print(f"delete {label}: HTTP {st}")
        done["deleted"] += 1

    policy, group = find(s, "policy", policy_name), find(s, "group", group_name)
    if policy and group:
        s.must("PUT", f"/api/policies/{policy['id']}/unassign", {"groupIds": [group["id"]]})
    gone(policy, "/api/policies/{id}", f"policy {policy_name}")
    gone(group, "/api/resources/groups/{id}", f"group {group_name}")
    if everything:
        index = alert_index(s, b)
        for a in b["alerts"]:  # alerts before the symptoms they reference
            name = definition_name(b, owner, a["condition"])
            gone(index.get(name), "/api/alertdefinitions/{id}", f"alert {name}")
        for x in b["symptoms"]:
            name = definition_name(b, owner, x["condition"])
            gone(find(s, "symptom", name), "/api/symptomdefinitions/{id}", f"symptom {name}")
    left = [n for n, k in ((policy_name, "policy"), (group_name, "group")) if find(s, k, n)]
    if everything:
        index = alert_index(s, b)
        left += [n for n in (definition_name(b, owner, x["condition"]) for x in b["alerts"]) if n in index]
        left += [n for n in (definition_name(b, owner, x["condition"]) for x in b["symptoms"]) if find(s, "symptom", n)]
    print(f"teardown: {done['deleted']} deleted, {done['absent']} already absent, {len(left)} left behind")
    return {**done, "left": len(left)}


# ---------------------------------------------------------------- the command line
def parse_args(argv: list[str]) -> dict:
    if not argv or argv[0] not in ("plan", "apply", "status", "teardown"):
        raise SystemExit(__doc__)
    a = {"cmd": argv[0], "scope": None, "bundle": BUNDLE, "only": None, "yes": False, "all": False, "out": None}
    rest = argv[1:]
    while rest:
        x = rest.pop(0)
        if x in ("--scope", "--bundle", "--out") and rest:
            a[x[2:]] = Path(rest.pop(0))
        elif x == "--only" and rest:
            a["only"] = {i.strip() for i in rest.pop(0).split(",") if i.strip()}
        elif x in ("--yes", "--all"):
            a[x[2:]] = True
        else:
            raise SystemExit(f"unknown argument {x!r}")
    if a["scope"] is None:
        raise SystemExit("--scope <scope.json> is required")
    if a["cmd"] in ("apply", "teardown") and not a["yes"]:
        raise SystemExit(f"{a['cmd']} writes to VCF Operations; read `plan` first, then rerun with --yes")
    return a


def main(argv: list[str]) -> int:
    a = parse_args(argv)
    b, scope = load(a["bundle"]), json.loads(a["scope"].read_text(encoding="utf-8"))
    problems = check(b)
    for p in problems:
        print("rule:", p)
    if problems:
        raise SystemExit(f"{len(problems)} rule(s) broken; fix the bundle first")
    alerts = chosen(b, a["only"])
    if a["cmd"] == "plan":
        group_name, policy_name = scope_names(b, scope)
        print(f"group {group_name!r}: {b['kind']['label']}s under {scope['clusters']}")
        print(f"policy {policy_name!r}, inheriting {scope['parentPolicy']!r}; off in {scope.get('disableIn') or []}")
        keyed = {x["key"]: x for x in b["symptoms"]}
        for k in needed(alerts):
            print("symptom", json.dumps(symptom_body(b, keyed[k], scope["owner"])))
        stand_in = {k: f"<id of {k}>" for k in needed(alerts)}
        for x in alerts:
            print("alert", json.dumps(alert_body(b, x, stand_in, scope["owner"])))
        print(f"plan: {len(needed(alerts))} symptoms, {len(alerts)} alerts, 0 rules broken")
        return 0
    from lmlib import Scrubber, Session  # the network, only past this point

    s = Session()
    if a["cmd"] == "apply":
        apply(s, b, scope, alerts)
    elif a["cmd"] == "teardown":
        teardown(s, b, scope, a["all"])
    else:
        result = status(s, b, scope, alerts)
        if a["out"]:
            scrub = Scrubber()
            scrub.add(scope["scope"], "scope")
            for c in scope["clusters"]:
                scrub.add(c, "cluster")
            a["out"].mkdir(parents=True, exist_ok=True)
            out = a["out"] / "deploy-status.record.json"
            scrub.write(out, {"read_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "bundle": b["bundle"],
                              "scope": scope["scope"], **result})
            print(f"wrote {out.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
