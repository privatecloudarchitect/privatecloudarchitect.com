# Day-2 governance: the two-policy first change

The runnable companion to
[Day-2 governance: who controls the action count](https://privatecloudarchitect.com/handbook/day2-governance)
(and step 3 of [the assembled isolation design](https://privatecloudarchitect.com/handbook/isolation-design)).
Two HARD Day-2 action policies, shipped as one change, named per the sheet's convention.

**Provenance:** the policy type, body shape, and regime flip were proven on a live VCF 9.1 estate
(All Apps), 2026-08-08 through 2026-08-11. The policy model, the decision log, the dry run, the two checks and the
platform's validation answers were read again on VCF Automation 9.1.1.0100 on 2026-10-18
([`expected-output.md`](expected-output.md)). The two deletion fences that are policies, approval on destroy and a
lease, were exercised on throwaway objects on 9.1.1 on 2026-10-22 by `fences.py`, twice, the same answer both times.

## What is here

| Step | File | What it does |
|---|---|---|
| 1 | [`governance.py`](governance.py) | Read-only. Asks the policy plane to describe itself: the types this build declares, the three schemas each publishes, the capability flags and limits that make them unequal, the action selectors and the tree their wildcards form, the policies your organization holds, and the decision log with the rank the plane gave each applied policy and the effective definition it computed. Writes two records with every organization value replaced by a placeholder. |
| 2 | `--rehearse` | Optional. Runs the platform's own dry run of one more policy, reads back the decisions it would have produced, and proves the policy list is unchanged. |
| 3 | [`policies/`](policies/) | The two-policy first change, as importable bodies. |
| 4 | `--actions <deployment-id>` | Read-only. Reads one deployment's actions as you until two reads five seconds apart agree, and prints the count it settled on: the read to trust after a policy change. |
| 5 | `--authority <authority>` | Holds one authority against the forms the decision log writes (prefix, case, the group's trailing `@`), sends it through the platform's own check with `validationOnly`, which creates nothing, and says whether any decision holds a bucket for it yet. |
| 6 | [`fences.py`](fences.py) `--project <project>` | Writes, on objects it creates and deletes. A throwaway blueprint that provisions nothing, a lease and an approval on `Deployment.Delete` each scoped to that blueprint alone, one deployment, then two destroy requests: one you reject, one you approve. Records what each step did. See [the two deletion fences](#the-two-deletion-fences-that-are-policies). |

```bash
export VCFA_HOST=<automation-fqdn> VCFA_ORG=<org> VCFA_USER=<account>
( umask 077; mkdir -p ~/.vcf && cat > ~/.vcf/vcfa-password )   # paste your password, then Ctrl-D
export VCFA_PASSWORD_FILE=~/.vcf/vcfa-password             # mode 0600; or VCFA_REFRESH_TOKEN_FILE
export TLS_VERIFY=false                                    # only on a self-signed lab CA

python3 governance.py                          # read-only
python3 governance.py --rehearse               # also ask what one more policy would do
python3 governance.py --actions <deployment-id>
python3 governance.py --authority 'GROUP:Engineers@'
python3 fences.py --project <a project nobody depends on>   # writes, then deletes; see below
```

The sign-in is a session login as `<account>@<org>`, or a refresh token minted for the organization in a file of
mode 0600. A secret file open to group or other is refused before it is read. Exit codes: 0 read (for `--actions`
the count settled, for `--authority` well formed and held by a decision); 1 for `--actions` no two reads agreed
within a minute, for `--authority` well formed and held by no decision yet; 2 a call failed or the sign-in was
refused; 3 for `--authority` a form the decision log never holds; 5 an unknown argument.

`policy-model.json` and `decisions.json` are what it writes, and the chapter's plates render them. The decision
log is read in full, every page sorted by id: the plane serves at most 200 entries a page, and a read without a
sort has no stable order across pages.

### About `--rehearse`

`POST /policy/api/policies` takes a `dryRun` query parameter. The plane answers 202, creates nothing, and returns
a `Location` naming the decisions it *would* have produced, one per target the policy would touch. That is the
only way to see the regime flip below and the union arithmetic before they are real, and it is the single most
useful call on this API.

The flag sends that call with a grant naming a group that exists nowhere, follows the location, and reports how
many targets would be affected and how many policies would then apply to each. It then re-reads the policy list
and **stops hard if anything was created**. It compares each affected target with how many policies apply to it
today, read from the decision log; the reference estate's numbers are in
[`expected-output.md`](expected-output.md).

There is a narrower mode, `?validationOnly=true`, which checks the policy body and returns it without creating
anything: the cheap gate for a pipeline. `--authority` uses it. It refuses an action that exists nowhere and a
missing required field by name, and accepts an authority with no prefix, which is why the authority needs its
own check.

## The two deletion fences that are policies

The chapter's deletion fences include two that are policy types: an approval on destroy, and a lease. `fences.py`
proves both on your build without touching anything you run. In the project you name it creates a blueprint whose
only resource is a generated password (no machine, no namespace), and two HARD policies whose criteria match that
blueprint's id alone: a lease of one day with no grace, the shortest the schema's day unit allows, and an approval on
`Deployment.Delete` naming you as the one approver, expiring after a day with `REJECT` as the decision. It waits a
minute for the policies to reach new requests, deploys the blueprint, and reads the lease the deployment was given.
Then it asks to destroy the deployment, rejects the approval as the approver and reads that the deployment is still
there, asks again, approves, and reads it gone. Teardown runs whatever happened: any request still waiting is
rejected, the approval policy goes before anything it could hold, then the deployment if it is still there, the
lease and the blueprint, and a residue read counts anything named `probe-fences` that is left.

On the reference estate, VCF Automation 9.1.1 on 2026-10-22, two runs gave the same answer: the deployment's lease
read one day after its creation; each destroy request read `APPROVAL_PENDING` within seconds; the rejection set the
request to `APPROVAL_REJECTED` and left the deployment in place; the approval removed it within seconds; nothing was
left behind. The account that asked was allowed to approve its own request, because the policy named it.

Two things the run taught about the approvals API:

- **List approvals without a sort.** Every other list here is read page by page sorted by id; the approvals list
  answers HTTP 500 to that, and the script reads it unsorted. A failed read stops the run rather than waiting.
- **An approval item names its request in `requestId`.** Its `status` is the answer (`PENDING`, `REJECTED`,
  `APPROVED`); its `decision` is the policy's decision on expiry, and reads `REJECT` even on an approved item.

The account must hold the organization administrator role. Exit codes: 0 both fences held; 1 a fence did not hold,
and `fences.json` says which step; 2 a setting is missing or a secret file is open to group or other; 3 a read or a
write failed; 4 the record refused to write because an estate value survived; 5 an unknown argument, or `--project`
missing. The record and every printed line carry labels in place of the project, user, organization and host.

## Why two policies travel together

The first HARD Day-2 action policy in a project ends the permissive default for every principal
the project's policies do not name, project administrators included. Shipping the tenant grant
alone therefore strands the platform team in the same instant it governs the tenant. The pair:

| File | Grants | To |
|---|---|---|
| `policies/tenant-group-all-actions.hard.json` | every action, on what their role makes visible | the tenant group (bound to `edit`: own-only) |
| `policies/operators-grant.hard.json` | every action | the operators' group |

## The call

One POST per policy, as a principal allowed to manage policies:

```
POST https://<vcfa-fqdn>/policy/api/policies
Content-Type: application/json

<the file's body, with your UUIDs and group names filled in>
```

Field notes, all proven on the reference build:

- `orgId` and `projectId` are **bare UUIDs**, not `urn:` forms.
- `typeId` on 9.1 is `com.vmware.policy.deployment.action`.
- `actions: ["*"]` grants every action; `actions: []` is an explicit deny.
- **Omit `projectId`** to make a policy org-scoped (the A.1 dial); include it for one project (A.2).
- Group authorities carry a trailing `@`: `GROUP:Engineers@`.
- Policy names answer three questions in order, `Members | Action Scope | Visibility`, so the
  policy list reads as the access model. The visibility field names its true source (the org and
  project roles), because a policy grants actions, never visibility.

## Verification

Effects settled in roughly 16 to 20 seconds on the reference estate in August 2026; a read inside that window
reports the previous regime. Read the action count as an affected principal, under their own session, until two
reads agree:

```
python3 governance.py --actions <deployment-id>      # GET /deployment/api/deployments/<id>/actions, until stable
```

Expected after this pair lands: tenant-group members hold the full set on their own deployments,
operators hold the full set on everything their roles make visible, and every principal named by
neither policy holds zero. Poll until the count is stable before trusting it.

## Rollback

Deleting a policy (`DELETE /policy/api/policies/{id}`) removes its grant; deleting the last HARD
action policy in the project returns the project to the permissive default, after the same
propagation window.
