# What `guestcfg.py` printed

Run against one VCF Automation 9.1.1 organization, signed in with a session login, in throwaway namespaces created for
the runs: the two complete runs of the second proof, 2026-11-11, first, then two runs of an earlier revision,
2026-11-10, kept for what they showed. Each run's teardown removed everything it made and read the namespace back. Every estate value is a placeholder, except one storage class whose name
is also a word the companion uses for its own settings (`supervisor`), which the scrubber spares in the 2026-11-11 runs.
Your images, classes and timings will differ; the steps should not. The last line of each block, `exit N`, is the
shell's report of the script's exit status, not a line the script prints.

## The complete run, directly at the namespace endpoint: a key generated on the master, and the source ranges read

`GUESTCFG_KEYS=preseed GUESTCFG_PROVE_SOURCE_RANGES=1 GUESTCFG_RUNNER_ADDRESS=<your-runner-address> python3 guestcfg.py run --execute`,
with Sysprep for Windows, the default. The record is [`guestcfg.json`](guestcfg.json), also kept as
[`records/guestcfg-2026-11-11-runB-direct-keys-generated.json`](records/guestcfg-2026-11-11-runB-direct-keys-generated.json).

- **Source ranges.** With the API's load balancer patched to `192.0.2.0/24` (TEST-NET-1, which excludes the runner),
  the API kept answering the runner for the whole read, as it did with `0.0.0.0/0` and with the runner's own address. On
  this load balancer the field was accepted and did not restrict a client; prove your own with the same setting.
- **A key generated on the master.** The Linux minion's pair was generated with the wheel `key.gen_accept` before the
  minion existed and seeded through its cloud-config; the minion was never pending and answered a ping. The Windows
  minion was accepted by exact id, the companion's choice: one first-logon CommandLine holds at most 1024 characters, a
  PEM private key is longer, and splitting it across commands was neither built nor run. The record, written before this
  wording, gives an earlier reason in `steps.keysGenerated.windowsNotSeededBecause`.
- **The probes.** A consistency read, not a trust check: on both minions the public key the minion holds is the one
  the master holds for its id, while
  `key.finger` on the minion and on the master print different fingerprints: Salt 3008.5 hashes the PEM's inner lines on
  the minion and the whole PEM on the master. For the seeded Linux minion, whose `minion.pub` is the master's own text,
  a SHA-256 of the whole file equals the master's fingerprint; for the Windows minion, which made its own key, it does
  not. After the Sysprep first logon, `quser` read no user signed in (exit 0, nothing on stdout, `No User exists for *`
  on stderr).

```
namespace {{namespace-1}} in project {{project-1}}
  images the namespace can name: 4
    {{image-1}}  (cluster, ubuntu64Guest)
    {{image-2}}  (cluster, ubuntu64Guest)
    {{image-3}}  (cluster, vmwarePhoton64Guest)
    {{image-4}}  (cluster, windows2019srvNext_64Guest)
  classes: best-effort-large, best-effort-medium, best-effort-small, best-effort-xsmall
  storage classes visible: {{storageclass-1}}, {{storageclass-2}}, supervisor
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
    patch   vmoperator.vmware.com    virtualmachineservices   True
  what a run would use:
    Ubuntu 24.04 image    {{image-1}}
    Windows 2022 image    {{image-4}}
    classes               best-effort-small (master, Linux minion), best-effort-medium (Windows minion)
    storage class         {{storageclass-2}}
    built                 directly at the namespace endpoint (GUESTCFG_VIA=supervisor)
    minion keys           generated on the master and seeded at bootstrap (GUESTCFG_KEYS=preseed)
    API source ranges     not set; the run proves whether the load balancer enforces them
    Windows bootstrap     Sysprep (rawSysprep)

run 09af90: Salt 3008.5, Windows path Sysprep (rawSysprep)
  built directly at the namespace endpoint; minion keys generated on the master and seeded at bootstrap
step 2: the master
  master PoweredOn with an address after 51s
  load balancer for port 8000 has an address after 4s
  Salt API answered over TLS pinned to the run's certificate after 76s
source ranges: whether this estate's load balancer enforces loadBalancerSourceRanges
  TEST-NET-1 (192.0.2.0/24): answered at the end of a 180s read (13 of 13 reads answered)
  any source (0.0.0.0/0): answered at the end of a 180s read (13 of 13 reads answered)
  the runner's own address ({{cidr-1}}): answered at the end of a 180s read (13 of 13 reads answered)
  original ranges restored; the API answered again after 0s
keys generated on the master, before any minion exists (key.gen_accept)
  the Linux minion's pair generated and its public key accepted; the Windows minion keeps acceptance by exact id
step 3: the minions
  Windows path: Sysprep (rawSysprep)
  Linux minion PoweredOn with an address after 52s
  Windows minion PoweredOn with an address after 75s
step 4: key acceptance, by exact expected id; 1 key generated on the master
  accepted exactly the 2 expected ids after 62s
  the seeded minion answered a ping after 2s, was never pending, and its key is the one generated for it
step 5: ping, grains, one state, applied twice
  test.ping: 2 minions answered after 56s
  grains: Debian and Windows, Salt 3008.5
  the first apply changed the managed file; the second apply changed nothing, on both
probes, read-only: each minion's own key fingerprint against the master's, and the Windows sessions
  Linux: the same key True; key.finger minion e6:e8:a6:7e:8d:7a:bb:eb:04:4b:ce:d8:8b:a8:cb:ce:2d:5b:c4:04:5a:87:f5:8d:93:11:14:65:c5:d7:a0:26, master b8:c3:d5:27:47:86:66:a4:66:68:91:2e:6c:a3:40:63:8c:8a:25:e3:5d:12:86:ad:36:b4:cc:8c:50:65:4c:f6 (differ); SHA-256 of the whole minion.pub equals the master's; line lengths minion 26,64,64,64,64,64,64,8,24, master 26,64,64,64,64,64,64,8,24
  Windows: the same key True; key.finger minion 2e:3b:a7:45:47:3e:fb:ac:c3:69:5f:90:9c:9b:4e:f3:02:ee:c4:cd:42:57:e0:0d:f5:66:c1:53:fc:2a:fa:26, master e8:71:7f:73:29:cc:fa:ec:ab:e1:7b:b4:26:86:2f:ec:77:70:35:9b:66:fa:f0:28:07:92:22:41:4c:9b:74:5f (differ); SHA-256 of the whole minion.pub differs from the master's; line lengths minion 26,64,64,64,64,64,64,8,24, master 26,64,64,64,64,64,64,8,24
  on both minions the minion's own public key is the one the master holds for its id; Windows: 0 session(s) signed in (quser exit 0)
step 6: drift named, then corrected
  on both minions: test=True named the drift, an apply restored it, and test=True afterwards reported nothing to change
step 7: retirement, in order: keys, machines, master and secrets
  teardown: 2 minion machine(s), 1 load balancer(s), 1 master machine(s), 4 secret(s); keys: deleted; residue: none
step 8: read back
  nothing this run created is still here
wrote guestcfg.json: outcome complete
exit 0
```

## The complete run through VCF Automation: the three blueprints

`GUESTCFG_VIA=automation GUESTCFG_PROJECT=<the-project-holding-the-namespace> python3 guestcfg.py run --execute`, with
`GUESTCFG_API_SOURCE_RANGES` unset, so the master blueprint's `api_source_ranges` input was `0.0.0.0/0`. The run created
the three blueprints from the files beside the script as they stood that day, validated
each, deployed the master, read its address, deployed the two minions with it, and its teardown deleted the minions'
keys, then the deployments, the minions' first, then the master's, then the blueprints. Since that run, in
`salt-minion-linux.blueprint.yaml` the deletion of the seeded private key's copy moved before anything in the install can
exit; comments changed, as did the description of the master blueprint's address output. Record:
[`records/guestcfg-2026-11-11-runA5-automation.json`](records/guestcfg-2026-11-11-runA5-automation.json).

```
namespace {{namespace-1}} in project {{project-1}}
  images the namespace can name: 4
    {{image-1}}  (cluster, ubuntu64Guest)
    {{image-2}}  (cluster, ubuntu64Guest)
    {{image-3}}  (cluster, vmwarePhoton64Guest)
    {{image-4}}  (cluster, windows2019srvNext_64Guest)
  classes: best-effort-large, best-effort-medium, best-effort-small, best-effort-xsmall
  storage classes visible: {{storageclass-1}}, {{storageclass-2}}, supervisor
  storage quota free: 190.4 GiB; a run needs 160 GiB
  rights in the namespace:
    get     core                     secrets                  True
    get     vmoperator.vmware.com    virtualmachines          True
    get     vmoperator.vmware.com    virtualmachineservices   True
  what a run would use:
    Ubuntu 24.04 image    {{image-1}}
    Windows 2022 image    {{image-4}}
    classes               best-effort-small (master, Linux minion), best-effort-medium (Windows minion)
    storage class         {{storageclass-2}}
    built                 VCF Automation blueprints (GUESTCFG_VIA=automation)
    minion keys           accepted by exact expected id (GUESTCFG_KEYS=accept)
    API source ranges     0.0.0.0/0
    Windows bootstrap     Sysprep (rawSysprep)

run 906e54: Salt 3008.5, Windows path Sysprep (rawSysprep)
  built VCF Automation blueprints; minion keys accepted by exact expected id
step 2: the master, through VCF Automation
  3 blueprints created in the project from the files as written
  each validated with no error: salt-master.blueprint.yaml, salt-minion-linux.blueprint.yaml, salt-minion-windows-sysprep.blueprint.yaml
  deployment guestcfg-906e54-master CREATE_SUCCESSFUL after 110s
  master PoweredOn with an address after 6s more, read from the namespace
  load balancer for port 8000 has an address after 6s
  Salt API answered over TLS pinned to the run's certificate after 92s
  the load balancer carries loadBalancerSourceRanges 0.0.0.0/0
step 3: the minions, through VCF Automation
  Windows path: Sysprep (rawSysprep)
  deployments guestcfg-906e54-linux and gc-906e54-win CREATE_SUCCESSFUL after 47s and 0s more
  Linux minion PoweredOn with an address after 47s
  Windows minion PoweredOn with an address after 54s
step 4: key acceptance, by exact expected id
  accepted exactly the 2 expected ids after 78s
step 5: ping, grains, one state, applied twice
  test.ping: 2 minions answered after 56s
  grains: Debian and Windows, Salt 3008.5
  the first apply changed the managed file; the second apply changed nothing, on both
probes, read-only: each minion's own key fingerprint against the master's, and the Windows sessions
  Linux: the same key True; key.finger minion b2:0f:0f:ac:9d:fd:03:cd:15:f5:b6:b2:03:3a:00:fe:e4:90:36:74:4f:1d:49:6a:5e:87:e3:66:16:f4:04:52, master 13:f3:83:54:d6:b3:c4:f3:79:5c:27:a9:30:c2:1b:db:61:c2:a7:4d:b9:bb:66:61:1a:c6:40:00:76:d8:64:67 (differ); SHA-256 of the whole minion.pub differs from the master's; line lengths minion 26,64,64,64,64,64,64,8,24, master 26,64,64,64,64,64,64,8,24
  Windows: the same key True; key.finger minion dd:9d:f9:85:25:0c:27:e4:7d:ec:f1:23:b8:c9:3e:57:6e:24:24:c0:56:a3:c1:e3:34:f8:68:1b:70:7a:f5:6d, master 6a:90:64:83:b2:52:37:57:ac:46:82:cb:01:7e:af:c0:69:ce:27:a6:43:c6:66:1d:df:f7:0d:43:bc:92:66:35 (differ); SHA-256 of the whole minion.pub differs from the master's; line lengths minion 26,64,64,64,64,64,64,8,24, master 26,64,64,64,64,64,64,8,24
  on both minions the minion's own public key is the one the master holds for its id; Windows: 0 session(s) signed in (quser exit 0)
step 6: drift named, then corrected
  on both minions: test=True named the drift, an apply restored it, and test=True afterwards reported nothing to change
step 7: retirement, in order: keys, the minion deployments, the master's, the blueprints
  teardown: 3 deployment(s) deleted through VCF Automation, minions first; 3 blueprint(s); keys: deleted; residue: none
step 8: read back
  nothing this run created is still here
wrote guestcfg.json: outcome complete
exit 0
```

## Two runs of an earlier revision, 2026-11-10

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
