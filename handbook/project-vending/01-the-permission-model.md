# 01 - The permission model

One idea makes every access outcome on VCFA predictable: access is decided by **two
roles on two planes**, not one. Hold that and the rest is bookkeeping.

## The two roles

- **The organization role** is the door. Organization User is the floor and defers
  to the project role. Organization Administrator sees every deployment in every
  project, an org-wide bypass. Self-service users are always Organization User.
- **The project role** is the center of gravity. It is a Kubernetes-side binding
  (a `ProjectRoleBinding`, module 04 shows the call) and it grants consumption
  inside one project. Four tiers, each with a console name and a short handle this
  solution uses thereafter:

  | Console name | Handle | Sees | On the workload plane |
  |---|---|---|---|
  | Project User | `edit` | own deployments only | no reach (this is the isolation floor) |
  | Project Auditor | `view` | all project deployments | read-only |
  | Project Advanced User | `edit_adv` | all project deployments | full, project-wide |
  | Project Administrator | `admin` | all, plus manages the project's RBAC and namespaces | full, project-wide |

## The two planes

Access travels on two surfaces with different controls. Keep them separate; blurring
them is where mistakes hide.

- **The deployment plane** (Automation): catalog items, deployments, and their
  **Day-2 actions** (power, resize, snapshot, delete). Visibility comes from the two
  roles; which actions a principal holds comes from **Day-2 action policies**. Day-2
  actions exist only on resources that define them: deployments, virtual machines,
  and disks. A raw Kubernetes object like a ConfigMap has none, so never reason about
  Day-2 actions from Kubernetes objects.
- **The Kubernetes workload plane** (the services portal): kubectl against the
  namespace endpoint. Access is the **project role tier alone**: `edit` gets nothing,
  `view` is read-only, `edit_adv` and `admin` get full read and write. Day-2 action
  policies do not apply here at all. Governance on this plane is Kubernetes-native
  RBAC.

The one sentence to carry: **the project role, alone, decides the workload plane; no
organization right opens the services portal for a Project User.**

## Grant by intent

Read the ladder by what the person needs to do, not by seniority.

| The user needs to | Organization role | Project role |
|---|---|---|
| Deploy from the catalog, manage only their own work | Organization User | `edit` |
| Read a project's resources without changing them | Organization User | `view` |
| Use the services portal and switch namespaces | Organization User | `edit_adv` |
| Create and manage namespaces and project bindings | Organization User plus the catalogs role | `admin` |
| Read the whole organization for audit, act on nothing | Organization Auditor | none |
| Administer the organization and vend projects | Organization Administrator | any |

## Never grant these to a self-service user

These are org-wide rights. Given to a tenant they defeat the whole model:

- `Projects: View` and `Projects: Manage` (the org-wide project surface, and the
  only way to create or delete projects, which is why project lifecycle stays an
  operator task, module 04).
- `Access Any Namespace: View` and `Access Any Namespace: Edit` (an org-wide
  namespace bypass).
- `Inventory: View` (org-wide deployment visibility, carried by Organization
  Administrator and Organization Auditor). This is why self-service users must be
  Organization User: Organization Administrator sees everyone's work.

## Where authority actually lives

Assign a project role by creating a `ProjectRoleBinding` on the CCI plane. You may
find REST membership arrays elsewhere that look writable; they are a read-only
projection that accepts a write, returns 200, and persists nothing. Bind on the CCI
plane (module 04 has the exact call, and `scripts/vcfa.py` has it as `bind_role`).

Next: [02 - The isolation answer](02-the-isolation-answer.md), where this model
resolves the first half of the use-case.
