#!/usr/bin/env python3
"""leavers.py - who has left at the identity provider and can still get into VCF Automation. Report-only by default.

Removing someone at the identity provider stops their next sign-in. It does not touch the account VCF Automation
created at their first sign-in, which stays enabled, nor an API token that account holds, which keeps working until
it is revoked. And VCF Automation keys a federated account on its user name, so a new person later given the same
name signs in to the old account and holds every role granted to it directly. This script closes that gap from the
platform's side, for every organization federated to one Entra ID tenant, of either type and either protocol.

Each organization is found from its own settings: OIDC by an issuer on the tenant (its client id names the Entra
app), SAML by identity-provider metadata naming the tenant (its service-provider entity id names the app). Nothing
is declared by hand, so an organization federated later is covered on the first run after.

The rule. A federated account is a LEAVER when Entra has no user by its name, that user is disabled, or the user can
no longer pass both gates a sign-in passes:
  Entra's gate          when the app requires assignment, the user is assigned to it, directly or through a group
  VCF Automation's      the sign-in carries a group imported into the organization (a user in none is refused); with
                        groupMembershipClaims ApplicationGroup the claim carries only groups assigned to the app
Accounts are matched to Entra by the key the organization names them with, read from its own settings: by name for
OIDC keyed on preferred_username and for SAML keyed on Entra's name claim, by object id for OIDC keyed on oid. A name
is looked up by userPrincipalName, then by mail, then by otherMails (a guest's userPrincipalName in the tenant carries
#EXT#, while the name it signs in with is its own address, held in mail); exactly one Entra user across the three is
the person, and more than one is undetermined. A name no lookup finds is a leaver only when another federated account
of the same organization was found: when none was, every account of the organization is undetermined, because the
name its user key carries is not one the lookups can read. Any other key, or an account whose name does not fit its
organization's key, is undetermined. Local accounts are out of scope. Two more things are flagged and never acted on:
a federated account holding a role directly (a reused name inherits it), and an account disabled here whose name an
enabled, entitled Entra user now holds (if that is a different person, re-enabling the account hands them its roles).
A flag a person has decided on can be acknowledged until a date with --ack; the report still lists it, as such.

Fail closed. An organization whose gate cannot be read, or an account whose state cannot be read, is reported
undetermined and never acted on. Entra's directory reads settle after a change, so before acting the script reads
a leaver again CONFIRM_READS times, CONFIRM_PAUSE seconds apart, and acts only when every read agrees; otherwise the
account is left for the next run. Acting needs a named organization (--org): the script never acts on every
organization it can see. And it refuses an organization whose open leavers exceed a share no ordinary week produces
(more than MAX_LEAVERS and more than a quarter of its federated accounts, or more than --max-leavers N), closing none
of them and saying why: a wrong lookup reads everyone as gone. A leaver already disabled with no token is in step, so
a re-run changes nothing.

VCF Automation, as the provider:
  GET    /cloudapi/1.0.0/orgs                                 the organizations
  GET    /api/admin/org/{id}/settings/oauth, .../federation   each one's OIDC and SAML settings (and, for SAML, its
                                                              service-provider metadata, for the entity id)
  GET    /cloudapi/1.0.0/users, /groups, /tokens              per organization, in its tenant context
  with --execute, for each confirmed leaver:
  DELETE /cloudapi/1.0.0/tokens/{id}                          each API token the account holds
  PUT    /cloudapi/1.0.0/users/{id}                           the account's full record with enabled false, then
                                                              read back: disabled, nothing else changed, no token
Microsoft Graph (an app permitted to read users, groups, applications and service principals):
  GET /servicePrincipals, /applications, /servicePrincipals/{id}/appRoleAssignedTo, /groups (filtered)
  GET /users?$filter=userPrincipalName eq '{name}', mail eq '{name}', otherMails/any(m:m eq '{name}')
                                                              each a filter Graph serves without advanced query
                                                              parameters (no ConsistencyLevel header, no $count)
  POST /users/{id}/checkMemberGroups                          a read: which of the gate's groups the user is in

Secrets die where they arrive: the OIDC settings carry the client secret in clear, a token list can carry a token's
value and a user record a password field; each is deleted from the answer before any function sees it, and the
record keeps only the fields the allow-lists below name.

Env:  VCFA_HOST; VCFA_PROVIDER_REFRESH_TOKEN_FILE (a provider API token, traded at /oauth/provider/token) or
      VCFA_PROVIDER_BEARER_FILE (a provider bearer you already hold); TLS_VERIFY=false only on a self-signed lab CA
      (VCF Automation only; Entra and Graph are always verified); ENTRA_TENANT_ID, ENTRA_CLIENT_ID and
      ENTRA_CLIENT_SECRET_FILE, or ENTRA_CERT_FILE and ENTRA_KEY_FILE (PEM; needs the `cryptography` package);
      ORGS (comma list, to read fewer organizations); OUT (default leavers.json)
Use:  python3 leavers.py                                   report every federated organization, write the record
      python3 leavers.py --redact                          the same, printed with placeholders, to share
      python3 leavers.py --ack acks.json                   the same, with the flags a person has decided on silenced
                                                           until their date (a JSON list of {"org", "account", "flag",
                                                           "until": "YYYY-MM-DD"}; flag direct-role or
                                                           name-in-use-again); the report lists them as acknowledged
      python3 leavers.py --execute --org NAME [--user UPN] close the confirmed leavers of one organization (with
                                                           --user, only that account; every account is still read)
                     [--max-leavers N]                     refuse the organization when more than N leavers are open
                                                           (default: more than MAX_LEAVERS and more than a quarter)
      python3 leavers.py --close-now --org NAME --user ACCOUNT [--execute]
                                                           the urgent close: one named account (its user name, a
                                                           principal name or an object id), closed now without asking
                                                           Entra whether the person has left; plan only without
                                                           --execute. Needs no Graph credential.
Exit, the first that applies, so a scheduler reads one state from one number:
      2 with --execute, a close that did not hold on read-back
      1 an open leaver: an account to close (still enabled or holding a token), including one --execute refused
      3 a read failed, or an account is undetermined: nothing is known about what was not read (a credential that
        could not be obtained is one: nothing is read and nothing is written)
      4 a flag (a direct role, a name in use again) not acknowledged in --ack
      0 nothing open, nothing unread, nothing flagged (with --close-now: the plan printed, or the close held)
      5 a usage error, an unreadable --ack file, an account --close-now cannot name exactly once, or the record
        refused because an estate value survived the scrub (nothing is written)
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
from datetime import datetime, timezone
from pathlib import Path

CLOUDAPI = "application/json;version=9.1.0"
TENANT_JSON = "application/json;version=10.0.0.0-alpha"  # the version the platform's own user writes were proven with
VCD_JSON = "application/*+json;version=9.1.0"
SAML_METADATA = "application/samlmetadata+xml"
GRAPH = "https://graph.microsoft.com/v1.0"
ENTRA = "https://login.microsoftonline.com"
TENANT_HEADER = "X-VMWARE-VCLOUD-TENANT-CONTEXT"
FEDERATED = ("OAUTH", "SAML")
# How an organization's user key names its accounts, and so how Entra is asked for the person behind one. Matched by
# principal name: OIDC keyed on preferred_username and SAML keyed on Entra's name claim, the two keys the reference runs
# read. Matched by object id: OIDC keyed on oid, whose accounts are named by the object id. Any other key (sub is
# pairwise per app; an unset key falls back to it) makes every account of the organization undetermined, never a
# leaver: a lookup by the wrong name finds nobody, and nobody reads as a leaver (G-380).
BY_NAME = {"preferred_username", "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name"}
BY_ID = {"oid"}
OBJECT_ID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
# The lookups a name goes through, in order: the filter each sends to /users. Each is a form Microsoft Graph's user
# resource documents for $filter and serves by default, without the ConsistencyLevel header or $count.
NAME_LOOKUPS = (("userPrincipalName", "userPrincipalName eq '{}'"), ("mail", "mail eq '{}'"),
                ("otherMails", "otherMails/any(m:m eq '{}')"))
NO_SUCH_NAME = "no Entra user has this name"
APPLICATION_GROUP = "ApplicationGroup"
CONFIRM_READS = 3   # reads that must all say "leaver" before the script acts
CONFIRM_PAUSE = 10  # seconds between them
MAX_LEAVERS = 3     # --execute refuses an organization with more open leavers than this and than a quarter of it
FLAG_KINDS = ("direct-role", "name-in-use-again")
EXIT_HELD_NOT, EXIT_OPEN, EXIT_UNREAD, EXIT_FLAGGED, EXIT_USAGE = 2, 1, 3, 4, 5
SECRET_KEYS = {"clientSecret", "client_secret", "password", "token", "accessToken", "refreshToken", "secretText",
               "privateKey"}

# ── the allow-lists: a field not named here never reaches the record ───────────────────────────────────────────
USER = ("id", "username", "providerType", "enabled", "inheritGroupRoles")  # roles are kept by name, beside it
TOKEN = ("id", "name", "type", "expirationTimeUtc", {"owner": ("id", "name")})


def keep(obj: object, spec: tuple) -> object:
    """Only the fields `spec` names; a {field: spec} entry keeps that sub-object, or each item of that list."""
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


# ── the rule, as pure functions ──────────────────────────────────────────────────────────────────────────────────
def claim_groups(gate: dict) -> dict:
    """The imported groups a sign-in's groups claim can carry (group id -> name)."""
    if gate["group_claims"] == APPLICATION_GROUP:
        return {i: n for i, n in gate["imported_ids"].items() if i in gate["assigned_groups"]}
    return dict(gate["imported_ids"])


def watched(gate: dict) -> list[str]:
    """Every group id whose membership the decision reads."""
    return sorted(set(gate["assigned_groups"]) | set(gate["imported_ids"]))


def decide(user: dict, found: dict | None, member_of: set | None, gate: dict | None) -> tuple[str, str]:
    """One account, what Entra holds for its name, which watched groups that Entra user is in (None when unread),
    and the organization's gate: (decision, reason). Decisions: keep, leaver, out of scope, undetermined."""
    if user.get("providerType") not in FEDERATED:
        return "out of scope", f"{user.get('providerType') or 'unknown'} account, not federated"
    if gate is None:
        return "undetermined", "the organization's gate could not be read"
    if found is None:  # a leaver only while another account of the organization was found (unfound_guard)
        return "leaver", NO_SUCH_NAME
    if found.get("accountEnabled") is False:
        return "leaver", "the Entra account is disabled"
    if member_of is None:
        return "undetermined", "the user's group membership could not be read"
    entra_gate = (not gate["assignment_required"] or found.get("id") in gate["assigned_users"]
                  or bool(member_of & set(gate["assigned_groups"])))
    if not entra_gate:
        return "leaver", "not assigned to the app, directly or through a group"
    carried = member_of & set(claim_groups(gate))
    if not carried and gate.get("unresolved"):
        return "undetermined", ("an imported group matches no single Entra group ("
                                + ", ".join(gate["unresolved"]) + "), so membership through it cannot be read")
    if not carried:
        return "leaver", "in no imported group the sign-in can carry"
    return "keep", "entitled through " + ", ".join(sorted(claim_groups(gate)[g] for g in carried))


def flags(user: dict, decision: str) -> list[str]:
    """What the script reports and never acts on (IAM-F70: a name in use again takes over the account)."""
    out = []
    if user.get("providerType") in FEDERATED and user.get("roleEntityRefs"):
        out.append("direct-role: a person later given this name holds these roles at the first sign-in")
    if user.get("providerType") in FEDERATED and user.get("enabled") is False and decision == "keep":
        out.append("name-in-use-again: disabled here, and an enabled, entitled Entra user holds this name; if that "
                   "is a different person, delete the account or drop its direct roles before enabling it")
    return out


def action(user: dict, decision: str, tokens: list, execute: bool, act_on: str | None) -> str | None:
    """What the run does with an account before any confirmation: None for a kept one."""
    if decision != "leaver":
        return None
    if user.get("enabled") is False and not tokens:
        return "in step: already disabled, no token"
    if not execute:
        return "would revoke its tokens and disable it"
    if act_on and user.get("username", "").lower() != act_on.lower():
        return "would revoke its tokens and disable it (outside --user)"
    return "confirm"


def unfound_guard(rows: list[dict], key: str | None) -> int:
    """A name no lookup finds is a leaver only when another federated account of the organization was found. When
    none was, the organization's names are not ones the lookups read (a name claim sourced from another attribute),
    so every such leaver becomes undetermined. Each row carries `found` (True, False, or None when not looked up);
    returns how many rows it changed."""
    federated = [r for r in rows if r.get("providerType") in FEDERATED]
    if any(r.get("found") is True for r in federated):
        return 0
    changed = 0
    for r in federated:
        if r["decision"] == "leaver" and r["reason"] == NO_SUCH_NAME:
            r["decision"], changed = "undetermined", changed + 1
            r["reason"] = (f"no federated account of this organization matched an Entra user by userPrincipalName, mail "
                           f"or otherMails, so the name its user key ({key or 'not set'}) carries is not one this job "
                           "reads; no account of it is judged a leaver")
    return changed


def leaver_guard(open_leavers: int, federated: int, max_leavers: int | None = None) -> dict:
    """Whether --execute refuses the organization: more open leavers than --max-leavers, or by default more than
    MAX_LEAVERS and more than a quarter of its federated accounts. A share that size is a wrong lookup more often
    than a bad week, and closing it would lock out the people still there."""
    if max_leavers is not None:
        exceeded, limit = open_leavers > max_leavers, f"more than {max_leavers} (--max-leavers)"
    else:
        exceeded = open_leavers > MAX_LEAVERS and open_leavers * 4 > federated
        limit = f"more than {MAX_LEAVERS} and more than a quarter of the federated accounts"
    return {"open": open_leavers, "federated": federated, "limit": limit, "exceeded": exceeded,
            "why": (f"{open_leavers} open leavers of {federated} federated accounts is {limit}: closing none; read "
                    "why so many read gone (a name claim from another attribute, a lookup refused), then close them "
                    "by name or rerun with --max-leavers") if exceeded else ""}


def load_acks(path: str) -> list[dict]:
    """The flags a person has decided on: a JSON list of {"org", "account", "flag", "until": "YYYY-MM-DD"}. Anything
    else is refused (ValueError), never half read: a silenced flag must be one somebody wrote down."""
    acks = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(acks, list):
        raise ValueError("--ack: the file must hold a JSON list")
    for i, a in enumerate(acks):
        if not isinstance(a, dict) or not all(isinstance(a.get(k), str) and a.get(k) for k in ("org", "account", "flag", "until")):
            raise ValueError(f"--ack: entry {i} needs org, account, flag and until")
        if a["flag"] not in FLAG_KINDS:
            raise ValueError(f"--ack: entry {i} names flag {a['flag']!r}; the flags are {', '.join(FLAG_KINDS)}")
        a["until"] = datetime.strptime(a["until"], "%Y-%m-%d").strftime("%Y-%m-%d")  # malformed: ValueError
    return acks


def apply_acks(record: dict, acks: list[dict], today: str) -> None:
    """Mark each flag an acknowledgement covers (same organization, account and flag, `until` today or later) on its
    row as `acknowledged`; an expired one leaves the flag counting. Counts what matched nothing, never names it."""
    used = set()
    for o in record["organizations"]:
        for r in o["users"]:
            for f in r.get("flags") or []:
                kind = f.split(":", 1)[0]
                for i, a in enumerate(acks):
                    if a["org"] == o["org"] and a["account"].lower() == str(r.get("username", "")).lower() \
                            and a["flag"] == kind:
                        used.add(i)
                        if a["until"] >= today:
                            r.setdefault("acknowledged", []).append({"flag": kind, "until": a["until"]})
                        else:
                            r.setdefault("ack_expired", []).append({"flag": kind, "until": a["until"]})
    record["acks"] = {"entries": len(acks), "unmatched": len(acks) - len(used)}


def exit_code(summary: dict, execute: bool) -> int:
    """One state per code, the first that applies: a close that did not hold, an open leaver, a read that failed or
    an account undetermined, a flag nobody acknowledged, nothing. A flag never hides a failed read or a leaver."""
    if execute and summary.get("not_held"):
        return EXIT_HELD_NOT
    if summary.get("open_leavers"):
        return EXIT_OPEN
    if summary.get("undetermined") or summary.get("unreadable"):
        return EXIT_UNREAD
    if summary.get("flagged"):
        return EXIT_FLAGGED
    return 0


# ── HTTP, standard library only ──────────────────────────────────────────────────────────────────────────────────
def _ctx(verify: bool) -> ssl.SSLContext:
    return ssl.create_default_context() if verify else ssl._create_unverified_context()


def _lab_verify() -> bool:
    return os.environ.get("TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")


def _secret_file(name: str) -> str:
    with open(os.environ[name], encoding="utf-8") as f:
        return f.read().strip()


def _message(e: urllib.error.HTTPError) -> str:
    """The server's own words for a refusal, printed for the operator and never recorded."""
    try:
        body = json.loads(e.read() or b"{}")
        return str(body.get("message") or body.get("error_description") or body.get("error") or "")[:240] \
            if isinstance(body, dict) else ""
    except (ValueError, OSError):
        return ""


class Reader:
    """One plane under one credential. Every call is recorded with its status; secrets are deleted from each answer
    as it arrives; a refusal is recorded, never raised."""

    def __init__(self, plane: str, base: str, headers: dict, verify: bool, calls: list):
        self.plane, self.base, self.headers, self.verify, self.calls = plane, base, headers, verify, calls

    def call(self, method: str, url_or_path: str, body: object = None, accept: str = "application/json",
             headers: dict | None = None) -> tuple[int | None, object]:
        path = url_or_path.removeprefix(self.base)
        rec = {"plane": self.plane, "method": method, "path": path.split("?", 1)[0], "status": None}
        self.calls.append(rec)
        data = json.dumps(body).encode() if body is not None else None
        h = {**self.headers, "Accept": accept, **(headers or {})}
        if data is not None:
            h["Content-Type"] = "application/json"
        url = url_or_path if url_or_path.startswith("https://") else self.base + url_or_path
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=h, method=method),
                                        context=_ctx(self.verify), timeout=60) as r:
                rec["status"], raw = r.status, r.read()
        except urllib.error.HTTPError as e:
            rec["status"], rec["message"] = e.code, _message(e)
            return e.code, None
        except (urllib.error.URLError, OSError) as e:
            rec["error"] = str(getattr(e, "reason", e))[:120]
            return None, None
        try:
            answer = json.loads(raw) if raw else {}
        except ValueError:
            return rec["status"], raw.decode(errors="replace")
        strip_secrets(answer)
        return rec["status"], answer


class Vcfa(Reader):
    def __init__(self, host: str, calls: list):
        verify = _lab_verify()
        if os.environ.get("VCFA_PROVIDER_BEARER_FILE"):
            bearer = _secret_file("VCFA_PROVIDER_BEARER_FILE").removeprefix("Bearer ").strip()
        else:
            form = urllib.parse.urlencode({"grant_type": "refresh_token",
                                           "refresh_token": _secret_file("VCFA_PROVIDER_REFRESH_TOKEN_FILE")}).encode()
            req = urllib.request.Request(f"https://{host}/oauth/provider/token", data=form, method="POST", headers={
                "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
            with urllib.request.urlopen(req, context=_ctx(verify), timeout=60) as r:
                bearer = json.loads(r.read())["access_token"]
        super().__init__("vcf-automation", f"https://{host}", {"Authorization": f"Bearer {bearer}"}, verify, calls)
        del bearer

    def pages(self, path: str, org_urn: str | None = None) -> list | None:
        """Every page of a cloudapi list (pages count from 1); None when a page was refused."""
        out, page, hdr = [], 1, ({TENANT_HEADER: org_urn} if org_urn else {})
        while True:
            status, answer = self.call("GET", f"{path}?page={page}&pageSize=128", accept=TENANT_JSON if org_urn else CLOUDAPI,
                                       headers=hdr)
            if not isinstance(answer, dict):
                return None
            out += answer.get("values") or []
            if page >= int(answer.get("pageCount") or 1):
                return out
            page += 1


class Graph(Reader):
    def __init__(self, calls: list):
        tenant, client = os.environ["ENTRA_TENANT_ID"], os.environ["ENTRA_CLIENT_ID"]
        form = {"client_id": client, "scope": "https://graph.microsoft.com/.default", "grant_type": "client_credentials"}
        if os.environ.get("ENTRA_CLIENT_SECRET_FILE"):
            form["client_secret"] = _secret_file("ENTRA_CLIENT_SECRET_FILE")
        else:
            form["client_assertion_type"] = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
            form["client_assertion"] = _assertion(tenant, client)
        req = urllib.request.Request(f"{ENTRA}/{tenant}/oauth2/v2.0/token", data=urllib.parse.urlencode(form).encode(),
                                     method="POST", headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, context=_ctx(True), timeout=60) as r:
            bearer = json.loads(r.read())["access_token"]
        del form
        super().__init__("graph", GRAPH, {"Authorization": f"Bearer {bearer}"}, True, calls)
        del bearer

    def values(self, path: str, **query: str) -> list | None:
        """Every item of a Graph list, following nextLink; None when a page was refused."""
        qs = urllib.parse.urlencode({f"${k}": v for k, v in query.items()}, quote_via=urllib.parse.quote)
        url, out = f"{GRAPH}{path}" + (f"?{qs}" if qs else ""), []
        while url:
            _status, answer = self.call("GET", url)
            if not isinstance(answer, dict):
                return None
            out += answer.get("value") or []
            url = answer.get("@odata.nextLink")
        return out

    def one(self, path: str, flt: str, select: str) -> dict | None:
        rows = self.values(path, filter=flt, select=select)
        if rows is None:
            raise LookupError(f"Graph refused {path}")
        return rows[0] if len(rows) == 1 else None


def _assertion(tenant: str, client: str) -> str:
    """A signed JWT in place of a secret (PS256, x5t#S256), the form Entra takes for a certificate credential."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    def b64(b: bytes) -> str:
        return base64.urlsafe_b64encode(b).rstrip(b"=").decode()

    with open(os.environ["ENTRA_CERT_FILE"], "rb") as f:
        der = x509.load_pem_x509_certificate(f.read()).public_bytes(serialization.Encoding.DER)
    with open(os.environ["ENTRA_KEY_FILE"], "rb") as f:
        key = serialization.load_pem_private_key(f.read(), password=None)
    now = int(time.time())
    head = {"alg": "PS256", "typ": "JWT", "x5t#S256": b64(hashlib.sha256(der).digest())}
    claims = {"aud": f"{ENTRA}/{tenant}/oauth2/v2.0/token", "iss": client, "sub": client, "jti": str(uuid.uuid4()),
              "nbf": now, "iat": now, "exp": now + 600}
    signing = b64(json.dumps(head, separators=(",", ":")).encode()) + "." + b64(json.dumps(claims, separators=(",", ":")).encode())
    sig = key.sign(signing.encode(), padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
                   hashes.SHA256())
    return signing + "." + b64(sig)


# ── reading the two planes ───────────────────────────────────────────────────────────────────────────────────────
def federated_orgs(vcfa: Vcfa, tenant: str, only: list[str]) -> tuple[list[dict], list[dict], int]:
    """The organizations federated to the tenant, found from their own settings; the ones that could not be read;
    and how many others have OIDC or SAML on toward another provider."""
    found, unreadable, elsewhere = [], [], 0
    orgs = vcfa.pages("/cloudapi/1.0.0/orgs")
    if orgs is None:
        return [], [{"org": None, "reason": "the organization list was refused"}], 0
    for org in orgs:
        name = str(org.get("name"))
        if only and name not in only:
            continue
        uid, urn = str(org["id"]).rsplit(":", 1)[-1], str(org["id"])
        _s, oauth = vcfa.call("GET", f"/api/admin/org/{uid}/settings/oauth", accept=VCD_JSON)
        _s, fed = vcfa.call("GET", f"/api/admin/org/{uid}/settings/federation", accept=VCD_JSON)
        if not isinstance(oauth, dict) or not isinstance(fed, dict):
            unreadable.append({"org": name, "reason": "its identity settings were refused"})
            continue
        if oauth.get("enabled") and f"login.microsoftonline.com/{tenant}" in str(oauth.get("issuerId") or "") \
                and oauth.get("clientId"):
            found.append({"org": name, "urn": urn, "protocol": "OIDC", "app": oauth["clientId"],
                          "key": (oauth.get("oidcAttributeMapping") or {}).get("subjectAttributeName")})
        elif fed.get("enabled") and f"sts.windows.net/{tenant}" in str(fed.get("samlMetadata") or ""):
            href = next((ln["href"] for ln in fed.get("link") or [] if ln.get("type") == SAML_METADATA), None)
            _s, xml = vcfa.call("GET", "/" + href.split("://", 1)[-1].split("/", 1)[-1], accept=SAML_METADATA) \
                if href else (None, None)
            m = re.search(r'entityID="([^"]+)"', xml) if isinstance(xml, str) else None
            if m:
                found.append({"org": name, "urn": urn, "protocol": "SAML", "app": m.group(1),
                              "key": (fed.get("samlAttributeMapping") or {}).get("userNameAttributeName")})
            else:
                unreadable.append({"org": name, "reason": "its SAML service-provider metadata was refused"})
        elif oauth.get("enabled") or fed.get("enabled"):
            elsewhere += 1
    for n in sorted(set(only) - {o["org"] for o in found} - {u["org"] for u in unreadable}):
        unreadable.append({"org": n, "reason": "not found, or not federated to this tenant"})
    return found, unreadable, elsewhere


def read_gate(graph: Graph, of: dict, groups: list[dict]) -> dict:
    """Both gates of an organization: the Entra app's assignment and group claims, and the imported groups."""
    if of["protocol"] == "OIDC":
        sp = graph.one("/servicePrincipals", f"appId eq '{of['app']}'", "id,appId,appRoleAssignmentRequired")
    else:
        sp = graph.one("/servicePrincipals", f"servicePrincipalNames/any(x:x eq '{of['app']}')",
                       "id,appId,appRoleAssignmentRequired")
    if sp is None:
        raise LookupError(f"no single Entra service principal for the organization's {of['protocol']} app")
    app = graph.one("/applications", f"appId eq '{sp['appId']}'", "id,groupMembershipClaims") or {}
    assigned = graph.values(f"/servicePrincipals/{sp['id']}/appRoleAssignedTo")
    if assigned is None:
        raise LookupError("the app's assignments were refused")
    imported = sorted(str(g.get("name")) for g in groups if g.get("providerType") in FEDERATED)
    ids, unresolved = {}, []
    for name in imported:
        rows = graph.values("/groups", filter=f"displayName eq '{name}'", select="id")
        if rows is None:   # refused (GroupMember.Read.All missing): the gate cannot be read, so nothing is judged
            raise LookupError("Graph refused /groups: the imported groups cannot be matched to Entra")
        if len(rows) == 1:
            ids[rows[0]["id"]] = name
        else:              # no Entra group, or several, by that name: a rename or a duplicate, never "nobody is in it"
            unresolved.append(name)
    key = of.get("key")
    return {"user_key": key, "lookup": "name" if key in BY_NAME else "id" if key in BY_ID else None,
            "assignment_required": bool(sp.get("appRoleAssignmentRequired")),
            "group_claims": app.get("groupMembershipClaims"),
            "assigned_groups": {a["principalId"]: str(a.get("principalDisplayName")) for a in assigned
                                if a.get("principalType") == "Group"},
            "assigned_users": {a["principalId"] for a in assigned if a.get("principalType") == "User"},
            "imported": imported, "imported_ids": ids, "unresolved": unresolved}


def entra_user(graph: Graph, username: str, lookup: str = "name") -> tuple[dict | None, str | None]:
    """The Entra user an account names, and how it was found. Under oid, by object id. By name, by userPrincipalName,
    then mail, then otherMails: every lookup is read, and exactly one Entra user across them is the person (the first
    lookup that found it says how). (None, None): no lookup found anyone. A refused read, or more than one user,
    raises LookupError, so the account is undetermined and never a leaver."""
    select = "id,userPrincipalName,accountEnabled"
    if lookup == "id":
        status, answer = graph.call("GET", f"/users/{urllib.parse.quote(username)}?$select={select}")
        if status == 404:
            return None, None
        if not isinstance(answer, dict) or not answer.get("id"):
            raise LookupError("Graph refused /users/{id}")
        return answer, "id"
    if "'" in username:  # a quote would end the filter's string; such a name is never guessed at
        raise LookupError("a name holding a single quote is not looked up")
    found: dict[str, tuple[dict, str]] = {}
    for how, form in NAME_LOOKUPS:
        rows = graph.values("/users", filter=form.format(username), select=select)
        if rows is None:
            raise LookupError(f"Graph refused the {how} lookup")
        for row in rows:
            found.setdefault(str(row.get("id")), (row, how))
    if len(found) > 1:
        hows = sorted({h for _r, h in found.values()})
        raise LookupError(f"{len(found)} Entra users match this name (by {', '.join(hows)}), so which one signs in "
                          "is not known")
    return next(iter(found.values())) if found else (None, None)


def member_of(graph: Graph, user_id: str, groups: list[str]) -> set | None:
    """Which of the given groups the user is in, transitively (Graph's checkMemberGroups, at most 20 per call)."""
    out = set()
    for i in range(0, len(groups), 20):
        _s, answer = graph.call("POST", f"/users/{user_id}/checkMemberGroups", {"groupIds": groups[i:i + 20]})
        if not isinstance(answer, dict):
            return None
        out |= set(answer.get("value") or [])
    return out


class Verdict(tuple):
    """(decision, reason, found, matched_by): found is True when Entra holds the account's user, False when no lookup
    found one, None when none was made; matched_by names the lookup that found it."""

    def __new__(cls, decision: str, reason: str, found: bool | None = None, matched_by: str | None = None):
        return super().__new__(cls, (decision, reason, found, matched_by))


def judge(graph: Graph, user: dict, gate: dict | None) -> Verdict:
    """Read Entra for one account and apply the rule; a refused read makes it undetermined."""
    if user.get("providerType") not in FEDERATED or gate is None:
        return Verdict(*decide(user, None, None, gate))
    lookup = gate.get("lookup")
    if lookup is None:
        return Verdict("undetermined", f"the organization's user key ({gate.get('user_key') or 'not set'}) is not one "
                                       "this job matches to Entra, so no account of it is judged")
    if lookup == "id" and not OBJECT_ID.match(str(user.get("username"))):
        return Verdict("undetermined", "the organization is keyed on the object id and this account's name is not one")
    try:
        found, how = entra_user(graph, user["username"], lookup)
    except LookupError as e:
        return Verdict("undetermined", f"Entra could not be read for this user: {e}")
    groups = member_of(graph, found["id"], watched(gate)) if found else set()
    return Verdict(*decide(user, found, groups, gate), found is not None, how)


def confirm(graph: Graph, user: dict, gate: dict, reads: int | None = None, pause: float | None = None,
            sleep=time.sleep) -> tuple[bool, list[str]]:
    """Read the account's state again `reads` times, `pause` seconds apart; True only when every read says leaver."""
    reads = CONFIRM_READS if reads is None else reads
    pause = CONFIRM_PAUSE if pause is None else pause
    seen = []
    for i in range(reads):
        if i:
            sleep(pause)
        seen.append(judge(graph, user, gate)[0])
    return all(d == "leaver" for d in seen), seen


def close(vcfa: Vcfa, urn: str, user: dict, tokens: list[dict]) -> dict:
    """Revoke the leaver's tokens, then disable the account by a round trip of its full record; read both back.
    The record must come back unchanged apart from `enabled`; a refused call is recorded and ends this close."""
    hdr, out = {TENANT_HEADER: urn}, {"revoked": [], "disabled": False}
    for t in tokens:
        status, _a = vcfa.call("DELETE", f"/cloudapi/1.0.0/tokens/{t['id']}", accept=TENANT_JSON, headers=hdr)
        out["revoked"].append({"name": t.get("name"), "type": t.get("type"), "status": status})
    path = f"/cloudapi/1.0.0/users/{user['id']}"
    _s, before = vcfa.call("GET", path, accept=TENANT_JSON, headers=hdr)
    if not isinstance(before, dict):
        return {**out, "held": False, "error": "the account could not be read"}
    allowed = {"enabled"}
    if before.get("enabled") is not False:
        status, _a = vcfa.call("PUT", path, {**before, "enabled": False}, accept=TENANT_JSON, headers=hdr)
        if status == 400 and "field 'email'" in str(vcfa.calls[-1].get("message")):
            # a SAML account created at first sign-in can hold an email the platform refuses on update (G-316):
            # the write goes again with the email cleared, the one other field it then changes
            status, _a = vcfa.call("PUT", path, {**before, "enabled": False, "email": None}, accept=TENANT_JSON,
                                   headers=hdr)
            out["email_cleared"], allowed = True, {"enabled", "email"}
        if status != 200:
            return {**out, "held": False, "error": f"the write was refused ({status})"}
        out["disabled"] = True
    _s, after = vcfa.call("GET", path, accept=TENANT_JSON, headers=hdr)
    after = after if isinstance(after, dict) else {}
    moved = sorted(k for k in set(before) | set(after) if k not in allowed and before.get(k) != after.get(k))
    left = [t.get("name") for t in vcfa.pages("/cloudapi/1.0.0/tokens", urn) or []
            if (t.get("owner") or {}).get("id") == user["id"]]
    out["read_back"] = {"enabled": after.get("enabled"), "changed_unasked": moved, "tokens_left": left}
    out["held"] = after.get("enabled") is False and not moved and not left \
        and all(r["status"] in (200, 204) for r in out["revoked"])
    return out


def close_now(vcfa: Vcfa, org_name: str, account: str, execute: bool) -> dict:
    """The urgent close: one account of one organization, named exactly, closed now without asking Entra whether the
    person has left (they may still be entitled there, so remove them at the provider too). Plan only unless
    `execute`. Reads the organization's accounts and tokens, and touches the named account's tokens and record only;
    an account the name does not match exactly once is refused, never guessed."""
    record = {"captured": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "mode": "close-now" if execute else "close-now plan", "organizations": [], "unreadable": [],
              "federated_elsewhere": 0, "sent": []}
    orgs = vcfa.pages("/cloudapi/1.0.0/orgs")
    if orgs is None:
        record["refused"] = "the organization list was refused"
        record["summary"] = summary(record)
        return record
    org = [o for o in orgs if str(o.get("name")) == org_name]
    if len(org) != 1:
        record["refused"] = f"no single organization is named {org_name}"
        record["summary"] = summary(record)
        return record
    urn = str(org[0]["id"])
    users = vcfa.pages("/cloudapi/1.0.0/users", urn)
    tokens = vcfa.pages("/cloudapi/1.0.0/tokens", urn)
    if users is None or tokens is None:
        record["refused"] = "the organization's users or tokens were refused"
        record["summary"] = summary(record)
        return record
    match = [u for u in users if str(u.get("username", "")).lower() == account.lower()]
    if len(match) != 1:
        record["refused"] = (f"{len(match)} accounts in {org_name} are named {account}; --close-now acts on exactly one"
                             " and never guesses")
        record["summary"] = summary(record)
        return record
    user = match[0]
    mine = [t for t in tokens if (t.get("owner") or {}).get("id") == user.get("id")]
    row = {**keep(user, USER), "tokens": keep(mine, TOKEN), "decision": "closed on request",
           "reason": "named with --close-now; Entra was not asked whether the person has left",
           "direct_roles": sorted(str(r.get("name")) for r in user.get("roleEntityRefs") or []),
           "effective_roles": sorted(str(r.get("name")) for r in user.get("effectiveRoleEntityRefs") or []),
           "flags": []}
    if not execute:
        row["action"] = (f"planned: revoke {len(mine)} token(s) (DELETE /cloudapi/1.0.0/tokens/{{id}} each), then "
                         "disable the account (PUT /cloudapi/1.0.0/users/{id} with enabled false); nothing sent")
    else:
        row["action"] = "closed"
        row["result"] = close(vcfa, urn, user, mine)
    record["organizations"].append({"org": org_name, "protocol": user.get("providerType"), "user_key": None,
                                    "close_now": True, "users": [row]})
    record["summary"] = summary(record)
    record["sent"] = [f"{c['method']} {c['path']}" for c in vcfa.calls if c["method"] in ("PUT", "DELETE")]
    return record


def reconcile(vcfa: Vcfa, graph: Graph, tenant: str, only: list[str], execute: bool, act_on: str | None,
              say=print, max_leavers: int | None = None) -> dict:
    """Report every federated organization's leavers; with `execute`, close the confirmed ones of `only`, unless
    the organization's open leavers exceed the guard (leaver_guard), when none is closed."""
    orgs, unreadable, elsewhere = federated_orgs(vcfa, tenant, only)
    record = {"captured": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "mode": "execute" if execute else "report", "tenant": tenant, "organizations": [],
              "unreadable": unreadable, "federated_elsewhere": elsewhere, "sent": []}
    say(f"Leavers · {'EXECUTE' if execute else 'REPORT'} · {len(orgs)} organization(s) federated to the tenant"
        + (f", {elsewhere} federated elsewhere (not read)" if elsewhere else ""))
    for u in unreadable:
        say(f"  {u['org']}: unreadable ({u['reason']})")
    for of in orgs:
        users = vcfa.pages("/cloudapi/1.0.0/users", of["urn"])
        groups = vcfa.pages("/cloudapi/1.0.0/groups", of["urn"])
        tokens = vcfa.pages("/cloudapi/1.0.0/tokens", of["urn"])
        entry = {"org": of["org"], "protocol": of["protocol"], "user_key": of.get("key"), "users": []}
        if users is None or groups is None or tokens is None:
            entry["error"] = "the organization's users, groups or tokens were refused"
            record["organizations"].append(entry)
            say(f"  {of['org']} ({of['protocol']}): {entry['error']}")
            continue
        try:
            gate = read_gate(graph, of, groups)
        except LookupError as e:
            gate, entry["gate_error"] = None, str(e)[:160]
        if gate is not None:
            entry["gate"] = {"assignment_required": gate["assignment_required"], "group_claims": gate["group_claims"],
                             "assigned_groups": sorted(gate["assigned_groups"].values()),
                             "directly_assigned_users": len(gate["assigned_users"]), "imported": gate["imported"],
                             "claimable": sorted(claim_groups(gate).values()), "unresolved": gate["unresolved"]}
        say(f"  {of['org']} ({of['protocol']}): {len(users)} account(s), {len(tokens)} token(s); gate "
            + (", ".join(entry["gate"]["claimable"]) or "no claimable group" if gate else f"UNREAD ({entry['gate_error']})"))
        mine = {u.get("id"): [t for t in tokens if (t.get("owner") or {}).get("id") == u.get("id")] for u in users}
        for user in users:  # judge every account first: the guards below read the organization as a whole
            v = judge(graph, user, gate)
            row = {**keep(user, USER), "tokens": keep(mine[user.get("id")], TOKEN), "decision": v[0], "reason": v[1],
                   "found": v[2], "direct_roles": sorted(str(r.get("name")) for r in user.get("roleEntityRefs") or []),
                   "effective_roles": sorted(str(r.get("name")) for r in user.get("effectiveRoleEntityRefs") or [])}
            if v[3]:
                row["matched_by"] = v[3]
            entry["users"].append(row)
        unfound_guard(entry["users"], of.get("key"))
        todo = {}
        for user, row in zip(users, entry["users"], strict=True):
            row["flags"] = flags(user, row["decision"])
            todo[user.get("id")] = action(user, row["decision"], mine[user.get("id")], execute, act_on)
        federated = sum(1 for u in users if u.get("providerType") in FEDERATED)
        entry["leaver_guard"] = leaver_guard(sum(1 for t in todo.values() if t and not t.startswith("in step")),
                                             federated, max_leavers)
        for user, row in zip(users, entry["users"], strict=True):
            t = todo[user.get("id")]
            if t == "confirm" and entry["leaver_guard"]["exceeded"]:
                row["action"] = "refused: " + entry["leaver_guard"]["why"]
            elif t == "confirm":
                confirmed, reads = confirm(graph, user, gate)
                row["confirm_reads"] = reads
                if not confirmed:
                    row["action"] = "not confirmed: Entra's reads disagree; left for the next run"
                else:
                    row["action"] = "closed"
                    row["result"] = close(vcfa, of["urn"], user, mine[user.get("id")])
            elif t:
                row["action"] = t
            say(f"    {user.get('username')}: {row['decision']} ({row['reason']})"
                + (f" -> {row['action']}" if row.get("action") else "")
                + "".join(f"  FLAG {f.split(':', 1)[0]}" for f in row["flags"]))
        record["organizations"].append(entry)
    record["summary"] = summary(record)
    record["sent"] = [f"{c['method']} {c['path']}" for c in vcfa.calls if c["method"] in ("PUT", "DELETE")]
    return record


def summary(record: dict) -> dict:
    """The counts a scheduler and a reader act on, by organization and in total."""
    rows = [r for o in record["organizations"] for r in o["users"]]
    is_open = ("would", "not confirmed", "refused")

    def unacked(r: dict) -> list[str]:
        acked = {a["flag"] for a in r.get("acknowledged") or []}
        return [f for f in r["flags"] if f.split(":", 1)[0] not in acked]

    s = {k.replace(" ", "_"): sum(1 for r in rows if r["decision"] == k)
         for k in ("keep", "leaver", "out of scope", "undetermined")}
    s.update(organizations=len(record["organizations"]), federated_elsewhere=record.get("federated_elsewhere", 0),
             unreadable=len(record.get("unreadable") or []) + sum(1 for o in record["organizations"]
                                                                   if o.get("error") or o.get("gate_error")),
             open_leavers=sum(1 for r in rows if str(r.get("action", "")).startswith(is_open)),
             refused=sum(1 for r in rows if str(r.get("action", "")).startswith("refused")),
             closed=sum(1 for r in rows if r.get("action") == "closed"),
             not_held=sum(1 for r in rows if r.get("action") == "closed" and not (r.get("result") or {}).get("held")),
             in_step=sum(1 for r in rows if str(r.get("action", "")).startswith("in step")),
             direct_role=sum(1 for r in rows if any(f.startswith("direct-role") for f in r["flags"])),
             name_in_use_again=sum(1 for r in rows if any(f.startswith("name-in-use-again") for f in r["flags"])),
             acknowledged=sum(len(r.get("acknowledged") or []) for r in rows))
    s["flagged"] = sum(len(unacked(r)) for r in rows)  # what exit 4 reads: raised and not acknowledged
    s["per_org"] = [{"org": o["org"], "protocol": o["protocol"], "accounts": len(o["users"]),
                     "federated": sum(1 for r in o["users"] if r.get("providerType") in FEDERATED),
                     "found": sum(1 for r in o["users"] if r.get("found") is True),
                     "keep": sum(1 for r in o["users"] if r["decision"] == "keep"),
                     "leaver": sum(1 for r in o["users"] if r["decision"] == "leaver"),
                     "open": sum(1 for r in o["users"] if str(r.get("action", "")).startswith(is_open)),
                     "guard_exceeded": bool((o.get("leaver_guard") or {}).get("exceeded")),
                     "flagged": sum(1 for r in o["users"] if unacked(r)),
                     "direct_federated": [{"user": r.get("username"), "roles": r["direct_roles"]} for r in o["users"]
                                          if r.get("providerType") in FEDERATED and r["direct_roles"]],
                     "direct_local": sum(1 for r in o["users"] if r.get("providerType") not in FEDERATED and r["direct_roles"])}
                    for o in record["organizations"]]
    return s


# ── the record contract: every estate value replaced, or nothing written ─────────────────────────────────────────
# Product vocabulary is never registered, so it is never replaced and never mistaken for a surviving value; it is
# matched without regard to case, and it includes every decision, protocol and type the script prints (G-356).
PRODUCT = {w.lower() for w in (
    "System", "admin", "administrator", "default", "login.microsoftonline.com", "graph.microsoft.com",
    "sts.windows.net", "OIDC", "SAML", "OAUTH", "LOCAL", "LDAP", "ApplicationGroup", "SecurityGroup", "All", "None",
    "DirectoryRole", "keep", "leaver", "out of scope", "undetermined", "report", "execute", "Group", "User",
    "Organization Administrator", "Organization Owner", "Organization Member", "Organization User",
    "Organization Auditor", "Project Administrator", "Project User", "Service Broker User", "Catalog Author",
    "Organization Viewer", "Console Access Only", "Defer to Identity Provider", "ProviderConsumptionOrg")}
FIELDS = {"org": "org", "urn": "id", "id": "id", "username": "user", "user": "user", "name": "name", "tenant": "id", "app": "name",
          "assigned_groups": "group", "imported": "group", "claimable": "group", "unresolved": "group",
          "direct_roles": "role", "effective_roles": "role", "roles": "role"}
PATTERNS = [("id", re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")),
            ("host", re.compile(r"\b[a-z0-9-]+(?:\.[a-z0-9-]+)+\.[a-z]{2,}\b", re.I)),
            ("ip", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
            ("user", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)*\b"))]
NOT_SHAPED = {"captured", "expirationTimeUtc"}
PLACEHOLDER = re.compile(r"\{\{[a-z-]+-\d+\}\}")


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
    """Each estate value in the record, and each the reader was given, mapped to its placeholder: organizations
    first, then by field, then anything shaped like an id, host, address or user name."""
    table, seen, count = {}, set(), Counter()

    def add(value: str, kind: str) -> None:
        if value and len(value) >= 3 and value.lower() not in PRODUCT and value.lower() not in seen:
            seen.add(value.lower())
            count[kind] += 1
            table[value] = f"{{{{{kind}-{count[kind]}}}}}"

    for o in record.get("organizations") or []:
        add(o.get("org"), "org")
    for u in record.get("unreadable") or []:
        add(u.get("org") or "", "org")
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


def scrub(obj: object, table: dict) -> object:
    """The record with every registered value replaced by its placeholder in one pass. Keys are never touched."""
    rx, lower = _pattern(table), {k.lower(): v for k, v in table.items()}
    if rx is None:
        return obj
    if isinstance(obj, dict):
        return {k: scrub(v, table) for k, v in obj.items()}
    if isinstance(obj, list):
        return [scrub(v, table) for v in obj]
    return rx.sub(lambda m: lower[m.group(0).lower()], obj) if isinstance(obj, str) else obj


def leaks(obj: object, table: dict) -> list[str]:
    """The kind of every estate value still in a scrubbed record: a registered one, anything shaped like one, or a
    value under an identity field that is not a placeholder or product vocabulary."""
    rx, found = _pattern(table), []
    kind_of = {k.lower(): v.strip("{}").rsplit("-", 1)[0] for k, v in table.items()}
    for field, s in _strings(obj):
        rest = PLACEHOLDER.sub(" ", s)
        found += [kind_of[m.group(0).lower()] for m in rx.finditer(rest)] if rx else []
        if field not in NOT_SHAPED:
            found += [kind for kind, p in PATTERNS for m in p.findall(rest) if m.lower() not in PRODUCT]
        if field in FIELDS and len(s) >= 3 and s.lower() not in PRODUCT and re.search(r"[A-Za-z0-9]", rest):
            found.append(FIELDS[field])
    return found


def report_lines(record: dict) -> list[str]:
    """The run as the lines it prints, from the record alone (so a redacted record prints the same way)."""
    s = record["summary"]
    if record["mode"].startswith("close-now"):
        out = [f"Leavers · {record['mode'].upper()} · one named account, closed without asking Entra"]
    else:
        out = [f"Leavers · {record['mode'].upper()} · {s['organizations']} organization(s) federated to the tenant"
               + (f", {s['federated_elsewhere']} federated elsewhere (not read)" if s["federated_elsewhere"] else "")]
    out += [f"  {u['org']}: unreadable ({u['reason']})" for u in record.get("unreadable") or []]
    if record.get("refused"):
        out.append(f"  refused: {record['refused']}")
    for o in record["organizations"]:
        g = o.get("gate")
        if o.get("close_now"):
            out.append(f"  {o['org']}: one account named for --close-now; Entra not asked")
        else:
            out.append(f"  {o['org']} ({o['protocol']}): {len(o['users'])} account(s); gate "
                       + (", ".join(g["claimable"]) or "no claimable group" if g else f"UNREAD ({o.get('gate_error') or o.get('error')})"))
        direct = [f"{r.get('username')} ({', '.join(r['direct_roles'])})" for r in o["users"]
                  if r.get("providerType") in FEDERATED and r["direct_roles"]]
        out.append("    direct role assignments on federated accounts: " + ("; ".join(direct) if direct else "none"))
        guard = o.get("leaver_guard") or {}
        if guard.get("exceeded"):
            out.append(f"    --execute refuses this organization: {guard['why']}")
        for r in o["users"]:
            ends = sorted(t["expirationTimeUtc"][:10] for t in r.get("tokens") or [] if t.get("expirationTimeUtc"))
            held = (f"; {len(r['tokens'])} token(s)" + (f", the last ending {ends[-1]}" if ends else "")) if r.get("tokens") else ""
            how = f"; found by {r['matched_by']}" if r.get("matched_by") not in (None, "userPrincipalName", "id") else ""
            acked = {a["flag"]: a["until"] for a in r.get("acknowledged") or []}
            out.append(f"    {r.get('username')}: {r['decision']} ({r['reason']}{how}{held})"
                       + (f" -> {r['action']}" if r.get("action") else "")
                       + "".join(f"  FLAG {k}" + (f" (acknowledged until {acked[k]})" if k in acked else "")
                                 for k in (f.split(":", 1)[0] for f in r["flags"])))
            res = r.get("result")
            if res:
                rb = res.get("read_back") or {}
                out.append(f"      revoked {sum(1 for t in res.get('revoked') or [] if t.get('status') in (200, 204))} of "
                           f"{len(res.get('revoked') or [])} token(s); read back: enabled {rb.get('enabled')}, "
                           f"tokens left {len(rb.get('tokens_left') or [])}, other fields changed "
                           f"{len(rb.get('changed_unasked') or [])}; held {res.get('held')}"
                           + (f" ({res['error']})" if res.get("error") else ""))
    keys = ("keep", "leaver", "out_of_scope", "undetermined", "open_leavers", "refused", "closed", "not_held", "in_step",
            "direct_role", "name_in_use_again", "acknowledged", "flagged")
    out.append("  totals: " + ", ".join(f"{k.replace('_', ' ')} {s.get(k, 0)}" for k in keys))
    if (record.get("acks") or {}).get("unmatched"):
        out.append(f"  acknowledgements matching no flag: {record['acks']['unmatched']} (remove them from the --ack file)")
    if "exit" in record:
        out.append(f"  exit {record['exit']}: {EXIT_MEANS.get(record['exit'], '')}")
    return out


EXIT_MEANS = {0: "nothing open, nothing unread, nothing flagged", EXIT_OPEN: "an open leaver: run the close",
              EXIT_HELD_NOT: "a close did not hold on read-back: read the result",
              EXIT_UNREAD: "a read failed or an account is undetermined: fix the read, nothing is known about it",
              EXIT_FLAGGED: "a flag nobody acknowledged: decide it, then acknowledge it with --ack",
              EXIT_USAGE: "not run as asked"}


def given_values() -> list[tuple[str, str]]:
    out = [(os.environ.get("VCFA_HOST", ""), "host"), (os.environ.get("ENTRA_TENANT_ID", ""), "id"),
           (os.environ.get("ENTRA_CLIENT_ID", ""), "id")]
    return [(v, k) for v, k in out if v]


def _write(record: dict, calls: list, redact: bool) -> int:
    """Print the run, scrub the record and write it; refuse to write one in which an estate value survived."""
    record["calls"] = [{k: v for k, v in c.items() if k != "message"} for c in calls]
    table = estate_values(record, given_values())
    clean = scrub(record, table)
    left = leaks(clean, table)
    out = os.environ.get("OUT", "leavers.json")
    if not (left and redact):  # a redacted print with a surviving value would print that value
        print("\n".join(report_lines(clean if redact else record)))
        for c in calls:
            if c["status"] is None or c["status"] >= 400:
                where = scrub(c["path"], table) if redact else c["path"]
                print(f"  FAILED {c['plane']} {c['method']} {where}: {c['status'] or c.get('error') or ''}"
                      + ("" if redact else f" {c.get('message') or ''}"))
    if left:
        print(f"refusing to write {out}: {len(left)} estate value(s) survived the scrub ({', '.join(sorted(set(left)))})",
              file=sys.stderr)
        return EXIT_USAGE
    with open(out, "w", encoding="utf-8") as f:
        f.write(json.dumps(clean, indent=1, ensure_ascii=False) + "\n")
    print(f"\n{len(calls)} call(s), {sum(1 for c in calls if c['status'] is None or c['status'] >= 400)} refused; "
          f"{out} written with every estate value replaced; exit {record['exit']}")
    return record["exit"]


def _no_credential(e: Exception) -> int:
    """A credential that could not be obtained is a read that failed: nothing was read, so nothing is known (exit 3),
    and nothing is written. The message names the error's kind and phrase, never a secret."""
    why = getattr(e, "reason", "") or getattr(e, "code", "")
    print(f"could not obtain a credential: {type(e).__name__} {str(why)[:160]}".rstrip(), file=sys.stderr)
    return EXIT_UNREAD


def _close_now_main(a: argparse.Namespace) -> int:
    if not (a.org and a.user):
        print("--close-now needs --org and --user: it closes exactly one named account", file=sys.stderr)
        return EXIT_USAGE
    if not os.environ.get("VCFA_HOST"):
        print("set VCFA_HOST (see the header); --close-now needs no Graph credential", file=sys.stderr)
        return EXIT_USAGE
    calls: list = []
    try:
        vcfa = Vcfa(os.environ["VCFA_HOST"], calls)
    except (urllib.error.URLError, OSError, KeyError, ValueError) as e:
        return _no_credential(e)
    record = close_now(vcfa, a.org, a.user, a.execute)
    record["exit"] = EXIT_USAGE if record.get("refused") else exit_code(record["summary"], a.execute)
    return _write(record, calls, a.redact)


class _Parser(argparse.ArgumentParser):
    """argparse exits 2 on a usage error, the code this script gives a close that did not hold; it exits 5 here."""

    def error(self, message: str):
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        raise SystemExit(EXIT_USAGE)


def main(argv: list[str] | None = None) -> int:
    ap = _Parser(description="Report, and on request close, VCF Automation accounts of people who have left at "
                             "Entra ID.")
    ap.add_argument("--execute", action="store_true", help="close the confirmed leavers of the organization --org names")
    ap.add_argument("--org", help="the one organization --execute acts on")
    ap.add_argument("--user", help="with --execute, act on this account only (every account is still read)")
    ap.add_argument("--redact", action="store_true", help="print with placeholders instead of your names")
    ap.add_argument("--ack", metavar="FILE", help="acknowledged flags: a JSON list of {org, account, flag, until}")
    ap.add_argument("--max-leavers", type=int, metavar="N",
                    help=f"with --execute, refuse an organization with more than N open leavers (default: more than "
                         f"{MAX_LEAVERS} and more than a quarter of its federated accounts)")
    ap.add_argument("--close-now", action="store_true",
                    help="close the one account --user names in --org now, without asking Entra; plan only without --execute")
    a = ap.parse_args(argv)
    if a.close_now:
        return _close_now_main(a)
    if a.execute and not a.org:
        print("--execute needs --org: the script never acts on every organization it can see", file=sys.stderr)
        return EXIT_USAGE
    if (a.org or a.user) and not a.execute:
        print("--org and --user choose what --execute acts on; to read fewer organizations set ORGS", file=sys.stderr)
        return EXIT_USAGE
    if a.max_leavers is not None and (a.max_leavers < 0 or not a.execute):
        print("--max-leavers takes a number of 0 or more, and only with --execute", file=sys.stderr)
        return EXIT_USAGE
    try:
        acks = load_acks(a.ack) if a.ack else []
    except (OSError, ValueError) as e:
        print(f"--ack {a.ack}: {type(e).__name__}: {str(e)[:200]}", file=sys.stderr)
        return EXIT_USAGE
    missing = [k for k in ("VCFA_HOST", "ENTRA_TENANT_ID", "ENTRA_CLIENT_ID") if not os.environ.get(k)]
    if missing:
        print(f"set {', '.join(missing)} (see the header)", file=sys.stderr)
        return EXIT_USAGE
    calls: list = []
    try:
        vcfa, graph = Vcfa(os.environ["VCFA_HOST"], calls), Graph(calls)
    except (urllib.error.URLError, OSError, KeyError, ValueError) as e:
        return _no_credential(e)
    only = [a.org] if a.execute else [o.strip() for o in os.environ.get("ORGS", "").split(",") if o.strip()]
    record = reconcile(vcfa, graph, os.environ["ENTRA_TENANT_ID"], only, a.execute, a.user, say=lambda _m: None,
                       max_leavers=a.max_leavers)
    if a.ack:
        apply_acks(record, acks, record["captured"][:10])  # the run's own UTC date
        record["summary"] = summary(record)
    record["exit"] = exit_code(record["summary"], a.execute)
    return _write(record, calls, a.redact)


if __name__ == "__main__":
    sys.exit(main())
