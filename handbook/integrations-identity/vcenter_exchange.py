#!/usr/bin/env python3
"""vcenter_exchange.py - a VCF SSO API client into vCenter, and who else signs in there. Read-only.

Under VCF single sign-on a vCenter does not take the broker's bearer as presented. The API client's API token is
traded at the broker for a bearer, the bearer is exchanged at vCenter for a SAML token that lives minutes, and the
SAML token opens a REST session (an Authorization header of the SIGN scheme) or a SOAP session (LoginByToken). This
script makes the exchange on each vCenter, opens and closes one session of each kind, and records who the session
is. With --sessions it then reads each vCenter's session list as an administrator and groups every session by the
kind of principal and its client agent, so an integration still signing in as a person's directory account shows
up beside the machine identities.

  1. the bearer as presented     GET  /api/vcenter/datacenter                      (refused, the expected answer)
  2. the exchange                POST /api/vcenter/authentication/token            (form; the access token alone)
  3. a REST session              POST /api/session   Authorization: SIGN token="<base64(gzip(assertion))>"
  4. a SOAP session              SessionManager.LoginByToken, the assertion in a WS-Security header
  5. --sessions                  SessionManager.sessionList, read as VC_USER, the census's own session left out

It opens sessions and closes them, and changes no configuration. No token, assertion, password, address, session
key or login time is printed or recorded.

Env:  BROKER_HOST                 the identity broker that trades the API client's token for a bearer
      BROKER_REALM                the broker's realm path segment (default CUSTOMER)
      API_TOKEN_FILE              the API client's API token (mode 0600); API_TOKEN is read if it is unset
      BEARER_FILE                 instead, a broker bearer you already hold
      VC_HOSTS                    comma-separated vCenter FQDNs
      VC_USER, VC_PASSWORD_FILE   for --sessions: an account that may read the session list, user@domain (mode 0600;
                                  VC_PASSWORD is read if it is unset)
      DIRECTORY_DOMAINS           for --sessions: the directory domains as vCenter spells them, comma-separated
      REALM_DOMAIN                the realm's domain as a session spells it (default CUSTOMER)
      LOCAL_DOMAIN                the vCenter's own SSO domain (default VSPHERE.LOCAL)
      TLS_VERIFY=false            only on a self-signed lab CA
      OUT                         the record (default exchange.json)
Use:  python3 vcenter_exchange.py [--sessions] [--redact]
Exit: 0 every vCenter took the client through both sessions, and with --sessions no directory account signs in from
      a vSphere SDK · 1 a vCenter refused the client, or a read failed · 2 a usage error, or the record was refused
      because an estate value survived the scrub · 3 --sessions found a directory account signing in from a vSphere SDK
"""

from __future__ import annotations

import argparse
import base64
import gzip
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
from datetime import datetime, timezone

AGENT = "vcenter_exchange.py"
API_TOKEN_GRANT = "urn:custom:vcf:params:oauth:grant-type:api-token"
EXCHANGE = {"grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
            "requested_token_type": "urn:ietf:params:oauth:token-type:saml2"}
SOAPENV = "http://schemas.xmlsoap.org/soap/envelope/"
WSSE = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"
VIM = "urn:vim25"
# Client agents that name a vSphere SDK. A directory account signing in from one is an integration, not a person at a
# browser; the list is the SDKs seen on the reference estate's session lists plus PowerCLI and rbvmomi.
SDK_MARKERS = ("pyvmomi", "govmomi", "vim-java", "XML-WS", "PowerCLI", "rbvmomi")


# ── HTTP, standard library only ──────────────────────────────────────────────────────────────────────────────────
def _ctx() -> ssl.SSLContext:
    verify = os.environ.get("TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")
    return ssl.create_default_context() if verify else ssl._create_unverified_context()


def _secret(name: str) -> str:
    path = os.environ.get(f"{name}_FILE")
    if path:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    return os.environ.get(name, "")


def _open(req: urllib.request.Request, opener=None, timeout: int = 60) -> tuple[int, bytes]:
    """(status, body) for any answer, a refusal included; (0, b"") when the host did not answer."""
    try:
        r = (opener.open(req, timeout=timeout) if opener else urllib.request.urlopen(req, context=_ctx(), timeout=timeout))
        with r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read() or b""
    except (urllib.error.URLError, OSError):
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
    if os.environ.get("BEARER_FILE"):
        return _secret("BEARER").removeprefix("Bearer ").strip()
    realm = os.environ.get("BROKER_REALM", "CUSTOMER")
    status, answer = _form(f"https://{os.environ['BROKER_HOST']}/acs/t/{realm}/token",
                           {"grant_type": API_TOKEN_GRANT, "api_token": _secret("API_TOKEN")})
    if status != 200 or "access_token" not in answer:
        # a deleted or rotated API token answers 500 here, not 401: check the token still exists before its expiry
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
    out["vm_list_status"], _ = _open(urllib.request.Request(f"https://{host}/api/vcenter/vm", headers=h))
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

    def sessions(self) -> tuple[list[dict], str | None]:
        """Every session's principal and client agent, and this session's key so the census can leave itself out.
        Keys stay in memory; addresses and login times are never read."""
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
                    rows.append({"key": s.findtext(f"{{{VIM}}}key"), "user": s.findtext(f"{{{VIM}}}userName") or "",
                                 "agent": s.findtext(f"{{{VIM}}}userAgent") or ""})
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


def classify(principal: str, realm: str, directories: set[str], local: str) -> str:
    """The kind of principal a session holds, by how it signs in under VCF single sign-on."""
    domain, _, name = principal.rpartition("\\")
    d = domain.upper()
    if d == realm.upper():
        return "api client"            # a VCF SSO API client's session reads <realm>\<client id>
    if d in directories:
        return "directory"             # a person or an integration signing in through the broker
    if d == local.upper():
        if name.lower() == "administrator":
            return "local administrator"
        return "local, VCF integration account" if name.lower().startswith("svc-") else "local, other"
    return "another provider"


def census(rows: list[dict], mine: str | None, realm: str, directories: set[str], local: str) -> dict:
    """Sessions by class; the local administrator by agent; each directory principal with its agents. No local
    principal is named, because a local account's name can carry estate values."""
    by_class, admin, dirs, clients = Counter(), Counter(), {}, set()
    for r in rows:
        if r["key"] == mine:
            continue
        cls, agent = classify(r["user"], realm, directories, local), agent_of(r["agent"])
        by_class[cls] += 1
        if cls == "local administrator":
            admin[agent] += 1
        elif cls == "directory":
            dirs.setdefault(r["user"], Counter())[agent] += 1
        elif cls == "api client":
            clients.add(r["user"])
    return {"sessions": sum(by_class.values()), "by_class": dict(sorted(by_class.items())),
            "local_administrator_by_agent": dict(sorted(admin.items())),
            "directory": [{"principal": p, "agents": dict(sorted(a.items())),
                           "sdk": any(m.lower() in ag.lower() for ag in a for m in SDK_MARKERS)}
                          for p, a in sorted(dirs.items())],
            "api_clients": len(clients), "own_session_left_out": mine is not None}


def read_sessions(host: str, user: str, password: str, realm: str, directories: set[str], local: str) -> dict:
    s = Soap(host)
    if not s.session_manager or not s.login(user, password):
        return {"error": s.fault or f"HTTP {s.status}"}
    try:
        rows, mine = s.sessions()
        if s.fault:
            return {"error": s.fault}
        return census(rows, mine, realm, directories, local)
    finally:
        s.logout()


# ── the record ───────────────────────────────────────────────────────────────────────────────────────────────────
def summary(record: dict) -> dict:
    """The lines the run exists for: per vCenter, whether the client got both sessions and who it was; with
    --sessions, the census by class and every directory principal signing in from a vSphere SDK."""
    vcs = record.get("vcenters") or []
    took = [v for v in vcs if (v.get("rest") or {}).get("status") == 201 and (v.get("soap") or {}).get("user")]
    sessions = [v for v in vcs if isinstance(v.get("sessions"), dict) and "by_class" in v["sessions"]]
    return {
        "vcenters": len(vcs),
        "client_took_both_sessions": len(took),
        "bearer_as_presented": sorted({v.get("bearer_as_presented") for v in vcs}, key=str),
        "saml_lifetime_s": sorted({(v.get("exchange") or {}).get("expires_in_s") for v in vcs} - {None}),
        "session_users": sorted({u for v in vcs for u in ((v.get("rest") or {}).get("user"), (v.get("soap") or {}).get("user")) if u}),
        "sessions_read": len(sessions),
        "sessions_by_class": dict(sorted(sum((Counter(v["sessions"]["by_class"]) for v in sessions), Counter()).items())),
        "local_administrator_by_agent": dict(sorted(sum((Counter(v["sessions"]["local_administrator_by_agent"])
                                                         for v in sessions), Counter()).items())),
        "directory_principals": sorted({d["principal"] for v in sessions for d in v["sessions"]["directory"]}),
        "directory_from_sdk": sorted({d["principal"] for v in sessions for d in v["sessions"]["directory"] if d["sdk"]}),
    }


def report(record: dict) -> list[str]:
    lines = []
    for v in record["vcenters"]:
        ex, rest, soap = v.get("exchange") or {}, v.get("rest") or {}, v.get("soap") or {}
        lines.append(f"vCenter {v['vcenter']}")
        lines.append(f"  the bearer as presented: HTTP {v['bearer_as_presented']}")
        lines.append(f"  exchange: HTTP {ex.get('status')}, {ex.get('issued_token_type') or 'no token'}"
                     + (f", {ex.get('token_type')}, lives {ex.get('expires_in_s')} s" if ex.get("status") == 200 else ""))
        lines.append(f"  REST session (SIGN): HTTP {rest.get('status')}" + (f", user {rest.get('user')}, VM list HTTP "
                                                                             f"{rest.get('vm_list_status')}" if rest.get("user") else ""))
        lines.append("  SOAP session (LoginByToken): " + (f"user {soap['user']}" if soap.get("user") else f"refused: {soap.get('fault')}"))
        s = v.get("sessions")
        if isinstance(s, dict) and "by_class" in s:
            lines.append(f"  sessions ({s['sessions']}, this census's own left out): "
                         + ", ".join(f"{k} {n}" for k, n in s["by_class"].items()))
            if s["local_administrator_by_agent"]:
                lines.append("    local administrator by agent: " + ", ".join(f"{a} {n}" for a, n in s["local_administrator_by_agent"].items()))
            for d in s["directory"]:
                lines.append(f"    directory {d['principal']}: " + ", ".join(f"{a} {n}" for a, n in d["agents"].items())
                             + ("  SIGNS IN FROM A vSPHERE SDK" if d["sdk"] else ""))
        elif isinstance(s, dict):
            lines.append(f"  sessions not read: {s.get('error')}")
    sm = record["summary"]
    lines.append(f"The client took both sessions on {sm['client_took_both_sessions']} of {sm['vcenters']} vCenter(s)")
    if sm["sessions_read"]:
        lines.append(f"Directory accounts signing in from a vSphere SDK: {len(sm['directory_from_sdk'])}")
    return lines


# ── the record contract: every estate value replaced, or nothing written ─────────────────────────────────────────
PRODUCT = {"customer", "vsphere.local", "administrator", "(none)"}
PATTERNS = [("id", re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")),
            ("host", re.compile(r"\b[a-z0-9-]+(?:\.[a-z0-9-]+)+\.[a-z]{2,}\b", re.I)),
            ("ip", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
            ("name", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)*\b"))]
NOT_SHAPED = {"issued_token_type", "token_type"}


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
            add(name, "client" if domain.upper() == os.environ.get("REALM_DOMAIN", "CUSTOMER").upper() else "name")
    for field, s in _strings(record):
        if field not in NOT_SHAPED:
            for kind, rx in PATTERNS:
                for m in rx.findall(s):
                    add(m, kind)
    return table


def scrub(obj, table: dict):
    if not table:
        return obj
    rx = re.compile(r"(?<![A-Za-z0-9])(?:" + "|".join(re.escape(v) for v in sorted(table, key=len, reverse=True))
                    + r")(?![A-Za-z0-9])", re.I)
    lower = {k.lower(): v for k, v in table.items()}
    if isinstance(obj, dict):
        return {scrub(k, table): scrub(v, table) for k, v in obj.items()}
    if isinstance(obj, list):
        return [scrub(v, table) for v in obj]
    return rx.sub(lambda m: lower[m.group(0).lower()], obj) if isinstance(obj, str) else obj


def leaks(obj, table: dict) -> list[str]:
    found = []
    lower = {k.lower() for k in table}
    for field, s in _strings(obj):
        found += [k for k in lower if re.search(r"(?<![A-Za-z0-9])" + re.escape(k) + r"(?![A-Za-z0-9])", s, re.I)]
        if field not in NOT_SHAPED:
            found += [kind for kind, p in PATTERNS for m in p.findall(s) if m.lower() not in PRODUCT]
    return found


# ── the run ──────────────────────────────────────────────────────────────────────────────────────────────────────
def run(with_sessions: bool) -> dict:
    hosts = [h.strip() for h in os.environ.get("VC_HOSTS", "").split(",") if h.strip()]
    bearer = broker_bearer()
    realm = os.environ.get("REALM_DOMAIN", "CUSTOMER")
    directories = {d.strip().upper() for d in os.environ.get("DIRECTORY_DOMAINS", "").split(",") if d.strip()}
    local = os.environ.get("LOCAL_DOMAIN", "VSPHERE.LOCAL")
    record = {"captured": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "sent": ["POST /acs/t/<realm>/token at the broker (unless BEARER_FILE)",
                       "per vCenter: POST /api/vcenter/authentication/token, REST and SOAP sessions opened and closed"]
              + (["per vCenter: a SOAP session as VC_USER, opened and closed"] if with_sessions else []),
              "vcenters": []}
    for host in hosts:
        status, _ = _open(urllib.request.Request(f"https://{host}/api/vcenter/datacenter",
                                                 headers={"Authorization": f"Bearer {bearer}", "User-Agent": AGENT}))
        row = {"vcenter": host, "bearer_as_presented": status}
        row["exchange"], assertion = exchange(host, bearer)
        row["rest"] = rest_session(host, assertion) if assertion else {"status": None}
        _, second = exchange(host, bearer)   # a second assertion for SOAP: one may not open two sessions
        row["soap"] = soap_session(host, second) if second else {"status": None}
        if with_sessions:
            row["sessions"] = read_sessions(host, os.environ["VC_USER"], _secret("VC_PASSWORD"), realm, directories, local)
        record["vcenters"].append(row)
    record["summary"] = summary(record)
    record["exit"] = exit_code(record)
    return record


def exit_code(record: dict) -> int:
    """1 when a vCenter refused the client or a read failed; else 3 when a directory account signs in from a vSphere
    SDK; else 0. A scheduler reads it."""
    vcs = record["vcenters"]
    refused = [v for v in vcs if not ((v.get("rest") or {}).get("status") == 201 and (v.get("soap") or {}).get("user"))]
    unread = [v for v in vcs if isinstance(v.get("sessions"), dict) and "error" in v["sessions"]]
    if refused or unread or not vcs:
        return 1
    return 3 if record["summary"]["directory_from_sdk"] else 0


def given_values() -> list[tuple[str, str]]:
    out = [(h.strip(), "host") for h in os.environ.get("VC_HOSTS", "").split(",") if h.strip()]
    out += [(os.environ.get("BROKER_HOST", ""), "host"), (os.environ.get("VC_USER", ""), "name")]
    out += [(d.strip(), "domain") for d in os.environ.get("DIRECTORY_DOMAINS", "").split(",") if d.strip()]
    return [(v, k) for v, k in out if v]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="A VCF SSO API client into vCenter, and who else signs in there. Read-only.")
    ap.add_argument("--sessions", action="store_true", help="read each vCenter's session list as VC_USER")
    ap.add_argument("--redact", action="store_true", help="print with placeholders instead of your names")
    a = ap.parse_args(argv)
    if not os.environ.get("VC_HOSTS") or not (os.environ.get("BEARER_FILE") or
                                              (os.environ.get("BROKER_HOST") and _secret("API_TOKEN"))):
        print("VC_HOSTS and the API client's credential (BROKER_HOST with API_TOKEN_FILE, or BEARER_FILE) are required",
              file=sys.stderr)
        return 2
    if a.sessions and not (os.environ.get("VC_USER") and _secret("VC_PASSWORD")):
        print("--sessions needs VC_USER and VC_PASSWORD_FILE", file=sys.stderr)
        return 2
    try:
        record = run(a.sessions)
    except (RuntimeError, urllib.error.URLError, OSError) as e:
        print(f"could not start: {e}", file=sys.stderr)
        return 1
    table = estate_values(record, given_values())
    clean = scrub(record, table)
    clean["summary"] = summary(clean)
    left = leaks(clean, table)
    out = os.environ.get("OUT", "exchange.json")
    if not (left and a.redact):  # a redacted print with a surviving value would print that value
        print("\n".join(report(clean if a.redact else record)))
    if left:
        print(f"refusing to write {out}: {len(left)} estate value(s) survived the scrub", file=sys.stderr)
        return 2
    with open(out, "w", encoding="utf-8") as f:
        f.write(json.dumps(clean, indent=1, ensure_ascii=False) + "\n")
    print(f"\n{out} written with every estate value replaced; exit {record['exit']}")
    return record["exit"]


if __name__ == "__main__":
    sys.exit(main())
