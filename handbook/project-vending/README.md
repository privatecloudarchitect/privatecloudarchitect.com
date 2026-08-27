# Project vending: the runnable companion

The runnable companion to
[field note 03, a tenant project and its first namespace stand up entirely by API](https://privatecloudarchitect.com/notes/vcfa-project-vending),
and the code the [tenant self-service playbook](https://privatecloudarchitect.com/playbooks/tenant-self-service-isolation)
runs. Four standard-library Python scripts that create a tenant project and its
first Supervisor Namespace on **your** VCF Automation 9.1 organization, entirely
by API, and confirm the scope a tenant ends up with.

**Provenance:** proven on a live VCF Automation 9.1 estate, 2026-08-26 (the vend
reached a Ready namespace on two freshly created projects; the scope reads and the
role convergence ran against real principals). This directory is the `repo`
referent for the field note and the playbook.

## What is here

```
vcfa.py                 a minimal, commented VCFA API client (the API fundamentals as code)
vend_project.py         create a project, bind the owner and operators, create the first namespace
setup_catalogs_role.py  create the custom org role that populates the new-namespace form
verify_scope.py         log in as a tenant and print exactly what they can see
```

Read `vcfa.py` first. It is the two things a newcomer to the VCFA API must learn,
as code: the session token comes back in a response header, and there are two API
surfaces (cloudapi for identity and roles, the Cloud Consumption Interface for
projects and namespaces).

## Prerequisites

- Python 3.9 or newer. Nothing else; no pip installs.
- Four environment variables. Nothing secret is hard-coded:

  ```bash
  export VCFA_HOST=vcfa.example.com     # your appliance FQDN
  export VCFA_ORG=Acme                  # the tenant organization name
  export VCFA_USER=admin                # the account to act as
  export VCFA_PASSWORD="$(secret-tool lookup service vcfa)"   # from a secret store
  export VCFA_INSECURE=1                # only for a self-signed lab certificate
  ```

- The account must hold the right the task needs. Creating projects and custom
  roles is an organization-administrator operation; `verify_scope.py` is run as the
  tenant, to see what that tenant sees.
- For `vend_project.py`, your estate's region, VPC, and service engine group names,
  plus a zone name. Read them once from a namespace that already works (the script
  header shows the call), then reuse them.

## The runbook

```bash
# your first call: log in and see who you are
python3 vcfa.py

# one-time per org: the role that lets a namespace operator use the create form
python3 setup_catalogs_role.py --name "Namespace Self-Service User"

# once per tenant trust boundary: the three-call vend
python3 vend_project.py \
    --project team-acme --owner alice --owner-role edit_adv \
    --operators-group "Platform Operators" \
    --region <your-region> --vpc <your-vpc> --seg <your-service-engine-group> \
    --zone <your-zone>

# confirm the scope, run as the tenant
VCFA_USER=alice python3 verify_scope.py
```

The two spec fields that were the whole fresh-project blocker are `generateName`
(the namespace derives its own name; a fixed name is rejected) and `segName` (the
load-balancer service engine group; omit it on an NSX-registered load-balancing
region and the create fails "SEG is required"). The field note explains both.

## What ships is what ran

- The scripts create objects (`vend_project.py`, `setup_catalogs_role.py`) but never
  delete anything. Teardown is a deliberate, separate act.
- `vend_project.py` fails if the project name already exists, so a re-run cannot
  silently produce a duplicate tenant.
- `setup_catalogs_role.py` is idempotent; `verify_scope.py` is read-only.
- Everything is parameterized for your estate through the environment variables and
  the command-line flags; nothing here assumes the estate it was proven on.
