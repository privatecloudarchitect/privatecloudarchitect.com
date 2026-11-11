# Guest configuration with Salt

Companion to the handbook's [guest configuration chapter](https://privatecloudarchitect.com/handbook/guest-configuration), extra credit that nothing later in the handbook depends on.
Stage 02 of the template series ends with a machine that configures itself once, at first boot. This folder holds what
keeps that guest configured afterwards, on the free, community-driven Salt Project's path:

| What | Where |
|---|---|
| `guestcfg.py` | Stands up an independent Salt master, a Linux minion and a Windows minion on the VM Service, walks the guest-configuration lifecycle, removes every object it made, and writes a scrubbed record. Standard library; no token or password is printed or written. |
| `states/guestcfg/` | The two small Salt states a run applies: `init.sls`, one managed file for Linux and Windows, and `drift.sls`, the drift for step 6. |
| `templates/02x-vm-salt-minion/` | The same shapes for readers: `salt-master.vm.yaml`, `salt-minion-linux.vm.yaml`, `salt-minion-windows-sysprep.vm.yaml` (the default Windows path) and `salt-minion-windows.vm.yaml` (cloud-init, for an image built with Cloudbase-Init), densely commented, with `<REPLACE_ME-...>` placeholders. A test holds them to what the run renders. They sit in this folder, beside the script, because the template series' folder is enumerated and pinned at six stages: this branch does not change that count. |
| `guestcfg.json` | The record of the complete proof run on the reference estate, 2026-11-10, every estate value a placeholder. |
| `expected-output.md` | What the script printed in the three proof runs, the complete one first. |
| `records/` | The two earlier proof runs' records: the cloud-init path on Windows, and the Windows name refused on the Sysprep path. |

**Which Salt.** This is Salt Project, the free community tool, run by you, on your own master. It is not VMware Salt
(a licensed VCF Advanced Service) and it is not the Salt that VCF runs for its own components, which is not a master
for your workloads. Nothing later in the handbook depends on this track.

**Provenance:** run on VCF Automation 9.1.1 on 2026-11-10 under a session login, three times, in a throwaway namespace
created for the runs and deleted afterwards ([`expected-output.md`](expected-output.md)). The
third run completed every step with Sysprep for Windows ([`guestcfg.json`](guestcfg.json)); the first two, which each
tore down cleanly, are kept in [`records/`](records/). Each run left nothing behind, and vCenter listed none of their
machines afterwards.

## Run it

```bash
export VCFA_HOST=<automation-fqdn> VCFA_ORG=<org> VCFA_USER=<account>
( umask 077; mkdir -p ~/.vcf && cat > ~/.vcf/vcfa-password )   # paste your password, then Ctrl-D
export VCFA_PASSWORD_FILE=~/.vcf/vcfa-password             # mode 0600; or VCFA_REFRESH_TOKEN_FILE
export GUESTCFG_NAMESPACE=<a-throwaway-namespace-you-may-build-in>
export TLS_VERIFY=false                                    # only on a self-signed lab CA

python3 guestcfg.py read                # read-only: images, classes, storage, what a run would need
python3 guestcfg.py run --dry-run       # the default for run: every object it would create, nothing created
python3 guestcfg.py run --execute       # build, prove, tear down, read back
python3 guestcfg.py teardown            # list what a teardown would delete, deleting nothing
python3 guestcfg.py teardown --execute  # idempotent; safe to run after any failure
```

Optional settings, each described in `--help`: `GUESTCFG_PROJECT`, `GUESTCFG_LINUX_IMAGE`, `GUESTCFG_WINDOWS_IMAGE`,
`GUESTCFG_VM_CLASS`, `GUESTCFG_WINDOWS_VM_CLASS`, `GUESTCFG_STORAGE_CLASS`, `GUESTCFG_MIN_FREE_GIB`,
`GUESTCFG_WINDOWS_BOOTSTRAP` (`cloudinit` or `sysprep`), `GUESTCFG_RUN_ID`, `OUT_DIR`. The sign-in is the same session
login or organization refresh token the other companions use; a secret file open to group or other is refused before it is read.

A run can outlast one bearer, so a bearer that ends is renewed with the same sign-in and the request sent again; the password or
token stays in memory for the length of the run for that reason.

Exit codes: 0 done; 2 a sign-in was refused, a precondition was not met, or a step failed and the teardown ran; 3
something this run created could not be removed; 5 an unknown argument. An unknown argument is refused before any
client opens; `--help` prints the usage and does nothing else.

## What a run does

| Step | What it does | What it proves |
|---|---|---|
| 1 | Reads images, classes, storage and rights; stops if anything is missing | the run can complete |
| 2 | Builds one Ubuntu 24.04 master: Salt 3008 LTS, API over TLS, `auto_accept: False` | an independent master stands up with no hand step |
| 3 | Builds one Ubuntu 24.04 minion and one Windows Server 2022 minion | the bootstrap works on both, in the VM Service shape |
| 4 | Accepts exactly the two expected minion ids and leaves any other pending key unaccepted, reporting how many | key trust by identity |
| 5 | Pings, reads grains, applies one state to each, then applies it again | the state works and the second apply changes nothing |
| 6 | Changes the managed file; `test=True` names it; an apply restores it | drift is named, then corrected |
| 7 | Deletes the minion keys, then the machines, then the master and secrets | the retirement order |
| 8 | Reads the namespace back | no residue |

**Objects a run creates**, all in the namespace `GUESTCFG_NAMESPACE` names, each labelled `handbook-guestcfg-run=<run>`:
four `Secret` objects (`<prefix>-api-access`, `<prefix>-master-bootstrap`, `<prefix>-linux-bootstrap`,
`<prefix>-windows-bootstrap`), three `VirtualMachine` objects (`<prefix>-master`, `<prefix>-linux`, `<prefix>-windows`)
and one `VirtualMachineService` (`<prefix>-api`), where `<prefix>` is `guestcfg-<run>` and `<run>` is six hexadecimal
characters generated for the run. `run --dry-run` lists exactly these before any is made. Any failure runs the teardown
before the script exits, and `teardown --execute` can repeat that at any time; both delete only what carries the run's
label, read back by label afterwards.

## Reach: how a script outside the VPC talks to a master inside it

The master sits on the namespace's private VPC network and the script runs from somewhere else. The Salt API therefore
needs a way in, and it gets the narrowest one that does the job: the stage 03 load-balancer shape, one
`VirtualMachineService` of type `LoadBalancer`, port 8000 only, selecting the master, created after the master is up and
deleted first in the teardown. Nothing else about the master is exposed.

Minions need the master's address, so the master is built and read (`status.network.primaryIP4`) before the minions are.
Salt's minion ports stay private: minions dial out to the master on 4505 and 4506 inside the VPC, the two ports are
reachable on the master only, and neither has a load balancer.

The API runs TLS with a certificate generated for the run with `openssl`, so the script never turns verification off: it
pins that certificate, trusting nothing else, and skips the hostname check because the load balancer's address is
unknown when the certificate is made. The Salt API account's rights are exactly the functions the run calls and exactly
the two minions it expects, and the password is held only in a Kubernetes Secret: the guest receives its SHA-256 digest
in Salt's `file` eauth backend, never the password itself. The master's Salt configuration keeps `auto_accept: False`
and `open_mode: False`, and enables only the three API clients the run uses.

## Windows: two ways to bootstrap, one that is named when it fails

`GUESTCFG_WINDOWS_BOOTSTRAP=sysprep`, the default, takes the path Windows carries as shipped: `spec.bootstrap.sysprep.rawSysprep`
over a Secret holding an unattend answer file, the VM Operator project's minimal raw Sysprep configuration plus an
automatic first logon that downloads the pinned Salt installer from Broadcom's package location and runs Salt's
documented silent install with the master's address and the minion id. Two of its fields follow Microsoft's unattend
reference rather than the VM Operator page's example: the DNS server's address is the element's value with an index as
its key, and the default route's prefix is `0.0.0.0/0`, not a subnet mask. On this path the machine's name is its Windows
host name, which VM Operator limits to 15 characters, so the Windows minion is `gc-<run>-win`.

`GUESTCFG_WINDOWS_BOOTSTRAP=cloudinit` is for an image built with Cloudbase-Init: the Secret's user-data is a
`#ps1_sysnative` PowerShell script running the same install. On the stock Windows Server 2022 image the proof runs used
it left the guest with link-local addresses only and the run failed at its limit ([`expected-output.md`](expected-output.md)).

Which path a run tried is in its output and record. A Windows minion whose key does not reach the master within the
Windows limit is a timed failure that names the path tried, says which setting selects the other one, and tears down.

**Timeouts are stated, and progress is reported.** A first boot is the long wait. The limits in `LIMITS` in `guestcfg.py`:
15 minutes for a machine to be PoweredOn with an address (30 for Windows), 15 for the load balancer's address, 30 for the
master's first boot to answer on its API, 30 for the Linux minion's key, 60 for the Windows minion's key, 20 for one Salt
job, and 20 for a machine's delete. The script prints a progress line at regular intervals while it waits.

## Trust: accept the ones you expect

The master never accepts a key on its own. The run lists pending keys and accepts exactly the two minion ids it expects
(the machines' own names, `guestcfg-<run>-linux` and `gc-<run>-win`; a Windows machine's name is its host name, and on the Sysprep path VM Operator refuses one over 15 characters). A third machine cannot be created in this
proof, so "refuse a third name" is implemented as: accept exactly the two expected ids, leave any other pending key
unaccepted, and report how many there were. A third name is never accepted, and a stray key already in the accepted list
stops the run.

The run compares no fingerprint: within its access it has the master's view of a pending key and no second source to
check it against. So acceptance is by exact expected id, which trusts the id the minion declares. By hand, do better:
read the pending key's fingerprint on the master with `salt-key -f <minion-id>`, read the minion's own on its console
with `salt-call --local key.finger`, and accept with `salt-key -a <minion-id>` only when they match. The stronger form
is a key generated on the master before first boot with the wheel function `key.gen_accept`, delivered to the minion in
its bootstrap Secret; whoever can read that Secret then holds the minion's identity. The companion does not exercise it.

## What the runs confirmed, and what they did not

Each behavior below held on VCF Automation 9.1.1 on 2026-11-10; the runs' own output, with their timings, is in
[`expected-output.md`](expected-output.md), and that is the place to compare your run with.

- A session login that created the namespace held every right the run checks there: Secrets, VirtualMachines and
  VirtualMachineServices, created and deleted directly at the namespace endpoint.
- Guests reached `packages.broadcom.com` through the VPC's outbound path; the master installed Salt 3008.5 and answered
  its API over TLS; both minions reached the master on its private address; and a `LoadBalancer` service reached port
  8000 from outside the VPC.
- The `file` eauth backend with a SHA-256 digest, the `L@` target and the `@wheel` and `@runner` rights worked as
  configured: the run accepted keys, pinged, applied states and deleted keys with no other right.
- On Windows, the Sysprep path gave the guest its address and its first logon installed the minion, whose key reached the
  master.
- The cloud-init path did not, on the stock Windows Server 2022 image the runs used: VMware Tools ran and the guest held
  link-local addresses only, so nothing in the image applied the network configuration the VM Service supplied.

Not exercised: a Windows image built with Cloudbase-Init, a guest that cannot reach the package location (an internal
mirror), a key fingerprint compared before acceptance, and a run that reaches any of its time limits other than the
Windows address.

## Reading the record

`guestcfg.json` is written after every `run --execute`, success or failure, with every estate name replaced by a
placeholder and refused if a secret or an estate value survives. `steps` carries each step's result, `created` what the
run made by kind and role, `teardown` what was removed and `residue`, `outcome` and `failure` how the run ended, and
`windowsBootstrapPath` which Windows path it took. `expected-output.md` holds the three proof runs' output.

## Sources

Salt's [Linux (DEB) install](https://docs.saltproject.io/salt/install-guide/en/latest/topics/install-by-operating-system/linux-deb.html) and
[Windows install](https://docs.saltproject.io/salt/install-guide/en/latest/topics/install-by-operating-system/windows.html) guides,
[master configuration reference](https://docs.saltproject.io/en/latest/ref/configuration/master.html),
[rest_cherrypy](https://docs.saltproject.io/en/latest/ref/netapi/all/salt.netapi.rest_cherrypy.html),
[External Authentication](https://docs.saltproject.io/en/latest/topics/eauth/index.html),
[the file auth module](https://docs.saltproject.io/en/latest/ref/auth/all/salt.auth.file.html),
[the wheel key module](https://docs.saltproject.io/en/latest/ref/wheel/all/salt.wheel.key.html) and
[compound matchers](https://docs.saltproject.io/en/latest/topics/targeting/compound.html). Cloudbase-Init's
[userdata](https://cloudbase-init.readthedocs.io/en/latest/userdata.html) and
[services](https://cloudbase-init.readthedocs.io/en/latest/services.html) pages. The VM Operator project's
[guest customization page](https://vm-operator.readthedocs.io/en/stable/concepts/workloads/guest/) for the Cloud-Init and raw Sysprep shapes.
