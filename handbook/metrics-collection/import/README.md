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
(`00000000-0000-4000-8000-000000000000`, named "the VCF domain you choose at import"), so straight after
import each viewer shows the message "Unable to establish a connection with the Real-time metrics component.
Please verify the Cloud Proxy status and review the logs." That message is the unbound source, not a proxy
fault; bind the source before you read any log.

Bind it one of two ways:

- **After import, in the dashboard:** edit each of the three viewers (the widgets titled "Contention hot list
  at 20 seconds", "vCPU to physical core ratio per host", and "The 2-second tail"). Under Output Data, the
  Source field reads "No applicable VCF instance selected"; its list is grouped by VCF instance and offers each
  instance's domains (the management domain and the workload domains). Choose the domain whose vCenter holds
  the VMs you want charted, leave the toggle beside it at vCenter / vSAN (the default: the guide's queries name
  vCenter metric families, and the NSX setting reads the NSX manager's families under other names), and save.
  One viewer charts one domain; to chart a second domain, duplicate the widget and bind the copy.
- **Before import:** rebuild the bundle with your id in `../../frameworks/collect-once/`: `python build_dashboard.py --source-id <id>`,
  where `<id>` is the resource id of the domain
  (`GET /suite-api/api/resources?resourceKind=VCFDomain&adapterKind=VcfAdapter`).

The three queries run as written on any instance; they name metric families and features, never a host or a
VM. Rehearsed 2026-09-16 on a 9.1.0 instance with Real-Time Metrics deployed: the import accepts the
placeholder, the six lists fill, and the three viewers show the message above until a domain is bound, and chart as soon as a domain is chosen in the editor and saved.

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
- **The three viewers say "Unable to establish a connection with the Real-time metrics component".** The
  source is not bound (step 3). Bind it before reading logs; if the message stays with a domain chosen, check
  that the Real-Time Metrics service runs on that domain's VCF instance.
- **The tail viewer alone stays empty.** The hosts do not have the ESX Top 2-second set enabled.
- **The storage and filesystem columns are empty for a VM.** No VMware Tools in that VM.
- **The two charts are empty.** They follow the selected VM: click a row in the CPU or memory list.

## Rebuild instead of adjust

The generators and sources live in `../../frameworks/collect-once/`: `build_copy.py` (the teaching text), `build_views.py` (the six views
and their bundle), `build_dashboard.py` (the dashboard and its bundle, `--source-id` to bind the viewers). The two files here are byte copies of the bundles those generators emit.
