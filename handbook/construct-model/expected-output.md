# Expected output

One run of `inventory.py` against a VCF Automation 9.1 organization on 2026-09-16. Every estate name is a placeholder
the script assigned in the order it met the object.

```text
inventory.py: the construct model read through the Cloud Consumption Interface, read-only

  taxonomy: 13 VMware API groups, 99 kinds; 60 published at the top level, 40 under a project
  published: 1 region(s), 3 zone(s), 3 namespace class(es), 1 VPC(s), 3 subnet(s), 3 storage-class quota(s), 16 VM class summaries
  {{project-1}}: bindings {'regions': 0, 'classes': 0, 'vpcs': 0, 'subnets': 0, 'serviceEngineGroups': 0, 'infraPolicies': 0}; role bindings {'count': 4, 'roles': ['admin', 'edit', 'edit_adv'], 'fields': ['roleRef', 'subjects']}; images 3; catalog items 10; na
     {{namespace-1}}: phase Created; bound {'region': '{{region-1}}', 'zone': None, 'class': '{{class-1}}', 'vpc': '{{vpc-1}}', 'storageClasses': 0, 'vmClasses': 0, 'classOverrides': False}; workloads {'virtualMachines': 7, 'vksClusters': 2}
     {{namespace-2}}: phase Created; bound {'region': '{{region-1}}', 'zone': None, 'class': '{{class-1}}', 'vpc': '{{vpc-1}}', 'storageClasses': 0, 'vmClasses': 0, 'classOverrides': False}; workloads {'virtualMachines': 3, 'vksClusters': 1}
     {{namespace-3}}: phase Created; bound {'region': '{{region-1}}', 'zone': None, 'class': '{{class-1}}', 'vpc': '{{vpc-1}}', 'storageClasses': 0, 'vmClasses': 0, 'classOverrides': False}; workloads {'virtualMachines': 5, 'vksClusters': 1}
  {{project-2}}: bindings {'regions': 0, 'classes': 0, 'vpcs': 0, 'subnets': 0, 'serviceEngineGroups': 0, 'infraPolicies': 0}; role bindings {'count': 2, 'roles': ['edit'], 'fields': ['roleRef', 'subjects']}; images 3; catalog items 10; namespaces 0

wrote taxonomy.json (100 kinds) and estate.json (2 project(s)); every estate name replaced by a stable label
```

The two records it wrote are [`taxonomy.json`](taxonomy.json) (every VMware API group and kind the interface
declared, with scope, verbs, and the count of each top-level kind) and [`estate.json`](estate.json) (the tree).
