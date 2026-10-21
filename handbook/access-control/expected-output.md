# Expected output

One run of `whoami.py` against a VCF Automation 9.1.1.0100.25757808 All Apps organization on 2026-10-13, with `VC_HOST` set and
`VCFA_BEARER_FILE` holding a session login's bearer for one identity of that organization (its roles were not read
in this run; the rights it derived are in the record). The run of 2026-10-07 on the earlier 9.1 build read the same counts except the rules review (186 then,
209 now). Your numbers will differ with your rights and your role; the shape is what to expect.

```text
whoami.py: the derivation, asked of the platform rather than inferred

  organization gateway: 67 groups derived (66 from rights, 1 system); userInfo extra: org, token
      its token field is the bearer you sent (compared by digest): never log the whole answer
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
  SelfSubjectRulesReview: 209 resource rules in that one namespace
  third surface (vCenter): the bearer that works above answers as a bearer token: 401, as a vCenter session id: 401, with no credential: 401 here

wrote derivation.json: the derivation as the platform states it, group names are product rights, nothing estate-shaped
```

Five things in that output carry the chapter:

- **The token field is the bearer you sent.** The gateway's answer carries it in `extra`; the script compares it with
  the bearer by digest, prints only that it matched, and keeps neither. Never log a whole self review.
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

## reprobe.py: the writes, re-asked on 9.1.1

Three runs on 2026-10-21 against the same organization on VCF Automation 9.1.1.0100, on the operator's go, each on
throwaway objects: `--probe-import <GROUP>` with a directory group that held no members, `--probe-project-scope`, and
`--probe-namespace`. The test users are three directory users bound edit (through a group), edit_adv and admin in one
project; the foreign project is one the administrator is not bound in. Every password came from a file of mode 0600.
The three runs are shown in that order. One line is marked: the run printed the readiness wait with an HTTP label,
which the script has since corrected to seconds.

```text
G-094, the group import:
  import under the automation grant:   the refresh token was refused at /oauth (HTTP 400)
  import under a session login:        HTTP 201
  read back HTTP 200, members 0; deleted HTTP 204
  absent afterwards: True

  wrote reprobe.json (statuses, counts and scrubbed messages)

G-126, a project administrator and projects:
  access reviews as the project administrator: {'create any': True, 'update the foreign project': True, 'delete the foreign project': True}
  project create:                      HTTP 403
  update of the foreign project, dry:  HTTP 403
  delete of the foreign project, dry:  HTTP 404
  the foreign project unchanged afterwards: True

  wrote reprobe.json (statuses, counts and scrubbed messages)

G-127 and the management ladder, in a throwaway namespace:
  conditions: {'class_bindings_in_project': 0, 'classes_listed_by_org_admin': 3, 'class_list_as_project_admin': 403}
  namespace create as edit_adv:        HTTP 403
  namespace create as admin:           HTTP 400
  namespace create as the org admin:   HTTP 200
    admin can read after_s             11 s   (printed as HTTP 11 by that run)
    advanced creates its own           HTTP 201
    admin creates its own              HTTP 201
    advanced edits the admin's         HTTP 200
    admin edits the advanced's         HTTP 200
    member lists them                  HTTP 403
    advanced deletes the admin's       HTTP 200
    admin deletes the advanced's       HTTP 200
    the advanced's afterwards          HTTP 404
    the admin's afterwards             HTTP 404
  teardown: {'namespace 1': 60}; probe namespaces left in the project: 0

  wrote reprobe.json (statuses, counts and scrubbed messages)
```

What the record holds, and what it says:

- **The import works under a session login on 9.1.1: 201, read back, removed, absent.** The automation-grant leg
  was not asked: the stored refresh token was refused at the token endpoint, so the 403 on that path is the
  2026-08-07 reading on 9.1, not a 9.1.1 one.
- **An access review overclaims for a project administrator.** It answers allowed for creating any project and for
  updating and deleting one the administrator does not belong to; the create is refused (403), the update of the
  spec is refused (403), and the delete answers 404, because that project is not visible to it. An update outside
  the spec is refused before any of that, with "Only project spec can be updated".
- **The namespace's workload plane has no per-user ownership.** The edit_adv member and the administrator each
  created a ConfigMap, edited the other's and deleted it; the edit member was refused the list.
- **A namespace create is refused by role for edit_adv (403) and by class for the administrator (400, "class not
  found") in a project with no class binding, where the administrator also could not list the cluster's classes.**
  The organization administrator's create, with the same spec, succeeded. The record states the conditions beside
  the refusal and does not claim which of them caused it.
