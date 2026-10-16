#!/usr/bin/env python3
"""claims.py - what a bearer says it is.

Exchanges your api-token at the identity broker for a bearer (opslib.py, the flow the Platform identity
chapter teaches), then decodes the bearer's claims without verifying them (the decoding needs no key; the
verification is the platform's job) and prints what the token says about its holder:

  issuer and audience         who minted it and for whom
  the principal               prn_type, where the broker states it: USER a person, SERVICE a machine (an API client);
                              without it, a person's claim (a user name, an email, a user id) names a person, unless
                              it holds service-account-<name>, the name VCF Automation gives a service account's
                              user; that token, and one with neither, is not determined (exit 3), never read as a
                              person or a machine on the strength of a name
  issued at, expires at       the bearer's own lifetime, read off the token rather than assumed
  scopes and realm            what the mint was narrowed to

Any other JWT can be decoded instead: set JWT_ENV to the name of an environment variable holding it (for
example a service JWT from the fleet plane's exchange, or the bearer another flow returned).

Env:   opslib.py's variables (OPS_HOST, OPS_API_TOKEN_FILE; OPS_BROKER_HOST, the broker that trades the token, when it
       is not OPS_HOST; BROKER_TENANT, OPS_TLS_VERIFY optional)
       JWT_ENV (optional)  name of an env var holding a JWT to decode instead of minting one
Use:   python3 claims.py                           mint at the broker and decode the bearer; --help prints this
       python3 claims.py --replay replay/claims    without an estate: the broker's answer from the recorded set beside
                                                   this script (its hosts are placeholders); nothing is sent and no
                                                   credential is read; JWT_ENV does not combine with it
Exit:  0 claims printed, the principal a PERSON or a CLIENT
       3 the mint failed (the broker did not trade the api-token for a bearer, or answered a bearer that is not a JWT),
         the principal is not determined (no prn_type and no person's claim, no prn_type and a person's claim holding
         a VCF Automation service account's user name, or a prn_type other than USER or SERVICE), a request a --replay
         set holds no answer for, or an error the script did not expect
       5 a usage error: an argument it does not take, OPS_HOST or the api-token unset, OPS_API_TOKEN_FILE that cannot
         be read, JWT_ENV naming an empty variable or a value that is not a JWT, a --replay directory that cannot be
         read or holds no replay set, --replay with JWT_ENV set, or a Python older than 3.10
A refused mint names no cause. A deleted or rotated api-token was refused at the broker with HTTP 500 on the 9.1.0
run of 2026-09-16, and a deleted API client token with HTTP 400 on 9.1.1 (X-153, X-190); one past its expiry date is
not tested.
Never prints a token value.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from datetime import datetime, timezone

from opslib import _replay_check  # noqa: F401  the replay block's check of a set, so a set can be checked from here

EXIT_UNREAD, EXIT_USAGE = 3, 5

PRINCIPAL_KEYS = ("sub", "prn", "prn_type", "azp", "client_id", "cid")
PERSON_KEYS = ("preferred_username", "username", "upn", "email", "eml", "user_id", "name", "user_name", "given_name")
SCOPE_KEYS = ("scp", "scope", "scopes")


def b64url(part):
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


class NotAJwt(ValueError):
    """A value that does not decode as a JWT: a usage error when the reader named it, never a failed read."""


def decode(jwt):
    parts = jwt.split(".")
    if len(parts) != 3:
        raise NotAJwt(f"not a JWT (expected three dot-separated parts, got {len(parts)})")
    try:
        header, claims = json.loads(b64url(parts[0])), json.loads(b64url(parts[1]))
    except ValueError as e:
        raise NotAJwt(f"not a JWT ({type(e).__name__} decoding its header or claims)") from None
    if not isinstance(header, dict) or not isinstance(claims, dict):
        raise NotAJwt("not a JWT (its header and claims must each decode to a JSON object)")
    return header, claims


# VCF Automation names a service account's user service-account-<name> (its session read so on the reference estate,
# 2026-10-08 and 2026-10-13, X-075 and X-147). A VCF Automation bearer carries no prn_type, so without it a claim
# holding that name cannot tell the machine from a person: the principal is not determined, never a PERSON or a CLIENT
# on the strength of a name.
SERVICE_ACCOUNT_PREFIX = "service-account-"


def principal_kind(claims):
    """PERSON, CLIENT or None (not determined), and why. The broker's prn_type decides (USER a person's api-token,
    SERVICE an API client's); without it a person's claim names a person, unless one of them holds a VCF Automation
    service account's user name, and an absent claim names nobody. A prn of the form id@tenant decides nothing: an API
    client's bearer carried one too."""
    person = [k for k in PERSON_KEYS if claims.get(k)]
    held = claims.get("prn_type")
    if isinstance(held, str) and held.upper() == "USER":
        return "PERSON", ", ".join(["prn_type USER", *person])
    if isinstance(held, str) and held.upper() == "SERVICE":
        return "CLIENT", "prn_type SERVICE" + (f"; it also carries {', '.join(person)}" if person else "")
    if held is not None:
        return None, f"prn_type {held!r}, which names neither USER nor SERVICE"
    machine = [k for k in person if isinstance(claims[k], str)
               and claims[k].strip().lower().startswith(SERVICE_ACCOUNT_PREFIX)]
    if machine:
        return None, (f"no prn_type claim, and {', '.join(machine)} holds a name of the form {SERVICE_ACCOUNT_PREFIX}<name>, "
                      "the name VCF Automation gives a service account's user, so the claims do not tell that machine "
                      "from a person")
    if person:
        return "PERSON", ", ".join(person)
    return None, "no prn_type claim and no person's claim; a claim that is absent names no machine"


def stamp(epoch):
    return datetime.fromtimestamp(int(epoch), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class _Parser(argparse.ArgumentParser):
    """argparse's own refusal exits 2; here a usage error exits 5, as on every identity companion."""

    def __init__(self, *args, **kwargs):  # an abbreviation never parses as a whole flag name
        kwargs.setdefault("allow_abbrev", False)
        super().__init__(*args, **kwargs)

    def error(self, message):
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        raise SystemExit(EXIT_USAGE)


def main(argv: list[str] | None = None) -> int:
    """The run, with three guards around it: a Python older than 3.10 is refused (exit 5), an argument the script does
    not take is a usage error (exit 5) before anything is read, and an error the script did not expect exits 3, the
    code for a read that failed. A replay set, once loaded, is unloaded however the run ends."""
    if sys.version_info < (3, 10):  # noqa: UP036  the script is run by readers on their own Python
        print("claims.py needs Python 3.10 or later", file=sys.stderr)
        return EXIT_USAGE
    ap = _Parser(prog="claims.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--replay", metavar="DIR",
                    help="answer every request from the recorded set in DIR (replay/claims beside this script is one): "
                         "nothing is sent and no credential is read")
    a = ap.parse_args(argv)
    import opslib  # the broker exchange beside this script, and the replay set its requests are answered from

    try:
        if a.replay:
            try:
                opslib.replay_start(a.replay)
            except (OSError, ValueError) as e:
                print(f"--replay {a.replay}: {e}; nothing was sent", file=sys.stderr)
                return EXIT_USAGE
            if os.environ.get("JWT_ENV"):
                print("--replay answers the broker's mint from the recorded set, and JWT_ENV names a JWT to decode "
                      "instead, so the two do not combine: unset JWT_ENV, or run without --replay; nothing was sent",
                      file=sys.stderr)
                return EXIT_USAGE
        return _run()
    except Exception as e:  # noqa: BLE001  the last guard: whatever was not expected is not known, so exit 3
        print(f"the run stopped on an error it did not expect: {type(e).__name__}: {str(e)[:160]} (exit 3)", file=sys.stderr)
        return EXIT_UNREAD
    finally:
        opslib.replay_stop()


def _run():
    if os.environ.get("JWT_ENV"):
        source = f"the JWT in ${os.environ['JWT_ENV']}"
        jwt = os.environ.get(os.environ["JWT_ENV"], "")
        if not jwt:
            print(f"FATAL: {os.environ['JWT_ENV']} is empty", file=sys.stderr)
            return EXIT_USAGE
    else:
        from opslib import bearer, secret
        try:
            held = secret("OPS_API_TOKEN")
        except OSError as e:
            print(f"FATAL: OPS_API_TOKEN_FILE could not be read: {type(e).__name__}", file=sys.stderr)
            return EXIT_USAGE
        if not os.environ.get("OPS_HOST") or not held:
            print("FATAL: OPS_HOST and OPS_API_TOKEN_FILE (or OPS_API_TOKEN) are required, or JWT_ENV to decode a JWT you hold",
                  file=sys.stderr)
            return EXIT_USAGE
        source = "the bearer exchanged from your api-token at the broker"
        try:
            jwt = bearer()
        except Exception as e:  # noqa: BLE001 - the harness reports, it does not retry
            print(f"FATAL: the broker exchange failed: {type(e).__name__}: {e}")
            print("       the broker refused the api-token; a deleted API client token was refused with HTTP 400 on 9.1.1 "
                  "(HTTP 500 on the 9.1.0 run of 2026-09-16): check the token still exists, then its expiry, before the service")
            return EXIT_UNREAD
    try:
        header, claims = decode(jwt)
    except NotAJwt as e:
        if os.environ.get("JWT_ENV"):  # a value the reader named: the invocation is wrong
            print(f"FATAL: {e}", file=sys.stderr)
            return EXIT_USAGE
        print(f"FATAL: the broker answered a bearer that is {e}: nothing can be read off it (exit 3)", file=sys.stderr)
        return EXIT_UNREAD
    print(f"decoded: {source} ({len(jwt)} characters; value never printed)")
    print(f"header:   alg={header.get('alg')}  typ={header.get('typ')}  kid={'present' if header.get('kid') else 'absent'}")
    print(f"issuer:   {claims.get('iss')}")
    aud = claims.get("aud")
    print(f"audience: {aud if not isinstance(aud, list) else ', '.join(map(str, aud))}")
    for k in PRINCIPAL_KEYS:
        if k in claims:
            print(f"{k + ':':<10}{claims[k]}")
    kind, why = principal_kind(claims)
    if kind == "PERSON":
        print(f"principal: a PERSON ({why}): this bearer carries that person's rights, and a pipeline holding it dies with their account")
    elif kind == "CLIENT":
        print(f"principal: a CLIENT ({why}): a machine identity, the shape automation should hold")
    else:
        print(f"principal: not determined ({why})")
    for k in SCOPE_KEYS:
        if k in claims:
            print(f"{k + ':':<10}{claims[k]}")
    for k in ("realm", "tenant", "org", "tid", "context_name"):
        if k in claims:
            print(f"{k + ':':<10}{claims[k]}")
    iat, exp = claims.get("iat"), claims.get("exp")
    if iat and exp:
        life = int(exp) - int(iat)
        print(f"issued:   {stamp(iat)}")
        print(f"expires:  {stamp(exp)}  (lifetime {life // 60} min {life % 60} s: the minutes clock; the api-token behind it is on the months clock)")
    elif exp:
        print(f"expires:  {stamp(exp)}")
    else:
        print("expires:  no exp claim")
    other = sorted(k for k in claims if k not in PRINCIPAL_KEYS + PERSON_KEYS + SCOPE_KEYS + ("iss", "aud", "iat", "exp", "nbf", "jti", "realm", "tenant", "org", "tid", "context_name"))
    if other:
        print(f"other claims present: {', '.join(other)}")
    if kind is None:
        print("NOT DETERMINED: the claims do not say whether a person or a machine holds this bearer (exit 3)")
        return EXIT_UNREAD
    return 0


if __name__ == "__main__":
    sys.exit(main())
