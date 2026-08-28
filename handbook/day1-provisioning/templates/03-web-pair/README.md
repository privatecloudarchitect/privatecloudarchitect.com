# Template 3 (Walk): a load-balanced web pair

The application grows up here. Template 2 was one web server reachable only from
inside the namespace. This is two identical servers behind one external front door:
reachable from outside, and able to survive losing a VM.

**File:** [`web-pair.blueprint.yaml`](./web-pair.blueprint.yaml)

## The one new concept

**Composition: more than one of a thing, and a front door that spreads traffic
across them.** You already know how to declare a VM and configure it. This template
declares that VM twice, gives both the same label, and puts a `LoadBalancer` in
front that selects on that label. The selector is the wiring; the pool is anything
that carries the label.

## What changed from template 2

| Change | What it is |
|---|---|
| A second VM | `Web01` and `Web02` are the template-2 VM with ordinals `-01` and `-02`, sharing one bootstrap Secret so they are configured identically. |
| A shared pool label | Both carry `app: <app>-web`. That single label is what makes them a pool. |
| A `LoadBalancer` resource | A `VirtualMachineService` of `type: LoadBalancer`, selecting `app: <app>-web`. NSX Advanced Load Balancer spreads connections across every VM that matches. |

The cloud-init and the VM shape are unchanged from template 2. What is new is having
two, and fronting them.

## How the pieces connect

```
Browser -> <app>-lb (LoadBalancer, external IP) -> { <app>-web-01, <app>-web-02 }
                         selects app=<app>-web  ---^
```

Two ideas are worth taking from this:

- **The selector, not a list, defines the backends.** The load balancer never names
  the VMs. It matches a label. Add a `Web03` with the same label and it joins the
  pool with no change to the load balancer. Remove one and traffic simply stops
  going there. This is how scaling and healing stay decoupled from the front door.
- **Identical servers share one bootstrap.** Both VMs reference the same Secret, so
  there is one place to change their configuration, not two.

The page each server serves prints its own hostname, so when you open the front-door
IP and refresh, you can watch the name change as the load balancer alternates between
`web-01` and `web-02`. That is the pair and the balancing, proven by eye.

## When you need more than L4

This template balances at the connection level (L4), which is what a plain web pair
needs. When you need path-based routing, sticky sessions, or TLS termination at the
application layer, the common move is to add a small proxy VM (HAProxy is typical) in
front of the web VMs and point the LoadBalancer at the proxy. It is the same shape
with one more tier, not a redesign.

## Before you deploy

Fill the inputs this template marks required (the ones with no default): the target
namespace, the region, the VM image, and the storage class. Each carries its
discovery command in its description, and
[00-reaching-the-supervisor](../../00-reaching-the-supervisor.md) collects those
commands in one place. If you cannot yet run `kubectl get supervisornamespaces`,
start with that precursor.

## Deploy it

Same paths as before. The form is the same as template 2 (one deployment now brings
up two VMs and a load balancer). Supply your estate's namespace, image, and storage
class as always.

## What "working" looks like

```
kubectl get virtualmachine -n <namespace> -l app=<app_name>-web       # two VMs, Running
kubectl get virtualmachineservice <app_name>-lb -n <namespace> \
  -o jsonpath='{.status.loadBalancer.ingress[0].ip}'                  # the external IP
# open http://<that-ip>/ and refresh a few times
```

Two Running VMs, a front-door IP, and a hostname that changes as you refresh: the
tier is up and balancing.

## Graduate to template 4

Every VM so far has been stateless and interchangeable. Real applications keep
state, and the tiers are rarely all the same kind of thing. **Template 4** is the
hybrid: a database on a VM and a web/app tier in containers, coexisting in one
namespace. It is where a virtual machine and Kubernetes stop being separate worlds.

Next: [`../04-hybrid-3tier/`](../04-hybrid-3tier/)
