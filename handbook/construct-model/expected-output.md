# Expected output

One run of `inventory.py` against a VCF Automation 9.1.1 organization on 2026-10-20, signed in with a session login
(`VCFA_USER`, `VCFA_PASSWORD`) and given a provider bearer for the provider edges (`VCFA_PROVIDER_BEARER_FILE`), with `naming-standard.json` beside it so the naming audit runs. Every estate name is a placeholder the script assigned in the order it met
the object; the audit prints conformance counts and never a name. The kind counts are distinct kinds:
SupervisorNamespace is served in two API versions and counts once, so `taxonomy.json` holds 101 entries and 100 kinds.

```text
inventory.py: the construct model read through the Cloud Consumption Interface, read-only

  taxonomy: 13 VMware API groups, 100 kinds; 61 published at the top level, 39 under a project
  published: 1 region(s), 3 zone(s), 3 namespace class(es), 1 VPC(s), 3 subnet(s), 3 storage-class quota(s), 16 VM class summaries
  {{project-1}}: bindings {'regions': 0, 'classes': 0, 'vpcs': 0, 'subnets': 0, 'serviceEngineGroups': 0, 'infraPolicies': 0}; role bindings {'count': 4, 'roles': ['admin', 'edit', 'edit_adv'], 'fields': ['roleRef', 'subjects']}; images 3; catalog items 10; namespaces 5
     {{namespace-1}}: phase Created; bound {'region': '{{region-1}}', 'zone': '{{zone-1}}', 'class': '{{class-3}}', 'vpc': '{{vpc-1}}', 'storageClasses': 1, 'vmClasses': 4, 'classOverrides': True, 'sharedSubnets': 0, 'infraPolicies': 0}; workloads {'virtualMachines': 2, 'vksClusters': 1, 'vmServices': 1}
     {{namespace-2}}: phase Created; bound {'region': '{{region-1}}', 'zone': '{{zone-1}}', 'class': '{{class-1}}', 'vpc': '{{vpc-1}}', 'storageClasses': 1, 'vmClasses': 4, 'classOverrides': True, 'sharedSubnets': 0, 'infraPolicies': 0}; workloads {'virtualMachines': 4, 'vksClusters': 1, 'vmServices': 3}
     {{namespace-3}}: phase Created; bound {'region': '{{region-1}}', 'zone': '{{zone-3}}', 'class': '{{class-1}}', 'vpc': '{{vpc-1}}', 'storageClasses': 1, 'vmClasses': 4, 'classOverrides': True, 'sharedSubnets': 0, 'infraPolicies': 0}; workloads {'virtualMachines': 0, 'vksClusters': 0, 'vmServices': 0}
     {{namespace-4}}: phase Created; bound {'region': '{{region-1}}', 'zone': '{{zone-2}}', 'class': '{{class-1}}', 'vpc': '{{vpc-1}}', 'storageClasses': 1, 'vmClasses': 4, 'classOverrides': True, 'sharedSubnets': 0, 'infraPolicies': 0}; workloads {'virtualMachines': 3, 'vksClusters': 1, 'vmServices': 2}
     {{namespace-5}}: phase Created; bound {'region': '{{region-1}}', 'zone': '{{zone-1}}', 'class': '{{class-1}}', 'vpc': '{{vpc-1}}', 'storageClasses': 1, 'vmClasses': 4, 'classOverrides': True, 'sharedSubnets': 0, 'infraPolicies': 0}; workloads {'virtualMachines': 3, 'vksClusters': 0, 'vmServices': 0}
  {{project-2}}: bindings {'regions': 0, 'classes': 0, 'vpcs': 0, 'subnets': 0, 'serviceEngineGroups': 0, 'infraPolicies': 0}; role bindings {'count': 2, 'roles': ['edit'], 'fields': ['roleRef', 'subjects']}; images 3; catalog items 10; namespaces 0

  naming: 6 of 49 names conform to the standard, across 10 constructs
     project                  2 of 2   keep    <team / app-portfolio>  e.g. checkout-team
     supervisor-namespace     0 of 5   rename  <app>-<env>-<region>-<sup-hash>  e.g. checkout-prod-eu-west-1-g9w34
     region                   1 of 1   keep    <geo>-<direction>-<ordinal>  e.g. eu-west-1
     supervisor-zone          0 of 3   rename  <region>-az<n>  e.g. eu-west-1-az1
     namespace-class          0 of 3   rename  ns-<profile>-<size>  e.g. ns-general-small
     vpc                      0 of 1   rename  vpc-<consumer>-<region>[-<ordinal>]  e.g. vpc-checkout-eu-west-1
     vpc-subnet               0 of 3   rename  <access-mode>-<purpose?>-<ordinal>  e.g. private-web-01
     vm-class                 0 of 16  rename  <qos>-<profile?>-<size>  e.g. guaranteed-general-large
     virtualmachine           1 of 12  refine  <app>-<role>-<ordinal>  e.g. checkout-web-01
     vks-cluster              2 of 3   refine  <app>-<env>-vks  e.g. checkout-prod-vks

  edges: 31 read, 31 with instances on this estate, 0 with none, 0 not read; every observed cardinality holds
     Organization           1 : 0+  Project                live      1 -> 2; to per from [2, 2], from per to [1, 1]
     Project                1 : 0+  Supervisor Namespace   live      2 -> 5; to per from [0, 5], from per to [1, 1]
     Supervisor Namespace   N : 1   Region                 live      5 -> 1; to per from [1, 1], from per to [5, 5]
     Supervisor Namespace   N : 1   Namespace Class        live      5 -> 2; to per from [1, 1], from per to [1, 4]
     Supervisor Namespace   N : 1   VPC                    live      5 -> 1; to per from [1, 1], from per to [5, 5]
     Supervisor Namespace   N : N   Zone                   live      5 -> 3; to per from [1, 1], from per to [1, 3]
     Supervisor Namespace   N : N   Storage Class          live      5 -> 1; to per from [1, 1], from per to [5, 5]
     Supervisor Namespace   N : N   VM Class               live      5 -> 4; to per from [4, 4], from per to [5, 5]
     Supervisor Namespace   1 : 0+  VirtualMachine         live      5 -> 12; to per from [0, 4], from per to [1, 1]
     Supervisor Namespace   1 : 0+  VKS Cluster            live      5 -> 3; to per from [0, 1], from per to [1, 1]
     Region                 1 : N   Zone                   live      1 -> 3; to per from [3, 3], from per to [1, 1]
     Region                 1 : 0+  VPC                    live      1 -> 1; to per from [1, 1], from per to [1, 1]
     Region                 1 : 0+  VM Class               live      1 -> 16; to per from [16, 16], from per to [1, 1]
     VirtualMachine         N : 1   VM Class               live      12 -> 3; to per from [1, 1], from per to [2, 8]
     VirtualMachine         N : 1   VM Image               live      12 -> 4; to per from [1, 1], from per to [2, 6]
     VirtualMachine         N : 1   Storage Class          live      12 -> 1; to per from [1, 1], from per to [12, 12]
     VirtualMachine         N : N   Network                live      8 -> 3; to per from [1, 1], from per to [2, 3]
     VirtualMachine         N : 1   Zone                   live      12 -> 2; to per from [1, 1], from per to [3, 9]
     VKS Cluster            1 : N   Node VirtualMachine    live      3 -> 8; to per from [2, 3], from per to [1, 1]
     VirtualMachineService  N : N   VirtualMachine         live      6 -> 8; to per from [1, 2], from per to [1, 1]
     VirtualMachineService  1 : 0+  Load balancer address  live      6 -> 5; to per from [0, 1], from per to [1, 1]
     Region                 1 : N   Supervisor             live      1 -> 1; to per from [1, 1], from per to [1, 1]
     Supervisor             N : 1   Region                 live      1 -> 1; to per from [1, 1], from per to [1, 1]
     Region                 1 : 1   NSX Manager            live      1 -> 1; to per from [1, 1], from per to [1, 1]
     Region                 1 : N   Storage Policy         live      1 -> 3; to per from [3, 3], from per to [1, 1]
     Supervisor             N : 1   vCenter                live      1 -> 1; to per from [1, 1], from per to [1, 1]
     Supervisor             1 : N   Supervisor Zone        live      1 -> 3; to per from [3, 3], from per to [1, 1]
     Supervisor Zone        1 : 1   vSphere Zone           live      3 -> 3; to per from [1, 1], from per to [1, 1]
     Organization           1 : 0+  Content Library        live      1 -> 1; to per from [1, 1], from per to [1, 1]
     Organization           N : N   Region                 live      5 -> 1; to per from [1, 1], from per to [5, 5]
     Regional networking    N : 1   Provider Gateway       live      4 -> 1; to per from [1, 1], from per to [4, 4]

  bindings: not asked (pass --probe-bindings to send the refused attempts; see the README)

wrote taxonomy.json (100 kinds) and estate.json (2 project(s)) and naming.json (counts only) and edges.json (31 edges, counts only); every estate name replaced by a stable label
```

Read the `bound` map as the namespace's four create-time bindings. `zone` is not a `zoneName` field on the
namespace: on 9.1 the spec carries `classConfigOverrides`, and the zone is named inside it, alongside the per-zone
budget the namespace restates for itself. `storageClasses` and `vmClasses` are not spec fields either; the class
config carries them and the namespace reports the effective set in its status, which is why every namespace here
shows one storage class and four machine classes rather than the zeroes an earlier run of this script printed
against field names that no longer exist.

The four records it wrote are [`taxonomy.json`](taxonomy.json) (every VMware API group and kind the interface
declared, with scope, verbs, and the count of each top-level kind), [`estate.json`](estate.json) (the tree),
[`naming.json`](naming.json) (per construct, how many of that estate's names conform to the standard), and
[`edges.json`](edges.json) (every edge between constructs with the field that proves it).

Read an edge line as From, its cardinality, To, the tier, then how many objects stood on each side, how many To each
From held, and how many From each To had. Every declared cardinality held on this run; one that did not would end its
line with `NOT AS DECLARED`.

Six of fifty-one names conformed on that run, which is the ordinary result for an estate that grew before it had a
standard: the region and the projects conform, and the namespaces, zones, classes, VPC, subnets, and VM classes do
not. The verdict column is the work list, and the rename order is outermost boundary first.

## Asking whether the bindings hold: `--probe-bindings`

With the flag, the same run adds a fifth section and a fourth record. This is the chapter's claim about the
crossroads put to the platform rather than asserted:

```
  bindings: asking namespace-1 whether its create-time bindings and its parent can be changed
     PATCH spec.className = a value that exists nowhere                   HTTP 422
           SupervisorNamespace.infrastructure.cci.vmware.com "{{namespace-1}}" is invalid: [spec.className: Property cannot be updated]
     PATCH spec.regionName = a value that exists nowhere                  HTTP 422
           SupervisorNamespace.infrastructure.cci.vmware.com "{{namespace-1}}" is invalid: [spec.regionName: Property cannot be updated]
     PATCH spec.vpcName = a value that exists nowhere                     HTTP 422
           SupervisorNamespace.infrastructure.cci.vmware.com "{{namespace-1}}" is invalid: [spec.vpcName: Property cannot be updated]
     PATCH metadata.namespace = a project that does not exist             HTTP 200
     PUT   the whole object, body.metadata.namespace = a sibling project, URL unchanged HTTP 422
           SupervisorNamespace.infrastructure.cci.vmware.com "{{namespace-1}}" is invalid: [metadata.namespace: Namespace mismatch:
           value is "{{project-2}}" in the resource and "{{project-1}}" in the path]
     the namespace is unchanged: phase Created, conditions {'Ready': 'True', 'PolicyApplied': 'True', 'Realized': 'True'}
     the Tenant Manager surface, where the project assignment IS a field:
       PUT   the whole object, projectAssignment = a sibling project    HTTP 400
             Changing project assignment of a namespace is not allowed.
       PUT   the whole object, projectAssignment = null                 HTTP 400
             validation error on field 'projectAssignment': may not be null
       POST  an import naming a namespace that exists nowhere           HTTP 400
             Namespace import is not supported for a supervisor associated with NSX Manager.

wrote taxonomy.json (99 kinds) and estate.json (2 project(s)) and naming.json (counts only) and bindings.json (5 refused attempts plus 3 on the Tenant Manager); every estate name replaced by a stable label
```

Read the five rows as two answers.

**The class, the region, and the VPC are frozen.** All three come back `Property cannot be updated`. The guard
runs before the value is validated, which is why a class that exists nowhere still draws the immutability error
rather than a not-found: the field is refused whatever you put in it.

**The parent project is not a field at all.** The fourth row is the one that does not refuse: a patch naming a
different parent is accepted, and the parent simply is not part of what a patch carries, so nothing moves. The
fifth row asks the same question in the form the interface does answer, and the answer names the rule: the
namespace in the body has to match the namespace in the path. The parent is the path. That is also why the
chapter says a namespace belongs to exactly one project rather than that it has a project field.

**The second group is the one that settles it.** A structural refusal only tells you an interface has no field for
something. The tenant manager's namespace body does carry the project assignment, and asked there with an identity
permitted to write, the platform states the rule in a sentence: changing it is not allowed. The field may not be
null either, so a namespace cannot even be released to no project. The binding is therefore permanent by rule
rather than by interface shape, and it holds whatever pathway put the namespace there.

**The third row is the adoption pathway.** A namespace can be created on the Supervisor directly, and the platform
has an import that would bring such a namespace into a project. On this estate it is refused because the Supervisor
is attached to an NSX manager, which is what VPC networking means, and the check runs before the namespace is even
looked up. Where that path is closed, every namespace is born through this interface, with its project chosen at
that moment and never after. What a Supervisor on vSphere networking answers is untested here and not claimed.

A documented cross-project path does exist and it is a copy, not a move: capture the namespace as a blueprint and
redeploy it under another project, leaving the original where it is.

On 9.1.1 the spec also carries `sharedSubnets` and `infraPolicyNames`, and the `bound` map counts both: none of the namespaces here names either.
