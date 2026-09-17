# Expected output

One run of `inventory.py` against a VCF Automation 9.1 organization on 2026-09-16, with `naming-standard.json`
beside it so the naming audit runs. Every estate name is a placeholder the script assigned in the order it met
the object; the audit prints conformance counts and never a name.

```text
inventory.py: the construct model read through the Cloud Consumption Interface, read-only

  taxonomy: 13 VMware API groups, 99 kinds; 60 published at the top level, 40 under a project
  published: 1 region(s), 3 zone(s), 3 namespace class(es), 1 VPC(s), 3 subnet(s), 3 storage-class quota(s), 16 VM class summaries
  {{project-1}}: bindings {'regions': 0, 'classes': 0, 'vpcs': 0, 'subnets': 0, 'serviceEngineGroups': 0, 'infraPolicies': 0}; role bindings {'count': 4, 'roles': ['admin', 'edit', 'edit_adv'], 'fields': ['roleRef', 'subjects']}; images 3; 
     {{namespace-1}}: phase Created; bound {'region': '{{region-1}}', 'zone': None, 'class': '{{class-1}}', 'vpc': '{{vpc-1}}', 'storageClasses': 0, 'vmClasses': 0, 'classOverrides': False}; workloads {'virtualMachines': 7, 'vksClusters': 2
     {{namespace-2}}: phase Created; bound {'region': '{{region-1}}', 'zone': None, 'class': '{{class-1}}', 'vpc': '{{vpc-1}}', 'storageClasses': 0, 'vmClasses': 0, 'classOverrides': False}; workloads {'virtualMachines': 3, 'vksClusters': 1
     {{namespace-3}}: phase Created; bound {'region': '{{region-1}}', 'zone': None, 'class': '{{class-1}}', 'vpc': '{{vpc-1}}', 'storageClasses': 0, 'vmClasses': 0, 'classOverrides': False}; workloads {'virtualMachines': 5, 'vksClusters': 1
  {{project-2}}: bindings {'regions': 0, 'classes': 0, 'vpcs': 0, 'subnets': 0, 'serviceEngineGroups': 0, 'infraPolicies': 0}; role bindings {'count': 2, 'roles': ['edit'], 'fields': ['roleRef', 'subjects']}; images 3; catalog items 10; nam

  naming: 6 of 51 names conform to the standard, across 10 constructs
     project                  2 of 2   keep    <team / app-portfolio>  e.g. checkout-team
     supervisor-namespace     0 of 3   rename  <app>-<env>-<region>-<sup-hash>  e.g. checkout-prod-eu-west-1-g9w34
     region                   1 of 1   keep    <geo>-<direction>-<ordinal>  e.g. eu-west-1
     supervisor-zone          0 of 3   rename  <region>-az<n>  e.g. eu-west-1-az1
     namespace-class          0 of 3   rename  ns-<profile>-<size>  e.g. ns-general-small
     vpc                      0 of 1   rename  vpc-<tenant/project>-<region>  e.g. vpc-checkout-eu-west-1
     vpc-subnet               0 of 3   rename  <vpc>-<function>  e.g. vpc-checkout-eu-west-1-private
     vm-class                 0 of 16  rename  <qos>-<profile?>-<size>  e.g. guaranteed-general-large
     virtualmachine           1 of 15  refine  <app>-<role>-<ordinal>  e.g. checkout-web-01
     vks-cluster              2 of 4   refine  <app>-<env>-vks  e.g. checkout-prod-vks

wrote taxonomy.json (100 kinds) and estate.json (2 project(s)) and naming.json (counts only); every estate name replaced by a stable label
```

The three records it wrote are [`taxonomy.json`](taxonomy.json) (every VMware API group and kind the interface
declared, with scope, verbs, and the count of each top-level kind), [`estate.json`](estate.json) (the tree), and
[`naming.json`](naming.json) (per construct, how many of that estate's names conform to the standard).

Six of fifty-one names conformed on that run, which is the ordinary result for an estate that grew before it had a
standard: the region and the projects conform, and the namespaces, zones, classes, VPC, subnets, and VM classes do
not. The verdict column is the work list, and the rename order is outermost boundary first.
