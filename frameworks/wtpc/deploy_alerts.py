#!/usr/bin/env python3
"""Deploy the WTPC POSTURE alert bundle — POST the symptom + alert definitions and enable them in the WTPC
policy ONLY (never Default). Public API (/api/symptomdefinitions, /api/alertdefinitions) — supported.

Reads the generated artifacts (content/wtpc-alerts.{symptoms,alerts}.json). On POST the server
assigns ids (it rejects a client id), so this maps the generator's slug ids -> server ids and
rewires each alert's symptom-set references before POSTing the alerts. Idempotent by NAME (re-runs
reuse existing definitions). Portable: the WTPC + Default policies resolve by name at runtime.

SCOPING (the estate's hard rule): each alert is ENABLED in the WTPC policy and DISABLED in Default — so it
fires only on objects whose EFFECTIVE policy is WTPC (never all objects). NOTE: precedence still
applies — an alert fires on a member only when WTPC is that member's effective policy; run the
effective-policy parity check (validate_live.py --parity) if members are shadowed by another policy.

Usage (from deploy/vcf-ops-content/wtpc/):
  python deploy_alerts.py            # dry-run
  python deploy_alerts.py --execute  # POST + enable
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from lib._alerts import find_existing
from lib._client import ops_client

HERE = os.path.dirname(os.path.abspath(__file__))
SYMPTOMS = os.path.join(HERE, "content", "wtpc-alerts.symptoms.json")
ALERTS = os.path.join(HERE, "content", "wtpc-alerts.alerts.json")
WTPC_POLICY = "PCA - WTPC - Policy - prod-latency-critical-db"


def load(path, key):
    return json.load(open(path, encoding="utf-8"))[key]


def resolve_policies(c):
    pols = c.get("/api/policies", params={"_no_links": "true", "pageSize": 500}).json()["policySummaries"]
    wtpc = next((p["id"] for p in pols if p["name"] == WTPC_POLICY), None)
    default = next((p["id"] for p in pols if p.get("defaultPolicy")), None)
    if not wtpc:
        raise SystemExit(f"policy {WTPC_POLICY!r} not found — run the step-4 policy instantiation first")
    return wtpc, default


def deploy(c, execute: bool) -> int:
    symptoms = load(SYMPTOMS, "symptomDefinitions")
    alerts = load(ALERTS, "alertDefinitions")
    wtpc, default = (resolve_policies(c) if execute else ("<wtpc>", "<default>"))
    print(f"WTPC alert deploy · {'EXECUTE' if execute else 'DRY-RUN'}  (policy {str(wtpc)[:8]})")

    # 1) symptoms — idempotent by name: UPDATE in place (PUT with id) if the name exists, else POST.
    #    (find_existing is a read-only GET, so it runs in dry-run too and the preview is truthful.)
    existing_sym = find_existing(c, "/api/symptomdefinitions", "symptomDefinitions")
    id_map: dict[str, str] = {}
    print(f"1) {len(symptoms)} symptom definitions")
    for s in symptoms:
        slug, short = s["id"], s["name"].split(" - ")[-1]
        body = {k: v for k, v in s.items() if k != "id"}
        if s["name"] in existing_sym:
            sid = existing_sym[s["name"]]
            id_map[slug] = sid
            if not execute:
                print(f"   DRY-RUN would UPDATE symptom {short}")
            else:
                c.put("/api/symptomdefinitions", json={**body, "id": sid})
                print(f"   updated: {short} -> {sid[:24]}")
            continue
        if not execute:
            print(f"   DRY-RUN would POST symptom {short} (new)")
            id_map[slug] = f"<server-id:{slug}>"
            continue
        got = c.post("/api/symptomdefinitions", json=body).json()
        id_map[slug] = got["id"]
        print(f"   POSTed: {short} -> {got['id'][:24]}")

    # 2) alerts — remap symptom refs to server ids; UPDATE in place if the name exists, else POST.
    existing_alert = find_existing(c, "/api/alertdefinitions", "alertDefinitions")
    alert_ids: list[tuple[str, str]] = []
    print(f"2) {len(alerts)} alert definitions")
    for a in alerts:
        name, short = a["name"], a["name"].split(" - ", 2)[-1]
        body = {k: v for k, v in a.items() if k != "id"}
        for st in body["states"]:
            ss = st["base-symptom-set"]
            ss["symptomDefinitionIds"] = [id_map[sid] for sid in ss["symptomDefinitionIds"]]
        if name in existing_alert:
            aid = existing_alert[name]
            alert_ids.append((name, aid))
            if not execute:
                print(f"   DRY-RUN would UPDATE alert {short} (symptom-set + text)")
            else:
                c.put("/api/alertdefinitions", json={**body, "id": aid})
                print(f"   updated: {short} -> {aid[:24]}")
            continue
        if not execute:
            print(f"   DRY-RUN would POST alert {short} (new)")
            continue
        got = c.post("/api/alertdefinitions", json=body).json()
        alert_ids.append((name, got["id"]))
        print(f"   POSTed: {short} -> {got['id'][:24]}")

    # 3) enable each alert in the WTPC policy; disable in Default (BLOCK invariant — never all-objects)
    print("3) enable in WTPC policy ONLY (disable in Default)")
    for name, aid in alert_ids:
        if not execute:
            print(f"   DRY-RUN would enable {name.split(' - ', 2)[-1]} in WTPC, disable in Default")
            continue
        # per-policy enablement: PUT /enable?policyId (verified endpoint "Enable alert definition in policies")
        c.put(f"/api/alertdefinitions/{aid}/enable", params={"policyId": wtpc})
        if default:
            c.put(f"/api/alertdefinitions/{aid}/disable", params={"policyId": default})
        print(f"   enabled in WTPC: {name.split(' - ', 2)[-1]}")
    print(f"\n{'done' if execute else 'dry-run complete'} — {len(alerts)} alerts scoped to the WTPC policy. "
          "Firing is precedence-gated: a member pages only when WTPC is its effective policy (--parity).")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Deploy + enable the WTPC posture alert bundle (public API)")
    ap.add_argument("--execute", action="store_true", help="POST + enable (default: dry-run)")
    args = ap.parse_args()
    with ops_client() as c:
        return deploy(c, args.execute)


if __name__ == "__main__":
    sys.exit(main())
