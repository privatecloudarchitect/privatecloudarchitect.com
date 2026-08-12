# Day-2 governance: the two-policy first change

The runnable companion to
[Day-2 governance: who controls the action count](https://privatecloudarchitect.com/handbook/day2-governance)
(and step 3 of [the assembled isolation design](https://privatecloudarchitect.com/handbook/isolation-design)).
Two HARD Day-2 action policies, shipped as one change, named per the sheet's convention.

**Provenance:** the policy type, body shape, and regime flip were proven on a live VCF 9.1 estate
(All Apps), 2026-08-08 through 2026-08-11.

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

Effects settle in roughly 16 to 20 seconds; a read inside that window reports the previous
regime. Then read the action count as an affected principal, under their own session:

```
GET /deployment/api/deployments/<deployment-id>/actions
```

Expected after this pair lands: tenant-group members hold the full set on their own deployments,
operators hold the full set on everything their roles make visible, and every principal named by
neither policy holds zero. Poll until the count is stable before trusting it.

## Rollback

Deleting a policy (`DELETE /policy/api/policies/{id}`) removes its grant; deleting the last HARD
action policy in the project returns the project to the permissive default, after the same
propagation window.
