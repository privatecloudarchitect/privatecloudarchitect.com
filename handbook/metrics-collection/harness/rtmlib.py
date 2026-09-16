"""Real-Time Metrics plumbing: the per-service JWT exchange and the data-query-service reads.

Stdlib only. The services that run on the VCF services runtime refuse the suite-api bearer;
VCF Operations mints a service-scoped JWT instead, the recipe the Real-Time Metrics OpenAPI
description documents:
  1. any valid suite-api session (the api-token bearer from opslib.py works),
  2. GET /suite-api/api/integrations/services and pick the entry whose type is VCF_VODAP,
  3. POST /suite-api/api/auth/token/exchange {"serviceKeys": [key]} and read jwtToken.
The JWT lasted 35 minutes on the build it was proven on; re-mint on a schedule, never cache it.

Environment (in addition to opslib.py's):
  RTM_HOST  (required)  the VCF instance services FQDN that fronts /data-query-service
"""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from opslib import _ctx, ops


def service_jwt(tok, service_type="VCF_VODAP"):
    """Exchange the suite-api session for a JWT scoped to one registered service."""
    st, body = ops("GET", "/api/integrations/services", tok)
    if st != 200:
        raise SystemExit(f"FATAL: GET /api/integrations/services -> HTTP {st}")
    keys = [s.get("key") for s in (body or {}).get("servicesDetails", [])
            if s.get("type") == service_type]
    if not keys:
        raise SystemExit(f"FATAL: no registered service of type {service_type}; "
                         "is Real-Time Metrics deployed on this VCF instance?")
    st, body = ops("POST", "/api/auth/token/exchange", tok, body={"serviceKeys": [keys[0]]})
    jwt = (body or {}).get("jwtToken") if st == 200 else None
    if not jwt:
        raise SystemExit(f"FATAL: POST /api/auth/token/exchange -> HTTP {st}")
    return jwt


def rtm_get(path, jwt, params=None):
    """One data-query-service request. Returns (status, parsed-json-or-None, seconds)."""
    host = os.environ["RTM_HOST"]
    url = f"https://{host}/data-query-service{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {jwt}", "Accept": "application/json"})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, context=_ctx(), timeout=60) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None), time.monotonic() - t0
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw), time.monotonic() - t0
        except Exception:
            return e.code, {"raw": raw.decode(errors="replace")[:300]}, time.monotonic() - t0
