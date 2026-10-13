#!/usr/bin/env python3
"""api_client.py - one VCF SSO API client for one integration: plan it, create it, and remove it. Plan by default.

Behind the identity broker an integration signs in as a VCF SSO API client of its own: a client on the realm, one VCF
role bound to it, and an API token issued with both of its lifetimes set. This script is that lifecycle on VCF
Operations' fleet identity API, and nothing else:

  plan (no flag)              prints every call it would send, with its body, and changes nothing
  --execute                   1. POST /ssorealms/{realm}/api-clients              the client, by the id you give
                              2. PUT  /ssorealms/{realm}/principals/{uuid}/roles    one VCF role, at realm scope
                              3. POST /ssorealms/{realm}/api-tokens                 its token, with both lifetimes
                              then trades the token at the broker for a bearer once, to prove it, and reads the client
                              and its token back; the token goes to --token-file (mode 0600) and is never printed
  --rotate --execute          issues the client a new token with both lifetimes, proves it at the broker, deletes every
                              token the client held before, and reads back that one token is left; with
                              --old-token-file it shows the old token trading for a bearer before the delete and
                              refused after it, so an integration can switch over in the overlap
  --teardown --execute        deletes the client's tokens and the client, then reads both lists again for residue

A client that already exists is refused, never adopted, so a run cannot take over an identity someone else made; a
teardown of a client that is not there removes nothing and exits 0, so it is safe to re-run. Lifetimes outside the
bounds the broker held on the reference estate (an API token of 1,440 to 259,200 minutes, an access token of 30 to 60)
are refused before anything is sent.

Env:  OPS_HOST                 VCF Operations FQDN (required)
      OPS_API_TOKEN_FILE       an API token of a user who may manage the fleet's API clients (mode 0600; OPS_API_TOKEN
                               is read if it is unset), traded at the broker for a bearer: OPS_BROKER_HOST (default
                               OPS_HOST), BROKER_TENANT (the broker tenant, the realm's path segment; default
                               CUSTOMER; OPS_REALM, its earlier name, is still read)
      OPS_BEARER_FILE          instead, a bearer you already hold
      TLS_VERIFY=false         only on a self-signed lab CA
      OUT                      the record (default api_client.json)
Use:  python3 api_client.py --client-id ID --role ROLE --api-token-ttl MIN --access-token-ttl MIN [--token-file PATH]
                            [--execute] [--redact]
      python3 api_client.py --client-id ID --rotate --api-token-ttl MIN --access-token-ttl MIN --token-file NEW
                            [--old-token-file OLD] [--execute] [--redact]
      python3 api_client.py --client-id ID --teardown [--execute] [--redact]
Exit: 0 the plan printed, or the run held on read-back (the client with its one role and an active token with both
      lifetimes; for a rotation, the new token proved, the old ones gone and, when given, the old token refused; for a
      teardown, no client and no token left) · 1 a call failed, or the read-back did not hold · 2 a usage error, a
      refusal (the client exists, or for a rotation does not; a lifetime outside the bounds; the token file exists),
      or the record was refused because an estate value survived the scrub
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
from datetime import datetime, timezone

AGENT = "api_client.py"
IAM = "/api/fleet-management/iam"
API_TOKEN_GRANT = "urn:custom:vcf:params:oauth:grant-type:api-token"
# The bounds the broker held a create to on the reference estate (minutes), not the documented ranges.
API_TOKEN_TTL = (1440, 259200)
ACCESS_TOKEN_TTL = (30, 60)


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
        with urllib.request.urlopen(urllib.request.Request(url, data=data, method=method, headers=h),
                                    context=_ctx(), timeout=60) as r:
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
    broker = os.environ.get("OPS_BROKER_HOST") or os.environ["OPS_HOST"]
    status, answer = _send("POST", f"https://{broker}/acs/t/{broker_tenant()}/token",
                           form={"grant_type": API_TOKEN_GRANT, "api_token": _secret("OPS_API_TOKEN")})
    if status != 200 or not isinstance(answer, dict) or "access_token" not in answer:
        # a deleted or rotated API token answers 500 here, not 401: check the token still exists before its expiry
        raise RuntimeError(f"the broker did not trade the operator's API token for a bearer (HTTP {status})")
    return answer["access_token"]


class Fleet:
    """VCF Operations' fleet identity API under one bearer; every call kept, with its path templated."""

    def __init__(self, host: str, bearer: str, calls: list):
        self.base, self.bearer, self.calls = f"https://{host}/suite-api{IAM}", bearer, calls

    def call(self, method: str, path: str, shown: str, body: object | None = None) -> tuple[int, object]:
        status, answer = _send(method, self.base + path, body, {"Authorization": f"Bearer {self.bearer}"})
        self.calls.append({"method": method, "path": shown, "status": status})
        return status, answer


# ── the plan: every call and body, from the arguments alone ──────────────────────────────────────────────────────
def create_bodies(client_id: str, role: str, api_ttl: int, access_ttl: int, description: str) -> list[dict]:
    """The three writes that make one client with one role and one token, in the order they are sent."""
    return [
        {"method": "POST", "path": "/ssorealms/{realm}/api-clients",
         "body": {"clientId": client_id, "clientName": client_id, "clientDescription": description}},
        {"method": "PUT", "path": "/ssorealms/{realm}/principals/{client uuid}/roles",
         "body": {"vcfRoleAssignments": [{"roleName": role, "roleScope": {"scopeType": "SSO_REALM", "resources": []}}]}},
        {"method": "POST", "path": "/ssorealms/{realm}/api-tokens",
         "body": {"apiClientId": client_id, "tokenName": f"{client_id}-token", "tokenType": "API_CLIENT",
                  "apiTokenTtl": api_ttl, "accessTokenTtl": access_ttl}},
    ]


def rotate_calls(client_id: str, api_ttl: int, access_ttl: int) -> list[dict]:
    """A rotation in the order it is sent: the new token first, the old ones deleted only once the new one has traded."""
    return [{"method": "POST", "path": "/ssorealms/{realm}/api-clients/query and api-tokens/query  (the client and the tokens it holds)",
             "body": {}},
            {"method": "POST", "path": "/ssorealms/{realm}/api-tokens",
             "body": {"apiClientId": client_id, "tokenName": f"{client_id}-token-<UTC stamp>", "tokenType": "API_CLIENT",
                      "apiTokenTtl": api_ttl, "accessTokenTtl": access_ttl}},
            {"method": "POST", "path": "/acs/t/{broker tenant}/token at the broker  (the new token, once; with --old-token-file the old one too)",
             "body": None},
            {"method": "DELETE", "path": "/ssorealms/{realm}/api-tokens/{token id}  (each token the client held before)", "body": None},
            {"method": "POST", "path": "/acs/t/{broker tenant}/token at the broker  (with --old-token-file: the old token again, expected refused)",
             "body": None},
            {"method": "POST", "path": "/ssorealms/{realm}/api-tokens/query  (read back: one token left)", "body": {}}]


def teardown_calls(client_id: str) -> list[dict]:
    return [{"method": "POST", "path": "/ssorealms/{realm}/api-tokens/query", "body": {}},
            {"method": "DELETE", "path": "/ssorealms/{realm}/api-tokens/{token id}  (each of the client's tokens)", "body": None},
            {"method": "DELETE", "path": f"/ssorealms/{{realm}}/api-clients/{client_id}", "body": None},
            {"method": "POST", "path": "/ssorealms/{realm}/api-clients/query and api-tokens/query  (residue)", "body": {}}]


def bounds_error(api_ttl: int | None, access_ttl: int | None) -> str | None:
    if api_ttl is None or access_ttl is None:
        return "set both lifetimes: --api-token-ttl and --access-token-ttl, in minutes"
    if not API_TOKEN_TTL[0] <= api_ttl <= API_TOKEN_TTL[1]:
        return f"--api-token-ttl {api_ttl} is outside the broker's bounds of {API_TOKEN_TTL[0]} to {API_TOKEN_TTL[1]} minutes"
    if not ACCESS_TOKEN_TTL[0] <= access_ttl <= ACCESS_TOKEN_TTL[1]:
        return f"--access-token-ttl {access_ttl} is outside the broker's bounds of {ACCESS_TOKEN_TTL[0]} to {ACCESS_TOKEN_TTL[1]} minutes"
    return None


# ── the reads every run makes ────────────────────────────────────────────────────────────────────────────────────
def realm_id(fleet: Fleet) -> str | None:
    status, answer = fleet.call("GET", "/ssorealms", "/ssorealms")
    realms = (answer or {}).get("ssoRealms") or [] if isinstance(answer, dict) else []
    return realms[0].get("id") if status == 200 and realms else None


def clients(fleet: Fleet, rid: str) -> list[dict] | None:
    status, answer = fleet.call("POST", f"/ssorealms/{rid}/api-clients/query", "/ssorealms/{realm}/api-clients/query",
                                {"pageSize": 500})
    return ((answer or {}).get("apiClients") or []) if status == 200 and isinstance(answer, dict) else None


def tokens(fleet: Fleet, rid: str) -> list[dict] | None:
    status, answer = fleet.call("POST", f"/ssorealms/{rid}/api-tokens/query", "/ssorealms/{realm}/api-tokens/query", {})
    return ((answer or {}).get("apiTokens") or []) if status == 200 and isinstance(answer, dict) else None


def mine(rows: list[dict], client_id: str) -> list[dict]:
    return [r for r in rows if client_id in (r.get("clientId"), r.get("clientName"), r.get("apiClientId"), r.get("principalName"))]


def readback(fleet: Fleet, rid: str, client_id: str) -> dict:
    """What the fleet holds for the client now: its roles, and each token's status and lifetimes. No token value."""
    cl, tk = clients(fleet, rid), tokens(fleet, rid)
    if cl is None or tk is None:
        return {"error": "a list could not be read"}
    c = mine(cl, client_id)
    return {"client_present": bool(c),
            "roles": sorted({r.get("roleName") for x in c for r in (x.get("roles") or [])} - {None}),
            "role_scopes": sorted({(r.get("roleScope") or {}).get("scopeType") for x in c for r in (x.get("roles") or [])} - {None}),
            "tokens": [{"status": t.get("tokenStatus"), "api_token_ttl_min": t.get("apiTokenTtl"),
                        "access_token_ttl_min": t.get("accessTokenTtl")} for t in mine(tk, client_id)]}


def prove(token: str) -> dict:
    """Trade the new API token at the broker once: the status, and the bearer's principal type and lifetime. The
    token and the bearer stay in memory."""
    broker = os.environ.get("OPS_BROKER_HOST") or os.environ["OPS_HOST"]
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


# ── create and teardown ──────────────────────────────────────────────────────────────────────────────────────────
def create(fleet: Fleet, rid: str, a: argparse.Namespace, record: dict) -> int:
    existing = clients(fleet, rid)
    if existing is None:
        return 1
    if mine(existing, a.client_id):
        record["refused"] = "the client exists; this script never adopts a client: --teardown it first, or choose another id"
        return 2
    post, put, issue = create_bodies(a.client_id, a.role, a.api_token_ttl, a.access_token_ttl, a.description)
    status, answer = fleet.call("POST", f"/ssorealms/{rid}/api-clients", post["path"], post["body"])
    if status not in (200, 201) or not isinstance(answer, dict):
        return 1
    uuid = answer.get("clientUuid") or answer.get("id") or answer.get("uuid")
    partial = "the client exists without its role or its token: remove it with --teardown --execute before trying again"
    status, _ = fleet.call("PUT", f"/ssorealms/{rid}/principals/{uuid}/roles", put["path"], put["body"])
    if status not in (200, 201, 204):
        record["partial"] = partial
        return 1
    status, answer = fleet.call("POST", f"/ssorealms/{rid}/api-tokens", issue["path"], issue["body"])
    token = next((answer[k] for k in ("token", "apiToken", "value") if isinstance(answer, dict) and isinstance(answer.get(k), str)), None)
    if status not in (200, 201) or not token:
        record["partial"] = partial
        return 1
    fd = os.open(a.token_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(token)
    record["token_file_written"] = True
    record["exchange"] = prove(token)
    del token
    record["readback"] = rb = readback(fleet, rid, a.client_id)
    held = (rb.get("client_present") and rb.get("roles") == [a.role] and rb.get("role_scopes") == ["SSO_REALM"]
            and any(t["status"] == "ACTIVE" and t["api_token_ttl_min"] == a.api_token_ttl
                    and t["access_token_ttl_min"] == a.access_token_ttl for t in rb.get("tokens") or [])
            and record["exchange"].get("status") == 200)
    return 0 if held else 1


def rotate(fleet: Fleet, rid: str, a: argparse.Namespace, record: dict) -> int:
    """Issue a new token, prove it, delete the old ones, and read back that one is left. The client keeps its id and
    role, so an integration changes only the token it reads; with --old-token-file the record shows the old token
    working in the overlap and refused after the delete."""
    cl, tk = clients(fleet, rid), tokens(fleet, rid)
    if cl is None or tk is None:
        return 1
    if not mine(cl, a.client_id):
        record["refused"] = "no client by that id; a rotation never creates one: create it first"
        return 2
    before = [t for t in mine(tk, a.client_id) if t.get("id")]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    body = {"apiClientId": a.client_id, "tokenName": f"{a.client_id}-token-{stamp}", "tokenType": "API_CLIENT",
            "apiTokenTtl": a.api_token_ttl, "accessTokenTtl": a.access_token_ttl}
    status, answer = fleet.call("POST", f"/ssorealms/{rid}/api-tokens", "/ssorealms/{realm}/api-tokens", body)
    token = next((answer[k] for k in ("token", "apiToken", "value") if isinstance(answer, dict) and isinstance(answer.get(k), str)), None)
    if status not in (200, 201) or not token:
        record["refused"] = f"the new token was not issued (HTTP {status}); the old ones are untouched"
        return 1
    fd = os.open(a.token_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(token)
    record["token_file_written"] = True
    record["tokens_before"] = len(before)
    record["exchange"] = prove(token)
    del token
    overlap = readback(fleet, rid, a.client_id)
    record["overlap"] = {"active_tokens": sum(1 for t in overlap.get("tokens") or [] if t["status"] == "ACTIVE")}
    old = _read(a.old_token_file) if a.old_token_file else None
    if old:
        record["old_token_before_delete"] = {"status": prove(old)["status"]}
    if record["exchange"].get("status") != 200:
        record["partial"] = ("the new token did not trade at the broker, so the old ones were kept: remove the new one by "
                             "hand, or run --teardown --execute")
        return 1
    for t in before:
        fleet.call("DELETE", f"/ssorealms/{rid}/api-tokens/{t['id']}", "/ssorealms/{realm}/api-tokens/{token id}")
    if old:
        record["old_token_after_delete"] = {"status": prove(old)["status"]}
        del old
    record["readback"] = rb = readback(fleet, rid, a.client_id)
    left = rb.get("tokens") or []
    held = (len(left) == 1 and left[0]["status"] == "ACTIVE" and left[0]["api_token_ttl_min"] == a.api_token_ttl
            and left[0]["access_token_ttl_min"] == a.access_token_ttl
            and ("old_token_after_delete" not in record or record["old_token_after_delete"]["status"] != 200))
    return 0 if held else 1


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read().strip()


def teardown(fleet: Fleet, rid: str, client_id: str, record: dict) -> int:
    tk, cl = tokens(fleet, rid), clients(fleet, rid)
    if tk is None or cl is None:
        return 1
    for t in mine(tk, client_id):
        if t.get("id"):
            fleet.call("DELETE", f"/ssorealms/{rid}/api-tokens/{t['id']}", "/ssorealms/{realm}/api-tokens/{token id}")
    if mine(cl, client_id):
        fleet.call("DELETE", f"/ssorealms/{rid}/api-clients/{client_id}", "/ssorealms/{realm}/api-clients/{client id}")
    else:
        record["nothing_to_remove"] = True
    rb = readback(fleet, rid, client_id)
    record["residue"] = {"client_present": rb.get("client_present"), "tokens_left": len(rb.get("tokens") or [])}
    return 0 if rb.get("client_present") is False and not rb.get("tokens") else 1


# ── the record contract: every estate value replaced, or nothing written ─────────────────────────────────────────
PRODUCT = {"customer", "sso_realm", "api_client", "active", "expired"}
PATTERNS = [("id", re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")),
            ("host", re.compile(r"\b[a-z0-9-]+(?:\.[a-z0-9-]+)+\.[a-z]{2,}\b", re.I)),
            ("ip", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
            ("name", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)*\b"))]


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


def scrub(obj, table: dict):
    if not table:
        return obj
    rx = re.compile(r"(?<![A-Za-z0-9])(?:" + "|".join(re.escape(v) for v in sorted(table, key=len, reverse=True))
                    + r")(?![A-Za-z0-9])", re.I)
    lower = {k.lower(): v for k, v in table.items()}
    if isinstance(obj, dict):
        return {k: scrub(v, table) for k, v in obj.items()}
    if isinstance(obj, list):
        return [scrub(v, table) for v in obj]
    return rx.sub(lambda m: lower[m.group(0).lower()], obj) if isinstance(obj, str) else obj


def leaks(obj, table: dict) -> list[str]:
    found = []
    for s in _strings(obj):
        found += [k for k in table if re.search(r"(?<![A-Za-z0-9])" + re.escape(k) + r"(?![A-Za-z0-9])", s, re.I)]
        found += [m for _kind, p in PATTERNS for m in p.findall(s) if m.lower() not in PRODUCT]
    return found


# ── the run ──────────────────────────────────────────────────────────────────────────────────────────────────────
def plan_lines(a: argparse.Namespace) -> list[str]:
    if a.teardown:
        calls, kind = teardown_calls(a.client_id), "Teardown"
    elif a.rotate:
        calls, kind = rotate_calls(a.client_id, a.api_token_ttl, a.access_token_ttl), "Rotation"
    else:
        calls, kind = create_bodies(a.client_id, a.role, a.api_token_ttl, a.access_token_ttl, a.description), "Create"
    out = [f"{kind} plan for API client {a.client_id} on {os.environ.get('OPS_HOST', '<OPS_HOST>')}:"]
    for c in calls:
        out.append(f"  {c['method']:6} {c['path'] if c['path'].startswith('/acs') else IAM + c['path']}")
        if c.get("body"):
            out.append("         " + json.dumps(c["body"], sort_keys=True))
    if a.rotate:
        out.append(f"  then: the new token to {a.token_file or '<--token-file>'} (mode 0600, never printed); the old ones "
                   "are deleted only after the new one trades at the broker")
    elif not a.teardown:
        out.append(f"  then: the token to {a.token_file or '<--token-file>'} (mode 0600, never printed), traded at the broker once, "
                   "and the client and its token read back")
    return out


def report(record: dict) -> list[str]:
    lines = [f"{record['mode']}: API client {record['client']}"]
    for c in record.get("calls", []):
        lines.append(f"  {c['method']:6} {c['path']}: HTTP {c['status']}")
    if record.get("refused"):
        lines.append(f"  refused: {record['refused']}")
    if record.get("partial"):
        lines.append(f"  stopped part way: {record['partial']}")
    if "exchange" in record:
        e = record["exchange"]
        lines.append(f"  the {'new ' if record.get('mode') == 'rotate' else ''}token traded at the broker: HTTP {e.get('status')}"
                     + (f", a {e.get('principal_type')} bearer living {e.get('bearer_lifetime_min')} min" if e.get("principal_type") else ""))
    if "overlap" in record:
        lines.append(f"  in the overlap: {record['tokens_before']} token(s) held before, {record['overlap']['active_tokens']} active "
                     "with the new one")
    for key, when in (("old_token_before_delete", "before the delete"), ("old_token_after_delete", "after the delete")):
        if key in record:
            st = record[key]["status"]
            lines.append(f"  the old token at the broker, {when}: HTTP {st}, {'traded' if st == 200 else 'refused'}")
    if "readback" in record:
        rb = record["readback"]
        lines.append(f"  read back: client present {rb.get('client_present')}, roles {', '.join(rb.get('roles') or []) or 'none'} "
                     f"at {', '.join(rb.get('role_scopes') or []) or 'no'} scope; tokens "
                     + ("; ".join(f"{t['status']} API {t['api_token_ttl_min']} min, access {t['access_token_ttl_min']} min"
                                  for t in rb.get("tokens") or []) or "none"))
    if "residue" in record:
        r = record["residue"]
        lines.append(f"  residue: client present {r['client_present']}, tokens left {r['tokens_left']}"
                     + ("  (there was nothing to remove)" if record.get("nothing_to_remove") else ""))
    lines.append(f"exit {record['exit']}")
    return lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="One VCF SSO API client for one integration: plan, create, remove. Plan by default.")
    ap.add_argument("--client-id", required=True, help="the client's id, also its name; one per integration")
    ap.add_argument("--role", help="the one VCF role the client holds, at realm scope (for example vcf_viewer)")
    ap.add_argument("--api-token-ttl", type=int, help="the API token's lifetime in minutes (1440 to 259200)")
    ap.add_argument("--access-token-ttl", type=int, help="the lifetime in minutes of each bearer it yields (30 to 60)")
    ap.add_argument("--token-file", help="where the token is written, mode 0600; it must not exist")
    ap.add_argument("--description", default="an integration's own identity", help="the client's description")
    ap.add_argument("--teardown", action="store_true", help="remove the client and its tokens instead")
    ap.add_argument("--rotate", action="store_true", help="issue a new token, prove it, delete the old ones")
    ap.add_argument("--old-token-file", help="with --rotate: the token the integration holds now, to show it refused after")
    ap.add_argument("--execute", action="store_true", help="send the calls; without it the plan is printed")
    ap.add_argument("--redact", action="store_true", help="print with placeholders instead of your names")
    a = ap.parse_args(argv)
    if a.rotate and a.teardown:
        print("--rotate and --teardown are two runs, not one", file=sys.stderr)
        return 2
    if a.old_token_file and not a.rotate:
        print("--old-token-file is read only with --rotate", file=sys.stderr)
        return 2
    if a.rotate and a.old_token_file and not os.path.exists(a.old_token_file):
        print(f"{a.old_token_file} does not exist", file=sys.stderr)
        return 2
    if not a.teardown:
        problem = (None if a.role or a.rotate else "--role is required") or bounds_error(a.api_token_ttl, a.access_token_ttl)
        if not problem and a.execute and not a.token_file:
            problem = "--execute needs --token-file, where the token is written (mode 0600)"
        if not problem and a.execute and os.path.exists(a.token_file):
            problem = f"{a.token_file} exists; the token is never written over a file"
        if problem:
            print(problem, file=sys.stderr)
            return 2
    if not a.execute:
        lines = plan_lines(a)
        if a.redact:   # the plan carries the host and the client id you gave; a shared transcript carries neither
            given = [(os.environ.get("OPS_HOST", ""), "host"), (a.client_id, "client")]
            lines = scrub(lines, estate_values({"plan": lines}, [(v, k) for v, k in given if v]))
        print("\n".join(lines))
        print("\nplan only: nothing was sent (--execute sends it)")
        return 0
    if not os.environ.get("OPS_HOST") or not (os.environ.get("OPS_BEARER_FILE") or _secret("OPS_API_TOKEN")):
        print("OPS_HOST and a VCF Operations credential (OPS_API_TOKEN_FILE or OPS_BEARER_FILE) are required", file=sys.stderr)
        return 2
    record = {"captured": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "mode": "teardown" if a.teardown else "rotate" if a.rotate else "create", "client": a.client_id, "calls": []}
    if a.rotate:
        record["asked"] = {"api_token_ttl_min": a.api_token_ttl, "access_token_ttl_min": a.access_token_ttl,
                           "old_token_given": bool(a.old_token_file)}
    elif not a.teardown:
        record["asked"] = {"role": a.role, "scope": "SSO_REALM", "api_token_ttl_min": a.api_token_ttl,
                           "access_token_ttl_min": a.access_token_ttl}
    try:
        fleet = Fleet(os.environ["OPS_HOST"], ops_bearer(), record["calls"])
    except (RuntimeError, urllib.error.URLError, OSError) as e:
        print(f"could not start: {e}", file=sys.stderr)
        return 1
    rid = realm_id(fleet)
    if not rid:
        record["exit"] = 1
    else:
        record["exit"] = (teardown(fleet, rid, a.client_id, record) if a.teardown
                          else rotate(fleet, rid, a, record) if a.rotate else create(fleet, rid, a, record))
    given = [(os.environ.get(k, ""), "host") for k in ("OPS_HOST", "OPS_BROKER_HOST")] + [(a.client_id, "client")]
    table = estate_values(record, [(v, k) for v, k in given if v])
    clean = scrub(record, table)
    left = leaks(clean, table)
    out = os.environ.get("OUT", "api_client.json")
    if not (left and a.redact):
        print("\n".join(report(clean if a.redact else record)))
    if left:
        print(f"refusing to write {out}: {len(left)} estate value(s) survived the scrub", file=sys.stderr)
        return 2
    with open(out, "w", encoding="utf-8") as f:
        f.write(json.dumps(clean, indent=1, ensure_ascii=False) + "\n")
    print(f"\n{out} written with every estate value replaced")
    return record["exit"]


if __name__ == "__main__":
    sys.exit(main())
