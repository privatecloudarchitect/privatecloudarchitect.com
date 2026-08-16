#!/usr/bin/env python3
"""destroy.py — the SEPARATE, deliberate WTPC teardown (the inverse lifecycle of apply.py).

Teardown is NOT a phase of build. `apply.py` converges the estate and is a no-op once converged, so you
almost never need this — destroy exists for a genuine decommission or a from-scratch rebuild, and it is
kept OFF the build path on purpose (the fragility this whole design removes came from conflating the two).

Cascade-aware, reverse dependency order — the inverse of apply's DAG:
    1. alert definitions        (delete before their symptoms — alerts reference symptoms)
    2. symptom definitions
    3. posture policies         (DELETE /api/policies/{id} — removes the policy from the priority list and
                                 unbinds its groups as a side effect; descendants left unless --delete-descendants)
    4. super metrics            (multi-pass: a SM referenced by another can't delete until its consumer is
                                 gone, so we retry until a pass removes nothing — the DAG unwinds itself)
    5. custom groups
Tags are LEFT INTACT — they are the shop-agnostic membership CONTRACT, not WTPC content, and 9.1 tag
removal is a separate Tag Management action that must DETACH before delete. Remove them there if
you truly mean to.

SAFETY: only objects carrying the WTPC marker are ever touched — name prefix ``PCA - WTPC -`` (policies /
groups / super metrics), ``PCA - WTPC`` (alert + symptom defs). Every target is re-checked against the
marker immediately before the DELETE (belt-and-suspenders — a shop's own object is never in range). Dry-run
by default; ``--execute`` deletes. ``--posture P`` scopes to one posture's policy + groups + ``(P)``-suffixed
super metrics (shared observation SMs + alerts are left for a full teardown). A FULL teardown (no --posture)
under --execute additionally requires ``--yes-full-teardown`` — an explicit acknowledgement for the
irreversible wipe. DELETE endpoints verified against the VCF Operations 9.1 public API specification.

Usage (from anywhere):
  python destroy.py                                         # DRY-RUN: full teardown plan
  python destroy.py --posture test-dev-traditional          # DRY-RUN: scope to one posture
  python destroy.py --posture test-dev-traditional --execute
  python destroy.py --execute --yes-full-teardown           # full wipe (all postures)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from lib._client import ops_client
from lib._groups import list_groups

from lib._alerts import find_existing   # paginated name->id for our namespace (paginates past the page-size cap)

HERE = Path(__file__).resolve().parent
MARK_POLICY = "PCA - WTPC - Policy - "
MARK_GROUP = "PCA - WTPC - Group - "
MARK_SM = "PCA - WTPC -"
MARK_ALERT = "PCA - WTPC"


def _guard(name: str, marker: str) -> None:
    """Refuse to delete anything not carrying the WTPC marker (defence in depth, right before the DELETE)."""
    if not name.startswith(marker):
        raise SystemExit(f"REFUSING to delete {name!r} — missing WTPC marker {marker!r}. This is a bug; aborting.")


def collect(c: VcfOpsClient, posture: str | None) -> dict[str, list[tuple[str, str]]]:
    """Gather WTPC-marked targets as {kind: [(name, id), ...]} in the scope requested."""
    plan: dict[str, list[tuple[str, str]]] = {}

    # policies
    pols = c.get("/api/policies", params={"_no_links": "true", "pageSize": 500}).json()["policySummaries"]
    if posture:
        plan["policies"] = [(p["name"], p["id"]) for p in pols if p["name"] == f"{MARK_POLICY}{posture}"]
    else:
        plan["policies"] = [(p["name"], p["id"]) for p in pols if p["name"].startswith(MARK_POLICY)]

    # super metrics — full id (SuperMetric-<uuid>) for the DELETE
    sms = c.get("/api/supermetrics", params={"pageSize": 2000}).json()["superMetrics"]
    if posture:
        plan["super_metrics"] = [(s["name"], s["id"]) for s in sms
                                 if s["name"].startswith(MARK_SM) and s["name"].rstrip().endswith(f"({posture})")]
    else:
        plan["super_metrics"] = [(s["name"], s["id"]) for s in sms if s["name"].startswith(MARK_SM)]

    # custom groups
    groups = list_groups(c)
    gpref = f"{MARK_GROUP}{posture} " if posture else MARK_GROUP
    plan["groups"] = [(g["resourceKey"]["name"], g["id"]) for g in groups
                      if g.get("resourceKey", {}).get("name", "").startswith(gpref)]

    # alerts + symptoms — only in a FULL teardown (shared/exemplar-scoped; not per-posture)
    if not posture:
        plan["alerts"] = sorted(find_existing(c, "/api/alertdefinitions", "alertDefinitions", MARK_ALERT).items())
        plan["symptoms"] = sorted(find_existing(c, "/api/symptomdefinitions", "symptomDefinitions", MARK_ALERT).items())
        plan["alerts"] = [(n, i) for n, i in plan["alerts"]]
        plan["symptoms"] = [(n, i) for n, i in plan["symptoms"]]
    else:
        plan["alerts"] = []
        plan["symptoms"] = []
    return plan


def delete_simple(c: VcfOpsClient, endpoint: str, items: list[tuple[str, str]], marker: str) -> int:
    fails = 0
    for name, oid in items:
        _guard(name, marker)
        try:
            c.delete(f"{endpoint}/{oid}")
            print(f"    ✓ deleted {name}")
        except Exception as e:   # noqa: BLE001 — report + continue; teardown is re-runnable
            fails += 1
            print(f"    ✗ {name}: {str(e)[:90]}")
    return fails


def delete_supermetrics(c: VcfOpsClient, items: list[tuple[str, str]]) -> int:
    """Multi-pass: a SM referenced by another SM's formula won't delete until its consumer is gone. Retry
    until a pass deletes nothing (the DAG unwinds from consumers down to observations)."""
    remaining = list(items)
    for _pass in range(1, 6):
        progressed = []
        still = []
        for name, sid in remaining:
            _guard(name, MARK_SM)
            try:
                c.delete(f"/api/supermetrics/{sid}")
                progressed.append(name)
            except Exception:   # noqa: BLE001 — likely still-referenced; retry next pass
                still.append((name, sid))
        print(f"    pass {_pass}: deleted {len(progressed)}, {len(still)} remaining")
        remaining = still
        if not remaining or not progressed:
            break
    for name, _ in remaining:
        print(f"    ✗ still-referenced (re-run after its consumers are gone): {name}")
    return len(remaining)


def main() -> int:
    ap = argparse.ArgumentParser(description="Deliberate cascade-aware WTPC teardown (reverse of apply.py)")
    ap.add_argument("--posture", help="scope to one posture's policy + groups + (P)-suffixed super metrics")
    ap.add_argument("--execute", action="store_true", help="perform the deletes (default: dry-run)")
    ap.add_argument("--yes-full-teardown", action="store_true",
                    help="required to --execute a FULL (all-posture) teardown — the irreversible wipe")
    ap.add_argument("--delete-descendants", action="store_true", help="pass deleteDescendants=true on policy delete")
    args = ap.parse_args()

    scope = f"posture={args.posture}" if args.posture else "FULL (all postures)"
    mode = "EXECUTE" if args.execute else "DRY-RUN"
    print(f"WTPC destroy · {mode}  scope={scope}\nReverse-order teardown; tags are left intact.")

    if args.execute and not args.posture and not args.yes_full_teardown:
        print("\n✗ Refusing a FULL --execute teardown without --yes-full-teardown (irreversible). "
              "Add the flag, or scope with --posture.")
        return 1

    with ops_client() as c:
        plan = collect(c, args.posture)

        order = [("alerts", "/api/alertdefinitions", MARK_ALERT),
                 ("symptoms", "/api/symptomdefinitions", MARK_ALERT),
                 ("policies", "/api/policies", MARK_POLICY),
                 ("super_metrics", None, MARK_SM),
                 ("groups", "/api/resources/groups", MARK_GROUP)]

        total = sum(len(plan[k]) for k, _, _ in order)
        print(f"\nteardown plan ({total} WTPC-marked object(s), reverse dependency order):")
        for kind, _ep, _m in order:
            items = plan[kind]
            print(f"  {kind:14} {len(items)}")
            for name, _ in items:
                print(f"       - {name}")

        if not args.execute:
            print(f"\nDry-run. Re-run with --execute"
                  f"{'' if args.posture else ' --yes-full-teardown'} to delete.")
            return 0

        print("\nexecuting teardown:")
        fails = 0
        for kind, ep, marker in order:
            items = plan[kind]
            if not items:
                continue
            print(f"  {kind}:")
            if kind == "super_metrics":
                fails += delete_supermetrics(c, items)
            elif kind == "policies":
                dd = "true" if args.delete_descendants else "false"
                for name, oid in items:
                    _guard(name, marker)
                    try:
                        c.delete(f"/api/policies/{oid}", params={"deleteDescendants": dd})
                        print(f"    ✓ deleted {name}")
                    except Exception as e:   # noqa: BLE001
                        fails += 1
                        print(f"    ✗ {name}: {str(e)[:90]}")
            else:
                fails += delete_simple(c, ep, items, marker)

        print(f"\n{'✓' if fails == 0 else '⚠'} teardown complete — {total - fails}/{total} deleted"
              f"{'' if fails == 0 else f', {fails} failed (re-run; teardown is idempotent)'}.")
        return 0 if fails == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
