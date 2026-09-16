#!/usr/bin/env python3
"""Verify the PromQL reference against a live VCF Operations 9.1 Real-Time Metrics service and emit
functions.json, examples.json, and reconciliation.json beside metrics.json.

Stdlib only. Auth follows the harness recipe (the Real-Time Metrics OpenAPI description documents it):
an api-token bearer from the Identity Broker, then the suite-api service-key exchange for the VCF_VODAP
JWT. Credentials are read in-process from the catalog payload or from the environment and never printed.

  python verify_promql.py                      # full run (about two minutes on a Medium instance)
  python verify_promql.py --no-crossplane      # skip the Operations stats comparison
  OPS_HOST=... RTM_HOST=... OPS_API_TOKEN=... OPS_BROKER_HOST=... python verify_promql.py

Every emitted "verified" block carries the date, the source, the HTTP status, and the series count the
engine answered with, so a future build can be re-verified by re-running this file.
"""
from __future__ import annotations
import argparse, collections, json, os, ssl, statistics, sys, time, urllib.error, urllib.parse, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
TODAY = time.strftime("%Y-%m-%d", time.gmtime()); NOW = int(time.time())
GRANT = "urn:custom:vcf:params:oauth:grant-type:api-token"
CTX = ssl._create_unverified_context()  # self-signed lab CA (CLAUDE.md: allowed)

# ----------------------------------------------------------------------------------------------- auth + http
def load_env():
    if "OPS_API_TOKEN" not in os.environ:
        tf = os.path.join(ROOT, "secrets", "credentials", "vidb", "vcf-ops.api-token.json")
        if os.path.exists(tf):
            t = json.load(open(tf)); os.environ.setdefault("OPS_API_TOKEN", t["api_token"])
            os.environ.setdefault("OPS_BROKER_HOST", t["broker_fqdn"]); os.environ.setdefault("OPS_REALM", t.get("realm", "CUSTOMER"))
    # OPS_HOST and RTM_HOST come from the environment in the public cut
    for k in ("OPS_API_TOKEN", "OPS_HOST", "RTM_HOST"):
        if not os.environ.get(k): raise SystemExit("missing " + k)
def http(host, path, method="GET", body=None, headers=None, form=None):
    hd = {"Accept": "application/json"}; hd.update(headers or {}); data = None
    if form is not None: hd["Content-Type"] = "application/x-www-form-urlencoded"; data = urllib.parse.urlencode(form).encode()
    elif body is not None: hd["Content-Type"] = "application/json"; data = json.dumps(body).encode()
    req = urllib.request.Request("https://%s%s" % (host, path), headers=hd, data=data, method=method)
    try:
        with urllib.request.urlopen(req, context=CTX, timeout=120) as r: raw = r.read(); st = r.status
    except urllib.error.HTTPError as e: raw = e.read(); st = e.code
    try: return st, json.loads(raw)
    except Exception: return st, {"raw": raw.decode(errors="replace")[:300]}
def bearer():
    st, j = http(os.environ.get("OPS_BROKER_HOST", os.environ["OPS_HOST"]), "/acs/t/%s/token" % os.environ.get("OPS_REALM", "CUSTOMER"), "POST",
                 form={"grant_type": GRANT, "api_token": os.environ["OPS_API_TOKEN"]})
    if st != 200 or "access_token" not in j: raise SystemExit("broker exchange failed: HTTP %s" % st)
    return j["access_token"]
def ops(tok, method, path, body=None):
    return http(os.environ["OPS_HOST"], "/suite-api" + path, method, body, {"Authorization": "Bearer " + tok})
def service_jwt(tok):
    st, j = ops(tok, "GET", "/api/integrations/services"); keys = [s["key"] for s in j.get("servicesDetails", []) if s.get("type") == "VCF_VODAP"]
    if not keys: raise SystemExit("no VCF_VODAP service registered: is Real-Time Metrics deployed?")
    st, j = ops(tok, "POST", "/api/auth/token/exchange", {"serviceKeys": [keys[0]]})
    if st != 200 or "jwtToken" not in j: raise SystemExit("service exchange failed: HTTP %s" % st)
    return j["jwtToken"]
class RTM:
    def __init__(self, jwt): self.jwt = jwt; self.calls = 0
    def get(self, path, params):
        self.calls += 1
        return http(os.environ["RTM_HOST"], "/data-query-service" + path + "?" + urllib.parse.urlencode(params), headers={"Authorization": "Bearer " + self.jwt})
    def names(self, source=None):
        st, j = self.get("/api/v1/metadata", {"sourceId": source} if source else {}); d = j.get("data") or {}
        return sorted(d.keys()) if isinstance(d, dict) else sorted(x if isinstance(x, str) else x.get("name", "") for x in d)
    def range(self, q, source, span=1800, step="20s", end=None):
        end = end or NOW; st, j = self.get("/api/v1/query_range", {"query": q, "sourceId": source, "start": end - span, "end": end, "step": step})
        return st, ((j.get("data") or {}).get("result") or []), (j.get("error") or ""), (j.get("warnings") or [])
    def instant(self, q, source):
        st, j = self.get("/api/v1/query", {"query": q, "sourceId": source, "time": NOW})
        return st, ((j.get("data") or {}).get("result") or []), (j.get("error") or "")
def verified(st, res, err, warn, source, **extra):
    v = {"date": TODAY, "source": source, "http": st, "series": len(res), "status": "served" if st == 200 and res else ("empty" if st == 200 else "refused"),
         "error": err[:160] if err else "", "warnings": warn if warn else []}
    v.update(extra); return v

# ----------------------------------------------------------------------------------------------- the functions
UI_FUNCTIONS = [  # (name, description as the widget's Functions tab shows it, form, signature, standard PromQL)
 ("sum", "Sum of values across all time series", "snapshot", "sum(<instant vector>) [by|without (labels)]", True),
 ("min", "Minimum value across all time series", "snapshot", "min(<instant vector>) [by|without (labels)]", True),
 ("max", "Maximum value across all time series", "snapshot", "max(<instant vector>) [by|without (labels)]", True),
 ("avg", "Average value across all time series", "snapshot", "avg(<instant vector>) [by|without (labels)]", True),
 ("count", "Number of time series in result set", "snapshot", "count(<instant vector>) [by|without (labels)]", True),
 ("topk", "Top k time series by value", "count-then-snapshot", "topk(k, <instant vector>) [by (labels)]", True),
 ("bottomk", "Bottom k time series by value", "count-then-snapshot", "bottomk(k, <instant vector>) [by (labels)]", True),
 ("topn_sum", "Top n time series by sum", "count-then-snapshot", "topn_sum(n, <instant vector>)", False),
 ("bottomn_sum", "Bottom n time series by sum", "count-then-snapshot", "bottomn_sum(n, <instant vector>)", False),
 ("avg_over_time", "Average value over time range", "clip", "avg_over_time(<range vector>)", True),
 ("min_over_time", "Minimum value over time range", "clip", "min_over_time(<range vector>)", True),
 ("max_over_time", "Maximum value over time range", "clip", "max_over_time(<range vector>)", True),
 ("sum_over_time", "Sum of values over time range", "clip", "sum_over_time(<range vector>)", True),
 ("count_over_time", "Number of points over time range", "clip", "count_over_time(<range vector>)", True),
 ("last_over_time", "Most recent value over time range", "clip", "last_over_time(<range vector>)", True),
 ("abs", "Absolute value of time series", "snapshot", "abs(<instant vector>)", True),
 ("ceil", "Round values up to nearest integer", "snapshot", "ceil(<instant vector>)", True),
 ("floor", "Round values down to nearest integer", "snapshot", "floor(<instant vector>)", True),
 ("rate", "Per-second rate of increase over time range", "clip", "rate(<range vector>)", True),
 ("resets", "Number of counter resets over time range", "clip", "resets(<range vector>)", True),
 ("absent", "Returns 1 if vector is empty, empty result otherwise", "snapshot", "absent(<instant vector>)", True),
 ("absent_over_time", "Returns 1 if range vector is empty, empty result otherwise", "clip", "absent_over_time(<range vector>)", True),
]
EXTRA_FUNCTIONS = [  # served on the build but absent from the widget's list; irate is in VMware guidance, increase is not
 ("irate", "Per-second rate from the last two data points of the range (VMware guidance wording: uses the last two data points)", "clip", "irate(<range vector>)", True, True),
 ("increase", "Increase of a counter over the range (standard PromQL; not in VMware guidance, not in the widget list)", "clip", "increase(<range vector>)", True, False),
]
FORMS = {"topk": "topk(3, X)", "bottomk": "bottomk(3, X)", "topn_sum": "topn_sum(3, X)", "bottomn_sum": "bottomn_sum(3, X)", "rate": "rate(X[5m])", "irate": "irate(X[5m])",
         "increase": "increase(X[5m])", "resets": "resets(X[5m])", "absent": "absent(no.such.metric.HOST)", "absent_over_time": "absent_over_time(no.such.metric.HOST[5m])"}
CAUTIONS = {
 "rate": ["Counter semantics apply on this build: on a gauge (cpu.usagemhz.HOST, 84 decreases in 181 samples) rate() returned no negative value and matched a reset-adding computation (mean absolute error 4 against 282 for a plain first-to-last delta). The example in VMware guidance rate(cpu.capacity.usage.HOST{host='host-17'}[5m]) applies it to a gauge and overstates change.",
          "Use avg_over_time or max_over_time for a level; rate and increase only on cumulative names (vmop.*.CLSTR and DCENTER, envoy_*_total)."],
 "irate": ["Same counter semantics as rate; on a gauge it returned no negative value and did not match a last-two-points delta."],
 "increase": ["Correct on the cumulative vmop.* names (vmop.vmotion.CLSTR stepped 2227 to 2230 over 24 h on the management source); returns 0 on a quiet cluster."],
 "resets": ["Equals the number of decreases inside the window (167 of 181 buckets exact on a gauge); on a gauge it counts dips, not counter resets."],
 "topk": ["Evaluated per step: over a range the answer is the union of every step's top k (6 series for k=3 over 30 minutes on 6 hosts) and the legend changes as leaders change. by (label) is accepted."],
 "bottomk": ["Per step, as topk; the union of every step's bottom k."],
 "topn_sum": ["VCF-specific. Selects the n series with the highest sum over the whole query range and returns their raw values (checked against a manual sum over 6 hosts): exactly n series, stable legend. by (label) is accepted and ignored; VMware guidance says by and without are unsupported."],
 "bottomn_sum": ["VCF-specific. Mirror of topn_sum: the n series with the lowest sum over the range, raw values returned."],
 "absent": ["Returns one series valued 1 when the selector matches nothing (an unknown name or an unmatched label), and nothing when it matches. The reconcile-absence guard for a scoped extract."],
 "absent_over_time": ["As absent, over the range."],
 "avg_over_time": ["The range must sit inside a function: a bare range vector is a parse error in a range query, and the PromQL Viewer widget always runs a range query."],
 "count_over_time": ["Counts raw samples: 3 per minute on the 20-second profiles, 30 on the ESX Top profile. The cadence instrument."],
 "sum": ["by and without both work. Vector matching modifiers (on, ignoring, group_left) are parse errors."],
}

# ----------------------------------------------------------------------------------------------- the examples
EXAMPLES = [
 {"id": "E1", "lane": "discovery", "title": "Cardinality and cadence before any extract",
  "query": "count by (profile) (cpu.capacity.contention.VM)",
  "decision": "Which profile serves a name, at what cadence, and whether a call will hit the 101-series ceiling. Run it once per name before an extract or a widget.",
  "reads": "one series per profile whose value is the number of series; a name under two profiles returns two rows, and the extract pins feature or profile."},
 {"id": "E2", "lane": "hot-set", "title": "Contention hot list at 20 seconds, bounded",
  "query": "topn_sum(5, cpu.capacity.contention.VM{feature='TROUBLESHOOTING'})",
  "decision": "The scoped hot-set the charter allows out of Real-Time Metrics: the five most contended VMs over the window, raw 20-second values, five series whatever the estate size.",
  "reads": "a stable legend of five VMs (MOID in the vm label, readable host in host_fqdn); the value is CPU contention percent every 20 seconds."},
 {"id": "E3", "lane": "cross-plane", "title": "The store's peak key, reproduced from the 20-second samples",
  "query": "max_over_time(net.throughput.usage.VM{vm='<vm>'}[5m])",
  "companion": "avg_over_time(net.throughput.usage.VM{vm='<vm>'}[5m])",
  "decision": "Proof for the extraction contract: the 5-minute analytics store already keeps the mean and the in-cycle peak of this plane (net|usage_average, net|20_sec_peak_usage_average). Ship the store's keys and hourly rollups, not the samples.",
  "reads": "per 5-minute cycle, the maximum and the average of the fifteen samples; compared live with the Operations keys below."},
 {"id": "E4", "lane": "cross-plane", "title": "Same samples, different units across planes",
  "query": "guest.cpu.runQueue.VM / cpu.corecount.provisioned.VM",
  "decision": "Operations stores the guest run queue per vCPU (guest|cpu_queue) and the guest disk queue divided by 100 (guest|disk_queue); the real-time plane stores the raw values. A warehouse that mixes planes checks the scale per key first.",
  "reads": "the run queue normalized per vCPU, the number Operations shows; without the division the two planes disagree by the vCPU count."},
 {"id": "E5", "lane": "gold", "title": "vCPU to physical core ratio per host, computed live",
  "query": "sum by (host_fqdn) (cpu.corecount.provisioned.VM) / count by (host_fqdn) (cpu.utilization.PCORE{feature='TROUBLESHOOTING'})",
  "decision": "The capacity policy input (the charter's CPU 4:1 ratio) as one daily number per host: provisioned vCPUs over physical cores, from two families joined on host_fqdn.",
  "reads": "one series per host; 1.0 means one vCPU per core; the count of PCORE series is the host's core count."},
 {"id": "E6", "lane": "troubleshooting", "title": "The 2-second tail: kernel latency per LUN, per host",
  "query": "max_over_time(storage.latency.totalKavg.LUN{feature='ESX_TOP'}[1m])",
  "filter_form": "max_over_time(storage.latency.totalKavg.LUN{feature='ESX_TOP'}[1m]) > 100",
  "decision": "What the 5-minute mean hides at the storage layer: the worst 2-second kernel latency inside each minute, per host. Read within hours, per source; the 2-second set is cut per source at the store's own moments.",
  "reads": "one series per host with an ESX Top opt-in; spikes of a few hundred milliseconds in one minute against a mean of a few milliseconds."},
 {"id": "E7", "lane": "troubleshooting", "title": "Per-core hot spots on one host at 2 seconds",
  "query": "topn_sum(5, cpu.utilization.PCORE{feature='ESX_TOP', host_fqdn='<host_fqdn>'})",
  "decision": "Placement and imbalance evidence: the five busiest physical cores of one host; the host matcher keeps the answer under the 101-series ceiling on any host size.",
  "reads": "five per-core series at 2-second cadence; a core pinned near 100 while the host mean is low is the scheduling story the mean cannot tell."},
 {"id": "E8", "lane": "gold", "title": "Counters, the right function: operations churn per cluster",
  "query": "increase(vmop.vmotion.CLSTR[1h])",
  "companion": "sum by (cluster) (increase(vmop.vmotion.CLSTR[6h]))",
  "decision": "vmop.* are cumulative counters (the vCenter data profile), so increase() gives migrations per window per cluster: the churn number for the gold layer. rate() belongs here, never on a gauge.",
  "reads": "vMotions per hour per cluster MOID; 0 on a quiet cluster."},
 {"id": "E9", "lane": "discovery", "title": "Absence is a value to reconcile",
  "query": "absent(cpu.capacity.contention.VM{vm='<vm>'})",
  "decision": "The reconcile-absence rule as a query: a scoped object that stops reporting returns 1 here and nothing in the data call. Land it as a gap to reconcile, never as zero.",
  "reads": "empty while the VM reports; one series valued 1 when it does not (an unknown MOID returns 1 immediately)."},
 {"id": "E10", "lane": "troubleshooting", "title": "Memory tiers at 2 seconds",
  "query": "mem.tier.consumed.MEMTYPE{feature='ESX_TOP'}",
  "decision": "Tiering engagement per host and tier (the mem label), the input of the memory-tiering lens; on a DRAM-only host the mem label carries one value.",
  "reads": "one series per host and tier at 2-second cadence."},
]

# ----------------------------------------------------------------------------------------------- the VMware guidance list
def guidance_list(path):
    """Parse VODAP-9.1-Metrics-List-Per-Provider.xlsx (stdlib): {metric key: [row per sheet]} with sheet, profile, intervals, label."""
    import zipfile, xml.etree.ElementTree as ET
    z = zipfile.ZipFile(path); NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}; R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    wb = ET.fromstring(z.read("xl/workbook.xml")); rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
    sst = ["".join(t.text or "" for t in si.iter("{%s}t" % NS["m"])) for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS)]
    def val(c):
        v = c.find("m:v", NS)
        if v is None:
            isel = c.find("m:is", NS); return "".join(x.text or "" for x in isel.iter("{%s}t" % NS["m"])) if isel is not None else ""
        return sst[int(v.text)] if c.get("t") == "s" else v.text
    def col(ref):
        n = 0
        for ch in ref:
            if ch.isalpha(): n = n * 26 + ord(ch) - 64
        return n - 1
    out = {}
    for sh in wb.find("m:sheets", NS):
        name = sh.get("name"); target = rels[sh.get(R)]; path_ = target.lstrip("/") if target.startswith("/") else "xl/" + target
        if name == "README": continue
        rows = []
        for r in ET.fromstring(z.read(path_)).find("m:sheetData", NS).findall("m:row", NS):
            cells = {col(c.get("r")): val(c) for c in r.findall("m:c", NS)}; rows.append([cells.get(i, "") for i in range(max(cells) + 1)] if cells else [])
        hdr = [h.strip() for h in rows[0]]
        for row in rows[1:]:
            if not row or not row[0]: continue
            rec = {hdr[i]: (row[i] if i < len(row) else "") for i in range(len(hdr)) if hdr[i]}
            out.setdefault(rec["Metric Key"].strip(), []).append({"sheet": name, "label": rec.get("Label", ""), "profile": rec.get("Profile", ""), "sampling_s": rec.get("Sampling Interval", ""),
                                                                  "collection_s": rec.get("Collection Interval", ""), "unit": rec.get("Unit", ""), "resource_kind": rec.get("Resource Kind", ""), "esxtop_2s": rec.get("ESXTop (2s)", "")})
    return out

# ----------------------------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--no-crossplane", action="store_true")
    ap.add_argument("--guidance-xlsx", default="", help="path to VMware guidance's VODAP-9.1-Metrics-List-Per-Provider.xlsx (kept out of the repository); adds the per-provider classification")
    args = ap.parse_args(); guidance = guidance_list(args.guidance_xlsx) if args.guidance_xlsx else {}
    load_env(); tok = bearer(); rtm = RTM(service_jwt(tok)); build = "VCF Operations 9.1 (%s)" % os.environ["OPS_HOST"]
    # sources
    st, j = rtm.get("/api/v1/vcenters/metrics_config", {}); vcs = [c["id"] for c in (j if isinstance(j, list) else [])]
    st, j = ops(tok, "GET", "/api/resources?resourceKind=TransportNode&pageSize=500")
    nsx = sorted({i["value"] for r in j.get("resourceList", []) for i in r["resourceKey"].get("resourceIdentifiers", []) if i["identifierType"]["name"] == "MANAGEMENT_CLUSTER_UUID"})
    catalog = rtm.names(); per_source = {s: rtm.names(s) for s in vcs + nsx}
    vc_src = max(vcs, key=lambda s: len(per_source[s])) if vcs else None
    print("sources: vCenter %s, NSX %s; catalog %d names; per source %s" % (vcs, nsx, len(catalog), {s[:8]: len(n) for s, n in per_source.items()}))
    # pick live placeholders on the busiest vCenter source
    st, res, err, warn = rtm.range("topn_sum(1, net.throughput.usage.VM{feature='TROUBLESHOOTING'})", vc_src, span=3600, step="300s")
    vm = res[0]["metric"]["vm"] if res else "vm-1"; host = res[0]["metric"].get("host_fqdn", "") if res else ""
    st, res, err, warn = rtm.range("count by (host_fqdn) (cpu.utilization.PCORE{feature='ESX_TOP'})", vc_src, span=600, step="60s")
    esx_host = res[0]["metric"]["host_fqdn"] if res else host
    subs = {"<vm>": vm, "<host_fqdn>": esx_host}
    # ---- functions
    functions = []
    for i, (name, desc, form, sig, std) in enumerate(UI_FUNCTIONS, 1):
        q = FORMS.get(name, ("%s(X[5m])" % name) if name.endswith("_over_time") else "%s(X)" % name).replace("X", "cpu.usagemhz.HOST")
        st, res, err, warn = rtm.range(q, vc_src)
        functions.append({"name": name, "key": name, "id": "fn-%d" % i, "description": desc, "form": form, "signature": sig, "standard_promql": std,
                          "listed_in_widget": True, "on_guidance_page": True, "cautions": CAUTIONS.get(name, []), "verified": verified(st, res, err, warn, vc_src, query=q, build=build)})
    for k, (name, desc, form, sig, std, on_page) in enumerate(EXTRA_FUNCTIONS, len(UI_FUNCTIONS) + 1):
        q = FORMS[name].replace("X", "cpu.usagemhz.HOST"); st, res, err, warn = rtm.range(q, vc_src)
        functions.append({"name": name, "key": name, "id": "fn-%d" % k, "description": desc, "form": form, "signature": sig, "standard_promql": std,
                          "listed_in_widget": False, "on_guidance_page": on_page, "cautions": CAUTIONS.get(name, []), "verified": verified(st, res, err, warn, vc_src, query=q, build=build)})
    # dialect facts, each one call
    dialect = []
    for label, q, kind in [("labels are lowercase: VMware guidance's HOST='host-17' matches nothing, host matches", "cpu.usagemhz.HOST{HOST='host-17'}", "empty"),
                           ("a bare range vector is a parse error in a range query", "cpu.usagemhz.HOST[5m]", "refused"),
                           ("a subquery is a parse error in a range query", "cpu.usagemhz.HOST[30m:5m]", "refused"),
                           ("unary minus is a parse error", "-cpu.usagemhz.HOST", "refused"),
                           ("vector matching modifiers are parse errors", "cpu.usagemhz.HOST / on(host) mem.consumed.HOST", "refused"),
                           ("arithmetic between two label-matched series works", "cpu.usagemhz.HOST / mem.consumed.HOST", "served"),
                           ("comparison with bool works", "cpu.usagemhz.HOST > bool 80", "served"),
                           ("or works", "cpu.usagemhz.HOST or mem.consumed.HOST", "served"),
                           ("unless works (empty when the right side matches every series, all series when it matches none)", "cpu.usagemhz.HOST unless no.such.metric.HOST", "served"),
                           ("the @ modifier fails", "cpu.usagemhz.HOST @ %d" % (NOW - 600), "refused"),
                           ("stddev, quantile, count_values fail", "quantile(0.95, cpu.usagemhz.HOST)", "refused"),
                           ("round and sqrt are unsupported functions", "round(cpu.usagemhz.HOST)", "refused")]:
        st, res, err, warn = rtm.range(q, vc_src); v = verified(st, res, err, warn, vc_src, query=q); v["expected"] = kind; v["as_expected"] = (v["status"] == kind)
        dialect.append({"fact": label, "verified": v})
    # offset: parses, but does it shift? compare against the unshifted series
    st, a, e1, w1 = rtm.range("cpu.usagemhz.HOST{host_fqdn='%s'}" % host, vc_src, span=1200); st2, b, e2, w2 = rtm.range("cpu.usagemhz.HOST{host_fqdn='%s'} offset 10m" % host, vc_src, span=1200)
    if a and b:
        va = {int(float(t)): v for t, v in a[0]["values"]}; vb = {int(float(t)): v for t, v in b[0]["values"]}
        same = sum(1 for t in vb if t in va and va[t] == vb[t]); shifted = sum(1 for t in vb if (t - 600) in va and va[t - 600] == vb[t])
        dialect.append({"fact": "offset parses but does not shift (VMware guidance: unsupported in 9.1)", "verified": {"date": TODAY, "source": vc_src, "http": st2, "points": len(vb), "same_as_unshifted": same, "shifted_matches": shifted, "status": "accepted-ignored" if same > shifted else "shifts"}})
    st, res, err = rtm.instant("cpu.usagemhz.HOST[30m:5m]", vc_src); dialect.append({"fact": "a subquery works only as the outermost expression of an instant query", "verified": {"date": TODAY, "source": vc_src, "http": st, "series": len(res), "error": err[:120], "status": "served" if res else "refused"}})
    # rate on a gauge: counter semantics?
    st, raw, err, warn = rtm.range("cpu.usagemhz.HOST{host_fqdn='%s'}" % host, vc_src, span=3600); pts = [(int(float(t)), float(v)) for t, v in raw[0]["values"]] if raw else []
    st, rr, err, warn = rtm.range("rate(cpu.usagemhz.HOST{host_fqdn='%s'}[5m])" % host, vc_src, span=3600); rv = [(int(float(t)), float(v)) for t, v in rr[0]["values"]] if rr else []
    def counter_rate(t):
        w = [p for p in pts if t - 300 < p[0] <= t]
        if len(w) < 2: return None
        inc = sum((w[i][1] - w[i - 1][1]) if w[i][1] >= w[i - 1][1] else w[i][1] for i in range(1, len(w))); return inc / (w[-1][0] - w[0][0])
    def plain_rate(t):
        w = [p for p in pts if t - 300 < p[0] <= t]; return (w[-1][1] - w[0][1]) / (w[-1][0] - w[0][0]) if len(w) >= 2 else None
    if pts and rv:
        ec = [abs(v - counter_rate(t)) for t, v in rv if counter_rate(t) is not None]; ep = [abs(v - plain_rate(t)) for t, v in rv if plain_rate(t) is not None]
        dialect.append({"fact": "rate() on a gauge applies counter semantics (decreases read as resets)", "verified": {"date": TODAY, "source": vc_src, "gauge": "cpu.usagemhz.HOST", "decreases_in_raw": sum(1 for i in range(1, len(pts)) if pts[i][1] < pts[i - 1][1]),
                        "raw_points": len(pts), "negative_rate_values": sum(1 for _, v in rv if v < 0), "mean_abs_err_vs_counter_style": round(sum(ec) / len(ec), 3), "mean_abs_err_vs_plain_delta": round(sum(ep) / len(ep), 3)}})
    # topn_sum semantics
    st, raw, err, warn = rtm.range("cpu.usagemhz.HOST", vc_src); sums = {r["metric"].get("host_fqdn"): sum(float(v) for _, v in r["values"]) for r in raw}
    st, top, err, warn = rtm.range("topn_sum(3, cpu.usagemhz.HOST)", vc_src); order = sorted(sums, key=sums.get, reverse=True)
    dialect.append({"fact": "topn_sum(n, x) returns the n series with the highest sum over the query range, raw values", "verified": {"date": TODAY, "source": vc_src, "returned": sorted(r["metric"].get("host_fqdn") for r in top), "expected_by_manual_sum": sorted(order[:3]), "match": sorted(r["metric"].get("host_fqdn") for r in top) == sorted(order[:3])}})
    # ---- examples
    examples = []
    for ex in EXAMPLES:
        e = dict(ex); q = e["query"]
        for k, v in subs.items(): q = q.replace(k, v)
        src = vc_src; step = "300s" if "increase" in q else ("2s" if "ESX_TOP" in q and "topn_sum" not in q else "60s"); span = 6 * 3600 if "[6h]" in q else 1800
        st, res, err, warn = rtm.range(q, src, span=span, step=step)
        ex_vals = [(r["metric"].get("host_fqdn") or r["metric"].get("cluster") or r["metric"].get("vm") or r["metric"].get("profile") or "", r["values"][-1][1]) for r in res[:6]]
        e["verified"] = verified(st, res, err, warn, src, query=q, substitutions={k: v for k, v in subs.items() if k in e["query"]}, sample_last_values=ex_vals, build=build)
        e["verified"]["expected"] = "empty" if e["id"] == "E9" else "served"; e["verified"]["as_expected"] = (e["verified"]["status"] == e["verified"]["expected"])
        examples.append(e)
    # ---- cross-plane comparison (E3, E4): Real-Time Metrics rolled up per Operations cycle against the stored mean and peak keys
    crossplane = []
    if not args.no_crossplane and vc_src:
        st, j = ops(tok, "GET", "/api/resources?resourceKind=VirtualMachine&adapterKind=VMWARE&pageSize=2000")
        def ids(r): return {i["identifierType"]["name"]: i["value"] for i in r["resourceKey"].get("resourceIdentifiers", [])}
        moid2ops = {ids(r).get("VMEntityObjectID"): (r["identifier"], r["resourceKey"]["name"]) for r in j.get("resourceList", []) if ids(r).get("VMEntityVCID", "").lower() == vc_src.lower()}
        SPAN = 3 * 3600
        for rname, mkey, pkey in [("net.throughput.usage.VM", "net|usage_average", "net|20_sec_peak_usage_average"), ("guest.contextSwapRate.VM", "guest|contextSwapRate_latest", "guest|20_sec_peak_contextSwapRate_latest"),
                                  ("guest.cpu.runQueue.VM", "guest|cpu_queue", "guest|20_sec_peak_cpu_queue"), ("guest.disk.requestQueueAvg.VM", "guest|disk_queue", "guest|20_sec_peak_disk_queue")]:
            st, top, err, warn = rtm.range("topn_sum(3, %s{feature='TROUBLESHOOTING'})" % rname, vc_src, span=SPAN, step="300s"); moids = [r["metric"]["vm"] for r in top if r["metric"]["vm"] in moid2ops]
            if not moids: continue
            st, stats = ops(tok, "POST", "/api/resources/stats/query", {"resourceId": [moid2ops[m][0] for m in moids], "statKey": [mkey, pkey, "config|hardware|num_Cpu"], "begin": (NOW - SPAN) * 1000, "end": NOW * 1000})
            for v in stats.get("values", []):
                moid = [m for m in moids if moid2ops[m][0] == v["resourceId"]][0]; series = {s["statKey"]["key"]: dict(zip(s["timestamps"], s["data"])) for s in v["stat-list"]["stat"]}
                if mkey not in series or pkey not in series: continue
                st, raw, err, warn = rtm.range("%s{vm='%s', feature='TROUBLESHOOTING'}" % (rname, moid), vc_src, span=SPAN + 600); pts = sorted((int(float(t)), float(x)) for r in raw for t, x in r["values"])
                rows = []
                for T in sorted(series[mkey]):
                    s = T // 1000; w = [x for t, x in pts if s - 300 < t <= s]
                    if len(w) >= 5 and series[mkey][T] and series[pkey].get(T): rows.append((series[mkey][T], series[pkey][T], sum(w) / len(w), max(w)))
                if len(rows) < 6: continue
                rm = [r[2] / r[0] for r in rows]; rp = [r[3] / r[1] for r in rows]; em = [abs(r[2] - r[0]) / abs(r[0]) for r in rows]; ep = [abs(r[3] - r[1]) / abs(r[1]) for r in rows]
                crossplane.append({"date": TODAY, "source": vc_src, "rtm_name": rname, "ops_mean_key": mkey, "ops_peak_key": pkey, "vm": moid, "vm_name": moid2ops[moid][1], "num_cpu": list(series.get("config|hardware|num_Cpu", {}).values())[-1:],
                                   "buckets": len(rows), "mean_ratio_rtm_over_ops_median": round(statistics.median(rm), 3), "mean_rel_err_median": round(statistics.median(em), 3), "peak_ratio_rtm_over_ops_median": round(statistics.median(rp), 3), "peak_rel_err_median": round(statistics.median(ep), 3)})
    # ---- reconciliation of metrics.json against the catalogs
    doc = json.load(open(os.path.join(HERE, "metrics.json"))); keys = [d["key"] for d in doc]; byk = {d["key"]: d for d in doc}
    vc_names = set().union(*[set(per_source[s]) for s in vcs]) if vcs else set(); nsx_names = set().union(*[set(per_source[s]) for s in nsx]) if nsx else set(); cat = set(catalog)
    lower = {n.lower(): n for n in cat}
    status = {}
    for k in keys:
        if k in vc_names: status[k] = "served-vcenter"
        elif k in nsx_names: status[k] = "served-nsx"
        elif k in cat: status[k] = "catalog-not-served"
        elif k.lower() in lower: status[k] = "case-mismatch"
        else: status[k] = "not-in-catalog"
    profiles = {}
    if vc_src:
        for n in sorted(vc_names):
            st, res, err, warn = rtm.range("count by (profile) (%s)" % n, vc_src, span=900, step="60s"); profiles[n] = sorted({r["metric"].get("profile", "?") for r in res})
    recon = {"generated": TODAY, "build": build, "sources": {"vcenter": vcs, "nsx": nsx}, "catalog_names": len(cat), "per_source_names": {s: len(n) for s, n in per_source.items()},
             "doc_keys": len(keys), "counts": dict(collections.Counter(status.values())),
             "status": status, "profiles_on_%s" % (vc_src or "none"): profiles,
             "case_mismatch": [{"doc_key": k, "live_key": lower[k.lower()], "guidance_rows_for_doc_key": guidance.get(k), "guidance_rows_for_live_key": guidance.get(lower[k.lower()])} for k in keys if status[k] == "case-mismatch"],
             "guidance_list": ({"file": os.path.basename(args.guidance_xlsx), "distinct_keys": len(guidance), "sheets": dict(collections.Counter(r["sheet"] for v in guidance.values() for r in v)),
                              "widget_keys_in_guidance_list": sum(1 for k in keys if k in guidance), "widget_keys_not_in_guidance_list": sorted(k for k in keys if k not in guidance),
                              "guidance_keys_not_in_widget": sorted(k for k in guidance if k not in byk), "engine_names_not_in_guidance_list": sorted(n for n in cat if n not in guidance),
                              "not_in_catalog_by_guidance_sheet_and_profile": dict(collections.Counter("%s/%s" % (guidance[k][0]["sheet"], guidance[k][0]["profile"]) for k in keys if status[k] == "not-in-catalog" and k in guidance).most_common()),
                              "not_in_catalog_and_not_in_guidance_list": sorted(k for k in keys if status[k] == "not-in-catalog" and k not in guidance),
                              "widget_name_differs_from_guidance_label": [{"key": k, "widget_name": byk[k]["name"], "guidance_label": guidance[k][0]["label"]} for k in keys if k in guidance and byk[k]["name"].strip().lower() != guidance[k][0]["label"].strip().lower()],
                              "per_key": {k: guidance[k] for k in keys if k in guidance}} if guidance else None),
             "not_in_catalog_by_family": dict(collections.Counter(k.split(".")[0] for k in keys if status[k] == "not-in-catalog").most_common()),
             "live_names_not_in_doc": sorted(n for n in cat if n not in byk),
             "semantic_findings": [
               {"doc_name": "Failed Requests To SDK Endpoint", "key": "envoy_cluster_upstream_rq", "finding": "the key is the envoy upstream request counter carrying envoy_cluster_name and envoy_response_code labels; on this build its only series is envoy_response_code=503 on cluster 'localhost 8085', so the friendly name encodes a label filter the copyable key does not carry."},
               {"doc_name": "Failed Requests To UI Endpoint", "key": "envoy_cluster_upstream_rq_retry_success", "finding": "the key counts successful retries on cluster vsphere-ui-http2-cluster, not failed requests; the friendly name and the key disagree."},
               {"doc_name": "Request Count To UI Endpoint", "key": "envoy_cluster_upstream_rq_total", "finding": "the key serves two clusters (localhost 8085 and vsphere-ui-http2-cluster); the friendly name is narrower than the key. The VMware guidance list carries this key twice, as 'Request Count To SDK Endpoint' and 'Request Count To UI Endpoint': the definitions are label-filtered variants of one key, and the widget's picker keeps one name per key.", "guidance_rows": guidance.get("envoy_cluster_upstream_rq_total")},
               {"doc_name": "High VCPU Ready Percentage", "key": "platform.vcpu_utilization_hist_max", "finding": "the key's own words say utilization, and it serves 42 to 76 on NSX edge nodes while platform.vcpu.ready_hist_max (the doc's 'High VCPU Usage Percentage') serves 0.8 to 5.1; the two friendly names read as swapped. Neither key is in the VMware guidance per-provider list, so the widget's own catalog is the only place carrying these names.", "in_guidance_list": bool(guidance.get("platform.vcpu_utilization_hist_max"))},
               {"doc_name": "CPU Privileged", "key": "vcResources.priviledgedcpuusage.VCRES", "finding": "misspelled in the widget's copyable key and, with --guidance-xlsx, checked against the VMware guidance per-provider list: the list carries the same misspelled key (VC sheet, VERBOSE profile, 300-second sampling), so the misspelling is in the metric definition itself, not a transcription error of the widget; neither spelling is served on this Essentials-only deployment.", "guidance_rows": guidance.get("vcResources.priviledgedcpuusage.VCRES")},
               {"doc_name": "mem.swapIn.HOST and three siblings", "key": "mem.swapIn.HOST", "finding": "with --guidance-xlsx: the VMware guidance list carries both mem.swapIn.HOST (VERBOSE, 300-second sampling, label equal to the key) and mem.swapin.HOST (ESSENTIAL, 20-second sampling, label 'Memory Swapped In') as distinct definitions; the mixed-case keys are Verbose-profile metrics this deployment does not collect, not typos of the served keys, and their label is the raw key.", "guidance_rows": {"mem.swapIn.HOST": guidance.get("mem.swapIn.HOST"), "mem.swapin.HOST": guidance.get("mem.swapin.HOST")}}]}
    # ---- emit
    for fn, obj in (("functions.json", functions), ("examples.json", {"generated": TODAY, "build": build, "placeholders": subs, "examples": examples, "dialect": dialect, "crossplane": crossplane}), ("reconciliation.json", recon)):
        with open(os.path.join(HERE, fn), "w", encoding="utf-8") as f: json.dump(obj, f, indent=1, ensure_ascii=True); f.write("\n")
        print("wrote", fn)
    print("calls:", rtm.calls, "| functions served:", sum(1 for f in functions if f["verified"]["status"] == "served"), "of", len(functions), "| examples served:", sum(1 for e in examples if e["verified"]["status"] == "served"), "of", len(examples), "| crossplane rows:", len(crossplane), "| recon:", recon["counts"])
if __name__ == "__main__": main()
