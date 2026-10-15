#!/usr/bin/env python3
"""watch.py - will each federated VCF Automation organization still sign its people in after the identity
provider's next change? Read-only.

An organization federated to Entra ID keeps working only while a few things on two sides stay in step: the signing
keys it stores against the keys Entra publishes, the SAML certificate in its metadata against the one Entra signs
with, the client secret against its end date, and every imported group's name against a group assigned to the app.
None of them fails loudly. Entra's sign-in log records a success for every refusal that is VCF Automation's, and
the page a user sees names no cause. This script reads both sides and says which of them is out of step, now or at
the next roll, with an exit code a scheduler can act on.

Every call is a GET. It changes nothing on VCF Automation or on Entra.

Per organization, from VCF Automation (as the provider):
  /api/admin/org/{id}/settings/oauth        key refresh, stored signing key ids, PKCE, the client secret (see below)
  /api/admin/org/{id}/settings/federation   SAML on or off, the identity provider metadata it holds
  /cloudapi/1.0.0/groups, /cloudapi/1.0.0/users, /cloudapi/1.0.0/roles   imported group names; whether a local user holds
                                            the organization's top role
From the provider's public keys endpoint (the organization's own jwksUri): the key ids Entra publishes.
From Microsoft Graph (optional; an app permitted to read applications and service principals): the app behind
the organization (OIDC by its client id,
SAML by the organization's entity id), its client secrets' end dates, the service principal's signing
certificates, whether it is enabled and requires assignment, and the names of the groups assigned to it.

Secrets are destroyed where they arrive. The OIDC settings carry the client secret in clear and the user records a
password field; each is deleted inside the function that read it, keeping only whether one was present and, for the
client secret, its first three characters for as long as it takes to compare them with the `hint` Graph returns for
each of the app's secrets, so the check judges the secret the organization actually holds.

The key-refresh signal is the age of `lastKeySuccessfulRefresh` against `keyRefreshFrequencyInHours`, not a
difference between it and `lastKeyRefreshAttempt`. On a 24-hour interval the attempt timestamp moves every hour while
the success timestamp moves once a day, so the two differ on a healthy organization (read on two organizations,
2026-10-12). On the cycle read, the refresh ran at the first hourly run a full interval after the last success (a run
0.4 s short of the interval did not refresh), so a healthy success can be up to an hour older than the interval; older
than that, refreshes are not succeeding. `keys_held` checks the outcome
directly: a key Entra publishes and the organization does not hold fails every sign-in signed with it, and the
unknown key triggers no refresh, so sign-in stays down until a scheduled refresh or a write puts the key back.

Checks (pure functions over what was read; each returns {check, state, detail, measure}):
  key_refresh      automatic refresh on, strategy ADD, interval at most 1 h, last success not older than the interval
                   plus the hour the schedule can take (and a quarter hour of slack)
                   (a new organization has no refresh until the first scheduled run: unknown until then)
  keys_held        every key id the provider publishes is among the organization's stored keys
  pkce             usePKCE off for an Entra web app (every sign-in failed with it on)
  secret_end       the client secret the organization holds: expired fails, inside WARN_DAYS warns, and a held secret
                   that matches none of the app's secrets fails (removed at Entra, or another app's)
  saml_cert_end    the app's active SAML signing certificate: expired fails, inside WARN_DAYS warns
  saml_cert_held   the active certificate is in the organization's stored metadata (else every sign-in fails);
                   a second certificate it does not hold warns (making it active would stop sign-in)
  group_names      every imported group's name is the name of a group assigned to the app (else a rename or a
                   removed assignment: its members are refused by VCF Automation)
  app_gate         the app is enabled, and requires assignment (the first of the two gates)
  break_glass      an enabled local user holds the organization's top role (Organization Administrator in an All Apps
                   organization, Organization Owner in a classic one): the way in when the provider refuses

Env:  VCFA_HOST; VCFA_PROVIDER_REFRESH_TOKEN_FILE (a provider api-token, traded at /oauth/provider/token) or
      VCFA_PROVIDER_BEARER_FILE (a provider bearer you already hold); TLS_VERIFY=false on a self-signed lab CA (applies
      to VCF Automation and to a non-Entra keys endpoint, never to Entra or Graph); optional ENTRA_TENANT_ID,
      ENTRA_CLIENT_ID and ENTRA_CLIENT_SECRET_FILE, or ENTRA_CERT_FILE and ENTRA_KEY_FILE (PEM; needs the
      `cryptography` package): without them the Graph checks are skipped and the run says which; ORGS (comma list;
      default every organization with OIDC or SAML on, except one signed in through VCF single sign-on and the
      provider's own consumption organization); WARN_DAYS
      (default 30); OUT (default watch.json).
A read the watch could not make is never a pass. An organization whose reads fail is kept in the run, named and
counted, whether or not ORGS names it; an app or service principal Graph cannot find for an organization federated to
the Graph credential's tenant is a failed read, as is a settings read that returns no client secret to match; and a
credential refused before any organization is read ends the run at exit 3 with no record. The Graph checks are
skipped by design, and the run says why, only where no Graph credential was given, the provider is not Entra ID, or
the organization is federated to another Entra tenant than ENTRA_TENANT_ID.

Use:  python3 watch.py                      read, print, write the record
      python3 watch.py --redact             print with placeholders instead of your names (for a shared transcript)
      python3 watch.py --why "<what the user saw>" [--protocol oidc|saml]   the sign-in router; reads nothing
Exit: 0 every check ok, or skipped for a reason the run prints · 1 a warning (an end date inside WARN_DAYS, a refresh
      interval over 1 h, a gap that is not yet an outage) · 2 a failure that stops sign-in now or at the provider's
      next roll (a key not held, refresh not succeeding, an expired secret or certificate, a held secret the app no
      longer lists, a renamed group, PKCE on, a disabled app) · 3 a read failed and nothing failed (an organization
      unread, the tenant's app not found, a credential refused). --why: 0 a row matched; 1 none did, and it prints the
      first reads for a message no run showed.
"""

from __future__ import annotations

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
from datetime import datetime, timedelta, timezone

CLOUDAPI = "application/json;version=9.1.0"
VCD_JSON = "application/*+json;version=9.1.0"
SAML_METADATA = "application/samlmetadata+xml"
GRAPH = "https://graph.microsoft.com/v1.0"
ENTRA = "https://login.microsoftonline.com"
ENTRA_HOST = "login.microsoftonline.com"
# On the cycle read (one organization, 2026-10-12) the refresh ran at the first hourly run a full interval after the
# last success, and a run 0.4 s short did not: on schedule, a success's age reaches the interval plus up to an hour.
REFRESH_GRACE = timedelta(hours=1, minutes=15)
SECRET_KEYS = ("clientSecret", "password", "secretText", "hint", "privateKey")
ORDER = {"ok": 0, "unknown": 0, "warn": 1, "fail": 2}


# ── the sign-in router: what a user saw, where it was refused, what to read first ────────────────────────────
# Each row is a row of playbook 10's diagnosis table or day-2 table, with its message as the records hold it.
# `seen` are verbatim strings (an Entra code and its text, VCF Automation's page text, the URL it lands on);
# `hints` are loose words a person might type. `teaches` names the chapter section that teaches the fix.
SSO_FAILED = "Your Single Sign-On attempt failed"
SSO_FAILURE_URL = "/login/ssoFailure"
SIGN_IN_ROUTER = [
    {"id": "not-assigned", "seen": ["AADSTS50105", "to block users unless they are specifically granted"],
     "hints": ["nested group", "not assigned"], "protocol": "any", "refused_by": "provider",
     "entra_log": "the error AADSTS50105",
     "look_at": "the user's groups: a direct member of a group assigned to the app gets in; a member of a nested group does not",
     "then": "add the user to the assigned group itself", "teaches": "assignment"},
    {"id": "app-disabled", "seen": ["AADSTS7000112"], "hints": ["app disabled", "application is disabled"],
     "protocol": "any", "refused_by": "provider", "entra_log": "the error AADSTS7000112",
     "look_at": "the app's service principal: disabled at Entra",
     "then": "sign in with the organization's local administrator; enable the app again", "teaches": "app-disabled"},
    {"id": "user-disabled", "seen": ["AADSTS50057", "The user account is disabled"], "hints": ["account disabled"],
     "protocol": "any", "refused_by": "provider", "entra_log": "the error AADSTS50057",
     "look_at": "the user at Entra: disabled. Neither that nor revoking its Entra sign-in sessions ends what VCF Automation "
                "issued: on the run read, the bearer the user held ran to the end of its hour and its API token kept refreshing "
                "for the 69 minutes read, and Entra's revoke reaches only the tokens Entra issued",
     "then": "close the account in VCF Automation now, on a provider bearer: leavers.py --close-now --org <org> --user <account> "
             "in the identity-lifecycle companion plans it, and with --execute revokes its tokens and disables it", "teaches": "leaver"},
    {"id": "mfa", "seen": ["AADSTS50079", "you must enroll in multi-factor authentication", "Let's keep your account secure"],
     "hints": ["mfa", "multi-factor", "authenticator"], "protocol": "any", "refused_by": "conditional-access",
     "entra_log": "an interrupt or a failure",
     "look_at": "the user's MFA registration and the Conditional Access policy on the app, and any exemption",
     "then": "complete MFA registration, or correct the policy; an exemption must never imply entitlement", "teaches": "mfa"},
    {"id": "consent", "seen": ["AADSTS65001", "has not consented to use the application"], "hints": ["consent"],
     "protocol": "oidc", "refused_by": "provider", "entra_log": "the error AADSTS65001",
     "look_at": "admin consent on the app for openid, profile and email",
     "then": "grant admin consent once, so no user is asked", "teaches": "assignment"},
    {"id": "oidc-key-missing", "seen": [SSO_FAILED, SSO_FAILURE_URL], "hints": ["signing key", "key roll"],
     "protocol": "oidc", "refused_by": "organization", "entra_log": "a success",
     "look_at": "the organization's stored signing keys against the keys Entra publishes, and the age of its last successful refresh (watch.py: keys_held, key_refresh)",
     "then": "write Entra's current keys into the organization; sign-in works at the next attempt. Waiting means the next scheduled refresh plus about five minutes",
     "teaches": "key-rollover"},
    {"id": "oidc-group-renamed", "seen": [SSO_FAILED, SSO_FAILURE_URL], "hints": ["group renamed", "rename"],
     "protocol": "oidc", "refused_by": "organization", "entra_log": "a success",
     "look_at": "the imported group's name against the name of the group assigned to the app (watch.py: group_names)",
     "then": "restore the group's name at Entra; change it only together with the imported group", "teaches": "group-rename"},
    {"id": "oidc-secret-expired", "seen": [SSO_FAILED, SSO_FAILURE_URL], "hints": ["secret expired", "client secret"],
     "protocol": "oidc", "refused_by": "organization", "entra_log": "a success",
     "look_at": "the end date of the client secret the organization holds (watch.py: secret_end)",
     "then": "write a valid secret into the organization; next time rotate with overlap", "teaches": "secret-rotation"},
    {"id": "oidc-pkce", "seen": [SSO_FAILED, SSO_FAILURE_URL], "hints": ["pkce"],
     "protocol": "oidc", "refused_by": "organization", "entra_log": "a success",
     "look_at": "usePKCE in the organization's OIDC settings (watch.py: pkce)",
     "then": "switch it off, then prove several sign-ins spread over minutes", "teaches": "pkce"},
    {"id": "saml-certificate", "seen": ["An error occurred during login"], "hints": ["certificate", "signing certificate"],
     "protocol": "saml", "refused_by": "organization", "entra_log": "a success",
     "look_at": "the organization's stored metadata against the app's active signing certificate (watch.py: saml_cert_held)",
     "then": "load Entra's current metadata for the app into the organization", "teaches": "saml-certificate"},
    {"id": "saml-group-renamed", "seen": [SSO_FAILURE_URL], "hints": ["group renamed", "rename"],
     "protocol": "saml", "refused_by": "organization", "entra_log": "a success",
     "look_at": "the imported group's name against the name of the group assigned to the app (watch.py: group_names)",
     "then": "restore the group's name at Entra; change it only together with the imported group", "teaches": "group-rename"},
    {"id": "saml-upn-renamed", "seen": [SSO_FAILURE_URL], "hints": ["upn", "renamed user", "user name changed"],
     "protocol": "saml", "refused_by": "organization", "entra_log": "a success",
     "look_at": "whether the user's UPN changed: the organization matches a returning SAML user on its user name, so the renamed user is refused and no account is made",
     "then": "restore the user's principal name at Entra: the next sign-in reached the same account. If the new name must "
             "stay, delete the old VCF Automation account: the next sign-in made a new account holding its groups' roles. Each "
             "was run once, on an All Apps organization; the run granted the old account no direct role, so what deleting it drops "
             "was not measured. Plan the next rename as a leaver and a joiner", "teaches": "upn-rename"},
    {"id": "oidc-upn-renamed", "seen": [], "hints": ["roles gone", "second account", "lost my roles", "upn", "renamed user"],
     "protocol": "oidc", "refused_by": "none: admitted as a second user", "entra_log": "a success",
     "look_at": "the organization's subject mapping: keyed on preferred_username, a renamed user signs in as a new user holding only its groups' roles; keyed on oid, as the same user",
     "then": "grant roles only through groups; plan a rename as a leaver and a joiner and disable the first account",
     "teaches": "upn-rename"},
]


# What to read first when no row fits: a message none of the measured runs showed. It places the refusal by the plane
# that refused it, as every row does, and keeps the message, so the router can gain a row for it.
UNMATCHED = {
    "id": "no-row-fits", "seen": [], "hints": [], "protocol": "any", "refused_by": "not placed yet",
    "entra_log": "an error with an AADSTS code where Entra refused it; a success where VCF Automation did",
    "look_at": "the plane order every row follows. First Entra: the user's sign-in log for the organization's app at that "
               "minute; an error there is Entra's refusal, and its AADSTS code, pasted here, may name the row. A success there "
               "means the organization refused it: run the watch for every check, then read the organization's imported groups "
               "and the user's account",
    "then": "fix it on the plane that refused it, and keep the message with that plane, so it can become a row",
    "teaches": "assignment"}


def route(seen: str, protocol: str = "any") -> list[dict]:
    """The router rows that match what a user saw: a verbatim string first, then a loose word."""
    text = seen.lower()
    fits = [r for r in SIGN_IN_ROUTER if protocol == "any" or r["protocol"] in ("any", protocol)]
    exact = [r for r in fits if any(s.lower() in text for s in r["seen"])]
    return exact or [r for r in fits if any(h in text for h in r["hints"])]


# The checks that read the tenant's Entra app through Microsoft Graph, so they run only with the read-only app the
# tenant consents to (main's graph_checks). Without it, what each reads is a question for the tenant's identity
# administrator, and the router says so for every row that starts at one of them.
TENANT_READS = {
    "secret_end": "the client secret's end date",
    "saml_cert_end": "the signing certificate's end date",
    "saml_cert_held": "the app's active signing certificate",
    "app_gate": "whether the app requires assignment",
    "group_names": "the names of the groups assigned to the app",
}


def without_tenant_app(row: dict) -> str:
    """What a router row's first read needs when the tenant's read-only app is not held; empty when the row reads only
    the organization's side, the provider's published keys, or Entra itself."""
    asks = [v for k, v in TENANT_READS.items() if re.search(rf"\b{k}\b", row["look_at"])]
    if not asks:
        return ""
    ask = asks[0] if len(asks) == 1 else ", ".join(asks[:-1]) + " and " + asks[-1]
    return f"ask the tenant's identity administrator for {ask}; the organization's side is yours to read"


# ── time ───────────────────────────────────────────────────────────────────────────────────────────────────
def when(value: str | None) -> datetime | None:
    """An ISO 8601 instant as either API writes it (a Z suffix, three to seven fractional digits)."""
    if not value:
        return None
    m = re.match(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d+))?(Z|[+-]\d\d:\d\d)?$", value)
    if not m:
        return None
    frac = (m.group(2) or "0")[:6].ljust(6, "0")
    tz = timezone.utc if m.group(3) in (None, "Z") else datetime.strptime(m.group(3).replace(":", ""), "%z").tzinfo
    return datetime.strptime(f"{m.group(1)}.{frac}", "%Y-%m-%dT%H:%M:%S.%f").replace(tzinfo=tz)


def _days(end: datetime, now: datetime) -> float:
    return round((end - now).total_seconds() / 86400, 1)


def _result(check: str, state: str, detail: str, **measure: object) -> dict:
    return {"check": check, "state": state, "detail": detail, "measure": measure}


def _worst(*states: str) -> str:
    return max(states, key=lambda s: ORDER[s]) if states else "ok"


# ── the checks ─────────────────────────────────────────────────────────────────────────────────────────────
def key_refresh(oauth: dict, now: datetime) -> dict:
    hours = oauth.get("keyRefreshFrequencyInHours")
    success = when(oauth.get("lastKeySuccessfulRefresh"))
    age = round((now - success).total_seconds() / 3600, 1) if success else None
    if not oauth.get("autoRefreshKey"):
        return _result("key_refresh", "fail", "automatic key refresh is off: a key the provider rolls in is never fetched", interval_h=hours, success_age_h=age)
    if success is None and not oauth.get("lastKeyRefreshAttempt"):
        return _result("key_refresh", "unknown", "no scheduled refresh yet; the first runs on the hour", interval_h=hours, success_age_h=None)
    if success is None:
        return _result("key_refresh", "fail", "refreshes have run and none has succeeded", interval_h=hours, success_age_h=None)
    if hours and now - success > timedelta(hours=hours) + REFRESH_GRACE:
        return _result("key_refresh", "fail", f"the last successful refresh is {age} h old against a {hours} h interval: refreshes are not succeeding", interval_h=hours, success_age_h=age)
    notes, state = [], "ok"
    if oauth.get("keyRefreshStrategy") != "ADD":
        notes.append(f"strategy {oauth.get('keyRefreshStrategy')}, not ADD")
        state = "warn"
    if not hours or hours > 1:
        notes.append(f"refresh every {hours} h: an emergency roll at the provider stops sign-in for up to that long; set 1 h")
        state = "warn"
    return _result("key_refresh", state, "; ".join(notes) or f"refreshes every {hours} h, strategy ADD, last success on schedule", interval_h=hours, success_age_h=age)


def keys_held(held: list[str], published: list[str]) -> dict:
    missing = sorted(set(published) - set(held))
    if not published:
        return _result("keys_held", "unknown", "the provider's keys endpoint returned no keys", held=len(held), published=0)
    if missing:
        return _result("keys_held", "fail", f"{len(missing)} of {len(published)} published keys are not held: every sign-in signed with one fails until the keys are written back", held=len(held), published=len(published), missing=len(missing))
    return _result("keys_held", "ok", f"all {len(published)} published keys are held", held=len(held), published=len(published), missing=0)


def pkce(oauth: dict) -> dict:
    entra = urllib.parse.urlparse(oauth.get("issuerId") or "").hostname == ENTRA_HOST
    if not oauth.get("usePKCE"):
        return _result("pkce", "ok", "PKCE is off")
    if entra:
        return _result("pkce", "fail", "PKCE is on: every sign-in to an Entra web app failed with it on")
    return _result("pkce", "unknown", "PKCE is on; measured only against Entra web apps, where it fails")


def secret_end(app: dict, now: datetime, warn_days: int) -> dict:
    """Judge the secret the organization holds (marked `in_use` by its hint). A held secret that matches none of the
    app's secrets fails: it is the state a rotation leaves when the old secret is removed before the new one is
    written, and Entra refuses a secret it does not hold. No other secret stands in for it."""
    creds = [c for c in app.get("passwordCredentials") or [] if when(c.get("endDateTime"))]
    held = [c for c in creds if c.get("in_use")]
    if not held:
        listed = f"none of the {len(creds)} secret(s) the app lists" if creds else "no secret: the app lists none"
        return _result("secret_end", "fail", f"the secret the organization holds matches {listed}; it was removed at Entra "
                       "or is another app's, and Entra refuses a secret it does not hold: write the app's current secret "
                       "into the organization", days_left=None, matched=False, listed=len(creds))
    judged = held[0]
    days = _days(when(judged["endDateTime"]), now)
    which = "the secret the organization holds"
    others = [c for c in creds if c is not judged and when(c["endDateTime"]) < now]
    tail = f"; {len(others)} other listed secret(s) already expired" if others else ""
    if days < 0:
        return _result("secret_end", "fail", f"{which} expired {-days} days ago{tail}", days_left=days, matched=True)
    if days <= warn_days:
        return _result("secret_end", "warn", f"{which} ends in {days} days: rotate with overlap{tail}", days_left=days, matched=True)
    return _result("secret_end", "ok", f"{which} ends in {days} days{tail}", days_left=days, matched=True)


def _thumb(key_credential: dict) -> str:
    """A key credential's certificate thumbprint as upper-case hex (Graph gives it base64 in customKeyIdentifier)."""
    try:
        return base64.b64decode(key_credential.get("customKeyIdentifier") or "").hex().upper()
    except ValueError:
        return ""


def _signing(sp: dict) -> list[dict]:
    return [k for k in sp.get("keyCredentials") or [] if k.get("usage") == "Sign"]


def saml_cert_end(sp: dict, now: datetime, warn_days: int) -> dict:
    active = (sp.get("preferredTokenSigningKeyThumbprint") or "").upper()
    cert = next((k for k in _signing(sp) if _thumb(k) == active), None)
    if not active or cert is None or not when(cert.get("endDateTime")):
        return _result("saml_cert_end", "unknown", "no active signing certificate could be read on the app")
    days = _days(when(cert["endDateTime"]), now)
    if days < 0:
        return _result("saml_cert_end", "fail", f"the active signing certificate expired {-days} days ago", days_left=days)
    if days <= warn_days:
        return _result("saml_cert_end", "warn", f"the active signing certificate ends in {days} days: add the next one and load metadata carrying both", days_left=days)
    return _result("saml_cert_end", "ok", f"the active signing certificate ends in {days} days", days_left=days)


def saml_cert_held(stored: list[str], sp: dict) -> dict:
    held = {t.upper() for t in stored}
    active = (sp.get("preferredTokenSigningKeyThumbprint") or "").upper()
    others = {_thumb(k) for k in _signing(sp)} - {active, ""}
    if not active:
        return _result("saml_cert_held", "unknown", "the app names no active signing certificate")
    if active not in held:
        return _result("saml_cert_held", "fail", "the active signing certificate is not in the organization's metadata: every sign-in fails until current metadata is loaded", stored=len(held), others_not_held=len(others - held))
    if others - held:
        return _result("saml_cert_held", "warn", f"{len(others - held)} other signing certificate(s) on the app are not in the organization's metadata: making one active stops sign-in until metadata carrying it is loaded", stored=len(held), others_not_held=len(others - held))
    return _result("saml_cert_held", "ok", "the organization's metadata holds every signing certificate on the app", stored=len(held), others_not_held=0)


def group_names(assigned: list[str], imported: list[str]) -> dict:
    lost = sorted(set(imported) - set(assigned))
    unimported = sorted(set(assigned) - set(imported))
    if not imported:
        return _result("group_names", "warn", "no group is imported for this protocol: no federated user holds a role", imported=0, assigned=len(assigned))
    if lost:
        return _result("group_names", "fail", f"{len(lost)} of {len(imported)} imported groups match no group assigned to the app: renamed, or no longer assigned; their members are refused", imported=len(imported), assigned=len(assigned), unmatched=len(lost))
    if unimported:
        return _result("group_names", "warn", f"{len(unimported)} assigned group(s) are not imported: their members reach the organization and hold no role", imported=len(imported), assigned=len(assigned), unmatched=0)
    return _result("group_names", "ok", f"every imported group ({len(imported)}) is assigned to the app by that name", imported=len(imported), assigned=len(assigned), unmatched=0)


def app_gate(sp: dict) -> dict:
    if sp.get("accountEnabled") is False:
        return _result("app_gate", "fail", "the app is disabled at Entra: every federated sign-in is refused (AADSTS7000112)")
    if sp.get("appRoleAssignmentRequired") is not True:
        return _result("app_gate", "warn", "the app does not require assignment: any user of the tenant reaches the organization, and only the imported groups stand between them and a role")
    return _result("app_gate", "ok", "the app is enabled and requires assignment")


def admin_role(org_type: str, roles: list[str]) -> str:
    """The organization's top role, which differs by type: an All Apps organization has Organization Administrator, a
    classic one has none and its top role is Organization Owner. Read from the organization's own role list; the type
    decides only when that list could not be read."""
    for name in ("Organization Administrator", "Organization Owner"):
        if name in roles:
            return name
    return "Organization Owner" if org_type == "classic" else "Organization Administrator"


def break_glass(users: list[dict], role: str = "Organization Administrator") -> dict:
    admins = [u for u in users if u.get("providerType") == "LOCAL" and u.get("enabled")
              and any(r.get("name") == role for r in u.get("roleEntityRefs") or [])]
    if admins:
        return _result("break_glass", "ok", f"{len(admins)} enabled local user(s) holding {role}", local_admins=len(admins), role=role)
    return _result("break_glass", "warn", f"no enabled local user holds {role}: when the provider refuses the organization, nobody can sign in to it", local_admins=0, role=role)


# ── reading ────────────────────────────────────────────────────────────────────────────────────────────────
def _ctx(verify: bool) -> ssl.SSLContext:
    return ssl.create_default_context() if verify else ssl._create_unverified_context()


def _lab_verify() -> bool:
    return os.environ.get("TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")


def _fetch(url: str, headers: dict, verify: bool, data: bytes | None = None, method: str = "GET"):
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, context=_ctx(verify), timeout=60) as r:
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


def _secret_file(name: str) -> str:
    with open(os.environ[name], encoding="utf-8") as f:
        return f.read().strip()


class Vcfa:
    def __init__(self, host: str):
        self.host, self.verify = host, _lab_verify()
        if os.environ.get("VCFA_PROVIDER_BEARER_FILE"):
            self._bearer = _secret_file("VCFA_PROVIDER_BEARER_FILE").removeprefix("Bearer ").strip()
        else:
            form = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": _secret_file("VCFA_PROVIDER_REFRESH_TOKEN_FILE")}).encode()
            r = _fetch(f"https://{host}/oauth/provider/token", {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}, self.verify, form, "POST")
            self._bearer = r["access_token"]

    def get(self, path: str, accept: str = CLOUDAPI, org_id: str | None = None):
        h = {"Authorization": f"Bearer {self._bearer}", "Accept": accept}
        if org_id:
            h["X-VMWARE-VCLOUD-TENANT-CONTEXT"] = org_id
        return _fetch(f"https://{self.host}{path}", h, self.verify)

    def pages(self, path: str, org_id: str | None = None) -> list[dict]:
        out, page = [], 1
        while True:
            r = self.get(f"{path}{'&' if '?' in path else '?'}page={page}&pageSize=128", org_id=org_id)
            out += r.get("values") or []
            if page >= (r.get("pageCount") or 1):
                return out
            page += 1

    def oauth(self, uid: str) -> tuple[dict, str]:
        """The org's OIDC settings with the client secret destroyed; returns the secret's first three characters
        alone, for matching against Graph's hint, and the caller drops them once compared."""
        body = self.get(f"/api/admin/org/{uid}/settings/oauth", VCD_JSON)
        prefix = (body.get("clientSecret") or "")[:3]
        body["clientSecretPresent"] = _strip(body)
        return body, prefix

    def federation(self, uid: str) -> dict:
        body = self.get(f"/api/admin/org/{uid}/settings/federation", VCD_JSON)
        _strip(body)
        return body

    def sp_entity_id(self, fed: dict) -> str | None:
        href = next((ln["href"] for ln in fed.get("link") or [] if ln.get("type") == SAML_METADATA), None)
        if not href:
            return None
        xml = self.get("/" + href.split("://", 1)[-1].split("/", 1)[-1], SAML_METADATA)
        m = re.search(r'entityID="([^"]+)"', xml if isinstance(xml, str) else json.dumps(xml))
        return m.group(1) if m else None

    def roles(self, org_id: str) -> list[str]:
        return [r["name"] for r in self.pages("/cloudapi/1.0.0/roles", org_id) if r.get("name")]

    def users(self, org_id: str) -> list[dict]:
        rows = self.pages("/cloudapi/1.0.0/users", org_id)
        _strip(rows)
        return rows


class Graph:
    def __init__(self):
        self.tenant, self.client = os.environ["ENTRA_TENANT_ID"], os.environ["ENTRA_CLIENT_ID"]
        form = {"client_id": self.client, "scope": "https://graph.microsoft.com/.default", "grant_type": "client_credentials"}
        if os.environ.get("ENTRA_CLIENT_SECRET_FILE"):
            form["client_secret"] = _secret_file("ENTRA_CLIENT_SECRET_FILE")
        else:
            form["client_assertion_type"] = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
            form["client_assertion"] = self._assertion()
        r = _fetch(f"{ENTRA}/{self.tenant}/oauth2/v2.0/token", {"Content-Type": "application/x-www-form-urlencoded"}, True, urllib.parse.urlencode(form).encode(), "POST")
        self._bearer = r["access_token"]
        del form

    def _assertion(self) -> str:
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
        claims = {"aud": f"{ENTRA}/{self.tenant}/oauth2/v2.0/token", "iss": self.client, "sub": self.client,
                  "jti": str(uuid.uuid4()), "nbf": now, "iat": now, "exp": now + 600}
        signing = b64(json.dumps(head, separators=(",", ":")).encode()) + "." + b64(json.dumps(claims, separators=(",", ":")).encode())
        sig = key.sign(signing.encode(), padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH), hashes.SHA256())
        return signing + "." + b64(sig)

    def values(self, path: str, **query: str) -> list[dict]:
        qs = urllib.parse.urlencode({f"${k}": v for k, v in query.items()}, quote_via=urllib.parse.quote)
        url, out = f"{GRAPH}{path}" + (f"?{qs}" if qs else ""), []
        while url:
            r = _fetch(url, {"Authorization": f"Bearer {self._bearer}", "Accept": "application/json"}, True)
            out += r.get("value") or []
            url = r.get("@odata.nextLink")
        return out


def published_kids(jwks_uri: str) -> list[str]:
    verify = urllib.parse.urlparse(jwks_uri).hostname == ENTRA_HOST or _lab_verify()
    return [k["kid"] for k in (_fetch(jwks_uri, {"Accept": "application/json"}, verify).get("keys") or []) if k.get("kid")]


def metadata_thumbprints(xml: str) -> list[str]:
    """SHA-1 thumbprints (upper-case hex) of every certificate in SAML metadata, the form Entra names a certificate by."""
    return [hashlib.sha1(base64.b64decode(re.sub(r"\s", "", c))).hexdigest().upper()
            for c in re.findall(r"<(?:\w+:)?X509Certificate>([^<]+)<", xml or "")]


def _skipped(names: tuple[str, ...], why: str) -> list[dict]:
    return [_result(n, "unknown", f"skipped: {why}") for n in names]


ENTRA_TENANT_IN = re.compile(r"(?:login\.microsoftonline\.com|sts\.windows\.net)/([0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})/")


def entra_tenant(protocol: str, oauth: dict, fed: dict) -> str | None:
    """The Entra tenant an organization is federated to: from the OIDC issuer, or from the issuer in the SAML metadata
    it holds. None when the provider is not Entra ID."""
    text = (oauth.get("issuerId") or "") if protocol == "oidc" else (fed.get("samlMetadata") or "") if protocol == "saml" else ""
    m = ENTRA_TENANT_IN.search(text)
    return m.group(1).lower() if m else None


def graph_skip(protocol: str, tenant: str | None, graph_tenant: str | None) -> str:
    """Why the Graph checks are skipped by design for this organization, or "" when they must run. A skip is a choice
    the run prints; anything else that keeps a Graph check from running is a failed read."""
    if graph_tenant is None:
        return "no Graph credential given"
    if tenant is None:
        return "the provider is not Entra ID"
    if tenant != graph_tenant.lower():
        return "the organization is federated to another Entra tenant than ENTRA_TENANT_ID"
    return ""


def kept(result: dict, wanted: list[str]) -> bool:
    """Whether an organization belongs in the run: every one ORGS names; otherwise every federated one, and every one
    whose reads failed, since an organization that could not be read cannot be shown to be outside the watch."""
    return bool(wanted) or result.get("protocol") in ("oidc", "saml", "unread")


def watch_org(api: Vcfa, graph: Graph | None, org: dict, now: datetime, warn_days: int, seen: set,
              graph_error: str = "") -> dict:
    """Read one organization on both sides and run its checks. `seen` collects every estate value read, for the scrub.
    `graph_error` is set when a Graph credential was given and refused: every Graph check it would have run is unread."""
    uid = org["id"].rsplit(":", 1)[-1]
    seen.update({org["name"], org["id"], uid})
    out = {"org": org["name"], "org_type": "classic" if org.get("isClassicTenant") else "all-apps", "checks": [], "read_errors": []}
    try:
        oauth, prefix = api.oauth(uid)
        fed = api.federation(uid)
        users = api.users(org["id"])
        groups = api.pages("/cloudapi/1.0.0/groups", org["id"])
        roles = api.roles(org["id"])
    except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
        out["protocol"] = "unread"   # kept by main(), so a refused read is never a silent pass
        out["read_errors"].append(f"VCF Automation: {type(e).__name__}")
        return out
    for u in users:
        seen.update(v for v in (u.get("username"), u.get("email"), u.get("fullName"), u.get("nameInSource")) if v)
    for g in groups:
        seen.update(v for v in (g.get("name"), g.get("nameInSource"), g.get("id")) if v)
    oidc = bool(oauth.get("enabled")) and not oauth.get("vidb")
    saml = bool(fed.get("enabled"))
    out["protocol"] = "oidc" if oidc else "saml" if saml else "none"
    seen.update(v for v in (oauth.get("issuerId"), oauth.get("clientId"), oauth.get("jwksUri"), oauth.get("orgRedirectUri")) if v)
    checks, app, sp = out["checks"], None, None
    if oidc:
        checks.append(key_refresh(oauth, now))
        held = [k.get("keyId") for k in ((oauth.get("oAuthKeyConfigurations") or {}).get("oAuthKeyConfiguration") or [])]
        try:
            checks.append(keys_held(held, published_kids(oauth["jwksUri"])))
        except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
            checks.append(_result("keys_held", "unknown", "the provider's keys endpoint could not be read"))
            out["read_errors"].append(f"keys endpoint: {type(e).__name__}")
        checks.append(pkce(oauth))
    imported = [g["name"] for g in groups if g.get("providerType") == ("OAUTH" if oidc else "SAML")]
    graph_checks = ("secret_end", "app_gate", "group_names") if oidc else ("saml_cert_end", "saml_cert_held", "app_gate", "group_names")
    skip = graph_skip(out["protocol"], entra_tenant(out["protocol"], oauth, fed),
                      graph.tenant if graph is not None else (os.environ.get("ENTRA_TENANT_ID") if graph_error else None))
    if not (oidc or saml):
        out["read_errors"].append("neither OIDC nor SAML is on for this organization")
    elif skip:
        checks += _skipped(graph_checks, skip)
    elif graph is None:   # a Graph credential was given and refused: each check it would have run is unread
        out["read_errors"].append(graph_error)
        checks += _skipped(graph_checks, "the Graph credential given was refused")
    else:
        try:
            sel = "id,appId,displayName,passwordCredentials,identifierUris"
            if oidc:
                apps = graph.values("/applications", filter=f"appId eq '{oauth['clientId']}'", select=sel)
                looked_for = "the organization's client id"
            else:
                entity = api.sp_entity_id(fed)
                seen.update([entity] if entity else [])
                apps = graph.values("/applications", filter=f"identifierUris/any(x:x eq '{entity}')", select=sel) if entity else []
                looked_for = "the organization's entity id" if entity else "an entity id (the organization's metadata names none)"
            app = apps[0] if apps else None
            if app:
                for c in app.get("passwordCredentials") or []:
                    c["in_use"] = bool(prefix) and c.get("hint") == prefix
                _strip(app)
                seen.update(v for v in (app.get("id"), app.get("appId"), app.get("displayName"), *(app.get("identifierUris") or [])) if v)
                sps = graph.values("/servicePrincipals", filter=f"appId eq '{app['appId']}'",
                                   select="id,accountEnabled,appRoleAssignmentRequired,preferredTokenSigningKeyThumbprint,keyCredentials")
                sp = sps[0] if sps else None
                if sp is None:
                    out["read_errors"].append("Graph: the app has no service principal in the tenant")
            else:   # an app the watch cannot find is a read it could not make, never a pass
                out["read_errors"].append(f"Graph: no app in the tenant carries {looked_for}")
            if sp is not None:
                seen.add(sp["id"])
                rows = graph.values(f"/servicePrincipals/{sp['id']}/appRoleAssignedTo", select="principalDisplayName,principalType")
                assigned = [a["principalDisplayName"] for a in rows if a.get("principalType") == "Group" and a.get("principalDisplayName")]
                seen.update(assigned)
        except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
            out["read_errors"].append(f"Graph: {type(e).__name__}")
            sp = None
        held_secret = bool(prefix)
        prefix = ""
        if sp is None:
            checks += _skipped(graph_checks, "the app behind the organization could not be read in Graph")
        else:
            if oidc and not held_secret:
                out["read_errors"].append("VCF Automation: the organization's settings returned no client secret to match")
                checks += _skipped(("secret_end",), "the organization's client secret was not in its settings read")
            elif oidc:
                checks.append(secret_end(app, now, warn_days))
            else:
                checks.append(saml_cert_end(sp, now, warn_days))
                checks.append(saml_cert_held(metadata_thumbprints(fed.get("samlMetadata") or ""), sp))
            checks.append(app_gate(sp))
            checks.append(group_names(assigned, imported))
    del prefix
    checks.append(break_glass(users, admin_role(out["org_type"], roles)))
    return out


def exit_code(results: list[dict]) -> int:
    states = [c["state"] for r in results for c in r["checks"]]
    if "fail" in states:
        return 2
    if any(r["read_errors"] for r in results):
        return 3
    return 1 if "warn" in states else 0


# ── the record contract ────────────────────────────────────────────────────────────────────────────────────
UUIDISH = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
# Product vocabulary never becomes a placeholder, even when an estate object is named after it.
RESERVED = {"Organization Administrator", "Organization User", "Organization Member", "Organization Auditor", "Organization Owner",
            "Administrator", "administrator", "admin", "System", "OAUTH", "SAML", "LOCAL"}
HOSTISH = re.compile(r"\b[a-z0-9-]+(?:\.[a-z0-9-]+)+\.[a-z]{2,}\b", re.I)


def placeholders(results: list[dict]) -> dict:
    return {r["org"]: f"{{{{org-{i}}}}}" for i, r in enumerate(results, 1)}


def scrub(text: str, names: dict, seen: set) -> str:
    """Every estate value replaced in one longest-first pass; refuse when one survives."""
    seen = {v for v in seen if len(v) >= 4 and v not in RESERVED}
    table = dict(names)
    for v in sorted(seen, key=len, reverse=True):
        table.setdefault(v, "{{estate}}")
    if table:
        rx = re.compile("|".join(re.escape(k) for k in sorted(table, key=len, reverse=True)))
        text = rx.sub(lambda m: table[m.group(0)], text)
    left = [v for v in seen if v and v in text] + UUIDISH.findall(text) + HOSTISH.findall(text)
    if left:
        raise SystemExit(f"refusing to write: {len(left)} estate value(s) survived the scrub")
    return text


def record(results: list[dict], warn_days: int, now: datetime, seen: set) -> str:
    names = placeholders(results)
    doc = {"captured": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "warn_days": warn_days, "exit": exit_code(results),
           "organizations": [{**r, "org": names[r["org"]]} for r in results]}
    return scrub(json.dumps(doc, indent=2, ensure_ascii=False), names, seen | {os.environ.get("VCFA_HOST", "")} - {""})


def _print(results: list[dict], names: dict | None) -> None:
    for r in results:
        label = names[r["org"]] if names else r["org"]
        print(f"\n{label}  ({r.get('protocol', '?')}, {r['org_type']})")
        for c in r["checks"]:
            print(f"  {c['state'].upper():<8}{c['check']:<16}{c['detail']}")
        for e in r["read_errors"]:
            print(f"  READ    {e}")


def main(argv: list[str]) -> int:
    if "--why" in argv:
        seen = argv[argv.index("--why") + 1] if len(argv) > argv.index("--why") + 1 else ""
        proto = argv[argv.index("--protocol") + 1] if "--protocol" in argv else "any"
        rows = route(seen, proto)
        for r in rows:
            print(f"\n{r['id']}: refused by {r['refused_by']}; Entra's sign-in log shows {r['entra_log']}")
            print(f"  look at: {r['look_at']}\n  then:    {r['then']}")
            if without_tenant_app(r):
                print(f"  without the tenant's read-only app: {without_tenant_app(r)}")
        if not rows:
            r = UNMATCHED
            print(f"\nNo row matches; read these first. Entra's sign-in log shows {r['entra_log']}")
            print(f"  look at: {r['look_at']}\n  then:    {r['then']}")
        return 0 if rows else 1
    unknown = [a for a in argv if a not in ("--redact",)]
    if unknown:
        print(f"unknown argument(s): {' '.join(unknown)}", file=sys.stderr)
        return 3
    now = datetime.now(timezone.utc)
    warn_days = int(os.environ.get("WARN_DAYS", "30"))
    wanted = [o.strip() for o in os.environ.get("ORGS", "").split(",") if o.strip()]
    # A credential refused, or an organization list that cannot be read, ends the run before any check: exit 3, no record.
    try:
        api = Vcfa(os.environ["VCFA_HOST"])
        listed = api.pages("/cloudapi/1.0.0/orgs")
    except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
        print(f"READ FAILED: VCF Automation, before any organization was read: {type(e).__name__}; exit 3, no record written")
        return 3
    if not listed:
        print("READ FAILED: the organization list came back empty, so the credential sees no organization; exit 3, no record written")
        return 3
    graph, graph_error = None, ""
    if os.environ.get("ENTRA_TENANT_ID"):
        try:
            graph = Graph()
        except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
            graph_error = f"Graph: the token request failed ({type(e).__name__})"
    # By default the provider's own consumption organization is left out: its sign-in settings are the platform's.
    orgs = [o for o in listed if (o["name"] in wanted if wanted else not o.get("isProviderConsumptionOrg"))]
    seen = {os.environ.get("ENTRA_TENANT_ID", ""), os.environ.get("ENTRA_CLIENT_ID", "")} - {""}
    results = []
    for o in orgs:
        r = watch_org(api, graph, o, now, warn_days, seen, graph_error)
        if kept(r, wanted):
            results.append(r)
    missing = sorted(set(wanted) - {r["org"] for r in results})
    for m in missing:
        results.append({"org": m, "org_type": "?", "checks": [], "read_errors": ["no organization by that name"]})
    _print(results, placeholders(results) if "--redact" in argv else None)
    text = record(results, warn_days, now, seen)
    with open(os.environ.get("OUT", "watch.json"), "w", encoding="utf-8") as f:
        f.write(text + "\n")
    code = exit_code(results)
    print(f"\n{len(results)} organization(s); exit {code}; record written with every estate value replaced")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
