# Scripts

Five standard-library Python scripts (no pip installs). `vcfa.py` is the shared
client; the other four are thin command-line tools that use it. Read `vcfa.py`
first: it is the API fundamentals as code, and module 00 walks through it.

## Prerequisites

- Python 3.9 or newer. Nothing else.
- Network reach to your VCFA appliance.
- Four environment variables (the scripts read these; nothing is hard-coded):

  ```bash
  export VCFA_HOST=vcfa.example.com     # your appliance FQDN
  export VCFA_ORG=Acme                  # the tenant organization name
  export VCFA_USER=admin                # the account to act as
  export VCFA_PASSWORD="$(secret-tool lookup service vcfa)"   # from a secret store
  export VCFA_INSECURE=1                # only for a self-signed lab certificate
  ```

  Source `VCFA_PASSWORD` from a secret store, never type it inline where it lands
  in shell history. For a production appliance with a real certificate, leave
  `VCFA_INSECURE` unset so TLS is verified.

- The account in `VCFA_USER` must hold the right the task needs. Creating projects
  and custom roles is an organization-administrator operation; `verify_scope.py`
  is meant to be run as a tenant, to see what that tenant sees.

## The tools

| Script | What it does | Run as |
|---|---|---|
| `python3 vcfa.py` | Logs in and prints who you are and the projects you can see. Your first API call. | anyone |
| `python3 setup_catalogs_role.py --name "Namespace Self-Service User"` | Creates the custom org role that populates the new-namespace form. Idempotent. | org admin |
| `python3 vend_project.py --project team-acme --owner alice --owner-role edit_adv --operators-group "Platform Operators" --region <r>` | Creates a project, binds the owner and operators, and creates the first namespace. `--region` is required; `--vpc`/`--seg`/`--zone` are optional per your estate. | org admin |
| `python3 e2e_tenant_setup.py --project team-acme --ad-group "Platform Engineers" --region <r>` | The full onboarding in one run, top to bottom: authenticate, create the project, import an AD group, bind it, create the first namespace, poll to Ready. | org admin |
| `python3 verify_scope.py` | Logs in as a tenant and prints the projects and namespaces they can see. | the tenant |

Read a script's top-of-file docstring for its full options and an example.

## Naming conventions

A little discipline in names pays off for the life of the estate. There are two levels,
and each script repeats the gist in a comment next to the name it takes.

**The hard rule (the platform enforces it):** projects and namespaces are Kubernetes
objects, so their names are RFC 1123 - **lowercase letters, digits, and hyphens only**,
starting and ending with an alphanumeric, no spaces, underscores, or capitals, 63
characters or fewer. `team-payments` is valid; `Team_Payments` is not.

**A convention worth adopting (a good habit, not enforced):**

| Object | Pattern | Example |
|---|---|---|
| Project | the trust boundary's owner in kebab-case, with a short type prefix so they group | `team-payments`, `usr-alice`, `sandbox-bob` |
| Namespace | the namespace's PURPOSE, not "ns" - the platform appends `-<random>` for uniqueness | stem `web-` -> `web-a1b2c`; stem `data-` -> `data-9f3k1` |
| Directory group | mirror the project so the group-to-project mapping is legible | `grp-team-payments`, one group per project |

Principles: make the name self-describing and greppable; put the stable identity (the
owner or the purpose) in the base and let the platform's suffix carry the uniqueness;
keep it short; and keep dates, ticket numbers, and personal data OUT of the base name -
the object outlives them. Pick one scheme and apply it everywhere: consistency is worth
more than any single clever name.

## Reading the estate values

`vend_project.py` needs your region, VPC, and service engine group names, plus a
zone name. Read them once from any namespace that already works, then reuse them:

```bash
# as an admin, against a project that already hosts a namespace
curl -sk -H "Authorization: Bearer $TOKEN" \
  "https://$VCFA_HOST/cci/kubernetes/apis/infrastructure.cci.vmware.com/v1alpha3/namespaces/<project>/supervisornamespaces/<name>" \
  | python3 -c "import sys,json; s=json.load(sys.stdin)['spec']; print(s['regionName'], s['vpcName'], s['segName'])"
```

## Safety

- The scripts create objects (`vend_project.py`, `setup_catalogs_role.py`) but
  never delete anything. Teardown is a deliberate, separate act you perform by
  hand or with your own tooling.
- `vend_project.py` fails if the project name already exists. That is intentional:
  a re-run cannot silently produce a duplicate tenant.
- `setup_catalogs_role.py` is idempotent: run it repeatedly and it converges the
  same role.
- `verify_scope.py` is read-only.
