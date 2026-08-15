"""Shared plumbing for the ops-estate harness: broker exchange + Ops requests.

Stdlib only. The api-token -> bearer exchange is the VCF 9.x unified-identity
flow the sheet's Part 0 chapter teaches: a long-lived api-token (minted in the
operations console) exchanges at the Identity Broker for a ~30-minute bearer
via a custom OAuth grant, and that bearer authenticates /suite-api.

Environment:
  OPS_HOST        (required)  VCF Operations FQDN
  OPS_BROKER_HOST (optional)  Identity Broker FQDN; defaults to OPS_HOST
  OPS_REALM       (optional)  broker realm, default CUSTOMER
  OPS_API_TOKEN   (required)  the api-token from the operations console
  OPS_INSECURE=1  (optional)  skip TLS verification (self-signed lab CA)
"""

import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request

GRANT = "urn:custom:vcf:params:oauth:grant-type:api-token"


def _ctx():
    if os.environ.get("OPS_INSECURE") == "1":
        return ssl._create_unverified_context()
    return ssl.create_default_context()


def bearer():
    host = os.environ["OPS_HOST"]
    broker = os.environ.get("OPS_BROKER_HOST", host)
    realm = os.environ.get("OPS_REALM", "CUSTOMER")
    token = os.environ["OPS_API_TOKEN"]
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
