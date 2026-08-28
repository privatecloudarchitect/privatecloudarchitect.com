# Template 2 (Crawl): a VM that configures itself with cloud-init

Template 1 gave you a VM that boots and sits there. This one has it come up
already doing its job: on first boot it creates a login user, installs nginx, and
serves a page. The tool for that is cloud-init, and it is the same idea you will
use to configure every VM from here on.

**File:** [`vm-cloud-init.blueprint.yaml`](./vm-cloud-init.blueprint.yaml)

## The one new concept

**cloud-init: day-0 configuration, declared separately from the VM.** The blueprint
still declares the infrastructure (a VM of this size, from this image). Cloud-init
declares what the guest OS does the first time it boots. Keeping the two apart lets
you resize or re-image the VM without rewriting its setup, and revise its setup
without touching the VM.

## What changed from template 1

Two additions, nothing else:

| Change | What it is |
|---|---|
| A new `Secret` resource | Holds the cloud-init `user-data` (the `#cloud-config` document). It travels as a Secret because it can carry credentials, and the VM references it by name. |
| A `spec.bootstrap.cloudInit` block on the VM | Points the VM at that Secret by name and key. The Supervisor injects the user-data, and cloud-init runs it on first boot. |

If a line in the blueprint is uncommented, you read it in template 1.

## What the cloud-init does

A small, realistic first boot:

- **Creates a login user** (`admin_username`) with passwordless sudo, so you have a
  way in. Its password comes from the `admin_password` input, marked `encrypted` so
  the platform stores it as a secret.
- **Installs and starts nginx and chrony** (a web server and time sync).
- **Serves a page** that names the host, so one look confirms the whole thing ran.

Two habits are built into that config and worth carrying forward:

- **cloud-init is idempotent.** It runs its modules once, keyed to the instance, so
  a bootstrap is the state the VM reaches, not a script that fires every boot.
- **Credentials are referenced, not echoed.** The password is consumed inside
  cloud-init and never emitted in an output. For anything past a lab, prefer an SSH
  key and source the secret from a vault.

There is one watch point in the config, called out in a comment: on Ubuntu a
background updater can hold the package lock at first boot, and an install that
races it waits or fails with a "could not get lock" message. The bootstrap stops
those timers before installing so the two do not collide. This is designed
behaviour meeting a first-boot timing window, not a defect.

## Before you deploy

Fill the inputs this template marks required (the ones with no default): the target
namespace, the region, the VM image, and the storage class. Each carries its
discovery command in its description, and
[00-reaching-the-supervisor](../../00-reaching-the-supervisor.md) collects those
commands in one place. If you cannot yet run `kubectl get supervisornamespaces`,
start with that precursor.

## Deploy it

Same two paths as template 1 (catalog or API), with two new form fields: the admin
username and password. You still supply your estate's namespace, image, and storage
class (the discovery commands are in each input's description).

## What "working" looks like

The VM has no external front door yet, so you reach it from inside. Forward its web
port to your workstation and open the page:

```
kubectl get virtualmachine <app_name>-01 -n <namespace> -o wide   # Running, with an IP
kubectl port-forward -n <namespace> vm/<app_name>-01 8080:80      # then open http://localhost:8080/
```

A page that names the host means cloud-init ran, nginx installed, and the service
started, all from the bootstrap you supplied.

## Graduate to template 3

You have one web server, reachable only from inside the namespace. **Template 3**
gives it a real front door and a sibling: two web VMs behind a `LoadBalancer`, so
the application is reachable from outside and survives losing one VM. That is the
step from a single server to a load-balanced tier.

Next: [`../03-web-pair/`](../03-web-pair/)
