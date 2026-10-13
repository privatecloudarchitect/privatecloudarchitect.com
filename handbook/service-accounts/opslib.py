"""Shared plumbing for the ops-estate harness: broker exchange + Ops requests.

Stdlib only. The api-token -> bearer exchange is the VCF 9.x unified-identity
flow the sheet's Part 0 chapter teaches: a long-lived api-token (minted in the
operations console) exchanges at the Identity Broker for a ~30-minute bearer
via a custom OAuth grant, and that bearer authenticates /suite-api.

Environment:
  OPS_HOST        (required)  VCF Operations FQDN
  OPS_BROKER_HOST (optional)  Identity Broker FQDN; defaults to OPS_HOST
  BROKER_TENANT   (optional)  the broker tenant, the realm's path segment at the broker, default CUSTOMER;
                              not the realm's name (OPS_REALM, its earlier name, is still read)
  OPS_API_TOKEN_FILE          a file holding the api-token from the operations console, mode 0600 (or
                              OPS_API_TOKEN, the value itself, which lands in the shell's history)
  OPS_TLS_VERIFY  (optional)  TLS verification, on by default; set false for a self-signed CA
"""

import json
import os
import ssl
import sys
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
    The file keeps a tier-0 token out of the shell's history and the process list."""
    path = os.environ.get(f"{name}_FILE")
    if path:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    return os.environ.get(name) or None


def broker_tenant():
    """The broker tenant: the realm's path segment at the broker (/acs/t/<tenant>/), CUSTOMER unless set; not the realm's
    name. OPS_REALM, its earlier name, is still read when BROKER_TENANT is unset, with a notice."""
    if os.environ.get("OPS_REALM") and not os.environ.get("BROKER_TENANT"):
        print("note: OPS_REALM is now BROKER_TENANT (the broker tenant, not the realm's name); reading OPS_REALM this time",
              file=sys.stderr)
    return os.environ.get("BROKER_TENANT") or os.environ.get("OPS_REALM") or "CUSTOMER"


def bearer():
    host = os.environ["OPS_HOST"]
    broker = os.environ.get("OPS_BROKER_HOST", host)
    tenant = broker_tenant()
    token = secret("OPS_API_TOKEN")
    if not token:
        raise KeyError("OPS_API_TOKEN_FILE (or OPS_API_TOKEN) is not set")
    body = urllib.parse.urlencode({"grant_type": GRANT, "api_token": token}).encode()
    req = urllib.request.Request(
        f"https://{broker}/acs/t/{tenant}/token", data=body, method="POST",
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
