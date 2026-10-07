#!/usr/bin/env python3
"""test_resilient.py - the write guarantees of resilient.py, checked offline with stubbed reads and writes.

demo.py is read-only, so it cannot show a write being confirmed. This does, without touching an estate: a dry run
that sends nothing, a write that applies and is confirmed, a second run that sends nothing, a write answered that
applied nothing (refused), an update that left the object wrong (refused), and a write with no send function.

Run:  python3 test_resilient.py      exit 0 when every case holds
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from resilient import EffectError, confirm, ensure  # noqa: E402

state, sent = {}, []
desired = {"name": "g", "size": 2}


def find():
    return state.get("g")


def applies(method, path, body):
    sent.append((method, path)); state["g"] = dict(body)


def applies_nothing(method, path, body):
    sent.append((method, path))                       # answered, and nothing changed


def applies_wrong(method, path, body):
    sent.append((method, path)); state["g"] = {"name": "g", "size": 1}


def matches(g):
    return g == desired


def create(send):
    return lambda: ("POST", "/groups", desired, send)


def update(send):
    return lambda g: None if g == desired else ("PUT", "/groups", desired, send)


def case(name, fn, holds):
    try:
        got = fn()
    except Exception as e:  # noqa: BLE001  the refusals are the result under test
        got = e
    ok = holds(got)
    print(("PASS" if ok else "FAIL"), name)
    return ok


def main():
    results = []
    state.clear(); sent.clear()
    results.append(case("a dry run sends nothing", lambda: ensure(find, create(applies), dry_run=True),
                        lambda r: r[0] == "create" and not sent))
    results.append(case("a write that applies is confirmed", lambda: ensure(find, create(applies), matches=matches, dry_run=False),
                        lambda r: r[0] == "created" and r[1] == desired))
    results.append(case("a second run sends nothing", lambda: ensure(find, create(applies), update(applies), matches=matches, dry_run=False),
                        lambda r: r[0] == "unchanged" and len(sent) == 1))
    state.clear()
    results.append(case("a write answered that applied nothing is refused", lambda: ensure(find, create(applies_nothing), matches=matches, dry_run=False),
                        lambda e: isinstance(e, EffectError) and "finds nothing" in str(e)))
    state["g"] = {"name": "g", "size": 1}
    results.append(case("an update that left the object wrong is refused", lambda: ensure(find, create(applies_wrong), update(applies_wrong), matches=matches, dry_run=False),
                        lambda e: isinstance(e, EffectError) and "not in the desired state" in str(e)))
    state.clear()
    results.append(case("a write with no send function is refused", lambda: ensure(find, lambda: ("POST", "/groups", desired), dry_run=False),
                        lambda e: isinstance(e, ValueError)))
    state["g"] = desired
    results.append(case("confirm passes on an object in the desired state", lambda: confirm(find, matches), lambda r: r == desired))
    print(f"\n{sum(results)} of {len(results)} cases hold")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
