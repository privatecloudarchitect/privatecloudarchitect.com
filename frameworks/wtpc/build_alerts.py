#!/usr/bin/env python3
"""WTPC alert generator - posture prod-latency-critical-db (the "now clock").

Reads the portable declarative source (alerts.yaml) + the built super-metric record (supermetrics.yaml)
and emits import-ready VCF Ops symptom + alert definitions:
  - content/wtpc-alerts.symptoms.json  ({"symptomDefinitions": [...]}, POST /api/symptomdefinitions)
  - content/wtpc-alerts.alerts.json    ({"alertDefinitions":   [...]}, POST /api/alertdefinitions)

Super metrics are referenced by KEY in alerts.yaml; this resolves them to minted sm ids (the same
portable pattern as build_views.py). Symptom + alert ids are deterministic slugs, so re-import updates
in place. Schema shapes are hydrated from the live instance's built-in definitions (CONDITION_HT for a
super-metric threshold - real analog "Metrics|Violations GT 0.0"; CONDITION_PROPERTY_NUMERIC for the
floor dasConfig/drsConfig properties), so what this emits imports the same way.

SCOPING (BLOCK invariant): these definitions carry NO group - they are enabled in the WTPC policy ONLY,
which is what scopes them to posture members (never "all objects"). This generator does NOT enable them
anywhere; enablement is the operator's controlled, posture-scoped step. NOTIFICATIONS are out of scope
(Ops-only). Both facts are asserted from alerts.yaml at validate().

Usage:  python build_alerts.py        (from deploy/vcf-ops-content/wtpc/; no live API calls)
"""
import json
import os
import re

from lib._sm import SM_STAT_KEY_RE, load_sm_ids, sm_stat_key

HERE = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.join(HERE, "content")
ALERTS_YAML = os.path.join(HERE, "alerts.yaml")
OUT_SYMPTOMS = os.path.join(CONTENT, "wtpc-alerts.symptoms.json")
OUT_ALERTS = os.path.join(CONTENT, "wtpc-alerts.alerts.json")

# Shared SM ids come from the instance record adopt_shared.py emits (ids mint per instance);
# alerts.yaml references them by key as "Shared:<KEY>".
SHARED_RECORD = os.path.join(HERE, "supermetrics.shared.yaml")


def shared_ids():
    if not os.path.exists(SHARED_RECORD):
        raise SystemExit("supermetrics.shared.yaml not found - run adopt_shared.py first")
    return {e["key"]: e["id"] for e in load_yaml(SHARED_RECORD)["supermetrics"]}

VALID_SEVERITY = {"CRITICAL", "WARNING", "IMMEDIATE", "INFO"}
VALID_OPERATOR = {"GT", "LT", "LT_EQ", "EQ", "NOT_EQ"}      # live CONDITION_HT / PROPERTY operator enum
VALID_KINDS = {"VirtualMachine", "HostSystem", "ClusterComputeResource"}   # per-alert resource_kind (two-unit)
IMPACT_DETAIL = {"risk", "health", "efficiency"}            # BADGE detail
ALERT_TYPE, ALERT_SUBTYPE = 16, 18                          # observed valid VMWARE combo (Virtualization)


def slug(s):
    return re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-")


def load_yaml(path):
    import yaml
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def sm_id(key, sm, shared):
    """Resolve an alerts.yaml SM reference (a posture key like 'R1' or 'Shared:<KEY>') to a minted id."""
    if key.startswith("Shared:"):
        short = key.split(":", 1)[1]
        if short not in shared:
            raise SystemExit(f"unknown Shared SM ref {key} (not in supermetrics.shared.yaml)")
        return shared[short]
    if key not in sm:
        raise SystemExit(f"alerts.yaml references SM key {key!r} not in supermetrics.yaml")
    return sm[key]


def build_symptom(sym_id, name, resource_kind, severity, wait_cycles, condition):
    return {"id": sym_id, "name": name, "adapterKindKey": "VMWARE", "resourceKindKey": resource_kind,
            "waitCycles": wait_cycles, "cancelCycles": 1,
            "state": {"severity": severity, "condition": condition}}


def ht_condition(sm_key_id, operator, value):
    return {"type": "CONDITION_HT", "key": sm_stat_key(sm_key_id), "operator": operator,
            "value": f"{float(value):g}", "valueType": "NUMERIC", "instanced": False,
            "thresholdType": "STATIC"}


def property_numeric_condition(key, operator, value):
    return {"type": "CONDITION_PROPERTY_NUMERIC", "key": key, "operator": operator,
            "value": float(value), "instanced": False, "thresholdType": "STATIC"}


def build(doc, sm, shared):
    default_kind = doc["resource_kind"]
    symptoms, alerts = [], []
    for a in doc["alerts"]:
        # per-alert resource_kind (falls back to the doc default): the two-unit model needs the WORKLOAD
        # alert (Performance) on VirtualMachine so it fires on the VM under its posture policy regardless of
        # the cluster's tier policy, while the HARDWARE alerts stay cluster-scoped. Symptoms inherit it.
        a_kind = a.get("resource_kind", default_kind)
        severity = a["severity"]
        wait = int(a["wait_cycles"])
        aslug = slug(a["name"])
        sym_ids = []
        for i, s in enumerate(a["symptoms"], 1):
            sid = f"SymptomDefinition-{aslug}-{i}"
            if "sm" in s:
                cond = ht_condition(sm_id(s["sm"], sm, shared), s["operator"], s["value"])
            elif "property_numeric" in s:
                cond = property_numeric_condition(s["property_numeric"], s["operator"], s["value"])
            else:
                raise SystemExit(f"symptom {s.get('label')!r} has neither 'sm' nor 'property_numeric'")
            # persistence lives at the symptom layer; the alert set fires on 1 cycle of the symptom
            symptoms.append(build_symptom(sid, f"PCA - WTPC - {s['label']}", a_kind, severity, wait, cond))
            sym_ids.append(sid)
        alert = {
            "id": f"AlertDefinition-{aslug}", "name": a["name"], "description": a["rationale"],
            "adapterKindKey": "VMWARE", "resourceKindKey": a_kind,
            "waitCycles": 1, "cancelCycles": 1, "type": ALERT_TYPE, "subType": ALERT_SUBTYPE,
            "states": [{
                "severity": severity,
                "base-symptom-set": {"type": "SYMPTOM_SET", "relation": "SELF",
                                     "symptomSetOperator": a.get("symptom_operator", "OR"),
                                     "symptomDefinitionIds": sym_ids, "alertConditions": []},
                "impact": {"impactType": "BADGE", "detail": a["impact"]},
            }],
            "forVCDTenants": False,
        }
        alerts.append(alert)
    return symptoms, alerts


def validate(doc, symptoms, alerts):
    assert len(alerts) == len(doc["alerts"]), "alert count mismatch"
    # scoping invariant: policy-enablement (never all-objects) + notifications out of scope
    assert doc.get("scoping") == "policy-enablement", "scoping MUST be policy-enablement (BLOCK: no all-objects)"
    assert doc.get("notifications") == "out-of-scope", "notifications MUST be out-of-scope (outbound invariant)"
    sym_by_id = {s["id"]: s for s in symptoms}
    for s in symptoms:
        c = s["state"]["condition"]
        assert s["state"]["severity"] in VALID_SEVERITY, f"{s['id']}: bad severity"
        assert c["operator"] in VALID_OPERATOR, f"{s['id']}: bad operator {c['operator']}"
        if c["type"] == "CONDITION_HT":
            m = SM_STAT_KEY_RE.match(c["key"])
            assert m, f"{s['id']}: unresolved SM key {c['key']!r}"
        assert s["resourceKindKey"] in VALID_KINDS and s["adapterKindKey"] == "VMWARE"
    for a in alerts:
        st = a["states"][0]
        assert st["severity"] in VALID_SEVERITY
        assert st["impact"]["detail"] in IMPACT_DETAIL, f"{a['id']}: bad impact"
        ids = st["base-symptom-set"]["symptomDefinitionIds"]
        assert ids and all(i in sym_by_id for i in ids), f"{a['id']}: dangling symptom ref"
        assert st["base-symptom-set"]["symptomSetOperator"] in ("AND", "OR")
        assert a["resourceKindKey"] in VALID_KINDS
        # vROps requires each symptom's resource kind to MATCH its alert's kind
        assert all(sym_by_id[i]["resourceKindKey"] == a["resourceKindKey"] for i in ids), \
            f"{a['id']}: a symptom's resource_kind differs from the alert's ({a['resourceKindKey']})"
    # no group / all-objects field anywhere in the emitted defs
    blob = json.dumps(symptoms) + json.dumps(alerts)
    assert "resourceId" not in blob and "groupId" not in blob, "a definition carries an object/group scope — must be policy-scoped only"
    return {"symptoms": len(symptoms), "alerts": len(alerts)}


def main():
    doc = load_yaml(ALERTS_YAML)
    # the posture's SM record (renamed from the old flat supermetrics.yaml in the multi-posture refactor)
    sm_yaml = os.path.join(HERE, f"supermetrics.{doc['posture']}.yaml")
    sm = load_sm_ids(sm_yaml)
    shared = shared_ids()
    symptoms, alerts = build(doc, sm, shared)
    counts = validate(doc, symptoms, alerts)
    os.makedirs(CONTENT, exist_ok=True)
    with open(OUT_SYMPTOMS, "w", encoding="utf-8") as f:
        json.dump({"symptomDefinitions": symptoms}, f, indent=1, ensure_ascii=True)
        f.write("\n")
    with open(OUT_ALERTS, "w", encoding="utf-8") as f:
        json.dump({"alertDefinitions": alerts}, f, indent=1, ensure_ascii=True)
        f.write("\n")
    print(f"posture: {doc['posture']}  (scoping: {doc['scoping']}; notifications: {doc['notifications']})")
    print(f"  symptoms: {counts['symptoms']}  ->  {OUT_SYMPTOMS.split('/')[-1]}")
    print(f"  alerts:   {counts['alerts']}  ->  {OUT_ALERTS.split('/')[-1]}")
    for a in alerts:
        st = a["states"][0]
        print(f"    {st['severity']:<8} {st['impact']['detail']:<10} "
              f"[{st['base-symptom-set']['symptomSetOperator']} x{len(st['base-symptom-set']['symptomDefinitionIds'])}]  {a['name']}")
    print("  validated (SM refs resolve, symptom-set refs, operators/severities/impacts, policy-scoped only)")


if __name__ == "__main__":
    main()
