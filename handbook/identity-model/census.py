#!/usr/bin/env python3
"""census.py - read a VCF 9.1 estate's identity model from the planes that own it. Read-only by default.

The model: an identity broker holds one single sign-on realm; the realm covers whole VCF instances; one identity
provider sits under the realm, with its directories under it; VCF Automation's organizations each choose their own
way in. This script reads each piece from the API that answers for it, so every line it prints can be checked
against that API, and prints the lines a reader should be able to explain: which brokers exist and of which kind,
which realm covers which instances, the provider's type and protocol, each directory's protocol and port, the two
ways a vCenter grant can spell a principal (a bound directory's domain, which a broker session carries, and the
realm's name, which a grant accepts and, behind an AD/LDAP provider, applied to nobody), whether an emergency client exists, the API clients and
their tokens' lifetimes with each token's runway (its days left, and when it was last exchanged for a bearer), and how
each organization signs in.

--orgs-only reads VCF Automation alone, as the provider: each organization's ways in, on VCFA_HOST and a provider
credential, with no VCF Operations credential. A VCF Automation provider administrator can run it without the fleet's
most privileged token. It reads no broker, so an OIDC issuer is called the broker only when its host is in
BROKER_HOSTS, which it requires; an organization signing in through VCF single sign-on whose issuer they do not name
fails the read, because its issuer is a broker by definition.

Fleet IAM, through VCF Operations (/suite-api/api/fleet-management/iam):
  GET  /vidbs                                 the brokers, instance or embedded. Read here, never from the fleet
                                              inventory: an embedded broker lives inside a management vCenter and
                                              has no inventory row of its own
  GET  /ssorealms, /ssorealms/{id}            each realm, the instances and components it covers, its issues
  GET  /identity-providers/{id}               the realm's provider: protocol, type, provisioning, and each
                                              directory's domain controllers with protocol and port
  GET  /identity-providers/{id}/ldap-directories   each directory's sync state
  POST /ssorealms/{id}/api-clients/query, /ssorealms/{id}/api-tokens/query   API clients, roles, token lifetimes
  GET  /ssorealms/{id}/emergency-clients, /ssorealms/{id}/oauth-apps
  POST /components/auth-sources/query         which component signs in through which realm
  GET  /settings, /roles                      the fleet's token lifetimes; the VCF roles, built in or custom
VCF Automation, as the provider (optional): each organization's LDAP, OIDC and SAML settings.
vCenter (optional): each vCenter's identity provider and the broker it points at, and each Supervisor's providers
with the host of each one's issuer (read from the provider's own record: the Supervisor's list carries no issuer).

The POSTs to .../query are searches and change nothing. vCenter is read under a session the script opens and closes.
--egress-metadata-url URL sends one request per broker that is not a read: POST /saml-metadata/validate asks the
broker to fetch that SAML metadata URL itself, so 200 proves the broker reaches the identity provider and a failure
says it does not. The contract describes the call as validating and parsing metadata; the script reads the brokers,
realms and providers again after it and records any difference, so the run itself shows whether anything changed.

Secrets die where they arrive. The API returns some in clear (an emergency client's access token, a provider's
client secret and bind password, an API token's value); the reader deletes each from the body before any function
sees it, and the record keeps only the fields the allow-lists below name.

Env:  OPS_HOST                 VCF Operations FQDN (required)
      OPS_API_TOKEN_FILE       an API token from VCF Operations (mode 0600; OPS_API_TOKEN is read if it is unset, then
                               API_TOKEN_FILE and API_TOKEN, the names integrations-identity's vcenter_exchange.py
                               takes), traded at the broker for a bearer: OPS_BROKER_HOST (BROKER_HOST is read when it
                               is unset; default OPS_HOST), BROKER_TENANT
                               (the broker tenant, the realm's path segment at the broker; default CUSTOMER; it was
                               OPS_REALM, still read when BROKER_TENANT is unset, with a notice)
      OPS_BEARER_FILE          instead, a bearer you already hold (it lives an hour unless the fleet says otherwise)
      VCFA_HOST                optional, with VCFA_PROVIDER_BEARER_FILE (a provider bearer you already hold) or
                               VCFA_PROVIDER_REFRESH_TOKEN_FILE (a provider API token, traded at /oauth/provider/token);
                               with --orgs-only, these alone are required
      BROKER_HOSTS             with --orgs-only, required, comma-separated: every broker's host (the instance broker
                               and each management vCenter's embedded one), so that an OIDC issuer on one of them
                               reads as the broker and not as a provider of the organization's own. --orgs-only reads
                               no broker, so it refuses to start without them, and an organization signing in through
                               VCF single sign-on whose issuer they do not name fails the read (the full census reads
                               the brokers from the identity plane)
      FINGERPRINT_KEY_FILE     optional: a secret of your own (mode 0600, kept off any shared disk). With it, each API
                               client carries a keyed fingerprint of its id and name, the same in every record made
                               under that key, so service-accounts' catalog_check.py --census can join the record to
                               your catalog although every name in it is a placeholder
      VC_HOSTS                 optional, comma-separated, with VC_USER (user@domain) and VC_PASSWORD_FILE (mode
                               0600; VC_PASSWORD is read if it is unset)
      TLS_VERIFY=false         only on a self-signed lab CA (the metadata URL is fetched by the broker, not here)
      OUT                      the record (default census.json; census.replay.json under --replay, a record that
                               carries "replay": true, which a tool reading census records refuses as no read)
Use:  python3 census.py [--redact] [--egress-metadata-url URL]
      python3 census.py --orgs-only [--redact]       VCF Automation's organizations only, on a provider credential
      python3 census.py --replay replay/census       without an estate: every answer from the recorded set beside
                                                     this script (its hosts are placeholders); nothing is sent and
                                                     no credential is read, and a request the set holds no answer
                                                     for is a read that failed (exit 3)
Exit, the first that applies, so a scheduler reads one state from one number:
      0 recorded, every call answered
      3 a read failed or is not known: a call failed or answered without what the read needs, such as a vCenter's
        session POST with no session id, a list read whose answer holds no list (a 200 without its list key is
        not an empty list), a paged list not read whole (no stated total, a page empty or short before the total, a
        total that changed between pages), an organization listed without isClassicTenant (its type prints "type not
        read") or without isProviderConsumptionOrg (it prints "provider consumption not read"), a broker listed
        without its healthy flag (it prints "health not read"), a list of no broker
        (the census's own bearer came from one) or, as the provider, of no organization (the provider's own System
        organization is one) (the record is still written and names the call; a fleet read refused or read in part
        opens the print with NOT READ, so its counts are not taken for the estate's), the credential could
        not be obtained, --orgs-only read an organization signing in through VCF single sign-on whose issuer
        BROKER_HOSTS does not name (so the brokers given miss at least the one the platform signs in through), the
        record refused because an estate value survived the scrub (nothing is written, so a tool that reads the
        record has nothing to read), a request a --replay set holds no answer for, or an error the script did not
        expect
      5 a usage error (a missing credential or host, a credential file that cannot be read or holds nothing, a
        credential file open to group or other, refused unread with the fix (chmod 600), VC_HOSTS without VC_USER and a
        password, --orgs-only without BROKER_HOSTS, a FINGERPRINT_KEY_FILE unreadable or open to group or other, a
        --replay directory that cannot be read or holds no replay set, a Python older than 3.10), found before anything
        is sent
A tool that reads this record (service-accounts' catalog_check.py --census) takes it as a read only when its exit is
0, no fleet call failed, each paged list's last call states it was read whole (`listed`: the stated total and the
distinct entries read, equal), and the lines it needs are there.

Before a realm. The fleet read runs on a bearer the broker trades for an API token, and the token is made for an API
client of a realm or a VCF single sign-on user, so the census as written starts once VCF single sign-on has a realm.
Before that, read what has no realm to wait for: --orgs-only on a VCF Automation provider credential, and
vcenter-authorization's authz.py, which runs with --no-realm. Whether VCF Operations' own local administrator,
through /suite-api/api/auth/token/acquire, can read the fleet identity plane was not tried.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone

IAM = "/api/fleet-management/iam"
CLOUDAPI = "application/json;version=9.1.0"
VCD_JSON = "application/*+json;version=9.1.0"
API_TOKEN_GRANT = "urn:custom:vcf:params:oauth:grant-type:api-token"
SECRET_KEYS = {"accessToken", "token", "bindDnPassword", "clientSecret", "client_secret", "password",
               "refreshToken", "refresh_token", "privateKey"}
KIND = {"EXTERNAL": "instance", "EMBEDDED": "embedded"}
EXIT_UNREAD, EXIT_USAGE = 3, 5

# ── the allow-lists: a field not named here never reaches the record ───────────────────────────────────────────
DC = ("host", "port", "protocol", "certificateName")
BROKER = ("id", "displayName", "fqdn", "deploymentType", "version", "healthy", "vcfInstanceId",
          {"vidbStatus": ("eligibilityStatus", "reasons")})
REALM = ("id", "name", "idpId", "vcfInstanceId", "vidbResourceId", "totalConfiguredComponents",
         {"ssoRealmCoverage": ("id", "name", "ssoEntityType")}, {"issues": ("name", "severity")})
PROVIDER = ("id", "name", "idpProtocol", "idpType", "provisionType", "ssoRealmId",
            {"directories": ("id", "name", "domains", "defaultDomain")},
            {"idpConfig": ({"oidcConfiguration": ("clientId", "internalUserIdentifierAttribute",
                                                  "openIdUserIdentifierAttribute")},
                           {"samlConfiguration": ("metadataSourceType", "nameIdFormatType", "authenticationContext")})},
            {"provisioningConfig": ({"ldapConfigurations": (
                "name", "domains", "ldapConfigurationId",
                {"ldapBindConfiguration": ("type", "baseDn", "bindDn", "communicationMode", "directorySearchAttribute",
                                           {"primaryDomainController": DC}, {"secondaryDomainController": DC})})},)})
DIRECTORY = ("name", "domains", "domainControllerHost", "domainControllerPort", "lastSyncStatus", "lastSyncDateTime",
             "numberOfUsers", "numberOfGroups", "setupStatus", "ldapConfigurationId")
ROLES = {"roles": ("roleName", "expiresAt")}
API_CLIENT = ("clientId", "clientUuid", "clientName", ROLES)
API_TOKEN = ("tokenName", "tokenType", "tokenStatus", "principalName", "principalStatus", "apiClientId",
             "apiTokenTtl", "accessTokenTtl", "expirationDate", "lastUsedDate")
EMERGENCY = ("clientId", "clientName", "accessTokenStatus", "accessTokenTtl", "accessTokenExpirationDate", ROLES)
AUTH_SOURCE = ("componentType", "status", "authSourceType", "ssoRealmId", "vcfComponentId")
SETTINGS = ("accessTokenTtl", "apiTokenTtl", "apiTokenRetentionPeriod", "allUsersGroupEnabled",
            "jitInactiveUserEnabled", "jitInactiveUserTtl")
VC_PROVIDER = ("name", "config_tag", "federation_type", "is_default", "domain_names", "upn_claim", "groups_claim")


def keep(obj: object, spec: tuple) -> object:
    """Only the fields `spec` names. A {field: spec} entry keeps that sub-object, or each item of that list, by its
    own spec, so a field the API adds later never reaches the record."""
    if isinstance(obj, list):
        return [keep(x, spec) for x in obj]
    if not isinstance(obj, dict):
        return None
    out = {}
    for f in spec:
        if isinstance(f, dict):
            out.update({k: keep(obj[k], sub) for k, sub in f.items() if obj.get(k) is not None})
        elif f in obj:
            out[f] = obj[f]
    return out


def strip_secrets(obj: object) -> bool:
    """Delete every secret-bearing key in place, at any depth; True when one carried a value."""
    found = False
    if isinstance(obj, dict):
        for k in list(obj):
            if k in SECRET_KEYS:
                found = bool(obj.pop(k)) or found  # pop first: an `or` would skip the pop once one is found
            else:
                found = strip_secrets(obj[k]) or found
    elif isinstance(obj, list):
        for v in obj:
            found = strip_secrets(v) or found
    return found


def host_of(url: str | None) -> str | None:
    return urllib.parse.urlparse(url).hostname if url else None


def listed(body: object, key: str | None = None) -> list | None:
    """The list in an answer, or None when the answer holds none: the answer itself when it is a list, the list under
    `key` when one is named (a named key is authoritative: another list in the body is not it, and its absence is not
    an empty list), or with no key the first list in the body."""
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        if key is not None:
            return body[key] if isinstance(body.get(key), list) else None
        return next((v for v in body.values() if isinstance(v, list)), None)
    return None


def shape_error(calls: list, why: str) -> None:
    """Mark the last call as answered without what the read needs, so failed() counts it and the run exits 3. A call
    that already failed (a refusal, no answer) keeps its own reason."""
    last = calls[-1] if calls else None
    if last is not None and (last.get("status") or 0) < 400 and not last.get("error") and not last.get("shape"):
        last["shape"] = why


def items(reader: Reader, body: object, key: str | None = None) -> list:
    """The list a list read answered. An answer that came back without its list, a 200 missing its list key included,
    read nothing: the call is marked, the run exits 3, and an empty list here never stands for an empty estate."""
    got = listed(body, key)
    if got is None:
        shape_error(reader.calls, f"no {key} list in the answer" if key else "no list in the answer")
        return []
    return got


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
def _ctx() -> ssl.SSLContext:
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


def _secret(name: str) -> str:
    """NAME_FILE's secret, read through read_secret, or NAME itself."""
    if REPLAY is not None:  # a replayed run reads no credential: nothing is sent
        return REPLAY_CREDENTIAL
    if os.environ.get(f"{name}_FILE"):
        return read_secret(f"{name}_FILE")
    return os.environ.get(name, "")


def fingerprint_key() -> bytes | None:
    """The secret in FINGERPRINT_KEY_FILE, or None when it is unset. Read as bytes, as every tool that joins on it
    reads it; a file open to group or other is refused before it is read, as read_secret refuses one."""
    path = os.environ.get("FINGERPRINT_KEY_FILE")
    if not path:
        return None
    with open(path, "rb") as f:
        mode = os.fstat(f.fileno()).st_mode & 0o777
        # Windows makes the mode from the read-only flag alone, so it has no group or other bits to judge.
        if mode & 0o077 and os.name != "nt":
            raise PermissionError(f"FINGERPRINT_KEY_FILE names a file of mode {mode:04o}, open to group or other: "
                                  'run chmod 600 "$FINGERPRINT_KEY_FILE" and try again (the file was not read)')
        key = f.read().strip()
    if not key:
        raise ValueError("FINGERPRINT_KEY_FILE is empty")
    return key


def fingerprint(value: str, key: bytes) -> str:
    """A name's keyed fingerprint: the same under one key in every record, and nothing without the key. Case and
    surrounding space are ignored, as a catalog may spell a client either way."""
    return hmac.new(key, value.strip().lower().encode(), hashlib.sha256).hexdigest()[:16]


def key_check(key: bytes) -> str:
    """A short value that says which key fingerprinted a record, so records made under two keys are never joined."""
    return fingerprint("fingerprint key check", key)[:8]


class Reader:
    """One plane's API under one credential. Every call is recorded with its answer, a refusal included; secrets are
    deleted from each body as it arrives; nothing raises."""

    def __init__(self, plane: str, base: str, headers: dict, calls: list):
        self.plane, self.base, self.headers, self.calls = plane, base, headers, calls

    def call(self, method: str, path: str, body: object = None, accept: str = "application/json",
             headers: dict | None = None, timeout: int = 60) -> object:
        rec = {"plane": self.plane, "method": method, "path": path, "status": None}
        self.calls.append(rec)
        data = json.dumps(body).encode() if body is not None else None
        h = {**self.headers, "Accept": accept, **(headers or {})}
        if data is not None:
            h["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data, headers=h, method=method)
        try:
            with _urlopen(req, context=_ctx(), timeout=timeout) as r:
                rec["status"], raw = r.status, r.read()
        except urllib.error.HTTPError as e:
            rec["status"], rec["error"], rec["message"] = e.code, str(e.reason), _message(e)
            return None
        except (urllib.error.URLError, OSError) as e:
            rec["error"] = str(getattr(e, "reason", e))[:120]
            return None
        try:
            answer = json.loads(raw) if raw else {}
        except ValueError:
            return raw.decode(errors="replace")
        strip_secrets(answer)
        return answer

    def get(self, path: str, accept: str = "application/json") -> object:
        return self.call("GET", path, accept=accept)


def _message(e: urllib.error.HTTPError) -> str:
    """The server's own words for a refusal, printed for the operator and never recorded."""
    try:
        body = json.loads(e.read() or b"{}")
        return str(body.get("message") or body.get("error") or body)[:240] if isinstance(body, dict) else ""
    except (ValueError, OSError):
        return ""


# A list is complete only when it is read whole: pages are read until the count of DISTINCT entries (by id, a duplicate
# removed) equals the total the answer states. An answer without its list or without a stated total, a page that comes
# back empty or short before the total is reached, a page that adds nothing new, and a total that changes between pages
# are an unread list: the call is marked (`shape`), so the run exits 3 and the record names it, and the entries read so
# far never stand for the whole list. The same pager, written the same way, is in each identity companion that pages.
FLEET_PAGE_SIZE = 50    # the fleet's queries take page (from 0) and pageSize in the query; 50 by default (9.1.1)
VCFA_PAGE_SIZE = 128    # VCF Automation's cloudapi lists take page (from 1) and pageSize; 128 is the largest page
MAX_PAGES = 10000
IDS = ("id", "clientUuid", "clientId", "roleName")


def ident(row: object) -> str:
    """An entry's identity for counting distinct entries: its id, or, for an entry that carries none, the entry."""
    if isinstance(row, dict):
        for k in IDS:
            if row.get(k) not in (None, ""):
                return f"{k}:{row[k]}"
    return json.dumps(row, sort_keys=True, default=str)


def read_whole(reader: Reader, ask, key: str, total_of, size_of, size: int) -> list:
    """Every page of one list, read to the total its answer states. `ask(page_index)` makes one call and returns the
    answer; `total_of` and `size_of` read the stated total and the page size the answer was served at. Each page call
    carries `listed`, the stated total and the distinct entries read so far, so a tool reading the record can check
    that the list was read whole; an unread list marks its last call `shape` and returns what was read."""
    out, seen, total = [], set(), None
    for i in range(MAX_PAGES):
        answer = ask(i)
        rows = listed(answer, key)
        if rows is None:
            shape_error(reader.calls, f"no {key} list in the answer")
            return out
        stated = total_of(answer)
        if isinstance(stated, bool) or not isinstance(stated, int) or stated < 0:
            shape_error(reader.calls, f"no stated total in the answer, so the {key} list cannot be known whole")
            return out
        if total is not None and stated != total:
            shape_error(reader.calls, f"the stated total changed between pages, {total} then {stated}: the {key} list "
                                      "moved under the read")
            return out
        total, before = stated, len(out)
        for row in rows:
            k = ident(row)
            if k not in seen:
                seen.add(k)
                out.append(row)
        reader.calls[-1]["listed"] = {"total": total, "distinct": len(out)}
        if len(out) == total:
            return out
        if len(out) > total:
            shape_error(reader.calls, f"{len(out)} distinct {key} entries against a stated total of {total}: the list "
                                      "moved under the read")
            return out
        served = size_of(answer)
        served = served if isinstance(served, int) and not isinstance(served, bool) and served > 0 else size
        if not rows or len(out) == before or len(rows) < served:
            shape_error(reader.calls, f"the pages ended at {len(out)} of the {total} {key} entries the answer states")
            return out
    shape_error(reader.calls, f"the {key} list did not end within {MAX_PAGES} pages")
    return out


def fleet_pages(ops: Reader, method: str, path: str, key: str, body: object = None) -> list:
    """Every page of a fleet IAM list, read whole: `page` counts from 0, and pageInfo.totalCount is the total."""
    def info(answer: object) -> dict:
        pi = answer.get("pageInfo") if isinstance(answer, dict) else None
        return pi if isinstance(pi, dict) else {}

    return read_whole(ops, lambda i: ops.call(method, f"{path}?page={i}&pageSize={FLEET_PAGE_SIZE}", body), key,
                      lambda a: info(a).get("totalCount"), lambda a: info(a).get("pageSize"), FLEET_PAGE_SIZE)


def vcfa_pages(vcfa: Reader, path: str) -> list:
    """Every page of a VCF Automation list, read whole: `page` counts from 1, and resultTotal is the total. A page
    without its `values` list read nothing, so it is a failed read, never "no organizations"."""
    def field(answer: object, k: str) -> object:
        return answer.get(k) if isinstance(answer, dict) else None

    return read_whole(vcfa, lambda i: vcfa.call("GET", f"{path}?page={i + 1}&pageSize={VCFA_PAGE_SIZE}", accept=CLOUDAPI),
                      "values", lambda a: field(a, "resultTotal"), lambda a: field(a, "pageSize"), VCFA_PAGE_SIZE)


# ── credentials ──────────────────────────────────────────────────────────────────────────────────────────────────
def _form(url: str, fields: dict) -> dict:
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
    with _urlopen(req, context=_ctx(), timeout=60) as r:
        return json.loads(r.read())


def broker_tenant() -> str:
    """The broker tenant: the realm's path segment at the broker (/acs/t/<tenant>/), CUSTOMER unless set. It is not the
    realm's name. On the reference estate an API client's vCenter session carried it as its domain, CUSTOMER\\<client id>
    (X-141), while a grant spelled with the realm's name applied to nobody behind an AD/LDAP provider (the 2026-10-06
    grant probe)."""
    return os.environ.get("BROKER_TENANT") or os.environ.get("OPS_REALM") or "CUSTOMER"


def ops_bearer() -> str:
    """A bearer for VCF Operations: the one in OPS_BEARER_FILE, or an API token traded at the broker for one."""
    if os.environ.get("OPS_BEARER_FILE"):
        return _secret("OPS_BEARER").removeprefix("Bearer ").strip()
    broker = os.environ.get("OPS_BROKER_HOST") or os.environ.get("BROKER_HOST") or os.environ["OPS_HOST"]
    answer = _form(f"https://{broker}/acs/t/{broker_tenant()}/token",
                   {"grant_type": API_TOKEN_GRANT, "api_token": (_secret("OPS_API_TOKEN") or _secret("API_TOKEN"))})
    return answer["access_token"]


def vcfa_bearer(host: str) -> str:
    if os.environ.get("VCFA_PROVIDER_BEARER_FILE"):
        return _secret("VCFA_PROVIDER_BEARER").removeprefix("Bearer ").strip()
    answer = _form(f"https://{host}/oauth/provider/token",
                   {"grant_type": "refresh_token", "refresh_token": _secret("VCFA_PROVIDER_REFRESH_TOKEN")})
    return answer["access_token"]


def vc_session(host: str, user: str, password: str, calls: list) -> Reader | None:
    vc = Reader(f"vcenter:{host}", f"https://{host}", {}, calls)
    basic = base64.b64encode(f"{user}:{password}".encode()).decode()
    sid = vc.call("POST", "/api/session", headers={"Authorization": f"Basic {basic}"})
    if not isinstance(sid, str):
        if (calls[-1].get("status") or 0) < 400 and not calls[-1].get("error"):
            calls[-1]["shape"] = "no session id in the answer"   # an answer, but no session: this vCenter is not read
        return None
    vc.headers["vmware-api-session-id"] = sid
    return vc


# ── the planes ───────────────────────────────────────────────────────────────────────────────────────────────────
def brokers(ops: Reader) -> list[dict]:
    """The identity plane's brokers. The fleet inventory lists an appliance; an embedded broker lives inside a
    management vCenter and appears only here."""
    found = [keep(v, BROKER) for v in items(ops, ops.get(f"{IAM}/vidbs"), "vidbs")]
    if not found:   # the bearer this census reads on came from a broker, so a list of none did not read the plane
        shape_error(ops.calls, "no broker in the list, where the census's own bearer came from one")
    # A broker listed without its healthy flag was not read for health: it prints "health not read", never NOT HEALTHY
    # and never healthy, and the run exits 3, as an organization listed without its type does.
    unread = sum(1 for b in found if not isinstance(b.get("healthy"), bool))
    if unread:
        shape_error(ops.calls, f"{unread} broker(s) in the list without healthy, so their health is not read")
    return sorted(found, key=lambda b: b.get("fqdn") or "")


def realms(ops: Reader) -> list[dict]:
    """Each realm in full: the list carries a summary, the realm's own read carries its coverage and issues."""
    out = []
    for r in items(ops, ops.get(f"{IAM}/ssorealms"), "ssoRealms"):
        detail = ops.get(f"{IAM}/ssorealms/{r['id']}")
        if not (isinstance(detail, dict) and detail.get("id")):
            shape_error(ops.calls, "no realm in the answer")   # the summary is kept; the run says it is not the realm
        out.append(keep(detail if isinstance(detail, dict) and detail.get("id") else r, REALM))
    return sorted(out, key=lambda r: r.get("id") or "")


def provider(ops: Reader, idp_id: str) -> dict:
    """The realm's identity provider. Of a federated provider's URLs only the host is kept."""
    p = ops.get(f"{IAM}/identity-providers/{idp_id}")
    if not (isinstance(p, dict) and p.get("id")):
        shape_error(ops.calls, "no provider in the answer")
        p = {"id": idp_id}
    cfg = p.get("idpConfig") or {}
    out = keep(p, PROVIDER)
    hosts = {"discoveryHost": host_of((cfg.get("oidcConfiguration") or {}).get("discoveryEndpoint")),
             "metadataHost": host_of((cfg.get("samlConfiguration") or {}).get("metadataUrl"))}
    return {**out, **{k: v for k, v in hosts.items() if v}}


def identity_plane(ops: Reader) -> dict:
    """Brokers, realms and providers: the part of the fleet a reach check must leave unchanged."""
    rs = realms(ops)
    return {"brokers": brokers(ops), "realms": rs, "providers": [provider(ops, r["idpId"]) for r in rs if r.get("idpId")]}


def realm_clients(ops: Reader, realm_id: str) -> dict:
    """What can sign in to a realm without a person: API clients and their tokens, emergency clients, OAuth apps."""
    base = f"{IAM}/ssorealms/{realm_id}"
    apps = items(ops, ops.get(f"{base}/oauth-apps"), "oauthApps")
    return {
        "realmId": realm_id,
        "api_clients": [keep(c, API_CLIENT) for c in fleet_pages(ops, "POST", f"{base}/api-clients/query", "apiClients", {})],
        "api_tokens": [keep(t, API_TOKEN) for t in fleet_pages(ops, "POST", f"{base}/api-tokens/query", "apiTokens", {})],
        "emergency_clients": [keep(e, EMERGENCY)
                              for e in items(ops, ops.get(f"{base}/emergency-clients"), "emergencyClients")],
        "oauth_apps": [{**keep(a, ("clientName", "clientId")),
                        "redirectHosts": sorted({h for h in map(host_of, a.get("redirectUrls") or []) if h})}
                       for a in apps],
    }


def fleet(ops: Reader) -> dict:
    """The whole fleet IAM plane, read once."""
    out = identity_plane(ops)
    out["directories"] = [{"idpId": p["id"], **keep(d, DIRECTORY)} for p in out["providers"]
                          for d in items(ops, ops.get(f"{IAM}/identity-providers/{p['id']}/ldap-directories"),
                                         "ldapDirectories")]
    out["clients"] = [realm_clients(ops, r["id"]) for r in out["realms"]]
    out["auth_sources"] = [keep(a, AUTH_SOURCE) for a in
                           items(ops, ops.call("POST", f"{IAM}/components/auth-sources/query", {}),
                                 "iamComponentAuthSources")]
    settings = ops.get(f"{IAM}/settings")
    if not isinstance(settings, dict):
        shape_error(ops.calls, "no settings in the answer")
    out["settings"] = keep(settings, SETTINGS) if isinstance(settings, dict) else None
    out["roles"] = [keep(r, ("roleName", "type")) for r in fleet_pages(ops, "GET", f"{IAM}/roles", "vcfRoles")]
    return out


def organization(org: dict, ldap: dict, oauth: dict, saml: dict) -> dict:
    """One organization's ways in, from its own three settings reads. Of the OIDC issuer only the host is kept."""
    custom = ldap.get("customOrgLdapSettings") or {}
    classic, consumption = org.get("isClassicTenant"), org.get("isProviderConsumptionOrg")
    return {"name": org.get("name"), "id": org.get("id"), "classic": classic if isinstance(classic, bool) else None,
            "providerConsumption": consumption if isinstance(consumption, bool) else None, "enabled": org.get("isEnabled"),
            "ldapMode": ldap.get("orgLdapMode"), "ldapHost": custom.get("hostName"), "ldapPort": custom.get("port"),
            "ldapSsl": custom.get("isSsl"), "oidc": bool(oauth.get("enabled")), "oidcVidb": bool(oauth.get("vidb")),
            "issuerHost": host_of(oauth.get("issuerId")), "saml": bool(saml.get("enabled"))}


def organizations(vcfa: Reader) -> list[dict]:
    """Every VCF Automation organization's LDAP, OIDC and SAML settings, read as the provider. A list of none read
    nothing: the provider signs in to its own System organization, which its list held on every run read here, so
    none is a failed read, never an estate without organizations."""
    out = []
    orgs = vcfa_pages(vcfa, "/cloudapi/1.0.0/orgs")
    if not orgs:
        shape_error(vcfa.calls, "no organization in the list, where the provider's own System organization is one")
    # The type decides which ways in and roles apply, and the provider consumption flag says which organization the
    # provider consumes from: an entry without either is printed "type not read" or "provider consumption not read",
    # never all-apps or an ordinary organization, and the run exits 3.
    untyped = sum(1 for o in orgs if not isinstance(o.get("isClassicTenant"), bool))
    unflagged = sum(1 for o in orgs if not isinstance(o.get("isProviderConsumptionOrg"), bool))
    missing = ([f"{untyped} organization(s) in the list without isClassicTenant, so their type is not read"] if untyped
               else []) + ([f"{unflagged} organization(s) in the list without isProviderConsumptionOrg, so whether each "
                            "is the provider's consumption organization is not read"] if unflagged else [])
    if missing:
        shape_error(vcfa.calls, "; ".join(missing))
    for org in orgs:
        uid = str(org.get("id", "")).rsplit(":", 1)[-1]
        reads = []
        for s in ("ldap", "oauth", "federation"):
            r = vcfa.get(f"/api/admin/org/{uid}/settings/{s}", VCD_JSON)
            if not isinstance(r, dict):
                shape_error(vcfa.calls, f"no {s} settings in the answer")
            reads.append(r if isinstance(r, dict) else {})
        out.append(organization(org, *reads))
    return out


def supervisor_providers(vc: Reader, sid: str) -> list[dict]:
    """A Supervisor's identity providers. The list names each one; its issuer is only in the provider's own read."""
    base = f"/api/vcenter/namespace-management/supervisors/{sid}/identity/providers"
    out = []
    for i in items(vc, vc.get(base)):
        d = vc.get(f"{base}/{i.get('provider')}")
        d = d if isinstance(d, dict) else i
        out.append({"display_name": d.get("display_name"), "provider": i.get("provider"),
                    "issuerHost": host_of(d.get("issuer_URL")), "username_claim": d.get("username_claim"),
                    "groups_claim": d.get("groups_claim")})
    return out


def vcenter(vc: Reader, host: str) -> dict:
    """A vCenter's identity providers, the host each one discovers its issuer at, and each Supervisor's providers."""
    providers = [{**keep(p, VC_PROVIDER), "discoveryHost": host_of((p.get("oidc") or {}).get("discovery_endpoint"))}
                 for p in items(vc, vc.get("/api/vcenter/identity/providers"))]
    supervisors = [{"supervisor": s.get("supervisor"), "name": (s.get("info") or {}).get("name"),
                    "identity_providers": supervisor_providers(vc, s.get("supervisor"))}
                   for s in items(vc, vc.get("/api/vcenter/namespace-management/supervisors/summaries"), "items")]
    return {"vcenter": host, "identity_providers": providers, "supervisors": supervisors}


def egress(ops: Reader, found: list[dict], url: str) -> list[dict]:
    """Ask each broker to fetch a SAML metadata URL itself (a request, not a read): 200 proves it reaches the
    identity provider; a failure says it does not."""
    out = []
    for b in found:
        answer = ops.call("POST", f"{IAM}/saml-metadata/validate", {"metadata": url, "vidbResourceId": b.get("id")},
                          timeout=120)
        last = ops.calls[-1]
        out.append({"broker": b.get("fqdn"), "status": last["status"], "error": last.get("error"),
                    "preferredBinding": answer.get("preferredBinding") if isinstance(answer, dict) else None})
    return out


def diff(before: object, after: object, at: str = "") -> list[str]:
    """The paths at which two reads differ; an empty list means they are the same."""
    if isinstance(before, dict) and isinstance(after, dict):
        return [p for k in sorted(set(before) | set(after)) for p in diff(before.get(k), after.get(k), f"{at}.{k}".lstrip("."))]
    if isinstance(before, list) and isinstance(after, list) and len(before) == len(after):
        return [p for i, (x, y) in enumerate(zip(before, after)) for p in diff(x, y, f"{at}[{i}]")]
    return [] if before == after else [at or "."]


def reach(ops: Reader, before: dict, url: str) -> dict:
    """The egress check with its proof of no change: the identity plane read before, the requests, the read after."""
    results = egress(ops, before["brokers"], url)
    after = identity_plane(ops)
    changed = {k: diff(before[k], after[k]) for k in ("brokers", "realms", "providers")}
    return {"metadata_url": url, "results": results, "unchanged": not any(changed.values()),
            "differences": {k: v for k, v in changed.items() if v}}


# ── what a reader should be able to explain ──────────────────────────────────────────────────────────────────────
def broker_kind(deployment_type: str | None) -> str:
    """The API's EXTERNAL is the instance broker; EMBEDDED lives inside a management vCenter."""
    return KIND.get(deployment_type or "", (deployment_type or "unknown").lower())


def broker_lines(f: dict) -> list[dict]:
    """Each broker, its kind, and the realm it holds: a broker holds one realm or none."""
    holder = {r.get("vidbResourceId"): r.get("name") for r in f.get("realms") or []}
    return [{"fqdn": b.get("fqdn"), "kind": broker_kind(b.get("deploymentType")), "realm": holder.get(b.get("id")),
             "healthy": b.get("healthy")} for b in f.get("brokers") or []]


def realm_lines(f: dict) -> list[dict]:
    """Each realm, the broker holding it, and the VCF instances it covers: whole instances, never part of one."""
    by_id = {b.get("id"): b for b in f.get("brokers") or []}
    out = []
    for r in f.get("realms") or []:
        b = by_id.get(r.get("vidbResourceId")) or {}
        cover = r.get("ssoRealmCoverage") or []
        out.append({"name": r.get("name"), "broker": b.get("fqdn"), "broker_kind": broker_kind(b.get("deploymentType")),
                    "instances": [c.get("name") for c in cover if c.get("ssoEntityType") == "VCF_INSTANCE"],
                    "components": r.get("totalConfiguredComponents"),
                    "issues": [i.get("name") for i in r.get("issues") or []]})
    return out


def provider_lines(f: dict) -> list[dict]:
    """Each realm's provider: what it is (type), how the broker speaks to it (protocol), how users arrive."""
    realm = {r.get("id"): r.get("name") for r in f.get("realms") or []}
    return [{"realm": realm.get(p.get("ssoRealmId")), "name": p.get("name"), "type": p.get("idpType"),
             "protocol": p.get("idpProtocol"), "provisioning": p.get("provisionType")} for p in f.get("providers") or []]


def directory_lines(p: dict, synced: list[dict]) -> list[dict]:
    """Each directory under a provider with the protocol and port the broker binds over. An LDAP provider names its
    domain controllers; a federated provider's directory has none, and its protocol is the provider's."""
    state = {d.get("ldapConfigurationId"): d for d in synced if d.get("idpId") == p.get("id")}
    out = []
    for c in (p.get("provisioningConfig") or {}).get("ldapConfigurations") or []:
        bind, d = c.get("ldapBindConfiguration") or {}, state.get(c.get("ldapConfigurationId")) or {}
        dc, second = bind.get("primaryDomainController") or {}, bind.get("secondaryDomainController")
        out.append({"name": c.get("name"), "domains": c.get("domains") or [], "protocol": dc.get("protocol"),
                    "port": dc.get("port"), "host": dc.get("host"),
                    "secondary": {k: second.get(k) for k in ("host", "protocol", "port")} if second else None,
                    "sync": d.get("lastSyncStatus"), "users": d.get("numberOfUsers"), "groups": d.get("numberOfGroups")})
    for d in p.get("directories") or []:
        out.append({"name": d.get("name"), "domains": d.get("domains") or [], "protocol": p.get("idpProtocol"),
                    "port": None, "host": None, "secondary": None, "sync": None, "users": None, "groups": None})
    return out


DAY_MS = 86_400_000


def _day(ms: object) -> str | None:
    """An epoch-milliseconds date, as the fleet API gives it, as YYYY-MM-DD in UTC."""
    if not isinstance(ms, int) or ms <= 0:
        return None
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")


def captured_ms(record: dict) -> int | None:
    """The moment of the read, in epoch milliseconds: a token's runway is counted from it, so a record reads the same
    on any later day."""
    try:
        return int(datetime.strptime(record["captured"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp() * 1000)
    except (KeyError, TypeError, ValueError):
        return None


def token_line(t: dict, now: int | None = None) -> dict:
    """A token's two lifetimes, in minutes (the API token's own, and that of each bearer traded for it), and its
    runway at the read: the date it expires and the days left, the date it was last exchanged for a bearer and the
    days since. The fleet API dates both in epoch milliseconds."""
    exp, used = t.get("expirationDate"), t.get("lastUsedDate")
    known = isinstance(now, int)
    return {"name": t.get("tokenName"), "principal": t.get("principalName"), "status": t.get("tokenStatus"),
            "api_token_ttl_min": t.get("apiTokenTtl"), "access_token_ttl_min": t.get("accessTokenTtl"),
            "expires": _day(exp), "days_left": (exp - now) // DAY_MS if known and _day(exp) else None,
            "last_used": _day(used), "days_since_used": (now - used) // DAY_MS if known and _day(used) else None}


def client_lines(c: dict, now: int | None = None) -> list[dict]:
    """Each API client with its roles and the tokens issued to it, and its keyed fingerprints when the read had a key."""
    out = []
    for a in c.get("api_clients") or []:
        ids = (a.get("clientId"), a.get("clientUuid"))
        mine = [t for t in c.get("api_tokens") or [] if t.get("tokenType") == "API_CLIENT"
                and (t.get("apiClientId") in ids or t.get("principalName") == a.get("clientId"))]
        line = {"name": a.get("clientName") or a.get("clientId"),
                "roles": [r.get("roleName") for r in a.get("roles") or []], "tokens": [token_line(t, now) for t in mine]}
        if a.get("fingerprints"):
            line["fingerprints"] = a["fingerprints"]
        out.append(line)
    return out


def emergency_lines(c: dict) -> list[dict]:
    """The realm's emergency clients: the way in when the identity provider is down. None is an answer too."""
    return [{"name": e.get("clientName") or e.get("clientId"), "status": e.get("accessTokenStatus"),
             "access_token_ttl_min": e.get("accessTokenTtl")} for e in c.get("emergency_clients") or []]


def settings_line(s: dict) -> dict:
    """The fleet's token lifetimes, in minutes, and its two group switches."""
    return {"access_token_ttl_min": s.get("accessTokenTtl"), "api_token_ttl_min": s.get("apiTokenTtl"),
            "api_token_retention_min": s.get("apiTokenRetentionPeriod"), "all_users_group": s.get("allUsersGroupEnabled"),
            "jit_inactive_user_ttl_min": s.get("jitInactiveUserTtl") if s.get("jitInactiveUserEnabled") else None}


def sign_in(org: dict, broker_hosts: set) -> list[str]:
    """How an organization's people get in: VCF single sign-on (VCF Automation's own flag), OIDC to the broker or
    to another provider, SAML, the system or the organization's own LDAP; local accounts only if none."""
    ways = []
    if org.get("oidc"):
        ways.append("vcf-sso" if org.get("oidcVidb") else "oidc-broker" if org.get("issuerHost") in broker_hosts
                    else "oidc")
    if org.get("saml"):
        ways.append("saml")
    if org.get("ldapMode") in ("SYSTEM", "CUSTOM"):
        ways.append(f"ldap-{org['ldapMode'].lower()}")
    return ways or ["local"]


def issuer_kind(org: dict, broker_hosts: set) -> str | None:
    if not org.get("oidc"):
        return None
    host = org.get("issuerHost")
    return "broker" if host in broker_hosts else "entra" if host == "login.microsoftonline.com" else "other"


def org_type(classic: object) -> str:
    """An organization's type from VCF Automation's isClassicTenant: classic when true, All Apps when false, and not
    read when the list entry carried no such flag (the run then exits 3: an absent flag is not All Apps)."""
    return "classic" if classic is True else "all-apps" if classic is False else "type not read"


def org_lines(orgs: list[dict], broker_hosts: set) -> list[dict]:
    """Each organization's type and its ways in."""
    return [{"name": o.get("name"), "type": org_type(o.get("classic")),
             "provider_consumption": o.get("providerConsumption"), "sign_in": sign_in(o, broker_hosts),
             "issuer": issuer_kind(o, broker_hosts)} for o in orgs]


def vcenter_lines(vcenters: list[dict], kinds: dict) -> list[dict]:
    """The broker each vCenter's default provider points at, and each Supervisor's issuers."""
    out = []
    for v in vcenters:
        default = next((p for p in v.get("identity_providers") or [] if p.get("is_default")), {})
        through = default.get("discoveryHost")
        out.append({"vcenter": v.get("vcenter"), "config_tag": default.get("config_tag"), "through": through,
                    "broker_kind": kinds.get(through, "not a broker") if through else None,
                    "supervisors": [{"name": s.get("name"), "issuers": [i.get("issuerHost") for i in s.get("identity_providers") or []]}
                                    for s in v.get("supervisors") or []]})
    return out


def summary(record: dict) -> dict:
    """The lines the census exists for, each from the plane that owns it."""
    f = record.get("fleet") or {}
    kinds = {b.get("fqdn"): broker_kind(b.get("deploymentType")) for b in f.get("brokers") or []}
    clients = f.get("clients") or []
    tokens = [t for c in clients for t in c.get("api_tokens") or []]
    egress_read = record.get("egress")
    now = captured_ms(record)
    given = set(record.get("broker_hosts_given") or [])
    return {
        "brokers": broker_lines(f),
        "realms": realm_lines(f),
        "providers": provider_lines(f),
        "directories": [d for p in f.get("providers") or [] for d in directory_lines(p, f.get("directories") or [])],
        "emergency_clients": [e for c in clients for e in emergency_lines(c)],
        "api_clients": [a for c in clients for a in client_lines(c, now)],
        "user_tokens": [token_line(t, now) for t in tokens if t.get("tokenType") == "USER"],
        "settings": settings_line(f.get("settings") or {}),
        "organizations": org_lines(record.get("organizations") or [], set(kinds) | given),
        "vcenters": vcenter_lines(record.get("vcenters") or [], kinds),
        "broker_tenant": record.get("broker_tenant"),
        "orgs_only": bool(record.get("orgs_only")),
        "egress": None if not egress_read else {
            "reached": [{"broker": r.get("broker"), "status": r.get("status")} for r in egress_read["results"]],
            "unchanged": egress_read["unchanged"]},
    }


def _minutes(n: object) -> str:
    if not isinstance(n, int):
        return "?"
    return f"{n} min ({n / 1440:g} d)" if n >= 1440 else f"{n} min"


def spelled(value: str | None) -> str:
    """A domain as a vCenter grant spells it, in capitals. A placeholder stays as it is, so a redacted line still
    names the value its record replaced."""
    return value if not value or PLACEHOLDER.fullmatch(value) else value.upper()


def spellings(s: dict) -> str | None:
    """The two ways to spell a principal in a vCenter grant under this estate's realm: each bound directory's domain,
    which a broker session carries, and the realm's name, which a grant accepts and nobody signs in as. A realm-spelled
    grant was measured inert behind an AD/LDAP provider only, so the line says which this estate's provider is."""
    if not s["realms"]:
        return None
    bound = sorted({x for d in s["directories"] if d["host"] for x in d["domains"] if x})
    providers = s.get("providers") or []
    directory = bool(providers) and all(p.get("protocol") == "LDAP_BIND" for p in providers)
    realm = ("the realm's name, inert behind an AD/LDAP provider" if directory
             else "the realm's name; measured inert behind an AD/LDAP provider only, not behind this one")
    return "vCenter grant spellings: " + "; ".join(
        [f"{spelled(x)}\\<name> (directory)" for x in bound]
        + [f"{spelled(r['name'])}\\<name> ({realm})" for r in s["realms"]])


def client_session(s: dict) -> str | None:
    """How an API client's vCenter session reads: the broker tenant, a different string from the realm's name."""
    if not s["realms"] or not s.get("broker_tenant"):
        return None
    return (f"API client sessions in vCenter: {s['broker_tenant']}\\<client id> "
            "(the broker tenant, not the realm's name)")


def runway(t: dict) -> str:
    """A token's runway at the read: the days left to its expiry, and how long since it was last exchanged."""
    if t.get("expires") is None:
        left = "expiry not read"
    elif t["days_left"] is None:
        left = f"expires {t['expires']}"
    else:
        left = (f"expires {t['expires']}, {t['days_left']} d left" if t["days_left"] >= 0
                else f"EXPIRED {t['expires']}, {-t['days_left']} d ago")
    if t.get("last_used") is None:
        used = "never exchanged"
    elif t["days_since_used"] is None:
        used = f"last used {t['last_used']}"
    else:
        used = f"last used {t['last_used']}, {t['days_since_used']} d before the read"
    return f"{left}; {used}"


def _token_text(t: dict) -> str:
    return (f"token {t['name']} {t['status']}: API token {_minutes(t['api_token_ttl_min'])}, "
            f"access token {_minutes(t['access_token_ttl_min'])}; {runway(t)}")


def unplaced_issuers(s: dict) -> list[str]:
    """--orgs-only: the organizations that sign in through VCF single sign-on, whose issuer is a broker by definition,
    with an issuer BROKER_HOSTS does not name. Any one of them means the brokers given miss the platform's own, so an
    OIDC issuer on a broker may be read as a provider of the organization's own: a failed read, never a clean one. An
    embedded broker left out is not caught this way, which is why every broker is named."""
    if not s.get("orgs_only"):
        return []
    return [o["name"] for o in s["organizations"] if "vcf-sso" in o["sign_in"] and o["issuer"] != "broker"]


def consumption(flag: object) -> str:
    """The provider consumption flag as the Organizations line prints it: named when true, nothing when false, and
    "provider consumption not read" when the list entry carried no such flag (the run then exits 3: an absent flag is
    not false)."""
    return ", provider consumption" if flag is True else "" if flag is False else ", provider consumption not read"


def org_report(s: dict) -> list[str]:
    """The organizations block: each organization's type and its ways in."""
    if not s["organizations"]:
        return []
    lines = [f"Organizations: {len(s['organizations'])}"]
    lines += [f"  {o['name']}  {o['type']}{consumption(o['provider_consumption'])}: "
              f"{', '.join(o['sign_in'])}" + (f" (issuer: {o['issuer']})" if o["issuer"] else "")
              for o in s["organizations"]]
    if s.get("orgs_only") and not s["brokers"] and any(o["issuer"] == "other" for o in s["organizations"]):
        lines.append("  no broker was read: an OIDC issuer reads broker only when its host is in BROKER_HOSTS")
    missed = unplaced_issuers(s)
    if missed:
        lines.append(f"NOT PLACED: {len(missed)} organization(s) sign in through VCF single sign-on with an issuer "
                     "BROKER_HOSTS does not name, so the brokers given miss the platform's own and an organization "
                     "on a broker may read as on a provider of its own; name every broker's host and read again; exit 3")
    return lines


def health(flag: object) -> str:
    """A broker's healthy flag as its line prints it: nothing when true, NOT HEALTHY when false, and "health not read"
    when the list entry carried no such flag (the run then exits 3: an absent flag is not false). What the flag
    measures is the identity plane's; the census prints it and judges nothing."""
    return "" if flag is True else "  NOT HEALTHY" if flag is False else "  health not read"


def report(s: dict) -> list[str]:
    """The summary as the lines the census prints."""
    n = Counter(b["kind"] for b in s["brokers"])
    lines = [f"Brokers, from the identity plane: {len(s['brokers'])} "
             f"({', '.join(f'{v} {k}' for k, v in sorted(n.items()))})"]
    lines += [f"  {b['fqdn']}  {b['kind']}  " + (f"holds realm {b['realm']}" if b["realm"] else "holds no realm")
              + health(b["healthy"]) for b in s["brokers"]]
    lines += [f"Realm {r['name']} on the {r['broker_kind']} broker {r['broker']}: covers {len(r['instances'])} VCF "
              f"instance(s) ({', '.join(r['instances'])}), {r['components']} component(s); "
              f"issues: {', '.join(r['issues']) or 'none'}" for r in s["realms"]]
    lines += [f"Provider {p['name']}: type {p['type']}, protocol {p['protocol']}, provisioning {p['provisioning']}"
              for p in s["providers"]]
    for d in s["directories"]:
        where = f" to {d['host']}" if d["host"] else ""
        extra = f"; secondary {d['secondary']['protocol']} port {d['secondary']['port']}" if d["secondary"] else ""
        sync = f"; sync {d['sync']}, {d['users']} users, {d['groups']} groups" if d["sync"] else ""
        lines.append(f"  directory {d['name']} ({', '.join(d['domains'])}): {d['protocol']} "
                     f"port {d['port'] or 'none'}{where}{extra}{sync}")
    if spellings(s):
        lines.append(spellings(s))
    if client_session(s):
        lines.append(client_session(s))
    lines.append("Emergency client: " + (", ".join(
        f"{e['name']} ({e['status']}, access token {_minutes(e['access_token_ttl_min'])})"
        for e in s["emergency_clients"]) or "none"))
    lines.append(f"API clients: {len(s['api_clients'])}")
    lines += [f"  {c['name']}: roles {', '.join(c['roles']) or 'none'}; "
              + ("; ".join(_token_text(t) for t in c["tokens"]) or "no token") for c in s["api_clients"]]
    lines += [f"User API token of {t['principal']}: {_token_text(t)}" for t in s["user_tokens"]]
    st = s["settings"]
    lines.append(f"Fleet settings: access token {_minutes(st['access_token_ttl_min'])}, API token "
                 f"{_minutes(st['api_token_ttl_min'])}, retention {_minutes(st['api_token_retention_min'])}, "
                 f"all-users group {'on' if st['all_users_group'] else 'off'}")
    lines += org_report(s)
    for v in s["vcenters"]:
        through = f"{v['through']} ({v['broker_kind']})" if v["through"] else "no default provider"
        sups = "; ".join(f"Supervisor {x['name']}: {', '.join(i or '?' for i in x['issuers']) or 'no provider'}"
                         for x in v["supervisors"])
        lines.append(f"vCenter {v['vcenter']} signs in through {through}" + (f"; {sups}" if sups else ""))
    if s["egress"]:
        got = ", ".join(f"{r['broker']} {r['status'] or 'no answer'}" for r in s["egress"]["reached"])
        lines.append(f"Egress (each broker fetched the metadata URL): {got}; identity plane "
                     + ("unchanged" if s["egress"]["unchanged"] else "CHANGED, see the record"))
    return lines


# ── the record contract: every estate value replaced, or nothing written ─────────────────────────────────────────
# Product vocabulary is never registered, so it is never replaced and never mistaken for a surviving value. It is
# matched without regard to case (vCenter spells its OIDC config tag "Oidc"), and it includes every way in, protocol,
# kind and type the census prints: a type is not an identity.
PRODUCT = {w.lower() for w in (
    "CUSTOMER", "System", "admin", "Administrator", "Administrators", "default", "vsphere.local", "localos",
    "login.microsoftonline.com", "graph.microsoft.com",
    "Automation Appliance", "Operations Appliance", "VCF Operations for Networks", "VCF Operations for Logs",
    "oidc", "saml", "ldap", "ldaps", "ldap_bind", "vcf-sso", "oidc-broker", "ldap-system", "ldap-custom", "local",
    "classic", "all-apps", "instance", "embedded", "external", "broker", "entra", "other", "unknown",
    "adldap", "openldap", "entra_id", "okta", "ping", "adfs", "symantec_idsp", "jit", "scim",
    "active_directory_ldap")}
# Fields whose value is an estate value of a known kind; anything shaped like one, anywhere, is registered too.
FIELDS = {"fqdn": "host", "host": "host", "domainControllerHost": "host", "ldapHost": "host", "issuerHost": "host",
          "discoveryHost": "host", "metadataHost": "host", "redirectHosts": "host", "vcenter": "host",
          "id": "id", "vcfInstanceId": "id", "vidbResourceId": "id", "idpId": "id", "ssoRealmId": "id", "realmId": "id",
          "ldapConfigurationId": "id", "vcfComponentId": "id", "clientUuid": "id", "supervisor": "id",
          "name": "name", "displayName": "name", "display_name": "name", "clientName": "name", "clientId": "name",
          "apiClientId": "name", "tokenName": "name", "principalName": "name", "certificateName": "name",
          "domains": "domain", "defaultDomain": "domain", "domain_names": "domain", "baseDn": "dn", "bindDn": "dn",
          "roleName": "role", "broker_tenant": "name", "broker_hosts_given": "host"}
PATTERNS = [("id", re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")),
            ("host", re.compile(r"\b[a-z0-9-]+(?:\.[a-z0-9-]+)+\.[a-z]{2,}\b", re.I)),
            ("ip", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
            ("name", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)*\b"))]
NOT_SHAPED = {"version"}  # a version string is shaped like an address and is not one
PLACEHOLDER = re.compile(r"\{\{[a-z-]+-\d+\}\}")
OWN = re.compile(f"({PLACEHOLDER.pattern})")  # splits a text into what lies outside the placeholders and each one


def _strings(obj: object, field: str | None = None):
    """Every (field, string) in a record, the field being the key the string sits under."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _strings(v, k)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v, field)
    elif isinstance(obj, str):
        yield field, obj


def estate_values(record: dict, given: list[tuple[str, str]]) -> dict[str, str]:
    """Each estate value in the record, and each the reader was given (hosts, a user, the metadata URL), mapped to
    its placeholder. Organizations first, then by field, then anything shaped like an id, host, address or user."""
    table, seen, count = {}, set(), Counter()
    built_in = {str(r.get("roleName")).lower() for r in (record.get("fleet") or {}).get("roles") or [] if r.get("type") == "BUILT_IN"}
    spare = PRODUCT | built_in

    def add(value: str, kind: str) -> None:
        if value and len(value) >= 3 and value.lower() not in spare and value.lower() not in seen:
            seen.add(value.lower())
            count[kind] += 1
            table[value] = f"{{{{{kind}-{count[kind]}}}}}"

    for o in record.get("organizations") or []:
        add(o.get("name"), "org")
    for value, kind in given:
        add(value, kind)
    for part in ("fleet", "organizations", "vcenters", "egress", "calls", "summary"):
        for field, s in _strings(record.get(part)):
            if field in FIELDS:
                add(s, FIELDS[field])
    for field, s in _strings(record):
        if field not in NOT_SHAPED:
            for kind, rx in PATTERNS:
                for m in rx.findall(s):
                    add(m, kind)
    return table


def _pattern(table: dict) -> re.Pattern | None:
    """One alternation, longest first, matched only where it is not part of a longer word."""
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
    return lambda text: "".join(part if i % 2 else rx.sub(lambda m: label[m.group(0).lower()], part)
                                for i, part in enumerate(OWN.split(text)))


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
    """The kind of every estate value still in a scrubbed record: a registered one, anything shaped like one, or a
    value under an identity field that is not a placeholder, so a value the registration missed is caught too."""
    rx, found = _pattern(table), []
    kind_of = {k.lower(): v.strip("{}").rsplit("-", 1)[0] for k, v in table.items()}
    roles = (obj.get("fleet") or {}).get("roles") or [] if isinstance(obj, dict) else []
    spare = PRODUCT | {str(r.get("roleName")).lower() for r in roles if r.get("type") == "BUILT_IN"}
    for field, s in _strings(obj):
        rest = PLACEHOLDER.sub(" ", s)  # a placeholder's own letters are not a surviving value
        found += [kind_of[m.group(0).lower()] for m in rx.finditer(rest)] if rx else []
        if field not in NOT_SHAPED:
            found += [kind for kind, p in PATTERNS for m in p.findall(rest) if m.lower() not in PRODUCT]
        if field in FIELDS and len(s) >= 3 and s.lower() not in spare and re.search(r"[A-Za-z0-9]", rest):
            found.append(FIELDS[field])
    return found


# ── the run ──────────────────────────────────────────────────────────────────────────────────────────────────────
def fingerprint_clients(fleet_read: dict, key: bytes) -> None:
    """Give each API client the keyed fingerprints of its id and its name, in place, before the scrub replaces both."""
    for c in fleet_read.get("clients") or []:
        for a in c.get("api_clients") or []:
            names = [str(a[k]) for k in ("clientId", "clientName") if a.get(k)]
            a["fingerprints"] = sorted({fingerprint(n, key) for n in names})


def census(egress_url: str | None, ops_token: str | None, vcfa_token: str | None, orgs_only: bool = False,
           key: bytes | None = None) -> dict:
    """Read every plane the environment names; the egress check, when asked, runs straight after the fleet read. With
    orgs_only, VCF Automation alone is read, on the provider credential, and no other plane is called."""
    calls: list = []
    record = {"captured": replay_now().strftime("%Y-%m-%dT%H:%M:%SZ"), "sent": [], "fleet": {},
              "organizations": [], "vcenters": [], "egress": None, "calls": calls, "broker_tenant": broker_tenant()}
    if REPLAY is not None:  # answered from a recorded set: a tool reading the record must not take it for a read
        record["replay"] = True
    if orgs_only:
        record["orgs_only"] = True
        record["broker_hosts_given"] = given_brokers()
        vcfa = Reader("vcf-automation", f"https://{os.environ['VCFA_HOST']}", {"Authorization": f"Bearer {vcfa_token}"}, calls)
        record["organizations"] = organizations(vcfa)
        record["summary"] = summary(record)
        record["exit"] = EXIT_UNREAD if failed(calls) or unplaced_issuers(record["summary"]) else 0
        return record
    ops = Reader("vcf-operations", f"https://{os.environ['OPS_HOST']}/suite-api", {"Authorization": f"Bearer {ops_token}"}, calls)
    record["fleet"] = fleet(ops)
    if key:
        fingerprint_clients(record["fleet"], key)
        record["fingerprint_key_check"] = key_check(key)
    if egress_url:
        record["sent"].append("POST /suite-api/api/fleet-management/iam/saml-metadata/validate, once per broker")
        record["egress"] = reach(ops, record["fleet"], egress_url)
    if vcfa_token:
        vcfa = Reader("vcf-automation", f"https://{os.environ['VCFA_HOST']}", {"Authorization": f"Bearer {vcfa_token}"}, calls)
        record["organizations"] = organizations(vcfa)
    hosts = [h.strip() for h in os.environ.get("VC_HOSTS", "").split(",") if h.strip()]
    if hosts:
        record["sent"].append("POST and DELETE /api/session on each vCenter: a session opened and closed")
    for host in hosts:
        vc = vc_session(host, os.environ["VC_USER"], _secret("VC_PASSWORD"), calls)
        if vc:
            record["vcenters"].append(vcenter(vc, host))
            vc.call("DELETE", "/api/session")
    record["summary"] = summary(record)
    record["exit"] = EXIT_UNREAD if failed(calls) else 0
    return record


def failed(calls: list[dict]) -> list[dict]:
    """The calls that did not read: no answer, a refusal, or an answer without what the read needs (`shape`)."""
    return [c for c in calls if c["status"] is None or c["status"] >= 400 or c.get("shape")]


CREDENTIAL_SECRETS = ("OPS_API_TOKEN", "API_TOKEN", "OPS_BEARER", "VCFA_PROVIDER_BEARER", "VCFA_PROVIDER_REFRESH_TOKEN",
                      "VC_PASSWORD")


def credential_problem() -> str | None:
    """A credential the run was given but cannot use, found before anything is sent: a NAME_FILE that cannot be read,
    holds nothing or is open to group or other (refused unread, with the fix), or VC_HOSTS without VC_USER and a
    password. A usage error (exit 5), never a failed read."""
    for name in CREDENTIAL_SECRETS:
        if os.environ.get(f"{name}_FILE"):
            try:
                if not _secret(name):
                    return f"{name}_FILE is empty"
            except (OSError, UnicodeDecodeError) as e:   # the refusal (no errno) names the variable and the fix
                refused = isinstance(e, PermissionError) and e.errno is None
                return str(e) if refused else f"{name}_FILE could not be read: {type(e).__name__}"
    if os.environ.get("VC_HOSTS", "").strip() and not (os.environ.get("VC_USER") and _secret("VC_PASSWORD")):
        return "VC_HOSTS needs VC_USER and VC_PASSWORD_FILE (or VC_PASSWORD)"
    return None


def unread(bad: list[dict]) -> str | None:
    """A refused fleet read leaves its lines counting nothing (0 brokers, no emergency client), and a list read in part
    counts only its first pages. Said first, so a count is never read as the estate's when the identity plane did not
    answer it whole. The role sentence is printed only when a read was refused."""
    fleet = [c for c in bad if c.get("plane") == "vcf-operations"]
    if not fleet:
        return None
    refused = any(c.get("status") in (401, 403) for c in fleet)
    return (f"NOT READ: {len(fleet)} fleet identity read(s) refused, failed or read in part; a line below that counts "
            "from one is unread, not the estate's (the FAILED lines name each)."
            + (" The credential's role must read the fleet identity plane." if refused else ""))


def given_brokers() -> list[str]:
    """The brokers' hosts the reader named in BROKER_HOSTS, for --orgs-only, which reads no broker itself."""
    return sorted({h.strip().lower() for h in os.environ.get("BROKER_HOSTS", "").split(",") if h.strip()})


def given_values(egress_url: str | None) -> list[tuple[str, str]]:
    hosts = [os.environ.get(k, "") for k in ("OPS_HOST", "OPS_BROKER_HOST", "BROKER_HOST", "VCFA_HOST")]
    hosts += os.environ.get("VC_HOSTS", "").split(",") + os.environ.get("BROKER_HOSTS", "").split(",")
    out = [(h.strip(), "host") for h in hosts if h.strip()]
    out += [(os.environ.get("VC_USER", ""), "name")] + ([(egress_url, "metadata-url")] if egress_url else [])
    return [(v, k) for v, k in out if v]


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
    """The run, with two guards around it: a Python older than 3.10 is refused (exit 5) before anything is read, and an
    error the script did not expect exits 3, the code for a read that failed."""
    if sys.version_info < (3, 10):  # noqa: UP036  the script is run by readers on their own Python
        print("census.py needs Python 3.10 or later", file=sys.stderr)
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
    ap = _Parser(description="Read a VCF 9.1 estate's identity model, read-only by default.")
    ap.add_argument("--redact", action="store_true", help="print with placeholders instead of your names")
    ap.add_argument("--egress-metadata-url", metavar="URL",
                    help="ask each broker to fetch this SAML metadata URL (sends one request per broker)")
    ap.add_argument("--orgs-only", action="store_true",
                    help="read only VCF Automation's organizations, on VCFA_HOST and a provider credential alone")
    ap.add_argument("--replay", metavar="DIR",
                    help="answer every request from the recorded set in DIR (replay/census beside this script is "
                         "one): nothing is sent and no credential is read")
    a = ap.parse_args(argv)
    if a.replay:
        try:
            replay_start(a.replay)
        except (OSError, ValueError) as e:
            print(f"--replay {a.replay}: {e}; nothing was sent", file=sys.stderr)
            return EXIT_USAGE
    problem = credential_problem()
    if problem:
        print(f"{problem}; nothing was sent", file=sys.stderr)
        return EXIT_USAGE
    if os.environ.get("OPS_REALM") and not os.environ.get("BROKER_TENANT"):
        print("note: OPS_REALM is now BROKER_TENANT (the broker tenant, the realm's path segment at the broker, CUSTOMER by "
              "default, which is not the realm's name); reading OPS_REALM this time.", file=sys.stderr)
    vcfa_cred = bool(os.environ.get("VCFA_PROVIDER_BEARER_FILE") or os.environ.get("VCFA_PROVIDER_REFRESH_TOKEN_FILE")
                     or _secret("VCFA_PROVIDER_REFRESH_TOKEN"))
    if a.orgs_only:
        if a.egress_metadata_url:
            print("--orgs-only reads VCF Automation alone; --egress-metadata-url asks the brokers, so the two do not combine",
                  file=sys.stderr)
            return EXIT_USAGE
        if not os.environ.get("VCFA_HOST") or not vcfa_cred:
            print("--orgs-only needs VCFA_HOST and a provider credential (VCFA_PROVIDER_BEARER_FILE or "
                  "VCFA_PROVIDER_REFRESH_TOKEN_FILE); no VCF Operations credential is read", file=sys.stderr)
            return EXIT_USAGE
        if not given_brokers():
            print("--orgs-only needs BROKER_HOSTS, every broker's host (the instance broker and each management "
                  "vCenter's embedded one): it reads no broker, so without them an organization on a broker would read "
                  "as on a provider of its own, and the census would pass", file=sys.stderr)
            return EXIT_USAGE
    elif not os.environ.get("OPS_HOST") or not (os.environ.get("OPS_BEARER_FILE") or (_secret("OPS_API_TOKEN") or _secret("API_TOKEN"))):
        print("OPS_HOST and a VCF Operations credential (OPS_API_TOKEN_FILE or OPS_BEARER_FILE) are required; "
              "--orgs-only reads the organizations on a VCF Automation provider credential alone", file=sys.stderr)
        return EXIT_USAGE
    if a.egress_metadata_url:
        print("--egress-metadata-url: each broker will be asked to fetch the URL; this sends a request per broker")
    try:
        key = None if a.orgs_only else fingerprint_key()
    except (OSError, ValueError) as e:
        print(f"{e}; nothing was sent" if isinstance(e, PermissionError) and e.errno is None
              else f"FINGERPRINT_KEY_FILE could not be read: {type(e).__name__}", file=sys.stderr)
        return EXIT_USAGE
    try:
        ops_token = None if a.orgs_only else ops_bearer()
        vcfa_token = vcfa_bearer(os.environ["VCFA_HOST"]) if os.environ.get("VCFA_HOST") else None
    except (urllib.error.URLError, OSError, KeyError, ValueError) as e:
        print(f"could not obtain a credential: {type(e).__name__} {getattr(e, 'code', '')}".rstrip()
              + ("; if the estate has no realm yet, there is no API client or VCF single sign-on user to make the token "
                 "for, so read it with --orgs-only and vcenter-authorization's authz.py --no-realm first" if not a.orgs_only else ""),
              file=sys.stderr)
        return EXIT_UNREAD
    record = census(a.egress_metadata_url, ops_token, vcfa_token, orgs_only=a.orgs_only, key=key)
    bad = failed(record["calls"])
    table = estate_values(record, given_values(a.egress_metadata_url))
    clean = scrub({**record, "calls": [{k: v for k, v in c.items() if k != "message"} for c in record["calls"]]}, table)
    left = leaks(clean, table)
    out = os.environ.get("OUT") or ("census.replay.json" if REPLAY is not None else "census.json")
    if not (left and a.redact):  # a redacted print with a surviving value would print that value
        shown = clean if a.redact else record
        lines = org_report(shown["summary"]) or ["Organizations: none read"] if a.orgs_only else report(shown["summary"])
        print("\n".join(([unread(bad)] if unread(bad) else []) + lines))
        for c, shown_call in zip(bad, failed(shown["calls"])):
            print(f"FAILED {shown_call['plane']} {c['method']} {shown_call['path']}: {c['status'] or ''} "
                  f"{c.get('error') or c.get('shape') or ''} {'' if a.redact else c.get('message') or ''}".rstrip())
    if left:   # not a usage error: the run read, and its record could not be written, so nothing is known from it
        print(f"refusing to write {out}: {len(left)} estate value(s) survived the scrub ({', '.join(sorted(set(left)))}); "
              f"{out} not written, exit {EXIT_UNREAD}: a tool that reads the record has nothing to read", file=sys.stderr)
        return EXIT_UNREAD
    with open(out, "w", encoding="utf-8") as f:
        f.write(json.dumps(clean, indent=1, ensure_ascii=False) + "\n")
    print(f"\n{len(record['calls'])} call(s), {len(bad)} failed; {out} written with every estate value replaced")
    return record["exit"]


if __name__ == "__main__":
    sys.exit(main())
