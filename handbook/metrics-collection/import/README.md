# Import the PCA - Collection Strategy Guide into VCF Operations

Two files, imported in this order, and one binding step afterwards. Nothing here writes through the API:
both imports take the product's own Manage > Import screens, the same path any content pack takes.

## Before you start

- **VCF Operations 9.1.** The six views name statkeys as the 9.1 vCenter adapter publishes them; every key was
  checked against a live statkey list when the views were built.
- **Real-Time Metrics on the VCF instance** the dashboard will read, for the three PromQL Viewer widgets. The
  other twenty-one widgets need nothing beyond the vCenter adapter and work without it.
- **The ESX Top 2-second set enabled on the hosts** for the latency-tail viewer; the other two viewers run on
  the 20-second profile every host has.
- **VMware Tools in the VMs** for the guest-OS family (the `guest|` keys in the storage and filesystem list).
- **An account that can import content:** the Manage menu must be visible under Visualize > Views and
  Visualize > Dashboards.

## 1. Views: Visualize > Views > Manage > Import

`views/collect-once-views.import.zip`, one file, do not unzip. It carries the six views: PCA - Collect
Once - VM - Configuration and State, CPU Demand and Contention, Memory Demand and Contention, Virtual Disk
Workload, Network Workload, Storage and Guest Filesystem. You know it worked when six views with those names
appear in the list. Views update in place by id, so a later copy of the same file replaces them.

## 2. Dashboard: Visualize > Dashboards > Manage > Import

`dashboards/collection-strategy-guide.import.zip`, one file, do not unzip. The dashboard binds the six
views by id, which is why the views go first: without them the six list widgets have nothing to show. You know
it worked when **PCA - Collection Strategy Guide** appears under Dashboards and its six lists fill with your own
VMs (the lists ride the vSphere World provider, so they show every VM the instance manages). The dashboard, its
tab, and its widgets carry ids of their own (`...000002`, `...00ab`, widgets 101 and up), so it imports beside
any earlier copy instead of replacing it. Re-importing a changed dashboard is delete, then import; dashboards
have no REST surface on this product.

## 3. Bind the three PromQL Viewers (the one instance-specific step)

The three viewers chart one VCF domain's Real-Time Metrics, and the dashboard JSON carries that domain's
resource id verbatim; the importer does not remap it. The committed value is a placeholder
(`00000000-0000-4000-8000-000000000000`, named "the VCF domain you choose at import") that charts nothing.
Bind it one of two ways:

- **After import:** open the dashboard, edit each of the three viewers (the widgets titled "Contention hot
  list at 20 seconds", "vCPU to physical core ratio per host", and "The 2-second tail"), choose your VCF domain
  as the source, save.
- **Before import:** rebuild the bundle with your id in `../../frameworks/collect-once/`: `python build_dashboard.py --source-id <id>`,
  where `<id>` is the resource id of your VCF domain
  (`GET /suite-api/api/resources?resourceKind=VCFDomain&adapterKind=VcfAdapter`).

The three queries run as written on any instance; they name metric families and features, never a host or a
VM. The reference estate's own copy was built with its source id bound, so the placeholder path above is the
guide's description of the widget editor rather than a rehearsed import; if yours behaves differently, open an
issue with what the screen showed.

## What you may want to adjust

- **Time.** Every widget reads the last hour; change it per widget with the widget's date filter.
- **Scope.** The lists show every VM the instance manages. On a large instance, point a list widget at a custom
  group instead of vSphere World in its edit dialog and the lesson reads the same on a smaller set.
- **Heights.** The text widgets were sized for a 1380 px wide window (twelve columns). Narrower windows wrap the
  text; drag a widget taller if its last lines are cut.
- Nothing else is environment-specific. Statkeys, units, and cadences are the product's, and the catalog text
  cites the reference estate only where a number was measured there.

## If something looks wrong

- **The six lists are empty.** The views were not imported, or were imported after the dashboard. Import the
  views, then delete and re-import the dashboard.
- **The three viewers are empty.** Step 3 was skipped, the instance has no Real-Time Metrics service, or, for
  the tail viewer only, the hosts do not have the ESX Top set enabled.
- **The storage and filesystem columns are empty for a VM.** No VMware Tools in that VM.
- **The two charts are empty.** They follow the selected VM: click a row in the CPU or memory list.

## Rebuild instead of adjust

The generators and sources live in `../../frameworks/collect-once/`: `build_copy.py` (the teaching text), `build_views.py` (the six views
and their bundle), `build_dashboard.py` (the dashboard and its bundle, `--source-id` to bind the viewers). The two files here are byte copies of the bundles those generators emit.
