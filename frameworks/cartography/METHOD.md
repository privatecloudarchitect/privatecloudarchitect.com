# The Application Cartography method

The discovery method behind the [Discovery and naming](https://privatecloudarchitect.com/handbook/cartography)
chapter series. This file is the map: the whole method on one page, marked with which parts run from this
repo today and which are taught on the site and ship next. The narrative teaching, with the live evidence,
lives in the chapters; this is the structure you can hold in your head.

> **You cannot tune by posture what you cannot name.** Application cartography is the upstream of every
> other framework: it earns the classification that tuning, micro-segmentation, capacity planning, and
> BCDR all assume you already have. Public cloud hands you a named, tagged estate and a scoreboard. A
> brownfield private cloud hands you a room of unlabeled machines and a tagging scheme nobody trusts.
> This method earns the map, and keeps it earned.

## Three principles

1. **Triangulate.** No single lens is sufficient. A flow shows that two machines talk, not what they
   are; a process banner names a service, not the application it serves; a security group records a
   prior team's intent, not today's reality. Confidence is agreement across independent lenses, never
   the word of one.
2. **Shared services first.** Extract the common services (DNS, directory, time, logging, and the VCF
   platform itself) before any boundary math. A shared service reached by everything, left in the graph,
   makes every application look adjacent to every other. Quarantine it first and the real boundaries
   resolve on their own.
3. **Classify, then govern.** Discovery is not a project that ends; it is a standing capability. A
   one-time map decays the moment an application team next deploys. The deliverable is not the diagram,
   it is the coverage number you drive to zero unclassified and hold there.

## The lenses

| Lens | Reads | Says | Certainty |
|---|---|---|---|
| **Flow** (VCF Operations for Networks) | east-west traffic: source, destination, port, volume | dependency edges and fan-in | traffic, not identity |
| **Process** (Operations Service Discovery) | listening services inside the guest | what an endpoint *is* | identity, where VMware Tools is current |
| **Metadata + security** (vCenter, NSX) | names, placement, groups, firewall rules | prior human intent | asserted, and often stale |
| **Declared** (Supervisor labels) | the app, tier, and function a Kubernetes-managed workload states about itself | an authoritative self-declaration | certain, where it exists |

The **flow lens** is the primary instrument: it is the only one that shows the real east-west
dependency graph, and it is the evidence for both boundaries and fan-in. The **declared lens** is the
cleanest to adopt first, because its source is authoritative rather than inferred. This repo ships both:
the supervisor lens at the root, and the flow lens's Phase 4-5 core in [`flow/`](flow/).

## The ten phases

| Phase | Goal | Primary lens | In this repo |
|---|---|---|---|
| 0 · Frame | decide the target taxonomy before you look at a single flow | a decision, ratified with the estate owner | `taxonomy.yaml` (the four discovery-owned axes) |
| 1 · Substrate | turn the lenses on, prove they flow, start the accumulation window | flow + process | operator step |
| 2 · Census | enumerate everything, so coverage has a denominator | inventory | operator step |
| 3 · Multi-modal | gather raw evidence from every lens, conclude nothing yet | all four | **the supervisor lens reads the declared column** |
| 4 · Shared services | quarantine high-fan-in common services before boundary math | flow + identity | **the flow lens, [`flow/`](flow/)** (port-only) |
| 5 · Boundaries + tiers | cluster the shared-service-free graph into apps, assign tiers | flow | **the flow lens, [`flow/`](flow/)** |
| 6 · Env + zone | overlay environment and security zone, orthogonal to identity | metadata + NSX | flow lens (next); the supervisor lens observes environment |
| 7 · Arbitrate | collapse the lenses into one confidence-scored classification per workload | all four | flow lens (next) |
| 8 · Persist | write the confident classifications back as durable, governed tags | the write | **the supervisor lens writes back today** |
| 9 · Govern | re-run on a cadence; drive the unclassified backlog to zero and hold | census delta | operator cadence |

Read the columns honestly: the supervisor lens covers the declared evidence of Phase 3 and the write-back
of Phase 8; the flow lens in [`flow/`](flow/) covers Phases 4 and 5, shared-services extraction and
boundary-plus-tier clustering, on port-only heuristics. Phases 6 and 7 (the environment and zone overlay,
and the arbitration that fuses the lenses) plus the flow lens's identity anchor live in the platform's
`pca vcf-opsnet` commands and are the next slice. Phases 0, 1, 2, and 9 are operator steps the method
frames but no tool performs for you.

## The target taxonomy

The full method produces the axes below. The supervisor lens writes only the four it can **observe**; the
rest come from the flow lens, from attestation, or from a human decision, and are never guessed.

| Axis | Values | Produced from | Supervisor lens writes it |
|---|---|---|---|
| `app` | the application identifier | flow clusters, naming, declared labels | yes, from the declared label |
| `tier` (app-layer) | presentation / logic / data | ports, process, declared labels | yes, from unambiguous components only |
| `function` | db / web / app / vdi / k8s / infra | ports, declared labels | yes, the axis the tuning framework governs on |
| `env-observed` | prod / stage / dev / test / dr / lab | subnet, naming, namespace | yes, the observed twin only, never your declared `env` |
| `zone` | dmz / internal / restricted | NSX segment, north-south exposure | no, the flow and security lenses |
| `shared-service` | dns / ad / ntp / backup / ... | fan-in analysis | no, the flow lens |
| `sla` | your business service tiers | business input, keyed off `app` + `env` | no, a human decision |
| `owner` | team or cost center | attestation, CMDB | no, attestation |

The provenance rule the whole method enforces: **discovery observes; it never declares intent.** That is
why the environment it writes is `env-observed` and not `env`: the namespace name is an observation, your
production designation is a decision, and the two are kept as separate axes so a tool can never overwrite
intent with a guess.

## What "done" looks like for one workload

```yaml
vm: storefront-web-01
app: storefront
tier: presentation
function: web
env-observed: prod
zone: dmz
sla: sla-2
owner: retail-platform
shared_service: null
confidence: high          # corroborated by a declared label plus flow and service evidence
basis: "declared app=storefront; flow community with storefront-db; discovered nginx; name stem agrees"
conflicts: []
```

A workload is cartographed when it carries that record **and** the record is defended by the Phase 9
cadence. The estate is cartographed when the unclassified backlog sits at zero and stays there, at which
point tuning, micro-segmentation, and capacity planning all inherit a map they can trust.

## Runnable today, and where to learn the rest

- **Run the supervisor lens** from this directory: see [`README.md`](README.md). It reads the labels your
  Supervisor workloads already declare, proposes durable tags held for your ratification, writes back only
  what you approve on the vCenter tag plane with read-back verification, and reverses cleanly with a scoped
  un-write. An offline `--self-test` reproduces a golden classification before you point it at an estate.
- **Learn the full method** on the site: [Application Cartography: discover before you tune](https://privatecloudarchitect.com/handbook/cartography),
  then [The supervisor lens: labels are declarations](https://privatecloudarchitect.com/handbook/cartography-supervisor),
  then [Tag governance: facts, intent, and who may write](https://privatecloudarchitect.com/handbook/cartography-governance).
- **Run the flow lens** from [`flow/`](flow/): see [`flow/README.md`](flow/README.md). It pulls the flows
  VCF Operations for Networks collects, quarantines the shared services by fan-in, and clusters the
  remaining VM-to-VM graph into tiered candidate applications, read-only, with its own offline
  `--self-test`. It carries Phases 4 and 5; the environment and zone overlay, the identity anchor, and the
  cross-lens arbitration (Phases 6 and 7) remain in the platform's `pca vcf-opsnet discover-*` commands.

Every claim on the site carries an evidence tier, defined on the [method page](https://privatecloudarchitect.com/method).
This repo is the `repo` tier: what you can run and read for yourself.
