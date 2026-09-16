# PromQL on VCF Operations 9.1 Real-Time Metrics: the reference, verified

The PromQL Viewer widget and the Real-Time Metrics query service speak a PromQL dialect. This folder holds what the
product shows, what VMware guidance documents, and what the engine actually answered on a live 9.1 instance, side by side,
so that a warehouse pipeline or a dashboard author can rely on the key names, the function semantics, and the cadences
without re-deriving them. Every claim below carries its evidence; the JSON files carry the verification blocks.

| File | What it is | Origin |
|---|---|---|
| `metrics.json` | the widget's Metrics tab, 1,345 rows of `name`, `key`, `id` | captured from the PromQL Viewer widget on 2026-09-16; unmodified |
| `functions.json` | the widget's Functions tab (22 functions) plus `irate` and `increase`, each with its call form, signature, standard-PromQL flag, cautions, and a live verification block | descriptions verbatim from the widget; verification by `verify_promql.py` |
| `examples.json` | ten queries built for the collection strategy, each with the decision it serves and a verification block; the dialect facts; the cross-plane comparison | `verify_promql.py` |
| `reconciliation.json` | every key of `metrics.json` against the live catalogs and the VMware guidance per-provider list, the acquisition profile per served name, the case pairs, the semantic findings, and the engine names the widget does not list | `verify_promql.py` |
| `verify_promql.py` | regenerates the three JSON files against a live instance (about 250 calls, two minutes); `--guidance-xlsx <file>` adds the per-provider classification | stdlib only; credentials in-process, never printed |

The VMware guidance list (`VODAP-9.1-Metrics-List-Per-Provider.xlsx`) is read from a path you give; it is not stored in this
repository. Source of record for the strategy these examples serve: `the Collect Once, Decide at Source charter, whose public form is the metrics-collection chapter`.

## 1. How it was verified

One VCF 9.1 estate, 2026-09-16 (UTC). Real-Time Metrics on the reference instance, read through `/data-query-service`
with the service JWT the suite API mints (`the harness's rtmlib.py`). Sources: three vCenter
instance ids listed by `GET /api/v1/vcenters/metrics_config` and three NSX manager cluster ids carried by Operations as
the `MANAGEMENT_CLUSTER_UUID` identifier of transport nodes. Operations stats for the cross-plane comparison came from
`POST /suite-api/api/resources/stats/query` on the same VMs, keyed on `VMEntityVCID` + `VMEntityObjectID`. VMware guidance's
per-provider list was retrieved the same day from the link on the Real-Time Metrics policy page.

| Catalog | Names |
|---|---|
| Engine catalog (`/api/v1/metadata` without a source) | 437 |
| Management vCenter source | 175 |
| Workload vCenter source | 171 |
| Third vCenter source listed by `metrics_config` (no host series served) | 171 |
| NSX sources (management, workload, a third with no data) | 254, 262, 0 |
| The widget's Metrics tab (`metrics.json`) | 1,345 |
| The VMware guidance per-provider list (sheets ESXi 950, VC 144, VSAN 143, NSX 248, ESXTop 21; 28 keys on two sheets) | 1,478 distinct |

## 2. Three catalogs that disagree pairwise

| Status of a `metrics.json` key | Count | Meaning |
|---|---|---|
| served on a vCenter source | 175 | the key returns series here; the acquisition profile per name is in `reconciliation.json` |
| served on an NSX source | 77 | the key is an NSX family name served under the NSX cluster id as `sourceId` |
| case pair | 4 | the copyable key differs from a served key only by letter case and returns nothing; the VMware guidance list shows why (section 3) |
| not in this deployment's catalog | 1,089 | by the VMware guidance list: 538 ESXi Verbose, 271 ESXi Standard, 131 vSAN Verbose, 85 VC Verbose, 12 vSAN Essential, 11 ESXi Essential, 6 NSX Essential, 3 VC Essential, and 32 keys the list does not carry. Standard needs a Large deployment, Verbose is off by default, and vSAN is not in use on this estate |

The widget against the VMware guidance list: 1,305 of the widget's keys are in the list, 40 are not (32 `vna.*`, 7 `platform.*`,
1 `tn-traffic.*`), and 173 of the list's keys (NSX edge families: `disk.*`, `edge_*`, and more) are not in the widget.
The engine against the VMware guidance list: 401 of its 437 names are in the list, 36 are not (`platform.*_hist*`,
`pnic.link_status`, `tn-traffic.fastpath_*`). The widget against the engine: 185 engine names (NSX families) are absent
from the widget. No catalog is a subset of another; the metadata endpoint of the query service is the only list that
says what a source serves.

## 3. Findings and how to report them

| Finding | Evidence | Report type |
|---|---|---|
| `vcResources.priviledgedcpuusage.VCRES` is misspelled | the VMware guidance list carries the same misspelled key (VC sheet, label "CPU Privileged", Verbose profile, 300-second sampling); no source on this Essentials deployment serves either spelling | a defect in the metric definition itself, not in the widget: report as a key correction that keeps the old key as an alias; a warehouse mapping carries the key verbatim until then |
| `mem.swapIn.HOST`, `mem.swapOut.HOST`, `mem.swapIn.VM`, `mem.swapOut.VM` return nothing while `mem.swapin.HOST` and the others serve | the VMware guidance list carries both spellings as distinct definitions: the mixed-case keys are Verbose-profile metrics sampled at 300 seconds whose label is the raw key; the lowercase keys are Essentials at 20 seconds ("Memory Swapped In") | not a typo. Report the naming hazard (two keys that differ only by case) and the missing labels; on an Essentials deployment the mixed-case keys are simply not collected |
| "High VCPU Ready Percentage" is mapped to `platform.vcpu_utilization_hist_max` and "High VCPU Usage Percentage" to `platform.vcpu.ready_hist_max` | the keys' own words say the opposite, the values agree with the keys (utilization 42 to 76 on NSX edge nodes, ready 0.8 to 5.1), and neither key is in the VMware guidance list | text bug in the widget's own catalog: the two friendly names are swapped |
| "Failed Requests To SDK Endpoint" is mapped to the bare `envoy_cluster_upstream_rq` | the key carries `envoy_cluster_name` and `envoy_response_code`; on this build its only series is `envoy_response_code='503'` on cluster `localhost 8085` | the name encodes a label filter the key does not; report as a design gap |
| "Failed Requests To UI Endpoint" is mapped to `envoy_cluster_upstream_rq_retry_success` | the key counts successful retries on `vsphere-ui-http2-cluster`; the VMware guidance list carries the same name for it | the name contradicts the key in the definition itself |
| "Request Count To UI Endpoint" is mapped to `envoy_cluster_upstream_rq_total` | the key serves two clusters; the VMware guidance list carries the key twice, as "Request Count To SDK Endpoint" and "Request Count To UI Endpoint" | the definitions are label-filtered variants of one key and the picker keeps one name per key; report as a design gap |
| 51 widget names differ from the VMware guidance labels | mostly NSX names ("Error Packet Drop" against "Packet drops due to errors") | cosmetic; key a warehouse mapping on `key`, never on `name` |
| The VMware guidance PromQL Queries page writes `{HOST='host-17'}` | the engine's label is `host`; the uppercase form returns 0 series with status success | documentation text bug on the page |
| The widget lists no NSX edge family names although the engine and the VMware guidance list carry them | 173 keys of the VMware guidance list and 185 engine names absent from the widget | enhancement request: the picker should list them, or say it lists vCenter names only |

## 4. The functions

The widget lists 22 functions. The call form is the thing to know:

- **snapshot** functions take an instant vector, a bare metric or a selector: `sum`, `min`, `max`, `avg`, `count`, `abs`, `ceil`, `floor`, `absent`. The five aggregations take `by (label)` and `without (label)`.
- **count, then snapshot**: `topk(k, x)`, `bottomk(k, x)`, `topn_sum(n, x)`, `bottomn_sum(n, x)`.
- **clip** functions take a range vector, the metric with a window such as `[5m]`: the six `_over_time` functions, `rate`, `resets`, `absent_over_time`; and `irate` and `increase`, which the engine serves although the widget does not list them (`irate` is in VMware guidance, `increase` is not).

Semantics verified on the build (the numbers sit in `examples.json` under `dialect` and in `functions.json` under `cautions`):

| Function | What the engine does |
|---|---|
| `topn_sum`, `bottomn_sum` | VCF-specific. Select the n series with the highest or lowest **sum over the whole query range** and return their raw values: exactly n series, a stable legend (checked against a manual sum over 6 hosts). `by (label)` is accepted and ignored; VMware guidance says `by` and `without` are unsupported. |
| `topk`, `bottomk` | Per step. Over a range the answer is the union of every step's top k (6 series for k=3 over 30 minutes on 6 hosts) and the legend changes as leaders change. |
| `rate`, `irate` | **Counter semantics on a gauge.** On `cpu.usagemhz.HOST` (84 decreases in 181 samples) `rate()` returned no negative value and matched a reset-adding computation (mean absolute error 4 against 282 for a plain first-to-last delta). The example in VMware guidance `rate(cpu.capacity.usage.HOST{host='host-17'}[5m])` applies it to a gauge and overstates change. Use `avg_over_time` or `max_over_time` for a level; `rate` and `increase` only on cumulative names (`vmop.*`, `envoy_*_total`). |
| `resets` | The number of decreases inside the window (167 of 181 buckets exact on a gauge). On a gauge it counts dips. |
| `absent`, `absent_over_time` | One series valued 1 when the selector matches nothing (an unknown name or an unmatched label); nothing when it matches. |
| `count_over_time` | Counts raw samples: 3 per minute on the 20-second profiles, 30 per minute on the ESX Top profile. The cadence instrument. |

`rate` and `resets` are counter functions, and the engine confirms it; the reference marks VMware guidance page's
`rate` example as one to avoid rather than reproduce. `topn_sum` and `bottomn_sum` take `(n, metric)` exactly like
`topk`, so the "unconfirmed" note that motivated this file is closed.

## 5. The dialect on this build

| Works | Does not work |
|---|---|
| lowercase labels (`vm`, `host`, `cluster`, `datacenter` carry MOIDs; `host_fqdn`, `host_ip`, `vc_ip`; `feature`, `profile`, `provider`; `mem` on MEMTYPE names; `le` on histograms) with `=`, `!=`, `=~`, `!~` | VMware guidance's uppercase `HOST='host-17'` (0 series, status success) |
| a range vector inside a function | a bare range vector or a subquery as the outermost expression of a range query (the widget always runs a range query) |
| a subquery `[30m:5m]` as the outermost expression of an instant query through the API | a nested subquery |
| `+ - * / % ^` between a series and a number, or between two series whose labels match; comparisons with `bool`; `and`, `or`, `unless` | `on`, `ignoring`, `group_left`; unary minus; the `@` modifier |
| `sum`, `min`, `max`, `avg`, `count`, `topk`, `bottomk`, `topn_sum`, `bottomn_sum` | `stddev`, `stdvar`, `quantile`, `count_values`, `group` |
| the six `_over_time` functions, `rate`, `irate`, `increase`, `resets`, `abs`, `ceil`, `floor`, `absent`, `absent_over_time` | `round`, `sqrt`, `log`, `delta`, `deriv`, `predict_linear`, `sort_desc`, `clamp_max`, `label_replace`, `label_join`, `histogram_quantile`, `quantile_over_time`, `stddev_over_time`, `changes`, `time()`, `vector()`, `scalar()` |
| `offset` parses | it returned the unshifted series point for point (61 of 61); VMware guidance lists it unsupported in 9.1 |

Cadence, measured the same day on both vCenter sources: every name under the ESXi 20-second profile, the vCenter
20-second data profile, and the PerformanceManager profile (whose name carries `300`) serves 3 samples per minute with
a median change spacing of 20 seconds; the ESX Top profile serves 30 per minute. The VMware guidance list documents the same
thing for the VC sheet as `Sampling Interval 20.0, Collection Interval 300.0`: the 300 is how often the collector polls,
the 20 is the spacing of the samples it brings back. Nineteen names serve both a 20-second and a 2-second series under
one name (21 carry `feature='ESX_TOP'` on the workload source; the VMware guidance ESXi sheet marks the same 21 as ESXTop-capable);
pin `feature` or a chart draws both.

## 6. The examples and the decisions they serve

`examples.json` carries the query, the decision, what the chart reads, and the verification. In short:

| Id | Lane | Query | Decision |
|---|---|---|---|
| E1 | discovery | `count by (profile) (cpu.capacity.contention.VM)` | which profile serves a name, at what cadence, and whether the 101-series ceiling is near |
| E2 | hot-set | `topn_sum(5, cpu.capacity.contention.VM{feature='TROUBLESHOOTING'})` | the scoped hot-set the charter allows out of this plane: five series whatever the estate size |
| E3 | cross-plane | `max_over_time(net.throughput.usage.VM{vm='<vm>'}[5m])` and `avg_over_time(...)` | the store already keeps this plane's mean and in-cycle peak; ship the store's keys, not the samples |
| E4 | cross-plane | `guest.cpu.runQueue.VM / cpu.corecount.provisioned.VM` | the planes share samples but not units: check the scale per key before joining |
| E5 | gold | `sum by (host_fqdn) (cpu.corecount.provisioned.VM) / count by (host_fqdn) (cpu.utilization.PCORE{feature='TROUBLESHOOTING'})` | the capacity ratio (vCPU to core) per host as one number |
| E6 | troubleshooting | `max_over_time(storage.latency.totalKavg.LUN{feature='ESX_TOP'}[1m])` | the 2-second latency tail the mean hides; read within hours, per source |
| E7 | troubleshooting | `topn_sum(5, cpu.utilization.PCORE{feature='ESX_TOP', host_fqdn='<host_fqdn>'})` | per-core hot spots on one host, bounded under the ceiling |
| E8 | gold | `increase(vmop.vmotion.CLSTR[1h])` | counters get counter functions: migrations per window per cluster |
| E9 | discovery | `absent(cpu.capacity.contention.VM{vm='<vm>'})` | the reconcile-absence rule as a query |
| E10 | troubleshooting | `mem.tier.consumed.MEMTYPE{feature='ESX_TOP'}` | tiering engagement per host and tier at 2 seconds |

The cross-plane comparison behind E3 and E4 (36 five-minute buckets per VM, three VMs per name, management source;
the workload source gave the same picture):

| Real-Time Metrics name (20 s) | Operations keys | Mean ratio, median | Peak ratio, median |
|---|---|---|---|
| `net.throughput.usage.VM` | `net\|usage_average`, `net\|20_sec_peak_usage_average` | 0.98 | 0.95 to 0.97 |
| `guest.contextSwapRate.VM` | `guest\|contextSwapRate_latest`, `guest\|20_sec_peak_contextSwapRate_latest` | 1.00 | 1.00 |
| `guest.cpu.runQueue.VM` | `guest\|cpu_queue`, `guest\|20_sec_peak_cpu_queue` | equals the VM's vCPU count (4, 16, 24) | same |
| `guest.disk.requestQueueAvg.VM` | `guest\|disk_queue`, `guest\|20_sec_peak_disk_queue` | 100 | 100 |

Reading: the analytics store's 5-minute mean and its `20_sec_peak` keys are the rollups of the same 20-second samples
this plane serves (exactly, for the guest family; within a few percent for network usage, whose two collection paths
sample at different phases). A warehouse that already extracts the store's mean and peak keys, and the hourly MAX
rollup, keeps what a 20-second feed would give it, without the volume. And the store normalizes two guest keys
(run queue per vCPU, disk queue divided by 100) where this plane serves raw values, so a join across planes scales
per key first.

## 7. Direct access: the calls behind the widget

The widget is the demonstration; a pipeline runs the same language against the query service, one HTTP call per
query. Verified on this instance:

1. **Mint.** Any suite API session (a VCF SSO API client identity) calls `GET /suite-api/api/integrations/services`, takes the `key` of the entry whose `type` is `VCF_VODAP`, and posts it to `POST /suite-api/api/auth/token/exchange` as `{"serviceKeys":[key]}`. The answer's `jwtToken` lasts 35 minutes from the bearer's own mint, not from the exchange: re-mint both on one schedule.
2. **Address.** `https://<instance services FQDN>/data-query-service/api/v1/` with `Authorization: Bearer <jwt>`. The FQDN is the VCF instance's services address, not the Operations node.
3. **Discover.** `GET /api/v1/vcenters/metrics_config` lists the vCenter ids, each the vCenter instance UUID that the store carries as `VMEntityVCID`. `GET /api/v1/metadata?sourceId=<id>` lists the names that source serves; without a source, the engine's whole catalog. NSX sources are the managers' cluster UUIDs (`MANAGEMENT_CLUSTER_UUID` on transport nodes in Operations).
4. **Size.** `count by (profile) (<name>)` per name. Pin `feature` or `profile`; partition by `host` when a name-profile pair exceeds 101 series; fail the run on `warnings`, never on the status, because a truncated answer is a 200.
5. **Pull.** `GET /api/v1/query_range?query=<promql>&sourceId=<id>&start=<epoch s>&end=<epoch s>&step=20s`, `step=2s` for the ESX Top set with `feature='ESX_TOP'`; a few hours per call. `GET /api/v1/query?query=&time=` reads one instant.
6. **Land.** Each element of `data.result` carries `metric` (the labels) and `values` as `[[epoch, "value"], ...]`. The row key is (`sourceId`, the `vm` or `host` label), which is the store's (`VMEntityVCID`, `VMEntityObjectID`) pair, so the hot-set joins the tiers without a lookup. Stamp feature, profile, and query; upsert on (source, name, labels, timestamp).
7. **Bound.** 20-second series stay 15 days, the 2-second set a shorter window cut per source at the store's own moments. Extract within hours, keep it in the region, never as the BI feed.

One call, spelled out (the hot-set of the hour):

```sh
curl -sk -G -H "Authorization: Bearer $JWT" \
  "https://<instance services FQDN>/data-query-service/api/v1/query_range" \
  --data-urlencode "query=topn_sum(20, cpu.capacity.contention.VM{feature='TROUBLESHOOTING'})" \
  --data-urlencode "sourceId=<vCenter instance UUID>" \
  --data-urlencode "start=$(($(date +%s)-3600))" --data-urlencode "end=$(date +%s)" \
  --data-urlencode "step=20s"
```

What not to do: `rate()` on a gauge (a dip reads as a counter reset), `offset` (accepted, not applied), a subquery in a
range call, an unpinned name that serves two cadences, a join across planes without the per-key scale check.
`verify_promql.py` is the runnable form of this section; the companion harness `rtm_query.py` in the
`handbook/metrics-collection` folder encodes the same discipline.

## 8. Open items

- The Standard profile (Large deployments only), the Verbose profile, and vSAN were not available on this estate; their families stay unverified beyond the VMware guidance list.
- The third vCenter source id that `metrics_config` lists (`ce1826a6-...`, 171 catalog names) served no host series in the last 15 minutes; its identity was not established in this pass.
- Thirty-two Essentials keys in the VMware guidance list are not in this deployment's catalog: 11 ESXi (GPU device counters and a memory-tier latency), 12 vSAN, 6 NSX edge datapath, 3 VC cluster rollups; `reconciliation.json` names them under VMware guidance list's per-key block.

## 9. VMware guidance read for this reference (VCF 9.1)

- PromQL Widget: https://techdocs.broadcom.com/us/en/vmware-cis/vcf/vcf-9-0-and-later/9-1/infrastructure-operations/dashboards-and-widgets/using-widgets/widget-definitions-list/promql-widget.html
- PromQL Queries: https://techdocs.broadcom.com/us/en/vmware-cis/vcf/vcf-9-0-and-later/9-1/infrastructure-operations/dashboards-and-widgets/using-widgets/widget-definitions-list/promql-widget/promql-queries.html
- Real-Time Metrics policy workspace (the Essentials, Standard, and ESX Top levels; links the list): https://techdocs.broadcom.com/us/en/vmware-cis/vcf/vcf-9-0-and-later/9-1/infrastructure-operations/configuring-policies/using-the-monitoring-policy-workspace/policy-workspace/real-time-metrics-policy-workspace.html
- The per-provider metrics list (retrieved 2026-09-16, an Excel workbook of six sheets): https://techdocs.broadcom.com/content/dam/broadcom/techdocs/us/en/assets/vmware-cis/vcf/VODAP-9.1-Metrics-List-Per-Provider.xlsx
