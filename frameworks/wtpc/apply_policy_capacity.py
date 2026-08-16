#!/usr/bin/env python3
"""Apply each posture policy's capacity-allocation from its committed payload - the reproducible half of
the policy 'ruler' the C2 check guards.

`build.py` EMITS `policy-capacity-allocation.<posture>.json` from the envelope targets, but nothing
APPLIED it - the PATCH was a manual UI step, which is how test-dev's density envelope
(memory 2.0) was left unapplied and the policy silently inherited a strict memory=1.0. This closes that
gap: the policy's live allocation becomes the reproducible output of the envelope, not a hand action.

Idempotent (skips a posture already in parity); dry-run by default. Read side is
`GET /api/policies/{id}/settings`; write side is `PATCH` the same endpoint (the shape build.py's payload
is generated for). Confirm afterwards with `governance.py --config-parity`.

Usage (from deploy/vcf-ops-content/wtpc/):
  python apply_policy_capacity.py            # dry-run: current effective vs catalog, per posture
  python apply_policy_capacity.py --execute  # PATCH the capacity-allocation to match the catalog
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

from lib._client import ops_client, policy_index

HERE = os.path.dirname(os.path.abspath(__file__))
POLICY_PREFIX = "PCA - WTPC - Policy - "
_KEYS = ("cpu", "memory", "diskspace", "poweredOffVmsConsidered")
# CAPACITY_ALLOCATION_MODEL is resource-kind-scoped; this exact param set is the live-verified GET/PATCH shape.
_PARAMS = {"type": "CAPACITY_ALLOCATION_MODEL", "resourceKind": "ClusterComputeResource", "adapterKind": "VMWARE"}


def _alloc(doc):
    s = doc.get("capacitySettings", {}).get("capacity", {}).get("capacityAllocationSettings", [])
    return s[0]["capacityAllocation"] if s else None


def _get(c, pid, inherited):
    params = {**_PARAMS, "_no_links": "true"}
    if inherited:
        params["includeInherited"] = "true"
    return _alloc(c.get(f"/api/policies/{pid}/settings", params=params).json())


def main() -> int:
    ap = argparse.ArgumentParser(description="Apply posture policy capacity-allocation from the committed payload")
    ap.add_argument("--execute", action="store_true", help="PATCH the settings (default: dry-run)")
    args = ap.parse_args()
    with ops_client() as c:
        live = policy_index(c)
        rc = 0
        print(f"capacity-allocation apply · {'EXECUTE' if args.execute else 'DRY-RUN'}")
        for path in sorted(glob.glob(os.path.join(HERE, "policy-capacity-allocation.*.json"))):
            posture = os.path.basename(path)[len("policy-capacity-allocation."):-len(".json")]
            pid = live.get(POLICY_PREFIX + posture)
            if not pid:
                print(f"  {posture}: policy not live - skipped")
                continue
            want = json.load(open(path, encoding="utf-8"))["capacitySettings"]["capacity"][
                "capacityAllocationSettings"][0]["capacityAllocation"]
            cur = _get(c, pid, inherited=True)
            if cur is not None and all(cur.get(k) == want.get(k) for k in _KEYS):
                print(f"  {posture}: already in parity ({want})")
                continue
            print(f"  {posture}: {'PATCH' if args.execute else 'DRY-RUN would PATCH'}  effective {cur} -> {want}")
            if args.execute:
                c.patch(f"/api/policies/{pid}/settings", params=_PARAMS, json=json.load(open(path, encoding="utf-8")))
                after = _get(c, pid, inherited=False)   # own setting now, must match
                ok = after is not None and all(after.get(k) == want.get(k) for k in _KEYS)
                print(f"       -> applied; own setting now {after}  {'OK' if ok else 'MISMATCH'}")
                if not ok:
                    rc = 2
    print(f"\n{'applied' if args.execute else 'dry-run complete'} - confirm with: python governance.py --config-parity")
    return rc


if __name__ == "__main__":
    sys.exit(main())
