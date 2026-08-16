"""wtpc/lib/_sm — super-metric mechanics shared across the generators.

Four things every SM generator did by hand, gathered so each is learned once:

  • the STAT KEY a view/alert/formula uses to read an SM by id — `Super Metric|sm_<uuid>`. This is
    the single most-copied string in the bundle, and the one whose wrong form (`super:<uuid>`) silently
    resolves to nothing so the metric reads blank. It lives here with its validator regex.
  • the live SM lookup — {name: id} with the `SuperMetric-` id prefix stripped (the form upsert + activate
    both want).
  • the adopt-by-NAME upsert: id-preserving PUT when the name is live (syncs formula + rationale), else POST. The SM name carries no ':' or '|' — that is the generator's concern, not this
    seam's; this seam just adopts whatever name it is handed.
  • the programmatic policy ACTIVATION (PUT /internal/supermetrics/assign on the header-gated internal
    surface; the header is added by the client): a POSTed-but-unassigned SM never computes, so create → activate must both run.
"""
from __future__ import annotations

import re

import yaml

# A super-metric is read by `Super Metric|sm_<uuid>`, NOT `super:<uuid>` (which resolves to nothing
# and the metric reads blank). This regex is the guard alert-generators use to assert a key is fully resolved.
SM_STAT_KEY_RE = re.compile(r"^Super Metric\|sm_[0-9a-f-]{36}$")


def sm_stat_key(sm_id: str) -> str:
    """The metric key that reads super-metric `sm_id`."""
    return f"Super Metric|sm_{sm_id}"


def existing_supermetrics(c) -> dict[str, str]:
    """{super-metric name: id} for every live SM, the `SuperMetric-` id prefix stripped (the form the upsert
    and activation want). One page of 2000 covers the lab estate."""
    return {s["name"]: s["id"].replace("SuperMetric-", "")
            for s in c.get("/api/supermetrics", params={"pageSize": "2000"}).json()["superMetrics"]}


def upsert_supermetric(c, *, name, formula, description, existing, dry, dry_id):
    """Adopt-or-create a super-metric by its stable NAME. If the name is already live, PUT
    id-preservingly (syncs the formula + rationale onto it); otherwise POST (the server assigns the
    id). Returns (id, action) with action ∈ {"reused", "posted", "dry-new"} so the caller keeps its own
    posted/reused tally. dry=True does the reads but no writes; a brand-new SM in dry-run returns
    (dry_id, "dry-new"). `existing` is an existing_supermetrics(c) map."""
    if name in existing:
        sid = existing[name]
        if not dry:
            c.put("/api/supermetrics",
                  json={"id": sid, "name": name, "formula": formula, "description": description})
        return sid, "reused"
    if dry:
        return dry_id, "dry-new"
    r = c.post("/api/supermetrics", json={"name": name, "formula": formula, "description": description})
    r.raise_for_status()
    return r.json()["id"].replace("SuperMetric-", ""), "posted"


def activate_in_policy(c, sm_id: str, policy_id: str, object_type: str) -> None:
    """Enable super-metric `sm_id` on `object_type` inside one policy — the programmatic assign over
    the header-gated internal API (the header is added by the client). Call once per (sm, policy):
    the posture generators enable in one policy, the governance generator loops the posture policies."""
    c.put("/internal/supermetrics/assign", params={"policyIds": policy_id},
          json={"superMetricId": sm_id,
                "resourceKindKeys": [{"adapterKind": "VMWARE", "resourceKind": object_type}]})


def load_sm_ids(path: str, field: str = "supermetrics") -> dict[str, str]:
    """{sm key: id} from a committed SM record — supermetrics.<posture>.yaml (field 'supermetrics') or
    tiers.<name>.yaml (field 'host_supermetrics'). A missing/empty field yields {}."""
    doc = yaml.safe_load(open(path, encoding="utf-8"))
    return {e["key"]: e["id"] for e in (doc.get(field) or [])}
