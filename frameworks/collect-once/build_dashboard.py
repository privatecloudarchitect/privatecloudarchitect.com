#!/usr/bin/env python3
"""Build the PCA - Collection Strategy Guide dashboard (deterministic) + its Manage > Import zip.

One dashboard whose layout is the story, top-down: start here, the metric list mapped, then one row per
family of the client's list (a teaching note beside the live VM list: configuration, CPU, memory; virtual
disk beside network; storage and guest filesystem), the per-VM charts that draw a 5-minute mean beside its
20-second peak key (driven by a row selected in the CPU or memory list), the Real-Time Metrics plane shown
live through three PromQL Viewer widgets charting verified strategy queries, with the language the plane speaks on this build, what should not come from
Operations and when, the extraction contract that feeds the ELT, and a collapsed column reference.

Text widgets sync verbatim from content/widget-*.html (authored by build_copy.py, never edited inside
the JSON); View widgets bind the six ViewDefs build_views.py emits by their stable ids on the portable
vSphere World provider (the importer remaps it through entries.resource name+identifiers, the companion's field notes). The
PromQL Viewer widget (type VODAP) mirrors the shape the UI saved on 2026-09-16; its source is one VCF
domain object whose id is instance-specific (VODAP_SOURCE below, or --source-id), so on another instance
pick the source in the widget's Edit dialog after import. Widget and config shapes mirror the live-validated
exemplars (memory-tiering, wtpc). Import the views bundle first, then this zip, through the UI (dashboards
have no REST surface).

Run:  python build_dashboard.py [--check] [--source-id <VCFDomain resource id>]
"""
from __future__ import annotations
import json, os, sys, zipfile
HERE = os.path.dirname(os.path.abspath(__file__)); CONTENT = os.path.join(HERE, "content"); IMPORT = os.path.join(HERE, "import")
sys.path.insert(0, os.path.dirname(HERE))
try:
    from _shared._copy import assert_current_voice  # noqa: E402  (the estate-wide copy-voice gate, private corpus)
except ImportError:  # the public companion ships without the estate gate; the copy was gated before it was published
    def assert_current_voice(texts): return None
NAME = "PCA - Collection Strategy Guide"
OUT = os.path.join(CONTENT, "collection-strategy-guide.dashboard.json")
ZIP = os.path.join(IMPORT, "dashboards", "collection-strategy-guide.import.zip")
# ids: the 2026-09-16 universal build carries new dashboard, tab, and widget ids so it can sit beside the earlier, estate-specific import
DASH_ID = "c01cd000-0000-4a00-b000-000000000002"; TAB_ID = "c01ct000-0000-4a00-b000-0000000000ab"
def wid(n): return f"c01ce000-0000-4a00-b000-{n + 100:012d}"
def vid(n): return f"c01c000{n}-000{n}-4a00-b000-00000000000{n}"
VSPHERE_WORLD = {"resourceId": "resource:id:0_::_", "traversalSpecId": "", "resourceName": "vSphere World",
                 "resourceKindId": "002006VMWAREvSphere World", "id": "Ext.vcops.chrome.model.Resource-24"}
# The PromQL Viewer's source: a VCFDomain resource (VcfAdapter) of the importing instance. Read live 2026-09-16 with
# GET /suite-api/api/resources?resourceKind=VCFDomain&adapterKind=VcfAdapter; the id below is this lab's workload domain.
VODAP_SOURCE = {"name": "the VCF domain you choose at import", "resourceKind": "VCFDomain", "adapterKind": "VcfAdapter", "id": "00000000-0000-4000-8000-000000000000"}
# the three queries charted live (E2, E5, E6 of the promql folder beside the generators: examples.json, verified on this instance)
Q_HOT = "topn_sum(5, cpu.capacity.contention.VM{feature='TROUBLESHOOTING'})"
Q_RATIO = "sum by (host_fqdn) (cpu.corecount.provisioned.VM) / count by (host_fqdn) (cpu.utilization.PCORE{feature='TROUBLESHOOTING'})"
Q_TAIL = "max_over_time(storage.latency.totalKavg.LUN{feature='ESX_TOP'}[1m])"
LAST_HOUR = "s%3A%7B%22dateRange%22%3A%22lastHour%22%2C%22dateFrom%22%3Anull%2C%22dateTo%22%3Anull%2C%22timeFrom%22%3Anull%2C%22timeTo%22%3Anull%7D"
def read_html(fname):
    with open(os.path.join(CONTENT, fname), encoding="utf-8") as f: return f.read()
def _wrap(n, wtype, title, coords, config, collapsed=False, states=None):
    x, y, w, h = coords
    return {"tabId": TAB_ID, "collapsed": collapsed, "id": wid(n), "gridsterCoords": {"x": x, "y": y, "w": w, "h": h},
            "state": "", "type": wtype, "title": title, "config": config, "height": 0, "states": states or []}
def text(n, title, coords, html_file, collapsed=False):
    return _wrap(n, "TextDisplay", title, coords, {"locationFile": "", "locationUrl": "", "editorData": read_html(html_file)}, collapsed)
def view(n, title, coords, view_id):
    cfg = {"refreshInterval": 300, "resource": dict(VSPHERE_WORLD), "traversalSpecId": None, "refreshContent": {"refreshContent": False},
           "isUpdatedView": True, "chartViewItems": [], "selectFirstRow": {"selectFirstRow": False}, "selfProvider": {"selfProvider": True},
           "title": title, "viewDefinitionId": view_id}
    return _wrap(n, "View", title, coords, cfg)
def metric_chart(n, title, coords, metrics):
    rkm = [{"yellowBound": None, "metricUnitId": "percent", "unit": "%", "metricName": mname, "metricKey": mkey, "isStringMetric": False,
            "resourceKindName": "Virtual Machine", "id": f"rsm-{i}", "redBound": None, "resourceKindId": "resourceKind:id:5_::_",
            "orangeBound": None, "colorMethod": 2} for i, (mname, mkey) in enumerate(metrics, 1)]
    cfg = {"depth": 1, "metric": {"mode": "resourceKind", "resourceMetrics": [], "resourceKindMetrics": rkm, "subMode": "resourceKindAll"},
           "refreshInterval": 300, "resource": [], "refreshContent": {"refreshContent": True}, "relationshipMode": {"relationshipMode": 0},
           "customFilter": {"filter": [], "excludedResources": None, "includedResources": None}, "selfProvider": {"selfProvider": False},
           "title": title, "resInteractionMode": None}
    return _wrap(n, "MetricChart", title, coords, cfg)
def promql(n, title, coords, query, source_id):
    # the exact config the UI saved for a PromQL Viewer in self-provider mode (export read 2026-09-16); widgetId repeats the widget id
    cfg = {"vodapEnabled": True, "refreshInterval": 300, "widgetId": wid(n), "sourceParentId": source_id, "query": query,
           "refreshContent": {"refreshContent": True}, "description": "", "sourceResourceKind": "VMwareAdapter Instance",
           "viewDetails": "", "selfProvider": {"selfProvider": True}, "title": title}
    states = [{"value": LAST_HOUR, "key": f"permDateFilter_widget_{DASH_ID}_{wid(n)}"}]
    return _wrap(n, "VODAP", title, coords, cfg, states=states)
def build(source_id=VODAP_SOURCE["id"]):
    # rows top-down; y is computed so no row can overlap the one above (dashboards.md: next_y = y + h)
    # text heights = ceil(rendered px / 55) + 1, the px measured in headless Chrome at 1380 px (12 columns) and 560 px (5 columns);
    # 55 px per grid row is the calibration read off the estate's live-tuned exemplars and the operator's padding report of 2026-09-16
    rows = [
        [("text", 1, "Start here: collect once, decide at source", 12, 11, "widget-start.html", False)],
        [("text", 2, "The VM utilization catalog, mapped to Operations", 12, 51, "widget-mapping.html", False)],
        [("text", 3, "Configuration and state", 5, 9, "widget-config.html", False), ("view", 4, "VM configuration and state (live)", 7, 9, vid(1), None)],
        [("text", 5, "CPU: demand, ready, co-stop", 5, 12, "widget-cpu.html", False), ("view", 6, "VM CPU demand and contention (live)", 7, 12, vid(2), None)],
        [("text", 7, "Memory: active, consumed, the reclamation ladder", 5, 12, "widget-memory.html", False), ("view", 8, "VM memory demand and contention (live)", 7, 12, vid(3), None)],
        [("text", 9, "Virtual disk and network", 12, 8, "widget-disknet.html", False)],
        [("view", 10, "VM virtual disk workload (live)", 6, 9, vid(4), None), ("view", 11, "VM network workload (live)", 6, 9, vid(5), None)],
        [("text", 12, "Storage and guest filesystem", 5, 8, "widget-storage.html", False), ("view", 13, "VM storage and guest filesystem (live)", 7, 8, vid(6), None)],
        [("text", 14, "The mean and its hidden peak", 12, 3, "widget-charts.html", False)],
        [("chart", 15, "CPU Ready: 5-minute mean vs in-cycle peak (selected VM)", 6, 9, [("CPU|Ready (%)", "cpu|readyPct"), ("CPU|Peak vCPU Ready within collection cycle (%)", "cpu|20_sec_peak_readyPct")], None),
         ("chart", 16, "Memory Contention: 5-minute mean vs in-cycle peak (selected VM)", 6, 9, [("Memory|Contention (%)", "mem|host_contentionPct"), ("Memory|Peak Contention within collection cycle (%)", "mem|20_sec_peak_host_contentionPct")], None)],
        [("text", 17, "Real-Time Metrics: read a name, pin the feature", 5, 18, "widget-promql.html", False),
         ("promql", 18, "Contention hot list at 20 seconds, bounded: topn_sum(5, cpu.capacity.contention.VM)", 7, 18, Q_HOT, None)],
        [("promql", 19, "vCPU to physical core ratio per host, computed live from two families", 6, 12, Q_RATIO, None),
         ("promql", 20, "The 2-second tail: worst kernel latency per LUN inside each minute, per host", 6, 12, Q_TAIL, None)],
        [("text", 21, "PromQL for the strategy: ten queries, the functions, the dialect (verified on this instance)", 12, 37, "widget-promql-reference.html", False)],
        [("text", 22, "What should not come from Operations, and when", 12, 10, "widget-not-from-ops.html", False)],
        [("text", 23, "Extract it: three tiers, one key, the rules, and the PromQL calls", 12, 27, "widget-extract.html", False)],
        [("text", 24, "Reference: every column, statkey, unit, cadence", 12, 20, "widget-reference.html", True)],
    ]
    widgets = []; y = 1
    for row in rows:
        x = 1; tallest = 0
        for kind, n, title, w, h, arg, collapsed in row:
            coords = (x, y, w, h)
            if kind == "text": widgets.append(text(n, title, coords, arg, collapsed=bool(collapsed)))
            elif kind == "view": widgets.append(view(n, title, coords, arg))
            elif kind == "promql": widgets.append(promql(n, title, coords, arg, source_id))
            else: widgets.append(metric_chart(n, title, coords, arg))
            x += w; tallest = max(tallest, h)
        assert x - 1 == 12, f"row at y={y} does not fill 12 columns"
        y += tallest
    interactions = [{"widgetIdProvider": wid(p), "type": "resourceId", "widgetIdReceiver": wid(r)} for p in (6, 8) for r in (15, 16)]
    entries = {"resourceKind": [{"resourceKindKey": "VirtualMachine", "internalId": "resourceKind:id:5_::_", "adapterKindKey": "VMWARE"}],
               "resource": [{"resourceKindKey": "vSphere World", "internalId": "resource:id:0_::_", "adapterKindKey": "VMWARE", "identifiers": [], "name": "vSphere World"}]}
    dashboard = {"shared": False, "hidden": False, "autoswitchEnabled": False, "importAttempts": 0, "columnProportion": "1-1", "importComplete": False,
                 "description": ("Collect once, decide at source: a BI team's VM utilization metric list shown live on this instance, family by family, "
                                 "with the cadence each value is kept at, the peak keys the 5-minute mean hides, the Real-Time Metrics plane through three "
                                 "PromQL Viewers charting verified strategy queries, what should not come from Operations, and the three-tier "
                                 "extraction contract that feeds an ELT warehouse."),
                 "widgets": widgets, "states": [], "editAllowed": True, "homeTab": False, "rank": 0, "disabled": False, "id": DASH_ID,
                 "adapterName": "VMware vSphere", "locked": False, "dashboardNavigations": {}, "columnCount": 12,
                 "name": NAME, "gridsterMaxColumns": 12,
                 "widgetInteractions": interactions, "namePath": "Custom Dashboards", "userId": "", "lastUpdateUserId": ""}
    return {"entries": entries, "dashboards": [dashboard], "uuid": DASH_ID}
def validate(doc):
    dash = doc["dashboards"][0]; ws = dash["widgets"]; assert len(ws) == 24 and dash["name"] == NAME and sum(1 for w in ws if w["type"] == "VODAP") == 3
    assert {w["type"] for w in ws} == {"TextDisplay", "View", "MetricChart", "VODAP"}
    rects = []
    for w in ws:
        g = w["gridsterCoords"]; assert 1 <= g["x"] and g["x"] + g["w"] - 1 <= 12 and g["y"] >= 1 and g["h"] >= 1
        rects.append((w["title"], g["x"], g["y"], g["w"], g["h"]))
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            t1, x1, y1, w1, h1 = rects[i]; t2, x2, y2, w2, h2 = rects[j]
            assert not (x1 < x2 + w2 and x2 < x1 + w1 and y1 < y2 + h2 and y2 < y1 + h1), f"gridster overlap: {t1!r} / {t2!r}"
    rows = {}
    for w in ws:
        g = w["gridsterCoords"]; rows.setdefault(g["y"], set()).add((g["x"], g["w"]))
    for y, segs in rows.items():
        if len(segs) > 1: assert frozenset(segs) in {frozenset({(1, 6), (7, 6)}), frozenset({(1, 5), (6, 7)})}, f"unproven split at y={y}: {sorted(segs)}"
    known = {vid(n) for n in range(1, 7)}; ids = {w["id"] for w in ws}; tvm = {w["id"]: w["type"] for w in ws}
    for w in ws:
        if w["type"] == "View": assert w["config"]["viewDefinitionId"] in known and w["config"]["resource"]["resourceId"] == VSPHERE_WORLD["resourceId"]
        if w["type"] == "VODAP":
            c = w["config"]; assert c["widgetId"] == w["id"] and c["sourceParentId"] and c["query"] and c["selfProvider"] == {"selfProvider": True}
            assert w["states"] and w["states"][0]["key"].endswith(w["id"])
    for it in dash["widgetInteractions"]:
        assert it["widgetIdProvider"] in ids and it["widgetIdReceiver"] in ids and tvm[it["widgetIdProvider"]] == "View" and tvm[it["widgetIdReceiver"]] == "MetricChart"
    texts = {w["title"]: w["config"]["editorData"] for w in ws if w["type"] == "TextDisplay"}
    assert len(texts) == 13 and all(v.strip().startswith("<div") for v in texts.values())
    assert_current_voice(texts)
    internal = [e["internalId"] for e in doc["entries"]["resourceKind"]] + [e["internalId"] for e in doc["entries"]["resource"]]
    assert len(internal) == len(set(internal))
    for e in doc["entries"]["resource"]: assert "name" in e and e.get("identifiers") == []
    return {t: sum(1 for w in ws if w["type"] == t) for t in {w["type"] for w in ws}}
def main():
    args = sys.argv[1:]; source_id = VODAP_SOURCE["id"]
    if "--source-id" in args: source_id = args[args.index("--source-id") + 1]
    doc = build(source_id); types = validate(doc)
    if "--check" in args: print("[check] dashboard valid", types); return
    os.makedirs(os.path.dirname(ZIP), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f: json.dump(doc, f, indent=1, ensure_ascii=True); f.write("\n")
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED) as z: z.writestr(zipfile.ZipInfo("dashboard/dashboard.json", (1980, 1, 1, 0, 0, 0)), open(OUT, "rb").read())
    print("emitted", os.path.relpath(OUT, HERE), "and", os.path.relpath(ZIP, HERE), types)
if __name__ == "__main__": main()
