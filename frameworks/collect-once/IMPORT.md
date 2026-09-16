# Import guide - Collect Once, VM utilization

Order: import the views **before** the dashboard (the dashboard binds its views by id).

## 1. Views -> Visualize > Views > Manage > Import

| File | Contains |
|---|---|
| `import/views/collect-once-views.import.zip` | all six views (one click): PCA - Collect Once - VM - Configuration and State, CPU Demand and Contention, Memory Demand and Contention, Virtual Disk Workload, Network Workload, Storage and Guest Filesystem |

## 2. Dashboard -> Visualize > Dashboards > Manage > Import

| File | What it is |
|---|---|
| `import/dashboards/collection-strategy-guide.import.zip` | **PCA - Collection Strategy Guide** (binds the six views; import those first; do not unzip). The 2026-09-16 universal build carries new dashboard, tab, and widget ids (`...000002`, `...00ab`, widgets 101 and up), so it imports beside an earlier copy renamed in the UI |

The dashboard's list widgets ride the portable vSphere World provider, so they list every VM the importing instance
manages; click a row in the CPU or memory list to drive the two charts. Nothing is automated over the API: dashboards
have no REST surface, and the views follow the estate's Manage > Import path. Re-importing a changed dashboard
is delete-then-reimport; views update in place by id.

## 3. The PromQL Viewer's source (instance-specific)

The three PromQL Viewer widgets (type `VODAP`) chart the Real-Time Metrics of one VCF domain, and the dashboard JSON carries
that domain's resource id verbatim (the importer does not remap it). The committed value is this lab's workload domain
`the reference estate's workload domain` (a `VCFDomain` resource of the `VcfAdapter`). On another instance either rebuild with
`python build_dashboard.py --source-id <id>` (find the id with `GET /suite-api/api/resources?resourceKind=VCFDomain&adapterKind=VcfAdapter`)
or, after import, open the widget, Edit, choose the source, and save. The widget needs the Real-Time Metrics service and a
VCF instance; hosts must have the ESX Top (2-second) set enabled for the latency-tail viewer to draw anything; the other two run on the 20-second profile.

## Everything else is an intermediary (never imported)

`content/` holds the sources; `build_copy.py`, `build_views.py`, and `build_dashboard.py` regenerate them and the bundles.
