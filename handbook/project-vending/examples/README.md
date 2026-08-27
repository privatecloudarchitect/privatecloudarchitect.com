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
