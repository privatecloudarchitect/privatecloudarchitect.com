"""The day1-provisioning adapter: self-service-provisioning, read from two content-libraries records, since day1.json
holds no declared state (it collects publishToCatalog without writing it, and --lookup writes no record; f8's queue makes
day1.py judge its own declaration). f8's rules R1 to R6 apply (adapters/__init__.py). Each declaration is matched by what
it declares, so the adapter reads the register before and after 64 adds the pins-and-locks declaration (step 5):

- The catalog (VCF Automation): one line, scope `organization`. Every released blueprint version that pins an image is
  declared, and one whose pin resolves nowhere, or names a display name more than one image carries, is drifted (the
  sweep's `unrelease_dead_pins.py --record`, read-only). The sweep judges against the cluster-scoped images and does not
  read a namespace's own library, which the check text says.
- The repository's image pins and their locks per namespace (the repository): one line, scope `organization` (the
  namespaces the organization's account can see), read from `libraries.py --pins --lock`. The rules are content-libraries'
  own (1b, its lane): each namespace is an item, its placeholder naming it and keying no line (R6). A namespace is in
  sync when every pin resolves to one image, by id or by name, and every lock reads HELD; drifted when a pin resolves
  nowhere or to several images, or a lock reads RE-QUALIFY, AMBIGUOUS or UNRESOLVED (the image under the pin is not the
  one qualified, or there is none); check_failed when its endpoint did not answer the image lists, or a lock reads NOT
  CHECKED (the fingerprint was not read). A run given no `--pins` or no `--lock` did not reach that part: it is named
  not read and leaves the line's state (f8's reach rule).
- Any other declaration is not covered: no rule of this adapter reads it (R4).

The mode is `detected`; neither record stores a platform evaluation time or an exit code.
"""

from __future__ import annotations

from ..drift import line
from ..drift import unread as unread_line
from ..models import Register
from ..policy import Loaded
from . import utc, worst

COMPANION = "handbook/day1-provisioning"
CHECK = (
    "content-libraries' catalog sweep: each released version's image pin against the images "
    "(unrelease_dead_pins.py --record)"
)


DRIFTED_LOCKS = ("RE-QUALIFY", "AMBIGUOUS", "UNRESOLVED")
CHECK_LOCKS = "each namespace's image pins and image locks against the images it can name (libraries.py --pins --lock)"


def _part(records: dict[str, dict], name: str) -> tuple[str, dict]:
    return next((p, r) for p, r in records.items() if p.endswith(name))


def _catalog(rec: dict) -> tuple[str, int, list[dict], list[str]]:
    released, judged = rec.get("releasedVersionsRead"), rec.get("pinsJudged") or {}
    dead = rec.get("pinningARemovedImage") or []
    unread = [f"namespace libraries ({rec.get('judgedAgainst', 'not stated')})"]
    if not isinstance(released, int) or "versionsWithNoPin" not in judged:
        return "check_failed", 0, [], [*unread, "the sweep's counts are missing"]
    declared = released - judged["versionsWithNoPin"]
    items = [
        {
            "declared": "an image pin that resolves to one image",
            "actual": d.get("why"),
            "resolution": "open",
        }
        for d in dead
    ]
    if not declared:
        return "check_failed", 0, items, [*unread, "no released version pins an image"]
    return (
        worst(["drifted"] * len(items) + ["in_sync"] * (declared - len(items))),
        declared,
        items,
        unread,
    )


def _locks(rec: dict) -> tuple[str, int, list[dict], list[str]]:
    rows = rec.get("namespaces") or []
    if not rows:
        return "check_failed", 0, [], ["no namespace was listed, which a failed listing also gives"]
    results, items, unread = [], [], []
    if not any("pins" in n for n in rows):
        unread.append("the image pins (the run was given no --pins)")
    if not any("locks" in n for n in rows):
        unread.append("the image locks (the run was given no --lock)")
    for n in rows:
        name = n.get("name")
        if n.get("unread"):
            results.append("check_failed")
            unread.append(f"{name} ({n['unread']})")
            continue
        pins = n.get("pins") or []
        locks = n.get("locks") or []
        loose = [p for p in pins if p.get("resolves") not in ("id", "name")]
        moved = [lk for lk in locks if lk.get("verdict") in DRIFTED_LOCKS]
        unchecked = [lk for lk in locks if lk.get("verdict") == "NOT CHECKED"]
        if loose or moved:
            results.append("drifted")
            items.append(
                {
                    "declared": {
                        "namespace": name,
                        "pins": "each resolves to one image",
                        "locks": "HELD",
                    },
                    "actual": {
                        "namespace": name,
                        "pins resolving nowhere or to several": len(loose),
                        "locks": sorted({lk["verdict"] for lk in moved}),
                    },
                    "resolution": "open",
                }
            )
        elif unchecked:
            results.append("check_failed")
            unread.append(
                f"{name}'s {len(unchecked)} lock(s) not checked (the fingerprint was not read)"
            )
        else:
            results.append("in_sync")
    return worst(results), len(rows), items, unread


def lines(records: dict[str, dict], pol: Loaded, register: Register, capability: str) -> list[dict]:
    sweep_path, sweep = _part(records, ".catalog-pin-read.json")
    libs_path, libs = _part(records, ".libraries.json")
    out = []
    for decl in next(c for c in register.capabilities if c.id == capability).declarations:
        obj = decl.object.lower()
        if decl.system == "repo" and "image pins and their locks" in obj:
            result, declared, items, unread = _locks(libs)
            path, read_at, store, check = (
                libs_path,
                libs["capturedUtc"],
                "the repository",
                CHECK_LOCKS,
            )
        elif decl.system == "vcf-automation" and "catalog" in obj:
            result, declared, items, unread = _catalog(sweep)
            path, read_at, store, check = sweep_path, sweep["captured"], "VCF Automation", CHECK
        else:
            out.append(
                unread_line(
                    capability=capability,
                    declaration=decl,
                    scope="organization",
                    read_at=utc(sweep["captured"]),
                    companion=COMPANION,
                    check="not read: no rule of the day1-provisioning adapter reads this declaration",
                    record=sweep_path,
                    exit=None,
                    pol=pol,
                )
            )
            continue
        out.append(
            line(
                capability=capability,
                declaration=decl,
                store=store,
                declared_version=None,
                scope="organization",
                mode="detected",
                result=result,
                items_declared=declared,
                items_drifted=len(items),
                items=items,
                read_at=utc(read_at),
                checked_at=None,
                companion=COMPANION,
                check=check + (f"; not read: {'; '.join(unread)}" if unread else ""),
                record=path,
                exit=None,
                pol=pol,
            )
        )
    return out
