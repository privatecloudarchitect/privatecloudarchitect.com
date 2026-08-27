# 02 - The isolation answer

The use-case has two halves that pull against each other: keep users from touching
each other's resources, and give a large subset of them services self-service. This
module resolves the tension. The resolution decides how many projects you create,
so read it before you build anything.

## Two questions, because there are two planes

"Can a user touch another user's resource" has a different answer on each plane, so
answer it per plane.

### The deployment plane: own-only is native

On the deployment plane, a Project User (`edit`) sees and acts on only their own
deployments. Another user's deployment is not merely un-actionable, it is invisible
(a 404). This holds for members of the same group: a group bound to `edit` does not
pool visibility, so two members each see only their own. So for users who consume
through the catalog and do not need kubectl, own-only isolation is native and needs
no per-user objects. Module 05 shows the group pattern that scales it to a whole
tenant with one binding and one policy.

### The workload plane: there is no per-user ownership

The services portal (Virtual Machine Service, Kubernetes) does not run on the
deployment plane. It runs on the Kubernetes workload plane inside the supervisor
namespace, and that plane is different in one decisive way: **it has no per-user
object ownership.** Every `edit_adv` or `admin` member of a project resolves to one
shared namespace identity, so each of them can create, read, update, and delete
every object in the namespace regardless of who made it. This was proven on a live
estate: one user deleted an object another user had created.

Two things that look like they would carve a smaller boundary do not, and both were
tested live:

- A custom **organization** role does not help. Adding namespace-catalog rights to a
  Project User opens catalog visibility but leaves the workload plane closed; the
  services plane gate is the project role alone.
- A hand-authored **namespace RoleBinding** cannot pull in a user. The Supervisor's
  admission control allows a namespace holder to bind only service-account subjects,
  not users, so you cannot scope an outside user into one namespace this way. (You
  can delegate workload RBAC to service accounts; you cannot delegate tenant
  membership.)

So the smallest boundary the services plane offers is the **project**.

## The rule that follows

**A user who must self-serve the services portal and must not reach another user's
resources gets their own project.** Because services self-service needs `edit_adv`,
which is project-wide, own-only and services coexist only inside a project that
holds a single trust boundary: one person, or one team that already trusts each
other. Inside that project, "project-wide" and "own-only" are the same thing,
because the project holds only that tenant's work, and every other project is
invisible to them.

This is the second half of the use-case answered, and it is why the answer involves
creating projects: not as bureaucracy, but as the isolation unit itself.

## The project count is a function of trust boundaries

Do not count users; count trust boundaries.

- A ten-person team that trusts itself with each other's namespaces is **one**
  project.
- Ten engineers who must not touch each other's services are **ten** projects.
- A user who only deploys from the catalog and never needs kubectl does not need
  their own project at all; they belong in a shared project on the group pattern.

The scale worry is unfounded: a project is metadata plus a namespace, both created
by API in seconds (module 04), and the organization holds many thousands of them.

## Decision guide

Use this to route each group of users before you build:

| The group needs | Shape | How |
|---|---|---|
| Catalog deploys, own-only, no kubectl | one shared project, all on `edit`, the group pattern | module 05 |
| The services portal, own-only | a vended project per user or per team, owner on `edit_adv` | modules 03 and 04 |
| The services portal, plus namespace creation | same, owner on `admin`, plus the catalogs role | modules 03 and 04 |
| Org-wide read for audit | Organization Auditor, no project | module 01 |

Next: [03 - Namespace and supervisor-service self-service](03-services-self-service.md),
which builds the services half in detail.
