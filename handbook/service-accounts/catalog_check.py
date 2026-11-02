#!/usr/bin/env python3
"""catalog_check.py - is every credential your automation holds a managed object, with its rotation still ahead of it?

A held credential is more than its value: it has an owner who answers for it, a scope that says what a leak would
reach, a rotation clock and a backend where the value rests. This reads a catalog of those four things, one entry
per credential, and says which entry is missing one, which is overdue, and which falls due inside the warning
window. It reads metadata only: an entry that carries a field shaped like a secret is refused, because a catalog
that holds values is a second place the secret leaks from.

Each entry: name, owner, scope, backend, cadence_days, last_rotated, next_due (dates as YYYY-MM-DD); kind is
optional, and api_client names the VCF SSO API client an entry is for, by its client id or name, when the entry's
name is not that. Start from credentials.example.json beside this script.

Each run writes its record, catalog_check.json in the working directory (OUT names another path), with every name a
placeholder: the day the states were judged at, each entry's state and reasons, which of the four facts it records and
which it lacks, its dates, and, with --census, each API client the census read, its state and the entry that names it.
The record carries no value an entry holds beyond its dates, counts and states, and a record an estate value survived
the scrub in is not written. A later run compares records; a drift read reads the states.

--census CENSUS.json joins the catalog to a record written by identity-model's census.py, which reads every API
client with its roles and its tokens' two lifetimes. Each API client in the record is checked for what neither file
holds alone: an owner, a role, both lifetimes and a rotation date. A client that no catalog entry names, or whose
entry has no owner or no next_due, fails; so does one with no role, a token missing a lifetime, a token EXPIRED or
REVOKED, or a token whose end date has passed; a client holding no token, or a token that expires before its entry's
next_due, is a warning, and so is an entry that two API clients join (a name two clients share, in two realms or
across a re-creation): one entry per credential, so name each by its client id. A token whose state (anything but
ACTIVE, EXPIRED or REVOKED) or end date the record does not carry is not judged: its client reads `unread`, and the run
exits 3. Every name in a census record is a
placeholder, so the join is on keyed fingerprints: run the census with FINGERPRINT_KEY_FILE set, and give this
script the same file. The join first checks that the census read, each check on its own whatever the record's exit
says. A record is not a read when a replayed run wrote it (census.py --replay marks its record "replay": true: its
answers came from a recorded set, not from an estate); when its own exit is not 0; when a call to VCF Operations'
fleet identity plane failed, or answered without the list the read needs (census.py marks such a call `shape`); when
it carries no API client list or no realm list (a --orgs-only record reads no fleet); when it lists no realm, or did
not query the API client and token lists of every realm it lists; when the last page of a realm's API client or token
list does not state that the list was read whole (census.py records the stated total and the distinct entries read,
`listed`, on each page; a record an earlier census.py wrote carries none) or states fewer entries read than its total;
when its API client lines are not the clients its reads listed; or when an API client line carries no roles or tokens list, or, in a
fingerprinted record, no fingerprint. The join then stops with exit 3, because a census that did not read its API
clients would otherwise pass as an estate with none. An empty API client list from a read that passes every check is
a read: the run says that zero were joined, and why the empty list is the estate's.

Use:  python3 catalog_check.py [CATALOG.json] [--today YYYY-MM-DD] [--census CENSUS.json]
Env:  OUT (optional) the record's path, default catalog_check.json; FINGERPRINT_KEY_FILE, with --census, the file the
      census ran with
Exit, the worst state in this order, so a warning never hides a client the run could not judge:
      2 a failure (a field missing, a date overdue or unreadable, a secret in the file, an API client without an
        owner, a role, both lifetimes or a rotation date, or holding a token EXPIRED, REVOKED or past its end date)
      3 the census record is not a read (a replayed run wrote it, its exit is not 0, a fleet identity call failed or
        was marked `shape`, it has no API client list or no realm list, a realm's client or token list was not queried
        or does not state it was read whole, its client lines are not the clients its reads listed, or a client line
        lacks its roles, tokens or fingerprint), checked before any entry is printed, with nothing joined, because
        nothing about the API clients is known; or a joined client holds a token whose state or end date the record does not carry, so that client
        is not judged; or an error the script did not expect; or a run whose code was 0 whose record was not written
        because an estate value survived the scrub (nothing is known from a record that was not written)
      1 a warning (due inside the window, a next-due date later than the cadence allows, a client with no token, a
        token expiring before its rotation date, or a catalog entry two API clients join), and nothing above
      0 every entry complete and not due inside the window, and with --census every API client complete
      5 a usage error: an argument this script does not take, a --today that is not a date, a catalog or census file
        that cannot be read, a catalog that is not one (no JSON object with a credentials list of objects), FINGERPRINT_KEY_FILE unset, unreadable or open to group or other (refused unread, with the fix: chmod 600), a census record without fingerprints or made
        under another key, or a Python older than 3.10
Standard library only; reads its files and FINGERPRINT_KEY_FILE, writes its record with every estate value replaced or
nothing, calls nothing.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone

REQUIRED = ("name", "owner", "scope", "backend", "cadence_days", "last_rotated", "next_due")
SECRET_SHAPED = ("password", "secret", "token", "value", "private_key", "key_material")


def _date(s: object) -> date | None:
    try:
        return date.fromisoformat(str(s))
    except ValueError:
        return None


def check(entry: dict, today: date, warn_days: int) -> tuple[str, list[str]]:
    """One entry's state (ok, warn or fail) and every reason for it."""
    fail, warn = [], []
    leaked = sorted(k for k in entry if any(s in k.lower() for s in SECRET_SHAPED))
    if leaked:
        fail.append(f"holds a field shaped like a secret ({', '.join(leaked)}); keep values in the backend, never here")
    missing = [k for k in REQUIRED if entry.get(k) in (None, "")]
    if missing:
        fail.append(f"missing {', '.join(missing)}")
    last, due = _date(entry.get("last_rotated")), _date(entry.get("next_due"))
    if entry.get("last_rotated") not in (None, "") and last is None:
        fail.append("last_rotated is not a date")
    if entry.get("next_due") not in (None, "") and due is None:
        fail.append("next_due is not a date")
    if due is not None:
        if due < today:
            fail.append(f"overdue since {due.isoformat()}")
        elif due <= today + timedelta(days=warn_days):
            warn.append(f"due {due.isoformat()}, inside the {warn_days}-day window")
    cadence = entry.get("cadence_days")
    if last is not None and due is not None and isinstance(cadence, int) and due > last + timedelta(days=cadence):
        warn.append(f"next_due is later than last_rotated plus the {cadence}-day cadence")
    return ("fail" if fail else "warn" if warn else "ok"), fail + warn


# ── --census: the catalog joined to identity-model's census record ──────────────────────────────────────────────
def fingerprint(value: str, key: bytes) -> str:
    """A name's keyed fingerprint, computed as census.py computes it: case and surrounding space ignored."""
    return hmac.new(key, value.strip().lower().encode(), hashlib.sha256).hexdigest()[:16]


def key_check(key: bytes) -> str:
    return fingerprint("fingerprint key check", key)[:8]


LIVE = "ACTIVE"
ENDED = {"EXPIRED", "REVOKED"}   # a token in either state no longer signs anything in: a finding, never a pass


def client_check(client: dict, entry: dict | None, today: date | None = None) -> tuple[str, list[str]]:
    """One API client from the census, with the catalog entry that names it (or none): an owner, a role, both
    lifetimes and a rotation date, each token's state and end date, and whether its token outlives the rotation date.
    A token whose end date or state the census did not read is not judged: the client reads `unread` (exit 3)."""
    today = today or date.today()
    fail, warn, unread = [], [], []
    if entry is None:
        fail.append("no catalog entry names this client, so it has no owner and no rotation date")
    else:
        fail += [f"its catalog entry has no {what}" for k, what in (("owner", "owner"), ("next_due", "rotation date (next_due)"))
                 if entry.get(k) in (None, "")]
    if not client.get("roles"):
        fail.append("holds no role")
    tokens = client.get("tokens") or []
    if not tokens:
        warn.append("holds no token, so no lifetime to read: nothing signs in as it until one is issued")
    due = _date(entry.get("next_due")) if entry else None
    for t in tokens:
        name = t.get("name")
        missing = [k for k in ("api_token_ttl_min", "access_token_ttl_min") if not isinstance(t.get(k), int)]
        if missing:
            fail.append(f"token {name} has no {' or '.join(missing)}")
        status = str(t.get("status") or "").upper()
        if status in ENDED:
            fail.append(f"token {name} is {status}: it signs nothing in; issue its replacement, then delete it")
        elif status != LIVE:
            unread.append(f"token {name}: its state was not read ({t.get('status')!r}), so whether it still signs in is not known")
        expires = _date(t.get("expires"))
        if expires is None:
            unread.append(f"token {name}: its end date was not read, so neither its runway nor its rotation can be judged")
        elif expires < today:
            fail.append(f"token {name} ended {expires.isoformat()}, before {today.isoformat()}: issue its replacement")
        elif due is not None and expires < due:
            warn.append(f"token {name} expires {expires.isoformat()}, before the rotation date {due.isoformat()}")
    state = "fail" if fail else "unread" if unread else "warn" if warn else "ok"
    return state, fail + unread + warn


def census_join(catalog: dict, census: dict, key: bytes,
                today: date | None = None) -> list[tuple[dict, dict | None, str, list[str]]]:
    """Each API client in the census record with the catalog entry whose api_client (or name) fingerprints to it."""
    by_fp = {}
    for e in catalog.get("credentials") or []:
        name = e.get("api_client") or e.get("name")
        if name:
            by_fp.setdefault(fingerprint(str(name), key), e)
    out = []
    for client in (census.get("summary") or {}).get("api_clients") or []:
        entry = next((by_fp[f] for f in client.get("fingerprints") or [] if f in by_fp), None)
        out.append((client, entry, *client_check(client, entry, today)))
    # One entry per credential. Two API clients can share a name (one in each of two realms, or a client made again
    # under the name of one never deleted), and an entry that names its client by that name joins both: each is then
    # judged against one owner's rotation date that can track only one of them. A warning, never a pass.
    shared: dict[int, int] = {}
    for _client, entry, _state, _why in out:
        if entry is not None:
            shared[id(entry)] = shared.get(id(entry), 0) + 1
    for i, (client, entry, state, why) in enumerate(out):
        if entry is not None and shared[id(entry)] > 1:
            named = entry.get("api_client") or entry.get("name")
            why = [*why, f"{shared[id(entry)]} API clients join the one catalog entry naming {named}: one entry per "
                         "credential keeps each one's rotation on its own record, so name each by its client id"]
            out[i] = (client, entry, state if state in ("fail", "unread") else "warn", why)
    return out


EXIT_UNREAD, EXIT_USAGE = 3, 5
FLEET = "vcf-operations"
# The run's exit is its worst state, in this order: a failure (2) comes first, then a client not judged (3), so a
# warning (1) never hides a token the run could not read.
RANK = {"ok": 0, "warn": 1, "unread": 2, "fail": 3}
EXIT = {"ok": 0, "warn": 1, "unread": EXIT_UNREAD, "fail": 2}


def realms_queried(calls: list, kind: str) -> set[str]:
    """The realms whose `kind` list (api-clients or api-tokens) the census queried: one path segment per realm, every
    page of one realm's list counted once."""
    found = set()
    for c in calls:
        if isinstance(c, dict) and c.get("plane") == FLEET:
            m = re.search(rf"/ssorealms/([^/?]+)/{kind}/query(?:\?|$)", str(c.get("path") or ""))
            if m:
                found.add(m.group(1))
    return found


def last_pages(calls: list, kind: str) -> dict[str, dict]:
    """Each realm's last page call of its `kind` list: census.py records on it the total the answer stated and the
    distinct entries read (`listed`), equal only when the list was read whole."""
    last: dict[str, dict] = {}
    for c in calls:
        if isinstance(c, dict) and c.get("plane") == FLEET:
            m = re.search(rf"/ssorealms/([^/?]+)/{kind}/query(?:\?|$)", str(c.get("path") or ""))
            if m:
                last[m.group(1)] = c
    return last


def census_unread(record: dict) -> str | None:
    """Why a census record is not a read of the API clients, or None when it is one. A census that was refused its
    fleet reads still writes a record, and its API client list is then empty, so an empty list proves nothing until
    the run's own exit, its calls and the list itself are checked. Each check stands on its own, whatever the record's
    exit says: a writer that marked a call and still wrote exit 0 is refused all the same."""
    if not isinstance(record, dict):
        return "it is not a census record"
    if record.get("replay", False) is not False:  # census.py --replay writes "replay": true; a live record has no key
        return ("a replayed run wrote it (\"replay\": true): its answers came from a recorded set, not from an estate, so "
                "its API clients are no estate's")
    if record.get("orgs_only"):
        return "it is a --orgs-only record, which reads no fleet and so no API client"
    code = record.get("exit")
    if isinstance(code, bool) or code != 0:
        return f"the census exited {code!r}, not 0: a read failed, so its counts are not the estate's"
    calls = record.get("calls")
    if not isinstance(calls, list):
        return "it carries no list of the calls the census made, so nothing says its fleet reads answered"
    fleet = [c for c in calls if isinstance(c, dict) and c.get("plane") == FLEET]
    failed = [c for c in fleet if isinstance(c.get("status"), bool) or not isinstance(c.get("status"), int)
              or c["status"] >= 400]
    if failed:
        return f"{len(failed)} of its fleet identity call(s) failed, so an API client it lists none of may be one it did not read"
    shaped = [c for c in fleet if c.get("shape")]
    if shaped:
        why = "; ".join(sorted({str(c["shape"]) for c in shaped}))
        return (f"{len(shaped)} of its fleet identity call(s) answered without the list the read needs ({why}), so an "
                "empty list there is an unread one")
    if not fleet:
        return "it made no call to the fleet identity plane"
    summary = record.get("summary") if isinstance(record.get("summary"), dict) else {}
    clients = summary.get("api_clients")
    if not isinstance(clients, list):
        return "it carries no API client list (summary.api_clients)"
    realms = summary.get("realms")
    if not isinstance(realms, list):
        return "it carries no realm list (summary.realms), so nothing says whose API clients it read"
    if not realms:
        return "it lists no realm, so it queried no API client list, and a client list it never queried is not an empty one"
    for kind, what in (("api-clients", "API clients"), ("api-tokens", "API tokens")):
        queried = len(realms_queried(fleet, kind))
        if queried < len(realms):
            return f"it lists {len(realms)} realm(s) and queried the {what} of {queried}, so the rest are unread"
    read_clients = 0
    for kind, what in (("api-clients", "API client"), ("api-tokens", "API token")):
        for realm, last in last_pages(fleet, kind).items():
            whole = last.get("listed")
            total = whole.get("total") if isinstance(whole, dict) else None
            distinct = whole.get("distinct") if isinstance(whole, dict) else None
            if not all(isinstance(n, int) and not isinstance(n, bool) for n in (total, distinct)):
                return (f"its {what} list of realm {realm} does not state that it was read whole (no `listed` total on its "
                        "last page; an earlier census.py did not record it), so a short read would pass "
                        "as the whole list: run census.py again")
            if distinct != total:
                return (f"its {what} list of realm {realm} was read to {distinct} of the {total} entries it states, so "
                        "the rest are unread")
            read_clients += distinct if kind == "api-clients" else 0
    if read_clients != len(clients):
        return (f"it carries {len(clients)} API client line(s) where its reads listed {read_clients}, so the record does "
                "not hold what was read")
    for i, c in enumerate(clients, 1):
        if not isinstance(c, dict):
            return f"its API client line {i} is not an object"
        gaps = [k for k in ("roles", "tokens") if not isinstance(c.get(k), list)]
        if gaps:
            return (f"its API client line {i} carries no {' and no '.join(gaps)} list, so a role or a token missing from "
                    "the record would read as one missing from the estate")
        if not all(isinstance(t, dict) for t in c["tokens"]):
            return f"its API client line {i} holds a token line that is not an object"
        if record.get("fingerprint_key_check") and not c.get("fingerprints"):
            return f"its API client line {i} carries no fingerprint, so no catalog entry could be joined to it"
    return None


def fingerprint_key() -> bytes:
    """The secret in FINGERPRINT_KEY_FILE, read as bytes as census.py reads it. A file open to group or other is refused
    before it is read; the refusal names the variable and the fix, never the file's content."""
    path = os.environ["FINGERPRINT_KEY_FILE"]
    with open(path, "rb") as f:
        mode = os.fstat(f.fileno()).st_mode & 0o777
        # Windows makes the mode from the read-only flag alone, so it has no group or other bits to judge.
        if mode & 0o077 and os.name != "nt":
            raise PermissionError(f"FINGERPRINT_KEY_FILE names a file of mode {mode:04o}, open to group or other: "
                                  'run chmod 600 "$FINGERPRINT_KEY_FILE" and try again (the file was not read)')
        return f.read().strip()


def _census(path: str) -> tuple[dict | None, bytes | None, str | None, int]:
    """The census record and the key, or the reason the join cannot run and its exit: 5 for what the operator gave
    (a file, the key), 3 for a record that is not a read."""
    try:
        with open(path, encoding="utf-8") as f:
            record = json.load(f)
    except (OSError, ValueError) as e:
        return None, None, f"could not read {path}: {type(e).__name__}", EXIT_USAGE
    if not os.environ.get("FINGERPRINT_KEY_FILE"):
        return None, None, "--census needs FINGERPRINT_KEY_FILE, the same file the census ran with", EXIT_USAGE
    try:
        key = fingerprint_key()
    except OSError as e:   # the refusal of a file open to group or other (no errno) names the variable and the fix
        refused = isinstance(e, PermissionError) and e.errno is None
        return None, None, str(e) if refused else f"could not read FINGERPRINT_KEY_FILE: {type(e).__name__}", EXIT_USAGE
    unread = census_unread(record)
    if unread:
        return None, None, f"NOT READ: {path} is not a read of the API clients: {unread}. Nothing is joined (exit 3)", EXIT_UNREAD
    if not record.get("fingerprint_key_check"):
        return None, None, f"{path} carries no fingerprints: run census.py with FINGERPRINT_KEY_FILE set", EXIT_USAGE
    if not key or record["fingerprint_key_check"] != key_check(key):
        return None, None, f"{path} was fingerprinted under another key than FINGERPRINT_KEY_FILE", EXIT_USAGE
    return record, key, None, 0


def catalog_shape(catalog: object) -> str | None:
    """What makes a file not a catalog: not an object, no `credentials` list, an entry that is not an object, or a
    `warn_days` that is not a whole number. A usage error (exit 5): the file is the reader's, not a platform read."""
    if not isinstance(catalog, dict):
        return "it holds no JSON object"
    if not isinstance(catalog.get("credentials"), list):
        return "it carries no credentials list"
    if not all(isinstance(e, dict) for e in catalog["credentials"]):
        return "a credentials entry is not an object"
    warn = catalog.get("warn_days", 30)
    if isinstance(warn, bool) or not isinstance(warn, int):
        return "warn_days is not a whole number of days"
    return None


# ── the record contract: every estate value replaced, or nothing written ─────────────────────────────────────────
# The record is what the run judged, for a later run to compare against and for a drift read to read: the day the
# states were judged at, each entry's state, reasons, dates and which of the four facts it records, and each API client
# the census joined, with the entry that names it. A name, an owner, a scope and a backend are estate values: each is
# replaced by a placeholder numbered in listing order ({{credential-N}} an entry, {{client-N}} the API client it names,
# {{owner-N}}, {{scope-N}}, {{backend-N}}; a census name is a placeholder already), anything shaped like an id, host,
# address or user is replaced too, and a record one survives in is not written. The record carries no value an entry
# holds beyond its dates, counts and states.
FACTS = (("owner", "owner"), ("scope", "scope"), ("backend", "backend"), ("next_due", "rotation date"))
PRODUCT = {"ok", "warn", "fail", "unread"}  # the states are never a name
FIELDS = {"name": "credential", "catalog": "credential"}  # a field that holds a name: a placeholder, or a leak
PATTERNS = [("id", re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")),
            ("host", re.compile(r"\b[a-z0-9-]+(?:\.[a-z0-9-]+)+\.[a-z]{2,}\b", re.I)),
            ("ip", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
            ("user", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)*\b"))]
NOT_SHAPED = {"captured", "today", "last_rotated", "next_due"}
PLACEHOLDER = re.compile(r"\{\{[a-z-]+-\d+\}\}")
OWN = re.compile(f"({PLACEHOLDER.pattern})")  # splits a text into what lies outside the placeholders and each one


def _strings(obj: object, field: str | None = None):
    """Every (field, string) in a record, the field being the key the string sits under."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _strings(v, k)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v, field)
    elif isinstance(obj, str):
        yield field, obj


def estate_values(record: dict, catalog: dict, census: dict | None) -> dict[str, str]:
    """Each estate value the run read, mapped to its placeholder: every entry's name, the API client it names, its
    owner, scope and backend; every API client and token name the census carries that is not a placeholder already;
    then anything in the record shaped like an id, host, address or user."""
    table: dict[str, str] = {}
    seen: set[str] = set()
    count: Counter = Counter()

    def add(value: object, kind: str) -> None:
        s = str(value).strip() if isinstance(value, (str, int, float)) and not isinstance(value, bool) else ""
        if len(s) >= 3 and s.lower() not in PRODUCT and s.lower() not in seen and not PLACEHOLDER.fullmatch(s):
            seen.add(s.lower())
            count[kind] += 1
            table[s] = f"{{{{{kind}-{count[kind]}}}}}"

    for e in catalog.get("credentials") or []:
        add(e.get("name"), "credential")
        add(e.get("api_client"), "client")
        for k, kind in (("owner", "owner"), ("scope", "scope"), ("backend", "backend")):
            add(e.get(k), kind)
    for c in ((census or {}).get("summary") or {}).get("api_clients") or []:
        add(c.get("name"), "client")
        for t in c.get("tokens") or []:
            add(t.get("name"), "token")
    for field, s in _strings(record):
        if field not in NOT_SHAPED:
            for kind, rx in PATTERNS:
                for m in rx.findall(s):
                    add(m, kind)
    return table


def _pattern(table: dict) -> re.Pattern | None:
    """One alternation, longest first, matched only where it is not part of a longer word."""
    if not table:
        return None
    alt = "|".join(re.escape(v) for v in sorted(table, key=len, reverse=True))
    return re.compile(rf"(?<![A-Za-z0-9])(?:{alt})(?![A-Za-z0-9])", re.I)


def one_pass(table: dict):
    """A text with every registered value replaced by its placeholder in one pass: the longest value first, matched
    without regard to case where it is not part of a longer word, and only outside the placeholders already in the
    text, so a second scrub changes nothing and a value spelled like a placeholder rewrites no other's."""
    rx, label = _pattern(table), {}
    for value, placeholder in table.items():
        label.setdefault(value.lower(), placeholder)
    if rx is None:
        return lambda text: text
    return lambda text: "".join(part if i % 2 else rx.sub(lambda m: label[m.group(0).lower()], part)
                                for i, part in enumerate(OWN.split(text)))


def scrub(obj: object, table: dict) -> object:
    """The record with every registered value replaced by its placeholder (one_pass); keys are never touched."""
    replace = one_pass(table)

    def walk(o: object) -> object:
        if isinstance(o, dict):
            return {k: walk(v) for k, v in o.items()}
        if isinstance(o, list):
            return [walk(v) for v in o]
        return replace(o) if isinstance(o, str) else o

    return walk(obj)


def leaks(obj: object, table: dict) -> list[str]:
    """The kind of every estate value still in a scrubbed record: a registered one, anything shaped like one, or a
    name under a field that holds one (FIELDS) that is not a placeholder, so a value the registration missed (a name
    under three characters) is caught before the record is written."""
    rx, found = _pattern(table), []
    kind_of = {k.lower(): v.strip("{}").rsplit("-", 1)[0] for k, v in table.items()}
    for field, s in _strings(obj):
        rest = PLACEHOLDER.sub(" ", s)  # a placeholder's own letters are not a surviving value
        found += [kind_of[m.group(0).lower()] for m in rx.finditer(rest)] if rx else []
        if field not in NOT_SHAPED:
            found += [kind for kind, p in PATTERNS for _m in p.findall(rest)]
        if field in FIELDS and re.search(r"[A-Za-z0-9]", rest):
            found.append(FIELDS[field])
    return found


def record_of(judged: list[tuple[dict, str, list[str]]], joined: list | None, census: dict | None,
              today: date, warn_days: int, code: int) -> dict:
    """The record, every name still its own (scrub replaces them): the entries as judged, the census join when there
    was one, the counts, and the run's exit. An entry's dates are carried only where they parse."""
    rows = []
    for e, state, reasons in judged:
        cadence = e.get("cadence_days")
        rows.append({
            "name": e.get("name") if isinstance(e.get("name"), str) else None,
            "kind": e.get("kind") if isinstance(e.get("kind"), str) else None,
            "state": state,
            "reasons": reasons,
            "recorded": [what for k, what in FACTS if e.get(k) not in (None, "")],
            "missing": [what for k, what in FACTS if e.get(k) in (None, "")],
            "cadence_days": cadence if isinstance(cadence, int) and not isinstance(cadence, bool) else None,
            "last_rotated": e.get("last_rotated") if _date(e.get("last_rotated")) else None,
            "next_due": e.get("next_due") if _date(e.get("next_due")) else None,
        })
    states = Counter(state for _e, state, _r in judged)
    summary: dict = {"credentials": len(rows), **{s: states.get(s, 0) for s in ("ok", "warn", "fail")}, "api_clients": None}
    part = None
    if census is not None:
        clients = [{
            "name": c.get("name"),
            "catalog": (entry.get("name") or entry.get("api_client")) if entry else None,
            "roles": len(c.get("roles") or []),
            "tokens": [{
                "name": t.get("name"),
                "status": str(t.get("status")).upper() if t.get("status") else None,
                "lifetimes_set": all(isinstance(t.get(k), int) and not isinstance(t.get(k), bool)
                                     for k in ("api_token_ttl_min", "access_token_ttl_min")),
                "expires": t.get("expires") if _date(t.get("expires")) else None,
            } for t in c.get("tokens") or [] if isinstance(t, dict)],
            "state": state,
            "reasons": reasons,
        } for c, entry, state, reasons in joined or []]
        by = Counter(c["state"] for c in clients)
        summary["api_clients"] = {"joined": len(clients), "recorded": sum(1 for c in clients if c["catalog"]),
                                  **{s: by.get(s, 0) for s in ("ok", "warn", "fail", "unread")}}
        part = {"captured": census.get("captured"), "clients": clients}
    return {"captured": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "today": today.isoformat(),
            "warn_days": warn_days, "sent": [], "entries": rows, "census": part, "summary": summary, "exit": code}


def write_record(record: dict, table: dict) -> tuple[str, list[str]]:
    """The record scrubbed and written to OUT (default catalog_check.json); or, when an estate value survived the
    scrub, the kinds that did, and nothing written."""
    out = os.environ.get("OUT") or "catalog_check.json"
    clean = scrub(record, table)
    left = leaks(clean, table)
    if not left:
        with open(out, "w", encoding="utf-8") as f:
            f.write(json.dumps(clean, indent=1, ensure_ascii=False) + "\n")
    return out, left


def _args(argv: list[str]) -> tuple[dict, str | None]:
    """The catalog path and the values of --today and --census; any other argument is refused."""
    out: dict = {"path": None, "--today": None, "--census": None}
    rest = list(argv)
    while rest:
        a = rest.pop(0)
        if a in ("--today", "--census"):
            if not rest:
                return out, f"{a} takes a value"
            out[a] = rest.pop(0)
        elif a.startswith("--") or out["path"] is not None:
            return out, f"unknown argument {a}"
        else:
            out["path"] = a
    return out, None


def main(argv: list[str]) -> int:
    """The run, with two guards around it: a Python older than 3.10 is refused (exit 5) before anything is read, and an
    error the script did not expect exits 3, never 1 or 2, which are findings."""
    if sys.version_info < (3, 10):  # noqa: UP036  the script is run by readers on their own Python
        print("catalog_check.py needs Python 3.10 or later", file=sys.stderr)
        return EXIT_USAGE
    try:
        return _run(argv)
    except Exception as e:  # the last guard: whatever was not expected is not known, so exit 3
        print(f"the run stopped on an error it did not expect: {type(e).__name__}: {str(e)[:160]} (exit 3)", file=sys.stderr)
        return EXIT_UNREAD


def _run(argv: list[str]) -> int:
    a, problem = _args(argv)
    if problem:
        print(f"{problem}; use: catalog_check.py [CATALOG.json] [--today YYYY-MM-DD] [--census CENSUS.json]", file=sys.stderr)
        return EXIT_USAGE
    path = a["path"] or "credentials.json"
    today = date.today()
    if a["--today"] is not None:
        parsed = _date(a["--today"])
        if parsed is None:
            print("--today takes a date, YYYY-MM-DD", file=sys.stderr)
            return EXIT_USAGE
        today = parsed
    try:
        with open(path, encoding="utf-8") as f:
            catalog = json.load(f)
    except (OSError, ValueError) as e:
        print(f"could not read {path}: {type(e).__name__}", file=sys.stderr)
        return EXIT_USAGE
    shape = catalog_shape(catalog)
    if shape:
        print(f"{path} is not a catalog: {shape}", file=sys.stderr)
        return EXIT_USAGE
    census, key = None, None
    if a["--census"] is not None:
        census, key, problem, code = _census(a["--census"])
        if problem:
            print(problem, file=sys.stderr)
            return code
    warn_days = int(catalog.get("warn_days", 30))
    entries = catalog.get("credentials") or []
    worst = "ok"
    print(f"catalog_check.py: {len(entries)} credential(s) in {path}, read on {today.isoformat()}, warning window {warn_days} days\n")
    judged: list[tuple[dict, str, list[str]]] = []
    for e in entries:
        state, reasons = check(e, today, warn_days)
        judged.append((e, state, reasons))
        worst = max(worst, state, key=RANK.__getitem__)
        print(f"  {state:<5} {str(e.get('name', '<no name>')):<24} owner {e.get('owner') or '-':<16} due {e.get('next_due') or '-'}")
        for r in reasons:
            print(f"        {r}")
    joined = None
    if census is not None:
        joined = census_join(catalog, census, key, today)
        realms = len(census["summary"]["realms"])
        read = (f"the census read the API client and token lists of its {realms} realm(s) to the totals they state, with no "
                "call refused or answered without its list")
        if joined:
            print(f"\nAPI clients in the census of {census.get('captured', '?')}: {len(joined)}, joined to the catalog by "
                  f"fingerprint ({read})\n")
        else:
            print(f"\nAPI clients in the census of {census.get('captured', '?')}: 0, so none is joined to the catalog: {read}, "
                  "and those lists hold no API client")
        for client, entry, state, reasons in joined:
            worst = max(worst, state, key=RANK.__getitem__)
            print(f"  {state:<5} {client.get('name')!s:<24} catalog {(entry or {}).get('name') or '-':<20} "
                  f"roles {', '.join(client.get('roles') or []) or '-'}")
            for r in reasons:
                print(f"        {r}")
    if worst == "unread":
        print("\nNOT READ: a token's state or end date was not in the census record, so that client is not judged (exit 3)")
    code = EXIT[worst]
    record = record_of(judged, joined, census, today, warn_days, code)
    out, left = write_record(record, estate_values(record, catalog, census))
    if left:  # not a usage error: the run read, and its record could not be written, so nothing is known from it
        if code == 0:
            code = EXIT_UNREAD
        print(f"\nrefusing to write {out}: {len(left)} estate value(s) survived the scrub ({', '.join(sorted(set(left)))}); "
              f"{out} not written, exit {code}: a tool that reads the record has nothing to read", file=sys.stderr)
    else:
        print(f"\n{out} written with every estate value replaced")
    print(f"\nexit {code}")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
