#!/usr/bin/env python3
"""hostlife.py: both declarations of every cluster, read in one command, and the order to move an estate off the legacy.

A host in a vSphere Lifecycle Manager cluster is meant to be two declarations: the cluster's image says what software
it runs (a base image, a vendor add-on, a firmware and drivers add-on, components) and, where the cluster has
vSphere Configuration Profiles, the configuration document says how it is set. This script reads both, for every
cluster of every vCenter you name, with the stored results that say whether the hosts still match them:

  1. the IMAGE: whether the cluster is managed with an image at all, its parts, and the stored image compliance;
  2. the CONFIGURATION: whether Configuration Profiles is enabled, when it was enabled (its audit records), the
     document's sections, and the stored compliance with, for every drifted item, its path and its non-identifying
     fields only (a protocol and a port, never a host name or an address);
  3. what feeds and surrounds them: the depots, the newest base image the depot holds, any hardware support manager,
     any host profile, and the Auto Deploy and Image Builder services;
  4. with --host-builds, what each host RUNS: its version and build read live from the host's own summary, never from
     a stored compliance result, with its connection state and maintenance mode. Each host is named by a keyed
     fingerprint of its hardware UUID (FINGERPRINT_KEY_FILE), so a dated series can join one host across runs while
     the record names none; a UUID that is missing, all zeros, or reported by two hosts never joins.

It also carries plan(), a pure function: given what you answer about your estate, the moves off baselines, host
profiles, Auto Deploy and UMDS, in the order the documentation sets, each marked enforced, documented order or
advised, and flagged where the move cannot be undone. The handbook chapter's planner is a JavaScript twin of it.

READ-ONLY. Every REST call is a GET. The only other requests are signing in and out: a vCenter session opened with
VC_USER and VC_PASSWORD_FILE and closed when the script is done, and, to read host profiles, the vSphere API's own
session the same way, opened and closed. No compliance check, precheck, stage, remediation, export, extract or
service start is ever sent: every compliance figure is the last result vCenter stored, with its own time.

Every credential file is refused, unread, if it is open to group or other.

Run:
  export VC_HOST=<vcenter-fqdn>[,<another-vcenter-fqdn>...]
  export VC_USER=<sso-user>  VC_PASSWORD_FILE=/path/to/password      # mode 0600
         # or, for one vCenter: VC_SESSION_FILE=/path/to/session-id   (mode 0600)
  export TLS_VERIFY=false                                           # only on a self-signed lab CA
  python3 hostlife.py                     # the report; writes out/hostlife.record.json, scrubbed
  python3 hostlife.py --json              # the scrubbed record on stdout instead of the report
  python3 hostlife.py --host-builds       # also each host's running build (or HOST_BUILDS=1); with
         FINGERPRINT_KEY_FILE=/path/to/key   # optional, mode 0600: a secret of your own that keys each host's fingerprint
  python3 hostlife.py --from-record PATH  # the report again, from a record, with no call
  python3 hostlife.py plan --baselines --upgrade --host-profiles   # the ordered moves for your answers

Exit: 0 every cluster read is managed with an image and the stored compliance with each declaration it has is
      compliant · 1 a cluster is still on baselines, or a stored image or configuration compliance is not compliant:
      the alert · 2 a setting is missing, an argument is wrong, or a secret file is open to group or other · 3 a
      sign-in or a read failed · 4 the record refused to write, because an estate value survived the scrub
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import hmac
import http.cookiejar
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

AGENT = "hostlife.py (read-only)"
IPV4 = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
URL = re.compile(r"^([a-z][a-z0-9+.-]*)://([^/:]+)(?::(\d+))?(/.*)?$", re.I)
PLACEHOLDER = re.compile(r"(\{\{[^}]*\}\})")
# A field of a drifted configuration item whose name says it can identify something is withheld: the record keeps its
# name in `withheld` and never its value.
IDENTIFYING = re.compile(r"host|name|addr|ip|fqdn|server|url|uri|user|account|cert|key|thumb|pass|secret|token|"
                         r"domain|path|dn$|mac|serial|uuid|id$", re.I)
COMPLIANT = {"COMPLIANT"}
DRIFTED = {"NON_COMPLIANT", "NOT_COMPLIANT", "INCOMPATIBLE"}
SERVICES = (("Auto Deploy", "rbd"), ("Image Builder", "imagebuilder"), ("vSphere Lifecycle Manager", "vlcm"),
            ("Update Manager", "updatemgr"))


class ReadFailed(Exception):
    """A sign-in or a read the record depends on did not answer."""


class Refused(Exception):
    """The record would carry an estate value; nothing is written."""


# ── credentials and transport ────────────────────────────────────────────────────────────────────────────────────
def read_secret(var: str) -> str:
    """The secret in the file VAR names. A file open to group or other is refused before it is read; the refusal
    names the variable and the fix, never the file's content."""
    with open(os.environ[var], encoding="utf-8") as f:
        mode = os.fstat(f.fileno()).st_mode & 0o777
        # Windows makes the mode from the read-only flag alone, so it has no group or other bits to judge.
        if mode & 0o077 and os.name != "nt":
            raise PermissionError(f"{var} names a file of mode {mode:04o}, open to group or other: "
                                  f'run chmod 600 "${var}" and try again (the file was not read)')
        return f.read().strip()


def ctx() -> ssl.SSLContext:
    verify = os.environ.get("TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")
    return ssl.create_default_context() if verify else ssl._create_unverified_context()


def _open(req: urllib.request.Request, opener=None, timeout: int = 120):
    """(status, headers, body bytes); an HTTP error is an answer, a transport error raises ReadFailed."""
    try:
        r = (opener.open(req, timeout=timeout) if opener else urllib.request.urlopen(req, context=ctx(), timeout=timeout))
        with r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()
    except (urllib.error.URLError, OSError) as e:
        raise ReadFailed(f"{req.full_url.split('/')[2]} did not answer ({type(e).__name__})") from None


def _json(raw: bytes):
    try:
        return json.loads(raw or b"null")
    except ValueError:
        return None


class Vcenter:
    """One vCenter: a REST session for the GETs, and the reads this script makes, kept as (method, path, status)."""

    def __init__(self, host: str, user: str | None = None, password: str | None = None, session: str | None = None):
        self.host, self.user, self.password = host, user, password
        self.calls: list[dict] = []
        self.opened = False
        if session is None:
            basic = base64.b64encode(f"{user}:{password}".encode()).decode()
            st, _, raw = _open(urllib.request.Request(f"https://{host}/api/session", method="POST",
                                                      headers={"Authorization": f"Basic {basic}", "User-Agent": AGENT}))
            self.calls.append({"method": "POST", "path": "/api/session", "status": st, "why": "sign in"})
            if st != 201:
                raise ReadFailed(f"the vCenter sign-in answered {st}")
            session, self.opened = _json(raw), True
        self.session = session

    def get(self, path: str, template: str | None = None):
        """GET /api<path>; the call is recorded by its template (an object id replaced by its kind)."""
        st, _, raw = _open(urllib.request.Request(f"https://{self.host}/api{path}", headers={
            "vmware-api-session-id": self.session, "Accept": "application/json", "User-Agent": AGENT}))
        self.calls.append({"method": "GET", "path": "/api" + (template or path), "status": st})
        return st, _json(raw)

    def close(self) -> None:
        if self.opened:
            st, _, _ = _open(urllib.request.Request(f"https://{self.host}/api/session", method="DELETE",
                                                    headers={"vmware-api-session-id": self.session, "User-Agent": AGENT}))
            self.calls.append({"method": "DELETE", "path": "/api/session", "status": st, "why": "sign out"})
            self.opened = False


def message(body) -> str | None:
    """The first message a vAPI error carries, for the record."""
    if isinstance(body, dict):
        msgs = body.get("messages") or []
        if msgs and isinstance(msgs[0], dict):
            return msgs[0].get("default_message")
        return body.get("error_type")
    return None


# ── host profiles: the vSphere API, read with GETs where the build serves its JSON form ───────────────────────────
def host_profiles(vc: Vcenter) -> dict:
    """The host profiles a vCenter holds. The vSphere API's JSON form (VI/JSON) answers a property read as a GET; its
    own session is opened with VC_USER and closed at once. Where that form is absent the read falls back to SOAP, whose
    property read (RetrievePropertiesEx) is a read carried in a POST, as every SOAP call is."""
    base = f"https://{vc.host}/sdk"
    st, _, raw = _open(urllib.request.Request(f"{base}/vimServiceVersions.xml", headers={"User-Agent": AGENT}))
    vc.calls.append({"method": "GET", "path": "/sdk/vimServiceVersions.xml", "status": st})
    m = re.search(rb"<name>urn:vim25</name>\s*<version>([^<]+)</version>", raw or b"")
    release = m.group(1).decode() if m else None
    if release:
        out = _vi_json(vc, base, release)
        if out is not None:
            return out
    if vc.user is None:
        return {"read": False, "why": "the vSphere API's JSON form did not answer and a session id alone cannot open SOAP"}
    return _soap(vc, base)


def _vi_json(vc: Vcenter, base: str, release: str) -> dict | None:
    """The host profile list through the JSON form: first with the REST session, and only if that is refused with a
    session of its own, opened and closed here. None when the build serves no JSON form."""
    root, tpl = f"{base}/vim25/{release}", "/sdk/vim25/{release}"
    h = {"Accept": "application/json", "User-Agent": AGENT, "vmware-api-session-id": vc.session}

    def get(path: str, template: str):
        st, _, raw = _open(urllib.request.Request(root + path, headers=h))
        vc.calls.append({"method": "GET", "path": tpl + template, "status": st})
        return st, _json(raw)

    st, content = get("/ServiceInstance/ServiceInstance/content", "/ServiceInstance/ServiceInstance/content")
    if st == 404:
        return None
    content = content if st == 200 and isinstance(content, dict) else {}
    hpm = (content.get("hostProfileManager") or {}).get("value") or "HostProfileManager"
    sm = (content.get("sessionManager") or {}).get("value") or "SessionManager"
    st, refs = get(f"/HostProfileManager/{hpm}/profile", "/HostProfileManager/{manager}/profile")
    if st == 404:
        return None
    opened = False
    if st in (401, 403) and vc.user is not None:
        body = json.dumps({"userName": vc.user, "password": vc.password}).encode()
        st_l, hdr, _ = _open(urllib.request.Request(f"{root}/SessionManager/{sm}/Login", data=body, method="POST", headers={
            "Accept": "application/json", "Content-Type": "application/json", "User-Agent": AGENT}))
        vc.calls.append({"method": "POST", "path": tpl + "/SessionManager/{manager}/Login", "status": st_l,
                         "why": "sign in to the vSphere API"})
        sid = hdr.get("vmware-api-session-id") if st_l == 200 and hdr else None
        if not sid:
            return None
        h["vmware-api-session-id"], opened = sid, True
        st, refs = get(f"/HostProfileManager/{hpm}/profile", "/HostProfileManager/{manager}/profile")
    try:
        if st != 200:
            return {"read": False, "via": "vi-json", "why": f"the profile list answered {st}"}
        refs = refs or []
        profiles = []
        for ref in refs if isinstance(refs, list) else []:
            pid = ref.get("value") if isinstance(ref, dict) else None
            if not pid:
                continue
            row = {}
            for prop in ("name", "entity"):
                st, val = get(f"/HostProfile/{pid}/{prop}", "/HostProfile/{profile}/" + prop)
                val = val if st == 200 else None
                row[prop] = val if prop == "name" else (len(val) if isinstance(val, list) else None)
            profiles.append({"name": row.get("name"), "attached_to": row.get("entity")})
        return {"read": True, "via": "vi-json", "count": len(profiles), "profiles": profiles}
    finally:
        if opened:
            st, _, _ = _open(urllib.request.Request(f"{root}/SessionManager/{sm}/Logout", method="POST", headers=h))
            vc.calls.append({"method": "POST", "path": tpl + "/SessionManager/{manager}/Logout", "status": st,
                             "why": "sign out of the vSphere API"})


SOAPENV, VIM = "http://schemas.xmlsoap.org/soap/envelope/", "urn:vim25"


def _soap(vc: Vcenter, base: str) -> dict:
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx()),
                                         urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def call(body: str, why: str):
        env = (f'<?xml version="1.0" encoding="UTF-8"?><soapenv:Envelope xmlns:soapenv="{SOAPENV}">'
               f"<soapenv:Body>{body}</soapenv:Body></soapenv:Envelope>")
        st, _, raw = _open(urllib.request.Request(base, data=env.encode(), method="POST", headers={
            "Content-Type": "text/xml; charset=utf-8", "SOAPAction": "urn:vim25/8.0.0.0", "User-Agent": AGENT}), opener)
        vc.calls.append({"method": "POST", "path": "/sdk", "status": st, "why": why})
        try:
            node = ET.fromstring(raw).find(f"{{{SOAPENV}}}Body")
        except ET.ParseError:
            return None
        return node[0] if node is not None and len(node) and not node[0].tag.endswith("Fault") else None

    esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")  # noqa: E731
    sc = call(f'<RetrieveServiceContent xmlns="{VIM}"><_this type="ServiceInstance">ServiceInstance</_this>'
              "</RetrieveServiceContent>", "read the service content")
    rv = sc.find(f"{{{VIM}}}returnval") if sc is not None else None
    if rv is None:
        return {"read": False, "via": "soap", "why": "the service content did not answer"}
    sm, pc, hpm = (rv.findtext(f"{{{VIM}}}{k}") for k in ("sessionManager", "propertyCollector", "hostProfileManager"))
    if call(f'<Login xmlns="{VIM}"><_this type="SessionManager">{sm}</_this><userName>{esc(vc.user)}</userName>'
            f"<password>{esc(vc.password)}</password></Login>", "sign in to the vSphere API") is None:
        return {"read": False, "via": "soap", "why": "the vSphere API sign-in was refused"}
    try:
        r = call(f'<RetrievePropertiesEx xmlns="{VIM}"><_this type="PropertyCollector">{pc}</_this><specSet><propSet>'
                 f"<type>HostProfileManager</type><pathSet>profile</pathSet></propSet><objectSet><obj "
                 f'type="HostProfileManager">{hpm}</obj></objectSet></specSet><options/></RetrievePropertiesEx>',
                 "read the host profile list")
        if r is None:
            return {"read": False, "via": "soap", "why": "the property read did not answer"}
        refs = [e.text for e in r.iter(f"{{{VIM}}}ManagedObjectReference")]
        return {"read": True, "via": "soap", "count": len(refs), "profiles": [{"name": None, "attached_to": None}] * len(refs)}
    finally:
        call(f'<Logout xmlns="{VIM}"><_this type="SessionManager">{sm}</_this></Logout>', "sign out of the vSphere API")


# ── what each host runs: its live build, read per host, keyed so a series can join it without naming it ──────────
ZERO_UUID = re.compile(r"^[0\-]*$")
BUILD_PATHS = ("summary.config.product.version", "summary.config.product.build", "summary.hardware.uuid",
               "summary.runtime.connectionState", "summary.runtime.inMaintenanceMode")


def fingerprint_key() -> bytes | None:
    """The secret in FINGERPRINT_KEY_FILE, or None when it is unset; the identity census's rule, so a key serves both."""
    if not os.environ.get("FINGERPRINT_KEY_FILE"):
        return None
    key = read_secret("FINGERPRINT_KEY_FILE")
    if not key:
        raise KeyError("FINGERPRINT_KEY_FILE names an empty file: write a secret of your own to it")
    return key.encode()


def fingerprint(key: bytes, value: str) -> str:
    return hmac.new(key, value.strip().lower().encode(), hashlib.sha256).hexdigest()[:16]


def _vim_release(vc: Vcenter) -> str | None:
    st, _, raw = _open(urllib.request.Request(f"https://{vc.host}/sdk/vimServiceVersions.xml", headers={"User-Agent": AGENT}))
    vc.calls.append({"method": "GET", "path": "/sdk/vimServiceVersions.xml", "status": st})
    m = re.search(rb"<name>urn:vim25</name>\s*<version>([^<]+)</version>", raw or b"")
    return m.group(1).decode() if m else None


def _summaries_json(vc: Vcenter, release: str, host_ids: list[str]) -> dict | None:
    """Each host's summary through the vSphere API's JSON form, on the REST session. None when the build serves no
    JSON form or refuses it the REST session, so the caller falls back to SOAP; a host whose summary did not answer maps
    to None."""
    root, tpl = f"https://{vc.host}/sdk/vim25/{release}", "/sdk/vim25/{release}/HostSystem/{host}/summary"
    out: dict = {}
    for hid in host_ids:
        st, _, raw = _open(urllib.request.Request(f"{root}/HostSystem/{hid}/summary", headers={
            "Accept": "application/json", "User-Agent": AGENT, "vmware-api-session-id": vc.session}))
        vc.calls.append({"method": "GET", "path": tpl, "status": st})
        if st in (401, 403, 404) and not out:
            return None
        s = _json(raw) if st == 200 else None
        if not isinstance(s, dict):
            out[hid] = None
            continue
        cfg, hw, rt = s.get("config") or {}, s.get("hardware") or {}, s.get("runtime") or {}
        product = cfg.get("product") or {}
        out[hid] = {"version": product.get("version"), "build": product.get("build"), "uuid": hw.get("uuid"),
                    "connection_state": rt.get("connectionState"), "in_maintenance": rt.get("inMaintenanceMode")}
    return out


def _summaries_soap(vc: Vcenter, host_ids: list[str]) -> dict | None:
    """The same five properties over SOAP, one RetrievePropertiesEx for every host, on a session of its own opened and
    closed here. None when no user is set (a session id alone cannot open SOAP)."""
    if vc.user is None:
        return None
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx()),
                                         urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    base = f"https://{vc.host}/sdk"

    def call(body: str, why: str):
        env = (f'<?xml version="1.0" encoding="UTF-8"?><soapenv:Envelope xmlns:soapenv="{SOAPENV}">'
               f"<soapenv:Body>{body}</soapenv:Body></soapenv:Envelope>")
        st, _, raw = _open(urllib.request.Request(base, data=env.encode(), method="POST", headers={
            "Content-Type": "text/xml; charset=utf-8", "SOAPAction": "urn:vim25/8.0.0.0", "User-Agent": AGENT}), opener)
        vc.calls.append({"method": "POST", "path": "/sdk", "status": st, "why": why})
        try:
            node = ET.fromstring(raw).find(f"{{{SOAPENV}}}Body")
        except ET.ParseError:
            return None
        return node[0] if node is not None and len(node) and not node[0].tag.endswith("Fault") else None

    esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")  # noqa: E731
    sc = call(f'<RetrieveServiceContent xmlns="{VIM}"><_this type="ServiceInstance">ServiceInstance</_this>'
              "</RetrieveServiceContent>", "read the service content")
    rv = sc.find(f"{{{VIM}}}returnval") if sc is not None else None
    if rv is None:
        return None
    sm, pc = (rv.findtext(f"{{{VIM}}}{k}") for k in ("sessionManager", "propertyCollector"))
    if call(f'<Login xmlns="{VIM}"><_this type="SessionManager">{sm}</_this><userName>{esc(vc.user)}</userName>'
            f"<password>{esc(vc.password)}</password></Login>", "sign in to the vSphere API") is None:
        return None
    try:
        paths = "".join(f"<pathSet>{p}</pathSet>" for p in BUILD_PATHS)
        objs = "".join(f'<objectSet><obj type="HostSystem">{esc(h)}</obj></objectSet>' for h in host_ids)
        r = call(f'<RetrievePropertiesEx xmlns="{VIM}"><_this type="PropertyCollector">{pc}</_this><specSet><propSet>'
                 f"<type>HostSystem</type>{paths}</propSet>{objs}</specSet><options/></RetrievePropertiesEx>",
                 "read each host's build")
        if r is None:
            return None
        out: dict = dict.fromkeys(host_ids)
        for o in r.iter(f"{{{VIM}}}objects"):
            hid = o.findtext(f"{{{VIM}}}obj")
            props = {p.findtext(f"{{{VIM}}}name"): p.findtext(f"{{{VIM}}}val") for p in o.findall(f"{{{VIM}}}propSet")}
            out[hid] = {"version": props.get(BUILD_PATHS[0]), "build": props.get(BUILD_PATHS[1]),
                        "uuid": props.get(BUILD_PATHS[2]), "connection_state": props.get(BUILD_PATHS[3]),
                        "in_maintenance": {"true": True, "false": False}.get(str(props.get(BUILD_PATHS[4])).lower())}
        return out
    finally:
        call(f'<Logout xmlns="{VIM}"><_this type="SessionManager">{sm}</_this></Logout>', "sign out of the vSphere API")


def host_builds(vc: Vcenter, key: bytes | None, clusters: list[tuple[str, list[str]]] | None = None) -> dict:
    """Each host's running version and build, read live per host from its summary (summary.config.product,
    summary.hardware.uuid, summary.runtime), never from a stored compliance result (G-781). Each host is named by a
    keyed fingerprint of its hardware UUID (the census's FINGERPRINT_KEY_FILE rule), so a dated series can join one
    host across runs while the record names none. A row is joinable only when it is keyed and its UUID is its own: a
    UUID that is missing or all zeros, or that another host in the same read also reports, never joins. A host that is
    not connected reports the last build vCenter knew, which a reader takes as last known, never as running. What a
    host reports here after a Live Patch, applied without a reboot, has not been read on an estate yet, so the read
    makes no claim for a host live-patched since its last reboot.

    `clusters` is [(cluster name, [host id, ...])]; without it the clusters and their hosts are listed here. A host in
    no cluster is read too, under the cluster None."""
    if clusters is None:
        st, cls = vc.get("/vcenter/cluster")
        if st != 200 or not isinstance(cls, list):
            return {"read": False, "why": f"the cluster list answered {st}"}
        clusters = []
        for cl in sorted(cls, key=lambda c: c.get("name") or ""):
            st, hs = vc.get(f"/vcenter/host?clusters={cl['cluster']}", "/vcenter/host?clusters={cluster}")
            clusters.append((cl.get("name"), [h["host"] for h in hs] if st == 200 and isinstance(hs, list) else []))
    st, every = vc.get("/vcenter/host")
    if st != 200 or not isinstance(every, list):
        return {"read": False, "why": f"the host list answered {st}"}
    in_clusters = {h for _, hosts in clusters for h in hosts}
    standalone = sorted(h["host"] for h in every if h.get("host") not in in_clusters)
    if standalone:
        clusters = [*clusters, (None, standalone)]
    ids = [h for _, hosts in clusters for h in hosts]
    read_at = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    release = _vim_release(vc)
    found, via = (_summaries_json(vc, release, ids), "vi-json") if release else (None, None)
    if found is None:
        found, via = _summaries_soap(vc, ids), "soap"
    if found is None:
        return {"read": False, "read_at": read_at, "why": "neither the vSphere API's JSON form nor SOAP answered"}
    uuids = [str((found.get(h) or {}).get("uuid") or "").strip().lower() for h in ids]
    seen = {u: uuids.count(u) for u in set(uuids)}
    rows, unread = [], 0
    for (cname, hosts) in clusters:
        for h in hosts:
            s = found.get(h)
            if s is None:
                unread += 1
                continue
            u = str(s.get("uuid") or "").strip().lower()
            identified = bool(u) and not ZERO_UUID.match(u)
            rows.append({"key": fingerprint(key, u) if key and identified else None,
                         "joinable": bool(key) and identified and seen[u] == 1,
                         "cluster": cname, "version": s.get("version"), "build": s.get("build"),
                         "connection_state": s.get("connection_state"), "in_maintenance": s.get("in_maintenance")})
    return {"read": True, "via": via, "read_at": read_at, "keyed": key is not None, "hosts": rows,
            "unread": unread,
            "collisions": sum(n for u, n in seen.items() if n > 1 and u and not ZERO_UUID.match(u)),
            "unidentified": sum(1 for u in uuids if not u or ZERO_UUID.match(u))}


def guard_joins(reads: list[dict]) -> None:
    """Across several vCenters' host_builds: a key two rows share anywhere in the census never joins, and each
    vCenter's `collisions` counts its rows that share a key with a row elsewhere too."""
    keys = [r["key"] for b in reads if b.get("read") for r in b["hosts"] if r["key"]]
    shared = {k for k in keys if keys.count(k) > 1}
    for b in reads:
        if not b.get("read"):
            continue
        across = 0
        for r in b["hosts"]:
            if r["key"] in shared and r["joinable"]:
                r["joinable"], across = False, across + 1
        b["collisions"] += across


# ── the reads ───────────────────────────────────────────────────────────────────────────────────────────────────
def item_fields(value) -> dict:
    """The non-identifying fields of one drifted configuration item: a URL keeps its scheme and port, an object keeps
    its numbers, booleans and short words, and every field whose name could identify something is withheld by name."""
    obj = value
    if isinstance(value, str):
        try:
            obj = json.loads(value)
        except ValueError:
            obj = value
    if isinstance(obj, str):
        m = URL.match(obj.strip())
        if m:
            return {"fields": {"scheme": m.group(1).lower(), "port": int(m.group(3)) if m.group(3) else None},
                    "withheld": ["host"]}
        return {"fields": {}, "withheld": ["value"]}
    if isinstance(obj, dict):
        kept, held = {}, []
        for k, v in sorted(obj.items()):
            if IDENTIFYING.search(k):
                held.append(k)
            elif isinstance(v, bool) or v is None or isinstance(v, (int, float)):
                kept[k] = v
            elif isinstance(v, str) and URL.match(v.strip()):
                m = URL.match(v.strip())
                kept[k] = {"scheme": m.group(1).lower(), "port": int(m.group(3)) if m.group(3) else None}
            elif isinstance(v, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,23}", v):
                kept[k] = v
            else:
                held.append(k)
        return {"fields": kept, "withheld": held}
    if isinstance(obj, (int, float, bool)) or obj is None:
        return {"fields": {"value": obj}, "withheld": []}
    return {"fields": {}, "withheld": ["value"]}


def _day(t) -> str | None:
    return str(t)[:10] if t else None


def read_cluster(vc: Vcenter, cid: str, name: str, hosts: int | None) -> dict:
    b = f"/esx/settings/clusters/{cid}"
    tb = "/esx/settings/clusters/{cluster}"
    out: dict = {"name": name, "hosts": hosts}
    st, en = vc.get(f"{b}/enablement/software", f"{tb}/enablement/software")
    out["image_managed"] = bool(en.get("enabled")) if st == 200 and isinstance(en, dict) else None
    if out["image_managed"]:
        st, sw = vc.get(f"{b}/software", f"{tb}/software")
        if st != 200 or not isinstance(sw, dict):
            raise ReadFailed(f"the image of a cluster answered {st}")
        add_on, hs = sw.get("add_on") or None, sw.get("hardware_support") or {}
        firmware = None
        for manager, pkg in sorted((hs.get("packages") or {}).items()):   # one firmware add-on per manager
            firmware = {"package": (pkg or {}).get("pkg") or manager, "version": (pkg or {}).get("version")}
            break
        out["image"] = {
            "base_image": (sw.get("base_image") or {}).get("version"),
            "vendor_add_on": ({"name": add_on.get("name"), "version": add_on.get("version"),
                               "vendor": (add_on.get("details") or {}).get("vendor")} if isinstance(add_on, dict) else None),
            "firmware_add_on": firmware,
            "components": sorted((sw.get("components") or {}).keys()),
            "solutions": sorted((sw.get("solutions") or {}).keys()),
            "alternative_images": len(sw.get("alternative_images") or {}),
        }
        st, comp = vc.get(f"{b}/software/compliance", f"{tb}/software/compliance")
        if st == 200 and isinstance(comp, dict):
            hosts_c = comp.get("hosts") or {}
            out["image_compliance"] = {
                "status": comp.get("status"), "checked": comp.get("scan_time"),
                "hosts": sorted({(v or {}).get("status") for v in hosts_c.values()} - {None}) if isinstance(hosts_c, dict) else []}
        else:
            out["image_compliance"] = {"status": None, "why": message(comp) or f"answered {st}"}
    st, en = vc.get(f"{b}/enablement/configuration", f"{tb}/enablement/configuration")
    enabled = bool(en.get("enabled")) if st == 200 and isinstance(en, dict) else None
    cfg: dict = {"enabled": enabled}
    if enabled:
        st, aud = vc.get(f"{b}/configuration/audit-records", f"{tb}/configuration/audit-records")
        records = [{"operation": r.get("operation"), "status": r.get("status"), "started": r.get("start_time")}
                   for r in (aud if isinstance(aud, list) else [])]
        records.sort(key=lambda r: r["started"] or "")
        cfg["audit"] = records
        cfg["enabled_on"] = next((_day(r["started"]) for r in records if str(r["operation"]).startswith("Transition")), None)
        cfg["last_change"] = _day(records[-1]["started"]) if records else None
        st, doc = vc.get(f"{b}/configuration", f"{tb}/configuration")
        cfg["document"] = document_shape(doc) if st == 200 else {"why": message(doc) or f"answered {st}"}
        st, lc = vc.get(f"{b}/configuration/reports/last-compliance-result",
                        f"{tb}/configuration/reports/last-compliance-result")
        cfg["compliance"] = compliance_shape(lc) if st == 200 and isinstance(lc, dict) else {
            "status": None, "why": message(lc) or f"answered {st}"}
    out["configuration"] = cfg
    return out


def document_shape(doc) -> dict:
    """The configuration document's shape: its section names and counts, and never a value from it."""
    raw = doc.get("config") if isinstance(doc, dict) else None
    try:
        d = json.loads(raw) if isinstance(raw, str) else {}
    except ValueError:
        return {"why": "the document is not JSON"}
    prof = d.get("profile") if isinstance(d.get("profile"), dict) else {}
    esx = prof.get("esx") if isinstance(prof.get("esx"), dict) else {}
    meta = d.get("metadata") if isinstance(d.get("metadata"), dict) else {}
    ref = meta.get("reference_host") if isinstance(meta.get("reference_host"), dict) else {}
    return {"esx_sections": sorted(esx), "esx_subsections": sum(len(v) for v in esx.values() if isinstance(v, dict)),
            "other_sections": sorted(k for k in prof if k != "esx"),
            "host_override": len(d.get("host-override") or {}), "host_specific": len(d.get("host-specific") or {}),
            "reference_host_version": ref.get("version")}


def compliance_shape(lc: dict) -> dict:
    """The stored configuration compliance: its status and time, and per host its status and every drifted item's
    path with its non-identifying fields."""
    info = lc.get("host_info") or {}
    hosts = []
    for hid, hv in sorted((lc.get("hosts") or {}).items()):
        ci = ((hv or {}).get("host_compliance") or {}).get("compliance_info") or {}
        drift = []
        for change, key in (("add", "target"), ("delete", "current"), ("update", "target")):
            for it in ci.get(change + "s") or []:
                if not isinstance(it, dict):
                    continue
                drift.append({"change": change, "path": it.get("path"),
                              "shows": " / ".join(it.get("display_path") or []) or None,
                              **item_fields(it.get(key))})
        hosts.append({"name": ((info.get(hid) or {}).get("name") if isinstance(info, dict) else None) or hid,
                      "status": ((hv or {}).get("host_compliance") or {}).get("status"), "drift": drift})
    return {"status": lc.get("cluster_status"), "checked": lc.get("end_time"), "hosts": hosts}


def newer(a: str, b: str) -> bool:
    """Whether version a is newer than b, part by part as numbers (9.1.1.0100 is newer than 9.1.1.0)."""
    pa = [int(x) for x in re.findall(r"\d+", a or "")]
    pb = [int(x) for x in re.findall(r"\d+", b or "")]
    return pa > pb


def read_vcenter(vc: Vcenter, builds: bool = False, key: bytes | None = None) -> dict:
    out: dict = {"name": vc.host}
    st, v = vc.get("/appliance/system/version")
    if st != 200 or not isinstance(v, dict):
        raise ReadFailed(f"the vCenter version read answered {st}")
    out["version"], out["build"] = v.get("version"), v.get("build")
    st, svcs = vc.get("/vcenter/services")
    out["services"] = ({label: {"state": (svcs.get(key) or {}).get("state"), "startup": (svcs.get(key) or {}).get("startup_type")}
                        for label, key in SERVICES} if st == 200 and isinstance(svcs, dict) else {"why": f"answered {st}"})
    st, hsm = vc.get("/esx/settings/hardware-support/managers")
    out["hardware_support_managers"] = len(hsm) if st == 200 and isinstance(hsm, list) else None
    out["host_profiles"] = host_profiles(vc)
    st_u, _ = vc.get("/esx/settings/depots/umds")
    st_on, online = vc.get("/esx/settings/depots/online")
    st_off, offline = vc.get("/esx/settings/depots/offline")
    st_b, bases = vc.get("/esx/settings/depot-content/base-images")
    depots = []
    for d in (online or {}).values() if st_on == 200 and isinstance(online, dict) else []:
        owner, desc = str(d.get("owner") or ""), str(d.get("description") or "")
        kind = ("the VCF depot, through vCenter" if owner == "com.vmware.vcIntegrity"
                else "SDDC Manager's depot" if desc.startswith("SDDC Manager") else "added by a user account")
        loc = URL.match(str(d.get("location") or ""))
        depots.append({"kind": kind, "enabled": bool(d.get("enabled")), "description": desc or None,
                       "server": loc.group(2) if loc else None})
    versions = sorted({b.get("version") for b in bases if isinstance(b, dict) and b.get("version")},
                      key=lambda x: [int(n) for n in re.findall(r"\d+", x)]) if st_b == 200 and isinstance(bases, list) else []
    out["depot"] = {"umds": "configured" if st_u == 200 else f"none ({st_u})",
                    "online": sorted(depots, key=lambda d: (d["kind"], d["description"] or "")),
                    "offline_bundles": len(offline) if st_off == 200 and isinstance(offline, (dict, list)) else None,
                    "base_images": len(versions), "newest_base_image": versions[-1] if versions else None}
    st, clusters = vc.get("/vcenter/cluster")
    if st != 200 or not isinstance(clusters, list):
        raise ReadFailed(f"the cluster list answered {st}")
    out["clusters"], members = [], []
    for cl in sorted(clusters, key=lambda c: c.get("name") or ""):
        st, hs = vc.get(f"/vcenter/host?clusters={cl['cluster']}", "/vcenter/host?clusters={cluster}")
        out["clusters"].append(read_cluster(vc, cl["cluster"], cl.get("name"), len(hs) if isinstance(hs, list) else None))
        members.append((cl.get("name"), [h["host"] for h in hs] if st == 200 and isinstance(hs, list) else []))
    if builds:
        out["host_builds"] = host_builds(vc, key, members)
    return out


# ── what the reads mean ─────────────────────────────────────────────────────────────────────────────────────────
def findings(vcs: list[dict]) -> list[dict]:
    """Each finding: its level (ALERT drives exit 1, NOTE does not) and the sentence the report prints."""
    out = []
    for v in vcs:
        for c in v["clusters"]:
            who = c["name"]
            if c["image_managed"] is False:
                out.append({"level": "ALERT", "where": who, "says": "still on baselines: move it to an image before "
                            "any ESX 9 upgrade"})
                continue
            ic = (c.get("image_compliance") or {}).get("status")
            if ic in DRIFTED:
                out.append({"level": "ALERT", "where": who, "says": f"image compliance {ic}"})
            elif ic not in COMPLIANT:
                out.append({"level": "NOTE", "where": who, "says": f"no stored image compliance ({ic})"})
            cfg = c["configuration"]
            if cfg.get("enabled"):
                cc = (cfg.get("compliance") or {}).get("status")
                if cc in DRIFTED:
                    paths = sorted({d["path"] for h in cfg["compliance"]["hosts"] for d in h["drift"]})
                    out.append({"level": "ALERT", "where": who, "says": f"configuration compliance {cc}, drift at "
                                + ", ".join(paths)})
                elif cc not in COMPLIANT:
                    out.append({"level": "NOTE", "where": who, "says": f"no stored configuration compliance ({cc})"})
        newest, running = v["depot"]["newest_base_image"], {c["image"]["base_image"] for c in v["clusters"] if c.get("image")}
        if newest and running and all(newer(newest, r) for r in running):
            out.append({"level": "NOTE", "where": v["name"], "says": f"the depot holds base image {newest}, newer "
                        "than every image this vCenter's clusters declare"})
        hp = v["host_profiles"]
        if hp.get("read") and hp.get("count"):
            out.append({"level": "NOTE", "where": v["name"], "says": f"{hp['count']} host profile(s): a move to "
                        "Configuration Profiles, which cannot be undone, is ahead"})
        if not hp.get("read"):
            out.append({"level": "NOTE", "where": v["name"], "says": f"host profiles not read: {hp.get('why')}"})
    return out


def summarize(vcs: list[dict]) -> dict:
    cl = [c for v in vcs for c in v["clusters"]]
    return {"vcenters": len(vcs), "clusters": len(cl), "hosts": sum(c["hosts"] or 0 for c in cl),
            "on_images": sum(1 for c in cl if c["image_managed"]),
            "on_baselines": sum(1 for c in cl if c["image_managed"] is False),
            "image_compliant": sum(1 for c in cl if (c.get("image_compliance") or {}).get("status") in COMPLIANT),
            "with_vendor_add_on": sum(1 for c in cl if (c.get("image") or {}).get("vendor_add_on")),
            "with_firmware_add_on": sum(1 for c in cl if (c.get("image") or {}).get("firmware_add_on")),
            "with_configuration_profiles": sum(1 for c in cl if c["configuration"].get("enabled")),
            "configuration_compliant": sum(1 for c in cl if c["configuration"].get("enabled")
                                           and (c["configuration"].get("compliance") or {}).get("status") in COMPLIANT),
            "hardware_support_managers": sum(v["hardware_support_managers"] or 0 for v in vcs),
            "host_profiles": sum((v["host_profiles"].get("count") or 0) for v in vcs),
            "host_profiles_read_on": sum(1 for v in vcs if v["host_profiles"].get("read")),
            "auto_deploy_running": sum(1 for v in vcs if (v["services"].get("Auto Deploy") or {}).get("state") == "STARTED"),
            "image_builder_running": sum(1 for v in vcs if (v["services"].get("Image Builder") or {}).get("state") == "STARTED"),
            "umds_configured": sum(1 for v in vcs if v["depot"]["umds"] == "configured")}


# ── the record contract: estate values become placeholders, and a record that keeps one is never written ─────────
class Labels:
    """Estate values become stable placeholders, in one longest-first pass on a name boundary; the product's own
    vocabulary is never registered."""

    RESERVED = {"localhost", "default", "none", "ESX", "esx"}

    def __init__(self):
        self.maps: dict[str, dict[str, str]] = {}

    def add(self, family: str, name, same_as: str | None = None) -> None:
        """Register a name; `same_as` gives a short name the label of the full name it abbreviates."""
        if not name or str(name) in self.RESERVED:
            return
        m = self.maps.setdefault(family, {})
        if same_as and same_as in m:
            m.setdefault(str(name), m[same_as])
            return
        m.setdefault(str(name), f"{family}-{len(set(m.values())) + 1}")

    def known(self) -> list[tuple[str, str]]:
        return [(r, lab) for m in self.maps.values() for r, lab in m.items()]

    def one_pass(self, text: str) -> str:
        label_of = dict(self.known())
        if not label_of:
            return text
        rx = re.compile(r"(?<![A-Za-z0-9-])(" + "|".join(map(re.escape, sorted(label_of, key=len, reverse=True)))
                        + r")(?![A-Za-z0-9-])")
        return "".join(part if i % 2 else rx.sub(lambda m: "{{%s}}" % label_of[m.group(1)], part)
                       for i, part in enumerate(PLACEHOLDER.split(text)))


def register(vcs: list[dict], L: Labels) -> None:
    """Every estate name the reads brought back, by family. Hosts before their short names, so a short name that is
    the first label of a host's name scrubs on its own."""
    for v in vcs:
        L.add("vcenter", v["name"])
        L.add("vcenter", v["name"].split(".")[0], same_as=v["name"])
        for d in v["depot"]["online"]:
            L.add("depot-server", d.get("server"))
        for p in v["host_profiles"].get("profiles") or []:
            L.add("host-profile", p.get("name"))
        for c in v["clusters"]:
            L.add("cluster", c["name"])
            for h in ((c["configuration"].get("compliance") or {}).get("hosts") or []):
                L.add("host", h["name"])
                L.add("host", str(h["name"]).split(".")[0], same_as=h["name"])
    domains = {".".join(n.split(".")[1:]) for n, _ in L.known() if n.count(".") >= 2}
    for d in sorted(domains):
        L.add("domain", d)


def scrub(record: dict, L: Labels, also: tuple[str, ...] = ()) -> dict:
    """The record with every registered value replaced, walked value by value (a key is the product's schema or this
    script's, never scrubbed), refused if a registered value, an address or one of `also` survives."""
    def walk(o):
        if isinstance(o, dict):
            return {k: walk(v) for k, v in o.items()}
        if isinstance(o, list):
            return [walk(v) for v in o]
        return L.one_pass(o) if isinstance(o, str) else o
    out = walk(record)
    text = json.dumps(out, ensure_ascii=False)
    keys_before = sorted(_keys(record))
    if sorted(_keys(out)) != keys_before:
        raise Refused("the scrub changed a key")
    bare = PLACEHOLDER.sub("", text)
    # A product version has the shape of an address (9.1.1.0), so the address check reads every value but the versions.
    if any(IPV4.search(v) for k, v in _strings(out) if not VERSION_KEY.search(k)):
        raise Refused("an address reached the record")
    for real, label in L.known():
        if re.search(r"(?<![A-Za-z0-9-])" + re.escape(real) + r"(?![A-Za-z0-9-])", bare):
            shape = re.sub(r"[A-Za-z]", "a", re.sub(r"[0-9]", "9", real))
            raise Refused(f"a {label.rsplit('-', 1)[0]} value ({len(real)} characters, shape {shape}) reached the record")
    for value in also:
        if value and value in bare:
            raise Refused("a value from the environment reached the record")
    return out


VERSION_KEY = re.compile(r"version|base_image|build", re.I)


def _strings(o, key: str = ""):
    """Every string value in a record, with the key it sits under (a list's items take the list's key)."""
    if isinstance(o, dict):
        for k, v in o.items():
            yield from _strings(v, k)
    elif isinstance(o, list):
        for v in o:
            yield from _strings(v, key)
    elif isinstance(o, str):
        yield key, o


def _keys(o):
    if isinstance(o, dict):
        for k, v in o.items():
            yield k
            yield from _keys(v)
    elif isinstance(o, list):
        for v in o:
            yield from _keys(v)


# ── the report ──────────────────────────────────────────────────────────────────────────────────────────────────
def report(rec: dict) -> list[str]:
    """The lines the script prints, from a record: the same function prints a live run and a saved record."""
    s = rec["summary"]
    lines = [f"hostlife.py: both declarations of every cluster, read {rec['captured_utc']}", "",
             f"  {s['vcenters']} vCenter(s), {s['clusters']} cluster(s), {s['hosts']} host(s)"]
    for v in rec["vcenters"]:
        lines += ["", f"{v['name']}  vCenter {v['version']} build {v['build']}"]
        svc = v["services"]
        lines.append("  services   " + ", ".join(f"{k} {(svc.get(k) or {}).get('state')} ({(svc.get(k) or {}).get('startup')})"
                                                for k, _ in SERVICES if isinstance(svc.get(k), dict)))
        hp = v["host_profiles"]
        lines.append(f"  host profiles {hp['count'] if hp.get('read') else 'not read: ' + str(hp.get('why'))}"
                     f"{' (read through ' + hp['via'] + ')' if hp.get('read') else ''}; hardware support managers "
                     f"{v['hardware_support_managers']}")
        dep = v["depot"]
        kinds: dict[str, list[bool]] = {}
        for d in dep["online"]:
            kinds.setdefault(d["kind"], []).append(d["enabled"])
        on = "; ".join(f"{k} {sum(e)} of {len(e)} on" for k, e in sorted(kinds.items()))
        lines.append(f"  depot      UMDS {dep['umds']}; online depots: {on or 'none'}")
        lines.append(f"             {dep['base_images']} base image(s), newest {dep['newest_base_image']}; "
                     f"{dep['offline_bundles']} offline bundle(s)")
        hb = v.get("host_builds")
        if hb is not None:
            if not hb.get("read"):
                lines.append(f"  host builds  not read: {hb.get('why')}")
            else:
                runs: dict[str, int] = {}
                for r in hb["hosts"]:
                    tag = f"{r['version']} build {r['build']}" + ("" if r["connection_state"] == "connected"
                                                                  else f" (last known, {r['connection_state']})")
                    runs[tag] = runs.get(tag, 0) + 1
                lines.append(f"  host builds  {len(hb['hosts'])} read live ({hb['via']}), {hb['read_at']}: "
                             + "; ".join(f"{n} on {t}" for t, n in sorted(runs.items())))
                lines.append(f"             in maintenance {sum(1 for r in hb['hosts'] if r['in_maintenance'])}; "
                             f"keyed {'yes' if hb['keyed'] else 'no (set FINGERPRINT_KEY_FILE to join a series)'}; "
                             f"collisions {hb['collisions']}; unidentified {hb['unidentified']}; unread {hb['unread']}")
        for c in v["clusters"]:
            lines.append(f"  {c['name']}  {c['hosts']} host(s)")
            if not c["image_managed"]:
                lines.append("    image    NONE: managed with baselines")
            else:
                im, ic = c["image"], c.get("image_compliance") or {}
                parts = [f"base {im['base_image']}"]
                parts.append(f"vendor add-on {im['vendor_add_on']['name']} {im['vendor_add_on']['version']}"
                             if im["vendor_add_on"] else "no vendor add-on")
                parts.append(f"firmware add-on {im['firmware_add_on']['package']}" if im["firmware_add_on"] else "no firmware add-on")
                parts.append(f"{len(im['components'])} component(s)")
                if im["solutions"]:
                    parts.append("solutions " + ", ".join(im["solutions"]))
                lines.append("    image    " + "; ".join(parts))
                lines.append(f"             compliance {ic.get('status')}, stored {ic.get('checked') or ic.get('why')}")
            cfg = c["configuration"]
            if not cfg.get("enabled"):
                lines.append("    configuration profiles  not enabled")
                continue
            doc, cc = cfg.get("document") or {}, cfg.get("compliance") or {}
            lines.append(f"    configuration profiles  enabled {cfg.get('enabled_on')}, last change {cfg.get('last_change')}; "
                         f"{len(doc.get('esx_sections') or [])} ESX sections, {doc.get('esx_subsections')} subsections"
                         + (", also " + ", ".join(doc["other_sections"]) if doc.get("other_sections") else "")
                         + f"; reference host {doc.get('reference_host_version')}")
            lines.append(f"             compliance {cc.get('status')}, stored {cc.get('checked') or cc.get('why')}")
            for h in cc.get("hosts") or []:
                lines.append(f"             {h['name']}  {h['status']}")
                for d in h["drift"]:
                    f = ", ".join(f"{k} {json.dumps(x) if isinstance(x, dict) else x}" for k, x in d["fields"].items())
                    lines.append(f"               {d['change']:<6} {d['path']}  {f or '(no field shown)'}"
                                 + (f"  [withheld: {', '.join(d['withheld'])}]" if d["withheld"] else ""))
    lines.append("")
    for f in rec["findings"]:
        lines.append(f"{f['level']:5}  {f['where']}: {f['says']}")
    if not rec["findings"]:
        lines.append("every cluster read holds both declarations it has")
    return lines


# ── the plan: the order of the moves, from your answers ─────────────────────────────────────────────────────────
# Each move: what to do, the pages it rests on (the record's ids for the 9.1 and 9.0 documentation), how its place in
# the order is held (enforced: the platform refuses the next step without it; documented order: a page states the
# order; advised: the order this companion recommends, the reason given), and whether it can be undone.
STEPS = {
    "depot": {"text": "Feed vSphere Lifecycle Manager from the VCF software depot, which holds its authentication and "
                      "synchronization in 9.1, and retire UMDS.",
              "rests_on": ["R15", "R30"], "order": "advised", "why": "every image is built from what the depot holds",
              "irreversible": False, "plate": "02"},
    "depot-offline": {"text": "Build an offline depot with the VCF download tool, or a local depot store for a site "
                              "with no connection at all, behind the VCF software depot, and retire UMDS.",
                      "rests_on": ["R30", "R31"], "order": "advised", "why": "every image is built from what the depot holds",
                      "irreversible": False, "plate": "02"},
    "vcenter-nsx": {"text": "Upgrade NSX Manager and vCenter before any ESX host.", "rests_on": ["R116"],
                    "order": "documented order", "why": "the ESX upgrade page lists it as a prerequisite",
                    "irreversible": False, "plate": "06"},
    "conflict-heterogeneous": {"text": "Settle a heterogeneous cluster on baselines with Broadcom first: the VCF page "
                                       "moves baseline clusters to images before the ESX 9 upgrade, and the vSphere "
                                       "page upgrades a heterogeneous cluster to ESX 9.0 before it moves.",
                               "rests_on": ["R40", "R114"], "order": "open", "why": "the two pages read differently",
                               "irreversible": False, "plate": "06"},
    "images": {"text": "Move every baseline cluster to an image, from the Image Library, a new image or a reference "
                       "host, after its eligibility check.", "rests_on": ["R39", "R40", "R23", "R17"],
               "order": "enforced", "why": "no ESX 9 upgrade until every cluster uses an image",
               "irreversible": True, "plate": "06"},
    "images-vcf": {"text": "In VCF, make that move with SDDC Manager's mechanisms only: its PowerShell script or its "
                           "API.", "rests_on": ["R114", "R115"], "order": "documented order",
                   "why": "the VCF transition page names the only supported mechanisms", "irreversible": False, "plate": "06"},
    "images-supervisor": {"text": "With a Supervisor on a baseline cluster, move that cluster after the vCenter "
                                  "upgrade and before the ESX upgrade.", "rests_on": ["R115"],
                          "order": "documented order", "why": "the VCF transition page orders it", "irreversible": False,
                          "plate": "06"},
    "firmware": {"text": "Add the vendor's firmware and drivers add-on with its hardware support manager, so "
                         "compliance covers firmware too.", "rests_on": ["R123", "R124", "R126"], "order": "advised",
                 "why": "firmware is declared with the image it ships beside", "irreversible": False, "plate": "01"},
    "no-firmware": {"text": "Without a hardware support manager, vSphere Lifecycle Manager treats the firmware a host "
                            "runs as its target: keep firmware current by the vendor's own process.",
                    "rests_on": ["R125"], "order": "advised", "why": "nothing in the image will move it",
                    "irreversible": False, "plate": "01"},
    "import": {"text": "Import the target image into the VCF instance through VCF Operations, at the ESX version of "
                       "the release's bill of materials.", "rests_on": ["R111", "R112"], "order": "documented order",
               "why": "a cluster in VCF takes its image from the instance", "irreversible": False, "plate": "02"},
    "esx": {"text": "Upgrade ESX by remediating each cluster to its new image: precheck, stage, then remediate.",
            "rests_on": ["R16", "R29", "R36", "R116"], "order": "documented order",
            "why": "the image is the only way to upgrade ESX in 9.x", "irreversible": False, "plate": "06"},
    "configuration-profiles": {"text": "Move the cluster from host profiles to Configuration Profiles: eligibility, "
                                       "import from a reference host or a JSON file, validate, precheck, remediate.",
                               "rests_on": ["R88", "R92", "R95"], "order": "documented order",
                               "why": "on an image cluster every host must first be compliant with the image",
                               "irreversible": True, "plate": "05"},
    "declare-configuration": {"text": "Enable Configuration Profiles on the cluster, from a reference host or a "
                                      "JSON file, once every host is compliant with the image.",
                              "rests_on": ["R88", "R92"], "order": "documented order",
                              "why": "on an image cluster every host must first be compliant with the image",
                              "irreversible": True, "plate": "05"},
    "owners": {"text": "Before you declare a setting, find every other writer of it and leave out what another "
                       "system owns.", "rests_on": ["R85", "R94"], "order": "advised",
               "why": "remediation writes the declared value back over the other writer's", "irreversible": False,
               "plate": "05"},
    "iso": {"text": "Build each VCF host from an ESX ISO, the one exported from its cluster's image where it needs a "
                    "custom one, and keep stateless hosts out of VCF.", "rests_on": ["R58", "R82", "R83"],
            "order": "advised", "why": "VCF host preparation documents the ISO and supports no stateless host",
            "irreversible": False, "plate": "03"},
    "ztp": {"text": "Move vSphere clusters' network builds to Zero Touch Provisioning: UEFI HTTPS boot in the "
                    "firmware, one vCenter URL, the cluster's own image.", "rests_on": ["R63", "R65", "R70", "R71"],
            "order": "advised", "why": "the 9.1 notes call it the forward-looking replacement for legacy Auto Deploy",
            "irreversible": False, "plate": "03"},
    "stateless": {"text": "Rebuild stateless hosts as stateful ones before you rely on image compliance or "
                          "Configuration Profiles: neither applies to a stateless host.", "rests_on": ["R56", "R59"],
                  "order": "documented order", "why": "the 9.1 pages exclude stateless hosts from both",
                  "irreversible": False, "plate": "03"},
    "drift": {"text": "Read both declarations on a schedule: vCenter holds the compliance and remediates, VCF "
                      "Operations detects fleet drift and does not remediate.", "rests_on": ["R94", "R98", "R99"],
              "order": "advised", "why": "drift is only a finding when someone reads it", "irreversible": False,
              "plate": "05"},
}

SOURCES = {  # the page each move rests on, by the handbook record's claim id: (its title, its URL as fetched)
    "R15": ("What is vSphere Lifecycle Manager",
            "https://techdocs.broadcom.com/us/en/vmware-cis/vsphere/vsphere/9-1/managing-host-and-cluster-lifecycle/about-vsphere-lifecycle-manager-new.html"),
    "R16": ("vSphere Lifecycle Manager Images and Baselines",
            "https://techdocs.broadcom.com/us/en/vmware-cis/vsphere/vsphere/9-1/managing-host-and-cluster-lifecycle/about-vsphere-lifecycle-manager-new/vlcm-baselines-and-images.html"),
    "R17": ("How to Use vSphere Lifecycle Manager Images",
            "https://techdocs.broadcom.com/us/en/vmware-cis/vsphere/vsphere/9-1/managing-host-and-cluster-lifecycle/using-images-to-install-and-update-esxi-hosts-and-clusters.html"),
    "R23": ("vSphere Lifecycle Manager Images",
            "https://techdocs.broadcom.com/us/en/vmware-cis/vsphere/vsphere/9-1/managing-host-and-cluster-lifecycle/about-vsphere-lifecycle-manager-new/vlcm-baselines-and-images/vsphere-lifecycle-manager-images.html"),
    "R29": ("Lifecycle Management of Clusters and Standalone Hosts at Scale",
            "https://techdocs.broadcom.com/us/en/vmware-cis/vsphere/vsphere/9-1/managing-host-and-cluster-lifecycle/global-lifecycle-mangement.html"),
    "R30": ("The vSphere Lifecycle Manager Depot",
            "https://techdocs.broadcom.com/us/en/vmware-cis/vsphere/vsphere/9-1/managing-host-and-cluster-lifecycle/working-with-vsphere-lifecycle-manager-depots.html"),
    "R31": ("The vSphere Lifecycle Manager Depot",
            "https://techdocs.broadcom.com/us/en/vmware-cis/vsphere/vsphere/9-1/managing-host-and-cluster-lifecycle/working-with-vsphere-lifecycle-manager-depots.html"),
    "R36": ("Staging vSphere Lifecycle Manager Images to ESX Hosts in a Cluster or Standalone Hosts",
            "https://techdocs.broadcom.com/us/en/vmware-cis/vsphere/vsphere/9-1/managing-host-and-cluster-lifecycle/using-images-to-install-and-update-esxi-hosts-and-clusters/staging-vlcm-images-to-esxi-hosts-in-a-cluster.html"),
    "R39": ("Transition a Cluster or a Host That Uses Baselines Into a Cluster or a Host That Uses vSphere Lifecycle Manager Images",
            "https://techdocs.broadcom.com/us/en/vmware-cis/vsphere/vsphere/9-1/managing-host-and-cluster-lifecycle/using-images-to-install-and-update-esxi-hosts-and-clusters/switching-from-baselines-to-images.html"),
    "R40": ("Transition a Cluster or a Host That Uses Baselines Into a Cluster or a Host That Uses vSphere Lifecycle Manager Images",
            "https://techdocs.broadcom.com/us/en/vmware-cis/vsphere/vsphere/9-1/managing-host-and-cluster-lifecycle/using-images-to-install-and-update-esxi-hosts-and-clusters/switching-from-baselines-to-images.html"),
    "R56": ("How to Choose and Switch Between Provisioning Methods in Auto Deploy",
            "https://techdocs.broadcom.com/us/en/vmware-cis/vsphere/vsphere/9-1/esx-installation-and-setup/installing-esxi/installing-esxi-using-vsphere-auto-deploy/using-zero-touch-provisioning/how-to-choose-and-switch-between-provisioning-modes-in-auto-deploy.html"),
    "R58": ("Managing ESX Hosts in VMware Cloud Foundation",
            "https://techdocs.broadcom.com/us/en/vmware-cis/vcf/vcf-9-0-and-later/9-1/building-your-private-cloud-infrastructure/host-management.html"),
    "R59": ("Managing Hosts Provisioned with vSphere Auto Deploy or Zero Touch Provisioning",
            "https://techdocs.broadcom.com/us/en/vmware-cis/vsphere/vsphere/9-1/managing-host-and-cluster-lifecycle/how-to-use-images-for-managing-stateless-hosts.html"),
    "R63": ("What's new: vSphere",
            "https://techdocs.broadcom.com/us/en/vmware-cis/vcf/vcf-9-0-and-later/9-1/release-notes/vmware-cloud-foundation-9-1-0-0-release-notes/what-s-new/whats-new-vsphere.html"),
    "R65": ("What is Zero Touch Provisioning with Auto Deploy",
            "https://techdocs.broadcom.com/us/en/vmware-cis/vsphere/vsphere/9-1/esx-installation-and-setup/installing-esxi/installing-esxi-using-vsphere-auto-deploy/using-zero-touch-provisioning/what-is-zero-touch-provisioning-with-auto-deploy(1).html"),
    "R70": ("What is Zero Touch Provisioning with Auto Deploy",
            "https://techdocs.broadcom.com/us/en/vmware-cis/vsphere/vsphere/9-1/esx-installation-and-setup/installing-esxi/installing-esxi-using-vsphere-auto-deploy/using-zero-touch-provisioning/what-is-zero-touch-provisioning-with-auto-deploy(1).html"),
    "R71": ("What is Zero Touch Provisioning with Auto Deploy",
            "https://techdocs.broadcom.com/us/en/vmware-cis/vsphere/vsphere/9-1/esx-installation-and-setup/installing-esxi/installing-esxi-using-vsphere-auto-deploy/using-zero-touch-provisioning/what-is-zero-touch-provisioning-with-auto-deploy(1).html"),
    "R82": ("Install ESX on Hosts Using an ISO Image",
            "https://techdocs.broadcom.com/us/en/vmware-cis/vcf/vcf-9-0-and-later/9-1/deployment/deploying-a-new-vmware-cloud-foundation-or-vmware-vsphere-foundation-private-cloud-/preparing-your-environment/preparing-esx-hosts-for-vmware-cloud-foundation-or-vmware-vsphere-foundation/install-esx-on-hosts-using-the-iso.html"),
    "R83": ("Creating a Custom ESX ISO Image Using vSphere Lifecycle Manager",
            "https://techdocs.broadcom.com/us/en/vmware-cis/vcf/vcf-9-0-and-later/9-1/deployment/deploying-a-new-vmware-cloud-foundation-or-vmware-vsphere-foundation-private-cloud-/preparing-your-environment/preparing-esx-hosts-for-vmware-cloud-foundation-or-vmware-vsphere-foundation/create-a-custom-esx-iso-image-using-vsphere-lifecycle-manager.html"),
    "R85": ("What is vSphere Configuration Profiles",
            "https://techdocs.broadcom.com/us/en/vmware-cis/vsphere/vsphere/9-1/vsphere-configuration-profiles/using-vsphere-config-profiles-to-manage-host-configuration-at-a-cluster-level.html"),
    "R88": ("What is vSphere Configuration Profiles",
            "https://techdocs.broadcom.com/us/en/vmware-cis/vsphere/vsphere/9-1/vsphere-configuration-profiles/using-vsphere-config-profiles-to-manage-host-configuration-at-a-cluster-level.html"),
    "R92": ("Enable vSphere Configuration Profiles on an Existing Cluster",
            "https://techdocs.broadcom.com/us/en/vmware-cis/vsphere/vsphere/9-1/vsphere-configuration-profiles/enable-vsphere-configuration-profiles-on-a-cluster/transition-to-using-vsphere-configuration-profiles.html"),
    "R94": ("Check Host Compliance Against the Desired Configuration for the Cluster",
            "https://techdocs.broadcom.com/us/en/vmware-cis/vsphere/vsphere/9-1/vsphere-configuration-profiles/check-compliance.html"),
    "R95": ("How Host Profile Configuration Settings Map to the vSphere Configuration Profiles Settings for ESX Hosts",
            "https://techdocs.broadcom.com/us/en/vmware-cis/vsphere/vsphere/9-1/vsphere-configuration-profiles/view-host-settings-and-host-overrides/how-host-profile-configuration-settings-map-to-the-vsphere-configuration-profile-settings-for-esx-hosts.html"),
    "R98": ("What's new: VCF Operations",
            "https://techdocs.broadcom.com/us/en/vmware-cis/vcf/vcf-9-0-and-later/9-1/release-notes/vmware-cloud-foundation-9-1-0-0-release-notes/what-s-new/whats-new-vcf-ops.html"),
    "R99": ("Fleet Configuration Management",
            "https://techdocs.broadcom.com/us/en/vmware-cis/vcf/vcf-9-0-and-later/9-1/design/design-blueprints-for/infrastructure-modernization/fleet-management-blueprint/vsphere-configuration-management.html"),
    "R111": ("Managing vSphere Lifecycle Manager Images for VMware Cloud Foundation",
            "https://techdocs.broadcom.com/us/en/vmware-cis/vcf/vcf-9-0-and-later/9-1/lifecycle-management/lifecycle-management-of-vcf-components/managing-vsphere-lifecycle-manager-images-for-vmware-cloud-foundation.html"),
    "R112": ("Import a vSphere Lifecycle Manager Image to a VCF Instance",
            "https://techdocs.broadcom.com/us/en/vmware-cis/vcf/vcf-9-0-and-later/9-1/lifecycle-management/lifecycle-management-of-vcf-components/managing-vsphere-lifecycle-manager-images-for-vmware-cloud-foundation/import-a-vsphere-lifecycle-manager-image-to-a-vcf-instance.html"),
    "R114": ("Upgrade ESX to 9.1",
            "https://techdocs.broadcom.com/us/en/vmware-cis/vcf/vcf-9-0-and-later/9-1/deployment/upgrading-cloud-foundation/upgrade-the-management-domain-to-vmware-cloud-foundation-5-2/upgrade-esxi-for-vmware-cloud-foundation-5-2-1.html"),
    "R115": ("Transitioning from vSphere Lifecycle Manager Baselines to vSphere Lifecycle Manager Images",
            "https://techdocs.broadcom.com/us/en/vmware-cis/vcf/vcf-9-0-and-later/9-1/deployment/upgrading-cloud-foundation/upgrade-the-management-domain-to-vmware-cloud-foundation-5-2/vlcm-baseline-to-vlcm-image-cluster-transition-.html"),
    "R116": ("Upgrade ESX to 9.1",
            "https://techdocs.broadcom.com/us/en/vmware-cis/vcf/vcf-9-0-and-later/9-1/deployment/upgrading-cloud-foundation/upgrade-the-management-domain-to-vmware-cloud-foundation-5-2/upgrade-esxi-for-vmware-cloud-foundation-5-2-1.html"),
    "R123": ("Firmware Updates with vSphere Lifecycle Manager",
            "https://techdocs.broadcom.com/us/en/vmware-cis/vsphere/vsphere/9-1/managing-host-and-cluster-lifecycle/using-images-to-install-and-update-esxi-hosts-and-clusters/firmware-updates.html"),
    "R124": ("Firmware Updates with vSphere Lifecycle Manager",
            "https://techdocs.broadcom.com/us/en/vmware-cis/vsphere/vsphere/9-1/managing-host-and-cluster-lifecycle/using-images-to-install-and-update-esxi-hosts-and-clusters/firmware-updates.html"),
    "R125": ("Firmware Updates with vSphere Lifecycle Manager",
            "https://techdocs.broadcom.com/us/en/vmware-cis/vsphere/vsphere/9-1/managing-host-and-cluster-lifecycle/using-images-to-install-and-update-esxi-hosts-and-clusters/firmware-updates.html"),
    "R126": ("Deploying Hardware Support Managers",
            "https://techdocs.broadcom.com/us/en/vmware-cis/vsphere/vsphere/9-1/managing-host-and-cluster-lifecycle/using-images-to-install-and-update-esxi-hosts-and-clusters/firmware-updates/hardware-support-managers.html"),
}

ANSWERS = {  # each answer: its default, and the question it answers (the page's form asks the same)
    "vcf": (True, "Are the hosts managed by VCF (SDDC Manager)?"),
    "baselines": (False, "Is any cluster still managed with baselines?"),
    "supervisor": (False, "Does a cluster still on baselines run a Supervisor?"),
    "heterogeneous": (False, "Does a cluster still on baselines mix hardware vendors or generations?"),
    "upgrade": (False, "Is an ESX upgrade planned?"),
    "host_profiles": (False, "Is any host profile attached?"),
    "configuration_profiles": (False, "Do you want each cluster's configuration declared?"),
    "auto_deploy": ("none", "How does Auto Deploy build hosts today: none, stateful or stateless?"),
    "disconnected": (False, "Is the site without internet access?"),
    "hsm": (False, "Does the hardware vendor ship a hardware support manager you run?"),
}
AUTO_DEPLOY = ("none", "stateful", "stateless")


def answers_of(given: dict) -> dict:
    """The answers with every default filled in; an unknown key or value is refused."""
    unknown = set(given) - set(ANSWERS)
    if unknown:
        raise KeyError(f"unknown answer(s): {', '.join(sorted(unknown))}")
    a = {k: given.get(k, d) for k, (d, _) in ANSWERS.items()}
    if a["auto_deploy"] not in AUTO_DEPLOY:
        raise KeyError(f"auto_deploy is one of {', '.join(AUTO_DEPLOY)}")
    for k, v in a.items():
        if k != "auto_deploy" and not isinstance(v, bool):
            raise KeyError(f"{k} is yes or no")
    return a


def plan(given: dict) -> list[dict]:
    """The moves for these answers, in order: each {id, order, irreversible}. Pure: it reads nothing but its argument,
    and the handbook page's planner is its JavaScript twin, held equal to it in a browser at build."""
    a = answers_of(given)
    ids = ["depot-offline" if a["disconnected"] else "depot"]
    if a["upgrade"]:
        ids.append("vcenter-nsx")
    if a["baselines"]:
        if a["heterogeneous"]:
            ids.append("conflict-heterogeneous")
        ids.append("images")
        if a["vcf"]:
            ids.append("images-vcf")
        if a["supervisor"]:
            ids.append("images-supervisor")
    ids.append("firmware" if a["hsm"] else "no-firmware")
    if a["upgrade"]:
        if a["vcf"]:
            ids.append("import")
        ids.append("esx")
    if a["auto_deploy"] == "stateless":
        ids.append("stateless")
    if a["auto_deploy"] != "none" or a["vcf"]:
        ids.append("iso" if a["vcf"] else "ztp")
    if a["host_profiles"]:
        ids.append("configuration-profiles")
    elif a["configuration_profiles"]:
        ids.append("declare-configuration")
    if a["host_profiles"] or a["configuration_profiles"]:
        ids.append("owners")
    ids.append("drift")
    return [{"id": i, "order": STEPS[i]["order"], "irreversible": STEPS[i]["irreversible"]} for i in ids]


def plan_lines(given: dict, sources: bool = False) -> list[str]:
    """The plan as printed: each move with its order, why it stands there and the chapter's plate that teaches it;
    with `sources`, the documentation pages it rests on too."""
    out = []
    for n, s in enumerate(plan(given), 1):
        st = STEPS[s["id"]]
        flag = "  CANNOT BE UNDONE" if s["irreversible"] else ""
        out.append(f"{n:>2}. [{s['order']}]{flag} {st['text']}")
        out.append(f"      why here: {st['why']}; plate {st['plate']}")
        if sources:
            seen = []
            for rid in st["rests_on"]:
                if SOURCES[rid] not in seen:
                    seen.append(SOURCES[rid])
            out += [f"      read: {title} <{url}>" for title, url in seen]
    return out


# ── main ────────────────────────────────────────────────────────────────────────────────────────────────────────
def census(hosts: list[str], user: str | None = None, password: str | None = None, session: str | None = None,
           builds: bool = False, key: bytes | None = None) -> tuple[dict, dict]:
    """Read every vCenter named; returns (the record before the scrub, the Labels that scrub it). Credentials come in
    as arguments, so a caller that holds them in memory never writes them anywhere."""
    started = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    vcs, calls = [], []
    for host in hosts:
        vc = Vcenter(host, user, password, session)
        try:
            vcs.append(read_vcenter(vc, builds, key))
        finally:
            vc.close()
            calls.append({"vcenter": host, "calls": vc.calls})
    if builds:
        guard_joins([v["host_builds"] for v in vcs])
    found = findings(vcs)
    rec = {"tool": "hostlife.py", "captured_utc": started,
           "finished_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "read_only": "every REST call a GET; sessions opened and closed; no check, precheck, stage, remediation, "
                        "export, extract or service start sent",
           "summary": summarize(vcs), "vcenters": vcs, "findings": found,
           "exit": 1 if any(f["level"] == "ALERT" for f in found) else 0, "calls": calls}
    L = Labels()
    register(vcs, L)
    return rec, L


def write_record(rec: dict, L: Labels, out_dir: str, also: tuple[str, ...] = ()) -> tuple[dict, str]:
    clean = scrub(rec, L, also)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "hostlife.record.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(clean, indent=1, ensure_ascii=False) + "\n")
    return clean, path


def _plan_args(argv: list[str]) -> dict:
    p = argparse.ArgumentParser(prog="hostlife.py plan", description="the ordered moves for your answers")
    p.add_argument("--not-vcf", action="store_true", help="the hosts are not managed by VCF")
    for k in ANSWERS:
        if k not in ("vcf", "auto_deploy"):
            p.add_argument("--" + k.replace("_", "-"), action="store_true", help=ANSWERS[k][1])
    p.add_argument("--auto-deploy", choices=AUTO_DEPLOY, default="none", help=ANSWERS["auto_deploy"][1])
    p.add_argument("--sources", action="store_true", help="also print the documentation pages each move rests on")
    ns = p.parse_args(argv)
    given = {k: getattr(ns, k) for k in ANSWERS if k not in ("vcf", "auto_deploy")}
    given.update(vcf=not ns.not_vcf, auto_deploy=ns.auto_deploy)
    return given, ns.sources


def main(argv: list[str]) -> int:
    if argv[:1] == ["plan"]:
        given, sources = _plan_args(argv[1:])
        print("\n".join(plan_lines(given, sources)))
        return 0
    p = argparse.ArgumentParser(description="both declarations of every cluster, read-only")
    p.add_argument("--json", action="store_true", help="print the scrubbed record instead of the report")
    p.add_argument("--from-record", metavar="PATH", help="print the report from a saved record; no call is made")
    p.add_argument("--out-dir", default=os.environ.get("OUT_DIR", "out"), help="where the scrubbed record is written")
    p.add_argument("--host-builds", action="store_true", default=os.environ.get("HOST_BUILDS", "").strip() == "1",
                   help="also read each host's running version and build, keyed by FINGERPRINT_KEY_FILE where it is set")
    ns = p.parse_args(argv)
    if ns.from_record:
        with open(ns.from_record, encoding="utf-8") as f:
            rec = json.load(f)
        print(json.dumps(rec, indent=1) if ns.json else "\n".join(report(rec)))
        return rec["exit"]
    hosts = [h.strip() for h in os.environ.get("VC_HOST", "").split(",") if h.strip()]
    if not hosts:
        raise KeyError("set VC_HOST, one vCenter or several separated by commas")
    user = os.environ.get("VC_USER")
    key = fingerprint_key() if ns.host_builds else None
    if user and os.environ.get("VC_PASSWORD_FILE"):
        rec, L = census(hosts, user=user, password=read_secret("VC_PASSWORD_FILE"), builds=ns.host_builds, key=key)
    elif os.environ.get("VC_SESSION_FILE") and len(hosts) == 1:
        rec, L = census(hosts, session=read_secret("VC_SESSION_FILE"), builds=ns.host_builds, key=key)
    else:
        raise KeyError("set VC_USER with VC_PASSWORD_FILE, or VC_SESSION_FILE for a single vCenter")
    clean, path = write_record(rec, L, ns.out_dir, also=tuple(hosts) + ((user,) if user else ()))
    print(json.dumps(clean, indent=1) if ns.json else "\n".join(report(rec)))
    if not ns.json:
        print(f"\nwrote {path}; every vCenter, cluster, host and depot server replaced by a placeholder")
    return rec["exit"]


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except (KeyError, PermissionError) as e:
        print(f"hostlife.py: {e}", file=sys.stderr)
        sys.exit(2)
    except ReadFailed as e:
        print(f"READ FAILED: {e}", file=sys.stderr)
        sys.exit(3)
    except Refused as e:
        print(f"REFUSING to write: {e}", file=sys.stderr)
        sys.exit(4)
