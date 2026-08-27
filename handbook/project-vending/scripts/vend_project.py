#!/usr/bin/env python3
"""vend_project.py: create a tenant project and its first namespace, entirely by API.

This is the answer to "if project creation is the fix, it must be programmatic and
as-code." It is the three-call vend: create the project, bind the roles, create the
first Supervisor Namespace, then poll it to Ready. No console step.

Run it once per tenant trust boundary. For services self-service that must stay
own-only, that is one project per user or per team (see 02-isolation-answer.md for
why the project is the isolation unit).

Prerequisites:
  * The four VCFA_* environment variables from vcfa.py, as an account holding the
    organization-level project-management right (creating projects is a provider
    or organization administrator operation, not a tenant one).
  * Your estate's region name (required). VPC, service engine group, and zone are
    OPTIONAL and depend on how your supervisor is networked - read whichever apply
    from a namespace that already works, and pass only those:
      GET /cci/kubernetes/apis/infrastructure.cci.vmware.com/v1alpha3/namespaces/<project>/supervisornamespaces/<name>
    and copy spec.regionName (always) plus spec.vpcName / spec.segName / a zone name
    IF that namespace carries them. --seg is needed only where the region load-
    balances through NSX Advanced Load Balancer (Avi); a supervisor without service
    engine groups omits it.

Example (a region that uses NSX Advanced Load Balancer):
  export VCFA_HOST=vcfa.example.com VCFA_ORG=Acme VCFA_USER=admin
  export VCFA_PASSWORD="$(some-secret-tool get vcfa-admin)"
  python3 vend_project.py \
      --project team-acme --owner alice --owner-role edit_adv \
      --operators-group "Platform Operators" \
      --region <your-region> --vpc <your-vpc> --seg <your-service-engine-group> \
      --zone <your-zone>

Example (a supervisor with no service engine groups - just the required region):
  python3 vend_project.py --project team-acme --owner alice --region <your-region>

Safety: this script CREATES a project and a namespace. It never deletes anything.
Re-running with the same --project fails on the create (projects are unique); that
is intentional, so a re-run cannot silently duplicate a tenant.
"""
import argparse
import sys
import time

from vcfa import Vcfa, VcfaError


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True, help="the new project's name")
    ap.add_argument("--owner", required=True, help="the tenant owner's username")
    ap.add_argument("--owner-role", default="edit_adv", choices=["edit", "edit_adv", "admin"],
                    help="edit_adv for a services owner (default); admin to also manage namespaces")
    ap.add_argument("--operators-group", default=None,
                    help="an operators group to bind as project admin (recommended)")
    ap.add_argument("--namespace-stem", default=None,
                    help="generateName stem for the first namespace (default: <project>-ns-)")
    ap.add_argument("--region", required=True, help="a region on the org (CRD-required)")
    ap.add_argument("--vpc", default=None, help="the NSX VPC (estate-dependent; omit if not used)")
    ap.add_argument("--seg", default=None,
                    help="the load-balancer service engine group; needed ONLY when the region "
                         "load-balances through NSX Advanced Load Balancer (Avi). Omit otherwise.")
    ap.add_argument("--zone", default=None,
                    help="a zone for per-zone limit overrides; omit to inherit the class defaults")
    ap.add_argument("--class-name", default="large")
    ap.add_argument("--no-namespace", action="store_true",
                    help="create the project and bindings only, skip the namespace")
    args = ap.parse_args()

    v = Vcfa()
    who = v.whoami()
    print(f"# acting as {who['user']} (org {who['org']})")

    # 1. Create the project.
    print(f"[1] create project {args.project!r}")
    v.create_project(args.project, description=f"Vended project for {args.owner}.")

    # 2. Bind the owner, and the operators group if given.
    print(f"[2] bind {args.owner} -> {args.owner_role}")
    v.bind_role(args.project, "User", args.owner, args.owner_role)
    if args.operators_group:
        print(f"[2b] bind group {args.operators_group!r} -> admin")
        v.bind_role(args.project, "Group", args.operators_group, "admin")

    if args.no_namespace:
        print("done (project + bindings; namespace skipped)")
        return 0

    # 3. Create the first namespace, and poll it to Ready.
    stem = args.namespace_stem or f"{args.project}-ns-"
    print(f"[3] create namespace (generateName {stem!r})")
    ns = v.create_namespace(args.project, stem, args.region, args.vpc, args.seg, args.zone,
                            class_name=args.class_name)
    name = ns["metadata"]["name"]
    print(f"    created {name}; polling to Ready")
    for i in range(12):
        cur = v.get_namespace(args.project, name)
        phase = (cur or {}).get("status", {}).get("phase")
        print(f"    poll {i}: phase={phase}")
        if phase in ("Created", "Ready"):
            print(f"done: {args.project}/{name} is {phase}")
            return 0
        time.sleep(12)
    print("namespace did not reach Created within the poll window; check it in the console")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except VcfaError as e:
        sys.exit(f"ERROR: {e}")
