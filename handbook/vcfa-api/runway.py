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
VCFA_REFRESH_TOKEN_FILE is mode 0600: a file open to group or other is refused unread, before anything is sent.
Use:  python3 runway.py           it takes no option but --help
Exit, the first that applies, so a scheduler reads one state from one number:
      2 a listed token within ALERT_DAYS or past its listed date, or the stored refresh token refused (400
        invalid_grant): re-mint it
      1 a listed token within WARN_DAYS
      3 nothing could be read, or a result is undetermined: the grant answered anything but 200 or a 400
        invalid_grant, or did not answer (not a verdict on the token), no bearer to read the list with, the token list
        not read whole, or an error the script did not expect, printed on one line
      0 every listed token has more than WARN_DAYS, and the stored refresh token, when given, was honoured
      5 a usage error, with nothing sent: an option it does not take, VCFA_HOST or VCFA_ORG unset, no credential set
        (VCFA_REFRESH_TOKEN_FILE, VCFA_USER with VCFA_PASSWORD, or VCFA_BEARER), a WARN_DAYS or ALERT_DAYS that is
        not a whole number, or a VCFA_REFRESH_TOKEN_FILE that cannot be read, is empty or is open to group or other
        (refused unread, with the fix: chmod 600)
The contract every identity companion keeps: 0 nothing for a person to act on, 3 a read failed or a result is
undetermined, 5 a usage error; 1 and 2 are this script's own, above; an error the script did not expect is 3.
"""

import argparse
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
EXIT_OK, EXIT_WARN, EXIT_ALERT, EXIT_UNREAD, EXIT_USAGE = 0, 1, 2, 3, 5


def ctx():
    verify = os.environ.get("TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")
    return ssl.create_default_context() if verify else ssl._create_unverified_context()


def send(req):
    """One request; the status, the parsed body and the headers, whatever the status; status 0 when the host did not
    answer, which is no verdict on anything."""
    try:
        with urllib.request.urlopen(req, context=ctx(), timeout=60) as r:
            status, raw, hdrs = r.status, r.read(), dict((k.lower(), v) for k, v in r.getheaders())
    except urllib.error.HTTPError as e:
        status, raw, hdrs = e.code, e.read(), dict((k.lower(), v) for k, v in e.headers.items())
    except (urllib.error.URLError, OSError):
        return 0, None, {}
    try:
        body = json.loads(raw) if raw else None
    except ValueError:
        body = raw.decode(errors="replace")[:300]
    return status, body, hdrs


def grant(host, org, refresh):
    """One refresh grant. Returns (bearer or None, the line to print, its level): 0 honoured, 2 refused as the token's
    own verdict (400 invalid_grant), 3 not judged (any other answer, or none)."""
    form = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": refresh}).encode()
    req = urllib.request.Request(f"https://{host}/oauth/tenant/{org}/token", data=form, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
    status, body, _ = send(req)
    if status == 200 and isinstance(body, dict) and body.get("access_token"):
        rotated = body.get("refresh_token") not in (None, refresh)
        tail = "a different refresh token came back: store it, the old value is dead" if rotated else \
               "the refresh token that came back is the value sent"
        return body["access_token"], f"honoured (HTTP 200); {tail}", EXIT_OK
    err = body if isinstance(body, dict) else {}
    said = f'{err.get("error", "?")}: {err.get("error_description", "")}'.strip(": ")
    if status == 400 and err.get("error") == "invalid_grant":
        why = "revoked, expired, or minted for another organization; re-mint it (the console, or the session-login mint)"
        return None, f"REFUSED (HTTP {status}, {said}): {why}", EXIT_ALERT
    if status == 0:
        return None, "NOT JUDGED (no answer): the endpoint did not answer the grant; this is not a verdict on the token", \
            EXIT_UNREAD
    if status == 400:
        why = "the request was refused before the token was judged; check the organization name and the grant type"
    else:
        why = "the endpoint did not answer the grant; this is not a verdict on the token"
    return None, f"NOT JUDGED (HTTP {status}, {said}): {why}", EXIT_UNREAD


def session(host, user_at_org, password):
    cred = base64.b64encode(f"{user_at_org}:{password}".encode()).decode()
    req = urllib.request.Request(f"https://{host}/cloudapi/1.0.0/sessions", method="POST",
                                 headers={"Authorization": "Basic " + cred, "Accept": ACCEPT})
    status, _, hdrs = send(req)
    return hdrs.get("x-vmware-vcloud-access-token") if status == 200 else None


def tokens(host, bearer):
    """Every page of the token list, refusing to stop short of the total the first page declares; None, never a
    shorter list, when a page was refused or not answered or the pages end short of the total."""
    out, page, total = [], 1, None
    while True:
        req = urllib.request.Request(f"https://{host}/cloudapi/1.0.0/tokens?page={page}&pageSize=128",
                                     headers={"Authorization": "Bearer " + bearer, "Accept": ACCEPT})
        status, body, _ = send(req)
        if status != 200 or not isinstance(body, dict):
            print("\nthe token list " + (f"answered HTTP {status}" if status else "got no answer") + "; nothing was judged")
            return None
        total = body.get("resultTotal") if total is None else total
        out += body.get("values") or []
        if page >= int(body.get("pageCount") or 1):
            break
        page += 1
    if total is not None and len(out) != int(total):
        print(f"\ncollected {len(out)} tokens of a declared total of {total}; nothing was judged")
        return None
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


def read_secret(var):
    """The secret in the file VAR names. A file open to group or other is refused before it is read; the refusal
    names the variable and the fix, never the file's content."""
    with open(os.environ[var], encoding="utf-8") as f:
        mode = os.fstat(f.fileno()).st_mode & 0o777
        # Windows makes the mode from the read-only flag alone, so it has no group or other bits to judge.
        if mode & 0o077 and os.name != "nt":
            raise PermissionError(f"{var} names a file of mode {mode:04o}, open to group or other: "
                                  f'run chmod 600 "${var}" and try again (the file was not read)')
        return f.read().strip()


class _Parser(argparse.ArgumentParser):
    """argparse exits 2 on a usage error, the code this script gives an alert; it exits 5 here."""

    def __init__(self, *args, **kwargs):  # an abbreviation never parses as a whole flag name
        kwargs.setdefault("allow_abbrev", False)
        super().__init__(*args, **kwargs)

    def error(self, message: str):  # type: ignore[override]
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        raise SystemExit(EXIT_USAGE)


def first_that_applies(levels) -> int:
    """The run's one code from every state it met: an alert (2), then a warning (1), then a read that failed or a
    result undetermined (3), then 0, so a finding read whole is never hidden by a read that failed beside it."""
    met = set(levels)
    return next((code for code in (EXIT_ALERT, EXIT_WARN, EXIT_UNREAD) if code in met), EXIT_OK)


def usage_problem() -> str | None:
    """What the run needs before anything is sent, or None: its host and organization, a credential to read the
    list with, and whole numbers of days."""
    missing = [k for k in ("VCFA_HOST", "VCFA_ORG") if not os.environ.get(k)]
    if missing:
        return f"set {' and '.join(missing)} (see the header)"
    if not (os.environ.get("VCFA_REFRESH_TOKEN_FILE") or os.environ.get("VCFA_BEARER")
            or (os.environ.get("VCFA_USER") and os.environ.get("VCFA_PASSWORD"))):
        return "set VCFA_REFRESH_TOKEN_FILE, VCFA_USER with VCFA_PASSWORD, or VCFA_BEARER (see the header)"
    for k, default in (("WARN_DAYS", "14"), ("ALERT_DAYS", "7")):
        if not os.environ.get(k, default).strip().isdigit():
            return f"{k} is {os.environ[k]!r}: a whole number of days, 0 or more"
    return None


def main(argv: list[str] | None = None) -> int:
    """The run, with its guard: an option it does not take is a usage error (5), and an error the script did not
    expect exits 3 on one line, never 1, which says a token is inside WARN_DAYS, and never a traceback."""
    try:
        _Parser(prog="runway.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
                ).parse_args(sys.argv[1:] if argv is None else argv)
        return _run()
    except SystemExit as e:  # the parser's own exits: 5 on a usage error, 0 after --help
        return e.code if isinstance(e.code, int) else EXIT_USAGE
    except Exception as e:  # the last guard: whatever was not expected is not known, so exit 3
        print(f"runway.py: the run stopped on an error it did not expect: {type(e).__name__}: {str(e)[:160]}; nothing "
              "was judged (exit 3)", file=sys.stderr)
        return EXIT_UNREAD


def _run() -> int:
    problem = usage_problem()
    if problem:
        print(f"runway.py: {problem}; nothing was sent", file=sys.stderr)
        return EXIT_USAGE
    host, org = os.environ["VCFA_HOST"], os.environ["VCFA_ORG"]
    warn, alert = int(os.environ.get("WARN_DAYS", "14")), int(os.environ.get("ALERT_DAYS", "7"))
    refresh = None
    if os.environ.get("VCFA_REFRESH_TOKEN_FILE"):   # read before anything is sent
        try:
            refresh = read_secret("VCFA_REFRESH_TOKEN_FILE")
        except (OSError, UnicodeDecodeError) as e:   # the refusal (no errno) names the variable, the mode and the fix
            why = str(e) if isinstance(e, PermissionError) and e.errno is None else \
                f"VCFA_REFRESH_TOKEN_FILE names a file that cannot be read ({type(e).__name__})"
            print(f"runway.py: {why}; nothing was sent", file=sys.stderr)
            return EXIT_USAGE
        if not refresh:
            print("runway.py: VCFA_REFRESH_TOKEN_FILE is empty; nothing was sent", file=sys.stderr)
            return EXIT_USAGE
    now = datetime.now(timezone.utc)
    levels, bearer = [], None
    print(f"runway.py: refresh-token runway on one organization, warn at {warn} days, alert at {alert}\n")

    if refresh:
        bearer, line, level = grant(host, org, refresh)
        print(f"  grant   the stored refresh token: {line}")
        levels.append(level)
    if not bearer and os.environ.get("VCFA_USER") and os.environ.get("VCFA_PASSWORD"):
        bearer = session(host, os.environ["VCFA_USER"], os.environ["VCFA_PASSWORD"])
        print(f"  bearer  from a session login: {'yes' if bearer else 'the login did not return one'}")
    if not bearer and os.environ.get("VCFA_BEARER"):
        bearer = os.environ["VCFA_BEARER"]
        print("  bearer  from VCFA_BEARER")
    if not bearer:
        print("\nno bearer to read the token list with; set a refresh token that works, a session login, or VCFA_BEARER")
        return first_that_applies([*levels, EXIT_UNREAD])

    listed = tokens(host, bearer)
    if listed is None:
        return first_that_applies([*levels, EXIT_UNREAD])
    print(f"\n  {'token':<34} {'type':<10} {'expires (UTC)':<22} {'days':>6}  verdict")
    for t in sorted(listed, key=lambda t: t.get("expirationTimeUtc") or "9999"):
        exp = t.get("expirationTimeUtc")
        days = None
        if exp:
            when = datetime.fromisoformat(exp.replace("Z", "+00:00"))
            days = (when - now).total_seconds() / 86400
        level, word = verdict(days, warn, alert)
        levels.append(level)
        rot = " (rotates on every use)" if t.get("requireRotation") else ""
        print(f"  {str(t.get('name', '?'))[:34]:<34} {str(t.get('type', '?')):<10} {(exp or '-')[:19]:<22} "
              f"{'-' if days is None else f'{days:.1f}':>6}  {word}{rot}")
    code = first_that_applies(levels)
    print(f"\n{len(listed)} token(s) listed; exit {code}")
    return code


if __name__ == "__main__":
    sys.exit(main())
