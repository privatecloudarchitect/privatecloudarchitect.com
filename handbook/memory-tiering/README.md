# Memory tiering candidacy: the lens's verdict metrics

The runnable companion to
[Memory tiering candidacy is an active-memory question](https://privatecloudarchitect.com/handbook/memory-tiering).
The three super metrics that produce the lens's verdicts, in the exact formulas proven live, and a package of
every super metric the lens's views and dashboard use.

**Provenance:** the formulas, including the denominator the chapter teaches, were validated against a live VCF
Operations 9.1 instance, and the lens audit `candidacy.py` was last run against VCF Operations 9.1.1 with every host on
ESX 9.1.1 on 2026-10-22 ([expected-output.md](expected-output.md)). The 50 gate and the 80 trigger are from the
vSphere 9.1 memory-tiering documentation.

## Get started in the VCF Operations UI

Three files, imported in this order, then one setting. No CLI or API is needed. The screens, with what each option
does, are in [IMPORTING.md](../../IMPORTING.md) at the top of this repository. Each path below is clicked in order, left
to right. Download the files and import each zip as it is, without unzipping it.

1. **The super metrics.** **Operate ▸ Administration ▸ Configurations ▸ Super Metrics ▸ ⋯ ▸ Import**: choose
   `supermetrics/memory-tiering-supermetrics.import.json`, keep **Skip import**, and click **IMPORT**. The dialog reports **19** imported (or skipped, for any you already have).
2. **The views.** **Operate ▸ Dashboards ▸ Views ▸ Manage ▸ ⋯ ▸ Import**: choose
   `views/memory-tiering-views.import.zip`, keep **Skip import**. Three views arrive: **PCA - MemTier - Host
   Candidates**, **Capex Avoidance** and **Cluster Readiness**.
3. **The dashboard.** **Operate ▸ Dashboards ▸ Manage ▸ ⋯ ▸ Import**: choose
   `dashboard/memory-tiering-readiness.import.zip`. It arrives as **PCA - MemTier - Readiness**, owned by you, and its
   Setup panel repeats these steps.
4. **Switch the 19 super metrics on** in the policy that governs your hosts and clusters (the **Default Policy** if
   you have not made your own). On the **Super Metrics** screen, filter on `PCA - MemTier` and `PCA - Shared`, then
   for each one **EDIT ▸ 4 - Policies**, tick that policy in the column its name gives, and **UPDATE**: **Host
   System** for a `- Host -` metric, **Cluster Compute Resource** for a `- Cluster -` one. Four host metrics are
   also assigned to clusters, where their DRAM-tier denominator does not roll up, so leave their cluster column
   unticked. Until this step the dashboard's rows stay blank.
5. **Set your price** in **PCA - MemTier - Host - Price Delta (USD/GB)** (the section below), then give it two
   collection cycles and open the dashboard.

Importing again later? Keep **Skip import**, or the shipped Price Delta replaces yours. The same super metrics and
views also ship as content packages (`*.contentpkg.zip`) for **Content Management ▸ Import**; choose **Skip
item(s)** there, because its default overwrites.

## The three metrics

| Metric | Question it answers | Unit |
|---|---|---|
| Active pct of DRAM | Candidacy: is the hot working set inside the 0 to 50 gate? | percent |
| Recoverable Cold DRAM (GB) | Payoff: how much DRAM is backing cold pages tiering can relocate? | GB |
| Consumed pct of DRAM | Activation readiness: how close is consumption to the 80 trigger? | percent |

The artifacts, and the order they import in (metrics before views before the dashboard, because
each layer references the previous one by id):

- `supermetrics/editor-formulas.yaml`: the three verdict metrics' exact formulas in super-metric
  editor syntax, object types, and units, for building them by hand.
- `supermetrics/memory-tiering-supermetrics.import.json`: the readable form of all 19 super metrics
  the lens's views and dashboard reference: the three verdict metrics; three host qualifiers (reserved
  memory, NVMe tier size as Actual Tiering Uplift, NVMe tier used); the cluster readiness roll-ups
  (worst host active, hosts over the gate, untiered hosts, hosts actively tiering, cluster recoverable
  cold DRAM); the cost chain (price delta, tiering uplift, capex and DRAM avoided, per host and per
  fleet); and the cluster's HA headroom. Id-keyed; the ids are what the views bind to. A unit rides as
  `unitId` where one is declared, because an import is how a unit gets set.
- `supermetrics/memory-tiering-supermetrics.contentpkg.zip`: the same 19 metrics as an
  **id-preserving content package**, importable in the UI through **Content Management ▸ Import** (the steps
  above) or through `POST /suite-api/api/content/operations/import` (multipart field `contentFile`). The import
  creates any absent metric with its shipped id; the `force` flag affects only a metric that
  already exists: `force=false` skips it (safe, non-destructive), `force=true` overwrites it (only
  to push an update). The API defaults the flag to `true`/overwrite, so pass `force=false` for a
  non-destructive import; the UI's import tab likewise defaults to **Overwrite existing content**, and its
  **Skip item(s)** is the same non-destructive choice. Built by filtering the reference instance's own export, so what ships is
  the export format verbatim. A no-force test-import on the reference instance (2026-10-08) reported
  all 19 skipped and none failed, and a read of every field of all 19 before and after showed no change,
  with the instance's super metric count the same.
- `views/memory-tiering-views.import.zip`: the lens's three views in the **Views ▸ Manage ▸ ⋯ ▸ Import** shape,
  the UI route above. Id-preserving, so the dashboard finds them.
- `views/memory-tiering-views.contentpkg.zip`: the lens's three views (host candidates, capex
  avoidance, cluster readiness) as the same kind of id-preserving package; a no-force test-import
  (2026-10-08) reported all three skipped and none failed. The views reference the metrics by id, which is why the
  package pair imports in order.
- `dashboard/memory-tiering-readiness.import.zip`: the readiness dashboard in the **Dashboards ▸
  Manage ▸ ⋯ ▸ Import** shape (dashboard import is UI-only on this build; import the zip directly, do
  not unzip it). This is the reference estate's own deploy artifact: its runbook deploys exactly
  this file through **Manage ▸ ⋯ ▸ Import**, and the live dashboard matches the committed contents. It
  references the views and metrics by id, so import it last, after the super metrics and the views. Blank rows
  right after import mean the super metrics are not yet activated in the collecting policy,
  which is step 4 above.

## The one input you set

The cost chain reads a single constant, **Price Delta (USD/GB)**: your DRAM price per GB minus your
NVMe price per GB, 4.70 by default (5.00 minus 0.30). After import, edit the trailing number in that
super metric's formula to your own prices; every capex-avoided and DRAM-avoided figure, per host and per
fleet, follows from it. The `* 0` term only anchors the constant to each host so it computes per object.

## The rules the formulas encode

- **The denominator is the DRAM tier's own capacity key**, never total memory capacity. On a host
  that already tiers, total capacity includes the NVMe tier and understates percent-of-DRAM by up
  to half at a 1:1 ratio, quietly qualifying hosts that should have failed the gate. Proven live.
- **Candidacy and activation readiness are two columns, not one.** Candidacy reads active against
  the 50 gate; readiness reads consumed against the 80 trigger. Reporting both is what turns
  "we activated it and nothing happened" into a question you can answer.
- **On a host whose tier holds pages, consumed counts them.** Host consumed memory is the DRAM tier's usage plus
  the NVMe tier's, so **Consumed pct of DRAM** passes 100 there. Read readiness on such a host from the DRAM tier's
  own usage, `mem:DRAM|tier.usage` (MB), against the same denominator; `candidacy.py` prints both.
- **The consumed-percent metric does not compute at cluster scope.** The DRAM-tier denominator
  does not roll up; proven live. Read it per host, or aggregate host values deliberately.

## Building the verdict metrics by hand instead, and checking one host

1. Create each of the three verdict metrics in the editor from `editor-formulas.yaml`, binding it to the object
   types listed there: hosts, rolling to clusters where the metric supports it. The views and the dashboard look
   for the shipped ids, so a hand-built metric serves your own views, not the shipped ones; import the package for
   those.
2. **Activate each super metric in the policy that collects for its object types.** A super
   metric that exists but is not activated in the collecting policy collects nothing and raises
   no error; it simply stays empty. This is the single most common reason a freshly built lens
   shows no data.
3. First values appear after the following collection cycles (five minutes each by vendor
   default). Validate one host by hand before trusting a fleet-wide read: pick a host you know,
   and check the metric against its raw statkeys.

## Running the lens against your own hosts

`candidacy.py` runs the gate and the trigger against every host your Operations instance collects
and prints what the verdict alone does not give you. Read-only: resource lists, relationships, properties, stat
keys and stat values. It writes nothing to the instance and no host name reaches its record.

```
umask 077                            # files you create from here on are mode 0600
export OPS_HOST=... OPS_BROKER_HOST=...
export OPS_API_TOKEN_FILE=<a file holding your api-token, mode 0600>
export OPS_TLS_VERIFY=false          # only on a self-signed lab CA
python3 candidacy.py --days 60       # writes candidacy.json beside the script
```

It reports:

1. **Where each host lands.** Active as a percent of the DRAM tier against the gate, consumed
   against the trigger, and cold DRAM in GiB. Hosts are numbered by consumption rank, never named, and only hosts
   that exist are measured: a host whose resource an adapter reports as NOT_EXISTING, or with no consumption sample
   in the last hour, is skipped and counted, because a removed host keeps its last values.
2. **What the wrong denominator would have cost**, per host, with the signed error. The error does not have one
   sign: on a host with a tier the total counts the tier and understates percent-of-DRAM; on a host without one the
   total is memory usable by workloads, net of hypervisor overhead, and overstates it. **The error passes through
   zero at activation**, so no correction factor fixes it and no drift-watching notices it.
3. **What each configured tier has held, day by day.** `mem:NVMe|memory_tier_size` says a tier exists;
   `mem:NVMe|tier.usage` says whether pages are in it. For each host with a tier the script reads `--days` of daily
   maxima (60 by default) and prints the first day the tier held pages, the five-minute sample when the first ones
   arrived with the host's consumption then, the peak and its day, and how many days the host spent at or past the
   trigger before the first page. The DRAM-side counters are the control: if they carry traffic, the
   instrumentation is collecting and a zero is a reading rather than a gap.
4. **What consumed counts.** Host consumed memory beside the two tiers' usage, and the DRAM tier's usage alone as a
   percent of DRAM, which is the readiness figure on a host whose tier holds pages.
5. **Whether the 1:1 default holds.** The uplift a 1:1 ratio would give against the tier size the host reports. Where
   the two differ, every figure derived from the assumed uplift carries the difference.

[expected-output.md](expected-output.md) holds a run against the reference estate, with notes on reading it.

The api-token is read from `OPS_API_TOKEN_FILE`, a file of mode 0600, when it is set; a wider mode is refused.
The value itself in `OPS_API_TOKEN` still works, but it lands in the shell's history and the process list, so
keep it for a throwaway credential.

### Two read shapes worth keeping

- **The stat-key container is `stat-key`, hyphenated.** `GET /api/resources/<id>/statkeys` returns
  `{"stat-key": [...]}`. A reader who guesses a camel-case name gets HTTP 200 and an empty list,
  which reads as a host that collects nothing rather than as a wrong key.
- **Detect a tier with `mem:NVMe|memory_tier_size`, never with
  `mem:NVMe|memory_tier_total_capacity`.** The capacity key can be present on every host and read zero where there
  is no tier, so its presence proves nothing, and on the reference estate it read the same figure on two hosts
  whose tiers differ fourfold, so its value is not the tier's size. The cleanest detector is the key set: the keys
  on every host with a tier and on no host without one. `candidacy.py` reads every host's key list for it, because
  a key on one untiered host can be missing from another; on the reference estate six keys qualified (the tier's
  size and usage, and read and write latency and bandwidth on the NVMe side).

### Scope and units

`mem|guest_demand` is a **VirtualMachine** key and is not present on a host; the host-scope
analogue is `mem|host_demand`. `mem:DRAM|memory_tier_total_capacity` is a **HostSystem** key and is
not present on a machine, which is the same fact that makes the percent-of-DRAM metrics compute per
host and refuse to roll up to a cluster. And the units are mixed: the `mem|` keys and the DRAM tier capacity report
KB while both tiers' `tier.usage` report MB, which `candidacy.py` confirms on your hosts when the two tiers' usage
adds up to consumed.
