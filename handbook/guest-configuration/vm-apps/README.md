# Guest configuration on VM Apps: the same walkthrough, by difference

Your organization is VM Apps ([how to tell](../../day1-provisioning/vm-apps/README.md#which-one-is-yours)). This page
takes you through the walkthrough's eight pages in that dialect. Read each page there first: the ideas, the commands
on the master and the things that bite are the same, and they are taught once. This page says only what is different,
and shows what the proof printed where it differs.

The three blueprints here are the All Apps ones in the VM Apps dialect. Each machine's `cloudConfig` is rendered by
the harness's own renderer, so it is the All Apps machine's first boot with two changes, and a test holds each file to
that renderer:

| Blueprint | The machine | What it takes |
|---|---|---|
| [`salt-master.blueprint.yaml`](salt-master.blueprint.yaml) | `<app_name>-master`, Ubuntu 24.04, Salt 3008.5 master and API | placement (an image mapping, a flavor mapping, a network profile's tag), your SSH public key, the API's two minion ids, digest, certificate and key |
| [`salt-minion-linux.blueprint.yaml`](salt-minion-linux.blueprint.yaml) | `<app_name>-linux`, Ubuntu 24.04, Salt 3008.5 minion | placement, your SSH public key, the master's address, and optionally a key pair made on the master |
| [`salt-minion-windows.blueprint.yaml`](salt-minion-windows.blueprint.yaml) | `<app_name>-win`, Windows Server 2022, Salt 3008.5 minion | placement, the Administrator password, the master's address |

## What is different, and why

**No `kubectl`, no load balancer.** A VM Apps machine sits on a network your administrator routes, so the master's API
(8000) and SSH (22) answer at the master's own address, and the walkthrough's SSH front door is not needed. If your
workstation has no route to that network, work from a machine on it: the proof did, from a V02 machine on the same
network.

**A login on the master and the Linux minion, always.** On VM Apps these pages build only through the blueprints, so they
carry the `salt-operator` login the All Apps templates make optional. It takes your SSH public key and no password.

**The install survives the first boot's reboot.** vSphere's guest customization can reboot a VM Apps machine
during cloud-init's first boot, as it did on the image the proof used, and cloud-init never runs a once-per-instance
module again once it has started it (G-988). So the install is not a `runcmd`.
It runs as a per-boot script that does nothing once its marker exists, and it bounds every download. The install
itself is the All Apps one, unchanged.

**Windows is the organization's own Windows form.** `cloudConfig` is a MIME document whose one part,
`#ps1_sysnative`, Cloudbase-Init runs at first boot: it sets the Administrator's password from your input, then runs
the same PowerShell install as the All Apps paths. The Sysprep answer file's constraints, its field forms (G-971) and
its 1,024-character commands (G-983), do not apply here; the 15-character name does (G-970).

## Pages 00 and 01: before you start, and a master

What you need is page 00's list with VM Apps' nouns: a project you may deploy in, an Ubuntu 24.04 and a Windows Server
2022 image mapping, flavor mappings, the tag of a network profile whose network the three machines share, and outbound
reach from that network to `packages.broadcom.com` and to the Ubuntu image's package mirrors. Three reads give the values: `GET /iaas/api/images`,
`GET /iaas/api/flavors` and `GET /iaas/api/network-profiles`.

Make page 01's certificate and API password, then the master blueprint's three encoded inputs; its header gives the
commands. Request the master, with `<app_name>-linux` and `<app_name>-win` as the two minion ids. When the deployment
is `CREATE_SUCCESSFUL`, its `master_address` output is the address for everything else:

```bash
M=<master_address>
ssh salt-operator@$M 'salt-master --version; sudo salt-key -L'
curl -sS --cacert api.crt --resolve salt-master:8000:$M https://salt-master:8000/login \
  -H 'Accept: application/json' -d username=guestcfg-api -d eauth=file \
  --data-urlencode "password=$(cat api.password)"
```

What the master answered on the reference estate, 2026-11-12, once its deployment was `CREATE_SUCCESSFUL`: the
version and the key list, then the API's answer as the proof's script reduced it, to its account and its rights (the
full answer has page 01's form):

```
salt-master 3008.5 (Argon)
Accepted Keys:
Denied Keys:
Unaccepted Keys:
Rejected Keys:
eauth file user guestcfg-api
[{"@runner": ["jobs.lookup_jid"]}, {"@wheel": ["key.list_all", "key.accept", "key.delete", "key.finger", "key.print"]}, {"L@z2m-linux,z2m-win": ["test.ping", "grains.item", "state.apply"]}]
```

## Pages 02 to 04: one minion, its key, a state and drift

Request the Linux minion with the master's address as `salt_master_address`. Everything after that is page 02 to page
04 as written, with the machines' own addresses in place of `-J` through a front door:

```bash
L=<the minion's address>      # its deployment's sign_in output names it
ssh salt-operator@$M "sudo grep -v -- ----- /etc/salt/pki/master/minions_pre/<app_name>-linux | tr -d '\n' | sha256sum"
ssh salt-operator@$L "sudo grep -v -- ----- /etc/salt/pki/minion/minion.pub | tr -d '\n' | sha256sum"
```

What the proof printed, shortened: the two hashes, the accept's last line, the two applies and the drift named and
corrected, each apply to the lines that differ:

```
5cbc424279653e678638865b866062132a5120bd9c388fe8e802644abb80665e  -
5cbc424279653e678638865b866062132a5120bd9c388fe8e802644abb80665e  -
Key for minion z2m-linux accepted.
     Comment: File /etc/guestcfg/managed.conf updated
Succeeded: 1 (changed=1)
     Comment: File /etc/guestcfg/managed.conf is in the correct state
Succeeded: 1
      Result: None
     Comment: The file /etc/guestcfg/managed.conf is set to be changed
                  -managed-by: someone-else
                  +managed-by: salt
                  +baseline: guest-configuration
     Comment: File /etc/guestcfg/managed.conf updated
managed-by: salt
baseline: guest-configuration
```

Page 02's box on a ping sent right after the accept applies here: the proof's first ping, sent at once, missed.

## Page 05: a Windows minion

Request the Windows minion with the same master address and an Administrator password. Its first boot sets the
built-in Administrator's password from that input, enables the account, and installs the minion. Not `remoteAccess`:
on the image the proof used, the password `remoteAccess` carried was accepted by none of the accounts the proof
tried, Administrator, Admin and cloudbase-init (G-989).

Compare the key as page 05 does, with the minion's own half read where you can sign in as Administrator: RDP to its
address, open PowerShell as administrator, and run page 05's line. The proof had no RDP client, so it ran the same
line over WinRM, signed in as Administrator, from the machine on the network. Both are channels that are not Salt, and
both came before the accept:

```
-- master
69a823976080dbc4ae3e3963905332917860b53a536f565b6c2abb6745f879a5  -
-- minion, over WinRM as Administrator
z2m-win
z2m-win\administrator
69a823976080dbc4ae3e3963905332917860b53a536f565b6c2abb6745f879a5
Running
```

The master's hash; then, on the minion, its name, the account the line ran as, its hash, and the minion service's
state. The two hashes are equal. After the accept, the
proof read the same as page 05 (shortened):

```
z2m-win:
    True
z2m-win:
    ----------
    os_family:
        Windows
    saltversion:
        3008.5
     Comment: File C:\ProgramData\guestcfg\managed.conf updated
Succeeded: 1 (changed=1)
     Comment: File C:\ProgramData\guestcfg\managed.conf is in the correct state
Succeeded: 1
```

**A key that came back.** While these pages were proven, a Windows minion was rebuilt under the same id, and page 06's
box on a key that comes back happened here: the first machine re-offered its key before its delete finished, and the
new machine's key landed in `Denied Keys`.

## Page 06: retire through the deployments

Page 06's order, with VCF Automation doing the machine half: delete each key on the master by exact id, then delete
the minions' deployments, then the master's.

```
Key for minion z2m-linux deleted.
Key for minion z2m-win deleted.
Accepted Keys:
Denied Keys:
Unaccepted Keys:
Rejected Keys:
```

What the proof printed, shortened: the two keys deleted by id, then, after both minions' deployments were deleted, the
master's empty list. The master's deployment went last. Afterwards the project listed none of the proof's deployments
or blueprints, and none of the reference estate's vCenters held a machine from them.

## Page 07: on VM Apps the blueprints are the path

Page 07 turns the by-hand pages into blueprints. On VM Apps they already are: the three files here are what you import
as templates, release, and offer in your project's catalog. The proof deployed each through the API, a blueprint
created in the project and then a deployment request; the catalog form was not run. What page 07 says about inputs, encrypted secrets, a
master deployed once and minions that take its address, applies unchanged.

## Where this ends

VM Apps keeps a guest configured as well as All Apps does: the Salt practices are the same, and so is the master. What
VM Apps does not give you is the rest of the series. When your organization adds All Apps, the All Apps
[walkthrough](../README.md) is these pages without the differences, and the
[branch's last section](../../day1-provisioning/vm-apps/README.md#where-vm-apps-ends-moving-to-all-apps) maps each
VM Apps object to its All Apps form.
