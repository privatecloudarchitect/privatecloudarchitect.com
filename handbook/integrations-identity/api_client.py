#!/usr/bin/env python3
"""api_client.py - one VCF SSO API client for one integration: plan it, create it, and remove it. Plan by default.

Behind the identity broker an integration signs in as a VCF SSO API client of its own: a client on the realm, one VCF
role bound to it, and an API token issued with both of its lifetimes set. This script is that lifecycle on VCF
Operations' fleet identity API, and nothing else:

  plan (no flag)              prints every call it would send, with its body, and changes nothing
  --execute                   1. POST /ssorealms/{realm}/api-clients              the client, by the id you give
                              2. PUT  /ssorealms/{realm}/principals/{uuid}/roles    one VCF role, at the realm's scope
                                                                                     or, with --scope instance, at one
                                                                                     VCF instance's (its id read from
                                                                                     the realm's coverage)
                              3. POST /ssorealms/{realm}/api-tokens                 its token, with both lifetimes
                              then trades the token at the broker for a bearer once, to prove it, and reads the client
                              and its token back; the token goes to --token-file (mode 0600) and is never printed
  --rotate --execute          issues the client a new token with both lifetimes and proves it at the broker. The
                              old tokens stay, so both work while you point the integration at the new one; with
                              --old-token-file it shows the old token still trading in that overlap
  --retire-old --execute      once the integration runs on the new token: deletes every token of the client older
                              than its newest and reads back that one is left. Refused while the client holds only
                              one token, and when its newest is not the one this script issued last; with
                              --old-token-file it shows the old token trading before the delete and refused after
  --teardown --execute        deletes the client's tokens and the client, then reads both lists again for residue

A client that already exists is refused, never adopted, so a run cannot take over an identity someone else made. The
create writes a state file (STATE, default api_client.<client id>.state.json, mode 0600: the client's id and uuid, the
realm it was made in and the ids of the tokens this script issued, no secret; keep it beside the record and do not
publish it), and --rotate, --retire-old and --teardown act only on a client that file records with the same uuid, in
the realm it records, so a mistyped id, a client someone else made under it, or a run that reads another realm is
refused before anything is sent. A client made in the console is rotated and removed in the console. None of them acts
on the client the run is signed in as, a rotation included: run them on the token of the administrator who made the
client, never on the client's own. A teardown of a client that is not there removes nothing and exits 0, so it is safe
to re-run: in the fleet's only realm, or in the realm the state file records. On a fleet of more than one realm, a
teardown, a rotation or a retirement that finds no client where no state file records the realm it was made in exits 3
(NOT READ), because the client may live in a realm this run never read; it never says the client is gone, and never
suggests making it again.

One realm, named. Every run acts in one realm, and the plan and the record name it. With --realm (its name or its id,
as GET /ssorealms lists them) the run acts in that realm; without it, in the fleet's only realm. A fleet holding more
than one realm, with no --realm, and a --realm that names none of the fleet's realms or more than one, are refused
(exit 5) after the realm list is read and before anything else is sent, so a client is never made, or a role never
bound, in a realm nobody chose.

Every list is read to its end: the realm's API clients and its API tokens (people's tokens included) are read page by
page, 50 asked to a page, until the items counted once each (by id) reach the total the fleet states
(pageInfo.totalCount). A page refused, an answer with no list or no total, a total that changes between pages, a page
that adds nothing new, or pages that end (a page shorter than the page size the answer states it served) before the
total is reached, is a read that failed (exit 3), never a shorter list, and a run that could not read a list whole sends
no write that rests on it. Lifetimes outside the bounds the broker held on the reference
estate (an API token of 1,440 to 259,200 minutes, an access token of 30 to 60) are refused before anything is sent.

Env:  OPS_HOST                 VCF Operations FQDN (required)
      OPS_API_TOKEN_FILE       an API token of a user whose fleet role may manage the fleet's API clients: the
                               reference runs sent these writes on a VCF single sign-on user's API token holding VCF
                               Administrator, and no narrower role was tried (mode 0600; OPS_API_TOKEN
                               is read if it is unset, then API_TOKEN_FILE and API_TOKEN), traded at the broker for a
                               bearer: OPS_BROKER_HOST (BROKER_HOST is read when it is unset; default OPS_HOST),
                               BROKER_TENANT (the broker tenant, the realm's path segment; default CUSTOMER;
                               OPS_REALM, its earlier name, is still read)
      OPS_BEARER_FILE          instead, a bearer you already hold
      STATE                    the state file (default api_client.<client id>.state.json)
      TLS_VERIFY=false         only on a self-signed lab CA
      OUT                      the record (default api_client.json; api_client.replay.json under --replay)
Use:  python3 api_client.py --client-id ID --role ROLE --api-token-ttl MIN --access-token-ttl MIN [--token-file PATH]
                            [--scope instance --instance NAME] [--realm REALM] [--execute] [--redact]
      python3 api_client.py --client-id ID --rotate --api-token-ttl MIN --access-token-ttl MIN --token-file NEW
                            [--old-token-file OLD] [--realm REALM] [--execute] [--redact]
      python3 api_client.py --client-id ID --retire-old [--old-token-file OLD] [--realm REALM] [--execute] [--redact]
      python3 api_client.py --client-id ID --teardown [--realm REALM] [--execute] [--redact]
      python3 api_client.py --replay replay/api_client ...   without an estate: nothing is sent and no credential is
                            read, and --execute runs its plan alone (the plan reads nothing); the set beside this
                            script holds the answers the reads get, and a request it holds no answer for is a read
                            that failed (exit 3)
Exit, the first that applies, so a scheduler reads one state from one number:
      2 refused by this script before any write: the client exists (for a create); no state file records the client
        with this uuid (for a rotation, a retirement or a teardown), the state file records it in another realm, or
        there is no client by that id (for a rotation or a retirement, in the fleet's only realm or the realm the
        state file records); the run is signed in as the client, or its bearer is not a JWT this script can read or
        is an API client's that carries no client id (azp), for every write after the create, a rotation included; a retirement while the client holds one token, or whose
        newest token this script did not issue last; or the fleet holds no realm (no client to make, rotate, retire or
        remove in one)
      1 the run did not hold: a write was refused, or the read-back was not what was asked
      3 a read failed or is undetermined: a list or the realm list could not be read (a page refused, an answer with no
        list or no total, a total that changed between pages, a page that added nothing new, or pages that end before
        the total they state), the read-back could not be read, the create answered without the client's uuid (nothing
        more is sent), a teardown, a rotation or a retirement on a fleet of more than one realm that found no client
        where no state file records its realm, the operator's credential was not traded for a bearer, a request that got
        no answer (a write among them: whether it was made is not known), a request a --replay set holds no answer
        for, or an error the script did not expect
      0 the plan printed, or the run held on read-back (the client with its one role and an active token with both
        lifetimes; for a rotation, the new token proved and active beside the old ones, and, when given, the old token
        still trading; for a retirement, one token left, the newest, and, when given, the old token refused; for a
        teardown, no client and no token left, in the fleet's only realm or the realm the state file records)
      5 a usage error (a missing or bad argument or environment variable, a lifetime outside the bounds, a token file
        that exists, with --execute an operator credential file that cannot be read or is empty, a fleet holding more
        than one realm with no --realm, a --realm that names none of the fleet's realms or more than one, a --replay
        directory that cannot be read or holds no replay set), or a Python older than 3.10; nothing is written
      A record refused because an estate value survived the scrub is not written, and never hides the run's result:
      the run's code stands when it is 1, 2 or 3, and a run that held exits 3 (its write was made; the record was not
      written).
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter

AGENT = "api_client.py"
IAM = "/api/fleet-management/iam"
API_TOKEN_GRANT = "urn:custom:vcf:params:oauth:grant-type:api-token"
# The bounds the broker held a create to on the reference estate (minutes), not the documented ranges.
API_TOKEN_TTL = (1440, 259200)
ACCESS_TOKEN_TTL = (30, 60)
# One exit contract for every identity companion: 0 nothing to act on, 3 a read failed or is undetermined, 5 a usage
# error; 1 and 2 are this script's own (the run did not hold; refused before any write).
EXIT_OK, EXIT_NOT_HELD, EXIT_REFUSED, EXIT_UNREAD, EXIT_USAGE = 0, 1, 2, 3, 5


# ── replay: recorded answers in place of the estate (the same block, byte for byte, in every identity companion) ──
# --replay DIR answers every request from the recorded answers in DIR's *.json files, so a reader runs the tool without
# an estate and a test drives its real code path. An answer is chosen by the request's method, path and query (an
# answer may also name the host, headers the request must carry, such as an organization's tenant context, or a string
# its body must hold); the most specific answer that fits is given, and several answers to one request are given in
# their order, the last one again after that.
# Nothing is sent while a set is loaded: _urlopen answers from the set and never reaches the network, no credential is
# read, a request the set holds no answer for is a read that did not happen (exit 3, never an empty answer), and a
# writing mode runs its plan alone. A set may name the time its answers were recorded ("now"), so a run judges dates
# as it did then, and the hosts it recorded ("env"), never a credential.
REPLAY = None  # the loaded set; None while the tool runs against an estate
REPLAY_CREDENTIAL = "replay-placeholder"  # what a replayed run holds instead of a credential: nothing is sent
REPLAY_ANSWER_KEYS = {"method", "path", "query", "host", "request_headers", "body_contains", "status", "body", "text",
                      "headers", "fail", "note"}
REPLAY_SET_KEYS = {"replay", "about", "source", "now", "env", "answers"}


class ReplayMiss(urllib.error.URLError):
    """A request the replay set holds no answer for: a read that did not happen, never an empty answer."""


class _Replayed:
    """A recorded answer in the shape urllib.request.urlopen returns."""

    def __init__(self, url, status, headers, raw):
        self.url, self.status, self.code, self.headers, self.reason, self._raw = url, status, status, headers, "", raw

    def read(self, amt=None):
        out = self._raw if amt is None else self._raw[:amt]
        self._raw = self._raw[len(out):]
        return out

    def getcode(self):
        return self.status

    def geturl(self):
        return self.url

    def info(self):
        return self.headers

    def getheader(self, name, default=None):
        return self.headers.get(name, default)

    def close(self):
        self._raw = b""

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()
        return False


def _replay_tokens(value):
    """{"$jwt": {claims}} anywhere in an answer becomes an unsigned token carrying those claims, made here: a set holds
    no token, and a token made here was never issued by anything."""
    import base64

    def part(obj):
        return base64.urlsafe_b64encode(json.dumps(obj, separators=(",", ":")).encode()).rstrip(b"=").decode()

    if isinstance(value, dict):
        if set(value) == {"$jwt"} and isinstance(value["$jwt"], dict):
            return f"{part({'alg': 'none', 'typ': 'JWT'})}.{part(value['$jwt'])}.cmVwbGF5"
        return {k: _replay_tokens(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_replay_tokens(v) for v in value]
    return value


def _replay_check(name, doc):
    """Why a set file cannot be replayed, or None."""
    if not isinstance(doc, dict) or not isinstance(doc.get("answers"), list):
        return f"{name}: no answers list"
    if set(doc) - REPLAY_SET_KEYS:
        return f"{name}: keys a set does not take: {', '.join(sorted(set(doc) - REPLAY_SET_KEYS))}"
    env = doc.get("env", {})
    if not isinstance(env, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
        return f"{name}: env is not a map of names to values"
    secret = [k for k in env if any(w in k.upper() for w in ("TOKEN", "SECRET", "PASSWORD", "BEARER", "KEY", "CERT"))]
    if secret:
        return f"{name}: env names a credential ({', '.join(secret)}); a set carries none"
    for i, a in enumerate(doc["answers"]):
        where = f"{name} answer {i + 1}"
        if not isinstance(a, dict):
            return f"{where}: not an object"
        if set(a) - REPLAY_ANSWER_KEYS:
            return f"{where}: keys an answer does not take: {', '.join(sorted(set(a) - REPLAY_ANSWER_KEYS))}"
        if not isinstance(a.get("method"), str) or not isinstance(a.get("path"), str) or not a["path"].startswith("/"):
            return f"{where}: needs a method and a path that starts with /"
        query = a.get("query", {})
        if query != "*" and not (isinstance(query, dict) and all(
                isinstance(v, str) or (isinstance(v, list) and all(isinstance(x, str) for x in v))
                for v in query.values())):
            return f"{where}: query is not a map of names to values, or *"
        status = a.get("status", 200)
        if isinstance(status, bool) or not isinstance(status, int) or not 100 <= status <= 599:
            return f"{where}: status is not an HTTP status"
        if "body" in a and "text" in a:
            return f"{where}: holds both body and text"
        if not all(isinstance(a.get(k, {}), dict) for k in ("headers", "request_headers")):
            return f"{where}: headers or request_headers is not a map"
        if not isinstance(a.get("fail", ""), str) or not isinstance(a.get("body_contains", ""), str):
            return f"{where}: fail is not a reason, or body_contains is not a string"
    return None


class Replay:
    """The recorded answers in one directory's *.json files, read in name order."""

    def __init__(self, directory):
        from datetime import datetime

        names = sorted(n for n in os.listdir(directory) if n.endswith(".json"))
        if not names:
            raise ValueError(f"{directory} holds no *.json answer file")
        self.directory, self.answers, self.env, self.now = directory, [], {}, None
        self.asked, self.missed, self.answered = {}, [], 0
        for name in names:
            with open(os.path.join(directory, name), encoding="utf-8") as f:
                doc = json.load(f)
            why = _replay_check(name, doc)
            if why:
                raise ValueError(why)
            self.answers += doc["answers"]
            self.env.update(doc.get("env", {}))
            if doc.get("now"):
                now = datetime.fromisoformat(str(doc["now"]).replace("Z", "+00:00"))
                if now.tzinfo is None:
                    raise ValueError(f"{name}: now carries no offset")
                if self.now is not None and now != self.now:
                    raise ValueError(f"{name}: now differs from another file's")
                self.now = now

    def answer(self, req):
        """The recorded answer to one request, as urlopen would give it; ReplayMiss when the set holds none."""
        import email.message
        import io

        if isinstance(req, str):
            req = urllib.request.Request(req)
        method = req.get_method().upper()
        url = urllib.parse.urlsplit(req.full_url)
        path, host = urllib.parse.unquote(url.path), url.hostname
        query = urllib.parse.parse_qs(url.query, keep_blank_values=True)
        sent = req.data.decode("utf-8", "replace") if isinstance(req.data, bytes) else ""
        carried = {k.lower(): str(v) for k, v in req.header_items()}

        def fits(a):
            if a["method"].upper() != method or urllib.parse.unquote(a["path"]) != path:
                return False
            if a.get("host") not in (None, host) or a.get("body_contains", "") not in sent:
                return False
            if any(carried.get(k.lower()) != str(v) for k, v in a.get("request_headers", {}).items()):
                return False
            want = a.get("query", {})
            return want == "*" or (set(want) == set(query) and all(
                v == "*" or (v if isinstance(v, list) else [v]) == query[k] for k, v in want.items()))

        def weight(a):  # the most specific answer is given: an exact query over a "*", a named host over none
            want = a.get("query", {})
            exact = 0 if want == "*" else 1 if "*" in want.values() else 2
            return exact, "host" in a, len(a.get("request_headers", {})), "body_contains" in a

        hits = [a for a in self.answers if fits(a)]
        hits = [a for a in hits if weight(a) == max(map(weight, hits))]
        shown = f"{method} {url.path}" + (f"?{url.query}" if url.query else "")
        if not hits:
            self.missed.append(shown)
            print(f"replay: the set holds no answer for {shown}: a read that did not happen", file=sys.stderr)
            raise ReplayMiss(f"replay: no recorded answer for {method} {url.path}")
        key = tuple(id(a) for a in hits)
        a = hits[min(self.asked.get(key, 0), len(hits) - 1)]
        self.asked[key] = self.asked.get(key, 0) + 1
        self.answered += 1
        if a.get("fail"):
            raise urllib.error.URLError(f"replay: {a['fail']}")
        headers = email.message.Message()
        for k, v in _replay_tokens(a.get("headers", {})).items():
            headers[k] = str(v)
        if "body" in a:
            raw, kind = json.dumps(_replay_tokens(a["body"])).encode(), "application/json"
        else:
            raw, kind = str(a.get("text", "")).encode(), "text/plain"
        if raw and headers.get("Content-Type") is None:
            headers["Content-Type"] = kind
        status = a.get("status", 200)
        if status >= 400:
            raise urllib.error.HTTPError(req.full_url, status, "replayed refusal", headers, io.BytesIO(raw))
        return _Replayed(req.full_url, status, headers, raw)


def replay_start(directory):
    """Load the set in DIR for this run. ValueError or OSError when it cannot be replayed: a usage error (exit 5)."""
    global REPLAY
    REPLAY = Replay(directory)
    for k, v in REPLAY.env.items():
        if k not in os.environ:
            os.environ[k] = v
        else:
            REPLAY.env[k] = None  # the reader's own value stands, and stays when the run ends
    print(f"replay: {len(REPLAY.answers)} recorded answers from {directory}; nothing is sent and no credential is read",
          file=sys.stderr)
    return REPLAY


def replay_stop():
    """Unload the set and the hosts it named: a run in a test leaves nothing behind for the next."""
    global REPLAY
    if REPLAY is not None:
        for k, v in REPLAY.env.items():
            if v is not None:
                os.environ.pop(k, None)
    REPLAY = None


def replay_now():
    """The time a replayed set was recorded at, when it names one, or the time now: dates are judged as they were."""
    from datetime import datetime, timezone

    return REPLAY.now if REPLAY is not None and REPLAY.now is not None else datetime.now(timezone.utc)


def _urlopen(req, context=None, timeout=60, opener=None):
    """urllib.request.urlopen, or, with a replay set loaded, its recorded answer: nothing leaves the process."""
    if REPLAY is not None:
        return REPLAY.answer(req)
    if opener is not None:
        return opener.open(req, timeout=timeout)
    return urllib.request.urlopen(req, context=context, timeout=timeout)
# ── end of the replay block ──────────────────────────────────────────────────────────────────────────────────────


# ── HTTP, standard library only ──────────────────────────────────────────────────────────────────────────────────
def _ctx() -> ssl.SSLContext | None:
    if REPLAY is not None:  # a replayed run opens no connection, so it loads no certificate store
        return None
    verify = os.environ.get("TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")
    return ssl.create_default_context() if verify else ssl._create_unverified_context()


def _secret(name: str) -> str:
    if REPLAY is not None:  # a replayed run reads no credential: nothing is sent
        return REPLAY_CREDENTIAL
    path = os.environ.get(f"{name}_FILE")
    if path:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    return os.environ.get(name, "")


def credential_problem() -> str | None:
    """With --execute: an operator credential file named but unreadable or empty, found before anything is sent. A
    usage error (exit 5), never a read that failed."""
    for name in ("OPS_API_TOKEN", "API_TOKEN", "OPS_BEARER"):
        if os.environ.get(f"{name}_FILE"):
            try:
                if not _secret(name):
                    return f"{name}_FILE is empty"
            except (OSError, UnicodeDecodeError) as e:
                return f"{name}_FILE could not be read: {type(e).__name__}"
    return None


def _send(method: str, url: str, body: object | None = None, headers: dict | None = None,
          form: dict | None = None) -> tuple[int, object]:
    """(status, parsed body) for any answer, a refusal included; (0, {}) when the host did not answer."""
    h = {"Accept": "application/json", "User-Agent": AGENT, **(headers or {})}
    data = None
    if form is not None:
        data, h["Content-Type"] = urllib.parse.urlencode(form).encode(), "application/x-www-form-urlencoded"
    elif body is not None:
        data, h["Content-Type"] = json.dumps(body).encode(), "application/json"
    try:
        with _urlopen(urllib.request.Request(url, data=data, method=method, headers=h), context=_ctx(),
                      timeout=60) as r:
            raw = r.read()
            status = r.status
    except urllib.error.HTTPError as e:
        raw, status = e.read() or b"", e.code
    except (urllib.error.URLError, OSError):
        return 0, {}
    try:
        return status, json.loads(raw) if raw else {}
    except ValueError:
        return status, {}


def broker_tenant() -> str:
    """The broker tenant: the realm's path segment in the broker's token URL."""
    return os.environ.get("BROKER_TENANT") or os.environ.get("OPS_REALM") or "CUSTOMER"


def ops_bearer() -> str:
    """The bearer in OPS_BEARER_FILE, or the operator's API token traded at the broker for one."""
    if os.environ.get("OPS_BEARER_FILE"):
        return _secret("OPS_BEARER").removeprefix("Bearer ").strip()
    broker = os.environ.get("OPS_BROKER_HOST") or os.environ.get("BROKER_HOST") or os.environ["OPS_HOST"]
    status, answer = _send("POST", f"https://{broker}/acs/t/{broker_tenant()}/token",
                           form={"grant_type": API_TOKEN_GRANT, "api_token": (_secret("OPS_API_TOKEN") or _secret("API_TOKEN"))})
    if status != 200 or not isinstance(answer, dict) or "access_token" not in answer:
        # a deleted API token is refused here, not with 401: HTTP 500 on 9.1.0 (2026-09-16), HTTP 400 for a deleted API
        # client token on 9.1.1 (X-153, X-190); check the token still exists, then its expiry, before the service
        raise RuntimeError(f"the broker did not trade the operator's API token for a bearer (HTTP {status})")
    return answer["access_token"]


class Fleet:
    """VCF Operations' fleet identity API under one bearer; every call kept, with its path templated."""

    def __init__(self, host: str, bearer: str, calls: list):
        self.base, self.bearer, self.calls = f"https://{host}/suite-api{IAM}", bearer, calls

    def call(self, method: str, path: str, shown: str, body: object | None = None) -> tuple[int, object]:
        status, answer = _send(method, self.base + path, body, {"Authorization": f"Bearer {self.bearer}"})
        rec = {"method": method, "path": shown, "status": status}
        if status >= 400 and isinstance(answer, dict):   # the fleet's own reason for a refusal, kept short
            rec["message"] = str(answer.get("message") or answer.get("errorMessage") or answer.get("error") or "")[:200]
        self.calls.append(rec)
        return status, answer


# ── the plan: every call and body, from the arguments alone ──────────────────────────────────────────────────────
REALM_SCOPE = {"scopeType": "SSO_REALM", "resources": []}


def instance_scope(instance_id: str, name: str) -> dict:
    """One VCF instance's scope: what a role bound at it reaches is that instance's components, not the realm's."""
    return {"scopeType": "VCF_INSTANCE", "resources": [{"id": instance_id, "name": name}]}


def create_bodies(client_id: str, role: str, api_ttl: int, access_ttl: int, description: str,
                  scope: dict | None = None) -> list[dict]:
    """The three writes that make one client with one role and one token, in the order they are sent."""
    return [
        {"method": "POST", "path": "/ssorealms/{realm}/api-clients",
         "body": {"clientId": client_id, "clientName": client_id, "clientDescription": description}},
        {"method": "PUT", "path": "/ssorealms/{realm}/principals/{client uuid}/roles",
         "body": {"vcfRoleAssignments": [{"roleName": role, "roleScope": scope or REALM_SCOPE}]}},
        {"method": "POST", "path": "/ssorealms/{realm}/api-tokens",
         "body": {"apiClientId": client_id, "tokenName": f"{client_id}-token", "tokenType": "API_CLIENT",
                  "apiTokenTtl": api_ttl, "accessTokenTtl": access_ttl}},
    ]


def rotate_calls(client_id: str, api_ttl: int, access_ttl: int) -> list[dict]:
    """A rotation in the order it is sent: a new token issued and proved, and nothing deleted. The old tokens go with
    --retire-old, once the integration runs on the new one."""
    return [{"method": "POST", "path": "/ssorealms/{realm}/api-clients/query and api-tokens/query, ?page=N&pageSize=50 to the stated total: the client and the tokens it holds",
             "body": {}},
            {"method": "POST", "path": "/ssorealms/{realm}/api-tokens",
             "body": {"apiClientId": client_id, "tokenName": f"{client_id}-token-<UTC stamp>", "tokenType": "API_CLIENT",
                      "apiTokenTtl": api_ttl, "accessTokenTtl": access_ttl}},
            {"method": "POST", "path": "/acs/t/{broker tenant}/token at the broker  (the new token, once; with --old-token-file the old one too)",
             "body": None},
            {"method": "POST", "path": "/ssorealms/{realm}/api-tokens/query, every page; read back: the new token active beside the old", "body": {}}]


def retire_calls() -> list[dict]:
    """A retirement in the order it is sent: every token older than the newest deleted, then the read-back."""
    return [{"method": "POST", "path": "/ssorealms/{realm}/api-clients/query and api-tokens/query, ?page=N&pageSize=50 to the stated total: the client and the tokens it holds",
             "body": {}},
            {"method": "POST", "path": "/acs/t/{broker tenant}/token at the broker  (with --old-token-file: the old token, before the delete)",
             "body": None},
            {"method": "DELETE", "path": "/ssorealms/{realm}/api-tokens/{token id}  (each token older than the newest)", "body": None},
            {"method": "POST", "path": "/acs/t/{broker tenant}/token at the broker  (with --old-token-file: the old token again, expected refused)",
             "body": None},
            {"method": "POST", "path": "/ssorealms/{realm}/api-tokens/query, every page; read back: one token left", "body": {}}]


def teardown_calls(client_id: str) -> list[dict]:
    return [{"method": "POST", "path": "/ssorealms/{realm}/api-tokens/query and api-clients/query, ?page=N&pageSize=50 to the stated total", "body": {}},
            {"method": "DELETE", "path": "/ssorealms/{realm}/api-tokens/{token id}  (each of the client's tokens)", "body": None},
            {"method": "DELETE", "path": f"/ssorealms/{{realm}}/api-clients/{client_id}", "body": None},
            {"method": "POST", "path": "/ssorealms/{realm}/api-clients/query and api-tokens/query, every page: residue", "body": {}}]


def bounds_error(api_ttl: int | None, access_ttl: int | None) -> str | None:
    if api_ttl is None or access_ttl is None:
        return "set both lifetimes: --api-token-ttl and --access-token-ttl, in minutes"
    if not API_TOKEN_TTL[0] <= api_ttl <= API_TOKEN_TTL[1]:
        return f"--api-token-ttl {api_ttl} is outside the broker's bounds of {API_TOKEN_TTL[0]} to {API_TOKEN_TTL[1]} minutes"
    if not ACCESS_TOKEN_TTL[0] <= access_ttl <= ACCESS_TOKEN_TTL[1]:
        return f"--access-token-ttl {access_ttl} is outside the broker's bounds of {ACCESS_TOKEN_TTL[0]} to {ACCESS_TOKEN_TTL[1]} minutes"
    return None


# ── the reads every run makes ────────────────────────────────────────────────────────────────────────────────────
def _shape(fleet: Fleet, why: str) -> None:
    """Mark the last call's record with why its answer was not a read, so the report says what was short."""
    if fleet.calls and isinstance(fleet.calls[-1], dict):
        fleet.calls[-1]["shape"] = why


def realm_list(fleet: Fleet) -> list[dict] | None:
    """The fleet's realms, each with its id and its name; [] when the fleet answered and holds none; None when the read
    failed: a refused answer, an answer without its ssoRealms list, or a realm without an id."""
    status, answer = fleet.call("GET", "/ssorealms", "/ssorealms")
    if status != 200 or not isinstance(answer, dict) or not isinstance(answer.get("ssoRealms"), list):
        if status == 200:
            _shape(fleet, "no ssoRealms list in the answer")
        return None
    realms = [{"id": str(r.get("id") or ""), "name": str(r.get("name") or "")} for r in answer["ssoRealms"]
              if isinstance(r, dict)]
    if len(realms) != len(answer["ssoRealms"]) or any(not r["id"] for r in realms):
        _shape(fleet, "a realm without an id")
        return None
    return realms


def choose_realm(realms: list[dict], asked: str | None) -> tuple[dict | None, str | None]:
    """The one realm a run acts in, and None; or None and why no realm can be chosen (a usage error, exit 5). With
    --realm, the realm whose name or id it gives, compared without case after trimming; without it, the fleet's only
    realm. A fleet of more than one realm with no --realm is refused, so nothing is made in a realm nobody chose."""
    held = ", ".join(r["name"] or r["id"] for r in realms)
    if asked and asked.strip():
        want = asked.strip().lower()
        hits = [r for r in realms if want in (r["name"].lower(), r["id"].lower())]
        if len(hits) == 1:
            return hits[0], None
        if not hits:
            return None, f"--realm {asked.strip()} names none of the fleet's realms ({held})"
        return None, f"--realm {asked.strip()} names {len(hits)} realms by that name; give its id ({held})"
    if len(realms) == 1:
        return realms[0], None
    return None, (f"the fleet holds {len(realms)} realms ({held}); name the one to act in with --realm, by its name or "
                  "its id")


def realm_words(realm: dict) -> str:
    """How the plan, the report and the record name a realm: its name, or its id when it has none."""
    return realm.get("name") or realm.get("id") or ""


def realm_refusal(state: dict, realm: dict) -> str | None:
    """Why a rotation, a retirement or a teardown is refused before anything is sent: the state file records the client
    in another realm than the one this run reads, where a teardown would find nothing and report the client gone."""
    made_in = state.get("realm_id")
    if made_in and made_in != realm.get("id"):
        return (f"the state file records this client in realm {state.get('realm') or made_in}, and this run reads realm "
                f"{realm_words(realm)}: run it with --realm naming the realm the client was made in")
    return None


def instances(fleet: Fleet, rid: str) -> dict[str, str] | None:
    """The VCF instances the realm covers, name to id, from the realm's own coverage."""
    status, answer = fleet.call("GET", f"/ssorealms/{rid}", "/ssorealms/{realm}")
    if status != 200 or not isinstance(answer, dict):
        return None
    return {str(c.get("name")): str(c.get("id")) for c in answer.get("ssoRealmCoverage") or []
            if c.get("ssoEntityType") == "VCF_INSTANCE" and c.get("id")}


# The fleet's queries take `page` (from 0) and `pageSize` as query parameters, 50 by default (the 9.1.1 specification);
# a pageSize sent in the body is not read. The token list covers the whole realm, people's tokens included.
PAGE_SIZE = 50
MAX_PAGES = 10000


def _item_id(row: dict) -> str | None:
    """What a row is counted once by: a token's id, a client's uuid, or its client id."""
    ident = row.get("id") or row.get("clientUuid") or row.get("clientId")
    return str(ident) if ident else None


def served_size(info: object, asked: int) -> int:
    """The page size the fleet served: pageInfo.pageSize when the answer states a positive one, else the size asked. A
    fleet may serve fewer than it was asked for (asked 500, the reference estate answered 50), so a page is short only
    against the size it was served at, never against the size asked."""
    size = info.get("pageSize") if isinstance(info, dict) else None
    return size if isinstance(size, int) and not isinstance(size, bool) and size > 0 else asked


def fleet_pages(fleet: Fleet, rid: str, kind: str, key: str) -> list[dict] | None:
    """Every page of one fleet IAM query (`kind` is api-clients or api-tokens), read until the items counted once each,
    by id, reach the total the answer states (pageInfo.totalCount). None, never a shorter list, when a page is refused,
    an answer carries no list under `key` or no total, the total changes between pages, an item carries no id, a page
    adds no item not already read, more distinct items come back than the total states, or a page comes back empty or
    short (against the page size the answer states it served) before the total is reached: a list read in part is not
    a list, and a teardown or a retirement that trusted one could leave a token alive. A row repeated on a later page
    (the list moved under the read) is counted once."""
    found: dict[str, dict] = {}
    total: int | None = None
    for page in range(MAX_PAGES):
        query = f"page={page}&pageSize={PAGE_SIZE}"
        status, answer = fleet.call("POST", f"/ssorealms/{rid}/{kind}/query?{query}",
                                    f"/ssorealms/{{realm}}/{kind}/query?{query}", {})
        if status != 200 or not isinstance(answer, dict) or not isinstance(answer.get(key), list):
            if status == 200:   # a 200 that lists nothing read nothing
                _shape(fleet, f"no {key} list in the answer")
            return None
        info = answer.get("pageInfo")
        stated = info.get("totalCount") if isinstance(info, dict) else None
        if not isinstance(stated, int) or isinstance(stated, bool) or stated < 0:
            _shape(fleet, "no total in the answer (pageInfo.totalCount), so the list cannot be known whole")
            return None
        if total is not None and stated != total:
            _shape(fleet, f"the total moved from {total} to {stated} between pages")
            return None
        total = stated
        rows = answer[key]
        if any(not isinstance(r, dict) or not _item_id(r) for r in rows):
            _shape(fleet, "an item without an id, which cannot be counted once")
            return None
        before = len(found)
        for r in rows:
            found.setdefault(_item_id(r), r)
        if len(found) == total:
            return list(found.values())
        if len(found) > total:
            _shape(fleet, f"{len(found)} distinct items where the answer states {total}")
            return None
        if len(rows) < served_size(info, PAGE_SIZE) or len(found) == before:
            _shape(fleet, f"the pages ended at {len(found)} of the {total} the answer states")
            return None
    _shape(fleet, f"more than {MAX_PAGES} pages")
    return None


def clients(fleet: Fleet, rid: str) -> list[dict] | None:
    return fleet_pages(fleet, rid, "api-clients", "apiClients")


def tokens(fleet: Fleet, rid: str) -> list[dict] | None:
    return fleet_pages(fleet, rid, "api-tokens", "apiTokens")


def mine(rows: list[dict], client_id: str) -> list[dict]:
    """The client's own rows: the client, and its tokens. The token list covers the whole realm, so a person's token
    (tokenType USER) is never the client's, whatever its principal name reads."""
    return [r for r in rows if r.get("tokenType") != "USER"
            and client_id in (r.get("clientId"), r.get("clientName"), r.get("apiClientId"), r.get("principalName"))]


def readback(fleet: Fleet, rid: str, client_id: str, keep: str | None = None) -> dict:
    """What the fleet holds for the client now: its roles, and each token's status and lifetimes. No token value. With
    `keep`, a token id, whether that token is among the client's: a retirement holds only when the one left is it."""
    cl, tk = clients(fleet, rid), tokens(fleet, rid)
    if cl is None or tk is None:
        return {"error": "a list could not be read"}
    c = mine(cl, client_id)
    kept = {"newest_kept": any(t.get("id") == keep for t in mine(tk, client_id))} if keep else {}
    return {**kept, "client_present": bool(c),
            "roles": sorted({r.get("roleName") for x in c for r in (x.get("roles") or [])} - {None}),
            "role_scopes": sorted({(r.get("roleScope") or {}).get("scopeType") for x in c for r in (x.get("roles") or [])} - {None}),
            "scope_resources": sorted({str(res.get("name") or res.get("id")) for x in c for r in (x.get("roles") or [])
                                       for res in (r.get("roleScope") or {}).get("resources") or []}),
            "tokens": [{"status": t.get("tokenStatus"), "api_token_ttl_min": t.get("apiTokenTtl"),
                        "access_token_ttl_min": t.get("accessTokenTtl")} for t in mine(tk, client_id)]}


def prove(token: str) -> dict:
    """Trade the new API token at the broker once: the status, and the bearer's principal type and lifetime. The
    token and the bearer stay in memory."""
    broker = os.environ.get("OPS_BROKER_HOST") or os.environ.get("BROKER_HOST") or os.environ["OPS_HOST"]
    status, answer = _send("POST", f"https://{broker}/acs/t/{broker_tenant()}/token",
                           form={"grant_type": API_TOKEN_GRANT, "api_token": token})
    out = {"status": status}
    bearer = answer.get("access_token") if isinstance(answer, dict) else None
    if bearer:
        seg = bearer.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4)))
        out.update({"principal_type": claims.get("prn_type"),
                    "bearer_lifetime_min": round(((claims.get("exp") or 0) - (claims.get("iat") or 0)) / 60, 1)})
    return out


def claims_of(bearer: str | None) -> dict | None:
    """A bearer's payload, read without a network call; None when it is not a JWT. Nothing of it is printed."""
    try:
        seg = (bearer or "").split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4)))
    except (IndexError, ValueError):
        return None
    return claims if isinstance(claims, dict) else None


def signed_in_as(bearer: str | None) -> dict:
    """Who the run is signed in as, from its own bearer: a person, or an API client and its id. An API client's bearer
    reads prn_type SERVICE with its client id in azp (on the reference estate its prn carried a uuid that was not the
    client's clientUuid, so the id is what names it)."""
    claims = claims_of(bearer)
    if claims is None:
        return {"type": None}
    kind = claims.get("prn_type")
    if kind != "SERVICE":
        return {"type": kind or "unknown"}
    return {"type": "SERVICE", "client": str(claims.get("azp") or "")}


def is_self(me: dict, client_id: str, row: dict | None = None) -> bool:
    """Whether the run is signed in as this client: the client id its own bearer carries."""
    return me.get("type") == "SERVICE" and bool(me.get("client")) and me["client"].lower() == client_id.lower()


def whoami_words(me: dict, client_id: str, row: dict | None) -> str:
    """The record's account of who the run is signed in as, with no name in it."""
    if me.get("type") is None:
        return "not readable: the bearer is not a JWT"
    if me["type"] != "SERVICE":
        return "a person's token" if me["type"] == "USER" else f"a principal of type {me['type']}"
    if not me.get("client"):
        return "an API client whose id the bearer does not carry"
    return "this client itself" if is_self(me, client_id, row) else "another API client"


def state_path(client_id: str) -> str:
    """The state file the create writes and every later write reads: STATE, or one per client id in this folder."""
    return os.environ.get("STATE") or f"api_client.{re.sub(r'[^A-Za-z0-9._-]', '_', client_id)}.state.json"


def load_state(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def save_state(path: str, state: dict) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1)
    os.chmod(path, 0o600)


def owned(state: dict, client_id: str, row: dict | None) -> bool:
    """Whether the state file records this client as one this script made: the same id, and the same uuid."""
    uuid = (row or {}).get("clientUuid")
    return bool(state.get("tool") == AGENT and state.get("client_id") == client_id and uuid
                and state.get("client_uuid") == uuid)


def elsewhere(record: dict, state: dict, rid: str) -> str | None:
    """Why a client this realm's list, read whole, does not hold may still live in another realm, or None when this
    realm is the only place it can be: the fleet's only realm, or the realm the state file records. On a fleet of more
    than one realm with no state file naming this realm, the run looked in one realm of several, so whether the client
    exists was not read (C11 N4): every write after the create, a rotation and a retirement as much as a teardown,
    then exits 3 (NOT READ), never "not there" and never a suggestion to make the client again."""
    if (record.get("realms_in_fleet") or 1) <= 1 or state.get("realm_id") == rid:
        return None
    return (f"no client by that id in realm {record.get('realm') or rid}, one of the fleet's "
            f"{record.get('realms_in_fleet')} realms, and "
            + ("no state file records the realm it was made in" if not state.get("realm_id")
               else "the state file records another realm")
            + ": whether it lives in another realm was not read. Run with --realm naming the realm its create "
              "recorded, from the folder the create ran in or with STATE set")


def guard(fleet: Fleet, client_id: str, row: dict | None, state: dict, record: dict) -> int | None:
    """The refusals every write after the create runs before it sends anything, a rotation as much as a removal: a
    client this script did not make, a bearer this script cannot read, and the client the run is signed in as. None
    when the write may go ahead."""
    me = signed_in_as(getattr(fleet, "bearer", None))
    record["signed_in_as"] = whoami_words(me, client_id, row)
    if not owned(state, client_id, row):
        record["refused"] = ("this script did not make this client: no state file records it with this uuid "
                             f"({'none read' if not state else 'another client recorded'}). A client made in the "
                             "console is rotated and removed in the console; for one made here, run from the folder, "
                             "or with the STATE, its create wrote")
        return EXIT_REFUSED
    if me.get("type") is None:
        record["refused"] = ("the run's bearer is not a readable JWT, so this script cannot rule out acting on the "
                             "client it is signed in as; run it on the token of the administrator who made the client")
        return EXIT_REFUSED
    if me.get("type") == "SERVICE" and not me.get("client"):
        record["refused"] = ("the run's bearer is an API client's and carries no client id (azp), so this script cannot "
                             "rule out acting on the client it is signed in as; run it on the token of the administrator "
                             "who made the client")
        return EXIT_REFUSED
    if is_self(me, client_id, row):
        record["refused"] = ("the run is signed in as this client: a client never rotates or removes itself, because "
                             "once its tokens change or go, no credential outlives the write to read it back or to "
                             "finish it. Run it on the token of the administrator who made the client, or do it in the "
                             "console")
        return EXIT_REFUSED
    return None


# ── create and teardown ──────────────────────────────────────────────────────────────────────────────────────────
def no_answer(what: str) -> str:
    """The record's words for a request that got no answer at all (status 0): never a refusal and never a pass, because
    whether a write that got none was made, or what a trade that got none would have answered, is not known."""
    return f"{what} got no answer, so what it did is not known: read the realm's API clients and tokens before acting"


def create(fleet: Fleet, rid: str, a: argparse.Namespace, record: dict) -> int:
    existing = clients(fleet, rid)
    if existing is None:
        return EXIT_UNREAD
    if mine(existing, a.client_id):
        record["refused"] = "the client exists; this script never adopts a client: --teardown it first, or choose another id"
        return EXIT_REFUSED
    scope = REALM_SCOPE
    if a.scope == "instance":
        covered = instances(fleet, rid)
        if covered is None:
            return EXIT_UNREAD
        if a.instance not in covered:
            record["refused"] = (f"the realm covers no VCF instance named {a.instance}; it covers "
                                 f"{', '.join(sorted(covered)) or 'none'}")
            return EXIT_REFUSED
        scope = instance_scope(covered[a.instance], a.instance)
    post, put, issue = create_bodies(a.client_id, a.role, a.api_token_ttl, a.access_token_ttl, a.description, scope)
    status, answer = fleet.call("POST", f"/ssorealms/{rid}/api-clients", post["path"], post["body"])
    if status == 0:
        record["undetermined"] = no_answer("the create")
        return EXIT_UNREAD
    if status not in (200, 201) or not isinstance(answer, dict):
        return EXIT_NOT_HELD
    uuid = answer.get("clientUuid") or answer.get("id") or answer.get("uuid")
    if not isinstance(uuid, str) or not uuid:   # the role is bound by uuid: never PUT to a principal not named
        record["partial"] = ("the create answered without the client's uuid, so no role was bound and no token issued: "
                             "read the realm's API clients, and remove this one in the console")
        return EXIT_UNREAD
    state_file = state_path(a.client_id)
    state = {"tool": AGENT, "client_id": a.client_id, "client_uuid": uuid, "realm_id": rid, "realm": record.get("realm"),
             "created": replay_now().strftime("%Y-%m-%dT%H:%M:%SZ"), "tokens": []}
    save_state(state_file, state)   # before the role and the token, so a client left part way can still be removed
    record["state_file_written"] = True
    partial = "the client exists without its role or its token: remove it with --teardown --execute before trying again"
    status, _ = fleet.call("PUT", f"/ssorealms/{rid}/principals/{uuid}/roles", put["path"], put["body"])
    if status not in (200, 201, 204):
        record["partial"] = partial
        if status == 0:
            record["undetermined"] = no_answer("the role binding")
            return EXIT_UNREAD
        return EXIT_NOT_HELD
    status, answer = fleet.call("POST", f"/ssorealms/{rid}/api-tokens", issue["path"], issue["body"])
    token = next((answer[k] for k in ("token", "apiToken", "value") if isinstance(answer, dict) and isinstance(answer.get(k), str)), None)
    if status not in (200, 201) or not token:
        record["partial"] = partial
        if status == 0:
            record["undetermined"] = no_answer("the token's issue")
            return EXIT_UNREAD
        return EXIT_NOT_HELD
    fd = os.open(a.token_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(token)
    record["token_file_written"] = True
    record["exchange"] = prove(token)
    del token
    after = tokens(fleet, rid)
    if after is None:   # the token is issued, but which id is its own is not known: never record a guess
        record["partial"] = ("the client, its role and its token are made and the token is in --token-file, but the "
                             "token list could not be read after it, so the state file holds no token id and "
                             "--retire-old will refuse; read it again, or remove the client with --teardown --execute")
        return EXIT_UNREAD
    state["tokens"] = [t["id"] for t in mine(after, a.client_id) if t.get("id")]
    save_state(state_file, state)
    record["readback"] = rb = readback(fleet, rid, a.client_id)
    held = (rb.get("client_present") and rb.get("roles") == [a.role] and rb.get("role_scopes") == [scope["scopeType"]]
            and rb.get("scope_resources") == sorted(str(r.get("name")) for r in scope["resources"])
            and any(t["status"] == "ACTIVE" and t["api_token_ttl_min"] == a.api_token_ttl
                    and t["access_token_ttl_min"] == a.access_token_ttl for t in rb.get("tokens") or [])
            and record["exchange"].get("status") == 200)
    if "error" in rb:
        return EXIT_UNREAD
    if record["exchange"].get("status") == 0:
        record["undetermined"] = no_answer("the token's trade at the broker")
        return EXIT_UNREAD
    return EXIT_OK if held else EXIT_NOT_HELD


def rotate(fleet: Fleet, rid: str, a: argparse.Namespace, record: dict) -> int:
    """Issue a new token and prove it, and leave the old ones: the integration moves to the new token while both
    work, and --retire-old removes the old ones after. The client keeps its id and role, so an integration changes
    only the token it reads; with --old-token-file the record shows the old token still trading in the overlap."""
    cl, tk = clients(fleet, rid), tokens(fleet, rid)
    if cl is None or tk is None:
        return EXIT_UNREAD
    rows = mine(cl, a.client_id)
    state_file = state_path(a.client_id)
    state = load_state(state_file)
    if not rows:
        unread = elsewhere(record, state, rid)
        if unread:   # one realm of several read: the client may be in another, and is never made again here
            record["undetermined"] = unread
            return EXIT_UNREAD
        record["refused"] = "no client by that id; a rotation never creates one: create it first"
        return EXIT_REFUSED
    refused = guard(fleet, a.client_id, rows[0], state, record)
    if refused is not None:
        return refused
    before = {t["id"] for t in mine(tk, a.client_id) if t.get("id")}
    stamp = replay_now().strftime("%Y%m%dT%H%M%SZ")
    body = {"apiClientId": a.client_id, "tokenName": f"{a.client_id}-token-{stamp}", "tokenType": "API_CLIENT",
            "apiTokenTtl": a.api_token_ttl, "accessTokenTtl": a.access_token_ttl}
    status, answer = fleet.call("POST", f"/ssorealms/{rid}/api-tokens", "/ssorealms/{realm}/api-tokens", body)
    token = next((answer[k] for k in ("token", "apiToken", "value") if isinstance(answer, dict) and isinstance(answer.get(k), str)), None)
    if status == 0:
        record["undetermined"] = no_answer("the new token's issue") + "; the old ones are untouched"
        return EXIT_UNREAD
    if status not in (200, 201) or not token:
        record["refused"] = f"the new token was not issued (HTTP {status}); the old ones are untouched"
        return EXIT_NOT_HELD
    fd = os.open(a.token_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(token)
    record["token_file_written"] = True
    record["tokens_before"] = len(before)
    record["exchange"] = prove(token)
    del token
    after = tokens(fleet, rid)
    if after is None:   # the new token is issued, but which id is its own is not known: never record a guess
        record["partial"] = ("the new token is issued and in --token-file, but the token list could not be read after "
                             "it, so the state file does not record it and --retire-old will refuse; the old tokens are "
                             "untouched")
        return EXIT_UNREAD
    new = [t["id"] for t in mine(after, a.client_id) if t.get("id") and t["id"] not in before]
    if len(new) == 1:
        state["tokens"] = [*state.get("tokens", []), new[0]]
        save_state(state_file, state)
    overlap = readback(fleet, rid, a.client_id)
    record["overlap"] = {"active_tokens": sum(1 for t in overlap.get("tokens") or [] if t["status"] == "ACTIVE")}
    if a.old_token_file:
        old = _read(a.old_token_file)
        record["old_token_in_overlap"] = {"status": prove(old)["status"]}
        del old
    record["readback"] = overlap
    unanswered = [w for w, st in (("the new token's trade at the broker", record["exchange"].get("status")),
                                  ("the old token's trade in the overlap",
                                   (record.get("old_token_in_overlap") or {}).get("status", 200))) if st == 0]
    if unanswered:
        record["undetermined"] = no_answer(" and ".join(unanswered)) + "; the old ones are untouched"
        return EXIT_UNREAD
    if record["exchange"].get("status") != 200:
        record["partial"] = ("the new token did not trade at the broker; the old ones are untouched: point nothing at "
                             "the new one, and remove it with --retire-old only once a new token proves")
        return EXIT_NOT_HELD
    record["next"] = "point the integration at the new token, run one job, then --retire-old"
    if "error" in overlap:
        return EXIT_UNREAD
    held = (record["overlap"]["active_tokens"] == len(before) + 1 and len(new) == 1
            and ("old_token_in_overlap" not in record or record["old_token_in_overlap"]["status"] == 200))
    return EXIT_OK if held else EXIT_NOT_HELD


def retire_old(fleet: Fleet, rid: str, a: argparse.Namespace, record: dict) -> int:
    """Delete every token of the client older than its newest, once the integration runs on the newest, and read
    back that one is left. Refused while the client holds one token, when the newest is not the one this script issued
    last, and when the run is signed in as the client; with --old-token-file the record shows the old token trading
    before the delete and refused after it."""
    cl, tk = clients(fleet, rid), tokens(fleet, rid)
    if cl is None or tk is None:
        return EXIT_UNREAD
    rows = mine(cl, a.client_id)
    state = load_state(state_path(a.client_id))
    if not rows:
        unread = elsewhere(record, state, rid)
        if unread:   # one realm of several read: the client may be in another
            record["undetermined"] = unread
            return EXIT_UNREAD
        record["refused"] = "no client by that id"
        return EXIT_REFUSED
    refused = guard(fleet, a.client_id, rows[0], state, record)
    if refused is not None:
        return refused
    held_now = [t for t in mine(tk, a.client_id) if t.get("id")]
    record["tokens_before"] = len(held_now)
    if len(held_now) < 2:
        record["refused"] = ("the client holds one token, so there is nothing older to retire; --rotate issues a new "
                             "one first")
        return EXIT_REFUSED
    if any(t.get("creationDate") is None for t in held_now):
        record["refused"] = "a token carries no creation date, so the newest cannot be told; retire them in the console"
        return EXIT_REFUSED
    newest = max(held_now, key=lambda t: t["creationDate"])
    issued = state.get("tokens") or []
    if not issued or newest["id"] != issued[-1]:
        record["refused"] = ("the newest token is not the one this script issued last, so it may not be the one the "
                             "integration holds: point the integration at the token you mean to keep, and retire the "
                             "others in the console")
        return EXIT_REFUSED
    old = _read(a.old_token_file) if a.old_token_file else None
    if old:
        record["old_token_before_delete"] = {"status": prove(old)["status"]}
    gone = 0
    for t in held_now:
        if t["id"] != newest["id"]:
            status, _ = fleet.call("DELETE", f"/ssorealms/{rid}/api-tokens/{t['id']}", "/ssorealms/{realm}/api-tokens/{token id}")
            gone += status in (200, 204)
    record["deleted"] = gone
    if old:
        record["old_token_after_delete"] = {"status": prove(old)["status"]}
        del old
    record["readback"] = rb = readback(fleet, rid, a.client_id, keep=newest["id"])
    unanswered = [w for w, k in (("the old token's trade before the delete", "old_token_before_delete"),
                                 ("the old token's trade after the delete", "old_token_after_delete"))
                  if k in record and record[k]["status"] == 0]
    if unanswered:   # a trade that got no answer is neither traded nor refused
        record["undetermined"] = no_answer(" and ".join(unanswered))
        return EXIT_UNREAD
    left = rb.get("tokens") or []
    held = (len(left) == 1 and left[0]["status"] == "ACTIVE" and rb.get("newest_kept") is True
            and ("old_token_after_delete" not in record or record["old_token_after_delete"]["status"] != 200))
    if "error" in rb:
        return EXIT_UNREAD
    return EXIT_OK if held else EXIT_NOT_HELD


def _read(path: str) -> str:
    """A token file's value (an old token, to show it trading or refused). A replayed run reads none."""
    if REPLAY is not None:  # a replayed run reads no credential: nothing is sent
        return REPLAY_CREDENTIAL
    with open(path, encoding="utf-8") as f:
        return f.read().strip()


def teardown(fleet: Fleet, rid: str, client_id: str, record: dict) -> int:
    """Delete the client's tokens and the client, then read both lists for residue. Only a client this script made,
    and never the client the run is signed in as; a client that is not there removes nothing and exits 0."""
    tk, cl = tokens(fleet, rid), clients(fleet, rid)
    if tk is None or cl is None:
        return EXIT_UNREAD
    rows = mine(cl, client_id)
    state_file = state_path(client_id)
    state = load_state(state_file)
    if rows:
        refused = guard(fleet, client_id, rows[0], state, record)
        if refused is not None:
            return refused
    elif elsewhere(record, state, rid):
        # the realm read holds no such client, and nothing says the client was made here: on a fleet of more than one
        # realm it may live in another, where it was never looked for (C11 N4). Not read, never "nothing to remove".
        record["undetermined"] = elsewhere(record, state, rid)
        return EXIT_UNREAD
    if rows:
        for t in mine(tk, client_id):
            if t.get("id"):
                fleet.call("DELETE", f"/ssorealms/{rid}/api-tokens/{t['id']}", "/ssorealms/{realm}/api-tokens/{token id}")
        fleet.call("DELETE", f"/ssorealms/{rid}/api-clients/{client_id}", "/ssorealms/{realm}/api-clients/{client id}")
    else:
        record["nothing_to_remove"] = True
    rb = readback(fleet, rid, client_id)
    record["residue"] = {"client_present": rb.get("client_present"), "tokens_left": len(rb.get("tokens") or [])}
    clean = rb.get("client_present") is False and not rb.get("tokens")
    if clean and rows:
        state["removed"] = replay_now().strftime("%Y-%m-%dT%H:%M:%SZ")
        save_state(state_file, state)
    if "error" in rb:
        return EXIT_UNREAD
    return EXIT_OK if clean else EXIT_NOT_HELD


# ── the record contract: every estate value replaced, or nothing written ─────────────────────────────────────────
PRODUCT = {"customer", "sso_realm", "api_client", "active", "expired"}
PATTERNS = [("id", re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")),
            ("host", re.compile(r"\b[a-z0-9-]+(?:\.[a-z0-9-]+)+\.[a-z]{2,}\b", re.I)),
            ("ip", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
            ("name", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)*\b"))]
PLACEHOLDER = re.compile(r"\{\{[a-z-]+-\d+\}\}")
OWN = re.compile(f"({PLACEHOLDER.pattern})")  # splits a text into what lies outside the placeholders and each one


def _strings(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)
    elif isinstance(obj, str):
        yield obj


def estate_values(record: dict, given: list[tuple[str, str]]) -> dict[str, str]:
    table, count = {}, Counter()
    for value, kind in given:
        if value and len(value) >= 3 and value.lower() not in PRODUCT and value not in table:
            count[kind] += 1
            table[value] = f"{{{{{kind}-{count[kind]}}}}}"
    for s in _strings(record):
        for kind, rx in PATTERNS:
            for m in rx.findall(s):
                if m not in table and m.lower() not in PRODUCT:
                    count[kind] += 1
                    table[m] = f"{{{{{kind}-{count[kind]}}}}}"
    return table


def one_pass(table: dict):
    """A text with every registered value replaced by its placeholder in one pass: one alternation, the longest value
    first, matched without regard to case where it is not part of a longer word, and only outside the placeholders
    already in the text. A value spelled like a placeholder (a client named name-1) never rewrites the {{name-1}}
    another value was given, and a second scrub changes nothing. A value registered twice, in two cases, keeps its
    first placeholder."""
    label = {}
    for value, placeholder in table.items():
        label.setdefault(value.lower(), placeholder)
    if not label:
        return lambda text: text
    rx = re.compile(r"(?<![A-Za-z0-9])(?:" + "|".join(re.escape(v) for v in sorted(table, key=len, reverse=True))
                    + r")(?![A-Za-z0-9])", re.I)
    return lambda text: "".join(part if i % 2 else rx.sub(lambda m: label[m.group(0).lower()], part)
                                for i, part in enumerate(OWN.split(text)))


def scrub(obj, table: dict):
    """The record with every registered value replaced by its placeholder in one pass (one_pass). Keys are never
    touched."""
    if not table:
        return obj
    replace = one_pass(table)

    def walk(o):
        if isinstance(o, dict):
            return {k: walk(v) for k, v in o.items()}
        if isinstance(o, list):
            return [walk(v) for v in o]
        return replace(o) if isinstance(o, str) else o

    return walk(obj)


def leaks(obj, table: dict) -> list[str]:
    """Every registered value, and anything shaped like an estate value, still in a scrubbed record, read outside the
    placeholders: a placeholder's own letters are not a surviving value."""
    found = []
    for s in _strings(obj):
        rest = PLACEHOLDER.sub(" ", s)
        found += [k for k in table if re.search(r"(?<![A-Za-z0-9])" + re.escape(k) + r"(?![A-Za-z0-9])", rest, re.I)]
        found += [m for _kind, p in PATTERNS for m in p.findall(rest) if m.lower() not in PRODUCT]
    return found


# ── the run ──────────────────────────────────────────────────────────────────────────────────────────────────────
def plan_lines(a: argparse.Namespace) -> list[str]:
    if a.teardown:
        calls, kind = teardown_calls(a.client_id), "Teardown"
    elif a.retire_old:
        calls, kind = retire_calls(), "Retirement"
    elif a.rotate:
        calls, kind = rotate_calls(a.client_id, a.api_token_ttl, a.access_token_ttl), "Rotation"
    else:
        scope = (instance_scope(f"<id of {a.instance}, from the realm's coverage>", a.instance) if a.scope == "instance"
                 else REALM_SCOPE)
        calls, kind = create_bodies(a.client_id, a.role, a.api_token_ttl, a.access_token_ttl, a.description, scope), "Create"
    out = [f"{kind} plan for API client {a.client_id} on {os.environ.get('OPS_HOST', '<OPS_HOST>')}:",
           (f"  in realm {a.realm.strip()}, the one --realm names (refused, exit 5, if no realm or more than one answers "
            "to it)" if a.realm and a.realm.strip()
            else "  in the fleet's only realm (refused, exit 5, if it holds more than one: name it with --realm)")]
    for c in calls:
        out.append(f"  {c['method']:6} {c['path'] if c['path'].startswith('/acs') else IAM + c['path']}")
        if c.get("body"):
            out.append("         " + json.dumps(c["body"], sort_keys=True))
    if a.rotate:
        out.append(f"  then: the new token to {a.token_file or '<--token-file>'} (mode 0600, never printed); nothing is "
                   "deleted: point the integration at the new token, run one job, then --retire-old")
    elif a.retire_old:
        out.append("  only for a client the state file records, and never on the client's own token; refused while it "
                   "holds one token, or when its newest is not the one this script issued last")
    elif a.teardown:
        out.append("  only for a client the state file records, and never on the client's own token")
    else:
        out.append(f"  then: the token to {a.token_file or '<--token-file>'} (mode 0600, never printed), traded at the broker once, "
                   "and the client and its token read back")
    return out


def report(record: dict) -> list[str]:
    lines = [f"{record['mode']}: API client {record['client']}"
             + (f" in realm {record['realm']}, one of the fleet's {record['realms_in_fleet']}"
                if record.get("realm") and (record.get("realms_in_fleet") or 0) > 1 else "")]
    for c in record.get("calls", []):
        lines.append(f"  {c['method']:6} {c['path']}: HTTP {c['status']}" + (f" ({c['message']})" if c.get("message") else "")
                     + (f" ({c['shape']})" if c.get("shape") else ""))
    if record.get("refused"):
        lines.append(f"  refused: {record['refused']}")
    if record.get("partial"):
        lines.append(f"  stopped part way: {record['partial']}")
    if record.get("undetermined"):
        lines.append(f"  NOT READ: {record['undetermined']}")
    if "exchange" in record:
        e = record["exchange"]
        lines.append(f"  the {'new ' if record.get('mode') == 'rotate' else ''}token traded at the broker: HTTP {e.get('status')}"
                     + (f", a {e.get('principal_type')} bearer living {e.get('bearer_lifetime_min')} min" if e.get("principal_type") else ""))
    if record.get("signed_in_as"):
        lines.append(f"  signed in as: {record['signed_in_as']}")
    if "overlap" in record:
        lines.append(f"  in the overlap: {record['tokens_before']} token(s) held before, {record['overlap']['active_tokens']} active "
                     "with the new one")
    elif record.get("mode") == "retire-old" and "tokens_before" in record:
        lines.append(f"  held before: {record['tokens_before']} token(s)"
                     + (f"; deleted {record['deleted']}, every one older than the newest" if "deleted" in record else ""))
    for key, when in (("old_token_in_overlap", "in the overlap, the old ones kept"),
                      ("old_token_before_delete", "before the delete"), ("old_token_after_delete", "after the delete")):
        if key in record:
            st = record[key]["status"]
            lines.append(f"  the old token at the broker, {when}: HTTP {st}, "
                         + ("traded" if st == 200 else "no answer, not read" if st == 0 else "refused"))
    if "readback" in record:
        rb = record["readback"]
        lines.append(f"  read back: client present {rb.get('client_present')}, roles {', '.join(rb.get('roles') or []) or 'none'} "
                     f"at {', '.join(rb.get('role_scopes') or []) or 'no'} scope"
                     + (f" ({', '.join(rb['scope_resources'])})" if rb.get("scope_resources") else "") + "; tokens "
                     + ("; ".join(f"{t['status']} API {t['api_token_ttl_min']} min, access {t['access_token_ttl_min']} min"
                                  for t in rb.get("tokens") or []) or "none"))
    if record.get("next"):
        lines.append(f"  next: {record['next']}")
    if "residue" in record:
        r = record["residue"]
        lines.append(f"  residue: client present {r['client_present']}, tokens left {r['tokens_left']}"
                     + ("  (there was nothing to remove)" if record.get("nothing_to_remove") else ""))
    lines.append(f"exit {record['exit']}")
    return lines


class _Parser(argparse.ArgumentParser):
    """argparse exits 2 on a usage error, the code this script gives a refusal; it exits 5 here."""

    def __init__(self, *args, **kwargs):  # an abbreviation never parses as a whole flag name
        kwargs.setdefault("allow_abbrev", False)
        super().__init__(*args, **kwargs)

    def error(self, message: str):
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        raise SystemExit(EXIT_USAGE)


def main(argv: list[str] | None = None) -> int:
    """The run, with two guards around it: a Python older than 3.10 is refused (exit 5) before anything is sent, and
    an error the script did not expect exits 3, the code for a read that failed, never 1 or 2."""
    if sys.version_info < (3, 10):  # noqa: UP036  the script is run by readers on their own Python
        print("api_client.py needs Python 3.10 or later", file=sys.stderr)
        return EXIT_USAGE
    try:
        return _run(argv)
    except Exception as e:  # the last guard: whatever was not expected is not known, so exit 3
        print(f"the run stopped on an error it did not expect: {type(e).__name__}: {str(e)[:160]}; read the fleet "
              "before trusting what it holds (exit 3)", file=sys.stderr)
        return EXIT_UNREAD
    finally:
        replay_stop()


def _run(argv: list[str] | None = None) -> int:
    ap = _Parser(description="One VCF SSO API client for one integration: plan, create, remove. Plan by default.")
    ap.add_argument("--client-id", required=True, help="the client's id, also its name; one per integration")
    ap.add_argument("--role", help="the one VCF role the client holds (for example vcf_viewer)")
    ap.add_argument("--scope", choices=("realm", "instance"), default="realm",
                    help="where the role applies: the whole realm (default), or one VCF instance with --instance")
    ap.add_argument("--instance", help="with --scope instance: the VCF instance's name, as the realm's coverage names it")
    ap.add_argument("--realm", help="the realm to act in, by its name or its id as GET /ssorealms lists them; required "
                                    "when the fleet holds more than one realm")
    ap.add_argument("--api-token-ttl", type=int, help="the API token's lifetime in minutes (1440 to 259200)")
    ap.add_argument("--access-token-ttl", type=int, help="the lifetime in minutes of each bearer it yields (30 to 60)")
    ap.add_argument("--token-file", help="where the token is written, mode 0600; it must not exist")
    ap.add_argument("--description", default="an integration's own identity", help="the client's description")
    ap.add_argument("--teardown", action="store_true", help="remove the client and its tokens instead")
    ap.add_argument("--rotate", action="store_true", help="issue a new token and prove it; the old ones stay")
    ap.add_argument("--retire-old", action="store_true",
                    help="delete every token older than the newest, once the integration runs on the newest")
    ap.add_argument("--old-token-file",
                    help="with --rotate or --retire-old: the token the integration held, to show it trading, then refused")
    ap.add_argument("--execute", action="store_true", help="send the calls; without it the plan is printed")
    ap.add_argument("--redact", action="store_true", help="print with placeholders instead of your names")
    ap.add_argument("--replay", metavar="DIR",
                    help="answer every request from the recorded set in DIR (replay/api_client beside this script is "
                         "one): nothing is sent and no credential is read")
    a = ap.parse_args(argv)
    if a.replay:
        try:
            replay_start(a.replay)
        except (OSError, ValueError) as e:
            print(f"--replay {a.replay}: {e}; nothing was sent", file=sys.stderr)
            return EXIT_USAGE
        if a.execute:   # every write this script sends needs --execute: off before anything is read
            print("replay: --execute runs its plan alone under --replay; nothing is sent", file=sys.stderr)
            a.execute = False
    if sum((a.rotate, a.retire_old, a.teardown)) > 1:
        print("--rotate, --retire-old and --teardown are separate runs, not one", file=sys.stderr)
        return EXIT_USAGE
    if (a.scope == "instance") != bool(a.instance):
        print("--scope instance and --instance NAME go together", file=sys.stderr)
        return EXIT_USAGE
    if a.scope == "instance" and (a.rotate or a.retire_old or a.teardown):
        print("--scope is read only when a client is created", file=sys.stderr)
        return EXIT_USAGE
    if a.old_token_file and not (a.rotate or a.retire_old):
        print("--old-token-file is read only with --rotate or --retire-old", file=sys.stderr)
        return EXIT_USAGE
    if a.old_token_file and REPLAY is None and not os.path.exists(a.old_token_file):   # a replayed run reads none
        print(f"{a.old_token_file} does not exist", file=sys.stderr)
        return EXIT_USAGE
    if not (a.teardown or a.retire_old):
        problem = (None if a.role or a.rotate else "--role is required") or bounds_error(a.api_token_ttl, a.access_token_ttl)
        if not problem and a.execute and not a.token_file:
            problem = "--execute needs --token-file, where the token is written (mode 0600)"
        if not problem and a.execute and os.path.exists(a.token_file):
            problem = f"{a.token_file} exists; the token is never written over a file"
        if problem:
            print(problem, file=sys.stderr)
            return EXIT_USAGE
    if a.realm is not None and not a.realm.strip():
        print("--realm is empty: give the realm's name or its id, as GET /ssorealms lists them", file=sys.stderr)
        return EXIT_USAGE
    if not a.execute:
        lines = plan_lines(a)
        if a.redact:   # the plan carries the host, the client id and the realm you gave; a shared transcript none
            given = [(os.environ.get("OPS_HOST", ""), "host"), (a.client_id, "client"), (a.instance or "", "instance"),
                     ((a.realm or "").strip(), "realm")]
            lines = scrub(lines, estate_values({"plan": lines}, [(v, k) for v, k in given if v]))
        print("\n".join(lines))
        print("\nplan only: nothing was sent (--execute sends it)")
        return EXIT_OK
    problem = credential_problem()
    if problem:
        print(f"{problem}; nothing was sent", file=sys.stderr)
        return EXIT_USAGE
    if not os.environ.get("OPS_HOST") or not (os.environ.get("OPS_BEARER_FILE") or (_secret("OPS_API_TOKEN") or _secret("API_TOKEN"))):
        print("OPS_HOST and a VCF Operations credential (OPS_API_TOKEN_FILE or OPS_BEARER_FILE) are required", file=sys.stderr)
        return EXIT_USAGE
    mode = "teardown" if a.teardown else "retire-old" if a.retire_old else "rotate" if a.rotate else "create"
    record = {"captured": replay_now().strftime("%Y-%m-%dT%H:%M:%SZ"),
              "mode": mode, "client": a.client_id, "calls": []}
    if a.rotate:
        record["asked"] = {"api_token_ttl_min": a.api_token_ttl, "access_token_ttl_min": a.access_token_ttl,
                           "old_token_given": bool(a.old_token_file)}
    elif a.retire_old:
        record["asked"] = {"old_token_given": bool(a.old_token_file)}
    elif not a.teardown:
        record["asked"] = {"role": a.role, "scope": "VCF_INSTANCE" if a.scope == "instance" else "SSO_REALM",
                           "api_token_ttl_min": a.api_token_ttl, "access_token_ttl_min": a.access_token_ttl}
        if a.instance:
            record["asked"]["instance"] = a.instance
    try:
        fleet = Fleet(os.environ["OPS_HOST"], ops_bearer(), record["calls"])
    except (RuntimeError, urllib.error.URLError, OSError) as e:
        print(f"could not start: {e}", file=sys.stderr)
        return EXIT_UNREAD
    realms = realm_list(fleet)
    realm, made_in = None, {}
    if realms is None:
        record["exit"] = EXIT_UNREAD
    elif not realms:
        record["refused"] = ("the fleet holds no realm: an API client lives in a realm, so "
                             + ("there is nothing to make it in until VCF single sign-on has one" if mode == "create"
                                else "there is no API client to rotate, retire or remove, and nothing was sent"))
        record["exit"] = EXIT_REFUSED
    else:
        realm, problem = choose_realm(realms, a.realm)
        if problem:   # read the realm list, sent nothing else: a usage error, and no record
            if a.redact:   # a shared transcript names no realm
                names = [(r["name"], "realm") for r in realms] + [((a.realm or "").strip(), "realm")]
                problem = scrub(problem, estate_values({"m": problem}, [(v, k) for v, k in names if v]))
            print(f"{problem}; nothing else was sent and nothing is written (exit {EXIT_USAGE})", file=sys.stderr)
            return EXIT_USAGE
        record["realm"], record["realms_in_fleet"] = realm_words(realm), len(realms)
        made_in = {} if mode == "create" else load_state(state_path(a.client_id))
        refused = realm_refusal(made_in, realm) if made_in else None
        if refused:
            record["refused"], record["exit"] = refused, EXIT_REFUSED
        else:
            rid = realm["id"]
            record["exit"] = (teardown(fleet, rid, a.client_id, record) if a.teardown
                              else retire_old(fleet, rid, a, record) if a.retire_old
                              else rotate(fleet, rid, a, record) if a.rotate else create(fleet, rid, a, record))
    given = ([(os.environ.get(k, ""), "host") for k in ("OPS_HOST", "OPS_BROKER_HOST", "BROKER_HOST")] + [(a.client_id, "client")]
             + [(a.instance or "", "instance"), ((a.realm or "").strip(), "realm")]
             + ([(realm["name"], "realm")] if realm else []) + [(str(made_in.get("realm") or ""), "realm")])
    return write_record(record, given, a.redact,
                        os.environ.get("OUT") or ("api_client.replay.json" if REPLAY is not None else "api_client.json"))


def write_record(record: dict, given: list[tuple[str, str]], redact: bool, out: str) -> int:
    """Print the run, scrub the record and write it; refuse to write one in which an estate value survived. A record
    refused for a surviving value never hides what the run did: its code stands when it is 1, 2 or 3, and a run that
    held exits 3, because its write was made and the record that shows it was not written."""
    table = estate_values(record, [(v, k) for v, k in given if v])
    clean = scrub(record, table)
    left = leaks(clean, table)
    if not (left and redact):   # a redacted print with a surviving value would print that value
        print("\n".join(report(clean if redact else record)))
    if left:
        code = record["exit"] if record["exit"] in (EXIT_NOT_HELD, EXIT_REFUSED, EXIT_UNREAD) else EXIT_UNREAD
        why = ("the run's own code stands" if code == record["exit"]
               else "the run held and its writes were made, but the record that shows them was not written")
        print(f"refusing to write {out}: {len(left)} estate value(s) survived the scrub; {out} not written; exit {code}: "
              f"{why}", file=sys.stderr)
        return code
    with open(out, "w", encoding="utf-8") as f:
        f.write(json.dumps(clean, indent=1, ensure_ascii=False) + "\n")
    print(f"\n{out} written with every estate value replaced")
    return record["exit"]


if __name__ == "__main__":
    sys.exit(main())
