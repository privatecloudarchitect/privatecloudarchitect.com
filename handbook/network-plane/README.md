# The network plane, read from your own estate

Companion to the chapter
([privatecloudarchitect.com/handbook/network-plane](https://privatecloudarchitect.com/handbook/network-plane)):
one read-only script that asks the networking plane to describe itself, and writes two records the chapter's
plates render.

| File | What it is |
|---|---|
| `network.py` | Read-only. The networking API groups and every kind with its scope, declared verbs and instance count; the chain object by object, then walked outward from each VPC's subnets; the subnets and their access modes; the security strategies the platform ships, the strategy each attached profile carries, and the region's networking capabilities; and the translation rule that carries private space outward. |
| `network-model.json` | The catalog held as families, the access modes with the platform's own description of each, the strategies with their rule templates, the profiles with the strategies each carries, the attached one with its creation time, and the region's capabilities. |
| `chain.json` | The chain: IP blocks with their visibility, the connectivity profile, the VPC, both attachments, the gateway connection, the subnets, and the outbound translation. |
| `overlay.py` | Read-only, with a provider credential: what the provider runs above the gateway connection, the last object `network.py` can read. The Tier-0 gateways with their HA mode and edge clusters, each gateway connection and how many transit gateways attach to it, per NSX project its transit gateway, the connection that gateway uses (or none), its connectivity profile and its VPCs, the IP blocks by visibility, and with vCenter settings the zones and the cluster each holds. Every name is a label. |
| `overlay.json` | That record from the reference estate's workload domain, 2026-10-22. |
| `expected-output.md` | What both scripts printed on the reference estate: `network.py` with `--publishable`, and `overlay.py`. |
| `records/network-model-vcf-9.1.json` | The catalog record of the 9.1 run of 2026-09-21, as that run wrote it; the chapter computes what the upgrade added from it. |

## Run it

```bash
export VCFA_HOST=<automation-fqdn> VCFA_ORG=<org> VCFA_USER=<account>
( umask 077; mkdir -p ~/.vcf && cat > ~/.vcf/vcfa-password )   # paste your password, then Ctrl-D
export VCFA_PASSWORD_FILE=~/.vcf/vcfa-password             # mode 0600; or VCFA_REFRESH_TOKEN_FILE
export TLS_VERIFY=false                                    # only on a self-signed lab CA

python3 network.py                 # your own ranges on screen
python3 network.py --publishable   # documentation ranges on screen, as the records carry them
```

The sign-in is a session login as `<account>@<org>`, or a refresh token minted for the organization in a file of
mode 0600. A secret file open to group or other is refused before it is read. Every list is read to its last
page, and a list the platform refuses ends the run rather than reading as empty. Exit codes: 0 read; 2 a call
failed or the sign-in was refused; 5 an unknown argument.

## Above the gateway connection: overlay.py

```bash
export NSX_HOST=<nsx-manager-fqdn>
export NSX_USER=<provider-user> NSX_PASSWORD_FILE=~/.secrets/nsx           # mode 0600; or NSX_TOKEN_FILE, a bearer
export VC_HOST=<vcenter-fqdn> VC_USER=<sso-user> VC_PASSWORD_FILE=~/.secrets/vc   # optional: the zones
export TLS_VERIFY=false
python3 overlay.py --project <your NSX project id or display name>; echo "exit $?"
```

A tenant cannot run this: it reads the provider's side of the fabric, which no organization credential reaches. Ask
the provider to run it once and record two lines of its output beside your network design: which gateway connection
your project's transit gateway attaches to, and how many transit gateways share it. Exit codes: 0 read; 2 a setting or
argument is missing, or a secret file is open to group or other; 3 a sign-in or a read failed; 4 the record refused to
write because a name survived.

## The one question to run it for

Most of what this prints is orientation. One line is not:

```
     ATTACHED: the VPC's profile carries <strategy>
```

The platform ships five named isolation strategies, one of them `none`, and marks the security profile that
carries `none` as its default. A VPC arrives with that default profile attached: on the reference estate the record shows the
security profile attachment created in the same second as the VPC. So a VPC that nobody has thought about runs the `none`
strategy, and an estate that deliberately runs an open posture looks identical to one that never decided. That
line tells you which strategy is attached; only a recorded decision tells you whether anyone chose it.

If it reports `none`, that is not a fault. It is the answer to a question worth having asked, and attaching the
named strategy that matches your actual intent is what lets the estate answer it next time without running this
script.

## Scope, stated plainly

- Read-only, under one organization's bearer. The records hold what that organization can see, which is the
  tenant's view: a provider sees every organization and can write the kinds a tenant cannot.
- The verbs recorded are what the interface declares for a kind, not what your role allows. The group declares
  read and write as separate kinds, and a tenant bearer is refused on the write ones.
- The families are a reading aid, not the platform's taxonomy. Nothing enforces them. If a kind appears
  that the grouping does not recognize, the script prints it, which is the prompt to re-read the catalog rather
  than a fault.
- Addresses in the records are one estate's arbitrary choices. The structure is the lesson: which block carries
  which visibility, which one the connectivity profile assigns to which purpose, and what the translation rule
  maps onto.
- Every organization name is replaced by a stable placeholder, and the script refuses to write a record in
  which one survived. That check earned its keep on the first run: an IP block's name appears not only as its
  own name but as a value inside the connectivity profile and the gateway connection, and the first version
  scrubbed only the former.
