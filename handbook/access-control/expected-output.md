# Expected output

One run of `whoami.py` against a VCF Automation 9.1 All Apps organization on 2026-10-07, with `VC_HOST` set, as
an identity holding Organization Administrator and a project `admin` binding. Your numbers will differ with your
rights and your role; the shape is what to expect.

```text
whoami.py: the derivation, asked of the platform rather than inferred

  organization gateway: 67 groups derived (66 from rights, 1 system); userInfo extra: org, token
  project roles published: ['view', 'edit', 'admin', 'edit_adv']
  authority: 4 ProjectRoleBindings, by role {'admin': 2, 'edit': 1, 'edit_adv': 1}, subject kinds ['Group', 'User']
  projection: project-service arrays administrators (2, the admin bindings), advancedUsers (1, the edit_adv bindings), auditors (0), users (1, the edit bindings)
  workload plane:       2 groups derived for the same bearer (0 from rights, 1 plane-scoped)
      edit-<project-uid>-<project>@<realm>

  the same question, asked two ways (an access review is about RBAC wiring, not enforcement):
      verb   apiGroup                resource        no scope  with scope
      list   vmoperator.vmware.com   virtualmachines False     True
      create vmoperator.vmware.com   virtualmachines False     True
      delete vmoperator.vmware.com   virtualmachines False     True
      create core                    secrets         False     True
      create core                    namespaces      False     False
  real reads for comparison: {'virtualmachines': 200, 'secrets': 200}
  SelfSubjectRulesReview: 186 resource rules in that one namespace
  third surface (vCenter): the bearer that works above answers as a bearer token: 401, as a vCenter session id: 401, with no credential: 401 here

wrote derivation.json: the derivation as the platform states it, group names are product rights, nothing estate-shaped
```

Four things in that output carry the chapter:

- **67 groups at the organization gateway, 2 at a namespace endpoint, for the same bearer.** None of the
  right-named groups crosses. That is the two-surface model stated by the platform rather than argued.
- **The plane-scoped group is keyed by the project, not by the user.** Every holder of that namespace resolves
  to the same subject, which is why per-user isolation lives at the project boundary.
- **The same access review answered false without a namespace and an API group, and true with both.** An access
  review is a statement about RBAC wiring, and without scope it is not even that.
- **Each REST membership array holds exactly the principals of one role's bindings.** `administrators` is the
  `admin` bindings, `users` the `edit` bindings, `advancedUsers` the `edit_adv` bindings, and `auditors` the
  `view` bindings, which are empty here. The arrays are the authority projected, which is why a write to them
  persists nothing; the isolation-design companion's `isolation.py` sends that write and reads it back.
