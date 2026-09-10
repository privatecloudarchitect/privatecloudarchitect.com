# Template 1 (Crawl): a single virtual machine

The smallest useful thing: one VM that boots and runs. You deploy it, and you
watch it come up. Modest as that sounds, it teaches the shape every later template
builds on.

**File:** [`single-vm.blueprint.yaml`](./single-vm.blueprint.yaml)

## What you will learn here

- The **anatomy** of a CCI/Supervisor cloud template: `formatVersion`, `inputs`,
  `resources`, `outputs`.
- The **wrapper model** that commonly trips up newcomers: a `CCI.Supervisor.Resource`
  is a thin envelope around a raw Kubernetes manifest that VCF Automation applies
  for you. You meet it here and recognize the same shape in every later template.
- Two habits we bake in from the very first template: **parameterize everything
  estate-specific** (nothing borrowed is hardcoded), and **name things for their
  function**.

## The one new concept

**A VM is declared as desired-state, not a script.** You do not tell VCF
Automation the steps to build a VM. You declare the VM you want - this image,
this size, this disk, powered on - and the Supervisor reconciles reality to
match. Everything in this series is that same idea at growing scale.

## Anatomy, top to bottom

| Block | What it is | Why it matters |
|---|---|---|
| `formatVersion: 2` | The template schema version | Required the moment you use an `outputs:` block. Start new templates at 2. |
| `inputs` | The questions the consumer answers | The template's contract. Estate-specific values (image, storage, region, namespace) live here, never in a resource. |
| `resources.Namespace` | The namespace, **referenced** | `existing: true`. You deploy INTO a namespace your platform vends you; you do not create tenancy here. |
| `resources.VM` | The VirtualMachine manifest | `className`/`imageName`/`storageClass` are the Supervisor's names for size/image/disk. No `networks:` block - the namespace's VPC gives the VM a NIC automatically. |
| `outputs` | What you see when done | Tells the consumer what they got and the command to prove it is alive. |

## Before you deploy

Fill the inputs this template marks required (the ones with no default): the target
namespace, the region, the VM image, and the storage class. Each carries its
discovery command in its description, and
[00-reaching-the-supervisor](../../00-reaching-the-supervisor.md) collects those
commands in one place and shows how to run them. If you do not have a namespace to
deploy into yet, a platform-team member vends you one; the companion
**project-vending** series covers that.

## Deploy it

Three ways, same VM. All three apply the identical VirtualMachine; the blueprint
just wraps it so the catalog and the API can apply it on your behalf.

- **The one-command way (kubectl / CCI).** The same VM as a plain Kubernetes
  manifest you apply yourself: [`single-vm.vm.yaml`](./single-vm.vm.yaml). Once you
  have a namespace context (see
  [00-reaching-the-supervisor](../../00-reaching-the-supervisor.md)), fill its three
  estate values (image, storage, region; the discovery command sits beside each),
  then one command builds it:

  ```
  kubectl apply -f single-vm.vm.yaml -n <your-namespace>
  ```

  This is the CCI/CLI path, the same interface every later template's app tier uses.
- **The catalog way (self-service).** Import the blueprint as a template, release a
  version, add it to your project's catalog, then Deploy and fill in the form. This
  is the experience your end users get.
- **The API / IaC way (automation).** Submit the blueprint with an inputs payload
  through the VCF Automation API or your pipeline, the catalog request the demo
  bundles automate.

Either way, authoring changed nothing; **Deploy** (or `kubectl apply`) is the step
that builds the VM.

## What "working" looks like

This VM has no login yet - creating a user is cloud-init's job, which is exactly
template 2. So success at this stage is precise and honest: the VM reaches
`PoweredOn` and the platform assigns it an address.

```
kubectl get virtualmachine <app_name>-01 -n <namespace> -o wide
# STATUS should read Running (PoweredOn), with an IP in the address column.
```

A Running VM with an address means you provisioned real infrastructure from a
template. That is the crawl.

## Graduate to template 2

Right now the VM runs but does nothing and no one can log in. **Template 2** adds
**cloud-init**: a bootstrap that, on first boot, creates a user, installs
packages, and starts a service - turning this bare VM into one that configures
itself. It is the same template you see here, plus one new resource and one new
`spec` field. That is how the series is built: each step is the last one plus a
single new idea.

Next: [`../02-vm-cloud-init/`](../02-vm-cloud-init/)
