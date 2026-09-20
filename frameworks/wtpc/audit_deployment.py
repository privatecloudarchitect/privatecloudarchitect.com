#!/usr/bin/env python3
"""audit_deployment.py: is the framework, as deployed, actually governing anything?

`validate_live.py` asks whether each posture group's members resolve to that posture's policy. This asks the
question before it: are there members at all, and which half of the framework is landing on real objects.

Four reads, in the order a deployment fails:

  1. THE GROUPS AND HOW THEY RESOLVE. Every framework group with the mechanism it uses. Two mechanisms are in
     play and they behave differently: a **tag rule** re-resolves on an interval and self-heals, and a
     **static list** is written once by a reconciler and holds until something rewrites it. A group is
     reported with its mechanism and its live member count, because an empty tag-rule group and an empty
     static list are different failures with different owners;
  2. WHAT GOVERNS EACH OBJECT. The effective policy of every virtual machine, host and cluster, bucketed into
     the two families the framework declares: a workload takes a **posture**, a host or cluster takes a
     **tier**. The claim is that the two never compete for the same object, and the way to check it is to
     count objects that land in the wrong family rather than to reason about it;
  3. THE ENVELOPE, AS ENFORCED. A posture is only real where the platform is carrying its numbers, and the
     numbers live in three separate places: the policy's capacity overcommit thresholds, its super metric
     enablement, and its alert enablement. This reports all three per posture policy, so "the envelope is
     enforced" becomes a count rather than an assertion;
  4. THE PARITY, RESTATED. How many objects each posture policy actually governs. A posture with an envelope,
     a policy, groups and zero members is deployed and governing nobody, which looks identical to a working
     posture in every inventory.

Read-only throughout. Nothing here tags, converges, or edits a policy.

Run:
  export OPS_HOST=<operations-fqdn>
  export OPS_BROKER_HOST=<identity-broker-fqdn>   # omit if the broker shares the Ops FQDN
  export OPS_REALM=CUSTOMER
  export OPS_API_TOKEN=<api-token>
  export WTPC_PREFIX="PCA - WTPC"                 # the prefix your framework content carries
  export OPS_TLS_VERIFY=false                     # only on a self-signed lab CA
  python3 audit_deployment.py
"""

from __future__ import annotations

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

from lib._client import OpsSession, _ctx

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
KINDS = ("VirtualMachine", "HostSystem", "ClusterComputeResource")
WORKLOAD_KINDS = ("VirtualMachine",)


def family(name: str) -> str:
    """Which half of the framework a policy belongs to, by the name it carries."""
    n = str(name or "")
    if " - Policy - " in n:
        return "posture"
    if " - Tier - " in n:
        return "tier"
    return "outside the framework"


def page(ops, path, key, **params):
    out, n = [], 0
    while True:
        body = ops.get(path, params={"pageSize": 1000, "page": n, "_no_links": "true", **params}).json() or {}
        items = body.get(key) or []
        out += items
        total = (body.get("pageInfo") or {}).get("totalCount")
        n += 1
        if not items or total is None or len(out) >= total or n > 20:
            break
    return out


def effective(ops, ids):
    """resource id -> policy id, or {} when the unsupported query refuses.

    The query needs exactly one acknowledgment header, which the session attaches, and it groups resources
    UNDER each policy rather than returning one row per resource.
    """
    if not ids:
        return {}
    body = ops.post("/internal/policies/effective/query", json={"resourceIds": list(ids)}).json() or {}
    out = {}
    for entry in body.get("effectivePolicies") or []:
        for rid in entry.get("resourceIds") or []:
            out[rid] = entry.get("policyId")
    return out



def enforced_envelope(ops, policy_id):
    """The three places a posture's numbers actually live, read from the policy export.

    The overcommit dials are not on the settings endpoint; that one serves time-remaining criticality
    thresholds. They come from the export, which is the one request the shared session cannot carry: the
    endpoint answers 500 to any Accept other than application/zip, and the session sets its own. So this
    request is built inline, with the session's own bearer, and commented where it happens.
    """
    out = {"overcommit": {}, "superMetrics": 0, "superMetricsEnabled": 0, "alerts": 0, "alertsEnabled": 0}
    url = (f"{ops.base}/api/policies/export?"
           + urllib.parse.urlencode({"id": [policy_id]}, doseq=True))
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {ops._token}",
                                               "Accept": "application/zip"})
    try:
        with urllib.request.urlopen(req, context=_ctx(ops.insecure), timeout=180) as r:
            raw = r.read()
    except (urllib.error.HTTPError, urllib.error.URLError, OSError):
        return out
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
        root = ET.fromstring(archive.read(archive.namelist()[0]))
    except (zipfile.BadZipFile, ET.ParseError, IndexError):
        return out
    block = next((p for p in root.iter("Policy") if p.get("key") == policy_id), None)
    if block is None:
        return out
    for el in block.iter("ApplicableResourceContainer"):
        container, sub = el.get("resourceContainerKey"), el.get("subResourceContainerKey")
        value = el.get("overCommitThreshold")
        if container and value is not None:
            out["overcommit"][f"{container}/{sub}" if sub else container] = float(value)
    for sm in block.iter("SuperMetric"):
        out["superMetrics"] += 1
        out["superMetricsEnabled"] += 1 if str(sm.get("enabled")).lower() == "true" else 0
    for al in block.iter("Alert"):
        out["alerts"] += 1
        out["alertsEnabled"] += 1 if str(al.get("enabled")).lower() == "true" else 0
    return out


def main():
    prefix = os.environ.get("WTPC_PREFIX", "PCA - WTPC")
    out_dir = os.environ.get("OUT_DIR", ".")
    ops = OpsSession()
    print(f"audit_deployment.py: what the framework prefixed {prefix!r} is currently governing\n")

    policies = {p["id"]: p["name"] for p in
                ((ops.get("/api/policies", params={"_no_links": "true"}).json() or {})
                 .get("policySummaries") or [])}
    mine = {pid: n for pid, n in policies.items() if str(n).startswith(prefix)}

    # ---- 1: the groups and how they resolve
    groups = (ops.get("/api/resources/groups",
                      params={"includePolicy": "true", "_no_links": "true"}).json() or {}).get("groups") or []
    rows = []
    for g in groups:
        name = (g.get("resourceKey") or {}).get("name")
        if not str(name).startswith(prefix):
            continue
        md = g.get("membershipDefinition") or {}
        mechanism = "tag rule" if (md.get("rules") or []) else "static list"
        body = ops.get("/api/resources", params={"parentId": g["id"], "pageSize": 1,
                                                 "_no_links": "true"}).json() or {}
        members = (body.get("pageInfo") or {}).get("totalCount")
        rows.append({"group": str(name)[len(prefix):].strip(" -"), "mechanism": mechanism,
                     "members": members, "policy": policies.get(g.get("policy")),
                     "autoResolve": bool(g.get("autoResolveMembership"))})
    by_mech = collections.Counter(r["mechanism"] for r in rows)
    empty = collections.Counter(r["mechanism"] for r in rows if not r["members"])
    print(f"  GROUPS: {len(rows)} carrying the prefix; {dict(by_mech)}")
    for r in sorted(rows, key=lambda x: (x["mechanism"], x["group"])):
        print(f"     {r['group'][:44]:<44} {r['mechanism']:<12} members={r['members']}")
    for mech in by_mech:
        print(f"     {empty.get(mech, 0)} of {by_mech[mech]} {mech} group(s) are empty")

    # ---- 2: what governs each object
    governance, misplaced = {}, []
    for kind in KINDS:
        rl = page(ops, "/api/resources", "resourceList", resourceKind=kind)
        ids = [x["identifier"] for x in rl if x.get("identifier")]
        eff = effective(ops, ids)
        fams = collections.Counter(family(policies.get(p)) for p in eff.values())
        names = collections.Counter(policies.get(p) for p in eff.values()
                                    if str(policies.get(p)).startswith(prefix))
        want = "posture" if kind in WORKLOAD_KINDS else "tier"
        wrong = sum(n for f, n in fams.items() if f not in (want, "outside the framework"))
        misplaced.append({"kind": kind, "wrongFamily": wrong})
        governance[kind] = {"objects": len(ids), "resolved": len(eff), "byFamily": dict(fams),
                            "expectedFamily": want, "wrongFamily": wrong,
                            "byPolicy": {str(k)[len(prefix):].strip(" -"): v for k, v in names.items()}}
        print(f"\n  {kind}: {len(ids)} object(s); expected family {want!r}")
        for f, n in fams.most_common():
            print(f"     {n:>4}  {f}")
        if wrong:
            print(f"     {wrong} object(s) governed by the WRONG family, which the two-unit model forbids")

    # ---- 3: the envelope, as enforced, across the three surfaces that carry it
    envelopes = {}
    for pid, name in sorted(mine.items(), key=lambda kv: kv[1]):
        envelopes[str(name)[len(prefix):].strip(" -")] = enforced_envelope(ops, pid)
    print(f"\n  ENVELOPE, AS ENFORCED ({len(envelopes)} framework policies, three surfaces each):")
    dials = sorted({k for v in envelopes.values() for k in v["overcommit"]})
    if dials:
        print(f"     {'policy':<34} " + "".join(f"{d:<17}" for d in dials) + "metrics  alerts")
        for short, v in envelopes.items():
            row = "".join(f"{str(v['overcommit'].get(d, '-')):<17}" for d in dials)
            print(f"     {short[:32]:<34} {row}{v['superMetricsEnabled']:>3}/{v['superMetrics']:<5}"
                  f"{v['alertsEnabled']:>3}/{v['alerts']}")

    # ---- 4: the parity, restated
    parity = {}
    for pid, name in mine.items():
        short = str(name)[len(prefix):].strip(" -")
        total = sum(v["byPolicy"].get(short, 0) for v in governance.values())
        parity[short] = total
    governing = sum(1 for v in parity.values() if v)
    print(f"\n  PARITY: {governing} of {len(parity)} framework policies govern at least one object")
    for short, n in sorted(parity.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"     {n:>4}  object(s) under {short[:52]}")

    payload = {"captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "prefix": prefix,
               "groups": rows,
               "groupsByMechanism": dict(by_mech), "emptyByMechanism": dict(empty),
               "governance": governance, "misplaced": misplaced,
               "policies": len(mine), "parity": parity, "envelopes": envelopes,
               "policiesGoverningSomething": governing}
    text = UUID.sub("{{id}}", json.dumps(payload, indent=1, ensure_ascii=False))
    for var in ("OPS_HOST", "OPS_BROKER_HOST"):
        v = os.environ.get(var)
        assert not v or v not in text, f"{var} reached the record"
    # Only framework object names appear, and they carry the prefix by construction; no estate machine,
    # host or cluster is named anywhere in this record.
    os.makedirs(out_dir, exist_ok=True)
    open(os.path.join(out_dir, "deployment.json"), "w", encoding="utf-8").write(text + "\n")
    print(f"\nwrote deployment.json; only framework object names appear, and no machine, host or cluster "
          f"is named")


if __name__ == "__main__":
    main()
