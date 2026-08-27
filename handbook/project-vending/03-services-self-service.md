# 03 - Namespace and supervisor-service self-service

This module gives a subset of your users the developer services portal (Virtual
Machine Service, Kubernetes, and the rest) and, where they need it, the ability to
create namespaces. It builds on module 02's rule: services self-service that must
stay own-only lives in a vended project per trust boundary.

## What the services portal actually is

The portal tiles (Virtual Machine, Kubernetes, Container, Virtual Machine Image,
Network, Volume, Database, Load Balancer) operate on the Kubernetes workload plane
inside a supervisor namespace. Reaching that plane is the whole of "can this user
self-serve services." Module 01 established the tiers; here is what each does for
this purpose, verified live:

| Project role | Sees namespaces (the switcher) | Uses the services portal in a namespace |
|---|---|---|
| `edit` | no (403) | no: this role has no workload plane at all |
| `view` | yes | read-only: list and get, no create or delete |
| `edit_adv` | yes, the project's namespaces | yes, full |
| `admin` | yes | yes, full, plus manages namespaces and bindings |

So the floor for services self-service is **`edit_adv`**. Bumping a user from `edit`
to `edit_adv` is a single ProjectRoleBinding change; nothing on the organization
side moves.

## Namespace toggling

"Switch between the namespaces I am a member of" is a property of `edit_adv` and up:
the namespace switcher lists the namespaces of the projects the user is a member of.
In a vended per-user project, that is exactly their own namespaces and no one
else's, which is the behavior you want. A user is never shown a namespace from a
project they are not a member of.

## Giving a user the ability to create namespaces

A Project Administrator (`admin`) holds the right to create namespaces, but the
create action has a second requirement that trips people up: the new-namespace form
reads three organization-gated catalogs, namespace classes, regions, and storage
classes. Without them the form is empty and a create fails. Deliver those catalogs
in one of two ways, both of which avoid any org-wide visibility:

1. **A narrow custom organization role.** Create a role that adds only the three
   catalog read rights on top of the Organization User baseline. That is exactly
   what `scripts/setup_catalogs_role.py` builds, once per organization:

   ```bash
   python3 scripts/setup_catalogs_role.py --name "Namespace Self-Service User"
   ```

   Assign it to the users who need the namespace-operator tier, or make it the role
   of a dedicated group. It grants no org-wide visibility and no project CRUD.

2. **Publish Namespace Self-Service to the project** (an organization-administrator
   action in the console), which delivers the same catalogs scoped to that project.

Either way, the user is then `admin` in their own project with the catalogs
available, and can create namespaces from the form or, better, by the API in the
next module.

## What you have decided by the end of this module

For each services-self-service group you now know:

- they are **Organization User** on the org side (never Administrator),
- they own a **vended project** (their trust boundary, per module 02),
- their project role is **`edit_adv`** for services use, or **`admin`** if they also
  create namespaces, in which case they also hold the **catalogs role** above.

Next: [04 - Project vending as-code](04-project-vending-as-code.md), which creates
that vended project and its first namespace by API.
