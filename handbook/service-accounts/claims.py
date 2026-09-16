#!/usr/bin/env python3
"""claims.py - what a bearer says it is.

Exchanges your api-token at the identity broker for a bearer (opslib.py, the flow the Platform identity
chapter teaches), then decodes the bearer's claims without verifying them (the decoding needs no key; the
verification is the platform's job) and prints what the token says about its holder:

  issuer and audience         who minted it and for whom
  the principal claims        a client id and no username, email, or user id claim is a machine; a person shows up as user@realm
  issued at, expires at       the bearer's own lifetime, read off the token rather than assumed
  scopes and realm            what the mint was narrowed to

Any other JWT can be decoded instead: set JWT_ENV to the name of an environment variable holding it (for
example a service JWT from the fleet plane's exchange, or the bearer another flow returned).

Env:   opslib.py's variables (OPS_HOST, OPS_API_TOKEN; OPS_BROKER_HOST, OPS_REALM, OPS_TLS_VERIFY optional)
       JWT_ENV (optional)  name of an env var holding a JWT to decode instead of minting one
Exit:  0 claims printed · 2 the mint failed
Never prints a token value.
"""

import base64
import json
import os
import sys
from datetime import datetime, timezone

PRINCIPAL_KEYS = ("sub", "prn", "azp", "client_id", "cid")
PERSON_KEYS = ("preferred_username", "username", "upn", "email", "eml", "user_id", "name", "user_name", "given_name")
SCOPE_KEYS = ("scp", "scope", "scopes")


def b64url(part):
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def decode(jwt):
    parts = jwt.split(".")
    if len(parts) != 3:
        raise SystemExit(f"FATAL: not a JWT (expected three dot-separated parts, got {len(parts)})")
    return json.loads(b64url(parts[0])), json.loads(b64url(parts[1]))


def stamp(epoch):
    return datetime.fromtimestamp(int(epoch), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main():
    if os.environ.get("JWT_ENV"):
        source = f"the JWT in ${os.environ['JWT_ENV']}"
        jwt = os.environ.get(os.environ["JWT_ENV"], "")
        if not jwt:
            raise SystemExit(f"FATAL: {os.environ['JWT_ENV']} is empty")
    else:
        from opslib import bearer
        source = "the bearer exchanged from OPS_API_TOKEN at the broker"
        try:
            jwt = bearer()
        except Exception as e:  # noqa: BLE001 - the harness reports, it does not retry
            print(f"FATAL: the broker exchange failed: {type(e).__name__}: {e}")
            print("       an EXPIRED api-token answers HTTP 500 here, not 401: check its expiry before the service")
            sys.exit(2)
    header, claims = decode(jwt)
    print(f"decoded: {source} ({len(jwt)} characters; value never printed)")
    print(f"header:   alg={header.get('alg')}  typ={header.get('typ')}  kid={'present' if header.get('kid') else 'absent'}")
    print(f"issuer:   {claims.get('iss')}")
    aud = claims.get("aud")
    print(f"audience: {aud if not isinstance(aud, list) else ', '.join(map(str, aud))}")
    for k in PRINCIPAL_KEYS:
        if k in claims:
            print(f"{k + ':':<10}{claims[k]}")
    person = [k for k in PERSON_KEYS if claims.get(k)]
    prn = str(claims.get("prn") or "")
    if "@" in prn and prn not in person:
        person.append("prn is user@realm")
    if person:
        print(f"principal: a PERSON ({', '.join(person)}): this bearer carries that person's rights, and a pipeline holding it dies with their account")
    else:
        print("principal: a CLIENT (no username, email, or user id claim; prn is a client id): a machine identity, the shape automation should hold")
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


if __name__ == "__main__":
    main()
