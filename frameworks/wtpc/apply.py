#!/usr/bin/env python3
"""apply.py - the single level-triggered entry point for the WTPC starter estate.

One command that converges the estate to desired state from ANY starting point - a clean
Operations instance, a partially-built one, or one whose bindings a redo orphaned. It does NOT
tear anything down; it sequences the already-idempotent generators and reconcilers in dependency
order, each of which adopts-or-creates by a stable NAME key. Re-running is a no-op once converged.
Teardown is the SEPARATE, deliberate `destroy.py` - never a phase here.

Dependency DAG - the workload-posture unit, in order:
  0. tag taxonomy    ensure_tag_definitions.py  - the categories every group rule depends on
  1. shared SMs      adopt_shared.py            - the shared + lens super metrics posture content references
  per posture P:
  2. tags+groups     instantiate_posture.py     - the membership contract the rest binds to
  3. policy          reconcile_policy.py        - adopt-or-create the posture policy (needs the groups)
  4. super metrics   build.py                   - create the SM DAG AND activate it in the policy
  5. infra groups    reconcile_infra_groups.py  - derive Host/Cluster membership from VM placement
  then, globally:
  6. capacity        apply_policy_capacity.py   - PATCH each policy's allocation from the committed payload
  7. posture alerts  build_alerts.py + deploy_alerts.py - build the definitions offline, POST them,
                                                  and enable in the posture policy ONLY
  then read-only VERIFY (always; aggregates a non-zero rc if any gate fails):
  8. governance --priority-parity / --config-parity ; validate_live --parity per posture

Workload VM tagging is deliberately NOT a phase here: tagging carries your estate's own change
process, and membership follows tagging on the group re-resolution interval. Views, dashboards,
and view bundles are OFFLINE generators (build_views.py, build_dashboard.py,
build_view_bundles.py) - run them after a posture's SMs exist, then import through the UI.

Dry-run by default (every sub-step previews). --execute applies. --create permits the ONE
bootstrap act (cloning a new posture policy from Default) - without it, apply CONVERGES the live
set and never spawns an undeclared policy.

Usage (from anywhere; paths resolve against the estate dir):
  python apply.py                                          # DRY-RUN converge the exemplar postures
  python apply.py --execute                                # apply the convergence
  python apply.py test-dev-traditional --execute           # scope to one posture
  python apply.py test-dev-traditional --create --execute  # bootstrap it on a fresh instance
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY = sys.executable
# The starter's documented exemplar pair (the strict posture and its best-effort inverse).
DEFAULT_POSTURES = ["prod-latency-critical-db", "test-dev-traditional"]


def run(label: str, script: str, argv: list[str], *, verify: bool = False) -> int:
    """Run one sub-step as a subprocess (cwd=estate dir so `postures/...` + record files resolve)."""
    kind = "verify" if verify else "step"
    print(f"\n{'=' * 78}\n> {kind}: {label}   ({script} {' '.join(argv)})\n{'=' * 78}")
    proc = subprocess.run([PY, str(HERE / script), *argv], cwd=HERE)
    if proc.returncode != 0:
        print(f"x {label} exited {proc.returncode}")
    return proc.returncode


# build.py / adopt_shared.py are execute-by-DEFAULT (--dry-run to preview); the rest are
# dry-run-by-default (--execute to apply). `_inv` handles the inverted convention.
def _inv(execute):
    return [] if execute else ["--dry-run"]


def main() -> int:
    ap = argparse.ArgumentParser(description="Level-triggered WTPC estate reconcile (converge; never teardown)")
    ap.add_argument("postures", nargs="*", default=[], help=f"posture names (default: {DEFAULT_POSTURES})")
    ap.add_argument("--execute", action="store_true", help="apply mutations (default: dry-run over every step)")
    ap.add_argument("--create", action="store_true",
                    help="permit CREATE of a new posture policy (bootstrap a fresh instance); off by default")
    ap.add_argument("--keep-going", action="store_true", help="do not fail-fast on a mutation step")
    ap.add_argument("--skip-verify", action="store_true", help="skip the read-only parity gates")
    args = ap.parse_args()

    postures = args.postures or DEFAULT_POSTURES
    ex = ["--execute"] if args.execute else []
    mode = "EXECUTE" if args.execute else "DRY-RUN"
    print(f"WTPC apply · {mode}  postures={postures}  create={args.create}")
    print("level-triggered converge - no teardown (that is destroy.py). Each step is idempotent.")

    plan: list[tuple[str, str, list[str]]] = []
    plan.append(("tag taxonomy (native define)", "ensure_tag_definitions.py", ex))
    plan.append(("shared + lens super metrics", "adopt_shared.py", _inv(args.execute)))
    for P in postures:
        plan += [
            (f"tags+groups [{P}]", "instantiate_posture.py", [f"postures/{P}.yaml", *ex]),
            (f"policy [{P}]", "reconcile_policy.py",
             ["--posture", P, *(["--create", P] if args.create else []), *ex]),
            (f"super-metrics [{P}]", "build.py", [f"postures/{P}.yaml", *_inv(args.execute)]),
            (f"infra-groups [{P}]", "reconcile_infra_groups.py", ["--posture", P, *ex]),
        ]
    plan += [
        ("capacity (all postures)", "apply_policy_capacity.py", ex),
        # offline emitter: alerts.yaml + the exemplar SM record -> content/wtpc-alerts.*.json
        ("alert definitions (offline build)", "build_alerts.py", []),
        ("posture alerts", "deploy_alerts.py", ex),
    ]

    # Fail-fast policy: only in --execute (a nonzero mutation step is a real failure to stop on). In
    # DRY-RUN a nonzero is informational - "changes pending", an empty-group refusal, parity drift -
    # so preview EVERY step and summarize; never stop early.
    pending: list[tuple[str, int]] = []
    for label, script, argv in plan:
        rc = run(label, script, argv)
        if rc != 0:
            pending.append((label, rc))
            if args.execute and not args.keep_going:
                print(f"\nx apply STOPPED at '{label}' (rc={rc}). Fix + re-run (idempotent), or pass --keep-going.")
                return rc
    if pending and not args.execute:
        print("\n(dry-run) steps signaling a non-zero preview (changes pending / drift / empty-group refusal):")
        for label, rc in pending:
            print(f"    - {label}  (rc={rc})")

    if args.skip_verify:
        print("\n(verify skipped)")
        return 0

    print(f"\n{'-' * 78}\nVERIFY (read-only parity gates)\n{'-' * 78}")
    failed: list[str] = []
    for label, script, argv in [
        ("priority-parity", "governance.py", ["--priority-parity"]),
        ("config-parity", "governance.py", ["--config-parity"]),
        *[(f"effective-policy parity [{P}]", "validate_live.py", ["--posture", P, "--parity"])
          for P in postures],
    ]:
        if run(label, script, argv, verify=True) != 0:
            failed.append(label)

    print(f"\n{'=' * 78}")
    if not failed:
        print(f"OK WTPC apply · {mode} complete - estate converged, all parity gates green.")
        return 0
    # The gates are read-only + idempotent; the Operations API can 500 intermittently on the
    # policy/group read path, so a nonzero gate is EITHER a transient read-flake OR real drift.
    # Re-run the named gate to disambiguate (a transient clears; real drift persists).
    print(f"! WTPC apply · {mode} - parity gate(s) returned non-zero: {failed}")
    print("   Read-only + idempotent -> re-run the named gate to tell a transient 500 from real drift.")
    return 2


if __name__ == "__main__":
    sys.exit(main())
