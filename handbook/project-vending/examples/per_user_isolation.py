#!/usr/bin/env python3
"""Demonstrate per-user project isolation on VCF Automation.

Give each user their OWN project as a Project Advanced User (edit_adv), then prove
neither can see or touch the other's. This is the own-only pattern for services
self-service, and the reason it needs a project per user: the project role is
project-wide and the workload plane has no per-user ownership, so two advanced
users in ONE project are NOT isolated (each can act on every namespace in it) -
the project is the trust boundary, so each user gets their own.

Run as an organization administrator (the VCFA_* variables from vcfa.py). Every
named user must already be an organization principal that has synced from your
directory into the supervisor's identity provider - a brand-new user can log in
before that sync completes but cannot yet be bound here or operate on the workload
plane. Creates a project + a namespace per user; never deletes.

Optionally proves the isolation: set TENANT_PASSWORD to the shared password of the
named users and the script logs in as each and confirms they see and reach ONLY
their own project.

Example:
  export VCFA_HOST=vcfa.example.com VCFA_ORG=Acme VCFA_USER=admin
  export VCFA_PASSWORD="$(secret-tool lookup service vcfa-admin)"
  export TENANT_PASSWORD="$(secret-tool lookup service vcfa-tenants)"   # optional, runs the proof
  python3 per_user_isolation.py \
      --assign alice:proj-alice --assign bob:proj-bob \
      --region <your-region> --vpc <your-vpc> --seg <your-seg> --zone <your-zone>
"""
import argparse
import json
import os
import sys
import time

# vcfa.py is the shared client, one directory up in scripts/.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
from vcfa import Vcfa, VcfaError  # noqa: E402

_NS_API = "/apis/infrastructure.cci.vmware.com/v1alpha3"


def poll(client, project, name):
    for _ in range(12):
        cur = client.get_namespace(project, name)
        phase = (cur or {}).get("status", {}).get("phase")
        if phase in ("Created", "Ready"):
            return phase
        time.sleep(12)
    return "Timeout"


def existing_ns(client, project):
    st, raw, _ = client.cci("GET", f"{_NS_API}/namespaces/{project}/supervisornamespaces")
    items = json.loads(raw).get("items", []) if st == 200 else []
    return items[0]["metadata"]["name"] if items else None


def ns_get(client, project, name):
    st, _, _ = client.cci("GET", f"{_NS_API}/namespaces/{project}/supervisornamespaces/{name}")
    return st


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--assign", action="append", required=True, metavar="USER:PROJECT",
                    help="a user and the project to isolate them in (repeat; use 2+ to show isolation)")
    ap.add_argument("--role", default="edit_adv", choices=["view", "edit", "edit_adv", "admin"],
                    help="project role each user gets: view=Project Auditor, edit=Project User, "
                         "edit_adv=Project Advanced User (default), admin=Project Administrator")
    ap.add_argument("--region", required=True, help="a region on the org (CRD-required)")
    ap.add_argument("--vpc", default=None)
    ap.add_argument("--seg", default=None, help="service engine group; only for NSX ALB regions")
    ap.add_argument("--zone", default=None)
    args = ap.parse_args()
    pairs = [(a.split(":", 1)[0], a.split(":", 1)[1]) for a in args.assign if ":" in a]
    if len(pairs) != len(args.assign):
        sys.exit("each --assign must be USER:PROJECT")

    admin = Vcfa()
    who = admin.whoami()
    print(f"admin {who['user']} (org {who['org']})")
    ns_of = {}
    for user, project in pairs:
        admin.create_project(project, description=f"Isolated project for {user}.")
        admin.bind_role(project, "User", user, args.role)
        name = existing_ns(admin, project) or admin.create_namespace(
            project, f"{project}-ns-", args.region, args.vpc, args.seg, args.zone)["metadata"]["name"]
        ns_of[project] = name
        print(f"[build] {project}: {user} {args.role}, namespace {name} -> {poll(admin, project, name)}")

    tenant_pw = os.environ.get("TENANT_PASSWORD")
    if not tenant_pw or len(pairs) < 2:
        print("\n(set TENANT_PASSWORD and assign 2+ users to run the isolation proof)")
        return 0

    print("\n-- isolation proof (fresh login per user) --")
    insecure = os.environ.get("VCFA_INSECURE") == "1"
    ok = True
    for user, project in pairs:
        others = [p for _, p in pairs if p != project]
        u = Vcfa(host=admin.host, org=admin.org, user=user, password=tenant_pw, insecure=insecure)
        visible = set(u.list_projects())
        own = ns_get(u, project, ns_of[project])
        other = [ns_get(u, o, ns_of[o]) for o in others]
        isolated = (project in visible and not any(o in visible for o in others)
                    and own == 200 and all(r in (403, 404) for r in other))
        ok = ok and isolated
        print(f"{user}: sees={sorted(visible)} own-ns={own} other-ns={other} ISOLATED={isolated}")
    print(f"\nVERDICT - project-level isolation between the users: {ok}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except VcfaError as e:
        sys.exit(f"ERROR: {e}")
