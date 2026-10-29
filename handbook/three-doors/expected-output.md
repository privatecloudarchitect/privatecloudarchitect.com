# What doors.py printed on the reference estate

Run on VCF Automation 9.1.1.0100 under a session login, with `VC_HOST` set to the workload domain's vCenter
(vCenter 9.1.1.0.25712839). Every estate name is a placeholder, exactly as the script prints it.

## Read-only: `python3 doors.py`

Run on 2026-10-28, after the provider content library was attached to the whole Supervisor: no namespace has an image
bound to it, and every one names the library's general-purpose images at cluster scope, so every one can build. The
record it wrote is [`doors.json`](doors.json).

```text
doors.py: the same machine, through each door, and what each leaves behind

  in {{project-1}}, what the DIRECT door needs, on this estate:
     a Supervisor namespace, vended to you          3 of 3
     a VM image THAT namespace can name             3 of 3
     storage quota with room for the boot disk      3 of 3
  what the AUTOMATION doors need on top:
     a project you are a member of                  1
     a blueprint holding the manifest               12
     a released version                             39
     a catalog item, for the catalog door only      10

  3 of 3 namespace(s) could build a VM today (an image they can name and room for a 20Gi boot disk)
     {{namespace-1}}        images  0 bound  3 cluster  classes  4  free   262.6 GiB of 390.6  can build
     {{namespace-2}}        images  0 bound  3 cluster  classes  4  free   290.0 GiB of 293.0  can build
     {{namespace-3}}        images  0 bound  3 cluster  classes  4  free    43.0 GiB of 293.0  can build
  images: 0 bound to these namespaces, 102 cluster-scoped (3 general-purpose), sharing 0 by id and 0 by name; 99 of the cluster-scoped are Kubernetes node images, 58 of the 60 that are Ubuntu
  one credential, 4 door(s): 3 answered it, VCF Automation, API 200, VCF Automation, catalog 200, Supervisor, direct 200, vCenter 401

  what a deployment record CLAIMS and what the claim BUYS
     the claim is one string: cci:{{project-1}}:{{namespace-3}}:vmoperator.vmware.com/v1alpha5:VirtualMachine:{{machine-7}}
     5 deployment-level and 12 resource-level Day-2 action(s) exist on a claimed machine
     VirtualMachine.Add.Disk, VirtualMachine.Create.Snapshot, VirtualMachine.Delete.Snapshot, VirtualMachine.Get.Password, VirtualMachine.PowerOff, VirtualMachine.PowerOn ...
     the record carries 19 field(s), including who asked and what they typed

  probe: not run (pass --probe-doors to build the same machine through two doors and compare)

wrote doors.json (3 namespace(s), 17 Day-2 action(s) counted); every estate name replaced by a placeholder
```

## The plan first: `python3 doors.py --probe-doors --probe-vcenter --dry-run`

Run on 2026-10-19, before the image rule changed (its plan line says "the first bound image"); only the two plan
lines are shown.

```text
  DRY RUN, the fourth door would create in vCenter: a machine named handbook-doors-vcenter-native, 1 vCPU, 512 MiB, a 1 GiB disk, in a folder the Supervisor does not own, on one cluster's root pool and a datastore that cluster's machines use, then delete it and read it back. Nothing was created.
  DRY RUN, the probe would create in {{namespace-2}}: a VirtualMachine named handbook-doors-direct (class best-effort-xsmall, the first bound image, storage class {{storageclass-1}}); a blueprint handbook-doors-probe and its version handbook-doors-probe:1.0.0 released to the catalog in {{project-1}}; and a catalog request for a deployment and machine named handbook-doors-catalog. It would then delete all of them and read back the machines, the deployment, the blueprint, the version and both catalogs. No name it would use is taken. Nothing was created.
```

## The probes: `python3 doors.py --probe-doors --probe-vcenter`

From the probe of 2026-10-19 at 21:37:20Z. The record it wrote is kept as
[`records/doors-2026-10-19.json`](records/doors-2026-10-19.json); a run writes only what it read, so today's
`doors.json` carries no probe.

```text
  the fourth door: a machine made straight in vCenter, which is not one of the three
  fourth door: created straight in vCenter, declared by 0 of 5 namespace(s), claimed by no deployment, and it moved the tenant storage quota by 0 bytes. Deleted, and gone: True

  probe: building the same machine twice in {{namespace-2}}, then deleting both and reading back
  DIRECT      created and PoweredOn in ~20s
  CATALOG     requested, deployment settled in ~40s, machine PoweredOn

  the two machines are INDISTINGUISHABLE: 0 owner reference(s) between them, 0 marker(s) naming a door; annotation sets equal
  teardown    direct ~30s (disk promotion at delete: True); through the deployment ~335s (its machine gone at ~324s)
  residue     nothing this run created is still here

wrote doors.json (5 namespace(s), 17 Day-2 action(s) counted, probe included); every estate name replaced by a placeholder
```
