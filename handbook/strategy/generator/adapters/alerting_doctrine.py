"""The alerting-doctrine adapter: actionable-alerting, read from alerts.py's audit of the three rules. parent-aware.json
comes from a writing probe and feeds no line (R5); storm.json reads alert history for a value, not a declaration. The
rules are 3c's (2026-11-02): R1 to R6 and the reach rule, and R7 to R13 (adapters/__init__.py).

Every line is scope `estate`, mode `detected`; the record stores no exit and no platform evaluation time.

- Each policy's enablement list (VCF Operations). Each owned definition is declared. The record's `ownedEntries`
  counts entries, the default policy's ancestors included, one per kind, so 24 entries can hide an absent definition:
  until alerts.py keeps one entry list per owned definition (3c's fix), the line is check_failed (R1, an absence of
  evidence is never in sync), and an owned definition the default policy shows enabled is check_failed too, since the
  override is not established (3c). A missing review, or an export read as no entries (a failed export gives the same),
  is check_failed. Every policy but the default is not read, and a partial reach is said in the check text and leaves
  the result as it stands. When the per-definition list lands, an absent or enabled definition is drifted, resolution
  `open`; it becomes an exception only when the portfolio holds one for that declaration (the adapter never infers a
  reason).
- The super metrics that hold thresholds (VCF Operations): not covered. The chapter declares no count at which a
  condition outside a super metric is drift, and 18 of 24 is a reference-estate reading, not a declaration (3c).
- The notification rules (VCF Operations). Each enabled rule is an item, named by its listing position, so it keys no
  line (R6); disabled rules are read beside and not judged. An enabled rule with no filter set, or one that sends a
  child's alerts one by one (no definition filter, no resource filter, and no kind or a child kind), is drifted. Each
  rule is recomputed and checked against the record's counts; a disagreement is check_failed. A rule list read as
  empty is check_failed (R7). A rule field the record lists that is neither a filter nor one of the notification-rule
  schema's non-narrowing properties may be a filter a later release added, so the rules are check_failed, never
  drifted (3c, A8).
"""

from __future__ import annotations

from ..drift import line
from ..drift import unread as unread_line
from ..models import Register
from ..policy import Loaded
from . import utc, worst

COMPANION = "handbook/alerting-doctrine"
CHECK_POLICY = (
    "the default policy's export, each owned definition's entry and its reach (alerts.py)"
)
CHECK_RULES = (
    "each enabled notification rule's filters, recomputed against the audit's counts (alerts.py)"
)
# the notification-rule schema's properties that narrow nothing (VCF Operations 9.1.1 public API, `notification-rule`,
# docs/reference/api-specs/vcf-ops-9.1.1-public.json): every other property is in alerts.py's RULE_FILTERS
NOT_FILTERS = (
    "enabled",
    "id",
    "links",
    "name",
    "pluginId",
    "properties",
    "ruleType",
    "sendHeartbeat",
    "templateId",
)


def _enablement(rec: dict) -> tuple[str, int, list[dict], list[str]]:
    owned = (rec.get("definitions") or {}).get("owned") or 0
    review = rec.get("defaultPolicyReview") or {}
    unread = ["every policy but the default (only the default policy's list is read in full)"]
    if review.get("error"):
        return (
            "check_failed",
            owned,
            [],
            [*unread, "the default policy (no policy is flagged the default)"],
        )
    if not review.get("explicitEntries"):
        return (
            "check_failed",
            owned,
            [],
            [*unread, "the default policy's export (read as no entries)"],
        )
    blast = rec.get("blastRadius") or {}
    if not blast or blast.get("underTheDefaultPolicy") is None:
        unread.append("the default policy's reach")
    elif blast.get("undetermined") or (blast.get("queried") or 0) < (blast.get("resources") or 0):
        unread.append(
            f"the reach of {(blast.get('resources') or 0) - (blast.get('resolved') or 0)} objects"
        )
    unread.append(
        "each owned definition's own entry (ownedEntries counts entries, the default policy's ancestors included, so "
        "an absent definition can hide)"
    )
    enabled = review.get("ownedEnabledNames") or []
    if enabled:
        unread.append(
            f"whether the default policy's own entry enables {len(enabled)} owned definitions"
        )
    return "check_failed", owned, [], unread


def _one_by_one(rule: dict, child_kinds: set[str]) -> bool:
    return (
        not rule.get("alertDefinitionFilters")
        and not rule.get("resourceFilters")
        and "resourceFilter" not in (rule.get("otherFilters") or {})
        and (not rule.get("kinds") or bool(set(rule["kinds"]) & child_kinds))
    )


def _rules(rec: dict) -> tuple[str, int, list[dict], list[str], str]:
    routing, corr = rec.get("routing") or {}, rec.get("correlation") or {}
    if not routing.get("rules"):
        return (
            "check_failed",
            0,
            [],
            ["the rule list (read as empty, which a refused listing also gives)"],
            "",
        )
    unknown = [
        f
        for f in routing.get("fields") or []
        if f not in (routing.get("filterFields") or []) and f not in NOT_FILTERS
    ]
    rows = routing.get("perRule") or []
    enabled = [(n, r) for n, r in enumerate(rows, 1) if r.get("enabled")]
    if unknown:
        return (
            "check_failed",
            len(enabled),
            [],
            [f"whether {', '.join(unknown)} narrows a rule (a field the audit does not know)"],
            "",
        )
    child = set(corr.get("childKinds") or [])
    no_filter = sum(1 for _n, r in enabled if not r.get("filters"))
    singly = sum(1 for _n, r in enabled if _one_by_one(r, child))
    if (
        no_filter != routing.get("enabledWithNoFilter")
        or singly != corr.get("enabledRulesSendingChildAlertsOneByOne")
        or len(enabled) != routing.get("enabled")
    ):
        return (
            "check_failed",
            len(enabled),
            [],
            ["the rules as recomputed disagree with the audit's counts"],
            "",
        )
    results, items = [], []
    for n, r in enabled:
        if not r.get("filters") or _one_by_one(r, child):
            results.append("drifted")
            items.append(
                {
                    "declared": {
                        "rule": f"rule {n} of {len(rows)}",
                        "narrowed by": "a definition or an object",
                    },
                    "actual": {
                        "rule": f"rule {n} of {len(rows)}",
                        "filters": r.get("filters"),
                        "alertDefinitionFilters": r.get("alertDefinitionFilters"),
                        "resourceFilters": r.get("resourceFilters"),
                        "kinds": r.get("kinds") or [],
                    },
                    "resolution": "open",
                }
            )
        else:
            results.append("in_sync")
    said = f"; disabled, not judged: {len(rows) - len(enabled)}" if len(rows) > len(enabled) else ""
    if not enabled:  # R3: zero items in sync only where zero is the declared state, said in words
        return "in_sync", 0, [], [], "; no rule is enabled, so none sends an alert out" + said
    return worst(results), len(enabled), items, [], said


THRESHOLDS_WHY = (
    "not read: alerts.py counts the owned conditions whose key reads a super metric, never the super metrics "
    "themselves, and the chapter declares no count at which a condition outside one is drift"
)


def lines(records: dict[str, dict], pol: Loaded, register: Register, capability: str) -> list[dict]:
    ((record_path, rec),) = records.items()
    common = {
        "capability": capability,
        "scope": "estate",
        "read_at": utc(rec["captured_utc"]),
        "companion": COMPANION,
        "record": record_path,
        "exit": None,
        "pol": pol,
    }
    out = []
    for decl in next(c for c in register.capabilities if c.id == capability).declarations:
        obj = decl.object.lower()
        if "enablement" in obj:
            result, declared, items, unread = _enablement(rec)
            check, said = CHECK_POLICY, ""
        elif "notification rules" in obj:
            result, declared, items, unread, said = _rules(rec)
            check = CHECK_RULES
        else:
            why = (
                THRESHOLDS_WHY
                if "super metrics" in obj
                else "not read: no rule of the alerting-doctrine adapter reads this declaration"
            )
            out.append(unread_line(declaration=decl, check=why, **common))
            continue
        out.append(
            line(
                declaration=decl,
                store="VCF Operations",
                declared_version=None,
                mode="detected",
                result=result,
                items_declared=declared,
                items_drifted=len(items),
                items=items,
                checked_at=None,
                check=check + said + (f"; not read: {'; '.join(unread)}" if unread else ""),
                **common,
            )
        )
    return out
