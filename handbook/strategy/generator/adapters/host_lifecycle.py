"""The host-lifecycle adapter, the first (20-PILOT.md step 5), unchanged in what it emits.

One line per image declaration per cluster: the cluster's declared image is read against the image compliance vCenter
stored, so the mode is `detected` and `checked_at` is the platform's own evaluation time (G-781). A stored COMPLIANT is
`in_sync`; a stored NON_COMPLIANT, NOT_COMPLIANT or INCOMPATIBLE is `drifted`; a compliance that was not read is
`check_failed`; a cluster managed with baselines has no image declaration to read, so it is `not_covered`.
"""

from __future__ import annotations

from ..drift import line
from ..models import Register
from ..policy import Loaded

COMPANION = "handbook/host-lifecycle"
DRIFTED = {"NON_COMPLIANT", "NOT_COMPLIANT", "INCOMPATIBLE"}


def lines(records: dict[str, dict], pol: Loaded, register: Register, capability: str) -> list[dict]:
    """The capability's image declaration, as the register declares it, read against each cluster's stored result."""
    ((record_path, record),) = records.items()
    decl = next(c for c in register.capabilities if c.id == capability).declarations[0]
    out = []
    for v in record["vcenters"]:
        for c in v["clusters"]:
            ic = c.get("image_compliance") or {}
            if not c.get("image_managed"):
                result, checked, declared = "not_covered", None, None
            else:
                declared = (c.get("image") or {}).get("base_image")
                status = ic.get("status")
                checked = ic.get("checked")
                result = (
                    "in_sync"
                    if status == "COMPLIANT"
                    else "drifted"
                    if status in DRIFTED
                    else "check_failed"
                )
            out.append(
                line(
                    capability=capability,
                    declaration=decl,
                    store="vCenter",
                    declared_version=declared,
                    scope=f"cluster:{c['name']}",
                    mode="detected",
                    result=result,
                    items_declared=1 if c.get("image_managed") else 0,
                    items_drifted=1 if result == "drifted" else 0,
                    items=[{"declared": declared, "actual": ic.get("status"), "resolution": "open"}]
                    if result == "drifted"
                    else [],
                    read_at=record["captured_utc"],
                    checked_at=checked,
                    companion=COMPANION,
                    check="not read: the cluster is managed with baselines, so it holds no image declaration"
                    if result == "not_covered"
                    else "image compliance",
                    record=record_path,
                    exit=record.get("exit"),
                    pol=pol,
                    replay=bool(record.get("replay")),
                )
            )
    return out
