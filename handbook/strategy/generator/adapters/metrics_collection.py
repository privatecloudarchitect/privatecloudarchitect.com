"""The metrics-collection adapter: telemetry-collection. collection_planes.py and topology.py print and write no record
(their kept run is a transcript, never a record, R12), so the lines read the sibling companions' records:
log-collection's log_paths.py run and flow-collection's two reads. The rules are 3c's (2026-11-02): R1 to R6 and the
reach rule, and R7 to R13 (adapters/__init__.py). Every line is scope `estate`, mode `detected`; no record stores its exit
or a platform evaluation time, and placeholders never join across the records (R11).

- The statistics level per instance (vCenter): not covered. No companion script reads it.
- The vCenter adapter instances and their intervals (VCF Operations): not covered. No record is written and no file
  declares the instances or their intervals (collection-design.yaml, 3c's queue, waits for the lab).
- The forwarding and each source's path (VCF Operations for Logs). Under R13, 3c rules the chapter's universal rule the
  declaration, in the companion's own words (log-collection README, its exit status): "1 when a host delivered none of
  its own events in the window, would fail its TLS check, or sits under an enabled vCenter whose stored TLS setting
  differs from the recommended one". Each host is an item: drifted when it delivered none of its own events,
  or when its target is read and it does not trust it, or when its target is not TLS (the declared transport is the
  record's own recommended TLS; an estate that chooses otherwise records an exception, 3c B10); check_failed when the
  host's trust read did not complete, or the probe opened no TLS session (a harness fault, never drift); in sync when
  its own events arrive and it trusts its target. A host a completed trust read does not list is named not read and
  given no result (the record cannot place a host under a vCenter). A host list read as empty is
  check_failed, since a failed listing gives the same. Each enabled vCenter is an item: drifted when its stored TLS
  setting differs from the recommended one, in sync when it matches, check_failed when the record holds no
  recommended setting to compare against; a vCenter with collection off is not judged and
  is named. Each source's declared path is not read: the record tallies collection by adapter kind only.
- The flow exporters and their collector (the vDS and NSX flow exporters): not covered until the flow coverage spec of
  40-FLOW-COVERAGE.md section 3 is built; the two flow records name no workload host set, and their placeholders do not
  join.
"""

from __future__ import annotations

from ..drift import line
from ..drift import unread as unread_line
from ..models import Register
from ..policy import Loaded
from . import utc, worst

COMPANION = "handbook/metrics-collection"
CHECK_LOGS = (
    "each host's own events, its trust of its target, and each enabled vCenter's stored TLS setting against the "
    "recommended one (log-collection's log_paths.py)"
)
WHY = {
    "statistics level": "not read: no companion script reads a vCenter's statistics level",
    "adapter instances": (
        "not read: collection_planes.py and topology.py print and write no record, and no file declares the adapter "
        "instances or their intervals"
    ),
    "flow exporters": (
        "not read: no record holds the declared flow coverage (the coverage spec is proposed, not built); the flow "
        "records name no set of hosts that run workloads, and their placeholders do not join"
    ),
}


def _part(records: dict[str, dict], name: str) -> tuple[str, dict]:
    return next((p, r) for p, r in records.items() if p.endswith(name))


def _forwarding(rec: dict) -> tuple[str, int, list[dict], list[str]]:
    hosts = (rec.get("source_proof") or {}).get("hosts") or []
    if not hosts:
        return (
            "check_failed",
            0,
            [],
            ["the hosts (read as none, which a failed listing also gives)"],
        )
    trust = rec.get("trust_proof") or {}
    trusted = (
        {h.get("host"): h for h in trust.get("hosts") or []} if trust.get("read") == "read" else {}
    )
    results, items, unread = (
        [],
        [],
        ["each source's declared path (the record tallies collection by adapter kind)"],
    )
    if trust.get("read") != "read":
        unread.append("the hosts' trust of their targets")
    sessionless = []
    for h in hosts:
        name, t = h.get("host"), trusted.get(h.get("host"))
        if not h.get("own_events"):
            results.append("drifted")
            items.append(
                {
                    "declared": {"host": name, "own events reach Log Management": True},
                    "actual": {"host": name, "own_events": h.get("own_events")},
                    "resolution": "open",
                }
            )
        elif t is None and not trusted:
            results.append("check_failed")  # the trust read did not complete
        elif t is None:
            continue  # outside a completed trust read: named below, no result (the reach rule; 3c, finding 4)
        elif str(t.get("why") or "").startswith("no TLS session"):
            results.append(
                "check_failed"
            )  # the probe opened no session: a harness fault is no drift (3c, finding 1)
            sessionless.append(name)
        elif t.get("trusts_target") is not True:
            results.append("drifted")
            items.append(
                {
                    "declared": {"host": name, "target": "TLS, trusted"},
                    "actual": {
                        "host": name,
                        "trusts_target": t.get("trusts_target"),
                        "why": t.get("why"),
                    },
                    "resolution": "open",
                }
            )
        else:
            results.append("in_sync")
    if sessionless:
        unread.append(f"the trust of {len(sessionless)} hosts (no TLS session was opened)")
    missing = sum(1 for h in hosts if h.get("own_events") and h.get("host") not in trusted)
    if trusted and missing:
        unread.append(f"the trust of {missing} hosts the trust read does not list")
    stored = rec.get("stored_config") or {}
    if stored.get("read") != "read":
        results.append("check_failed")
        unread.append(f"the stored collection settings ({stored.get('read') or 'not read'})")
    else:
        want = (stored.get("recommended") or {}).get("ssl_enabled")
        off = [v.get("vcenter") for v in stored.get("vcenters") or [] if not v.get("enabled")]
        if want is None:  # nothing to compare against (3c, finding 2)
            unread.append("the recommended TLS setting")
        for v in stored.get("vcenters") or []:
            if not v.get("enabled"):
                continue
            if want is None:
                results.append("check_failed")
            elif v.get("ssl_enabled") == want:
                results.append("in_sync")
            else:
                results.append("drifted")
                items.append(
                    {
                        "declared": {"vcenter": v.get("vcenter"), "ssl_enabled": want},
                        "actual": {
                            "vcenter": v.get("vcenter"),
                            "ssl_enabled": v.get("ssl_enabled"),
                        },
                        "resolution": "open",
                    }
                )
        if off:
            unread.append(f"{len(off)} vCenter with collection off, not judged ({', '.join(off)})")
    return worst(results), len(results), items, unread


def lines(records: dict[str, dict], pol: Loaded, register: Register, capability: str) -> list[dict]:
    logs_path, logs = _part(records, ".log-paths.json")
    flows_path, flows = _part(records, ".exporters.json")
    out = []
    for decl in next(c for c in register.capabilities if c.id == capability).declarations:
        obj = decl.object.lower()
        flow = decl.system == "flow-exporters" or "flow exporters" in obj
        common = {
            "capability": capability,
            "declaration": decl,
            "scope": "estate",
            "read_at": utc((flows if flow else logs)["read_at"]),
            "companion": COMPANION,
            "record": flows_path if flow else logs_path,
            "exit": None,
            "pol": pol,
        }
        if "forwarding" in obj:
            result, declared, items, unread = _forwarding(logs)
            out.append(
                line(
                    store="VCF Operations for Logs",
                    declared_version=None,
                    mode="detected",
                    result=result,
                    items_declared=declared,
                    items_drifted=len(items),
                    items=items,
                    checked_at=None,
                    check=CHECK_LOGS + (f"; not read: {'; '.join(unread)}" if unread else ""),
                    **common,
                )
            )
            continue
        why = next(
            (w for key, w in WHY.items() if key in obj),
            "not read: no rule of the metrics-collection adapter reads this declaration",
        )
        out.append(unread_line(check=why, **common))
    return out
