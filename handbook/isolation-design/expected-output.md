# What a passing run looks like

Captured shapes from the proven run (VCF 9.1, 2026-08-11), with generic principal names. Your
action counts may differ by build and blueprint (a real-VM deployment carries more resource
actions than the ConfigMap marker); the shape is what matters.

## `matrix` on the permissive default (zero HARD policies in the project)

```
targets: alpha(owner=user1), beta(owner=user2)

actor        role/group         | alpha(own=user1)   | beta(own=user2)
------------------------------------------------------------------------------
user1        edit               | 5-actions(ALLOW)   | not-visible(404)
user2        edit               | not-visible(404)   | 5-actions(ALLOW)
user3        edit_adv           | 5-actions(ALLOW)   | 5-actions(ALLOW)
user4        admin              | 5-actions(ALLOW)   | 5-actions(ALLOW)
```

What to see: the two `edit` users each see and act on only their own deployment and receive a
hard 404 on the other's. That 404 is the design holding, not an error. If your operator row's
account is an Organization Administrator, it sees both targets regardless of project role: that
is the org-role bypass the design contains, and it is expected.

## `matrix` after `flip-on` (one HARD policy naming only the operators group)

Wait roughly 20 seconds after the flip before reading; a sooner read reports the previous regime.

```
actor        role/group         | alpha(own=user1)   | beta(own=user2)
------------------------------------------------------------------------------
user1        edit               | 0-actions(DENY)    | not-visible(404)
user2        edit               | not-visible(404)   | 0-actions(DENY)
user3        edit_adv           | 0-actions(DENY)    | 0-actions(DENY)
user4        admin              | 0-actions(DENY)    | 0-actions(DENY)
op1          Platform Operators | 5-actions(ALLOW)   | 5-actions(ALLOW)
```

What to see: every principal the policy does not name reads zero actions, the project `admin`
role included; visibility is unchanged because a Day-2 policy grants actions, never visibility.
`flip-off` returns the project to the first table after the same propagation window.

## VCF Automation 9.1.1, 2026-10-21: the assembled design (three HARD policies, two granting every action), read-only

`python3 isolation.py` under an organization administrator's session login (its summary lines), then
`python3 verify.py matrix --record matrix.json` as the four test principals over two deployments that already existed,
owned by the two `edit` users. Nothing was written on the estate. The membership write and the naming pass were not
re-sent; the record carries their 9.1 readings.

```
  roles: 4 project role(s), cluster-scoped and read-only
  bindings: 6 across 2 project(s); every name is cci:<kind>:<subject minus a trailing @>: True
  access reviews: the interface declares 4 -> ['localsubjectaccessreviews', 'selfsubjectaccessreviews', 'selfsubjectrulesreviews', 'subjectaccessreviews']
  self rules: 153 rule(s), incomplete=False; widest group is vpc.nsx.vmware.com with 164 resource grants
  visibility floor: this identity sees 4 deployment(s) owned by 3 distinct principal(s). Isolation is a property of principals below this role, not of the platform
  action regime: 3 Day-2 action policies in force, 3 HARD; organization HARD naming 1 subject(s), actions all; project HARD naming 1 subject(s), actions all; project HARD naming 1 subject(s), actions 1
wrote isolation.json (4 roles, 6 bindings, 2 of 4 access reviews answering); every organization name replaced by a placeholder
```

```
targets: alpha(owner=user1), beta(owner=user2)

actor        role/group         | alpha(own=user1) | beta(own=user2)
------------------------------------------------------------------------------
user1        edit               | 5-actions(ALLOW) | not-visible(404)
user2        edit               | not-visible(404) | 5-actions(ALLOW)
user3        edit_adv           | 0-actions(DENY) | 0-actions(DENY)
user4        admin              | 0-actions(DENY) | 0-actions(DENY)
```

What to see: this is neither capture above. Every action policy in force is HARD, and two grant every action, one to a
group in the project and one to a group across the organization. The two `edit` users act on their own deployment and
receive 404 on each other's; `edit_adv` and `admin`, named by neither policy, see both deployments and hold no action on
either. That is the design of the chapter, assembled: actions follow the policies, sight follows the role.
