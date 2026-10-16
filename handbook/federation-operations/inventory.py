#!/usr/bin/env python3
"""inventory.py - the provider's view across its Entra tenants: which organizations federate to each, who owns each
side, whether each tenant consented to the read-only app, and whether the watch's and the leaver report's schedules are
running. Read-only.

The federation watch (watch.py, beside this file) and the leaver report (leavers.py, in the identity-lifecycle
companion) each run once per Entra tenant, and neither holds the list of tenants it runs for, who owns each side,
which tenant withholds the read-only app, or whether each schedule still runs. This script holds that list in a file
the provider keeps, the inventory, and reads the estate against it both ways: an organization federated to a tenant
the file has no row for, or missing from its tenant's row, and a row or a declared organization that names no
organization.

Reads. From VCF Automation, as the provider:
  GET /cloudapi/1.0.0/orgs                       every organization, read whole
  GET /api/admin/org/{id}/settings/oauth         its OIDC settings; the client secret is deleted on arrival, unread
  GET /api/admin/org/{id}/settings/federation    its SAML settings and the identity provider metadata it holds
On a provider API token the run first trades it for a bearer at /oauth/provider/token (a POST that opens a session and
changes no setting). From Entra, with no credential: GET the public OpenID configuration of each tenant the file names
by a domain name, whose issuer names the tenant's id. From the local disk: the inventory, and the last record each
declared schedule wrote. Nothing on VCF Automation or Entra changes, and no Graph credential is taken: a tenant's
consent is read from the watch's own record (its mode), never from a token request.

Each organization is read as the watch reads it: OIDC is on when its OIDC settings are enabled and not signed in
through VCF single sign-on (vidb); SAML is on when its federation settings are enabled; otherwise it signs in through
VCF single sign-on, or its federation is switched off. Its Entra tenant is read from the stored OIDC issuer or the
stored SAML metadata, whether or not the protocol is on; one switched off whose stored settings name no Entra tenant
reads as not federated. The provider's own consumption organization is listed as the provider's and not read
further, as the watch leaves it out.

The inventory (JSON, named by INVENTORY_FILE; inventory.example.json shows its shape). Keys starting with "_" are
notes and are ignored; any other key not listed here is refused, so a misspelled key is never read as a missing one:
  {"tenants": [{
     "tenant": "<the tenant's id, or one of its domain names>",
     "consent": "consented" | "withheld",          withheld: the watch runs declared --provider-only
     "owners": {"tenant": "<role or mailbox>", "provider": "<role or mailbox>"},
     "schedules": {
       "watch":   {"every_hours": 24, "record": "<path of the watch.json that schedule writes>", "slack_hours": 1},
       "leavers": {"every_hours": 24, "record": "<path of its leavers.json>"} | null},
     "organizations": ["<name>", {"name": "<name>", "id": "urn:vcloud:org:<uuid>", "federation": "on" | "off"}]}]}
A record path that is not absolute is read from the inventory's own folder. slack_hours defaults to 1; federation
defaults to on. A tenant that withholds the app has no leaver report to schedule (the report needs the app), so its
leavers is null.

What it judges, each a line with its state (ok, drift, unread, or note, which is information and changes no exit):
  organization  federated to a tenant with no row, or missing from its tenant's row (drift); declared under another
                tenant's row than the one its settings name, switched off while declared on, on while declared off,
                or signing in through VCF single sign-on while declared (drift); its settings not read (unread). An
                organization switched off is reported as switched off, never as missing; one on toward a provider other
                than Entra ID, signed in through VCF single sign-on, or never federated, and not declared, is a note.
  row           a declared organization that no organization matches: no organization by its name; its declared id
                held by an organization of another name; or its name held by an organization of another id, a name
                reused by a new organization (drift). A row no organization names, switched on or off (drift; unread
                when an organization's settings were not read, since the unread one may name it).
  owners        the tenant's owner or the provider's owner blank or missing (drift).
  watch, leavers  the last record each schedule wrote: past its interval plus its slack, a missed run (drift, whatever
                the record holds); missing, unreadable, without a capture time it can read, or from a run that did not
                read (unread); no watch schedule, or no leaver report for a tenant that consented (drift).
  consent       the file's consent against the watch's last record: consented with a run declared provider-only or
                run without the app, or withheld with a run made with the tenant's app or not declared (drift).
The record check. Before it uses a schedule's record the inventory checks that the run which wrote it read: the record
parses as a JSON object and carries the fields used here (the watch's captured, exit, mode, judged, run_errors and
organizations, each with its read_errors; the leaver report's captured, exit, mode, organizations, unreadable, summary
and calls); it does not declare itself replayed ("replay": a run answered from a recorded set is no run of the
schedule); its exit is one its tool writes and is not 3 or 5; the watch judged at least one organization, names no
run error and no organization's read error; the leaver record is a report (an --execute or a close-now record covers
one organization), names no unreadable organization and no account undetermined, judged at least one organization, and
records no call refused or misshapen. A record that fails is from a run that did not read: its schedule is unread
(exit 3), and its consent is not compared. A check that could not run is never a pass. The findings inside a record
(the watch's warnings and failures, the report's open leavers) are its own schedule's to act on: the inventory prints
the record's exit beside it and leaves it out of its own. A record names its tenant by a placeholder only, so the file's
path is what ties a record to its tenant.

Env:  VCFA_HOST; VCFA_PROVIDER_REFRESH_TOKEN_FILE (a provider API token) or VCFA_PROVIDER_BEARER_FILE (a provider
      bearer), as the watch takes them; TLS_VERIFY=false on a self-signed lab CA (VCF Automation only; Entra is always
      verified); INVENTORY_FILE (the inventory; kept private, it names the estate); OUT (default inventory.json, or
      inventory.replay.json under --replay: the record, never the inventory or a schedule's record).
Use:  python3 inventory.py               read, print, write the record
      python3 inventory.py --redact      print with placeholders instead of your names (for a shared transcript)
      python3 inventory.py --replay replay/inventory   without an estate: every answer from the recorded set beside this
                                         script, against the inventory the set names (replay/inventory/files/, its
                                         schedules pointed at the records in this companion tree); nothing is sent and
                                         no credential is read, a request the set holds no answer for is a read that
                                         failed (exit 3), and the record carries "replay": true
Exit, the first that applies: 3 the run judged no organization (a wrong host, a credential that lists none it can
      read) · 1 drift a person acts on: an organization with no row or missing from its row, a row or a declared
      organization with no organization, a reused name, a declared state the estate does not hold, a blank owner, a
      missed schedule, a schedule not declared, a consent the watch's record contradicts · 3 nothing drifted, and a read
      failed or a result is undetermined: the organization list not read whole, a settings read refused, a schedule's
      record missing, unreadable or from a run that did not read, a tenant's domain not resolved, a record the scrub
      refused (no record is written), or a request a --replay set holds no answer for · 0 nothing for a person to act
      on · 5 a usage error: an unknown or abbreviated flag, a missing environment variable or a file that cannot be
      read, a --replay directory that cannot be read or holds no replay set, an inventory that is not valid JSON or not
      the shape above, a tenant that is neither an id nor a domain name or a domain Entra names no tenant for, a tenant
      or an organization declared twice, OUT naming the inventory or a schedule's record, a Python older than 3.9.
      An error the run did not expect exits 3, never 1. A record the scrub refuses never hides a 1, and turns a 0 into
      a 3.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

CLOUDAPI = "application/json;version=9.1.0"
VCD_JSON = "application/*+json;version=9.1.0"
ENTRA = "https://login.microsoftonline.com"
# Every list is read page by page; a page of this size is the most the platform was asked for at once.
PAGE_SIZE = 128
SECRET_KEYS = ("clientSecret", "password", "secretText", "hint", "privateKey")
# One code per state a scheduler acts on (the identity companions' shared contract): 0 nothing to act on, 1 drift a
# person acts on, 3 a read failed or a result is undetermined (never a finding), 5 not run as asked.
EXIT_OK, EXIT_DRIFT, EXIT_UNREAD, EXIT_USAGE = 0, 1, 3, 5
OK, DRIFT, UNREAD, NOTE = "ok", "drift", "unread", "note"
SLACK_HOURS = 1
SCHEDULES = ("watch", "leavers")
# What the watch's record says of the run's Graph credential (watch.py, main's `mode`), and the consent each shows.
WATCH_MODES = {"with the tenant's app": "consented", "provider-only, declared": "withheld",
               "provider-only, undeclared": None}
# What the inventory reads from each record, and the exits each tool writes (watch.py and leavers.py, Exit).
WATCH_FIELDS = ("captured", "exit", "mode", "judged", "run_errors", "organizations")
LEAVERS_FIELDS = ("captured", "exit", "mode", "organizations", "unreadable", "summary", "calls")
WATCH_EXITS = (0, 1, 2, 3, 5)
LEAVERS_EXITS = (0, 1, 2, 3, 4, 5)
# The commands a line suggests: each parses with the parser of the tool it names (G-463), held by the tests.
SUGGEST_DECLARE = ("watch.py", ["--provider-only"])
SUGGEST_REDACT = ("inventory.py", ["--redact"])


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


# ── reading, written as the watch writes it ──────────────────────────────────────────────────────────────────────
_CONTEXTS: dict = {}


def _ctx(verify: bool) -> ssl.SSLContext:
    """One TLS context per verify mode for the run: building one loads the CA store, which every request repeated."""
    if verify not in _CONTEXTS:
        _CONTEXTS[verify] = ssl.create_default_context() if verify else ssl._create_unverified_context()
    return _CONTEXTS[verify]


def _lab_verify() -> bool:
    return os.environ.get("TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")


def _fetch(url: str, headers: dict, verify: bool, data: bytes | None = None, method: str = "GET"):
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with _urlopen(req, context=_ctx(verify), timeout=60) as r:
        body = r.read()
        return json.loads(body) if "json" in (r.headers.get("Content-Type") or "") else body.decode(errors="replace")


def _strip(obj: object) -> bool:
    """Delete every secret-bearing key in place; True when one carried a value."""
    found = False
    if isinstance(obj, dict):
        for k in list(obj):
            if k in SECRET_KEYS:
                value = obj.pop(k)  # pop first: an `or` would skip the pop once one secret is found
                found = bool(value) or found
            else:
                found = _strip(obj[k]) or found
    elif isinstance(obj, list):
        for v in obj:
            found = _strip(v) or found
    return found


class ReadError(ValueError):
    """A list not read whole: what it would have shown is not known (exit 3), never a short or an empty list."""


MAX_PAGES = 10000


def whole_list(fetch, what: str) -> list[dict]:
    """Every item of a VCF Automation cloudapi list, read page by page (fetch(page), pages counted from 1) until the
    count of distinct items, by id, equals the total the answer states (resultTotal). A list is read whole or not at
    all: an answer without its list or without a stated total, a page that comes back empty or short before the total
    is reached, pages that end (pageCount) short of it, a total that changes between pages, or a page that adds no item
    not already read (a pager that would never reach the total), is a list not read (ReadError, exit 3), never a short
    or an empty one. Each page adds at least one item, so the read ends within the total's count of pages."""
    seen: set = set()
    out: list[dict] = []
    total, size = None, None
    for page in range(1, MAX_PAGES + 1):
        data = fetch(page)
        if not isinstance(data, dict) or not isinstance(data.get("values"), list):
            raise ReadError(f"{what}: page {page} came back without its list")
        stated = data.get("resultTotal")
        if isinstance(stated, bool) or not isinstance(stated, int):
            raise ReadError(f"{what}: page {page} states no total, so a short list could not be told from a whole one")
        if total is None:
            total = stated
        elif stated != total:
            raise ReadError(f"{what}: the stated total moved from {total} to {stated} between pages")
        rows, before = data["values"], len(out)
        for row in rows:   # a row that moved to a later page during the read is counted once
            ident = row.get("id") if isinstance(row, dict) and row.get("id") else json.dumps(row, sort_keys=True)
            if ident not in seen:
                seen.add(ident)
                out.append(row)
        if len(out) == total:
            return out
        if len(out) > total:
            raise ReadError(f"{what}: {len(out)} distinct items against the {total} the answer states")
        if size is None:   # the page size the platform answers with, which can be less than the size asked for
            size = data.get("pageSize") if isinstance(data.get("pageSize"), int) and data.get("pageSize") > 0 else len(rows)
        count = data.get("pageCount")
        if not rows or len(rows) < size or (isinstance(count, int) and page >= count):
            raise ReadError(f"{what}: the pages ended at {len(out)} of the {total} items the answer states")
        if len(out) == before:   # a whole page of items already read: a pager that does not advance is not followed
            raise ReadError(f"{what}: page {page} added no item not already read, at {len(out)} of the {total} the "
                            "answer states")
    raise ReadError(f"{what}: more than {MAX_PAGES} pages")


def _secret_file(name: str) -> str:
    if REPLAY is not None:  # a replayed run reads no credential: nothing is sent
        return REPLAY_CREDENTIAL
    with open(os.environ[name], encoding="utf-8") as f:
        return f.read().strip()


class Vcfa:
    def __init__(self, host: str):
        self.host, self.verify = host, _lab_verify()
        if os.environ.get("VCFA_PROVIDER_BEARER_FILE"):
            self.kind = "provider bearer"
            self._bearer = _secret_file("VCFA_PROVIDER_BEARER_FILE").removeprefix("Bearer ").strip()
        else:
            self.kind = "provider API token"
            form = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": _secret_file("VCFA_PROVIDER_REFRESH_TOKEN_FILE")}).encode()
            r = _fetch(f"https://{host}/oauth/provider/token", {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}, self.verify, form, "POST")
            self._bearer = r["access_token"]
            del form, r

    def get(self, path: str, accept: str = CLOUDAPI, org_id: str | None = None):
        h = {"Authorization": f"Bearer {self._bearer}", "Accept": accept}
        if org_id:
            h["X-VMWARE-VCLOUD-TENANT-CONTEXT"] = org_id
        return _fetch(f"https://{self.host}{path}", h, self.verify)

    def pages(self, path: str, org_id: str | None = None) -> list[dict]:
        """Every item of a cloudapi list, read whole (whole_list): a page that answers without its list or its stated
        total, or pages that end short of that total, are a read that did not happen (ReadError, exit 3), never a
        short or an empty list."""
        sep = "&" if "?" in path else "?"
        return whole_list(lambda page: self.get(f"{path}{sep}page={page}&pageSize={PAGE_SIZE}", org_id=org_id),
                          path.split("?")[0])

    def oauth(self, uid: str) -> dict:
        """The organization's OIDC settings, with the client secret deleted on arrival: the inventory never reads it."""
        body = self.get(f"/api/admin/org/{uid}/settings/oauth", VCD_JSON)
        _strip(body)
        return body

    def federation(self, uid: str) -> dict:
        body = self.get(f"/api/admin/org/{uid}/settings/federation", VCD_JSON)
        _strip(body)
        return body


# ── tenants, resolved as the watch resolves them ─────────────────────────────────────────────────────────────────
ENTRA_TENANT_IN = re.compile(r"(?:login\.microsoftonline\.com|sts\.windows\.net)/([0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})/")
TENANT_ID = re.compile(r"^[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$")
DOMAIN = re.compile(r"^(?=.{4,253}$)[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$")


def entra_tenant(protocol: str, oauth: dict, fed: dict) -> str | None:
    """The Entra tenant an organization is federated to: from the OIDC issuer, or from the issuer in the SAML metadata
    it holds. None when the provider is not Entra ID."""
    text = (oauth.get("issuerId") or "") if protocol == "oidc" else (fed.get("samlMetadata") or "") if protocol == "saml" else ""
    m = ENTRA_TENANT_IN.search(text)
    return m.group(1).lower() if m else None


class TenantError(Exception):
    """A tenant the inventory names that names no Entra tenant: a usage error (exit 5)."""


def tenant_form(value: str) -> str:
    """'id', 'domain', or '' for a string that is neither (a usage error before anything is read)."""
    v = value.strip()
    return "id" if TENANT_ID.match(v) else "domain" if DOMAIN.match(v) else ""


def resolve_tenant(value: str, discover=None) -> str:
    """The tenant's id in lower case. An id is taken as it is. A domain name is resolved through Entra's public OpenID
    configuration for it, whose issuer names the tenant's id; Entra answers a domain that names no tenant with an
    error (TenantError, exit 5). A read that does not answer raises as any read does (exit 3)."""
    v = value.strip()
    if TENANT_ID.match(v):
        return v.lower()
    if not DOMAIN.match(v):
        raise TenantError(f"{v!r} is neither a tenant id nor a domain name")
    fetch = discover or (lambda d: _fetch(f"{ENTRA}/{urllib.parse.quote(d)}/v2.0/.well-known/openid-configuration",
                                          {"Accept": "application/json"}, True))
    try:
        doc = fetch(v)
    except urllib.error.HTTPError as e:
        if 400 <= e.code < 500:
            raise TenantError(f"Entra names no tenant for the domain {v!r} (HTTP {e.code})") from None
        raise
    m = ENTRA_TENANT_IN.search((doc.get("issuer") or "") + "/" if isinstance(doc, dict) else "")
    if not m:
        raise TenantError(f"Entra's OpenID configuration for {v!r} names no tenant id")
    return m.group(1).lower()


# ── the inventory the provider keeps ─────────────────────────────────────────────────────────────────────────────
class InventoryError(Exception):
    """The inventory cannot be read, or is not the shape the header gives: a usage error (exit 5)."""


ORG_ID = re.compile(r"^(?:urn:vcloud:org:)?([0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})$")
ROW_KEYS = {"tenant", "consent", "owners", "schedules", "organizations"}


def _keys(obj: dict, allowed: set, where: str) -> None:
    unknown = sorted(k for k in obj if not str(k).startswith("_") and k not in allowed)
    if unknown:
        raise InventoryError(f"{where}: unknown key(s) {', '.join(repr(k) for k in unknown)}; the keys are "
                             f"{', '.join(sorted(allowed))}")


def _hours(value: object, where: str, positive: bool) -> float:
    number = not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)
    if not number or (value <= 0 if positive else value < 0):
        raise InventoryError(f"{where} takes a number of hours, {'more than 0' if positive else '0 or more'}, not "
                             f"{value!r}")
    return float(value)


def _schedule(value: object, where: str) -> dict | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise InventoryError(f"{where} is an object ({{\"every_hours\", \"record\"}}) or null")
    _keys(value, {"every_hours", "record", "slack_hours"}, where)
    if not isinstance(value.get("record"), str) or not value["record"].strip():
        raise InventoryError(f"{where}.record names the record that schedule writes")
    return {"every_hours": _hours(value.get("every_hours"), f"{where}.every_hours", True),
            "slack_hours": _hours(value.get("slack_hours", SLACK_HOURS), f"{where}.slack_hours", False),
            "record": value["record"].strip()}


def _org(value: object, where: str) -> dict:
    if isinstance(value, str):
        value = {"name": value}
    if not isinstance(value, dict):
        raise InventoryError(f"{where} is a name, or an object with a name")
    _keys(value, {"name", "id", "federation"}, where)
    if not isinstance(value.get("name"), str) or not value["name"].strip():
        raise InventoryError(f"{where}.name is the organization's name")
    out = {"name": value["name"].strip(), "federation": value.get("federation", "on")}
    if out["federation"] not in ("on", "off"):
        raise InventoryError(f"{where}.federation is \"on\" or \"off\", not {out['federation']!r}")
    if "id" in value:
        m = ORG_ID.match(str(value["id"]).strip()) if isinstance(value["id"], str) else None
        if not m:
            raise InventoryError(f"{where}.id is the organization's id, urn:vcloud:org:<uuid>")
        out["id"] = m.group(1).lower()
    return out


def load_inventory(path: str) -> list[dict]:
    """The inventory's rows, checked against the shape the header gives; anything else is a usage error (exit 5):
    unreadable, not JSON, a key not listed, a value of the wrong kind, a tenant that is neither an id nor a domain
    name, an organization declared twice, or a tenant that withholds the app with a leaver report scheduled."""
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError) as e:
        raise InventoryError(f"the inventory {path} does not read as JSON ({type(e).__name__})") from None
    if not isinstance(doc, dict) or not isinstance(doc.get("tenants"), list) or not doc["tenants"]:
        raise InventoryError("the inventory is an object whose \"tenants\" list holds at least one row")
    _keys(doc, {"tenants"}, "the inventory")
    rows, names, ids = [], set(), set()
    for i, row in enumerate(doc["tenants"], 1):
        where = f"tenants[{i}]"
        if not isinstance(row, dict):
            raise InventoryError(f"{where} is an object")
        _keys(row, ROW_KEYS, where)
        missing = sorted(k for k in ROW_KEYS if k not in row)
        if missing:
            raise InventoryError(f"{where} lacks {', '.join(missing)}")
        given = row["tenant"]
        if not isinstance(given, str) or not tenant_form(given):
            raise InventoryError(f"{where}.tenant {given!r} is neither a tenant id nor a domain name")
        if row["consent"] not in ("consented", "withheld"):
            raise InventoryError(f"{where}.consent is \"consented\" or \"withheld\", not {row['consent']!r}")
        owners = row["owners"]
        if not isinstance(owners, dict):
            raise InventoryError(f"{where}.owners is an object: {{\"tenant\": ..., \"provider\": ...}}")
        _keys(owners, {"tenant", "provider"}, f"{where}.owners")
        for side in ("tenant", "provider"):
            if owners.get(side) is not None and not isinstance(owners[side], str):
                raise InventoryError(f"{where}.owners.{side} is a role or a mailbox, as text")
        sched = row["schedules"]
        if not isinstance(sched, dict) or any(k not in sched for k in SCHEDULES):
            raise InventoryError(f"{where}.schedules names both \"watch\" and \"leavers\" (each an object, or null)")
        _keys(sched, set(SCHEDULES), f"{where}.schedules")
        out = {"given": given.strip(), "consent": row["consent"],
               "owners": {s: (owners.get(s) or "").strip() for s in ("tenant", "provider")},
               "schedules": {k: _schedule(sched[k], f"{where}.schedules.{k}") for k in SCHEDULES},
               "organizations": []}
        if out["consent"] == "withheld" and out["schedules"]["leavers"] is not None:
            raise InventoryError(f"{where}: a tenant that withholds the read-only app has no leaver report to schedule "
                                 "(the report needs the app): set schedules.leavers to null")
        if not isinstance(row["organizations"], list):
            raise InventoryError(f"{where}.organizations is a list")
        for j, value in enumerate(row["organizations"], 1):
            org = _org(value, f"{where}.organizations[{j}]")
            if org["name"] in names or org.get("id") in ids:
                raise InventoryError(f"{where}.organizations[{j}]: an organization is declared twice")
            names.add(org["name"])
            if org.get("id"):
                ids.add(org["id"])
            out["organizations"].append(org)
        rows.append(out)
    return rows


def resolve_rows(rows: list[dict], discover=None) -> list[dict]:
    """Each row's tenant as its id, resolved as the watch resolves it: a domain Entra names no tenant for is a usage
    error (TenantError, exit 5), and two rows naming one tenant are too (InventoryError); a resolution that does not
    answer raises as any read does (exit 3)."""
    done: dict = {}
    for r in rows:
        if r["given"] not in done:
            done[r["given"]] = resolve_tenant(r["given"], discover)
        r["tenant"] = done[r["given"]]
    tenants = [r["tenant"] for r in rows]
    twice = sorted({t for t in tenants if tenants.count(t) > 1})
    if twice:
        raise InventoryError(f"{len(twice)} tenant(s) have two rows: one row per tenant")
    return rows


# ── the census: every organization, read as the watch reads it ───────────────────────────────────────────────────
def org_state(oauth: dict, fed: dict) -> tuple[str, str | None]:
    """The organization's sign-in state as the watch reads it ("oidc", "saml", "vcf-sso" or "off"), and the Entra
    tenant its stored settings name: the protocol that is on, or, switched off or on VCF single sign-on, the stored
    OIDC issuer and then the stored SAML metadata, read whether or not the protocol is on."""
    oidc = bool(oauth.get("enabled")) and not oauth.get("vidb")
    saml = bool(fed.get("enabled"))
    state = "oidc" if oidc else "saml" if saml else "vcf-sso" if oauth.get("enabled") else "off"
    if state in ("oidc", "saml"):
        return state, entra_tenant(state, oauth, fed)
    return state, entra_tenant("oidc", oauth, fed) or entra_tenant("saml", oauth, fed)


def _why(e: BaseException) -> str:
    code = getattr(e, "code", None)
    return f"{type(e).__name__} {code}" if isinstance(code, int) else type(e).__name__


def read_census(api: Vcfa, listed: list[dict], seen: set) -> list[dict]:
    """One entry per organization listed: its name, id, state and stored tenant. The provider's own consumption
    organization is the provider's, and not read. An organization whose settings read fails is kept, named, with its
    state "unread", never dropped. `seen` collects every estate value read, for the scrub."""
    out = []
    for org in listed:
        name = str(org.get("name") or "") if isinstance(org, dict) else ""
        urn = str(org.get("id") or "") if isinstance(org, dict) else ""
        uid = urn.rsplit(":", 1)[-1]
        seen.update(v for v in (name, urn, uid) if v)
        entry = {"org": name, "id": uid.lower()}
        if isinstance(org, dict) and org.get("isProviderConsumptionOrg"):
            entry["state"] = "provider"
            out.append(entry)
            continue
        try:
            oauth, fed = api.oauth(uid), api.federation(uid)
            if not isinstance(oauth, dict) or not isinstance(fed, dict):
                raise ReadError("the settings came back without a JSON body")
        except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
            entry.update(state="unread", read_error=f"VCF Automation: {_why(e)}")
            out.append(entry)
            continue
        entry["state"], entry["tenant"] = org_state(oauth, fed)
        seen.update(v for v in (oauth.get("issuerId"), oauth.get("clientId"), oauth.get("jwksUri"),
                                oauth.get("orgRedirectUri"), entry["tenant"]) if isinstance(v, str) and v)
        out.append(entry)
    return out


# ── the record check: did the run that wrote a schedule's record read? ───────────────────────────────────────────
CAPTURED = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")


def captured_at(doc: dict) -> datetime | None:
    """A record's capture time, in the form both tools write it (UTC, to the second, a Z suffix); None otherwise."""
    value = doc.get("captured")
    if not isinstance(value, str) or not CAPTURED.match(value):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _exit_problem(doc: dict, codes: tuple, tool: str) -> list[str]:
    if doc.get("replay"):   # answered from a recorded set: it shows no run of the schedule
        return ["it is a replayed record, answered from a recorded set, not a run of the schedule"]
    code = doc.get("exit")
    if isinstance(code, bool) or not isinstance(code, int) or code not in codes:
        return [f"its exit {code!r} is not one {tool} writes"]
    if code == 3:
        return ["its run exited 3: a read failed or a result was undetermined"]
    if code == 5:
        return ["its run exited 5: not run as asked"]
    return []


def watch_record_problems(doc: object) -> list[str]:
    """Why a watch record is not from a run that read, or [] when it is: every field the inventory reads present, an
    exit the watch writes other than 3 or 5, a mode it writes, at least one organization judged, no run error, and no
    organization carrying a read error."""
    if not isinstance(doc, dict):
        return ["the record is not a JSON object"]
    missing = [k for k in WATCH_FIELDS if k not in doc]
    if missing:
        return [f"the record lacks {', '.join(missing)}"]
    out = _exit_problem(doc, WATCH_EXITS, "the watch")
    if doc["mode"] not in WATCH_MODES:
        out.append(f"its mode {doc['mode']!r} is not one the watch writes")
    judged = doc["judged"]
    if isinstance(judged, bool) or not isinstance(judged, int) or judged < 1:
        out.append("its run judged no organization")
    if not isinstance(doc["run_errors"], list) or doc["run_errors"]:
        out.append("its run names a run error")
    orgs = doc["organizations"]
    if not isinstance(orgs, list) or not all(isinstance(o, dict) and isinstance(o.get("read_errors"), list) for o in orgs):
        out.append("its organizations do not each carry a read_errors list")
    else:
        unread = sum(1 for o in orgs if o["read_errors"])
        if unread:
            out.append(f"{unread} organization(s) in it carry a read error")
    return out


def leavers_record_problems(doc: object) -> list[str]:
    """Why a leaver record is not from a scheduled report that read, or [] when it is: every field the inventory reads
    present, an exit the report writes other than 3 or 5, a report (an --execute or close-now record covers one
    organization), no unreadable organization and no account undetermined, at least one organization judged, and no
    call refused or misshapen."""
    if not isinstance(doc, dict):
        return ["the record is not a JSON object"]
    missing = [k for k in LEAVERS_FIELDS if k not in doc]
    if missing:
        return [f"the record lacks {', '.join(missing)}"]
    out = _exit_problem(doc, LEAVERS_EXITS, "the leaver report")
    if doc["mode"] != "report":
        out.append(f"it is a {doc['mode']!r} record, not the scheduled report's: it covers one organization")
    if not isinstance(doc["unreadable"], list) or doc["unreadable"]:
        out.append("it names an unreadable organization")
    summary = doc["summary"] if isinstance(doc["summary"], dict) else {}
    if not summary:
        out.append("its summary does not read")
    elif summary.get("unreadable") or summary.get("undetermined") or summary.get("credential_unread"):
        out.append("its summary counts an unreadable organization, an undetermined account or an unread credential")
    if not isinstance(doc["organizations"], list) or not doc["organizations"]:
        out.append("its run judged no organization")
    calls = doc["calls"]
    if not isinstance(calls, list) or not all(isinstance(c, dict) for c in calls):
        out.append("its calls do not read")
    else:
        failed = sum(1 for c in calls if not isinstance(c.get("status"), int) or c["status"] >= 400 or c.get("shape"))
        if failed:
            out.append(f"{failed} of its {len(calls)} call(s) were refused or came back misshapen")
    return out


PROBLEMS = {"watch": watch_record_problems, "leavers": leavers_record_problems}


def record_path(sched: dict, base: Path) -> Path:
    p = Path(sched["record"]).expanduser()
    return p if p.is_absolute() else base / p


def judge_schedule(kind: str, sched: dict, base: Path, now: datetime) -> dict:
    """The schedule's last record, judged: past its interval plus its slack is a missed run (drift, whatever the record
    holds, since no run has written it since); missing, unreadable, without a capture time, captured later than the
    slack allows, or from a run that did not read, is unread. `doc` is the record when its run read, for the consent."""
    path = record_path(sched, base)
    every, slack = sched["every_hours"], sched["slack_hours"]
    measure = {"every_hours": every, "slack_hours": slack}
    out = {"state": UNREAD, "measure": measure, "doc": None}
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except FileNotFoundError:
        out["detail"] = f"the record {path} is missing: the schedule has not written it, or the path is wrong"
        return out
    except (OSError, ValueError) as e:
        out["detail"] = f"the record {path} does not read as JSON ({type(e).__name__})"
        return out
    if not isinstance(doc, dict):
        out["detail"] = f"the record {path} is not a JSON object"
        return out
    at = captured_at(doc)
    if at is None:
        out["detail"] = "the record carries no capture time that reads, so its age is not known"
        return out
    age = now - at
    measure["age_h"] = round(age.total_seconds() / 3600, 1)
    measure["record_exit"] = doc.get("exit")
    if kind == "watch":
        measure["record_mode"] = doc.get("mode")
    if age < -timedelta(hours=slack):
        out["detail"] = f"the record was captured {-measure['age_h']} h after this run's own time: its age is not known"
        return out
    problems = PROBLEMS[kind](doc)
    if problems:
        measure["problems"] = problems
    if age > timedelta(hours=every + slack):
        out["state"] = DRIFT
        out["detail"] = (f"the last record is {measure['age_h']} h old, past its {_h(every)} h interval plus "
                         f"{_h(slack)} h of slack: the schedule missed its run" +
                         (f" (the record also fails its check: {'; '.join(problems)})" if problems else ""))
        out["doc"] = None if problems else doc
        return out
    if problems:
        out["detail"] = f"the last record ({measure['age_h']} h old) is from a run that did not read: {'; '.join(problems)}"
        return out
    out.update(state=OK, doc=doc, detail=f"the last record is {measure['age_h']} h old, inside its {_h(every)} h "
               f"interval plus {_h(slack)} h of slack; its run read, and exited {doc['exit']} (its own schedule acts on that)")
    return out


def _h(hours: float) -> str:
    return str(int(hours)) if float(hours).is_integer() else str(hours)


def judge_consent(consent: str, watch: dict | None) -> tuple[str, str]:
    """The file's consent against the mode of the watch's last record, when that record passed its check."""
    if watch is None or watch.get("doc") is None:
        return NOTE, "not compared: no watch record that passed its check"
    mode = watch["doc"]["mode"]
    shown = WATCH_MODES.get(mode)
    if shown == consent:
        return OK, ("the watch's last run read with the tenant's app, as the file states" if consent == "consented" else
                    "the watch's last run was declared provider-only, as the file states the tenant withholds the app")
    if consent == "consented":
        how = "was declared provider-only" if mode == "provider-only, declared" else "ran without the tenant's app"
        return DRIFT, (f"the file states the tenant consented, and the watch's last run {how}: give the watch the "
                       "tenant's read-only app (ENTRA_TENANT_ID, ENTRA_CLIENT_ID and its credential), or set consent "
                       "to withheld")
    if mode == "with the tenant's app":
        return DRIFT, ("the file states the tenant withholds the read-only app, and the watch's last run read with it: "
                       "set consent to consented, or take the app's credential out of the watch's schedule")
    tool, argv = SUGGEST_DECLARE
    return DRIFT, (f"the file states the tenant withholds the read-only app, and the watch's last run was not declared: "
                   f"run it as {tool} {' '.join(argv)}")


# ── judging the estate against the inventory ─────────────────────────────────────────────────────────────────────
def _finding(state: str, subject: str, detail: str, tenant: str | None = None, org: str | None = None,
             **measure: object) -> dict:
    out = {"state": state, "subject": subject, "tenant": tenant, "org": org, "detail": detail}
    if measure:
        out["measure"] = measure
    return out


PROTO = {"oidc": "OIDC", "saml": "SAML"}


def _declared(rows: list[dict], org: dict) -> tuple[dict, dict] | None:
    """The row and entry that declare this organization: by id where the entry gives one, else by name."""
    for r in rows:
        for d in r["organizations"]:
            if (d["id"] == org["id"]) if d.get("id") else (d["name"] == org["org"]):
                return r, d
    return None


def judge_orgs(rows: list[dict], census: list[dict]) -> list[dict]:
    """One line per organization listed: where it stands against the file."""
    has_row = {r["tenant"] for r in rows}
    out = []
    for o in census:
        name, state, t = o["org"], o["state"], o.get("tenant")
        m = _declared(rows, o)
        row = m[0]["tenant"] if m else None
        if state == "provider":
            out.append(_finding(DRIFT if m else NOTE, "organization", "the provider's own consumption organization, "
                                + ("declared under this tenant: it is the provider's, and the watch leaves it out" if m
                                   else "left out as the watch leaves it out"), row, name))
        elif state == "unread":
            out.append(_finding(UNREAD, "organization", f"its settings were not read ({o['read_error']}): its tenant "
                                "and state are not known", row, name))
        elif state in PROTO and t is None:
            out.append(_finding(DRIFT, "organization", f"{PROTO[state]} is on toward a provider other than Entra ID, "
                                "and the file declares it under this tenant", row, name) if m else
                       _finding(NOTE, "organization", f"{PROTO[state]} is on toward a provider other than Entra ID: "
                                "outside this inventory, which reads Entra tenants", None, name))
        elif state in PROTO:
            if m and row != t:
                out.append(_finding(DRIFT, "organization", f"{PROTO[state]}, federated to the tenant {t}, and declared "
                                    "under this row", row, name))
            elif m and m[1]["federation"] == "off":
                out.append(_finding(DRIFT, "organization", f"{PROTO[state]} is on, and the file declares its "
                                    "federation switched off", row, name))
            elif m:
                out.append(_finding(OK, "organization", f"{PROTO[state]}, federated to this tenant, declared", row, name))
            elif t in has_row:
                out.append(_finding(DRIFT, "organization", f"{PROTO[state]}, federated to this tenant, and missing "
                                    "from its row's organization list", t, name))
            else:
                out.append(_finding(DRIFT, "organization", f"{PROTO[state]}, federated to the tenant {t}, which has "
                                    "no row in the file", None, name))
        elif state == "off":
            names = f"its stored settings name the tenant {t}" if t else "its stored settings name no Entra tenant"
            if m and t and row != t:
                out.append(_finding(DRIFT, "organization", f"switched off; {names}, not this row's", row, name))
            elif m and m[1]["federation"] == "off":
                out.append(_finding(OK, "organization", f"switched off, as the file declares; {names}", row, name))
            elif m:
                out.append(_finding(DRIFT, "organization", f"switched off: neither OIDC nor SAML is on, and the file "
                                    f"declares it on; {names}", row, name))
            elif t:
                out.append(_finding(NOTE, "organization", f"switched off, and not declared; {names}",
                                    t if t in has_row else None, name))
            else:
                out.append(_finding(NOTE, "organization", "neither OIDC nor SAML is on, and its stored settings name "
                                    "no Entra tenant: not federated, and not declared", None, name))
        else:   # vcf-sso
            out.append(_finding(DRIFT, "organization", "signs in through VCF single sign-on, and the file declares it "
                                "under this tenant", row, name) if m else
                       _finding(NOTE, "organization", "signs in through VCF single sign-on: the platform's sign-in, "
                                "outside this inventory", None, name))
    return out


def judge_rows(rows: list[dict], census: list[dict]) -> list[dict]:
    """Each row against the census: a declared organization nothing matches, and a row no organization names."""
    by_name = {o["org"]: o for o in census}
    by_id = {o["id"]: o for o in census if o.get("id")}
    unread = sum(1 for o in census if o["state"] == "unread")
    out = []
    for r in rows:
        for d in r["organizations"]:
            if d.get("id"):
                live = by_id.get(d["id"])
                if live and live["org"] != d["name"]:
                    out.append(_finding(DRIFT, "row", f"its declared id is held by the organization {live['org']}: "
                                        "renamed, or the entry's id is wrong", r["tenant"], d["name"]))
                elif not live and d["name"] in by_name:
                    out.append(_finding(DRIFT, "row", "the name is held by an organization of another id than "
                                        "declared: the declared organization is gone and a new one took its name; vet "
                                        "the new one before you declare its id", r["tenant"], d["name"]))
                elif not live:
                    out.append(_finding(DRIFT, "row", "no organization holds the declared name or the declared id",
                                        r["tenant"], d["name"]))
            elif d["name"] not in by_name:
                out.append(_finding(DRIFT, "row", "no organization by the declared name", r["tenant"], d["name"]))
        named = [o for o in census if o.get("tenant") == r["tenant"] and o["state"] in ("oidc", "saml", "off")]
        if named:
            continue
        if unread:
            out.append(_finding(UNREAD, "row", f"no organization read names this tenant, and {unread} organization(s) "
                                "were not read: one of them may", r["tenant"]))
        else:
            out.append(_finding(DRIFT, "row", "no organization names this tenant, switched on or off", r["tenant"]))
    return out


def judge_row_terms(r: dict, base: Path, now: datetime) -> list[dict]:
    """A row's owners, its schedules' last records, and its consent against the watch's last record."""
    t, out = r["tenant"], []
    blank = [side for side in ("tenant", "provider") if not r["owners"][side]]
    if blank:
        who = " and ".join(f"the {s}'s owner" for s in blank)
        out.append(_finding(DRIFT, "owners", f"{who} {'is' if len(blank) == 1 else 'are'} blank: name a role or a "
                            "mailbox", t))
    else:
        out.append(_finding(OK, "owners", "the tenant's owner and the provider's owner are named", t))
    results = {}
    for kind in SCHEDULES:
        sched = r["schedules"][kind]
        if sched is None:
            results[kind] = None
            if kind == "watch":
                out.append(_finding(DRIFT, "watch", "no watch schedule is declared: nothing reads this tenant's "
                                    "organizations for drift", t))
            elif r["consent"] == "consented":
                out.append(_finding(DRIFT, "leavers", "no leaver report is scheduled for a tenant that consented to "
                                    "the read-only app it needs", t))
            else:
                out.append(_finding(NOTE, "leavers", "no leaver report: it needs the read-only app, which the tenant "
                                    "withholds; a leaver is closed from the tenant's dated leaver notice", t))
            continue
        res = results[kind] = judge_schedule(kind, sched, base, now)
        out.append(_finding(res["state"], kind, res["detail"], t, **res["measure"]))
    state, detail = judge_consent(r["consent"], results["watch"])
    out.append(_finding(state, "consent", detail, t, consent=r["consent"]))
    return out


NONE_JUDGED = "the run judged no organization"


def judge(rows: list[dict], census: list[dict], now: datetime, base: Path) -> tuple[list[dict], list[str]]:
    """Every finding, and what is wrong with the run as a whole. A run that read no organization's settings judges no
    organization and no row (each would read as drift built on nothing), and exits 3."""
    errors = []
    judged = [o for o in census if o["state"] not in ("provider", "unread")]
    findings = []
    if judged:
        findings += judge_orgs(rows, census) + judge_rows(rows, census)
    else:
        unread = sum(1 for o in census if o["state"] == "unread")
        own = sum(1 for o in census if o["state"] == "provider")
        parts = [f"{len(census)} listed"] + ([f"{own} the provider's own"] if own else []) + \
                ([f"{unread} not read"] if unread else [])
        errors.append(f"{NONE_JUDGED} ({'; '.join(parts)}): check VCFA_HOST and the credential; a run that judges "
                      "nothing is never a pass")
        findings += [f for f in judge_orgs(rows, census) if f["state"] in (NOTE, UNREAD)]
    for r in rows:
        findings += judge_row_terms(r, base, now)
    return findings, errors


def exit_code(findings: list[dict], errors: list[str] | tuple = ()) -> int:
    """The first that applies: a run that judged no organization (3); drift (1); a read that failed or a result
    undetermined (3); nothing to act on (0). A note changes no exit."""
    states = {f["state"] for f in findings}
    if errors:
        return EXIT_UNREAD
    if DRIFT in states:
        return EXIT_DRIFT
    return EXIT_UNREAD if UNREAD in states else EXIT_OK


def census_counts(census: list[dict], rows: list[dict]) -> dict:
    states = [o["state"] for o in census]
    return {"listed": len(census), "provider_own": states.count("provider"), "unread": states.count("unread"),
            "judged": sum(1 for s in states if s not in ("provider", "unread")),
            "oidc": states.count("oidc"), "saml": states.count("saml"), "switched_off": states.count("off"),
            "vcf_sso": states.count("vcf-sso"),
            "other_provider": sum(1 for o in census if o["state"] in PROTO and not o.get("tenant")),
            "tenants_named": len({o["tenant"] for o in census if o.get("tenant")}),
            "rows": len(rows), "declared": sum(len(r["organizations"]) for r in rows)}


# ── the record contract ──────────────────────────────────────────────────────────────────────────────────────────
UUIDISH = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
# Product vocabulary never becomes a placeholder, even when an estate object is named after it.
RESERVED = {"Organization Administrator", "Organization User", "Organization Member", "Organization Auditor",
            "Organization Owner", "Administrator", "administrator", "admin", "System", "OAUTH", "SAML", "LOCAL", "OIDC"}
HOSTISH = re.compile(r"\b[a-z0-9-]+(?:\.[a-z0-9-]+)+\.[a-z]{2,}\b", re.I)
PLACEHOLDER = re.compile(r"\{\{[a-z-]+(?:-\d+)?\}\}")


class ScrubError(Exception):
    """The record (or a redacted print) would carry an estate value, so it is not written."""


def placeholders(rows: list[dict], census: list[dict]) -> dict:
    """A stable placeholder for each organization (listed ones first, then names declared and not listed) and each
    tenant (the file's rows first, by id and by the domain given for it, then tenants only an organization names)."""
    orgs = list(dict.fromkeys([o["org"] for o in census if o["org"]] +
                              [d["name"] for r in rows for d in r["organizations"]]))
    names = {n: f"{{{{org-{i}}}}}" for i, n in enumerate(orgs, 1)}
    tenants = list(dict.fromkeys([r["tenant"] for r in rows] + [o["tenant"] for o in census if o.get("tenant")]))
    names.update({t: f"{{{{tenant-{i}}}}}" for i, t in enumerate(tenants, 1)})
    names.update({r["given"]: names[r["tenant"]] for r in rows if r["given"] != r["tenant"]})
    return names


def scrub(obj: object, names: dict, seen: set) -> object:
    """Every estate value replaced in every string, in one longest-first pass per string; refuse (ScrubError) when one
    survives: a value read or given, an id, or a host name."""
    seen = {v for v in seen if isinstance(v, str) and len(v) >= 4 and v not in RESERVED}
    table = dict(names)
    for v in sorted(seen, key=len, reverse=True):
        table.setdefault(v, "{{estate}}")
    rx = re.compile("|".join(re.escape(k) for k in sorted(table, key=len, reverse=True))) if table else None
    left: list[str] = []

    def one(s: str) -> str:
        s = rx.sub(lambda m: table[m.group(0)], s) if rx else s
        bare = PLACEHOLDER.sub(" ", s)
        left.extend([v for v in seen if v in bare] + UUIDISH.findall(bare) + HOSTISH.findall(bare))
        return s

    def walk(o: object) -> object:
        if isinstance(o, dict):
            return {k: walk(v) for k, v in o.items()}
        if isinstance(o, list):
            return [walk(v) for v in o]
        return one(o) if isinstance(o, str) else o

    out = walk(obj)
    if left:
        raise ScrubError(f"refusing to write: {len(left)} estate value(s) survived the scrub")
    return out


def record(rows: list[dict], census: list[dict], findings: list[dict], errors: list[str], now: datetime, kind: str,
           seen: set) -> str:
    """The run's record: its exit, its census, each row's terms (owners named or blank, never their values) and every
    finding, each organization and tenant under its placeholder and every estate value replaced."""
    # A record a replayed run writes says so: it shows no read of an estate, and a reader takes it as none.
    doc = {**({"replay": True} if REPLAY is not None else {}),
           "captured": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "exit": exit_code(findings, errors),
           "credential": {"kind": kind}, "census": census_counts(census, rows), "run_errors": errors,
           "tenants": [{"tenant": r["tenant"], "consent": r["consent"],
                        "owners": {s: "named" if r["owners"][s] else "blank" for s in ("tenant", "provider")},
                        "declared": len(r["organizations"]),
                        "schedules": {k: (None if r["schedules"][k] is None else
                                          {"every_hours": r["schedules"][k]["every_hours"],
                                           "slack_hours": r["schedules"][k]["slack_hours"]}) for k in SCHEDULES}}
                       for r in rows],
           "organizations": [{"org": o["org"], "state": o["state"], "tenant": o.get("tenant")} for o in census],
           "findings": findings}
    clean = scrub(doc, placeholders(rows, census), seen | {os.environ.get("VCFA_HOST", "")} - {""})
    return json.dumps(clean, indent=2, ensure_ascii=False)


# ── printing ─────────────────────────────────────────────────────────────────────────────────────────────────────
def report_lines(rows: list[dict], findings: list[dict], errors: list[str]) -> list[str]:
    """The run on stdout: each row with its findings (its terms first, then its organizations), then the
    organizations outside every row, then what is wrong with the run as a whole."""
    out = []
    order = {"owners": 0, "consent": 1, "watch": 2, "leavers": 3, "row": 4, "organization": 5}

    def line(f: dict) -> str:
        who = f"{f['org']}: " if f.get("org") else ""
        return f"  {f['state'].upper():<8}{f['subject']:<14}{who}{f['detail']}"

    for r in rows:
        mine = sorted((f for f in findings if f["tenant"] == r["tenant"]), key=lambda f: order[f["subject"]])
        owners = ", ".join(f"{s} {r['owners'][s] or '(blank)'}" for s in ("tenant", "provider"))
        out += [f"\n{r['tenant']}  (consent: {r['consent']}; owners: {owners}; "
                f"{len(r['organizations'])} organization(s) declared)"] + [line(f) for f in mine]
    rest = [f for f in findings if f["tenant"] is None]
    if rest:
        out += ["\noutside every row"] + [line(f) for f in rest]
    for e in errors:
        out.append(f"\nREAD    {e}")
    return out


class _Parser(argparse.ArgumentParser):
    """argparse exits 2 on a usage error; the identity companions' contract gives a usage error 5."""

    def __init__(self, *args, **kwargs):  # an abbreviation never parses as a whole flag name
        kwargs.setdefault("allow_abbrev", False)
        super().__init__(*args, **kwargs)

    def error(self, message: str):  # type: ignore[override]
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        raise SystemExit(EXIT_USAGE)


def build_parser() -> _Parser:
    ap = _Parser(prog="inventory.py", description="The provider's tenants, consent, schedules and owners, held "
                 "against the estate. Read-only.")
    ap.add_argument("--redact", action="store_true", help="print with placeholders instead of your names")
    ap.add_argument("--replay", metavar="DIR",
                    help="answer every request from the recorded set in DIR (replay/inventory beside this script is "
                         "one): nothing is sent and no credential is read")
    return ap


def credential_given(env: dict, *names: str) -> bool:
    """Whether a credential is given: one of the named variables is set, or the run is replayed, where the credential
    is the placeholder _secret_file returns and nothing is read."""
    return REPLAY is not None or any(env.get(n) for n in names)


def replayed_inventory(env: dict) -> dict:
    """Under --replay, an INVENTORY_FILE the set itself names, as a relative path, is read from the set's folder: the
    set carries the inventory its answers were recorded against, wherever the run is started. A reader's own
    INVENTORY_FILE is read as given."""
    given = env.get("INVENTORY_FILE")
    if REPLAY is not None and given and REPLAY.env.get("INVENTORY_FILE") == given and not Path(given).is_absolute():
        return {**env, "INVENTORY_FILE": str(Path(REPLAY.directory) / given)}
    return env


def usage_problem(env: dict) -> str:
    """What is missing in the environment, or "": checked before any call, a usage error (exit 5)."""
    if not env.get("VCFA_HOST"):
        return "set VCFA_HOST"
    if not credential_given(env, "VCFA_PROVIDER_REFRESH_TOKEN_FILE", "VCFA_PROVIDER_BEARER_FILE"):
        return "set VCFA_PROVIDER_REFRESH_TOKEN_FILE or VCFA_PROVIDER_BEARER_FILE"
    if not env.get("INVENTORY_FILE"):
        return "set INVENTORY_FILE to the inventory the provider keeps (inventory.example.json shows its shape)"
    for k in (() if REPLAY is not None else ("VCFA_PROVIDER_REFRESH_TOKEN_FILE", "VCFA_PROVIDER_BEARER_FILE")) + \
            ("INVENTORY_FILE",):   # a replayed run opens no credential file; the inventory is read as given
        if env.get(k) and not (Path(env[k]).is_file() and os.access(env[k], os.R_OK)):
            return f"{k} names a file that cannot be read"
    return ""


def out_clash(out: Path, inventory: str, rows: list[dict], base: Path) -> str:
    """Why OUT may not be written, or "": it never names the inventory or a schedule's record, which the run would
    overwrite."""
    target = out.expanduser().resolve()
    if target == Path(inventory).expanduser().resolve():
        return "OUT names the inventory itself: point OUT at the run's record, inventory.json by default"
    for r in rows:
        for kind in SCHEDULES:
            if r["schedules"][kind] and record_path(r["schedules"][kind], base).resolve() == target:
                return f"OUT names the record the {kind} schedule writes: point OUT at this run's own record"
    return ""


def main(argv: list[str] | None = None) -> int:
    """The run, with two guards around it: a Python older than 3.9 is refused (exit 5) before anything is read, and an
    error the run did not expect exits 3, the code for a result not known, never 1, the code for drift."""
    if sys.version_info < (3, 9):  # noqa: UP036  the script is run by readers on their own Python
        print("inventory.py needs Python 3.9 or later", file=sys.stderr)
        return EXIT_USAGE
    try:
        return _run(sys.argv[1:] if argv is None else argv)
    except SystemExit as e:  # the parser's own exits: 5 on a usage error, 0 after --help
        return e.code if isinstance(e.code, int) else EXIT_USAGE
    except Exception as e:  # the last guard: whatever was not expected is not known, so exit 3
        print(f"the run stopped on an error it did not expect: {type(e).__name__}; nothing is known about what it had "
              "not read (exit 3)", file=sys.stderr)
        return EXIT_UNREAD
    finally:
        replay_stop()


def _run(argv: list[str]) -> int:
    a = build_parser().parse_args(argv)
    if a.replay:
        try:
            replay_start(a.replay)
        except (OSError, ValueError) as e:
            print(f"--replay {a.replay}: {e}; nothing was sent", file=sys.stderr)
            return EXIT_USAGE
    now = replay_now()   # the time now, or the time a replayed set was recorded at
    env = replayed_inventory(dict(os.environ))
    problem = usage_problem(env)
    if problem:
        print(f"{problem} (see the header); nothing was read", file=sys.stderr)
        return EXIT_USAGE
    inventory = env["INVENTORY_FILE"]
    base = Path(inventory).expanduser().resolve().parent
    out = Path(env.get("OUT") or ("inventory.replay.json" if REPLAY is not None else "inventory.json"))
    try:
        rows = load_inventory(inventory)
        clash = out_clash(out, inventory, rows, base)
        if clash:
            raise InventoryError(clash)
        rows = resolve_rows(rows)
    except (InventoryError, TenantError) as e:
        print(f"{e} (see the header); nothing was read", file=sys.stderr)
        return EXIT_USAGE
    except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
        print(f"READ FAILED: Entra's OpenID configuration, resolving a tenant's domain name: {_why(e)}; exit 3, no "
              "record written")
        return EXIT_UNREAD
    # A credential refused, or an organization list that cannot be read whole, ends the run before any judgment.
    try:
        api = Vcfa(env["VCFA_HOST"])
        listed = api.pages("/cloudapi/1.0.0/orgs")
    except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
        print(f"READ FAILED: VCF Automation, the organization list: {_why(e)}; exit 3, no record written")
        return EXIT_UNREAD
    if not listed:
        print("READ FAILED: the organization list came back empty, so the credential sees no organization; exit 3, "
              "no record written")
        return EXIT_UNREAD
    seen = {inventory, str(base)} | {r["given"] for r in rows} | {r["tenant"] for r in rows}
    seen |= {v for r in rows for v in r["owners"].values() if v}
    seen |= {d["id"] for r in rows for d in r["organizations"] if d.get("id")}
    for r in rows:
        for kind in SCHEDULES:
            if r["schedules"][kind]:
                seen |= {r["schedules"][kind]["record"], str(record_path(r["schedules"][kind], base))}
    census = read_census(api, listed, seen)
    findings, errors = judge(rows, census, now, base)
    code = exit_code(findings, errors)
    lines = report_lines(rows, findings, errors)
    names = placeholders(rows, census)
    try:
        print("\n".join(scrub(lines, names, seen | {env["VCFA_HOST"]}) if a.redact else lines))
    except ScrubError:
        print("refusing to print the redacted report: an estate value survived the placeholders", file=sys.stderr)
    counts = census_counts(census, rows)
    tail = (f"{counts['listed']} organization(s) listed, {counts['judged']} judged; "
            f"{sum(1 for f in findings if f['state'] == DRIFT)} drift, "
            f"{sum(1 for f in findings if f['state'] == UNREAD)} unread")
    try:
        text = record(rows, census, findings, errors, now, api.kind, seen)
    except ScrubError as e:   # the result above stands; the record does not, so a 0 is not on record
        code = code if code == EXIT_DRIFT else EXIT_UNREAD
        print(f"\n{tail}; {e}; no record written; exit {code}")
        return code
    with open(out, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(f"\n{tail}; exit {code}; record written with every estate value replaced")
    return code


if __name__ == "__main__":
    sys.exit(main())
