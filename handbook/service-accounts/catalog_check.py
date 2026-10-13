#!/usr/bin/env python3
"""catalog_check.py - is every credential your automation holds a managed object, with its rotation still ahead of it?

A held credential is more than its value: it has an owner who answers for it, a scope that says what a leak would
reach, a rotation clock and a backend where the value rests. This reads a catalog of those four things, one entry
per credential, and says which entry is missing one, which is overdue, and which falls due inside the warning
window. It reads metadata only: an entry that carries a field shaped like a secret is refused, because a catalog
that holds values is a second place the secret leaks from.

Each entry: name, owner, scope, backend, cadence_days, last_rotated, next_due (dates as YYYY-MM-DD); kind is
optional. Start from credentials.example.json beside this script.

Use:  python3 catalog_check.py [CATALOG.json] [--today YYYY-MM-DD]
Exit: 0 every entry complete and not due inside the window · 1 a warning (due inside the window, or a next-due
      date later than the cadence allows) · 2 a failure (a field missing, a date overdue or unreadable, a secret
      in the file) · 3 the file could not be read
Standard library only; reads one file, writes nothing, calls nothing.
"""

from __future__ import annotations

import json
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


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    path = args[0] if args else "credentials.json"
    today = date.today()
    if "--today" in argv:
        i = argv.index("--today")
        parsed = _date(argv[i + 1]) if i + 1 < len(argv) else None
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
    print(f"\nexit {worst}")
    return worst


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
