# Before you start

A few minutes of orientation that the rest of the series assumes. If you are new
to VCF Automation, this is the part worth reading carefully.

## The orientation that clears up the most confusion

Two words get used constantly and confusingly: **All Apps** and **CCI**. They are
not two formats you choose between. They are two different things:

- **All Apps** is the *mode* you work in - the VCF Automation 9.x application
  experience (the successor to what was called "VM Apps"). Inside an All Apps org
  you author **cloud templates** and publish them to a catalog. It is the "where,"
  not the "how."

- **CCI** (Cloud Consumption Interface) is the *plumbing* underneath. It is how VCF
  Automation talks to a **Supervisor** - a Kubernetes control plane running on your
  vSphere clusters - to provision workloads into **Supervisor namespaces**.

Now the part that actually matters for these templates. A cloud template can be
written in one of two **dialects**:

| Dialect | Resource types you write | Provisions to |
|---|---|---|
| **Classic IaaS** | `Cloud.vSphere.Machine`, `Cloud.NSX.Network`, ... | vSphere / NSX directly |
| **CCI / Supervisor** | `CCI.Supervisor.Namespace`, `CCI.Supervisor.Resource` | a Supervisor namespace, Kubernetes-native |

**This series teaches the CCI / Supervisor dialect, start to finish.** Two reasons.
First, it is the modern, Supervisor-native path VCF is built around. Second - and
this is the pedagogy - it is the *only* dialect that carries you smoothly from a
single VM all the way to a Kubernetes microservices app without ever switching
mental models. You will meet the classic dialect in the wild; when you do, you
will recognize it as "the other way to write the same kind of template." If your
goal is purely traditional vSphere VMs with no Kubernetes ahead of you, the
classic dialect is a fine choice - but it is not the road this series walks.

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
3. **`kubectl` with a Supervisor context**, for the discovery commands below and to
   watch your deployments come up. Your platform team provides the kubeconfig /
   `vcf context` to reach the Supervisor.

## The discovery commands (fill in your estate's values)

The templates never hardcode anything specific to your cloud. Instead, each
estate-specific input carries the command that finds the right value. You will use
these constantly:

```
kubectl get supervisornamespaces          # a namespace you can deploy into
kubectl get regions                        # your region slug
kubectl get clustervirtualmachineimages    # VM images (pick an Ubuntu 24.04 vmi-... ID)
kubectl get storageclasses                 # storage classes you are entitled to
kubectl get virtualmachineclasses          # VM sizes (best-effort-* / guaranteed-*)
```

Supply these as the template's inputs and the same template deploys correctly on
any cloud. That portability is why they are inputs rather than baked in.

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
