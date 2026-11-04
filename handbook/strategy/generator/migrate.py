"""The migration harness (charter section 5.12, the schema change class; 30-GATES.md step 2).

A schema change is made expand, then contract: the new form is added beside the old, every file migrates, and the old
form leaves in the next schema version with a migration of its own. Each migration here is a pure function from one
schema version of one kind of file to the next, registered by the kind and the version it starts from. `upgrade` runs
them in order, so a file one or more versions behind loads as the current version and is told how far behind it was;
nothing is written back to the file, which stays its writer's.

Schema 2 types what schema 1 left as text where a gate judges it. In the register and a portfolio:
  * an `evidence` item that cites an external source becomes a citation, `{cite, fetched, version, quote}` (GATE-6,
    BLOCK-010); a reference within the repository stays a string;
  * a portfolio's exception becomes `{id, part, reason, decided_by, granted, renewals, kind, source}` (GATE-13), its
    expiry derived from `policy.yaml`, never typed.
In schema 2 an evidence string may still hold a URL, which GATE-6 refuses with its line; schema 3 removes that form.
In `policy.yaml`, a method's `golden` becomes `{holds, test}`: what its golden fixture holds, and the test that holds
it, which GATE-14 finds on disk. The migration cannot know the test, so it writes none and GATE-14 names the gap.

Schema 3 (40-BREADTH.md step 2) types the rest of what schema 2 left as text, and adds what the served projection
needs. In the register and a portfolio:
  * an `evidence` item that is still a string becomes `{ref}`, a reference within the repository or the assessment's
    own reasoning; one that holds a URL is refused, since only a person can say when it was fetched and its version;
  * a value id `RENAMED` names moves to its successor everywhere a file writes it, and the register keeps the old id as
    a tombstone in its capability's `retired_values`, so a file that still names it resolves for one schema version.
In a portfolio:
  * the role history, the decision log, each capability's readings and each initiative's planning assessments gain an
    `id`, the key an approval addresses them by, derived from what each holds (`_keyed`), never typed;
  * `scans` and `approvals` are added, empty: the migration adds no approval to any file.
A typed form schema 3 adds beside a plain one (an untaught entry, an unconverted measure, a name, a lane and message on
an untaught hand-off, a drift read not covered) needs no migration: the plain form is still read.

A node-level migration (`NODE_MIGRATIONS`) carries a recorded approval's node forward to the current schema in memory,
so a node approved under one schema is compared with today's under another; a stored approval is never rewritten.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Callable
from typing import Any

from .models import SCHEMA_VERSIONS


class MigrationError(ValueError):
    """A file that cannot be carried to the next schema version without a person's decision."""


MIGRATIONS: dict[tuple[str, int], Callable[[dict], dict]] = {}


def migration(kind: str, start: int):
    def register(fn: Callable[[dict], dict]) -> Callable[[dict], dict]:
        if (kind, start) in MIGRATIONS:
            raise ValueError(f"two migrations of {kind} from schema {start}")
        MIGRATIONS[(kind, start)] = fn
        return fn

    return register


def upgrade(kind: str, doc: dict) -> tuple[dict, list[str]]:
    """The document at the current schema version of its kind, and a note per migration run on the way."""
    current = SCHEMA_VERSIONS[kind]
    version = doc.get("schema")
    if not isinstance(version, int) or version > current:
        raise MigrationError(
            f"{kind}: schema {version!r} is not a version this code reads (current {current})"
        )
    notes = []
    while version < current:
        step = MIGRATIONS.get((kind, version))
        if step is None:
            raise MigrationError(f"{kind}: no migration from schema {version}")
        doc = step(copy.deepcopy(doc))
        if doc.get("schema") != version + 1:
            raise MigrationError(
                f"{kind}: the migration from schema {version} did not reach {version + 1}"
            )
        notes.append(f"{kind}: read at schema {version}, migrated to {version + 1}")
        version += 1
    return doc, notes


# ── schema 1 to 2 ───────────────────────────────────────────────────────────────────────────────────────────────────
CITED = re.compile(r"^(?P<cite>https?://\S+)\s+\((?P<rest>.*)\)\s*$", re.DOTALL)
FETCHED = re.compile(
    r"^(?:(?P<label>.*?),\s*)?fetched (?P<date>\d{4}-\d{2}-\d{2})(?::\s*(?P<said>.*))?$", re.DOTALL
)
DATED = re.compile(
    r"\b(version|revision|published|issued|publication date|updated|dated|released)\b",
    re.IGNORECASE,
)


def citation(item: Any) -> Any:
    """A schema 1 evidence string that cites a URL as `URL (..., fetched YYYY-MM-DD: what it said)`, as a citation.
    Its version is the first clause of what it said that names a version or a date. Anything else is returned as it
    is: a reference within the repository is a string by design, and a URL in another form stays a string for GATE-6
    to name."""
    if not isinstance(item, str):
        return item
    m = CITED.match(item)
    if not m:
        return item
    f = FETCHED.match(m["rest"])
    if not f:
        return {"cite": m["cite"], "fetched": None, "version": None, "quote": m["rest"]}
    said = f["said"]
    version = next((seg.strip() for seg in (said or "").split(";") if DATED.search(seg)), None)
    quote = f"{f['label']}: {said}" if f["label"] and said else (said or f["label"])
    return {"cite": m["cite"], "fetched": f["date"], "version": version, "quote": quote}


WAIVER = ("id", "part", "reason", "decided_by", "granted", "kind")


@migration("register", 1)
def register_1_to_2(doc: dict) -> dict:
    for d in doc.get("initiatives") or []:
        for g in d.get("guidance") or []:
            g["evidence"] = [citation(x) for x in g.get("evidence") or []]
    doc["schema"] = 2
    return doc


@migration("portfolio", 1)
def portfolio_1_to_2(doc: dict) -> dict:
    for d in doc.get("initiatives") or []:
        for a in d.get("planning") or []:
            a["evidence"] = [citation(x) for x in a.get("evidence") or []]
    for c in doc.get("capabilities") or []:
        waivers = []
        for i, x in enumerate(c.get("exceptions") or []):
            missing = [k for k in WAIVER if not (isinstance(x, dict) and x.get(k))]
            if missing:
                raise MigrationError(
                    f"portfolio: {c.get('id')}'s exception {i} has no {', '.join(missing)}; schema 2 needs each, "
                    "and only the estate can supply them"
                )
            waivers.append({**x, "renewals": x.get("renewals", 0)})
        c["exceptions"] = waivers
    doc["schema"] = 2
    return doc


@migration("policy", 1)
def policy_1_to_2(doc: dict) -> dict:
    for m in doc.get("methods") or []:
        if isinstance(m.get("golden"), str):
            m["golden"] = {"holds": m["golden"], "test": None}
    doc["schema"] = 2
    return doc


# ── schema 2 to 3 ───────────────────────────────────────────────────────────────────────────────────────────────────
# A value id that named what its value no longer measures, its successor, the day it moved and the ruling that applied
# charter section 5.12's stable-identifier rule (D4-13). Read by both migrations, and by the node migrations.
RENAMED = {
    "remediation-intervention-share": {
        "id": "failed-host-remediation-share",
        "on": "2026-10-30",
        "decided_by": ["D4-13"],
    },
}


def _new_id(value_id: Any) -> Any:
    return RENAMED[value_id]["id"] if value_id in RENAMED else value_id


def _ref(item: Any) -> Any:
    """A schema 2 evidence string as schema 3 types it: `{ref}`, or a citation as it was. A URL in a string is refused:
    only the estate can say when it was fetched and its version (GATE-6, BLOCK-010)."""
    if isinstance(item, str):
        if URL_IN_TEXT.search(item):
            raise MigrationError(
                f"the evidence {item[:80]!r} cites a URL as text; schema 3 needs it as a citation with the day it was "
                "fetched and its version, which only a person can supply"
            )
        return {"ref": item}
    return item


URL_IN_TEXT = re.compile(r"https?://", re.IGNORECASE)


def _keyed(items: list, key) -> None:
    """Give each item an `id` derived from what it holds, `-2`, `-3` appended for a second and third on one key, in list
    order; an item that has one keeps it."""
    seen: dict[str, int] = {}
    for x in items:
        if not isinstance(x, dict) or x.get("id"):
            continue
        base = key(x)
        seen[base] = seen.get(base, 0) + 1
        x["id"] = base if seen[base] == 1 else f"{base}-{seen[base]}"


@migration("register", 2)
def register_2_to_3(doc: dict) -> dict:
    for d in doc.get("initiatives") or []:
        for g in d.get("guidance") or []:
            g["evidence"] = [_ref(x) for x in g.get("evidence") or []]
        d["cost_of_delay_through"] = _new_id(d.get("cost_of_delay_through"))
    for c in doc.get("capabilities") or []:
        retired = list(c.get("retired_values") or [])
        for v in c.get("value") or []:
            v["paired_with"] = _new_id(v.get("paired_with"))
            if v.get("id") in RENAMED:
                old = v["id"]
                v["id"] = RENAMED[old]["id"]
                retired.append({"id": old, "superseded_by": dict(RENAMED[old])})
        if retired:
            c["retired_values"] = retired
    doc["schema"] = 3
    return doc


def _capabilities_3_to_4(capabilities: list, initiatives: list) -> None:
    """The capability's contraction at schema 4, for the register's capabilities and a portfolio's own: an untaught
    entry written as plain text is refused, since no migration can supply the lane it was sent to or the message on
    record; the retired-value tombstone is dropped after every value id the file writes (`paired_with`,
    `cost_of_delay_through`) is moved through `RENAMED`, and an id that then names no live value is refused, never
    left to fail at a page. The `practice` key is new, and absent stays absent."""
    for d in initiatives:
        d["cost_of_delay_through"] = _new_id(d.get("cost_of_delay_through"))
    live = {v.get("id") for c in capabilities for v in c.get("value") or []}
    for c in capabilities:
        for u in c.get("untaught") or []:
            if isinstance(u, str):
                raise MigrationError(
                    f"{c.get('id')}'s untaught entry {u[:80]!r} is plain text; schema 4 needs its territory, the lane it "
                    "was sent to and the message on record, which only a person can supply"
                )
        for v in c.get("value") or []:
            v["paired_with"] = _new_id(v.get("paired_with"))
            if v["paired_with"] is not None and v["paired_with"] not in live:
                raise MigrationError(
                    f"{c.get('id')}'s value {v.get('id')} is paired with {v['paired_with']!r}, which names no live value "
                    "once the tombstone leaves; name the successor"
                )
        c.pop("retired_values", None)
    for d in initiatives:
        through = d.get("cost_of_delay_through")
        if through is not None and through not in live:
            raise MigrationError(
                f"{d.get('id')}'s cost_of_delay_through {through!r} names no live value once the tombstone leaves; "
                "name the successor"
            )


@migration("register", 3)
def register_3_to_4(doc: dict) -> dict:
    """Schema 4 (40-BREADTH.md step 4, the first practice batch; charter section 5.12, expand then contract): the
    `practice` key is new; the two forms schema 3 read for one version leave (`_capabilities_3_to_4`)."""
    _capabilities_3_to_4(doc.get("capabilities") or [], doc.get("initiatives") or [])
    doc["schema"] = 4
    return doc


UNTYPED_UNCONVERTED = "schema 3 wrote the measure's id alone; the kind of the decision to show it beside the rank was not recorded"


@migration("portfolio", 3)
def portfolio_3_to_4(doc: dict) -> dict:
    """Schema 4 of a portfolio, taken with the register's (its estate-local capabilities are the register's model):
    the capability contraction over `local_capabilities` and `local_initiatives`, and the plain `unconverted` id, read
    for one version beside the typed item, typed as the item whose decision's kind was not recorded (three states,
    never an invented one, P-027). The reference portfolio's own item is typed by hand with the kind D4-14 approved
    it under, which the served projection shows in the recorded form until the typed form is approved."""
    _capabilities_3_to_4(doc.get("local_capabilities") or [], doc.get("local_initiatives") or [])
    # every value id the portfolio writes moves through RENAMED, since schema 3 still resolved the retired id
    for c in doc.get("capabilities") or []:
        c["targets"] = {_new_id(k): v for k, v in (c.get("targets") or {}).items()}
        for r in c.get("readings") or []:
            r["value"] = _new_id(r.get("value"))
    for r in doc.get("conversion_rates") or []:
        r["measure"] = _new_id(r.get("measure"))
    doc["unconverted"] = [
        {"measure": _new_id(x), "kind": "not_recorded", "note": UNTYPED_UNCONVERTED}
        if isinstance(x, str)
        else {**x, "measure": _new_id(x.get("measure"))}
        for x in doc.get("unconverted") or []
    ]
    doc["schema"] = 4
    return doc


@migration("register", 4)
def register_4_to_5(doc: dict) -> dict:
    """Schema 5 (40-BREADTH.md step 5): a scan area's `searched`, a scan's `note` and a portfolio capability's
    `parameters` are new and optional, so a schema-4 file reads unchanged and the version alone moves (the expand
    step; charter section 5.12)."""
    doc["schema"] = 5
    return doc


@migration("portfolio", 4)
def portfolio_4_to_5(doc: dict) -> dict:
    """Schema 5 of a portfolio, taken with the register's (it embeds `Scan` and gains `parameters`): the version alone
    moves."""
    doc["schema"] = 5
    return doc


@migration("portfolio", 2)
def portfolio_2_to_3(doc: dict) -> dict:
    for d in doc.get("initiatives") or []:
        for a in d.get("planning") or []:
            a["evidence"] = [_ref(x) for x in a.get("evidence") or []]
        _keyed(d.get("planning") or [], lambda a: f"assessed-{a.get('assessed')}")
    for c in doc.get("capabilities") or []:
        c["targets"] = {_new_id(k): v for k, v in (c.get("targets") or {}).items()}
        for r in c.get("readings") or []:
            r["value"] = _new_id(r.get("value"))
        _keyed(c.get("readings") or [], lambda r: f"{r.get('value')}-{str(r.get('read_at'))[:10]}")
    for r in doc.get("conversion_rates") or []:
        r["measure"] = _new_id(r.get("measure"))
    doc["unconverted"] = [
        _new_id(x) if isinstance(x, str) else dict(x, measure=_new_id(x.get("measure")))
        for x in doc.get("unconverted") or []
    ]
    _keyed(doc.get("decision_log") or [], lambda e: f"decided-{e.get('date')}")
    _keyed(
        doc.get("role_history") or [],
        lambda h: f"{h.get('role')}-{h.get('scope')}-from-{h.get('from') or 'unrecorded'}",
    )
    doc.setdefault("scans", [])
    doc.setdefault("approvals", [])
    doc["schema"] = 3
    return doc


@migration("catalog_map", 1)
def catalog_map_1_to_2(doc: dict) -> dict:
    """Schema 2 adds an untaught placement's `territory` and `message` (40-BREADTH.md step 3). No file was written at
    schema 1 (the model shipped with step 2a, the file lands in step 3), so there is nothing to carry; the version
    moves so the lock's pin of schema 1 is never edited (GATE-14, clause 14.7)."""
    doc["schema"] = 2
    return doc


# ── node migrations: a recorded approval's node carried forward in memory (40-BREADTH.md step 2) ──────────────────────
# Keyed by (shape, the schema it starts from); each takes (address, form) and returns the (address, form) pairs it
# becomes: it may retype a field, move the address or split one node into several (a child that gains a kind takes
# its parent's recorded kind), and adds no other field. A stored approval is never rewritten.
NODE_MIGRATIONS: dict[tuple[str, int], Callable[[tuple, Any], list[tuple[tuple, Any]]]] = {}


def node_migration(shape: str, start: int):
    def register(fn):
        if (shape, start) in NODE_MIGRATIONS:
            raise ValueError(f"two node migrations of {shape} from schema {start}")
        NODE_MIGRATIONS[(shape, start)] = fn
        return fn

    return register


@node_migration(("unconverted", "*"), 3)
def unconverted_3_to_4(address: tuple, form: Any) -> list[tuple[tuple, Any]]:
    """Schema 4 types every unconverted item: a recorded plain id is carried as the item whose decision's kind was not
    recorded, exactly as `portfolio_3_to_4` writes it, so the approval claims nothing the ruling did not say; a
    recorded typed item is carried as it was."""
    if isinstance(form, str):
        return [(address, {"measure": form, "kind": "not_recorded", "note": UNTYPED_UNCONVERTED})]
    return [(address, form)]
