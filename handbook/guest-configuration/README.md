# Guest configuration with Salt

Companion to the handbook's [guest configuration chapter](https://privatecloudarchitect.com/handbook/guest-configuration), extra credit that nothing later in the handbook depends on.
Stage 02 of the template series ends with a machine that configures itself once, at first boot. This folder holds what
keeps that guest configured afterwards, on the free, community-driven Salt Project's path:

| What | Where |
|---|---|
| `guestcfg.py` | Stands up an independent Salt master, a Linux minion and a Windows minion on the VM Service, directly at the namespace endpoint or through VCF Automation blueprints, walks the guest-configuration lifecycle, removes every object it made, and writes a scrubbed record. Standard library; no token, password or private key is printed or written. |
| `states/guestcfg/` | The three small Salt states a run applies: `init.sls`, one managed file for Linux and Windows; `drift.sls`, the drift for step 6; and `probe.sls`, reads that change nothing (the minion's own public key and its fingerprints, the directory it keeps its key pair in, and on Windows the signed-in sessions). |
| `templates/02x-vm-salt-minion/` | The same shapes for readers. To apply by hand: `salt-master.vm.yaml`, `salt-minion-linux.vm.yaml`, `salt-minion-windows-sysprep.vm.yaml` (the default Windows path) and `salt-minion-windows.vm.yaml` (cloud-init, for an image built with Cloudbase-Init), with `<REPLACE_ME-...>` placeholders. As VCF Automation blueprints in stage 02's shape: `salt-master.blueprint.yaml`, `salt-minion-linux.blueprint.yaml` and `salt-minion-windows-sysprep.blueprint.yaml`, each taking inputs. All densely commented, and a test holds each to what the run renders. They sit in this folder, beside the script, because the template series' folder is enumerated and pinned at six stages: this branch does not change that count. |
| `guestcfg.json` | The record of the complete run directly at the namespace endpoint on the reference estate, 2026-11-11, with a key generated on the master for the Linux minion and the source ranges read; every estate value a placeholder. |
| `expected-output.md` | What the script printed: the two complete runs of 2026-11-11 (directly at the namespace endpoint, and through the three blueprints), then two runs of an earlier revision, 2026-11-10. |
| `records/` | Each of those runs' records under its date: the two complete runs of 2026-11-11, and from 2026-11-10 the cloud-init path on Windows and the Windows name refused on the Sysprep path. |

**Which Salt.** This is Salt Project, the free community tool, run by you, on your own master. It is not VMware Salt
(a licensed VCF Advanced Service) and it is not the Salt that VCF runs for its own components, which is not a master
for your workloads. Nothing later in the handbook depends on this track.

**Provenance:** run on VCF Automation 9.1.1 under a session login, in throwaway namespaces created for the runs
([`expected-output.md`](expected-output.md)). On 2026-11-11 the second proof completed every step twice: through VCF
Automation from the three blueprints as they stood at the repository's commit `108782b3` (run A5; since then, in
`salt-minion-linux.blueprint.yaml` the deletion of the seeded private key's copy moved before anything in the install can
exit; comments changed, as did the description of the master blueprint's address output), and directly at the namespace
endpoint with a key generated on the master for the Linux minion and the load balancer's source ranges read (run B,
[`guestcfg.json`](guestcfg.json)). Runs A1 to A3 that day, through VCF Automation, stopped at the probes when the
minion's and the master's fingerprints of the same key differed, which is how Salt 3008.5's two fingerprints were found;
each tore down cleanly. On 2026-11-10, an earlier revision completed with Sysprep for Windows after two runs that are
kept in [`records/`](records/): the cloud-init path on Windows, and the Windows name refused on the Sysprep path. Each
run's teardown removed everything it made and read the namespace back with nothing left.

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

Optional settings, each described in `--help`: `GUESTCFG_PROJECT`, `GUESTCFG_VIA` (`supervisor` or `automation`),
`GUESTCFG_LINUX_IMAGE`, `GUESTCFG_WINDOWS_IMAGE`, `GUESTCFG_VM_CLASS`, `GUESTCFG_WINDOWS_VM_CLASS`,
`GUESTCFG_STORAGE_CLASS`, `GUESTCFG_MIN_FREE_GIB`, `GUESTCFG_WINDOWS_BOOTSTRAP` (`cloudinit` or `sysprep`),
`GUESTCFG_KEYS` (`accept` or `preseed`), `GUESTCFG_API_SOURCE_RANGES`, `GUESTCFG_PROVE_SOURCE_RANGES`,
`GUESTCFG_RUNNER_ADDRESS`, `GUESTCFG_RUN_ID`, `OUT_DIR`. The sign-in is the same session login or organization refresh
token the other companions use; a secret file open to group or other is refused before it is read.

The same run through VCF Automation, from the three blueprints, and the supervisor path with the two proofs it carries:

```bash
export GUESTCFG_VIA=automation GUESTCFG_PROJECT=<the-project-holding-the-namespace>
export GUESTCFG_API_SOURCE_RANGES=<your-runner-address>/32   # who may reach the API's load balancer
python3 guestcfg.py run --dry-run       # the blueprints, deployments and objects a run would make
python3 guestcfg.py run --execute
python3 guestcfg.py teardown --execute  # with the same GUESTCFG_VIA and GUESTCFG_PROJECT

unset GUESTCFG_VIA
export GUESTCFG_PROVE_SOURCE_RANGES=1 GUESTCFG_RUNNER_ADDRESS=<your-runner-address> GUESTCFG_KEYS=preseed
python3 guestcfg.py run --execute
```

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
| 4 | Accepts exactly the two expected minion ids and leaves any other pending key unaccepted, reporting how many; stops if a second key appears under an expected id (denied or rejected) | key trust by identity |
| 5 | Pings, reads grains, applies one state to each, then applies it again | the state works and the second apply changes nothing |
| probes | Applies `guestcfg.probe` to each minion: its own public key, decoded, must be the one the master holds for its id (wheel `key.print`); both fingerprints and the minion's `pki_dir` are recorded, and on Windows the signed-in sessions; a second key under an expected id is read for again | the two copies of each key agree, a consistency read and not a trust check (below); the Sysprep first logon leaves no session signed in |
| 6 | Changes the managed file; `test=True` names it; an apply restores it | drift is named, then corrected |
| 7 | Deletes the minion keys, then the machines, then the master and secrets | the retirement order |
| 8 | Reads the namespace back | no residue |

**Objects a run creates** on the supervisor path, all in the namespace `GUESTCFG_NAMESPACE` names, each labelled
`handbook-guestcfg-run=<run>`: four `Secret` objects (`<prefix>-api-access`, `<prefix>-master-bootstrap`,
`<prefix>-linux-bootstrap`, `<prefix>-windows-bootstrap`), three `VirtualMachine` objects (`<prefix>-master`,
`<prefix>-linux`, `gc-<run>-win`) and one `VirtualMachineService` (`<prefix>-api`), where `<prefix>` is `guestcfg-<run>`
and `<run>` is six hexadecimal characters generated for the run. `run --dry-run` lists exactly these before any is made.
Any failure runs the teardown before the script exits, and `teardown --execute` can repeat that at any time; both delete
only what carries the run's label, read back by label afterwards.

**Through VCF Automation** (`GUESTCFG_VIA=automation`, with `GUESTCFG_PROJECT` naming the project), steps 2 and 3 change
and nothing else does. The run creates the three blueprints in the project from the files beside it exactly as written,
named `<prefix>-salt-master`, `<prefix>-salt-minion-linux` and `<prefix>-salt-minion-windows-sysprep`; validates each,
stopping on any error before anything is deployed; requests the master's deployment and waits for `CREATE_SUCCESSFUL`
(`CREATE_FAILED` stops the run with the deployment's own message); reads the master's address from the namespace; and
requests the two minion deployments with it. The deployments make the objects, labelled with the run and with
`app.kubernetes.io/managed-by: vcf-automation`; the run itself writes nothing at the namespace endpoint. Its teardown
deletes the minion deployments, then the master's, each by a `Deployment.Delete` request on the deployment, never the
machines underneath it, waits for each to be gone, deletes the blueprints, and reads back the namespace by label and the
project's deployments and blueprints by the run's names. A teardown on the supervisor path refuses to delete an object a
deployment made, and says to set `GUESTCFG_VIA=automation`. The automation path takes the Sysprep blueprint for Windows.

## Reach: how a script outside the VPC talks to a master inside it

The master sits on the namespace's private VPC network and the script runs from somewhere else. The Salt API therefore
needs a way in, and it gets the narrowest one that does the job: the stage 03 load-balancer shape, one
`VirtualMachineService` of type `LoadBalancer`, port 8000 only, selecting the master, created after the master is up and
deleted first in the teardown. Nothing else about the master is exposed.

`GUESTCFG_API_SOURCE_RANGES` narrows who may reach it, as the load balancer's `loadBalancerSourceRanges`, and the run
reads the field back once the API answers. VM Operator's v1alpha5 reference says of the field "This field will be
ignored if the provider does not support the feature.", so whether a given load balancer enforces it is a question for
a run: `GUESTCFG_PROVE_SOURCE_RANGES=1` patches the ranges, once the API answers, to `192.0.2.0/24` (TEST-NET-1, which no
runner is in), then to `0.0.0.0/0`, then to `GUESTCFG_RUNNER_ADDRESS/32` when it is set, reads after each whether the
API answers from where the script runs (a refused or timed-out connection is "did not answer"), restores the original
ranges and waits for the API to answer again. It records each outcome with the wait used; what it finds never fails the
run, and a refused patch does. The automation path does not patch: there the load balancer belongs to a deployment.

What the runs found, on VCF 9.1.1: a one-entry list reached the object as given (runs A4 and A5 set `0.0.0.0/0`
through the master blueprint's array input and read it back unchanged; a longer list was not run), and on the load
balancer run B used, the field did not restrict a client (run B: with `192.0.2.0/24` the API kept answering the runner for the whole three-minute read, as with `0.0.0.0/0` and
with the runner's own address). A range on the object is not a control until your own run shows it holds: limit port
8000 at your network's edge, and delete the load balancer when the API is no longer needed.

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

The automatic first logon is an Administrator session, and a second first-logon command (Order 2) signs it out with
`shutdown.exe /l`. Microsoft's page for a first-logon command's Order says these commands "are now started at the same
time, and no longer wait for the previous command to finish", so the sign-out does not trust its Order: it waits until
the `salt-minion` service runs and the installer has exited, 60 minutes at most, and then signs out. The probe's `quser`
read records whether any session is still signed in, judged on what `quser` prints: in runs A5 and B it exited 0 with
nothing on stdout and `No User exists for *` on stderr, no user signed in, so neither the exit code nor an empty stdout
alone is evidence of it.

`GUESTCFG_WINDOWS_BOOTSTRAP=cloudinit` is for an image built with Cloudbase-Init: the Secret's user-data is a
`#ps1_sysnative` PowerShell script running the same install. On the stock Windows Server 2022 image the proof runs used
it left the guest with link-local addresses only and the run failed at its limit ([`expected-output.md`](expected-output.md)).

Which path a run tried is in its output and record. A Windows minion whose key does not reach the master within the
Windows limit is a timed failure that names the path tried, says which setting selects the other one, and tears down.

**Timeouts are stated, and progress is reported.** A first boot is the long wait. The limits in `LIMITS` in `guestcfg.py`:
15 minutes for a machine to be PoweredOn with an address (30 for Windows), 15 for the load balancer's address, 30 for the
master's first boot to answer on its API, 30 for the Linux minion's key, 60 for the Windows minion's key, 20 for one Salt
job, and 20 for a machine's delete; on the automation path, 45 for a deployment to finish creating and 30 for one to be
deleted; and 3 for each source-range setting to be read. The script prints a progress line at regular intervals while it
waits.

## Trust: accept the ones you expect

The master never accepts a key on its own. The run lists pending keys and accepts exactly the two minion ids it expects
(the machines' own names, `guestcfg-<run>-linux` and `gc-<run>-win`; a Windows machine's name is its host name, and on the Sysprep path VM Operator refuses one over 15 characters). A third machine cannot be created in this
proof, so "refuse a third name" is implemented as: accept exactly the two expected ids, leave any other pending key
unaccepted, and report how many there were. A third name is never accepted, and a stray key already in the accepted list
stops the run. So does a second key under an expected id, which the master puts in `minions_denied` (salt-key's page:
"This occurs when a minion has a duplicate ID"), or a rejected one; the run reads for both at the key step and again at
the probes.

Before acceptance the run has the master's view of a pending key and no second source to check it against, so
acceptance is by exact expected id, which trusts the id the minion declares. By hand, do better: compare the key itself,
out of band, before you accept it. Print the pending key on the master with `sudo salt-key -p <minion-id>`, read the
minion's own `minion.pub` in the directory its `pki_dir` names (`/etc/salt/pki/minion` on Linux, readable by root,
`C:\ProgramData\Salt Project\Salt\conf\pki\minion` on Windows, each read from a 3008.5 minion installed as this
folder installs it), and accept with `sudo salt-key -a <minion-id>` only when the lines between `BEGIN PUBLIC KEY` and
`END PUBLIC KEY` are the same. That needs a way into both machines that is not Salt, a console or SSH with a login given
at create: the master and Linux minion templates here carry none, so add stage 02's operator user, with `sudo`, if you
mean to compare by hand; on the Sysprep path the Administrator password you give is the Windows login. How to reach a VM
Service machine's console on 9.1.1 is not established here, and no run compared by hand. Where it fits, a key generated
on the master (below) needs no comparison.

Do not compare fingerprints for this on Salt 3008.5. `salt-key -f` on the master and `salt-call --local key.finger` on
the minion hash different text: the minion's `key.finger` hashes the lines inside `minion.pub`, header and footer
dropped, and the master's hashes the whole PEM it holds in its key cache (`salt/utils/crypt.py` `pem_finger`,
`salt/key.py` `Key.finger` and `salt/modules/key.py`, read from the `salt-common` 3008.5 package). The two
fingerprints differed for every minion that made its own key: in run A1 on Linux only, where it stopped, and in runs A2
to A5 and B on Linux and on Windows. Runs A3 to A5 and B, which read the key itself as well, found the same key in the
same line layout at both ends.

After acceptance the run reads the key's two copies: the probe state reads each minion's own `minion.pub` and the run
decodes it beside the public key the master holds for the id (wheel `key.print`); a different key stops the run. Both
fingerprints are recorded beside it and neither decides. The API account holds `key.print` and `key.finger` for that,
and nothing that writes. This is a consistency read, not a trust check: the probe reaches the minion over the channel
the accepted key authenticates, so a second machine that claimed the id first would answer with its own key and the two
copies would still agree. The read for a second key under the id, above, is what can show such a machine.

The stronger form is a key generated on the master before first boot with the wheel function `key.gen_accept`,
delivered to the minion in its bootstrap Secret; whoever can read that Secret then holds the minion's identity.
`GUESTCFG_KEYS=preseed` exercises it on the supervisor path: once the API answers and before any minion exists, the run
calls `key.gen_accept` for the Linux minion (and grants the API account that one function more), reads the fingerprint
the master holds for it, and writes the pair, one line of base64 each, into the minion's cloud-config, where the install
puts it in `/etc/salt/pki/minion/` before the package first starts the minion, the files and the order Salt's page on
preseeding gives. Step 4 then requires the minion to answer a ping, never to have been pending (or denied), and its
accepted key to be the generated one; in run B it was never pending and answered a ping. The run never prints or
records the private key: it holds it in memory and writes it only to the minion's bootstrap Secret, which the teardown
deletes, and the install deletes the copy beside its script before anything in it can exit. The Windows minion is not
seeded, the companion's choice: Microsoft's reference holds one first-logon `CommandLine` to "a maximum length of 1024
characters", a PEM private key is longer, and splitting it across commands was neither built nor run. So it keeps
acceptance by exact id. Run B's record, written before this wording, gives an earlier reason in
`steps.keysGenerated.windowsNotSeededBecause`.

## What the runs confirmed, and what they did not

Each behavior below held on VCF Automation 9.1.1, on 2026-11-10 or in the second proof of 2026-11-11; the runs' own
output, with their timings, is in [`expected-output.md`](expected-output.md), and that is the place to compare your run
with.

- A session login that created the namespace held every right the run checks there: Secrets, VirtualMachines and
  VirtualMachineServices, created, patched and deleted directly at the namespace endpoint.
- Guests reached `packages.broadcom.com` through the VPC's outbound path; the master installed Salt 3008.5 and answered
  its API over TLS; both minions reached the master on its private address; and a `LoadBalancer` service reached port
  8000 from outside the VPC.
- `salt-common` 3008.5 carries the CherryPy that `salt-api` serves with: the master installs nothing from the Python
  Package Index, and the API answered in every run of the second proof. (CherryPy 18.10.0 in the package's own Python,
  read from the amd64 package fetched from Broadcom's package location and checked against the repository index's
  SHA-256.)
- The `file` eauth backend with a SHA-256 digest, the `L@` target and the `@wheel` and `@runner` rights worked as
  configured: the run accepted keys, generated one, pinged, applied states, read keys and deleted them with no other
  right.
- The three blueprints validated with no error, deployed through VCF Automation as the run read them at commit
  `108782b3`, the master's first and then the two minions' with its address as an input, and the teardown deleted the
  minions' keys, then the deployments, the minions' first, then the master's, then the blueprints. The master
  blueprint's one-entry array input, `["0.0.0.0/0"]`, reached the `VirtualMachineService`'s `loadBalancerSourceRanges`
  unchanged in runs A4 and A5; a longer list was not run.
- On the load balancer run B used, a source range that excluded the runner did not stop it (Reach, above).
- A key generated on the master and seeded through the Linux minion's cloud-config was never pending, and the minion
  answered a ping.
- The minion's and the master's fingerprints of the same key differ on Salt 3008.5, and the key itself matched at both
  ends (Trust, above).
- On Windows, the Sysprep path gave the guest its address, its first logon installed the minion, whose key reached the
  master, and the first logon was signed out: `quser` read no user signed in.
- The cloud-init path did not give the guest its address, on the stock Windows Server 2022 image the runs used: VMware
  Tools ran and the guest held link-local addresses only, so nothing in the image applied the network configuration the
  VM Service supplied.

Not exercised: a Windows image built with Cloudbase-Init, a guest that cannot reach the package location (an internal
mirror), a key compared by hand, out of band, before acceptance (the run reads the two copies after acceptance, which is
not a trust check), a key seeded into a Windows minion, a master's API grant grown as minions join, and a
run that reaches any of its time limits other than the Windows address.

## Reading the record

`guestcfg.json` is written after every `run --execute`, success or failure, with every estate name replaced by a
placeholder and refused if a secret or an estate value survives. `steps` carries each step's result, `created` what the
run made by kind and role, `teardown` what was removed and `residue`, `outcome` and `failure` how the run ended, and
`windowsBootstrapPath` which Windows path it took. `via`, `keys` and `sourceRanges` say which path, key mode and ranges
the run used (a range is a placeholder unless it is `0.0.0.0/0` or `192.0.2.0/24`); `steps.2.blueprints` and the
deployment timings appear on the automation path, `steps.2.sourceRanges` holds the ranges read back,
`steps.sourceRanges` each patched setting's outcome, `steps.keysGenerated` and `steps.4.generatedOnTheMaster` the
preseed checks, and `steps.probes` the key comparison (`sameKey`), both fingerprints beside it, the minion's `pki_dir`
and the Windows session read, never a user name. `expected-output.md` holds the runs' output, and `records/` each run's
record under its date.

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

For the second proof, each read whole on 2026-11-11: Salt's
[salt-key page](https://docs.saltproject.io/en/latest/ref/cli/salt-key.html) (`-p`: "Print the specified public key."),
its [preseeding page](https://docs.saltproject.io/en/latest/topics/tutorials/preseed_key.html) (a Linux minion's key files,
placed before the minion first starts), its
[minion configuration reference](https://docs.saltproject.io/en/latest/ref/configuration/minion.html) (`pki_dir`), the
[cmd states](https://docs.saltproject.io/en/latest/ref/states/all/salt.states.cmd.html) (`success_retcodes`) and the
[test states](https://docs.saltproject.io/en/latest/ref/states/all/salt.states.test.html) (`show_notification`).
Microsoft's unattend pages for a first-logon command's
[Order](https://learn.microsoft.com/en-us/windows-hardware/customize/desktop/unattend/microsoft-windows-shell-setup-firstlogoncommands-synchronouscommand-order)
and [CommandLine](https://learn.microsoft.com/en-us/windows-hardware/customize/desktop/unattend/microsoft-windows-shell-setup-firstlogoncommands-synchronouscommand-commandline)
(at most 1024 characters), and its
[shutdown](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/shutdown) command (`/l` signs
the current user out). The VM Operator project's
[v1alpha5 reference](https://vm-operator.readthedocs.io/en/stable/ref/api/v1alpha5/) for `loadBalancerSourceRanges`.
