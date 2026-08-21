#!/usr/bin/env python3
"""The flow lens: discover applications from the east-west flow graph (Phases 4-5, read-only).

Public cloud hands you a named estate. A brownfield private cloud hands you a room of machines and no
map. The flow lens is the one instrument that shows the real east-west dependency graph: it pulls the
flows VCF Operations for Networks already collects, quarantines the shared services (the high-fan-in
DNS/AD/NTP/platform nodes that otherwise make every app look adjacent to every other), then clusters
the remaining VM-to-VM graph into candidate applications and assigns each member a tier from the
ports it serves. Nothing is written: the output is a defensible proposal an admin confirms, and the
hand-off to the supervisor lens's write-back.

  python3 discover_flows.py                       # pull the last 24h, print the findings
  python3 discover_flows.py --hours 168 --export findings.json
  python3 discover_flows.py --self-test           # offline: reproduce the golden from the fixture

Dependencies: Python 3 plus `pydantic`. One plane, from the environment (see lib/_client.py):
  export VRNI_HOST=<vrni-fqdn> VRNI_USERNAME=<user> VRNI_PASSWORD=<password>
  export VRNI_INSECURE=1     # only on a self-signed lab CA
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from lib._boundaries import BoundariesReport, build_boundaries
from lib._shared_services import SharedServicesReport, analyze, project_flows

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"


def run_analysis(raw_flows: list[dict], *, hours: int, min_fan_in: int,
                 min_edge_weight: int) -> tuple[SharedServicesReport, BoundariesReport]:
    """The whole pure pipeline: project -> Phase-4 shared services -> Phase-5 boundaries. No I/O."""
    projected = project_flows(raw_flows)
    shared = analyze(projected, total_flows=len(raw_flows), window_hours=hours, min_fan_in=min_fan_in)
    quarantine = {c.destination for c in shared.quarantine}
    boundaries = build_boundaries(projected, shared_services=quarantine, total_flows=len(raw_flows),
                                  window_hours=hours, min_edge_weight=min_edge_weight)
    return shared, boundaries


def findings_dict(shared: SharedServicesReport, boundaries: BoundariesReport) -> dict:
    return {"shared_services": shared.model_dump(mode="json"),
            "boundaries": boundaries.model_dump(mode="json")}


def render_summary(shared: SharedServicesReport, boundaries: BoundariesReport) -> None:
    print(f"\n  Flow lens: {shared.total_flows} raw flows, {shared.projected_flows} resolved to "
          f"src->dst edges over {shared.window_hours}h; {shared.distinct_sources} sources talking to "
          f"{shared.distinct_destinations} destinations.\n")

    quarantine = shared.quarantine
    review = [c for c in shared.candidates if c.verdict == "review"]
    print(f"  SHARED SERVICES (quarantined before boundary detection): {len(quarantine)}")
    for c in quarantine:
        label = ", ".join(c.well_known) or ", ".join(map(str, c.ports))
        print(f"    {c.destination[:32]:32} fan-in {c.distinct_sources:<4} {label}")
    if review:
        print(f"\n  REVIEW (high fan-in on web ports, a shared service OR a popular front-end): {len(review)}")
        for c in review:
            label = ", ".join(c.well_known) or ", ".join(map(str, c.ports))
            print(f"    {c.destination[:32]:32} fan-in {c.distinct_sources:<4} {label}")

    print(f"\n  APPLICATIONS ({len(boundaries.applications)} candidate boundaries from "
          f"{boundaries.vm_flows} VM-to-VM flows, {boundaries.shared_services_excluded} shared services excluded):")
    for a in boundaries.applications:
        tiers = ", ".join(f"{n} {t}" for t, n in sorted(a.tiers.items()))
        print(f"    {a.app_id[:28]:28} {a.size} VMs ({tiers}), {a.internal_edges} internal edges")
        for m in a.members:
            ports = "/".join(map(str, m.serves_ports)) or "-"
            print(f"        {m.tier:8} {m.vm[:40]:40} serves {ports}")
    if boundaries.singletons:
        print(f"\n  SINGLETONS (no qualifying coupling after exclusions): {len(boundaries.singletons)}")
        print("    " + ", ".join(boundaries.singletons))
    print("\n  Nothing was written. Confirm these candidates, then hand the confident ones to the "
          "supervisor lens's write-back (../writeback_tags.py) or your own tagging.")


def self_test(*, update: bool = False) -> int:
    """Offline: run the pure pipeline on the shipped fixture and compare to the golden findings."""
    fx = json.loads((FIXTURES / "flows.json").read_text())
    shared, boundaries = run_analysis(
        fx["flows"], hours=fx["hours"], min_fan_in=fx["min_fan_in"],
        min_edge_weight=fx.get("min_edge_weight", 1))
    got = findings_dict(shared, boundaries)
    golden = FIXTURES / "expected-findings.json"
    if update:
        golden.write_text(json.dumps(got, indent=2) + "\n")
        print(f"golden updated: {golden}")
        return 0
    expected = json.loads(golden.read_text())
    if got == expected:
        n_ss = len([c for c in got["shared_services"]["candidates"] if c["verdict"] == "shared-service"])
        n_app = len(got["boundaries"]["applications"])
        print(f"self-test OK: the fixture ({len(fx['flows'])} synthetic flows) reproduces the golden "
              f"findings exactly, {n_ss} shared service(s) quarantined and {n_app} application "
              f"boundary(ies) resolved, entirely offline.")
        return 0
    print("self-test FAILED: the analysis output differs from the golden findings.")
    print("  (if the change is intended, re-run with --self-test --update to refresh the golden.)")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description="The flow lens: discover applications from the flow graph")
    ap.add_argument("--hours", type=int, default=24, help="flow window length in hours (default 24)")
    ap.add_argument("--min-fan-in", type=int, default=5,
                    help="distinct-source count that makes a destination a shared-service candidate")
    ap.add_argument("--min-edge-weight", type=int, default=1,
                    help="minimum flow count for a VM-to-VM edge to count toward a boundary")
    ap.add_argument("--max-flows", type=int, default=5000, help="search cap (a hit is reported LOUD)")
    ap.add_argument("--export", type=Path, help="also write the full findings as JSON to this path")
    ap.add_argument("--self-test", action="store_true",
                    help="offline: reproduce the golden findings from the fixture, then exit")
    ap.add_argument("--update", action="store_true", help="with --self-test: refresh the golden")
    args = ap.parse_args()

    if args.self_test:
        return self_test(update=args.update)

    from lib._client import vrni_client
    from lib._collect import collect_flows
    with vrni_client() as client:
        raw = collect_flows(client, hours=args.hours, max_flows=args.max_flows)
    shared, boundaries = run_analysis(
        raw, hours=args.hours, min_fan_in=args.min_fan_in, min_edge_weight=args.min_edge_weight)
    render_summary(shared, boundaries)
    if args.export:
        args.export.write_text(json.dumps(findings_dict(shared, boundaries), indent=2) + "\n")
        print(f"\n  findings written to {args.export}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
