#!/usr/bin/env python3
"""parent_aware.py: prove, on your own instance, that a VM alert can stay quiet while its host carries a failure.

VCF Operations ships nothing that keeps a child's alert quiet while its parent fails (alerts.py, check 6, counts it on
your instance). The API can express it: a symptom set can point at the PARENT, and a reference inside it can be negated,
"!" before the symptom id, which the 9.1.1 API describes as a NOT EXISTS reference. This script builds the pattern with
throwaway objects, watches what the platform raises, and removes everything:

  S_vm      VirtualMachine symptom: summary|runtime|powerState EQ "Powered On", true on every running VM
  S_host    HostSystem symptom: summary|hostuuid EQ <host A's uuid>, true on host A only; it stands in for a failure
  control   VM alert: S_vm                                      should raise on the VM on host A and the VM on host B
  aware     VM alert: S_vm AND PARENT HostSystem [!S_host]      should raise on the VM on host B only
  rollup    host alert: CHILD VirtualMachine [S_vm], COUNT > 0  should raise once on each host, not once per VM

A throwaway custom group holds one running VM on each of two hosts, and the two hosts, under a throwaway policy that
inherits the default policy. All four objects must already be governed by the default policy, so for them nothing
changes but the three test alerts, and no other object is touched. INFORMATION severity throughout. Every object is
deleted in a finally block and read back absent.

Without --execute it picks the subjects, prints every body it would send, and changes nothing. With --execute it
refuses to start while an enabled notification rule could send the test alerts anywhere.

Run:
  export OPS_HOST=<operations-fqdn>  OPS_BROKER_HOST=<identity-broker-fqdn>  OPS_API_TOKEN=<api-token>
  export OPS_TLS_VERIFY=false                     # only on a self-signed lab CA
  export OPS_HOST_A=<host name>  OPS_HOST_B=<host name>   # optional; otherwise the first two that qualify
  python3 parent_aware.py                         # dry run: the subjects and the bodies
  python3 parent_aware.py --execute               # build, watch up to 25 minutes, remove; writes parent-aware.json
"""

import json
import os
import re
import sys
import time
import urllib.parse

from alerts import RULE_FILTERS, effective_policies, filter_size, policy_alert_entries
from opslib import bearer, ops

VM, HOST = ("VMWARE", "VirtualMachine"), ("VMWARE", "HostSystem")
CYCLE_S, WATCH_S, SETTLE_S = 60, 25 * 60, 2 * 300
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def call(method, path, tok, body=None, params=None, ok=(200, 201, 204)):
    st, out = ops(method, path, tok, body=body, params=params)
    if st not in ok:
        raise RuntimeError(f"{method} {path} answered {st}: {json.dumps(out)[:300]}")
    return out


def props(rid, tok):
    st, out = ops("GET", f"/api/resources/{rid}/properties", tok)
    return {p["name"]: p["value"] for p in (out or {}).get("property") or []}


def related(rid, which, tok, kind=None):
    st, out = ops("GET", f"/api/resources/{rid}/relationships/{which}", tok, params={"pageSize": 1000})
    return [r for r in (out or {}).get("resourceList") or [] if kind is None or r["resourceKey"]["resourceKindKey"] == kind]


def ancestors(rid, tok, depth=6):
    seen, frontier = set(), {rid}
    for _ in range(depth):
        frontier = {p["identifier"] for r in frontier for p in related(r, "parents", tok)} - seen
        if not frontier:
            break
        seen |= frontier
    return seen


def host_of(vm, tok):
    return next((r["identifier"] for r in related(vm, "parents", tok, "HostSystem")), None)


def subjects(tok, default_id):
    """Two hosts and one running VM under each, all four governed by the default policy."""
    st, out = ops("GET", "/api/resources", tok, params={"adapterKind": HOST[0], "resourceKind": HOST[1],
                                                        "pageSize": 1000, "_no_links": "true"})
    hosts = {r["resourceKey"]["name"]: r["identifier"] for r in (out or {}).get("resourceList") or []}
    wanted = [os.environ[k] for k in ("OPS_HOST_A", "OPS_HOST_B") if os.environ.get(k)]
    order = wanted or sorted(hosts)
    eff = effective_policies([hosts[h] for h in order if h in hosts], tok)
    picked = []
    for name in order:
        hid = hosts.get(name)
        if not hid or eff.get(hid) != default_id or "summary|hostuuid" not in props(hid, tok):
            continue
        vms = related(hid, "children", tok, "VirtualMachine")
        veff = effective_policies([v["identifier"] for v in vms], tok) if vms else {}
        vm = next((v["identifier"] for v in sorted(vms, key=lambda v: v["resourceKey"]["name"])
                   if veff.get(v["identifier"]) == default_id
                   and props(v["identifier"], tok).get("summary|runtime|powerState") == "Powered On"), None)
        if vm:
            picked.append((hid, vm))
        if len(picked) == 2:
            break
    if len(picked) < 2:
        raise SystemExit("no two hosts each with a running VM, all governed by the default policy; set OPS_HOST_A/B")
    (ha, vma), (hb, vmb) = picked
    return {"host_a": ha, "host_b": hb, "vm_a": vma, "vm_b": vmb}


def senders(tok, subject_ids):
    """Enabled rules that could send a test alert: no definition filter (the test definitions are new, so no
    definition filter can name them), and neither a kind filter that leaves out both test kinds nor a resource
    filter that names objects none of the subjects is, or descends from."""
    st, out = ops("GET", "/api/notifications/rules", tok, params={"_no_links": "true"})
    near = set(subject_ids).union(*[ancestors(s, tok) for s in subject_ids])
    risky = []
    for r in (out or {}).get("rules") or []:
        if not r.get("enabled") or filter_size(r.get("alertDefinitionIdFilters")):
            continue
        kinds = {k.get("resourceKind") for k in r.get("resourceKindFilters") or []} | {(r.get("resourceKindFilter") or {}).get("resourceKind")}
        kinds.discard(None)
        if kinds and not kinds & {VM[1], HOST[1]}:
            continue
        named = [f.get("resourceId") for f in (r.get("resourceFilters") or []) + [r.get("resourceFilter") or {}] if f.get("resourceId")]
        if named and not set(named) & near:
            continue
        risky.append({"filters": sorted(f for f in RULE_FILTERS if filter_size(r.get(f)))})
    return risky


def bodies(stamp, uuid_a):
    name = f"zz-throwaway parent-aware {stamp} - "
    s_vm = {"name": name + "vm-on", "adapterKindKey": VM[0], "resourceKindKey": VM[1], "waitCycles": 1, "cancelCycles": 1,
            "state": {"severity": "INFORMATION", "condition": {"type": "CONDITION_PROPERTY_STRING", "key": "summary|runtime|powerState",
                                                               "operator": "EQ", "stringValue": "Powered On", "instanced": False,
                                                               "thresholdType": "STATIC"}}}
    s_host = {"name": name + "host-a", "adapterKindKey": HOST[0], "resourceKindKey": HOST[1], "waitCycles": 1, "cancelCycles": 1,
              "state": {"severity": "INFORMATION", "condition": {"type": "CONDITION_PROPERTY_STRING", "key": "summary|hostuuid",
                                                                 "operator": "EQ", "stringValue": uuid_a, "instanced": False,
                                                                 "thresholdType": "STATIC"}}}
    self_vm = {"type": "SYMPTOM_SET", "relation": "SELF", "aggregation": "ALL", "symptomSetOperator": "AND",
               "symptomDefinitionIds": ["<S_vm>"]}
    sets = {
        "control": (VM, self_vm),
        "aware": (VM, {"type": "SYMPTOM_SET_COMPOSITE", "operator": "AND", "symptom-sets": [
            self_vm, {"type": "SYMPTOM_SET", "adapterKindKey": HOST[0], "resourceKindKey": HOST[1], "relation": "PARENT",
                      "aggregation": "ANY", "symptomSetOperator": "AND", "symptomDefinitionIds": ["!<S_host>"]}]}),
        "rollup": (HOST, {"type": "SYMPTOM_SET", "adapterKindKey": VM[0], "resourceKindKey": VM[1], "relation": "CHILD",
                          "aggregation": "COUNT", "populationOperator": "GT", "value": 0, "symptomSetOperator": "AND",
                          "symptomDefinitionIds": ["<S_vm>"]}),
    }
    alerts = {k: {"name": name + k, "description": "parent_aware.py throwaway", "adapterKindKey": kind[0],
                  "resourceKindKey": kind[1], "waitCycles": 1, "cancelCycles": 1, "type": 15, "subType": 19,
                  "states": [{"severity": "INFORMATION", "base-symptom-set": base,
                              "impact": {"impactType": "BADGE", "detail": "health"}}]}
              for k, (kind, base) in sets.items()}
    return name, s_vm, s_host, alerts


def fill(body, ids):
    text = json.dumps(body)
    for k, v in ids.items():
        text = text.replace(f"<{k}>", v)
    return json.loads(text)


def raised(alert_id, tok):
    st, out = ops("POST", "/api/alerts/query", tok, body={"alertDefinitionId": [alert_id], "activeOnly": True},
                  params={"page": 0, "pageSize": 500})
    return sorted({a["resourceId"] for a in (out or {}).get("alerts") or []})


def enable(alert_id, kind, policy_id, tok):
    """Switch the alert on in the throwaway policy, and read the policy back until it shows the alert set there."""
    for _ in range(5):
        call("PUT", f"/api/alertdefinitions/{alert_id}/enable?" + urllib.parse.urlencode({"policyId": [policy_id]}, doseq=True), tok)
        entries = policy_alert_entries(policy_id, tok) or []
        if any(e["policyKey"] == policy_id and e["alertId"] == alert_id and e["enabled"] and e["resourceKind"] == kind[1]
               for e in entries):
            return
        time.sleep(10)
    raise RuntimeError(f"alert {alert_id} never read back as enabled in the throwaway policy")


def main(argv):
    if argv not in ([], ["--execute"]):
        raise SystemExit("usage: parent_aware.py [--execute]")
    execute = argv == ["--execute"]
    tok = bearer()
    st, out = ops("GET", "/api/policies", tok, params={"_no_links": "true"})
    default_id = next(p["id"] for p in (out or {}).get("policySummaries") or [] if p.get("defaultPolicy"))
    sub = subjects(tok, default_id)
    label = {v: k.replace("_", " ") for k, v in sub.items()}
    uuid_a = props(sub["host_a"], tok)["summary|hostuuid"]
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    prefix, s_vm, s_host, alert_bodies = bodies(stamp, uuid_a)
    print("parent_aware.py: one running VM on each of two hosts, both hosts, all governed by the default policy")
    print(f"  the alert bodies, as they will be sent (<S_vm> and <S_host> become the new symptoms' ids):")
    for k, b in alert_bodies.items():
        print(f"    {k}: {json.dumps(b['states'][0]['base-symptom-set'])}")
    risky = senders(tok, list(sub.values()))
    if not execute:
        print(f"\n  {len(risky)} enabled notification rule(s) could send a test alert"
              + ("; --execute will refuse until they cannot" if risky else ""))
        print("dry run: nothing was created; rerun with --execute")
        return 0
    if risky:
        raise SystemExit(f"refusing: {len(risky)} enabled notification rule(s) could send a test alert: {risky}")

    rec = {"captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "observations": [], "cleanup": {}}
    made = {}
    hosts_at_start = {k: host_of(sub[k], tok) == sub[k.replace("vm", "host")] for k in ("vm_a", "vm_b")}
    try:
        g = call("POST", "/api/resources/groups", tok, body={
            "resourceKey": {"name": prefix + "group", "adapterKindKey": "Container", "resourceKindKey": "Environment"},
            "autoResolveMembership": True,
            "membershipDefinition": {"includedResources": list(sub.values()), "excludedResources": [], "rules": []}})
        made["group"] = g["id"]
        p = call("POST", "/api/policies", tok, body={"name": prefix + "policy", "description": "parent_aware.py throwaway",
                                                     "parentPolicy": default_id})
        made["policy"] = p["id"]
        call("PUT", f"/api/policies/{made['policy']}/assign", tok, body={"groupIds": [made["group"]]})
        made["symptom:vm"] = call("POST", "/api/symptomdefinitions", tok, body=s_vm)["id"]
        made["symptom:host"] = call("POST", "/api/symptomdefinitions", tok, body=s_host)["id"]
        ids = {"S_vm": made["symptom:vm"], "S_host": made["symptom:host"]}
        for k, b in alert_bodies.items():
            made["alert:" + k] = call("POST", "/api/alertdefinitions", tok, body=fill(b, ids))["id"]
            enable(made["alert:" + k], VM if b["resourceKindKey"] == VM[1] else HOST, made["policy"], tok)
        built = time.time()
        time.sleep(30)
        eff = effective_policies(list(sub.values()), tok)
        rec["governedByTheThrowawayPolicy"] = all(eff.get(v) == made["policy"] for v in sub.values())
        settled = None
        while time.time() - built < WATCH_S:
            time.sleep(CYCLE_S)
            obs = {"after_s": round(time.time() - built)}
            for k in ("control", "aware", "rollup"):
                obs[k] = [label.get(x, "another object") for x in raised(made["alert:" + k], tok)]
            rec["observations"].append(obs)
            print(f"  {obs}")
            if settled is None and {"vm a", "vm b"} <= set(obs["control"]) and "vm b" in obs["aware"]:
                settled = time.time()
            if settled and time.time() - settled >= SETTLE_S:
                break
        rec["stayedOnTheirHosts"] = all(hosts_at_start.values()) and all(
            host_of(sub[k], tok) == sub[k.replace("vm", "host")] for k in ("vm_a", "vm_b"))
    finally:
        for k in [k for k in made if k.startswith("alert:")]:
            rec["cleanup"][k] = ops("DELETE", f"/api/alertdefinitions/{made[k]}", tok)[0]
        for k in [k for k in made if k.startswith("symptom:")]:
            rec["cleanup"][k] = ops("DELETE", f"/api/symptomdefinitions/{made[k]}", tok)[0]
        if "policy" in made and "group" in made:
            ops("PUT", f"/api/policies/{made['policy']}/unassign", tok, body={"groupIds": [made["group"]]})
        if "policy" in made:
            rec["cleanup"]["policy"] = ops("DELETE", f"/api/policies/{made['policy']}", tok)[0]
        if "group" in made:
            rec["cleanup"]["group"] = ops("DELETE", f"/api/resources/groups/{made['group']}", tok)[0]
        residue = []
        for k, v in made.items():
            path = {"alert": "/api/alertdefinitions/", "symptom": "/api/symptomdefinitions/",
                    "group": "/api/resources/groups/"}.get(k.split(":")[0])
            if path and ops("GET", path + v, tok)[0] == 200:
                residue.append(k)
        st, out = ops("GET", "/api/policies", tok, params={"_no_links": "true"})
        if "policy" in made and any(p["id"] == made["policy"] for p in (out or {}).get("policySummaries") or []):
            residue.append("policy")
        rec["residue"] = residue
        print(f"  removed everything it made; residue: {residue or 'none'}")

    seen = rec["observations"]
    last = seen[-1] if seen else {}
    first = next((o["after_s"] for o in seen if o["control"]), None)
    rec["verdict"] = {
        "controlOnBothVms": {"vm a", "vm b"} <= set(last.get("control", [])),
        "awareQuietUnderTheMarkedHost": bool(last) and "vm a" not in last.get("aware", []),
        "awareRaisedUnderTheOtherHost": "vm b" in last.get("aware", []),
        "rollupOncePerHost": sorted(last.get("rollup", [])) == ["host a", "host b"],
        "nothingOutsideTheGroup": not any("another object" in o[k] for o in seen for k in ("control", "aware", "rollup")),
        "samplesAfterSettling": sum(1 for o in seen if {"vm a", "vm b"} <= set(o["control"])),
        "firstRaiseAfterSeconds": first,
    }
    rec["bodies"] = {k: b["states"][0]["base-symptom-set"] for k, b in alert_bodies.items()}
    held = all(v for k, v in rec["verdict"].items() if k not in ("samplesAfterSettling", "firstRaiseAfterSeconds"))
    rec["held"] = held and not rec["residue"]
    text = UUID.sub("{{id}}", json.dumps(rec, indent=1))
    text = text.replace(uuid_a, "{{host-a-uuid}}")
    for var in ("OPS_HOST", "OPS_BROKER_HOST", "OPS_HOST_A", "OPS_HOST_B"):
        v = os.environ.get(var)
        assert not v or v not in text, f"{var} reached the record"
    out_dir = os.environ.get("OUT_DIR", ".")
    os.makedirs(out_dir, exist_ok=True)
    open(os.path.join(out_dir, "parent-aware.json"), "w", encoding="utf-8").write(text + "\n")
    print(f"\n  {'HELD' if rec['held'] else 'DID NOT HOLD'}: {rec['verdict']}")
    print("wrote parent-aware.json; hosts and VMs are labels, never names")
    return 0 if rec["held"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
