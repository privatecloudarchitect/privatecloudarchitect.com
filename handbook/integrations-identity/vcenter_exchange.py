#!/usr/bin/env python3
"""vcenter_exchange.py - a VCF SSO API client into vCenter, and who else signs in there. Read-only.

Under VCF single sign-on a vCenter does not take the broker's bearer as presented. The API client's API token is
traded at the broker for a bearer, the bearer is exchanged at vCenter for a SAML token that lives minutes, and the
SAML token opens a REST session (an Authorization header of the SIGN scheme) or a SOAP session (LoginByToken). This
script makes the exchange on each vCenter, opens and closes one session of each kind, and records who the session
is. With --sessions it reads each vCenter's session list and groups every session by the kind of principal and its
client agent, so an integration still signing in as a person's directory account shows up beside the machine
identities: every directory-account session from a client that is not interactive (anything but the vSphere Client,
unless INTERACTIVE_AGENTS says otherwise) is flagged, so a REST integration on a password is flagged as an SDK one is.
The census needs no API client: with VC_USER alone it reads the list as that account, so it can come first; with an
API client and no VC_USER it reads the list as the client's own session, so a scheduled census runs as a machine
identity rather than on a person's password. An identity that may read only its own sessions (a list holding nothing
but the census's own session by key, or every session under the census identity's own name) is reported as unable to
read the list, never as an empty one, and so is a list that does not hold the session that read it. The census reads vCenter only: NSX, VCF Operations, the SDDC
Manager API and VCF Automation are not read.

  1. the bearer as presented     GET  /api/vcenter/datacenter                      (refused, the expected answer)
  2. the exchange                POST /api/vcenter/authentication/token            (form; the access token alone)
  3. a REST session              POST /api/session   Authorization: SIGN token="<base64(gzip(assertion))>"
  4. a SOAP session              SessionManager.LoginByToken, the assertion in a WS-Security header
  5. --sessions                  SessionManager.sessionList, read as VC_USER or, without it, as the client's own
                                 session; the census's own session left out

It opens sessions and closes them, and changes no configuration. No token, assertion, password, session key or login
time is printed or recorded. No address is recorded, and none is printed unless --where asks.

--where (with --sessions, never with --redact) also prints, for each directory, local administrator and unplaced
session, the two UserSession properties that lead to its client: ipAddress, the client's identity ("It could be IP address, or pipe
name depended on client binding", in the vSphere Web Services API reference), and lastActiveTime, when the session
last ran a command. They are printed on your terminal only and never written to the record, so resolve each address
to a host and its owner there. The client agent alone does not name a product: vim-java, XML-WS and vAPI clients are
shared by many.

A session list holds only what is signed in at the moment of the read: a job that runs at 02:00 for ten minutes is
absent from a read at 10:00, so the reads are held to a coverage (--compare, below). vCenter's sign-in and sign-out
events (UserLoginSessionEvent, UserLogoutSessionEvent) reach back further, and are not read here: on the reference estate
(vCenter 9.1.1, X-205) a REST session left no sign-in event, only a sign-out event once it was closed, and the people
signing in at the vSphere Client had sign-ins from other agents (VMware vim-java, VcApiGw) within seconds of their
vSphereUI ones, so a census of those events would flag the people it exists to clear until that is settled.

--compare RECORD RECORD [...] reads two or more records of --sessions runs and lists the sessions (the directory account
or the local administrator, with its client agent) present in every record and those that came and went. Every name in
a record is a placeholder numbered afresh on each run, so the records are joined on keyed fingerprints instead: run each
census with FINGERPRINT_KEY_FILE set to the same secret, and each vCenter and directory principal carries a fingerprint
that is the same in every record made under it. It reads files only. It prints the coverage its records give (the hours
of day, UTC, at which a read was taken, the span from the first read to the last, and the largest gap between two reads)
and holds it to the coverage asked: --cover-hours N (default 24, every hour of day), --span-days N (default 7, a weekly
cycle) and --max-gap-minutes N (unset by default). Read at intervals shorter than the shortest session a job holds,
across your longest job cycle, and ask for exactly that.

--ack FILE (with --sessions, or with --compare) names the (directory account, client agent) pairs a person has decided
on, each until a date: a person who signs in with PowerCLI, confirmed as that person. An acknowledged pair is still
listed, as acknowledged; it never silences the same account from another agent, another account, or itself after its
date. The file is a JSON list of {"account": "DOMAIN\\name" as the census prints it, "agent": the client agent as it
prints it, "until": "YYYY-MM-DD", "note": optional}; anything else is refused. With --compare it needs
FINGERPRINT_KEY_FILE, to match each account to its fingerprint.

Env:  BROKER_HOST                 the identity broker that trades the API client's token for a bearer (not needed for a
                                  census as VC_USER alone); OPS_BROKER_HOST, then OPS_HOST, are read when it is unset,
                                  the names api_client.py and identity-model's census.py take
      BROKER_TENANT               the broker tenant: the realm's path segment, which an API client's vCenter session
                                  carries as its domain (default CUSTOMER; BROKER_REALM, its earlier name, is still
                                  read). When the client's own session is opened, the domain it reads is used. This is
                                  not vcenter-authorization's REALM_DOMAIN, which is the realm's name
      API_TOKEN_FILE              the API client's API token (mode 0600); API_TOKEN is read if it is unset, then
                                  OPS_API_TOKEN_FILE and OPS_API_TOKEN, with a note: the census then reads as whoever
                                  holds that token
      BEARER_FILE                 instead, a broker bearer you already hold (OPS_BEARER_FILE is read when it is unset)
      VC_HOSTS                    comma-separated vCenter FQDNs
      VC_USER, VC_PASSWORD_FILE   for --sessions as an account: one that may read the session list, user@domain (mode
                                  0600; VC_PASSWORD is read if it is unset); leave both unset to read as the API client
      DIRECTORY_DOMAINS           for --sessions, required: the directory domains as vCenter spells them,
                                  comma-separated, every directory whose accounts sign in to these vCenters. Unset,
                                  no directory session would be judged, so --sessions refuses to start without it
      OTHER_DOMAINS               for --sessions, optional: comma-separated domains you know are another identity
                                  provider's (authz.py's name and meaning). Their sessions are placed, as another
                                  provider's, and never flagged. A session in a domain that is none of these, the
                                  directory domains, LOCAL_DOMAIN and the broker tenant is NOT PLACED, and the read
                                  fails (exit 3): it could be a second directory's integration on a password. A domain
                                  in both lists is refused (exit 5)
      INTERACTIVE_AGENTS          for --sessions: the vSphere Client's agent, if yours reads another name (default
                                  vSphereUI, the only agent a person's session showed on the reference estate's lists).
                                  Never name a scripting client here (PowerCLI, an SDK): every account's sessions from it
                                  would pass unflagged. Acknowledge a person's pair with --ack instead
      LOCAL_DOMAIN                the vCenter's own SSO domain (default VSPHERE.LOCAL)
      FINGERPRINT_KEY_FILE        for --sessions records you will --compare: a secret of your own (mode 0600, kept off
                                  any shared disk), the same file on every run
      TLS_VERIFY=false            only on a self-signed lab CA
      OUT                         the record (default exchange.json; exchange.replay.json under --replay)
Use:  python3 vcenter_exchange.py [--sessions [--ack FILE]] [--redact]
      python3 vcenter_exchange.py --sessions --where      the address and last activity of each session, printed only
      python3 vcenter_exchange.py --compare A.json B.json C.json [--ack FILE] [--cover-hours N] [--span-days N]
                                  [--max-gap-minutes N]
      python3 vcenter_exchange.py --replay replay/vcenter_exchange [--sessions]   without an estate: every answer from
                                  the recorded set beside this script (its hosts are placeholders); nothing is sent and
                                  no credential is read, and a request the set holds no answer for is a read that
                                  failed (exit 3)
Exit, the first that applies, so a scheduler reads one state from one number:
      1 --sessions found a directory account signing in from a client that is not interactive, a pair not acknowledged
      2 a vCenter answered the API client's exchange, or one of its sessions, and did not take the client
      3 a read failed or is undetermined: a vCenter that did not answer the exchange or any other request, a session
        list not read (an empty one included: it always holds the census's own session, and one that does not hold
        it), a census identity that could read only its own sessions (by key, or every session under its own name), a
        session NOT PLACED (in a domain neither DIRECTORY_DOMAINS nor OTHER_DOMAINS names, so it was not judged), no
        vCenter read, a credential the broker did not trade, a request a --replay set holds no answer for, or an error
        the script did not expect
      4 --sessions found the local administrator signing in from a client that is not interactive
      0 every vCenter took the client through both sessions (when a client is given), and with --sessions every
        directory-account session is from an interactive client or acknowledged, and the local administrator signs in
        from none other
      5 a usage error (a missing or bad argument or environment variable, --sessions without DIRECTORY_DOMAINS, a
        domain in both DIRECTORY_DOMAINS and OTHER_DOMAINS, an --ack file that cannot be read or breaks its format, a
        credential file named that cannot be read or is empty, a --replay directory that cannot be read or holds no
        replay set, among them), or a Python older than 3.10; nothing is written
      A record refused because an estate value survived the scrub is not written, and never hides the run's result:
      the run's code stands when it is 1, 2, 3 or 4, and a run that found nothing exits 3 (the record a later --compare
      reads was not written).
      The exit reads vCenter's session lists at one moment: an integration that is not signed in then is not seen.
      --compare is the gate across reads. It checks first that each record read what it is compared on: a
      vCenter whose census failed in a record (a list not read, only the census's own session, a session not placed,
      no fingerprint) is not a read of that vCenter. The first that applies: 1 a directory
      account from a client that is not interactive in any record, a pair not acknowledged · 3 a vCenter not read in
      every record, a record holding no session census read on any vCenter, or the records short of the coverage asked
      (hours of day, span, largest gap) · 4 the local administrator from a client that is not interactive in any
      record · 0 none of these · 5 a usage error: fewer than two records, an option that is not --compare's, a record
      that cannot be read or parsed, one without fingerprints, records made under two keys, or --ack without
      FINGERPRINT_KEY_FILE or under another key. A record a --replay run wrote carries "replay": true, and --compare
      refuses it, alone or among live ones, before it compares anything: exit 3, naming the file (it is no read of an
      estate), with --replay or without
"""

from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import hmac
import http.cookiejar
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime

AGENT = "vcenter_exchange.py"
API_TOKEN_GRANT = "urn:custom:vcf:params:oauth:grant-type:api-token"
EXCHANGE = {"grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
            "requested_token_type": "urn:ietf:params:oauth:token-type:saml2"}
SOAPENV = "http://schemas.xmlsoap.org/soap/envelope/"
WSSE = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"
VIM = "urn:vim25"
# The client agents a person signs in from. Every other agent on a directory account or the local administrator is
# treated as an integration: a REST client (vAPI, curl, a product's own agent) on a password as much as an SDK. On the
# reference estate a person's session at the vSphere Client read vSphereUI and nothing else (X-142, one session).
INTERACTIVE_AGENTS = ("vSphereUI",)
# One exit contract for every identity companion: 0 nothing to act on, 3 a read failed or is undetermined, 5 a usage
# error; 1, 2 and 4 are this script's own (a directory account off the vSphere Client, the client refused, the local
# administrator off it).
EXIT_OK, EXIT_DIRECTORY, EXIT_REFUSED, EXIT_UNREAD, EXIT_ADMIN, EXIT_USAGE = 0, 1, 2, 3, 4, 5


def interactive_agents() -> set[str]:
    raw = os.environ.get("INTERACTIVE_AGENTS")
    names = [a.strip() for a in raw.split(",")] if raw else list(INTERACTIVE_AGENTS)
    return {a.lower() for a in names if a}


def interactive(agent: str, allowed: set[str] | None = None) -> bool:
    """Whether a session's agent (its name, version left off) is one a person signs in from."""
    return agent.lower() in (allowed if allowed is not None else interactive_agents())


def broker_tenant() -> str:
    """The broker tenant: the realm's path segment, and the domain an API client's vCenter session carries."""
    return os.environ.get("BROKER_TENANT") or os.environ.get("BROKER_REALM") or "CUSTOMER"


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


def broker_host() -> str:
    """The broker to trade at: BROKER_HOST, or the names api_client.py and census.py take (OPS_BROKER_HOST, OPS_HOST)."""
    return os.environ.get("BROKER_HOST") or os.environ.get("OPS_BROKER_HOST") or os.environ.get("OPS_HOST", "")


def api_token() -> str:
    """The API client's token: API_TOKEN[_FILE], or OPS_API_TOKEN[_FILE] as the other companions name it."""
    return _secret("API_TOKEN") or _secret("OPS_API_TOKEN")


def bearer_file() -> str:
    return os.environ.get("BEARER_FILE") or os.environ.get("OPS_BEARER_FILE", "")


def fingerprint_key() -> bytes | None:
    """The secret in FINGERPRINT_KEY_FILE, or None when it is unset."""
    path = os.environ.get("FINGERPRINT_KEY_FILE")
    if not path:
        return None
    if REPLAY is not None:  # a replayed run reads no credential: records made under it carry the placeholder's key
        return REPLAY_CREDENTIAL.encode()
    with open(path, "rb") as f:
        key = f.read().strip()
    if not key:
        raise ValueError("FINGERPRINT_KEY_FILE is empty")
    return key


def fingerprint(value: str, key: bytes) -> str:
    """A name's keyed fingerprint: the same under one key in every record, and nothing without the key."""
    return hmac.new(key, value.strip().lower().encode(), hashlib.sha256).hexdigest()[:16]


def key_check(key: bytes) -> str:
    """A short value that says which key fingerprinted a record, so records made under two keys are never joined."""
    return fingerprint("fingerprint key check", key)[:8]


NO_ANSWER: list[str] = []   # each request of this run that got no answer at all, in order: run() reads it per vCenter


def _call_name(req: urllib.request.Request) -> str:
    """A request as the record names it: its method and path, and for a SOAP request (every one a POST to /sdk) the
    operation its body holds. No query, header or body value."""
    path = urllib.parse.urlsplit(req.full_url).path
    op = re.search(r"<soapenv:Body><(\w+)", req.data.decode(errors="replace")) if isinstance(req.data, bytes) else None
    return f"{req.get_method()} {path}" + (f" {op.group(1)}" if op else "")


def _open(req: urllib.request.Request, opener=None, timeout: int = 60) -> tuple[int, bytes]:
    """(status, body) for any answer, a refusal included; (0, b"") when the host did not answer, and the request is
    added to NO_ANSWER, so a vCenter where one went unanswered is a read that did not happen (exit 3), never a pass."""
    try:
        r = (_urlopen(req, timeout=timeout, opener=opener) if opener else _urlopen(req, context=_ctx(), timeout=timeout))
        with r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read() or b""
    except (urllib.error.URLError, OSError):
        NO_ANSWER.append(_call_name(req))
        return 0, b""


def _form(url: str, fields: dict, headers: dict | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(url, data=urllib.parse.urlencode(fields).encode(), method="POST", headers={
        "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json", "User-Agent": AGENT,
        **(headers or {})})
    status, raw = _open(req)
    try:
        return status, json.loads(raw) if raw else {}
    except ValueError:
        return status, {}


def broker_bearer() -> str:
    """The bearer in BEARER_FILE, or the API client's API token traded at the broker for one."""
    if bearer_file():
        if REPLAY is not None:  # a replayed run reads no credential: nothing is sent
            return REPLAY_CREDENTIAL
        with open(bearer_file(), encoding="utf-8") as f:
            return f.read().strip().removeprefix("Bearer ").strip()
    status, answer = _form(f"https://{broker_host()}/acs/t/{broker_tenant()}/token",
                           {"grant_type": API_TOKEN_GRANT, "api_token": api_token()})
    if status != 200 or "access_token" not in answer:
        # a deleted API token is refused here, not with 401: HTTP 500 on 9.1.0 (2026-09-16), HTTP 400 for a deleted API
        # client token on 9.1.1 (X-153, X-190); check the token still exists, then its expiry, before the service
        raise RuntimeError(f"the broker did not trade the API token for a bearer (HTTP {status})")
    return answer["access_token"]


# ── the exchange, and the REST session it opens ──────────────────────────────────────────────────────────────────
def exchange(host: str, bearer: str) -> tuple[dict, str | None]:
    """Trade the broker bearer at vCenter for a SAML token; return what the answer says and the assertion, its XML
    declaration removed (LoginByToken refuses an assertion that starts with one)."""
    status, answer = _form(f"https://{host}/api/vcenter/authentication/token", {**EXCHANGE, "subject_token": bearer},
                           {"Authorization": f"Bearer {bearer}"})
    seen = {"status": status, "issued_token_type": answer.get("issued_token_type"),
            "token_type": answer.get("token_type"), "expires_in_s": answer.get("expires_in")}
    if status != 200 or not answer.get("access_token"):
        return seen, None
    raw = base64.b64decode(answer["access_token"]).decode()
    return seen, re.sub(r"^<\?xml[^>]*\?>\s*", "", raw)


def rest_session(host: str, assertion: str) -> dict:
    """A REST session from the SAML assertion: who it is, whether it reads the VM list, then closed."""
    sign = base64.b64encode(gzip.compress(assertion.encode())).decode()
    status, raw = _open(urllib.request.Request(f"https://{host}/api/session", method="POST", headers={
        "Authorization": f'SIGN token="{sign}"', "User-Agent": AGENT}))
    out = {"status": status}
    if status != 201:
        return out
    h = {"vmware-api-session-id": json.loads(raw), "User-Agent": AGENT}
    _, who = _open(urllib.request.Request(f"https://{host}/api/session", headers=h))
    out["user"] = (json.loads(who or b"{}") or {}).get("user")
    out["vm_list_status"], vms = _open(urllib.request.Request(f"https://{host}/api/vcenter/vm", headers=h))
    try:   # how many VMs the session sees, never which: vCenter filters the list by the session's permissions
        out["vm_count"] = len(json.loads(vms or b"[]")) if out["vm_list_status"] == 200 else None
    except ValueError:
        out["vm_count"] = None
    _open(urllib.request.Request(f"https://{host}/api/session", method="DELETE", headers=h))
    return out


# ── SOAP, standard library only ──────────────────────────────────────────────────────────────────────────────────
class Soap:
    """vCenter's vSphere API over SOAP, one session per instance, kept in its own cookie jar."""

    def __init__(self, host: str):
        self.url = f"https://{host}/sdk"
        self.opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=_ctx()),
                                                  urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        _, raw = _open(urllib.request.Request(f"https://{host}/sdk/vimServiceVersions.xml"), self.opener)
        m = re.search(r"<name>urn:vim25</name>\s*<version>([^<]+)</version>", raw.decode(errors="replace"))
        self.version = m.group(1) if m else "8.0.0.0"
        content = self.call(f'<RetrieveServiceContent xmlns="{VIM}"><_this type="ServiceInstance">ServiceInstance'
                            "</_this></RetrieveServiceContent>")
        rv = content.find(f"{{{VIM}}}returnval") if content is not None else None
        self.session_manager = rv.findtext(f"{{{VIM}}}sessionManager") if rv is not None else None
        self.property_collector = rv.findtext(f"{{{VIM}}}propertyCollector") if rv is not None else None

    def call(self, body: str, header: str = "") -> ET.Element | None:
        """The operation's response element, or None on a fault (the fault string kept in self.fault)."""
        env = (f'<?xml version="1.0" encoding="UTF-8"?><soapenv:Envelope xmlns:soapenv="{SOAPENV}" '
               'xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
               f"<soapenv:Header>{header}</soapenv:Header><soapenv:Body>{body}</soapenv:Body></soapenv:Envelope>")
        req = urllib.request.Request(self.url, data=env.encode(), method="POST", headers={
            "Content-Type": "text/xml; charset=utf-8", "SOAPAction": f"urn:vim25/{getattr(self, 'version', '8.0.0.0')}",
            "User-Agent": AGENT})
        status, raw = _open(req, self.opener)
        self.status, self.fault = status, None
        try:
            root = ET.fromstring(raw) if raw else None
        except ET.ParseError:
            root = None
        found = root.find(f"{{{SOAPENV}}}Body") if root is not None else None
        child = found[0] if found is not None and len(found) else None
        if child is None or child.tag == f"{{{SOAPENV}}}Fault":
            self.fault = (child.findtext("faultstring") if child is not None else None) or f"HTTP {status}"
            return None
        return child

    def login_by_token(self, assertion: str) -> str | None:
        r = self.call(f'<LoginByToken xmlns="{VIM}"><_this type="SessionManager">{self.session_manager}</_this>'
                      "</LoginByToken>", f'<wsse:Security xmlns:wsse="{WSSE}">{assertion}</wsse:Security>')
        return r.findtext(f"{{{VIM}}}returnval/{{{VIM}}}userName") if r is not None else None

    def login(self, user: str, password: str) -> str | None:
        esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")  # noqa: E731
        r = self.call(f'<Login xmlns="{VIM}"><_this type="SessionManager">{self.session_manager}</_this>'
                      f"<userName>{esc(user)}</userName><password>{esc(password)}</password></Login>")
        return r.findtext(f"{{{VIM}}}returnval/{{{VIM}}}userName") if r is not None else None

    def sessions(self, where: bool = False) -> tuple[list[dict], str | None]:
        """Every session's principal and client agent, and this session's key so the census can leave itself out.
        Keys stay in memory. With where, each session's ipAddress and lastActiveTime are read too, for the terminal
        only; login times are never read."""
        r = self.call(f'<RetrievePropertiesEx xmlns="{VIM}"><_this type="PropertyCollector">{self.property_collector}'
                      '</_this><specSet><propSet><type>SessionManager</type><all>false</all><pathSet>sessionList</pathSet>'
                      "<pathSet>currentSession</pathSet></propSet><objectSet><obj type=\"SessionManager\">"
                      f"{self.session_manager}</obj><skip>false</skip></objectSet></specSet><options/></RetrievePropertiesEx>")
        rows, mine = [], None
        if r is None:
            return rows, mine
        for prop in r.iter(f"{{{VIM}}}propSet"):
            name = prop.findtext(f"{{{VIM}}}name")
            val = prop.find(f"{{{VIM}}}val")
            if val is None:
                continue
            if name == "currentSession":
                mine = val.findtext(f"{{{VIM}}}key")
            elif name == "sessionList":
                for s in val.findall(f"{{{VIM}}}UserSession"):
                    row = {"key": s.findtext(f"{{{VIM}}}key"), "user": s.findtext(f"{{{VIM}}}userName") or "",
                           "agent": s.findtext(f"{{{VIM}}}userAgent") or ""}
                    if where:
                        row["address"] = s.findtext(f"{{{VIM}}}ipAddress") or ""
                        row["last_active"] = s.findtext(f"{{{VIM}}}lastActiveTime") or ""
                    rows.append(row)
        return rows, mine

    def logout(self) -> None:
        self.call(f'<Logout xmlns="{VIM}"><_this type="SessionManager">{self.session_manager}</_this></Logout>')


def soap_session(host: str, assertion: str) -> dict:
    s = Soap(host)
    user = s.login_by_token(assertion) if s.session_manager else None
    out = {"status": s.status, "user": user} if user else {"status": s.status, "fault": s.fault}
    if user:
        s.logout()
    return out


# ── the session census ───────────────────────────────────────────────────────────────────────────────────────────
def agent_of(raw: str) -> str:
    """The client agent without its version: a version such as 9.1.0.0 has the shape of an address, and the client's
    name is what tells an integration from a person (G-356 is the same trap from the other side)."""
    name = re.sub(r"\s*\bv?\d+(?:\.\d+)+\b", "", raw.split("/")[0])
    return " ".join(name.split())[:60] or "(none)"


NOT_PLACED = "not placed"


def other_domains() -> set[str]:
    """OTHER_DOMAINS, upper-cased: the domains the reader knows are another identity provider's (authz.py's name and
    meaning). Their sessions are placed, as another provider's, and never flagged."""
    return {d.strip().upper() for d in os.environ.get("OTHER_DOMAINS", "").split(",") if d.strip()}


def classify(principal: str, tenant: str, directories: set[str], local: str, others: set[str] = frozenset()) -> str:
    """The kind of principal a session holds, by how it signs in under VCF single sign-on; a domain none of these
    names is not placed."""
    domain, _, name = principal.rpartition("\\")
    d = domain.upper()
    if not d:
        return "no domain"             # never a directory account, nor another provider's: no domain names it
    if d == tenant.upper():
        return "api client"            # a VCF SSO API client's session reads <broker tenant>\<client id>
    if d in directories:
        return "directory"             # a person or an integration signing in through the broker
    if d == local.upper():
        if name.lower() == "administrator":
            return "local administrator"
        return "local, VCF integration account" if name.lower().startswith("svc-") else "local, other"
    if d in {o.upper() for o in others}:
        return "another provider"      # declared in OTHER_DOMAINS: placed, and never flagged
    return NOT_PLACED


def placement_failed(by_class: dict, declared: bool = True) -> bool:
    """Whether a vCenter's census left a session unplaced, a failed read (exit 3): a domain neither DIRECTORY_DOMAINS nor
    OTHER_DOMAINS names could be a second directory, or a misspelled one, whose integrations on a password nothing would
    flag. A record made before OTHER_DOMAINS (declared False) failed when no directory session stood beside another
    provider's."""
    if declared:
        return bool(by_class.get(NOT_PLACED))
    return not by_class.get("directory") and bool(by_class.get("another provider"))


def unplaced(record: dict) -> list[str]:
    """The vCenters whose census left a session unplaced."""
    declared = "other_domains_declared" in record
    return [v["vcenter"] for v in record.get("vcenters") or []
            if isinstance(v.get("sessions"), dict) and "by_class" in v["sessions"]
            and placement_failed(v["sessions"]["by_class"], declared)]


ACK_FIELDS = {"account", "agent", "until", "note"}


def load_acks(path: str) -> list[dict]:
    """The (directory account, client agent) pairs a person has decided on: a JSON list of {"account": "DOMAIN\\name" as
    the census prints it, "agent": the client agent as it prints it, "until": "YYYY-MM-DD", "note": optional}. Anything
    else is refused (ValueError), never half read: a silenced pair is one somebody wrote down, and an entry written
    loosely (a wildcard, an account without its domain, a field misspelled) silences nothing by accident."""
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, list):
        raise ValueError("--ack: the file must hold a JSON list")
    acks = []
    for i, a in enumerate(raw):
        if not isinstance(a, dict) or not all(isinstance(a.get(k), str) and a[k].strip() for k in ("account", "agent", "until")):
            raise ValueError(f"--ack: entry {i} needs account, agent and until")
        if set(a) - ACK_FIELDS or not isinstance(a.get("note", ""), str):
            raise ValueError(f"--ack: entry {i} holds a field other than account, agent, until and a note in words")
        domain, sep, name = a["account"].strip().rpartition("\\")
        if not sep or not domain.strip() or not name.strip():
            raise ValueError(f"--ack: entry {i}'s account must be DOMAIN\\name, as the census prints it")
        if any(c in a["account"] + a["agent"] for c in "*?"):
            raise ValueError(f"--ack: entry {i} holds a wildcard; an acknowledgement names one account and one agent")
        until = datetime.strptime(a["until"].strip(), "%Y-%m-%d").strftime("%Y-%m-%d")  # malformed: ValueError
        acks.append({"account": f"{domain.strip()}\\{name.strip()}", "agent": agent_of(a["agent"]), "until": until})
    return acks


def ack_for(acks: list[dict] | None, account: str, agent: str, fp: str | None = None, key: bytes | None = None) -> str | None:
    """The latest date to which the acknowledgements cover this exact (account, agent) pair, or None. With a key, the
    account may be given as its fingerprint (a record's), matched against each acknowledged account's own."""
    dates = [a["until"] for a in acks or [] if a["agent"].lower() == agent.lower()
             and ((fp is not None and key is not None and fingerprint(a["account"], key) == fp)
                  or (fp is None and a["account"].lower() == account.lower()))]
    return max(dates) if dates else None


def flagged_agents(d: dict, allowed: set[str] | None = None) -> list[str]:
    """A directory principal's client agents that are not interactive and not acknowledged. A record written before
    acknowledgements existed carries only `not_interactive`; its agents are judged again here."""
    if "not_interactive_agents" in d:
        bad = d["not_interactive_agents"]
    elif d.get("not_interactive"):
        bad = sorted(ag for ag in d.get("agents") or {} if not interactive(ag, allowed)) or sorted(d.get("agents") or {})
    else:
        bad = []
    acked = {x["agent"].lower() for x in d.get("acknowledged") or []}
    return [ag for ag in bad if ag.lower() not in acked]


def census(rows: list[dict], mine: str | None, tenant: str, directories: set[str], local: str,
           key: bytes | None = None, acks: list[dict] | None = None, today: str | None = None,
           others: set[str] = frozenset()) -> dict:
    """Sessions by class; the local administrator by agent; each directory principal with its agents, flagged when any
    agent is not interactive and that pair is not acknowledged until today or later, and with a keyed fingerprint when
    a key is given. No local principal is named, because a local account's name can carry estate values. A session's
    address and activity never reach the census. The domains of sessions not placed are counted under
    `_not_placed_domains`, which run() takes out before the record is made: printed on the terminal, never recorded."""
    by_class, admin, dirs, clients, loose = Counter(), Counter(), {}, set(), Counter()
    allowed = interactive_agents()
    today = today or replay_now().strftime("%Y-%m-%d")
    for r in rows:
        if r["key"] == mine:
            continue
        cls, agent = classify(r["user"], tenant, directories, local, others), agent_of(r["agent"])
        by_class[cls] += 1
        if cls == NOT_PLACED:
            loose[r["user"].rpartition("\\")[0]] += 1
        if cls == "local administrator":
            admin[agent] += 1
        elif cls == "directory":
            dirs.setdefault(r["user"], Counter())[agent] += 1
        elif cls == "api client":
            clients.add(r["user"])
    directory = []
    for p, a in sorted(dirs.items()):
        bad = sorted(ag for ag in a if not interactive(ag, allowed))
        d = {"principal": p, "agents": dict(sorted(a.items())), "not_interactive": bool(bad), "not_interactive_agents": bad,
             **({"fingerprint": fingerprint(p, key)} if key else {})}
        if acks is not None:
            covered = {ag: ack_for(acks, p, ag) for ag in bad}
            d["acknowledged"] = [{"agent": ag, "until": u} for ag, u in covered.items() if u and u >= today]
            expired = [{"agent": ag, "until": u} for ag, u in covered.items() if u and u < today]
            if expired:
                d["ack_expired"] = expired
        directory.append(d)
    out = {"sessions": sum(by_class.values()), "by_class": dict(sorted(by_class.items())),
           "local_administrator_by_agent": dict(sorted(admin.items())),
           "local_administrator_not_interactive": sum(n for ag, n in admin.items() if not interactive(ag, allowed)),
           "directory": directory, "api_clients": len(clients), "own_session_left_out": mine is not None}
    if loose:
        out["_not_placed_domains"] = dict(sorted(loose.items()))
    return out


def where_rows(host: str, rows: list[dict], mine: str | None, tenant: str, directories: set[str], local: str,
               others: set[str] = frozenset()) -> list[dict]:
    """Each directory, local administrator and unplaced session with its address and last activity, for the terminal
    only: the sessions whose owner the census asks you to name."""
    out = []
    for r in rows:
        cls = classify(r["user"], tenant, directories, local, others)
        if r["key"] != mine and cls in ("directory", "local administrator", NOT_PLACED):
            out.append({"vcenter": host, "class": cls, "user": r["user"], "agent": agent_of(r["agent"]),
                        "address": r.get("address") or "", "last_active": r.get("last_active") or ""})
    return sorted(out, key=lambda w: (w["class"], w["user"].lower(), w["agent"], w["last_active"]))


def _census_of(s: Soap, who: str, tenant: str, directories: set[str], local: str, key: bytes | None = None,
               where: list | None = None, acks: list[dict] | None = None, others: set[str] = frozenset()) -> dict:
    """The census from an open session. vCenter states no count for the list, so it is checked for the member it must
    hold, the session that read it, the way vcenter-authorization's authz.py checks it: a list without that session, or
    with no key for it, is not the whole list (exit 3). So is a list that holds nothing but the census identity's own
    sessions, by key or by its user name: an identity that may not read the others lists only its own (a directory
    account with no administrator role did, on the reference estate), and that list says nothing of anyone else, so it
    is reported as such and never as an estate where no one else is signed in. With a where list, the address and last
    activity of each directory and local administrator session go into that list, never into the census."""
    try:
        rows, mine = s.sessions(where=where is not None)
        if s.fault:
            return {"error": s.fault}
        if not rows:   # the list always holds the census's own session, so an empty one was not read: never zero sessions
            return {"error": "the session list came back empty, though it always holds this census's own session: not read"}
        if not mine or mine not in {r["key"] for r in rows}:
            return {"error": "the session list does not hold the session that read it, so it is not the whole list: not read"}
        if all(r["key"] == mine for r in rows):
            return {"error": "the session list held only this census's own session: this identity cannot read the others",
                    "only_own_session_visible": True, "census_identity": {"user": who}}
        me = {str(who or "").strip().lower()} | {str(r["user"]).strip().lower() for r in rows if r["key"] == mine}
        me.discard("")
        if all(r["key"] == mine or str(r["user"]).strip().lower() in me for r in rows):
            return {"error": (f"the session list held only this census identity's own sessions ({len(rows)}, under its "
                              "own name): an identity that may not read the others lists only its own, so it is not the "
                              "whole list"),
                    "only_own_session_visible": True, "census_identity": {"user": who}}
        if where is not None:
            where += where_rows(s.url.split("/")[2], rows, mine, tenant, directories, local, others)
        today = replay_now().strftime("%Y-%m-%d")
        return {**census(rows, mine, tenant, directories, local, key, acks, today, others), "census_identity": {"user": who}}
    finally:
        s.logout()


def read_sessions(host: str, user: str, password: str, tenant: str, directories: set[str], local: str,
                  key: bytes | None = None, where: list | None = None, acks: list[dict] | None = None,
                  others: set[str] = frozenset()) -> dict:
    """The census as an account that signs in with a password (VC_USER)."""
    s = Soap(host)
    who = s.login(user, password) if s.session_manager else None
    if not who:
        return {"error": s.fault or f"HTTP {s.status}"}
    return _census_of(s, who, tenant, directories, local, key, where, acks, others)


def read_sessions_as_client(host: str, assertion: str, tenant: str, directories: set[str], local: str,
                            key: bytes | None = None, where: list | None = None, acks: list[dict] | None = None,
                            others: set[str] = frozenset()) -> dict:
    """The census as the API client itself: its own SOAP session from a fresh SAML assertion."""
    s = Soap(host)
    who = s.login_by_token(assertion) if s.session_manager else None
    if not who:
        return {"error": s.fault or f"HTTP {s.status}"}
    return _census_of(s, who, tenant, directories, local, key, where, acks, others)


# ── the record ───────────────────────────────────────────────────────────────────────────────────────────────────
def summary(record: dict) -> dict:
    """The lines the run exists for: per vCenter, whether the client got both sessions and who it was; with
    --sessions, the census by class, every directory principal signing in from a client that is not interactive, and the
    local administrator's sessions from one."""
    vcs = record.get("vcenters") or []
    took = [v for v in vcs if (v.get("rest") or {}).get("status") == 201 and (v.get("soap") or {}).get("user")]
    sessions = [v for v in vcs if isinstance(v.get("sessions"), dict) and "by_class" in v["sessions"]]
    allowed = {a.lower() for a in record["interactive_agents"]} if record.get("interactive_agents") else None
    out = {
        "vcenters": len(vcs),
        "census_as": record.get("census_as"),
        "client_tried": sum(1 for v in vcs if "exchange" in v),
        "client_took_both_sessions": len(took),
        "census_only_own_session": sum(1 for v in vcs if isinstance(v.get("sessions"), dict)
                                       and v["sessions"].get("only_own_session_visible")),
        "bearer_as_presented": sorted({v.get("bearer_as_presented") for v in vcs}, key=str),
        "saml_lifetime_s": sorted({(v.get("exchange") or {}).get("expires_in_s") for v in vcs} - {None}),
        "session_users": sorted({u for v in vcs for u in ((v.get("rest") or {}).get("user"), (v.get("soap") or {}).get("user")) if u}),
        "sessions_read": len(sessions),
        "sessions_by_class": dict(sorted(sum((Counter(v["sessions"]["by_class"]) for v in sessions), Counter()).items())),
        "local_administrator_by_agent": dict(sorted(sum((Counter(v["sessions"]["local_administrator_by_agent"])
                                                         for v in sessions), Counter()).items())),
        "directory_principals": sorted({d["principal"] for v in sessions for d in v["sessions"]["directory"]}),
        "directory_not_interactive": sorted({d["principal"] for v in sessions for d in v["sessions"]["directory"]
                                             if flagged_agents(d, allowed)}),
        "local_administrator_not_interactive": sum(v["sessions"].get("local_administrator_not_interactive", 0)
                                                   for v in sessions),
    }
    if record.get("acks") is not None:   # only a run with --ack carries these, so an older record's summary is unchanged
        out["directory_acknowledged"] = sorted({d["principal"] for v in sessions for d in v["sessions"]["directory"]
                                                if d.get("acknowledged")})
    return out


def report(record: dict) -> list[str]:
    lines = []
    declared = "other_domains_declared" in record
    if record.get("census_as"):
        lines.append("Census read as " + ("the API client's own session" if record["census_as"] == "client"
                                          else "VC_USER, an account with a password"))
    for v in record["vcenters"]:
        ex, rest, soap = v.get("exchange") or {}, v.get("rest") or {}, v.get("soap") or {}
        lines.append(f"vCenter {v['vcenter']}")
        if "exchange" in v:
            lines.append(f"  the bearer as presented: HTTP {v['bearer_as_presented']}")
            lines.append(f"  exchange: HTTP {ex.get('status')}, {ex.get('issued_token_type') or 'no token'}"
                         + (f", {ex.get('token_type')}, lives {ex.get('expires_in_s')} s" if ex.get("status") == 200 else ""))
            lines.append(f"  REST session (SIGN): HTTP {rest.get('status')}" + (f", user {rest.get('user')}, VM list HTTP "
                                                                                 f"{rest.get('vm_list_status')}"
                                                                                 + (f" ({rest['vm_count']} VMs visible)"
                                                                                    if rest.get("vm_count") is not None else "")
                                                                                 if rest.get("user") else ""))
            lines.append("  SOAP session (LoginByToken): " + (f"user {soap['user']}" if soap.get("user") else f"refused: {soap.get('fault')}"))
        if v.get("no_answer"):
            lines.append(f"  NOT READ: no answer to {', '.join(v['no_answer'])}; a read that did not happen (exit 3)")
        s = v.get("sessions")
        if isinstance(s, dict) and "by_class" in s:
            lines.append(f"  sessions ({s['sessions']}, this census's own left out): "
                         + ", ".join(f"{k} {n}" for k, n in s["by_class"].items()))
            if declared and placement_failed(s["by_class"]):
                lines.append(f"    NOT PLACED: {s['by_class'][NOT_PLACED]} session(s) in a domain neither DIRECTORY_DOMAINS nor "
                             "OTHER_DOMAINS names: a second directory's integration on a password would sit there unflagged; "
                             "name each such domain in DIRECTORY_DOMAINS, or in OTHER_DOMAINS if it is another identity "
                             "provider's, and read again (exit 3)")
            elif not declared and placement_failed(s["by_class"], False):
                lines.append(f"    NOT PLACED: DIRECTORY_DOMAINS names nothing on this vCenter: {s['by_class']['another provider']} "
                             "session(s) read as another provider's and none as a directory account's, so every directory "
                             "session may be hiding there unflagged; set the domains as vCenter spells them and read again")
            lines += principal_lines(s, "    ")
        elif isinstance(s, dict):
            lines.append(f"  sessions not read: {s.get('error')}")
    sm = record["summary"]
    if sm["client_tried"]:
        lines.append(f"The client took both sessions on {sm['client_took_both_sessions']} of {sm['vcenters']} vCenter(s)")
    if sm["sessions_read"]:
        lines.append(f"Directory accounts signing in from a client that is not interactive: {len(sm['directory_not_interactive'])}"
                     + (" not acknowledged" if record.get("acks") is not None else ""))
        if record.get("acks") is not None:
            a = record["acks"]
            lines.append(f"Acknowledged: {len(sm.get('directory_acknowledged') or [])} account(s) on a pair a person decided on; "
                         f"{a['entries']} acknowledgement(s), {a['unmatched']} matching no pair read"
                         + (" (remove them from the --ack file when they are no longer needed)" if a["unmatched"] else ""))
        nothing = unplaced(record)
        if nothing:
            lines.append(f"FAILED READ: sessions not placed on {len(nothing)} vCenter(s), in a domain the census was not given, "
                         "so a directory session there was not judged; exit 3" if declared else
                         f"FAILED READ: DIRECTORY_DOMAINS named nothing on {len(nothing)} vCenter(s), so the census saw no directory "
                         "session it was asked to see there; exit 3")
        if sm["local_administrator_not_interactive"]:
            lines.append(f"WATCH: the local administrator holds {sm['local_administrator_not_interactive']} session(s) from "
                         "clients that are not interactive: an account in automated use is not a break-glass account")
    return lines


def principal_lines(s: dict, pad: str) -> list[str]:
    """The local administrator by agent, and each directory principal with its agents: a pair from a client that is not
    interactive is flagged unless it is acknowledged, and an acknowledgement past its date is said so."""
    lines = []
    if s["local_administrator_by_agent"]:
        lines.append(f"{pad}local administrator by agent: " + ", ".join(f"{a} {n}" for a, n in s["local_administrator_by_agent"].items()))
    for d in s["directory"]:
        acked = {x["agent"]: x["until"] for x in d.get("acknowledged") or []}
        expired = {x["agent"]: x["until"] for x in d.get("ack_expired") or []}
        flagged = flagged_agents(d)
        lines.append(f"{pad}directory {d['principal']}"
                     + (f" [fingerprint {d['fingerprint']}]" if d.get("fingerprint") else "") + ": "
                     + ", ".join(f"{a} {n}" + (f" (acknowledged until {acked[a]})" if a in acked else "")
                                 + (f" (acknowledgement ended {expired[a]})" if a in expired else "")
                                 for a, n in d["agents"].items())
                     + ("  SIGNS IN FROM A CLIENT THAT IS NOT INTERACTIVE" if flagged else ""))
    return lines


# ── the record contract: every estate value replaced, or nothing written ─────────────────────────────────────────
PRODUCT = {"customer", "vsphere.local", "administrator", "(none)"}
PATTERNS = [("id", re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")),
            ("host", re.compile(r"\b[a-z0-9-]+(?:\.[a-z0-9-]+)+\.[a-z]{2,}\b", re.I)),
            ("ip", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
            ("name", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)*\b"))]
NOT_SHAPED = {"issued_token_type", "token_type"}
PLACEHOLDER = re.compile(r"\{\{[a-z-]+-\d+\}\}")
OWN = re.compile(f"({PLACEHOLDER.pattern})")  # splits a text into what lies outside the placeholders and each one


def _strings(obj, field=None):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _strings(k, "__key__")
            yield from _strings(v, k)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v, field)
    elif isinstance(obj, str):
        yield field, obj


def estate_values(record: dict, given: list[tuple[str, str]]) -> dict[str, str]:
    """Each estate value mapped to its placeholder: the hosts, user and domains the reader gave, every session
    principal's name and domain, then anything shaped like an id, host, address or user."""
    table, count = {}, Counter()

    def add(value: str, kind: str) -> None:
        if value and len(value) >= 3 and value.lower() not in PRODUCT and value.lower() not in {k.lower() for k in table}:
            count[kind] += 1
            table[value] = f"{{{{{kind}-{count[kind]}}}}}"

    for value, kind in given:
        add(value, kind)
    for field, s in _strings(record):
        if field in ("user", "principal") or (field == "__key__" and "\\" in s):
            domain, _, name = s.rpartition("\\")
            add(domain, "domain")
            add(name, "client" if domain.upper() == broker_tenant().upper() else "name")
    for field, s in _strings(record):
        if field not in NOT_SHAPED:
            for kind, rx in PATTERNS:
                for m in rx.findall(s):
                    add(m, kind)
    return table


def one_pass(table: dict):
    """A text with every registered value replaced by its placeholder in one pass: one alternation, the longest value
    first, matched without regard to case where it is not part of a longer word, and only outside the placeholders
    already in the text. A value spelled like a placeholder (a principal named name-1) never rewrites the {{name-1}}
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
    """The record with every registered value replaced by its placeholder in one pass (one_pass), in its keys too: a
    session's principal can be a key."""
    if not table:
        return obj
    replace = one_pass(table)

    def walk(o):
        if isinstance(o, dict):
            return {walk(k): walk(v) for k, v in o.items()}
        if isinstance(o, list):
            return [walk(v) for v in o]
        return replace(o) if isinstance(o, str) else o

    return walk(obj)


def leaks(obj, table: dict) -> list[str]:
    """Every registered value, and the kind of anything shaped like an estate value, still in a scrubbed record, read
    outside the placeholders: a placeholder's own letters are not a surviving value."""
    found = []
    lower = {k.lower() for k in table}
    for field, s in _strings(obj):
        rest = PLACEHOLDER.sub(" ", s)
        found += [k for k in lower if re.search(r"(?<![A-Za-z0-9])" + re.escape(k) + r"(?![A-Za-z0-9])", rest, re.I)]
        if field not in NOT_SHAPED:
            found += [kind for kind, p in PATTERNS for m in p.findall(rest) if m.lower() not in PRODUCT]
    return found


# ── the run ──────────────────────────────────────────────────────────────────────────────────────────────────────
def directory_domains() -> set[str]:
    """DIRECTORY_DOMAINS, upper-cased: the domains whose sessions the census flags."""
    return {d.strip().upper() for d in os.environ.get("DIRECTORY_DOMAINS", "").split(",") if d.strip()}


def have_client() -> bool:
    return bool(bearer_file() or (broker_host() and api_token()))


def run(with_sessions: bool, where: list | None = None, key: bytes | None = None,
        acks: list[dict] | None = None, loose: dict | None = None) -> dict:
    """The exchange and the census on every vCenter named. With a where list, the address and last activity of each
    directory, local administrator and unplaced session go into that list and never into the record; with a key, each
    vCenter and directory principal in the record carries its keyed fingerprint; with acks, the pairs they cover are
    listed as acknowledged; with a loose dict, the domains of the sessions not placed go into it, by vCenter, and never
    into the record."""
    hosts = [h.strip() for h in os.environ.get("VC_HOSTS", "").split(",") if h.strip()]
    NO_ANSWER.clear()
    bearer = broker_bearer() if have_client() else None
    census_as = None if not with_sessions else ("password" if os.environ.get("VC_USER") else "client")
    tenant = broker_tenant()
    directories, others = directory_domains(), other_domains()
    local = os.environ.get("LOCAL_DOMAIN", "VSPHERE.LOCAL")
    sent = []
    if bearer:
        sent += ["POST /acs/t/<broker tenant>/token at the broker (unless BEARER_FILE)",
                 "per vCenter: POST /api/vcenter/authentication/token, REST and SOAP sessions opened and closed"]
    if census_as == "password":
        sent.append("per vCenter: a SOAP session as VC_USER, opened and closed")
    elif census_as == "client":
        sent.append("per vCenter: a third exchange, and a SOAP session as the client, opened and closed")
    record = {"captured": replay_now().strftime("%Y-%m-%dT%H:%M:%SZ"), "census_as": census_as,
              "sent": sent, "vcenters": []}
    if REPLAY is not None:   # a replayed run is never taken for a read of an estate: --compare refuses this record
        record["replay"] = True
    if with_sessions:
        record["interactive_agents"] = sorted(interactive_agents())
        record["other_domains_declared"] = len(others)   # a count, never the names; its presence marks the placement rule
    if key and with_sessions:
        record["fingerprint_key_check"] = key_check(key)
    if with_sessions and acks is not None:
        record["acks"] = {"entries": len(acks), "unmatched": 0}
    for host in hosts:
        row = {"vcenter": host, **({"fingerprint": fingerprint(host, key)} if key and with_sessions else {})}
        start = len(NO_ANSWER)
        if bearer:
            status, _ = _open(urllib.request.Request(f"https://{host}/api/vcenter/datacenter",
                                                     headers={"Authorization": f"Bearer {bearer}", "User-Agent": AGENT}))
            row["bearer_as_presented"] = status
            row["exchange"], assertion = exchange(host, bearer)
            row["rest"] = rest_session(host, assertion) if assertion else {"status": None}
            _, second = exchange(host, bearer)   # a second assertion for SOAP: one may not open two sessions
            row["soap"] = soap_session(host, second) if second else {"status": None}
            seen = ((row["soap"].get("user") or row["rest"].get("user") or "").rpartition("\\")[0])
            if seen and seen.upper() != tenant.upper():   # the client's own session names the broker tenant
                record["broker_tenant"] = {"set": tenant, "read_from_client_session": seen}
                tenant = seen
        if census_as == "password":
            row["sessions"] = read_sessions(host, os.environ["VC_USER"], _secret("VC_PASSWORD"), tenant, directories, local,
                                            key, where, acks, others)
        elif census_as == "client":
            _, third = exchange(host, bearer)
            row["sessions"] = (read_sessions_as_client(host, third, tenant, directories, local, key, where, acks, others)
                               if third else {"error": "the exchange for the census's own session failed"})
        domains = row["sessions"].pop("_not_placed_domains", None) if isinstance(row.get("sessions"), dict) else None
        if domains and loose is not None:
            loose[host] = domains
        if len(NO_ANSWER) > start:   # a request here got no answer: a read that did not happen on this vCenter
            row["no_answer"] = NO_ANSWER[start:]
        record["vcenters"].append(row)
    if "acks" in record:
        record["acks"]["unmatched"] = unmatched_acks(record, acks)
    record["summary"] = summary(record)
    record["exit"] = exit_code(record)
    return record


def unmatched_acks(record: dict, acks: list[dict]) -> int:
    """How many acknowledgements matched no pair the run read: counted, never named."""
    seen = {(d["principal"].lower(), ag.lower()) for v in record.get("vcenters") or [] if isinstance(v.get("sessions"), dict)
            for d in v["sessions"].get("directory") or [] for ag in d["agents"]}
    return sum(1 for a in acks if (a["account"].lower(), a["agent"].lower()) not in seen)


def took_client(v: dict) -> bool:
    """Whether a vCenter took the API client through both sessions."""
    return (v.get("rest") or {}).get("status") == 201 and bool((v.get("soap") or {}).get("user"))


def refused_client(v: dict) -> bool:
    """Whether a vCenter answered the client's exchange, or one of its sessions, and did not take the client: an answer
    that refused, never a request that got none (that is a read that did not happen, exit 3)."""
    ex, rest, soap = v.get("exchange") or {}, v.get("rest") or {}, v.get("soap") or {}
    if took_client(v) or not ex.get("status"):
        return False
    return (ex["status"] != 200 or (bool(rest.get("status")) and rest["status"] != 201)
            or (bool(soap.get("status")) and bool(soap.get("fault"))) or not v.get("no_answer"))


def exit_code(record: dict) -> int:
    """The first that applies: 1 a directory account signs in from a client that is not interactive, a pair nobody
    acknowledged; 2 a vCenter answered the client's exchange or one of its sessions and did not take the client; 3 a
    read failed or is undetermined (a vCenter that did not answer the exchange, or any other request, a session list
    not read, without the census's own session or holding only the census identity's own sessions, a session in a
    domain neither DIRECTORY_DOMAINS nor OTHER_DOMAINS names, or no vCenter at all); 4 the local administrator signs in
    from a client that is not interactive; else 0. A scheduler reads it."""
    vcs = record["vcenters"]
    tried = [v for v in vcs if "exchange" in v]
    refused = [v for v in tried if refused_client(v)]
    silent = [v for v in tried if v not in refused and not took_client(v)]   # a request without an answer: not known
    unread = [v for v in vcs if (isinstance(v.get("sessions"), dict) and "error" in v["sessions"]) or v.get("no_answer")]
    sm = record["summary"]
    if sm["directory_not_interactive"]:
        return EXIT_DIRECTORY
    if refused:
        return EXIT_REFUSED
    if silent or unread or unplaced(record) or not vcs:
        return EXIT_UNREAD
    return EXIT_ADMIN if sm["local_administrator_not_interactive"] else EXIT_OK


def loose_report(loose: dict, redact: bool) -> list[str]:
    """The domains of the sessions not placed, by vCenter: printed on the terminal, never recorded, and under --redact
    counted only, so a shared transcript names none of them."""
    if redact:
        n = len({d.upper() for doms in loose.values() for d in doms})
        return [f"NOT PLACED: {n} domain(s) the census was not given (names withheld under --redact; run without it, on "
                "your own terminal, to see them)"]
    lines = ["NOT PLACED, the domains the census was not given (printed here only, never recorded): name each in "
             "DIRECTORY_DOMAINS, or in OTHER_DOMAINS if it is another identity provider's"]
    for host, doms in loose.items():
        lines.append(f"  {host}: " + ", ".join(f"{d} {n}" for d, n in doms.items()))
    return lines


def where_report(where: list[dict]) -> list[str]:
    """The --where lines: printed on the terminal, never recorded."""
    if not where:
        return ["Where: no directory or local administrator session to place"]
    lines = ["Where each directory and local administrator session comes from (printed here only, never recorded; "
             "resolve each address to a host and its owner):"]
    for w in where:
        lines.append(f"  {w['vcenter']}  {w['class']} {w['user']} from {w['agent']}: address {w['address'] or 'none given'}, "
                     f"last active {w['last_active'] or 'not given'}")
    return lines


# ── --compare: sessions across dated records, held to the coverage asked ─────────────────────────────────────────
COVER_HOURS, SPAN_DAYS = 24, 7   # the defaults: a read in every hour of day, across a weekly cycle


class CompareError(ValueError):
    """A set of records that cannot be compared as given: the reason is printed and the exit is 5."""


def read_of(v: dict, declared: bool = True) -> bool:
    """Whether a record's row for one vCenter is a read of its sessions: a census that answered, read more than its own
    session, and placed every session it read, under a fingerprint. Anything else is not a read of that vCenter."""
    s = v.get("sessions")
    return bool(v.get("fingerprint")) and isinstance(s, dict) and "by_class" in s and "error" not in s \
        and not placement_failed(s["by_class"], declared)


def sessions_of(record: dict) -> dict[str, dict]:
    """Per vCenter fingerprint: its placeholder, its sessions as (who, agent) pairs, the directory principal by its
    fingerprint and the local administrator as itself, and which of those pairs are from a client that is not
    interactive, as the run that read them judged. Only the vCenters the record read are here."""
    out = {}
    allowed = {a.lower() for a in record["interactive_agents"]} if record.get("interactive_agents") else None
    declared = "other_domains_declared" in record
    for v in record.get("vcenters") or []:
        s = v.get("sessions")
        if not read_of(v, declared):
            continue   # a census that failed, read only itself or left a session unplaced here is not a read of it
        pairs, names, flagged = set(), {}, set()
        for d in s.get("directory") or []:
            if not d.get("fingerprint"):
                raise CompareError("a directory principal carries no fingerprint")
            names[d["fingerprint"]] = d["principal"]
            who = f"directory {d['fingerprint']}"
            pairs |= {(who, a) for a in d["agents"]}
            bad = d["not_interactive_agents"] if "not_interactive_agents" in d else (
                [a for a in d["agents"] if not interactive(a, allowed)] if d.get("not_interactive") else [])
            flagged |= {(who, a) for a in bad}
        for a in s.get("local_administrator_by_agent") or {}:
            pairs.add(("local administrator", a))
            if not interactive(a, allowed):
                flagged.add(("local administrator", a))
        out[v["fingerprint"]] = {"vcenter": v["vcenter"], "pairs": pairs, "names": names, "flagged": flagged}
    return out


def named(record: dict) -> dict[str, str]:
    """Every vCenter a record names under a fingerprint, read or not, with its placeholder."""
    return {v["fingerprint"]: v.get("vcenter") or "?" for v in record.get("vcenters") or [] if v.get("fingerprint")}


def coverage(captured: list[str], cover_hours: int = COVER_HOURS, span_days: float = SPAN_DAYS,
             max_gap: int | None = None) -> dict:
    """What the reads cover, as a quantity: the hours of day (UTC) at which a read was taken, the span from the first
    read to the last, and the largest gap between two reads; and each way that falls short of the coverage asked. A job
    that runs between two reads is absent from both, so a gate over reads is only as wide as what they cover."""
    when = sorted(datetime.fromisoformat(c.replace("Z", "+00:00")) for c in captured)
    hours = sorted({w.hour for w in when})
    span_h = (when[-1] - when[0]).total_seconds() / 3600 if when else 0.0
    gaps = [(b - a).total_seconds() / 60 for a, b in zip(when, when[1:], strict=False)]
    largest = round(max(gaps)) if gaps else None
    short = []
    if len(hours) < cover_hours:
        short.append(f"reads in {len(hours)} of the {cover_hours} hours of day asked")
    if span_h < span_days * 24:
        short.append(f"a span of {span_h / 24:.2f} day(s) where {span_days:g} were asked")
    if max_gap is not None and (largest is None or largest > max_gap):
        short.append(f"a largest gap of {largest} min where at most {max_gap} was asked")
    return {"hours_of_day_utc": hours, "span_hours": round(span_h, 2), "largest_gap_minutes": largest,
            "asked": {"cover_hours": cover_hours, "span_days": span_days, "max_gap_minutes": max_gap}, "short": short}


def compare(records: list[dict], cover_hours: int = COVER_HOURS, span_days: float = SPAN_DAYS, max_gap: int | None = None,
            acks: list[dict] | None = None, key: bytes | None = None, today: str | None = None) -> dict:
    """Which sessions are present in every record and which came and went, per vCenter; which pairs came from a client
    that is not interactive in any record, and whether a person acknowledged each directory pair; and the coverage the
    records give against the coverage asked. It first checks what each record read: a vCenter a record did not read is
    listed with the records that missed it, and a record that read no vCenter is listed too, so the comparison is never
    taken over reads that did not happen."""
    if len(records) < 2:
        raise CompareError("--compare needs two or more records")
    checks = {r.get("fingerprint_key_check") for r in records}
    if None in checks:
        raise CompareError("a record carries no fingerprints: run each --sessions census with FINGERPRINT_KEY_FILE set")
    if len(checks) > 1:
        raise CompareError("the records were fingerprinted under different keys; use one FINGERPRINT_KEY_FILE for all")
    if acks is not None and (key is None or key_check(key) not in checks):
        raise CompareError("--ack with --compare needs FINGERPRINT_KEY_FILE, the key the records were fingerprinted under")
    try:
        cover = coverage([r["captured"] for r in records], cover_hours, span_days, max_gap)
    except (KeyError, TypeError, ValueError):
        raise CompareError("a record carries no capture time it can be placed by") from None
    today = today or replay_now().strftime("%Y-%m-%d")
    ordered = sorted(records, key=lambda r: r["captured"])
    reads = [(r["captured"], sessions_of(r), named(r)) for r in ordered]
    vcenters = []
    every = sorted({fp for _, by_vc, names in reads for fp in (*by_vc, *names)})
    for fp in every:
        seen = [(when, by_vc[fp]) for when, by_vc, _ in reads if fp in by_vc]
        missed = [when for when, by_vc, _ in reads if fp not in by_vc]
        label = next((by_vc[fp]["vcenter"] for _, by_vc, _ in reversed(reads) if fp in by_vc), None) \
            or next(nm[fp] for _, _, nm in reversed(reads) if fp in nm)
        everyone = set.intersection(*(x["pairs"] for _, x in seen)) if seen else set()
        names = {k: v for _, x in seen for k, v in x["names"].items()}   # the latest record's placeholder wins
        came = sorted((set.union(*(x["pairs"] for _, x in seen)) - everyone)) if seen else []
        flagged = []
        for p in sorted(set().union(*(x["flagged"] for _, x in seen)) if seen else set()):
            f = {"pair": p, "seen": [w for w, x in seen if p in x["flagged"]]}
            if p[0].startswith("directory "):
                until = ack_for(acks, "", p[1], fp=p[0].split(" ", 1)[1], key=key)
                if until and until >= today:
                    f["acknowledged_until"] = until
                elif until:
                    f["ack_expired"] = until
            flagged.append(f)
        vcenters.append({"fingerprint": fp, "vcenter": label, "read_in": len(seen), "not_read_in": missed,
                         "in_every_record": sorted(everyone),
                         "came_and_went": [{"pair": p, "seen": [w for w, x in seen if p in x["pairs"]]} for p in came],
                         "not_interactive": flagged, "names": names})
    days = sorted({when[:10] for when, by_vc, _ in reads if by_vc})
    return {"records": len(records), "captured": [w for w, _, _ in reads], "days": days, "vcenters": vcenters,
            "records_reading_nothing": [w for w, by_vc, _ in reads if not by_vc], "coverage": cover,
            "acks": None if acks is None else len(acks), "today": today}


def _who(pair: tuple[str, str], names: dict) -> str:
    kind, agent = pair
    if kind.startswith("directory "):
        fp = kind.split(" ", 1)[1]
        return f"directory {names.get(fp, '?')} [fingerprint {fp}] from {agent}"
    return f"{kind} from {agent}"


def compare_report(result: dict) -> list[str]:
    cv = result["coverage"]
    asked = cv["asked"]
    lines = [f"Compared {result['records']} session records on {len(result['days'])} day(s): {', '.join(result['days'])}",
             f"Coverage: reads in {len(cv['hours_of_day_utc'])} of 24 hours of day (UTC: "
             + (", ".join(f"{h:02d}" for h in cv["hours_of_day_utc"]) or "none") + f"); a span of {cv['span_hours']} h "
             f"({cv['span_hours'] / 24:.2f} days) from the first read to the last; the largest gap between two reads "
             + (f"{cv['largest_gap_minutes']} min" if cv["largest_gap_minutes"] is not None else "none"),
             f"Asked: reads in {asked['cover_hours']} hours of day, a span of {asked['span_days']:g} days, "
             + (f"no gap over {asked['max_gap_minutes']} min" if asked["max_gap_minutes"] is not None else "no gap limit")]
    if cv["short"]:
        lines.append("COVERAGE SHORT: " + "; ".join(cv["short"]) + ". A job that runs between two reads is absent from "
                     "both, so what these records do not show is not known; that is exit 3, unless a finding comes first")
    for when in result.get("records_reading_nothing") or []:
        lines.append(f"NOT READ: the record of {when} holds no session census read on any vCenter, so it adds nothing to "
                     "compare; that is exit 3, unless a finding comes first")
    unread = [v for v in result["vcenters"] if v["read_in"] < result["records"]]
    if unread:
        lines.append(f"NOT READ: {len(unread)} vCenter(s) missing a read in at least one record (a census that failed "
                     "there, read only its own session, or left a session unplaced there is not a read of "
                     "it), so what came and went on them is not known; that is exit 3, unless a finding comes first")
    for v in result["vcenters"]:
        lines.append(f"vCenter {v['vcenter']} [fingerprint {v['fingerprint']}], read in {v['read_in']} of "
                     f"{result['records']} record(s)"
                     + (f"; not read in the record(s) of {', '.join(v.get('not_read_in') or [])}" if v.get("not_read_in") else ""))
        lines.append("  in every record: " + ("; ".join(_who(p, v["names"]) for p in v["in_every_record"]) or "none"))
        if not v["came_and_went"]:
            lines.append("  came and went: none")
        for c in v["came_and_went"]:
            lines.append(f"  came and went: {_who(c['pair'], v['names'])}, seen {', '.join(w[:10] for w in c['seen'])}")
        for f in v.get("not_interactive") or []:
            if not f["pair"][0].startswith("directory "):
                state = "a break-glass account in automated use"
            elif f.get("acknowledged_until"):
                state = f"acknowledged until {f['acknowledged_until']}"
            else:
                state = "NOT ACKNOWLEDGED" + (f" (its acknowledgement ended {f['ack_expired']})" if f.get("ack_expired") else "")
            lines.append(f"  from a client that is not interactive: {_who(f['pair'], v['names'])}, seen in "
                         f"{len(f['seen'])} record(s): {state}")
    return lines


def compare_exit(result: dict) -> int:
    """The first that applies: 1 a directory account from a client that is not interactive in any record, a pair not
    acknowledged; 3 a vCenter not read in every record, a record that read none, or the records short of the coverage
    asked; 4 the local administrator from a client that is not interactive in any record; else 0."""
    flagged = [f for v in result["vcenters"] for f in v.get("not_interactive") or []]
    if any(f["pair"][0].startswith("directory ") and not f.get("acknowledged_until") for f in flagged):
        return EXIT_DIRECTORY
    whole = all(v["read_in"] == result["records"] for v in result["vcenters"])
    if not whole or result.get("records_reading_nothing") or not result["vcenters"] or result["coverage"]["short"]:
        return EXIT_UNREAD
    return EXIT_ADMIN if any(f["pair"][0] == "local administrator" for f in flagged) else EXIT_OK


def compare_main(paths: list[str], cover_hours: int = COVER_HOURS, span_days: float = SPAN_DAYS,
                 max_gap: int | None = None, ack_path: str | None = None) -> int:
    records = []
    for path in paths:
        try:
            with open(path, encoding="utf-8") as f:
                records.append(json.load(f))
        except (OSError, ValueError) as e:
            print(f"could not read {path}: {type(e).__name__}", file=sys.stderr)
            return EXIT_USAGE
    replayed = [path for path, r in zip(paths, records, strict=True) if isinstance(r, dict) and r.get("replay")]
    if replayed:   # recorded answers, not an estate: comparing them would pass a coverage nobody read
        print(f"{', '.join(replayed)}: a --replay run's record (\"replay\": true) is no read of an estate; nothing was "
              f"compared (exit {EXIT_UNREAD})", file=sys.stderr)
        return EXIT_UNREAD
    acks = key = None
    if ack_path:
        try:
            acks, key = load_acks(ack_path), fingerprint_key()
        except (OSError, ValueError) as e:
            print(f"--ack {ack_path}: {type(e).__name__}: {str(e)[:200]}", file=sys.stderr)
            return EXIT_USAGE
    try:
        result = compare(records, cover_hours, span_days, max_gap, acks, key)
    except CompareError as e:
        print(f"cannot compare: {e}", file=sys.stderr)
        return EXIT_USAGE
    print("\n".join(compare_report(result)))
    code = compare_exit(result)
    print(f"\nexit {code}")
    return code


def given_values() -> list[tuple[str, str]]:
    out = [(h.strip(), "host") for h in os.environ.get("VC_HOSTS", "").split(",") if h.strip()]
    out += [(os.environ.get(k, ""), "host") for k in ("BROKER_HOST", "OPS_BROKER_HOST", "OPS_HOST")]
    out += [(os.environ.get("VC_USER", ""), "name")]
    out += [(d.strip(), "domain") for v in ("DIRECTORY_DOMAINS", "OTHER_DOMAINS")
            for d in os.environ.get(v, "").split(",") if d.strip()]
    return [(v, k) for v, k in out if v]


def _bounded(kind, low, high, what: str):
    def parse(text: str):
        try:
            value = kind(text)
        except ValueError:
            raise argparse.ArgumentTypeError(f"{what}: {text!r} is not a number") from None
        if not low <= value <= high:
            raise argparse.ArgumentTypeError(f"{what}: {text} is outside {low} to {high}")
        return value
    return parse


_hours = _bounded(int, 1, 24, "--cover-hours")
_span = _bounded(float, 0, 3660, "--span-days")
_minutes = _bounded(int, 1, 527040, "--max-gap-minutes")
SECRET_FILES = ("VC_PASSWORD_FILE", "API_TOKEN_FILE", "OPS_API_TOKEN_FILE", "BEARER_FILE", "OPS_BEARER_FILE",
                "FINGERPRINT_KEY_FILE")


def unusable_secret_files() -> list[str]:
    """The *_FILE variables set to a file that cannot be read or holds nothing: a usage error, found before any call.
    A replayed run opens none of them: it reads no credential."""
    if REPLAY is not None:
        return []
    bad = []
    for name in SECRET_FILES:
        path = os.environ.get(name)
        if not path:
            continue
        try:
            with open(path, "rb") as f:
                if not f.read().strip():
                    bad.append(name)
        except OSError:
            bad.append(name)
    return bad


class _Parser(argparse.ArgumentParser):
    """argparse exits 2 on a usage error, the code this script gives a refused client; it exits 5 here."""

    def __init__(self, *args, **kwargs):  # an abbreviation never parses as a whole flag name
        kwargs.setdefault("allow_abbrev", False)
        super().__init__(*args, **kwargs)

    def error(self, message: str):
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        raise SystemExit(EXIT_USAGE)


def main(argv: list[str] | None = None) -> int:
    """The run, with two guards around it: a Python older than 3.10 is refused (exit 5) before anything is read, and
    an error the script did not expect exits 3, the code for a read that failed, never 1, the code for a finding."""
    if sys.version_info < (3, 10):  # noqa: UP036  the script is run by readers on their own Python
        print("vcenter_exchange.py needs Python 3.10 or later", file=sys.stderr)
        return EXIT_USAGE
    try:
        return _run(argv)
    except Exception as e:  # the last guard: whatever was not expected is not known, so exit 3
        print(f"the run stopped on an error it did not expect: {type(e).__name__}: {str(e)[:160]}; nothing is known "
              "about what it had not read (exit 3)", file=sys.stderr)
        return EXIT_UNREAD
    finally:
        replay_stop()


def _run(argv: list[str] | None = None) -> int:
    ap = _Parser(description="A VCF SSO API client into vCenter, and who else signs in there. Read-only.")
    ap.add_argument("--sessions", action="store_true",
                    help="read each vCenter's session list: as VC_USER when it is set, otherwise as the API client")
    ap.add_argument("--redact", action="store_true", help="print with placeholders instead of your names")
    ap.add_argument("--where", action="store_true",
                    help="with --sessions: print each directory and local administrator session's address and last "
                         "activity, on the terminal only; never with --redact")
    ap.add_argument("--ack", metavar="FILE",
                    help="with --sessions or --compare: the (directory account, client agent) pairs a person has decided "
                         "on, each until a date: a JSON list of {account, agent, until, note}")
    ap.add_argument("--compare", nargs="+", metavar="RECORD",
                    help="compare two or more --sessions records, held to the coverage asked; reads files only")
    ap.add_argument("--cover-hours", type=_hours, metavar="N",
                    help=f"with --compare: the hours of day (UTC) that must each hold a read (default {COVER_HOURS})")
    ap.add_argument("--span-days", type=_span, metavar="N",
                    help=f"with --compare: the days the reads must span, first to last (default {SPAN_DAYS})")
    ap.add_argument("--max-gap-minutes", type=_minutes, metavar="N",
                    help="with --compare: the longest gap allowed between two reads (default: none asked)")
    ap.add_argument("--replay", metavar="DIR",
                    help="answer every request from the recorded set in DIR (replay/vcenter_exchange beside this script "
                         "is one): nothing is sent and no credential is read")
    a = ap.parse_args(argv)
    if a.replay:
        try:
            replay_start(a.replay)
        except (OSError, ValueError) as e:
            print(f"--replay {a.replay}: {e}; nothing was sent", file=sys.stderr)
            return EXIT_USAGE
    compare_only = [o for o, v in (("--cover-hours", a.cover_hours), ("--span-days", a.span_days),
                                   ("--max-gap-minutes", a.max_gap_minutes)) if v is not None]
    if a.compare:
        if a.sessions or a.where or a.redact:
            print("--compare reads records only; it takes --ack, --cover-hours, --span-days and --max-gap-minutes",
                  file=sys.stderr)
            return EXIT_USAGE
        return compare_main(a.compare, COVER_HOURS if a.cover_hours is None else a.cover_hours,
                            SPAN_DAYS if a.span_days is None else a.span_days, a.max_gap_minutes, a.ack)
    if compare_only:
        print(f"{', '.join(compare_only)} hold --compare to a coverage, so they need --compare", file=sys.stderr)
        return EXIT_USAGE
    if a.ack and not a.sessions:
        print("--ack judges the session census, so it needs --sessions", file=sys.stderr)
        return EXIT_USAGE
    try:
        acks = load_acks(a.ack) if a.ack else None
    except (OSError, ValueError) as e:
        print(f"--ack {a.ack}: {type(e).__name__}: {str(e)[:200]}", file=sys.stderr)
        return EXIT_USAGE
    bad = unusable_secret_files()
    if bad:
        print(f"{', '.join(bad)}: the file named cannot be read, or is empty", file=sys.stderr)
        return EXIT_USAGE
    if os.environ.get("INTERACTIVE_AGENTS"):
        print(f"note: INTERACTIVE_AGENTS names {', '.join(sorted(interactive_agents()))} as the clients a person signs in "
              "from, so every account's sessions from them pass unflagged; name only the vSphere Client's agent there, "
              "and acknowledge a person on PowerCLI or a script by its pair with --ack", file=sys.stderr)
    if a.where and a.redact:
        print("--where prints addresses, which --redact exists to hide; run them apart. --where writes nothing of them "
              "to the record either way", file=sys.stderr)
        return EXIT_USAGE
    if a.where and not a.sessions:
        print("--where reads the session list, so it needs --sessions", file=sys.stderr)
        return EXIT_USAGE
    if not os.environ.get("VC_HOSTS"):
        print("VC_HOSTS is required", file=sys.stderr)
        return EXIT_USAGE
    if not a.sessions and not have_client():
        print("the exchange needs the API client's credential (BROKER_HOST with API_TOKEN_FILE, or BEARER_FILE; "
              "OPS_BROKER_HOST or OPS_HOST, OPS_API_TOKEN_FILE and OPS_BEARER_FILE are read in their place); "
              "--sessions alone needs only VC_USER", file=sys.stderr)
        return EXIT_USAGE
    if have_client() and not bearer_file() and not _secret("API_TOKEN"):
        print("note: API_TOKEN_FILE is unset; reading OPS_API_TOKEN_FILE, so the exchange and a census without VC_USER "
              "run as whoever holds that token", file=sys.stderr)
    if a.sessions and os.environ.get("VC_USER") and not _secret("VC_PASSWORD"):
        print("--sessions as VC_USER needs VC_PASSWORD_FILE", file=sys.stderr)
        return EXIT_USAGE
    if os.environ.get("REALM_DOMAIN") and not (os.environ.get("BROKER_TENANT") or os.environ.get("BROKER_REALM")):
        print("note: REALM_DOMAIN is not read here. It is the realm's name, which vcenter-authorization's authz.py takes; "
              "an API client's session carries the broker tenant instead (BROKER_TENANT, default CUSTOMER)", file=sys.stderr)
    if a.sessions and not directory_domains():
        print("--sessions needs DIRECTORY_DOMAINS, the directory domains as vCenter spells them: without them no "
              "directory session would be judged, so a census of nothing would pass", file=sys.stderr)
        return EXIT_USAGE
    both = sorted(directory_domains() & other_domains())
    if a.sessions and both:
        print(f"DIRECTORY_DOMAINS and OTHER_DOMAINS both name {', '.join(both)}: a domain is your directory's, whose "
              "sessions the census judges, or another identity provider's, which it never flags; name it in one",
              file=sys.stderr)
        return EXIT_USAGE
    if a.sessions and not os.environ.get("VC_USER") and not have_client():
        print("--sessions needs VC_USER and VC_PASSWORD_FILE, or the API client's credential to read as the client",
              file=sys.stderr)
        return EXIT_USAGE
    where: list | None = [] if a.where else None
    loose: dict = {}
    try:
        key = fingerprint_key() if a.sessions else None
    except (OSError, ValueError) as e:
        print(f"FINGERPRINT_KEY_FILE could not be read: {type(e).__name__} {e}".rstrip(), file=sys.stderr)
        return EXIT_USAGE
    try:
        record = run(a.sessions, where, key, acks, loose)
    except (RuntimeError, urllib.error.URLError, OSError, ValueError) as e:
        print(f"could not start: {e}", file=sys.stderr)
        return EXIT_UNREAD
    table = estate_values(record, given_values())
    clean = scrub(record, table)
    clean["summary"] = summary(clean)
    left = leaks(clean, table)
    out = os.environ.get("OUT") or ("exchange.replay.json" if REPLAY is not None else "exchange.json")
    if not (left and a.redact):  # a redacted print with a surviving value would print that value
        print("\n".join(report(clean if a.redact else record)))
    if where is not None:
        print("\n".join(where_report(where)))
    if loose:
        print("\n".join(loose_report(loose, a.redact)))
    if left:
        code = record["exit"] if record["exit"] in (EXIT_DIRECTORY, EXIT_REFUSED, EXIT_UNREAD, EXIT_ADMIN) else EXIT_UNREAD
        why = ("the run's own code stands" if code == record["exit"]
               else "the run found nothing to act on, and the record a later --compare reads was not written")
        print(f"refusing to write {out}: {len(left)} estate value(s) survived the scrub; {out} not written; exit {code}: "
              f"{why}", file=sys.stderr)
        return code
    with open(out, "w", encoding="utf-8") as f:
        f.write(json.dumps(clean, indent=1, ensure_ascii=False) + "\n")
    print(f"\n{out} written with every estate value replaced; exit {record['exit']}")
    return record["exit"]


if __name__ == "__main__":
    sys.exit(main())
