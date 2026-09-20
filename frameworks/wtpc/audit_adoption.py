#!/usr/bin/env python3
"""audit_adoption.py: how far did adoption actually get, and where does the chain stop?

`apply.py` converges the estate and `audit_deployment.py` reports what the result governs. This reports the
thing between them: the adoption chain, link by link, so a stalled adoption names its own link instead of
presenting as a framework that does not work.

The chain has five links and they fail in a fixed order, because each one is the input to the next:

  1. THE CATEGORIES. A posture group rule is an AND of exact `category|value` conditions, so every declared
     category must exist on the vCenter with the declared cardinality. A missing category makes its rule
     unmatchable no matter what anybody tags;
  2. THE ASSIGNMENTS. How many objects actually carry a taxonomy tag. **This is the link the converge does not
     own**: `apply.py` states in its own docstring that workload tagging is deliberately not a phase, because
     tagging rides your estate's change process. It is still a link in the chain, and it is the one that
     silently is not done;
  3. THE GROUPS. Present, and resolving to how many members. A tag-rule group with zero members is link 2
     reported one layer up;
  4. THE DERIVE. Whether the host and cluster groups can be derived from where the tagged machines run. The
     estate refuses this when the VMs group is empty, on purpose, so an empty workload half cannot blank a
     populated hardware half;
  5. THE PARITY. Whether anything ends up governed, which `audit_deployment.py` reports in full.

Reports the first link that is not complete, because everything downstream of it is a consequence rather
than a finding.

Read-only throughout. It reads the vCenter tagging plane and the Operations group plane and writes nothing.

Run:
  export OPS_HOST=... OPS_BROKER_HOST=... OPS_API_TOKEN=...   # as the rest of the estate
  export VCENTER_HOST=...
  export VCENTER_SESSION_ID=...              # or VCENTER_USERNAME + VCENTER_PASSWORD
  export OPS_TLS_VERIFY=false                                 # only on a self-signed lab CA
  python3 audit_adoption.py
"""

from __future__ import annotations

import base64
import collections
import json
import os
import re
import time
import urllib.request

from lib._client import OpsSession, _ctx
from lib._taxonomy import categories as declared_categories

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
VMS_GROUP = re.compile(r"^Group - (?P<posture>.+) \(VMs\)$")

# The guard's own words, from the reconciler this framework ships. Quoted rather than paraphrased, because a
# chapter that reports a refusal should report the sentence the operator will actually see in the terminal.
DERIVE_GUARD = "REFUSING to reconcile: the VMs group is empty (likely a transient re-resolution)."


def _session_id():
    """A vCenter API session id, taken from the environment or minted from the credentials.

    Two paths on purpose. The estate's shared VcSession sends basic auth on every request, which the rest of
    the vCenter API accepts and which `/api/cis/tagging/*` answered 401 to on the build this was written
    against; the documented flow there is to exchange credentials once for a session id. And an estate whose
    tag plane is reached by some other identity can hand this one a session id directly through
    VCENTER_SESSION_ID rather than putting a second password in the environment, which is the better habit
    where it is available.
    """
    pre = os.environ.get("VCENTER_SESSION_ID")
    if pre:
        return pre.strip()
    host = os.environ["VCENTER_HOST"]
    cred = f"{os.environ['VCENTER_USERNAME']}:{os.environ['VCENTER_PASSWORD']}"
    req = urllib.request.Request(f"https://{host}/api/session", method="POST",
                                 headers={"Authorization": "Basic "
                                          + base64.b64encode(cred.encode()).decode()})
    with urllib.request.urlopen(req, context=_ctx(_insecure()), timeout=60) as r:
        return json.loads(r.read() or b'""')


def _insecure():
    raw = os.environ.get("VCENTER_TLS_VERIFY", os.environ.get("OPS_TLS_VERIFY", "true"))
    return str(raw).strip().lower() in ("0", "false", "no", "off")


def vcenter_categories():
    """Every tag category the vCenter holds, by name, with its cardinality."""
    host = os.environ["VCENTER_HOST"]
    sid = _session_id()

    def get(path):
        req = urllib.request.Request(f"https://{host}{path}",
                                     headers={"vmware-api-session-id": sid, "Accept": "application/json"})
        with urllib.request.urlopen(req, context=_ctx(_insecure()), timeout=60) as r:
            return json.loads(r.read() or b"null")

    out = {}
    for cid in (get("/api/cis/tagging/category") or []):
        body = get(f"/api/cis/tagging/category/{cid}") or {}
        name = body.get("name")
        if name:
            out[name] = {"cardinality": body.get("cardinality")}
    return out


def taxonomy_assignments(ops, wanted):
    """How many machines carry a tag from each declared category.

    Read from Operations rather than from the vCenter tag-association plane because the group rules match on
    what Operations sees, and that projection is the thing a rule can actually resolve against. The property
    to read is summary|tagJson: summary|tag renders as a display string that cannot be parsed back.
    """
    rl = (ops.get("/api/resources",
                  params={"resourceKind": "VirtualMachine", "pageSize": 2000,
                          "_no_links": "true"}).json() or {}).get("resourceList") or []
    ids = [r["identifier"] for r in rl if r.get("identifier")]
    if not ids:
        return {"machines": 0, "withAnyTag": 0, "withATaxonomyTag": 0, "byCategory": {}}
    body = ops.post("/api/resources/properties/latest/query",
                    json={"resourceIds": ids, "propertyKeys": ["summary|tagJson"]}).json() or {}
    any_tag, tax_tag = 0, 0
    per_category = collections.Counter()
    for v in body.get("values") or []:
        tags = []
        for prop in v.get("property-contents", {}).get("property-content", []):
            for raw in prop.get("values") or []:
                try:
                    tags += json.loads(raw)
                except (TypeError, ValueError):
                    pass
        if tags:
            any_tag += 1
        hit = False
        for cat in {t.get("category") for t in tags}:
            if cat in wanted:
                per_category[cat] += 1
                hit = True
        tax_tag += 1 if hit else 0
    return {"machines": len(ids), "withAnyTag": any_tag, "withATaxonomyTag": tax_tag,
            "byCategory": dict(per_category)}


def framework_groups(ops, prefix):
    rows = []
    for g in ((ops.get("/api/resources/groups",
                       params={"includePolicy": "true", "_no_links": "true"}).json() or {})
              .get("groups") or []):
        name = (g.get("resourceKey") or {}).get("name")
        if not str(name).startswith(prefix):
            continue
        md = g.get("membershipDefinition") or {}
        body = ops.get("/api/resources", params={"parentId": g["id"], "pageSize": 1,
                                                 "_no_links": "true"}).json() or {}
        rows.append({"group": str(name)[len(prefix):].strip(" -"),
                     "mechanism": "tag rule" if (md.get("rules") or []) else "static list",
                     "members": (body.get("pageInfo") or {}).get("totalCount")})
    return rows


def main():
    prefix = os.environ.get("WTPC_PREFIX", "PCA - WTPC")
    out_dir = os.environ.get("OUT_DIR", ".")
    ops = OpsSession()
    print("audit_adoption.py: how far did adoption get, and which link stops it?\n")

    # ---- link 1: the categories
    declared = {c["category"]: c for c in declared_categories()}
    live = {}
    vc_reachable = True
    try:
        live = vcenter_categories()
    except Exception as exc:
        vc_reachable = False
        print(f"  1. CATEGORIES: not read ({type(exc).__name__}); set VCENTER_HOST plus either "
              f"VCENTER_SESSION_ID or VCENTER_USERNAME and VCENTER_PASSWORD to include this link")
    cats = {}
    if vc_reachable:
        for name, spec in declared.items():
            got = live.get(name)
            cats[name] = {"present": bool(got),
                          "cardinalityMatches": bool(got) and got.get("cardinality") == spec.get("cardinality"),
                          "declaredValues": len(spec.get("values") or [])}
        present = sum(1 for v in cats.values() if v["present"])
        print(f"  1. CATEGORIES: {present} of {len(cats)} declared categories exist on the vCenter")
        for name, v in cats.items():
            state = "present" if v["present"] else "MISSING"
            extra = "" if not v["present"] else ("" if v["cardinalityMatches"] else ", cardinality differs")
            print(f"     {name:<12} {state}{extra}")

    # ---- link 2: the assignments
    assign = taxonomy_assignments(ops, set(declared))
    print(f"\n  2. ASSIGNMENTS: {assign['withATaxonomyTag']} of {assign['machines']} machine(s) carry a "
          f"taxonomy tag ({assign['withAnyTag']} carry any tag at all)")
    for name in declared:
        print(f"     {name:<12} carried by {assign['byCategory'].get(name, 0)} machine(s)")
    print(f"     this is the link the converge does NOT own: apply.py states that workload tagging is "
          f"deliberately not a phase, because it rides your estate's change process")

    # ---- link 3: the groups
    rows = framework_groups(ops, prefix)
    tagrule = [r for r in rows if r["mechanism"] == "tag rule"]
    empty = [r for r in tagrule if not r["members"]]
    print(f"\n  3. GROUPS: {len(rows)} present; {len(tagrule)} resolve by tag rule and {len(empty)} of those "
          f"have no members")

    # ---- link 4: the derive, and 5: what it all governs
    # The guard's condition is the guard's, not a plausible restatement of it. reconcile_infra_groups.py
    # refuses on `not vm_ids` for the posture it was invoked with, so the predicate is per posture and it
    # reads ONE group: that posture's VMs group. "Some tag rule somewhere is empty" is a different, broader
    # claim and would misreport an estate whose tier groups are empty while its posture VMs groups are not.
    derive = {}
    for row in rows:
        m = VMS_GROUP.match(row["group"])
        if m:
            n = row["members"]
            derive[m.group("posture")] = {"vmsGroupMembers": n, "wouldRefuse": not n}
    refusing = sorted(k for k, v in derive.items() if v["wouldRefuse"])
    print(f"\n  4. DERIVE: {len(refusing)} of {len(derive)} posture(s) would refuse to reconcile")
    for posture, v in sorted(derive.items()):
        verdict = "WOULD REFUSE" if v["wouldRefuse"] else "has members to derive from"
        print(f"     {posture:<28} VMs group {v['vmsGroupMembers']} member(s): {verdict}")
    print(f"     the guard is `not vm_ids` in reconcile_infra_groups.py, read per posture, so an empty "
          f"workload half cannot blank a populated hardware half")

    # ---- the verdict: the first incomplete link
    stops_at = None
    if vc_reachable and any(not v["present"] for v in cats.values()):
        stops_at = "1 · the categories: a declared category is missing, so its rule can never match"
    elif not assign["withATaxonomyTag"]:
        stops_at = "2 · the assignments: the categories exist and nothing carries them"
    elif empty:
        stops_at = "3 · the groups: objects are tagged and the rules are not matching them"
    print(f"\n  THE CHAIN STOPS AT: {stops_at or 'nowhere; every link is complete'}")
    if stops_at:
        print("     everything downstream of that link is a consequence rather than a finding")

    payload = {"captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "prefix": prefix,
               "categories": cats, "categoriesRead": vc_reachable,
               "assignments": assign, "groups": rows,
               "tagRuleGroups": len(tagrule), "tagRuleGroupsEmpty": len(empty),
               "derive": {"guard": DERIVE_GUARD, "postures": derive,
                          "posturesRefusing": len(refusing), "posturesTotal": len(derive)},
               "stopsAt": stops_at}
    text = UUID.sub("{{id}}", json.dumps(payload, indent=1, ensure_ascii=False))
    for var in ("OPS_HOST", "OPS_BROKER_HOST", "VCENTER_HOST", "VCENTER_USERNAME"):
        v = os.environ.get(var)
        assert not v or v not in text, f"{var} reached the record"
    # Only declared category names and framework group names appear. No machine is named, and no tag value
    # from outside the declared taxonomy is recorded: an estate's other tags are its own business.
    os.makedirs(out_dir, exist_ok=True)
    open(os.path.join(out_dir, "adoption.json"), "w", encoding="utf-8").write(text + "\n")
    print(f"\nwrote adoption.json; no machine is named and no tag outside the declared taxonomy is recorded")


if __name__ == "__main__":
    main()
