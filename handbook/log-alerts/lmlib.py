"""lmlib.py: the plumbing the log-alerts scripts share. Standard library only.

A log alert lives in two products. VCF Operations holds the definition and the policy that switches it on
(`/suite-api`, an api-token exchanged for a bearer, as the Part 0 chapters teach). Log Management stores the
events, matches them and runs one monitor per log symptom (`:9543`, a service JWT that VCF Operations mints for
the `VCF_OPS_LI` service). Both tokens are short-lived, so `Session` mints them again before they expire rather than
caching them for a run that can outlast them.

The Operations sign-in (`opslib.py`) and the service-JWT exchange (`rtmlib.py`) are the metrics-collection
harness's, and the scrubber is the log-collection harness's; each is imported from its folder beside this one, never
copied, so the auth flow and the record contract have one source.

Environment, as the metrics harness: OPS_HOST, OPS_API_TOKEN; optional OPS_BROKER_HOST, OPS_REALM, OPS_TLS_VERIFY.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _beside(folder: str, marker: str) -> Path:
    """A sibling harness folder in the companion repository (or under the companion staging tree in the private one)."""
    for p in (HERE.parent / folder, HERE.parents[3] / "deploy/privatecloudarchitect/companion/staging/handbook" / folder):
        if (p / marker).is_file():
            return p
    raise SystemExit(f"FATAL: {folder}/{marker} is not beside this folder; run from the companion repository's handbook/ tree")


sys.path.insert(0, str(_beside("metrics-collection/harness", "opslib.py")))
sys.path.insert(0, str(_beside("log-collection", "scrub.py")))

from opslib import _ctx, bearer, ops  # noqa: E402
from rtmlib import service_jwt  # noqa: E402
from scrub import Scrubber  # noqa: E402,F401

REMINT_S = 20 * 60  # the bearer lasted about 30 minutes and the service JWT about 35 on the build this was proven on


class Session:
    """A suite-api bearer and a Log Management JWT, minted again when they near the end of their life."""

    def __init__(self) -> None:
        self._tok, self._tok_at = "", 0.0
        self._jwt, self._jwt_at = "", 0.0
        self.li_address = ""

    def tok(self) -> str:
        if time.monotonic() - self._tok_at > REMINT_S:
            self._tok, self._tok_at = bearer(), time.monotonic()
        return self._tok

    def ops(self, method: str, path: str, body=None, params=None):
        """One /suite-api request: (status, parsed JSON or None)."""
        return ops(method, path, self.tok(), body=body, params=params)

    def must(self, method: str, path: str, body=None, params=None, ok=(200, 201, 204)):
        st, out = self.ops(method, path, body, params)
        if st not in ok:
            raise SystemExit(f"FATAL: {method} {path} -> HTTP {st}: {json.dumps(out)[:300]}")
        return out

    def jwt(self) -> str:
        if time.monotonic() - self._jwt_at > REMINT_S:
            services = self.must("GET", "/api/integrations/services").get("servicesDetails", [])
            entry = next((s for s in services if s.get("type") == "VCF_OPS_LI"), None)
            if entry is None:
                raise SystemExit("FATAL: no registered VCF_OPS_LI service; is Log Management deployed on this instance?")
            self.li_address = entry["address"]
            self._jwt, self._jwt_at = service_jwt(self.tok(), "VCF_OPS_LI"), time.monotonic()
        return self._jwt

    def li(self, method: str, path: str, body=None) -> tuple[int, object]:
        """One Log Management request on :9543: (status, parsed JSON or None)."""
        jwt = self.jwt()
        req = urllib.request.Request(
            f"https://{self.li_address}:9543{path}",
            data=json.dumps(body).encode() if body is not None else None,
            method=method,
            headers={"X-JWT-Token": jwt, "Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, context=_ctx(), timeout=180) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, {"raw": raw.decode(errors="replace")[:300]}

    def search(self, body: dict) -> dict:
        """`POST /api/v2/logs/search`: a bool query of term, match_phrase, prefix, exists and range clauses, at most
        2,000 events per call, and the multi_terms aggregation for counts by field."""
        st, out = self.li("POST", "/api/v2/logs/search", body)
        if st != 200:
            raise SystemExit(f"FATAL: Log Management search -> HTTP {st}: {json.dumps(out)[:300]}")
        return out or {}

    def monitors(self) -> dict[str, bool]:
        """Log Management's monitors by name, enabled or not: one per log symptom an alert uses."""
        st, out = self.li("GET", "/api/v2/ops-alerts")
        if st != 200:
            raise SystemExit(f"FATAL: GET /api/v2/ops-alerts -> HTTP {st}")
        return {m["name"]: bool(m.get("enabled")) for m in out or []}

    def paged(self, path: str, key: str, params: dict | None = None) -> list[dict]:
        """Every item of a paged suite-api list, read to its pageInfo.totalCount."""
        items: list[dict] = []
        page = 0
        while True:
            body = self.must("GET", path, params={**(params or {}), "page": page, "pageSize": 1000, "_no_links": "true"})
            got = (body or {}).get(key) or []
            items.extend(got)
            total = int(((body or {}).get("pageInfo") or {}).get("totalCount", len(items)))
            if not got or len(items) >= total:
                return items
            page += 1


def catch_all_rules(s: Session) -> list[str]:
    """Enabled notification rules that select neither alert definitions nor resources: any alert a test raises would
    be sent wherever they point. On 9.1.1 the list is under `rules`."""
    body = s.must("GET", "/api/notifications/rules", params={"_no_links": "true"}) or {}
    out = []
    for r in body.get("rules") or []:
        if r.get("enabled") is False:  # a rule that does not say is treated as enabled
            continue
        if not (r.get("alertDefinitionIdFilters") or {}).get("values") and not r.get("resourceFilters"):
            out.append(r.get("name") or r.get("id") or "?")
    return out


def now_ms() -> int:
    return int(time.time() * 1000)
