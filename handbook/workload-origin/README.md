# Where each namespace was born, read from your own estate

Companion to the chapter
([privatecloudarchitect.com/handbook/workload-origin](https://privatecloudarchitect.com/handbook/workload-origin)):
one read-only script that lists every namespace on your Supervisors with the plane that created it, and checks
the origin record you keep for the ones created on the Supervisor itself.

The chapter's point is that a namespace's origin fixes what its workloads can ever be given: one VCF Automation
created carries tenancy, and one created on a Supervisor attached to an NSX Manager can never be imported. No
single field on the namespace names its origin, so the script joins three reads and shows the evidence for each
answer.

| File | What it is |
|---|---|
| `origins.py` | Read-only, stdlib Python. Reads every namespace on each Supervisor from vCenter (with its system metadata and its VPC), the namespace each installed Supervisor Service runs in, and the namespace records VCF Automation holds, then gives each namespace one origin: `automation`, `service`, `supervisor`, `orphan` or `record-only`. With `--record` it also checks your origin record. Exit 0 every namespace has an origin and every check holds, 1 a check fails, 2 a read failed. |
| `origin-record.example.csv` | The shape of the record you keep: one row per namespace created on the Supervisor, saying whether it is provisional and, if so, who may decide it has become permanent. |
| `origins.json` | The record from the reference estate, 2026-10-07, written with `--scrub --json` while one throwaway namespace created through vCenter stood beside the estate's own, with the throwaway's outcome added under `probe`: the Supervisor's state before the create, the evidence the script read, the record check both ways, what the create made in vCenter and NSX, and the residue read after the delete. |
| `expected-output.md` | The transcripts of those runs. |

## Run it

```bash
export VCENTER_HOSTS=<vcenter-fqdn>                         # the vCenter in front of each Supervisor, comma-separated
export VCENTER_USER=<user@sso-domain>
export VCENTER_PASSWORD_FILE=/path/to/password              # mode 0600
#   or, instead of user and password, an existing session: VCENTER_SESSION_FILE=/path/to/session-id
export VCFA_HOST=<automation-fqdn>
export VCFA_PROVIDER_TOKEN_FILE=/path/to/bearer             # a provider administrator's bearer, mode 0600
export TLS_VERIFY=false                                     # only on a self-signed lab CA

python3 origins.py                                          # one line per namespace: origin and evidence
python3 origins.py --record origin-record.csv               # also check the record you keep
python3 origins.py --json                                   # the whole join as JSON
python3 origins.py --scrub                                  # every estate name replaced, for a transcript you share
```

## How it decides

| origin | the evidence it reads |
|---|---|
| `automation` | VCF Automation holds a record for the namespace on that Supervisor (`GET /cloudapi/v1/namespaceSummaries`). A check confirms that vCenter's `system_metadata` names the same organization and project; only VCF Automation writes that field. |
| `service` | An installed Supervisor Service runs in it (the service's `service_namespace`). These are the platform's own. |
| `supervisor` | Neither of the above: created on the Supervisor itself, through vCenter or its API. On the reference estate such a namespace carries no system metadata and no creator, and gets a VPC created for it in the Supervisor's default NSX project, where VCF Automation's sit in the organization's own. |
| `orphan` | vCenter's metadata names an organization and project, but VCF Automation holds no record of the namespace. |
| `record-only` | VCF Automation holds a record whose namespace is not on the Supervisor. |

The VPC placement is shown beside each answer as evidence; the record and the metadata decide the origin.

## Scope, stated plainly

- Read-only: nothing is created, changed or deleted, and no token value is printed.
- Run on the reference estate (VCF 9.1, one Supervisor on a VPC-networked NSX) on 2026-10-07 through both
  documented vCenter paths (a session file, then user and password), with the same result.
- The reference estate held no namespace created on the Supervisor, so the `supervisor` class was proved on a
  throwaway on 2026-10-07: one namespace created through vCenter's API with no workloads, listed as `supervisor`,
  checked against an origin record without and then with its row (exit 1, then 0), and deleted, with vCenter, NSX
  and VCF Automation read back identical to the read taken just before the create. The `orphan` and
  `record-only` classes were not produced on purpose; they follow from the same join.
- Supervisor Services are read per Supervisor, so a namespace left behind by an uninstalled service would list as
  `supervisor`. Read its name before acting on it.
- `record-only` reads the provider's namespace records. A tenant project's own namespace object, which on the
  reference estate outlived a provider-side delete on 2026-09-29 and kept its project from being deleted, is not
  read here.
- It does not say whether a namespace is provisional. That is a decision, and the record you keep is where it
  lives; `--record` checks that the decision has been written down.
