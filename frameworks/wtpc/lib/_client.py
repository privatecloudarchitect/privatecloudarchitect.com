"""frameworks/wtpc/lib/_client - the one way the estate reaches VCF Operations and vCenter.

Stdlib only. Two sessions, both configured entirely from the environment:

  with ops_client() as c:          # VCF Operations (/suite-api), bearer-authenticated
      ...
  with vcenter_client() as vc:     # vCenter (/api), session-authenticated - the tag planes only
      ...

The Operations bearer comes from the VCF 9.x unified-identity flow the handbook's Part 0 identity
chapter teaches: a long-lived api-token (minted in the operations console) exchanges at the
Identity Broker for a short-lived bearer via a custom OAuth grant. On a 401 mid-run the session
re-exchanges once and replays the request, so a converge that outlives one bearer keeps going.

Requests to the Operations internal surface (any path under /internal/) automatically carry the
X-Ops-API-use-unsupported header the web tier requires before serving that surface. The internal
surface is unsupported by the vendor and may change between releases; this estate touches it only
where the public API has a genuine gap (super-metric policy activation), and says so where it does.

Environment:
  OPS_HOST         (required)  VCF Operations FQDN
  OPS_BROKER_HOST  (optional)  Identity Broker FQDN; defaults to OPS_HOST
  OPS_REALM        (optional)  broker realm, default CUSTOMER
  OPS_API_TOKEN    (required)  the api-token from the operations console
  OPS_TLS_VERIFY   (optional)  TLS verification on by default; false for a self-signed lab CA
  VCENTER_HOST     (tag steps) vCenter FQDN
  VCENTER_USERNAME (tag steps) vCenter SSO user
  VCENTER_PASSWORD (tag steps) its password
  VCENTER_TLS_VERIFY (optional)  defaults to OPS_TLS_VERIFY

`policy_index(c)` is the near-universal first read (policy name -> id); it lives here because
almost every mutating script needs it to resolve `PCA - WTPC - Policy - <posture>` to an id.
"""
from __future__ import annotations

import base64
import json as _json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager

GRANT = "urn:custom:vcf:params:oauth:grant-type:api-token"
X_OPS_API_USE_UNSUPPORTED = "X-Ops-API-use-unsupported"


class HttpError(Exception):
    """A non-2xx response. Carries .status_code and the body text for the caller's message."""

    def __init__(self, method: str, url: str, status: int, body: str) -> None:
        super().__init__(f"{method} {url} -> HTTP {status}: {body[:200]}")
        self.status_code = status
        self.body = body


class Resp:
    """The response shape the estate's scripts consume: .json(), .status_code, .raise_for_status()."""

    def __init__(self, status: int, body: bytes) -> None:
        self.status_code = status
        self._body = body

    def json(self):
        return _json.loads(self._body) if self._body else None

    def raise_for_status(self) -> None:
        return None   # a session raises HttpError at request time; kept for call-site parity


def _require(var: str) -> str:
    v = os.environ.get(var)
    if not v:
        raise SystemExit(f"environment variable {var} is not set (see lib/_client.py for the contract)")
    return v


def _ctx(insecure: bool) -> ssl.SSLContext:
    return ssl._create_unverified_context() if insecure else ssl.create_default_context()


def _insecure(prefix: str, inherit: bool | None = None) -> bool:
    """True when TLS verification should be skipped for this plane. Verification is on by default;
    {prefix}_TLS_VERIFY=false (also 0/no/off) turns it off. The vCenter plane passes
    inherit=_insecure("OPS") to defer to Ops when its own flag is unset."""
    tv = os.environ.get(f"{prefix}_TLS_VERIFY")
    if tv is not None:
        return tv.strip().lower() in ("0", "false", "no", "off")
    return bool(inherit)


class _Session:
    """Shared request core: JSON in/out, query params, HttpError on any non-2xx status."""

    base = ""          # e.g. https://host/suite-api
    insecure = False
    timeout = 120

    def _headers(self, path: str) -> dict:
        raise NotImplementedError

    def _on_auth_failure(self) -> bool:
        """Refresh credentials if possible; return True to replay the request once."""
        return False

    def request(self, method: str, path: str, *, params=None, json=None) -> Resp:
        url = self.base + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = _json.dumps(json).encode() if json is not None else None
        for attempt in (1, 2):
            req = urllib.request.Request(url, data=data, method=method, headers=self._headers(path))
            try:
                with urllib.request.urlopen(req, context=_ctx(self.insecure), timeout=self.timeout) as r:
                    return Resp(r.status, r.read())
            except urllib.error.HTTPError as e:
                body = e.read().decode(errors="replace")
                if e.code == 401 and attempt == 1 and self._on_auth_failure():
                    continue
                raise HttpError(method, url, e.code, body) from None
        raise HttpError(method, url, 401, "auth retry exhausted")

    def get(self, path, *, params=None):
        return self.request("GET", path, params=params)

    def post(self, path, *, params=None, json=None):
        return self.request("POST", path, params=params, json=json)

    def put(self, path, *, params=None, json=None):
        return self.request("PUT", path, params=params, json=json)

    def patch(self, path, *, params=None, json=None):
        return self.request("PATCH", path, params=params, json=json)

    def delete(self, path, *, params=None):
        return self.request("DELETE", path, params=params)


class OpsSession(_Session):
    """VCF Operations /suite-api, bearer-authenticated via the broker api-token exchange."""

    def __init__(self) -> None:
        self.base = f"https://{_require('OPS_HOST')}/suite-api"
        self.insecure = _insecure("OPS")
        self._token = self._exchange()

    def _exchange(self) -> str:
        broker = os.environ.get("OPS_BROKER_HOST", os.environ["OPS_HOST"])
        realm = os.environ.get("OPS_REALM", "CUSTOMER")
        body = urllib.parse.urlencode({"grant_type": GRANT,
                                       "api_token": _require("OPS_API_TOKEN")}).encode()
        req = urllib.request.Request(
            f"https://{broker}/acs/t/{realm}/token", data=body, method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, context=_ctx(self.insecure), timeout=30) as r:
            return _json.loads(r.read())["access_token"]

    def _on_auth_failure(self) -> bool:
        self._token = self._exchange()
        return True

    def _headers(self, path: str) -> dict:
        h = {"Authorization": f"Bearer {self._token}",
             "Accept": "application/json", "Content-Type": "application/json"}
        if path.startswith("/internal/"):
            h[X_OPS_API_USE_UNSUPPORTED] = "true"
        return h


class VcSession(_Session):
    """vCenter Automation API (/api), session-token-authenticated - the tag definition and
    tag-association planes. The session id comes from POST /api/session under Basic auth."""

    def __init__(self) -> None:
        self.base = f"https://{_require('VCENTER_HOST')}/api"
        self.insecure = _insecure("VCENTER", inherit=_insecure("OPS"))
        self._sid = self._login()

    def _login(self) -> str:
        cred = f"{_require('VCENTER_USERNAME')}:{_require('VCENTER_PASSWORD')}"
        req = urllib.request.Request(
            self.base + "/session", data=b"", method="POST",
            headers={"Authorization": "Basic " + base64.b64encode(cred.encode()).decode()})
        with urllib.request.urlopen(req, context=_ctx(self.insecure), timeout=30) as r:
            return _json.loads(r.read())

    def _on_auth_failure(self) -> bool:
        self._sid = self._login()
        return True

    def _headers(self, path: str) -> dict:
        return {"vmware-api-session-id": self._sid,
                "Accept": "application/json", "Content-Type": "application/json"}


@contextmanager
def ops_client():
    """Open an Operations session (the common case): `with ops_client() as c: ...`."""
    yield OpsSession()


@contextmanager
def vcenter_client():
    """Open a vCenter session for the tag planes: `with vcenter_client() as vc: ...`."""
    yield VcSession()


def policy_index(c) -> dict[str, str]:
    """{policy name: id} for every policy - the standard first read a mutating script does to resolve a
    named WTPC policy (`PCA - WTPC - Policy - <posture>`) to its id."""
    return {p["name"]: p["id"] for p in
            c.get("/api/policies", params={"pageSize": 500, "_no_links": "true"}).json()["policySummaries"]}
