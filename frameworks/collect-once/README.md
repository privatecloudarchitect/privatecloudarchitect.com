# Collect Once: the PCA - Collection Strategy Guide dashboard

An educational VCF Operations dashboard for any BI or platform team that plans to collect VM utilization again
(vCenter PerformanceManager counters plus guest-OS items). It shows, live on the importing instance, that the
hypervisor half of any such list is already collected once, at which cadence each value is kept,
which peak keys the 5-minute mean hides, the Real-Time Metrics plane live through three PromQL Viewers charting
queries built for the strategy (the tables in the teaching widgets are generated from the `promql/` folder beside the generators), what should not come from Operations and when, and the three-tier extraction contract
that feeds an ELT warehouse. Source of record: the Collect Once, Decide at Source charter (its public form is the metrics-collection chapter).

| Piece | Home | Generator |
|---|---|---|
| Six VM list views (configuration, CPU, memory, virtual disk, network, storage and guest filesystem) | `content/collect-once-vm-*.view.xml` | `build_views.py` (also emits `import/views/collect-once-views.import.zip`) |
| Thirteen teaching Text widgets, universal by construction: the catalog names every Operations key against `reference/vm-statkeys.reference.json` and every vCenter counter against `reference/vcenter-perfcounters.reference.json`, both read live, and the build fails on a key that is not there | `content/widget-*.html` | `build_copy.py` (the copy source; emits the HTML the dashboard syncs verbatim) |
| The dashboard **PCA - Collection Strategy Guide**, 24 widgets: two per-VM charts driven by the CPU and memory lists, three PromQL Viewers (type `VODAP`) charting verified strategy queries on the Real-Time Metrics plane | `content/collection-strategy-guide.dashboard.json` | `build_dashboard.py` (also emits `import/dashboards/collection-strategy-guide.import.zip`; `--source-id` rebinds the PromQL source) |

The 2026-09-16 universal pass replaced one customer's metric list with the VM utilization catalog any warehouse asks for
(a vCenter counter column with statistics levels, a guest-OS-through-Tools family, the decision keys only Operations carries)
and cites the reference estate only where a number was measured; the dashboard, tab, and widget ids changed so the build
sits beside an earlier import. Every statkey is present on the 9.1 instance the views were authored against (read live 2026-09-16); every quoted metric
definition is VMware guidance's sentence; every number is a live measurement recorded in the charter; every PromQL query in the
guide was executed against this instance's Real-Time Metrics on 2026-09-16 by `promql/verify_promql.py`, whose
JSON outputs the copy generator reads, so the dashboard and the reference cannot drift apart. No super metrics: the
dashboard teaches the raw keys and their cadences on purpose. Rebuild after editing: `python build_copy.py && python build_views.py && python build_dashboard.py`;
gates: `python build_views.py --check`, `python build_dashboard.py --check`, `python ../lint_views.py`, `python ../lint_copy.py`.
