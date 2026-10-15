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
create writes a state file (STATE, default api_client.<client id>.state.json, mode 0600: the client's id and uuid and
the ids of the tokens this script issued, no secret; keep it beside the record and do not publish it), and --rotate,
--retire-old and --teardown act only on a client that file records with the same uuid, so a mistyped id, or a client
someone else made under it, is refused before anything is sent. A client made in the console is rotated and removed
in the console. None of them acts on the client the run is signed in as, a rotation included: run them on the token of
the administrator who made the client, never on the client's own. A teardown of a client that is not
there removes nothing and exits 0, so it is safe to re-run. Lifetimes outside the bounds the broker held on the
reference estate (an API token of 1,440 to 259,200 minutes, an access token of 30 to 60) are refused before anything
is sent.

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
      OUT                      the record (default api_client.json)
Use:  python3 api_client.py --client-id ID --role ROLE --api-token-ttl MIN --access-token-ttl MIN [--token-file PATH]
                            [--scope instance --instance NAME] [--execute] [--redact]
      python3 api_client.py --client-id ID --rotate --api-token-ttl MIN --access-token-ttl MIN --token-file NEW
                            [--old-token-file OLD] [--execute] [--redact]
      python3 api_client.py --client-id ID --retire-old [--old-token-file OLD] [--execute] [--redact]
      python3 api_client.py --client-id ID --teardown [--execute] [--redact]
Exit, the first that applies, so a scheduler reads one state from one number:
      2 refused by this script before any write: the client exists (for a create); no state file records the client
        with this uuid (for a rotation, a retirement or a teardown), or there is no client by that id (for a rotation or
        a retirement); the run is
        signed in as the client, or its bearer is not a JWT this script can read, for every write after the create,
        a rotation included; a retirement while the client holds one token, or whose newest token this script did not
        issue last; or the fleet holds no realm to make a client in
      1 the run did not hold: a write was refused, or the read-back was not what was asked
      3 a read failed or is undetermined: a list or the realm could not be read, the read-back could not be read, the
        operator's credential was not traded for a bearer, or an error the script did not expect
      0 the plan printed, or the run held on read-back (the client with its one role and an active token with both
        lifetimes; for a rotation, the new token proved and active beside the old ones, and, when given, the old token
        still trading; for a retirement, one token left and, when given, the old token refused; for a teardown, no
        client and no token left)
      5 a usage error (a missing or bad argument or environment variable, a lifetime outside the bounds, a token file
        that exists), a Python older than 3.10, or the record refused because an estate value survived the scrub
        (nothing is written)
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
# One exit contract for every identity companion: 0 nothing to act on, 3 a read failed or is undetermined, 5 a usage
# error; 1 and 2 are this script's own (the run did not hold; refused before any write).
EXIT_OK, EXIT_NOT_HELD, EXIT_REFUSED, EXIT_UNREAD, EXIT_USAGE = 0, 1, 2, 3, 5


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
    return [{"method": "POST", "path": "/ssorealms/{realm}/api-clients/query and api-tokens/query  (the client and the tokens it holds)",
             "body": {}},
            {"method": "POST", "path": "/ssorealms/{realm}/api-tokens",
             "body": {"apiClientId": client_id, "tokenName": f"{client_id}-token-<UTC stamp>", "tokenType": "API_CLIENT",
                      "apiTokenTtl": api_ttl, "accessTokenTtl": access_ttl}},
            {"method": "POST", "path": "/acs/t/{broker tenant}/token at the broker  (the new token, once; with --old-token-file the old one too)",
             "body": None},
            {"method": "POST", "path": "/ssorealms/{realm}/api-tokens/query  (read back: the new token active beside the old)", "body": {}}]


def retire_calls() -> list[dict]:
    """A retirement in the order it is sent: every token older than the newest deleted, then the read-back."""
    return [{"method": "POST", "path": "/ssorealms/{realm}/api-clients/query and api-tokens/query  (the client and the tokens it holds)",
             "body": {}},
            {"method": "POST", "path": "/acs/t/{broker tenant}/token at the broker  (with --old-token-file: the old token, before the delete)",
             "body": None},
            {"method": "DELETE", "path": "/ssorealms/{realm}/api-tokens/{token id}  (each token older than the newest)", "body": None},
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
    """The realm's id; "" when the fleet answered and holds no realm; None when the read failed."""
    status, answer = fleet.call("GET", "/ssorealms", "/ssorealms")
    if status != 200 or not isinstance(answer, dict):
        return None
    realms = answer.get("ssoRealms") or []
    return str(realms[0].get("id") or "") if realms else ""


def instances(fleet: Fleet, rid: str) -> dict[str, str] | None:
    """The VCF instances the realm covers, name to id, from the realm's own coverage."""
    status, answer = fleet.call("GET", f"/ssorealms/{rid}", "/ssorealms/{realm}")
    if status != 200 or not isinstance(answer, dict):
        return None
    return {str(c.get("name")): str(c.get("id")) for c in answer.get("ssoRealmCoverage") or []
            if c.get("ssoEntityType") == "VCF_INSTANCE" and c.get("id")}


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
    if is_self(me, client_id, row):
        record["refused"] = ("the run is signed in as this client: a client never rotates or removes itself, because "
                             "once its tokens change or go, no credential outlives the write to read it back or to "
                             "finish it. Run it on the token of the administrator who made the client, or do it in the "
                             "console")
        return EXIT_REFUSED
    return None


# ── create and teardown ──────────────────────────────────────────────────────────────────────────────────────────
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
    if status not in (200, 201) or not isinstance(answer, dict):
        return EXIT_NOT_HELD
    uuid = answer.get("clientUuid") or answer.get("id") or answer.get("uuid")
    state_file = state_path(a.client_id)
    state = {"tool": AGENT, "client_id": a.client_id, "client_uuid": uuid,
             "created": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "tokens": []}
    save_state(state_file, state)   # before the role and the token, so a client left part way can still be removed
    record["state_file_written"] = True
    partial = "the client exists without its role or its token: remove it with --teardown --execute before trying again"
    status, _ = fleet.call("PUT", f"/ssorealms/{rid}/principals/{uuid}/roles", put["path"], put["body"])
    if status not in (200, 201, 204):
        record["partial"] = partial
        return EXIT_NOT_HELD
    status, answer = fleet.call("POST", f"/ssorealms/{rid}/api-tokens", issue["path"], issue["body"])
    token = next((answer[k] for k in ("token", "apiToken", "value") if isinstance(answer, dict) and isinstance(answer.get(k), str)), None)
    if status not in (200, 201) or not token:
        record["partial"] = partial
        return EXIT_NOT_HELD
    fd = os.open(a.token_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(token)
    record["token_file_written"] = True
    record["exchange"] = prove(token)
    del token
    state["tokens"] = [t["id"] for t in mine(tokens(fleet, rid) or [], a.client_id) if t.get("id")]
    save_state(state_file, state)
    record["readback"] = rb = readback(fleet, rid, a.client_id)
    held = (rb.get("client_present") and rb.get("roles") == [a.role] and rb.get("role_scopes") == [scope["scopeType"]]
            and rb.get("scope_resources") == sorted(str(r.get("name")) for r in scope["resources"])
            and any(t["status"] == "ACTIVE" and t["api_token_ttl_min"] == a.api_token_ttl
                    and t["access_token_ttl_min"] == a.access_token_ttl for t in rb.get("tokens") or [])
            and record["exchange"].get("status") == 200)
    if "error" in rb:
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
    if not rows:
        record["refused"] = "no client by that id; a rotation never creates one: create it first"
        return EXIT_REFUSED
    state_file = state_path(a.client_id)
    state = load_state(state_file)
    refused = guard(fleet, a.client_id, rows[0], state, record)
    if refused is not None:
        return refused
    before = {t["id"] for t in mine(tk, a.client_id) if t.get("id")}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    body = {"apiClientId": a.client_id, "tokenName": f"{a.client_id}-token-{stamp}", "tokenType": "API_CLIENT",
            "apiTokenTtl": a.api_token_ttl, "accessTokenTtl": a.access_token_ttl}
    status, answer = fleet.call("POST", f"/ssorealms/{rid}/api-tokens", "/ssorealms/{realm}/api-tokens", body)
    token = next((answer[k] for k in ("token", "apiToken", "value") if isinstance(answer, dict) and isinstance(answer.get(k), str)), None)
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
    new = [t["id"] for t in mine(tokens(fleet, rid) or [], a.client_id) if t.get("id") and t["id"] not in before]
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
    if not rows:
        record["refused"] = "no client by that id"
        return EXIT_REFUSED
    state = load_state(state_path(a.client_id))
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
    record["readback"] = rb = readback(fleet, rid, a.client_id)
    left = rb.get("tokens") or []
    held = (len(left) == 1 and left[0]["status"] == "ACTIVE"
            and ("old_token_after_delete" not in record or record["old_token_after_delete"]["status"] != 200))
    if "error" in rb:
        return EXIT_UNREAD
    return EXIT_OK if held else EXIT_NOT_HELD


def _read(path: str) -> str:
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
        state["removed"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
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
    elif a.retire_old:
        calls, kind = retire_calls(), "Retirement"
    elif a.rotate:
        calls, kind = rotate_calls(a.client_id, a.api_token_ttl, a.access_token_ttl), "Rotation"
    else:
        scope = (instance_scope(f"<id of {a.instance}, from the realm's coverage>", a.instance) if a.scope == "instance"
                 else REALM_SCOPE)
        calls, kind = create_bodies(a.client_id, a.role, a.api_token_ttl, a.access_token_ttl, a.description, scope), "Create"
    out = [f"{kind} plan for API client {a.client_id} on {os.environ.get('OPS_HOST', '<OPS_HOST>')}:"]
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
    lines = [f"{record['mode']}: API client {record['client']}"]
    for c in record.get("calls", []):
        lines.append(f"  {c['method']:6} {c['path']}: HTTP {c['status']}" + (f" ({c['message']})" if c.get("message") else ""))
    if record.get("refused"):
        lines.append(f"  refused: {record['refused']}")
    if record.get("partial"):
        lines.append(f"  stopped part way: {record['partial']}")
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
            lines.append(f"  the old token at the broker, {when}: HTTP {st}, {'traded' if st == 200 else 'refused'}")
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


def _run(argv: list[str] | None = None) -> int:
    ap = _Parser(description="One VCF SSO API client for one integration: plan, create, remove. Plan by default.")
    ap.add_argument("--client-id", required=True, help="the client's id, also its name; one per integration")
    ap.add_argument("--role", help="the one VCF role the client holds (for example vcf_viewer)")
    ap.add_argument("--scope", choices=("realm", "instance"), default="realm",
                    help="where the role applies: the whole realm (default), or one VCF instance with --instance")
    ap.add_argument("--instance", help="with --scope instance: the VCF instance's name, as the realm's coverage names it")
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
    a = ap.parse_args(argv)
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
    if a.old_token_file and not os.path.exists(a.old_token_file):
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
    if not a.execute:
        lines = plan_lines(a)
        if a.redact:   # the plan carries the host and the client id you gave; a shared transcript carries neither
            given = [(os.environ.get("OPS_HOST", ""), "host"), (a.client_id, "client"), (a.instance or "", "instance")]
            lines = scrub(lines, estate_values({"plan": lines}, [(v, k) for v, k in given if v]))
        print("\n".join(lines))
        print("\nplan only: nothing was sent (--execute sends it)")
        return EXIT_OK
    if not os.environ.get("OPS_HOST") or not (os.environ.get("OPS_BEARER_FILE") or (_secret("OPS_API_TOKEN") or _secret("API_TOKEN"))):
        print("OPS_HOST and a VCF Operations credential (OPS_API_TOKEN_FILE or OPS_BEARER_FILE) are required", file=sys.stderr)
        return EXIT_USAGE
    mode = "teardown" if a.teardown else "retire-old" if a.retire_old else "rotate" if a.rotate else "create"
    record = {"captured": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
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
    rid = realm_id(fleet)
    if rid is None:
        record["exit"] = EXIT_UNREAD
    elif not rid:
        record["refused"] = ("the fleet holds no realm: an API client lives in a realm, so there is nothing to make it "
                             "in until VCF single sign-on has one")
        record["exit"] = EXIT_REFUSED
    else:
        record["exit"] = (teardown(fleet, rid, a.client_id, record) if a.teardown
                          else retire_old(fleet, rid, a, record) if a.retire_old
                          else rotate(fleet, rid, a, record) if a.rotate else create(fleet, rid, a, record))
    given = ([(os.environ.get(k, ""), "host") for k in ("OPS_HOST", "OPS_BROKER_HOST", "BROKER_HOST")] + [(a.client_id, "client")]
             + [(a.instance or "", "instance")])
    table = estate_values(record, [(v, k) for v, k in given if v])
    clean = scrub(record, table)
    left = leaks(clean, table)
    out = os.environ.get("OUT", "api_client.json")
    if not (left and a.redact):
        print("\n".join(report(clean if a.redact else record)))
    if left:
        print(f"refusing to write {out}: {len(left)} estate value(s) survived the scrub", file=sys.stderr)
        return EXIT_USAGE
    with open(out, "w", encoding="utf-8") as f:
        f.write(json.dumps(clean, indent=1, ensure_ascii=False) + "\n")
    print(f"\n{out} written with every estate value replaced")
    return record["exit"]


if __name__ == "__main__":
    sys.exit(main())
