# Memory tiering candidacy: the lens's verdict metrics

The runnable companion to
[Memory tiering candidacy is an active-memory question](https://privatecloudarchitect.com/handbook/memory-tiering).
The three super metrics that produce the lens's verdicts, in the exact formulas proven live.

**Provenance:** formulas derived and validated against a live VCF Operations instance (11 hosts,
5 clusters, ESXi 9.1), 2026-07-02 through 2026-07-08, including the denominator correction the
sheet teaches. Thresholds (the 50 gate, the 80 trigger) are from the vSphere 9.1 memory-tiering
best-practices documentation.

## The three metrics

| Metric | Question it answers | Unit |
|---|---|---|
| Active pct of DRAM | Candidacy: is the hot working set inside the 0 to 50 gate? | percent |
| Recoverable Cold DRAM GB | Payoff: how much DRAM is backing cold pages tiering can relocate? | GB |
| Consumed pct of DRAM | Activation readiness: how close is consumption to the 80 trigger? | percent |

The artifacts, and the order they import in (metrics before views before the dashboard, because
each layer references the previous one by id):

- `supermetrics/editor-formulas.yaml`: the three verdict metrics' exact formulas in super-metric
  editor syntax, object types, and units, for building them by hand.
- `supermetrics/memory-tiering-supermetrics.import.json`: the readable form of the full six-metric
  set the lens's views reference: the three verdict metrics plus three qualifiers (reserved memory,
  NVMe tier size, NVMe tier used). Id-keyed; the ids are what the views bind to.
- `supermetrics/memory-tiering-supermetrics.contentpkg.zip`: the same six metrics as an
  **id-preserving content package**, importable via the content-import UI or
  `POST /suite-api/api/content/operations/import` (multipart field `contentFile`). The import
  creates any absent metric with its shipped id; the `force` flag affects only a metric that
  already exists: `force=false` skips it (safe, non-destructive), `force=true` overwrites it (only
  to push an update). The API defaults the flag to `true`/overwrite, so pass `force=false` for a
  non-destructive import. Built by filtering the reference instance's own export, so what ships is
  the export format verbatim; a no-force test-import on the reference instance recognized all six
  with zero failures and zero changes.
- `views/memory-tiering-views.contentpkg.zip`: the lens's three views (host candidates, capex
  avoidance, cluster readiness) as the same kind of id-preserving package; no-force test-import
  recognized all three, zero failures. The views reference the metrics by id, which is why the
  package pair imports in order.
- `dashboard/memory-tiering-readiness.import.zip`: the readiness dashboard in the Dashboards,
  Manage, Import shape (dashboard import is UI-only on this build; import the zip directly, do
  not unzip it). This is the reference estate's own deploy artifact: its runbook deploys exactly
  this file through Manage, Import, and the live dashboard matches the committed contents. It
  references the views and metrics by id, so import it last, after both packages. Blank rows
  right after import mean the super metrics are not yet activated in the collecting policy,
  which is the activation step above.

## The rules the formulas encode

- **The denominator is the DRAM tier's own capacity key**, never total memory capacity. On a host
  that already tiers, total capacity includes the NVMe tier and understates percent-of-DRAM by up
  to half at a 1:1 ratio, quietly qualifying hosts that should have failed the gate. Proven live.
- **Candidacy and activation readiness are two columns, not one.** Candidacy reads active against
  the 50 gate; readiness reads consumed against the 80 trigger. Reporting both is what turns
  "we activated it and nothing happened" into expected behavior.
- **The consumed-percent metric does not compute at cluster scope.** The DRAM-tier denominator
  does not roll up; proven live. Read it per host, or aggregate host values deliberately.

## Importing, and the step that is easy to miss

1. Import each super metric (or create it in the editor from `editor-formulas.yaml`, binding it
   to the object types listed there: hosts, rolling to clusters where the metric supports it).
2. **Activate each super metric in the policy that collects for its object types.** A super
   metric that exists but is not activated in the collecting policy collects nothing and raises
   no error; it simply stays empty. This is the single most common reason a freshly built lens
   shows no data.
3. First values appear after the following collection cycles (five minutes each by vendor
   default). Validate one host by hand before trusting a fleet-wide read: pick a host you know,
   and check the metric against its raw statkeys.

## Running the lens against your own hosts

`candidacy.py` runs the gate and the trigger against every host your Operations instance collects
and prints the four readings the verdict alone does not give you. Read-only: resource lists, stat
keys, and stat values. It writes nothing to the instance and no host name reaches its record.

```
export OPS_HOST=... OPS_BROKER_HOST=... OPS_API_TOKEN=...
export OPS_TLS_VERIFY=false          # only on a self-signed lab CA
python3 candidacy.py                 # writes candidacy.json beside the script
```

It reports:

1. **Where each host lands.** Active as a percent of the DRAM tier against the gate, consumed
   against the trigger, and cold DRAM in GiB. Hosts are numbered by consumption rank, never named.
2. **What the wrong denominator would have cost**, per host, with the signed error. This is the
   reading that changed the sheet: the error does not have one sign. On a host with a tier the
   total counts the tier and understates percent-of-DRAM; on a host without one the total is
   memory usable by workloads, net of hypervisor overhead, and overstates it. Measured on the
   reference estate, -48.0 and -16.4 percent on the two tiered hosts against +5.3 to +29.0 on the
   nine untiered ones. **The error passes through zero at activation**, so no correction factor
   fixes it and no drift-watching notices it.
3. **Whether a configured tier is a used tier.** `mem:NVMe|memory_tier_size` says a tier exists;
   `mem:NVMe|tier.usage` and the four latency and bandwidth counters on the NVMe side say whether
   anything has moved into it. The script reads fourteen days of daily maxima so that a zero is a
   sustained zero, and it checks the DRAM-side counters as a control: if those carry traffic, the
   instrumentation is collecting and the silence is a fact rather than a gap.
4. **Whether the 1:1 default holds.** The uplift a 1:1 ratio would give against the tier size the
   host actually reports. On the reference estate one tiered host is exactly 1:1 and the other is
   1:0.25, which makes any figure derived from the assumed uplift four times too large on the
   second one.

### Two read shapes worth keeping

- **The stat-key container is `stat-key`, hyphenated.** `GET /api/resources/<id>/statkeys` returns
  `{"stat-key": [...]}`. A reader who guesses a camel-case name gets HTTP 200 and an empty list,
  which reads as a host that collects nothing rather than as a wrong key.
- **Detect a tier with `mem:NVMe|memory_tier_size`, never with
  `mem:NVMe|memory_tier_total_capacity`.** The capacity key is present on every host and reads
  zero where there is no tier, because it reports the NVMe capacity the hardware could use rather
  than the tier that is configured. The cleanest detector of all is the key set: a configured tier
  adds ten memory keys (a size, a usage, and read/write latency and bandwidth on each side of the
  boundary), and their arrival is unambiguous.

### Scope and units

`mem|guest_demand` is a **VirtualMachine** key and is not present on a host; the host-scope
analogue is `mem|host_demand`. `mem:DRAM|memory_tier_total_capacity` is a **HostSystem** key and is
not present on a machine, which is the same fact that makes the percent-of-DRAM metrics compute per
host and refuse to roll up to a cluster. And the units are mixed: the `mem|` keys report KB while
`mem:DRAM|tier.usage` reports MB.
