"""The identity-lifecycle adapter: access-lifecycle, read from leavers.py's report. The rules are 64's, as the lane that
owns the companion (64, 2026-11-02), over f8's R1 to R6 and its reach rule (adapters/__init__.py).

Every line is scope `estate`: organization, user and group placeholders follow listing order on each run, so they name
items and key no line (R6), and several tenants' runs merge into one line per declaration. A record whose `mode` is not
"report", or whose `sent` is not empty, came from a run that wrote (--execute, a close), and is refused (R5). A record
naming an organization no organization's settings tie to the tenant (an `unreadable` entry with no `org`) did not
establish which organizations to judge: every line is check_failed.

- The federation settings and the imported groups (VCF Automation): read. Each organization federated to the tenant is
  an item; its accounts are the item's detail. An organization is check_failed when it carries an error or a gate
  error, any account's decision is undetermined, its gate holds an unresolved group, or it is named unreadable. It is
  drifted when it holds an open leaver (an action that would revoke or was refused), a federated account (OAUTH or
  SAML) holding a direct role, enabled or disabled, or a name in use again. A local account's direct roles are counted
  apart and are not drift. A drift whose every flag a person acknowledged (--ack) keeps its drift, resolution
  `exception`; any other is `open`, the demonstration leaver's direct role among them until a portfolio exception
  records it. Every other organization is in sync. An account is named by leavers.py's placeholder only: a record
  naming one by a value is refused, so its line fails instead of publishing the name (64's review). The organizations federated elsewhere, and the switched-off
  organizations holding nothing federated, are counted and not read (the reach rule).
- The report's schedule (the repository): not covered. No record holds the interval, the owner its alert reaches, the
  record path or the tenant list a scheduled run is given. The run's own token flag is that token's reading, never
  drift of the schedule.
- The revocation latency and the acknowledged flags (the repository): not covered. leavers.py takes no latency, and a
  run given no --ack records no person's decision.

The mode is `detected` (a scheduled report, a person closes); the record stores its own exit code, carried on every
line, and no platform evaluation time.
"""

from __future__ import annotations

import re

from ..drift import RefusedError, line
from ..drift import unread as unread_line
from ..models import Register
from ..policy import Loaded
from . import utc, worst

COMPANION = "handbook/identity-lifecycle"
CHECK = (
    "the report: each organization federated to the tenant, each account kept, a leaver, out of scope or "
    "undetermined, a leaver in step or open, direct roles and names in use again flagged (leavers.py)"
)
FEDERATED = ("OAUTH", "SAML")
OPEN = ("would", "refused")
PLACEHOLDER = re.compile(
    r"^\{\{[a-z0-9-]+\}\}$"
)  # leavers.py's listing-order names; a value is refused (64)


def _organizations(rec: dict) -> tuple[str, int, list[dict], list[str]]:
    unreadable = {u.get("org") for u in rec.get("unreadable") or []}
    orgs = rec.get("organizations") or []
    if not orgs:
        return (
            "check_failed",
            0,
            [],
            ["no organization was listed, which a failed listing also gives"],
        )
    results, items, unread = [], [], []
    for o in orgs:
        org, users = o.get("org"), o.get("users") or []
        if (
            o.get("error")
            or o.get("gate_error")
            or org in unreadable
            or (o.get("gate") or {}).get("unresolved")
            or any(u.get("decision") == "undetermined" for u in users)
        ):
            results.append("check_failed")
            unread.append(f"{org} (a read failed or an account is undetermined)")
            continue
        drifts = []
        for u in users:
            kinds = []
            if str(u.get("action") or "").startswith(OPEN):
                kinds.append("open leaver")
            if u.get("providerType") in FEDERATED and u.get("direct_roles"):
                kinds.append("direct-role")
            if any(str(f).startswith("name-in-use-again") for f in u.get("flags") or []):
                kinds.append("name-in-use-again")
            if kinds:
                # an open leaver is no flag a person can acknowledge; a flag every kind of which is acknowledged is an
                # exception a person decided on (64's ruling 4)
                acked = {a.get("flag") for a in u.get("acknowledged") or []}
                decided = "open leaver" not in kinds and all(k in acked for k in kinds)
                drifts.append((u, kinds, "exception" if decided else "open"))
        if not drifts:
            results.append("in_sync")
            continue
        if any(not PLACEHOLDER.match(str(u.get("username"))) for u, *_x in drifts):
            raise RefusedError(
                "the record names an account by a value, not a placeholder: no line publishes it"
            )
        results.append("drifted")
        items.append(
            {
                "declared": {
                    "organization": org,
                    "roles": "through an imported group only",
                    "leavers": "closed",
                },
                "actual": {
                    "organization": org,
                    "accounts": [
                        {
                            "account": u.get("username"),
                            "enabled": u.get("enabled"),
                            "direct_roles": u.get("direct_roles") or [],
                            "tokens": u.get("tokens"),
                            "decision": u.get("decision"),
                            "flags": kinds,
                        }
                        for u, kinds, _r in drifts
                    ],
                },
                "resolution": "exception" if all(r == "exception" for *_x, r in drifts) else "open",
            }
        )
    elsewhere = rec.get("federated_elsewhere") or 0
    if elsewhere:
        unread.append(f"{elsewhere} organizations federated elsewhere, counted and not read")
    quiet = [
        s
        for s in rec.get("switched_off") or []
        if s.get("enabled_federated") == 0 and s.get("federated_tokens") == 0
    ]
    if quiet:
        unread.append(f"{len(quiet)} switched-off organizations holding nothing federated")
    return worst(results), len(orgs), items, unread


def _schedule_why(rec: dict) -> str:
    why = (
        "not read: no record holds the report's schedule (its interval, the owner its alert reaches, its record path), "
        "and the run was given no --expect-tenants, so whether a schedule reads its "
        f"{rec.get('federated_elsewhere') or 0} organizations federated elsewhere is not on record"
    )
    if (rec.get("credential") or {}).get("flag"):
        why += "; the run's own token is flagged inside its warning window, a reading of that token, not of the schedule"
    return why


LATENCY_WHY = (
    "not read: no record holds the revocation latency your estate accepts per organization (leavers.py takes none), and "
    "the run was given no --ack file, so which flags a person decided on is not on record"
)


def lines(records: dict[str, dict], pol: Loaded, register: Register, capability: str) -> list[dict]:
    ((record_path, rec),) = records.items()
    if rec.get("mode") != "report" or rec.get("sent"):
        raise RefusedError("a run that wrote (--execute or a close) never feeds a line (R5)")
    common = {
        "capability": capability,
        "scope": "estate",
        "read_at": utc(rec["captured"]),
        "companion": COMPANION,
        "record": record_path,
        "exit": rec.get("exit"),
        "pol": pol,
    }
    whole = any(u.get("org") is None for u in rec.get("unreadable") or [])
    out = []
    for decl in next(c for c in register.capabilities if c.id == capability).declarations:
        obj = decl.object.lower()
        if decl.system == "vcf-automation":
            if whole:
                result, declared, items, unread = (
                    "check_failed",
                    0,
                    [],
                    ["no organization names this tenant"],
                )
            else:
                result, declared, items, unread = _organizations(rec)
            out.append(
                line(
                    declaration=decl,
                    store="VCF Automation, each organization read against its identity provider",
                    declared_version=None,
                    mode="detected",
                    result=result,
                    items_declared=declared,
                    items_drifted=len(items),
                    items=items,
                    checked_at=None,
                    check=CHECK + (f"; not read: {'; '.join(unread)}" if unread else ""),
                    **common,
                )
            )
        elif "schedule" in obj:
            out.append(unread_line(declaration=decl, check=_schedule_why(rec), **common))
        elif "latency" in obj or "--ack" in obj:
            out.append(unread_line(declaration=decl, check=LATENCY_WHY, **common))
        else:
            out.append(
                unread_line(
                    declaration=decl,
                    check="not read: no rule of the identity-lifecycle adapter reads this declaration",
                    **common,
                )
            )
    return out
