# privatecloudarchitect.com companion

The code and records behind [privatecloudarchitect.com](https://privatecloudarchitect.com/), a field handbook for operating VMware Cloud
Foundation 9.1. Its chapters run in parts from the platform itself through tenancy, the workload planes,
operations, observability, optimization, security, discovery, Orchestrator content and identity, with field notes,
playbooks, a solution and a demo beside them, and every claim on it is marked with the evidence it rests on. This repository is where that evidence
can be run: each folder below backs one page, and running it on your own estate shows you the same thing the page
shows from the reference estate, or tells you where your estate differs.

## Where to start

- **By goal.** [Find your path](https://privatecloudarchitect.com/find-your-path) asks where you stand and routes you through the chapters, in
  order, to an outcome such as tenant self-service, observability and incident response, or moving an estate's
  identity to VCF single sign-on; where a step has a harness, it links to its folder here.
- **By the map.** [The handbook](https://privatecloudarchitect.com/handbook/) shows every chapter by part and level; [Start](https://privatecloudarchitect.com/start) is
  the short version for a first visit.
- **By folder.** The [map below](#the-map) lists every folder by the part of the site it serves, in the site's
  order. Start with the folder's README.
- **By example.** If you want to see VCF Automation done well before reading why, three folders form a course:
  [`handbook/project-vending/`](handbook/project-vending/) (authenticate, read access as two roles on two planes,
  vend a project and its first namespace in three calls; begin at module 00), then
  [`handbook/day1-provisioning/`](handbook/day1-provisioning/) (templates from a single VM to Kubernetes on VKS),
  then [`handbook/day2-governance/`](handbook/day2-governance/) (who may act on what after deployment).
- **Importing VCF Operations content** (super metrics, views, dashboards)? [IMPORTING.md](IMPORTING.md) walks the
  UI screens for each, in the order they depend on each other.

## Running a folder

```
git clone https://github.com/privatecloudarchitect/privatecloudarchitect.com
cd privatecloudarchitect.com/handbook/<folder>
# read README.md first: it names the environment variables, the credential and role the tool expects,
# and any library beyond the Python standard library
```

Some tools only read; others create, change or delete objects on your estate. Read the folder's README before
running anything, use the plan or preview a tool offers before the step that writes, and point any tool that writes
at a scope you can afford to change. Some folders import helpers from a sibling folder, so run them from a full
clone rather than from a copied directory.

## The contract

Everything in this repository satisfies four rules before it is pushed:

1. **It backs a published page.** The map below names the page each folder belongs to.
2. **It was proven on a live VMware Cloud Foundation estate**, and each folder's README states the build and the
   date it was proven on.
3. **It is parameterized for your estate.** Environment variables and marked placeholders carry everything
   estate-specific; nothing here assumes the estate it was proven on.
4. **What ships is what ran.** The exact files here were re-run against a live estate before publication, not
   sanitized afterward and assumed equivalent.

Framework estates carry five further clauses:

5. **Desired state is the interface.** You edit declarative files; converge scripts are the only mutation path,
   idempotent, adopting existing objects by their stable names.
6. **Teardown is scoped.** Every converge has a teardown that removes exactly what converge created, and nothing
   else.
7. **Dependencies are declared.** Most folders need only the Python standard library. Where one needs a library
   (pyVmomi to read vCenter, PyYAML, cryptography, ldap3, pydantic), its README names it.
8. **The reference estate is one usage.** Nothing estate-specific lives in the universal layer; your estate enters
   through the declared parameters, never through edits to shared logic.
9. **Round-tripped before publication.** Every slice was converged, verified and torn down live on the exact bytes
   published here.

## The map

### Part 0 · The platform

| Folder | Chapter | What it does |
|---|---|---|
| [`handbook/platform-map/`](handbook/platform-map/) | [The platform map](https://privatecloudarchitect.com/handbook/platform-map) | Places your own estate on the platform map: every domain with its clusters, hosts, vCenter and NSX, each Supervisor, and the release each component runs against the 9.1.1 bill of materials. Read-only |
| [`handbook/identity-model/`](handbook/identity-model/) | [The identity model](https://privatecloudarchitect.com/handbook/identity-model) | Reads the estate's identity model from the planes that own it: brokers, realms, providers and directories, the two vCenter grant spellings, API clients and their token lifetimes. Read-only |
| [`handbook/platform-identity/`](handbook/platform-identity/) | [Platform identity](https://privatecloudarchitect.com/handbook/platform-identity) | Decodes a bearer you already hold and tells you which of its two clocks ran out, the question every 401 raises |
| [`handbook/service-accounts/`](handbook/service-accounts/) | [Service accounts](https://privatecloudarchitect.com/handbook/service-accounts) | Proves a credential before a pipeline trusts it: what its bearer says about the holder, and which token each surface accepts, one harmless read per pair |
| [`handbook/resilient-api-call/`](handbook/resilient-api-call/) | [The resilient API call](https://privatecloudarchitect.com/handbook/resilient-api-call) | The client the chapter describes, readable in one sitting: re-mint once on a 401, a typed boundary, reads checked against their declared total, idempotent writes with a dry run and a confirming re-read |
| [`handbook/vcfa-api/`](handbook/vcfa-api/) | [The VCF Automation API](https://privatecloudarchitect.com/handbook/vcfa-api) | The VCF Automation token flows recorded as they went over the wire, with the script that records them on your estate and a runway check for your stored refresh token |

### Part I · Tenancy and consumption

| Folder | Chapter | What it does |
|---|---|---|
| [`handbook/construct-model/`](handbook/construct-model/) | [Construct model](https://privatecloudarchitect.com/handbook/construct-model) | The containment tree, taxonomy and naming standard read from your estate through the Cloud Consumption Interface, with every name audited against the grammar each construct takes |
| [`handbook/access-control/`](handbook/access-control/) | [Access control](https://privatecloudarchitect.com/handbook/access-control) | What the platform says you are on each plane: the groups derived for your bearer, the published project roles, and one access review asked with and without scope. Counts and shapes only |
| [`handbook/day2-governance/`](handbook/day2-governance/) | [Day-2 governance](https://privatecloudarchitect.com/handbook/day2-governance) | Asks the policy plane to describe itself: policy types and their schemas, action selectors, the policies you hold and the decision log; `--rehearse` runs the platform's own dry run of one more policy |
| [`handbook/network-plane/`](handbook/network-plane/) | [Network plane](https://privatecloudarchitect.com/handbook/network-plane) | Asks the networking plane to describe itself, from an IP block out to the provider gateway, and reports which security strategy is attached to your VPC. Read-only |
| [`handbook/capacity-plane/`](handbook/capacity-plane/) | [Capacity plane](https://privatecloudarchitect.com/handbook/capacity-plane) | Adds up capacity as the ledger it is: every zone's granted budget beside its reported consumption, every namespace's budget, and which of the two a create is measured against |
| [`handbook/day1-provisioning/`](handbook/day1-provisioning/) | [Day-1 provisioning](https://privatecloudarchitect.com/handbook/day1-provisioning) | Example cloud templates as a graded series, from a single VM through cloud-init, a load-balanced pair and a three-tier app to Kubernetes on VKS, each adding one idea |
| [`handbook/isolation-design/`](handbook/isolation-design/) | [The isolation design](https://privatecloudarchitect.com/handbook/isolation-design), then [Field note 01](https://privatecloudarchitect.com/notes/vcfa-access-control-three-factors) | Declarative manifests and a verifier that prove per-user isolation on your build |
| [`handbook/temporary-elevation/`](handbook/temporary-elevation/) | [Temporary elevation](https://privatecloudarchitect.com/handbook/temporary-elevation) | Asks your build what it can put a clock on: every policy type and access-granting object scanned for a field that could hold a deadline; `--probe-elevation` moves one binding you name up a role and puts it back |

### Part II · The workload planes

| Folder | Chapter | What it does |
|---|---|---|
| [`handbook/vks-operations/`](handbook/vks-operations/) | [Supervisor and VKS operations](https://privatecloudarchitect.com/handbook/vks-operations) | Reads the Kubernetes estate from both surfaces it answers on: the kinds and verbs at the organization gateway, and each cluster's capacity and control-plane health. Read-only |
| [`handbook/vm-service/`](handbook/vm-service/) | [The VM Service](https://privatecloudarchitect.com/handbook/vm-service) | Sorts every virtual machine on the workload plane by the path it arrived by, from the objects themselves rather than naming conventions. Read-only |
| [`handbook/namespace-storage/`](handbook/namespace-storage/) | [Namespace storage](https://privatecloudarchitect.com/handbook/namespace-storage) | Asks every plane that will answer how much storage is used, and prints the answers side by side on one day. Read-only |
| [`handbook/building-blueprints/`](handbook/building-blueprints/) | [Building blueprints](https://privatecloudarchitect.com/handbook/building-blueprints) | Measures the shape of every blueprint on your estate, parsed as YAML: its inputs, resources and declared types, joined against the schema its catalog item publishes. Read-only |
| [`handbook/control-plane-lb/`](handbook/control-plane-lb/) | [The control-plane load balancer](https://privatecloudarchitect.com/handbook/control-plane-lb) | Walks your load balancer's object graph forwards from every listener to its pools and reconciles the pool count against the selection rules. Read-only |
| [`handbook/three-doors/`](handbook/three-doors/) | [Three doors to one machine](https://privatecloudarchitect.com/handbook/deployment-paths) | Builds the same virtual machine twice, straight at a namespace and through the catalog, and reads both back field by field to show nothing on the machine names the door it came through |
| [`handbook/day2-pathways/`](handbook/day2-pathways/) | [Day-2 on three planes](https://privatecloudarchitect.com/handbook/day2-pathways) | Compares, for every machine a deployment claims, the manifest the record declares, the object it last observed and the live object, so drift is proven with one credential |
| [`handbook/workload-origin/`](handbook/workload-origin/) | [Where a workload is born](https://privatecloudarchitect.com/handbook/workload-origin) | Lists every Supervisor namespace with the plane that created it and the evidence for each answer. Read-only |
| [`handbook/event-model/`](handbook/event-model/) | [The event model](https://privatecloudarchitect.com/handbook/event-model) | Prints the event topics your organization publishes and which are blockable, then the lifecycle events your broker recorded, grouped by the request that caused them |

### Part III · Running the platform

| Folder | Chapter | What it does |
|---|---|---|
| [`handbook/platform-lifecycle/`](handbook/platform-lifecycle/) | [Platform lifecycle](https://privatecloudarchitect.com/handbook/platform-lifecycle) | Answers the question before a change window: is the upgrade the registry offers actually available, with its bundles downloaded. Read-only |
| [`handbook/certs-credentials/`](handbook/certs-credentials/) | [Certificates and credentials](https://privatecloudarchitect.com/handbook/certs-credentials) | Reports rotation coverage and the certificate horizon from metadata alone, built so that no secret can reach its output. Read-only |
| [`handbook/platform-backup/`](handbook/platform-backup/) | [Backup and restore](https://privatecloudarchitect.com/handbook/platform-backup) | Answers what a backup configuration cannot: did it run? Each plane's schedule in its own encoding, and the days between runs that carry no copy. Read-only |

### Part IV · Observability and response

| Folder | Chapter | What it does |
|---|---|---|
| [`handbook/ops-estate/`](handbook/ops-estate/) | [Operations content is code](https://privatecloudarchitect.com/handbook/ops-estate) | Two harnesses: `converge.py` asserts desired state for the VCF Operations content you own, with a scoped and verified teardown, and `content.py` audits the same estate read-only |
| [`handbook/alerting-doctrine/`](handbook/alerting-doctrine/) | [Alerting doctrine](https://privatecloudarchitect.com/handbook/alerting-doctrine) | Three scripts that check the chapter's practices on your own VCF Operations instance, starting with every field on every alert definition |
| [`handbook/incident-response/`](handbook/incident-response/) | [Incident response](https://privatecloudarchitect.com/handbook/incident-response) | Asks whether your alert queue is made of incidents: every alert by age, impact, concentration and control state. Read-only |
| [`handbook/availability/`](handbook/availability/) | [Availability is a computed promise](https://privatecloudarchitect.com/handbook/availability) | An importable dashboard that reports availability as five layers of evidence, and `promise.py`, which reads the roll-ups back with the age of each |
| [`handbook/metrics-collection/`](handbook/metrics-collection/) | [Collect once, decide at source](https://privatecloudarchitect.com/handbook/metrics-collection), then [Extract once, by tier, on one key](https://privatecloudarchitect.com/handbook/metrics-extraction) | The collection guide for VCF Operations in learning order: the import that puts the Collection Strategy Guide on your instance, then the read-only scripts behind each measurement |
| [`handbook/log-collection/`](handbook/log-collection/) | [Log collection](https://privatecloudarchitect.com/handbook/log-collection) | `log_paths.py`: the path each log source takes, what the proxies keep, and the source proof that each ESX host's own applications reach Log Management. Read-only |
| [`handbook/flow-collection/`](handbook/flow-collection/) | [Flow collection](https://privatecloudarchitect.com/handbook/flow-collection) | `flow_paths.py`: the Operations for Networks collector, every source's IPFIX state and the hour's flows by the host each endpoint runs on. Read-only |
| [`handbook/log-lifecycle/`](handbook/log-lifecycle/) | [Log lifecycle](https://privatecloudarchitect.com/handbook/log-lifecycle) | `lifecycle.py`: what your Log Management store keeps, sends, masks and drops and how far back it reaches, the shard budget, and trials that prove a rule on labelled lines |
| [`handbook/log-alerts/`](handbook/log-alerts/) | [Log alerts](https://privatecloudarchitect.com/handbook/log-alerts) | Builds VCF Operations log alerts that fire: find the identifier the platform writes, try the query, switch a bundle on for one group, and prove it with labelled lines; ships a storage path catalog |

### Part V · Optimization and economics

| Folder | Chapter | What it does |
|---|---|---|
| [`handbook/wtpc/`](handbook/wtpc/) | [The Well-Tuned Private Cloud](https://privatecloudarchitect.com/handbook/wtpc) | The starter catalog's three posture records, machine-readable and instance-independent |
| [`handbook/memory-tiering/`](handbook/memory-tiering/) | [Memory tiering](https://privatecloudarchitect.com/handbook/memory-tiering) | The memory tiering lens end to end: the super metrics, three views and the readiness dashboard |
| [`handbook/capacity-forecasting/`](handbook/capacity-forecasting/) | [Capacity forecasting](https://privatecloudarchitect.com/handbook/capacity-forecasting) | The commitment-adjusted runway, with a configuration gate that refuses to project against a drifted ruler |
| [`handbook/cost-showback/`](handbook/cost-showback/) | [Cost and showback](https://privatecloudarchitect.com/handbook/cost-showback) | The coverage gate: how many objects actually report each cost key, the totals checked against their parts, and whether your custom groups can carry cost |

### Part VII · Security and compliance

| Folder | Chapter | What it does |
|---|---|---|
| [`handbook/microsegmentation/`](handbook/microsegmentation/) | [Microsegmentation](https://privatecloudarchitect.com/handbook/microsegmentation) | The security policy round trip: group and policy manifests and the disabled-first enablement run |
| [`handbook/hardening-audit/`](handbook/hardening-audit/) | [Hardening and audit](https://privatecloudarchitect.com/handbook/hardening-audit) | The hardening loop as one command: seven reads distilled into a dated posture folder, with the audit trail's window checked |
| [`handbook/identifier-planes/`](handbook/identifier-planes/) | [Identifier planes](https://privatecloudarchitect.com/handbook/identifier-planes) | Asks every plane that holds an identifier for your workloads what it knows, and which groups defined by a tag resolve to anything |
| [`handbook/metadata-projection/`](handbook/metadata-projection/) | [Metadata projection](https://privatecloudarchitect.com/handbook/metadata-projection) | One read-only pass across VCF Automation, vCenter and VCF Operations: does the metadata your workloads declare reach the plane your consumers read |

### Part IX · Orchestrator content engineering

| Folder | Chapter | What it does |
|---|---|---|
| [`handbook/orchestrator-objects/`](handbook/orchestrator-objects/) | [The Orchestrator object model](https://privatecloudarchitect.com/handbook/orchestrator-objects) | Reads your Orchestrator's object tree and prints the three binding mechanisms that hold it together, the thing the console never shows |

### Part X · Identity and access

| Folder | Chapter | What it does |
|---|---|---|
| [`handbook/vcenter-authorization/`](handbook/vcenter-authorization/) | [vCenter authorization](https://privatecloudarchitect.com/handbook/vcenter-authorization) | Reads every permission on your vCenters and classifies how each behaves for a session signed in through the identity broker, with three opt-in probes for what a read cannot settle |
| [`handbook/integrations-identity/`](handbook/integrations-identity/) | [Integrations identity](https://privatecloudarchitect.com/handbook/integrations-identity) | Takes a VCF SSO API client through each vCenter's token exchange, and reads every vCenter's session list so an integration still signing in as a person shows up |
| [`handbook/tenant-federation/`](handbook/tenant-federation/) | [Tenant federation](https://privatecloudarchitect.com/handbook/tenant-federation) | Federates a throwaway VCF Automation organization to Microsoft Entra ID over OIDC or SAML: plans by default, builds with `--execute`, proves both sides, and tears down what it built |
| [`handbook/federation-operations/`](handbook/federation-operations/) | [Federation operations](https://privatecloudarchitect.com/handbook/federation-operations) | Reads both sides of every organization federated to Entra ID: signing keys, client secret dates, certificates, groups and the app's gate. Read-only |
| [`handbook/identity-lifecycle/`](handbook/identity-lifecycle/) | [Identity lifecycle](https://privatecloudarchitect.com/handbook/identity-lifecycle) | Finds every account whose person has left at Entra ID and reports what each still holds; `--execute --org` revokes a confirmed leaver's tokens and disables the account |

### Field notes, the solution and the demo

| Folder | Page | What it does |
|---|---|---|
| [`handbook/project-vending/`](handbook/project-vending/) | [The solution: tenant self-service with isolation](https://privatecloudarchitect.com/solutions/tenant-self-service-with-isolation), then [Field note 03](https://privatecloudarchitect.com/notes/vcfa-project-vending), then [the playbook](https://privatecloudarchitect.com/playbooks/tenant-self-service-isolation) | The complete tenant self-service solution: a six-module course, a standard-library API client, the three-call project and namespace vend, and an admin reference |
| [`handbook/capacity-in-and-out/`](handbook/capacity-in-and-out/) | [Field note 07](https://privatecloudarchitect.com/notes/capacity-in-and-out) | Walks the capacity ladder from workload domain to tenancy and prints each layer's gate. Read-only |
| [`handbook/orchestrator-upgrade/`](handbook/orchestrator-upgrade/) | [Field note 04](https://privatecloudarchitect.com/notes/aria-automation-8-18-to-vcf-automation-9-1-1) | Before you upgrade an Orchestrator, a read-only scan of what the new release breaks, on a live instance or on exported scripts, and a qualifier that runs your own actions on the target runtime before the upgrade does |
| [`handbook/lifecycle-demo/`](handbook/lifecycle-demo/) | [Demo: the hybrid application lifecycle](https://privatecloudarchitect.com/demo/hybrid-app-lifecycle) | The captured run behind the walkthrough, every step with its purpose, file, call and result, and the scrubber that produced it |

### Framework estates

Converge desired state you intend to keep; versioned as a unit.

| Folder | Backs | What it does |
|---|---|---|
| [`frameworks/wtpc/`](frameworks/wtpc/) | [The Well-Tuned Private Cloud](https://privatecloudarchitect.com/handbook/wtpc) | The adoptable starter estate: posture catalog, tag taxonomy, and the converge that builds groups, policies, super metrics, views, dashboards and alerts on your instance |
| [`frameworks/cartography/`](frameworks/cartography/) | [Cartography: the method](https://privatecloudarchitect.com/handbook/cartography) | The supervisor lens: classify Supervisor workloads from the labels they declare, propose tags for your ratification, and write back only what you approve |
| [`frameworks/cartography/flow/`](frameworks/cartography/flow/) | [Cartography: the method](https://privatecloudarchitect.com/handbook/cartography) | The flow lens: the east-west flow graph from VCF Operations for Networks, shared services set aside, and the rest clustered into candidate applications. Read-only |
| [`frameworks/collect-once/`](frameworks/collect-once/) | [Collect once, decide at source](https://privatecloudarchitect.com/handbook/metrics-collection) | The Collection Strategy Guide dashboard for VCF Operations, with the verified PromQL reference for the real-time plane |
| [`frameworks/standup-ladder/`](frameworks/standup-ladder/) | [Field note 05](https://privatecloudarchitect.com/notes/standup-dependency-ladder) | A dependency-ordered preflight you run against your target namespace before deploying, so a missing prerequisite fails fast with its remedy |

## Reading this repository against the site

The site marks every claim with one of three evidence tiers, defined on the [method page](https://privatecloudarchitect.com/method): `live`,
verified on a running VCF estate and dated; `repo`, modeled in a maintained codebase; and `doc`, documented by the
vendor and not exercised there. This repository is the visible part of the `repo` tier: when a page links a folder
here, that folder is the harness or content the claim rests on, and a `repo` mark with no link means the proof lives
in the author's own codebase. A folder appears only when a page references it, and a correction is dated in the
folder's README, never made silently.

License: [MIT](LICENSE).
