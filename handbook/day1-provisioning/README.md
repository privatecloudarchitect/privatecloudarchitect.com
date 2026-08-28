# Day-1 app templates: a crawl-walk-run series for VCF Automation

A set of example cloud templates that take you from your very first virtual
machine to a Kubernetes microservices application, one small step at a time.
Written for someone **brand new to All Apps and CCI** who has no template to copy
from and wants to learn the right habits from the start, not unlearn bad ones
later.

These are not just templates. Each one is a lesson: the blueprint is densely
commented with the design and the *why* behind every non-obvious line, and each
stage adds **exactly one new concept** to the one before it. Read them in order
and the hard ideas arrive one at a time.

## Start here

New to any of this? Read [`00-before-you-start.md`](./00-before-you-start.md)
first: what you need, the orientation worth having up front (what "All Apps" and
"CCI" actually are), and how to deploy a template.

## The learning path

| Stage | Template | The one new concept | What you end up with |
|---|---|---|---|
| **Crawl** | [`01-single-vm`](./templates/01-single-vm/) | A VM is declared desired-state; the template anatomy | One Ubuntu VM that boots and runs |
| **Crawl** | [`02-vm-cloud-init`](./templates/02-vm-cloud-init/) | Cloud-init: the VM configures itself on first boot | A VM that installs a package and creates a user |
| **Walk** | [`03-web-pair`](./templates/03-web-pair/) | More than one VM, behind a load-balancer front door | Two web servers reachable from outside |
| **Walk to run** | [`04-hybrid-3tier`](./templates/04-hybrid-3tier/) | A VM and containers as one app, in one namespace | A database VM with a containerized web/app tier |
| **Run** | [`05-microservices`](./templates/05-microservices/) | A full Kubernetes app on a VKS guest cluster | A multi-service application on Kubernetes |

The through-line is deliberate: every template is the **CCI/Supervisor dialect**,
so you are not switching mental models as the applications get more ambitious. By
the last stage you are running Kubernetes, having started from a single VM, and
each step in between followed because it was one idea larger than the last.

## What is in this folder

```
day1-app-templates/
  README.md                     # you are here: the learning path
  00-before-you-start.md        # prerequisites + orientation + how to deploy
  templates/
    01-single-vm/               # crawl:  one VM that boots and runs
      single-vm.blueprint.yaml
      README.md
    02-vm-cloud-init/           # crawl:  + cloud-init self-configuration
    03-web-pair/                # walk:   + a second VM and a load balancer
    04-hybrid-3tier/            # walk->run: + a VM database and a container tier
    05-microservices/           # run:    + a Kubernetes microservices app
```

Each stage folder holds the template file(s) and its own `README.md` that says
what it teaches, what changed from the previous stage, how to deploy it, and what
"working" looks like.

## How to use it

- **Learning?** Read the stage READMEs in order and read the blueprint comments
  as you go - the comments are the course. Deploy each one if you can; seeing it
  come up is worth more than reading about it.
- **Referencing?** Jump to the stage closest to what you are building and copy the
  template. Then do the step that separates a template from a copy: replace
  the estate-specific inputs (image, storage, region, namespace) with your own
  values. The templates keep these as inputs, so there are no buried values to
  hunt for.
- **Teaching?** The crawl-walk-run arc is the syllabus. Stages 1-2 are a first
  session; 3-4 a second; 5 a capstone.

## The best practices baked in from template 1

Everything here follows the same handful of habits, on purpose, from the first
file:

- **Parameterize everything estate-specific.** Image, size, storage, region, and
  namespace are inputs, not hardcoded values, so the same file deploys unchanged on
  any cloud.
- **Name for function.** Object names derive from an application slug and say what
  a thing *does* (`web`, `db`, `lb`), in lowercase kebab-case. No people, no
  mascots, no dates.
- **Reference tenancy, do not create it.** You deploy INTO a namespace your
  platform vends you. Provisioning a workload and owning a boundary are different
  jobs.
- **Right-size on purpose.** Boot disks and sizes are chosen, not inherited, so a
  deploy does not quietly spend quota you did not mean to.
- **Immutable images.** Pin the image to its ID, not a moving alias, so a deploy
  is reproducible.
