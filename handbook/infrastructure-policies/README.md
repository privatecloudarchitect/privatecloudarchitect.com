# What does an infrastructure policy do on your build?

Companion to field note 17
([privatecloudarchitect.com/notes/infrastructure-policies](https://privatecloudarchitect.com/notes/infrastructure-policies)):
one script that reads every VCF Automation infrastructure policy down to the vCenter compute policy under it, and, with
`--probe`, proves on throwaway objects what binds a VM. Stdlib Python only; no token or password is printed or written.

| File | What it is |
|---|---|
| `infra_policy.py` | Read-only by default: every provider policy (mandatory or optional, criteria, compatible zones, synced to vCenter), which organizations' region quotas list it, and with vCenter's credential the compute policy it names, the hosts carrying its host tag per cluster, the VMs carrying its VM tag, vCenter's namespace-level policies and the namespaces that list it. With `--probe`, the four layers built on throwaway objects, three VMs, and everything removed. |
| `infra.json` | The read from the reference estate. The field note renders it. |
| `infra-probe.json` | The probe's record from the same estate. The field note renders it. |
| `expected-output.md` | The printed lines of both runs. |

## Run it

```bash
export VCFA_HOST=<automation-fqdn>
export VCFA_PROVIDER_REFRESH_TOKEN_FILE=/path/to/provider-api-token    # mode 0600
export TLS_VERIFY=false                                                # only on a self-signed lab CA
# optional for the read, required by the probe: the vSphere side
export VC_HOST=<the vCenter behind the region>
export VC_USER=<account>
export VC_PASSWORD_FILE=/path/to/password                              # mode 0600; the session is closed at the end

python3 infra_policy.py
```

The policy plane answers only at API version 9.1.0, and the script sends it. An older version answers
`405 Method Not Allowed` on a path whose `OPTIONS` lists the method, which reads like a missing feature and is not.

## The probe

```bash
# a tenant organization administrator's session, as well as the above
export VCFA_ORG=<organization>
export VCFA_USER=<account>
export VCFA_PASSWORD_FILE=/path/to/password                            # mode 0600

python3 infra_policy.py --probe --project <a project nobody depends on> \
    --like <project>/<a namespace whose shape to copy> \
    --host-tag <category>/<tag already on the hosts you want>
```

The `--like` namespace and the host tag are read before anything is written, so a wrong one costs nothing. What it
writes, every name starting `probe-infra`, and removes:

1. **vCenter:** a tag category, two VM tags, and two VM-Host affinity compute policies on the host tag you name. No host
   is tagged or changed; only a VM carrying one of the new VM tags is bound.
2. **Provider:** two Optional policies on them, one with the criterion guest family Linux (the probe's VMs are Ubuntu),
   one with guest family Windows. Each create is retried until VCF Automation has synced the compute policy: it is
   refused as an unknown compute policy until then, which took from half a minute to fifteen minutes across the runs
   on the reference estate. The wait is bounded at 25 minutes.
3. **Provider:** both added to your organization's region quota. The list is read first and written back exactly at
   the end, and the residue read compares it.
4. **Tenant:** a namespace with the `--like` namespace's class, VPC and overrides, naming both policies, placed in a
   zone the policies are compatible with (the template's own zone when it is one), then three VMs from the same image:
   one that lists no policy, one that lists the Linux policy's ComputePolicy in `spec.policies`, and one that lists
   the Windows one.
5. **Tenant:** a second namespace naming the policies in a zone they are not compatible with, when the region has one.
   It should be refused.
6. **Teardown, always, in reverse:** VMs, namespaces (held two minutes after creation before the delete, and the delete
   sent again if the namespace is still there), the quota list, the provider's policies, then the compute policies
   and tags in vCenter, because deleting the provider's policy leaves the compute policy in place. A residue read ends
   the run.

A namespace made through the API carries no VM image library until one is attached; when the new namespace lists no
Ubuntu image, the probe attaches the `--like` namespace's library on vCenter's namespace setting.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Read: every policy is on some organization's quota, synced, and its compute policy found. Probe: every case behaved as the model says and nothing was left |
| 1 | Read: a policy applies to nothing. Probe: a case differed |
| 2 | A setting is missing, or a secret file is open to group or other (it is refused unread) |
| 3 | A read or a write failed; the step is named |
| 4 | A record refused to write because an estate name survived the labels |
| 5 | An unknown or incomplete argument |

## What the probe proved on the reference estate

Read on VCF Automation 9.1.1 and vCenter 9.1.1, and recorded in `infra-probe.json`:

- **The VM that listed no policy** was placed, carried no VM tag, and vCenter read the compute policy `NOT_APPLICABLE`.
- **The VM that opted in to the Linux policy** was placed carrying the compute policy's VM tag, and vCenter read `COMPLIANT`
  once it had evaluated. Read at power-on, compliance reads `UNKNOWN`, so the probe reads it until it changes, with a bound,
  and records how long that took.
- **The VM that opted in to the Windows policy** was not placed in the twenty minutes the probe watched it: its placement
  condition still read `failed to evaluate policy ... still being evaluated: policy not ready`.
- **The namespace in an incompatible zone** was refused.
- **The Supervisor namespace** held one `ComputePolicy` per policy, enforcement mode `Optional`, with the criterion
  translated into vSphere's match: guest family equals Linux.

Eleven earlier runs on throwaway objects on 2026-10-23 shaped the script. Every run's residue read found the quota list
as it was, and the read made before the script's own runs and the one made after them are identical: the estate's own
policy, its compute policy and the hosts carrying its host tag were left as they were.

## Scope, stated plainly

- **The read writes nothing.** The probe writes only the objects above, on the host tag you name, and removes them.
- **What a Mandatory policy does once on a quota was not tested.** The vendor's page says a mandatory policy cannot be
  assigned to a region quota once namespaces exist in that region, so testing it means a quota with no namespaces.
- **Criteria were tested with guest OS family only.** The other attributes (guest OS, custom label) and operators
  were not.
- **One region, one organization.** The read covers every quota the provider sees; the probe uses yours.
- **Every estate name in a record is a label**, and the script refuses to write a record in which one survived.
  Statuses, modes and kinds are the product's own words and are kept.
