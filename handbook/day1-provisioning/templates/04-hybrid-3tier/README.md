# Template 4 (Walk to run): a hybrid application, VM database + container tiers

Every template so far used virtual machines only. Real applications mix kinds:
some tiers are happiest on a VM, others in containers. This one is the hybrid, a
PostgreSQL database on a VM beside a web and app tier in containers, all in one
Supervisor namespace.

**Files:**
- [`hybrid-3tier.blueprint.yaml`](./hybrid-3tier.blueprint.yaml) - the infrastructure (DB VM + VKS cluster)
- [`app-and-web.k8s.yaml`](./app-and-web.k8s.yaml) - the application, applied into the cluster

## The one new concept

**A virtual machine and a Kubernetes cluster as peers in one namespace.** This is
the capability a Supervisor namespace adds: you do not run VMs in one place and
Kubernetes in another and bridge them. A database VM and a full Kubernetes cluster
sit in the same tenancy, on the same network, under one quota and one policy, and a
container reaches the database directly.

Match the tier to the substrate: a database wants stable storage and a long life,
which a VM gives it; web and app tiers are stateless and interchangeable, which is
what containers do well. The hybrid lets each tier live where it fits.

## What changed from template 3

A new kind of resource joins the VMs you already know:

| Resource | What it is |
|---|---|
| PostgreSQL VM | The template-2 VM pattern, with cloud-init installing Postgres and creating the app database instead of nginx. |
| VKS `Cluster` | One resource that asks the Supervisor for a full Kubernetes cluster (its own control plane and worker nodes). Your containers run here. |

The application itself (web and app tiers, the front door) is Kubernetes YAML you
apply into the cluster after it exists. That two-part shape, blueprint for the
platform then kubectl or GitOps for the app, is how these run in practice.

## How the boundary is crossed

```
Browser -> web-lb (LoadBalancer) -> web tier -> app tier ----(VPC IP :5432)----> Postgres VM
           [ ------------------ VKS Kubernetes cluster ------------------ ]      [ VM Service ]
                                                          both in one Supervisor namespace
```

Inside the cluster, tiers find each other by Kubernetes DNS (`web` calls
`app.<ns>.svc.cluster.local`). Reaching the database is the cross-boundary step: the
DB runs on a VM in a different Kubernetes cluster, so guest-cluster DNS does not
resolve it. The Pod connects to the VM by its network IP on 5432, which works because
the VKS nodes and the DB VM share the namespace's VPC network. You supply that IP as
configuration, so the app image stays free of environment specifics.

## Deploy it, in two parts

**Part 1, the infrastructure (the blueprint).** Deploy `hybrid-3tier.blueprint.yaml`
as in the earlier templates. This brings up the database VM and the VKS cluster. The
cluster takes several minutes to become ready (it is provisioning real nodes).

**Part 2, the application (kubectl).** Once the cluster is ready:

```
# 1. Get a kubeconfig for the VKS cluster (your platform documents the exact command;
#    it is typically a kubectl vsphere / vcf login against the cluster, or a
#    generated secret). Point kubectl at the VKS cluster, not the Supervisor.

# 2. Read the database VM's namespace IP:
kubectl get vm <app_name>-db-01 -n <namespace> \
  -o jsonpath='{.status.network.primaryIP4}'

# 3. In app-and-web.k8s.yaml, set DB_HOST to that IP and DB_PASSWORD to the value you
#    gave the blueprint, then apply it INTO the VKS cluster:
kubectl apply -f app-and-web.k8s.yaml
```

## What "working" looks like

```
kubectl get vm <app_name>-db-01 -n <namespace> -o wide          # DB VM Running
kubectl get cluster <app_name>-<env>-vks -n <namespace>          # cluster Provisioned
# then, against the VKS cluster:
kubectl get pods                                                 # web and app Running
kubectl get svc web-lb -o jsonpath='{.status.loadBalancer.ingress[0].ip}'   # front-door IP
```

A front-door IP that serves a page whose app tier can read the database means the
whole hybrid path is live: browser to web to app to a database on a VM, across the
container-to-VM boundary, inside one namespace.

## Graduate to template 5

Here two tiers were containers and one was a VM. **Template 5** goes fully
container-native: a microservices application, many small services on a VKS cluster,
talking to each other over Kubernetes networking. It is the run stage, and it reuses
the VKS cluster you just learned to provision.

Next: [`../05-microservices/`](../05-microservices/)
