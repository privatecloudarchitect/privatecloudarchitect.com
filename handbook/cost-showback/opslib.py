"""Shared plumbing for the ops-estate harness: broker exchange + Ops requests.

Stdlib only. The api-token -> bearer exchange is the VCF 9.x unified-identity
flow the sheet's Part 0 chapter teaches: a long-lived api-token (minted in the
operations console) exchanges at the Identity Broker for a ~30-minute bearer
via a custom OAuth grant, and that bearer authenticates /suite-api.

Environment:
  OPS_HOST        (required)  VCF Operations FQDN
  OPS_BROKER_HOST (optional)  Identity Broker FQDN; defaults to OPS_HOST
  OPS_REALM       (optional)  broker realm, default CUSTOMER
  OPS_API_TOKEN_FILE          a file holding the api-token from the operations console, mode 0600 (or
                              OPS_API_TOKEN, the value itself, which lands in the shell's history);
                              a file open to group or other is refused
  OPS_TLS_VERIFY  (optional)  TLS verification, on by default; set false for a self-signed CA
"""

import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request

GRANT = "urn:custom:vcf:params:oauth:grant-type:api-token"


def _ctx():
    # TLS verification is on by default; set OPS_TLS_VERIFY=false (or 0/no/off) for a self-signed CA.
    verify = os.environ.get("OPS_TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")
    return ssl.create_default_context() if verify else ssl._create_unverified_context()


def secret(name):
    """A secret from NAME_FILE (a file, mode 0600, its value stripped) or else NAME itself; None when neither is set.
    The file keeps a tier-0 token out of the shell's history and the process list. A file open to group or other is
    refused before it is read; the refusal names the variable and the fix, never the file's content."""
    path = os.environ.get(f"{name}_FILE")
    if path:
        with open(path, encoding="utf-8") as f:
            mode = os.fstat(f.fileno()).st_mode & 0o777
            # Windows makes the mode from the read-only flag alone, so it has no group or other bits to judge.
            if mode & 0o077 and os.name != "nt":
                raise PermissionError(f"{name}_FILE names a file of mode {mode:04o}, open to group or other: "
                                      f'run chmod 600 "${name}_FILE" and try again (the file was not read)')
            return f.read().strip()
    return os.environ.get(name) or None


def bearer():
    host = os.environ["OPS_HOST"]
    broker = os.environ.get("OPS_BROKER_HOST", host)
    realm = os.environ.get("OPS_REALM", "CUSTOMER")
    token = secret("OPS_API_TOKEN")
    if not token:
        raise KeyError("OPS_API_TOKEN_FILE (or OPS_API_TOKEN) is not set")
    body = urllib.parse.urlencode({"grant_type": GRANT, "api_token": token}).encode()
    req = urllib.request.Request(
        f"https://{broker}/acs/t/{realm}/token", data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, context=_ctx(), timeout=30) as r:
        return json.loads(r.read())["access_token"]


def ops(method, path, tok, body=None, params=None):
    """One /suite-api request. Returns (status, parsed-json-or-None)."""
    host = os.environ["OPS_HOST"]
    url = f"https://{host}/suite-api{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {tok}", "Accept": "application/json",
        "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, context=_ctx(), timeout=60) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw.decode(errors="replace")[:300]}
