"""frameworks/cartography/flow/lib/_collect - the imperative shell: the only network boundary.

Search Flow entities in the window, then batch-fetch their details as raw dicts. Read-only; it
leaves the estate exactly as it found it. A search that hits the cap is reported LOUD, never a
silent truncation, because a truncated flow set silently under-reports dependencies."""
from __future__ import annotations

from lib._client import VrniSession

DEFAULT_MAX_FLOWS = 5000


def collect_flows(client: VrniSession, *, hours: int = 24, page_size: int = 500,
                  max_flows: int = DEFAULT_MAX_FLOWS) -> list[dict]:
    """Search + batch-fetch Flow entity details over the last ``hours``. Returns raw vRNI dicts."""
    refs, _total = client.search("Flow", hours=hours, size=max_flows)
    if len(refs) >= max_flows:
        print(f"  WARNING: the Flow search returned {len(refs)} refs (at the cap of {max_flows}); "
              "the flow set is likely truncated. Narrow --hours or raise --max-flows, or the "
              "dependency graph will be incomplete.")
    ids = [r.get("entity_id") for r in refs if isinstance(r, dict) and r.get("entity_id")]
    raw: list[dict] = []
    for start in range(0, len(ids), page_size):
        raw.extend(client.fetch("Flow", ids[start:start + page_size]))
    return raw
