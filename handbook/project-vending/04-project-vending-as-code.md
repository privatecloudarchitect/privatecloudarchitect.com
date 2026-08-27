# 04 - Project vending as-code

Project creation is the isolation unit (module 02), so it has to be cheap and
repeatable. It is: a project and its first namespace stand up in three API calls
with no console step. This module is that vend, by hand so you understand it, then
as one script you run per tenant.

## The three calls

All three go to the CCI API under `/cci/kubernetes`, with the bearer token from
module 00, as an account holding the organization-level project-management right.

### 1. Create the project

```
POST /cci/kubernetes/apis/project.cci.vmware.com/v1alpha2/projects
{ "apiVersion": "project.cci.vmware.com/v1alpha2", "kind": "Project",
  "metadata": { "name": "checkout-team" },
  "spec": { "description": "Vended project for checkout-team." } }
```

### 2. Bind the owner, and the operators group

One ProjectRoleBinding per subject. Users bind by bare name; groups bind by name
with a trailing marker. Choose the owner's role by tier: `edit_adv` for a services
owner, `admin` if they also manage namespaces.

```
POST .../authorization.cci.vmware.com/v1alpha1/namespaces/checkout-team/projectrolebindings
{ "apiVersion": "authorization.cci.vmware.com/v1alpha1", "kind": "ProjectRoleBinding",
  "metadata": { "name": "cci:user:alice", "namespace": "checkout-team" },
  "roleRef": { "apiGroup": "authorization.cci.vmware.com", "kind": "ProjectRole", "name": "edit_adv" },
  "subjects": [ { "kind": "User", "name": "alice" } ] }
```

Repeat for the operators group, so your platform team keeps administrative reach:
`metadata.name` is `cci:group:platform-admins`, `roleRef.name` is `admin`, and the
subject is `{ "kind": "Group", "name": "platform-admins@" }` (note the trailing
`@` on group names).

### 3. Create the first namespace

This is the call that used to fight back. Only two spec fields are required by the
API, `className` and `regionName`; everything else is optional and depends on how
your supervisor is networked. The example below shows the optional fields in place so
you can see where they go. Drop the ones your estate does not use (the table after it
says which is which).

```
POST .../infrastructure.cci.vmware.com/v1alpha3/namespaces/checkout-team/supervisornamespaces
{ "apiVersion": "infrastructure.cci.vmware.com/v1alpha3", "kind": "SupervisorNamespace",
  "metadata": { "generateName": "checkout-prod-us-west-1-", "namespace": "checkout-team" },
  "spec": { "className": "large",
            "regionName": "<your-region>", "vpcName": "<your-vpc>",
            "segName": "<your-service-engine-group>",
            "classConfigOverrides": { "zones": [ { "name": "<your-zone>",
              "cpuLimit": "2000M", "cpuReservation": "0M",
              "memoryLimit": "4000Mi", "memoryReservation": "0Mi" } ] } } }
```

Then poll `GET .../supervisornamespaces/<derived-name>` until `status.phase` reads
`Created`.

## Which fields are required, and which depend on your estate

Read from the live `SupervisorNamespace` CRD (`v1alpha3`), only `className` and
`regionName` are required. The rest are optional at the schema level, though your
supervisor's networking can make one necessary at create time. When in doubt, read
the values from a namespace that already works (`GET` an existing `supervisornamespace`
and copy its `spec`) and pass only the fields that namespace carries.

| Field | Required? | What it is |
|---|---|---|
| `spec.className` | Always | The namespace class, its default CPU, memory, and storage envelope. |
| `spec.regionName` | Always | A region that exists on the organization. No per-project console step is needed. |
| `metadata.generateName` | In practice | The name is derived, not fixed (see below). |
| `spec.vpcName` | Estate-dependent | The NSX VPC the namespace's network is carved from. Present where the supervisor uses VPC networking. |
| `spec.segName` | Estate-dependent | The load-balancer service engine group (see below). |
| `spec.classConfigOverrides.zones[]` | Optional | Per-zone CPU and memory overrides. Omit to inherit the class defaults. |
| `spec.description` | Optional | Free text. |

### The two things a newcomer gets wrong

A fresh project's namespace create can fail with an opaque `Validation failed`, and
the reasonable read is that the project lacks a region. It almost never does; the
region only needs to exist on the organization. The real cause is one of these two:

1. **Use `generateName`, not a fixed `metadata.name`.** The resource derives its own
   name and appends a suffix; a fixed name is rejected. If you create with a manifest
   and `kubectl`, use `kubectl create` (which supports `generateName`), not `kubectl
   apply` (which keys on a fixed name). This one is universal.
2. **`segName` is conditional, include it only if your supervisor load-balances
   through NSX Advanced Load Balancer (Avi).** It names the Avi service engine group.
   It is not a schema-required field, but the backend controller rejects the create
   with "SEG is required" when the region's load balancing is registered through NSX
   ALB and you leave it out. A supervisor that does not use NSX ALB service engine
   groups has no `segName`, and you omit it. The tell is an existing working
   namespace: if its `spec` carries `segName`, yours needs it too.

This required-versus-optional split is read from the live CRD schema, and the vend was
proven end to end on freshly created projects.

## As one script

`scripts/vend_project.py` is the three calls, with the poll:

```bash
python3 scripts/vend_project.py \
    --project checkout-team --owner alice --owner-role edit_adv \
    --operators-group "platform-admins" \
    --region <your-region> --vpc <your-vpc> --seg <your-service-engine-group> \
    --zone <your-zone>
```

`--region` is required; `--vpc`, `--seg`, and `--zone` are optional and passed only
when your estate uses them (the script includes each spec field only when you supply
it). On a supervisor with no NSX Advanced Load Balancer service engine groups, the
minimal form is just `--project`, `--owner`, and `--region`. It creates the project,
binds the owner and operators, creates the namespace, and polls it to Ready, printing
each step. Run it once per tenant. It never deletes
anything, and it fails on a duplicate project name, so a re-run cannot silently
produce two tenants with the same name.

## At scale

Onboarding is a loop over this script with your tenant list. Each vend is seconds of
API work, so a project per trust boundary is affordable as the default. When you
want a request-and-approval gate in front of it (a tenant asks for a project, an
operator approves the vend), the same three calls sit behind the approval step;
that governed variant is a natural next build.

Next: [05 - Operate and verify](05-operate-and-verify.md), which handles the
deployment-plane half, governance, and proof.
