#!/usr/bin/env python3
"""WTPC view generator - the view-band copy, posture-parameterized.

Reads the posture YAML (postures/prod-latency-critical-db.yaml - the single threshold source) plus
the built super-metric record (supermetrics.yaml - minted ids) and emits the five ViewDef XMLs of
the exemplar build record (
exemplar-prod-latency-critical-db.md) into content/. Every band is GENERATOR-STAMPED from the
envelope (synthesis R1 - no threshold hand-placed in two mechanisms):

  - direct bands           = envelope target / warn / breach  (yellow / orange / red)
  - envelope-position bands = target/breach / warn/breach / 1.0  (position SMs are observed/breach)
  - floor bounds            = availability_floor values (n_plus, headroom_ceiling_pct) - binary
  - spec-fixed bands        = the few values section 4 fixes outside the envelope (count columns
                              0/0/0, swap any>0, the Consumed-% advisory edges, the provisional
                              cost-coverage gate) - each carries its citation at the constant below

ViewDef shape hydrated from live-validated exemplar views (both SubjectTypes, p95 = transformation
PERCENTILE + sibling percentile=95, multi-level sort = column order, verified unit ids
gb/percent/currency/7004/blank, XML-escaped text via ElementTree serialization).

View ids are STABLE HARDCODED uuids (deterministic output - rerunning the generator never mints a
new identity; re-import updates in place).

Usage:  python build_views.py          (from deploy/vcf-ops-content/wtpc/; no live API calls)

Emits + self-validates: ET.parse of every file and column-count/sort/resolution assertions.
"""
import os
import re
import sys
import xml.etree.ElementTree as ET

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
_args = [a for a in sys.argv[1:] if not a.startswith("-")]
POSTURE = _args[0] if _args else "prod-latency-critical-db"
POSTURE_YAML = os.path.join(HERE, "postures", f"{POSTURE}.yaml")
SM_YAML = os.path.join(HERE, f"supermetrics.{POSTURE}.yaml")
CONTENT_DIR = os.path.join(HERE, "content")

# --- stable view identities + files per posture (deterministic; re-import updates in place). Read from
#     the posture YAML's content_ids block (the elevator seam, _postures.py) - a new posture ships its
#     own ids, no edit here. The column SET and BANDS are envelope/floor-driven in build_views(), so an
#     axis a posture's envelope omits simply renders unbanded, and a density-led posture leads its
#     cluster views with the density-position signal. ---
from lib._postures import content_ids  # noqa: E402  (script, sibling module)

_cids = content_ids(POSTURE)
_S = {"prefix": _cids["view_prefix"], "id": _cids["view"]}
_SLUG = {"V1": "vm-contention", "V2": "capacity-hosts", "V3": "capacity-clusters",
         "V4": "cost-scorecard", "V5": "availability-floor"}
VIEW_IDS = {v: f"{_S['id']}000{v[1]}-{v[1]*4}-4a00-b000-00000000000{v[1]}" for v in _SLUG}
FILES = {v: f"wtpc-{_S['prefix']}-{slug}.view.xml" for v, slug in _SLUG.items()}

# --- the shared SM ids, from the instance record adopt_shared.py emits (ids mint per instance) ---
_SHARED_RECORD = os.path.join(HERE, "supermetrics.shared.yaml")
if not os.path.exists(_SHARED_RECORD):
    raise SystemExit("supermetrics.shared.yaml not found - run adopt_shared.py first")
_SH = {e["key"]: e["id"] for e in yaml.safe_load(open(_SHARED_RECORD, encoding="utf-8"))["supermetrics"]}
SH_CONSUMED_HA_DRAM = _SH["SH_CONSUMED_HA_DRAM"]
SH_CONSUMED_DRAM = _SH["SH_CONSUMED_DRAM"]
SH_FLEET_RECLAIM_COST = _SH["SH_FLEET_RECLAIM_COST"]

# --- spec-fixed band values NOT derivable from the envelope (each per exemplar section 4) ---
# V2 col 5: advisory saturation ceiling on Consumed % of DRAM - "60/80 are the documented
# HEADROOM/ACTIVE edges from the MemTier banding, read here as a saturation ceiling" (section 4 V2).
CONSUMED_DRAM_ADVISORY = (60, 80, 90)
# V3 col 6: display gradient toward the floor's pass/fail ceiling; the red edge is the floor's
# headroom_ceiling_pct (stamped below); 85/95 are the section-4 gradient steps.
CONSUMED_HA_GRADIENT_EDGES = (85, 95)
# V4 col 3: cost-coverage validity gate - provisional 80% per exemplar section 10-viii until the
# threshold is set from measured fleet attribution.
COST_COVERAGE_PROVISIONAL_PCT = 80


def fmt(v):
    """Numeric -> minimal XML value string (1.0 -> '1', 1.25 -> '1.25')."""
    return f"{float(v):g}"


def edge(v):
    """Envelope edge -> numeric bound. Maps the '>N' notation (e.g. mem_swapped_gb warn/breach
    '>0') to N: with ascendingRange=false the bound colors everything above it."""
    if isinstance(v, str) and v.startswith(">"):
        return float(v[1:])
    return float(v)


def band(env_entry):
    """Envelope {target, warn, breach} -> (yellow, orange, red)."""
    return (edge(env_entry["target"]), edge(env_entry["warn"]), edge(env_entry["breach"]))


def position_band(env_entry):
    """Envelope-position bands for the X-family (observed/breach): yellow = target/breach,
    orange = warn/breach, red = 1.0 (exemplar section 4 V2/V4 - generator-stamped)."""
    b = edge(env_entry["breach"])
    return (round(edge(env_entry["target"]) / b, 2), round(edge(env_entry["warn"]) / b, 2), 1.0)


def gate_lo(threshold):
    """Binary PASS-gate, 'value >= threshold passes, below fails'. Places the band bound at
    threshold - 0.5 so an integer boundary is unambiguous under EITHER vROps inclusive/exclusive
    convention - the fail value and the pass value fall cleanly on opposite sides. This is the fix for
    the binary-band boundary contradiction: a bound placed ON the boundary value (binary(n)) renders
    the boundary either as a false PASS (the fail state colours green) or a false BREACH (a healthy
    value colours red), depending on the convention. Use with asc=True (red below the bound)."""
    b = float(threshold) - 0.5
    return (b, b, b)


def gate_hi(threshold):
    """Binary PASS-gate, 'value <= threshold passes, above fails' (e.g. a count that must be 0).
    Bound at threshold + 0.5; use with asc=False (red above the bound). Same boundary-safety as
    gate_lo: 0 colours green, 1+ colours red, under either convention."""
    b = float(threshold) + 0.5
    return (b, b, b)


def band_of(pillar, key):
    """Band for an axis IF the posture's envelope declares it, else None -> the column renders
    unbanded. This is how a posture that omits an axis (no co-stop / balloon / swap edge at
    best-effort) drops the color there instead of copying a stricter posture's band."""
    return band(pillar[key]) if key in pillar else None


def load_sm_ids():
    with open(SM_YAML, encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    ids = {e["key"]: e["id"] for e in doc["supermetrics"]}
    needed = ["G1", "G2", "G3", "G4", "G5", "G6", "G7", "G12", "G13", "G14", "G15", "G16", "G17",
              "X1", "X2", "X7", "R1", "R2"]
    missing = [k for k in needed if k not in ids]
    if missing:
        raise SystemExit(f"supermetrics.yaml is missing required SM keys: {missing}")
    return ids


def column(key, name, unit="", transform="CURRENT", sort=False, prop=False, string=False,
           bands=None, asc=False):
    return {"key": key, "name": name, "unit": unit, "transform": transform, "sort": sort,
            "prop": prop, "string": string, "bands": bands, "asc": asc}


def build_views(posture, ids):
    """Return {view_key: view_dict} - columns per exemplar section 4, bands per R1."""
    env = posture["envelope"]
    floor = posture["availability_floor"]
    pname = posture["posture"]

    def sm(k):
        return f"Super Metric|sm_{ids[k]}"

    cap_mem = env["capacity"]["mem_overcommit"]
    cap_cpu = env["capacity"]["cpu_overcommit"]
    perf = env["performance"]
    cost = env["cost"]
    # Floor bounds (generator-stamped from the availability floor, binary - the color IS the verdict)
    n_plus = float(floor["n_plus"])            # failover level must be >= n_plus
    min_hosts = n_plus + 1                     # member hosts >= n_plus + 1
    ha_ceiling = float(floor["headroom_ceiling_pct"]) if "headroom_ceiling_pct" in floor else None
    binary = lambda v: (v, v, v)
    # posture shape -> which judgments apply (each conditional below defaults to prod-db's behaviour)
    density = bool(posture.get("density_signal"))       # density-led: under-packing is the cost failure
    ha_required = floor.get("ha") == "required"         # full floor vs restartable-only
    protect_required = perf.get("protection_coverage") == "required"   # reservations expected?

    views = {}

    # ------------------------------------------------------------------ V1 - VM contention
    if protect_required:   # strict posture: any swap is a breach, reservations are required
        v1_desc = (   # kept < 1024 chars — the ViewDef Description maxLength
            "Blank cells mean the metric is not yet enabled in the posture policy or has not "
            f"completed a collection cycle. Virtual machines of posture {pname} judged against the "
            "envelope. CPU Ready, Memory Contention, CPU Co-stop and Memory Balloon render "
            "at the 95th percentile over the 7-day window, the peak the SLA feels, not the smoothed "
            "mean. Ready and Co-stop mean the VM pays scheduling tax now. Memory Contention is "
            "latency-weighted memory pressure. Balloon is pressure building. Swapped is past the "
            "cliff: any swap is a breach here, so its band is red above zero. Memory "
            "Reservation and Limit are the protection-coverage drift check: this posture requires "
            "reservations (0 is drift, red); a Limit of -1 is unlimited (correct) while >= 0 "
            "silently manufactures contention. Balloon and swap are host-rooted symptoms: the "
            "durable fix is de-densify, rebalance or reserve, not tune the VM. Bands are "
            "generator-stamped from the envelope. Sorted worst-first by peak CPU Ready %, then "
            "peak Memory Contention %.")
    else:                  # best-effort: contention is expected under density, no swap edge, reservations optional
        v1_desc = (
            "Blank cells mean the metric is not yet enabled in the posture policy or has not "
            f"completed a collection cycle. Virtual machines of posture {pname} judged against the "
            "posture envelope. CPU Ready and Memory Contention render at the 95th percentile over "
            "the 7-day window, the peak the workload feels. Ready means the VM is paying scheduling "
            "tax; Memory Contention is latency-weighted memory pressure. Co-stop, Balloon and "
            "Swapped are shown for context: at best-effort these are expected under density and "
            "carry no envelope edge, so they are read, not judged. Memory Reservation and Limit are "
            "context too: this posture expects no reservation, and a Limit of -1 is unlimited "
            "(correct). A breach here is a dashboard color for the weekly review, never a page. "
            "Bands are generator-stamped from the envelope. Sorted worst-first by peak CPU Ready %, "
            "then peak Memory Contention %.")
    views["V1"] = {
        "id": VIEW_IDS["V1"], "file": FILES["V1"], "resource_kind": "VirtualMachine",
        "title": f"PCA - WTPC - VM Contention vs Envelope ({pname})",
        "description": v1_desc,
        "columns": [
            column("cpu|readyPct", "CPU Ready % (95th)", unit="percent", transform="PERCENTILE",
                   sort=True, bands=band_of(perf, "cpu_ready_pct_p95")),
            column("mem|host_contentionPct", "Memory Contention % (95th)", unit="percent",
                   transform="PERCENTILE", sort=True, bands=band_of(perf, "mem_contention_pct_p95")),
            column("cpu|costopPct", "CPU Co-stop % (95th)", unit="percent", transform="PERCENTILE",
                   bands=band_of(perf, "cpu_costop_pct_p95")),
            column("mem|balloonPct", "Memory Balloon % (95th)", unit="percent",
                   transform="PERCENTILE", bands=band_of(perf, "mem_balloon_pct_p95")),
            column("mem|swapped_average", "Memory Swapped (GB)", unit="gb",
                   bands=band_of(perf, "mem_swapped_gb")),  # banded only where the envelope sets an edge
            column("cpu|demandmhz", "CPU Demand MHz (95th)", transform="PERCENTILE"),
            column("mem|active_average", "Active (GB)", unit="gb"),
            column("mem|consumed_average", "Consumed (GB)", unit="gb"),
            # protection-coverage properties (section 4 V1 cols 9-10; band-on-property is a
            # section 10-vi build confirm - fallback is unbanded + education)
            column("config|memoryAllocation|reservation",
                   "Memory Reservation (MB, need > 0)" if protect_required else "Memory Reservation (MB)",
                   prop=True, bands=gate_lo(1) if protect_required else None, asc=protect_required),
            column("config|memoryAllocation|limit", "Memory Limit (-1 = unlimited)", prop=True),
        ],
    }

    # ------------------------------------------------------------------ V2 - capacity hosts
    if density:   # density-led: overcommit band is a safety ceiling, low consumed is under-use
        v2_desc = (
            "Blank cells mean the metric is not yet enabled in the posture policy or has not "
            f"completed a collection cycle. Member hosts of posture {pname} render against the "
            "capacity envelope. Memory Overcommit (x DRAM) is provisioned VM memory over physical "
            "DRAM; density is the point here, so the band is the safety ceiling "
            f"({fmt(cap_mem['target'])}/{fmt(cap_mem['warn'])}/{fmt(cap_mem['breach'])}), and "
            "packing past breach is the thrash cliff. CPU Overcommit is allocated vCPU per physical "
            f"core ({fmt(cap_cpu['target'])}/{fmt(cap_cpu['warn'])}/{fmt(cap_cpu['breach'])}). The "
            "Envelope Position columns normalize each ratio by its breach edge: 1.0 means at the "
            "breach. Consumed % of DRAM is context: at this posture a low value is under-use, "
            "judged on the cluster views, not here. VM Memory Provisioned and Allocated vCPU are "
            "the raw numerators. Bands are generator-stamped from the posture envelope. Sorted by "
            "Memory Overcommit, then CPU Overcommit.")
    else:
        v2_desc = (
            "Blank cells mean the metric is not yet enabled in the posture policy or has not "
            f"completed a collection cycle. Member hosts of posture {pname} render against the "
            "capacity envelope. Memory Overcommit (x DRAM) is provisioned VM memory over physical "
            "DRAM; memory tiering is withheld at this posture, so the strict DRAM ratio carries "
            f"the band ({fmt(cap_mem['target'])}/{fmt(cap_mem['warn'])}/{fmt(cap_mem['breach'])}). "
            "CPU Overcommit is allocated vCPU per physical core "
            f"({fmt(cap_cpu['target'])}/{fmt(cap_cpu['warn'])}/{fmt(cap_cpu['breach'])}). The "
            "Envelope Position columns normalize each ratio by its breach edge: 1.0 means at the "
            "breach, for every posture, and their bands sit at target/breach and warn/breach. "
            "Consumed % of DRAM is an advisory saturation ceiling (60 and 80 are the documented "
            "headroom/active edges), a ceiling reading, not a trigger to chase. VM Memory "
            "Provisioned and Allocated vCPU are the raw numerators. Bands are generator-stamped "
            "from the posture envelope. Sorted by Memory Overcommit, then CPU Overcommit.")
    views["V2"] = {
        "id": VIEW_IDS["V2"], "file": FILES["V2"], "resource_kind": "HostSystem",
        "title": f"PCA - WTPC - Capacity Envelope - Hosts ({pname})",
        "description": v2_desc,
        "columns": [
            column(sm("G2"), "Memory Overcommit (x DRAM)", sort=True, bands=band(cap_mem)),
            column(sm("G4"), "CPU Overcommit (vCPU per pCPU)", sort=True, bands=band(cap_cpu)),
            column(sm("X1"), "Mem Envelope Position", bands=position_band(cap_mem)),
            column(sm("X2"), "CPU Envelope Position", bands=position_band(cap_cpu)),
            column(f"Super Metric|sm_{SH_CONSUMED_DRAM}", "Consumed % of DRAM", unit="percent",
                   bands=None if density else CONSUMED_DRAM_ADVISORY),  # low consumed is the failure at density
            column(sm("G1"), "VM Memory Provisioned (GB)", unit="gb"),
            column(sm("G3"), "Allocated vCPU", unit="7004"),
        ],
    }

    # ------------------------------------------------------------------ V3 - capacity clusters
    if density:   # density-led: under-packing is the cost failure, so the density signal leads + sorts
        v3_desc = (
            "Blank cells mean the metric is not yet enabled in the posture policy or has not "
            f"completed a collection cycle. Member clusters of posture {pname} render against the "
            "capacity envelope. Density Position vs Target leads: at best-effort an under-packed "
            "cluster is the cost failure, so the most under-packed cluster sorts to the top. "
            "Cluster ratios are sum-of-numerators over sum-of-denominators, never averages of "
            "ratios. Memory and CPU Overcommit carry the safety ceiling band, because packing past "
            "breach is the thrash cliff even here. Hosts Over Memory and CPU Envelope count the "
            "members past that safety edge. Worst Host Memory Overcommit surfaces the packing skew "
            "a cluster average hides. Consumed % of HA DRAM is context; this posture declares no "
            "failover reserve ceiling. Bands are generator-stamped from the posture envelope. "
            "Sorted by Density Position, then Hosts Over Memory Envelope.")
        v3_cols = [
            column(sm("X8"), "Density Position vs Target", sort=True, bands=(1.0, 1.33, 2.0)),
            column(sm("G5"), "Memory Overcommit (x DRAM)", bands=band(cap_mem)),
            column(sm("G6"), "CPU Overcommit (vCPU per pCPU)", bands=band(cap_cpu)),
            column(sm("R1"), "Hosts Over Memory Envelope", unit="7004", sort=True, bands=gate_hi(0)),
            column(sm("R2"), "Hosts Over CPU Envelope", unit="7004", bands=gate_hi(0)),
            column(sm("G7"), "Worst Host Memory Overcommit (x DRAM)", bands=band(cap_mem)),
            column(f"Super Metric|sm_{SH_CONSUMED_HA_DRAM}", "Consumed % of HA DRAM", unit="percent"),
            column(sm("G12"), "Member Hosts", unit="7004"),
        ]
    else:
        v3_desc = (
            "Blank cells mean the metric is not yet enabled in the posture policy or has not "
            f"completed a collection cycle. Member clusters of posture {pname} against the "
            "capacity envelope. Worst Host Memory Overcommit leads: packing skew hides in cluster "
            "averages, so at this SLA the worst member carries the judgment. Cluster ratios "
            "are sum-of-numerators over sum-of-denominators, never averages of ratios. Hosts Over "
            "Memory/CPU Envelope are the now-clock compliance counts, and any nonzero count is "
            "red. Consumed % of HA DRAM is the floor-coupling gate shown as a display gradient "
            f"toward the pass/fail ceiling ({fmt(ha_ceiling)}): packing that eats the failover "
            "reserve is a deferred outage, not density. Past the envelope, the drift playbook "
            "runs Reclaim, then Rebalance, then Buy. Memory tiering is deliberately "
            "withheld (pinned memory cannot tier; never combine tiering with overcommit). "
            "Bands are generator-stamped from the posture envelope. Sorted by Worst Host Memory "
            "Overcommit, then Hosts Over Memory Envelope.")
        v3_cols = [
            column(sm("G7"), "Worst Host Memory Overcommit (x DRAM)", sort=True, bands=band(cap_mem)),
            column(sm("G5"), "Memory Overcommit (x DRAM)", bands=band(cap_mem)),
            column(sm("G6"), "CPU Overcommit (vCPU per pCPU)", bands=band(cap_cpu)),
            column(sm("R1"), "Hosts Over Memory Envelope", unit="7004", sort=True, bands=gate_hi(0)),
            column(sm("R2"), "Hosts Over CPU Envelope", unit="7004", bands=gate_hi(0)),
            column(f"Super Metric|sm_{SH_CONSUMED_HA_DRAM}", "Consumed % of HA DRAM", unit="percent",
                   bands=(CONSUMED_HA_GRADIENT_EDGES[0], CONSUMED_HA_GRADIENT_EDGES[1], ha_ceiling)),
            column(f"Super Metric|sm_{SH_FLEET_RECLAIM_COST}", "Fleet Reclaimable Cost ($/mo)", unit="currency"),
            column(sm("G12"), "Member Hosts", unit="7004"),
        ]
    views["V3"] = {
        "id": VIEW_IDS["V3"], "file": FILES["V3"], "resource_kind": "ClusterComputeResource",
        "title": f"PCA - WTPC - Capacity Envelope - Clusters ({pname})",
        "description": v3_desc, "columns": v3_cols,
    }

    # ------------------------------------------------------------------ V4 - cost scorecard
    cost_band = band(cost["reclaimable_pct"])
    views["V4"] = {
        "id": VIEW_IDS["V4"],
        "file": FILES["V4"],
        "title": f"PCA - WTPC - Cost Scorecard ({pname})",
        "resource_kind": "ClusterComputeResource",
        "description": (
            "Blank dollars mean the cost engine has not yet attributed a value; other blanks mean "
            "the metric is not yet enabled in the posture policy or has not completed a collection "
            f"cycle. Member clusters of posture {pname} against the cost envelope. Reclaimable "
            f"Memory % ({fmt(cost_band[0])}/{fmt(cost_band[1])}/{fmt(cost_band[2])}) is the score "
            "carrier: the envelope prices in purchased headroom (reservations and 1.0 memory "
            "overcommit are protection, not waste), so the score only moves on unclaimed oversize "
            "from the demand analysis. Reclaimable Envelope Position normalizes by the breach edge "
            "(1.0 means at breach). Cost Coverage % is a validity gate, not a score: below the "
            f"threshold ({fmt(COST_COVERAGE_PROVISIONAL_PCT)}%, provisional until measured "
            "attribution sets it) the dollars read as insufficient cost-engine coverage, and a low "
            "number with low coverage is unknown, not green. Cost per Workload is reported and "
            "baselined at activation, not banded in v1. Bands are generator-stamped from the "
            "posture envelope. Sorted by Reclaimable Memory %, "
            + ("then Density Position, " if density else "") + "then Cost Coverage %."
        ),
        "columns": [
            column(sm("G14"), "Reclaimable Memory (%)", unit="percent", sort=True,
                   bands=cost_band),
            column(sm("X7"), "Reclaimable Envelope Position",
                   bands=position_band(cost["reclaimable_pct"])),
            # density-led postures catch under-packing here (secondary sort); absent otherwise
            *([column(sm("X8"), "Density Position vs Target", sort=True, bands=(1.0, 1.33, 2.0))] if density else []),
            column(sm("G15"), "Cost Coverage (%)", unit="percent", sort=True,
                   bands=binary(float(COST_COVERAGE_PROVISIONAL_PCT)), asc=True),  # red below gate
            column(f"Super Metric|sm_{SH_FLEET_RECLAIM_COST}", "Fleet Reclaimable Cost ($/mo)",
                   unit="currency"),
            column(sm("G16"), "Total Cost ($/mo)", unit="currency"),
            column(sm("G17"), "Cost per Workload ($/mo)", unit="currency"),
            column(sm("G13"), "Member VMs", unit="7004"),
        ],
    }

    # ------------------------------------------------------------------ V5 - availability floor
    if ha_required:
        v5_desc = (   # kept < 1024 chars — the ViewDef Description maxLength
            "Blank cells mean the metric is not yet enabled in the posture policy or has not "
            f"completed a collection cycle. The availability floor for posture {pname} is one "
            "row per member cluster, one column per check, and binary bounds: the color IS the "
            "verdict (pass/fail, never a score). A2: admission control must be enabled (string "
            "display, judged by the floor alert). A3: failover level must be at least "
            f"{fmt(n_plus)} and member hosts at least {fmt(min_hosts)} (N+{fmt(n_plus)}). A4: DRS "
            f"must be fully automated (0 is red). A5: Consumed % of HA-usable DRAM must not exceed "
            f"{fmt(ha_ceiling)} (binary, no gradient), with the declared memory failover reserve "
            "shown alongside. A6: HA config issues must be 0, and hosts connected to master "
            "must equal member hosts minus one (N-1, master self-excluded, display column). "
            "Anti-affinity for the db replica pairs has no verified observable: an UNVERIFIED "
            "monthly hand check, never rendered as PASS. A red floor cell voids the tuning scores "
            "elsewhere, so restore the floor first. Bounds are generator-stamped from the floor.")
        v5_cols = [   # keys live-verified: dasConfig/drsConfig floor checks are METRICS, not properties
            # Admission control: the property reads true/false (clear); the metric is a cryptic -1.
            column("configuration|dasConfig|admissionControlEnabled",
                   "Admission Control (must be on)", prop=True, string=True),
            column("configuration|dasConfig|currentFailoverLevel", "HA Failover Level (need 1+)",
                   bands=gate_lo(n_plus), asc=True),                  # red below n_plus (bound n_plus-0.5)
            column(sm("G12"), "Member Hosts (need 2+)", unit="7004",
                   bands=gate_lo(min_hosts), asc=True),               # red below n_plus + 1 (bound min-0.5)
            column("configuration|drsConfig|enabledAndFullyAutomated",
                   "DRS Fully Automated (0 = no)", bands=gate_lo(1), asc=True),  # 1=automated green, 0=fail red
            column(f"Super Metric|sm_{SH_CONSUMED_HA_DRAM}", "Consumed % of HA DRAM (keep < 100)",
                   unit="percent", sort=True, bands=binary(ha_ceiling)),  # red above the ceiling
            column("configuration|dasConfig|currentMemoryFailoverResourcesPercent",
                   "Declared Memory Reserve %"),                      # metric; display
            column("configuration|dasConfig|ha_number_config_issues", "HA Config Issues (must be 0)",
                   bands=gate_hi(0)),                                 # metric; 0 green, any > 0 red
            column("configuration|dasConfig|ha_hosts_connected_to_master",
                   "Hosts Connected to Master"),                      # metric; N-1 (master excluded)
        ]
    else:   # restartable-only floor: two judged checks (HA on, config clean); the rest is context
        v5_desc = (
            "Blank cells mean the metric is not yet enabled in the posture policy or has not "
            f"completed a collection cycle. The availability floor for posture {pname} collapses "
            "to restartability: one row per member cluster, one column per check. HA Restart "
            "Enabled and HA Config Issues carry the verdict; restart protection must be on and its "
            "config must be clean. Admission Control, HA Failover Level, Member Hosts, DRS "
            "Automation and Consumed % of HA DRAM are context: this posture promises no "
            "host-failure headroom, so an empty red set is the designed norm, not a broken view. "
            "Declared Memory Reserve is shown alongside. When a judged cell turns red, restore "
            "restartability before reading the scores below. Bounds are stamped from the floor.")
        v5_cols = [
            column("configuration|dasConfig|enabled", "HA Restart Enabled", prop=True, string=True),
            column("configuration|dasConfig|admissionControlEnabled", "Admission Control", prop=True, string=True),
            column("configuration|dasConfig|currentFailoverLevel", "HA Failover Level"),          # display
            column(sm("G12"), "Member Hosts", unit="7004"),                                       # display
            column("configuration|drsConfig|defaultVmBehavior", "DRS Automation", prop=True, string=True),
            column(f"Super Metric|sm_{SH_CONSUMED_HA_DRAM}", "Consumed % of HA DRAM", unit="percent"),  # display
            column("configuration|dasConfig|currentMemoryFailoverResourcesPercent", "Declared Memory Reserve %"),
            column("configuration|dasConfig|ha_number_config_issues", "HA Config Issues (must be 0)",
                   sort=True, bands=gate_hi(0)),                      # worst-first: most config issues on top
        ]
    views["V5"] = {
        "id": VIEW_IDS["V5"], "file": FILES["V5"], "resource_kind": "ClusterComputeResource",
        "title": f"PCA - WTPC - Availability Floor ({pname})",
        "description": v5_desc, "columns": v5_cols,
    }

    return views


# ---------------------------------------------------------------------- XML emission

def _prop(parent, name, value):
    ET.SubElement(parent, "Property", {"name": name, "value": value})


def _bool(b):
    return "true" if b else "false"


def add_column_item(list_el, c, resource_kind):
    """One <Item><Value> per column - exact Property set/order of the rightsizing exemplars."""
    val = ET.SubElement(ET.SubElement(list_el, "Item"), "Value")
    _prop(val, "objectType", "RESOURCE")
    _prop(val, "attributeKey", c["key"])
    _prop(val, "preferredUnitId", c["unit"])
    _prop(val, "isStringAttribute", _bool(c["string"]))
    _prop(val, "adapterKind", "VMWARE")
    _prop(val, "resourceKind", resource_kind)
    _prop(val, "rollUpType", "NONE")
    _prop(val, "rollUpCount", "0")
    tr_list = ET.SubElement(ET.SubElement(val, "Property", {"name": "transformations"}), "List")
    ET.SubElement(tr_list, "Item", {"value": c["transform"]})
    if c["transform"] == "PERCENTILE":
        _prop(val, "percentile", "95")
    _prop(val, "sortCriteria", _bool(c["sort"]))
    _prop(val, "isProperty", _bool(c["prop"]))
    if c["bands"] is not None:
        y, o, r = c["bands"]
        _prop(val, "yellowBound", fmt(y))
        _prop(val, "orangeBound", fmt(o))
        _prop(val, "redBound", fmt(r))
        _prop(val, "ascendingRange", _bool(c["asc"]))
    _prop(val, "displayName", c["name"])
    _prop(val, "addTimestampAsColumn", "false")
    _prop(val, "isShowRelativeTimestamp", "false")


def emit_view(view):
    """Build the <Content><Views><ViewDef> document (shape: rightsizing exemplars verbatim)."""
    content = ET.Element("Content")
    views_el = ET.SubElement(content, "Views")
    vd = ET.SubElement(views_el, "ViewDef", {"id": view["id"]})
    ET.SubElement(vd, "Title").text = view["title"]
    ET.SubElement(vd, "Description").text = view["description"]
    for stype in ("descendant", "self"):   # BOTH - descendant serves broad inputs (views.md)
        ET.SubElement(vd, "SubjectType", {"adapterKind": "VMWARE",
                                          "resourceKind": view["resource_kind"], "type": stype})
    for usage in ("dashboard", "report", "details", "content"):
        ET.SubElement(vd, "Usage").text = usage

    controls = ET.SubElement(vd, "Controls")
    tis = ET.SubElement(controls, "Control",
                        {"id": "tis_1", "type": "time-interval-selector", "visible": "false"})
    _prop(tis, "advancedTimeMode", "false")
    _prop(tis, "unit", "DAYS")
    _prop(tis, "count", "7")

    asel = ET.SubElement(controls, "Control",
                         {"id": "as_2", "type": "attributes-selector", "visible": "false"})
    attr_list = ET.SubElement(ET.SubElement(asel, "Property", {"name": "attributeInfos"}), "List")
    for c in view["columns"]:
        add_column_item(attr_list, c, view["resource_kind"])

    pg = ET.SubElement(controls, "Control",
                       {"id": "pg_3", "type": "pagination-control", "visible": "true"})
    _prop(pg, "start", "0")
    _prop(pg, "size", "50")

    md = ET.SubElement(controls, "Control", {"id": "md_4", "type": "metadata", "visible": "false"})
    _prop(md, "maxPointsCount", "5000")
    _prop(md, "hideObjectNameColumn", "false")
    _prop(md, "listTopResultSize", "-1")

    ET.SubElement(ET.SubElement(vd, "DataProviders"), "DataProvider",
                  {"dataType": "list-view", "id": "lv_0"})
    ET.SubElement(vd, "Presentation", {"type": "list"})

    # ElementTree serialization XML-escapes every text node and attribute value (&, <, >, ")
    # - the defect class the content-import API passes but the UI import rejects (views.md).
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            + ET.tostring(content, encoding="unicode"))


# ---------------------------------------------------------------------- self-validation

COLUMN_XPATH = ("Views/ViewDef/Controls/Control[@type='attributes-selector']"
                "/Property/List/Item")  # exact depth - does not match nested transformation Items
UUID_RE = re.compile(r"^sm_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def validate(view_key, path, view):
    root = ET.parse(path).getroot()          # must parse - proves escaping
    items = root.findall(COLUMN_XPATH)
    n_expected = len(view["columns"])        # the emitted XML must carry exactly the defined columns
    assert len(items) == n_expected, (
        f"{view_key}: {len(items)} columns, expected {n_expected}")
    # ViewDef <Description> maxLength is 1024 in the import XSD — an over-length one fails the UI
    # import (cvc-maxLength-valid), not the parse. Guard it here so it never ships.
    desc = root.findtext("Views/ViewDef/Description") or ""
    assert len(desc) <= 1024, f"{view_key}: Description {len(desc)} chars > 1024 (ViewDef maxLength)"
    sort_cols, percentile_ok = [], True
    for idx, item in enumerate(items, 1):
        props = {p.get("name"): p.get("value") for p in item.find("Value")
                 if p.tag == "Property" and p.get("value") is not None}
        key = props["attributeKey"]
        assert key and "<" not in key and ">" not in key, f"{view_key} col {idx}: unresolved key"
        if key.startswith("Super Metric|"):
            assert UUID_RE.match(key.split("|", 1)[1]), (
                f"{view_key} col {idx}: malformed SM reference {key!r}")
        tr = [i.get("value") for i in item.find("Value").findall(
            "Property[@name='transformations']/List/Item")]
        assert (tr == ["PERCENTILE"]) == ("percentile" in props), (
            f"{view_key} col {idx}: percentile sibling must accompany PERCENTILE exactly")
        if props["sortCriteria"] == "true":
            sort_cols.append(idx)
        bands = [b for b in ("yellowBound", "orangeBound", "redBound") if b in props]
        assert len(bands) in (0, 3), f"{view_key} col {idx}: partial band set {bands}"
        if bands:
            assert "ascendingRange" in props, f"{view_key} col {idx}: banded without ascendingRange"
    expected_sorts = [i + 1 for i, c in enumerate(view["columns"]) if c["sort"]]
    assert sort_cols == expected_sorts, (
        f"{view_key}: sort columns {sort_cols} != spec {expected_sorts}")
    assert root.find("Views/ViewDef").get("id") == view["id"]
    return len(items), sort_cols


def main():
    with open(POSTURE_YAML, encoding="utf-8") as f:
        posture = yaml.safe_load(f)
    ids = load_sm_ids()
    views = build_views(posture, ids)

    os.makedirs(CONTENT_DIR, exist_ok=True)
    print(f"posture: {posture['posture']}  (envelope -> view bands, R1 generator-stamped)")
    for key in ("V1", "V2", "V3", "V4", "V5"):
        view = views[key]
        path = os.path.join(CONTENT_DIR, view["file"])
        with open(path, "w", encoding="utf-8") as f:
            f.write(emit_view(view))
        n, sorts = validate(key, path, view)
        print(f"  {key}  {view['file']}: {n} columns, sort={sorts}, "
              f"parse OK, id={view['id']}")
    print("all 5 views emitted + validated (ET.parse, column counts, sort order, SM resolution)")


if __name__ == "__main__":
    main()
