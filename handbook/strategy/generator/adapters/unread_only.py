"""The adapters of 3c's companions whose records hold no declared state yet: capacity-forecasting, cost-showback and
incident-response. Each declaration is matched by what it declares and read as not covered, its reason saying what no
record holds, so the page states the gap instead of counting it. The rules are 3c's (2026-11-02): R1 to R6 and the reach
rule, and R7 to R13 (adapters/__init__.py). Every line is scope `estate`; a stored exit is carried (R9).

- capacity-headroom (runway.py). The ruler: runway.json carries each governing policy's three blocks but not the parity
  gate's result, since a refused gate exits before any record is written and a passing one records nothing; buffers and
  thresholds are declared and compared by nothing (3c splits them into a line of their own). The reservations: the
  census counts reservations against no declared set, a value measure (R8). The record's exit is runway severity,
  carried as stored.
- workload-showback (coverage.py). The price inputs: coverage.json keeps no amount, only whether each driver's cost in
  force matches the product's reference, which cannot tell a value entered at the reference from one never set. The
  cost-carrying group tree: coverage.py asks every populated group for a cost key and never reads the declared tree.
  The record's calculation time carries no zone, so no check time is stored, never a guessed one (3c).
- incident-handling (triage.py). The routing table: the companion ranks the definitions that fill the queue and keeps
  no routing table, and none is in the repository. The failure record: the template binds only entries written after
  it, and the record holds no per-entry date, so its layer count is a value measure, not drift (3c, A21).
"""

from __future__ import annotations

from ..drift import unread as unread_line
from ..models import Register
from ..policy import Loaded
from . import utc

WHY = {
    "handbook/capacity-forecasting": (
        (
            "allocation ratios",
            "not read: runway.json carries each governing policy's three blocks but neither the declared ratios nor the "
            "parity gate's result (a refused gate exits before any record is written; a passing gate records nothing)",
        ),
        (
            "buffers and thresholds",
            "not read: the parity gate compares the allocation ratios only; no companion compares a policy's buffers or "
            "thresholds with a declaration",
        ),
        (
            "ruler",
            "not read: runway.json carries each governing policy's three blocks but neither the declared ratios nor the "
            "parity gate's result (a refused gate exits before any record is written; a passing gate records nothing); "
            "buffers and thresholds are compared by nothing",
        ),
        (
            "reservations",
            "not read: the census counts the machines carrying a CPU or memory reservation against no declared set, a "
            "value measure",
        ),
    ),
    "handbook/cost-showback": (
        (
            "price inputs",
            "not read: coverage.json keeps no amount, so no driver's value is compared with a declared one; it records "
            "only whether each driver's cost in force matches the product's reference",
        ),
        (
            "custom group tree",
            "not read: coverage.py asks every populated custom group for a cost key, never the declared cost-carrying tree",
        ),
    ),
    "handbook/incident-response": (
        (
            "routing table",
            "not read: the companion keeps no routing table; it ranks the definitions that fill the open queue, each a "
            "row still to write, and no routing-table.yaml is in the repository",
        ),
        (
            "failure record",
            "not read: the template binds only entries written after it, and the record holds no per-entry date, so "
            "its layer count is a value measure",
        ),
    ),
}


def lines_for(
    companion: str, records: dict[str, dict], pol: Loaded, register: Register, capability: str
) -> list[dict]:
    ((record_path, rec),) = records.items()
    out = []
    for decl in next(c for c in register.capabilities if c.id == capability).declarations:
        obj = decl.object.lower()
        why = next(
            (w for key, w in WHY[companion] if key in obj),
            f"not read: no rule of the {companion.split('/')[-1]} adapter reads this declaration",
        )
        out.append(
            unread_line(
                capability=capability,
                declaration=decl,
                scope="estate",
                read_at=utc(rec["captured_utc"]),
                companion=companion,
                check=why,
                record=record_path,
                exit=rec.get("exit"),
                pol=pol,
            )
        )
    return out
