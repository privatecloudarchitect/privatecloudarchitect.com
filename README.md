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
| [`handbook/vks-operations/`](handbook/vks-operations/) | [Supervisor and VKS operations](https://privatecloudarchitect.com/handbook/vks-operations) | A read-only script that reads the Kubernetes estate from both surfaces it answers on: every estate-management kind at the organization gateway with the verbs it declares AND the verbs you are actually permitted, which are different answers; each cluster's capacity and per-component control-plane health from the fleet projection, the triage read that needs no kubeconfig; the declared Cluster API object at each Supervisor namespace endpoint with its class, version, replicas and variables; and every node machine walked back through its controller owner to the declaration that produced it. It writes nothing. Every organization name is a placeholder |
| [`handbook/service-accounts/`](handbook/service-accounts/) | [Service accounts](https://privatecloudarchitect.com/handbook/service-accounts) | Prove a credential before a pipeline trusts it: what the bearer your api-token exchanges for says about its holder (a person or a machine, and its lifetime read off the token), and which token each surface accepts, one harmless read per pair with the count of effective rights per login path |
| [`handbook/resilient-api-call/`](handbook/resilient-api-call/) | [The resilient API call](https://privatecloudarchitect.com/handbook/resilient-api-call) | The three guarantees as a client you can read in one sitting (re-mint once on a 401, a typed boundary that names what drifted, a collection read against its declared total, an idempotent ensure with a dry run) and a six-step read-only demo against your own estate |
| [`handbook/temporary-elevation/`](handbook/temporary-elevation/) | [Temporary elevation](https://privatecloudarchitect.com/handbook/temporary-elevation) | A read-only script that asks your build what it can put a clock on: every policy type the plane declares with its schema scanned for any field that could hold a deadline, the complete field list of every object that grants access, and the deployment fields that do carry a time bound. The answer is what the whole elevation design rests on, so it is worth taking from your own estate rather than from a page. With `--probe-elevation <binding name>` it also moves one binding you name up a role and puts it back, reading the object directly after every step, which is how you learn whether a guaranteed revert is possible and whether this plane honours a dry run. It will not choose a binding for you. Every organization name is a placeholder |
| [`handbook/vcfa-api/`](handbook/vcfa-api/) | [The VCF Automation API](https://privatecloudarchitect.com/handbook/vcfa-api) | The two token flows recorded on a real estate as they went over the wire, every estate value replaced by a placeholder, with the script that records them on yours: the OAuth grant and one read per API surface, the Basic session login whose bearer arrives in a response header, and the rights present under one login path and absent under the other, by name |
| [`handbook/access-control/`](handbook/access-control/) | [Access control](https://privatecloudarchitect.com/handbook/access-control) | What the platform says you are, on each plane: the groups it derived for your bearer at the organization gateway and at a namespace endpoint, the published project roles, the binding authority beside the projection that discards writes, and one access review asked with and without scope against the matching real read. Counts and shapes only, never a name |
| [`handbook/construct-model/`](handbook/construct-model/) | [The construct model](https://privatecloudarchitect.com/handbook/construct-model) | The containment spine, the taxonomy, and the naming standard, read from your own estate through the Cloud Consumption Interface: every API group and kind the interface declares with its scope and verbs, the tree of projects, bindings, role bindings, namespaces with the fields each bound at create, and the workloads behind each namespace's endpoint, plus an audit of every name you carry against the grammar each construct should follow. With `--probe-bindings` it also asks the interface whether a namespace's class, region, VPC, and parent project can be changed after create, and records the answers verbatim. Every estate name is a placeholder and the audit records counts alone |
| [`handbook/isolation-design/`](handbook/isolation-design/) | [The isolation design, assembled](https://privatecloudarchitect.com/handbook/isolation-design) and [field note 01](https://privatecloudarchitect.com/notes/vcfa-access-control-three-factors) | Declarative manifests plus a verifier that proves per-user isolation on your build |
| [`handbook/project-vending/`](handbook/project-vending/) | [The solution, one page](https://privatecloudarchitect.com/solutions/tenant-self-service-with-isolation), [field note 03](https://privatecloudarchitect.com/notes/vcfa-project-vending), and the [playbook](https://privatecloudarchitect.com/playbooks/tenant-self-service-isolation) | The complete tenant self-service solution: a six-module learning path (API fundamentals through operate-and-verify), a standard-library API client, the three-call project-and-namespace vend, the catalogs-role setup, a tenant scope check, and a printable admin reference |
| [`handbook/day1-provisioning/`](handbook/day1-provisioning/) | [Day-1 provisioning](https://privatecloudarchitect.com/handbook/day1-provisioning) | Example cloud templates as a graded series: a single VM, then cloud-init, a load-balanced pair, a hybrid three-tier app, and Kubernetes on VKS. Each blueprint is densely commented and adds one concept to the last |
| [`handbook/day2-governance/`](handbook/day2-governance/) | [Day-2 governance](https://privatecloudarchitect.com/handbook/day2-governance) | A read-only script that asks the policy plane to describe itself: the types your build declares with the three schemas and the capability flags of each, the action selectors and the tree their wildcards form, the policies you hold, and the decision log with the rank the plane gave each applied policy and the effective definition it computed. With `--rehearse` it runs the platform's own dry run of one more policy and proves nothing was created. Plus the two-policy HARD change as importable JSON, named per the chapter's convention |
| [`handbook/capacity-plane/`](handbook/capacity-plane/) | [The capacity plane](https://privatecloudarchitect.com/handbook/capacity-plane) | Capacity here is a set of objects that reads like a ledger, so this adds it up rather than describing it: every zone's granted budget beside its reported consumption, for limits and reservations separately; every namespace's own per-zone budget; the sum of the second against the first, which tells you which of the two numbers a create is actually measured against; every class config compared field by field with what the namespaces bound to it hold, tallied as the same, above or below; and the region's storage ledgers and machine-class catalog. Read-only unless you pass `--probe-overrides`, which asks a create, six ways, which directions it may depart from its class config in, and deletes every namespace it makes. Quantities keep the unit suffix the interface returned them with. Every organization name is a placeholder |
| [`handbook/network-plane/`](handbook/network-plane/) | [The network plane](https://privatecloudarchitect.com/handbook/network-plane) | A read-only script that asks the networking plane to describe itself: every networking kind with its scope, verbs and instance count held as families, the chain from an IP block out to the provider gateway object by object, the subnets and the access mode each declares, the outbound translation rule, and the one line worth running it for, which security strategy is actually attached to your VPC. Every organization name is a placeholder |
| [`handbook/memory-tiering/`](handbook/memory-tiering/) | [Memory tiering candidacy](https://privatecloudarchitect.com/handbook/memory-tiering) | The lens end to end: the metrics (formulas plus id-preserving package), the three views, and the readiness dashboard |
| [`handbook/wtpc/`](handbook/wtpc/) | [The Well-Tuned Private Cloud](https://privatecloudarchitect.com/handbook/wtpc) | The starter catalog's three posture records, machine-readable and instance-independent |
| [`handbook/microsegmentation/`](handbook/microsegmentation/) | [Microsegmentation](https://privatecloudarchitect.com/handbook/microsegmentation) | The security-policy round trip: group and policy manifests plus the disabled-first enablement run |
| [`handbook/ops-estate/`](handbook/ops-estate/) | [The operations estate](https://privatecloudarchitect.com/handbook/ops-estate) | Desired-state converge for owned Operations content, with scoped teardown |
| [`handbook/capacity-forecasting/`](handbook/capacity-forecasting/) | [Capacity forecasting](https://privatecloudarchitect.com/handbook/capacity-forecasting) | The commitment-adjusted runway read, with the config-parity gate that refuses to project against a drifted ruler |
| [`handbook/hardening-audit/`](handbook/hardening-audit/) | [Hardening and audit](https://privatecloudarchitect.com/handbook/hardening-audit) | The hardening loop as one command: seven reads distilled into a dated posture folder |
| [`handbook/availability/`](handbook/availability/) | [Availability is a computed promise](https://privatecloudarchitect.com/handbook/availability) | One importable dashboard that reports availability as five layers of evidence, from reachability to the service SLI, each priced by posture |
| [`handbook/metrics-collection/`](handbook/metrics-collection/) | [Metrics collection](https://privatecloudarchitect.com/handbook/metrics-collection) | The education path in order: `import/`, the two files that put the PCA - Collection Strategy Guide on your own VCF Operations with one binding step and the guide's reading order; `harness/`, the read-only scripts that reproduce the chapter's measurements on your instance (the planes and their retention, the roll-up check, the extraction coefficients, the identity key, the real-time path); and the Collection Planes Atlas as one page |
| [`frameworks/wtpc/`](frameworks/wtpc/) | [The Well-Tuned Private Cloud](https://privatecloudarchitect.com/handbook/wtpc) chapter series | The adoptable starter estate: posture catalog, tag taxonomy, and the converge that builds groups, policies, super metrics, views, dashboards, and alerts on your instance |
| [`frameworks/cartography/`](frameworks/cartography/) | [Discovery and naming](https://privatecloudarchitect.com/handbook/cartography) chapter series | The adoptable supervisor lens: classify Supervisor workloads from the labels they already declare, propose durable tags held for your ratification, and write back only what you approve on the vCenter tag plane, verified and reversible |
| [`frameworks/cartography/flow/`](frameworks/cartography/flow/) | [Discovery and naming](https://privatecloudarchitect.com/handbook/cartography) chapter series | The flow lens: pull the east-west flow graph from VCF Operations for Networks, quarantine the shared services by fan-in, and cluster the rest into tiered candidate applications, read-only, with an offline self-test |
| [`frameworks/collect-once/`](frameworks/collect-once/) | [Metrics collection](https://privatecloudarchitect.com/handbook/metrics-collection) | The Collection Strategy Guide: an importable VCF Operations dashboard that maps the VM utilization catalog to Operations keys with their vCenter statistics levels, lists your own VMs live, charts the hidden peaks, and runs three PromQL Viewers on the real-time plane; beside it the verified PromQL reference (the functions, ten strategy queries, the widget's catalog reconciled against the engine and the VMware guidance list) and the generators every key is checked through |
| [`frameworks/standup-ladder/`](frameworks/standup-ladder/) | [Standup Dependency Ladder field note](https://privatecloudarchitect.com/notes/standup-dependency-ladder) | The adoptable preflight gate: a dependency-ordered check you run against your target namespace before deploying, so taken-for-granted prerequisites fail fast with a remediation instead of stalling silently |

## How to read this repo against the site

The site marks every claim with an evidence tier (`live` / `repo` / `doc`, defined on the
[method page](https://privatecloudarchitect.com/method)). This repo is the visible referent of the
`repo` tier: when a sheet links an artifact here, that artifact is the proof harness or content
the claim rests on. New artifacts appear only when a sheet references them, and corrections are
dated in the artifact's README, never silent.

License: [MIT](LICENSE).
