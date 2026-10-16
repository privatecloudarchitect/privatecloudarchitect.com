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
      OUT                                 the record (default service_account.json)
Use:  python3 service_account.py --org ORG --name NAME --role "ROLE NAME" [--token-file PATH] [--execute] [--redact]
            ROLE NAME is the organization's own role name: its member role is Organization User in an All Apps
            organization and Organization Member in a classic one (identity-model's census.py --orgs-only prints the type)
      python3 service_account.py --org ORG --name NAME --teardown [--token-file PATH] [--execute] [--redact]
Exit, the first that applies, so a scheduler reads one state from one number:
      2 refused by this script before any write: the account exists (for a create), or for a teardown it is not one
        the state file records; or no organization, or more than one, carries that name exactly
      1 the run did not hold: a write was refused (a teardown's revoke among them), or the read-back was not what was
        asked (the account active, its bearer holding exactly the role, the stored token refreshing; for a teardown,
        no account left and, with --token-file, the revoked token refused)
      3 a read failed or is undetermined: the organization or the account list not read whole (a page refused, an answer
        without its list or its total, a total that changed between pages, a page that added nothing new, or pages
        that end before the total they state), the read-back or the residue could not be read back, the provider's
        credential was not traded for a bearer, or an error the script did not expect
      0 the plan printed, or the run held on read-back: for a create, the account active, its bearer's session holding
        exactly the role and the stored token refreshing; for a teardown, every revoke answered, the organization's
        list read whole with no account by that name left and, with --token-file, the revoked token refused (without
        it the token is not tried, and the record notes it). An account of that name in another organization is not
        read: the organization is the one you name
      5 a usage error (a missing or bad argument or environment variable, a role given as an id, a token file that
        exists for a create or does not for a teardown, with --execute a provider credential file that cannot be read
        or is empty), or a Python older than 3.10; nothing is written
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
from datetime import datetime, timezone

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


# ── HTTP, standard library only ──────────────────────────────────────────────────────────────────────────────────
def _ctx() -> ssl.SSLContext:
    verify = os.environ.get("TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")
    return ssl.create_default_context() if verify else ssl._create_unverified_context()


def _secret_file(name: str) -> str:
    with open(os.environ[name], encoding="utf-8") as f:
        return f.read().strip()


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
    if status not in (200, 201) or not client_id:
        if status in (200, 201):   # registered, perhaps, with no id to record: nothing here can remove it
            record["partial"] = ("the register answered without a client id, so no state file records the account: "
                                 "read the organization's service accounts, and remove one by this name where it was made")
        return EXIT_NOT_HELD
    save_state(state_path(a.org, a.name), {"tool": AGENT, "org": a.org, "name": a.name, "client_id": client_id,
                                           "created": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
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
        return EXIT_NOT_HELD
    status, _ = vcfa.call("POST", "/cloudapi/1.0.0/deviceLookup/grant", "/cloudapi/1.0.0/deviceLookup/grant",
                          body={"userCode": device.get("user_code")}, org_urn=urn, accept=ACCOUNTS_ACCEPT)
    if status not in (200, 204):
        record["partial"] = partial
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
    if any(st not in (200, 202, 204) for st in revokes):   # the revoke is what ends the refresh token (G-374)
        record["revoke_refused"] = sorted({st for st in revokes if st not in (200, 202, 204)})
    refused = (not any(t["status"] == 200 or t["bearer"] for tries in checks.values() for t in tries)
               and "revoke_refused" not in record)
    if left == [] and rows:
        state["removed"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        save_state(state_file, state)
    if left is None:
        return EXIT_UNREAD   # the residue read failed: whether the account is gone is not known
    return EXIT_OK if left == [] and refused else EXIT_NOT_HELD


def _secret_from(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read().strip()


# ── the record contract: every estate value replaced, or nothing written ─────────────────────────────────────────
PRODUCT = {"active", "created", "revoked", "organization user", "organization member", "organization administrator",
           "organization owner", "organization auditor", "service-account"}
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
    for key in ("refused", "partial"):
        if record.get(key):
            lines.append(f"  {'refused' if key == 'refused' else 'stopped part way'}: {record[key]}")
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
                         f"bearer {'issued' if t['bearer'] else 'refused'}" + (f" ({t['error']})" if t.get("error") else ""))
    lines.append(f"exit {record['exit']}")
    return lines


def credential_problem() -> str | None:
    """With --execute: the provider credential file, named but unreadable or empty, found before anything is sent."""
    for name in ("VCFA_PROVIDER_BEARER_FILE", "VCFA_PROVIDER_REFRESH_TOKEN_FILE"):
        if os.environ.get(name):
            try:
                if not _secret_file(name):
                    return f"{name} is empty"
            except (OSError, UnicodeDecodeError) as e:
                return f"{name} could not be read: {type(e).__name__}"
    return None


def usage_problem(a: argparse.Namespace) -> str | None:
    if a.teardown:
        if a.token_file and not os.path.exists(a.token_file):   # named to be tried: a file not there would pass untried
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
    a = ap.parse_args(argv)
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
    record = {"captured": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "mode": "teardown" if a.teardown else "create", "org": a.org, "name": a.name, "calls": []}
    if not a.teardown:
        record["asked"] = {"role": a.role, "scope": role_scope(a.role)}
    try:
        vcfa = Vcfa(host, provider_bearer(host), record["calls"])
    except (RuntimeError, OSError, KeyError) as e:
        print(f"could not start: {e}", file=sys.stderr)
        return EXIT_UNREAD
    record["exit"] = teardown(vcfa, a, record) if a.teardown else create(vcfa, a, record)
    return write_record(record, given, a.redact, os.environ.get("OUT", "service_account.json"))


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
