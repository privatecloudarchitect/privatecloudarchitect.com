# 00 - VCF Automation API fundamentals

Start here even if you have never called the VCFA API. By the end of this module
you will have authenticated and made your first read, and you will understand the
two surfaces every later step uses. The code is `scripts/vcfa.py`; read it beside
this page.

## The objects you will work with

Four containers, widest to narrowest:

- **Organization**: the tenant. One identity domain, one set of roles. Your users
  live here.
- **Project**: a governed home inside an organization. RBAC is granted per project.
  This is the object you will create programmatically.
- **Supervisor Namespace**: a workload home inside a project, backed by vSphere
  Supervisor. This is where the developer services (Virtual Machine Service,
  Kubernetes) actually run.
- **Deployment**: what a tenant gets when they request a catalog item. Owned by the
  requester.

## The two API surfaces

VCFA answers on two different API styles, and knowing which is which removes most
early confusion.

1. **cloudapi**, paths under `/cloudapi/1.0.0/`. This is the VMware Cloud Director
   lineage. Roles, rights, users, groups, and login sessions live here. It wants a
   versioned Accept header: `application/json;version=9.1.0`. List endpoints page,
   and the page size caps at 128.

2. **CCI, the Cloud Consumption Interface**, paths under `/cci/kubernetes/apis/`.
   This is a Kubernetes-style API. Projects, ProjectRoleBindings, and Supervisor
   Namespaces are Kubernetes objects here, each with `apiVersion`, `kind`,
   `metadata`, and `spec`. Plain `application/json`.

You will use cloudapi to log in and to manage roles, and CCI to create projects,
bind roles, and create namespaces.

## Authentication: the session token comes back in a header

This is the single most common thing a newcomer gets wrong, so it is worth stating
plainly. You authenticate with HTTP Basic auth to one endpoint, and the token you
use for everything after is a **response header**, not the response body:

```
POST https://<host>/cloudapi/1.0.0/sessions
  Authorization: Basic base64("<user>@<org>:<password>")
  Accept: application/json;version=9.1.0
```

A 200 comes back. Read the **`X-VMWARE-VCLOUD-ACCESS-TOKEN`** response header; that
string is your bearer token. Send it as `Authorization: Bearer <token>` on every
later call. HTTP header names are case-insensitive, so match them case-insensitively
when you read them (`vcfa.py` lowercases them for exactly this reason).

### Why a session login and not an OAuth API token

VCFA also issues OAuth-style API tokens, and for the reads and writes in this
solution either works. Use the session login anyway, for one reason: the
identity-management rights that let you import Active Directory groups and users
are present only on an interactive session login and are stripped from OAuth
grants. Standardizing on the session login means the same code path can also
onboard identities when you need it to.

For both flows in full, and the rule that chooses between them, see the handbook
chapter [The VCF Automation API](https://privatecloudarchitect.com/handbook/vcfa-api).

## Your first call

Set the four environment variables from `scripts/README.md`, then:

```bash
python3 scripts/vcfa.py
```

It logs in, calls `GET /cloudapi/1.0.0/sessions/current` to print who you are and
your organization roles, and lists the projects you can see via CCI. If that runs,
your authentication is correct and you are ready for module 01. If it raises "no
X-VMWARE-VCLOUD-ACCESS-TOKEN header," your credentials reached the server but login
failed; check the user, org, and password.

## The mental checklist you now carry

- Two surfaces: cloudapi for identity and roles, CCI for projects and namespaces.
- Log in with Basic auth, then read the bearer token from the response header.
- Prefer the session login, so identity onboarding stays available.
- cloudapi wants the versioned Accept header and pages at 128.

Next: [01 - The permission model](01-the-permission-model.md), where those roles
become a model you can grant by intent.
