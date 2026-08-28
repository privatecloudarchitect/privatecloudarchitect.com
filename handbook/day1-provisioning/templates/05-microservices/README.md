# Template 5 (Run): a microservices application on Kubernetes

The capstone. Template 4 ran two tiers as containers beside a database VM. This one
is fully container-native: a set of small services, each doing one job, running on a
VKS Kubernetes cluster and talking over Kubernetes networking. No application VMs.

**Files:**
- [`microservices.blueprint.yaml`](./microservices.blueprint.yaml) - the VKS cluster
- [`microservices.k8s.yaml`](./microservices.k8s.yaml) - the services, applied into it

## The one new concept

**Many small services, composed by the cluster.** Instead of one application in a
VM, or a few tiers, a microservices app is a set of independent services. Each is
its own Deployment, scaled and released on its own schedule. They find each other by
Kubernetes DNS, so nothing hardcodes an address, and only the services that need to
face the outside world are exposed. The cluster does the composition; your job is to
declare the services and how they connect.

## What changed from template 4

Less infrastructure, more Kubernetes. The blueprint provisions only the VKS cluster,
the same resource you learned in template 4. Everything else is in the Kubernetes
manifest: three services (a frontend, a backend, a cache), their Deployments and
Services, and one LoadBalancer for the frontend. The centre of gravity has moved
from the platform to the application, which is what "container-native" means.

## How the services connect

```
Browser -> frontend-lb (LoadBalancer) -> frontend -> backend -> cache
                                          [ all ClusterIP DNS inside the cluster ]
```

Three ideas carry the whole model:

- **DNS, not addresses.** The frontend calls `http://backend:80`, the backend calls
  the cache at `cache:6379`. Kubernetes resolves those names to the Services. Scale a
  service or replace its Pods and callers never notice.
- **Exposed by exception.** Only the frontend has a `LoadBalancer`. The backend and
  cache are ClusterIP, reachable only from inside the cluster. Nothing faces the
  network that does not need to.
- **Independent Deployments.** Each service scales and ships on its own. That
  independence is the reason to choose microservices, and the reason they are more
  moving parts to operate.

## Before you deploy

Fill the inputs this template marks required (the ones with no default): the target
namespace and the storage class for the Kubernetes nodes. Each carries its
discovery command in its description, and
[00-reaching-the-supervisor](../../00-reaching-the-supervisor.md) collects those
commands, including how to fetch the VKS cluster's kubeconfig for part 2. If you
cannot yet run `kubectl get supervisornamespaces`, start there.

## Deploy it, in two parts

**Part 1, the cluster (the blueprint).** Deploy `microservices.blueprint.yaml`. It
brings up the VKS cluster and takes a few minutes to become ready.

**Part 2, the services (kubectl).** Point kubectl at the VKS cluster (your platform
documents the login), then:

```
kubectl apply -f microservices.k8s.yaml
```

Replace the frontend and backend images with your own services first; the cache runs
as-is on a real Redis image.

## What "working" looks like

```
kubectl get cluster <app_name>-<env>-vks -n <namespace>    # Provisioned (against the Supervisor)
# then, against the VKS cluster:
kubectl get pods                                           # frontend, backend, cache Running
kubectl get svc frontend-lb \
  -o jsonpath='{.status.loadBalancer.ingress[0].ip}'       # the external IP
# open http://<that-ip>/
```

A reachable frontend whose calls reach the backend and cache means the mesh of
services is up and composing correctly.

## You have run the whole path

From one virtual machine that just boots, to a VM that configures itself, to a
load-balanced pair, to a hybrid of a database VM and containers, to a microservices
application on Kubernetes. Every step was the previous one plus a single new idea,
and the dialect never changed underneath you: the same `CCI.Supervisor` shape carried
you from a lone VM to a Kubernetes cluster.

Where to go next:

- **Governance and isolation** - the `project-vending` companion shows how the
  namespaces you deployed into are vended and kept isolated per tenant.
- **A reference at scale** - the Google "Online Boutique" sample runs a dozen
  microservices on a VKS cluster with the same pattern shown here.
