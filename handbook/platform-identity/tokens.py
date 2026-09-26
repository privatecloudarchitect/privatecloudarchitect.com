#!/usr/bin/env python3
"""tokens.py: decode a bearer you are holding, and read its two clocks.

Offline. It makes no network call, contacts no identity provider, and never prints, logs or
returns a token value. It reads the claims a JWT carries about itself and tells you what they mean
for the surface you are about to call.

Why this exists: the commonest identity failure is not a wrong token, it is a token whose clock ran
out, and the error you get back almost never names one. A platform bearer and the credential that
minted it run on two different clocks, and knowing which one expired decides whether you re-mint in
a command or in a console.

    python tokens.py                      read a token from $TOKEN
    python tokens.py --file t.txt         read it from a file
    cat t.txt | python tokens.py -        read it from stdin
    python tokens.py --kubeconfig         every credential in your kubeconfig, no token needed

Nothing is written anywhere.
"""
from __future__ import annotations
import argparse, base64, json, os, sys, datetime as dt

SKEW = dt.timedelta(minutes=2)          # clocks disagree; do not call a token dead on the second


def _seg(part: str) -> dict:
    part += "=" * (-len(part) % 4)
    return json.loads(base64.urlsafe_b64decode(part))


def decode(token: str) -> dict | None:
    """The claims, or None if this is not a JWT. The token itself is never returned."""
    parts = token.strip().split(".")
    if len(parts) != 3:
        return None
    try:
        return _seg(parts[1])
    except Exception:
        return None


def clocks(claims: dict, now: dt.datetime | None = None) -> dict:
    """The two clocks a bearer carries, plus what the gap between them means.

    `exp` minus `iat` is the mint's lifetime, which is a property of the issuer's policy rather
    than of your token: it is the number to plan a refresh cadence around. `exp` minus now is what
    decides whether the next call works.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    out: dict = {"now": now}
    for k in ("iat", "nbf", "exp", "auth_time"):
        v = claims.get(k)
        if isinstance(v, (int, float)):
            out[k] = dt.datetime.fromtimestamp(v, dt.timezone.utc)
    if "iat" in out and "exp" in out:
        out["lifetime"] = out["exp"] - out["iat"]
    if "exp" in out:
        out["remaining"] = out["exp"] - now
        out["expired"] = out["exp"] <= now
        out["expiring_within_skew"] = (not out["expired"]) and out["remaining"] <= SKEW
    return out


def identity(claims: dict) -> dict:
    """Who the token says you are, and which authority said so. No secret is read."""
    pick = lambda *ks: next((claims[k] for k in ks if claims.get(k)), None)
    return {
        "subject": pick("sub", "username", "user_name", "preferred_username", "email"),
        "issuer": pick("iss"),
        "audience": pick("aud"),
        "tenant": pick("tenant", "tenant_name", "org_name", "context_name", "acct"),
        "client": pick("azp", "client_id", "cid"),
        "scopes": pick("scope", "scopes", "perms", "permissions"),
    }


def _fmt(d: dt.timedelta) -> str:
    total = int(abs(d.total_seconds()))
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    mins, secs = divmod(rem, 60)
    if days: return f"{days}d {hours}h"
    if hours: return f"{hours}h {mins}m"
    if mins: return f"{mins}m"
    return f"{secs}s"


def report(claims: dict) -> int:
    """Print the reading. Returns 0 if the token is usable, 1 if it is not."""
    c, who = clocks(claims), identity(claims)

    print("Who it says you are")
    for k in ("subject", "issuer", "audience", "tenant", "client"):
        if who.get(k):
            print(f"  {k:9s} {str(who[k])[:88]}")
    if who.get("scopes"):
        s = who["scopes"]
        n = len(s.split()) if isinstance(s, str) else len(s)
        print(f"  {'scopes':9s} {n} present (values not printed)")

    print("\nThe two clocks")
    if "lifetime" in c:
        print(f"  mint lifetime   {_fmt(c['lifetime'])}   the issuer's policy, not your token")
    if "iat" in c:
        print(f"  issued at       {c['iat'].isoformat()}")
    if "exp" not in c:
        print("  expires         no exp claim: this token does not say when it dies, so treat")
        print("                  its lifetime as unknown rather than as unlimited")
        return 0
    print(f"  expires at      {c['exp'].isoformat()}")

    if c["expired"]:
        print(f"\n  EXPIRED {_fmt(c['remaining'])} ago.")
        print("  Every call with it answers 401, and the message will not mention a token.")
        print("  Re-mint the bearer. If re-minting also fails, the credential BEHIND it is what")
        print("  expired, and that one is usually replaced in a console rather than a command.")
        return 1
    if c["expiring_within_skew"]:
        print(f"\n  Valid for {_fmt(c['remaining'])}, which is inside the clock-skew margin.")
        print("  Long enough to pass a check and short enough to fail the call after it. Re-mint.")
        return 1
    print(f"\n  Valid for {_fmt(c['remaining'])}.")
    if "lifetime" in c and c["lifetime"] <= dt.timedelta(hours=1):
        print("  Short-lived by design: refresh on a schedule rather than on failure, and never")
        print("  cache it past the lifetime above.")
    return 0


def from_kubeconfig() -> int:
    """Every credential in the kubeconfig, and which of them can renew itself.

    Reads the file directly rather than shelling out, because `kubectl config view` redacts token
    values and would silently report nothing at all.
    """
    try:
        import yaml
    except ImportError:
        print("this mode needs PyYAML (pip install pyyaml)"); return 2
    path = os.environ.get("KUBECONFIG") or os.path.expanduser("~/.kube/config")
    if not os.path.exists(path):
        print(f"no kubeconfig at {path}"); return 2
    with open(path, encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}
    users = cfg.get("users") or []
    if not users:
        print("kubeconfig declares no users"); return 0
    bad = 0
    print(f"{len(users)} credential(s) in {path}\n")
    for u in users:
        name, user = u.get("name", "?"), (u.get("user") or {})
        if "exec" in user:
            print(f"  {name[:52]:54s} exec plugin, renews itself (it may prompt)")
            continue
        if user.get("client-certificate-data") or user.get("client-certificate"):
            print(f"  {name[:52]:54s} client certificate, no login needed")
            continue
        tok = user.get("token")
        if not isinstance(tok, str) or not tok:
            print(f"  {name[:52]:54s} no token, no certificate, no exec plugin")
            continue
        claims = decode(tok)
        if not claims:
            print(f"  {name[:52]:54s} opaque token, no readable expiry")
            continue
        c = clocks(claims)
        if "exp" not in c:
            print(f"  {name[:52]:54s} no exp claim")
            continue
        state = (f"EXPIRED {_fmt(c['remaining'])} ago" if c["expired"]
                 else f"valid {_fmt(c['remaining'])}")
        life = f"  (lifetime {_fmt(c['lifetime'])})" if "lifetime" in c else ""
        print(f"  {name[:52]:54s} {state}{life}")
        bad += 1 if c["expired"] else 0
    if bad:
        print(f"\n{bad} credential(s) expired. A static token has no exec plugin, so kubectl")
        print("cannot renew it: it fails only when you next use it.")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", nargs="?", default=None, help="'-' to read the token from stdin")
    ap.add_argument("--file", help="read the token from this file")
    ap.add_argument("--kubeconfig", action="store_true", help="read every kubeconfig credential")
    a = ap.parse_args()

    if a.kubeconfig:
        return from_kubeconfig()

    if a.source == "-":
        raw = sys.stdin.read()
    elif a.file:
        with open(a.file, encoding="utf-8") as fh:
            raw = fh.read()
    else:
        raw = os.environ.get("TOKEN", "")
        if not raw:
            ap.print_help()
            print("\nno token given: set $TOKEN, pass --file, or pipe one with '-'")
            return 2

    raw = raw.strip()
    if raw.lower().startswith("bearer "):
        raw = raw[7:].strip()
    claims = decode(raw)
    if claims is None:
        print("This is not a JWT: it carries no readable claims, so nothing here can tell you when")
        print("it expires. An opaque token is not a worse token; it just means the issuer is the")
        print("only thing that knows, and you learn its lifetime from the issuer's documentation")
        print("or by measuring when it stops working.")
        return 2
    return report(claims)


if __name__ == "__main__":
    raise SystemExit(main())
