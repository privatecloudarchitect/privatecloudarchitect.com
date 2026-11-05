# What `vmservice.py` prints

Run against one VCF Automation 9.1.1.0100 organization on 2026-11-04, signed in with a session login. Your counts
will differ; the shapes should not.

```
vmservice.py: every machine on the workload plane, sorted by how it arrived

  the VM Service publishes 13 kind(s) at v1alpha5 (versions served: v1alpha1, v1alpha2, v1alpha3, v1alpha4, v1alpha5); 13 declare create
     clustervirtualmachineimages, virtualmachineclasses, virtualmachinegrouppublishrequests, virtualmachinegroups, virtualmachineimagecaches, virtualmachineimages, virtualmachinepublishrequests, virtualmachinereplicasets, virtualmachines, virtualmachineservices, virtualmachinesetresourcepolicies, virtualmachinesnapshots, virtualmachinewebconsolerequests
  the schema names 4 bootstrap provider(s): cloudInit, linuxPrep, sysprep, vAppConfig; cloud-init takes 6 cloud-config key(s) inline, or a secret by key and name
  power: 0 of 9 machine(s) hold a declared power state different from the observed one

  arrivals: 9 machine(s) = 3 minted by a cluster controller, 3 linked by a deployment resource, 3 made directly on the wire
     4 deployment resource(s) link a machine, naming 4 distinct machine(s); 1 of those are not on the plane

  bootstrap: 4 of 9 machine(s) name a provider, 4 of them cloud-init
     controller: cloudInit(instanceID, rawCloudConfig) 3
     catalog: cloudInit(instanceID, rawCloudConfig) 1; none 2
     wire: none 3
     bootstrap conditions in status: {'GuestCustomization=True': 9, 'VirtualMachineBootstrapReady=True': 4}
  of the 3 catalog-wrapped machines, 0 carry any label or annotation naming a deployment; of the 3 hand-made ones, 0

  a blueprint may declare 5 resource type(s): CCI.Supervisor.Namespace, CCI.Supervisor.Resource, CCI.VPC, CCI.VPC.Configuration, Util.PasswordEntry
     a virtual machine is not one of them; the catalog reaches one through the supervisor resource, which names the machine kind in 4 deployment resource(s) here
  classes visible across 4 namespace(s): 4, of which 4 publish a resource-policy block and 4 have every value in it set to zero
  the region publishes 16 class summaries, 0 requiring a reservation. A policy block is not a reservation, and this is the field that answers it
  exposure: {'ClusterIP': 1, 'LoadBalancer': 3}

wrote vmservice.json (13 kinds, 9 machines sorted into 3/3/3); every organization name replaced by a placeholder
```

## What each block tells you

- **the VM Service publishes**: every kind at the group's preferred version, the versions served, and how many
  kinds declare create. A declared verb is not a permission.
- **the schema names**: the bootstrap providers the served schema defines, and the two forms cloud-init takes: a
  subset of cloud-config written into the machine, or a key in a secret named by its name and key.
- **power**: how many machines hold a declared power state different from the observed one.
- **arrivals**: every machine sorted by object into minted by a cluster controller, linked by a deployment
  resource (joined on the namespace and the name the link carries), or made directly; then how many deployment
  resources link a machine and whether any of them names a machine that is not on the plane.
- **bootstrap**: how many machines name a provider and in what form, by the path each arrived by, key names only;
  then the bootstrap conditions their status reports. A machine that names none can still report guest
  customization: the schema says a default method may be selected by the guest OS, LinuxPrep for Linux.
- **catalog-wrapped machines ... carry any label or annotation**: whether the machine itself records its path.
- **a blueprint may declare**: the resource types, and the deployment resources that name the machine kind.
- **classes** and **class summaries**: the policy block every class publishes, and the region field that answers
  whether a class reserves anything.
- **exposure**: the service types in front of the machines.

## `--compare`: the weekly check

The same run with `--compare records/vmservice-vcf-9.1.json`, the 9.1 record of 2026-09-21 kept in this folder.
The direct-arrival count is the one that matters: when it rises the run exits 1, as it did on this run.

```
  compared with the earlier record, arrivals then and now:
     total              15 then,    9 now
     controllerOwned    10 then,    3 now
     catalogWrapped      3 then,    3 now
     rawOnTheWire        2 then,    3 now  ROSE

wrote vmservice.json (13 kinds, 9 machines sorted into 3/3/3); every organization name replaced by a placeholder
```
