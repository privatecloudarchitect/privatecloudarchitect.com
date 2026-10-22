# Expected output

What `elevation.py` printed on the reference estate on 2026-10-22: VCF Automation 9.1.1, one All Apps organization,
signed in with a session login. Policy-type schema fields are listed in full, as the script prints them.

## The read-only enumeration, 09:50Z

```
$ python3 elevation.py
elevation.py: what this platform can and cannot time-box

  policy types: 4 declared, each with its definition, target and scope schemas read
     com.vmware.policy.supervisor.iaas      says automationPolicy, automationPolicy.failurePolicy, automationPolicy.matchConditions, automationPolicy.matchConditions[].expression, automationPolicy.matchConditions[].name, automationPolicy.matchConstraints, automationPolicy.matchConstraints.excludeResourceRules, automationPolicy.matchConstraints.excludeResourceRules[].apiGroups, automationPolicy.matchConstraints.excludeResourceRules[].apiVersions, automationPolicy.matchConstraints.excludeResourceRules[].operations, automationPolicy.matchConstraints.excludeResourceRules[].resources, automationPolicy.matchConstraints.matchPolicy, automationPolicy.matchConstraints.objectSelector, automationPolicy.matchConstraints.objectSelector.matchExpressions, automationPolicy.matchConstraints.objectSelector.matchExpressions[].key, automationPolicy.matchConstraints.objectSelector.matchExpressions[].operator, automationPolicy.matchConstraints.objectSelector.matchExpressions[].values, automationPolicy.matchConstraints.objectSelector.matchLabels, automationPolicy.matchConstraints.resourceRules, automationPolicy.matchConstraints.resourceRules[].apiGroups, automationPolicy.matchConstraints.resourceRules[].apiVersions, automationPolicy.matchConstraints.resourceRules[].operations, automationPolicy.matchConstraints.resourceRules[].resources, automationPolicy.validationActions, automationPolicy.validations, automationPolicy.validations[].expression, automationPolicy.validations[].message, automationPolicy.validations[].messageExpression, automationPolicy.validations[].reason
     com.vmware.policy.deployment.action    says allowedActions, allowedActions[].actions, allowedActions[].authorities
     com.vmware.policy.deployment.lease     says leaseGrace, leaseTermMax, leaseTotalTermMax
        time-bounded: leaseGrace (definition schema): "The duration in days that an expired object should be held before it is deleted"
        time-bounded: leaseTermMax (definition schema): "The maximum duration in days between creation (or renewal) and expiration"
        time-bounded: leaseTotalTermMax (definition schema): "The maximum duration in days between creation and expiration. Unaffected by renewal."
     com.vmware.policy.approval             says actions, approvalMode, approverType, approvers, autoApprovalDecision, autoApprovalExpiry, level
        time-bounded: autoApprovalExpiry (definition schema): "No of days to keep the approval request"

  a ProjectRoleBinding's schema declares ['roleRef', 'roleRef.apiGroup', 'roleRef.kind', 'roleRef.name', 'subjects', 'subjects[].kind', 'subjects[].name']
  a ProjectRole's schema declares ['spec', 'spec.description']
  the 4 bindings visible carry ['metadata', 'roleRef', 'subjects'], whose metadata carries ['annotations', 'finalizers', 'labels', 'managedFields', 'name', 'namespace', 'ownerReferences', 'uid']
  fields of either kind that could hold a time bound: NONE
  (object metadata, the same on every kind and set by the server: metadata.creationTimestamp, metadata.deletionGracePeriodSeconds, metadata.deletionTimestamp, metadata.managedFields[].time)

  a deployment carries ['leaseGracePeriodDays'], so this platform can time-box a THING and not a PERSON

  elevation: not probed. Pass --probe-elevation <binding name> to move ONE binding up a role and back, which is the only way to learn whether a revert is possible. It writes to a live access object, so it takes the name from you.

  elevation: carrying forward the probe block captured earlier; this run did not re-probe and has not erased it

wrote elevation.json (4 policy types, 2 with a time-bounded field; 0 expiry field(s) on the access kinds); every organization name replaced by a placeholder
```

It exited 0. The probe block it carried forward is the run below.

## The probe, 09:49Z, on a binding made for the test

The binding was created for an RBAC test group, at `edit`, in a project with no deployments, and deleted after the
probe; the project's other bindings were read before and after and were unchanged. These are the probe's own lines:

```
$ python3 elevation.py --probe-elevation 'cci:group:<test group>' --project <test project>

  elevation: moving one named binding 'edit' -> 'edit_adv' and back
     apply with ?dryRun=All      HTTP 200  role now 'edit_adv'  -> THE DRY RUN APPLIED THE CHANGE
     elevate                     HTTP 200  role now 'edit_adv'
     revert                      HTTP 200  role now 'edit'  -> restored
```

It exited 0: the revert restored the role, read directly from the object. Before the probe, a binding naming a group
the identity provider does not know was refused at create with HTTP 400, "There are principals that are not present in
the Identity provider", so a test binding has to name a principal that exists.

## The broker, 09:57Z, read-only

The broker's service identity was the organization administrator and the caller a test user, both signed in with a
session login. Grants and the heartbeat went to local files; `check` executes nothing and `reconcile` ran without
`--apply`, so nothing on the platform changed. The member's deployment is a record whose resources were already
deleted; `check` reads only its owner, so the decision is the same. Names are replaced by placeholders; grant ids are
as printed.

```
$ python3 broker.py check --deployment <another user's deployment> --action Deployment.Delete
DENY: <member> does not own this deployment; ownership comes before any grant
exit 1

$ python3 broker.py check --deployment <the member's deployment> --action Deployment.Update
ALLOW: <member> owns the deployment, and Deployment.Update is not on the destructive list, so no grant is needed
exit 0

$ python3 broker.py check --deployment <the member's deployment> --action Deployment.Delete
DENY: <member> owns the deployment, and no live grant covers Deployment.Delete
exit 1

$ python3 broker.py grant --principal <member> --action Deployment.Delete --hours 1 --approver <approver> --reason "remove a failed build"
GRANTED 987bcda3093d: <member>, Deployment.Delete on their own deployments, until 2026-10-22T10:56:57Z; approved by <approver>
exit 0

$ python3 broker.py check --deployment <the member's deployment> --action Deployment.Delete
ALLOW: <member> owns the deployment, and grant 987bcda3093d covers Deployment.Delete until 2026-10-22T10:56:57Z
exit 0

$ python3 broker.py check --deployment <another user's deployment> --action Deployment.Delete
DENY: <member> does not own this deployment; ownership comes before any grant
exit 1

$ python3 broker.py grant --principal "<test group>" --group --scope --project <project> --role edit_adv --hours 1 --approver <approver> --reason "debug a stuck deployment"
GRANTED 68da3e4fec48: <test group>, edit_adv in <project>, baseline edit, until 2026-10-22T10:57:02Z; approved by <approver>
exit 0

$ python3 broker.py grant --principal "<test group>" --group --scope --project <project> --role edit_adv --hours 1 --approver <approver> --reason "a second, overlapping request"
REFUSED: another scope grant for this member in this project is live or not yet reverted: its baseline would be overwritten by an already-raised role
exit 1

$ python3 broker.py reconcile
  68da3e4fec48  <test group> in <project>: edit -> edit_adv  (raise pending; plan only)
reconcile: 1 scope grant(s) open, 0 written, 0 revert(s) due, 0 failed; plan only, nothing written
exit 0

$ python3 broker.py heartbeat --max-age-minutes 10
STALE: no applied reconcile pass has been recorded
exit 1
```
