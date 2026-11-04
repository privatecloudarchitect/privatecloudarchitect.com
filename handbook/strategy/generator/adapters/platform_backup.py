"""The platform-backup adapter: platform-restore's backup schedule, read as each plane's newest copy against the age its
schedule allows (recovery.py, the companion's alert arithmetic). f8's rules R1 to R6 apply (adapters/__init__.py).

One line, scope `estate`; each management plane the record read is an item. A plane is in sync when its newest copy is
younger than its schedule allows (`age.overdue` false); drifted when the copy is overdue, or when the read succeeded and
the schedule is not enabled (f8: the declared schedule is not in effect); check_failed when the plane was not reached or
the record carries no age for it. The mode is `detected`: a scheduled read, the platform team acts (README: "a scheduled
run of it is the alert"). The declared version is each plane's schedule in its own words, since the field that names a
plane's cadence is not the one that sets it (README, "The schedule is not the cadence"). No platform evaluation time is
stored, so `checked_at` is null; the record stores no exit code.
"""

from __future__ import annotations

from ..drift import line
from ..models import Register
from ..policy import Loaded
from . import utc, worst

COMPANION = "handbook/platform-backup"
CHECK = "each plane's newest copy against the age its schedule allows (recovery.py)"


def _words(schedule: dict) -> str:
    says = schedule.get("says") or "no cadence named"
    days = schedule.get("daysListed")
    hour, minute = schedule.get("atHour"), schedule.get("atMinute")
    at = f" at {hour:02d}:{minute:02d}" if isinstance(hour, int) and isinstance(minute, int) else ""
    listed = (
        f", {days} days listed"
        if days
        else f", an empty day list ({schedule['emptyDayListMeans']})"
        if schedule.get("emptyDayListMeans")
        else ""
    )
    return f"{says}{listed}{at}"


def lines(records: dict[str, dict], pol: Loaded, register: Register, capability: str) -> list[dict]:
    ((record_path, record),) = records.items()
    (decl,) = next(c for c in register.capabilities if c.id == capability).declarations
    results, items, unread, versions = [], [], [], []
    for p in record.get("planes") or []:
        plane, schedule, age = p.get("plane"), p.get("schedule") or {}, p.get("age") or {}
        versions.append(f"{plane}: {_words(schedule)}")
        if not p.get("reached") or "overdue" not in age:
            results.append("check_failed")
            unread.append(
                f"{plane}, {'not reached' if not p.get('reached') else 'no copy age recorded'}"
            )
        elif schedule.get("enabled") is False:
            results.append("drifted")
            items.append(
                {
                    "declared": {"plane": plane, "schedule": _words(schedule), "enabled": True},
                    "actual": {"plane": plane, "enabled": False},
                    "resolution": "open",
                }
            )
        elif age["overdue"]:
            results.append("drifted")
            items.append(
                {
                    "declared": {
                        "plane": plane,
                        "newest copy within hours": age.get("allowedHours"),
                    },
                    "actual": {"plane": plane, "newest copy age hours": age.get("ageHours")},
                    "resolution": "open",
                }
            )
        else:
            results.append("in_sync")
    if not results:
        unread.append("no plane was read")
    return [
        line(
            capability=capability,
            declaration=decl,
            store="each management plane",
            declared_version="; ".join(versions) or None,
            scope="estate",
            mode="detected",
            result=worst(results),
            items_declared=len(results),
            items_drifted=len(items),
            items=items,
            read_at=utc(record["captured_utc"]),
            checked_at=None,
            companion=COMPANION,
            check=CHECK + (f"; not read: {'; '.join(unread)}" if unread else ""),
            record=record_path,
            exit=None,
            pol=pol,
        )
    ]
