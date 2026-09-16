#!/usr/bin/env python3
"""Emit the six Collect Once VM views (content/*.view.xml) and their one-click Views > Manage > Import bundle.

Each view lists VIRTUAL MACHINES (self + descendant subjects, so a vSphere World provider lists every VM)
with the raw vCenter-adapter statkeys the client's utilization list maps to, one family per view, so the
dashboard can show the family live beside its teaching note. Column shapes mirror the live-validated
memory-tiering exemplar exactly (attributes-selector items with CURRENT, or PERCENTILE 95 over the 7-day
selector for the analysis-window columns); units use the confirmed internal ids (gb, percent) or Auto.
Descriptions are the views' own documentation and stay under the 1024-character import limit.

Run:  python build_views.py [--check]
"""
from __future__ import annotations
import os, sys, zipfile, xml.etree.ElementTree as ET
from xml.sax.saxutils import escape
HERE = os.path.dirname(os.path.abspath(__file__)); CONTENT = os.path.join(HERE, "content"); IMPORT = os.path.join(HERE, "import")
ZIP_TS = (1980, 1, 1, 0, 0, 0)
def vid(n): return f"c01c000{n}-000{n}-4a00-b000-00000000000{n}"
# (key, display name, preferredUnitId, transformation, sort)
V = [
 (vid(1), "PCA - Collect Once - VM - Configuration and State", "collect-once-vm-configuration.view.xml",
  "VIRTUAL MACHINES: the configured capacity and state fields of the utilization list that Operations keeps as metrics (the rest are properties, read through the properties API). vCPU count and total memory capacity are the configured size; Powered ON and the two uptimes are state. Every column is the vCenter adapter's 5-minute value; these change rarely, so the gold layer reads them once a day with the inventory. Sorted by memory capacity.",
  [("mem|guest_provisioned","Memory Capacity (GB)","gb","CURRENT",True),("config|hardware|num_Cpu","vCPUs","","CURRENT",False),("sys|poweredOn","Powered ON (1 = on)","","CURRENT",False),("sys|uptime_latest","Uptime (s)","","CURRENT",False),("sys|osUptime_latest","OS Uptime (s)","","CURRENT",False),("diskspace|provisionedSpace","Provisioned Space (GB)","gb","CURRENT",False)]),
 (vid(2), "PCA - Collect Once - VM - CPU Demand and Contention", "collect-once-vm-cpu.view.xml",
  "VIRTUAL MACHINES: CPU demand (the signal to size from) beside the three hypervisor contention counters that no guest agent can see: Ready, Co-stop, Swap wait. Each 5-minute value is the mean of fifteen 20-second samples; the Peak columns are the highest 20-second sample inside the same cycle, which the mean hides. The p95 columns are the 95th percentile of the 5-minute values over the selected 7 days: the analysis-window reading. Sorted by demand.",
  [("cpu|demandmhz","Demand (MHz)","","CURRENT",True),("cpu|demandmhz","Demand p95 7d (MHz)","","PERCENTILE",False),("cpu|usagemhz_average","Usage (MHz)","","CURRENT",False),("cpu|demandPct","Demand (%)","percent","CURRENT",False),("cpu|readyPct","Ready (%)","percent","CURRENT",False),("cpu|readyPct","Ready p95 7d (%)","percent","PERCENTILE",False),("cpu|20_sec_peak_readyPct","Peak Ready in cycle (%)","percent","CURRENT",False),("cpu|costopPct","Co-stop (%)","percent","CURRENT",False),("cpu|20_sec_peak_costopPct","Peak Co-stop in cycle (%)","percent","CURRENT",False),("cpu|swapwaitPct","Swap wait (%)","percent","CURRENT",False),("cpu|capacity_contentionPct","Contention (%)","percent","CURRENT",False)]),
 (vid(3), "PCA - Collect Once - VM - Memory Demand and Contention", "collect-once-vm-memory.view.xml",
  "VIRTUAL MACHINES: the memory fields of the utilization list kept as separate semantics. Guest Active is the hypervisor's estimate of recently touched memory (the demand signal); Consumed is the host memory the VM holds (the footprint); Balloon, Compressed, and Swapped are the reclamation ladder in order; Contention is the time the VM waited for memory, with its in-cycle peak; Guest Usage needs VMware Tools. All are 5-minute means of 20-second samples except the Peak column. Sorted by active memory.",
  [("mem|active_average","Guest Active (GB)","gb","CURRENT",True),("mem|active_average","Active p95 7d (GB)","gb","PERCENTILE",False),("mem|consumed_average","Consumed (GB)","gb","CURRENT",False),("mem|balloonPct","Balloon (%)","percent","CURRENT",False),("mem|compressed_average","Compressed (GB)","gb","CURRENT",False),("mem|swapped_average","Swapped (GB)","gb","CURRENT",False),("mem|host_contentionPct","Contention (%)","percent","CURRENT",False),("mem|20_sec_peak_host_contentionPct","Peak Contention in cycle (%)","percent","CURRENT",False),("mem|swapinRate_average","Swap In Rate (KBps)","","CURRENT",False),("mem|guest_usage","Guest Usage, Tools (GB)","gb","CURRENT",False)]),
 (vid(4), "PCA - Collect Once - VM - Virtual Disk Workload", "collect-once-vm-virtual-disk.view.xml",
  "VIRTUAL MACHINES: the virtual-disk workload aggregated across the VM's disks. Latency, IOPS, and outstanding IO are instanced statkeys whose VM-level value lives under the Aggregate of all instances instance (virtualDisk:Aggregate of all instances|...); per-disk instances read the same way (virtualDisk:<disk>|...). Throughput and the peak keys are plain VM keys. 5-minute means except the Peak columns, which keep the highest 20-second sample of the cycle. Sorted by read latency.",
  [("virtualDisk:Aggregate of all instances|totalReadLatency_average","Read Latency (ms)","","CURRENT",True),("virtualDisk:Aggregate of all instances|totalWriteLatency_average","Write Latency (ms)","","CURRENT",False),("virtualDisk|20_sec_peak_totalLatency_average","Peak Latency in cycle (ms)","","CURRENT",False),("virtualDisk:Aggregate of all instances|numberReadAveraged_average","Read IOPS","","CURRENT",False),("virtualDisk:Aggregate of all instances|numberWriteAveraged_average","Write IOPS","","CURRENT",False),("virtualDisk|peak_vDisk_iops","Highest IOPS of all disks","","CURRENT",False),("virtualDisk|read_average","Read Throughput (KBps)","","CURRENT",False),("virtualDisk|write_average","Write Throughput (KBps)","","CURRENT",False),("virtualDisk:Aggregate of all instances|vDiskOIO","Outstanding IO","","CURRENT",False)]),
 (vid(5), "PCA - Collect Once - VM - Network Workload", "collect-once-vm-network.view.xml",
  "VIRTUAL MACHINES: receive and transmit rates in KBps with the combined usage rate and its in-cycle peak (plain VM keys), packets per second each way and the dropped percentage (instanced keys whose VM-level value lives under net:Aggregate of all instances|...), the in-cycle peak packet rate, and the transmitted-drop count per cycle. Per-vNIC instances read the same way. 5-minute means except the Peak columns. Sorted by usage rate.",
  [("net|usage_average","Usage Rate (KBps)","","CURRENT",True),("net|20_sec_peak_usage_average","Peak Usage in cycle (KBps)","","CURRENT",False),("net|received_average","Receive Rate (KBps)","","CURRENT",False),("net|transmitted_average","Transmit Rate (KBps)","","CURRENT",False),("net:Aggregate of all instances|packetsRxPerSec","Packets Received /s","","CURRENT",False),("net:Aggregate of all instances|packetsTxPerSec","Packets Transmitted /s","","CURRENT",False),("net|20_sec_peak_packetsPerSec","Peak Packets /s in cycle","","CURRENT",False),("net:Aggregate of all instances|droppedPct","Packets Dropped (%)","percent","CURRENT",False),("net|droppedTx_summation","Transmitted Dropped (count per cycle)","","CURRENT",False)]),
 (vid(6), "PCA - Collect Once - VM - Storage and Guest Filesystem", "collect-once-vm-storage.view.xml",
  "VIRTUAL MACHINES: the storage footprint as vCenter reports it (Provisioned, Virtual Machine used, Not Shared, Snapshot) beside the guest filesystem totals VMware Tools reports (capacity, utilization, percentage; free space is capacity minus utilization). The filesystem columns are conditional: a blank means Tools did not report, never zero. Per-filesystem instances exist as instanced statkeys (guestfilesystem:<mount>|...). The OS-accurate available memory, swap, inodes, processes, and services are not here; they are the guest agent's job. Sorted by used space.",
  [("diskspace|used","VM Used (GB)","gb","CURRENT",True),("diskspace|provisionedSpace","Provisioned (GB)","gb","CURRENT",False),("diskspace|notshared","Not Shared (GB)","gb","CURRENT",False),("diskspace|snapshot|used","Snapshot Used (GB)","gb","CURRENT",False),("guestfilesystem|capacity_total","Guest FS Capacity (GB)","gb","CURRENT",False),("guestfilesystem|usage_total","Guest FS Used (GB)","gb","CURRENT",False),("guestfilesystem|percentage_total","Guest FS Used (%)","percent","CURRENT",False)]),
]
def item(key, name, unit, tr, sort):
    pct = '<Property name="percentile" value="95"/>' if tr == "PERCENTILE" else ""
    return ('<Item><Value><Property name="objectType" value="RESOURCE"/><Property name="attributeKey" value="%s"/>'
            '<Property name="preferredUnitId" value="%s"/><Property name="isStringAttribute" value="false"/>'
            '<Property name="adapterKind" value="VMWARE"/><Property name="resourceKind" value="VirtualMachine"/>'
            '<Property name="rollUpType" value="NONE"/><Property name="rollUpCount" value="0"/>%s'
            '<Property name="transformations"><List><Item value="%s"/></List></Property>'
            '<Property name="sortCriteria" value="%s"/><Property name="isProperty" value="false"/>'
            '<Property name="displayName" value="%s"/><Property name="addTimestampAsColumn" value="false"/>'
            '<Property name="isShowRelativeTimestamp" value="false"/></Value></Item>') % (escape(key, {'"': '&quot;'}), unit, pct, tr, "true" if sort else "false", escape(name, {'"': '&quot;'}))
def viewdef(id_, title, desc, cols):
    return ('<ViewDef id="%s"><Title>%s</Title><Description>%s</Description>'
            '<SubjectType adapterKind="VMWARE" resourceKind="VirtualMachine" type="descendant"/>'
            '<SubjectType adapterKind="VMWARE" resourceKind="VirtualMachine" type="self"/>'
            '<Usage>dashboard</Usage><Usage>report</Usage><Usage>details</Usage><Usage>content</Usage><Controls>'
            '<Control id="tis_1" type="time-interval-selector" visible="false"><Property name="advancedTimeMode" value="false"/><Property name="unit" value="DAYS"/><Property name="count" value="7"/></Control>'
            '<Control id="as_2" type="attributes-selector" visible="false"><Property name="attributeInfos"><List>%s</List></Property></Control>'
            '<Control id="pg_3" type="pagination-control" visible="true"><Property name="start" value="0"/><Property name="size" value="50"/></Control>'
            '<Control id="md_4" type="metadata" visible="false"><Property name="maxPointsCount" value="5000"/><Property name="hideObjectNameColumn" value="false"/><Property name="listTopResultSize" value="-1"/></Control>'
            '</Controls><DataProviders><DataProvider dataType="list-view" id="lv_0"/></DataProviders><Presentation type="list"/></ViewDef>') % (id_, escape(title), escape(desc), "".join(item(*c) for c in cols))
PREFIX = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Content><Views>'; SUFFIX = "</Views></Content>"
def main():
    check = "--check" in sys.argv[1:]; bodies = []
    for id_, title, fname, desc, cols in V:
        assert len(desc) <= 1024, f"{title}: description {len(desc)} chars over the 1024 limit"
        assert sum(1 for c in cols if c[4]) == 1, f"{title}: exactly one sort column"
        body = viewdef(id_, title, desc, cols); doc = PREFIX + body + SUFFIX
        root = ET.fromstring(doc); assert root.find("Views/ViewDef").get("id") == id_
        bodies.append(body)
        if not check:
            with open(os.path.join(CONTENT, fname), "w", encoding="utf-8") as f: f.write(doc + "\n")
    content_xml = PREFIX + "".join(bodies) + SUFFIX; ET.fromstring(content_xml)
    if check: print(f"[check] {len(V)} views valid"); return
    path = os.path.join(IMPORT, "views", "collect-once-views.import.zip")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z: z.writestr(zipfile.ZipInfo("content.xml", ZIP_TS), content_xml)
    print(f"emitted {len(V)} views into content/ and {os.path.relpath(path, HERE)}")
if __name__ == "__main__": main()
