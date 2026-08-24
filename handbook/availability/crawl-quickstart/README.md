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

- VCF Operations 9.1, with the Ping Adapter activated.
- A collector group whose collector can route to the addresses you want to check.

## What is in this bundle

| File | What it is |
|---|---|
| `checks.example.yaml` | The declarative source you edit. Copy it to `checks.yaml`. |
| `reconcile_checks.py` | Converges one Ping Adapter instance to `checks.yaml`. Dry-run by default. |
| `opslib.py` | The standalone Ops client it uses (stdlib only, no SDK). |
| `import/reachability-checks.import.zip` | One view: every check with its packet loss and latency. |

The view import is useful whichever way you configure the checks. The three tool files support the
scripted option below; the console option uses only the view import.

## Configure the checks: two ways

Two ways to put addresses under monitoring. Both drive the same Ping Adapter instance and the same
address list, so you can begin in the console and adopt the file-driven path later without redoing
anything.

### Option 1: in the operations console

Open your Ping Adapter instance, or create one, and enter your endpoints in its address list. VMware's
"Configuring Ping Adapter Instances," in the 9.1 configuration guide, walks the exact fields and their
supported value ranges. Pick a collector group whose collector can route to the addresses, name the
instance, and populate the list.

The address list carries more than one IP per line. An entry can be an IP, an FQDN, a **CIDR** (a whole
subnet at once), or a **range**, so a `/24` of switches is a single line rather than 254. That keeps a
list you maintain by hand workable well past the point where one row per address would become unwieldy.

This is the quickest way to a first picture, and it needs nothing beyond the console. Both gotchas below
apply here; the second one, a removed address leaving its check object behind, is manual housekeeping on
this path, and the usual reason a growing list moves to Option 2.

### Option 2: converge from a file

When the list outgrows hand-editing, treat `checks.yaml` as the single source of truth and let
`reconcile_checks.py` converge the instance to it. It is level-triggered and idempotent: run it as often
as you like, it touches only the instance you name, and it prunes the check objects for addresses you
remove. This path also needs an api-token, minted in the operations console under Administration.

Copy `checks.example.yaml` to `checks.yaml` and list your endpoints, using the same grammar as above:

```yaml
checks:
  - address: 192.0.2.0/24              # the switch management subnet, in one line
  - address: 198.51.100.11             # a storage controller
  - address: esx-01.mgmt.example.com   # a host management interface, by name
```

Then converge, dry-run first:

```
export OPS_HOST=ops.example.com  OPS_API_TOKEN=<your-token>  OPS_TLS_VERIFY=false   # for a self-signed CA

python reconcile_checks.py             # DRY-RUN: the exact plan, no changes
python reconcile_checks.py --execute   # create or update the instance, start it, wait for the checks
python reconcile_checks.py --status    # read-only: every check with its loss and latency
```

`--status` is your first look at the pulse in the terminal, with zero extra setup. To push a large
address set, either let `--execute` set the list over the API (nothing to upload), or run `--config-file`
to write VMware's native address-list XML, upload it via Administration > Management Packs Configuration,
and point the adapter's `conf_file_name` at it. Use one path or the other, not both.

## See it in the console

**Import it.** Views > Manage > Import, and choose `import/reachability-checks.import.zip`.

**Confirm it landed.** The success message does not name what it wrote, so confirm the import directly:
return to **Views > Manage** and search the list for **Reachability - Ping Checks**. Finding it there is
the proof it imported. The view is global, so anyone on the instance can use it.

**See the data.** A view is a table definition, not a dashboard: it renders only when pointed at a
subject. This view's subject is the ping checks, so point it at the object that owns them, the Ping
Adapter instance this crawl configured. The reliable path is a dashboard **View** widget: add one, assign
it **Reachability - Ping Checks**, and set its input object to that Ping Adapter instance. The widget then
lists every check beneath it, one row each, with its worst-in-cycle packet loss and latency, gear
included, colored so a red row (an endpoint the collector could not reach) reads at a glance. The same
view is offered anywhere you can browse an object's own views.

The view is deliberately dependency-free, reading the raw check stats, so it needs no super metrics and no
other content to render. For the same picture without the console, `reconcile_checks.py --status` prints
each check's loss and latency in the terminal.

## Gotchas worth knowing

- **`unique_name` must be a plain slug** (`[a-z0-9_]`). A space or punctuation there makes the adapter
  silently load zero checks while its heartbeat stays green. The reconciler derives a safe slug for you;
  if you create the instance in the console, set it deliberately.
- **Removing an address does not delete its check object.** The ping stops, but the object lingers, red
  and still counted. The reconciler prunes these on its next run; in the console, delete the stale check
  object yourself.

## Scaling to a large fleet

CIDRs and ranges already fold whole subnets into single lines, on either path. For a very large fleet,
shard the address set across several instances on a collector group, and tune the packet count and
interval for cycle time.

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
