# What `governance.py` prints

Run against one VCF 9.1 organization, 2026-09-17, with `--rehearse`. Your counts will differ; the shapes should
not.

```
governance.py: the policy model, read from the platform through the policy plane, read-only

  types: 4 declared
     com.vmware.policy.supervisor.iaas      enforcement=no  dryRun=yes  validation=yes  10 per org, 5 per project
     com.vmware.policy.deployment.action    enforcement=yes dryRun=yes  validation=no   unlimited
     com.vmware.policy.deployment.lease     enforcement=yes dryRun=yes  validation=no   unlimited
     com.vmware.policy.approval             enforcement=no  dryRun=no   validation=no   unlimited

  action selectors: 27, one root, 2 branches
     CCI.Supervisor.Resource.*          19 leaves in 3 kind(s): PersistentVolumeClaim (1), VirtualMachine (12), VirtualMachineGroup (6)
     Deployment.*                        5 leaves in 1 kind(s): (direct) (5)

  policies held: 3
     by type: {'action': 3}
     by scope: {'project': 2, 'organization': 1}   by enforcement: {'HARD': 3}

  decisions read: 200 of 229 held, over 38 target(s)
     policies applied per decision: {0: 33, 1: 52, 2: 70, 3: 45}
     ranks the plane assigned:      {1: 167, 2: 115, 3: 45}

  one decision of each shape the log holds:
     0 policy/policies applied -> 1 authority bucket(s), 1 action entr(ies)
     1 policy/policies applied -> 1 authority bucket(s), 1 action entr(ies)
     2 policy/policies applied -> 3 authority bucket(s), 2 action entr(ies)
     3 policy/policies applied -> 2 authority bucket(s), 3 action entr(ies)

  rehearsal: asking what one more policy would do, without creating it
     it would touch 8 target(s); policies applying per target would be [4]
     the policy list is 3 before and 3 after: nothing was created

wrote policy-model.json (4 types, 27 selectors) and decisions.json (200 decisions, 4 worked shapes); every organization value replaced by a placeholder
```

## What each block tells you

**The four types are not peers.** Two carry a hard or soft enforcement dial and two do not, so there is no
advisory approval policy to be had. Only the infrastructure type is validated by the platform and capped, at ten
per organization and five per project, and a cap that low is a design instruction rather than a limit you will
hit by accident. That type also governs namespaces rather than deployments, which puts Day-2 governance on two
planes.

**The action catalog is a tree.** One root star, two branch stars, and the concrete actions under each. A
selector ending in a star is a standing grant over its branch, including actions a later release adds beneath
it. That is right for an operators' grant and wrong for a tenant grant.

**The decision log is the composition rule, stated by the thing that performs it.** For every target the plane
records which policies applied, the rank it gave each one, and the effective definition it computed. Rank
follows scope: the organization-scoped policy is considered first. Nothing overrides anything; the output is one
bucket per authority holding the union of every grant that named it. Two readings worth knowing:

- A decision with **no policies** is not an absence. The plane writes the role itself as the sole authority
  holding the whole catalog, which is the permissive default made explicit. On this estate 33 of 200 decisions
  have that shape.
- An action listed **beside a star** is inert, because the star already covers it. It does nothing until the
  star is narrowed, which is how a future tightening is staged without a flag-day change.

**The rehearsal is the call to reach for first.** It costs one request, creates nothing, and names every target
the change would touch along with what each one's effective definition would become.

## Authorities, as the plane writes them

Read off the decision log rather than from documentation. Three prefixes appear, and the plane lowercases every
authority it stores:

| Prefix | As you write it | What it names | Trailing `@` |
|---|---|---|---|
| `ROLE:` | `ROLE:member` | a project role, so everyone holding it | no |
| `GROUP:` | `GROUP:Engineers@` | a group from the identity source | yes, it is part of the name |
| `USER:` | `USER:jsmith` | one person | no |

## After a real write

Effects settle in roughly 16 to 20 seconds. A read inside that window reports the previous regime, so poll until
the count is stable before trusting it:

```
GET /deployment/api/deployments/<deployment-id>/actions
```
