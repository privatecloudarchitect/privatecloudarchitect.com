# privatecloudarchitect.com companion artifacts

> **New to VMware Cloud Foundation?** There are two good ways in. Learn **by example**, right here:
> the [learning paths below](#learn-vcf-automation-by-example) are ordered, runnable lessons that
> show what good looks like before the theory, and each directory stands on its own. Or be routed
> **by goal** on the site at
> **[privatecloudarchitect.com/find-your-path](https://privatecloudarchitect.com/find-your-path)**,
> which sequences the whole curriculum and sends you back here to run each proof. Either way, this
> repository is where the examples live, and the site is where the reasoning is written down.

Runnable reference artifacts behind the sheets at [privatecloudarchitect.com](https://privatecloudarchitect.com).
Artifacts arrive in two classes. A **harness** (`handbook/<sheet>/`) backs one published sheet:
it proves that sheet's claims on your estate, read-only or round-tripped, and leaves your estate
as it found it. A **framework estate** (`frameworks/<name>/`) backs a chapter series: it converges
desired state you intend to keep, and is versioned as a unit.

## Learn VCF Automation by example

If you came to see what good looks like before the theory, start here. These are ordered lessons,
each a directory you can run, that build familiarity with VCF Automation All Apps as you go: read
the code, run it against your appliance, and follow the link to the sheet when you want the
reasoning. Each lesson also stands on its own, so you can enter at the one that matches today's
problem.

**Operating All Apps as an admin** is the progression most people want first:

1. **[Provision projects, as-code](handbook/project-vending/)** stands up tenancy the right way:
   authenticate to the API, read any access outcome as two roles on two planes, and vend a project
   and its first namespace in three calls. A from-zero six-module course; begin at module 00.
2. **[Provision workloads](handbook/day1-provisioning/)** deploys into a project, from a first single
   VM through cloud-init, a load-balanced pair, a hybrid three-tier app, and Kubernetes on VKS. Each
   template is a commented lesson that adds one idea to the last.
3. **[Govern day-2 actions](handbook/day2-governance/)** decides who may act on what, with the
   two-policy change that ends the permissive default without stranding the platform team.

The order is a sensible way to build up, not a gate: stop at any step, or start in the middle. Want
to be routed by a different goal instead? The site does that at
[privatecloudarchitect.com/find-your-path](https://privatecloudarchitect.com/find-your-path).

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
| [`handbook/project-vending/`](handbook/project-vending/) | [The solution, one page](https://privatecloudarchitect.com/solutions/tenant-self-service-with-isolation), [field note 03](https://privatecloudarchitect.com/notes/vcfa-project-vending), and the [playbook](https://privatecloudarchitect.com/playbooks/tenant-self-service-isolation) | The complete tenant self-service solution: a six-module learning path (API fundamentals through operate-and-verify), a standard-library API client, the three-call project-and-namespace vend, the catalogs-role setup, a tenant scope check, and a printable admin reference |
| [`handbook/day1-provisioning/`](handbook/day1-provisioning/) | [Day-1 provisioning](https://privatecloudarchitect.com/handbook/day1-provisioning) | Example cloud templates as a graded series: a single VM, then cloud-init, a load-balanced pair, a hybrid three-tier app, and Kubernetes on VKS. Each blueprint is densely commented and adds one concept to the last |
| [`handbook/day2-governance/`](handbook/day2-governance/) | [Day-2 governance](https://privatecloudarchitect.com/handbook/day2-governance) | The two-policy HARD change as importable JSON, named per the sheet's convention |
| [`handbook/memory-tiering/`](handbook/memory-tiering/) | [Memory tiering candidacy](https://privatecloudarchitect.com/handbook/memory-tiering) | The lens end to end: the metrics (formulas plus id-preserving package), the three views, and the readiness dashboard |
| [`handbook/wtpc/`](handbook/wtpc/) | [The Well-Tuned Private Cloud](https://privatecloudarchitect.com/handbook/wtpc) | The starter catalog's three posture records, machine-readable and instance-independent |
| [`handbook/microsegmentation/`](handbook/microsegmentation/) | [Microsegmentation](https://privatecloudarchitect.com/handbook/microsegmentation) | The security-policy round trip: group and policy manifests plus the disabled-first enablement run |
| [`handbook/ops-estate/`](handbook/ops-estate/) | [The operations estate](https://privatecloudarchitect.com/handbook/ops-estate) | Desired-state converge for owned Operations content, with scoped teardown |
| [`handbook/capacity-forecasting/`](handbook/capacity-forecasting/) | [Capacity forecasting](https://privatecloudarchitect.com/handbook/capacity-forecasting) | The commitment-adjusted runway read, with the config-parity gate that refuses to project against a drifted ruler |
| [`handbook/hardening-audit/`](handbook/hardening-audit/) | [Hardening and audit](https://privatecloudarchitect.com/handbook/hardening-audit) | The hardening loop as one command: seven reads distilled into a dated posture folder |
| [`handbook/availability/`](handbook/availability/) | [Availability is a computed promise](https://privatecloudarchitect.com/handbook/availability) | One importable dashboard that reports availability as five layers of evidence, from reachability to the service SLI, each priced by posture |
| [`handbook/metrics-collection/`](handbook/metrics-collection/) | [Metrics collection](https://privatecloudarchitect.com/handbook/metrics-collection) | The collection planes read from your instance: adapters and retention beside their defaults, the 5-minute roll-up checked against native points, extraction coefficients from bounded reads, the composite identity key, and one read of the Real-Time Metrics query API |
| [`frameworks/wtpc/`](frameworks/wtpc/) | [The Well-Tuned Private Cloud](https://privatecloudarchitect.com/handbook/wtpc) chapter series | The adoptable starter estate: posture catalog, tag taxonomy, and the converge that builds groups, policies, super metrics, views, dashboards, and alerts on your instance |
| [`frameworks/cartography/`](frameworks/cartography/) | [Discovery and naming](https://privatecloudarchitect.com/handbook/cartography) chapter series | The adoptable supervisor lens: classify Supervisor workloads from the labels they already declare, propose durable tags held for your ratification, and write back only what you approve on the vCenter tag plane, verified and reversible |
| [`frameworks/cartography/flow/`](frameworks/cartography/flow/) | [Discovery and naming](https://privatecloudarchitect.com/handbook/cartography) chapter series | The flow lens: pull the east-west flow graph from VCF Operations for Networks, quarantine the shared services by fan-in, and cluster the rest into tiered candidate applications, read-only, with an offline self-test |
| [`frameworks/standup-ladder/`](frameworks/standup-ladder/) | [Standup Dependency Ladder field note](https://privatecloudarchitect.com/notes/standup-dependency-ladder) | The adoptable preflight gate: a dependency-ordered check you run against your target namespace before deploying, so taken-for-granted prerequisites fail fast with a remediation instead of stalling silently |

## How to read this repo against the site

The site marks every claim with an evidence tier (`live` / `repo` / `doc`, defined on the
[method page](https://privatecloudarchitect.com/method)). This repo is the visible referent of the
`repo` tier: when a sheet links an artifact here, that artifact is the proof harness or content
the claim rests on. New artifacts appear only when a sheet references them, and corrections are
dated in the artifact's README, never silent.

License: [MIT](LICENSE).
