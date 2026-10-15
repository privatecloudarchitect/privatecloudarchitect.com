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
    python3 tokens.py --kubeconfig        every credential in your kubeconfig, no token needed; it reads each token's,
                                          token file's and client certificate's end date, judges each user entry by
                                          the soonest end among all it holds, and names what it cannot judge
    python3 tokens.py                     read a token from $TOKEN, when a tool already set it (typing
                                          `export TOKEN=...` at a prompt puts the bearer in your shell history)

Nothing is written anywhere.

Exit: 0 the token is usable (or, with --kubeconfig, every credential of every user entry was judged and none has run
        out: an exec plugin with a command renews itself, and each token's, token file's and client certificate's end
        date was read)
      1 a token is expired or inside the clock-skew margin (with --kubeconfig, a user entry whose soonest end, among
        every credential it holds, has passed or falls inside the margin: this comes first)
      3 undetermined: the token is not a JWT, or carries no `exp` claim, so nothing here can say when it expires (with
        --kubeconfig, and none run out: a credential it could not judge, which it names, such as an opaque token, a
        certificate or token file it could not read, an exec entry that is not a plugin with a command, an
        auth-provider, a user name and password, or an entry with none of these, even beside one it judged; or a
        kubeconfig that declares no users), or an error the script did not expect
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


def _der(data: bytes, i: int) -> tuple[int, int, int, int]:
    """One DER element at i: its tag, where its content starts, its length, and where the next element starts."""
    tag, n = data[i], data[i + 1]
    i += 2
    if n & 0x80:
        width = n & 0x7F
        n = int.from_bytes(data[i:i + width], "big")
        i += width
    return tag, i, n, i + n


def cert_end(pem: bytes) -> dt.datetime | None:
    """The notAfter of the first certificate in a PEM, read from its DER without a crypto library; None when it is
    not one. Only the date is read: nothing here says the certificate is trusted."""
    try:
        text = pem.decode("ascii")
        body = text.split("-----BEGIN CERTIFICATE-----", 1)[1].split("-----END CERTIFICATE-----", 1)[0]
        der = base64.b64decode("".join(body.split()))
        _, cert, _, _ = _der(der, 0)                    # Certificate
        _, i, _, _ = _der(der, cert)                    # tbsCertificate
        tag, _, _, nxt = _der(der, i)
        i = nxt if tag == 0xA0 else i                   # [0] version, when present
        for _ in range(3):                              # serialNumber, signature, issuer
            i = _der(der, i)[3]
        tag, v, _, _ = _der(der, i)                     # validity
        if tag != 0x30:
            return None
        tag, at, n, _ = _der(der, _der(der, v)[3])      # notAfter, after notBefore
        stamp = der[at:at + n].decode("ascii")
        if tag == 0x17:                                 # UTCTime, YYMMDDHHMMSSZ
            yy = int(stamp[:2])
            stamp = f"{1900 + yy if yy >= 50 else 2000 + yy}{stamp[2:]}"
        elif tag != 0x18:                               # GeneralizedTime, YYYYMMDDHHMMSSZ
            return None
        return dt.datetime.strptime(stamp[:14], "%Y%m%d%H%M%S").replace(tzinfo=dt.timezone.utc)
    except (IndexError, ValueError, UnicodeDecodeError):
        return None


def user_credentials(user: dict, read) -> list[tuple[str, object]]:
    """Every credential one kubeconfig user entry carries, each judged on its own: (what it is, its end). The end is the
    datetime read off it, "renews" for an exec plugin with a command to run, or None when it could not be judged. A
    user entry may carry more than one (a client certificate beside a token, a token beside an exec plugin), and which
    of them a client presents is not read here, so every one is judged, none is left out because another was judged,
    and the soonest end stands for the entry."""
    out: list[tuple[str, object]] = []
    if "exec" in user:
        ex = user.get("exec")
        runs = isinstance(ex, dict) and isinstance(ex.get("command"), str) and bool(ex["command"].strip())
        out.append(("exec plugin, renews itself (it may prompt)", "renews") if runs
                   else ("exec entry that is not a plugin with a command to run", None))
    if user.get("client-certificate-data") or user.get("client-certificate"):
        data = user.get("client-certificate-data")
        try:
            pem = base64.b64decode(data) if isinstance(data, str) and data else read(user.get("client-certificate"))
        except ValueError:
            pem = None
        end = cert_end(pem) if pem else None
        out.append(("client certificate" if end else "client certificate, its end date not read", end))
    for key, where in (("token", "token"), ("tokenFile", "token file")):
        if not user.get(key):
            continue
        if key == "token":
            tok = user.get("token") if isinstance(user.get("token"), str) else None
        else:
            raw = read(user.get("tokenFile"))
            tok = raw.decode("utf-8", "replace").strip() if raw else None
        if not tok:
            out.append((f"{where} that could not be read", None))
            continue
        claims = decode(tok)
        if not claims:
            out.append((f"opaque {where}, no readable expiry", None))
            continue
        c = clocks(claims)
        if "exp" not in c:
            out.append((f"{where} with no exp claim", None))
            continue
        out.append((where + (f" (lifetime {_fmt(c['lifetime'])})" if "lifetime" in c else ""), c["exp"]))
    if "auth-provider" in user:
        out.append(("auth-provider, whose expiry is not read here", None))
    if user.get("username") or user.get("password"):
        out.append(("a user name and password, which state no end", None))
    if not out:
        out.append(("no token, no certificate, no exec plugin", None))
    return out


def from_kubeconfig() -> int:
    """Every credential in the kubeconfig: whether it renews itself, and when the ones that do not run out.

    Reads the file directly rather than shelling out, because `kubectl config view` redacts token
    values and would silently report nothing at all. Every credential of each user entry is judged, and the user is
    judged by the soonest end among them: a credential renews itself (an exec plugin with a command) or its end date
    was read (a token, a token file, a client certificate). 1 when any user's soonest end has passed or falls inside the
    clock-skew margin; else 3 when any user carries a credential that was not judged (an opaque token, no `exp`, a
    certificate or file it could not read, an exec entry that is not a plugin with a command, an auth-provider, a user
    name and password, an entry with none of these) or the file declares no users at all; else 0.
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
        print(f"{path} declares no users, so no credential was judged (exit 3)")
        return EXIT_UNREAD
    here = os.path.dirname(os.path.abspath(path))
    bad, unjudged = 0, []
    now = dt.datetime.now(dt.timezone.utc)
    print(f"{len(users)} user entr{'y' if len(users) == 1 else 'ies'} in {path}, each judged by every credential it holds\n")

    def read(ref: object) -> bytes | None:   # a file a kubeconfig names, relative to the kubeconfig's own folder
        if not isinstance(ref, str) or not ref:
            return None
        try:
            with open(os.path.join(here, os.path.expanduser(ref)), "rb") as fh:
                return fh.read()
        except OSError:
            return None

    for u in users:
        u = u if isinstance(u, dict) else {}
        name, user = str(u.get("name", "?")), (u.get("user") if isinstance(u.get("user"), dict) else {})
        parts = user_credentials(user, read)
        said = []
        for what, end in parts:
            if isinstance(end, dt.datetime):
                left = end - now
                said.append(f"{what}, " + (f"EXPIRED {_fmt(left)} ago" if left.total_seconds() <= 0
                                           else f"valid {_fmt(left)}, inside the clock-skew margin" if left <= SKEW
                                           else f"valid {_fmt(left)}, to {end.date().isoformat()}"))
            else:
                said.append(what)
        ends = [e for _, e in parts if isinstance(e, dt.datetime)]
        soonest = min(ends) if ends else None
        missing = [w for w, e in parts if e is None]
        if soonest is not None and soonest - now <= SKEW:
            bad += 1
            verdict = "  RUN OUT: the soonest end stands"
        elif missing:
            unjudged += [(name, what) for what in missing]
            verdict = ": UNDETERMINED"
        else:
            verdict = ""
        print(f"  {name[:52]:54s} " + "; ".join(said) + (verdict if len(parts) > 1 or verdict.endswith("UNDETERMINED") else ""))
    if bad:
        print(f"\n{bad} user entr{'y' if bad == 1 else 'ies'} with a credential run out or inside the clock-skew margin. A "
              "static token or certificate has nothing to renew it: it fails only when you next use it.")
    if unjudged:
        print(f"\nNOT JUDGED: {len(unjudged)} credential(s) whose end this run could not read: "
              + ", ".join(f"{n[:52]} ({what})" for n, what in unjudged)
              + "; whether they still work is not known here" + ("" if bad else " (exit 3)."))
    return 1 if bad else (EXIT_UNREAD if unjudged else 0)


class _Parser(argparse.ArgumentParser):
    """argparse's own refusal exits 2; here a usage error exits 5, as on every identity companion."""

    def __init__(self, *args, **kwargs):  # an abbreviation never parses as a whole flag name
        kwargs.setdefault("allow_abbrev", False)
        super().__init__(*args, **kwargs)

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
