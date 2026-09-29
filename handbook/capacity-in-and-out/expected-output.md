# Expected output

The printed ladder from the reference estate, 2026-09-29, with three vCenters named. Names are placeholders;
your counts will differ. Exit code 2, because one gate did not pass.

```
capacity ladder, read 2026-09-29T05:47:10Z

L1 workload domains
  [PASS] every domain ACTIVE: 2 of 2 domains ACTIVE

L3 Supervisors
  [PASS] {{supervisor-1}} RUNNING and READY: RUNNING / READY, 3 zone(s) bound (3 management)
  [PASS] {{supervisor-1}} no zone left half-drained: 0 zone(s) marked for removal, 0 tenant namespace(s) still on them
  [PASS] {{supervisor-1}} identity slot held by Automation or empty: 1 external provider(s), 1 of them this Automation

L4 provider plane
  [PASS] every region READY: 1 of 1 region(s) READY

L5 tenancy
  [FAIL] no disabled organization still holding capacity or networking: 1 disabled organization(s) still hold quota, networking, VPCs or namespaces
  residue: {{org-1}}

L6 unmanaged VM lists
  {{vcenter-2}}: 9 unmanaged records, 2 of them the platform's own machines by name; fields per record: cpuCount, memory, moRef, name, path, state, storage, virtualHardwareVersion
  {{vcenter-3}}: 54 unmanaged records, 2 of them the platform's own machines by name; fields per record: cpuCount, memory, moRef, name, path, state, storage, virtualHardwareVersion
  {{vcenter-1}}: 31 unmanaged records, 9 of them the platform's own machines by name; fields per record: cpuCount, memory, moRef, name, path, state, storage, virtualHardwareVersion

wrote ./ladder.json; 1 gate(s) not passing
```

The one FAIL is the lesson of plate 05 in the field note, found on the estate the note is written from: an
organization that was disabled rather than decommissioned, still holding a quota, regional networking and a VPC.
