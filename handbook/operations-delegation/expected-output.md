# Expected output

One run of `delegation.py`, step by step, against VCF Operations 9.1.1.0 acting on a vCenter 9.1.1, on 2026-11-18. The
team is one directory group of one member, synced into VCF single sign-on through the identity provider's sync profile,
with one VM it owns and one it must not see. Every name and id is a placeholder: `{{team-1}}` is the team, `{{role-1}}` its role,
`{{scope-1}}` its scope, `{{group-1}}` its group, `{{person-1}}` the member, `{{vm-1}}` the team's VM and `{{vm-2}}` the other. The
records each step wrote are in `records/`. Compare the shape of your own run, not its names.

## 1. `plan`, as the administrator

Nothing exists yet, so the plan is three creates. A group that already holds a VCF role, or a VCF Operations role of its
own, would add a finding here. What the run printed:

```
plan: team {{team-1}}, group {{group-1}}, 1 VM, role {{role-1}}, scope {{scope-1}}
  apply would: create role {{role-1}} (179 privileges: ReadOnly's, the actions, Recent Tasks, All other Read, Write APIs)
  apply would: create scope {{scope-1}} (SPECIFIC: 1 VM)
  apply would: import {{group-1}} from VCF SSO with role {{role-1}} on scope {{scope-1}}
exit 0
```

## 2. `apply`, a dry run, then `--execute`

Without `--execute` nothing is sent. With it, each write is read back. What the run printed:

```
apply: team {{team-1}}, group {{group-1}}, 1 VM, role {{role-1}}, scope {{scope-1}}
  would: create role {{role-1}} (179 privileges: ReadOnly's, the actions, Recent Tasks, All other Read, Write APIs)
  would: create scope {{scope-1}} (SPECIFIC: 1 VM)
  would: import {{group-1}} from VCF SSO with role {{role-1}} on scope {{scope-1}}
  dry run: nothing sent; add --execute to send it
exit 0
```

```
apply: team {{team-1}}, group {{group-1}}, 1 VM, role {{role-1}}, scope {{scope-1}}
  sent: POST /api/auth/roles -> 201
  sent: POST /api/auth/scopes -> 201
  sent: POST /api/auth/usergroups -> 201
  held: role is recipe
  held: scope is the objects
  held: group has the permission
exit 0
```

A second `apply --execute` finds everything as the recipe says and sends nothing. What the run printed:

```
apply: team {{team-1}}, group {{group-1}}, 1 VM, role {{role-1}}, scope {{scope-1}}
  held: role is recipe
  held: scope is the objects
  held: group has the permission
exit 0
```

## 3. `check`, as the member

The member signs in with an api token minted in the console. Nothing is written and no action runs. What the run printed:

```
  held: the member's record lists the team's group: expected listed, got listed
  held: the member holds no permission of its own: expected none, got 0 of its own
  held: a named object is readable ({{vm-1}}): expected 200, got 200
  held: its Power Off VM query is answered ({{vm-1}}): expected 200, got 200
  held: an object outside the scope is invisible ({{vm-2}}): expected 404, got 404
  held: its Power Off VM query is refused ({{vm-2}}): expected refused, got 500
exit 0
```

## 4. `act`, as the member

A dry run sends only the action's query. With `--execute`, the body the query returned is sent, and the member reads its
own task's status, which the role's Recent Tasks privilege allows. What the run printed:

```
  Power Off VM on {{vm-1}}: query 200, offered True
  dry run: would send POST /api/actions/VMWARE-Power%20Off%20VM with the body the query returned; add --execute to send it
exit 0
```

```
  Power Off VM on {{vm-1}}: query 200, offered True, execute 200, task {{id-1}}, COMPLETED_SUCCESSFULLY by {{person-1}}
exit 0
```

A Power On asked for about a minute after the Power Off is not offered yet: VCF Operations has not collected the VM
as off, so the query leaves it out of parameterGroup, and act sends nothing. What the run printed:

```
  Power On VM on {{vm-1}}: query 200, offered False; VCF Operations does not offer this action for the object now: its query left the object out of parameterGroup, because VCF Operations decides from its last collection (a VM powered off moments ago is offered Power On after the next cycle)
exit 1
```

A minute later the query's parameterGroup carried the VM, and the same command with --execute completed. What the run printed:

```
  Power On VM on {{vm-1}}: query 200, offered True, execute 200, task {{id-2}}, COMPLETED_SUCCESSFULLY by {{person-1}}
exit 0
```

## 5. `who`, as the administrator

VCF Operations' action status names the member for both tasks. vCenter's events for the same two power changes name
only VCF Operations' own vCenter account. What the run printed:

```
  {{id-1}}: Power Off VM COMPLETED_SUCCESSFULLY by {{person-1}} (VCF SSO) on {{vm-1}}
  {{id-2}}: Power On VM COMPLETED_SUCCESSFULLY by {{person-1}} (VCF SSO) on {{vm-1}}
exit 0
```

## 6. `revoke`, a dry run, then `--execute`

The group import is deleted because `apply` made it; on a group someone else imported, only this role's permission comes
off. What the run printed:

```
revoke: team {{team-1}}, group {{group-1}}, 1 VM, role {{role-1}}, scope {{scope-1}}
  would remove: this role's permission from the group, the group import, the role, the scope
  dry run: nothing sent; add --execute to send it
exit 0
```

```
revoke: team {{team-1}}, group {{group-1}}, 1 VM, role {{role-1}}, scope {{scope-1}}
  sent: DELETE /api/auth/usergroups/<group> -> 204
  sent: DELETE /api/auth/roles/{{role-1}} -> 204
  sent: DELETE /api/auth/scopes -> 200
  held: role gone
  held: scope gone
  held: group without the role
exit 0
```
