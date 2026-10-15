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

--census CENSUS.json joins the catalog to a record written by identity-model's census.py, which reads every API
client with its roles and its tokens' two lifetimes. Each API client in the record is checked for what neither file
holds alone: an owner, a role, both lifetimes and a rotation date. A client that no catalog entry names, or whose
entry has no owner or no next_due, fails; so does one with no role, or a token missing a lifetime; a client holding
no token, or a token that expires before its entry's next_due, is a warning. Every name in a census record is a
placeholder, so the join is on keyed fingerprints: run the census with FINGERPRINT_KEY_FILE set, and give this
script the same file.

Use:  python3 catalog_check.py [CATALOG.json] [--today YYYY-MM-DD] [--census CENSUS.json]
Exit: 0 every entry complete and not due inside the window, and with --census every API client complete · 1 a
      warning (due inside the window, a next-due date later than the cadence allows, a client with no token, or a
      token expiring before its rotation date) · 2 a failure (a field missing, a date overdue or unreadable, a secret
      in the file, an API client without an owner, a role, both lifetimes or a rotation date) · 3 a file could not be
      read, a census record without fingerprints or made under another key, or an argument this script does not take
Standard library only; reads its files and FINGERPRINT_KEY_FILE, writes nothing, calls nothing.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
from datetime import date, timedelta

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


def client_check(client: dict, entry: dict | None) -> tuple[str, list[str]]:
    """One API client from the census, with the catalog entry that names it (or none): an owner, a role, both
    lifetimes and a rotation date, and whether its token outlives the rotation date."""
    fail, warn = [], []
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
    for t in tokens:
        missing = [k for k in ("api_token_ttl_min", "access_token_ttl_min") if not isinstance(t.get(k), int)]
        if missing:
            fail.append(f"token {t.get('name')} has no {' or '.join(missing)}")
        due = _date(entry.get("next_due")) if entry else None
        expires = _date(t.get("expires"))
        if due is not None and expires is not None and expires < due:
            warn.append(f"token {t.get('name')} expires {expires.isoformat()}, before the rotation date {due.isoformat()}")
    return ("fail" if fail else "warn" if warn else "ok"), fail + warn


def census_join(catalog: dict, census: dict, key: bytes) -> list[tuple[dict, dict | None, str, list[str]]]:
    """Each API client in the census record with the catalog entry whose api_client (or name) fingerprints to it."""
    by_fp = {}
    for e in catalog.get("credentials") or []:
        name = e.get("api_client") or e.get("name")
        if name:
            by_fp.setdefault(fingerprint(str(name), key), e)
    out = []
    for client in (census.get("summary") or {}).get("api_clients") or []:
        entry = next((by_fp[f] for f in client.get("fingerprints") or [] if f in by_fp), None)
        out.append((client, entry, *client_check(client, entry)))
    return out


def _census(path: str) -> tuple[dict | None, bytes | None, str | None]:
    """The census record and the key, or the reason the join cannot run."""
    try:
        with open(path, encoding="utf-8") as f:
            record = json.load(f)
    except (OSError, ValueError) as e:
        return None, None, f"could not read {path}: {type(e).__name__}"
    key_path = os.environ.get("FINGERPRINT_KEY_FILE")
    if not key_path:
        return None, None, "--census needs FINGERPRINT_KEY_FILE, the same file the census ran with"
    try:
        with open(key_path, "rb") as f:
            key = f.read().strip()
    except OSError as e:
        return None, None, f"could not read FINGERPRINT_KEY_FILE: {type(e).__name__}"
    if not record.get("fingerprint_key_check"):
        return None, None, f"{path} carries no fingerprints: run census.py with FINGERPRINT_KEY_FILE set"
    if not key or record["fingerprint_key_check"] != key_check(key):
        return None, None, f"{path} was fingerprinted under another key than FINGERPRINT_KEY_FILE"
    return record, key, None


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
    a, problem = _args(argv)
    if problem:
        print(f"{problem}; use: catalog_check.py [CATALOG.json] [--today YYYY-MM-DD] [--census CENSUS.json]", file=sys.stderr)
        return 3
    path = a["path"] or "credentials.json"
    today = date.today()
    if a["--today"] is not None:
        parsed = _date(a["--today"])
        if parsed is None:
            print("--today takes a date, YYYY-MM-DD", file=sys.stderr)
            return 3
        today = parsed
    try:
        with open(path, encoding="utf-8") as f:
            catalog = json.load(f)
    except (OSError, ValueError) as e:
        print(f"could not read {path}: {type(e).__name__}", file=sys.stderr)
        return 3
    census, key = None, None
    if a["--census"] is not None:
        census, key, problem = _census(a["--census"])
        if problem:
            print(problem, file=sys.stderr)
            return 3
    warn_days = int(catalog.get("warn_days", 30))
    entries = catalog.get("credentials") or []
    worst = 0
    print(f"catalog_check.py: {len(entries)} credential(s) in {path}, read on {today.isoformat()}, warning window {warn_days} days\n")
    for e in entries:
        state, reasons = check(e, today, warn_days)
        worst = max(worst, {"ok": 0, "warn": 1, "fail": 2}[state])
        print(f"  {state:<5} {str(e.get('name', '<no name>')):<24} owner {e.get('owner') or '-':<16} due {e.get('next_due') or '-'}")
        for r in reasons:
            print(f"        {r}")
    if census is not None:
        joined = census_join(catalog, census, key)
        print(f"\nAPI clients in the census of {census.get('captured', '?')}: {len(joined)}, joined to the catalog by fingerprint\n")
        for client, entry, state, reasons in joined:
            worst = max(worst, {"ok": 0, "warn": 1, "fail": 2}[state])
            print(f"  {state:<5} {client.get('name')!s:<24} catalog {(entry or {}).get('name') or '-':<20} "
                  f"roles {', '.join(client.get('roles') or []) or '-'}")
            for r in reasons:
                print(f"        {r}")
    print(f"\nexit {worst}")
    return worst


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
