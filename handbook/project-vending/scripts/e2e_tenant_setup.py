#!/usr/bin/env python3
"""e2e_tenant_setup.py: the full tenant-onboarding sequence, top to bottom, by API.

A chronological reference you can read straight down. It runs the six steps a
tenant onboarding actually takes, in order, each one a single call over the
minimal client in ``vcfa.py``:

  1. authenticate to VCF Automation (session login; the token is a response header)
  2. create a sample project
  3. import a group of users from Active Directory into the organization
  4. bind that group (and optionally an individual owner) to the project
  5. create the project's first Supervisor Namespace
  6. poll the namespace to Ready

Everything estate-specific is a flag; nothing is hard-coded. It CREATES a project,
a group binding, and a namespace, and never deletes anything, so a re-run with the
same ``--project`` fails on the duplicate rather than silently making a second one.

Prerequisites:
  * The four VCFA_* environment variables from vcfa.py, as an account that can
    create projects (an organization or provider administrator) AND import
    identities. Note the identity requirement: importing an AD group needs the
    GROUP_USER_MANAGE right, which is present only on a session login (this client)
    and stripped from OAuth / api-token grants. That is why vcfa.py logs in with a
    session, not an API token.
  * The AD/LDAP group must already exist in the directory the org federates to; the
    import resolves it server-side by name.
  * Your estate's region (required). VPC, service engine group, and zone are optional
    and depend on how your supervisor is networked (see 04-project-vending-as-code.md).

Example (a region that uses NSX Advanced Load Balancer):
  export VCFA_HOST=vcfa.example.com VCFA_ORG=Acme VCFA_USER=admin
  export VCFA_PASSWORD="$(some-secret-tool get vcfa-admin)"
  python3 e2e_tenant_setup.py \
      --project team-acme --ad-group "Acme Platform Engineers" \
      --project-role edit_adv --region <your-region> \
      --vpc <your-vpc> --seg <your-service-engine-group> --zone <your-zone>

Example (a supervisor with no service engine groups - just the required region):
  python3 e2e_tenant_setup.py --project team-acme --ad-group "Acme Platform Engineers" \
      --region <your-region>
"""
import argparse
import sys
import time

from vcfa import Vcfa, VcfaError


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True, help="the new project's name")
    ap.add_argument("--ad-group", required=True, help="the AD/LDAP group to import into the org")
    ap.add_argument("--group-org-role", default="Organization User",
                    help="the ORGANIZATION role the imported group gets (default: Organization User)")
    ap.add_argument("--project-role", default="edit_adv", choices=["edit", "edit_adv", "admin"],
                    help="the PROJECT role the group is bound to (edit_adv = services self-service)")
    ap.add_argument("--owner", default=None,
                    help="optional individual user to also bind to the project")
    ap.add_argument("--owner-role", default="edit_adv", choices=["edit", "edit_adv", "admin"])
    ap.add_argument("--region", required=True, help="a region on the org (CRD-required)")
    ap.add_argument("--vpc", default=None, help="the NSX VPC (estate-dependent; omit if unused)")
    ap.add_argument("--seg", default=None,
                    help="service engine group; needed ONLY for NSX Advanced Load Balancer regions")
    ap.add_argument("--zone", default=None, help="a zone for per-zone limits (omit for class defaults)")
    ap.add_argument("--class-name", default="large", help="the namespace class")
    ap.add_argument("--namespace-stem", default=None,
                    help="generateName stem for the namespace (default: <project>-ns-)")
    ap.add_argument("--no-namespace", action="store_true",
                    help="stop after the bindings; skip namespace creation")
    args = ap.parse_args()

    # 1. Authenticate. Vcfa() logs in on construction and holds the bearer token
    #    (which came back in a response header, not the body).
    v = Vcfa()
    who = v.whoami()
    print(f"[1] authenticated as {who['user']} (org {who['org']}, roles {who['roles']})")

    # 2. Create the project.
    print(f"[2] create project {args.project!r}")
    v.create_project(args.project, description=f"Vended for AD group {args.ad_group!r}.")

    # 3. Import the AD group into the organization, with an org role.
    print(f"[3] import AD group {args.ad_group!r} as org role {args.group_org_role!r}")
    v.import_ad_group(args.ad_group, role_name=args.group_org_role)

    # 3b. Refresh the directory so a just-created group/user is visible now (see
    #     sync_ldap's note: the workload plane has a separate provider that syncs
    #     on its own schedule, so binding a brand-new principal may still wait).
    print("[3b] sync the LDAP directory")
    v.sync_ldap()

    # 4. Bind the group (and optional owner) to the project. This is the authority
    #    for project RBAC; groups bind by name with a trailing '@' (vcfa.py handles it).
    print(f"[4] bind group {args.ad_group!r} -> project role {args.project_role} on {args.project}")
    v.bind_role(args.project, "Group", args.ad_group, args.project_role)
    if args.owner:
        print(f"[4b] bind owner {args.owner!r} -> {args.owner_role}")
        v.bind_role(args.project, "User", args.owner, args.owner_role)

    if args.no_namespace:
        print("done (project + AD group import + bindings; namespace skipped)")
        return 0

    # 5. Create the first namespace, then 6. poll it to Ready.
    stem = args.namespace_stem or f"{args.project}-ns-"
    print(f"[5] create first namespace (generateName {stem!r})")
    ns = v.create_namespace(args.project, stem, args.region, args.vpc, args.seg, args.zone,
                            class_name=args.class_name)
    name = ns["metadata"]["name"]
    print(f"    created {name}; polling to Ready")
    for i in range(12):
        cur = v.get_namespace(args.project, name)
        phase = (cur or {}).get("status", {}).get("phase")
        print(f"[6] poll {i}: phase={phase}")
        if phase in ("Created", "Ready"):
            print(f"done: {args.project}/{name} is {phase}, group {args.ad_group!r} bound")
            return 0
        time.sleep(12)
    print("namespace did not reach Created within the poll window; check it in the console")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except VcfaError as e:
        sys.exit(f"ERROR: {e}")
