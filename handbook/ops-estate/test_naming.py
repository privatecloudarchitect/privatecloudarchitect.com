#!/usr/bin/env python3
"""Offline cases for naming.check: each one a name the grammar accepts or a way a name fails it.

Run:  python3 test_naming.py      (standard library only; exits 0 when every case holds)
"""
import sys

import naming

V = {
    "owner": "PCA",
    "bundles": {"Shared": "_shared", "Example": "example"},
    "kinds": {"VM": {"plural": "VMs", "keys": ["VirtualMachine"]},
              "Host": {"plural": "Hosts", "keys": ["HostSystem"]},
              "Cluster": {"plural": "Clusters", "keys": ["ClusterComputeResource"]}},
    "scopes": ["gold", "silver", "gold tier"],
    "environmentValues": ["gold", "silver"],
}

CASES = [
    # (name, class, kind key or None, expected reason fragment or None for "conforms")
    ("PCA - Example - Host - Recoverable Cold DRAM (GB)", "super metric", None, None),
    ("PCA - Example - Host - CPU Overcommit Position [gold tier]", "super metric", None, None),
    ("PCA - Example - Host - Recoverable Cold DRAM GB", "super metric", None, "unit 'GB' outside parentheses"),
    ("PCA - Example - Host - Price Delta USD per GB", "super metric", None, "unit 'GB' outside parentheses"),
    ("PCA - Example - Host - Price Delta (USD/GB)", "super metric", None, None),
    ("PCA - Example - Cluster - Hosts Over CPU Envelope (count) [gold]", "super metric", None, None),
    ("PCA - Example - Cluster - Reclaimable Memory GB [gold]", "super metric", None, "unit 'GB' outside parentheses"),
    ("PCA - Example - Tier - gold - Host CPU Overcommit Position", "super metric", None, "field count"),
    ("PCA - Example - Rack - Power Draw (W)", "super metric", None, "kind 'Rack' is not in the kind vocabulary"),
    ("PCA - Example - VM - CPU Ready Envelope Position (gold)", "super metric", None, "environment value 'gold'"),
    ("PCA - Example - VM - CPU Ready [bronze]", "super metric", None, "not a declared scope"),
    ("PCA - Example - VM - CPU [Ready] Position [gold]", "super metric", None, "qualifier form"),
    ("PCA - Example - gold (Clusters)", "custom group", None, None),
    ("PCA - Example - gold tier (Hosts, Clusters)", "custom group", None, None),
    ("PCA - Example - gold", "custom group", None, "member kinds in parentheses"),
    ("PCA - Example - gold (Racks)", "custom group", None, "member kinds ['Racks']"),
    ("PCA - Example - gold", "policy", None, None),
    ("PCA - Example - Policy - gold", "policy", None, "field count"),
    ("PCA - Example - Envelope [gold]", "policy", None, "qualifier form"),
    ("PCA - Example - VM - CPU Ready over envelope", "symptom definition", "VirtualMachine", None),
    ("PCA - Example - Host - CPU Ready over envelope", "symptom definition", "VirtualMachine", "does not name the object's own kind"),
    ("PCA - Example - VM over CPU Ready envelope", "alert definition", "VirtualMachine", "field count"),
    ("PCAP - Example - VM - CPU Ready", "super metric", None, "not the owner's"),
    ("PCA - Unknown - VM - CPU Ready (%)", "super metric", None, "bundle 'Unknown' is not registered"),
    ("PCA - Example - Capacity Envelope - Clusters", "view", None, "field count"),
    ("PCA - Example - Cluster Capacity Envelope [gold]", "view", None, None),
    ("PCA - Example - Posture Scorecard [silver]", "dashboard", None, None),
    ("PCA - Example - Gold standard review", "dashboard", None, None),   # 'Gold' is not the value 'gold'
    ("PCA - Example - gold review", "dashboard", None, "environment value 'gold'"),
    ("PCA - Example - VM - CPU Ready (%)", "super metrics", None, None),   # content.py's plural label
]


def main():
    failed = 0
    for name, cls, kind, expect in CASES:
        reasons = naming.check(name, cls, V, kind)
        ok = (not reasons) if expect is None else any(expect in r for r in reasons)
        failed += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {cls:<20} {name}" + ("" if ok else f"\n       got {reasons}, expected {expect!r}"))
    print(f"\n{len(CASES) - failed} of {len(CASES)} cases hold")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
