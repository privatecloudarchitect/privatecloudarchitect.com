#!/usr/bin/env python3
"""Ensure the WTPC taxonomy's categories exist on your vCenter - step 1 of the adopt recipe.

Reads taxonomy.yaml (concept -> live category name, object scope, cardinality, closed value list)
and defines each category natively on the vCenter named by VCENTER_HOST. Native definition is the
projection-proof plane: the centralized Operations Tag Management API is the eventual home, but its
projection of a newly created category into vCenter is unreliable on current builds, and because
posture group rules reference categories BY NAME, nothing downstream depends on which plane
created them.

DRY-RUN by default. Idempotent: reuses an existing category this tool created, creates only
missing values, and never touches a same-named category it did not create (that is a CONFLICT,
reported and left untouched). REVERSIBLE: --teardown removes every category this tool created,
identified by the marker it stamps in the description.

Usage (from frameworks/wtpc/):
  python ensure_tag_definitions.py                       # DRY-RUN
  python ensure_tag_definitions.py --execute             # define categories + values
  python ensure_tag_definitions.py --only env,sla        # subset of concepts
  python ensure_tag_definitions.py --teardown --execute  # remove ours (detach assignments first)
"""
from __future__ import annotations

import argparse
import os
import sys

from lib import _taxonomy
from lib._client import vcenter_client
from lib._tagdefs import CategoryReport, NativeVcenterTagProvider


def render(reports: list[CategoryReport]) -> None:
    print(f"\n  {'category (live name)':26} {'scope':22} {'category':13} values")
    print(f"  {'-' * 26} {'-' * 22} {'-' * 13} ------")
    for r in reports:
        vals = []
        if r.values_created:
            vals.append(f"+{len(r.values_created)} ({','.join(r.values_created)})")
        if r.values_existing:
            vals.append(f"={len(r.values_existing)}")
        note = f"  ! {r.note}" if r.note else ""
        print(f"  {r.name[:26]:26} {r.object_type[:22]:22} {r.category_action:13} {' '.join(vals)}{note}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Ensure WTPC taxonomy categories on your vCenter (native plane)")
    ap.add_argument("--only", help="comma-separated concepts/categories to limit to (default: all)")
    ap.add_argument("--execute", action="store_true", help="apply (default: dry-run)")
    ap.add_argument("--teardown", action="store_true", help="remove the categories this tool created")
    args = ap.parse_args()

    cats = _taxonomy.categories()
    if args.only:
        want = {s.strip() for s in args.only.split(",")}
        cats = [c for c in cats if c["concept"] in want or c.get("category", c["concept"]) in want]
    if not cats:
        raise SystemExit("no taxonomy categories match (check --only / taxonomy.yaml)")

    provider = NativeVcenterTagProvider()
    dry = not args.execute
    mode = "TEARDOWN" if args.teardown else "ENSURE"
    vc_host = os.environ.get("VCENTER_HOST", "<VCENTER_HOST unset>")
    print(f"{mode} WTPC taxonomy on {vc_host} · {'EXECUTE' if args.execute else 'DRY-RUN'}"
          f"  (taxonomy: {_taxonomy.taxonomy_path()})")
    print("  categories: " + ", ".join(f"{c['concept']}->{c.get('category', c['concept'])}" for c in cats))

    with vcenter_client() as vc:
        index = provider.cat_index(vc)  # read the vCenter's category index ONCE
        reports: list[CategoryReport] = []
        for c in cats:
            name = c.get("category", c["concept"])
            if args.teardown:
                reports.append(provider.teardown_category(vc, vc_host, name, index, dry_run=dry))
            else:
                vals = c["values"] if isinstance(c.get("values"), list) else []
                reports.append(provider.ensure_category(
                    vc, vc_host, name, c["object"], c.get("cardinality", "SINGLE"),
                    vals, index, dry_run=dry))
        render(reports)

        conflicts = [r for r in reports if r.category_action == "conflict"]
        created = sum(1 for r in reports if r.category_action in ("create", "would-create"))
        vals_new = sum(len(r.values_created) for r in reports)
        print(f"\n  summary: {len(cats)} categor(y/ies) - {created} {'to create' if dry else 'created'}, "
              f"{vals_new} value(s) {'to create' if dry else 'created'}, {len(conflicts)} conflict(s).")
        if conflicts:
            print("  ! conflicts (same-named categories not created by this tool) were LEFT UNTOUCHED - "
                  "rename the category in taxonomy.yaml or resolve the collision before re-running.")
        if dry and not args.teardown:
            print("  DRY-RUN - re-run with --execute to apply.")
        return 1 if conflicts else 0


if __name__ == "__main__":
    sys.exit(main())
