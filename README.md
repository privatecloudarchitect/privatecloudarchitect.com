# privatecloudarchitect.com companion artifacts

Runnable reference artifacts behind the sheets at [privatecloudarchitect.com](https://privatecloudarchitect.com).
Artifacts arrive in two classes. A **harness** (`handbook/<sheet>/`) backs one published sheet:
it proves that sheet's claims on your estate, read-only or round-tripped, and leaves your estate
as it found it. A **framework estate** (`frameworks/<name>/`) backs a chapter series: it converges
desired state you intend to keep, and is versioned as a unit.

## The contract

Everything in this repo satisfies four rules before it is pushed:

1. **It backs a published sheet.** The map below names the sheet each directory belongs to.
2. **It was proven on a live VMware Cloud Foundation estate**, and each directory's README states
   the build and the date it was proven on.
3. **It is parameterized for your estate.** Environment variables and marked placeholders carry
   everything estate-specific; nothing here assumes the estate it was proven on.
4. **What ships is what ran.** The exact files here were re-run against a live estate before
   publication, not sanitized afterward and assumed equivalent.

Framework estates carry five further clauses:

5. **Desired state is the interface.** You edit declarative files; converge scripts are the only
   mutation path, idempotent, adopting existing objects by their stable names.
6. **Teardown is scoped.** Every converge has a teardown that removes exactly what converge
   created, and nothing else.
7. **Dependencies are declared.** Harnesses are stdlib Python only. A framework estate may declare
   a minimal dependency list in its README, and nothing outside that list.
8. **The reference estate is one usage.** Nothing estate-specific lives in the universal layer;
   your estate enters through the declared parameters, never through edits to shared logic.
9. **Round-tripped before publication.** Every slice was converged, verified, and torn down live
   on the exact bytes published here.

## The map

| Directory | Backs | What it is |
|---|---|---|
| [`handbook/isolation-design/`](handbook/isolation-design/) | [The isolation design, assembled](https://privatecloudarchitect.com/handbook/isolation-design) and [field note 01](https://privatecloudarchitect.com/notes/vcfa-access-control-three-factors) | Declarative manifests plus a verifier that proves per-user isolation on your build |
| [`handbook/project-vending/`](handbook/project-vending/) | [Field note 03](https://privatecloudarchitect.com/notes/vcfa-project-vending) and the [tenant self-service playbook](https://privatecloudarchitect.com/playbooks/tenant-self-service-isolation) | A standard-library API client plus the three-call project-and-namespace vend, the catalogs-role setup, and a tenant scope check, all by API on your build |
| [`handbook/day2-governance/`](handbook/day2-governance/) | [Day-2 governance](https://privatecloudarchitect.com/handbook/day2-governance) | The two-policy HARD change as importable JSON, named per the sheet's convention |
| [`handbook/memory-tiering/`](handbook/memory-tiering/) | [Memory tiering candidacy](https://privatecloudarchitect.com/handbook/memory-tiering) | The lens end to end: the metrics (formulas plus id-preserving package), the three views, and the readiness dashboard |
| [`handbook/wtpc/`](handbook/wtpc/) | [The Well-Tuned Private Cloud](https://privatecloudarchitect.com/handbook/wtpc) | The starter catalog's three posture records, machine-readable and instance-independent |
| [`handbook/microsegmentation/`](handbook/microsegmentation/) | [Microsegmentation](https://privatecloudarchitect.com/handbook/microsegmentation) | The security-policy round trip: group and policy manifests plus the disabled-first enablement run |
| [`handbook/ops-estate/`](handbook/ops-estate/) | [The operations estate](https://privatecloudarchitect.com/handbook/ops-estate) | Desired-state converge for owned Operations content, with scoped teardown |
| [`handbook/capacity-forecasting/`](handbook/capacity-forecasting/) | [Capacity forecasting](https://privatecloudarchitect.com/handbook/capacity-forecasting) | The commitment-adjusted runway read, with the config-parity gate that refuses to project against a drifted ruler |
| [`handbook/hardening-audit/`](handbook/hardening-audit/) | [Hardening and audit](https://privatecloudarchitect.com/handbook/hardening-audit) | The hardening loop as one command: seven reads distilled into a dated posture folder |
| [`handbook/availability/`](handbook/availability/) | [Availability is a computed promise](https://privatecloudarchitect.com/handbook/availability) | One importable dashboard that reports availability as five layers of evidence, from reachability to the service SLI, each priced by posture |
| [`frameworks/wtpc/`](frameworks/wtpc/) | [The Well-Tuned Private Cloud](https://privatecloudarchitect.com/handbook/wtpc) chapter series | The adoptable starter estate: posture catalog, tag taxonomy, and the converge that builds groups, policies, super metrics, views, dashboards, and alerts on your instance |
| [`frameworks/cartography/`](frameworks/cartography/) | [Discovery and naming](https://privatecloudarchitect.com/handbook/cartography) chapter series | The adoptable supervisor lens: classify Supervisor workloads from the labels they already declare, propose durable tags held for your ratification, and write back only what you approve on the vCenter tag plane, verified and reversible |
| [`frameworks/cartography/flow/`](frameworks/cartography/flow/) | [Discovery and naming](https://privatecloudarchitect.com/handbook/cartography) chapter series | The flow lens: pull the east-west flow graph from VCF Operations for Networks, quarantine the shared services by fan-in, and cluster the rest into tiered candidate applications, read-only, with an offline self-test |

## How to read this repo against the site

The site marks every claim with an evidence tier (`live` / `repo` / `doc`, defined on the
[method page](https://privatecloudarchitect.com/method)). This repo is the visible referent of the
`repo` tier: when a sheet links an artifact here, that artifact is the proof harness or content
the claim rests on. New artifacts appear only when a sheet references them, and corrections are
dated in the artifact's README, never silent.

License: [MIT](LICENSE).
