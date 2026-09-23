#!/usr/bin/env python3
"""identity_continuity.py - which entities your estate has split across more than one resource.

The composite key (vcenter_instance_uuid, moid) names WHERE a sample was taken. Both halves change
when a VM moves between vCenters, so VCF Operations mints a new resource with a new series and the old
one stops collecting. The identifier that survives, VMEntityInstanceUUID, is carried on the resource
and is NOT part of its uniqueness, so Operations does not reconcile the two for you and nothing in the
product is wrong: it is answering a different question from the one a BI pipeline asks.

This reads every VirtualMachine resource, groups them by that surviving identifier, and reports:

  * entities split across more than one resource, which is one time series a pipeline will read as two;
  * the tombstone Operations leaves behind, a MOID renamed `<moid>_vmotion_discarded_N` in state
    NOT_EXISTING, which is the closing event a continuity ledger can key on;
  * the OVERLAP, samples that exist on the superseded resource, because a relocation is not a clean cut
    and a pipeline summing across both records double counts that interval;
  * resources with no surviving identifier at all, which cannot be reconciled below the composite key.

It is read-only.

Usage:  python3 identity_continuity.py [--metric cpu|demandmhz] [--days 30]
Env:    see opslib.py (OPS_HOST, OPS_API_TOKEN, ...)
Exit:   0 every entity resolves to one resource
        1 at least one entity is split, so the pipeline needs a continuity ledger
        2 a read failed
"""

import re
import sys
import time
from collections import defaultdict

from opslib import bearer, ops

DISCARDED = re.compile(r"_vmotion_discarded_\d+$")


def identifiers(rec):
    return {i["identifierType"]["name"]: i.get("value")
            for i in rec.get("resourceKey", {}).get("resourceIdentifiers", [])}


def state(rec):
    states = rec.get("resourceStatusStates") or [{}]
    return states[0].get("resourceState") or "?"


def samples(tok, rid, metric, days):
    """How many points this resource holds for one always-on metric, and the last one."""
    end = int(time.time() * 1000)
    begin = end - days * 86400 * 1000
    try:
        st, r = ops("GET", f"/api/resources/{rid}/stats", tok,
                    params={"statKey": metric, "intervalType": "HOURS", "rollUpType": "AVG",
                            "begin": begin, "end": end})
        if st != 200 or not r:
            return None, None
    except Exception:
        return None, None
    try:
        stat = (r.get("values") or [{}])[0].get("stat-list", {}).get("stat", [])
        ts = stat[0].get("timestamps", []) if stat else []
        return len(ts), (max(ts) if ts else None)
    except Exception:
        return None, None


def main():
    argv = sys.argv[1:]
    metric = argv[argv.index("--metric") + 1] if "--metric" in argv else "cpu|demandmhz"
    days = int(argv[argv.index("--days") + 1]) if "--days" in argv else 30
    tok = bearer()

    try:
        st, r = ops("GET", "/api/resources", tok,
                    params={"resourceKind": "VirtualMachine", "pageSize": 5000})
        if st != 200 or not r:
            print(f"resource list returned HTTP {st}", file=sys.stderr)
            return 2
    except Exception as exc:
        print(f"read failed: {type(exc).__name__}", file=sys.stderr)
        return 2
    vms = r.get("resourceList", [])
    if not vms:
        print("no VirtualMachine resources returned", file=sys.stderr)
        return 2

    by_entity = defaultdict(list)
    keyless = []
    for rec in vms:
        ids = identifiers(rec)
        iu = ids.get("VMEntityInstanceUUID")
        (by_entity[iu] if iu else keyless).append((rec, ids))

    split = {iu: rs for iu, rs in by_entity.items() if len(rs) > 1}

    print(f"{len(vms)} VirtualMachine resource(s); {len(by_entity)} distinct surviving identifier(s)")
    print(f"resources with no surviving identifier: {len(keyless)}"
          + ("  <- these cannot be reconciled below the composite key" if keyless else ""))
    tombs = [ids.get("VMEntityObjectID") for rec, ids in
             ((x, identifiers(x)) for x in vms) if DISCARDED.search(ids.get("VMEntityObjectID") or "")]
    print(f"tombstones carrying a vmotion_discarded marker: {len(tombs)}")

    if not split:
        print("\nEvery entity resolves to exactly one resource. On this reading the composite key and "
              "the entity key still coincide.")
        return 0

    print(f"\n{len(split)} entit(y/ies) split across more than one resource:\n")
    for iu, rs in sorted(split.items(), key=lambda kv: -len(kv[1])):
        names = {ids.get("VMEntityName") for _r, ids in rs}
        print(f"  surviving identifier {iu}")
        print(f"    name(s) {', '.join(sorted(n for n in names if n))}")
        vcids = {ids.get("VMEntityVCID") for _r, ids in rs}
        print(f"    spans {len(vcids)} vCenter(s): "
              + ("the move crossed a vCenter boundary" if len(vcids) > 1
                 else "same vCenter, so the object was re-registered rather than relocated"))
        overlap = 0
        for rec, ids in sorted(rs, key=lambda x: x[0].get("creationTime", 0)):
            n, last = samples(tok, rec["identifier"], metric, days)
            moid = ids.get("VMEntityObjectID") or "?"
            mark = "  <- tombstone" if DISCARDED.search(moid) else ""
            print(f"      {state(rec):13s} moid={moid:34s} points={n if n is not None else '?'}{mark}")
            if DISCARDED.search(moid) and n:
                overlap += n
        if overlap:
            print(f"    OVERLAP: {overlap} point(s) on a superseded resource. A pipeline summing across "
                  f"both records double counts them; dedupe on (entity, timestamp, metric).")
        print()

    print("Resolve these through a continuity ledger keyed on the surviving identifier: see the charter "
          "section 6.5. The composite key stays on the fact; the entity key is a join, not a column the "
          "collector invents.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
