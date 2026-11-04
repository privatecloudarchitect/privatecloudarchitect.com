"""The service-accounts adapter: non-human-identity. The rules are 64's, as the lane that owns the companion (64,
2026-11-02), over f8's R1 to R6 and its reach rule (adapters/__init__.py).

Two records feed it. catalog_check.py's record holds the states of the estate's credential catalog (each held
credential's four facts recorded or missing, its rotation date judged at the record's own `today`) and, when the run
joined identity-model's census, each API client the census read with the entry that names it. The session census of
handbook/integrations-identity (exchange.json) is read as a drift-only proxy for the client-per-integration declaration
(R4): the census is a sample, so it can show drift and never sync.

- Each held credential's owner, scope, backend and rotation date (the credential catalog): the catalog record's entries
  are the items. An entry the check marks `fail` (a fact missing, a rotation date passed or unreadable, a field shaped
  like a secret) is a drifted item, resolution open; one it marks `warn` (due inside the warning window, a date past the
  cadence) is in sync, the count said in the check text; a record that lists no credential is check_failed, since an
  empty catalog and a failed read give the same empty list (R1). When the record joins the census, an API client no
  entry names is a held credential the catalog does not record: a drifted item of this line too.
- An API client per integration (the identity broker): one line, scope `estate`; each vCenter the census read is an
  item, its placeholder naming it and keying no line (R6). A vCenter where a directory principal, a person's account,
  or the local administrator signs in from a non-interactive agent is drifted: the outcome is that no integration or
  automation signs in on a person's account or a break-glass account. A vCenter whose sessions were not read is
  check_failed. When the catalog record joins the census, each joined client is an item of this line as well: one with
  no role, a token missing a lifetime, or a token expired, revoked or past its end date is drifted; one whose token's
  state or end date the census did not carry (`unread`) is check_failed; a client with no catalog entry is the catalog
  line's finding, not this one's. A sample of vCenters showing no drift cannot show sync (not covered, its reason in
  words); a census join that judged every client and found nothing can, since the census read its lists whole.

The mode is `detected`. Each record stores its own exit, carried as stored with its note (R9; a record's facts are
never rewritten): the session census's exit 3 was then a directory account signing in from a client other than the
vSphere Client, which exits 1 under today's table. A catalog record whose `sent` is not empty came from a run that
sent, which the check never does: refused (R5). A record naming a credential or a client by a value and not a
placeholder is refused, so no name reaches a line. No platform evaluation time is stored, and the states are judged at
each record's own day, never the day a page renders.
"""

from __future__ import annotations

import re

from ..drift import RefusedError, line
from ..drift import unread as unread_line
from ..models import Register
from ..policy import Loaded
from . import utc

COMPANION = "handbook/service-accounts"
CATALOG = ".catalog-check.json"  # the pinned copy of catalog_check.py's record
SESSIONS = ".exchange.json"  # the pinned copy of vcenter_exchange.py's record
CHECK_BROKER = (
    "the session census of handbook/integrations-identity, a drift-only proxy: who signs in to each vCenter, and from "
    "what agent (vcenter_exchange.py)"
)
CHECK_CATALOG = (
    "the catalog check's record: each held credential's owner, scope, backend and rotation date recorded, and the date "
    "ahead of the day the record judged it (catalog_check.py)"
)
EXIT_NOTE = "the stored exit 3 is under its day's table; the same finding exits 1 now"
ENDED = {"EXPIRED", "REVOKED"}
PLACEHOLDER = re.compile(r"^\{\{[a-z0-9-]+\}\}$")


def _part(records: dict[str, dict], suffix: str) -> tuple[str, dict]:
    return next((p, r) for p, r in records.items() if p.endswith(suffix))


def _joined(cat: dict) -> list[dict]:
    """The API clients the catalog record's census join holds; none when the run had no census."""
    census = cat.get("census")
    return list(census.get("clients") or []) if isinstance(census, dict) else []


def _placeholders_only(cat: dict) -> None:
    """A credential, client or token the record names by a value and not a placeholder never reaches a line (the
    broker line's findings quote token names; 1b's review of aac6d376)."""
    named = [e.get("name") for e in cat.get("entries") or []]
    for c in _joined(cat):
        named += [c.get("name"), c.get("catalog")]
        named += [t.get("name") for t in c.get("tokens") or [] if isinstance(t, dict)]
    bad = [n for n in named if n is not None and not (isinstance(n, str) and PLACEHOLDER.match(n))]
    if bad:
        raise RefusedError(
            f"the catalog record names {len(bad)} credential(s), client(s) or token(s) by a value, not a "
            "placeholder: no name reaches a line"
        )


def _iso_day(value: object) -> str | None:
    """The day of an ISO date or timestamp (YYYY-MM-DD, or that followed by a time), or None for any other form: a
    date in another form (epoch milliseconds, say) is not compared, it is not judged (1b's review of aac6d376)."""
    if isinstance(value, str) and re.match(r"^\d{4}-\d{2}-\d{2}(?:$|T)", value):
        return value[:10]
    return None


def _census(rec: dict) -> tuple[str, int, list[dict], list[str]]:
    vcs = rec.get("vcenters") or []
    if not vcs:
        return "check_failed", 0, [], ["no vCenter was listed, which a failed census also gives"]
    failed, items, unread = 0, [], []
    for v in vcs:
        s = v.get("sessions")
        if not isinstance(s, dict) or not isinstance(s.get("sessions"), int):
            failed += 1
            unread.append(f"{v.get('vcenter')}'s sessions (not read)")
            continue
        people = [d for d in s.get("directory") or [] if d.get("not_interactive")]
        admin = s.get("local_administrator_not_interactive") or 0
        if people or admin:
            items.append(
                {
                    "declared": {
                        "vcenter": v.get("vcenter"),
                        "integrations sign in on": "an API client, never a person's or the local administrator's account",
                    },
                    "actual": {
                        "vcenter": v.get("vcenter"),
                        "directory principals from a non-interactive agent": len(people),
                        "local administrator sessions from a non-interactive agent": admin,
                    },
                    "resolution": "open",
                }
            )
    if items:
        result = "drifted"
    elif failed:
        result = "check_failed"
    else:
        result = "not_covered"
    return result, len(vcs), items, unread


def _client_items(cat: dict) -> tuple[list[dict], int, list[str]]:
    """The census join's clients for the broker line: the drifted items (no role; a token without both lifetimes,
    expired, revoked or past its end date at the record's day), the count of clients judged, and the clients not judged
    (a token's state or end date the census did not carry)."""
    items, judged, unread = [], 0, []
    today = _iso_day(cat.get("today"))
    for c in _joined(cat):
        tokens = c.get("tokens") or []
        if c.get("state") == "unread":
            unread.append(f"{c.get('name')} (a token's state or end date not in the census)")
            continue
        if any(t.get("expires") is not None and _iso_day(t.get("expires")) is None for t in tokens):
            unread.append(f"{c.get('name')} (a token's end date not in a form this adapter reads)")
            continue
        judged += 1
        findings = []
        if not c.get("roles"):
            findings.append("holds no role")
        for t in tokens:
            if not t.get("lifetimes_set"):
                findings.append(f"token {t.get('name')} without both lifetimes")
            if (t.get("status") or "") in ENDED:
                findings.append(f"token {t.get('name')} {t.get('status')}")
            elif today and _iso_day(t.get("expires")) and _iso_day(t.get("expires")) < today:
                findings.append(f"token {t.get('name')} ended {t['expires']}")
        if findings:
            items.append(
                {
                    "declared": {
                        "client": c.get("name"),
                        "holds": "one role and a live token with both lifetimes set",
                    },
                    "actual": {
                        "client": c.get("name"),
                        "roles": c.get("roles"),
                        "tokens": len(tokens),
                        "findings": findings,
                    },
                    "resolution": "open",
                }
            )
    return items, judged, unread


def _catalog(cat: dict) -> tuple[str, int, list[dict], list[str]]:
    """The catalog line: each entry marked fail, and each joined client no entry names, as drifted items; the count
    judged; and the notes the check text carries (the warnings, in sync)."""
    entries = cat.get("entries") or []
    clients = _joined(cat)
    if not entries and not clients:
        return (
            "check_failed",
            0,
            [],
            ["not read: the record lists no credential, which an empty catalog and a failed read both give"],
        )
    items, notes = [], []
    for e in entries:
        if e.get("state") == "fail":
            items.append(
                {
                    "declared": {
                        "credential": e.get("name"),
                        "recorded": "an owner, a scope, a backend and a rotation date ahead of the day read",
                    },
                    "actual": {
                        "credential": e.get("name"),
                        "missing": list(e.get("missing") or []),
                        "reasons": list(e.get("reasons") or []),
                    },
                    "resolution": "open",
                }
            )
    warned = sum(1 for e in entries if e.get("state") == "warn")
    if warned:
        notes.append(f"{warned} due inside the warning window or past its cadence (warn): in sync, noted")
    unrecorded = [c for c in clients if not c.get("catalog")]
    for c in unrecorded:
        items.append(
            {
                "declared": {
                    "client": c.get("name"),
                    "recorded": "a catalog entry naming it, with its owner and rotation date",
                },
                "actual": {"client": c.get("name"), "catalog": None},
                "resolution": "open",
            }
        )
    if clients:
        notes.append(f"{len(clients)} API client(s) the census read joined, {len(unrecorded)} with no entry")
    return ("drifted" if items else "in_sync"), len(entries) + len(unrecorded), items, notes


def lines(records: dict[str, dict], pol: Loaded, register: Register, capability: str) -> list[dict]:
    sessions_path, sessions = _part(records, SESSIONS)
    cat_path, cat = _part(records, CATALOG)
    if cat.get("sent"):
        raise RefusedError("a catalog check that sent a request never feeds a line (R5)")
    _placeholders_only(cat)
    out = []
    for decl in next(c for c in register.capabilities if c.id == capability).declarations:
        if decl.system == "broker":
            common = {
                "capability": capability,
                "scope": "estate",
                "read_at": utc(sessions["captured"]),
                "companion": COMPANION,
                "record": sessions_path,
                "exit": sessions.get("exit"),
                "pol": pol,
            }
            result, declared, items, unread = _census(sessions)
            client_items, judged, not_judged = _client_items(cat)
            items += client_items
            declared += judged + len(not_judged)
            unread += not_judged
            if client_items:
                result = "drifted"
            elif not_judged and result != "drifted":
                result = "check_failed"
            elif judged and result == "not_covered":
                result = "in_sync"
            if result == "not_covered":
                out.append(
                    unread_line(
                        declaration=decl,
                        check="not read: the census shows no person's or local administrator's account signing in "
                        "from an agent, and a sample cannot show sync; the catalog check's record joins no census",
                        **common,
                    )
                )
                continue
            out.append(
                line(
                    declaration=decl,
                    store="each vCenter's sessions"
                    + ("; each API client's role and tokens, from the catalog check's census join" if judged or not_judged else ""),
                    declared_version=None,
                    mode="detected",
                    result=result,
                    items_declared=declared,
                    items_drifted=len(items),
                    items=items,
                    checked_at=None,
                    check=CHECK_BROKER
                    + (f"; {judged} API client(s) judged from the catalog check's census join" if judged else "")
                    + (f"; not read: {'; '.join(unread)}" if unread else "")
                    + (f"; {EXIT_NOTE}" if sessions.get("exit") == 3 else ""),
                    **common,
                )
            )
        elif decl.system == "credential-catalog":
            result, declared, items, notes = _catalog(cat)
            out.append(
                line(
                    declaration=decl,
                    store="the catalog's entries"
                    + ("; the census join's API clients" if _joined(cat) else ""),
                    declared_version=None,
                    mode="detected",
                    result=result,
                    items_declared=declared,
                    items_drifted=len(items),
                    items=items,
                    checked_at=None,
                    check=CHECK_CATALOG
                    + f"; judged at {cat.get('today')}, warning window {cat.get('warn_days')} days"
                    + "".join(f"; {n}" for n in notes),
                    capability=capability,
                    scope="estate",
                    read_at=utc(cat["captured"]),
                    companion=COMPANION,
                    record=cat_path,
                    exit=cat.get("exit"),
                    pol=pol,
                )
            )
        else:
            out.append(
                unread_line(
                    declaration=decl,
                    check="not read: neither record of this companion reads this declaration",
                    capability=capability,
                    scope="estate",
                    read_at=utc(cat["captured"]),
                    companion=COMPANION,
                    record=cat_path,
                    exit=cat.get("exit"),
                    pol=pol,
                )
            )
    return out
