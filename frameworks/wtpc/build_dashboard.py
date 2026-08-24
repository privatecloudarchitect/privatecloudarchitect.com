#!/usr/bin/env python3
"""WTPC scorecard dashboard generator - posture prod-latency-critical-db (exemplar step 7).

Composes the 18-widget scorecard of exemplar spec section 5 into an importable dashboard.json:
top-to-bottom reading order (prerequisites -> model -> how-to-read -> floor -> capacity ->
performance -> drill -> cost -> cadence -> reference), View widgets bound by viewDefinitionId to
the five step-6 views + the reused Rightsizing 'Oversized Candidates' lens view, two triage Heatmaps
(fixed color bounds - same color = same distance-from-envelope every time), two per-VM MetricCharts,
and the eight authored education Text widgets whose HTML is synced VERBATIM from content/widget-*.html into
config.editorData (never hand-edited inside the JSON - text-and-design.md / dashboards.md).

Widget/config shapes are mirrored from the live-validated exemplars
(rightsizing-readiness.dashboard.json + memory-tiering-readiness.dashboard.json) so Ops imports
this the same way.

SCOPE: each list widget binds to its posture custom group as the provider, so the view lists ONLY
that group's members (VMs->VMs group, Hosts->Hosts group, Clusters->Cluster group) instead of the
whole vSphere World - the audit fix for the 'ton of dashes / empty rows' the world-wide root
produced. PORTABILITY follows the supermetrics.yaml pattern: the generator + posture group NAMES
are the portable key; the resolved group ids are an INSTANCE output record in groups.<posture>.yaml
(git-tracked, like the SM ids). vROps re-resolves each provider from resourceId (the group uuid) on
import. If groups.<posture>.yaml is absent the build falls back to the portable vSphere World root (the WTPC
SMs still blank for non-members via per-policy enablement, section 8.4). View + super-metric ids
are the stable reference keys (deterministic; re-import updates in place).

Usage:
  python build_dashboard.py --resolve-groups   (live: resolve group ids -> groups.<posture>.yaml, then build)
  python build_dashboard.py                     (offline: read groups.<posture>.yaml if present, else unscoped)
Emits + self-validates: content/wtpc-posture-scorecard.dashboard.json.
"""
import json
import os

import sys
import zipfile
HERE = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.join(HERE, "content")
_args = [a for a in sys.argv[1:] if not a.startswith("-")]
POSTURE = _args[0] if _args else "prod-latency-critical-db"
# per-posture identity prefixes (view / dashboard / widget / tab) - read from the posture YAML's
# content_ids block (the elevator seam, _postures.py). The view prefix MUST equal build_views'
# content_ids.view (the dashboard binds the views build_views emits). A new posture ships its own ids.
from lib._postures import content_ids, load_posture  # noqa: E402  (script, sibling module)
from lib._sm import load_sm_ids, sm_stat_key  # noqa: E402  (script, sibling module)
from lib._groups import list_groups  # noqa: E402  (script, sibling module)

_PDOC = load_posture(POSTURE)                      # loaded once; reused for identity, envelope, density
_cids = content_ids(_PDOC)
_VP, _DP, _EP, _TP = (_cids["view"], _cids["dashboard"], _cids["widget"], _cids["tab"])
SM_YAML = os.path.join(HERE, f"supermetrics.{POSTURE}.yaml")
GROUPS_YAML = os.path.join(HERE, f"groups.{POSTURE}.yaml")   # instance output record (per posture, like supermetrics.<P>.yaml)
OUT = os.path.join(CONTENT, "wtpc-posture-scorecard.dashboard.json" if POSTURE == "prod-latency-critical-db"
                   else f"wtpc-scorecard.{POSTURE}.dashboard.json")
# the one-click Dashboards > Manage > Import bundle (a {dashboard/dashboard.json} zip) - emitted alongside
# the .json so it never goes stale (the gap that left the scorecard bundles pre-dating the .json edits).
ZIP = os.path.join(CONTENT, "wtpc-posture-scorecard.import.zip" if POSTURE == "prod-latency-critical-db"
                   else f"wtpc-scorecard.{POSTURE}.import.zip")

# --- stable identities (deterministic; shape mirrors the rightsizing d571/e5f6 ids) ---
DASH_ID = f"{_DP}0000-0000-4a00-b000-000000000001"
TAB_ID = f"{_TP}0000-0000-4a00-b000-0000000000aa"
def wid(n):   # widget id for widget index n (1..17)
    return f"{_EP}0000-0000-4a00-b000-{n:012d}"

# --- view ids (step-6 views + the reused Rightsizing Oversized lens view, which never forks per posture) ---
VIEWS = {
    "V1": f"{_VP}0001-1111-4a00-b000-000000000001",  # VM Contention vs Envelope
    "V2": f"{_VP}0002-2222-4a00-b000-000000000002",  # Capacity Envelope - Hosts
    "V3": f"{_VP}0003-3333-4a00-b000-000000000003",  # Capacity Envelope - Clusters
    "V4": f"{_VP}0004-4444-4a00-b000-000000000004",  # Cost Scorecard
    "V5": f"{_VP}0005-5555-4a00-b000-000000000005",  # Availability Floor
    "OVERSIZED": "c0570001-1111-4a00-b000-000000000001",  # Rightsizing lens (reuse, never fork)
}

# --- resource-kind descriptors (stable composite ids are the resolution key; the
#     resourceKind:id:N ordinals are internal hints re-resolved on import) ---
def rk(kind, ordinal):
    return {"resourceKind": kind, "adapterKind": "VMWARE", "typeId": f"resourceKind:id:{ordinal}_::_",
            "id": f"004null002006VMWARE{kind}", "text": kind, "type": "resourceKind",
            "parentText": "vCenter", "parentId": "VMWARE"}
RK_CLUSTER, RK_HOST, RK_VM = rk("ClusterComputeResource", 3), rk("HostSystem", 4), rk("VirtualMachine", 5)

# vSphere World provider binding (portable well-known root) - identical to the rightsizing exemplar
VSPHERE_WORLD = {"resourceId": "resource:id:0_::_", "traversalSpecId": "", "resourceName": "vSphere World",
                 "resourceKindId": "002006VMWAREvSphere World", "id": "Ext.vcops.chrome.model.Resource-24"}


def load_sm():
    return load_sm_ids(SM_YAML)


def load_envelope():
    return _PDOC["envelope"]


def pos_bounds(entry):
    """Fixed heatmap colour bounds for an envelope-position metric (observed/breach): [0, target/breach,
    warn/breach, 1.0]. Envelope-derived, so each posture's heatmap colours to its own distance-from-breach
    (V-2 fixed bounds) - prod-db's mem 1.0/1.1/1.25 reproduces [0, 0.80, 0.88, 1.0] exactly."""
    b = float(entry["breach"])
    return [0, round(float(entry["target"]) / b, 2), round(float(entry["warn"]) / b, 2), 1.0]


def read_html(fname):
    # posture override first (widget-<posture>-<name>.html), else the shared widget-<name>.html. prod-db
    # has no posture-prefixed files, so it always resolves to the shared file (identical output).
    base = fname.split("widget-", 1)[-1]
    for cand in (f"widget-{POSTURE}-{base}", fname):
        p = os.path.join(CONTENT, cand)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                return f.read()
    raise SystemExit(f"missing education widget HTML: author widget-{POSTURE}-{base} (or {fname})")


# --- widget builders (each returns the full widget dict; shapes mirror the live dashboards) ---

def _wrap(n, wtype, title, coords, config, collapsed=False):
    x, y, w, h = coords
    return {"tabId": TAB_ID, "collapsed": collapsed, "id": wid(n), "gridsterCoords": {"x": x, "y": y, "w": w, "h": h},
            "state": "", "type": wtype, "title": title, "config": config, "height": 0, "states": []}


def text(n, title, coords, html_file, collapsed=False):
    # collapsed=True ships the widget collapsed to its title bar (vROps compacts it at render, as the
    # availability estate's Setup widget does): available in one click, never blocking the scroll.
    cfg = {"locationFile": "", "locationUrl": "", "editorData": read_html(html_file)}
    return _wrap(n, "TextDisplay", title, coords, cfg, collapsed=collapsed)


def view(n, title, coords, view_id, provider=None):
    cfg = {"refreshInterval": 300, "resource": dict(provider or VSPHERE_WORLD), "traversalSpecId": None,
           "refreshContent": {"refreshContent": False}, "isUpdatedView": True, "chartViewItems": [],
           "selectFirstRow": {"selectFirstRow": False}, "selfProvider": {"selfProvider": True},
           "title": title, "viewDefinitionId": view_id}
    return _wrap(n, "View", title, coords, cfg)


# --- group-as-provider: scope each list to its posture group so only members list (audit fix) ---
GROUP_NAMES = {
    "VMs": f"PCA - WTPC - Group - {POSTURE} (VMs)",
    "Hosts": f"PCA - WTPC - Group - {POSTURE} (Hosts)",
    "Clusters": f"PCA - WTPC - Group - {POSTURE} (Clusters)",
}
VIEW_GROUP = {"V1": "VMs", "V2": "Hosts", "V3": "Clusters", "V4": "Clusters", "V5": "Clusters", "OVERSIZED": "VMs"}


def group_provider(group_id, group_name):
    """A custom group is a Container/Environment resource (VERIFIED live: /api/resources/<gid> returns
    adapterKindKey=Container, resourceKindKey=Environment). The composite resourceKindId follows the
    0020<len(adapter)><adapter><kind> shape -> 002009ContainerEnvironment (len('Container')==9). vROps
    resolves the provider from resourceId (the group uuid) on import; the view's own descendant
    SubjectType then walks the group down to its members, so the list shows members only."""
    return {"resourceId": group_id, "traversalSpecId": "", "resourceName": group_name,
            "resourceKindId": "002009ContainerEnvironment", "id": "Ext.vcops.chrome.model.Resource-24"}


def resolve_group_ids():
    """Live-resolve the three posture group ids by NAME. The group ids are an INSTANCE output record
    (recorded to groups.<posture>.yaml, exactly like the SM ids in supermetrics.<posture>.yaml); the generator + posture
    names are the portable key. Group names are matched under the custom-group adapter."""
    from lib._client import ops_client
    with ops_client() as c:
        groups = list_groups(c, include_policy=False)
    byname = {g.get("resourceKey", {}).get("name"): g["id"] for g in groups}
    out = {}
    for label, name in GROUP_NAMES.items():
        if name not in byname:
            raise SystemExit(f"group {name!r} not found in {len(byname)} groups — run step-3 group instantiation first")
        out[label] = (byname[name], name)
    return out


def write_groups(groups):
    import yaml
    rows = [{"label": lbl, "name": name, "id": gid} for lbl, (gid, name) in groups.items()]
    with open(GROUPS_YAML, "w", encoding="utf-8") as f:
        f.write("# WTPC posture group ids - INSTANCE output record (resolved live; like supermetrics.yaml).\n")
        f.write("# Regenerate: python build_dashboard.py --resolve-groups\n")
        yaml.safe_dump({"groups": rows}, f, sort_keys=False, default_flow_style=False)


def load_groups():
    """Read the recorded group ids -> {label: (id, name)}; None if not yet resolved (unscoped build)."""
    if not os.path.exists(GROUPS_YAML):
        return None
    import yaml
    rows = yaml.safe_load(open(GROUPS_YAML, encoding="utf-8"))["groups"]
    return {r["label"]: (r["id"], r["name"]) for r in rows}


def heatmap(n, title, coords, color_key, color_name, thresholds, size_key, size_name, then_rk, leaf_ordinal):
    GREEN, LGREEN, AMBER, RED = "#4b9b45", "#8abf5b", "#ecc33e", "#de3f30"
    cfg = {"mode": "all", "title": title, "configs": [{
        "colorBy": {"metricKey": color_key, "value": color_name},
        "focusOnGroups": True,
        "color": {"minValue": 0, "maxValue": 2.0,
                  "thresholds": {"values": list(thresholds), "colors": [GREEN, LGREEN, AMBER, RED, RED]}},
        "sizeBy": {"metricKey": size_key, "value": size_name},
        "relationalGrouping": False, "groupBy": dict(RK_CLUSTER), "thenBy": dict(then_rk),
        "mode": {"mode": False}, "resourceKind": f"resourceKind:id:{leaf_ordinal}_::_",
        "filterMode": "tagPicker", "solidColoring": True, "selfProvider": {"selfProvider": False},
        "name": title}]}
    return _wrap(n, "Heatmap", title, coords, cfg)


def metric_chart(n, title, coords, metrics):
    """metrics = [(metricName, metricKey, yellowBound, redBound)]; receiver (selfProvider false)."""
    rkm = []
    for i, (mname, mkey, yb, rb) in enumerate(metrics, 1):
        rkm.append({"yellowBound": yb, "metricUnitId": "percent", "unit": "%", "metricName": mname,
                    "metricKey": mkey, "isStringMetric": False, "resourceKindName": "Virtual Machine",
                    "id": f"rsm-{i}", "redBound": rb, "resourceKindId": "resourceKind:id:5_::_",
                    "orangeBound": None, "colorMethod": 2})
    cfg = {"depth": 1,
           "metric": {"mode": "resourceKind", "resourceMetrics": [], "resourceKindMetrics": rkm,
                      "subMode": "resourceKindAll"},
           "refreshInterval": 300, "resource": [], "refreshContent": {"refreshContent": True},
           "relationshipMode": {"relationshipMode": 0},
           "customFilter": {"filter": [], "excludedResources": None, "includedResources": None},
           "selfProvider": {"selfProvider": False}, "title": title, "resInteractionMode": None}
    return _wrap(n, "MetricChart", title, coords, cfg)


def build(sm, groups=None):
    def smk(key, name):   # a Super Metric heatmap metricKey + display value
        return sm_stat_key(sm[key]), name

    def gp(view_key):     # group provider for a view (None => vSphere World, the portable default)
        return group_provider(*groups[VIEW_GROUP[view_key]]) if groups else None
    env = load_envelope()
    _density = bool(_PDOC.get("density_signal"))
    # cost doctrine inverts by posture: prod-db defends purchased headroom; a density posture polices idleness
    cost_title = "Cost: idle headroom is the waste" if _density else "Cost: purchased headroom is not waste"
    x1_key, x1_name = smk("X1", "Mem Envelope Position")
    x3_key, x3_name = smk("X3", "CPU Ready Envelope Position")
    g1_key, g1_name = smk("G1", "VM Memory Provisioned (GB)")
    cap_bounds = pos_bounds(env["capacity"]["mem_overcommit"])          # host mem-position heatmap
    ready_bounds = pos_bounds(env["performance"]["cpu_ready_pct_p95"])  # VM ready-position heatmap

    # per-VM drill-down chart lines: (yellow, red) = (warn, breach) from THIS posture's performance
    # envelope, so a test-dev VM is judged at its OWN looser edge, never at prod-db's strict bound. An
    # axis the posture omits (best-effort declares no co-stop / balloon edge) is dropped from the chart
    # rather than shown at a borrowed bound - matching the contention view, which renders it as context.
    perf = env["performance"]

    def _numf(v):
        v = float(v)
        return int(v) if v == int(v) else v

    def _line(mname, mkey, short, envkey):
        e = perf.get(envkey)
        return (mname, mkey, _numf(e["warn"]), _numf(e["breach"]), short) if e else None

    def drill_chart(n, pillar, coords, lines):
        present = [ln for ln in lines if ln]
        title = f"{pillar}: {' and '.join(ln[4] for ln in present)} (selected VM)"
        return metric_chart(n, title, coords, [(m, k, y, r) for (m, k, y, r, _s) in present])

    P = POSTURE
    # Reading order redesigned for top-to-bottom scroll (design-audit 2026-08): a concept precedes the
    # view it explains, prerequisites open the page collapsed, and the two heavy teaching blocks frame it
    # (the model primer expanded at the top, the per-metric reference collapsed at the foot). Widget
    # NUMBERS are held stable so ids + the w07/w14->w10/w11 interactions never move; only coords, order
    # and the collapsed flag change, plus the new model primer (w18). Each row stacks by full expanded
    # height (vROps compacts the collapsed ones at render); every multi-widget row is a proven 5+7 / 6+6.
    widgets = [
        # -- orientation: prerequisites (collapsed), the model primer, how-to-read (collapsed) --
        text(16, "Prerequisites (one-time setup)", (1, 1, 12, 6), "widget-setup.html", collapsed=True),
        text(18, "The tuning model: two units", (1, 7, 12, 20), "widget-model.html"),
        text(3, "How to read this scorecard", (1, 27, 12, 14), "widget-how-to-read.html", collapsed=True),
        # -- the gate --
        text(1, "Availability floor: the gate", (1, 41, 5, 6), "widget-floor.html"),
        view(2, "Availability Floor (per cluster)", (6, 41, 7, 6), VIEWS["V5"], gp("V5")),
        # -- capacity pillar --
        view(4, "Cluster capacity vs envelope", (1, 47, 12, 8), VIEWS["V3"], gp("V3")),
        view(5, "Host capacity vs envelope", (1, 55, 6, 10), VIEWS["V2"], gp("V2")),
        heatmap(6, "Capacity envelope position", (7, 55, 6, 10),
                x1_key, x1_name, cap_bounds, g1_key, g1_name, RK_HOST, 4),
        # -- performance pillar --
        view(7, "VM contention vs envelope", (1, 65, 6, 12), VIEWS["V1"], gp("V1")),
        heatmap(8, "Ready position (heatmap)", (7, 65, 6, 12),
                x3_key, x3_name, ready_bounds, "cpu|demandmhz", "CPU Demand (MHz)", RK_VM, 5),
        text(9, "VM detail", (1, 77, 12, 2), "widget-vm-detail.html"),
        drill_chart(10, "CPU", (1, 79, 6, 9),
                    [_line("CPU|Ready (%)", "cpu|readyPct", "Ready %", "cpu_ready_pct_p95"),
                     _line("CPU|Co-stop (%)", "cpu|costopPct", "Co-stop %", "cpu_costop_pct_p95")]),
        drill_chart(11, "Memory", (7, 79, 6, 9),
                    [_line("Memory|Contention (%)", "mem|host_contentionPct", "Contention %", "mem_contention_pct_p95"),
                     _line("Memory|Balloon (%)", "mem|balloonPct", "Balloon %", "mem_balloon_pct_p95")]),
        # -- cost pillar --
        view(12, "Cost: envelope and coverage", (1, 88, 12, 7), VIEWS["V4"], gp("V4")),
        text(13, cost_title, (1, 95, 5, 10), "widget-cost.html"),
        view(14, "Reclaim evidence: oversized candidates", (6, 95, 7, 10), VIEWS["OVERSIZED"], gp("OVERSIZED")),
        # -- operating rhythm (the closer) --
        text(15, "The operating rhythm", (1, 105, 12, 13), "widget-cadence.html"),
        # -- deep per-metric reference (collapsed appendix) --
        text(17, "Metric reference: every column and threshold", (1, 118, 12, 14), "widget-reference.html", collapsed=True),
    ]
    # widgetInteractions: evidence views w07 + w14 drive the per-VM charts w10 + w11
    interactions = [{"widgetIdProvider": wid(p), "type": "resourceId", "widgetIdReceiver": wid(r)}
                    for p in (7, 14) for r in (10, 11)]
    entries = {"resourceKind": [
        {"resourceKindKey": "ClusterComputeResource", "internalId": "resourceKind:id:3_::_", "adapterKindKey": "VMWARE"},
        {"resourceKindKey": "HostSystem", "internalId": "resourceKind:id:4_::_", "adapterKindKey": "VMWARE"},
        {"resourceKindKey": "VirtualMachine", "internalId": "resourceKind:id:5_::_", "adapterKindKey": "VMWARE"},
    ], "resource": [{"resourceKindKey": "vSphere World", "internalId": "resource:id:0_::_",
                     "adapterKindKey": "VMWARE", "identifiers": [], "name": "vSphere World"}]}
    dashboard = {
        "shared": False, "hidden": False, "autoswitchEnabled": False, "importAttempts": 0,
        "columnProportion": "1-1", "importComplete": False,
        "description": (f"The Well-Tuned Private Cloud posture scorecard for {P}: an availability floor "
                        "read as a pass/fail gate, then the capacity, performance and cost pillars scored "
                        "as distance from this posture's envelope, with the operating rhythm that keeps "
                        "them tuned. Gate first, then score."),
        "widgets": widgets, "states": [], "editAllowed": True, "homeTab": False, "rank": 0,
        "disabled": False, "id": DASH_ID, "adapterName": "VMware vSphere", "locked": False,
        "dashboardNavigations": {}, "columnCount": 12, "name": f"PCA - WTPC - Posture Scorecard - {P}",
        "gridsterMaxColumns": 12, "widgetInteractions": interactions, "namePath": "Custom Dashboards",
        "userId": "", "lastUpdateUserId": "",
    }
    return {"entries": entries, "dashboards": [dashboard], "uuid": DASH_ID}


# ---------------------------------------------------------------------- self-validation


def _assert_proven_splits(widgets):
    """Row-split gate: multi-widget rows must use a live-proven split - full width, 6+6, or 5+7
    in the x1/x6 orientation. A 7+5 or 4+8 row misplaces/collapses widgets on import; the
    reference dashboards prove the allowed set."""
    allowed = {frozenset({(1, 6), (7, 6)}), frozenset({(1, 5), (6, 7)})}
    rows = {}
    for w in widgets:
        g = w["gridsterCoords"]
        rows.setdefault(g["y"], set()).add((g["x"], g["w"]))
    for y, segs in rows.items():
        if len(segs) > 1:
            assert frozenset(segs) in allowed, f"unproven row split at y={y}: {sorted(segs)}"

def validate(doc, groups=None):
    dash = doc["dashboards"][0]
    ws = dash["widgets"]
    assert len(ws) == 18, f"expected 18 widgets, got {len(ws)}"
    # 1) gridster: within the 12-col grid, no rectangle overlap
    rects = []
    for w in ws:
        g = w["gridsterCoords"]
        assert 1 <= g["x"] and g["x"] + g["w"] - 1 <= 12, f"{w['title']}: x out of 1..12 grid"
        assert g["y"] >= 1 and g["h"] >= 1 and g["w"] >= 1
        rects.append((w["title"], g["x"], g["y"], g["w"], g["h"]))
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            t1, x1, y1, w1, h1 = rects[i]
            t2, x2, y2, w2, h2 = rects[j]
            if x1 < x2 + w2 and x2 < x1 + w1 and y1 < y2 + h2 and y2 < y1 + h1:
                raise AssertionError(f"gridster overlap: {t1!r} and {t2!r}")
    _assert_proven_splits(ws)
    # 2) view refs resolve to a known view id, and each View is bound to the RIGHT provider:
    #    group-scoped -> its posture group id (members only); unscoped -> vSphere World (portable)
    known = set(VIEWS.values())
    uuid_to_key = {uuid: key for key, uuid in VIEWS.items()}
    for w in ws:
        if w["type"] == "View":
            vid = w["config"]["viewDefinitionId"]
            assert vid in known, f"{w['title']}: unknown view id"
            rid = w["config"]["resource"]["resourceId"]
            if groups:
                want = groups[VIEW_GROUP[uuid_to_key[vid]]][0]
                assert rid == want, f"{w['title']}: expected group provider {want}, got {rid}"
            else:
                assert rid == VSPHERE_WORLD["resourceId"], f"{w['title']}: expected vSphere World provider"
    # 3) interactions reference real widgets; providers are the evidence views, receivers the charts
    ids = {w["id"] for w in ws}
    tvm = {w["id"]: w["type"] for w in ws}
    for it in dash["widgetInteractions"]:
        assert it["widgetIdProvider"] in ids and it["widgetIdReceiver"] in ids, "interaction refs unknown widget"
        assert tvm[it["widgetIdProvider"]] == "View" and tvm[it["widgetIdReceiver"]] == "MetricChart"
    # 4) every TextDisplay carries synced HTML; SM/statkey heatmap keys are non-empty
    n_text = 0
    text_widgets = {}
    for w in ws:
        if w["type"] == "TextDisplay":
            assert w["config"]["editorData"].strip().startswith("<div"), f"{w['title']}: editorData not HTML"
            text_widgets[w["title"]] = w["config"]["editorData"]
            n_text += 1
        if w["type"] == "Heatmap":
            c = w["config"]["configs"][0]
            assert c["colorBy"]["metricKey"] and c["sizeBy"]["metricKey"], f"{w['title']}: empty heatmap key"
    assert n_text == 8, f"expected 8 education Text widgets, got {n_text}"
    # 5) copy discipline: authored copy states the current model, never its own history (changelog tell)
    from lib._copy import assert_current_voice
    assert_current_voice(text_widgets)
    types = {}
    for w in ws:
        types[w["type"]] = types.get(w["type"], 0) + 1
    return types


def main():
    import sys
    sm = load_sm()
    if "--resolve-groups" in sys.argv:
        groups = resolve_group_ids()
        write_groups(groups)
        print(f"resolved + recorded {len(groups)} group ids -> {GROUPS_YAML.split('/')[-1]}")
    else:
        groups = load_groups()
    doc = build(sm, groups)
    types = validate(doc, groups)
    os.makedirs(CONTENT, exist_ok=True)
    # appliance JSON style: single-space indent, non-ASCII escaped (dashboards.md)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1, ensure_ascii=True)
        f.write("\n")
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED) as z:   # the one-click import bundle, never stale
        z.writestr(zipfile.ZipInfo("dashboard/dashboard.json", (1980, 1, 1, 0, 0, 0)), open(OUT, "rb").read())
    scope = "group-scoped (members only)" if groups else "unscoped (vSphere World)"
    print(f"dashboard: {doc['dashboards'][0]['name']}")
    print(f"  widgets: {types}  (total {sum(types.values())})")
    print(f"  view scope: {scope}")
    print(f"  interactions: {len(doc['dashboards'][0]['widgetInteractions'])} (w07/w14 -> w10/w11)")
    print(f"  emitted + validated (gridster non-overlap, view refs, interaction refs, scope, 8 synced Text): "
          f"{OUT.split('/')[-1]} + {ZIP.split('/')[-1]}")


if __name__ == "__main__":
    main()
