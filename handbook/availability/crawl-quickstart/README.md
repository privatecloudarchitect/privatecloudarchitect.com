# Reachability, the crawl: a fleet you can see in an afternoon

The smallest first step in availability monitoring, done properly. One managed list of addresses, one
Ping Adapter instance, one picture of what answers and what does not. It covers everything with an IP:
virtual machines, host management interfaces, and the appliances and network equipment vCenter cannot
see. That last part is the point. Object-ping only works on vSphere objects, so it can never reach a
switch, a PDU, or a storage controller. The Ping Adapter can, which is why it, not object-ping, is the
crawl primitive for a mixed fleet.

This is the L1 layer, the reachability floor, of the five-layer availability model. It is a genuine
quick win on its own, and it is the on-ramp: nothing here is undone by the Walk and Run stages that
add depth on top.

## Before you start

- VCF Operations 9.1, with the Ping Adapter activated (you already have this).
- An api-token, minted in the operations console under Administration, for the standalone client.
- A collector group whose collector can route to the addresses you want to check.

## What is in this bundle

| File | What it is |
|---|---|
| `checks.example.yaml` | The declarative source you edit. Copy it to `checks.yaml`. |
| `reconcile_checks.py` | Converges one Ping Adapter instance to `checks.yaml`. Dry-run by default. |
| `opslib.py` | The standalone Ops client it uses (stdlib only, no SDK). |
| `import/reachability-checks.import.zip` | One view: every check with its packet loss and latency. |

## Step 1 - move your list into `checks.yaml`

If you started the way most teams do, with a short comma-separated list typed into a single adapter
instance by hand, this is the upgrade. Copy `checks.example.yaml` to `checks.yaml` and put your
endpoints under `checks:`. Each address is an IP, an FQDN, a **CIDR** (a whole subnet in one line), or
a **range**. Gear is where the CIDR earns its keep: a `/24` of switches is one line, not 254.

```yaml
checks:
  - address: 192.0.2.0/24              # the switch management subnet, in one line
  - address: 198.51.100.11             # a storage controller
  - address: esx-01.mgmt.example.com   # a host management interface, by name
```

## Step 2 - converge (dry-run first)

```
export OPS_HOST=ops.example.com  OPS_API_TOKEN=<your-token>  OPS_INSECURE=1   # OPS_INSECURE for a self-signed CA

python reconcile_checks.py             # DRY-RUN: the exact plan, no changes
python reconcile_checks.py --execute   # create or update the instance, start it, wait for the checks
python reconcile_checks.py --status     # read-only: every check with its loss and latency
```

The reconciler is level-triggered and idempotent: run it as often as you like, and it converges the
instance to whatever `checks.yaml` says. It touches only the instance you named, and it prunes the
check objects for addresses you remove. `--status` is your first look at the pulse, in the terminal,
with zero extra setup.

## Step 3 - see it in the console

Import `import/reachability-checks.import.zip` (Views > Manage > Import). The view lists every check
with its packet loss and latency, gear included, colored so a red row reads at a glance. Drop it on any
dashboard, or read it on its own. This view is deliberately dependency-free: it reads the raw check
stats, so it needs no super metrics and no other content to render.

## Two things that will cost you an afternoon if you miss them

- **`unique_name` must be a plain slug** (`[a-z0-9_]`). A space or punctuation there makes the adapter
  silently load zero checks while its heartbeat stays green. The reconciler derives a safe slug if you
  omit it.
- **Removing an address does not delete its check object.** The ping stops, but the object lingers, red
  and still counted. The reconciler prunes these on its next run, which is why you converge with the
  tool rather than editing the adapter by hand.

## Scaling past one line per host

Two paths, both from the same `checks.yaml`, and both honor CIDRs and ranges so a subnet is one line:

- `reconcile_checks.py --execute` sets the adapter's address list over the API. Nothing to upload.
- `reconcile_checks.py --config-file` writes VMware's native address-list XML. Upload it via
  Administration > Management Packs Configuration and point the adapter's `conf_file_name` at it. Use
  one path or the other, not both.

For very large fleets, shard the address set across several instances on a collector group and tune the
packet count and interval for cycle time.

## Where this sits on the map, so you build in the right direction

Reachability is the floor, not the whole promise. A machine that answers ping with a hung database is
up to a ping monitor and failing in reality, so treat L1 as the on-ramp, not the destination:

- **Crawl (here):** reachability across the whole mixed fleet, gear included, from one list.
- **Walk:** object-ping for single-homed VMs, where the metric lands on the vSphere object itself for a
  per-object heatmap; the native L2 platform floor for hosts (connection and power state, no ping
  needed); L3 guest liveness through VMware Tools, which covers the workload interior ping cannot reach.
- **Run:** the full promise, an SLI with a target, a window, and an error budget, priced by each
  workload's posture.

## What not to do

- **Do not object-ping a host.** Every NSX-prepared ESXi host carries a link-local interface that never
  answers, which pins its ping to a permanent, false 100 percent loss. A host's reachability comes from
  its management IP here, or better, from the native L2 floor at Walk.
- **Do not try to object-ping the gear.** There is no vSphere object to enable it on. The Ping Adapter
  is the only tool that reaches a switch or a PDU, and it is the one this crawl uses.
