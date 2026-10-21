#!/usr/bin/env python3
"""leaver_test.py - prove that one test leaver is out, inside the latency you promise. Read-only.

The leaver test (the identity-lifecycle chapter's proof, and the step that closes deprovisioning): a test user who
signs in to a VCF Automation organization through Entra ID and holds one API token is removed at Entra (disabled, or
taken out of the entitled group). Inside the latency you state, three things must hold, and this script reads each:

  account   the person's VCF Automation account reads disabled, and the organization's token list, read whole,
            holds no API token the account owns
  token     the test user's own API token no longer yields an access token: one refresh grant at the organization's
            token endpoint answers 400 invalid_grant
  sign-in   Entra refused a sign-in to the organization's app made after the removal, read from Entra's sign-in log,
            with an error code that says the person is out (PROOF_CODES): a refusal for any other reason, a wrong
            password among them, proves nothing about the removal

It never signs in for the person (a sign-in is a browser protocol): sign in as the test user yourself after the
removal, then run this. Each check carries the time of its evidence: the read itself for the account and the token,
the attempt's own time in the log for the sign-in. The deadline is --removed-at plus --latency.

Exit, the first that applies:
  1  the leaver still has a way in: the account reads enabled, a token it owns is listed, the refresh answered 200 (the
     access token it returned is dropped unread), or Entra admitted a sign-in after the deadline, or after it had
     already refused one
  3  a check could not be made, so nothing is proven: a read refused or not read whole, a refresh answered with
     anything but 200 or 400 invalid_grant, no sign-in attempt in the log since the removal that Entra refused with a
     PROOF_CODES code at or before the deadline (the log lags the attempt by minutes: run again before the deadline),
     a run made after the deadline (its account and token reads show the state now, not inside the latency), a record
     refused for an estate value that survived its scrub on a run that would have passed, a request a --replay set
     holds no answer for, or an error it did not expect. Never a pass, never a finding.
  0  every check passed, its evidence at or before the deadline
  5  a usage error: a missing or bad argument or environment variable, a token file that cannot be read, a --user that
     selects no account or more than one, a --replay directory that cannot be read or holds no replay set, or a Python
     older than 3.10; nothing is sent
The contract every identity companion keeps: 0 nothing for a person to act on, 3 a read failed or a result is
undetermined (never a finding), 5 a usage error; 1 is this script's own; an error it did not expect is 3.

What it sends (every call is a read but the refresh grant, which creates nothing a person keeps):
  GET  /cloudapi/1.0.0/orgs                       the organization by name (the provider's list, read whole)
  GET  /cloudapi/1.0.0/users                      its accounts, in its tenant context, read whole; --user selects one
  GET  /cloudapi/1.0.0/users/{id}                 the account: enabled or not
  GET  /cloudapi/1.0.0/tokens                     its API tokens, read whole: any the account owns
  POST /oauth/tenant/{org}/token                  grant_type=refresh_token with the test user's token
  GET  https://graph.microsoft.com/v1.0/auditLogs/signIns
       ?$filter=appId eq '{app}' and (userId eq '{object id}' | userPrincipalName eq '{name}')
        and createdDateTime ge {removed at}       every page, following @odata.nextLink to its end
       Microsoft Graph's List signIns names AuditLog.Read.All as the least privileged application permission.

Env:  VCFA_HOST; VCFA_PROVIDER_BEARER_FILE (a provider bearer, mode 0600) or VCFA_PROVIDER_REFRESH_TOKEN_FILE (a provider
      API token, traded at /oauth/provider/token): every VCF Automation call but the grant is a provider read;
      TLS_VERIFY=false only on a self-signed lab CA (VCF Automation only; Entra and Graph are always verified);
      TEST_REFRESH_TOKEN_FILE: the test user's own API token (a refresh token, mode 0600), minted before the removal;
      ENTRA_TENANT_ID (the tenant's id); ENTRA_CLIENT_ID and ENTRA_CLIENT_SECRET_FILE, or ENTRA_CERT_FILE and
      ENTRA_KEY_FILE (PEM, needs the `cryptography` package): an app that may read the sign-in log; OUT (default
      leaver-test.json; leaver-test.replay.json under --replay).
Use:  python3 leaver_test.py --org ORG --user ACCOUNT --app CLIENT_ID --removed-at 2026-10-16T09:00:00Z --latency 30
      ACCOUNT is the account's user name in the organization (a principal name; the person's Entra object id in an
      organization keyed on oid) or its id (urn:vcloud:user:...). CLIENT_ID is the application (client) id of the Entra
      app the organization signs in through. --removed-at is when you disabled or removed the test user at Entra
      (ISO 8601 with its offset, Z for UTC); --latency the minutes you promise; --redact prints placeholders.
      python3 leaver_test.py --replay replay/leaver_test --org ... (the same arguments): without an estate, every
      answer from the recorded set beside this script (its hosts are placeholders) and its checks judged at the time
      the set was recorded; nothing is sent and no credential is read, and a request the set holds no answer for is a
      read that failed (exit 3)
Needs Python 3.10 or later and nothing outside the standard library (the `cryptography` package only for a
certificate credential). No token, secret or password is printed or written.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
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
from datetime import datetime, timedelta, timezone
from pathlib import Path

EXIT_PASS, EXIT_OPEN, EXIT_UNREAD, EXIT_USAGE = 0, 1, 3, 5
UTC = timezone(timedelta(0))  # datetime.UTC is Python 3.11; readers run 3.10
CLOUDAPI = "application/json;version=9.1.0"
TENANT_JSON = "application/json;version=10.0.0.0-alpha"  # the version the platform's own user reads were proven with
TENANT_HEADER = "X-VMWARE-VCLOUD-TENANT-CONTEXT"
GRAPH = "https://graph.microsoft.com/v1.0"
ENTRA = "https://login.microsoftonline.com"
PAGE_SIZE = (
    128  # items per page of a cloudapi list asked for; a list is read to the total it states
)
MAX_PAGES = 10000  # a bound on one list read: a list that has not reached its stated total by then did not read
OBJECT_ID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
# Entra's sign-in error codes that say the person is out, each read on the reference estate in a refused browser
# sign-in: 50057 a disabled user, 50105 a user assigned to the app neither directly nor through a group.
PROOF_CODES = {50057: "the user is disabled", 50105: "the user is not assigned to the app"}
SECRET_KEYS = {
    "clientSecret",
    "client_secret",
    "password",
    "token",
    "accessToken",
    "refreshToken",
    "secretText",
    "access_token",
    "refresh_token",
    "id_token",
}


class UsageError(Exception):
    """Not run as asked: exit 5, nothing sent."""


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
def _ctx(verify: bool) -> ssl.SSLContext | None:
    if REPLAY is not None:  # a replayed run opens no connection, so it makes no TLS context
        return None
    return ssl.create_default_context() if verify else ssl._create_unverified_context()


def _lab_verify() -> bool:
    return os.environ.get("TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")


def _secret_file(name: str) -> str:
    if REPLAY is not None:  # a replayed run reads no credential: nothing is sent
        return REPLAY_CREDENTIAL
    return Path(os.environ[name]).read_text(encoding="utf-8").strip()


def _secret_given(name: str) -> bool:
    """Whether the variable naming a credential's file is set; a replayed run needs none (it reads no credential)."""
    return REPLAY is not None or bool(os.environ.get(name))


def strip_secrets(obj: object) -> bool:
    """Delete every secret-bearing key in place, at any depth; True when one carried a value."""
    found = False
    if isinstance(obj, dict):
        for k in list(obj):
            if k in SECRET_KEYS:
                found = bool(obj.pop(k)) or found
            else:
                found = strip_secrets(obj[k]) or found
    elif isinstance(obj, list):
        for v in obj:
            found = strip_secrets(v) or found
    return found


class Reader:
    """One plane under one credential. Every call is recorded with its status; secrets are deleted from each answer
    as it arrives; a refusal is recorded, never raised."""

    def __init__(self, plane: str, base: str, headers: dict, verify: bool, calls: list):
        self.plane, self.base, self.headers, self.verify, self.calls = (
            plane,
            base,
            headers,
            verify,
            calls,
        )

    def call(
        self,
        method: str,
        url_or_path: str,
        accept: str = "application/json",
        headers: dict | None = None,
        form: dict | None = None,
    ) -> tuple[int | None, object]:
        path = url_or_path.removeprefix(self.base)
        rec = {"plane": self.plane, "method": method, "path": path.split("?", 1)[0], "status": None}
        self.calls.append(rec)
        h = {**self.headers, "Accept": accept, **(headers or {})}
        data = None
        if form is not None:
            data = urllib.parse.urlencode(form).encode()
            h["Content-Type"] = "application/x-www-form-urlencoded"
        url = url_or_path if url_or_path.startswith("https://") else self.base + url_or_path
        try:
            with _urlopen(
                urllib.request.Request(url, data=data, headers=h, method=method),
                context=_ctx(self.verify),
                timeout=60,
            ) as r:
                rec["status"], raw = r.status, r.read()
        except urllib.error.HTTPError as e:
            rec["status"] = e.code
            try:
                body = json.loads(e.read() or b"{}")
            except (ValueError, OSError):
                body = None
            if isinstance(body, dict):
                strip_secrets(body)
                rec["error"] = str(body.get("error") or "")[:60] or None
            return e.code, body
        except (urllib.error.URLError, OSError) as e:
            rec["error"] = str(getattr(e, "reason", e))[:120]
            return None, None
        try:
            answer = json.loads(raw) if raw else {}
        except ValueError:
            return rec["status"], None
        strip_secrets(answer)
        return rec["status"], answer


def item_key(item: object) -> str:
    """What makes a list item distinct: its id, or, for one that carries none, its whole content."""
    if isinstance(item, dict) and item.get("id") is not None:
        return "id:" + str(item["id"])
    return "item:" + json.dumps(item, sort_keys=True, default=str)


def list_shape(answer: object, key: str, total: int | None) -> str | None:
    """Why one page of a cloudapi list did not read, or None: the answer carries its list under `key` and a whole
    resultTotal of 0 or more, the same total as the pages before it (`total`, None on the first page)."""
    if not isinstance(answer, dict) or not isinstance(answer.get(key), list):
        return f"no {key} list in the answer"
    stated = answer.get("resultTotal")
    if not isinstance(stated, int) or isinstance(stated, bool) or stated < 0:
        return "no resultTotal in the answer"
    if total is not None and stated != total:
        return f"the total changed between pages ({total}, then {stated})"
    return None


class Vcfa(Reader):
    def __init__(self, host: str, calls: list):
        verify = _lab_verify()
        if os.environ.get("VCFA_PROVIDER_BEARER_FILE"):
            bearer = _secret_file("VCFA_PROVIDER_BEARER_FILE").removeprefix("Bearer ").strip()
        else:
            form = urllib.parse.urlencode(
                {
                    "grant_type": "refresh_token",
                    "refresh_token": _secret_file("VCFA_PROVIDER_REFRESH_TOKEN_FILE"),
                }
            ).encode()
            req = urllib.request.Request(
                f"https://{host}/oauth/provider/token",
                data=form,
                method="POST",
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
            )
            with _urlopen(req, context=_ctx(verify), timeout=60) as r:
                bearer = json.loads(r.read())["access_token"]
        super().__init__(
            "vcf-automation",
            f"https://{host}",
            {"Authorization": f"Bearer {bearer}"},
            verify,
            calls,
        )
        del bearer

    def pages(self, path: str, org_urn: str | None = None) -> list | None:
        """Every item of a cloudapi list, read to the total the list states: pages count from 1, PAGE_SIZE items
        asked of each, and the list is read when its distinct items (by id) number the answer's resultTotal. None,
        never a shorter list, when a page is refused, an answer carries no `values` list or no resultTotal, the total
        changes between pages, a page comes back empty or short of the page size it states before the total is
        reached, a page adds no item not already read, or the distinct items pass the total: a list read in part is
        not a list. The call that ended a read in part is marked with why."""
        seen: dict[str, dict] = {}
        total, hdr = None, ({TENANT_HEADER: org_urn} if org_urn else {})
        for page in range(1, MAX_PAGES + 1):
            _status, answer = self.call(
                "GET",
                f"{path}?page={page}&pageSize={PAGE_SIZE}",
                accept=TENANT_JSON if org_urn else CLOUDAPI,
                headers=hdr,
            )
            why = list_shape(answer, "values", total)
            if why is None:
                total, rows, before = answer["resultTotal"], answer["values"], len(seen)
                for r in rows:
                    seen.setdefault(item_key(r), r)
                if len(seen) == total:
                    return list(seen.values())
                size = answer.get("pageSize")
                size = (
                    size
                    if isinstance(size, int) and not isinstance(size, bool) and size > 0
                    else PAGE_SIZE
                )
                if len(seen) > total:
                    why = f"{len(seen)} distinct items, more than the {total} the answer states"
                elif len(rows) < size:
                    why = f"the pages ended at {len(seen)} of the {total} the answer states"
                elif len(seen) == before:
                    why = f"page {page} added nothing to the {len(seen)} of the {total} the answer states"
            if why is not None:
                if self.calls and self.calls[-1].get("status") == 200:
                    self.calls[-1]["shape"] = why
                return None
        if self.calls:
            self.calls[-1]["shape"] = f"no end after {MAX_PAGES} pages"
        return None


class Graph(Reader):
    def __init__(self, calls: list):
        tenant, client = os.environ["ENTRA_TENANT_ID"], os.environ["ENTRA_CLIENT_ID"]
        form = {
            "client_id": client,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        }
        if os.environ.get("ENTRA_CLIENT_SECRET_FILE"):
            form["client_secret"] = _secret_file("ENTRA_CLIENT_SECRET_FILE")
        else:
            form["client_assertion_type"] = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
            form["client_assertion"] = _assertion(tenant, client)
        req = urllib.request.Request(
            f"{ENTRA}/{tenant}/oauth2/v2.0/token",
            data=urllib.parse.urlencode(form).encode(),
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with _urlopen(req, context=_ctx(True), timeout=60) as r:
            bearer = json.loads(r.read())["access_token"]
        del form
        super().__init__("graph", GRAPH, {"Authorization": f"Bearer {bearer}"}, True, calls)
        del bearer

    def values(self, path: str, **query: str) -> list | None:
        """Every item of a Graph list, following @odata.nextLink until an answer carries none; None, never a shorter
        list, when a page was refused, a 200 came back without its `value` list, a next link repeats one already
        followed (the pages would go round for ever), or MAX_PAGES pass: a list read in part is not a list. A page with
        no items and a next link is read on, since Graph's paging guidance says a page may hold none. The page that
        did not read is marked with why."""
        qs = urllib.parse.urlencode(
            {f"${k}": v for k, v in query.items()}, quote_via=urllib.parse.quote
        )
        url, out, followed = f"{GRAPH}{path}" + (f"?{qs}" if qs else ""), [], set()
        for _page in range(MAX_PAGES):
            _status, answer = self.call("GET", url)
            if not isinstance(answer, dict) or not isinstance(answer.get("value"), list):
                if self.calls and self.calls[-1].get("status") == 200:
                    self.calls[-1]["shape"] = "no value list in the answer"
                return None
            out += answer["value"]
            followed.add(url)
            url = answer.get("@odata.nextLink")
            if not url:
                return out
            if not isinstance(url, str):
                self.calls[-1]["shape"] = "a next page link that is not a link"
                return None
            if url in followed:
                self.calls[-1]["shape"] = "the next page link repeats one already read"
                return None
        self.calls[-1]["shape"] = f"no end after {MAX_PAGES} pages"
        return None


def _assertion(tenant: str, client: str) -> str:
    """A signed JWT in place of a secret (PS256, x5t#S256), the form Entra takes for a certificate credential."""
    if REPLAY is not None:  # a replayed run reads no key or certificate: nothing is sent
        return REPLAY_CREDENTIAL
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    def b64(b: bytes) -> str:
        return base64.urlsafe_b64encode(b).rstrip(b"=").decode()

    der = x509.load_pem_x509_certificate(
        Path(os.environ["ENTRA_CERT_FILE"]).read_bytes()
    ).public_bytes(serialization.Encoding.DER)
    key = serialization.load_pem_private_key(
        Path(os.environ["ENTRA_KEY_FILE"]).read_bytes(), password=None
    )
    now = int(time.time())
    head = {"alg": "PS256", "typ": "JWT", "x5t#S256": b64(hashlib.sha256(der).digest())}
    claims = {
        "aud": f"{ENTRA}/{tenant}/oauth2/v2.0/token",
        "iss": client,
        "sub": client,
        "jti": str(uuid.uuid4()),
        "nbf": now,
        "iat": now,
        "exp": now + 600,
    }
    signing = (
        b64(json.dumps(head, separators=(",", ":")).encode())
        + "."
        + b64(json.dumps(claims, separators=(",", ":")).encode())
    )
    sig = key.sign(
        signing.encode(),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256(),
    )
    return signing + "." + b64(sig)


# ── times ────────────────────────────────────────────────────────────────────────────────────────────────────────
def parse_time(value: str) -> datetime:
    """An ISO 8601 time with its offset (Z for UTC), in UTC; a time without an offset is refused, since its zone is a
    guess (ValueError)."""
    v = value.strip()
    if v.endswith(("Z", "z")):
        v = v[:-1] + "+00:00"
    t = datetime.fromisoformat(v)
    if t.tzinfo is None:
        raise ValueError(f"{value!r} carries no offset: write it with Z for UTC, or its offset")
    return t.astimezone(UTC)


def stamp(t: datetime | None) -> str | None:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ") if t else None


def _graph_time(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


# ── the three checks, as functions of what was read ──────────────────────────────────────────────────────────────
def judge_account(
    user: dict | None, tokens: list | None, read_at: datetime, deadline: datetime
) -> dict:
    """The account and its tokens: fail when it reads enabled or owns a listed token; unread when either read did
    not read; pass when disabled and no token, read at or before the deadline (after it, not proven inside it)."""
    out: dict = {"read_at": stamp(read_at)}
    if not isinstance(user, dict) or not isinstance(user.get("enabled"), bool) or tokens is None:
        return {**out, "result": "unread", "why": "the account or the token list did not read"}
    mine = [t for t in tokens if (t.get("owner") or {}).get("id") == user.get("id")]
    out.update(enabled=user["enabled"], tokens_owned=len(mine))
    if user["enabled"] or mine:
        why = (
            ("the account reads enabled" if user["enabled"] else "")
            + (" and " if user["enabled"] and mine else "")
            + (f"{len(mine)} API token(s) it owns are listed" if mine else "")
        )
        return {**out, "result": "fail", "why": why}
    if read_at > deadline:
        return {
            **out,
            "result": "unread",
            "why": "read after the deadline: disabled with no token now, which does not "
            "show it inside the latency",
        }
    return {**out, "result": "pass", "why": "disabled, and no API token it owns is listed"}


def judge_refresh(
    status: int | None, answer: object, read_at: datetime, deadline: datetime
) -> dict:
    """One refresh grant with the test user's API token: 200 fails (the access token is dropped unread), 400
    invalid_grant passes at or before the deadline, anything else did not read."""
    out: dict = {"read_at": stamp(read_at), "status": status}
    err = answer.get("error") if isinstance(answer, dict) else None
    if status == 200:
        return {
            **out,
            "result": "fail",
            "why": "the token still yields an access token (dropped unread)",
        }
    if status == 400 and err == "invalid_grant":
        if read_at > deadline:
            return {
                **out,
                "error": err,
                "result": "unread",
                "why": "refused now, read after the deadline: not shown inside the latency",
            }
        return {**out, "error": err, "result": "pass", "why": "refused: 400 invalid_grant"}
    return {
        **out,
        "error": err,
        "result": "unread",
        "why": f"the grant answered {status or 'nothing'}{' ' + err if err else ''}, neither 200 nor 400 "
        "invalid_grant, so whether the token is refused is not known",
    }


def judge_sign_ins(rows: list | None, removed: datetime, deadline: datetime) -> dict:
    """The app's sign-in log since the removal. Fail when Entra admitted a sign-in after the deadline, or after it had
    already refused one with a code that says the person is out. Pass when it refused one with such a code at or
    before the deadline. Unread otherwise: the log did not read, holds no attempt since the removal, or holds only
    refusals for other reasons (a wrong password proves nothing about the removal)."""
    if rows is None:
        return {
            "result": "unread",
            "why": "the sign-in log did not read (it needs AuditLog.Read.All)",
        }
    seen = []
    for r in rows:
        try:
            t = parse_time(str(r.get("createdDateTime")))
        except ValueError:
            return {"result": "unread", "why": "a sign-in in the log carries no time that reads"}
        code = (r.get("status") or {}).get("errorCode")
        if not isinstance(code, int) or isinstance(code, bool):
            return {"result": "unread", "why": "a sign-in in the log carries no error code"}
        if t >= removed:
            seen.append((t, code))
    seen.sort()
    attempts = [
        {"at": stamp(t), "error_code": c, "after_removal_s": round((t - removed).total_seconds())}
        for t, c in seen
    ]
    out: dict = {"attempts": attempts}
    proof = [t for t, c in seen if c in PROOF_CODES]
    first = proof[0] if proof else None
    late = [t for t, c in seen if c == 0 and (t > deadline or (first is not None and t > first))]
    if late:
        return {
            **out,
            "result": "fail",
            "why": f"Entra admitted a sign-in at {stamp(late[0])}, after "
            + ("the deadline" if late[0] > deadline else "it had refused one"),
        }
    if first is not None and first <= deadline:
        code = next(c for t, c in seen if t == first and c in PROOF_CODES)
        return {
            **out,
            "result": "pass",
            "first_refused_at": stamp(first),
            "error_code": code,
            "why": f"refused with {code} ({PROOF_CODES[code]}), {round((first - removed).total_seconds())} s "
            "after the removal",
        }
    if first is not None:
        return {
            **out,
            "result": "unread",
            "why": "the first refusal that says the person is out came after the "
            "deadline: not shown inside the latency",
        }
    if seen:
        return {
            **out,
            "result": "unread",
            "why": "no attempt since the removal was refused with a code that says the "
            "person is out (" + ", ".join(str(c) for c in PROOF_CODES) + ")",
        }
    return {
        **out,
        "result": "unread",
        "why": "no sign-in to the app since the removal is in the log yet: sign in as "
        "the test user, then run again before the deadline",
    }


def verdict(checks: dict) -> int:
    """Exit 1 when any check found a way in; 3 when any could not be made; 0 when all passed."""
    results = [c.get("result") for c in checks.values()]
    if "fail" in results:
        return EXIT_OPEN
    if any(r != "pass" for r in results):
        return EXIT_UNREAD
    return EXIT_PASS


def select(users: list, given: str) -> list:
    """The accounts --user names: by id (urn:vcloud:user:...), or by user name in any case."""
    g = given.strip().lower()
    return [
        u
        for u in users
        if str(u.get("id", "")).lower() == g or str(u.get("username", "")).lower() == g
    ]


def sign_in_filter(app: str, username: str, removed: datetime) -> str:
    """The sign-in log's filter: the app, the person (the object id under oid, else the principal name), the time."""
    who = (
        f"userId eq '{username}'"
        if OBJECT_ID.match(username)
        else f"userPrincipalName eq '{username}'"
    )
    return f"appId eq '{app}' and {who} and createdDateTime ge {_graph_time(removed)}"


# ── the record's scrub: every estate value replaced, and a record carrying one refused ───────────────────────────
PRODUCT = {
    w.lower()
    for w in (
        "OIDC",
        "SAML",
        "OAUTH",
        "LOCAL",
        "pass",
        "fail",
        "unread",
        "invalid_grant",
        "graph.microsoft.com",
        "login.microsoftonline.com",
    )
}
PATTERNS = [
    (
        "id",
        re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"),
    ),
    ("host", re.compile(r"\b[a-z0-9-]+(?:\.[a-z0-9-]+)+\.[a-z]{2,}\b", re.I)),
    ("user", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)*\b")),
]
FIELDS = {"org": "org", "account": "user", "app": "id", "id": "id"}
PLACEHOLDER = re.compile(r"\{\{[a-z-]+-\d+\}\}")
OWN = re.compile(f"({PLACEHOLDER.pattern})")  # splits a text into what lies outside the placeholders and each one
NOT_SHAPED = {"read_at", "at", "first_refused_at", "removed_at", "deadline", "captured"}


def _strings(obj: object, field: str | None = None):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _strings(v, k)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v, field)
    elif isinstance(obj, str):
        yield field, obj


def estate_values(record: dict, given: list[tuple[str, str]]) -> dict[str, str]:
    table, seen, count = {}, set(), Counter()

    def add(value: str, kind: str) -> None:
        if value and len(value) >= 3 and value.lower() not in PRODUCT and value.lower() not in seen:
            seen.add(value.lower())
            count[kind] += 1
            table[value] = f"{{{{{kind}-{count[kind]}}}}}"

    for value, kind in given:
        add(value, kind)
    for field, s in _strings(record):
        if field in FIELDS:
            add(s, FIELDS[field])
    for field, s in _strings(record):
        if field not in NOT_SHAPED:
            for kind, rx in PATTERNS:
                for m in rx.findall(s):
                    add(m, kind)
    return table


def _pattern(table: dict) -> re.Pattern | None:
    if not table:
        return None
    alt = "|".join(re.escape(v) for v in sorted(table, key=len, reverse=True))
    return re.compile(rf"(?<![A-Za-z0-9])(?:{alt})(?![A-Za-z0-9])", re.I)


def one_pass(table: dict):
    """A text with every registered value replaced by its placeholder in one pass: one alternation, the longest value
    first, on _pattern's boundary, and only outside the placeholders already in the text. A value spelled like a
    placeholder (an organization named org-1) never rewrites the {{org-1}} another value was given, and a second scrub
    changes nothing. A value registered twice, in two cases, keeps its first placeholder."""
    rx, label = _pattern(table), {}
    for value, placeholder in table.items():
        label.setdefault(value.lower(), placeholder)
    if rx is None:
        return lambda text: text
    return lambda text: "".join(
        part if i % 2 else rx.sub(lambda m: label[m.group(0).lower()], part)
        for i, part in enumerate(OWN.split(text))
    )


def scrub(obj: object, table: dict) -> object:
    """The record with every registered value replaced by its placeholder in one pass (one_pass). Keys are never
    touched."""
    if not table:
        return obj
    replace = one_pass(table)

    def walk(o: object) -> object:
        if isinstance(o, dict):
            return {k: walk(v) for k, v in o.items()}
        if isinstance(o, list):
            return [walk(v) for v in o]
        return replace(o) if isinstance(o, str) else o

    return walk(obj)


def leaks(obj: object, table: dict) -> list[str]:
    rx, found = _pattern(table), []
    kind_of = {k.lower(): v.strip("{}").rsplit("-", 1)[0] for k, v in table.items()}
    for field, s in _strings(obj):
        rest = PLACEHOLDER.sub(" ", s)
        found += [kind_of[m.group(0).lower()] for m in rx.finditer(rest)] if rx else []
        if field not in NOT_SHAPED:
            found += [
                kind for kind, p in PATTERNS for m in p.findall(rest) if m.lower() not in PRODUCT
            ]
        if (
            field in FIELDS
            and len(s) >= 3
            and s.lower() not in PRODUCT
            and re.search(r"[A-Za-z0-9]", rest)
        ):
            found.append(FIELDS[field])
    return found


# ── the run ──────────────────────────────────────────────────────────────────────────────────────────────────────
NAMES = {
    "account": "account disabled, no token",
    "refresh": "token refused",
    "sign_in": "sign-in refused",
}
EXIT_MEANS = {
    EXIT_PASS: "every check passed inside the latency",
    EXIT_OPEN: "the leaver still has a way in",
    EXIT_UNREAD: "not proven: a check could not be made (nothing is known about it)",
}


def refresh_grant(host: str, org: str, calls: list) -> tuple[int | None, object]:
    """One refresh grant with the test user's API token at the organization's token endpoint. The answer's secrets
    (an access token, on a 200) are deleted as it arrives (strip_secrets), so a token the grant returns is never read."""
    grant = Reader("vcf-automation", f"https://{host}", {}, _lab_verify(), calls)
    return grant.call(
        "POST",
        f"/oauth/tenant/{urllib.parse.quote(org)}/token",
        form={
            "grant_type": "refresh_token",
            "refresh_token": _secret_file("TEST_REFRESH_TOKEN_FILE"),
        },
    )


def run(a: argparse.Namespace, make_vcfa=None, make_graph=None, grant=None) -> tuple[dict, list]:
    """The three checks, each read once. ``make_vcfa``, ``make_graph`` and ``grant`` default to the real planes (a test
    passes its own)."""
    make_vcfa, make_graph, grant = make_vcfa or Vcfa, make_graph or Graph, grant or refresh_grant
    calls: list = []
    removed = parse_time(a.removed_at)
    deadline = removed + timedelta(minutes=a.latency)
    record: dict = {
        "captured": stamp(replay_now()),
        "org": a.org,
        "account": a.user,
        "app": a.app,
        "removed_at": stamp(removed),
        "latency_minutes": a.latency,
        "deadline": stamp(deadline),
        "checks": {},
    }
    checks = record["checks"]
    vcfa = make_vcfa(os.environ["VCFA_HOST"], calls)
    orgs = vcfa.pages("/cloudapi/1.0.0/orgs")
    org = [o for o in orgs or [] if str(o.get("name")) == a.org]
    if orgs is None:
        unread = {"result": "unread", "why": "the organization list did not read"}
        checks.update(account=dict(unread), refresh=dict(unread), sign_in=dict(unread))
        return record, calls
    if len(org) != 1:
        raise UsageError(f"no single organization is named {a.org}")
    urn = str(org[0]["id"])
    users = vcfa.pages("/cloudapi/1.0.0/users", urn)
    if users is None:
        unread = {"result": "unread", "why": "the organization's account list did not read"}
        checks.update(account=dict(unread), refresh=dict(unread), sign_in=dict(unread))
        return record, calls
    chosen = select(users, a.user)
    if len(chosen) != 1:
        raise UsageError(
            f"--user {a.user} selects {len(chosen)} accounts in {a.org}; name one by its id "
            "(urn:vcloud:user:...) or its exact user name"
        )
    acct = chosen[0]
    username = str(acct.get("username") or "")
    _s, user = vcfa.call(
        "GET",
        f"/cloudapi/1.0.0/users/{acct['id']}",
        accept=TENANT_JSON,
        headers={TENANT_HEADER: urn},
    )
    tokens = vcfa.pages("/cloudapi/1.0.0/tokens", urn)
    checks["account"] = judge_account(
        user if isinstance(user, dict) else None, tokens, replay_now(), deadline
    )
    status, answer = grant(os.environ["VCFA_HOST"], a.org, calls)
    checks["refresh"] = judge_refresh(status, answer, replay_now(), deadline)
    del answer
    try:
        graph = make_graph(calls)
    except (urllib.error.URLError, OSError, KeyError, ValueError) as e:
        checks["sign_in"] = {
            "result": "unread",
            "why": f"the Graph credential could not be obtained ({type(e).__name__})",
        }
        return record, calls
    rows = graph.values("/auditLogs/signIns", filter=sign_in_filter(a.app, username, removed))
    checks["sign_in"] = judge_sign_ins(rows, removed, deadline)
    return record, calls


def report_lines(record: dict) -> list[str]:
    lines = [
        f"leaver test: {record['account']} in {record['org']}, removed {record['removed_at']}, latency "
        f"{record['latency_minutes']} min (deadline {record['deadline']}); read {record['captured']}"
    ]
    for k, c in record["checks"].items():
        lines.append(f"  {c.get('result', 'unread').upper():7} {NAMES[k]}: {c.get('why', '')}")
    lines.append(f"exit {record['exit']}: {EXIT_MEANS.get(record['exit'], '')}")
    return lines


def write(record: dict, calls: list, redact: bool) -> int:
    """Print the run, scrub the record and write it; refuse to write one in which an estate value survived. A refused
    record never hides a finding: 1 and 3 stand, and a run that would have passed exits 3."""
    record["calls"] = calls
    if REPLAY is not None:  # a replayed run's record never passes for a live one: a reader refuses it as no run
        record = {"replay": True, **record}
    given = [
        (os.environ.get("VCFA_HOST", ""), "host"),
        (os.environ.get("ENTRA_TENANT_ID", ""), "id"),
        (os.environ.get("ENTRA_CLIENT_ID", ""), "id"),
        (record.get("org", ""), "org"),
        (record.get("account", ""), "user"),
        (record.get("app", ""), "id"),
    ]
    table = estate_values(record, [(v, k) for v, k in given if v])
    clean = scrub(record, table)
    left = leaks(clean, table)
    out = os.environ.get("OUT") or ("leaver-test.replay.json" if REPLAY is not None else "leaver-test.json")
    if not (left and redact):
        print("\n".join(report_lines(clean if redact else record)))
    if left:
        code = record["exit"] if record["exit"] != EXIT_PASS else EXIT_UNREAD
        print(
            f"refusing to write {out}: {len(left)} estate value(s) survived the scrub; exit {code}",
            file=sys.stderr,
        )
        return code
    Path(out).write_text(json.dumps(clean, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    failed = sum(
        1
        for c in calls
        if not expected_refusal(c) and (c["status"] is None or c["status"] >= 400 or c.get("shape"))
    )
    print(
        f"{len(calls)} call(s), {failed} read(s) refused or not read whole (the refresh grant's 400 invalid_grant is "
        f"the token check passing, not a failed read); {out} written with every estate value replaced"
    )
    return record["exit"]


def expected_refusal(call: dict) -> bool:
    """The refresh grant answered 400 invalid_grant: the answer the token check wants, not a read that failed."""
    return (
        call.get("method") == "POST"
        and call.get("status") == 400
        and call.get("error") == "invalid_grant"
    )


class _Parser(argparse.ArgumentParser):
    """argparse exits 2 on a usage error; the identity companions' contract gives a usage error 5."""

    def __init__(self, *args, **kwargs):  # an abbreviation never parses as a whole flag name
        kwargs.setdefault("allow_abbrev", False)
        super().__init__(*args, **kwargs)

    def error(self, message: str):
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        raise SystemExit(EXIT_USAGE)


def _minutes(value: str) -> int:
    if not value.isdigit() or int(value) < 1:
        raise argparse.ArgumentTypeError(f"{value!r} is not a whole number of minutes, 1 or more")
    return int(value)


def _time(value: str) -> str:
    try:
        parse_time(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from None
    return value


def build_parser() -> _Parser:
    ap = _Parser(
        description="Prove one test leaver is out of a VCF Automation organization inside a stated latency."
    )
    ap.add_argument("--org", required=True, help="the organization the test user signs in to")
    ap.add_argument(
        "--user",
        required=True,
        metavar="ACCOUNT",
        help="the test user's account: its user name in the organization, or its id (urn:vcloud:user:...)",
    )
    ap.add_argument(
        "--app",
        required=True,
        metavar="CLIENT_ID",
        help="the application (client) id of the Entra app the organization signs in through",
    )
    ap.add_argument(
        "--removed-at",
        required=True,
        type=_time,
        metavar="TIME",
        help="when the test user was disabled or removed at Entra, ISO 8601 with its offset",
    )
    ap.add_argument(
        "--latency", required=True, type=_minutes, metavar="MINUTES", help="the latency you promise"
    )
    ap.add_argument(
        "--redact", action="store_true", help="print with placeholders instead of your names"
    )
    ap.add_argument("--replay", metavar="DIR",
                    help="answer every request from the recorded set in DIR (replay/leaver_test beside this script is "
                         "one): nothing is sent and no credential is read")
    return ap


def _run(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    if a.replay:
        try:
            replay_start(a.replay)
        except (OSError, ValueError) as e:
            print(f"--replay {a.replay}: {e}; nothing was sent", file=sys.stderr)
            return EXIT_USAGE
    if not OBJECT_ID.match(a.app):
        print(f"--app {a.app!r}: the app's application (client) id, a GUID", file=sys.stderr)
        return EXIT_USAGE
    missing = [k for k in ("VCFA_HOST", "ENTRA_TENANT_ID", "ENTRA_CLIENT_ID") if not os.environ.get(k)]
    if not _secret_given("TEST_REFRESH_TOKEN_FILE"):
        missing.append("TEST_REFRESH_TOKEN_FILE")
    if not (
        _secret_given("VCFA_PROVIDER_BEARER_FILE")
        or _secret_given("VCFA_PROVIDER_REFRESH_TOKEN_FILE")
    ):
        missing.append("VCFA_PROVIDER_BEARER_FILE or VCFA_PROVIDER_REFRESH_TOKEN_FILE")
    if not (
        _secret_given("ENTRA_CLIENT_SECRET_FILE")
        or (_secret_given("ENTRA_CERT_FILE") and _secret_given("ENTRA_KEY_FILE"))
    ):
        missing.append("ENTRA_CLIENT_SECRET_FILE, or ENTRA_CERT_FILE and ENTRA_KEY_FILE")
    if missing:
        print(f"set {', '.join(missing)} (see the header)", file=sys.stderr)
        return EXIT_USAGE
    for name in (
        "TEST_REFRESH_TOKEN_FILE",
        "VCFA_PROVIDER_BEARER_FILE",
        "VCFA_PROVIDER_REFRESH_TOKEN_FILE",
        "ENTRA_CLIENT_SECRET_FILE",
        "ENTRA_CERT_FILE",
        "ENTRA_KEY_FILE",
    ):
        if REPLAY is None and os.environ.get(name) and not os.access(os.environ[name], os.R_OK):
            print(f"{name}: the file cannot be read", file=sys.stderr)
            return EXIT_USAGE
    try:
        record, calls = run(a)
    except UsageError as e:
        print(f"not run as asked: {e}; nothing written", file=sys.stderr)
        return EXIT_USAGE
    except (urllib.error.URLError, OSError, KeyError, ValueError) as e:
        print(
            f"could not obtain a credential or read: {type(e).__name__}; nothing is proven (exit 3)",
            file=sys.stderr,
        )
        return EXIT_UNREAD
    record["exit"] = verdict(record["checks"])
    return write(record, calls, a.redact)


def main(argv: list[str] | None = None) -> int:
    """The run, with two guards around it: a Python older than 3.10 is refused (exit 5) before anything is read, and an
    error the script did not expect exits 3, never 1, the code for a leaver who still has a way in."""
    if sys.version_info < (3, 10):  # noqa: UP036  the script is run by readers on their own Python
        print("leaver_test.py needs Python 3.10 or later", file=sys.stderr)
        return EXIT_USAGE
    try:
        return _run(argv)
    except Exception as e:  # the last guard: whatever was not expected is not known, so exit 3
        print(
            f"the run stopped on an error it did not expect: {type(e).__name__}; nothing is proven (exit 3)",
            file=sys.stderr,
        )
        return EXIT_UNREAD
    finally:
        replay_stop()


if __name__ == "__main__":
    sys.exit(main())
