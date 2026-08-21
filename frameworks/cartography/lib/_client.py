"""frameworks/cartography/lib/_client - the two sessions the estate reaches its planes through.

Stdlib only. Both configured entirely from the environment:

  with vcfa_client() as a:       # VCF Automation - the CCI reads (namespaces, VirtualMachine CRDs)
      ...
  with vcenter_client() as vc:   # vCenter - the tag planes (define, assign, verify)
      ...

The VCF Automation session is the org session login the handbook's access-control chapter teaches:
Basic auth as user@org against /cloudapi/1.0.0/sessions yields the access token, and that token
authenticates the Consumption Interface reads as a Bearer. The session is minted fresh on every
run by construction, which also sidesteps a proxy quirk the reference estate hit: the CCI surface
rejects a cached bearer before its nominal expiry, so a fresh mint per run is the reliable shape.

Environment:
  VCFA_HOST         (required)  VCF Automation FQDN
  VCFA_ORG          (required)  organization name
  VCFA_USER         (required)  user (without the org suffix)
  VCFA_PASSWORD     (required)  its password
  VCFA_INSECURE=1   (optional)  skip TLS verification (self-signed lab CA only)
  VCENTER_HOST      (tag steps) vCenter FQDN
  VCENTER_USERNAME  (tag steps) vCenter SSO user
  VCENTER_PASSWORD  (tag steps) its password
  VCENTER_INSECURE  (optional)  defaults to VCFA_INSECURE
  VCENTER_TAGAUTH_USERNAME / VCENTER_TAGAUTH_PASSWORD
                    (optional)  a least-privilege tag-authority identity on the same vCenter,
                                used when the actuator is asked to assign as that identity
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


class HttpError(Exception):
    """A non-2xx response. Carries .status_code and the body text for the caller's message."""

    def __init__(self, method: str, url: str, status: int, body: str) -> None:
        super().__init__(f"{method} {url} -> HTTP {status}: {body[:200]}")
        self.status_code = status
        self.body = body


class Resp:
    """The response shape the estate's scripts consume: .json(), .status_code, .headers."""

    def __init__(self, status: int, body: bytes, headers: dict | None = None) -> None:
        self.status_code = status
        self._body = body
        self.headers = headers or {}

    def json(self):
        return _json.loads(self._body) if self._body else None


def _require(var: str) -> str:
    v = os.environ.get(var)
    if not v:
        raise SystemExit(f"environment variable {var} is not set (see lib/_client.py for the contract)")
    return v


def _ctx(insecure: bool) -> ssl.SSLContext:
    return ssl._create_unverified_context() if insecure else ssl.create_default_context()


class _Session:
    """Shared request core: JSON in/out, query params, HttpError on any non-2xx status."""

    base = ""
    insecure = False
    timeout = 60

    def _headers(self, path: str) -> dict:
        raise NotImplementedError

    def _on_auth_failure(self) -> bool:
        return False

    def request(self, method: str, path: str, *, params=None, json=None, absolute: bool = False) -> Resp:
        url = path if absolute else self.base + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = _json.dumps(json).encode() if json is not None else None
        for attempt in (1, 2):
            req = urllib.request.Request(url, data=data, method=method, headers=self._headers(path))
            try:
                with urllib.request.urlopen(req, context=_ctx(self.insecure), timeout=self.timeout) as r:
                    return Resp(r.status, r.read(), dict(r.headers))
            except urllib.error.HTTPError as e:
                body = e.read().decode(errors="replace")
                if e.code == 401 and attempt == 1 and self._on_auth_failure():
                    continue
                raise HttpError(method, url, e.code, body) from None
        raise HttpError(method, url, 401, "auth retry exhausted")

    def get(self, path, *, params=None, absolute: bool = False):
        return self.request("GET", path, params=params, absolute=absolute)

    def post(self, path, *, params=None, json=None):
        return self.request("POST", path, params=params, json=json)

    def delete(self, path, *, params=None):
        return self.request("DELETE", path, params=params)


class VcfaSession(_Session):
    """VCF Automation, org-session-authenticated. The access token authenticates both the
    /cloudapi surface and the Consumption Interface (/cci/kubernetes/...) as a Bearer, and the
    per-namespace kubernetes proxy endpoints the namespace objects advertise."""

    def __init__(self) -> None:
        self.host = _require("VCFA_HOST")
        self.base = f"https://{self.host}"
        self.insecure = os.environ.get("VCFA_INSECURE") == "1"
        self._token = self._login()

    def _login(self) -> str:
        cred = f"{_require('VCFA_USER')}@{_require('VCFA_ORG')}:{_require('VCFA_PASSWORD')}"
        req = urllib.request.Request(
            self.base + "/cloudapi/1.0.0/sessions", data=b"", method="POST",
            headers={"Authorization": "Basic " + base64.b64encode(cred.encode()).decode(),
                     "Accept": "application/json;version=40.0"})
        with urllib.request.urlopen(req, context=_ctx(self.insecure), timeout=30) as r:
            tok = r.headers.get("X-VMWARE-VCLOUD-ACCESS-TOKEN")
        if not tok:
            raise SystemExit("VCFA session login returned no access token (check org/user/password)")
        return tok

    def _on_auth_failure(self) -> bool:
        self._token = self._login()
        return True

    def _headers(self, path: str) -> dict:
        return {"Authorization": f"Bearer {self._token}",
                "Accept": "application/json", "Content-Type": "application/json"}


class VcSession(_Session):
    """vCenter Automation API (/api), session-token-authenticated - the tag definition,
    tag-association, and inventory planes. The session id comes from POST /api/session under
    Basic auth. Pass tag_authority=True to authenticate as the least-privilege tag-authority
    identity instead of the primary vCenter identity (same host, different principal)."""

    def __init__(self, *, tag_authority: bool = False) -> None:
        self.base = f"https://{_require('VCENTER_HOST')}/api"
        self.insecure = os.environ.get("VCENTER_INSECURE", os.environ.get("VCFA_INSECURE", "")) == "1"
        self._user_var = "VCENTER_TAGAUTH_USERNAME" if tag_authority else "VCENTER_USERNAME"
        self._pass_var = "VCENTER_TAGAUTH_PASSWORD" if tag_authority else "VCENTER_PASSWORD"
        self._sid = self._login()

    def _login(self) -> str:
        cred = f"{_require(self._user_var)}:{_require(self._pass_var)}"
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

    # -- the inventory + association reads the verifier needs -------------------------------
    def list_vms(self) -> dict[str, str]:
        """{vm name: moref} for every VM on this vCenter (GET /api/vcenter/vm)."""
        return {v["name"]: v["vm"] for v in self.get("/vcenter/vm").json() or []}

    def list_attached_tag_urns(self, moref: str) -> list[str]:
        """The tag URNs attached to one VM, via the tag-association plane."""
        body = self.post("/cis/tagging/tag-association",
                         params={"action": "list-attached-tags"},
                         json={"object_id": {"id": moref, "type": "VirtualMachine"}}).json()
        return body.get("value", body) if isinstance(body, dict) else (body or [])


@contextmanager
def vcfa_client():
    """Open a VCF Automation session: `with vcfa_client() as a: ...`."""
    yield VcfaSession()


@contextmanager
def vcenter_client(*, tag_authority: bool = False):
    """Open a vCenter session for the tag planes: `with vcenter_client() as vc: ...`."""
    yield VcSession(tag_authority=tag_authority)
