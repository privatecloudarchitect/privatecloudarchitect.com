#!/usr/bin/env python3
"""content.py: audit an operations content estate the way a codebase gets audited.

converge.py in this folder asserts desired state. This is the other half: the four questions you would ask of
any codebase, asked of a running VCF Operations instance.

  1. the CENSUS: every content class the suite API serves, counted, each collection walked to its declared
     total rather than to one page. The ratio that matters is not the total, it is how small your own content
     is inside it, because you cannot rename the rest;
  2. the NAMING AUDIT: how many of your objects match the schema you publish, per class, with the field count
     of every name recorded. A class that diverges CONSISTENTLY is the standard being wrong about that class;
     a class that diverges in ones and twos is drift. A total cannot tell those apart;
  3. the REFERENTIAL INTEGRITY check across three edge types: alert definition to symptom definition, custom
     group to policy, and notification rule to alert definition. This is the one that catches the failure the
     chapter is about, a reference left pointing at an id that a rebuild re-minted;
  4. the DEFINED-versus-SET gap: how many alert definitions exist against how many the governing policy has
     an opinion about. Everything else is UNSET, which is a third origin and not a synonym for disabled;
  5. and a probe of the paths that would serve dashboards and views, recorded path by path, because an
     absence claim needs the set it was tested against.

Three ways this check answers wrongly, each of which it did first:

  * a referenced symptom id may carry a leading "!", which negates it. Resolve the id without the marker or a
    healthy estate reports every negated reference as broken;
  * a notification rule's alert filter is an object carrying a "values" array, not an array. Iterating the
    object yields its field names and reports those as dangling ids;
  * ownership is the prefix AND the separator. Testing for "PCA" also claims a vendor object named "PCAP ...".

Alert state semantics (three origins, UNSET reported as null, the export's accept type and ancestor chain)
follow the field guide the chapter cites; this script counts explicit entries and does not restate that
contract.

Auth and request plumbing come from opslib.py, which converge.py uses, so both harnesses take the same
environment. The one exception is the policy export, which must be requested as a zip and so cannot go
through the JSON helper; that request is built inline and commented where it happens.

Read-only throughout. Nothing here creates, converges or deletes content.

Run:
  export OPS_HOST=<operations-fqdn>
  export OPS_BROKER_HOST=<identity-broker-fqdn>   # omit if the broker shares the Ops FQDN
  export OPS_REALM=CUSTOMER                       # the broker realm, usually this
  export OPS_API_TOKEN=<api-token>                # minted in the operations console
  export OPS_OWNER="PCA"                          # the owner prefix your content carries
  export OPS_TLS_VERIFY=false                     # only on a self-signed lab CA
  python3 content.py
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

# The content classes this build serves, as (label, path under /suite-api, response key).
CLASSES = [
    ("custom groups", "/api/resources/groups", "groups"),
    ("super metrics", "/api/supermetrics", "superMetrics"),
    ("alert definitions", "/api/alertdefinitions", "alertDefinitions"),
    ("symptom definitions", "/api/symptomdefinitions", "symptomDefinitions"),
    ("policies", "/api/policies", "policySummaries"),
    ("report definitions", "/api/reportdefinitions", "reportDefinitions"),
    ("reports", "/api/reports", "reports"),
    ("notification rules", "/api/notifications/rules", "rules"),
]

# Paths that would plausibly serve a dashboard or a view. An absence claim needs its list.
ABSENT_CANDIDATES = [
    "/api/dashboards", "/api/views", "/api/dashboard", "/api/view", "/api/viewdefinitions",
    "/api/content", "/api/content/dashboards", "/api/content/views", "/api/content/operations",
    "/api/resources/dashboards", "/api/reports/views", "/api/supermetrics/dashboards",
]


def name_of(item):
    if not isinstance(item, dict):
        return ""
    return (item.get("resourceKey") or {}).get("name") or item.get("name") or ""


def owned_by(name, owner):
    """Ownership is the prefix AND the separator. Without it, "PCA" also claims "PCAP ..."."""
    return str(name or "").startswith(owner + " - ")


def fields(name):
    return len(str(name or "").split(" - "))


def page(path, key, tok, size=1000):
    """Walk a paged collection to its declared total rather than trusting one page."""
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


def export_alert_entries(policy_id, tok):
    """Count the alert entries a policy sets explicitly.

    Built inline rather than through opslib.ops because the export answers 500 to any Accept other than
    application/zip, and because its id parameter is an array. That 500 means "cannot determine", never
    anything about the policy.
    """
    host = os.environ["OPS_HOST"]
    url = (f"https://{host}/suite-api/api/policies/export?"
           + urllib.parse.urlencode({"id": [policy_id]}, doseq=True))
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}", "Accept": EXPORT_ACCEPT})
    try:
        with urllib.request.urlopen(req, context=_ctx(), timeout=180) as r:
            blob = r.read()
    except urllib.error.HTTPError as e:
        return {"error": f"the export answered HTTP {e.code}, which means cannot determine"}
    except (urllib.error.URLError, OSError) as e:
        return {"error": f"the export was unreachable ({str(e)[:60]})"}
    try:
        archive = zipfile.ZipFile(io.BytesIO(blob))
        root = ET.fromstring(archive.read(archive.namelist()[0]))
    except (zipfile.BadZipFile, ET.ParseError, IndexError) as exc:
        return {"error": f"the export did not parse ({type(exc).__name__})"}
    entries = [(a.get("id"), a.get("enabled")) for a in root.iter("Alert") if a.get("id")]
    on = sum(1 for _, e in entries if str(e).lower() == "true")
    return {"explicitlySet": len(entries), "explicitlyEnabled": on, "explicitlyDisabled": len(entries) - on}


def main():
    owner = os.environ.get("OPS_OWNER", "PCA")
    out_dir = os.environ.get("OUT_DIR", ".")
    tok = bearer()
    print(f"content.py: auditing an operations content estate owned by {owner!r}\n")

    # ---- 1: the census and the naming audit
    raw, census = {}, []
    for label, path, key in CLASSES:
        items = page(path, key, tok)
        raw[label] = items
        mine = [i for i in items if owned_by(name_of(i), owner)]
        conforming = [i for i in mine if fields(name_of(i)) >= 4]
        census.append({"class": label, "total": len(items), "owned": len(mine),
                       "conformingToSchema": len(conforming),
                       "fieldCounts": dict(collections.Counter(fields(name_of(i)) for i in mine))})
        print(f"  {label:<22} {len(items):>5} total   {len(mine):>4} {owner}-owned   "
              f"{len(conforming):>4} conforming to the four-field schema")
    total = sum(c["total"] for c in census)
    owned = sum(c["owned"] for c in census)
    conf = sum(c["conformingToSchema"] for c in census)
    print(f"  {'':<22} {total:>5} objects, of which {owned} are yours and {conf} match the schema you publish")

    near = sorted({name_of(i) for items in raw.values() for i in items
                   if str(name_of(i)).startswith(owner) and not owned_by(name_of(i), owner)})
    if near:
        print(f"\n  a prefix test without the separator would also claim {len(near)} object(s) that are "
              f"not yours")

    # ---- 2: referential integrity
    sd_ids = {i["id"] for i in raw["symptom definitions"] if i.get("id")}
    ad_ids = {i["id"] for i in raw["alert definitions"] if i.get("id")}
    pol_ids = {i["id"] for i in raw["policies"] if i.get("id")}
    edges, negated = [], 0
    for a in raw["alert definitions"]:
        for state in a.get("states") or []:
            for sid in ((state.get("base-symptom-set") or {}).get("symptomDefinitionIds") or []):
                # A leading "!" negates the symptom. It modifies the reference; it is not part of the id.
                bare = sid[1:] if sid.startswith("!") else sid
                negated += 1 if sid.startswith("!") else 0
                edges.append(("alert definition -> symptom definition", bare in sd_ids))
    st, body = ops("GET", "/api/resources/groups", tok,
                   params={"includePolicy": "true", "_no_links": "true"})
    gl = (body.get("groups") or []) if isinstance(body, dict) else []
    bound = [g for g in gl if g.get("policy")]
    for g in bound:
        edges.append(("custom group -> policy", g["policy"] in pol_ids))
    for rule in raw["notification rules"]:
        # The filter is an OBJECT carrying a "values" array. Iterating the object yields its field names.
        for aid in ((rule.get("alertDefinitionIdFilters") or {}).get("values") or []):
            edges.append(("notification rule -> alert definition", aid in ad_ids))
    by_edge = collections.Counter(k for k, _ in edges)
    dangling = collections.Counter(k for k, ok in edges if not ok)
    print(f"\n  REFERENTIAL INTEGRITY: {len(edges)} reference(s) across {len(by_edge)} edge type(s); "
          f"{sum(dangling.values())} dangling")
    for k, n in by_edge.items():
        print(f"     {n:>5}  {k:<44} dangling {dangling.get(k, 0)}")
    print(f"     {negated:>5}  of the symptom references carry a leading '!' that negates them; a check that "
          f"does not strip it reports every one as broken")

    # ---- 3: defined versus set
    default = next((p for p in raw["policies"] if p.get("defaultPolicy")), None)
    gap = {"error": "no policy is flagged as the default on this instance"}
    if default:
        gap = export_alert_entries(default["id"], tok)
        if "explicitlySet" in gap:
            gap["alertDefinitionsOnTheInstance"] = len(raw["alert definitions"])
            gap["unsetAndThereforeNull"] = len(raw["alert definitions"]) - gap["explicitlySet"]
            print(f"\n  DEFINED IS NOT SET: {gap['alertDefinitionsOnTheInstance']} alert definition(s) exist; "
                  f"the governing policy sets {gap['explicitlySet']} of them "
                  f"({gap['explicitlyEnabled']} on, {gap['explicitlyDisabled']} off)")
            print(f"     the other {gap['unsetAndThereforeNull']} are UNSET, which is null and neither of "
                  f"the two")
        else:
            print(f"\n  DEFINED IS NOT SET: not determined ({gap['error']})")

    # ---- 4: what has no read surface
    absent = []
    for p in ABSENT_CANDIDATES:
        st, _ = ops("GET", p, tok, params={"pageSize": 1})
        absent.append({"path": "/suite-api" + p, "status": st})
    served = [a for a in absent if a["status"] == 200]
    print(f"\n  NO READ SURFACE: {len(absent)} candidate path(s) probed for dashboards and views; "
          f"{len(served)} answered 200")

    payload = {"captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "owner": owner,
               "census": census,
               "totals": {"objects": total, "owned": owned, "conformingToSchema": conf},
               "ownedNames": sorted({name_of(i) for items in raw.values() for i in items
                                     if owned_by(name_of(i), owner)}),
               "prefixWithoutSeparatorWouldAlsoClaim": len(near),
               "integrity": {"references": len(edges), "dangling": sum(dangling.values()),
                             "byEdge": [{"edge": k, "references": n, "dangling": dangling.get(k, 0)}
                                        for k, n in by_edge.items()],
                             "negatedSymptomReferences": negated,
                             "groupsCarryingAPolicy": len(bound), "groupsTotal": len(gl)},
               "definedVersusSet": gap,
               "noReadSurface": absent}
    text = UUID.sub("{{id}}", json.dumps(payload, indent=1, ensure_ascii=False))
    for var in ("OPS_HOST", "OPS_BROKER_HOST"):
        v = os.environ.get(var)
        assert not v or v not in text, f"{var} reached the record"
    # Only the owner's own names are published. Every other object on the instance is a count: an estate's
    # object names are its own business, and the audit does not need them.
    for name in payload["ownedNames"]:
        assert owned_by(name, owner), "a name that is not the owner's reached the published list"
    os.makedirs(out_dir, exist_ok=True)
    open(os.path.join(out_dir, "content.json"), "w", encoding="utf-8").write(text + "\n")
    print(f"\nwrote content.json ({total} objects audited, {owned} of them yours); only your own object "
          f"names are published, everything else is a count")


if __name__ == "__main__":
    main()
