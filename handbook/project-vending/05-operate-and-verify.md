# 05 - Operate and verify

You can now vend an isolated services project (module 04). This module finishes the
picture: the deployment-plane half for users who do not need the services portal,
the one governance fact that catches every first design, how to scale, and how to
prove the isolation holds.

## The deployment-plane half: own-only without a project each

Not every user needs the services portal. Those who only consume the catalog belong
in a **shared project**, and there own-only is native and cheap. The group pattern:

- put the tenant's users in one directory group,
- bind that group to `edit` on the shared project (one ProjectRoleBinding),
- and, when you need to grant Day-2 actions, write one Day-2 action policy naming the
  group.

Because a group bound to `edit` does not pool visibility, every member sees and acts
on only their own deployments, with one binding and one policy for the whole tenant.
No per-user objects, no project per user. This is the right shape for a large body
of catalog consumers, and it composes with the vended-project shape: services users
get their own project, catalog-only users share one.

## The one governance fact that catches every first design

The moment you add your first **HARD Day-2 action policy** to a project, the project
flips from its permissive default to default-deny for every principal that no policy
names, project administrators included. An owner who held five actions on their own
deployments drops to zero the instant that first policy exists, unless a policy names
them.

The operational rule that follows: **ship the operators' grant in the same change as
the first tenant policy,** so the flip strands no one. Design your policy set to
include the operators' allow from the start, not as a follow-up.

## Scaling

- **Services users:** loop `vend_project.py` over your onboarding list. One project
  per trust boundary; the organization holds many thousands.
- **Catalog users:** the group pattern is constant cost per tenant (one binding, one
  policy) regardless of user count, because membership rides the directory group.
- **Adding a user later:** for the group-pattern tenants, it is a directory group
  membership change and nothing else. For a services user who needs their own
  project, it is one `vend_project.py` run.

## Verify

Prove the two halves separately.

### Scope, per principal

Run `scripts/verify_scope.py` as the tenant (set the `VCFA_*` variables to their
account). It prints the projects and namespaces that principal can see. A correct
services tenant sees only their own project and its namespaces, and a catalog-only
tenant on `edit` sees the shared project and gets a clean 403 on the workload plane,
which is the isolation floor working.

### The full Day-2 isolation matrix

For the deployment-plane proof (who can act on whose deployment, and the governance
flip in action), use the companion proof harness linked in
[references.md](references.md). It deploys one workload per user, runs the
actor-by-target matrix as live API calls, and includes the flip test that turns the
first HARD policy on and off so you can watch the regime change. It is the runnable
evidence behind this whole solution, and it leaves your estate as it found it.

## Mastery checklist

You have mastered this use-case when you can, without looking anything up:

- state why the services portal forces a project per trust boundary while catalog
  consumers share one,
- vend a project and its first namespace by API, saying why only `className` and
  `regionName` are required, why `generateName` (not a fixed name) is the field
  everyone trips on, and when `segName` is needed,
- grant any user their access by naming one organization role and one project role,
- name the three rights you must never give a self-service user,
- and predict what the first HARD policy does before you write it.

That is the whole solution: own-only isolation on both planes, services
self-service for the subset that needs it, and project creation as three lines of
script you run per tenant.

Back to the [README](README.md) or on to the sources in [references.md](references.md).
