"""The drift-read adapters, one module per companion (40-BREADTH.md step 7). Each exposes `COMPANION`, the companion
string the register's `drift_read` names, and `lines(records, pol, register, capability)`, pure over the records the
loader in `generator/drift.py` hands it: no file is opened here, and no interval or threshold is written here (GATE-14,
14.1), so each comes from the policy. An adapter imports the models, the policy and drift's builder only.

A line's scope is one of the four assignment scopes (estate, organization, project, cluster; 64's ruling as lead): the
plane, instance, machine or category a companion reads goes in the line's items, never in its scope. Each lane decides
what counts as drift for its own companions (charter section 5.6); its rules are written here and in each adapter.

f8's rules, for the adapters of f8's companions (f8, 2026-11-02):

- R1. `drifted` is a read that succeeded and shows the declared state not met; `check_failed` is a read that did not
  establish the state (a failed call, a missing field, an empty result the record cannot tell from a failed listing, an
  item never looked up). An absence of evidence is never `in_sync`.
- R2. On one line, `drifted` beats `check_failed` beats `in_sync`: known drift wins, and the items not read are named in
  the check text ("not read: <why>").
- R3. `in_sync` with zero items only where zero is the declared state, said in words ("no upgrade offered").
- R4. A declaration no record holds is `not_covered`: no proxy stands in for it and reads `in_sync`; a proxy may make a
  line `drifted` only where the chapter's rule makes that state drift whatever was declared.
- R5. A writing probe (verify.py, run.sh, traffic.py, --probe-*) never feeds a line.
- R6. A scope key is stable between runs: a placeholder assigned in listing order may name an item, never key a line.
- Reach (f8, 2026-11-02). check_failed (R1) is for an item the instrument reaches that this run did not establish (a
  failed call, a truncation, an item it covers but never looked up). A part or item the instrument does not reach at all
  is "not read: <why>" in the check text and leaves the line's state as it is; its structural fix is splitting the
  declaration in the register, so the unread part is a not_covered line of its own.

3c's rules, for the adapters of 3c's companions, beside R1 to R6 and the reach rule (3c, 2026-11-02):

- R7. A count the companion takes from a listing that ignores the HTTP status is `check_failed` when it reads zero.
- R8. A count with no declared set to compare against is a value measure, not a drift read: `not_covered`.
- R9. A stored exit is the companion's own verdict: it goes in `source.exit` and never sets `result`.
- R10. A record of a different subject is no read of the declaration.
- R11. Placeholders never join across records: each script numbers its own.
- R12. A transcript is never a record (the loader refuses any pinned file that is not a JSON object).
- R13. A companion's own finding rule may make a line `drifted` under R4; `in_sync` needs the declared side on record,
  or 3c's ruling that the chapter's universal rule is the declaration, written in the adapter's docstring in the
  chapter's own words.
"""

from __future__ import annotations

RANK = {"in_sync": 0, "check_failed": 1, "drifted": 2}


def worst(results: list[str]) -> str:
    """One line's result from its items' results, by f8's R2: drifted, then check_failed, then in_sync."""
    return max(results, key=RANK.__getitem__) if results else "check_failed"


def utc(stamp: str) -> str:
    """A record's capture time in the contract's form: a `+00:00` offset written as `Z`, the fraction dropped."""
    head = stamp.replace("+00:00", "Z")
    if "." in head:
        head = head.split(".", 1)[0] + "Z"
    return head
