# The isolation design: the reproducible proof

The runnable companion to
[The isolation design, assembled](https://privatecloudarchitect.com/handbook/isolation-design)
(and its dated proof,
[field note 01](https://privatecloudarchitect.com/notes/vcfa-access-control-three-factors)).
Declarative manifests plus one stdlib-only verifier that prove, on **your** VCF Automation 9.1
(All Apps) organization, that per-user isolation holds: two Project User (`edit`) members of one project each
operate their own deployment with full Day-2 authority and receive a hard 404 on each other's,
a Project Advanced User (`edit_adv`) sees project-wide, and the operators' group keeps reach through its own policy.

**Provenance:** proven on a live VCF 9.1 estate, 2026-08-11 (isolation matrix, real owned
deployments) and 2026-08-12 (workload plane). Every claim in the backing sheet carries its
evidence tier; this directory is the `repo` referent.

## What is here

```
manifests/00-project.yaml        the disposable test project
manifests/10-rolebindings.yaml   four ProjectRoleBindings, one declarative apply
manifests/20-namespace.yaml      the workload namespace (values copied from your estate)
blueprint/isolation-proof.blueprint.yaml      ConfigMap-only workload (owned, no VM capacity)
blueprint/isolation-proof-vm.blueprint.yaml   real-VM variant (adds resource-level Day-2 actions)
verify.py                        login / deploy / matrix / flip-on / flip-off
expected-output.md               what a passing run looks like
```

## Prerequisites

- A VCF Automation 9.1 (All Apps) org with an identity provider holding four test users
  (`user1..user4` by default) that share one password, plus one member of your operators' group.
- `kubectl` and Python 3 (standard library only).
- The environment variables listed at the top of `verify.py`. Nothing secret touches disk.

## The runbook (mirrors the sheet's six steps)

### 0. Point a kubectl context at the CCI org gateway

Project RBAC writes go to the Cloud Consumption Interface, not the REST membership arrays
(which accept a PATCH, return 200, and persist nothing):

```bash
kubectl config set-cluster vcfa-cci --server=https://<vcfa-fqdn>/cci/kubernetes
kubectl config set-credentials vcfa-cci-user --token=<access-token>
kubectl config set-context vcfa-cci --cluster=vcfa-cci --user=vcfa-cci-user
```

The access token comes from the session login (`POST /cloudapi/1.0.0/sessions`); the recipe is in
[the access-control chapter](https://privatecloudarchitect.com/handbook/access-control). On an
estate with a self-signed CA, add `--insecure-skip-tls-verify=true` to the `set-cluster` command
(the kubectl counterpart of `VCFA_INSECURE=1`).

### 1. Provision the project and all four bindings (one apply each)

```bash
kubectl --context vcfa-cci apply --server-side --dry-run=server -f manifests/00-project.yaml
kubectl --context vcfa-cci apply --server-side -f manifests/00-project.yaml
kubectl --context vcfa-cci apply --server-side -f manifests/10-rolebindings.yaml

# the bindings are real only if this lists them
kubectl --context vcfa-cci get projectrolebindings.authorization.cci.vmware.com -n rbac-lab
```

**Watch point:** plain `kubectl apply` is rejected on this plane ("Annotation updates are not
supported"); `--server-side` is required, and it is what makes the manifests idempotent. This is
the scalable core: N users are N documents in one file, applied in a single call.

### 2. Give the project a namespace, then publish the blueprint

**Watch point:** a brand-new project cannot host a Supervisor Namespace until a region and quota
are added to it; the create fails with an opaque validation error, and this resource does not
support `--dry-run=server`. Add the region first, then fill `manifests/20-namespace.yaml` by
copying the spec values from a namespace that already works on your estate and apply it the same
server-side way. Publish `blueprint/isolation-proof.blueprint.yaml` as a catalog item named
`isolation-proof` in the project (use the VM variant instead when you want resource-level Day-2
actions in the matrix).

### 3. Deploy one workload per user

```bash
python3 verify.py deploy    # user1 deploys "alpha", user2 deploys "beta"
```

Each user session-logs-in and requests the catalog item under their own token, so the platform
records them as owner. Authorization is state-independent: the matrix holds whether the
deployment is a ConfigMap marker or a real VM.

### 4. Run the matrix

```bash
python3 verify.py matrix
```

Every cell is a live HTTP call as that principal. Expected shape: `expected-output.md`.
A cross-user `not-visible(404)` is the design holding, not a failure.

### 5. The flip: prove what governance changes

```bash
python3 verify.py flip-on   # HARD policy: all actions, only the operators group
sleep 20                    # propagation: effects settle in ~16 to 20 seconds; do not read sooner
python3 verify.py matrix    # every unnamed principal reads 0-actions; operators keep theirs
python3 verify.py flip-off  # delete it; wait the same window; the permissive default returns
```

The first HARD Day-2 action policy ends the permissive default for every principal the project's
policies do not name, the project `admin` role included. That is why production ships the tenant
grant and the operators' grant in one change:
[`../day2-governance/`](../day2-governance/) holds the pair.

### 6. Teardown

Delete each deployment as its owner, then remove the bindings and the project:

```bash
kubectl --context vcfa-cci delete -f manifests/10-rolebindings.yaml
kubectl --context vcfa-cci delete -f manifests/00-project.yaml
```

**Watch point:** on the proven build, deleting a blueprint *version* returns HTTP 405; delete the
blueprint object itself (`DELETE /blueprint/api/blueprints/{id}`), which also removes its catalog
item.
