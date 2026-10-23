# Expected output

Both runs from the reference estate, 2026-10-23, on VCF Automation 9.1.1 and vCenter 9.1.1. Names are labels; your
counts, labels and timings will differ.

## The read

Exit code 1, because the estate's one policy is on no organization's quota and so applies to nothing.

```
infra_policy.py: the infrastructure policies, read from the provider and vCenter, read-only

  policy-1: mandatory, criteria False, compatible zones 1 of 3, on the quotas of no organization; compute policy vm_host_affinity, host tag on ['cluster 1: 0 of 2', 'cluster 2: 2 of 2', 'cluster 3: 0 of 2'], VM tag on 0 VM(s), listed by 0 namespace(s)  -> applies to nothing
  vCenter's namespace-level policies: 1 ['MANDATORY']
wrote infra.json; no policy, organization, zone, cluster, host, tag or namespace name is recorded
```

## The probe

Exit code 0: each of the three VMs behaved as the model says, the namespace in an incompatible zone was refused, and
the residue read found nothing left and the quota list as it was. The compute policy sync and the compliance settle
vary from run to run.

```
infra_policy.py --probe: writes, on throwaway objects it deletes

[08:53:10Z] the organization's region quota read {"policiesListed": 0}
[08:53:13Z] vCenter: a VM tag and a VM-Host affinity compute policy per case, on your host tag {"created": 2}
[08:54:25Z] provider: Optional policy, criterion guest family LINUX {"secondsUntilTheComputePolicySynced": 61}
[08:54:36Z] provider: Optional policy, criterion guest family WINDOWS {"secondsUntilTheComputePolicySynced": 0}
[08:54:37Z] provider: both policies added to your organization's region quota {"status": 200}
[08:55:07Z] tenant: the namespace's zone, chosen from those the policies are compatible with {"templateZones": ["zone-1"], "compatible": ["zone-2"], "chosen": "zone-2"}
[08:55:51Z] tenant: a namespace naming both policies {"created": true, "listsBoth": true}
[08:57:32Z] the namespace's library attached on vCenter's namespace setting (G-663) {"image": true}
[08:57:32Z] the Supervisor namespace's ComputePolicies {"found": 2, "enforcementModes": ["Optional"], "linuxMatch": {"op": "And", "workload": {"guest": {"guestFamily": {"op": "Equal", "value": "Linux"}}}}}
[08:59:05Z] VM, no opt-in {"placed": true, "carriesThePolicysVmTag": false, "compliance": "NOT_APPLICABLE", "secondsUntilComplianceSettled": 0, "statusPolicies": 0}
[09:00:08Z] VM, opts in, matching {"placed": true, "carriesThePolicysVmTag": true, "compliance": "COMPLIANT", "secondsUntilComplianceSettled": 62, "statusPolicies": 1}
[09:20:13Z] VM, opts in, not matching {"placed": false, "secondsWaited": 1204, "placementCondition": ["VirtualMachineConditionPlacementReady", "NotReady", "failed to reconcile vSphere policies for placement: failed to evaluate policy: VM namespace-2/probe-infra-vm-3 PolicyEvaluation namespace-2/vm-probe-infra-vm-3 still being evaluated: policy not ready"]}
[09:20:15Z] tenant: a namespace naming the policies in a zone they are not compatible with {"status": 400, "refused": "No compatible zone is available in region 'region-1' for infra policy 'policy-1'"}
[09:20:16Z] teardown VM {"status": 200}
[09:20:16Z] teardown VM {"status": 200}
[09:20:17Z] teardown VM {"status": 200}
[09:21:42Z] teardown namespace {"status": 200, "gone": true}
[09:21:42Z] teardown: the quota list put back as it was {"status": 200}
[09:21:43Z] teardown policy (LINUX) {"status": 202}
[09:21:43Z] teardown policy (WINDOWS) {"status": 202}
[09:21:55Z] teardown compute policy (LINUX) {"status": 204}
[09:21:55Z] teardown compute policy (WINDOWS) {"status": 204}
[09:21:57Z] teardown tags and category {"status": 204}
[09:21:59Z] residue {"probePolicies": 0, "probeComputePolicies": 0, "probeNamespaces": 0, "quotaAsBefore": true}
wrote infra-probe.json; no policy, organization, zone, cluster, host, tag or namespace name is recorded
```
