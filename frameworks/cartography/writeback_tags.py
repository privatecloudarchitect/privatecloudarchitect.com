#!/usr/bin/env python3
"""Apply approved tag recommendations - the mutating half of the two-phase write-back.

Consumes a recommendations file (classify_supervisor.py --export), an EXPLICIT approval, and
actuates ONLY the approved tags, entirely on the vCenter-native tag plane: projection-proof, and
no Operations access needed.

Provenance is the axis map. Discovery observes; it never declares intent. Every recommendation
category realizes to a discovery-owned category through taxonomy.yaml:

    recommendation  ->  taxonomy concept  ->  live category (your name)
    app                 app                   app
    tier                app-layer             app-layer
    function            function              function
    env                 env-observed          env-observed   (the declared env twin is never written)

Three distinct duties on one vCenter:
  DEFINE  categories and values are minted natively (instant, projection-proof) via the shared
          provider; a same-named category the estate did not create is a conflict, never adopted.
  ASSIGN  the native tag URN attaches through the tag-association plane. Default: the VCENTER_*
          identity; --actuate-as-tag-authority switches the assign to the VCENTER_TAGAUTH_*
          identity (a least-privilege principal that can bind every VM class, including
          Supervisor-managed VMs a plain grant cannot reach).
  VERIFY  the vCenter source of truth is read back after each assign and the run FAILS LOUD if
          the tag did not land: the silent accepted-but-not-applied failure mode becomes
          detectable instead of corrupting the map.

DRY-RUN by default; --execute applies. Change semantics are conservative: a different existing
value holds by default (surfaced, not overwritten); --allow-change permits the change and
detaches the old value first.

Usage (from frameworks/cartography/):
  python3 writeback_tags.py --recommendations recs.json --approve recommended            # dry-run
  python3 writeback_tags.py --recommendations recs.json --approve recommended --execute
  python3 writeback_tags.py --recommendations recs.json --approve-file picks.txt --execute
     (picks.txt: one `vm:category` per line; # comments allowed)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from lib import _taxonomy
from lib._client import VcSession, vcenter_client
from lib._models import DesiredTag, TagAction, reconcile_actions
from lib._tagdefs import CategoryReport, NativeVcenterTagProvider
from lib._tagging import attach_tag, detach_tag

REC_CONCEPT = {"app": "app", "tier": "app-layer", "env": "env-observed", "function": "function"}


def _tag_id_from_urn(urn: str) -> str:
    if urn.startswith("urn:"):
        parts = urn.split(":")
        if len(parts) >= 5:
            return parts[3]
    return urn


class NativeTagPlane:
    """DEFINE + URN resolution on the vCenter-native seam, scoped to the estate's own categories."""

    def __init__(self, vc: VcSession, vc_name: str) -> None:
        self.vc = vc
        self.vc_name = vc_name
        self.cats = _taxonomy.categories()
        self.provider = NativeVcenterTagProvider()
        self._index = self.provider.cat_index(vc)   # read the category index ONCE
        self._cat_id: dict[str, str] = {}
        self._catalog = None

    @property
    def catalog(self):
        if self._catalog is None:
            self._catalog = self.provider.catalog(self.vc, index=self._index,
                                                  only=self.owned_categories())
        return self._catalog

    def owned_categories(self) -> set[str]:
        return {c.get("category", c["concept"]) for c in self.cats.values()}

    def interpret(self, tag_id: str):
        cv = self.catalog.cv_by_uuid.get(tag_id)
        return cv if cv and cv[0] in self.owned_categories() else None

    def existing_urn(self, runtime_category: str, value: str):
        return self.catalog.urn(runtime_category, value)

    def ensure_category(self, concept: str, *, dry_run: bool) -> CategoryReport:
        cat = self.cats[concept]
        name = cat.get("category", concept)
        values = cat["values"] if isinstance(cat.get("values"), list) else []
        rep = self.provider.ensure_category(
            self.vc, self.vc_name, name, cat.get("object", "VirtualMachine"),
            cat.get("cardinality", "SINGLE"), values, self._index, dry_run=dry_run)
        if rep.category_id:
            self._cat_id[name] = rep.category_id
        return rep

    def ensure_value(self, runtime_category: str, value: str):
        cid = self._cat_id.get(runtime_category)
        if cid is None:
            return None
        return self.provider.ensure_value(self.vc, cid, value)


class VcVerifier:
    """SOURCE OF TRUTH: read current tags, verify an assignment landed."""

    def __init__(self, vc: VcSession) -> None:
        self.vc = vc
        self._moref = vc.list_vms()

    def moref(self, vm_name: str):
        return self._moref.get(vm_name)

    def attached_tag_ids(self, moref: str) -> set[str]:
        return {_tag_id_from_urn(u) for u in self.vc.list_attached_tag_urns(moref)}

    def verify_landed(self, moref: str, tag_id: str, *, tries: int = 4, delay: float = 5.0) -> bool:
        for i in range(tries):
            if tag_id in self.attached_tag_ids(moref):
                return True
            if i < tries - 1:
                time.sleep(delay)
        return False


def load_recommendations(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"recommendations file not found: {path} "
                         f"(produce it with classify_supervisor.py --export {path})")
    return json.load(open(path, encoding="utf-8"))


def select_approved(report: dict, approve: str | None, approve_file: Path | None) -> list[dict]:
    recs = report.get("recommendations", [])
    if approve_file is not None:
        picks: set[tuple[str, str]] = set()
        for raw in approve_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            vm, _, cat = line.replace("\t", ":").partition(":")
            if vm and cat:
                picks.add((vm.strip(), cat.strip()))
        return [r for r in recs if (r["vm"], r["category"]) in picks]
    if approve == "all":
        return list(recs)
    if approve == "recommended":
        return [r for r in recs if r["recommended"]]
    raise SystemExit("nothing approved: pass --approve all|recommended or --approve-file <path>")


def render_define(reports: list[CategoryReport]) -> None:
    if not reports:
        return
    print("\n  DEFINE (vCenter-native):")
    for r in reports:
        vals = []
        if r.values_created:
            vals.append(f"+{len(r.values_created)} ({','.join(r.values_created)})")
        if r.values_existing:
            vals.append(f"={len(r.values_existing)}")
        note = f"  ! {r.note}" if r.note else ""
        print(f"    {r.name[:36]:36} {r.category_action:13} {' '.join(vals)}{note}")


def apply(plane: NativeTagPlane, verifier: VcVerifier, approved: list[dict], *,
          execute: bool, allow_change: bool, actuator: VcSession | None = None) -> int:
    concepts_present = sorted({REC_CONCEPT[r["category"]] for r in approved})
    def_reports = [plane.ensure_category(c, dry_run=not execute) for c in concepts_present]
    render_define(def_reports)
    conflicts = [r for r in def_reports if r.category_action == "conflict"]
    if conflicts:
        for r in conflicts:
            print(f"  ! definition conflict on {r.name!r}: {r.note}")
        print("  a same-named category the estate did not create exists; resolve the collision first.")
        return 1

    names = sorted({r["vm"] for r in approved})
    resolvable, skipped = [], []
    for name in names:
        (resolvable if verifier.moref(name) else skipped).append(name)

    current_by_vm: dict[str, dict[str, str]] = {}
    for name in resolvable:
        moref = verifier.moref(name)
        current: dict[str, str] = {}
        for tid in verifier.attached_tag_ids(moref):
            cv = plane.interpret(tid)
            if cv:
                current[cv[0]] = cv[1]
        current_by_vm[name] = current

    cat_name = {c: _taxonomy.category_name(c) for c in REC_CONCEPT.values()}
    desired = [DesiredTag(object_ref=r["vm"], category=cat_name[REC_CONCEPT[r["category"]]],
                          value=r["value"])
               for r in approved if r["vm"] in current_by_vm]
    actions = reconcile_actions(desired, current_by_vm, allow_change=allow_change)

    print(f"\n  {'VM':28} {'CATEGORY':16} {'VALUE':16} {'CURRENT':12} ACTION")
    print(f"  {'-' * 28} {'-' * 16} {'-' * 16} {'-' * 12} {'-' * 26}")
    counts: dict[str, int] = {}
    applied = failed = 0
    for a in sorted(actions, key=lambda x: (not x.writes, x.object_ref, x.category)):
        counts[a.action] = counts.get(a.action, 0) + 1
        note = a.action
        if a.writes and not execute:
            new = "" if plane.existing_urn(a.category, a.value) else " [new tag]"
            note = f"{a.action} (DRY-RUN){new}"
        elif a.writes and execute:
            ok = _actuate(plane, verifier, a, actuator=actuator)
            if ok:
                applied += 1
                note = f"{a.action} APPLIED (verified in vCenter)"
            else:
                failed += 1
                print(f"  {a.object_ref[:28]:28} {a.category[:16]:16} {a.value[:16]:16} "
                      f"{(a.current or '-'):12} {a.action} FAILED verification")
                return _did_not_land(a)
        print(f"  {a.object_ref[:28]:28} {a.category[:16]:16} {a.value[:16]:16} "
              f"{(a.current or '-'):12} {note}")

    for name in skipped:
        print(f"  {name[:28]:28} {'-':16} {'-':16} {'-':12} SKIPPED: not on this vCenter")

    writes = sum(counts.get(k, 0) for k in ("attach", "change"))
    print(f"\n  summary: {len(actions)} decision(s) over {len(resolvable)} resolvable VM(s) "
          f"({len(skipped)} skipped): "
          + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    if not execute and writes:
        via = ("the tag-authority identity" if actuator is not None else "the VCENTER_* identity")
        hint = ("" if actuator is not None else
                "; to land on Supervisor-managed VMs, re-run with --actuate-as-tag-authority")
        print(f"  DRY-RUN: {writes} native tag(s) would be attached via {via}. "
              f"Re-run with --execute{hint}.")
    elif execute and writes:
        print(f"  Applied {applied} native tag(s), each verified against the vCenter source of "
              "truth. Group re-resolution then settles on its own interval (minutes).")
    return 0


def _actuate(plane: NativeTagPlane, verifier: VcVerifier, a: TagAction, *,
             actuator: VcSession | None = None) -> bool:
    urn = plane.ensure_value(a.category, a.value)
    if urn is None:
        return False
    moref = verifier.moref(a.object_ref)
    client = actuator if actuator is not None else plane.vc
    if a.action == "change" and a.current is not None:
        old = plane.existing_urn(a.category, a.current)
        if old:
            detach_tag(client, moref, "VirtualMachine", _tag_id_from_urn(old))
    attach_tag(client, moref, "VirtualMachine", _tag_id_from_urn(urn))
    return verifier.verify_landed(moref, _tag_id_from_urn(urn))


def _did_not_land(a: TagAction) -> int:
    print(f"\n  ACTUATION did not land for {a.object_ref!r} ({a.category}={a.value}): the assign "
          "reported success but the tag never appeared in the vCenter source of truth. The "
          "actuating identity lacks effective tag-assign authority on this VM class (a "
          "Supervisor-managed VM shadows a plain vCenter grant). Re-run with "
          "--actuate-as-tag-authority using a least-privilege identity that holds a global "
          "tag-assign role. No partial state was written that vCenter would show.")
    return 2


def main() -> int:
    ap = argparse.ArgumentParser(description="Apply approved tag recommendations (two-phase write-back)")
    ap.add_argument("--recommendations", required=True, type=Path,
                    help="the ratification queue (classify_supervisor.py --export)")
    ap.add_argument("--approve", choices=["all", "recommended"],
                    help="approve every recommendation, or only the safe-to-approve subset")
    ap.add_argument("--approve-file", type=Path,
                    help="approve an explicit subset: one `vm:category` per line")
    ap.add_argument("--actuate-as-tag-authority", action="store_true",
                    help="assign as the VCENTER_TAGAUTH_* identity (Supervisor-managed VM classes)")
    ap.add_argument("--allow-change", action="store_true",
                    help="permit overwriting a different existing value (default: hold and surface)")
    ap.add_argument("--execute", action="store_true", help="apply (default: dry-run)")
    args = ap.parse_args()

    report = load_recommendations(args.recommendations)
    approved = select_approved(report, args.approve, args.approve_file)
    if not approved:
        print("the approval selected zero recommendations; nothing to do")
        return 0
    mode = "EXECUTE" if args.execute else "DRY-RUN"
    print(f"write-back · {mode} · {len(approved)} approved recommendation(s) "
          f"from {args.recommendations}")

    with vcenter_client() as vc:
        plane = NativeTagPlane(vc, vc_name="vcenter")
        verifier = VcVerifier(vc)
        if args.actuate_as_tag_authority and args.execute:
            with vcenter_client(tag_authority=True) as actuator:
                return apply(plane, verifier, approved, execute=True,
                             allow_change=args.allow_change, actuator=actuator)
        return apply(plane, verifier, approved, execute=args.execute,
                     allow_change=args.allow_change,
                     actuator=None)


if __name__ == "__main__":
    sys.exit(main())
