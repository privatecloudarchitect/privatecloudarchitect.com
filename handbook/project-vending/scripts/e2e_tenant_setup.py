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
  * The group must already exist in the identity source the org federates to. Pass
    --provider-type LDAP (default) or SAML/OAUTH to match your org's provider. LDAP
    resolves the group by name against the directory; SAML/OAUTH (e.g. Azure AD)
    match it against the assertion's group claim and provision members just-in-time
    on first login, so you import the group and users flow in when they sign in.
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
    ap.add_argument("--ad-group", required=True, help="the directory group to import into the org")
    ap.add_argument("--provider-type", default="LDAP", choices=["LDAP", "OIDC", "SAML"],
                    help="the org's identity provider (see the three options + caveats at step 3): LDAP "
                         "queries a directory; OIDC/SAML match the group claim and provision users "
                         "just-in-time on login")
    ap.add_argument("--group-org-role", default="Organization User",
                    help="the ORGANIZATION role the imported group gets (see the org roles + the "
                         "keep-it-at-the-floor rule at step 3). Default Organization User = no "
                         "cross-project reach, the isolation floor for a tenant")
    ap.add_argument("--project-role", default="edit_adv", choices=["view", "edit", "edit_adv", "admin"],
                    help="the PROJECT role the group gets (see the four roles + distinctions at step 4): "
                         "view=Project Auditor, edit=Project User, edit_adv=Project Advanced User "
                         "(services floor), admin=Project Administrator (self-serve namespaces)")
    ap.add_argument("--owner", default=None,
                    help="optional individual user to also bind to the project")
    ap.add_argument("--owner-role", default="edit_adv", choices=["view", "edit", "edit_adv", "admin"],
                    help="project role for the optional individual owner (same four roles as --project-role)")
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

    # 3. Import the directory group into the organization, with an org role.
    #
    #    The org's identity provider decides how the group is matched and how its
    #    members arrive. Select it with --provider-type. The three options, each with
    #    the caveat that comes with it:
    #
    #    --- Option 1: LDAP  (providerType LDAP; e.g. on-prem Active Directory) ------
    #        The group is resolved against the directory by name, and you may ALSO
    #        import individual users (import_ad_user) and bind them directly - handy
    #        for a per-user project. Caveat: a newly created directory principal takes
    #        a periodic sync before it works on the Kubernetes workload plane;
    #        sync_ldap (step 3b) refreshes THIS org's view, but the supervisor's
    #        identity provider syncs on its own schedule, so binding a brand-new user
    #        may briefly wait. Fixtures: examples/ad_fixtures.py makes a throwaway
    #        group + users over LDAPS.
    #
    #    --- Option 2: OIDC  (providerType OAUTH; an OpenID Connect IdP) -------------
    #        The group is matched against the OIDC token's groups claim, and its
    #        members are provisioned just-in-time on first login - no per-user import,
    #        no directory to sync. Caveats: confirm your IdP passes group membership
    #        in the token (the groups claim) and whether it carries group names or
    #        ids; import the group by whatever it emits. Individual pre-import is
    #        normally unnecessary - bind the group and members flow in on login.
    #
    #    --- Option 3: SAML  (providerType SAML; e.g. Azure AD via SAML) -------------
    #        Same shape as OIDC: the group is matched against the SAML assertion's
    #        group claim and members are provisioned just-in-time on login. Caveats:
    #        Azure AD can send the group's DISPLAY NAME or its OBJECT ID in the group
    #        claim depending on the app-registration config - import the group by
    #        whichever your assertion carries. ad_fixtures.py does NOT apply (it
    #        writes to on-prem AD); create the group in Azure AD via Microsoft Graph
    #        or the portal first.
    #
    #    Whatever the source, everything AFTER this step - the project, the binding,
    #    the namespace, and the isolation - is identical.
    #
    #    The imported group ALSO gets an ORGANIZATION role (--group-org-role) - the
    #    "door" in the two-plane model, separate from the project role in step 4. It
    #    decides what the members are ACROSS the org, and for an isolated tenant it
    #    must stay at the floor. The built-in org roles (name -> what it grants,
    #    confirmed live; org roles are extensible, so custom ones are valid too):
    #
    #      * Organization User          The FLOOR, and the default here: no cross-
    #                                   project visibility - a member sees and touches
    #                                   only the projects they are bound to. THIS is
    #                                   what keeps a tenant out of everyone else's
    #                                   projects.
    #      * <custom, e.g. "Namespace Self-Service User">
    #                                   Organization User PLUS a few narrow rights (the
    #                                   namespace catalog reads setup_catalogs_role.py
    #                                   adds). Still the floor for isolation - no cross-
    #                                   project reach - but enough to self-serve
    #                                   namespaces. This is the org role for the admin
    #                                   self-service end-state (see examples/README.md).
    #      * Organization Administrator ORG-WIDE: sees and manages EVERY project in the
    #                                   org. The isolation-breaker - NEVER give this to
    #                                   a tenant; it is for platform operators only.
    #      * Organization Auditor       ORG-WIDE read-only: sees every project, changes
    #                                   nothing. For audit/compliance, not self-service
    #                                   (org-wide visibility defeats own-only).
    #      * Defer to Identity Provider Takes the effective role from the IdP assertion
    #                                   instead of pinning one here - useful with OIDC/
    #                                   SAML when the IdP drives role assignment.
    #
    #    The rule: a self-service tenant is Organization User (or the catalogs variant);
    #    their real power is the PROJECT role (step 4), scoped to their own project.
    print(f"[3] import {args.provider_type} group {args.ad_group!r} as org role {args.group_org_role!r}")
    v.import_ad_group(args.ad_group, role_name=args.group_org_role, provider_type=args.provider_type)

    # 3b. LDAP only: refresh the directory so a just-created group/user is visible now.
    #     OIDC and SAML provision members just-in-time on login, so there is nothing
    #     to sync and this step is skipped.
    if args.provider_type == "LDAP":
        print("[3b] sync the LDAP directory")
        v.sync_ldap()

    # 4. Bind the group (and optional owner) to a PROJECT ROLE - the authority for
    #    project RBAC (groups bind by name with a trailing '@', which vcfa.py adds).
    #
    #    --project-role picks how much the members can do INSIDE their project. The
    #    four roles, least to most, with the handle you pass (console name -> handle,
    #    confirmed live; each is the built-in Kubernetes ClusterRole of that name):
    #
    #    --- view  = Project Auditor -------------------------------------------------
    #        Read-only across the project: sees everything, changes nothing. For an
    #        observer who must look but never touch.
    #
    #    --- edit  = Project User ----------------------------------------------------
    #        The isolation floor. Own-only on the deployment plane (a user sees and
    #        acts on only their OWN work), and NO reach onto the Kubernetes workload
    #        plane (a 403) - so NOT enough for the services portal. For catalog-only
    #        consumers who never need kubectl.
    #
    #    --- edit_adv = Project Advanced User ----------------------------------------
    #        The services-portal floor: full read+write across the project's namespaces
    #        (VM Service, Kubernetes, and the rest). Note the underscore - edit_adv, not
    #        edit-adv. It is project-WIDE and the workload plane has no per-user
    #        ownership, so two edit_adv members of ONE project can act on each other's
    #        objects - which is why own-only services needs a project per user.
    #
    #    --- admin = Project Administrator -------------------------------------------
    #        Everything edit_adv can do, PLUS manages the project's namespaces (create
    #        and delete) and its RBAC. This is the tier that lets a user SELF-SERVE
    #        their own namespaces (edit_adv can use existing ones but not create them);
    #        pair it with the narrow catalogs org role so the new-namespace form works
    #        (see examples/README.md).
    #
    print(f"[4] bind group {args.ad_group!r} -> project role {args.project_role!r} on {args.project}")
    v.bind_role(args.project, "Group", args.ad_group, args.project_role)
    if args.owner:
        print(f"[4b] bind owner {args.owner!r} -> {args.owner_role!r}")
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
