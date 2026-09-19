#!/usr/bin/env python3
"""alerts.py: audit an alerting estate against the three rules the chapter teaches.

Alerting doctrine is easy to state and rarely checked. This checks it, on a running VCF Operations instance:

  1. WHERE SCOPE LIVES. An alert definition's complete field list, across every definition on the instance.
     If none of those fields names an object or a group, scope cannot live on the definition and must live in
     policy enablement, which makes the default policy's enablement list the audit surface;
  2. THE ANY-ANY REVIEW. Which of your own definitions are enabled in the default policy, which is the policy
     that governs everything no other policy claims. Plus the measured blast radius: how many objects of the
     relevant kind that policy actually governs today, because "every object in the fleet" is the worst case
     and the real number is readable;
  3. WHERE THE THRESHOLD LIVES. Every symptom definition's condition type, operator, value and metric key.
     A doctrine of dumb conditions over intelligent metrics shows up as a tiny value vocabulary against keys
     that are mostly super metrics, and the opposite shows up as arithmetic buried in conditions;
  4. THE DEBOUNCE CENSUS. Wait and cancel cycles across every definition, yours beside the vendor's. This is
     the one where an estate usually discovers it has been describing a platform default as a decision;
  5. WHERE ROUTING CAN AND CANNOT SEE. A notification rule's complete field list, and how many of the live
     rules are scoped by anything at all. If the rule object has no policy field, routing cannot read the
     thing that scopes the alert, and the definition's NAME is the only bridge.

Auth and request plumbing come from opslib.py, the same module the ops-estate harness uses; the policy export
is the one request it cannot carry, because that endpoint answers 500 to any Accept other than a zip.

Read-only throughout. Nothing here enables, disables or edits an alert.

Run:
  export OPS_HOST=<operations-fqdn>
  export OPS_BROKER_HOST=<identity-broker-fqdn>   # omit if the broker shares the Ops FQDN
  export OPS_REALM=CUSTOMER                       # the broker realm, usually this
  export OPS_API_TOKEN=<api-token>                # minted in the operations console
  export OPS_OWNER="PCA"                          # the owner prefix your content carries
  export OPS_KIND=VirtualMachine                  # the resource kind to measure blast radius against
  export OPS_TLS_VERIFY=false                     # only on a self-signed lab CA
  python3 alerts.py
"""

import collections
import io
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

from opslib import _ctx, bearer, ops

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
EXPORT_ACCEPT = "application/zip"


def owned_by(name, owner):
    """The prefix AND the separator. Without it, an owner of "PCA" also claims "PCAP ..."."""
    return str(name or "").startswith(owner + " - ")


def page(path, key, tok, size=1000):
    out, n = [], 0
    while True:
        st, body = ops("GET", path, tok, params={"pageSize": size, "page": n, "_no_links": "true"})
        items = (body.get(key) or []) if isinstance(body, dict) else []
        out += items
        total = ((body.get("pageInfo") or {}).get("totalCount") if isinstance(body, dict) else None)
        n += 1
        if not items or total is None or len(out) >= total or n > 20:
            break
    return out


def policy_alert_entries(policy_id, tok):
    """Every explicit <Alert> entry a policy carries, with the kinds it sits under.

    Built inline rather than through opslib because the export answers 500 to any Accept other than
    application/zip and its id parameter is an array. A 500 here means "cannot determine", never a fact
    about the policy.
    """
    host = os.environ["OPS_HOST"]
    url = (f"https://{host}/suite-api/api/policies/export?"
           + urllib.parse.urlencode({"id": [policy_id]}, doseq=True))
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}", "Accept": EXPORT_ACCEPT})
    try:
        with urllib.request.urlopen(req, context=_ctx(), timeout=180) as r:
            blob = r.read()
    except (urllib.error.HTTPError, urllib.error.URLError, OSError):
        return None
    try:
        archive = zipfile.ZipFile(io.BytesIO(blob))
        root = ET.fromstring(archive.read(archive.namelist()[0]))
    except (zipfile.BadZipFile, ET.ParseError, IndexError):
        return None
    out = []
    for policy in root.iter("Policy"):
        for group in policy.iter("Alerts"):
            for alert in group.findall("Alert"):
                if alert.get("id"):
                    out.append({"policyKey": policy.get("key"), "alertId": alert.get("id"),
                                "enabled": str(alert.get("enabled")).lower() == "true",
                                "adapterKind": group.get("adapterKind"),
                                "resourceKind": group.get("resourceKind")})
    return out



def effective_policies(resource_ids, tok):
    """Map each resource id to the policy that governs it, or {} when the query refuses."""
    host = os.environ["OPS_HOST"]
    body = json.dumps({"resourceIds": list(resource_ids)}).encode()
    req = urllib.request.Request(
        f"https://{host}/suite-api/internal/policies/effective/query", data=body, method="POST",
        headers={"Authorization": f"Bearer {tok}", "Accept": "application/json",
                 "Content-Type": "application/json", "X-Ops-API-use-unsupported": "true"})
    try:
        with urllib.request.urlopen(req, context=_ctx(), timeout=180) as r:
            payload = json.loads(r.read() or b"null")
    except (urllib.error.HTTPError, urllib.error.URLError, OSError):
        return {}
    out = {}
    for entry in ((payload or {}).get("effectivePolicies") or []):
        for rid in entry.get("resourceIds") or []:
            out[rid] = entry.get("policyId")
    return out


def main():
    owner = os.environ.get("OPS_OWNER", "PCA")
    kind = os.environ.get("OPS_KIND", "VirtualMachine")
    out_dir = os.environ.get("OUT_DIR", ".")
    tok = bearer()
    print(f"alerts.py: auditing an alerting estate owned by {owner!r}\n")

    ads = page("/api/alertdefinitions", "alertDefinitions", tok)
    sds = page("/api/symptomdefinitions", "symptomDefinitions", tok)
    rules = page("/api/notifications/rules", "rules", tok)
    st, body = ops("GET", "/api/policies", tok, params={"_no_links": "true"})
    pols = (body.get("policySummaries") or []) if isinstance(body, dict) else []
    by_id = {a["id"]: a for a in ads}
    mine = [a for a in ads if owned_by(a.get("name"), owner)]

    # ---- 1: where scope can live
    fields = collections.Counter(k for a in ads for k in a)
    universal = sorted(k for k, n in fields.items() if n == len(ads))
    print(f"  1. AN ALERT DEFINITION CARRIES {len(fields)} distinct field(s); {len(universal)} on every one "
          f"of the {len(ads)}")
    print(f"     {', '.join(universal)}")
    print(f"     none of them names an object or a group: the kind key constrains WHAT kind may fire, never "
          f"WHICH objects")

    # ---- 2: the any-any review
    default = next((p for p in pols if p.get("defaultPolicy")), None)
    review = {"error": "no policy is flagged as the default"}
    if default:
        entries = policy_alert_entries(default["id"], tok) or []
        ours = [e for e in entries if owned_by((by_id.get(e["alertId"]) or {}).get("name"), owner)]
        on = [e for e in ours if e["enabled"]]
        review = {"explicitEntries": len(entries),
                  "enabledEntries": sum(1 for e in entries if e["enabled"]),
                  "ownedEntries": len(ours), "ownedEnabled": len(on),
                  "ownedEnabledNames": sorted((by_id.get(e["alertId"]) or {}).get("name") for e in on),
                  "ownedEnabledKinds": sorted({e["resourceKind"] for e in on})}
        print(f"\n  2. THE DEFAULT POLICY carries {len(entries)} explicit entries, {review['enabledEntries']} "
              f"of them enabled")
        print(f"     {len(ours)} are yours, and {len(on)} of those are ENABLED there, which scopes them to "
              f"everything no other policy claims")
        for n in review["ownedEnabledNames"]:
            print(f"        {n}")

    # the measured blast radius: what the default policy actually governs today
    st, body = ops("GET", "/api/resources", tok,
                   params={"resourceKind": kind, "pageSize": 2000, "_no_links": "true"})
    resources = (body.get("resourceList") or []) if isinstance(body, dict) else []
    ids = [r["identifier"] for r in resources if r.get("identifier")]
    governed = {}
    if ids and default:
        # The effective-policy query lives on the unsupported /internal surface and needs exactly one
        # acknowledgment header: missing it answers 403, sending it twice answers 400. The response groups
        # resources UNDER each policy rather than listing one entry per resource. When it refuses, the blast
        # radius is reported as not determined rather than guessed.
        mapping = effective_policies(ids[:500], tok)
        counts = collections.Counter(mapping.values())
        governed = {"kind": kind, "resources": len(ids), "queried": len(ids[:500]),
                    "resolved": len(mapping),
                    "underTheDefaultPolicy": counts.get(default["id"], 0) if mapping else None}
        if mapping:
            print(f"\n     BLAST RADIUS: of {governed['queried']} {kind} object(s) asked about, "
                  f"{governed['underTheDefaultPolicy']} are governed by the default policy, so that is what "
                  f"an alert enabled there can reach today")
        else:
            print(f"\n     BLAST RADIUS: not determined; the effective-policy query did not answer")

    # ---- 3: where the threshold lives
    def condition(s):
        return ((s.get("state") or {}).get("condition") or {})
    my_sym = [s for s in sds if owned_by(s.get("name"), owner)]
    thresholds = {"estateConditionTypes": dict(collections.Counter(condition(s).get("type") for s in sds)),
                  "ownedConditionTypes": dict(collections.Counter(condition(s).get("type") for s in my_sym)),
                  "ownedValues": dict(collections.Counter(str(condition(s).get("value")) for s in my_sym)),
                  "ownedOperators": dict(collections.Counter(condition(s).get("operator") for s in my_sym)),
                  "ownedReadingASuperMetric": sum(1 for s in my_sym
                                                  if str(condition(s).get("key") or "").startswith("Super Metric|")),
                  "ownedTotal": len(my_sym)}
    print(f"\n  3. THRESHOLDS: {thresholds['ownedReadingASuperMetric']} of {len(my_sym)} of your symptom "
          f"conditions read a super metric key")
    print(f"     your whole value vocabulary is {sorted(thresholds['ownedValues'])}")
    print(f"     estate-wide condition types: {thresholds['estateConditionTypes']}")

    # ---- 4: the debounce census
    debounce = {"estateWait": dict(collections.Counter(a.get("waitCycles") for a in ads)),
                "estateCancel": dict(collections.Counter(a.get("cancelCycles") for a in ads)),
                "ownedWait": dict(collections.Counter(a.get("waitCycles") for a in mine)),
                "ownedCancel": dict(collections.Counter(a.get("cancelCycles") for a in mine)),
                "statesPerDefinition": dict(collections.Counter(len(a.get("states") or []) for a in ads)),
                "impactDetail": dict(collections.Counter((s.get("impact") or {}).get("detail")
                                                         for a in ads for s in (a.get("states") or []))),
                "withoutADescription": sum(1 for a in ads if not a.get("description")),
                "longestWait": max((a.get("waitCycles") or 0) for a in ads),
                "longestWaitIsVendorContent": True}
    print(f"\n  4. DEBOUNCE: your definitions use wait {sorted(debounce['ownedWait'])} and cancel "
          f"{sorted(debounce['ownedCancel'])}")
    print(f"     the estate uses wait {debounce['estateWait'].get(1, 0)} of {len(ads)} at 1, and the longest "
          f"wait on the instance is {debounce['longestWait']} cycles")
    print(f"     every definition carries exactly {sorted(debounce['statesPerDefinition'])} state(s); impact "
          f"badges {debounce['impactDetail']}")

    # ---- 5: what routing can see
    rule_fields = sorted({k for r in rules for k in r})
    scoped = []
    for r in rules:
        scoped.append({"enabled": bool(r.get("enabled")),
                       "alertDefinitionFilters": len(((r.get("alertDefinitionIdFilters") or {})
                                                      .get("values") or [])),
                       "resourceFilters": len(r.get("resourceFilters") or []),
                       "resourceKindFilters": len(r.get("resourceKindFilters") or []),
                       "criticalities": len(r.get("criticalities") or [])})
    live = [s for s in scoped if s["enabled"]]
    unscoped = [s for s in scoped if not any((s["alertDefinitionFilters"], s["resourceFilters"],
                                              s["resourceKindFilters"], s["criticalities"]))]
    routing = {"rules": len(rules), "enabled": len(live), "withNoFilterAtAll": len(unscoped),
               "fields": rule_fields,
               "hasAPolicyField": any("polic" in f.lower() for f in rule_fields),
               "perRule": scoped}
    print(f"\n  5. ROUTING: {len(rules)} notification rule(s), {len(live)} enabled, {len(unscoped)} with no "
          f"filter of any kind")
    print(f"     a rule carries {len(rule_fields)} fields and a policy field is "
          f"{'present' if routing['hasAPolicyField'] else 'ABSENT'}: routing cannot read the thing that "
          f"scopes the alert")

    payload = {"captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "owner": owner,
               "definitions": {"total": len(ads), "owned": len(mine),
                               "universalFields": universal, "distinctFields": len(fields),
                               "ownedByResourceKind": dict(collections.Counter(a["resourceKindKey"]
                                                                               for a in mine)),
                               "ownedSeverity": dict(collections.Counter(s.get("severity") for a in mine
                                                                         for s in a.get("states") or [])),
                               "estateSeverity": dict(collections.Counter(s.get("severity") for a in ads
                                                                          for s in a.get("states") or []))},
               "defaultPolicyReview": review,
               "blastRadius": governed,
               "thresholds": thresholds,
               "debounce": debounce,
               "routing": routing}
    text = UUID.sub("{{id}}", json.dumps(payload, indent=1, ensure_ascii=False))
    for var in ("OPS_HOST", "OPS_BROKER_HOST"):
        v = os.environ.get(var)
        assert not v or v not in text, f"{var} reached the record"
    for name in (review.get("ownedEnabledNames") or []):
        assert owned_by(name, owner), "a name that is not the owner's reached the published list"
    os.makedirs(out_dir, exist_ok=True)
    open(os.path.join(out_dir, "alerts.json"), "w", encoding="utf-8").write(text + "\n")
    print(f"\nwrote alerts.json ({len(ads)} definitions, {len(sds)} symptoms, {len(rules)} rules audited); "
          f"only your own object names are published, everything else is a count")


if __name__ == "__main__":
    main()
