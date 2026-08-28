# Before you start

A few minutes of orientation that the rest of the series assumes. If you are new
to VCF Automation, this is the part worth reading carefully.

## The orientation that clears up the most confusion

Two words get used constantly and confusingly: **All Apps** and **CCI**. They are
not two formats you choose between. They are two different things:

- **All Apps** is the kind of **organization** you work in: the application-centric
  VCF Automation 9.x experience, where you author **cloud templates** and publish
  them to a catalog. It sits beside the classic **VM Apps** organization (the Aria
  and Cloud Assembly style, still present in 9.x) rather than replacing it. It is
  the "where," not the "how."

- **CCI** (Cloud Consumption Interface) is the *plumbing* underneath. It is how VCF
  Automation talks to a **Supervisor** - a Kubernetes control plane running on your
  vSphere clusters - to provision workloads into **Supervisor namespaces**.

Now the part that actually matters for these templates. A cloud template can be
written in one of two **dialects**, and the dialect follows the organization:

| Dialect | Resource types you write | Native to | Provisions to |
|---|---|---|---|
| **Classic IaaS** | `Cloud.vSphere.Machine`, `Cloud.NSX.Network`, ... | the VM Apps org | vSphere / NSX directly |
| **CCI / Supervisor** | `CCI.Supervisor.Namespace`, `CCI.Supervisor.Resource` | the All Apps org | a Supervisor namespace, Kubernetes-native |

**This series teaches the CCI / Supervisor dialect, start to finish.** Two reasons.
First, it is the modern, Supervisor-native path VCF is built around. Second, and
this is the pedagogy, it is the *only* dialect that carries you smoothly from a
single VM all the way to a Kubernetes microservices app without switching mental
models. You will meet the classic dialect in the wild; when you do, you will
recognize it as "the other way to write the same kind of template." If your goal is
purely traditional vSphere VMs with no Kubernetes ahead of you, that is the VM Apps
org's classic dialect: a fine choice, but not the road this series walks.

Every CCI resource you will see is the same shape: a thin `CCI.Supervisor.Resource`
wrapper around a raw Kubernetes manifest, which VCF Automation submits to the
Supervisor on your behalf. You learn that shape in template 1 and meet it again in
every later stage.

## What you need

1. **Access to an All Apps organization** in VCF Automation 9.x, as a user who can
   author or deploy templates.
2. **A project, and a namespace inside it, to deploy into.** You do not create
   these in the templates - a platform-team member vends them to you. If you do not
   have one, that is precisely the job of the companion **project-vending** series.
   You consume the result here.
3. **`kubectl` reaching your Supervisor.** If you cannot yet run
   `kubectl get supervisornamespaces`, read
   [00-reaching-the-supervisor](./00-reaching-the-supervisor.md) first: it installs
   the vcf CLI, authenticates you, and gives you the context these templates run
   against.

## The discovery commands (fill in your estate's values)

The templates never hardcode anything specific to your cloud. Each estate-specific
input carries the one command that finds the right value, and
[00-reaching-the-supervisor](./00-reaching-the-supervisor.md) lists them in one
place: `kubectl get supervisornamespaces`, `regions`,
`clustervirtualmachineimages`, `storageclasses`, `virtualmachineclasses`, and
`tanzukubernetesreleases` (for the Kubernetes stages). Supply their output as the
template's inputs and the same template deploys correctly on any cloud. That
portability is why they are inputs rather than baked in.

## How to deploy a template

Every template in this series deploys the same two ways:

- **Self-service, through the catalog (the All Apps way).** Import the blueprint as
  a template, release a version of it, add that version to your project's catalog
  as an item, then Deploy and fill in the request form. This is the experience your
  end users get, and it is worth doing at least once to feel it.
- **Automated, through the API or a pipeline (the IaC way).** Submit the template
  with an inputs payload. This is how you wire deployments into GitOps or CI.

In both cases, importing or authoring a template changes nothing. **Deploy** is the
one step that creates infrastructure - so validate first, and on anything
production-adjacent, dry-run first.

## A word on naming

You will notice every object is named from a single `app_name` slug: the VM is
`<app>-01`, a database is `<app>-db-01`, a front door is `<app>-lb`. This is not
decoration. Names are the cheapest documentation an object carries and the first
thing every operator, script, and dashboard reads. The rule: **name for function,
in lowercase kebab-case, derived from the app** - never a person, a mascot, or a
date. The templates hold to it, so the habit is built in rather than something to
remember.

Ready. Start with [`templates/01-single-vm/`](./templates/01-single-vm/).
