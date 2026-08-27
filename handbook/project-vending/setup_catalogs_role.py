#!/usr/bin/env python3
"""setup_catalogs_role.py: create the custom org role that lets a namespace
operator populate the "+ New Namespace" form.

A Project Administrator holds the right to create namespaces, but the create form
reads three org-gated catalogs: namespace classes, regions, and storage classes.
Without them the form is empty. This role adds exactly those read rights on top of
the Organization User baseline, and nothing else: no org-wide visibility, no
project CRUD. Assign it to the users who need the namespace-operator tier
(see 03-services-self-service.md).

This is a one-time, idempotent setup: run it once per organization. It creates the
role if absent and converges its rights (following the platform's implied-rights
closure). Run as an organization administrator.

  python3 setup_catalogs_role.py --name "Namespace Self-Service User"
"""
import argparse
import sys

from vcfa import Vcfa, VcfaError

# The Organization User baseline plus the three namespace-create catalogs. The
# platform may pull in one or two implied rights (for example Storage Classes:
# View); vcfa.create_role follows that closure automatically.
RIGHTS = [
    # Organization User baseline, so the role is self-contained:
    "API Tokens: Manage",
    "Metrics: View",
    "Namespace Usage: Manage",
    "Namespace Usage: View",
    "vApp: Use Console",
    # the "+ New Namespace" catalogs, the actual elevation:
    "Namespace Class: View",
    "Regions: View",
    "Region: Simple View",
]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", default="Namespace Self-Service User",
                    help="the custom role name to create or converge")
    args = ap.parse_args()

    v = Vcfa()
    print(f"# acting as {v.whoami()['user']} in org {v.org}")
    role_id = v.create_role(
        args.name,
        "Organization User baseline plus read of the namespace-create catalogs "
        "(namespace classes, regions, storage classes). Grants no org-wide "
        "visibility and no project CRUD. Pair with a CCI project role.",
        RIGHTS)
    got = v.cloudapi_list(f"roles/{role_id}/rights")
    print(f"role {args.name!r} converged: {len(got)} rights")
    for r in sorted(x["name"] for x in got):
        print(f"  - {r}")
    print(f"\nid: {role_id}")
    print("assign it to a user in the console, or keep it as a dedicated AD group's role.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except VcfaError as e:
        sys.exit(f"ERROR: {e}")
