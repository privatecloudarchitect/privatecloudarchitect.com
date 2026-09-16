#!/usr/bin/env python3
"""doors.py - which token opens which door, read on your own estate.

Mints each token the documented way, issues ONE harmless read per surface, and prints one row per pair:
surface, token, HTTP status, verdict. Read-only against the platform: nothing is created or changed, except
that if VCF Automation answers a refresh-token grant with a different refresh token, the script writes that
value back to the file it came from (see VCFA_REFRESH_TOKEN_FILE). Stdlib only. Never prints a token value.

Surfaces are chosen by which environment variables are set; unset ones are skipped and reported as such.

  The broker (required): OPS_HOST, OPS_API_TOKEN  (OPS_BROKER_HOST, OPS_REALM, OPS_TLS_VERIFY optional)
      VCF Operations         GET /suite-api/api/resources?pageSize=1         broker bearer      expect accepted
      NSX          NSX_HOST  GET /api/v1/node                                broker bearer      expect accepted
      Real-Time Metrics RTM_HOST   GET /data-query-service/api/v1/metadata   broker bearer      expect refused
                                                                             service JWT        expect accepted
      Fleet lifecycle   FLEET_HOST GET /fleet-lcm/v1/components              its own JWT        expect accepted
                                                                             the metrics JWT    expect refused (audience per service;
                                                                             the /health probe answers any JWT and is shown for contrast)
      Log management    LOGS_HOST  GET /api/v2/agent/groups (X-JWT-Token)    its own JWT        expect accepted
                        (host:port, the API port is 9543 on the build this was proven on)
  VCF Automation (VCFA_HOST, VCFA_ORG):
      the tenant OAuth grant   VCFA_REFRESH_TOKEN_FILE   a file holding the refresh token, mode 0600;
                               if the answer carries a different refresh token the file is rewritten in place
                               GET /cloudapi/1.0.0/sessions/current/rights   the count of effective rights
                               GET /iaas/api/about                            expect accepted
                               GET /cci/kubernetes/api                        expect accepted
      the Basic session login  VCFA_USER (user@org), VCFA_PASSWORD
                               POST /cloudapi/1.0.0/sessions -> the bearer in X-VMWARE-VCLOUD-ACCESS-TOKEN
                               GET /cloudapi/1.0.0/sessions/current/rights   the count, to compare: the arrival rule
      the provider api-token   VCFA_PROVIDER_REFRESH_TOKEN_FILE  (POST /oauth/provider/token)
                               GET /cloudapi/1.0.0/sessions/current/rights   the count
                               GET /cci/kubernetes/api                        expect refused (a tenant surface)
  vCenter (VC_HOST, VC_USER, VC_PASSWORD):  POST /api/session, then GET /api/vcenter/datacenter    expect accepted
  SDDC Manager (SDDC_HOST, SDDC_USER, SDDC_PASSWORD): POST /v1/tokens, then GET /v1/sddc-managers  expect accepted

Verdict: accepted (status below 400), refused (401 or 403), other. Where the Platform identity chapter states
an expectation, the row says MATCH or DIFFERS; a DIFFERS row is worth a report, because the chapter's matrix
is built from exactly these reads. Exit 0 when every attempted read returned an HTTP status, 1 when a
transport error stopped one, 2 when the broker mint failed.
"""

import base64
import json
import os
import ssl
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request

from opslib import _ctx, bearer, ops
from rtmlib import service_jwt

CLOUDAPI_ACCEPT = "application/json;version=9.1.0"
ROWS = []


def req(method, url, headers=None, data=None, timeout=60):
    """One request. Returns (status, body, response headers); a transport error returns (None, message, {})."""
    r = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(r, context=_ctx(), timeout=timeout) as resp:
            raw = resp.read()
            try:
                body = json.loads(raw) if raw else None
            except Exception:  # noqa: BLE001
                body = raw.decode(errors="replace")[:300]
            return resp.status, body, dict(resp.headers)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            body = json.loads(raw)
        except Exception:  # noqa: BLE001
            body = raw.decode(errors="replace")[:300]
        return e.code, body, dict(e.headers)
    except (urllib.error.URLError, OSError, ssl.SSLError) as e:
        return None, f"{type(e).__name__}: {e}", {}


def verdict(status):
    if status is None:
        return "no answer"
    if status < 400:
        return "accepted"
    if status in (401, 403):
        return "refused"
    return "other"


def row(surface, token, status, expect=None, note=""):
    v = verdict(status)
    mark = "" if expect is None or status is None else ("MATCH" if v == expect else f"DIFFERS (chapter says {expect})")
    ROWS.append((surface, token, status, v, mark, note))
    print(f"  {surface:<34} {token:<26} {str(status) if status is not None else '---':>4}  {v:<9} {mark:<26} {note}")


def read_file_token(path):
    with open(path, encoding="utf-8") as f:
        return f.read().strip()


def write_file_token(path, value):
    """Rewrite the credential file atomically, owner-only, so the rotated token is what the next run holds."""
    d = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".rotating-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(value + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def vcfa_refresh_grant(host, path, token_file):
    """The RFC 6749 refresh-token grant; the platform answers with a bearer AND a new refresh token."""
    body = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": read_file_token(token_file)}).encode()
    st, data, _ = req("POST", f"https://{host}{path}", {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}, body)
    if st != 200 or not isinstance(data, dict) or not data.get("access_token"):
        print(f"  {path}: HTTP {st}: {str(data)[:160]}")
        return None
    sent = read_file_token(token_file); returned = data.get("refresh_token")
    if returned and returned != sent:
        write_file_token(token_file, returned)
        print(f"  {path}: bearer minted; the refresh token ROTATED and the file was rewritten (the old value is dead)")
    elif returned:
        print(f"  {path}: bearer minted; a refresh token came back with it and is the same value you sent (no rotation on this build)")
    else:
        print(f"  {path}: bearer minted; no refresh token in the answer")
    return data["access_token"]


def rights_count(host, tok):
    st, data, _ = req("GET", f"https://{host}/cloudapi/1.0.0/sessions/current/rights?pageSize=1", {"Authorization": f"Bearer {tok}", "Accept": CLOUDAPI_ACCEPT})
    n = data.get("resultTotal") if st == 200 and isinstance(data, dict) else None
    return st, n


def main():
    print("doors.py: one harmless read per pair; tokens minted per run and never printed\n")
    # ---- the broker and the surfaces its bearer reaches, or does not
    try:
        tok = bearer()
    except Exception as e:  # noqa: BLE001
        print(f"FATAL: the broker exchange failed: {type(e).__name__}: {e}")
        print("       an EXPIRED api-token answers HTTP 500 here, not 401: check its expiry before the service")
        sys.exit(2)
    print("broker bearer minted from OPS_API_TOKEN\n")
    st, _ = ops("GET", "/api/resources", tok, params={"pageSize": 1})
    row("VCF Operations", "broker bearer", st, "accepted")
    if os.environ.get("NSX_HOST"):
        st, _, _ = req("GET", f"https://{os.environ['NSX_HOST']}/api/v1/node", {"Authorization": f"Bearer {tok}", "Accept": "application/json"})
        row("NSX", "broker bearer", st, "accepted")
    else:
        print("  NSX                                skipped: NSX_HOST not set")
    rtm_jwt = None
    if os.environ.get("RTM_HOST"):
        rtm = f"https://{os.environ['RTM_HOST']}/data-query-service/api/v1/metadata"
        st, _, _ = req("GET", rtm, {"Authorization": f"Bearer {tok}", "Accept": "application/json"})
        row("Real-Time Metrics", "broker bearer", st, "refused", "the fleet plane refuses the broker's bearer")
        try:
            rtm_jwt = service_jwt(tok, "VCF_VODAP")
            st, _, _ = req("GET", rtm, {"Authorization": f"Bearer {rtm_jwt}", "Accept": "application/json"})
            row("Real-Time Metrics", "service JWT (VCF_VODAP)", st, "accepted")
        except SystemExit as e:
            print(f"  Real-Time Metrics service JWT: {e}")
    else:
        print("  Real-Time Metrics                  skipped: RTM_HOST not set")
    if os.environ.get("FLEET_HOST"):
        fleet = f"https://{os.environ['FLEET_HOST']}/fleet-lcm/v1/components"
        health = f"https://{os.environ['FLEET_HOST']}/fleet-lcm/v1/health"
        fjwt = None
        try:
            fjwt = service_jwt(tok, "VCF_FLEET_LCM")
            st, _, _ = req("GET", fleet, {"Authorization": f"Bearer {fjwt}", "Accept": "application/json"})
            row("Fleet lifecycle, components", "service JWT (VCF_FLEET_LCM)", st, "accepted")
        except SystemExit as e:
            print(f"  Fleet lifecycle service JWT: {e}")
        if rtm_jwt:
            st, _, _ = req("GET", fleet, {"Authorization": f"Bearer {rtm_jwt}", "Accept": "application/json"})
            row("Fleet lifecycle, components", "the metrics service's JWT", st, "refused", "audience is per service")
            st, _, _ = req("GET", health, {"Authorization": f"Bearer {rtm_jwt}", "Accept": "application/json"})
            row("Fleet lifecycle, health probe", "the metrics service's JWT", st, None, "the health probe does not check the audience")
        if fjwt and os.environ.get("RTM_HOST"):
            st, _, _ = req("GET", f"https://{os.environ['RTM_HOST']}/data-query-service/api/v1/metadata", {"Authorization": f"Bearer {fjwt}", "Accept": "application/json"})
            row("Real-Time Metrics", "the fleet service's JWT", st, "refused", "audience is per service")
    else:
        print("  Fleet lifecycle                    skipped: FLEET_HOST not set")
    if os.environ.get("LOGS_HOST"):
        try:
            ljwt = service_jwt(tok, "VCF_OPS_LI")
            st, _, _ = req("GET", f"https://{os.environ['LOGS_HOST']}/api/v2/agent/groups", {"X-JWT-Token": ljwt, "Accept": "application/json"})
            row("Log management", "service JWT (VCF_OPS_LI)", st, "accepted", "sent as X-JWT-Token")
        except SystemExit as e:
            print(f"  Log management service JWT: {e}")
    else:
        print("  Log management                     skipped: LOGS_HOST not set")
    # ---- VCF Automation: three login paths, one principal
    host, org = os.environ.get("VCFA_HOST"), os.environ.get("VCFA_ORG")
    counts = {}
    if host and org and os.environ.get("VCFA_REFRESH_TOKEN_FILE"):
        print("\nVCF Automation, the tenant OAuth grant")
        t = vcfa_refresh_grant(host, f"/oauth/tenant/{org}/token", os.environ["VCFA_REFRESH_TOKEN_FILE"])
        if t:
            st, n = rights_count(host, t); counts["OAuth grant"] = n
            row("VCF Automation, rights", "tenant OAuth bearer", st, "accepted", f"{n} effective rights" if n is not None else "")
            st, _, _ = req("GET", f"https://{host}/iaas/api/about", {"Authorization": f"Bearer {t}", "Accept": "application/json"})
            row("VCF Automation, deployment plane", "tenant OAuth bearer", st, "accepted")
            st, _, _ = req("GET", f"https://{host}/cci/kubernetes/api", {"Authorization": f"Bearer {t}", "Accept": "application/json"})
            row("VCF Automation, control plane", "tenant OAuth bearer", st, "accepted")
    else:
        print("\n  VCF Automation, tenant OAuth grant   skipped: VCFA_HOST, VCFA_ORG, VCFA_REFRESH_TOKEN_FILE not all set")
    if host and os.environ.get("VCFA_USER") and os.environ.get("VCFA_PASSWORD"):
        print("\nVCF Automation, the Basic session login")
        cred = base64.b64encode(f"{os.environ['VCFA_USER']}:{os.environ['VCFA_PASSWORD']}".encode()).decode()
        st, data, hdrs = req("POST", f"https://{host}/cloudapi/1.0.0/sessions", {"Authorization": f"Basic {cred}", "Accept": CLOUDAPI_ACCEPT})
        t = {k.lower(): v for k, v in hdrs.items()}.get("x-vmware-vcloud-access-token")
        row("VCF Automation, session login", "Basic (user@org)", st, "accepted", "bearer returned in a response header" if t else "")
        if t:
            st, n = rights_count(host, t); counts["Basic session"] = n
            row("VCF Automation, rights", "session bearer", st, "accepted", f"{n} effective rights" if n is not None else "")
    else:
        print("\n  VCF Automation, Basic session login   skipped: VCFA_USER and VCFA_PASSWORD not set")
    if host and os.environ.get("VCFA_PROVIDER_REFRESH_TOKEN_FILE"):
        print("\nVCF Automation, the provider api-token")
        t = vcfa_refresh_grant(host, "/oauth/provider/token", os.environ["VCFA_PROVIDER_REFRESH_TOKEN_FILE"])
        if t:
            st, n = rights_count(host, t); counts["provider api-token"] = n
            row("VCF Automation, provider rights", "provider bearer", st, "accepted", f"{n} effective rights" if n is not None else "")
            st, _, _ = req("GET", f"https://{host}/cci/kubernetes/api", {"Authorization": f"Bearer {t}", "Accept": "application/json"})
            row("VCF Automation, control plane", "provider bearer", st, "refused", "a tenant surface")
    else:
        print("\n  VCF Automation, provider api-token    skipped: VCFA_PROVIDER_REFRESH_TOKEN_FILE not set")
    if len(counts) > 1:
        print("\n  the arrival rule, in numbers: " + " · ".join(f"{k}: {v}" for k, v in counts.items()))
    # ---- components with a flow of their own
    if os.environ.get("VC_HOST") and os.environ.get("VC_USER") and os.environ.get("VC_PASSWORD"):
        print("\nvCenter, its own session")
        cred = base64.b64encode(f"{os.environ['VC_USER']}:{os.environ['VC_PASSWORD']}".encode()).decode()
        st, sid, _ = req("POST", f"https://{os.environ['VC_HOST']}/api/session", {"Authorization": f"Basic {cred}", "Accept": "application/json"})
        row("vCenter, session mint", "Basic", st, "accepted", "a session id in the body, no Bearer prefix" if st and st < 400 else "")
        if st and st < 400 and isinstance(sid, str):
            st, _, _ = req("GET", f"https://{os.environ['VC_HOST']}/api/vcenter/datacenter", {"vmware-api-session-id": sid, "Accept": "application/json"})
            row("vCenter API", "session id", st, "accepted")
    else:
        print("\n  vCenter                              skipped: VC_HOST, VC_USER, VC_PASSWORD not all set")
    if os.environ.get("SDDC_HOST") and os.environ.get("SDDC_USER") and os.environ.get("SDDC_PASSWORD"):
        print("\nSDDC Manager, its own bearer")
        body = json.dumps({"username": os.environ["SDDC_USER"], "password": os.environ["SDDC_PASSWORD"]}).encode()
        st, data, _ = req("POST", f"https://{os.environ['SDDC_HOST']}/v1/tokens", {"Content-Type": "application/json", "Accept": "application/json"}, body)
        t = data.get("accessToken") if st == 200 and isinstance(data, dict) else None
        row("SDDC Manager, token mint", "username and password", st, "accepted")
        if t:
            st, _, _ = req("GET", f"https://{os.environ['SDDC_HOST']}/v1/sddc-managers", {"Authorization": f"Bearer {t}", "Accept": "application/json"})
            row("SDDC Manager API", "its bearer", st, "accepted")
    else:
        print("\n  SDDC Manager                         skipped: SDDC_HOST, SDDC_USER, SDDC_PASSWORD not all set")
    print(f"\n{len(ROWS)} pairs read; {sum(1 for r in ROWS if r[4].startswith('DIFFERS'))} differ from the chapter; {sum(1 for r in ROWS if r[2] is None)} without an answer")
    sys.exit(1 if any(r[2] is None for r in ROWS) else 0)


if __name__ == "__main__":
    main()
