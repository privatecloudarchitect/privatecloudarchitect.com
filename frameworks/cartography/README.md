# Cartography starter estate: the supervisor lens

The adoptable slice behind the discovery-and-naming chapters. Where the tuning estate
(`frameworks/wtpc/`) governs workloads by posture, this slice earns the classification that
membership depends on: it reads the labels your Supervisor workloads already declare, proposes
durable tags with confidence and evidence attached, holds every proposal for your ratification,
and writes only what you approve, on the vCenter-native tag plane, with every write verified
against the source of truth.

Proven by a live round trip on the reference estate before publication, on exactly these bytes;
the run date and shape are recorded in the companion build records.

## The provenance rule the whole slice enforces

Discovery observes; it never declares intent. The four axes it writes are discovery-owned:

| recommendation | concept | what it is |
|---|---|---|
| `app` | `app` | the application the VM declares it belongs to (open registry) |
| `tier` | `app-layer` | presentation / logic / data, derived only from unambiguous components |
| `function` | `function` | the governance axis the tuning framework matches on; ratified, never guessed |
| `env` | `env-observed` | the environment observed from the namespace name; your declared `env` axis is never written |

Ambiguity is surfaced, not resolved: an unmapped component or a silent VM yields a flagged
proposal for you to classify, and the closed component map never grows by guesswork.

## Dependencies and environment

Python 3 plus exactly `PyYAML`. Two planes, both from the environment:

```bash
# VCF Automation - the Consumption Interface reads (org session, the access-control chapter's flow)
export VCFA_HOST=<vcfa-fqdn> VCFA_ORG=<org> VCFA_USER=<user> VCFA_PASSWORD=<password>
# vCenter - the tag planes (define, assign, verify)
export VCENTER_HOST=<vcenter-fqdn> VCENTER_USERNAME=<sso-user> VCENTER_PASSWORD=<password>
export VCFA_INSECURE=1     # only on a self-signed lab CA
# optional: a least-privilege assign identity for Supervisor-managed VM classes
export VCENTER_TAGAUTH_USERNAME=<user> VCENTER_TAGAUTH_PASSWORD=<password>
```

If your estate namespaces its category names, edit `taxonomy.yaml` (or point
`CARTOGRAPHY_TAXONOMY` at an alternate copy); scripts resolve concepts through it and are never
edited.

## The recipe

```bash
python3 classify_supervisor.py                       # read + classify; summary only, nothing written
python3 classify_supervisor.py --export recs.json    # also write the ratification queue
$EDITOR recs.json                                    # review; the file IS the queue
python3 writeback_tags.py --recommendations recs.json --approve recommended             # dry-run
python3 writeback_tags.py --recommendations recs.json --approve recommended --execute
```

`--approve recommended` takes only the safe-to-approve subset (declared apps, cluster nodes,
unambiguous components); `--approve-file` picks an explicit `vm:category` list; `env` proposals
are always flagged for confirmation and so never ride `recommended`. Every executed attach is
read back from vCenter and the run fails loud if a tag did not land, which usually means the
assign identity cannot bind Supervisor-managed VM classes: re-run with
`--actuate-as-tag-authority`.

The handoff this slice exists for: once `function` (and your declared `env` and `sla`) are on a
workload, the tuning estate's posture groups absorb it on the next membership re-resolution, with
no further wiring.

## The offline self-test

`python3 classify_supervisor.py --self-test` classifies the shipped fixture
(`fixtures/supervisor-vms.json`, nine VMs covering every classifier branch) and compares the
result against the golden queue (`fixtures/expected-recommendations.json`). The same two
classifiers were proven field-identical to the reference implementation over the same fixture
before publication.

## What this slice does not carry (yet)

The flow lens (east-west traffic analysis, shared-services extraction, boundary detection, and
the arbitration that triangulates lenses) is a later slice of the same framework; it publishes
when its own round trip does. Nothing in this slice depends on it, and everything this slice
writes is exactly what that lens will corroborate.
