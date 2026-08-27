# Tenant self-service with own-only isolation, on VCF Automation 9.1

A complete, from-zero solution to one use-case:

> "I need to keep users from deleting resources that are not theirs as they use VCF
> Automation, and I also need to give a large subset of those users namespace and
> supervisor service self-service. If the answer involves creating projects, it has
> to be programmatic and as-code."

This folder takes you from not knowing the VCF Automation API to operating that
pattern at scale, as-code. It assumes no prior VCFA API experience: module 00
teaches authentication and the two API surfaces from scratch, and every later step
builds on it. Everything here is generic. Fill in your estate's values and it runs
on your appliance.

## The answer

VCFA access is decided on two planes, and the developer services portal lives on
only one of them. Own-only isolation on the deployment plane (a user manages only
their own deployments) is native and scales with one group binding and one policy.
But the services portal runs on the Kubernetes workload plane, which has no
per-user ownership, so services self-service that must stay own-only cannot live in
a shared project. The unit of isolation for those users is therefore a project per
user or per team, and that is why the answer includes project creation. Creating a
project and its first namespace is three API calls with no console step, so "one
project per tenant" is a script you run, not a ticket you file.

## The learning path (read in order)

| Module | You learn to |
|---|---|
| [00 - VCFA API fundamentals](00-vcfa-api-fundamentals.md) | Authenticate to VCFA and make your first read. The two API surfaces, the session token that comes back in a header, and why session login matters. |
| [01 - The permission model](01-the-permission-model.md) | Read any access outcome as two roles on two planes, and grant by intent using the six-tier ladder. |
| [02 - The isolation answer](02-the-isolation-answer.md) | Why the workload plane forces a project per trust boundary, and when a shared project is still correct. |
| [03 - Namespace and supervisor-service self-service](03-services-self-service.md) | Give a subset of users the services portal and namespace creation, with the exact roles and the one custom role it needs. |
| [04 - Project vending as-code](04-project-vending-as-code.md) | Vend a project and its first namespace in three API calls, and run it per tenant with the scripts here. |
| [05 - Operate and verify](05-operate-and-verify.md) | Govern at scale, keep the deployment plane own-only with the group pattern, and prove the isolation holds. |

## What is in this folder

```
README.md                     this page
00..05-*.md                   the learning path, zero to mastery
references.md                 the public field note, handbook chapter, and proof harness
admin-reference.html          a single-page, printable admin reference (open in a browser or print to PDF)
scripts/
  README.md                   prerequisites, the four environment variables, and safety
  vcfa.py                     a minimal, commented VCFA API client (the API fundamentals as code)
  vend_project.py             create a tenant project and its first namespace, entirely by API
  e2e_tenant_setup.py         the full onboarding top to bottom: auth, project, AD group import, bind, namespace
  setup_catalogs_role.py      create the custom org role that lets a namespace operator use the create form
  verify_scope.py             log in as a tenant and confirm exactly what they can see
```

## How to use it

1. Work through modules 00 and 01 once, to build the model. They are short.
2. Decide, per group of users, which of two shapes they need (module 02 makes the
   call for you): deployment-plane own-only in a shared project, or services
   self-service in a vended project.
3. Run the scripts in `scripts/` against your estate for the vended-project shape,
   and follow the group-pattern steps in module 05 for the shared-project shape.
4. Verify with `scripts/verify_scope.py` and the companion proof harness in
   [references.md](references.md).

Every claim in this folder was proven on a running VCF Automation 9.1 estate. The
public teaching version of the vend is field note 03 on privatecloudarchitect.com,
and the runnable isolation proof is the companion harness; both are linked in
[references.md](references.md).
