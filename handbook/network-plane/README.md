# The network plane, read from your own estate

Companion to the chapter
([privatecloudarchitect.com/handbook/network-plane](https://privatecloudarchitect.com/handbook/network-plane)):
one read-only script that asks the networking plane to describe itself, and writes two records the chapter's
plates render.

| File | What it is |
|---|---|
| `network.py` | Read-only. The networking API groups and every kind with its scope, declared verbs and instance count; the chain object by object; the subnets and their access modes; the security strategies the platform ships and which one is attached to your VPC; and the translation rule that carries private space outward. |
| `network-model.json` | The catalog held as nine families, the access modes with the platform's own description of each, the strategies with their rule templates, and which profile is attached. |
| `chain.json` | The chain: IP blocks with their visibility, the connectivity profile, the VPC, both attachments, the gateway connection, the subnets, and the outbound translation. |
| `expected-output.md` | The transcript of one run. |

## Run it

```bash
export VCFA_HOST=<automation-fqdn> VCFA_ORG=<org>
export VCFA_REFRESH_TOKEN_FILE=/path/to/refresh-token      # mode 0600
export TLS_VERIFY=false                                    # only on a self-signed lab CA
export OUT_DIR=.

python3 network.py
```

## The one question to run it for

Most of what this prints is orientation. One line is not:

```
     ATTACHED: the VPC runs the <name> strategy
```

The platform ships five named isolation strategies and arrives with none of them attached, and it marks the
empty position as its own default. So a VPC that nobody has thought about has no strategy, and an estate that
deliberately runs an open posture looks identical to one that never decided. That line tells you which you are.

If it reports `none`, that is not a fault. It is the answer to a question worth having asked, and attaching the
named strategy that matches your actual intent is what lets the estate answer it next time without running this
script.

## Scope, stated plainly

- Read-only, under one organization's bearer. The records hold what that organization can see, which is the
  tenant's view: a provider sees every organization and can write the kinds a tenant cannot.
- The verbs recorded are what the interface declares for a kind, not what your role allows. The group declares
  read and write as separate kinds, and a tenant bearer is refused on the write ones.
- The nine families are a reading aid, not the platform's taxonomy. Nothing enforces them. If a kind appears
  that the grouping does not recognize, the script prints it, which is the prompt to re-read the catalog rather
  than a fault.
- Addresses in the records are one estate's arbitrary choices. The structure is the lesson: which block carries
  which visibility, which one the connectivity profile assigns to which purpose, and what the translation rule
  maps onto.
- Every organization name is replaced by a stable placeholder, and the script refuses to write a record in
  which one survived. That check earned its keep on the first run: an IP block's name appears not only as its
  own name but as a value inside the connectivity profile and the gateway connection, and the first version
  scrubbed only the former.
