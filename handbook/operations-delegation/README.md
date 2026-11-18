# A team acts on its own VMs through VCF Operations, and only on those

Companion to the chapter
([privatecloudarchitect.com/handbook/operations-delegation](https://privatecloudarchitect.com/handbook/operations-delegation)):
one script that carries the whole loop of delegating Day-2 work to a team through VCF Operations. It plans the team's
role and scope, applies them, proves the boundary from inside it as one of the team's members, runs an action the
documented way, reads who acted, and takes it all back. Stdlib Python only; no token or password is printed or written,
and a secret file open to group or other is refused unread.

| File | What it is |
|---|---|
| `delegation.py` | `plan` (read-only), `apply` (dry run unless `--execute`), `check` (as a member, runs nothing), `act` (as a member, dry run unless `--execute`), `who` (read-only) and `revoke` (dry run unless `--execute`). Each writes `<subcommand>.json` to `OUT`, every estate name replaced by a placeholder, and refuses to write one in which a name survived. |
| `opslib.py` | The sign-in every VCF Operations companion shares, byte for byte: an api token from the console traded at the identity broker for a bearer. |
| `records/` | Example output: the record each step wrote in one run, kept to compare your own records against. |
| `expected-output.md` | Example output: what each step printed in the same run. |

## Before you run it

1. **The team's group is in VCF single sign-on.** The identity provider syncs only the groups its sync profile names.
   Add the team's group under the directory's Group Provisioning, one group, never Select All (which syncs the whole
   container and every group added to it later), and sync. Provisioning one user through the broker's API was refused
   on a directory in full-sync mode; the group is the route that worked. Read the profile before and after and compare
   the groups by their DN, because the console's save reorders them, and when the profile includes nested groups and
   their members, count those members in the number of users you expect the sync to add.
2. **The vCenter's integration in VCF Operations has actions activated.** The action runs as that integration's own
   account, which is why the team needs no vCenter permission.
3. **Your own identity is a VCF Operations administrator**, with an api token minted in the console, mode 0600.
4. **For `check` and `act`, one of the team's members mints an api token** in the console after the team's role exists,
   signing in once through VCF single sign-on, and gives you the file, mode 0600.

## Run it

```bash
export OPS_HOST=<operations-fqdn> OPS_BROKER_HOST=<identity-broker-fqdn>
export OPS_API_TOKEN_FILE=~/.secrets/ops-admin                 # mode 0600; or OPS_TOKEN_FILE, an exchanged bearer
export OPS_TLS_VERIFY=false                                    # only on a self-signed lab CA
export OUT=~/delegation-records                                # one folder per run, so no record replaces another

T="--team payments --group payments-ops@example.com --objects pay-web-01,pay-db-01"
python3 delegation.py plan  $T                                 # read-only: what exists, what apply would write
python3 delegation.py apply $T --execute                       # add --api if the team acts through the API

export OPS_MEMBER_API_TOKEN_FILE=~/.secrets/ops-member         # a member's api token, mode 0600
python3 delegation.py check $T --outside hr-db-01              # as the member; runs no action
python3 delegation.py act   $T --object pay-web-01 --action "Power Off VM"            # the query only
python3 delegation.py act   $T --object pay-web-01 --action "Power Off VM" --execute  # sends it, reads the status
python3 delegation.py who   --task <task id act printed>       # who VCF Operations says acted
python3 delegation.py revoke $T --execute                      # takes back what apply made
```

`delegation.py` exits 0 when it is done and every check held; 1 when a check did not hold (a boundary, the recipe, a
read back, an action not offered or refused); 2 on a missing or wrong argument or setting, or a secret file open to
group or other; 3 when the sign-in or a read failed; 4 when the record was not written because an estate name survived
the scrub; and 5 when `apply` or `revoke` refused to change a role or scope it did not mark.

## What each step decides

**The recipe.** The act role is everything ReadOnly may see, the VM actions you name (`--actions`, by the names the
console lists; the default is Power Off VM and Power On VM), and Recent Tasks, so a member can read the result of its
own action. `--api` adds All other Read, Write APIs, which an action sent through the API needs: without it the execute
answers a bare HTML 403 that names no privilege. The console runs the action without it. The scope is the VMs you name
by `--objects`, selected one by one.

**What `apply` will and will not touch.** It names the role `<team>-act` and the scope `<team>-scope`, and marks each in
its description (`managed by delegation.py`). It changes a role or scope only when the mark is there, and stops with exit
5 otherwise. When the group is already imported, it adds or replaces only this role's permission on it, which VCF
Operations replaces per role, so the group's other permissions stay as they are; when the group is not imported, it
imports it from the VCF SSO source with the permission. Every write is read back, and a second run with nothing to
change sends nothing.

**A VCF role on the group.** `plan` reads the group's VCF roles in the realm and reports any it finds: a VCF role
overrides the scope, so the group's members see beyond it. `delegation.py` never changes VCF roles; take them off the
group in the console.

**`check`.** As the member: the member's record lists the team's group, the member holds no permission of its own, each
named VM is readable and its action query answered, and each `--outside` VM is invisible (404) and its action query
refused. A query only populates an action, so nothing runs.

**`act`.** The documented order: the action's query, then the body it returns. An action is offered only when the
query's `parameterGroup` carries the VM. VCF Operations decides from its last collection, so a VM powered off moments
ago is not offered Power On until the next cycle; `act` then reports it not offered and sends nothing. It runs only on one of
`--objects`, never on a VM outside the scope.

**`who`.** VCF Operations' action status for each task: the action, its state, who submitted it, through which source,
and on which VM. vCenter's events for the same change name only the integration's account, so this is where the person
is on record.

**`revoke`.** This role's permission off the group, the group's import when `apply` made it, then the role and the scope,
each only with the mark, and a read that they are gone. It touches no user record: the member's own VCF Operations
record, made at its first sign-in, stays until you remove it.

## Reading the records

| Record | Fields to read |
|---|---|
| `plan.json` | `findings` (what to fix first), `would` (what `apply` would send), `vcf_roles` (null when your identity cannot read the realm), `recipe` |
| `apply.json` | `sent` (each write and its status), `held` (each read back), `after` |
| `check.json` | `rows`: each check, what it expected, what it got, `held` |
| `act.json` | `offered`, `execute`, `task`, `status.submittedBy`, and `why` whenever it did not complete |
| `who.json` | `tasks`: `submittedBy`, `authSource`, `object`, `state` |
| `revoke.json` | `sent`, `held` |

Every name is a placeholder: `{{team-1}}` the team, `{{role-1}}` its role, `{{scope-1}}` its scope, `{{group-1}}` its
group, `{{person-1}}` a member, `{{vm-n}}` a VM, `{{id-n}}` an id, `{{host-n}}` a host.

## What it does not cover

- **VCF roles.** It reads them and never assigns or removes one.
- **A scope by group or by tag.** The scope it writes selects VMs by name; a scope built on a custom group is made in the
  console.
- **Actions on other kinds of object.** Its actions are VM actions, `<action>-VMWARE-VirtualMachine`.
- **Supervisor namespaces.** Access to a namespace is granted in vCenter, per namespace, as Owner, Edit or View; a VCF
  Operations role does not reach it.
- **Automated actions.** By VMware's documentation, anyone who can modify alerts, recommendations and policies can
  automate an action without permission to run it, and an action an alert triggers is submitted by the
  `automationAdmin` account, so `who` names that account for it, not a person. Keep the right to edit alerts,
  recommendations and policies as narrow as the right to act.

Held by `platform/tests/test_operations_delegation_companion.py` in the private repository, offline, against a stand-in
for VCF Operations.
