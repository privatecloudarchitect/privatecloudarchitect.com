#!/usr/bin/env python3
"""verify_scope.py: log in AS a tenant and show exactly what they can see.

Read-only. Set the VCFA_* variables to a tenant principal (not the admin), and
this prints the scope that the two roles compose to: which projects they see and
which supervisor namespaces they can list. It is the fastest way to confirm a
vend landed the isolation you intended.

What a correct result looks like for a services-self-service tenant who owns one
dedicated project:
  * projects visible  = only the projects they are a member of (their own, plus
    any shared ones). A project they were never bound into is invisible.
  * namespaces visible = the namespaces in those member projects, and nothing
    from another tenant's project.

If you see another tenant's project or namespace here, the principal has more
than own-only scope: check that they are Organization User (never Organization
Administrator, which carries an org-wide visibility bypass) and that they were not
bound into a shared project at edit_adv or above.

  export VCFA_HOST=... VCFA_ORG=... VCFA_USER=alice VCFA_PASSWORD=...
  python3 verify_scope.py

For the full multi-user Day-2 isolation matrix (who can act on whose deployment,
and the governance flip), run the companion proof harness linked in references.md.
"""
import sys

from vcfa import Vcfa, VcfaError


def main():
    v = Vcfa()
    who = v.whoami()
    print(f"# principal: {who['user']}  org role(s): {who['roles']}")
    if "Organization Administrator" in who["roles"]:
        print("  NOTE: this principal is Organization Administrator, which sees every project")
        print("        in the org by design. Self-service tenants should be Organization User.")

    projects = v.list_projects()
    print(f"\nprojects visible ({len(projects)}):")
    for p in projects:
        print(f"  - {p}")

    # namespaces visible across the whole org-scope this principal has
    status, raw, _ = v.cci(
        "GET", "/apis/infrastructure.cci.vmware.com/v1alpha3/supervisornamespaces")
    if status == 200:
        import json
        names = [i["metadata"]["name"] for i in json.loads(raw).get("items", [])]
        print(f"\nsupervisor namespaces visible ({len(names)}):")
        for n in names:
            print(f"  - {n}")
    elif status == 403:
        print("\nsupervisor namespaces: 403 (this principal has no workload-plane reach;")
        print("  that is the Project User floor, own-only on the deployment plane, by design)")
    else:
        print(f"\nsupervisor namespaces: HTTP {status}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except VcfaError as e:
        sys.exit(f"ERROR: {e}")
