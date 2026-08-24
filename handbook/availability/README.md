# Availability and service levels: the layered dashboard

The runnable companion to
[Availability is a computed promise](https://privatecloudarchitect.com/handbook/availability).
One dashboard that reports availability as five layers of evidence and teaches the reading as it
reports: reachability checks, the platform floor, the guest and the VMware Tools sensor that
carries it, native Service Discovery, and the agent plane, closed by the target-and-error-budget
model.

**Starting smaller?** `crawl-quickstart/` is the reachability on-ramp for a team that wants a quick
win at low effort: one managed list of addresses on the Ping Adapter, covering virtual machines,
host management interfaces, and the appliances and network gear vCenter cannot see, with a
dependency-free view you can stand up in an afternoon. It is L1 of the five layers, and it grows
into this dashboard with nothing to undo.

**Provenance:** every view, column, band, and formula here was proven on a live VCF Operations
9.1 instance (2026-08-17 and 2026-08-18), including the import shape itself. The no-force
content-import recognition test on the reference instance reports the shipped packages as
`skipped N, failed 0`, which is the id-preserving proof.

## Where to start, and how to grow

You do not have to stand up all five layers to get value, and you should not try to on day one.
Availability rests on two signals that are co-primary; the other layers are depth on top of them.

- **Guest liveness (layer 3).** VMware Tools reports a guest availability figure for every VM it
  runs on, collected through vCenter with no network path to the guest. It is already there once
  Tools is current, it costs nothing to enable, and it covers the fleet interior, including the
  workloads no collector can route to.
- **Reachability (layer 1).** A ping check proves the path from a collector's vantage to an
  endpoint it can route to. It is the only signal that catches a live guest whose path is down,
  and the right measure for anything fronted by a load balancer.

Neither is sufficient alone, which is the whole point. Reachability by itself is a blind spot for a
workload-heavy estate: a fleet of applications on private, inbound-isolated networks reads a near
total ping loss while every one of them is healthy, because no collector routes to their interiors
(the front-door rule below). Liveness by itself misses the live guest whose path has failed. Run
both, and each covers the other's gap; a VM that reads healthy on one and failing on the other is a
specific finding, not noise.

The path that has worked:

1. **Prove the two signals.** Enable guest liveness across the fleet (it is free) and add
   reachability on a handful of endpoints that carry an explicit promise. Read them side by side.
2. **Grow to the fleet.** Declare the reachability set for real (a whole subnet is one line;
   [CONFIGURATION.md](CONFIGURATION.md) section 1 has the compact form), point every workload check
   at its load-balancer front door, and read the two signals at fleet scale: liveness as the
   coverage floor, reachability as the path map. A heatmap of each, the guest KPI and the delivery
   percentage, turns thousands of objects into two at-a-glance reads.
3. **Layer up to the full promise.** Add the platform floor, native Service Discovery, the agent
   plane, and the target-and-error-budget close, in the order the dashboard's Setup panel walks.
   The layered dashboard in this directory is that end state.

## The artifacts, in import order

Each layer references the previous one by id, so the order matters:

1. `supermetrics/availability-slis.contentpkg.zip`: the five L1 reachability SLI super metrics
   (per-check packet delivery, endpoint count, reachable, unreachable, reachability SLI) as an
   **id-preserving content package**. This is the format the VCF Operations **content-import**
   mechanism reads, and the way super metrics travel between environments (a different path than
   the *Manage ▸ Import* used for views and dashboards). It carries each metric's id, so the views
   and dashboard that reference them by `Super Metric|sm_<id>` resolve on your instance; a plain
   `POST /api/supermetrics` would mint new ids and break those references.
   **Import** via the content-import UI, or
   `POST /suite-api/api/content/operations/import` (multipart field `contentFile`; poll
   `GET /api/content/operations/import` for `state=FINISHED`). The import **creates** any metric
   that is absent, with its shipped id, so a first import into a fresh environment needs nothing
   more. The `force` flag affects only a metric that **already exists**: `force=false` skips it
   (safe and non-destructive, and how you re-run without clobbering local edits); `force=true`
   **overwrites** it, which you want only to push an update to an environment that already has an
   earlier version. The API defaults the flag to `true`/overwrite, so pass `force=false`
   explicitly when you want the skip-existing behavior.
   Built as a verbatim filter of the reference instance's own export, so what ships is the
   export format exactly.
   - `supermetrics/availability-slis.import.json`: the same five metrics in readable, id-keyed
     form (names, formulas, object types, units): a reference for review or a hand-rebuild, not
     a direct import.
   - `supermetrics/editor-formulas.yaml`: the by-hand path: editor-syntax formulas with the two
     id substitutions the composition metrics need if you mint your own ids.
2. `views/availability-views.import.zip`: all thirteen views in the **Views, Manage, Import** shape
   (import the zip directly). Id-preserving, so the dashboard resolves them. Layer five carries
   two views, one per sensor: agentless Service Discovery and the agent's service monitors.
   Layer one carries two too: the ping-adapter tables and the object-level reachability view.
   Layer two now carries a VM platform-floor view beside the cluster, host, and datastore floors:
   each VM's own power state and uptime, reported by the hypervisor independent of VMware Tools, so
   a Powered On VM whose Tools is silent is read as running rather than misread as down.
   - `views/availability-views.contentpkg.zip`: the same thirteen views for the content-import API
     path, if you prefer one mechanism for metrics and views.
3. `dashboard/availability-service-levels.import.zip`: the dashboard, via **Dashboards, Manage,
   Import**, after the views. Twenty-three widgets: a collapsed Setup panel on top (expand it once:
   it is the from-scratch runbook), then education beside evidence for every layer. The two
   world providers (vSphere World, Ping World) bind YOUR instance's objects automatically
   through the import remap; if a ping table ever imports unconfigured, edit the widget and
   select the Ping World object once.

## What works out of the box, and what needs the metrics

The floor, guest, service, and agent tables read raw platform data: they render as soon as the
environment provides the sensors (below). Only the fleet reachability row and the delivery
columns are computed: they need the five super metrics from step 1, enabled in the policy that
governs your ping objects. Blank cells there mean the metrics are not yet created or not yet
enabled, not a broken import.

## Making it true from scratch

The dashboard's own Setup panel walks this in full, and
[CONFIGURATION.md](CONFIGURATION.md) is the deep guide: per-layer configuration with the exact
API payloads, the certificate-trust model (signing CA, not endpoint leaves), enablement
semantics, verification without the console, and a condensed failure-signature table, all
proven live. The short form, in sensor-chain order:

1. **Pipeline first.** A cloud proxy deployed and every collector UP. A down collector freezes
   every layer at once; the signature is fleet-wide staleness at one age.
2. **Ping monitoring (L1).** Add a Ping adapter instance (the internal unique name must be a
   plain slug; the display name can be branded), declare FQDN and IP targets, take values from
   the product's documented ranges, and read the instance's Adapter Status message as the health
   gate: an instance can heartbeat while reporting "Adapter configuration failed."
2b. **Object-level ping (optional, L1 on inventory).** For a vSphere guest VM the collector can
   reach, enable the `isPingEnabled` identifier (PUT /api/resources) to bind reachability onto the
   object itself, beside its guest KPI. Scope it by promise, but never onto a workload isolated on
   a private CIDR (a steady full loss from the collector while healthy, measured at its
   load-balancer VIP instead, the front-door rule below); and prefer guests to hosts, since a
   multi-homed ESXi host's portable loss key is pinned at 100 percent by a non-routable link-local
   vmknic. It runs from the object's collector, so read each as reachable-from-there.
   CONFIGURATION.md section 1b has the mechanism.
3. **VMware Tools everywhere (L3).** Tools is the sensor: the guest availability KPI, guest
   uptime, Service Discovery, and HA's guest-restart protection all ride it. The L3 table's
   Tools columns are your verification.
4. **Service Discovery (L5 sensor one, native).** Enable per vCenter adapter (its Service
   Discovery tab). It is credential-less on Windows with Tools 12.3.0 or later; on a Linux guest
   it needs guest credentials to see services inside the guest, and shows the VM with zero
   services until they are supplied. Activate monitoring for the services that matter to move
   them from daily discovery to five-minute collection and arm the shipped service-unavailability
   alert. Full per-layer detail, including the per-vCenter certificate trust, is in
   [CONFIGURATION.md](CONFIGURATION.md).
5. **Agents (L4, and L5 sensor two).** The OS and Application Monitoring agent gives the OS its
   own availability figure (L4) and, through per-service plugins, a per-service availability
   object (the agent half of L5). On a credential-constrained Linux service it is the sensor of
   record, not optional depth. Install by promise, not by fleet; it needs the target vCenter
   mapped to a proxy first, and the plugin needs the service's own connection (CONFIGURATION.md).
6. **The computed layer.** Step 1 above (the super metrics), plus alerting scoped to a dedicated
   group and policy, never to everything.
7. **Keep it true.** Templates carry current Tools and the agent; Tools currency rides the guest
   patching cadence (the dashboard's yellow "Supported Old" rows are the queue, pre-sorted); new
   endpoints enter the check set declared and reviewed. The dashboard is its own drift watch:
   every sensor has a column that goes red or yellow when it slips.

## The rules the content encodes

- **Liveness and reachability are co-primary.** The guest KPI answers "is the guest up" and the
  ping answers "is its path open." A workload-heavy estate needs both: reachability alone goes dark
  on every workload no collector can route to, and liveness alone misses the live guest whose path
  failed. The layer-1 and layer-3 rows carry them together so the pair reads as one finding.
- **Monitor the front door, not the private backend.** A workload on a private, inbound-isolated
  CIDR (a supervisor namespace, a VKS cluster, an NSX VPC, or anything reachable only through a
  load balancer) reads a steady 100% loss from the collector while it is healthy and serving
  traffic. Point the check at its external load-balancer VIP (the NSX Advanced Load Balancer
  VirtualService's `Summary|VSVIP`), never the private VM or pod IP. The signature is
  unmistakable: the private address holds 100% loss while, in the same window, the VIP answers
  ping at 0% and serves an HTTP 200.
- **Peak, not average.** Delivery reads the cycle's worst packet loss; a link that fails every
  fifth batch averages respectably and is still failing someone every fifth batch.
- **Blind is not down.** Tools heartbeat under 100 means the platform lost its sensor, and the
  honest guest reading is unknown, not unavailable. The L3 view pairs the KPI with its sensor
  columns so the distinction is visible.
- **Band bounds are exclusive at the top.** An ascending band colors green only above the yellow
  bound; a bound equal to the perfect value renders a perfect reading yellow.
- **String columns color by text match.** The band bound properties accept string values (only
  the bounds you need), which is how "false", a down state, or a stale Tools version carries
  severity color in these views.
- **Discovered is not monitored.** Service Discovery refreshes daily until monitoring is
  activated per service; blank metric cells in the L5 table are a coverage statement.
- **Datastore accessibility speaks power-state vocabulary.** The adapter reports accessible as
  "PoweredOn"; the shipped product views filter not-accessible as "PoweredOff". The column
  header carries the decode.
