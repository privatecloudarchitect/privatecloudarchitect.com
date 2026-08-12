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
