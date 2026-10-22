# What `governance.py` prints

Run against one VCF Automation 9.1.1.0100 organization on 2026-10-18, signed in with a session login, with
`--rehearse`. Your counts will differ; the shapes should not.

```
governance.py: the policy model, read from the platform through the policy plane, read-only

  types: 4 declared
     com.vmware.policy.approval             enforcement=no  dryRun=no   validation=no   unlimited
     com.vmware.policy.deployment.action    enforcement=yes dryRun=yes  validation=no   unlimited
     com.vmware.policy.deployment.lease     enforcement=yes dryRun=yes  validation=no   unlimited
     com.vmware.policy.supervisor.iaas      enforcement=no  dryRun=yes  validation=yes  10 per org, 5 per project

  action selectors: 27, one root, 2 branches
     CCI.Supervisor.Resource.*          19 leaves in 3 kind(s): PersistentVolumeClaim (1), VirtualMachine (12), VirtualMachineGroup (6)
     Deployment.*                        5 leaves in 1 kind(s): (direct) (5)

  policies held: 3
     by type: {'action': 3}
     by scope: {'organization': 1, 'project': 2}   by enforcement: {'HARD': 3}

  decisions read: 270 of 270 held, over 73 target(s)
     policies applied per decision: {0: 33, 1: 52, 2: 76, 3: 99, 4: 5, 5: 5}
     ranks the plane assigned:      {1: 237, 2: 185, 3: 109, 4: 10, 5: 5}
     authorities written: 518, by prefix {'GROUP': 348, 'ROLE': 40, 'USER': 130}, with a trailing at-sign {'GROUP': 348}, names in lower case 518
     decisions with both scopes: 163, the organization ranked first in 163; a project policy at rank 1 with no organization policy: 47 of 237
     buckets computed: 518; an empty action list 48 (in 46 decisions); a named action beside the star 47

  one decision of each shape the log holds:
     0 policy/policies applied -> 1 authority bucket(s), 1 action entr(ies)
     1 policy/policies applied -> 1 authority bucket(s), 1 action entr(ies)
     2 policy/policies applied -> 2 authority bucket(s), 2 action entr(ies)
     3 policy/policies applied -> 3 authority bucket(s), 3 action entr(ies)
     4 policy/policies applied -> 3 authority bucket(s), 5 action entr(ies)
     5 policy/policies applied -> 3 authority bucket(s), 6 action entr(ies)

  rehearsal: asking what one more policy would do, without creating it
     it would touch 4 target(s); policies applying per target would be [4], where [3] apply today
     the policy list is 3 before and 3 after: nothing was created

wrote policy-model.json (4 types, 27 selectors) and decisions.json (270 decisions, 6 worked shapes); every organization value replaced by a placeholder
```

## What each block tells you

**The four types are not peers.** Two carry a hard or soft enforcement dial and two do not, so there is no
advisory approval policy to be had. Only the infrastructure type has a second, type-specific check and a cap, at
ten per organization and five per project, and a cap that low is a design instruction rather than a limit you will
hit by accident. That type also governs namespaces rather than deployments, which puts Day-2 governance on two
planes. The model read on 9.1.1 is the one read on 9.1 on 2026-09-21, type for type and selector for selector:
diff `policy-model.json` after each upgrade and you have the release's change to the catalog.

**The action catalog is a tree.** One root star, two branch stars, and the concrete actions under each. A
selector ending in a star is a standing grant over its branch, including actions a later release adds beneath
it. That is right for an operators' grant and wrong for a tenant grant.

**The decision log is the composition rule, stated by the thing that performs it.** For every target the plane
records which policies applied, the rank it gave each one, and the effective definition it computed. The script
reads every page of the log, sorted by id: the plane serves at most 200 entries a page, and a read without a sort
has no stable order across pages. Rank follows scope: wherever an organization-scoped and a project-scoped policy
both applied, the organization-scoped one was ranked first. Nothing overrides anything; the output is one bucket
per authority holding the union of every grant that named it. Three readings worth knowing:

- A decision with **no policies** is not an absence. The plane writes the role itself as the sole authority
  holding the whole catalog, which is the permissive default made explicit.
- An action listed **beside a star** is inert, because the star already covers it. It does nothing until the
  star is narrowed, which is how a future tightening is staged without a flag-day change.
- An **empty action list** is an explicit deny, written for one authority while others hold actions.

**The rehearsal is the call to reach for first.** It costs one request, creates nothing, and names every target
the change would touch, with how many policies would apply to each against how many apply today.

## The two checks

`--actions` reads one deployment's actions as you until two reads five seconds apart agree; that is the count to
trust after a policy change. `--authority` holds one authority against the forms the decision log writes, sends it
through the platform's own check with `validationOnly` (which creates nothing), and says whether any decision holds
a bucket for it yet. Run on 2026-10-18, the deployment id replaced:

```
$ python3 governance.py --actions <deployment-id>
governance.py: the actions you hold on one deployment, read until two reads in a row agree

    1 s   4 of 5 actions valid for you
    6 s   4 of 5 actions valid for you

  settled at 4 after 6 s: this is the count to trust
  valid: ChangeLease, Delete, EditDeployment, PowerOff
exit 0

$ python3 governance.py --authority GROUP:Engineers@
governance.py: one authority, checked against the forms the decision log holds

  the log holds 518 authorities in 270 decisions; prefixes GROUP: 348, ROLE: 40, USER: 130; with a trailing at-sign GROUP: 348; names in lower case 518 of 518
  the platform's own check (validationOnly) accepted a policy naming it, and created nothing
  the log stores every name in lower case, so this one is held as GROUP:engineers@
  well formed, and no decision holds a bucket for it yet: a grant not written yet, or a principal that matches nobody
exit 1

$ python3 governance.py --authority GROUP:Engineers
governance.py: one authority, checked against the forms the decision log holds

  the log holds 518 authorities in 270 decisions; prefixes GROUP: 348, ROLE: 40, USER: 130; with a trailing at-sign GROUP: 348; names in lower case 518 of 518
  the platform's own check (validationOnly) accepted a policy naming it, and created nothing
  not a form the log holds: every GROUP: authority the log holds ends in an at-sign, and this one does not
  a policy naming it would match nobody
exit 3

$ python3 governance.py --authority Engineers@
governance.py: one authority, checked against the forms the decision log holds

  the log holds 518 authorities in 270 decisions; prefixes GROUP: 348, ROLE: 40, USER: 130; with a trailing at-sign GROUP: 348; names in lower case 518 of 518
  the platform's own check (validationOnly) accepted a policy naming it, and created nothing
  not a form the log holds: its prefix (none) is not one the log holds
  a policy naming it would match nobody
exit 3
```

## Authorities, as the plane writes them

Read off the decision log by the script (`authorityForms` in `decisions.json`). Three prefixes appear, every name
is stored in lower case, and only the group form carries the trailing at-sign:

| Prefix | As you write it | What it names | Trailing `@` |
|---|---|---|---|
| `ROLE:` | `ROLE:member` | a project role, so everyone holding it | no |
| `GROUP:` | `GROUP:Engineers@` | a group from the identity source | yes, it is part of the name |
| `USER:` | `USER:jsmith` | one person | no |

## What the platform will and will not catch in a policy you write

Probed with `?validationOnly=true` on 2026-10-18 (9.1.1), the policy list read before and after every call:

```
an action selector that exists nowhere                     HTTP 400  allowedActions[0].actions[0]: '"Deployment.NoSuchAction"' is invalid. Expected value in '["*", "CCI.Supervisor.Resource.*", "CCI.Supervisor.Resource.PersistentV
a lease body missing its two required numbers              HTTP 400  'leaseTotalTermMax' is required.
'leaseTermMax' is required.
an action policy with no allowedActions key                HTTP 200
an authority with no prefix                                HTTP 200
an infrastructure policy with an empty automation policy   HTTP 400  Policy validation failed. Error: automationPolicy.failurePolicy: failurePolicy is required,automationPolicy.validations: validations is required,automationPolic
policy list: 3 before, 3 after every call; nothing created
```

So the body check is real for actions and required fields and absent for authorities and for a missing grant
list. A policy naming a group that does not exist, or a bare string, is accepted and then does nothing, which
presents as a policy that is not working rather than one that is malformed: run `--authority` on what you wrote.

The `enablePolicyValidation` flag on a type does not mean "the platform checks this one". Every type is
schema-checked. The flag marks a second, type-specific stage, and you can tell you reached it because the
refusal reads `Policy validation failed. Error: ...` rather than naming a field. Only the infrastructure type
has one, and the two stages disagree: that type declares nothing in its required list, and the second stage
still refuses a body without its failure policy and validations.

## After a real write

Effects settled in roughly 16 to 20 seconds on the reference estate in August 2026 (the assembled isolation
design's `verify.py` reproduces the flip on a disposable project). A read inside that window reports the previous
regime, so read until the count is stable:

```
python3 governance.py --actions <deployment-id>
```

## `fences.py --project <project>`, on throwaway objects, 2026-10-22T21:09Z

```
[21:09:22Z] blueprint create {"status": 201, "refused": null}
[21:09:23Z] lease policy create {"status": 201, "refused": null}
[21:09:24Z] approval policy create {"status": 201, "refused": null}
[21:09:24Z] waiting for the policies to reach new requests {"seconds": 60}
[21:10:25Z] deploy request {"status": 202, "refused": null}
[21:10:46Z] deployment created {"seconds": 21, "status": "CREATE_SUCCESSFUL", "leaseSet": true, "leaseDays": 1.0}
[21:11:03Z] first destroy request {"status": "APPROVAL_PENDING", "secondsToSettle": 17}
[21:11:03Z] approval raised {"fields": ["action", "adminActioned", "autoApproval", "createdAt", "currentLevel", "decision", "deploymentId", "deploymentName", "expired", "expiryAt", "id", "lastUpdatedAt", "levels", "orgId", "projectId", "projectName", "requestId", "requestedBy", "status", "totalLevels"], "status": "PENDING", "currentLevel": 1, "totalLevels": 1, "expiresAfterHours": 23.9}
[21:11:10Z] rejected as the approver {"actionStatus": 200, "refused": null, "requestStatus": "APPROVAL_REJECTED", "secondsToSettle": 6, "deploymentStillThere": true, "item": {"status": "REJECTED", "decision": "REJECT", "currentLevel": 1, "totalLevels": 1, "autoApproval": true, "expired": false}}
[21:11:22Z] second destroy request {"status": "APPROVAL_PENDING", "secondsToSettle": 11}
[21:11:34Z] approved as the approver {"actionStatus": 200, "refused": null, "deploymentGone": true, "secondsToGone": 11, "item": {"status": "APPROVED", "decision": "REJECT", "currentLevel": 1, "totalLevels": 1, "autoApproval": true, "expired": false}}
[21:11:34Z] teardown approval policy {"status": 204}
[21:11:35Z] teardown lease policy {"status": 204}
[21:11:35Z] teardown blueprint {"status": 204}
[21:11:36Z] residue {"probePolicies": 0, "probeDeployments": 0, "probeBlueprints": 0}
wrote fences.json; no project, user, organization or host name is recorded; exit 0
```

It exited 0: the lease was set from the policy, the first destroy request waited for approval and the rejection kept the
deployment, and the second request, approved, removed it. The run before it, at 21:06Z, gave the same answer; its
record is `records/fences-2026-10-22T2106Z.json`.
