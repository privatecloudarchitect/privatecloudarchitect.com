#!/usr/bin/env python3
"""Create a WTPC posture's three custom GROUPS from its portable YAML source (dry-run by default).

Group-creation ONLY. The two sibling steps moved to purpose-built tools as the Model-A taxonomy landed:
  • tag CATEGORIES/values  -> ensure_tag_definitions.py  (native, fleet-wide — the Ops-projection workaround)
  • tag ASSIGNMENT on VMs  -> reconcile_posture_membership.py  (the vCenter tag-association plane)
So this tool now does one thing: materialize the VMs tag-rule group + the Host/Cluster placeholder groups
(born with the same rule, then converted to derived `includedResources` by reconcile_infra_groups.py). The rule references the LIVE category names resolved from the taxonomy manifest (concept ->
runtime, e.g. workload -> identity.function), so flipping naming_mode never edits this tool or the postures.

Categories are a PRECONDITION: run ensure_tag_definitions.py first (or apply.py, which sequences it).

Usage:
  python instantiate_posture.py postures/prod-latency-critical-db.yaml            # DRY-RUN
  python instantiate_posture.py postures/prod-latency-critical-db.yaml --execute  # apply
"""
from __future__ import annotations

import argparse
import sys

import yaml
from lib import _taxonomy
from lib._client import ops_client
from lib._groups import GROUPS_ENDPOINT, group_names, make_tag_rule_group
from validate_live import Ctx  # dry-run/execute helper


def main() -> int:
    ap = argparse.ArgumentParser(description="Create a WTPC posture's 3 custom groups from its YAML source")
    ap.add_argument("posture_yaml")
    ap.add_argument("--execute", action="store_true", help="apply mutations (default: dry-run)")
    args = ap.parse_args()

    doc = yaml.safe_load(open(args.posture_yaml, encoding="utf-8"))
    pr = _taxonomy.posture_runtime()  # {posture concept -> live runtime category name}
    # the AND-composed membership rule, resolved to LIVE category names (env AND workload AND sla)
    tag_conditions = [(pr.get(cat, cat), val) for cat, val in doc["membership"].items()]

    with ops_client() as c:
        ctx = Ctx(c, args.execute)
        mode = "EXECUTE" if args.execute else "DRY-RUN"
        print(f"instantiate posture {doc['posture']!r} — groups only  ({mode})")
        print(f"  membership rule (concept -> runtime): {tag_conditions}")
        print("  (categories: ensure_tag_definitions.py · tagging: reconcile_posture_membership.py)")

        have = group_names(c)
        for g in doc["groups"]:
            name, kind = g["name"], g["resource_kind"]
            if name in have:
                print(f"  exists: {name}")
                continue
            payload = make_tag_rule_group(name, kind, tag_conditions)
            ctx.act(
                f"create group {name!r} ({kind}, rule {tag_conditions})",
                lambda p=payload: c.post(GROUPS_ENDPOINT, json=p).json(),
            )
        print(
            "\nDone."
            + ("" if args.execute else "  Re-run with --execute to apply, then wait ~13 min for re-resolution.")
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
