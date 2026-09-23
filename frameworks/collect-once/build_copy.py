#!/usr/bin/env python3
"""Author the PCA - Collection Strategy Guide's Text widgets: emits content/widget-*.html in the estate design system
(text-and-design.md: inline styles only, the exact palette and type scale). The emitted HTML files are the
sources build_dashboard.py syncs verbatim into editorData; edit the copy here, re-run, rebuild.

Universal by construction (2026-09-16 pass): the guide teaches the VM utilization catalog any warehouse asks for,
not one customer's list. The live lists are the importing instance's own VMs; the text carries rules, and cites
the reference estate only as the place where a number was measured. Every Operations statkey the copy names is
checked against reference/vm-statkeys.reference.json (a powered-on VM's statkey list read live) and every vCenter
counter against reference/vcenter-perfcounters.reference.json (PerformanceManager.perfCounter read live), so the
catalog cannot name a key that does not exist. The PromQL tables are generated from the promql folder beside the generators: .
Every metric definition in quotation marks is the sentence in VMware guidance.
Run:  python build_copy.py
"""
from __future__ import annotations
import json, os
HERE = os.path.dirname(os.path.abspath(__file__)); CONTENT = os.path.join(HERE, "content"); REFD = os.path.join(HERE, "reference")
FONT = "Metropolis,'Segoe UI',Arial,sans-serif"
def wrap(*parts): return '<div style="font-family:%s;color:#22303f;font-size:13px;line-height:1.55;padding:6px 4px">\n%s\n</div>\n' % (FONT, "\n".join(parts))
def h1(t): return '<div style="font-size:18px;font-weight:700;color:#16283f;letter-spacing:.2px">%s</div>' % t
def sub(t): return '<div style="font-size:12.5px;color:#5c6b7a;margin-top:3px;margin-bottom:14px">%s</div>' % t
def h2(t): return '<div style="font-size:13.5px;font-weight:700;color:#16283f;margin-bottom:6px;margin-top:12px">%s</div>' % t
def p(t): return '<div style="color:#3b4b5b;font-size:12.5px;margin-bottom:8px">%s</div>' % t
def m(t): return '<span style="font-family:Consolas,monospace;font-size:12px;color:#6b7886">%s</span>' % t
def callout(head, body, amber=False):
    bg, bd, lf, hc = ("#fff8ec", "#f0dfb8", "#e0a92e", "#7a5a12") if amber else ("#f4f7fa", "#dbe4ec", "#2f6fb0", "#16283f")
    return ('<div style="background:%s;border:1px solid %s;border-left:3px solid %s;border-radius:5px;padding:11px 13px;margin-bottom:14px">'
            '<div style="font-size:13.5px;font-weight:700;color:%s;margin-bottom:5px">%s</div><div style="color:#3b4b5b;font-size:12.5px">%s</div></div>') % (bg, bd, lf, hc, head, body)
def chip(color, text): return '<span style="display:inline-block;width:11px;height:11px;background:%s;border-radius:2px;margin-right:6px;vertical-align:middle"></span>%s' % (color, text)
GOLD, HOURLY, HOT = "#4b9b45", "#8abf5b", "#ecc33e"
def table(headers, rows, widths=None):
    th = "".join('<th style="text-align:left;padding:5px 9px;border-bottom:2px solid #d7dee5;font-weight:600;color:#2f4256;background:#eef2f6%s">%s</th>' % ((";width:%s" % widths[i]) if widths and widths[i] else "", h) for i, h in enumerate(headers))
    trs = "".join("<tr>" + "".join('<td style="padding:5px 9px;border-bottom:1px solid #eef2f6;color:#3b4b5b;vertical-align:top">%s</td>' % c for c in r) + "</tr>" for r in rows)
    return '<table style="border-collapse:collapse;width:100%%;font-size:12.5px;margin-bottom:12px"><thead><tr>%s</tr></thead><tbody>%s</tbody></table>' % (th, trs)
def kv(rows):
    return '<table style="border-collapse:collapse;width:100%%;font-size:12.5px;margin-bottom:12px">%s</table>' % "".join('<tr><td style="padding:5px 10px 5px 0;vertical-align:top;width:170px;font-weight:600;color:#2f4256">%s</td><td style="padding:5px 0;color:#3b4b5b">%s</td></tr>' % r for r in rows)
def ol(items): return '<ol style="margin:0 0 10px 18px;padding:0;color:#3b4b5b;font-size:12.5px">%s</ol>' % "".join("<li style=\"margin-bottom:5px\">%s</li>" % i for i in items)
def ul(items): return '<ul style="margin:0 0 10px 18px;padding:0;color:#3b4b5b;font-size:12.5px">%s</ul>' % "".join("<li style=\"margin-bottom:5px\">%s</li>" % i for i in items)
def source(t): return '<div style="font-size:11px;color:#7a8794;border-top:1px solid #eef2f6;padding-top:8px;margin-top:6px">Source: %s</div>' % t
SRC_LIVE = "measured on the reference estate, one VCF 9.1 instance, 2026-09-15 and 2026-09-16 (the Collect Once, Decide at Source charter and its lab records)"
SRC_DOC = "Broadcom TechDocs, VCF 9.1, Virtual Machine Metrics (metric definitions quoted verbatim)"
SRC_VC = "vSphere Web Services API, PerformanceManager.perfCounter, read live on vCenter 9.1 (counter names, rollups, units, statistics levels)"

# ---------------------------------------------------------------- reference lists: every key named below must exist
_SK = json.load(open(os.path.join(REFD, "vm-statkeys.reference.json"), encoding="utf-8")); STATKEYS = set(_SK["keys"])
_PC = json.load(open(os.path.join(REFD, "vcenter-perfcounters.reference.json"), encoding="utf-8")); COUNTERS = _PC["counters"]
# catalog keys the reference VM does not carry: named only with the words "not collected on the reference estate"
NOT_COLLECTED = {"mem|vmmemctl_average", "mem|latency_average", "virtualDisk|readOIO_latest", "virtualDisk|writeOIO_latest", "net|droppedRx_summation", "guestfilesystem|freespace_total", "cost|reclaimableCost", "cpu|20_sec_peak_swapwaitPct"}
def K(key, nc=False):
    """An Operations statkey, checked against the reference VM's statkey list (or the explicit not-collected set)."""
    if nc: assert key in NOT_COLLECTED, key
    else: assert key in STATKEYS, "statkey not on the reference VM: " + key
    return m(key)
def P(key): return "property " + m(key)
def VC(name, rollup=None):
    """A vCenter PerformanceManager counter with its rollup, unit, and statistics level, from the live-read reference list."""
    assert name in COUNTERS, "counter not in the reference list: " + name
    rows = COUNTERS[name]; r = next((x for x in rows if rollup is None or x["rollup"] == rollup), rows[0])
    unit = {"percent": "%", "megaHertz": "MHz", "millisecond": "ms", "kiloBytes": "KB", "kiloBytesPerSecond": "KBps", "number": "count", "second": "s", "watt": "W"}.get(r["unit"], r["unit"])
    return m("%s.%s" % (name, r["rollup"])) + " (%s, L%s)" % (unit, r["level"])

W = {}
# ---------------------------------------------------------------- 1. start here
W["start"] = wrap(
 h1("Collection strategy: what Operations already holds"),
 sub("The VM utilization catalog a warehouse asks for, shown live on the importing instance: each family mapped to the plane that owns it, the cadence it is kept at, and the tier that carries it."),
 callout("The one idea: every counter in the catalog is already collected here, once",
  "The vCenter adapter samples every VM through vStats every 20 seconds and stores one value per statkey per 5 minutes: the <b>mean of the fifteen samples</b> (within 2 to 4 percent, measured on the reference estate). A few counters also keep the highest 20-second sample of the cycle in a separate <b>peak</b> key. The store keeps 5-minute values for 6 months, then hourly values for 36 months. Nothing below needs a second pull from vCenter; the work is to extract by tier."),
 h2("Three planes read the same host"),
 table(["Plane", "Cadence and keeping", "What it is for"], [
  ["vCenter PerformanceManager", "20-second real-time samples, rolled up to 5 minutes for a day, 30 minutes for a week, 2 hours for a month, a day for a year; shaped by the statistics level (1 by default), and many counters in the catalog below sit above level 1", "the classic charts and any SOAP client; the path a monitoring platform's vCenter integration re-pulls, which duplicates the plane below"],
  ["VCF Operations analytics store (this dashboard)", "20-second samples through vStats, independent of the statistics level; one 5-minute mean per statkey plus peak keys; 6 months at 5 minutes, then hourly for 36 months", "utilization, rightsizing, capacity, reclaim, placement: the decisions, and the extraction source"],
  ["Real-Time Metrics (9.1, per VCF instance)", "20-second series kept 15 days; a 2-second ESX Top set per opted-in host, cut per source at the store's own moments", "the troubleshooting workbench and a scoped hot-set; not a BI feed"]]),
 h2("How to read this dashboard"),
 p("One row per family of the catalog: configuration and state, CPU, memory, virtual disk, network, storage and guest filesystem. Each row is a live list of the virtual machines on the importing instance beside a note on cadence and meaning. Then two charts that draw a selected VM's 5-minute mean beside its hidden peak, three PromQL Viewers on the Real-Time Metrics plane with the language it speaks, a panel on what should not come from Operations and when, and the extraction contract that feeds the ELT, including the calls behind the viewers."),
 p(chip(GOLD, "gold layer, daily") + " &nbsp; " + chip(HOURLY, "analysis tier, hourly AVG and MAX") + " &nbsp; " + chip(HOT, "hot-set, native 5-minute or real-time") + " &nbsp; The tier chips in the catalog say which tier carries each family."),
 source(SRC_LIVE + "; " + SRC_DOC + "."))
# ---------------------------------------------------------------- 2. the catalog
def T(c, t): return chip(c, t)
rows = [
 ["<b>Configuration and state</b>", "", "", "", "", ""],
 ["vCPU count", "no counter (inventory)", K("config|hardware|num_Cpu") + "; also a property", "latest, and a property", T(GOLD, "gold"), "Number of CPUs"],
 ["memory configured", "no counter (inventory)", K("mem|guest_provisioned") + " (KB); " + P("config|hardware|memoryKB"), "latest, and a property", T(GOLD, "gold"), "Memory Total Capacity; normalize the unit in the warehouse"],
 ["power state", "no counter", P("summary|runtime|powerState") + "; metric " + K("sys|poweredOn"), "property, and a 0/1 metric", T(GOLD, "gold"), "Powered On or Powered Off"],
 ["connection state", "no counter", P("summary|runtime|connectionState"), "property", T(GOLD, "gold"), "connected, disconnected, orphaned, inaccessible"],
 ["uptime, OS uptime", VC("sys.uptime") + "; " + VC("sys.osUptime"), K("sys|uptime_latest") + "; " + K("sys|osUptime_latest"), "5-minute latest", T(GOLD, "gold"), "seconds; OS uptime needs level 4 on vCenter, level-independent here"],
 ["template flag, NIC count", "no counter", P("summary|config|isTemplate") + "; " + P("summary|config|numEthernetCards"), "properties", T(GOLD, "gold"), ""],
 ["identity", "no counter", "identifiers " + m("VMEntityVCID") + " + " + m("VMEntityObjectID") + "; " + P("summary|MOID") + "; " + m("VMEntityInstanceUUID"), "resource identifiers", T(GOLD, "gold"), "the observation key: vCenter instance UUID plus MOID, both of which change on a move; carry the instance UUID to resolve it"],
 ["Tools state, guest OS", "no counter", "properties " + m("summary|guest|toolsRunningStatus") + ", " + m("summary|guest|toolsVersionStatus2") + ", " + m("summary|guest|fullName") + "; metric " + K("guest|tools_running_status"), "properties, one metric", T(GOLD, "gold"), ""],
 ["<b>CPU</b>", "", "", "", "", ""],
 ["CPU demand (%)", VC("cpu.demand") + ", as a percentage of configured", K("cpu|demandPct"), "5-minute mean", T(HOURLY, "hourly"), "the sizing signal"],
 ["CPU demand (MHz)", VC("cpu.demand"), K("cpu|demandmhz"), "5-minute mean", T(HOURLY, "hourly"), "&quot;Total CPU resources required by the workloads on the virtual machine.&quot;"],
 ["CPU usage (MHz)", VC("cpu.usagemhz", "average"), K("cpu|usagemhz_average"), "5-minute mean", T(HOURLY, "hourly"), ""],
 ["CPU usage (%)", VC("cpu.usage", "average"), K("cpu|usage_average"), "5-minute mean", T(HOURLY, "hourly"), "carries a (DEP) mark in its display name on 9.1; prefer demand (%)"],
 ["CPU ready (%)", VC("cpu.ready") + ", milliseconds per sample", K("cpu|readyPct") + " + peak " + K("cpu|20_sec_peak_readyPct"), "5-minute mean + in-cycle peak", T(HOURLY, "hourly") + " " + T(HOT, "hot-set"), "Operations converts the summation to percent; the peak key keeps the 20-second maximum"],
 ["CPU co-stop (%)", VC("cpu.costop"), K("cpu|costopPct") + " + peak " + K("cpu|20_sec_peak_costopPct"), "5-minute mean + in-cycle peak", T(HOURLY, "hourly") + " " + T(HOT, "hot-set"), "co-scheduling contention across vCPUs"],
 ["CPU swap wait (%)", VC("cpu.swapwait"), K("cpu|swapwaitPct") + "; its peak key " + K("cpu|20_sec_peak_swapwaitPct", nc=True) + " is in the catalog but not collected on the reference estate", "5-minute mean", T(HOURLY, "hourly"), "level 3 on vCenter"],
 ["CPU I/O wait (%)", "no vCenter VM counter", K("cpu|iowaitPct") + " + peak " + K("cpu|20_sec_peak_iowaitPct"), "5-minute mean + in-cycle peak", T(HOURLY, "hourly"), ""],
 ["CPU contention (%)", "nearest: " + VC("cpu.latency"), K("cpu|capacity_contentionPct"), "5-minute mean", T(HOURLY, "hourly") + " " + T(HOT, "hot-set"), "derived by Operations: the stolen time as one number"],
 ["<b>Memory</b>", "", "", "", "", ""],
 ["memory active", VC("mem.active", "average"), K("mem|active_average") + " (KB)", "5-minute mean", T(HOURLY, "hourly"), "Guest Active: the demand estimate, itself a rolling average"],
 ["memory consumed", VC("mem.consumed", "average"), K("mem|consumed_average") + " (KB)", "5-minute mean", T(HOURLY, "hourly"), "&quot;Amount of host memory consumed by the virtual machine for guest memory&quot;"],
 ["memory usage (%)", VC("mem.usage", "average"), K("mem|usage_average"), "5-minute mean", T(HOURLY, "hourly"), "active as a percentage of configured"],
 ["memory ballooned", VC("mem.vmmemctl", "average"), K("mem|balloonPct") + " (%); the KB key " + K("mem|vmmemctl_average", nc=True) + " is in the catalog but not collected on the reference estate", "5-minute mean", T(HOURLY, "hourly"), "&quot;Percentage of total memory that has been reclaimed via ballooning&quot;"],
 ["memory compressed, swapped", VC("mem.compressed") + "; " + VC("mem.swapped", "average"), K("mem|compressed_average") + ", " + K("mem|swapped_average") + " (KB)", "5-minute mean", T(HOURLY, "hourly"), "the rest of the reclamation ladder"],
 ["memory swap in, out rate", VC("mem.swapinRate") + "; " + VC("mem.swapoutRate"), K("mem|swapinRate_average") + ", " + K("mem|swapoutRate_average") + " (KBps)", "5-minute mean", T(HOURLY, "hourly"), "the pressure signal that is collected"],
 ["memory contention (%)", VC("mem.latency"), K("mem|host_contentionPct") + " + peak " + K("mem|20_sec_peak_host_contentionPct") + "; " + K("mem|latency_average", nc=True) + " is in the catalog but not collected on the reference estate", "5-minute mean + in-cycle peak", T(HOURLY, "hourly") + " " + T(HOT, "hot-set"), "&quot;Percent memory contention.&quot;"],
 ["memory as the guest reports it", "no counter (VMware Tools)", K("mem|guest_usage") + "; " + K("guest|used_memory") + ", " + K("guest|mem.free_latest") + ", " + K("guest|mem.needed_latest") + ", " + K("guest|mem.physUsable_latest") + " (KB)", "5-minute, when Tools reports", T(HOURLY, "hourly"), "blank without Tools; a blank is absence, never zero"],
 ["<b>Guest OS through VMware Tools</b> (conditional)", "", "", "", "", ""],
 ["guest swap remaining, page rates", "no counter (VMware Tools)", K("guest|swap.spaceRemaining_latest") + "; " + K("guest|page.inRate_latest") + ", " + K("guest|page.outRate_latest") + " + peak " + K("guest|20_sec_peak_page.outRate_latest"), "5-minute mean + one peak", T(HOURLY, "hourly"), "the OS-side memory pressure the hypervisor cannot infer"],
 ["guest run queue, disk queue, context switches", "no counter (VMware Tools)", K("guest|cpu_queue") + " (per vCPU) + peak " + K("guest|20_sec_peak_cpu_queue") + "; " + K("guest|disk_queue") + " + peak " + K("guest|20_sec_peak_disk_queue") + "; " + K("guest|contextSwapRate_latest") + " + peak " + K("guest|20_sec_peak_contextSwapRate_latest"), "5-minute mean + in-cycle peak", T(HOURLY, "hourly") + " " + T(HOT, "hot-set"), "the run queue is stored per vCPU and the disk queue divided by 100 relative to the Real-Time Metrics plane"],
 ["guest filesystem capacity, used, used (%)", "no counter (VMware Tools)", K("guestfilesystem|capacity_total") + ", " + K("guestfilesystem|usage_total") + " (GB), " + K("guestfilesystem|percentage_total") + " (%); free is capacity minus used (" + K("guestfilesystem|freespace_total", nc=True) + " is not collected on the reference estate)", "5-minute, when Tools reports", T(GOLD, "gold"), "per-filesystem instances as " + m("guestfilesystem:&lt;mount&gt;|...")],
 ["<b>Virtual disk</b>", "", "", "", "", ""],
 ["disk read, write IOPS", VC("virtualDisk.numberReadAveraged") + "; " + VC("virtualDisk.numberWriteAveraged"), K("virtualDisk:Aggregate of all instances|numberReadAveraged_average") + ", " + m("...|numberWriteAveraged_average") + "; the busiest disk's IOPS in " + K("virtualDisk|peak_vDisk_iops"), "5-minute mean", T(HOURLY, "hourly"), "an instanced family: the VM-level value lives under the Aggregate of all instances instance; per disk as " + m("virtualDisk:&lt;disk&gt;|...") + "; the highest-of-all-instances key is a 5-minute average of one disk, not a time peak"],
 ["disk read, write throughput", VC("virtualDisk.read") + "; " + VC("virtualDisk.write"), K("virtualDisk|read_average") + ", " + K("virtualDisk|write_average") + " (KBps)", "5-minute mean", T(HOURLY, "hourly"), ""],
 ["disk read, write latency", VC("virtualDisk.totalReadLatency") + "; " + VC("virtualDisk.totalWriteLatency"), K("virtualDisk:Aggregate of all instances|totalReadLatency_average") + ", " + m("...|totalWriteLatency_average") + " (ms) + in-cycle peak " + K("virtualDisk|20_sec_peak_totalLatency_average") + "; the busiest disk's latency in " + K("virtualDisk|peak_vDisk_readLatency") + " and " + K("virtualDisk|peak_vDisk_writeLatency"), "5-minute mean + in-cycle peak", T(HOURLY, "hourly") + " " + T(HOT, "hot-set"), "milliseconds; the plain catalog key returns nothing; highest-of-all-instances keys are one disk's 5-minute average"],
 ["disk outstanding IO", VC("virtualDisk.readOIO") + "; " + VC("virtualDisk.writeOIO"), K("virtualDisk:Aggregate of all instances|vDiskOIO") + " (both directions); " + K("virtualDisk|readOIO_latest", nc=True) + " and " + K("virtualDisk|writeOIO_latest", nc=True) + " are in the catalog but not collected on the reference estate", "5-minute", T(HOURLY, "hourly"), ""],
 ["datastore throughput", VC("disk.usage", "average"), K("disk|usage_average") + " (KBps)", "5-minute mean", T(HOURLY, "hourly"), "all virtual disks of the VM against their datastores"],
 ["<b>Network</b>", "", "", "", "", ""],
 ["network usage, receive, transmit", VC("net.usage", "average") + "; " + VC("net.received") + "; " + VC("net.transmitted"), K("net|usage_average") + " + peak " + K("net|20_sec_peak_usage_average") + "; " + K("net|received_average") + ", " + K("net|transmitted_average") + " (KBps)", "5-minute mean + in-cycle peak", T(HOURLY, "hourly"), "per-vNIC instances exist"],
 ["network packets per second", VC("net.packetsRx") + "; " + VC("net.packetsTx"), K("net:Aggregate of all instances|packetsRxPerSec") + ", " + m("...|packetsTxPerSec") + " + peak " + K("net|20_sec_peak_packetsPerSec"), "5-minute", T(HOURLY, "hourly"), "an instanced family; Operations stores rates, vCenter counts per sample; per vNIC as " + m("net:&lt;nic&gt;|...")],
 ["network drops", VC("net.droppedRx") + "; " + VC("net.droppedTx"), K("net:Aggregate of all instances|droppedPct") + " (%); " + K("net|droppedTx_summation") + " (count per cycle); " + K("net|droppedRx_summation", nc=True) + " is not collected on the reference estate", "5-minute", T(HOURLY, "hourly"), "the count keys carry a (DEP) mark on 9.1"],
 ["<b>VM storage</b>", "", "", "", "", ""],
 ["storage used, provisioned, not shared", VC("disk.used") + "; " + VC("disk.provisioned") + "; " + VC("disk.unshared"), K("diskspace|used") + ", " + K("diskspace|provisionedSpace") + ", " + K("diskspace|notshared") + " (GB)", "5-minute latest", T(GOLD, "gold"), "&quot;Space used by virtual machine files&quot;; uncommitted is provisioned minus used; per datastore as " + m("diskspace:&lt;datastore&gt;|provisioned")],
 ["snapshot space, count", "no counter", K("diskspace|snapshot|used") + " (GB); " + K("summary|snapshot_count") + ", " + K("summary|snapshotSpace"), "5-minute latest", T(GOLD, "gold"), "a reclaim input"],
 ["<b>Decisions only Operations carries</b>", "", "", "", "", ""],
 ["oversized, undersized", "no counter (analytics)", K("summary|oversized") + ", " + K("summary|oversized|vcpus") + ", " + K("summary|oversized|memory") + " (KB); " + K("summary|undersized") + ", " + K("summary|undersized|vcpus") + ", " + K("summary|undersized|memory"), "daily analytics", T(GOLD, "gold"), "the rightsizing verdict per VM with the reclaimable amounts"],
 ["recommended size", "no counter (analytics)", K("OnlineCapacityAnalytics|cpu|recommendedSize") + " (MHz), " + K("OnlineCapacityAnalytics|mem|recommendedSize") + " (KB), " + K("OnlineCapacityAnalytics|diskspace|recommendedSize") + " (GB)", "daily analytics", T(GOLD, "gold"), "the projected size under the policy's risk level; read it, never recompute it"],
 ["idle, reclaimable cost", "no counter (analytics)", K("summary|idle") + "; " + K("cost|reclaimableCost", nc=True) + " where costing is configured", "daily analytics", T(GOLD, "gold"), "the reclaim inputs; the datacenter reclaim and rightsize lists carry the same numbers in different units"],
]
W["mapping"] = wrap(
 h1("The VM utilization catalog, mapped to Operations"),
 sub("Whatever a pipeline calls a metric, it is one of these. For each: the vCenter counter it usually derives from, with the statistics level vCenter needs to keep it beyond the real-time window; the Operations key that holds it; how it is kept; and the tier that carries it."),
 table(["Metric", "vCenter counter (rollup, unit, level)", "Operations key", "Kept as", "Tier", "Note"], rows, ["13%", "19%", "32%", "10%", "8%", "18%"]),
 callout("How to use the catalog with any list",
  "Take each name on a list, find its row by the vCenter counter or by the meaning, and copy the Operations key and the tier. A name with no row is one of three things: a guest-agent item that the panel on what should not come from Operations covers; a value the warehouse derives from rows here (uncommitted space, free filesystem space, utilization ratios); or a host, cluster, or datastore metric outside the VM scope of this guide."),
 callout("The statistics level is the trap a direct pull walks into",
  "vCenter keeps a counter beyond its real-time window only at or above the counter's level, and the default is 1. CPU demand, co-stop, active memory, swapped memory, and the network packet and drop counters sit at level 2; swap wait at 3; readiness and OS uptime at 4. Raising the level to feed a pull is the wrong fix; Operations reads every counter here through vStats at 20 seconds whatever the level says."),
 callout("Reading a dash: three causes, none of them zero",
  "A zero is a value and shows as 0. A dash is absence, with three causes. <b>No data for the object:</b> a powered-off VM emits no counters, so most of its performance keys are blank while its configuration keys still read; a few keys carry a 0 for it instead (CPU demand, the network byte rates, guest filesystem used), so the rows of powered-off VMs mix dashes and zeros. <b>A conditional source:</b> the guest family and Guest Usage need VMware Tools. <b>A key the resource does not collect:</b> the catalog lists more keys than the adapter emits under the effective policy, and an instanced family (virtual disk latency, IOPS, outstanding IO; network packets and drops) carries its VM-level value under the <b>Aggregate of all instances</b> instance, so the plain key returns nothing. The lists on this dashboard bind the collected names; ask a resource's own statkey list before assuming any other key is collected."),
 p("Units come from the platform: KB for memory, MHz for CPU, KBps for throughput, ms for latency, GB for disk space; normalize in the warehouse, never by a super metric. Keys marked (DEP) on 9.1 still serve values where they are collected; prefer the current key beside them."),
 source(SRC_DOC + "; " + SRC_VC + "; statkey and property presence read live on the reference estate, 2026-09-16 (every key above is checked against that list at build time)."))
# ---------------------------------------------------------------- 3. configuration
W["config"] = wrap(
 h1("Configuration and state"),
 sub("The rarely changing half of the catalog: configured size, power and connection state, Tools, identity."),
 p("Configured capacity and state live mostly as <b>properties</b> (read through the properties API, one call per resource or in bulk), and a few also as metrics: the vCPU count and Memory Total Capacity are both. The list beside this note shows the metric forms."),
 kv([("Read daily", "with the inventory: " + m("GET /api/resources") + " (identifiers) and " + m("GET /api/resources/{id}/properties") + " (configuration, state, Tools, guest OS)."),
     ("The key", m("VMEntityVCID") + " + " + m("VMEntityObjectID") + " are the resource identifiers Operations marks unique; " + m("summary|MOID") + " repeats the MOID as a property."),
     ("Uptime and Powered ON", "blank means the VM is powered off: no counter is emitted, so Uptime and OS Uptime read blank and Powered ON reads 0 or blank, both meaning off. Neither depends on VMware Tools."),
     ("Blank Tools fields", "a property missing from the response means the source did not report it; reconcile against the inventory before landing anything as a value.")]),
 source(SRC_LIVE + "."))
# ---------------------------------------------------------------- 4. cpu
W["cpu"] = wrap(
 h1("CPU: demand is the signal, ready and co-stop are the contention"),
 sub("Size from demand; read Ready, Co-stop, and Swap wait as hypervisor scheduling contention no guest agent can see."),
 kv([("Demand (MHz)", "&quot;Total CPU resources required by the workloads on the virtual machine.&quot; The sizing signal; the p95 column is its 95th percentile over the selected 7 days."),
     ("Ready (%)", "&quot;Percentage of time in which the VM was waiting in line to use the CPU on the host.&quot;"),
     ("Co-stop (%)", "The percentage of time the VM is ready to run but cannot, because of co-scheduling constraints across its vCPUs."),
     ("Swap wait (%)", "&quot;Percentage swap waits for CPU.&quot;"),
     ("Peak columns", "the highest 20-second sample inside the 5-minute cycle, kept in its own key; the mean beside it hides it.")]),
 p("Zeros are values and blanks are absence: swap wait and co-stop read 0 on VMs under no co-scheduling pressure, and every blank cell is a powered-off VM."),
 callout("What the 5-minute mean loses, measured",
  "Across 36 windows on the reference estate the median peak hidden by the mean was 18 to 25 percent for CPU MHz (p90 39 percent, worst 60 percent) and 72 percent for host CPU contention (worst 4.6 times the mean). The peak keys and the hourly MAX rollup are how the analysis tier keeps it."),
 source(SRC_DOC + "; " + SRC_LIVE + "."))
# ---------------------------------------------------------------- 5. memory
W["memory"] = wrap(
 h1("Memory: active is demand, consumed is footprint"),
 sub("Keep configured, active, consumed, and guest-reported memory as separate fields; they answer different questions."),
 kv([("Guest Active", "the hypervisor's estimate of recently touched memory, itself a rolling average of about four minutes, so sampling it faster stores noise the source already damped. The demand signal for rightsizing."),
     ("Consumed", "&quot;Amount of host memory consumed by the virtual machine for guest memory in kilobytes.&quot; The footprint."),
     ("Balloon, Compressed, Swapped", "the reclamation ladder in order: balloon first (&quot;Percentage of total memory that has been reclaimed via ballooning&quot;), then compression, then swap. Any of them above zero is memory pressure on the host."),
     ("Contention (%)", "&quot;Percent memory contention.&quot; With its in-cycle peak key."),
     ("Guest Usage", "what VMware Tools reports from inside the guest; blank without Tools. With current Tools the guest family also carries free, needed, and physically usable memory, swap space remaining, and the page rates: the OS-side pressure signals, in the catalog above.")]),
 callout("Measured", "The median peak the mean hides is 8 percent for active memory, because the source is already a slow average. Size from active, confirm with the guest-reported numbers, and treat balloon or swap above zero as the pressure signal. Where the ladder reads 0 on every powered-on VM there is no memory pressure; the columns are here so the ladder is visible the day it engages."),
 source(SRC_DOC + "; " + SRC_LIVE + "."))
# ---------------------------------------------------------------- 6. disk and network
W["disknet"] = wrap(
 h1("Virtual disk and network: throughput is a mean, latency and drops carry the peak"),
 sub("Rates in KBps and packets per second; latency in milliseconds; drops as a percentage and as per-cycle counts."),
 p("Read and write latency are &quot;Average amount of time for a read operation from the virtual disk&quot; and the write counterpart, in milliseconds. Outstanding read and write requests are the queue. The peak latency column keeps the 20-second maximum inside the cycle; the highest-IOPS column is the busiest disk's 5-minute average, VMware guidance's &quot;Highest IOPS of all instances&quot;, not a time peak. Network usage has its own in-cycle peak key, and packets have a peak rate. Latency, IOPS, outstanding IO, packets, and the dropped percentage are instanced families: the VM-level value lives under the Aggregate of all instances instance, per-disk and per-vNIC instances beside it, and the plain catalog key returns nothing. The lists read the aggregates."),
 p("Measured on the reference estate, the median peak hidden by the 5-minute mean was 54 percent for network usage. Drops are counted per cycle (the count keys carry a (DEP) mark on 9.1; the percentage is the current key); a warehouse that wants totals sums the cycles rather than expecting a cumulative counter."),
 callout("A 0 in the KBps columns beside a packet rate above zero is real, not a gap",
  "vSphere returns every performance sample as a 64-bit integer, so a VM moving less than half a kilobyte per second samples as 0 KBps while its packets per second, a fractional rate, still show the traffic. The 5-minute mean of fifteen integer samples is therefore always a multiple of one fifteenth (the 0.07, 0.13, and 0.27 in the list), which every nonzero KBps value checked on the reference estate was, and the byte-rate columns become informative above about 1 KBps."),
 source(SRC_DOC + "; vSphere Web Services API, PerfMetricIntSeries (&quot;An array of 64-bit integer values&quot;); " + SRC_LIVE + "."))
# ---------------------------------------------------------------- 7. storage
W["storage"] = wrap(
 h1("Storage capacity from the hypervisor, filesystem from Tools"),
 sub("Two sources in one row: what vCenter knows about the VM's files, and what VMware Tools reports from inside."),
 kv([("Provisioned, VM used, Not Shared, Snapshot", "the vSphere storage view of the VM: &quot;Provisioned space in gigabytes&quot;, &quot;Space used by virtual machine files&quot;, &quot;Space used by VMs that is not shared&quot;, &quot;Space used by snapshots&quot;. Uncommitted is provisioned minus used."),
     ("Guest filesystem", "&quot;Total capacity on guest file system&quot;, utilization, and free space, from VMware Tools; conditional. A blank cell is absence, never zero."),
     ("Zeros and blanks here", "Snapshot Used reads 0 where a VM has no snapshot; the reclaim input is the nonzero rows. Guest filesystem capacity and utilization are blank on powered-off VMs and on powered-on VMs whose Tools are not running; guest filesystem used reads 0 on the powered-off ones."),
     ("Not here", "per-process CPU and memory, service state, inodes, logs, and application counters: the guest agent's job (see the panel below).")]),
 source(SRC_DOC + "."))
# ---------------------------------------------------------------- 8. chart intro
W["charts"] = wrap(
 h1("Select a VM in the CPU or memory list to draw its mean beside its hidden peak"),
 p("The chart draws the 5-minute mean (Ready, Contention) and the peak key that kept the highest 20-second sample of the same cycle. The gap between the two lines is what the hourly MAX keeps and what a mean-only extract loses."))
# ---------------------------------------------------------------- 8b. real-time metrics beside the PromQL Viewer widgets
# The tables below are generated from the verified reference the promql folder beside the generators: {examples,functions}.json (verify_promql.py),
# so the dashboard and the reference cannot drift apart.
_REF = os.path.normpath(os.path.join(HERE, "..", "..", "..", "docs", "reference", "promql"))
if not os.path.isdir(_REF): _REF = os.path.join(HERE, "promql")  # the public companion ships the reference beside the generators
_EX = json.load(open(os.path.join(_REF, "examples.json"), encoding="utf-8")); _FN = json.load(open(os.path.join(_REF, "functions.json"), encoding="utf-8"))
_DATE = _EX["generated"]
def _esc(t): return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
W["promql"] = wrap(
 h1("Real-Time Metrics, live: the plane beside the store"),
 sub("The three PromQL Viewers around this note draw the Real-Time Metrics of one VCF instance with three of the ten queries the reference verified. Read them as the troubleshooting and hot-set plane; the extraction contract below stays on the analytics store."),
 callout("What the widget is",
  "&quot;The PromQL Viewer widget uses the Prometheus Query Language to identify real-time data to be visualized.&quot; It needs the Real-Time Metrics service and a VCF instance; in self-provider mode its source is one VCF domain, chosen in each widget's source setting, and it always runs a range query over its own time control. Edit a widget, paste a query from the panel below into Query, and Validate."),
 h2("Read a name, pin the feature"),
 kv([("A name", "family.counter.OBJECT; the suffix is the object the series describes. On the reference estate a vCenter source lists 171 to 175 names out of a 437-name engine catalog; the widget's Metrics tab lists 1,345 and the VMware guidance per-provider list 1,478, and none of the three is a subset of another. The catalog that counts is the metadata endpoint of the query service, per source."),
     ("The labels", "lowercase on this build: " + m("vm") + ", " + m("host") + ", " + m("cluster") + ", " + m("datacenter") + " carry vCenter MOIDs (VMware guidance's examples write " + m("HOST='host-17'") + ", which matches nothing); " + m("host_fqdn") + ", " + m("host_ip") + ", " + m("vc_ip") + " are the readable ones; " + m("feature") + " and " + m("profile") + " name the collection set; " + m("mem") + " names the tier on MEMTYPE names."),
     ("Cadence", "20-second samples on the ESXi profile, the vCenter data profile, and the PerformanceManager profile (its name carries 300, the collection interval; the samples are 20 seconds apart); 2-second samples on the ESX Top profile for hosts that opted in. " + m("count_over_time(x[1m])") + " reads 3 or 30 and settles it."),
     ("Two cadences under one name", "19 names serve both a 20-second series (" + m("feature='TROUBLESHOOTING'") + ") and a 2-second series (" + m("feature='ESX_TOP'") + "). Without the matcher a chart draws both; pin the feature."),
     ("What it keeps", "20-second series for 15 days; the 2-second set for a shorter window, cut per source at the store's own moments; every call serves at most 101 series and flags it in a warning, never an error.")]),
 callout("Not the BI feed",
  "The query a widget runs is the same call the API serves, " + m("GET /data-query-service/api/v1/query_range") + " with " + m("sourceId") + " set to the vCenter instance and a service token. It is the hot-set lane of the contract below: a scoped set of contention series, extracted within hours, kept in the region. The 5-minute store and its hourly rollups remain the extraction source, and the panel below shows why: they are rollups of these same samples.", amber=True),
 source("Broadcom TechDocs, VCF 9.1, PromQL Widget and PromQL Queries; names, labels, cadences and feature sets read live from the reference estate's Real-Time Metrics on " + _DATE + " (the promql folder)."))
_LANE = {"discovery": "discovery", "hot-set": "hot-set", "cross-plane": "cross-plane proof", "gold": "gold layer", "troubleshooting": "troubleshooting"}
_rows = []
for e in _EX["examples"]:
    v = e["verified"]; served = ("%d series" % v["series"]) if v["series"] else ("empty while the object reports" if e["id"] == "E9" else "empty")
    q = m(_esc(e["query"])) + ((" and " + m(_esc(e["companion"]))) if e.get("companion") else "")
    _rows.append([e["id"], _LANE.get(e["lane"], e["lane"]), q, e["decision"], served])
_cp = {}
for c in _EX.get("crossplane", []): _cp.setdefault(c["rtm_name"], []).append(c)
def _fmt(c_list, key):
    vals = sorted(x[key] for x in c_list); return "%.2f to %.2f" % (vals[0], vals[-1]) if vals[0] != vals[-1] else "%.2f" % vals[0]
_cprows = []
for name, cl in _cp.items():
    ops_keys = m(_esc(cl[0]["ops_mean_key"])) + ", " + m(_esc(cl[0]["ops_peak_key"]))
    if name == "guest.cpu.runQueue.VM": mean = peak = "equals the VM's vCPU count (" + ", ".join(str(int(x["mean_ratio_rtm_over_ops_median"])) for x in cl) + ")"
    else: mean = _fmt(cl, "mean_ratio_rtm_over_ops_median"); peak = _fmt(cl, "peak_ratio_rtm_over_ops_median")
    _cprows.append([m(_esc(name)), ops_keys, mean, peak, "%d VMs, %d buckets each" % (len(cl), cl[0]["buckets"])])
_fnrows = []
for f in _FN:
    v = f["verified"]; c = f["cautions"][0] if f["cautions"] else ""
    flag = "" if f["listed_in_widget"] else " (served, not in the widget's list)"
    _fnrows.append([m(f["name"]) + flag, f["form"], "%s, %d series" % (v["status"], v["series"]), _esc(c[:220] + ("..." if len(c) > 220 else ""))])
W["promqlref"] = wrap(
 h1("PromQL for the strategy: ten queries, what each decides, verified"),
 sub("Every query ran against the reference estate's Real-Time Metrics on " + _DATE + "; the series column is what that engine answered. Paste one into a PromQL Viewer's Query box and Validate; &lt;vm&gt; and &lt;host_fqdn&gt; stand for a MOID and a host name of the importing instance."),
 h2("Ten queries, the decision each serves"),
 table(["Id", "Lane", "Query", "Decision it serves", "Series on the reference estate"], _rows, ["4%", "9%", "34%", "43%", "10%"]),
 h2("Two planes, one set of samples: the store's mean and peak keys reproduced from the 20-second series"),
 table(["Real-Time Metrics name (20 s)", "Operations keys (5-minute mean, in-cycle peak)", "Mean ratio, plane over store", "Peak ratio", "Sample"], _cprows, ["22%", "34%", "16%", "12%", "16%"]),
 p("Reading: the analytics store's 5-minute mean and its 20_sec_peak keys are the average and the maximum of the same fifteen 20-second samples this plane serves: exact for the guest family, within a few percent for network usage whose two collection paths sample at different phases. A warehouse that extracts the store's mean and peak keys and the hourly MAX rollup keeps what a 20-second feed would give it, without the volume. And the store normalizes two guest keys (run queue per vCPU, disk queue divided by 100) where this plane serves raw values, so a join across planes scales per key first."),
 h2("The functions the widget lists, and how to call them"),
 p("Snapshot functions take a bare metric or a selector; count-then-snapshot functions take the number first; clip functions need the bracketed window inside the function, and this widget always runs a range query, so a bare range vector or a subquery is a parse error here."),
 table(["Function", "Form", "Verified", "Caution"], _fnrows, ["16%", "13%", "13%", "58%"]),
 h2("The dialect on this build"),
 table(["Works", "Does not work"], [
  ["lowercase labels with " + m("=") + ", " + m("!=") + ", " + m("=~") + ", " + m("!~") + "; several matchers in one brace", "VMware guidance's " + m("HOST='host-17'") + " (0 series, status success)"],
  ["a range vector inside a function", "a bare range vector or a subquery as the outermost expression of a range query"],
  [m("+ - * / % ^") + " between a series and a number, or two series whose labels match; comparisons with " + m("bool") + "; " + m("and") + ", " + m("or") + ", " + m("unless"), m("on") + ", " + m("ignoring") + ", " + m("group_left") + "; unary minus; the " + m("@") + " modifier"],
  [m("sum") + ", " + m("min") + ", " + m("max") + ", " + m("avg") + ", " + m("count") + " with " + m("by") + " or " + m("without") + "; " + m("topk") + ", " + m("bottomk") + ", " + m("topn_sum") + ", " + m("bottomn_sum"), m("stddev") + ", " + m("stdvar") + ", " + m("quantile") + ", " + m("count_values") + ", " + m("group")],
  ["the six " + m("_over_time") + " functions, " + m("rate") + ", " + m("irate") + ", " + m("increase") + ", " + m("resets") + ", " + m("abs") + ", " + m("ceil") + ", " + m("floor") + ", " + m("absent") + ", " + m("absent_over_time"), m("round") + ", " + m("sqrt") + ", " + m("log") + ", " + m("delta") + ", " + m("deriv") + ", " + m("predict_linear") + ", " + m("sort_desc") + ", " + m("clamp_max") + ", " + m("label_replace") + ", " + m("histogram_quantile") + ", " + m("quantile_over_time") + ", " + m("stddev_over_time") + ", " + m("changes") + ", " + m("time()") + ", " + m("vector()") + ", " + m("scalar()")],
  [m("offset") + " parses", "it returned the unshifted series point for point; VMware guidance lists it unsupported in 9.1"]], ["50%", "50%"]),
 source("the promql folder (functions.json, examples.json, reconciliation.json, generated by verify_promql.py on " + _DATE + "); Broadcom TechDocs, VCF 9.1, PromQL Widget and PromQL Queries."))
# ---------------------------------------------------------------- 9. not from ops
W["notops"] = wrap(
 h1("What should not come from Operations, and when"),
 sub("A pipeline drawn as greenfield asks for everything. These are the parts that belong elsewhere, with the circumstances."),
 table(["Item on a list", "Why not from here", "Where it belongs"], [
  ["A second pull of these counters from vCenter (a monitoring platform's vCenter integration, a warehouse SOAP client)", "it re-collects what this store already holds, adds load on vpxd, needs a raised statistics level for the counters above level 1, and creates a second truth with no peaks recovered", "extract from Operations; keep the collector for what is off vSphere"],
  ["Per-process CPU and memory, service state, inode counts, application counters, logs", "the hypervisor cannot see inside the guest beyond what VMware Tools reports (memory, swap, paging, queues, filesystem totals)", "one agent per guest: open-source Telegraf posting to Operations when the counters must live here, otherwise the estate's collector to its own store"],
  ["Process discovery as an unbounded metric dimension", "every process becomes a series; the store and the warehouse both pay for it", "an approved allowlist of processes and services, in the agent"],
  ["20-second and 2-second series as a BI feed", "tens of millions of samples a day per small source, a 15-day horizon, a 101-series ceiling per call, a per-source cut for the 2-second set", "a regional hot-set only: the contention series for a scoped set, extracted within hours"],
  ["Physical network devices", "not this store's lane; VCF Operations for Networks reads the flows the VMware estate itself exports", "a network-monitoring platform (DX NetOps leads; the Network Devices pack as the operations lens), or the domain collector's SNMP, gNMI, and flow inputs"],
  ["Anything the response omits", "a resource missing from a stats response had no data in the window, and a blank Tools field was not reported", "reconcile against inventory and collector health first; never land a gap as zero"]]),
 callout("When the whole family should not route through Operations",
  "Residency rules that keep raw series in a region (the regional instance already does), estates that are mostly not vSphere, and teams that own their own store: choose by where the data must live. The doors into Operations are the Management Pack Builder for any API or Prometheus source, open-source Telegraf for guests, the packs whose direction is stable, and the suite API push for numbers a pipeline already holds.", amber=True),
 source(SRC_LIVE + "; the Collect Once, Decide at Source charter, sections 3 and 3a."))
# ---------------------------------------------------------------- 10. extraction
W["extract"] = wrap(
 h1("Extract it: three tiers, one key, and the rules that ride every tier"),
 sub("The contract that feeds the ELT: what to call, how often, what lands, and what it costs, measured on the reference estate."),
 table(["Tier", "Call", "Cadence", "Lands as", "Measured cost"], [
  [chip(GOLD, "<b>Gold layer</b>"), m("POST /api/resources/stats/latest/query") + " with " + m("maxSamples=1") + " for the decision statkeys (the OnlineCapacityAnalytics recommendations and time remaining, the reclaim and rightsize lists), plus " + m("/api/resources") + " and " + m(".../properties") + " for the inventory and the configuration fields", "daily", "one row per object per day", "113 bytes per stat, 3.1 KB per VM inventory record"],
  [chip(HOURLY, "<b>Analysis tier</b>"), m("POST /api/resources/stats/query") + " with " + m("intervalType=HOURS") + " and " + m("rollUpType=AVG") + ", then a second call with " + m("MAX") + " (one rollup per call); exact against the native points, end-stamped on a fixed grid", "hourly buckets, pulled daily", "one row per object, statkey, hour, rollup", "about 30 bytes per point; 144 MB per day at 10,000 VMs and 20 statkeys; about 100 seconds of calls"],
  [chip(HOT, "<b>Hot-set</b>"), "native 5-minute contention keys for a scoped set (the same call without a rollup), or Real-Time Metrics " + m("GET /data-query-service/api/v1/query_range") + " at 20 s or 2 s with " + m("sourceId") + " per vCenter and the feature pinned (the calls are spelled out below)", "within hours of collection", "one row per object, statkey, sample, kept in the region", "1.7 GB per day per region if every 5-minute point were shipped; keep it scoped"]], ["11%", "42%", "12%", "15%", "20%"]),
 h2("The statkeys of the catalog, by tier"),
 kv([("Gold, daily", m("config|hardware|num_Cpu") + ", " + m("mem|guest_provisioned") + ", " + m("sys|poweredOn") + ", " + m("sys|uptime_latest") + ", " + m("diskspace|provisionedSpace") + ", " + m("diskspace|used") + ", " + m("diskspace|notshared") + ", " + m("diskspace|snapshot|used") + ", " + m("summary|snapshot_count") + ", the guest filesystem totals, the decision keys " + m("summary|oversized*") + ", " + m("summary|undersized*") + ", " + m("summary|idle") + ", " + m("OnlineCapacityAnalytics|*|recommendedSize") + "; properties for state, Tools, and guest OS"),
     ("Hourly AVG and MAX", m("cpu|demandmhz") + ", " + m("cpu|usagemhz_average") + ", " + m("cpu|demandPct") + ", " + m("cpu|readyPct") + ", " + m("cpu|costopPct") + ", " + m("cpu|swapwaitPct") + ", " + m("cpu|iowaitPct") + ", " + m("cpu|capacity_contentionPct") + ", " + m("mem|active_average") + ", " + m("mem|consumed_average") + ", " + m("mem|usage_average") + ", " + m("mem|balloonPct") + ", " + m("mem|compressed_average") + ", " + m("mem|swapped_average") + ", " + m("mem|swapinRate_average") + ", " + m("mem|swapoutRate_average") + ", " + m("mem|host_contentionPct") + ", the guest family " + m("guest|*") + ", " + m("virtualDisk|read_average") + ", " + m("virtualDisk|write_average") + ", " + m("disk|usage_average") + ", and under the Aggregate of all instances instance " + m("virtualDisk:Aggregate of all instances|numberReadAveraged_average") + ", " + m("...|numberWriteAveraged_average") + ", " + m("...|totalReadLatency_average") + ", " + m("...|totalWriteLatency_average") + ", " + m("...|vDiskOIO") + "; " + m("net|usage_average") + ", " + m("net|received_average") + ", " + m("net|transmitted_average") + ", " + m("net:Aggregate of all instances|packetsRxPerSec") + ", " + m("...|packetsTxPerSec") + ", " + m("...|droppedPct") + ", " + m("net|droppedTx_summation")),
     ("Hot-set, scoped", "the contention keys and their peaks: " + m("cpu|readyPct") + ", " + m("cpu|20_sec_peak_readyPct") + ", " + m("cpu|costopPct") + ", " + m("cpu|20_sec_peak_costopPct") + ", " + m("mem|host_contentionPct") + ", " + m("mem|20_sec_peak_host_contentionPct") + ", " + m("virtualDisk|20_sec_peak_totalLatency_average") + ", the guest queue peaks; or the 20-second series from Real-Time Metrics for the same objects")]),
 h2("Hot-set through the API: PromQL against the query service, directly"),
 p("The PromQL Viewers above are the demonstration. A pipeline runs the same language against the query service itself, one HTTP call per query, and lands the answer in the region. The recipe, verified on the reference estate:"),
 ol(["<b>Mint the token.</b> Any suite API session (the VCF SSO API client identity) calls " + m("GET /suite-api/api/integrations/services") + ", takes the " + m("key") + " of the entry whose type is " + m("VCF_VODAP") + ", and posts it to " + m("POST /suite-api/api/auth/token/exchange") + " as " + m("{&quot;serviceKeys&quot;:[key]}") + "; the answer's " + m("jwtToken") + " is the credential. It lasts 35 minutes from the bearer's own mint, not from the exchange, so re-mint both on one schedule.",
     "<b>Address the service.</b> " + m("https://&lt;instance services FQDN&gt;/data-query-service/api/v1/") + " with " + m("Authorization: Bearer &lt;jwt&gt;") + ": the VCF instance's services address, not the Operations node.",
     "<b>Discover the sources and their names.</b> " + m("GET /api/v1/vcenters/metrics_config") + " lists the vCenter ids: each is the vCenter instance UUID, the value the store carries as " + m("VMEntityVCID") + ". " + m("GET /api/v1/metadata?sourceId=&lt;id&gt;") + " lists the names that source serves; without a source it lists the engine's whole catalog. NSX sources are the managers' cluster UUIDs, which Operations carries as the " + m("MANAGEMENT_CLUSTER_UUID") + " identifier of transport nodes.",
     "<b>Size before you pull.</b> " + m("count by (profile) (&lt;name&gt;)") + " per name: the profile is the cadence, and a name-profile pair above 101 series has to be partitioned by " + m("host") + ". Pin " + m("feature") + " or " + m("profile") + " on every query; a truncated answer is a 200 with " + m("warnings") + " set, so the run fails on the warning, never on the status.",
     "<b>Pull.</b> " + m("GET /api/v1/query_range?query=&lt;promql&gt;&amp;sourceId=&lt;id&gt;&amp;start=&lt;epoch s&gt;&amp;end=&lt;epoch s&gt;&amp;step=20s") + ", " + m("step=2s") + " for the ESX Top set with " + m("feature='ESX_TOP'") + "; a few hours per call, never the whole horizon in one. " + m("GET /api/v1/query?query=&amp;time=") + " reads one instant.",
     "<b>Land.</b> Each element of " + m("data.result") + " carries " + m("metric") + " (the labels) and " + m("values") + " as " + m("[[epoch, &quot;value&quot;], ...]") + ". The row key is (" + m("sourceId") + ", the " + m("vm") + " or " + m("host") + " label), which is the store's (" + m("VMEntityVCID") + ", " + m("VMEntityObjectID") + ") pair, so the hot-set joins the tiers with no lookup. Stamp the feature, the profile, and the query; upsert on (source, name, labels, timestamp).",
     "<b>Bound it.</b> 20-second series stay 15 days, the 2-second set a shorter window cut per source; extract within hours, keep it in the region, and never turn this into the BI feed: the panel above shows the store's mean and peak keys are rollups of these same samples."]),
 kv([("The hot-set, as calls", "hour by hour, " + m("topn_sum(20, cpu.capacity.contention.VM{feature='TROUBLESHOOTING'})") + " at " + m("step=20s") + " names the twenty most contended VMs of the hour with their raw values (20 series, 180 points each); then, for a VM the tier flagged, " + m("cpu.capacity.contention.VM{vm='&lt;vm MOID&gt;', feature='TROUBLESHOOTING'}") + " over the same window; and per host the 2-second latency tail, " + m("max_over_time(storage.latency.totalKavg.LUN{feature='ESX_TOP', host_fqdn='&lt;host fqdn&gt;'}[1m])") + " at " + m("step=60s") + "."),
     ("One call, spelled out", m("curl -sk -G -H &quot;Authorization: Bearer $JWT&quot; &quot;https://&lt;instance services FQDN&gt;/data-query-service/api/v1/query_range&quot; --data-urlencode &quot;query=topn_sum(20, cpu.capacity.contention.VM{feature='TROUBLESHOOTING'})&quot; --data-urlencode &quot;sourceId=&lt;vCenter instance UUID&gt;&quot; --data-urlencode &quot;start=$(($(date +%s)-3600))&quot; --data-urlencode &quot;end=$(date +%s)&quot; --data-urlencode &quot;step=20s&quot;")),
     ("What not to do", "no " + m("rate()") + " on a gauge (the engine reads a dip as a counter reset), no " + m("offset") + " (accepted, not applied), no subquery in a range call, no unpinned name that serves two cadences, no join across planes without the per-key scale check (the guest run queue is per vCPU in the store, the guest disk queue divided by 100)."),
     ("Runnable form", "promql/verify_promql.py in this folder runs every query on this panel against a live instance and records what the engine answered; the ten strategy queries and their decisions sit beside it in examples.json.")]),
 h2("The key"),
 p("Every row lands on (vCenter instance UUID, MOID): " + m("VMEntityVCID") + " and " + m("VMEntityObjectID") + " from the resource identifiers, the pair Operations itself marks unique. A MOID alone collides at the second vCenter; a name collides at the first rename. The pair is the <b>observation</b> key: it names where a sample was taken, so a cross-vCenter move changes both halves at once, Operations mints a second resource, and the MOID the machine left behind is renamed " + m("&lt;moid&gt;_vmotion_discarded_1") + " with state " + m("NOT_EXISTING") + ". The VM instance UUID is carried on both and is not part of uniqueness, so resolve the pair to it through a continuity ledger before anything joins on identity. Real-time rows are stamped with the " + m("sourceId") + " they were queried under and the profile. The CMDB keys the same VM on the same pair, so its instance CI presents as new after a move unless the adapter is set to identify VMs by UUID."),
 h2("Rules that ride every tier"),
 ol(["<b>Watermark</b> on bucket-end timestamps with a two-cycle settling margin; re-pull the overlap, it costs 30 bytes a point.",
     "<b>Upsert</b> on (resource, statkey, timestamp); the overlap never duplicates.",
     "<b>Batch wide:</b> hundreds of resources times the statkey subset times a day per call; about half a second per call plus 4 microseconds per point, 48,000 points per call measured.",
     "<b>Never poll latest faster than the 5-minute cycle;</b> nothing new arrives in between.",
     "<b>Reconcile absence:</b> a resource missing from a response had no data in the window, not zero; deleted objects linger 168 hours and object history 90 days by default, so diff the inventory daily against the CMDB's lifecycle.",
     "<b>Tokens:</b> a VCF SSO API client identity (not a person) for the suite API; for Real-Time Metrics a service JWT exchanged from that bearer, which expires with the bearer's session, so re-mint both on one schedule and never let a cleanup path depend on an exchange.",
     "<b>Instanced families:</b> the VM-level value of virtual disk latency, IOPS, and outstanding IO, and of network packets and drops, lives under the <b>Aggregate of all instances</b> instance; the plain catalog key returns nothing, and the per-instance keys (per disk, per vNIC, per datastore, per mount) sit beside it. Read the resource's statkey list once and extract the names it actually carries.",
     "<b>Per region:</b> run the extract against the regional instance and ship the tiers, never the points; the WAN carries decisions and hourly aggregates."]),
 source(SRC_LIVE + " (the extraction contract, rollup exactness, and coefficients were measured live); VMware guidance pages for retention defaults."))
# ---------------------------------------------------------------- 11. reference (collapsed)
ref = [
 ["Configuration and State", "config|hardware|num_Cpu", "Number of CPUs", "vCPUs", "5-minute latest; also a property"],
 ["", "mem|guest_provisioned", "Memory Total Capacity", "KB (shown in GB)", "5-minute latest"],
 ["", "sys|poweredOn", "Powered ON", "0 or 1", "5-minute"],
 ["", "sys|uptime_latest, sys|osUptime_latest", "Uptime, OS Uptime", "seconds", "5-minute latest"],
 ["", "diskspace|provisionedSpace", "Provisioned Space", "GB", "5-minute; per datastore as diskspace:<datastore>|provisioned"],
 ["CPU", "cpu|demandmhz, cpu|usagemhz_average, cpu|demandPct", "Demand, Usage, Demand (%)", "MHz, MHz, %", "5-minute mean of 20-second samples; p95 column over 7 days"],
 ["", "cpu|readyPct, cpu|costopPct, cpu|swapwaitPct, cpu|capacity_contentionPct", "Ready, Co-stop, Swap wait, Contention", "%", "5-minute mean"],
 ["", "cpu|20_sec_peak_readyPct, cpu|20_sec_peak_costopPct", "Peak vCPU Ready, Peak vCPU Co-Stop within collection cycle", "%", "the highest 20-second sample of the cycle"],
 ["Memory", "mem|active_average, mem|consumed_average, mem|compressed_average, mem|swapped_average, mem|guest_usage", "Guest Active, Consumed, Compressed, Swapped, Guest Usage", "KB (shown in GB)", "5-minute mean; Guest Usage needs Tools"],
 ["", "mem|host_contentionPct, mem|balloonPct, mem|swapinRate_average", "Contention, Balloon (%), Swap In Rate", "%, %, KBps", "5-minute mean"],
 ["", "mem|20_sec_peak_host_contentionPct", "Peak Contention within collection cycle", "%", "the highest 20-second sample of the cycle"],
 ["Virtual disk", "virtualDisk:Aggregate of all instances|numberReadAveraged_average, virtualDisk:Aggregate of all instances|numberWriteAveraged_average, virtualDisk|peak_vDisk_iops", "Read IOPS, Write IOPS, Highest IOPS of all instances", "IOPS", "5-minute mean under the aggregate instance; the highest-of-all-instances key is the busiest disk's 5-minute average"],
 ["", "virtualDisk|read_average, virtualDisk|write_average", "Read Throughput, Write Throughput", "KBps", "5-minute mean"],
 ["", "virtualDisk:Aggregate of all instances|totalReadLatency_average, virtualDisk:Aggregate of all instances|totalWriteLatency_average, virtualDisk|20_sec_peak_totalLatency_average", "Read Latency, Write Latency, Peak Latency within collection cycle", "ms", "5-minute mean under the aggregate instance; the peak keeps the 20-second maximum"],
 ["", "virtualDisk:Aggregate of all instances|vDiskOIO", "Outstanding IO requests", "OIOs", "5-minute under the aggregate instance; the read and write split keys are not collected on the reference estate"],
 ["Network", "net|usage_average, net|received_average, net|transmitted_average, net|20_sec_peak_usage_average", "Usage Rate, Data Receive Rate, Data Transmit Rate, Peak Usage Rate within collection cycle", "KBps", "5-minute mean; one peak key"],
 ["", "net:Aggregate of all instances|packetsRxPerSec, net:Aggregate of all instances|packetsTxPerSec, net|20_sec_peak_packetsPerSec", "Packets Received per second, Packets Transmitted per second, Peak Network Packet per second", "packets/s", "5-minute under the aggregate instance; the peak is a plain key"],
 ["", "net:Aggregate of all instances|droppedPct, net|droppedTx_summation", "Packets Dropped (%), Transmitted Dropped", "%, count per cycle", "the percentage under the aggregate instance; the receive count key is not collected on the reference estate"],
 ["Storage and guest filesystem", "diskspace|used, diskspace|notshared, diskspace|snapshot|used", "Virtual Machine used, Not Shared, Snapshot Virtual Machine used", "GB", "5-minute"],
 ["", "guestfilesystem|capacity_total, guestfilesystem|usage_total, guestfilesystem|percentage_total", "Total Capacity, Utilization, Utilization (%)", "GB, GB, %", "5-minute when VMware Tools reports; blank otherwise; free is capacity minus utilization"],
]
for r in ref:
    for key in r[1].split(", "):
        assert key in STATKEYS, "reference table names a key the reference VM lacks: " + key
W["reference"] = wrap(
 h1("Reference: every column, its statkey, unit, and cadence"),
 sub("The six lists above, column by column, as the reference estate reports them (display names and units read live)."),
 table(["List", "Statkey", "Display name", "Unit", "Cadence"], [[c if i != 1 else m(c) for i, c in enumerate(r)] for r in ref], ["15%", "30%", "25%", "10%", "20%"]),
 p("Retention defaults on VCF Operations 9.1, all at their defaults on the reference estate: 5-minute values for 6 months, then hourly for 36 months; deleted objects 168 hours; object history 90 days. The vCenter statistics level shapes vCenter's own charts, not this store."),
 source(SRC_LIVE + "; " + SRC_DOC + "."))
NAMES = {"start": "widget-start.html", "mapping": "widget-mapping.html", "config": "widget-config.html", "cpu": "widget-cpu.html", "memory": "widget-memory.html", "disknet": "widget-disknet.html", "storage": "widget-storage.html", "charts": "widget-charts.html", "promql": "widget-promql.html", "promqlref": "widget-promql-reference.html", "notops": "widget-not-from-ops.html", "extract": "widget-extract.html", "reference": "widget-reference.html"}
if __name__ == "__main__":
    os.makedirs(CONTENT, exist_ok=True)
    for k, fn in NAMES.items():
        html = W[k]; assert "\u2014" not in html and "\u2013" not in html, k
        with open(os.path.join(CONTENT, fn), "w", encoding="utf-8") as f: f.write(html)
        print("wrote", fn, len(html), "bytes")
