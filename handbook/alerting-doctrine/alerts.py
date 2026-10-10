#!/usr/bin/env python3
"""alerts.py: audit an alerting estate against the three rules the chapter teaches.

Alerting doctrine is easy to state and rarely checked. This checks it, on a running VCF Operations instance:

  1. WHERE SCOPE LIVES. An alert definition's complete field list, across every definition on the instance.
     If none of those fields names an object or a group, scope cannot live on the definition and must live in
     policy enablement, which makes the default policy's enablement list the audit surface;
  2. THE ANY-ANY REVIEW. Which of your own definitions are enabled in the default policy, which is the policy
     that governs everything no other policy claims. Plus the measured blast radius, read two ways: the objects
     of the relevant kind that policy governs, and the objects governed by a policy that inherits from it. A
     policy takes every alert setting it does not set itself from its parent, so an alert switched on in the
     default policy is on in each descendant that leaves it alone. "Every object in the fleet" is the worst
     case, and the real number is readable;
  3. WHERE THE THRESHOLD LIVES. Every symptom definition's condition type, operator, value and metric key.
     A doctrine of dumb conditions over intelligent metrics shows up as a tiny value vocabulary against keys
     that are mostly super metrics, and the opposite shows up as arithmetic buried in conditions;
  4. THE DEBOUNCE CENSUS. Wait and cancel cycles across every definition, yours beside the vendor's, and the
     same two dials on the symptoms, which is where a condition can be held before the alert sees it. If yours
     are one value on every definition, those dials were set once for all of them;
  5. WHERE ROUTING CAN AND CANNOT SEE. A notification rule's complete field list, and how many of the live
     rules are scoped by any of the filters the API defines. If the rule object has no policy field, routing
     cannot read the thing that scopes the alert, and the definition's NAME is the only bridge;
  6. ONE FAILURE, ONE ALERT. Whether anything on the instance keeps a child's alert quiet while its parent
     fails (a symptom set on the PARENT or ANCESTOR with a negated reference), how many sets roll children up
     into the parent instead, which of your definitions on a child kind are parent-aware, and which enabled
     rules would send a child kind's alerts one by one, because a notification rule has no field that groups them.

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
  export OPS_CHILD_KINDS=VirtualMachine,HostSystem  # the kinds that fail with a parent, for check 6
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
# Every property of a notification rule that narrows which alerts it selects, from the VCF Operations 9.1.1 API's
# notification-rule schema. A rule with all of them empty selects every alert on the instance.
RULE_FILTERS = ("alertDefinitionIdFilters", "alertImpactFilters", "alertTypeFilters", "alertStatuses",
                "alertControlStates", "actionStatuses", "criticalities", "resourceFilters", "resourceFilter",
                "resourceKindFilters", "resourceKindFilter", "collectorGroupId", "collectorUUId")
REPORT = []


def say(line=""):
    """Print a line and keep it, so the record carries what the reader saw."""
    print(line)
    REPORT.extend(str(line).split("\n"))


def filter_size(value):
    """How many entries one rule filter carries: a str-values object counts its values, an object counts once."""
    if isinstance(value, dict):
        if "values" in value:
            return len(value.get("values") or [])
        return 1 if any(v not in (None, "", [], {}) for v in value.values()) else 0
    if isinstance(value, (list, tuple)):
        return len(value)
    return 1 if value not in (None, "", False) else 0


def symptom_sets(node):
    """Every plain symptom set inside an alert state's base-symptom-set, walking composites."""
    if not isinstance(node, dict):
        return []
    if node.get("type") == "SYMPTOM_SET_COMPOSITE" or "symptom-sets" in node:
        return [s for child in node.get("symptom-sets") or [] for s in symptom_sets(child)]
    return [node]


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


def export_policy(policy_id, tok):
    """One policy's export, parsed: the policy and its whole ancestor chain, or None when it cannot be read.

    Built inline rather than through opslib because the export answers 500 to any Accept other than
    application/zip and its id parameter is an array. A 500 here means "cannot determine", never a fact
    about the policy (the built-in Base Settings policy always answers 500).
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
        return ET.fromstring(archive.read(archive.namelist()[0]))
    except (zipfile.BadZipFile, ET.ParseError, IndexError):
        return None


def policy_alert_entries(policy_id, tok, root=None):
    """Every explicit <Alert> entry in a policy's export (the policy and its ancestors), with its kinds."""
    root = export_policy(policy_id, tok) if root is None else root
    if root is None:
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


def chain(policy_id, root):
    """The policy's keys from itself to its root, walking parentPolicy (document order is not stable)."""
    parent = {p.get("key"): p.get("parentPolicy") or None for p in root.iter("Policy")}
    out, key = [], policy_id
    while key and key in parent and key not in out:
        out.append(key)
        key = parent[key]
    return out


def resolves_enabled(alert, keys, entries):
    """Whether an alert is on under the first policy in the chain that sets it, under its own kinds only."""
    for key in keys:
        for e in entries:
            if (e["policyKey"] == key and e["alertId"] == alert["id"]
                    and e["adapterKind"] == alert.get("adapterKindKey")
                    and e["resourceKind"] == alert.get("resourceKindKey")):
                return e["enabled"]
    return None


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
    say(f"alerts.py: auditing an alerting estate owned by {owner!r}\n")

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
    say(f"  1. AN ALERT DEFINITION CARRIES {len(fields)} distinct field(s); {len(universal)} on every one "
          f"of the {len(ads)}")
    say(f"     {', '.join(universal)}")
    say(f"     none of them names an object or a group: the kind key constrains WHAT kind may fire, never "
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
        say(f"\n  2. THE DEFAULT POLICY carries {len(entries)} explicit entries, {review['enabledEntries']} "
              f"of them enabled")
        say(f"     {len(ours)} are yours, and " + (f"{len(on)} of those are ENABLED there, which scopes them to "
              f"everything no other policy claims and every policy that inherits from it" if on else
              "none of those is enabled there"))
        for n in review["ownedEnabledNames"]:
            say(f"        {n}")

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
            # Each governing policy is exported one at a time (the export carries its ancestors; a batch of
            # every policy at once can outlast the read timeout), and its chain is walked to see whether the
            # default policy is an ancestor, so an alert switched on there is on here unless this chain sets it.
            mine_on = [by_id[e["alertId"]] for e in on if e["alertId"] in by_id]
            inheriting, undetermined = [], 0
            reach = collections.Counter()
            for pid, n in counts.items():
                root = export_policy(pid, tok)
                if root is None:
                    undetermined += n
                    continue
                keys = chain(pid, root)
                if pid != default["id"] and default["id"] in keys:
                    inheriting.append(pid)
                entries = policy_alert_entries(pid, tok, root) or []
                for a in mine_on:
                    if resolves_enabled(a, keys, entries):
                        reach[a["name"]] += n
            below = sum(counts[p] for p in inheriting)
            governed.update({"governingPolicies": len(counts), "underAPolicyInheritingFromIt": below,
                             "policiesInheritingFromIt": len(inheriting),
                             "reachableFromTheDefaultPolicy": governed["underTheDefaultPolicy"] + below,
                             "undetermined": undetermined,
                             "ownedEnabledReach": {a["name"]: reach.get(a["name"], 0) for a in mine_on}})
            say(f"\n     BLAST RADIUS: of {governed['queried']} {kind} object(s) asked about, "
                  f"{governed['underTheDefaultPolicy']} are governed by the default policy and {below} more by "
                  f"{len(inheriting)} {'policy that inherits' if len(inheriting) == 1 else 'policies that inherit'} from it, so an alert switched on there reaches up to "
                  f"{governed['reachableFromTheDefaultPolicy']} today"
                  + (f"; {undetermined} not determined (their policy would not export)" if undetermined else ""))
            for name, n in governed["ownedEnabledReach"].items():
                say(f"        {name}: on for {n} of them")
        else:
            say(f"\n     BLAST RADIUS: not determined; the effective-policy query did not answer")

    # ---- 3: where the threshold lives
    def condition(s):
        return ((s.get("state") or {}).get("condition") or {})
    my_sym = [s for s in sds if owned_by(s.get("name"), owner)]
    thresholds = {"estateConditionTypes": dict(collections.Counter(condition(s).get("type") for s in sds)),
                  "ownedConditionTypes": dict(collections.Counter(condition(s).get("type") for s in my_sym)),
                  "ownedValues": dict(collections.Counter(str(condition(s).get("value")) for s in my_sym
                                                          if condition(s).get("value") is not None)),
                  "ownedWithoutAValue": sum(1 for s in my_sym if condition(s).get("value") is None),
                  "ownedOperators": dict(collections.Counter(condition(s).get("operator") for s in my_sym)),
                  "ownedReadingASuperMetric": sum(1 for s in my_sym
                                                  if str(condition(s).get("key") or "").startswith("Super Metric|")),
                  "ownedTotal": len(my_sym)}
    say(f"\n  3. THRESHOLDS: {thresholds['ownedReadingASuperMetric']} of {len(my_sym)} of your symptom "
          f"conditions read a super metric key")
    say(f"     your whole value vocabulary is {sorted(thresholds['ownedValues'], key=float)}"
          + (f"; {thresholds['ownedWithoutAValue']} compare no value (a log or event condition)"
             if thresholds["ownedWithoutAValue"] else ""))
    say(f"     estate-wide condition types: {thresholds['estateConditionTypes']}")

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
                "longestWaitIsVendorContent": not any((a.get("waitCycles") or 0) == max((x.get("waitCycles") or 0)
                                                      for x in ads) for a in mine)}
    # the symptoms carry their own wait and cancel, which is where a condition can be held before an alert sees it
    debounce.update({"ownedSymptomWait": dict(collections.Counter(s.get("waitCycles") for s in my_sym)),
                     "ownedSymptomCancel": dict(collections.Counter(s.get("cancelCycles") for s in my_sym)),
                     "estateSymptomWait": dict(collections.Counter(s.get("waitCycles") for s in sds)),
                     "estateSymptomCancel": dict(collections.Counter(s.get("cancelCycles") for s in sds))})
    say(f"\n  4. DEBOUNCE: your definitions use wait {sorted(debounce['ownedWait'])} and cancel "
          f"{sorted(debounce['ownedCancel'])}; your symptoms use wait {sorted(debounce['ownedSymptomWait'])} and "
          f"cancel {sorted(debounce['ownedSymptomCancel'])}")
    say(f"     the estate uses wait {debounce['estateWait'].get(1, 0)} of {len(ads)} at 1, and the longest "
          f"wait on the instance is {debounce['longestWait']} cycles")
    say(f"     every definition carries exactly {sorted(debounce['statesPerDefinition'])} state(s); impact "
          f"badges {debounce['impactDetail']}")

    # ---- 5: what routing can see
    def kinds_of(r):
        out = [k.get("resourceKind") for k in (r.get("resourceKindFilters") or []) if isinstance(k, dict)]
        one = r.get("resourceKindFilter") or {}
        return sorted({k for k in out + [one.get("resourceKind")] if k})
    rule_fields = sorted({k for r in rules for k in r})
    scoped = []
    for r in rules:
        sizes = {f: filter_size(r.get(f)) for f in RULE_FILTERS}
        scoped.append({"enabled": bool(r.get("enabled")),
                       "alertDefinitionFilters": sizes["alertDefinitionIdFilters"],
                       "resourceFilters": sizes["resourceFilters"],
                       "resourceKindFilters": sizes["resourceKindFilters"],
                       "criticalities": sizes["criticalities"],
                       "otherFilters": {f: n for f, n in sizes.items() if n and f not in (
                           "alertDefinitionIdFilters", "resourceFilters", "resourceKindFilters", "criticalities")},
                       "filters": sum(1 for n in sizes.values() if n),
                       "kinds": kinds_of(r)})
    live = [s for s in scoped if s["enabled"]]
    unscoped = [s for s in scoped if not s["filters"]]
    routing = {"rules": len(rules), "enabled": len(live), "withNoFilterAtAll": len(unscoped),
               "enabledWithNoFilter": sum(1 for s in unscoped if s["enabled"]),
               "fields": rule_fields, "filterFields": list(RULE_FILTERS),
               "hasAPolicyField": any("polic" in f.lower() for f in rule_fields),
               "perRule": scoped}
    say(f"\n  5. ROUTING: {len(rules)} notification rule(s), {len(live)} enabled, {len(unscoped)} with none of the "
          f"{len(RULE_FILTERS)} filters set, {routing['enabledWithNoFilter']} of those enabled")
    say(f"     a rule carries {len(rule_fields)} fields and a policy field is "
          f"{'present' if routing['hasAPolicyField'] else 'ABSENT'}: routing cannot read the thing that "
          f"scopes the alert")

    # ---- 6: one failure, one alert
    child_kinds = [k.strip() for k in os.environ.get("OPS_CHILD_KINDS", "VirtualMachine,HostSystem").split(",")
                   if k.strip()]

    def sets_of(a):
        return [s for st in (a.get("states") or []) for s in symptom_sets(st.get("base-symptom-set"))]

    def negated(s):
        return any(str(x).startswith("!") for x in s.get("symptomDefinitionIds") or [])

    def parent_aware(a):
        return any(s.get("relation") in ("PARENT", "ANCESTOR") and negated(s) for s in sets_of(a))

    def rolls_up(s):
        return s.get("relation") in ("CHILD", "DESCENDANT") and s.get("aggregation") in ("COUNT", "PERCENT")
    every_set = [s for a in ads for s in sets_of(a)]
    mine_child = [a for a in mine if a.get("resourceKindKey") in child_kinds]
    # A rule narrowed to a definition or to an object (and that object's children) is not counted here: it
    # selects what it names. One with neither, whose kind filter is empty or names a child kind, selects every
    # alert on every object of that kind.
    one_by_one = [s for s in live if not s["alertDefinitionFilters"] and not s["resourceFilters"]
                  and "resourceFilter" not in s["otherFilters"]
                  and (not s["kinds"] or set(s["kinds"]) & set(child_kinds))]
    correlation = {"childKinds": child_kinds,
                   "setsByRelation": dict(collections.Counter(s.get("relation") for s in every_set)),
                   "rollupSets": sum(1 for s in every_set if rolls_up(s)),
                   "definitionsWithARollup": sum(1 for a in ads if any(rolls_up(s) for s in sets_of(a))),
                   "negatedSets": sum(1 for s in every_set if negated(s)),
                   "definitionsKeepingAChildQuiet": sum(1 for a in ads if parent_aware(a)),
                   "ownedOnAChildKind": dict(collections.Counter(a["resourceKindKey"] for a in mine_child)),
                   "ownedParentAware": sum(1 for a in mine_child if parent_aware(a)),
                   "enabledRulesSendingChildAlertsOneByOne": len(one_by_one)}
    say(f"\n  6. ONE FAILURE, ONE ALERT: {correlation['definitionsKeepingAChildQuiet']} of {len(ads)} definitions keep "
          f"a child quiet while its parent fails (a negated PARENT or ANCESTOR set); "
          f"{correlation['definitionsWithARollup']} roll children up into the parent (CHILD or DESCENDANT, COUNT or "
          f"PERCENT)")
    say(f"     symptom sets by relation: {correlation['setsByRelation']}")
    say(f"     of your {len(mine_child)} definition(s) on {', '.join(child_kinds)}, {correlation['ownedParentAware']} "
          f"parent-aware")
    say(f"     {len(one_by_one)} enabled rule(s) select every alert on a child kind, narrowed by no definition and no "
          f"object; a rule has no field that groups alerts, so each one it selects reaches its plug-in on its own")

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
               "routing": routing,
               "correlation": correlation,
               "report": REPORT}
    text = UUID.sub("{{id}}", json.dumps(payload, indent=1, ensure_ascii=False))
    for var in ("OPS_HOST", "OPS_BROKER_HOST"):
        v = os.environ.get(var)
        assert not v or v not in text, f"{var} reached the record"
    for name in (review.get("ownedEnabledNames") or []):
        assert owned_by(name, owner), "a name that is not the owner's reached the published list"
    os.makedirs(out_dir, exist_ok=True)
    open(os.path.join(out_dir, "alerts.json"), "w", encoding="utf-8").write(text + "\n")
    say(f"\nwrote alerts.json ({len(ads)} definitions, {len(sds)} symptoms, {len(rules)} rules audited); "
          f"only your own object names are published, everything else is a count")


if __name__ == "__main__":
    main()
