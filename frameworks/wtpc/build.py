#!/usr/bin/env python3
"""WTPC posture build / reproduction tool  (the generator + the portable reproduction path).

Reads a posture YAML (the single source of truth), GENERATES the super-metric DAG — the breach
constants are stamped from the envelope's breach values, so no threshold is hand-placed in two
mechanisms  — POSTs the 35 SMs in dependency order resolving every cross-reference to
its freshly-minted id, then emits `supermetrics.yaml` (the record) and the policy `capacityDefinition`
payload (also generated from the envelope). Runs on ANY Operations instance; idempotent (reuses a
same-named SM). This is why the committed bundle is reproducible on a clean Ops even though SM ids are
instance-minted: the ids in `supermetrics.yaml` are an output *record*, not the portable key — the
portable key is this generator + the posture YAML.

Usage:  python build.py postures/prod-latency-critical-db.yaml [--dry-run]

Cross-instance transfer of the LIVE definitions (id-preserving) uses a content-import package; this
tool is the from-source rebuild. Every statkey binding was verified live before it entered a formula. SM name rule: no ':' or '|' in a name.
"""
import sys, os, re, yaml
from lib._client import ops_client, policy_index
from lib._sm import activate_in_policy, existing_supermetrics, upsert_supermetric

HERE = os.path.dirname(os.path.abspath(__file__))
def A(body): return "${adaptertype=VMWARE, " + body + "}"

def shared_record(dry: bool):
    """{key: (id, applies_to)} from supermetrics.shared.yaml - the instance record adopt_shared.py
    emits. The posture formulas and the scorecard reference these by id, so the record is a
    precondition: fail loud with the fix rather than emit formulas that resolve to nothing. In
    dry-run a missing record previews with DRY placeholders (read from the portable source) so a
    fresh estate's first full-DAG preview still walks every step."""
    path = os.path.join(HERE, "supermetrics.shared.yaml")
    if not os.path.exists(path):
        if dry:
            src = yaml.safe_load(open(os.path.join(HERE, "shared", "supermetrics.yaml"),
                                      encoding="utf-8"))["supermetrics"]
            return {e["key"]: (f"DRY-{e['key']}", e["applies_to"]) for e in src}
        sys.exit("supermetrics.shared.yaml not found - run adopt_shared.py first "
                 "(it adopts the shared/lens SMs this posture's content references)")
    return {e["key"]: (e["id"], e["applies_to"])
            for e in yaml.safe_load(open(path, encoding="utf-8"))["supermetrics"]}

# Each envelope axis -> its breach constant (C), envelope position (X = observed / breach), and optional
# roll-up (R = count of members past breach). Generation is ENVELOPE-DRIVEN: an axis absent from a
# posture's envelope emits none of its family, so a best-effort posture with no co-stop / balloon edges
# simply has no co-stop / balloon SMs. The C/X/R blocks keep their order. Statkeys per verified-statkeys.md.
AXES = [
  # (C, X, R, (pillar, metric), (C-name, obj, anchor), (X-name, obj, numerator), (R-name, obj-type, depth) | None)
  ("C1", "X1", "R1", ("capacity", "mem_overcommit"),
   ("Host - Breach Memory Overcommit", "HostSystem", "mem|totalCapacity_average"),
   ("Host - Memory Overcommit Envelope Position", "HostSystem", "Super Metric|sm_{G2}"),
   ("Cluster - Hosts Over Memory Envelope (count)", "HostSystem", 1)),
  ("C2", "X2", "R2", ("capacity", "cpu_overcommit"),
   ("Host - Breach CPU Overcommit", "HostSystem", "mem|totalCapacity_average"),
   ("Host - CPU Overcommit Envelope Position", "HostSystem", "Super Metric|sm_{G4}"),
   ("Cluster - Hosts Over CPU Envelope (count)", "HostSystem", 1)),
  ("C3", "X3", "R3", ("performance", "cpu_ready_pct_p95"),
   ("VM - Breach CPU Ready", "VirtualMachine", "mem|guest_provisioned"),
   ("VM - CPU Ready Envelope Position", "VirtualMachine", "cpu|readyPct"),
   ("Cluster - VMs Over Ready Breach (count)", "VirtualMachine", 2)),
  ("C4", "X4", "R4", ("performance", "mem_contention_pct_p95"),
   ("VM - Breach Memory Contention", "VirtualMachine", "mem|guest_provisioned"),
   ("VM - Memory Contention Envelope Position", "VirtualMachine", "mem|host_contentionPct"),
   ("Cluster - VMs Over Contention Breach (count)", "VirtualMachine", 2)),
  ("C5", "X5", None, ("performance", "cpu_costop_pct_p95"),
   ("VM - Breach CPU Co-stop", "VirtualMachine", "mem|guest_provisioned"),
   ("VM - CPU Co-stop Envelope Position", "VirtualMachine", "cpu|costopPct"),
   None),
  ("C6", "X6", None, ("performance", "mem_balloon_pct_p95"),
   ("VM - Breach Memory Balloon", "VirtualMachine", "mem|guest_provisioned"),
   ("VM - Memory Balloon Envelope Position", "VirtualMachine", "mem|balloonPct"),
   None),
  ("C7", "X7", None, ("cost", "reclaimable_pct"),
   ("Cluster - Breach Reclaimable Memory", "ClusterComputeResource", "mem|haTotalCapacity_average"),
   ("Cluster - Reclaimable Envelope Position", "ClusterComputeResource", "Super Metric|sm_{G14}"),
   None),
]

def build_defs(posture):
    """Return the ordered SM list (key, name, object, unit, formula-with-{placeholders})."""
    P = posture["posture"]
    e = posture["envelope"]
    sms = [
      # class G — observation (posture-agnostic)
      ("G1","PCA - WTPC - Host - VM Memory Provisioned (GB)","HostSystem","gb",
        "(sum("+A("objecttype=VirtualMachine, metric=mem|guest_provisioned, depth=1")+") / 1048576)"),
      ("G3","PCA - WTPC - Host - VM vCPU Allocated (count)","HostSystem","7004",
        "sum("+A("objecttype=VirtualMachine, metric=config|hardware|num_Cpu, depth=1")+")"),
      ("G8","PCA - WTPC - Cluster - Worst VM CPU Ready (%)","ClusterComputeResource","percent",
        "max("+A("objecttype=VirtualMachine, metric=cpu|readyPct, depth=2")+")"),
      ("G9","PCA - WTPC - Cluster - Worst VM Memory Contention (%)","ClusterComputeResource","percent",
        "max("+A("objecttype=VirtualMachine, metric=mem|host_contentionPct, depth=2")+")"),
      ("G10","PCA - WTPC - Cluster - Worst VM CPU Co-stop (%)","ClusterComputeResource","percent",
        "max("+A("objecttype=VirtualMachine, metric=cpu|costopPct, depth=2")+")"),
      ("G11","PCA - WTPC - Cluster - VMs Swapping (count)","ClusterComputeResource","7004",
        "count("+A("objecttype=VirtualMachine, metric=mem|swapped_average, depth=2, where=($value > 0)")+")"),
      ("G12","PCA - WTPC - Cluster - Member Hosts (count)","ClusterComputeResource","7004",
        "count("+A("objecttype=HostSystem, metric=mem|active_average, depth=1")+")"),
      ("G13","PCA - WTPC - Cluster - Cluster VMs (count)","ClusterComputeResource","7004",
        "count("+A("objecttype=VirtualMachine, metric=mem|guest_provisioned, depth=2")+")"),
      ("G14","PCA - WTPC - Cluster - Reclaimable Memory (%)","ClusterComputeResource","percent",
        "(100 * (sum("+A("objecttype=VirtualMachine, metric=Super Metric|sm_{SH_RECLAIM}, depth=2, where=($value > 0)")+") / (sum("+A("objecttype=VirtualMachine, metric=mem|guest_provisioned, depth=2")+") / 1048576)))"),
      ("G15","PCA - WTPC - Cluster - Cost Coverage (%)","ClusterComputeResource","percent",
        "(100 * (count("+A("objecttype=VirtualMachine, metric=cost|effectiveProjectedTotalCost, depth=2")+") / count("+A("objecttype=VirtualMachine, metric=mem|guest_provisioned, depth=2")+")))"),
      ("G16","PCA - WTPC - Cluster - Total Cost (USD/mo)","ClusterComputeResource","currency",
        "sum("+A("objecttype=VirtualMachine, metric=cost|effectiveProjectedTotalCost, depth=2")+")"),
      ("G2","PCA - WTPC - Host - Memory Overcommit (x DRAM)","HostSystem","",
        "(${this, metric=Super Metric|sm_{G1}} / (${this, metric=mem:DRAM|memory_tier_total_capacity} / 1048576))"),
      ("G4","PCA - WTPC - Host - CPU Overcommit (vCPU per pCPU)","HostSystem","",
        "(${this, metric=Super Metric|sm_{G3}} / ${this, metric=cpu|corecount_provisioned})"),
      ("G5","PCA - WTPC - Cluster - Memory Overcommit (x DRAM)","ClusterComputeResource","",
        "(sum("+A("objecttype=HostSystem, metric=Super Metric|sm_{G1}, depth=1")+") / (sum("+A("objecttype=HostSystem, metric=mem:DRAM|memory_tier_total_capacity, depth=1")+") / 1048576))"),
      ("G6","PCA - WTPC - Cluster - CPU Overcommit (vCPU per pCPU)","ClusterComputeResource","",
        "(sum("+A("objecttype=HostSystem, metric=Super Metric|sm_{G3}, depth=1")+") / sum("+A("objecttype=HostSystem, metric=cpu|corecount_provisioned, depth=1")+"))"),
      ("G7","PCA - WTPC - Cluster - Worst Host Memory Overcommit (x DRAM)","ClusterComputeResource","",
        "max("+A("objecttype=HostSystem, metric=Super Metric|sm_{G2}, depth=1")+")"),
      ("G17","PCA - WTPC - Cluster - Cost per Workload (USD/mo)","ClusterComputeResource","currency",
        "(${this, metric=Super Metric|sm_{G16}} / ${this, metric=Super Metric|sm_{G13}})"),
    ]
    # classes C (breach constant), X (envelope position), R (roll-up) — one family per envelope axis
    # present. The blocks keep their order (all C, then all X, then all R).
    c_defs, x_defs, r_defs = [], [], []
    for ck, xk, rk, (pillar, metric), (cn, co, ca), (xn, xo, xnum), rspec in AXES:
        axis = (e.get(pillar) or {}).get(metric)
        if not axis or axis.get("breach") is None:
            continue   # axis not in this posture's envelope -> its C/X/R do not exist
        c_defs.append((ck, f"PCA - WTPC - {cn} ({P})", co, "",
                       f"(${{this, metric={ca}}} * 0 + {axis['breach']})"))
        x_defs.append((xk, f"PCA - WTPC - {xn} ({P})", xo, "",
                       f"(${{this, metric={xnum}}} / ${{this, metric=Super Metric|sm_{{{ck}}}}})"))
        if rspec:
            rn, rot, rd = rspec   # rot = the objecttype counted; the roll-up SM itself applies to the cluster
            r_defs.append((rk, f"PCA - WTPC - {rn} ({P})", "ClusterComputeResource", "7004",
                           "count(" + A(f"objecttype={rot}, metric=Super Metric|sm_{{{xk}}}, depth={rd}, where=($value > 1)") + ")"))
    # density-position signal (the under-packing carrier for density-led postures): target / observed,
    # so >1 = below the overcommit target = the cost/density failure a best-effort posture polices.
    if posture.get("density_signal"):
        tgt = e["capacity"]["mem_overcommit"]["target"]
        x_defs.append(("X8", f"PCA - WTPC - Cluster - Density Position vs Target ({P})", "ClusterComputeResource", "",
                       f"({tgt} / ${{this, metric=Super Metric|sm_{{G5}}}})"))
    return sms + c_defs + x_defs + r_defs

def subst(f, ids):
    for k,v in ids.items(): f=f.replace("{"+k+"}", v)
    return f

def main():
    args=[a for a in sys.argv[1:] if not a.startswith("--")]
    dry="--dry-run" in sys.argv
    posture=yaml.safe_load(open(args[0] if args else os.path.join(HERE,"postures/prod-latency-critical-db.yaml")))
    P=posture["posture"]; defs=build_defs(posture)
    keys=[d[0] for d in defs]
    assert len(keys)==len(set(keys)), f"duplicate SM key in {P}: {[k for k in keys if keys.count(k)>1]}"
    shared=shared_record(dry)
    with ops_client() as c:
        existing=existing_supermetrics(c)
        # seed the substitution map with the shared/lens ids (adopt_shared.py's record) so a formula
        # placeholder like {SH_RECLAIM} resolves exactly like a sibling {G2} reference
        ids={k: i for k,(i,_a) in shared.items()}; rows=[]; posted=reused=0
        for key,name,obj,unit,formula in defs:
            f=subst(formula, ids)
            if re.search(r"\{[GCXR]\d+\}", f): sys.exit(f"unresolved ref in {key}: {f}")
            sid, action = upsert_supermetric(c, name=name, formula=f,
                description=sm_description(key, obj, unit, P), existing=existing, dry=dry, dry_id=f"DRY-{key}")
            if action == "posted": posted += 1
            elif action == "reused": reused += 1
            ids[key]=sid; rows.append((key,name,obj,unit,sid,f))
        print(f"posted={posted} reused={reused} total={len(rows)}" + ("  [DRY-RUN]" if dry else ""))
        if not dry:                      # dry-run is side-effect-free: no live POST, no file writes
            # ACTIVATION (programmatic, NOT a manual UI step): assign each SM its object type AND
            # enable it in THIS posture's policy (PUT /internal/supermetrics/assign, header-gated).
            # A POSTed-but-unassigned SM never computes (it stays blank). build.py now self-completes
            # create -> activate, so it no longer depends on a separate validate_live.py --assign run.
            # (The 4 PCA - Shared refs + lens SMs the scorecard also reads are activated by their owners.)
            pols=policy_index(c)
            pid=pols.get(f"PCA - WTPC - Policy - {P}")
            if pid:
                for _k,_n,obj,_u,sid,_f in rows:
                    activate_in_policy(c, sid, pid, obj)
                # the shared/lens SMs too: the starter estate is self-contained, so the refs the
                # scorecard reads (reclaim, consumed-of-DRAM, the lens quartet) are enabled in this
                # posture's policy here rather than by a separate owning bundle
                shared_acts = 0
                for _k,(sid,kinds) in shared.items():
                    for kind in kinds:
                        activate_in_policy(c, sid, pid, kind)
                        shared_acts += 1
                print(f"activated: {len(rows)} posture SMs + {shared_acts} shared/lens assignments "
                      f"enabled in PCA - WTPC - Policy - {P} (programmatic; no manual UI enablement)")
            else:
                print(f"NOTE: policy 'PCA - WTPC - Policy - {P}' not live - SMs POSTed but not enabled; "
                      "instantiate the posture policy first, then re-run to activate")
            emit_yaml(rows, P)
            emit_policy_payload(posture)

def sm_description(key,obj,unit,P):
    if key.startswith("C"):
        return (f"OBJECT: {obj}. UNIT: (constant). WTPC posture {P} envelope breach edge, GENERATED from "
                f"the posture catalog by build.py. Edit the posture envelope + rerun the generator; the "
                f"'* 0' term is an anchor that makes the constant compute per object - DO NOT change it.")
    if key=="X8":   # density position is INVERTED from the X-family: target / observed, not observed / breach
        return (f"OBJECT: {obj}. UNIT: {unit or '(ratio)'}. WTPC density position = target / observed "
                f"(>1 = below the overcommit target = under-packed, the cost failure this best-effort posture "
                f"polices). Generated by build.py from posture {P}; see the WTPC starter estate.")
    role={"G":"observation (posture-agnostic)","X":"envelope position = observed / breach (>1 = out of envelope)",
          "R":"compliance roll-up = count of members out of envelope"}[key[0]]
    return f"OBJECT: {obj}. UNIT: {unit or '(ratio)'}. WTPC {role}. Generated by build.py from posture {P}; see the WTPC starter estate."

def emit_yaml(rows, P):
    def cls(k): return {"G":"G - observation (posture-agnostic; enable per-policy)","C":"C - breach constants (generated from the envelope)",
                        "X":"X - envelope positions (per-posture)","R":"R - compliance roll-ups (per-posture)"}[k[0]]
    ng=sum(1 for r in rows if r[0][0]=="G"); nc=sum(1 for r in rows if r[0][0]=="C")
    nx=sum(1 for r in rows if r[0][0]=="X"); nr=sum(1 for r in rows if r[0][0]=="R"); total=len(rows)
    L=[f"# WTPC super metrics - posture {P}  (GENERATED by build.py from postures/{P}.yaml - do not hand-edit)",
       "#", f"# {total} SMs: {ng} observation (G) + {nc+nx+nr} posture-family ({nc} breach constants C from the",
       f"# envelope, {nx} positions X, {nr} roll-ups R). Ids below are this run's minted ids (an output RECORD,",
       "# not the portable key - rebuild on any Ops with build.py). ACTIVATION is PROGRAMMATIC:",
       "# build.py assigns each SM's object type + ENABLES it in this posture's policy via",
       "# PUT /internal/supermetrics/assign (the header-gated internal surface; only the SM display",
       "# unit has no REST field). The shared/lens refs the scorecard reads are activated from",
       "# supermetrics.shared.yaml in the same pass. Values validate on tagged members.",
       "# NAME rule: no ':' or '|' in a super-metric name.",
       "", "supermetrics:"]
    OBJ={"HostSystem":"[HostSystem]","ClusterComputeResource":"[ClusterComputeResource]","VirtualMachine":"[VirtualMachine]"}
    last=None
    for k,n,o,u,i,f in rows:
        cc=cls(k)
        if cc!=last: L.append(f"\n  # --- class {cc} ---"); last=cc
        u2=u if u else '""'
        if u2=="7004": u2='"7004"'
        L+= [f'  - key: {k}', f'    name: "{n}"', f'    id: {i}', f'    applies_to: {OBJ[o]}',
             f'    unit: {u2}', f'    formula: "{f}"',
             f'    description: "{sm_description(k,o,u,P)}"']
    fn=f"supermetrics.{P}.yaml"
    open(os.path.join(HERE,fn),"w").write("\n".join(L)+"\n")
    print(f"emitted {fn} ({total} SMs)")

def emit_policy_payload(posture):
    e=posture["envelope"]; pol=posture["policy"]; P=posture["posture"]
    payload={"capacitySettings":{"capacity":{"capacityAllocationSettings":[{
        "capacityAllocation":{"cpu":e["capacity"]["cpu_overcommit"]["target"],
                              "memory":e["capacity"]["mem_overcommit"]["target"],
                              "diskspace":pol["capacity_allocation"]["diskspace"],
                              "poweredOffVmsConsidered":pol["capacity_allocation"]["poweredOffVmsConsidered"]},
        "resourceKindKey":{"resourceKind":"ClusterComputeResource","adapterKind":"VMWARE"}}],
        "customProfileSettings":[],"capacityBufferSettings":[]}}}
    fn=f"policy-capacity-allocation.{P}.json"
    open(os.path.join(HERE,fn),"w").write(__import__("json").dumps(payload,indent=1)+"\n")
    print(f"emitted {fn} (cpu/mem generated from the envelope targets)")

if __name__=="__main__":
    main()
