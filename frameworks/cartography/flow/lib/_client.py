"""frameworks/cartography/flow/lib/_client - the standalone vRNI session the flow lens reads through.

Stdlib only (urllib). VCF Operations for Networks (formerly vRNI) speaks the NetworkInsight scheme:
``POST /api/ni/auth/token`` with ``{username, password, domain:{domain_type}}`` returns a token that
authenticates every later call as ``Authorization: NetworkInsight <token>``. This is the vRNI-native,
self-contained path: it works with a local vRNI user regardless of whether the appliance is wired to
VCF Operations' unified identity, so an adopter needs nothing but an account.

Environment:
  VRNI_HOST       (required)  VCF Operations for Networks FQDN
  VRNI_USERNAME   (required)  vRNI user (a LOCAL user, or a domain user with VRNI_DOMAIN=LDAP:<domain>)
  VRNI_PASSWORD   (required)  its password
  VRNI_DOMAIN     (optional)  LOCAL (default) or LDAP:<domain>, e.g. LDAP:example.com
  VRNI_INSECURE=1 (optional)  skip TLS verification (self-signed lab CA only)
"""
from __future__ import annotations

import json as _json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from typing import Iterator

_API = "/api/ni"


class HttpError(Exception):
    """A non-2xx vRNI response. Carries .status_code and the body text for the caller's message."""

    def __init__(self, method: str, url: str, status: int, body: str) -> None:
        super().__init__(f"{method} {url} -> HTTP {status}: {body[:200]}")
        self.status_code = status
        self.body = body


def _require(var: str) -> str:
    v = os.environ.get(var)
    if not v:
        raise SystemExit(f"environment variable {var} is not set (see flow/lib/_client.py for the contract)")
    return v


def _ctx(insecure: bool) -> ssl.SSLContext:
    return ssl._create_unverified_context() if insecure else ssl.create_default_context()


class VrniSession:
    """A NetworkInsight-authenticated vRNI session. The flow lens needs exactly two reads: search
    entities of a type in a window, and batch-fetch their full details. Both are read-only."""

    timeout = 90

    def __init__(self) -> None:
        self.host = _require("VRNI_HOST")
        self.base = f"https://{self.host}{_API}"
        self.insecure = os.environ.get("VRNI_INSECURE") == "1"
        self._token = self._login()

    # ── auth ──────────────────────────────────────────────────────────────────
    def _login(self) -> str:
        raw = os.environ.get("VRNI_DOMAIN", "LOCAL")
        if raw.upper().startswith("LDAP"):
            value = raw.split(":", 1)[1] if ":" in raw else ""
            if not value:
                raise SystemExit("VRNI_DOMAIN=LDAP needs a domain value, e.g. LDAP:example.com")
            domain = {"domain_type": "LDAP", "value": value}
        else:
            domain = {"domain_type": "LOCAL"}
        payload = {"username": _require("VRNI_USERNAME"), "password": _require("VRNI_PASSWORD"),
                   "domain": domain}
        body = self._request("POST", "/auth/token", json=payload, authed=False)
        token = body.get("token") if isinstance(body, dict) else None
        if not token:
            raise SystemExit("vRNI /auth/token returned no token (check VRNI_USERNAME/PASSWORD/DOMAIN)")
        return token

    # ── request core ──────────────────────────────────────────────────────────
    def _request(self, method: str, path: str, *, json=None, authed: bool = True):
        url = self.base + path
        data = _json.dumps(json).encode() if json is not None else None
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if authed:
            headers["Authorization"] = f"NetworkInsight {self._token}"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, context=_ctx(self.insecure), timeout=self.timeout) as r:
                body = r.read()
        except urllib.error.HTTPError as e:
            raise HttpError(method, url, e.code, e.read().decode(errors="replace")) from None
        return _json.loads(body) if body else None

    # ── the two reads the flow lens needs ───────────────────────────────────────
    def search(self, entity_type: str, *, hours: int = 24, size: int = 5000) -> tuple[list[dict], int]:
        """Search entities of a type over the last ``hours``. Returns (refs, total_count); each ref
        is a lightweight ``{entity_id, entity_type}``."""
        now = int(time.time())
        body = self._request("POST", "/search", json={
            "entity_type": entity_type, "size": size,
            "time_range": {"start_time": now - hours * 3600, "end_time": now},
        }) or {}
        return body.get("results", []) or [], int(body.get("total_count", 0) or 0)

    def fetch(self, entity_type: str, entity_ids: list[str]) -> list[dict]:
        """Batch-fetch full entity details. vRNI wants a list of ``{entity_id, entity_type}`` objects;
        each response item carries its detail under ``entity`` (or, in the legacy flat shape, inline)."""
        if not entity_ids:
            return []
        body = self._request("POST", "/entities/fetch", json={
            "entity_ids": [{"entity_id": i, "entity_type": entity_type} for i in entity_ids],
        }) or {}
        items = body.get("results") or body.get("entities") or []
        return [(it.get("entity") if isinstance(it.get("entity"), dict) else it) for it in items]


@contextmanager
def vrni_client() -> Iterator[VrniSession]:
    """Open a read-only vRNI session: ``with vrni_client() as vrni: ...``."""
    yield VrniSession()
