#!/usr/bin/env python3
"""runway.py - how long your VCF Automation refresh tokens have left, and whether one is still honoured.

Two reads, so a scheduler can raise the alarm while a person can still re-mint:

  1  with VCFA_REFRESH_TOKEN_FILE: one refresh grant at the tenant token endpoint. A token can be refused before
     the date the platform lists for it, so the grant is the authority on whether the stored value still works.
     A 400 is read for its error body and stated, never retried: an invalid_grant means the token was revoked,
     has expired, or belongs to another organization, and the move is a re-mint. One attempt per run.
  2  GET /cloudapi/1.0.0/tokens, every page to the declared total, under the bearer: each token's name, type and
     expiry, with the days left and a verdict against WARN_DAYS (default 14) and ALERT_DAYS (default 7). The list
     shows the tokens the bearer's user can see; under a service account's own bearer, its own.

The bearer for step 2 comes from the grant in step 1 when it succeeds, else from a session login (VCFA_USER as
user@org with VCFA_PASSWORD), else from VCFA_BEARER, a bearer you already hold. No token value is printed.

Env:  VCFA_HOST, VCFA_ORG; VCFA_REFRESH_TOKEN_FILE and/or VCFA_USER + VCFA_PASSWORD and/or VCFA_BEARER;
      WARN_DAYS, ALERT_DAYS; TLS_VERIFY=false on a self-signed lab CA
Exit: 0 every token has more than WARN_DAYS · 1 one is within WARN_DAYS · 2 one is within ALERT_DAYS or past
      its date, or the grant was refused · 3 nothing could be read
"""

import base64
import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ACCEPT = "application/json;version=9.1.0"


def ctx():
    verify = os.environ.get("TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")
    return ssl.create_default_context() if verify else ssl._create_unverified_context()


def send(req):
    """One request; the status, the parsed body and the headers, whatever the status."""
    try:
        with urllib.request.urlopen(req, context=ctx(), timeout=60) as r:
            status, raw, hdrs = r.status, r.read(), dict((k.lower(), v) for k, v in r.getheaders())
    except urllib.error.HTTPError as e:
        status, raw, hdrs = e.code, e.read(), dict((k.lower(), v) for k, v in e.headers.items())
    try:
        body = json.loads(raw) if raw else None
    except ValueError:
        body = raw.decode(errors="replace")[:300]
    return status, body, hdrs


def grant(host, org, refresh):
    """One refresh grant. Returns (bearer or None, the line to print, refused?)."""
    form = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": refresh}).encode()
    req = urllib.request.Request(f"https://{host}/oauth/tenant/{org}/token", data=form, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
    status, body, _ = send(req)
    if status == 200 and isinstance(body, dict) and body.get("access_token"):
        rotated = body.get("refresh_token") not in (None, refresh)
        tail = "a different refresh token came back: store it, the old value is dead" if rotated else \
               "the refresh token that came back is the value sent"
        return body["access_token"], f"honoured (HTTP 200); {tail}", False
    err = body if isinstance(body, dict) else {}
    said = f'{err.get("error", "?")}: {err.get("error_description", "")}'.strip(": ")
    if status == 400 and err.get("error") == "invalid_grant":
        why = "revoked, expired, or minted for another organization; re-mint it (the console, or the session-login mint)"
    elif status == 400:
        why = "the request was refused before the token was judged; check the organization name and the grant type"
    else:
        why = "the endpoint did not answer the grant; this is not a verdict on the token"
    return None, f"REFUSED (HTTP {status}, {said}): {why}", True


def session(host, user_at_org, password):
    cred = base64.b64encode(f"{user_at_org}:{password}".encode()).decode()
    req = urllib.request.Request(f"https://{host}/cloudapi/1.0.0/sessions", method="POST",
                                 headers={"Authorization": "Basic " + cred, "Accept": ACCEPT})
    status, _, hdrs = send(req)
    return hdrs.get("x-vmware-vcloud-access-token") if status == 200 else None


def tokens(host, bearer):
    """Every page of the token list, refusing to stop short of the total the first page declares."""
    out, page, total = [], 1, None
    while True:
        req = urllib.request.Request(f"https://{host}/cloudapi/1.0.0/tokens?page={page}&pageSize=128",
                                     headers={"Authorization": "Bearer " + bearer, "Accept": ACCEPT})
        status, body, _ = send(req)
        if status != 200 or not isinstance(body, dict):
            print(f"\nthe token list answered HTTP {status}; nothing was judged")
            sys.exit(3)
        total = body.get("resultTotal") if total is None else total
        out += body.get("values") or []
        if page >= int(body.get("pageCount") or 1):
            break
        page += 1
    if total is not None and len(out) != int(total):
        print(f"\ncollected {len(out)} tokens of a declared total of {total}; nothing was judged")
        sys.exit(3)
    return out


def verdict(days, warn, alert):
    if days is None:
        return 0, "no expiry listed"
    if days < 0:
        return 2, "ALERT past its listed date"
    if days <= alert:
        return 2, f"ALERT within {alert} days"
    if days <= warn:
        return 1, f"WARN within {warn} days"
    return 0, "ok"


def main():
    host, org = os.environ["VCFA_HOST"], os.environ["VCFA_ORG"]
    warn, alert = int(os.environ.get("WARN_DAYS", "14")), int(os.environ.get("ALERT_DAYS", "7"))
    now = datetime.now(timezone.utc)
    worst, bearer = 0, None
    print(f"runway.py: refresh-token runway on one organization, warn at {warn} days, alert at {alert}\n")

    if os.environ.get("VCFA_REFRESH_TOKEN_FILE"):
        refresh = open(os.environ["VCFA_REFRESH_TOKEN_FILE"], encoding="utf-8").read().strip()
        bearer, line, refused = grant(host, org, refresh)
        print(f"  grant   the stored refresh token: {line}")
        worst = max(worst, 2 if refused else 0)
    if not bearer and os.environ.get("VCFA_USER") and os.environ.get("VCFA_PASSWORD"):
        bearer = session(host, os.environ["VCFA_USER"], os.environ["VCFA_PASSWORD"])
        print(f"  bearer  from a session login: {'yes' if bearer else 'the login did not return one'}")
    if not bearer and os.environ.get("VCFA_BEARER"):
        bearer = os.environ["VCFA_BEARER"]
        print("  bearer  from VCFA_BEARER")
    if not bearer:
        print("\nno bearer to read the token list with; set a refresh token that works, a session login, or VCFA_BEARER")
        sys.exit(max(worst, 3) if worst < 2 else worst)

    listed = tokens(host, bearer)
    print(f"\n  {'token':<34} {'type':<10} {'expires (UTC)':<22} {'days':>6}  verdict")
    for t in sorted(listed, key=lambda t: t.get("expirationTimeUtc") or "9999"):
        exp = t.get("expirationTimeUtc")
        days = None
        if exp:
            when = datetime.fromisoformat(exp.replace("Z", "+00:00"))
            days = (when - now).total_seconds() / 86400
        level, word = verdict(days, warn, alert)
        worst = max(worst, level)
        rot = " (rotates on every use)" if t.get("requireRotation") else ""
        print(f"  {str(t.get('name', '?'))[:34]:<34} {str(t.get('type', '?')):<10} {(exp or '-')[:19]:<22} "
              f"{'-' if days is None else f'{days:.1f}':>6}  {word}{rot}")
    print(f"\n{len(listed)} token(s) listed; exit {worst}")
    sys.exit(worst)


if __name__ == "__main__":
    main()
