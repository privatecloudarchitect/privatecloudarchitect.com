# Examples

Runnable end-to-end demonstrations that use the client and tools in
[`../scripts/`](../scripts/). Where `scripts/` holds the client (`vcfa.py`) and the
atomic operations you run in production, these are full-scenario walkthroughs: they
provision, exercise, and (for the isolation demo) prove a pattern on your own estate.

Both are parameterized: every estate-specific value is a flag or an environment
variable, and secrets are read from a file or the environment, never inline.

| Example | What it does | Extra requirement |
|---|---|---|
| `per_user_isolation.py` | Builds a project per user (each a Project Advanced User), then proves neither can see or touch the other's. The own-only pattern for services self-service, end to end. | none (stdlib) |
| `ad_fixtures.py` | Provisions throwaway Active Directory test fixtures (a group + users) directly over LDAPS, and removes them with `--teardown`. Use it to create a directory group to feed the onboarding flow, when you don't already have one. | `pip install ldap3` |

## per_user_isolation.py

Give each user their own project and prove the isolation. Reads the `VCFA_*`
variables (see `../scripts/README.md`) for the administrator; set `TENANT_PASSWORD`
to the named users' shared password to also run the proof (log in as each and
confirm they reach only their own project).

```bash
export VCFA_HOST=vcfa.example.com VCFA_ORG=Acme VCFA_USER=admin
export VCFA_PASSWORD="$(secret-tool lookup service vcfa-admin)"
export TENANT_PASSWORD="$(secret-tool lookup service vcfa-tenants)"   # optional, runs the proof
python3 per_user_isolation.py --assign alice:proj-alice --assign bob:proj-bob \
    --region <your-region> [--vpc <v>] [--seg <s>] [--zone <z>]
```

Why a project each, and not one shared project with a namespace apiece: the project
role is project-wide and the Kubernetes workload plane has no per-user ownership, so
two Project Advanced Users in the same project can each act on the other's
namespaces. The project is the trust boundary; the namespace lives inside it and
cannot be shared across two projects. See module 02 in the parent folder.

Note: each named user must already have synced from your directory into the
supervisor's identity provider. A newly created directory user can log in before
that periodic sync completes but cannot yet be bound here or operate on the workload
plane, so provision users ahead of the run (or use ones that already exist).

## ad_fixtures.py

Provisions a disposable AD group and users so you have a directory group to import.
The only script here that needs a dependency (`ldap3`) and a domain administrator;
AD writes are directory-specific, which is why this is an example, not part of the
stdlib-only client. All coordinates are environment variables and passwords are read
from a secret file - nothing estate-specific is in the code.

```bash
export AD_HOST=ad.example.com AD_ADMIN=Administrator@example.com
export AD_ADMIN_SECRET=/path/to/ad-admin.json     # JSON with a "password" key
python3 ad_fixtures.py --group "Example AD Group" --users ExampleUser1,ExampleUser2
python3 ad_fixtures.py --group "Example AD Group" --users ExampleUser1,ExampleUser2 --teardown
```

## LDAP, OIDC, or SAML

The onboarding client works with any of the three identity sources; the difference is
confined to the import. `e2e_tenant_setup.py --provider-type` takes `LDAP` (default),
`OIDC`, or `SAML`, and **step 3 of that script spells out all three options and the
caveat of each inline** - so you see them at the point of the import, not only here.
Everything downstream (the project, the `ProjectRoleBinding`, the namespace, and the
isolation model) is identical regardless of the source. In brief:

- **LDAP** (on-prem Active Directory) - the group resolves against the directory by
  name, and you can also import and bind individual users. A brand-new principal takes
  a periodic sync before it works on the workload plane (`sync_ldap` refreshes the org
  view; the supervisor plane syncs on its own schedule). `ad_fixtures.py` makes test
  fixtures over LDAPS.
- **OIDC** (`providerType OAUTH`) - the group matches the token's `groups` claim and
  members provision just-in-time on first login (no per-user import, no directory
  sync). Confirm your IdP passes group membership and whether it carries group names
  or ids.
- **SAML** (e.g. Azure AD) - the same just-in-time shape as OIDC, matched on the
  assertion's group claim. Azure AD may send the group's display name or its object id,
  so import by whichever it emits. `ad_fixtures.py` does not apply; create the group in
  Azure AD via Microsoft Graph or the portal first.

## The self-service end-state (Azure AD / SAML, Project Administrator)

The refined target: pull users from Azure AD over SAML, give each their own project as
**Project Administrator** while keeping them **Organization User**, and let them
self-serve namespaces without seeing or touching anyone else's. Assemble it from the
pieces already here - no new tool.

Because SAML imports groups (users are just-in-time), the per-user unit is a **per-user
Azure AD group** (one member). The group binds to the project as Project Administrator;
the user lands there on first login. A team that shares a boundary is one group and one
project instead.

```bash
# once per org: the narrow catalogs role that lets a Project Administrator's
# new-namespace form work (Organization User + three catalog reads, no cross-project)
python3 ../scripts/setup_catalogs_role.py --name "Namespace Self-Service User"

# per user (or per team): import their Azure AD group AS that catalogs role, create
# their project, bind the group Project Administrator, let them self-serve namespaces
python3 ../scripts/e2e_tenant_setup.py \
    --project prj-alice --ad-group "prj-alice" --provider-type SAML \
    --group-org-role "Namespace Self-Service User" --project-role admin \
    --region <your-region> [--vpc <v>] [--seg <s>] [--zone <z>] --no-namespace
```

What each flag secures:

- `--provider-type SAML` - match Azure AD; members provision just-in-time on login.
- `--group-org-role "Namespace Self-Service User"` - the org role is Organization User
  plus the catalog reads, so they can open the new-namespace form yet see no other
  project.
- `--project-role admin` - **Project Administrator** on their OWN project: full control
  and the right to create and manage their own namespaces (a Project Advanced User,
  `edit_adv`, could use namespaces but not create them).
- `--no-namespace` - provision the project and leave namespace creation to them; drop
  it to seed a first namespace instead.

The result: each user is Organization User at the org and Project Administrator of a
project only they belong to, self-serving namespaces and resources, unable to see or
touch anyone else's - the isolation is the project boundary, exactly as in the LDAP
walkthrough.
