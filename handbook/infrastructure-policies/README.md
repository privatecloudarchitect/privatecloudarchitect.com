# What does an infrastructure policy do on your build?

Companion to field note 17
([privatecloudarchitect.com/notes/infrastructure-policies](https://privatecloudarchitect.com/notes/infrastructure-policies)):
one script that reads every VCF Automation infrastructure policy down to the vCenter compute policy under it, and, with
`--probe`, proves on throwaway objects what binds a VM. Stdlib Python only; no token or password is printed or written.

| File | What it is |
|---|---|
| `infra_policy.py` | Read-only by default: every provider policy (mandatory or optional, criteria, compatible zones, synced to vCenter), which organizations' region quotas list it, and with vCenter's credential the compute policy it names, the hosts carrying its host tag per cluster, the VMs carrying its VM tag, vCenter's namespace-level policies and the namespaces that list it. With `--probe`, the four layers built on throwaway objects, three VMs, and everything removed. |
| `infra.json` | An example record of the read, from the run on this site's reference estate on 2026-10-23; its printed lines are in `expected-output.md`. Your run writes your own. |
| `infra-probe.json` | An example record of the probe, from the same run. Your probe writes your own. |
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
   refused as an unknown compute policy until then; VMware's page says the sync might take a few minutes. The probe
   records how long it waited, and the wait is bounded at 25 minutes.
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

## What the probe proves

On VCF Automation 9.1.1 and vCenter 9.1.1:

- **A VM that lists no policy** is placed, carries no VM tag, and vCenter reads the compute policy `NOT_APPLICABLE`.
- **A VM that opts in to a policy it matches** is placed carrying the compute policy's VM tag, and vCenter reads `COMPLIANT`
  once it has evaluated. Read at power-on, compliance reads `UNKNOWN`, so the probe reads it until it changes, with a bound,
  and records how long that took.
- **A VM that opts in to a policy it does not match** is not placed: its placement condition reads
  `failed to evaluate policy ... still being evaluated: policy not ready` for as long as the probe watches it.
- **A namespace in an incompatible zone** is refused.
- **The Supervisor namespace** holds one `ComputePolicy` per policy it names, with its enforcement mode and the criterion
  translated into vSphere's match.

Earlier runs on throwaway objects shaped the script. Every run's residue read found the quota list as it was, and the
policies, compute policies and host tags that were there before were left as they were. An example of the probe's
printed lines is in `expected-output.md`.

## Scope, stated plainly

- **The read writes nothing.** The probe writes only the objects above, on the host tag you name, and removes them.
- **What a Mandatory policy does once on a quota was not tested.** The vendor's page says a mandatory policy cannot be
  assigned to a region quota once namespaces exist in that region, so testing it means a quota with no namespaces.
- **Criteria were tested with guest OS family only.** The other attributes (guest OS, custom label) and operators
  were not.
- **One region, one organization.** The read covers every quota the provider sees; the probe uses yours.
- **Every estate name in a record is a label**, and the script refuses to write a record in which one survived.
  Statuses, modes and kinds are the product's own words and are kept.
