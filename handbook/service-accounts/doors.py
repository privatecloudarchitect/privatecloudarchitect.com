#!/usr/bin/env python3
"""doors.py - which token opens which door, read on your own estate.

Mints each token the documented way, issues ONE harmless read per surface, and prints one row per pair:
surface, token, HTTP status, verdict. Read-only against the platform: nothing is created or changed, except
that if VCF Automation answers a refresh-token grant with a different refresh token, the script writes that
value back to the file it came from (see VCFA_REFRESH_TOKEN_FILE). Stdlib only. Never prints a token value.

Surfaces are chosen by which environment variables are set; unset ones are skipped and reported as such.

  The broker (required): OPS_HOST, OPS_API_TOKEN_FILE  (OPS_BROKER_HOST, BROKER_TENANT, OPS_TLS_VERIFY optional)
  Every password and token below is read from NAME_FILE (a file, mode 0600) when it is set, or else from NAME itself.
      VCF Operations         GET /suite-api/api/resources?pageSize=1         broker bearer      expect accepted
      NSX          NSX_HOST  GET /api/v1/node                                broker bearer      expect accepted
      Real-Time Metrics RTM_HOST   GET /data-query-service/api/v1/metadata   broker bearer      expect refused
                                                                             service JWT        expect accepted
      Fleet lifecycle   FLEET_HOST GET /fleet-lcm/v1/components              its own JWT        expect accepted
                                                                             the metrics JWT    expect refused (audience checked HERE;
                                                                             the reverse pair is accepted: the metrics
                                                                             service does not check, so mint one per
                                                                             service because at least one of them does;
                                                                             the /health probe answers any JWT and is shown for contrast)
      Log management    LOGS_HOST  GET /api/v2/agent/groups (X-JWT-Token)    its own JWT        expect accepted
                        (host:port, the API port is 9543 on the build this was proven on)
  VCF Automation (VCFA_HOST, VCFA_ORG):
      the tenant OAuth grant   VCFA_REFRESH_TOKEN_FILE   a file holding the refresh token, mode 0600;
                               if the answer carries a different refresh token the file is rewritten in place
                               GET /cloudapi/1.0.0/sessions/current/rights   the count of effective rights
                               GET /iaas/api/about                            expect accepted
                               GET /cci/kubernetes/api                        expect accepted
      the Basic session login  VCFA_USER (user@org), VCFA_PASSWORD_FILE
                               POST /cloudapi/1.0.0/sessions -> the bearer in X-VMWARE-VCLOUD-ACCESS-TOKEN
                               GET /cloudapi/1.0.0/sessions/current/rights   the count, to compare: the arrival rule
      the provider api-token   VCFA_PROVIDER_REFRESH_TOKEN_FILE  (POST /oauth/provider/token)
                               GET /cloudapi/1.0.0/sessions/current/rights   the count
                               GET /cci/kubernetes/api                        expect refused (a tenant surface)
  vCenter (VC_HOST, VC_USER, VC_PASSWORD_FILE):  POST /api/session, then GET /api/vcenter/datacenter    expect accepted
  SDDC Manager (SDDC_HOST, SDDC_USER, SDDC_PASSWORD_FILE): POST /v1/tokens, then GET /v1/sddc-managers  expect accepted

Verdict: accepted (status below 400), refused (401 or 403), other. Where the Platform identity chapter states
an expectation, the row says MATCH or DIFFERS; a DIFFERS row is worth a report, because the chapter's matrix
is built from exactly these reads. A DIFFERS row is counted on the summary line and does not change the exit: it is
the chapter's to correct, not a fault on your estate. A surface you configured whose own token could not be minted
(a service JWT, or a VCF Automation refresh-token grant that returned no bearer) has doors nobody read: the run prints
NOT READ for it and exits 3, never 0.

Use:  python3 doors.py           it takes no argument; --help prints this
Exit: 0 every door of every surface configured was read and returned an HTTP status
      3 a read failed: a transport error stopped one (no status), the broker mint failed, a configured surface's own
        token could not be minted so its doors were not read, or an error the script did not expect
      5 a usage error: an argument it does not take, OPS_HOST or the api-token unset, a credential file (any NAME_FILE,
        VCFA_REFRESH_TOKEN_FILE, VCFA_PROVIDER_REFRESH_TOKEN_FILE) that cannot be read, or a Python older than 3.10
A refused mint names no cause. A deleted or rotated api-token was refused at the broker with HTTP 500 on the 9.1.0
run of 2026-09-16, and a deleted API client token with HTTP 400 on 9.1.1 (X-153, X-190).
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import ssl
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request

from opslib import _ctx, bearer, ops, secret
from rtmlib import service_jwt

CLOUDAPI_ACCEPT = "application/json;version=9.1.0"
ROWS = []
NOT_READ = []  # each configured surface whose own token could not be minted: its doors were not read
EXIT_UNREAD, EXIT_USAGE = 3, 5
# The credential files the run may read. Each is read once before any call, so one that cannot be read is a usage error
# (exit 5), never an error met halfway through a run.
SECRET_NAMES = ("VCFA_PASSWORD", "VC_PASSWORD", "SDDC_PASSWORD")
TOKEN_FILES = ("VCFA_REFRESH_TOKEN_FILE", "VCFA_PROVIDER_REFRESH_TOKEN_FILE")


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


def ops_read(method, path, tok, **kw):
    """opslib.ops, with a transport error returned as no status (a failed read the exit counts), never raised."""
    try:
        return ops(method, path, tok, **kw)
    except (urllib.error.URLError, OSError, ssl.SSLError) as e:
        print(f"  {path}: no answer ({type(e).__name__})")
        return None, None


def not_read(surface, why):
    """A configured surface whose doors were not read: printed now, counted on the summary, and exit 3."""
    NOT_READ.append((surface, why))
    print(f"  NOT READ: {surface}: {why}; its doors were not read")


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
        not_read(f"VCF Automation, {path}", f"the refresh-token grant returned no bearer (HTTP {st})")
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


class _Parser(argparse.ArgumentParser):
    """argparse's own refusal exits 2; here a usage error exits 5, as on every identity companion."""

    def error(self, message):
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        raise SystemExit(EXIT_USAGE)


def credentials_readable():
    """The first credential file named but unreadable, as (variable, error name), or None. Read before any call."""
    for name in SECRET_NAMES:
        try:
            secret(name)
        except OSError as e:
            return f"{name}_FILE", type(e).__name__
    for var in TOKEN_FILES:
        if os.environ.get(var):
            try:
                read_file_token(os.environ[var])
            except OSError as e:
                return var, type(e).__name__
    return None


def main(argv: list[str] | None = None) -> int:
    """The run, with three guards around it: a Python older than 3.10 is refused (exit 5), an argument the script does
    not take is a usage error (exit 5) before anything is read, and an error the script did not expect exits 3, the
    code for a read that failed."""
    if sys.version_info < (3, 10):  # noqa: UP036  the script is run by readers on their own Python
        print("doors.py needs Python 3.10 or later", file=sys.stderr)
        return EXIT_USAGE
    _Parser(prog="doors.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)
    try:
        return _run()
    except Exception as e:  # noqa: BLE001  the last guard: whatever was not expected is not known, so exit 3
        print(f"the run stopped on an error it did not expect: {type(e).__name__}: {str(e)[:160]} (exit 3)", file=sys.stderr)
        return EXIT_UNREAD


def _run():
    ROWS.clear()
    NOT_READ.clear()
    try:
        held = secret("OPS_API_TOKEN")
    except OSError as e:
        print(f"FATAL: OPS_API_TOKEN_FILE could not be read: {type(e).__name__}", file=sys.stderr)
        return EXIT_USAGE
    if not os.environ.get("OPS_HOST") or not held:
        print("FATAL: OPS_HOST and OPS_API_TOKEN_FILE (or OPS_API_TOKEN) are required: the broker's bearer is the first "
              "door read", file=sys.stderr)
        return EXIT_USAGE
    bad = credentials_readable()
    if bad:
        print(f"FATAL: {bad[0]} could not be read: {bad[1]}; nothing was sent", file=sys.stderr)
        return EXIT_USAGE
    print("doors.py: one harmless read per pair; tokens minted per run and never printed\n")
    # ---- the broker and the surfaces its bearer reaches, or does not
    try:
        tok = bearer()
    except Exception as e:  # noqa: BLE001
        print(f"FATAL: the broker exchange failed: {type(e).__name__}: {e}")
        print("       the broker refused the api-token; a deleted API client token was refused with HTTP 400 on 9.1.1 "
              "(HTTP 500 on the 9.1.0 run of 2026-09-16): check the token still exists, then its expiry, before the service")
        return EXIT_UNREAD
    print("broker bearer minted from the api-token\n")
    st, _ = ops_read("GET", "/api/resources", tok, params={"pageSize": 1})
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
        except (SystemExit, urllib.error.URLError, OSError) as e:  # rtmlib exits on a refused mint
            print(f"  Real-Time Metrics service JWT: {e}")
            not_read("Real-Time Metrics, service JWT (VCF_VODAP)", "the service JWT could not be minted")
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
        except (SystemExit, urllib.error.URLError, OSError) as e:  # rtmlib exits on a refused mint
            print(f"  Fleet lifecycle service JWT: {e}")
            not_read("Fleet lifecycle, service JWT (VCF_FLEET_LCM)", "the service JWT could not be minted")
        if rtm_jwt:
            st, _, _ = req("GET", fleet, {"Authorization": f"Bearer {rtm_jwt}", "Accept": "application/json"})
            row("Fleet lifecycle, components", "the metrics service's JWT", st, "refused", "audience is per service")
            st, _, _ = req("GET", health, {"Authorization": f"Bearer {rtm_jwt}", "Accept": "application/json"})
            row("Fleet lifecycle, health probe", "the metrics service's JWT", st, None, "the health probe does not check the audience")
        if fjwt and os.environ.get("RTM_HOST"):
            st, _, _ = req("GET", f"https://{os.environ['RTM_HOST']}/data-query-service/api/v1/metadata", {"Authorization": f"Bearer {fjwt}", "Accept": "application/json"})
            # The chapter records the asymmetry rather than a symmetric rule: Fleet lifecycle refuses a JWT
            # minted for another service and the metrics service's metadata read does not. Expecting
            # "refused" here made this harness disagree with the page it exists to check, which is a
            # drift-detector reporting drift against itself.
            row("Real-Time Metrics", "the fleet service's JWT", st, "accepted",
                "this one does not check the audience; Fleet lifecycle does")
    else:
        print("  Fleet lifecycle                    skipped: FLEET_HOST not set")
    if os.environ.get("LOGS_HOST"):
        try:
            ljwt = service_jwt(tok, "VCF_OPS_LI")
            st, _, _ = req("GET", f"https://{os.environ['LOGS_HOST']}/api/v2/agent/groups", {"X-JWT-Token": ljwt, "Accept": "application/json"})
            row("Log management", "service JWT (VCF_OPS_LI)", st, "accepted", "sent as X-JWT-Token")
        except (SystemExit, urllib.error.URLError, OSError) as e:  # rtmlib exits on a refused mint
            print(f"  Log management service JWT: {e}")
            not_read("Log management, service JWT (VCF_OPS_LI)", "the service JWT could not be minted")
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
    if host and os.environ.get("VCFA_USER") and secret("VCFA_PASSWORD"):
        print("\nVCF Automation, the Basic session login")
        cred = base64.b64encode(f"{os.environ['VCFA_USER']}:{secret('VCFA_PASSWORD')}".encode()).decode()
        st, data, hdrs = req("POST", f"https://{host}/cloudapi/1.0.0/sessions", {"Authorization": f"Basic {cred}", "Accept": CLOUDAPI_ACCEPT})
        t = {k.lower(): v for k, v in hdrs.items()}.get("x-vmware-vcloud-access-token")
        row("VCF Automation, session login", "Basic (user@org)", st, "accepted", "bearer returned in a response header" if t else "")
        if t:
            st, n = rights_count(host, t); counts["Basic session"] = n
            row("VCF Automation, rights", "session bearer", st, "accepted", f"{n} effective rights" if n is not None else "")
    else:
        print("\n  VCF Automation, Basic session login   skipped: VCFA_USER and VCFA_PASSWORD_FILE not set")
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
    if os.environ.get("VC_HOST") and os.environ.get("VC_USER") and secret("VC_PASSWORD"):
        print("\nvCenter, its own session")
        cred = base64.b64encode(f"{os.environ['VC_USER']}:{secret('VC_PASSWORD')}".encode()).decode()
        st, sid, _ = req("POST", f"https://{os.environ['VC_HOST']}/api/session", {"Authorization": f"Basic {cred}", "Accept": "application/json"})
        row("vCenter, session mint", "Basic", st, "accepted", "a session id in the body, no Bearer prefix" if st and st < 400 else "")
        if st and st < 400 and isinstance(sid, str):
            st, _, _ = req("GET", f"https://{os.environ['VC_HOST']}/api/vcenter/datacenter", {"vmware-api-session-id": sid, "Accept": "application/json"})
            row("vCenter API", "session id", st, "accepted")
    else:
        print("\n  vCenter                              skipped: VC_HOST, VC_USER, VC_PASSWORD_FILE not all set")
    if os.environ.get("SDDC_HOST") and os.environ.get("SDDC_USER") and secret("SDDC_PASSWORD"):
        print("\nSDDC Manager, its own bearer")
        body = json.dumps({"username": os.environ["SDDC_USER"], "password": secret("SDDC_PASSWORD")}).encode()
        st, data, _ = req("POST", f"https://{os.environ['SDDC_HOST']}/v1/tokens", {"Content-Type": "application/json", "Accept": "application/json"}, body)
        t = data.get("accessToken") if st == 200 and isinstance(data, dict) else None
        row("SDDC Manager, token mint", "username and password", st, "accepted")
        if t:
            st, _, _ = req("GET", f"https://{os.environ['SDDC_HOST']}/v1/sddc-managers", {"Authorization": f"Bearer {t}", "Accept": "application/json"})
            row("SDDC Manager API", "its bearer", st, "accepted")
    else:
        print("\n  SDDC Manager                         skipped: SDDC_HOST, SDDC_USER, SDDC_PASSWORD_FILE not all set")
    print(f"\n{len(ROWS)} pairs read; {sum(1 for r in ROWS if r[4].startswith('DIFFERS'))} differ from the chapter; {sum(1 for r in ROWS if r[2] is None)} without an answer")
    if NOT_READ:
        print(f"NOT READ: {len(NOT_READ)} configured surface(s) whose own token could not be minted: "
              + "; ".join(s for s, _ in NOT_READ) + " (exit 3)")
    return EXIT_UNREAD if NOT_READ or any(r[2] is None for r in ROWS) else 0


if __name__ == "__main__":
    sys.exit(main())
