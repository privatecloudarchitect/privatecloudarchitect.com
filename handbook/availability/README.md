# Availability and service levels: the layered dashboard

The runnable companion to
[Availability is a computed promise](https://privatecloudarchitect.com/handbook/availability).
One dashboard that reports availability as five layers of evidence and teaches the reading as it
reports: reachability checks, the platform floor, the guest and the VMware Tools sensor that
carries it, native Service Discovery, and the agent plane, closed by the target-and-error-budget
model.

**Provenance:** every view, column, band, and formula here was proven on a live VCF Operations
9.1 instance (2026-08-17 and 2026-08-18), including the import shape itself. The no-force
content-import recognition test on the reference instance reports the shipped packages as
`skipped N, failed 0`, which is the id-preserving proof.

## The artifacts, in import order

Each layer references the previous one by id, so the order matters:

1. `supermetrics/availability-slis.contentpkg.zip`: the five L1 reachability SLI super metrics
   (per-check packet delivery, endpoint count, reachable, unreachable, reachability SLI) as an
   **id-preserving content package**. Import via the content-import UI or
   `POST /suite-api/api/content/operations/import?force=true` (multipart field `contentFile`).
   Built as a verbatim filter of the reference instance's own export, so what ships is the
   export format exactly.
   - `supermetrics/availability-slis.import.json`: the same five metrics in readable, id-keyed
     form: names, formulas, object types, units.
   - `supermetrics/editor-formulas.yaml`: the by-hand path: editor-syntax formulas with the two
     id substitutions the composition metrics need if you mint your own ids.
2. `views/availability-views.import.zip`: all twelve views in the **Views, Manage, Import** shape
   (import the zip directly). Id-preserving, so the dashboard resolves them. Layer five carries
   two views, one per sensor: agentless Service Discovery and the agent's service monitors.
   Layer one carries two too: the ping-adapter tables and the object-level reachability view.
   - `views/availability-views.contentpkg.zip`: the same twelve views for the content-import API
     path, if you prefer one mechanism for metrics and views.
3. `dashboard/availability-service-levels.import.zip`: the dashboard, via **Dashboards, Manage,
   Import**, after the views. Twenty-two widgets: a collapsed Setup panel on top (expand it once:
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
2b. **Object-level ping (optional, L1 on inventory).** For vSphere VMs and hosts, enable the
   `isPingEnabled` identifier (PUT /api/resources) to bind reachability onto the object itself,
   beside its guest KPI. Scope it by promise; it runs from the object's collector, so read each
   as reachable-from-there. CONFIGURATION.md section 1b has the mechanism.
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
