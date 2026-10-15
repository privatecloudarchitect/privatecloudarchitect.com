#!/usr/bin/env python3
"""tokens.py: decode a bearer you are holding, and read its two clocks.

Offline. It makes no network call, contacts no identity provider, and never prints, logs or
returns a token value. It reads the claims a JWT carries about itself and tells you what they mean
for the surface you are about to call.

Why this exists: the commonest identity failure is not a wrong token, it is a token whose clock ran
out, and the error you get back almost never names one. A platform bearer and the credential that
minted it run on two different clocks, and knowing which one expired decides whether you re-mint in
a command or in a console.

    python3 tokens.py -                   read it from stdin: paste it, then Ctrl-D (it stays out of your shell history)
    python3 tokens.py --file t.txt        read it from a file, mode 0600
    python3 tokens.py --kubeconfig        every credential in your kubeconfig, no token needed
    python3 tokens.py                     read a token from $TOKEN, when a tool already set it (typing
                                          `export TOKEN=...` at a prompt puts the bearer in your shell history)

Nothing is written anywhere.

Exit: 0 the token is usable (or, with --kubeconfig, every token's expiry was read and none has expired)
      1 a token is expired or inside the clock-skew margin (with --kubeconfig, any one of them: this comes first)
      3 undetermined: the token is not a JWT, or carries no `exp` claim, so nothing here can say when it expires (with
        --kubeconfig, a token like that and none expired), or an error the script did not expect
      5 a usage error: no token given, a --file or kubeconfig that cannot be read or is not one, PyYAML missing for
        --kubeconfig, an argument it does not take, or a Python older than 3.10
These are the codes every identity companion uses for 0, 3 and 5; 1 is this script's own finding.
"""
from __future__ import annotations
import argparse, base64, json, os, sys, datetime as dt

SKEW = dt.timedelta(minutes=2)          # clocks disagree; do not call a token dead on the second
EXIT_UNREAD, EXIT_USAGE = 3, 5


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
    """Print the reading. Returns 0 if the token is usable, 1 if it is not, 3 if it carries no `exp` to say."""
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
        print("\n  UNDETERMINED: nothing here can say whether the next call works (exit 3).")
        return EXIT_UNREAD
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
    values and would silently report nothing at all. 1 when any token has expired; else 3 when any
    token's expiry cannot be read (opaque, or no `exp`); else 0.
    """
    try:
        import yaml
    except ImportError:
        print("this mode needs PyYAML (pip install pyyaml)"); return EXIT_USAGE
    path = os.environ.get("KUBECONFIG") or os.path.expanduser("~/.kube/config")
    if not os.path.exists(path):
        print(f"no kubeconfig at {path}"); return EXIT_USAGE
    try:
        with open(path, encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
    except (OSError, ValueError, yaml.YAMLError) as e:
        print(f"could not read the kubeconfig at {path}: {type(e).__name__}")
        return EXIT_USAGE
    if not isinstance(cfg, dict) or not isinstance(cfg.get("users") or [], list):
        print(f"{path} is not a kubeconfig: no mapping with a users list")
        return EXIT_USAGE
    users = cfg.get("users") or []
    if not users:
        print("kubeconfig declares no users"); return 0
    bad = unknown = 0
    print(f"{len(users)} credential(s) in {path}\n")
    for u in users:
        u = u if isinstance(u, dict) else {}
        name, user = str(u.get("name", "?")), (u.get("user") if isinstance(u.get("user"), dict) else {})
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
            print(f"  {name[:52]:54s} opaque token, no readable expiry: UNDETERMINED")
            unknown += 1
            continue
        c = clocks(claims)
        if "exp" not in c:
            print(f"  {name[:52]:54s} no exp claim: UNDETERMINED")
            unknown += 1
            continue
        state = (f"EXPIRED {_fmt(c['remaining'])} ago" if c["expired"]
                 else f"valid {_fmt(c['remaining'])}")
        life = f"  (lifetime {_fmt(c['lifetime'])})" if "lifetime" in c else ""
        print(f"  {name[:52]:54s} {state}{life}")
        bad += 1 if c["expired"] else 0
    if bad:
        print(f"\n{bad} credential(s) expired. A static token has no exec plugin, so kubectl")
        print("cannot renew it: it fails only when you next use it.")
    if unknown:
        print(f"\n{unknown} token(s) carry no readable expiry: whether they still work is not known here"
              + ("" if bad else " (exit 3)."))
    return 1 if bad else (EXIT_UNREAD if unknown else 0)


class _Parser(argparse.ArgumentParser):
    """argparse's own refusal exits 2; here a usage error exits 5, as on every identity companion."""

    def error(self, message: str):
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        raise SystemExit(EXIT_USAGE)


def main(argv: list[str] | None = None) -> int:
    """The run, with two guards around it: a Python older than 3.10 is refused (exit 5), and an error the script did
    not expect exits 3, never 1, which says a token expired."""
    if sys.version_info < (3, 10):  # noqa: UP036  the script is run by readers on their own Python
        print("tokens.py needs Python 3.10 or later", file=sys.stderr)
        return EXIT_USAGE
    try:
        return _run(argv)
    except Exception as e:  # the last guard: whatever was not expected is not known, so exit 3
        print(f"the run stopped on an error it did not expect: {type(e).__name__}: {str(e)[:160]} (exit 3)", file=sys.stderr)
        return EXIT_UNREAD


def _run(argv: list[str] | None = None) -> int:
    ap = _Parser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", nargs="?", default=None, help="'-' to read the token from stdin")
    ap.add_argument("--file", help="read the token from this file")
    ap.add_argument("--kubeconfig", action="store_true", help="read every kubeconfig credential")
    a = ap.parse_args(argv)

    if a.kubeconfig:
        return from_kubeconfig()

    if a.source == "-":
        raw = sys.stdin.read()
    elif a.file:
        try:
            with open(a.file, encoding="utf-8") as fh:
                raw = fh.read()
        except (OSError, UnicodeDecodeError) as e:
            print(f"could not read {a.file}: {type(e).__name__}")
            return EXIT_USAGE
    else:
        raw = os.environ.get("TOKEN", "")
        if not raw:
            ap.print_help()
            print("\nno token given: paste or pipe one with '-', pass --file, or set $TOKEN")
            return EXIT_USAGE

    raw = raw.strip()
    if raw.lower().startswith("bearer "):
        raw = raw[7:].strip()
    claims = decode(raw)
    if claims is None:
        print("This is not a JWT: it carries no readable claims, so nothing here can tell you when")
        print("it expires. An opaque token is not a worse token; it just means the issuer is the")
        print("only thing that knows, and you learn its lifetime from the issuer's documentation")
        print("or by measuring when it stops working.")
        return EXIT_UNREAD
    return report(claims)


if __name__ == "__main__":
    raise SystemExit(main())
