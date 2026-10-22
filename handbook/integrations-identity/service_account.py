#!/usr/bin/env python3
"""service_account.py - one VCF Automation service account for one integration: plan it, create it, and remove it.

In VCF Automation an integration signs in as a service account of its own: an OAuth client registered in one
organization with one role named in its scope, activated through the device grant (RFC 8628), and holding a refresh
token that lasts until it is revoked. This script is that lifecycle, and nothing else. Plan by default:

  plan (no flag)              prints every call it would send, with its body, and changes nothing
  --execute                   1. POST /oauth/tenant/{org}/register                the client, its role named in the scope
                              2. POST /oauth/tenant/{org}/device_authorization    a device code and a user code
                              3. POST /cloudapi/1.0.0/deviceLookup/grant           you, as the provider, grant the user code
                              4. POST /oauth/tenant/{org}/token                    the device-code grant: a refresh token
                              then reads the bearer's own session (its principal and its roles), refreshes once with the
                              stored token the way the integration will, and reads the account back. The refresh token
                              goes to --token-file (mode 0600) and is never printed
  --teardown --execute        revokes the account's token and deletes the account, then reads the list again for
                              residue; with --token-file, refreshes once with the revoked token to show it is refused

The role is named, never numbered: the scope carries urn:vcloud:role:<the role's name, URL-encoded>, the form Broadcom's
page documents; a scope naming the role's id was refused on the reference estate. An account that already exists is
refused, never adopted, so a run cannot take over an identity someone else made. The register writes a state file
(STATE, default service_account.<org>.<name>.state.json, mode 0600: the organization, the account's name and its
OAuth client id, no secret; keep it beside the record and do not publish it), and --teardown revokes and deletes only
an account that file records with the same client id, so a mistyped name, or an account someone else made under it,
is refused before anything is sent. A teardown of an account that is not there removes nothing and exits 0, so it is
safe to re-run.

Every list is read whole: the organization list and the account list are read page by page until the items counted
once each (by id) reach the total the answer states (resultTotal). A page refused, an answer with no values list or no
total, a total that changes between pages, a page that adds nothing new, or pages that end before the total is reached,
is a list not read (exit 3), never a shorter or an empty one: a teardown that could not read the whole list revokes and
deletes nothing, and a create that could not read it registers nothing.

Env:  VCFA_HOST                           VCF Automation FQDN (required)
      VCFA_PROVIDER_BEARER_FILE           a provider bearer (mode 0600), minted just before the run as the platform-identity
                                          chapter's plate 04, "Your provider bearer", shows. The reference runs sent every
                                          call on a provider System Administrator's bearer, and no narrower provider
                                          role was tried
      VCFA_PROVIDER_REFRESH_TOKEN_FILE    instead, a provider API token, traded at /oauth/provider/token for a bearer
                                          (mode 0600). Untried for these writes: no reference run sent them on one
      STATE                               the state file (default service_account.<org>.<name>.state.json)
      TLS_VERIFY=false                    only on a self-signed lab CA
      OUT                                 the record (default service_account.json; service_account.replay.json
                                          under --replay)
Use:  python3 service_account.py --org ORG --name NAME --role "ROLE NAME" [--token-file PATH] [--execute] [--redact]
            ROLE NAME is the organization's own role name: its member role is Organization User in an All Apps
            organization and Organization Member in a classic one (identity-model's census.py --orgs-only prints the type)
      python3 service_account.py --org ORG --name NAME --teardown [--token-file PATH] [--execute] [--redact]
      python3 service_account.py --replay replay/service_account ...   without an estate: nothing is sent and no
            credential is read, and --execute runs its plan alone (the plan reads nothing); the set beside this script
            holds the answers the reads get, and a request it holds no answer for is a read that failed (exit 3)
Exit, the first that applies, so a scheduler reads one state from one number:
      2 refused by this script before any write: the account exists (for a create), or for a teardown it is not one
        the state file records; or no organization, or more than one, carries that name exactly
      1 the run did not hold: a write was refused (a teardown's revoke among them), or the read-back was not what was
        asked (the account active, its bearer holding exactly the role, the stored token refreshing; for a teardown,
        no account left and, with --token-file, the revoked token refused)
      3 a read failed or is undetermined: the organization or the account list not read whole (a page refused, an answer
        without its list or its total, a total that changed between pages, a page that added nothing new, or pages
        that end before the total they state), the read-back or the residue could not be read back, the provider's
        credential was not traded for a bearer, a request that got no answer (a write among them: whether it was made
        is not known; a refresh among them: neither held nor refused), a request a --replay set holds no answer for,
        or an error the script did not expect
      0 the plan printed, or the run held on read-back: for a create, the account active, its bearer's session holding
        exactly the role and the stored token refreshing; for a teardown, every revoke answered, the organization's
        list read whole with no account by that name left and, with --token-file, the revoked token refused (without
        it the token is not tried, and the record notes it). An account of that name in another organization is not
        read: the organization is the one you name
      5 a usage error (a missing or bad argument or environment variable, a role given as an id, a token file that
        exists for a create or does not for a teardown, with --execute a provider credential file that cannot be read,
        is empty or is open to group or other (refused unread, with the fix: chmod 600), a --replay directory that
        cannot be read or holds no replay set), or a Python older than 3.10; nothing is written
      A record refused because an estate value survived the scrub is not written, and never hides the run's result:
      the run's code stands when it is 1, 2 or 3, and a run that held exits 3 (its writes were made; the record was not
      written).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import Counter

AGENT = "service_account.py"
CLOUDAPI = "application/json;version=9.1.0"
ACCOUNTS_ACCEPT = "application/json;version=10.0.0.0-alpha"  # the version the service account calls were proven with
TENANT_HEADER = "X-VMWARE-VCLOUD-TENANT-CONTEXT"
DEVICE_CODE = "urn:ietf:params:oauth:grant-type:device_code"
ROLE_ID = re.compile(r"(?i)^(?:urn:vcloud:role:)?[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
# One exit contract for every identity companion: 0 nothing to act on, 3 a read failed or is undetermined, 5 a usage
# error; 1 and 2 are this script's own (the run did not hold; refused before any write).
EXIT_OK, EXIT_NOT_HELD, EXIT_REFUSED, EXIT_UNREAD, EXIT_USAGE = 0, 1, 2, 3, 5
POLL_SECONDS, POLL_LIMIT = 5, 12   # the device-code grant is polled until the grant lands, at most a minute
GONE_SECONDS, GONE_LIMIT = 3, 20   # a deleted account leaves the list within a minute on the reference estate


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


def _secret_file(name: str) -> str:
    """The secret in the file NAME names, read through read_secret."""
    if REPLAY is not None:  # a replayed run reads no credential: nothing is sent
        return REPLAY_CREDENTIAL
    return read_secret(name)


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
            raw, status = r.read(), r.status
    except urllib.error.HTTPError as e:
        raw, status = e.read() or b"", e.code
    except (urllib.error.URLError, OSError):
        return 0, {}
    try:
        return status, json.loads(raw) if raw else {}
    except ValueError:
        return status, {}


def provider_bearer(host: str) -> str:
    """The bearer in VCFA_PROVIDER_BEARER_FILE, or the provider's API token traded for one."""
    if os.environ.get("VCFA_PROVIDER_BEARER_FILE"):
        return _secret_file("VCFA_PROVIDER_BEARER_FILE").removeprefix("Bearer ").strip()
    status, answer = _send("POST", f"https://{host}/oauth/provider/token",
                           form={"grant_type": "refresh_token",
                                 "refresh_token": _secret_file("VCFA_PROVIDER_REFRESH_TOKEN_FILE")})
    if status != 200 or not isinstance(answer, dict) or "access_token" not in answer:
        raise RuntimeError(f"the provider's API token was not traded for a bearer (HTTP {status})")
    return answer["access_token"]


class Vcfa:
    """VCF Automation under the provider's bearer; the device calls go unauthenticated. Every call is kept, with its
    path templated, its status and nothing it carried."""

    def __init__(self, host: str, bearer: str, calls: list):
        self.base, self.bearer, self.calls = f"https://{host}", bearer, calls

    def call(self, method: str, path: str, shown: str, body: object | None = None, form: dict | None = None,
             org_urn: str | None = None, accept: str = CLOUDAPI, auth: bool | str = True) -> tuple[int, object]:
        h = {"Accept": accept}
        if auth is True:
            h["Authorization"] = f"Bearer {self.bearer}"
        elif auth:
            h["Authorization"] = f"Bearer {auth}"   # the service account's own bearer
        if org_urn:
            h[TENANT_HEADER] = org_urn
        status, answer = _send(method, self.base + path, body, h, form)
        self.calls.append({"method": method, "path": shown, "status": status})
        return status, answer


# ── the plan: every call and body, from the arguments alone ──────────────────────────────────────────────────────
def role_scope(role: str) -> str:
    return "urn:vcloud:role:" + urllib.parse.quote(role, safe="")


def register_body(name: str, role: str, software_id: str = "<a new UUID>") -> dict:
    return {"client_name": name, "software_id": software_id, "software_version": "1.0", "scope": role_scope(role)}


def create_calls(name: str, role: str) -> list[dict]:
    return [
        {"method": "GET", "path": "/cloudapi/1.0.0/orgs?filter=name=={org}&page=N&pageSize=32  (every page, to the stated total)", "body": None},
        {"method": "GET", "path": "/cloudapi/1.0.0/serviceAccounts?filter=name=={name}&page=N&pageSize=32  (in the organization, every page: refused if present)", "body": None},
        {"method": "POST", "path": "/oauth/tenant/{org}/register", "body": register_body(name, role)},
        {"method": "POST", "path": "/oauth/tenant/{org}/device_authorization", "body": {"client_id": "<from the register>"}},
        {"method": "POST", "path": "/cloudapi/1.0.0/deviceLookup/grant  (in the organization)", "body": {"userCode": "<from the device authorization>"}},
        {"method": "POST", "path": "/oauth/tenant/{org}/token  (polled until the grant lands)",
         "body": {"grant_type": DEVICE_CODE, "client_id": "<from the register>", "device_code": "<from the device authorization>"}},
    ]


def teardown_calls() -> list[dict]:
    return [
        {"method": "GET", "path": "/cloudapi/1.0.0/orgs?filter=name=={org}&page=N&pageSize=32, then serviceAccounts?filter=name=={name}  (every page, to the stated total)", "body": None},
        {"method": "POST", "path": "/cloudapi/1.0.0/serviceAccounts/{id}/revoke", "body": {}},
        {"method": "POST", "path": "/oauth/tenant/{org}/token  (refresh grant with the revoked token, with and without client_id)", "body": None},
        {"method": "DELETE", "path": "/cloudapi/1.0.0/serviceAccounts/{id}", "body": None},
        {"method": "GET", "path": "/cloudapi/1.0.0/serviceAccounts?filter=name=={name}&page=N&pageSize=32  (residue, until it is read empty)", "body": None},
        {"method": "POST", "path": "/oauth/tenant/{org}/token  (the same refresh grant again, after the delete)", "body": None},
    ]


# ── the reads every run makes ────────────────────────────────────────────────────────────────────────────────────
# Items asked for per page; pages count from 1. The service account list refuses a pageSize above 32 (HTTP 400, "must be
# less than or equal to 32", X-260) where the organization list takes 128, so one size that both take serves both.
PAGE_SIZE = 32
MAX_PAGES = 10000


def _shape(vcfa: Vcfa, why: str) -> None:
    """Mark the last call's record with why its answer was not a read, so the report says what was short."""
    if vcfa.calls and isinstance(vcfa.calls[-1], dict):
        vcfa.calls[-1]["shape"] = why


def served_size(answer: dict, asked: int) -> int:
    """The page size VCF Automation served: the answer's pageSize when it states a positive one, else the size asked. A
    page is short only against the size it was served at, never against the size asked, which a service may lower."""
    size = answer.get("pageSize")
    return size if isinstance(size, int) and not isinstance(size, bool) and size > 0 else asked


def vcfa_pages(vcfa: Vcfa, path: str, shown: str, org_urn: str | None = None,
               accept: str = CLOUDAPI) -> list[dict] | None:
    """Every page of one VCF Automation cloudapi list, read until the items counted once each, by id, reach the total
    the answer states (resultTotal). None, never a shorter list, when a page is refused, an answer carries no `values`
    list or no total, the total changes between pages, an item carries no id, a page adds no item not already read,
    more distinct items come back than the total states, or a page comes back empty or short (against the page size
    the answer states it served) before the total is reached: a list read in part is not a list, and a teardown that
    trusted one could leave an account alive. A row repeated on a later page (the list moved under the read) is
    counted once."""
    found: dict[str, dict] = {}
    total: int | None = None
    sep = "&" if "?" in path else "?"
    for page in range(1, MAX_PAGES + 1):
        query = f"page={page}&pageSize={PAGE_SIZE}"
        status, answer = vcfa.call("GET", f"{path}{sep}{query}", f"{shown}{sep}{query}", org_urn=org_urn, accept=accept)
        if status != 200 or not isinstance(answer, dict) or not isinstance(answer.get("values"), list):
            if status == 200:   # a 200 that lists nothing read nothing
                _shape(vcfa, "no values list in the answer")
            return None
        stated = answer.get("resultTotal")
        if not isinstance(stated, int) or isinstance(stated, bool) or stated < 0:
            _shape(vcfa, "no total in the answer (resultTotal), so the list cannot be known whole")
            return None
        if total is not None and stated != total:
            _shape(vcfa, f"the total moved from {total} to {stated} between pages")
            return None
        total = stated
        rows = answer["values"]
        if any(not isinstance(r, dict) or not r.get("id") for r in rows):
            _shape(vcfa, "an item without an id, which cannot be counted once")
            return None
        before = len(found)
        for r in rows:
            found.setdefault(str(r["id"]), r)
        if len(found) == total:
            return list(found.values())
        if len(found) > total:
            _shape(vcfa, f"{len(found)} distinct items where the answer states {total}")
            return None
        if len(rows) < served_size(answer, PAGE_SIZE) or len(found) == before:
            _shape(vcfa, f"the pages ended at {len(found)} of the {total} the answer states")
            return None
    _shape(vcfa, f"more than {MAX_PAGES} pages")
    return None


def org_lookup(vcfa: Vcfa, org: str) -> tuple[int, str | None, int]:
    """(200, the organization's URN, 1) when exactly one organization in the filtered list, read whole, carries the
    name given, character for character; (200, None, n) when n other than one do; (0, None, 0) when the list was not
    read whole. A row the filter returned under another name is never taken for the one named (a filter that matches
    more than the exact name, a wildcard among them, would otherwise hand the register an organization nobody named)."""
    rows = vcfa_pages(vcfa, f"/cloudapi/1.0.0/orgs?filter={urllib.parse.quote('name==' + org)}",
                      "/cloudapi/1.0.0/orgs?filter=name=={org}")
    if rows is None:
        return 0, None, 0
    named = [r for r in rows if r.get("name") == org]
    return 200, (str(named[0]["id"]) if len(named) == 1 else None), len(named)


def accounts(vcfa: Vcfa, urn: str, name: str) -> list[dict] | None:
    """The organization's service accounts by that name, from the filtered list read whole. None, never a shorter
    list, when the list was not read whole: an account on a page not read could be one a teardown leaves."""
    rows = vcfa_pages(vcfa, f"/cloudapi/1.0.0/serviceAccounts?filter={urllib.parse.quote('name==' + name)}",
                      "/cloudapi/1.0.0/serviceAccounts?filter=name=={name}", org_urn=urn, accept=ACCOUNTS_ACCEPT)
    return None if rows is None else [a for a in rows if a.get("name") == name]


def shape(rows: list[dict]) -> dict:
    """What the organization holds for the account: present, its status and its roles. No identifier."""
    return {"present": bool(rows), "status": [a.get("status") for a in rows],
            "roles": sorted({r.get("name") for a in rows for r in (a.get("roles") or [])} - {None}),
            "require_rotation": [a.get("requireRotation") for a in rows]}


def client_id_of(account: dict) -> str | None:
    """The OAuth client id a refresh presents, read from the account's own id (its last segment)."""
    return str(account.get("id") or "").rsplit(":", 1)[-1] or None


# ── create and teardown ──────────────────────────────────────────────────────────────────────────────────────────
def refresh(vcfa: Vcfa, org: str, client_id: str | None, token: str) -> tuple[int, dict, str]:
    """One refresh grant with the stored token, as the integration makes it: with the client's id when it is known, and
    without it if that form is refused. (status, answer, the form that answered)."""
    forms = ([("with client_id", {"client_id": client_id})] if client_id else []) + [("without client_id", {})]
    status, answer, used = 0, {}, ""
    for used, extra in forms:
        status, answer = vcfa.call("POST", f"/oauth/tenant/{org}/token", f"/oauth/tenant/{{org}}/token  (refresh grant, {used})",
                                   form={"grant_type": "refresh_token", "refresh_token": token, **extra},
                                   accept="application/json", auth=False)
        answer = answer if isinstance(answer, dict) else {}
        if status == 200:
            break
    return status, answer, used


def refusals(vcfa: Vcfa, org: str, client_id: str | None, token: str) -> list[dict]:
    """Every form of the refresh grant with a token that should be dead, each with its answer, so the refusal is shown
    for the form an integration makes, not only for the last form tried. A token that still answers is not kept."""
    forms = ([("with client_id", {"client_id": client_id})] if client_id else []) + [("without client_id", {})]
    out = []
    for used, extra in forms:
        status, answer = vcfa.call("POST", f"/oauth/tenant/{org}/token", f"/oauth/tenant/{{org}}/token  (refresh grant, {used})",
                                   form={"grant_type": "refresh_token", "refresh_token": token, **extra},
                                   accept="application/json", auth=False)
        answer = answer if isinstance(answer, dict) else {}
        out.append({"form": used, "status": status, "bearer": bool(answer.get("access_token")), "error": answer.get("error")})
        del answer
    return out


def state_path(org: str, name: str) -> str:
    """The state file the register writes and the teardown reads: STATE, or one per organization and account."""
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", f"{org}.{name}")
    return os.environ.get("STATE") or f"service_account.{safe}.state.json"


def load_state(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def save_state(path: str, state: dict) -> None:
    _write_0600(path, json.dumps(state, indent=1), new=False)
    os.chmod(path, 0o600)


def owned(state: dict, org: str, name: str, rows: list[dict]) -> bool:
    """Whether the state file records every account found under this name as one this script registered."""
    return bool(state.get("tool") == AGENT and state.get("org") == org and state.get("name") == name and rows
                and all(client_id_of(r) == state.get("client_id") for r in rows))


def _write_0600(path: str, value: str, new: bool) -> None:
    flags = os.O_WRONLY | os.O_CREAT | (os.O_EXCL if new else os.O_TRUNC)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(value)


def no_org(status: int, count: int, record: dict) -> int:
    """Why no one organization was found: its list was not read (3), or it was read whole and no organization, or more
    than one, carries the name given (2, refused before any write)."""
    if status != 200:
        return EXIT_UNREAD
    record["refused"] = ("the organization was not found by that name (compared exactly, case included)" if not count
                         else f"{count} organizations carry that name, and a run acts in exactly one")
    return EXIT_REFUSED


def no_answer(what: str) -> str:
    """The record's words for a request that got no answer at all (status 0): never a refusal and never a pass, because
    whether a write that got none was made, or what a read that got none would have said, is not known."""
    return (f"{what} got no answer, so what it did is not known: read the organization's service accounts before "
            "acting")


def create(vcfa: Vcfa, a: argparse.Namespace, record: dict) -> int:
    status, urn, count = org_lookup(vcfa, a.org)
    if not urn:
        return no_org(status, count, record)
    existing = accounts(vcfa, urn, a.name)
    if existing is None:
        return EXIT_UNREAD
    if existing:
        record["refused"] = "the service account exists; this script never adopts one: --teardown it first, or choose another name"
        return EXIT_REFUSED
    partial = "the account exists without an active token: remove it with --teardown --execute before trying again"
    status, reg = vcfa.call("POST", f"/oauth/tenant/{a.org}/register", "/oauth/tenant/{org}/register",
                            body=register_body(a.name, a.role, str(uuid.uuid4())), org_urn=urn, accept="application/json")
    client_id = reg.get("client_id") if isinstance(reg, dict) else None
    if status == 0:
        record["undetermined"] = no_answer("the register")
        return EXIT_UNREAD
    if status not in (200, 201) or not client_id:
        if status in (200, 201):   # registered, perhaps, with no id to record: nothing here can remove it
            record["partial"] = ("the register answered without a client id, so no state file records the account: "
                                 "read the organization's service accounts, and remove one by this name where it was made")
        return EXIT_NOT_HELD
    save_state(state_path(a.org, a.name), {"tool": AGENT, "org": a.org, "name": a.name, "client_id": client_id,
                                           "created": replay_now().strftime("%Y-%m-%dT%H:%M:%SZ")})
    record["state_file_written"] = True   # before the grant, so an account left part way can still be removed
    rows = accounts(vcfa, urn, a.name)
    if rows is None:   # the register answered; the list that shows it did not, so nothing is said about it
        record["registered"] = {"error": "the account list could not be read after the register"}
    else:
        record["registered"] = shape(rows)
        record["registered"]["id_carries_client_id"] = any(client_id_of(r) == client_id for r in rows)
    status, device = vcfa.call("POST", f"/oauth/tenant/{a.org}/device_authorization",
                               "/oauth/tenant/{org}/device_authorization", form={"client_id": client_id},
                               accept="application/json", auth=False)
    if status != 200 or not isinstance(device, dict) or not device.get("device_code") or not device.get("user_code"):
        record["partial"] = partial   # the grant names the user code this client's own authorization returned, or nothing
        if status == 0:
            record["undetermined"] = no_answer("the device authorization")
            return EXIT_UNREAD
        return EXIT_NOT_HELD
    status, _ = vcfa.call("POST", "/cloudapi/1.0.0/deviceLookup/grant", "/cloudapi/1.0.0/deviceLookup/grant",
                          body={"userCode": device.get("user_code")}, org_urn=urn, accept=ACCOUNTS_ACCEPT)
    if status not in (200, 204):
        record["partial"] = partial
        if status == 0:
            record["undetermined"] = no_answer("the grant of the user code")
            return EXIT_UNREAD
        return EXIT_NOT_HELD
    form = {"grant_type": DEVICE_CODE, "client_id": client_id, "device_code": device["device_code"]}
    answer: dict = {}
    for _ in range(POLL_LIMIT):
        status, answer = vcfa.call("POST", f"/oauth/tenant/{a.org}/token", "/oauth/tenant/{org}/token  (device-code grant)",
                                   form=form, accept="application/json", auth=False)
        answer = answer if isinstance(answer, dict) else {}
        if status == 200 or answer.get("error") not in ("authorization_pending", "slow_down"):
            break
        time.sleep(POLL_SECONDS)
    del device, form
    token, access = answer.get("refresh_token"), answer.get("access_token")
    record["device_grant"] = {"status": status, "refresh_token": bool(token), "expires_in_s": answer.get("expires_in")}
    if status != 200 or not token or not access:
        record["partial"] = partial
        if status == 0:
            record["undetermined"] = no_answer("the device-code grant")
            return EXIT_UNREAD
        return EXIT_NOT_HELD
    _write_0600(a.token_file, token, new=True)
    record["token_file_written"] = True
    status, session = vcfa.call("GET", "/cloudapi/1.0.0/sessions/current", "/cloudapi/1.0.0/sessions/current  (as the account)",
                                accept=CLOUDAPI, auth=access)
    session = session if isinstance(session, dict) else {}
    record["session"] = {"status": status, "principal": (session.get("user") or {}).get("name"),
                         "roles": sorted(session.get("roles") or [])}
    del access
    status, again, used = refresh(vcfa, a.org, client_id, token)
    rotated = bool(again.get("refresh_token")) and again.get("refresh_token") != token
    if rotated:   # a rotated token replaces the stored one, or the next refresh would present a dead token
        _write_0600(a.token_file, again["refresh_token"], new=False)
    record["refresh"] = {"status": status, "form": used, "bearer": bool(again.get("access_token")),
                         "refresh_token_returned": bool(again.get("refresh_token")), "rotated": rotated,
                         "error": again.get("error")}
    del token, again
    rows = accounts(vcfa, urn, a.name)
    if rows is None:   # a read-back that did not read is not a result: the account's state is not known
        record["readback"] = {"error": "the account list could not be read back"}
        return EXIT_UNREAD
    record["readback"] = rb = shape(rows)
    unanswered = [w for w, st in (("the bearer's session read", record["session"]["status"]),
                                  ("the refresh with the stored token", record["refresh"]["status"])) if st == 0]
    if unanswered:   # neither held nor refused: not read
        record["undetermined"] = no_answer(" and ".join(unanswered))
        return EXIT_UNREAD
    held = (rb["present"] and rb["status"] == ["ACTIVE"] and rb["roles"] == [a.role]
            and record["session"]["status"] == 200 and record["session"]["roles"] == [a.role]
            and record["refresh"]["status"] == 200 and record["refresh"]["bearer"])
    return EXIT_OK if held else EXIT_NOT_HELD


def teardown(vcfa: Vcfa, a: argparse.Namespace, record: dict) -> int:
    status, urn, count = org_lookup(vcfa, a.org)
    if not urn:
        return no_org(status, count, record)
    rows = accounts(vcfa, urn, a.name)
    if rows is None:
        return EXIT_UNREAD
    state_file = state_path(a.org, a.name)
    state = load_state(state_file)
    if rows and not owned(state, a.org, a.name, rows):
        record["refused"] = ("this script did not register this account: no state file records it with this client id "
                             f"({'none read' if not state else 'another account recorded'}). An account made elsewhere "
                             "is revoked and removed where it was made; for one made here, run from the folder, or with "
                             "the STATE, its create wrote")
        return EXIT_REFUSED
    client_id = next((client_id_of(r) for r in rows if client_id_of(r)), None)
    token = _secret_from(a.token_file) if a.token_file and os.path.exists(a.token_file) and rows else None
    checks: dict[str, list[dict]] = {}
    revokes = []
    for acct in rows:
        status, _ = vcfa.call("POST", f"/cloudapi/1.0.0/serviceAccounts/{acct['id']}/revoke",
                              "/cloudapi/1.0.0/serviceAccounts/{id}/revoke", body={}, org_urn=urn, accept=ACCOUNTS_ACCEPT)
        revokes.append(status)
    if token:   # read between the two writes, so the record says which of them refused the token
        checks["after_revoke"] = refusals(vcfa, a.org, client_id, token)
    for acct in rows:
        vcfa.call("DELETE", f"/cloudapi/1.0.0/serviceAccounts/{acct['id']}", "/cloudapi/1.0.0/serviceAccounts/{id}",
                  org_urn=urn, accept=ACCOUNTS_ACCEPT)
    if not rows:
        record["nothing_to_remove"] = True
    left = rows
    for _ in range(GONE_LIMIT if rows else 1):
        left = accounts(vcfa, urn, a.name)
        if left == []:
            break
        time.sleep(GONE_SECONDS)
    record["residue"] = {"account_present": bool(left) if left is not None else None}
    if token:
        checks["after_delete"] = refusals(vcfa, a.org, client_id, token)
        record["revoked_token"] = checks
    elif rows:
        record["revoked_token"] = "not tried: no --token-file"
    del token
    if any(st not in (0, 200, 202, 204) for st in revokes):   # the revoke is what ends the refresh token (G-374)
        record["revoke_refused"] = sorted({st for st in revokes if st not in (0, 200, 202, 204)})
    refused = (not any(t["status"] == 200 or t["bearer"] for tries in checks.values() for t in tries)
               and "revoke_refused" not in record)
    if left == [] and rows:
        state["removed"] = replay_now().strftime("%Y-%m-%dT%H:%M:%SZ")
        save_state(state_file, state)
    if left is None:
        return EXIT_UNREAD   # the residue read failed: whether the account is gone is not known
    unanswered = ((["the revoke"] if 0 in revokes else [])
                  + (["a refresh with the revoked token"] if any(t["status"] == 0 for tries in checks.values()
                                                                 for t in tries) else []))
    if unanswered:   # a revoke that got no answer may not have ended the token; a refresh that got none was not refused
        record["undetermined"] = no_answer(" and ".join(unanswered))
        return EXIT_UNREAD
    return EXIT_OK if left == [] and refused else EXIT_NOT_HELD


def _secret_from(path: str) -> str:
    if REPLAY is not None:  # a replayed run reads no credential: nothing is sent
        return REPLAY_CREDENTIAL
    with open(path, encoding="utf-8") as f:
        return f.read().strip()


# ── the record contract: every estate value replaced, or nothing written ─────────────────────────────────────────
PRODUCT = {"active", "created", "revoked", "organization user", "organization member", "organization administrator",
           "organization owner", "organization auditor", "service-account"}
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
    calls = teardown_calls() if a.teardown else create_calls(a.name, a.role)
    host = os.environ.get("VCFA_HOST", "<VCFA_HOST>")
    out = [f"{'Teardown' if a.teardown else 'Create'} plan for service account {a.name} in organization {a.org} on {host}:"]
    for c in calls:
        out.append(f"  {c['method']:6} {c['path']}")
        if c.get("body"):
            out.append("         " + json.dumps(c["body"], sort_keys=True))
    if a.teardown:
        out.append("  then: " + (f"one refresh with the revoked token in {a.token_file}, expected to be refused"
                                 if a.token_file else "no refresh test (no --token-file given)"))
        out.append("  only for an account the state file records with the same client id; any other is refused before "
                   "the revoke")
    else:
        out.append(f"  then: the refresh token to {a.token_file or '<--token-file>'} (mode 0600, never printed), the bearer's "
                   "session read for its principal and roles, one refresh with the stored token, and the account read back")
    return out


def report(record: dict) -> list[str]:
    lines = [f"{record['mode']}: service account {record['name']} in organization {record['org']}"]
    for c in record.get("calls", []):
        lines.append(f"  {c['method']:6} {c['path']}: HTTP {c['status']}" + (f" ({c['shape']})" if c.get("shape") else ""))
    for key, words in (("refused", "refused"), ("partial", "stopped part way"), ("undetermined", "NOT READ")):
        if record.get(key):
            lines.append(f"  {words}: {record[key]}")
    if "device_grant" in record:
        g = record["device_grant"]
        lines.append(f"  device-code grant: HTTP {g['status']}, refresh token {'issued' if g['refresh_token'] else 'not issued'}"
                     + (f", bearer for {g['expires_in_s']} s" if g.get("expires_in_s") else ""))
    if "session" in record:
        s = record["session"]
        lines.append(f"  the bearer's session: HTTP {s['status']}, principal {s['principal']}, roles {', '.join(s['roles']) or 'none'}")
    if "refresh" in record:
        r = record["refresh"]
        lines.append(f"  refresh with the stored token ({r['form']}): HTTP {r['status']}, bearer {'issued' if r['bearer'] else 'not issued'}, "
                     + ("a new refresh token, written over the stored one" if r["rotated"]
                        else "the same refresh token kept" if r["refresh_token_returned"] else "no refresh token returned"))
    if "readback" in record:
        rb = record["readback"]
        lines.append(f"  read back: present {rb['present']}, status {', '.join(map(str, rb['status'])) or 'none'}, "
                     f"roles {', '.join(rb['roles']) or 'none'}, rotation required on every refresh "
                     f"{', '.join(map(str, rb.get('require_rotation') or [])) or 'not stated'}")
    if "residue" in record:
        lines.append(f"  residue: account present {record['residue']['account_present']}"
                     + ("  (there was nothing to remove)" if record.get("nothing_to_remove") else ""))
    if isinstance(record.get("revoked_token"), str):
        lines.append(f"  the revoked token: {record['revoked_token']}")
    if record.get("revoke_refused"):
        lines.append(f"  the revoke answered HTTP {', '.join(map(str, record['revoke_refused']))}: not held")
    for when, tries in (record.get("revoked_token") if isinstance(record.get("revoked_token"), dict) else {}).items():
        for t in tries:
            lines.append(f"  refresh with the revoked token, {when.replace('_', ' ')} ({t['form']}): HTTP {t['status']}, "
                         + ("no answer, not read" if t["status"] == 0 else f"bearer {'issued' if t['bearer'] else 'refused'}")
                         + (f" ({t['error']})" if t.get("error") else ""))
    lines.append(f"exit {record['exit']}")
    return lines


def credential_problem() -> str | None:
    """With --execute: the provider credential file, named but unreadable, empty or open to group or other (refused
    unread, with the fix), found before anything is sent."""
    for name in ("VCFA_PROVIDER_BEARER_FILE", "VCFA_PROVIDER_REFRESH_TOKEN_FILE"):
        if os.environ.get(name):
            try:
                if not _secret_file(name):
                    return f"{name} is empty"
            except (OSError, UnicodeDecodeError) as e:   # the refusal (no errno) names the variable and the fix
                refused = isinstance(e, PermissionError) and e.errno is None
                return str(e) if refused else f"{name} could not be read: {type(e).__name__}"
    return None


def usage_problem(a: argparse.Namespace) -> str | None:
    if a.teardown:
        if a.token_file and REPLAY is None and not os.path.exists(a.token_file):   # a replayed run reads none
            return f"{a.token_file} does not exist: --token-file with --teardown is the stored token to try after the revoke"
        return None
    if not a.role:
        return ("--role is required: the role's name, for example \"Organization User\" in an All Apps organization or "
                "\"Organization Member\" in a classic one")
    if ROLE_ID.match(a.role.strip()):
        return "--role names the role, never its id: a scope naming the role's id was refused on the reference estate"
    if a.execute and not a.token_file:
        return "--execute needs --token-file, where the refresh token is written (mode 0600)"
    if a.execute and os.path.exists(a.token_file):
        return f"{a.token_file} exists; the token is never written over a file"
    return None


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
        print("service_account.py needs Python 3.10 or later", file=sys.stderr)
        return EXIT_USAGE
    try:
        return _run(argv)
    except Exception as e:  # the last guard: whatever was not expected is not known, so exit 3
        print(f"the run stopped on an error it did not expect: {type(e).__name__}: {str(e)[:160]}; read the "
              "organization before trusting what it holds (exit 3)", file=sys.stderr)
        return EXIT_UNREAD
    finally:
        replay_stop()


def _run(argv: list[str] | None = None) -> int:
    ap = _Parser(description="One VCF Automation service account: plan, create, remove. Plan by default.")
    ap.add_argument("--org", required=True, help="the organization's name")
    ap.add_argument("--name", required=True, help="the service account's name; one per integration")
    ap.add_argument("--role", help="the one role it holds, by name: \"Organization User\" in an All Apps organization, "
                                   "\"Organization Member\" in a classic one")
    ap.add_argument("--token-file", help="where the refresh token is written, mode 0600; it must not exist")
    ap.add_argument("--teardown", action="store_true", help="revoke and remove the account instead")
    ap.add_argument("--execute", action="store_true", help="send the calls; without it the plan is printed")
    ap.add_argument("--redact", action="store_true", help="print with placeholders instead of your names")
    ap.add_argument("--replay", metavar="DIR",
                    help="answer every request from the recorded set in DIR (replay/service_account beside this script "
                         "is one): nothing is sent and no credential is read")
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
    problem = usage_problem(a)
    if problem:
        print(problem, file=sys.stderr)
        return EXIT_USAGE
    given = [(os.environ.get("VCFA_HOST", ""), "host"), (a.org, "org"), (a.name, "client")]
    if not a.execute:
        lines = plan_lines(a)
        if a.redact:   # the plan carries the host and the names you gave; a shared transcript carries none of them
            lines = scrub(lines, estate_values({"plan": lines}, [(v, k) for v, k in given if v]))
        print("\n".join(lines))
        print("\nplan only: nothing was sent (--execute sends it)")
        return EXIT_OK
    host = os.environ.get("VCFA_HOST")
    if not host or not (os.environ.get("VCFA_PROVIDER_BEARER_FILE") or os.environ.get("VCFA_PROVIDER_REFRESH_TOKEN_FILE")):
        print("VCFA_HOST and a provider credential (VCFA_PROVIDER_REFRESH_TOKEN_FILE or VCFA_PROVIDER_BEARER_FILE) are required",
              file=sys.stderr)
        return EXIT_USAGE
    problem = credential_problem()
    if problem:
        print(f"{problem}; nothing was sent", file=sys.stderr)
        return EXIT_USAGE
    record = {"captured": replay_now().strftime("%Y-%m-%dT%H:%M:%SZ"),
              "mode": "teardown" if a.teardown else "create", "org": a.org, "name": a.name, "calls": []}
    if not a.teardown:
        record["asked"] = {"role": a.role, "scope": role_scope(a.role)}
    try:
        vcfa = Vcfa(host, provider_bearer(host), record["calls"])
    except (RuntimeError, OSError, KeyError) as e:
        print(f"could not start: {e}", file=sys.stderr)
        return EXIT_UNREAD
    record["exit"] = teardown(vcfa, a, record) if a.teardown else create(vcfa, a, record)
    return write_record(record, given, a.redact, os.environ.get("OUT") or (
        "service_account.replay.json" if REPLAY is not None else "service_account.json"))


def write_record(record: dict, given: list[tuple[str, str]], redact: bool, out: str) -> int:
    """Print the run, scrub the record and write it; refuse to write one in which an estate value survived. A record
    refused for a surviving value never hides what the run did: its code stands when it is 1, 2 or 3, and a run that
    held exits 3, because its writes were made and the record that shows them was not written."""
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
