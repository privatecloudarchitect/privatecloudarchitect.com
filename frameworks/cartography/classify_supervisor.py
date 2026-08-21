#!/usr/bin/env python3
"""Classify Supervisor workloads from their declared labels and export tag recommendations.

The read-only half of the slice. It walks the estate's Supervisor namespaces through the VCF
Automation Consumption Interface, reads each namespace's VirtualMachine objects, classifies every
VM twice from the same labels (the declared identity: app, tier, observed env; and the proposed
function axis), and emits a recommendations file. NOTHING is written and nothing is selected:
the file is the ratification queue, and the separate actuator (writeback_tags.py) consumes it
only with an explicit approval, dry-run first.

Recommendation semantics, deliberately conservative:
  app        declared part-of/name label; high confidence, safe to approve
  tier       the closed layer (presentation/logic/data) derived from the SAME conservative
             component map as function; confident components only
  function   the proposed governance axis; auto-ratifiable proposals (cluster nodes, db/web
             components) are marked recommended, everything else is flagged for review
  env        observed from the namespace name by token match; ALWAYS flagged for confirmation
             (an inference, never auto-approved), and the actuator writes it to the observed
             companion category, never your declared environment axis

Usage (from frameworks/cartography/):
  python3 classify_supervisor.py                          # live: discover namespaces, classify, summarize
  python3 classify_supervisor.py --export recs.json       # also write the ratification queue
  python3 classify_supervisor.py --project <cci-project>  # limit discovery to one project
  python3 classify_supervisor.py --namespace ns=https://<vcfa>/proxy/...   # explicit, repeatable
  python3 classify_supervisor.py --fixture fixtures/supervisor-vms.json --export recs.json  # offline
  python3 classify_supervisor.py --self-test              # offline: fixture in, golden out, compared
"""
from __future__ import annotations

import argparse
import json
import sys

from lib._classify import (
    FUNCTION_LAYER,
    classify_from_labels,
    classify_function,
)

CCI_SUPERVISOR_NS = "/cci/kubernetes/apis/infrastructure.cci.vmware.com/v1alpha2/supervisornamespaces"
VMOP_VERSION = "v1alpha5"
CAT_ORDER = {"app": 0, "tier": 1, "function": 2, "env": 3}
FIXTURE = "fixtures/supervisor-vms.json"
GOLDEN = "fixtures/expected-recommendations.json"


def discover_namespaces(a, project: str | None) -> dict[str, str]:
    """{namespace: cci_proxy_base} for every Created Supervisor namespace, via the CCI."""
    items = (a.get(CCI_SUPERVISOR_NS).json() or {}).get("items", [])
    out: dict[str, str] = {}
    for item in items:
        md, status = item.get("metadata", {}), item.get("status", {})
        name, base, phase = md.get("name"), status.get("namespaceEndpointURL"), status.get("phase")
        if name and base and phase == "Created" and (project is None or md.get("namespace") == project):
            out[name] = base
    return out


def fetch_namespace_vms(a, proxy_base: str, namespace: str) -> list[dict]:
    """The raw VirtualMachine CRD items for one namespace, via its per-namespace proxy."""
    path = f"{proxy_base}/apis/vmoperator.vmware.com/{VMOP_VERSION}/namespaces/{namespace}/virtualmachines"
    return (a.get(path, absolute=True).json() or {}).get("items", [])


def recommendations_for(namespace: str, vms_raw: list[dict]) -> tuple[list[dict], int, int]:
    """(recommendations, tag_ready_vms, held_vms) for one namespace's raw VM items. Pure."""
    recs: list[dict] = []
    ready = held = 0
    for vm in vms_raw:
        md = vm.get("metadata", {})
        name = md.get("name")
        if not isinstance(name, str) or not name:
            continue
        labels = md.get("labels", {}) or {}
        c = classify_from_labels(name, labels, namespace)
        p = classify_function(name, labels)
        vm_recs: list[dict] = []

        def rec(category, value, confidence, recommended, lenses, justification):
            vm_recs.append({
                "vm": name, "namespace": namespace, "category": category, "value": value,
                "confidence": confidence, "recommended": recommended,
                "lenses": list(lenses), "justification": justification,
            })

        if c.app:
            rec("app", c.app, "high", True, ("declared-label",),
                "declared by " + ", ".join(k for k in c.evidence if k.startswith("app.kubernetes.io")))
        if p.source == "component-label" and p.function in FUNCTION_LAYER:
            rec("tier", FUNCTION_LAYER[p.function], p.confidence, p.confidence == "high",
                ("component-label",), f"app.kubernetes.io/component maps to the {FUNCTION_LAYER[p.function]} layer")
        if p.function:
            rec("function", p.function, p.confidence, p.auto_ratifiable, (p.source,),
                p.note or "declared component maps unambiguously")
        if c.env != "unknown":
            rec("env", c.env, "medium", False, ("namespace-token",),
                f"namespace {namespace!r} carries the {c.env!r} token; confirm before writing the observed fact")
        if vm_recs:
            ready += 1
            recs.extend(vm_recs)
        else:
            held += 1
    return recs, ready, held


def build_report(sources: dict[str, list[dict]]) -> dict:
    """The full recommendations report over {namespace: raw VM items}. Pure and deterministic."""
    recs: list[dict] = []
    total = ready = held = 0
    for namespace in sorted(sources):
        vms = sources[namespace]
        total += sum(1 for v in vms if isinstance(v.get("metadata", {}).get("name"), str))
        r, a, h = recommendations_for(namespace, vms)
        recs.extend(r)
        ready += a
        held += h
    recs.sort(key=lambda r: (not r["recommended"], r["vm"], CAT_ORDER[r["category"]]))
    dist: dict[str, int] = {}
    for r in recs:
        dist[r["category"]] = dist.get(r["category"], 0) + 1
    return {
        "source": "supervisor-lens",
        "namespaces": len(sources),
        "total_vms": total,
        "tag_ready_vms": ready,
        "held_for_review": held,
        "recommended_count": sum(1 for r in recs if r["recommended"]),
        "confirm_count": sum(1 for r in recs if not r["recommended"]),
        "category_distribution": dict(sorted(dist.items())),
        "recommendations": recs,
    }


def render(report: dict) -> None:
    print(f"supervisor lens · {report['namespaces']} namespace(s), {report['total_vms']} VM(s): "
          f"{report['tag_ready_vms']} tag-ready, {report['held_for_review']} held (no signal)")
    print(f"  recommendations: {report['recommended_count']} safe to approve, "
          f"{report['confirm_count']} flagged for confirmation  {report['category_distribution']}")
    print(f"\n  {'VM':28} {'NS':22} {'CATEGORY':9} {'VALUE':14} {'CONF':7} {'FLAG':8} JUSTIFICATION")
    print(f"  {'-' * 28} {'-' * 22} {'-' * 9} {'-' * 14} {'-' * 7} {'-' * 8} {'-' * 30}")
    for r in report["recommendations"]:
        flag = "approve" if r["recommended"] else "confirm"
        print(f"  {r['vm'][:28]:28} {r['namespace'][:22]:22} {r['category']:9} {r['value'][:14]:14} "
              f"{r['confidence']:7} {flag:8} {r['justification'][:56]}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Classify Supervisor workloads; export the ratification queue")
    ap.add_argument("--project", help="limit CCI namespace discovery to one project")
    ap.add_argument("--namespace", action="append", metavar="NS=PROXY_BASE",
                    help="explicit namespace + its CCI proxy base (repeatable; skips discovery)")
    ap.add_argument("--fixture", help="classify a recorded fixture file instead of the live estate")
    ap.add_argument("--export", help="write the recommendations JSON (the ratification queue)")
    ap.add_argument("--self-test", action="store_true",
                    help="offline: classify the shipped fixture and compare against the golden output")
    args = ap.parse_args()

    if args.self_test:
        sources = json.load(open(FIXTURE, encoding="utf-8"))
        report = build_report(sources)
        golden = json.load(open(GOLDEN, encoding="utf-8"))
        if report != golden:
            print("self-test FAILED: the classifier no longer reproduces the golden recommendations")
            return 1
        print(f"self-test OK: {report['total_vms']} fixture VMs reproduce the golden recommendations "
              f"({report['recommended_count']} approve / {report['confirm_count']} confirm)")
        return 0

    if args.fixture:
        sources = json.load(open(args.fixture, encoding="utf-8"))
    else:
        from lib._client import vcfa_client
        with vcfa_client() as a:
            if args.namespace:
                ns_map: dict[str, str] = {}
                for spec in args.namespace:
                    ns, _, base = spec.partition("=")
                    if ns and base:
                        ns_map[ns.strip()] = base.strip()
            else:
                ns_map = discover_namespaces(a, args.project)
                if not ns_map:
                    print("no Created Supervisor namespaces discovered (check the org, or pass --namespace)")
                    return 1
            sources = {}
            for ns, base in ns_map.items():
                try:
                    sources[ns] = fetch_namespace_vms(a, base, ns)
                except Exception as exc:  # a namespace that cannot be read is skipped, never fatal
                    print(f"  skipping namespace {ns!r}: {str(exc)[:120]}")

    report = build_report(sources)
    render(report)
    if args.export:
        with open(args.export, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=1)
            f.write("\n")
        print(f"\nexported {args.export} - review it, then apply the approved subset with "
              f"writeback_tags.py --recommendations {args.export} --approve recommended (dry-run first)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
