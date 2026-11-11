# What `guestcfg.py` printed

Run against one VCF Automation 9.1.1 organization on 2026-11-10, signed in with a session login, in a throwaway namespace
created for the runs and deleted afterwards. Every estate value is a placeholder. Your images, classes and timings will
differ; the steps should not. The last line of each block, `exit N`, is the shell's report of the script's exit status,
not a line the script prints.

## The complete run: Sysprep for Windows

`GUESTCFG_WINDOWS_BOOTSTRAP=sysprep python3 guestcfg.py run --execute`, the record in [`guestcfg.json`](guestcfg.json).

```
namespace {{namespace-1}} in project {{project-1}}
  images the namespace can name: 4
    {{image-1}}  (cluster, ubuntu64Guest)
    {{image-2}}  (cluster, ubuntu64Guest)
    {{image-3}}  (cluster, vmwarePhoton64Guest)
    {{image-4}}  (cluster, windows2019srvNext_64Guest)
  classes: best-effort-large, best-effort-medium, best-effort-small, best-effort-xsmall
  storage classes visible: {{storageclass-1}}, {{storageclass-2}}, {{storageclass-3}}
  storage quota free: 190.4 GiB; a run needs 160 GiB
  rights in the namespace:
    create  core                     secrets                  True
    delete  core                     secrets                  True
    get     core                     secrets                  True
    create  vmoperator.vmware.com    virtualmachines          True
    delete  vmoperator.vmware.com    virtualmachines          True
    get     vmoperator.vmware.com    virtualmachines          True
    create  vmoperator.vmware.com    virtualmachineservices   True
    delete  vmoperator.vmware.com    virtualmachineservices   True
  what a run would use:
    Ubuntu 24.04 image    {{image-1}}
    Windows 2022 image    {{image-4}}
    classes               best-effort-small (master, Linux minion), best-effort-medium (Windows minion)
    storage class         {{storageclass-2}}
    Windows bootstrap     Sysprep (rawSysprep)

run ac5bd0: Salt 3008.5, Windows path Sysprep (rawSysprep)
step 2: the master
  master PoweredOn with an address after 46s
  load balancer for port 8000 has an address after 16s
  Salt API answered over TLS pinned to the run's certificate after 76s
step 3: the minions
  Windows path: Sysprep (rawSysprep)
  Linux minion PoweredOn with an address after 47s
  Windows minion PoweredOn with an address after 139s
step 4: key acceptance, by exact expected id
  accepted exactly the 2 expected ids after 16s
step 5: ping, grains, one state, applied twice
  test.ping: 2 minions answered after 56s
  grains: Debian and Windows, Salt 3008.5
  the first apply changed the managed file; the second apply changed nothing, on both
step 6: drift named, then corrected
  on both minions: test=True named the drift, an apply restored it, and test=True afterwards reported nothing to change
step 7: retirement, in order: keys, machines, master and secrets
  teardown: 2 minion machine(s), 1 load balancer(s), 1 master machine(s), 4 secret(s); keys: deleted; residue: none
step 8: read back
  nothing this run created is still here
wrote guestcfg.json: outcome complete
exit 0
```

## The two runs before it

**Cloud-init on Windows did not give the machine an address.** With the cloud-init path, the default of the revision that ran, the Windows minion powered on and
its customization reported done, but the guest reported no address within 30 minutes, so the run failed, named the path
it tried and tore down. During the wait VM Operator reported `GuestCustomization` True and
`VirtualMachineBootstrapReady` True, with `VirtualMachineGuestNetworkConfigSynced` False (`NotSynced`: "Neither IPv4 nor
IPv6 address reported by guest"), and vCenter read VMware Tools running and only link-local addresses on the network card. Nothing was read inside the guest, so it is an inference that the image carried nothing that applied the network configuration the VM Service supplies; the Linux guests,
whose cloud-init does, had theirs. Record:
[`records/guestcfg-2026-11-10-run1-cloudinit.json`](records/guestcfg-2026-11-10-run1-cloudinit.json).

```
namespace {{namespace-1}} in project {{project-1}}
  images the namespace can name: 4
    {{image-1}}  (cluster, ubuntu64Guest)
    {{image-2}}  (cluster, ubuntu64Guest)
    {{image-3}}  (cluster, vmwarePhoton64Guest)
    {{image-4}}  (cluster, windows2019srvNext_64Guest)
  classes: best-effort-large, best-effort-medium, best-effort-small, best-effort-xsmall
  storage classes visible: {{storageclass-1}}, {{storageclass-2}}, {{storageclass-3}}
  storage quota free: 190.4 GiB; a run needs 160 GiB
  rights in the namespace:
    create  core                     secrets                  True
    delete  core                     secrets                  True
    get     core                     secrets                  True
    create  vmoperator.vmware.com    virtualmachines          True
    delete  vmoperator.vmware.com    virtualmachines          True
    get     vmoperator.vmware.com    virtualmachines          True
    create  vmoperator.vmware.com    virtualmachineservices   True
    delete  vmoperator.vmware.com    virtualmachineservices   True
  what a run would use:
    Ubuntu 24.04 image    {{image-1}}
    Windows 2022 image    {{image-4}}
    classes               best-effort-small (master, Linux minion), best-effort-medium (Windows minion)
    storage class         {{storageclass-2}}
    Windows bootstrap     cloud-init through Cloudbase-Init

run 68c92c: Salt 3008.5, Windows path cloud-init through Cloudbase-Init
step 2: the master
  master PoweredOn with an address after 62s
  load balancer for port 8000 has an address after 16s
  Salt API answered over TLS pinned to the run's certificate after 61s
step 3: the minions
  Windows path: cloud-init through Cloudbase-Init
  Linux minion PoweredOn with an address after 62s
FAILED: StepFailed: machine guestcfg-68c92c-windows PoweredOn with an address: not done within 30 minutes; Windows path tried: cloud-init through Cloudbase-Init
running the teardown
  teardown: 2 minion machine(s), 1 load balancer(s), 1 master machine(s), 4 secret(s); keys: deleted; residue: none
wrote guestcfg.json: outcome failed
exit 2
```

**On the Sysprep path a Windows machine's name is its host name, and VM Operator refuses one over 15 characters.** The
create answered 422, "host name may not exceed 15 characters for Windows", and the run tore down what it had made. The
same 23-character name was admitted on the cloud-init path. The Windows minion is now `gc-<run>-win`. Record:
[`records/guestcfg-2026-11-10-run2-windows-name-refused.json`](records/guestcfg-2026-11-10-run2-windows-name-refused.json).

```
namespace {{namespace-1}} in project {{project-1}}
  images the namespace can name: 4
    {{image-1}}  (cluster, ubuntu64Guest)
    {{image-2}}  (cluster, ubuntu64Guest)
    {{image-3}}  (cluster, vmwarePhoton64Guest)
    {{image-4}}  (cluster, windows2019srvNext_64Guest)
  classes: best-effort-large, best-effort-medium, best-effort-small, best-effort-xsmall
  storage classes visible: {{storageclass-1}}, {{storageclass-2}}, {{storageclass-3}}
  storage quota free: 190.4 GiB; a run needs 160 GiB
  rights in the namespace:
    create  core                     secrets                  True
    delete  core                     secrets                  True
    get     core                     secrets                  True
    create  vmoperator.vmware.com    virtualmachines          True
    delete  vmoperator.vmware.com    virtualmachines          True
    get     vmoperator.vmware.com    virtualmachines          True
    create  vmoperator.vmware.com    virtualmachineservices   True
    delete  vmoperator.vmware.com    virtualmachineservices   True
  what a run would use:
    Ubuntu 24.04 image    {{image-1}}
    Windows 2022 image    {{image-4}}
    classes               best-effort-small (master, Linux minion), best-effort-medium (Windows minion)
    storage class         {{storageclass-2}}
    Windows bootstrap     Sysprep (rawSysprep)

run 7340de: Salt 3008.5, Windows path Sysprep (rawSysprep)
step 2: the master
  master PoweredOn with an address after 47s
  load balancer for port 8000 has an address after 16s
  Salt API answered over TLS pinned to the run's certificate after 76s
step 3: the minions
  Windows path: Sysprep (rawSysprep)
FAILED: StepFailed: create VirtualMachine guestcfg-7340de-windows answered 422: admission webhook "default.validating.virtualmachine.v1alpha5.vmoperator.vmware.com" denied the request: metadata.name: Invalid value: "guestcfg-7340de-windows": host name may not exceed 15 characters for Windows
running the teardown
  teardown: 1 minion machine(s), 1 load balancer(s), 1 master machine(s), 4 secret(s); keys: deleted; residue: none
wrote guestcfg.json: outcome failed
exit 2
```
