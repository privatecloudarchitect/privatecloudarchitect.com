"""wtpc/lib/_alerts — shared symptom/alert-definition mechanics.

`find_existing` is the paginated adopt-by-name lookup every alert tool needs: the instance carries thousands
of built-in symptom/alert definitions, so a single-page list can't be trusted — paginate the full list and
map name → id for the WTPC namespace. Consumers: the posture deploy (deploy_alerts), the tier re-home
(rehome_tier_alerts), the tier alert generator (build_tier_alerts), and teardown (destroy).
"""
from __future__ import annotations


def find_existing(c, endpoint: str, list_key: str, prefix: str = "PCA - WTPC") -> dict[str, str]:
    """Paginate the full definition list and map name → id for our namespace (idempotency). A single page
    can't be trusted — the instance has thousands of built-in definitions."""
    out: dict[str, str] = {}
    page = 0
    while True:
        items = c.get(endpoint, params={"page": page, "pageSize": 1000, "_no_links": "true"}).json().get(list_key, [])
        out.update({x["name"]: x["id"] for x in items if x["name"].startswith(prefix)})
        if len(items) < 1000:
            return out
        page += 1
