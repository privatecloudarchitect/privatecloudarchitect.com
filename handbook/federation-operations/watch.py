#!/usr/bin/env python3
"""watch.py - will each federated VCF Automation organization still sign its people in after the identity
provider's next change? Read-only.

An organization federated to Entra ID keeps working only while a few things on two sides stay in step: the signing
keys it stores against the keys Entra publishes, the SAML certificate in its metadata against the one Entra signs
with, the client secret against its end date, and every imported group's name against a group assigned to the app.
None of them fails loudly. Entra's sign-in log recorded a success for every refusal of VCF Automation's read against
it, and the page a user sees names no cause. This script reads both sides and says which of them is out of step, now or at
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
0.4 s short of the interval did not refresh), so a healthy success can be up to the interval plus an hour old; older
than the interval plus an hour, refreshes are not succeeding. The age is counted in whole minutes: every hourly run
read recorded its success within the first three seconds of the hour, and a read in those seconds must not fail an
organization whose refresh is under way. `keys_held` checks the outcome
directly: a key Entra publishes and the organization does not hold fails every sign-in signed with it, and the
unknown key triggers no refresh, so sign-in stays down until a scheduled refresh or a write puts the key back.

Checks (pure functions over what was read; each returns {check, state, detail, measure}):
  key_refresh      automatic refresh on, strategy ADD, interval at most 1 h, last success not older than the interval
                   plus an hour, in whole minutes
                   (a new organization has no refresh until the first scheduled run: unknown until then)
  keys_held        every key id the provider publishes is among the organization's stored keys
  pkce             usePKCE off for an Entra web app (every sign-in failed with it on)
  secret_end       the client secret the organization holds: expired fails, inside WARN_DAYS warns, and a held secret
                   that matches none of the app's secrets fails (removed at Entra, or another app's); where several
                   share its hint, each is judged and the first to end stands; a held secret whose end date does not
                   read is unknown, unless another held one has already ended
  saml_cert_end    the app's active SAML signing certificate: expired fails, inside WARN_DAYS warns
  saml_cert_held   the active certificate is in the organization's stored metadata (else every sign-in fails);
                   a second certificate it does not hold warns (making it active would stop sign-in)
  group_names      every imported group's name is the name of a group assigned to the app (else a rename or a
                   removed assignment: its members are refused by VCF Automation)
  app_gate         the app is enabled, and requires assignment (the first of the two gates)
  break_glass      an enabled local user holds the organization's top role (Organization Administrator in an All Apps
                   organization, Organization Owner in a classic one): the way in when the provider refuses
And one for the run (own_token), on a provider API token only: the end date of the watch's own token, read from the
provider's token list (GET /cloudapi/1.0.0/tokens, every page): the REFRESH token of the session's own user, named by
VCFA_PROVIDER_TOKEN_NAME where the user holds more than one. Inside WARN_DAYS it warns (exit 1): mint the next token
under a new name, set VCFA_PROVIDER_TOKEN_NAME to it (the user now holds two) and swap the file, run the watch once on
it, then revoke the old one. A token list that could not be read, or that names no token or several, leaves the end
date undetermined (exit 3). On a provider bearer the check does not run: a bearer is minted for a run, not held by a
schedule.

Env:  VCFA_HOST; VCFA_PROVIDER_REFRESH_TOKEN_FILE (a provider api-token, traded at /oauth/provider/token) or
      VCFA_PROVIDER_BEARER_FILE (a provider bearer, minted as platform-identity's plate 04, "Your provider bearer",
      shows); VCFA_PROVIDER_TOKEN_NAME (optional: the name the provider API token was minted under, the client name
      it was registered with); TLS_VERIFY=false on a self-signed lab CA (applies
      to VCF Automation and to a non-Entra keys endpoint, never to Entra or Graph); ENTRA_TENANT_ID (the tenant this run
      covers: its id in any case, or one of its domain names), ENTRA_CLIENT_ID
      and ENTRA_CLIENT_SECRET_FILE, or ENTRA_CERT_FILE and ENTRA_KEY_FILE (PEM; needs the `cryptography` package): the
      tenant's read-only app, which the rollover checks run through; ORGS (comma list; default every organization with
      OIDC or SAML on, except one signed in through VCF single sign-on and the provider's own consumption
      organization); WARN_DAYS (default 30); OUT (default watch.json; watch.replay.json under --replay).
A read the watch could not make is never a pass, and neither is a check it did not run. Every VCF Automation list is
read until its distinct items reach the total the answer states, a page that adds no item not already read being a read
that failed at once; a Graph list is read to its last next link, a page with no item read on (Microsoft's paging guidance
says a page may hold none) and a next link that comes back a read that failed at once. A list not read whole is a read
that failed. An organization with neither OIDC nor SAML on is left out unless ORGS names it, and printed
as left out. An organization whose reads
fail is kept in the run, named and counted, whether or not ORGS names it; an app or service principal Graph cannot find
for an organization federated to the run's tenant is a failed read, and so are two apps that carry its identifier, as is a settings read that returns no
client secret to match; a credential refused before any organization is read ends the run at exit 3 with no
record; and a run that judges no organization (a wrong host, the tenant's only organization with its federation
switched off, a credential that lists none it can judge) exits 3 and says what it listed and why it judged none of
them. Without the tenant's read-only app, and not declared provider-only, the run reads the organization's side (key
refresh, keys held and PKCE over OIDC, the local administrator over either protocol) and runs none of the rollover
checks (the client secret's end date,
the SAML certificate's end date and whether the organization holds it, the app's gate, the group names), says so for
each organization ("rollover checks not run: the tenant's read-only app is owed"), and exits 3. A provider other than
Entra ID, whose side this watch does not read, is the same.

One schedule per tenant. A provider with several tenants runs the watch once per Entra tenant, each run with that
tenant's ENTRA_TENANT_ID and app, and each passing the whole tenant list with --expect-tenants. An organization
federated to another tenant than the run's is "another tenant's: its own schedule reads it": named in the run, read no
further, and left out of its exit. An organization federated to a tenant outside --expect-tenants is "uncovered: no
schedule reads it", and exits 3. A run whose tenant no organization in it names exits 3: a wrong tenant would
otherwise read as every organization being another tenant's. A domain name is resolved to the tenant's id through
Entra's public OpenID configuration for that domain; a domain Entra answers names no tenant is a usage error.

A tenant may withhold the read-only app, since its Graph permissions read the whole directory. --provider-only declares
it: the run takes no Graph credential, judges its exit on the organization's side alone, and lists the rollover checks
as owed by the tenant (ENTRA_TENANT_ID, if set, names the tenant the run covers). --tenant-attested YYYY-MM-DD gives the
date of the tenant's last report of its rollover dates (its secrets' and certificates' end dates, its assignment and its
group names); a report older than --attested-max-days (default 30) warns, in the watch's own code 1. An undeclared run
without the app still exits 3.

Use:  python3 watch.py                      read, print, write the record
      python3 watch.py --redact             print with placeholders instead of your names (for a shared transcript)
      python3 watch.py --expect-tenants T1,T2       the full tenant list (ids or domain names); with any run
      python3 watch.py --provider-only [--tenant-attested YYYY-MM-DD [--attested-max-days N]]
      python3 watch.py --why "<what the user saw>" [--protocol oidc|saml]   the sign-in router; reads nothing
      python3 watch.py --replay replay/watch       without an estate: every answer from the recorded set beside this
                                                   script (its hosts and names are placeholders); nothing is sent and
                                                   no credential is read, a request the set holds no answer for is a
                                                   read that failed (exit 3), and the record carries "replay": true, so
                                                   a reader (inventory.py) never takes it for a run of the schedule
Exit: 0 every check this run owns ran and is ok, on at least one organization · 1 a warning (an end date inside
      WARN_DAYS, the watch's own provider API token's among them, a refresh interval over 1 h, a gap that is not yet an
      outage, a tenant's report older than --attested-max-days) · 2 a failure that stops
      sign-in now or at the provider's next roll (a key not held, refresh not succeeding, an expired secret or
      certificate, a held secret the app no longer lists, a renamed group, PKCE on, a disabled app) · 3 nothing failed,
      and a read failed or a result is undetermined: an organization unread, the tenant's app not found, a credential
      refused, a check that could not judge, the rollover checks not run on an undeclared run, an organization no
      schedule reads, a run whose tenant no organization names, a run that judged no organization, the watch's own
      token's end date unread, a record that could not be written, or a request a --replay set holds no answer for
      · 5 a usage error: an unknown or missing argument, a missing or inconsistent environment variable, a credential
      or key file that cannot be read, a tenant or date that names nothing, a --replay directory that cannot be read
      or holds no replay set, a Python older than 3.9. An error the watch did not
      expect exits 3, never 1. --why: 0 a row matched; 1 none did, and it prints the first reads for a message no run
      showed.
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
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

CLOUDAPI = "application/json;version=9.1.0"
VCD_JSON = "application/*+json;version=9.1.0"
SAML_METADATA = "application/samlmetadata+xml"
GRAPH = "https://graph.microsoft.com/v1.0"
ENTRA = "https://login.microsoftonline.com"
ENTRA_HOST = "login.microsoftonline.com"
# On the cycle read (one organization, 2026-10-12) the refresh ran at the first hourly run a full interval after the
# last success, and a run 0.4 s short did not: on schedule, a success's age reaches the interval plus up to an hour.
# Past the interval plus an hour, counted in whole minutes, refreshes are not succeeding (IAM-F86).
REFRESH_GRACE = timedelta(hours=1)
# Every list is read page by page; a page of this size is the most the platform was asked for at once.
PAGE_SIZE = 128
SECRET_KEYS = ("clientSecret", "password", "secretText", "hint", "privateKey")
ORDER = {"ok": 0, "unknown": 0, "warn": 1, "fail": 2}
# One code per state a scheduler acts on (the identity companions' shared contract): 0 nothing to act on, 1 a warning,
# 2 a failure, 3 a read failed or a result is undetermined (never a finding), 5 not run as asked.
EXIT_OK, EXIT_WARN, EXIT_FAIL, EXIT_UNREAD, EXIT_USAGE = 0, 1, 2, 3, 5


# ── the sign-in router: what a user saw, where it was refused, what to read first ────────────────────────────
# Each row is a row of playbook 10's diagnosis table or day-2 table, with its message as the records hold it.
# `seen` are verbatim strings (an Entra code and its text, VCF Automation's page text, the URL it lands on);
# `hints` are loose words a person might type. `teaches` names the chapter section that teaches the fix.
SSO_FAILED = "Your Single Sign-On attempt failed"
SSO_FAILURE_URL = "/login/ssoFailure"
# What Entra's sign-in log shows for a refusal by the organization: a success, on every such refusal read against the
# log (an OIDC signing key missing, a group renamed over OIDC and SAML, a SAML certificate not held, an expired OIDC
# secret). Two cases were not read against it, so their rows say that rather than borrow the others' answer.
LOG_READ, LOG_NOT_READ = "a success", "not read for this case; each refusal by the organization that was read showed a success"
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
             "in the identity-lifecycle companion plans it, and with --execute revokes its tokens and disables it. Under oid "
             "the account is the person's object id, from the tenant's dated leaver notice; a principal name given with "
             "--left-on, the notice's departure date, is resolved to it in the plan", "teaches": "leaver"},
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
     "protocol": "oidc", "refused_by": "organization", "entra_log": LOG_READ,
     "look_at": "the organization's stored signing keys against the keys Entra publishes, and the age of its last successful refresh (watch.py: keys_held, key_refresh)",
     "then": "write Entra's current keys into the organization; sign-in works at the next attempt. Waiting means the next successful refresh, at most the interval plus an hour after the last one, and about five minutes more",
     "teaches": "key-rollover"},
    {"id": "oidc-group-renamed", "seen": [SSO_FAILED, SSO_FAILURE_URL], "hints": ["group renamed", "rename"],
     "protocol": "oidc", "refused_by": "organization", "entra_log": LOG_READ,
     "look_at": "the imported group's name against the name of the group assigned to the app (watch.py: group_names)",
     "then": "restore the group's name at Entra; change it only together with the imported group", "teaches": "group-rename"},
    {"id": "oidc-secret-expired", "seen": [SSO_FAILED, SSO_FAILURE_URL], "hints": ["secret expired", "client secret"],
     "protocol": "oidc", "refused_by": "organization", "entra_log": LOG_READ,
     "look_at": "the end date of the client secret the organization holds (watch.py: secret_end)",
     "then": "write a valid secret into the organization; next time rotate with overlap", "teaches": "secret-rotation"},
    {"id": "oidc-pkce", "seen": [SSO_FAILED, SSO_FAILURE_URL], "hints": ["pkce"],
     "protocol": "oidc", "refused_by": "organization", "entra_log": LOG_NOT_READ,
     "look_at": "usePKCE in the organization's OIDC settings (watch.py: pkce)",
     "then": "switch it off, then prove several sign-ins spread over minutes", "teaches": "pkce"},
    {"id": "saml-certificate", "seen": ["An error occurred during login"], "hints": ["certificate", "signing certificate"],
     "protocol": "saml", "refused_by": "organization", "entra_log": LOG_READ,
     "look_at": "the organization's stored metadata against the app's active signing certificate (watch.py: saml_cert_held)",
     "then": "load Entra's current metadata for the app into the organization", "teaches": "saml-certificate"},
    {"id": "saml-group-renamed", "seen": [SSO_FAILURE_URL], "hints": ["group renamed", "rename"],
     "protocol": "saml", "refused_by": "organization", "entra_log": LOG_READ,
     "look_at": "the imported group's name against the name of the group assigned to the app (watch.py: group_names)",
     "then": "restore the group's name at Entra; change it only together with the imported group", "teaches": "group-rename"},
    {"id": "saml-upn-renamed", "seen": [SSO_FAILURE_URL], "hints": ["upn", "renamed user", "user name changed"],
     "protocol": "saml", "refused_by": "organization", "entra_log": LOG_NOT_READ,
     "look_at": "whether the user's UPN changed: the organization matches a returning SAML user on its user name, so the renamed user is refused and no account is made",
     "then": "restore the user's principal name at Entra: the next sign-in reached the same account. If the new name must "
             "stay, delete the old VCF Automation account: the next sign-in made a new account holding its groups' roles. Each "
             "was run once, on an All Apps organization; the run granted the old account no direct role, so what deleting it drops "
             "was not measured. Plan the next rename as a leaver and a joiner", "teaches": "upn-rename"},
    {"id": "oidc-upn-renamed", "seen": [], "hints": ["roles gone", "second account", "lost my roles", "upn", "renamed user"],
     "protocol": "oidc", "refused_by": "none: admitted as a second user",
     "entra_log": "a success, since the user was admitted; not read against the log",
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
    """An ISO 8601 instant as either API writes it (a Z suffix, three to seven fractional digits); None for anything
    else, a date that does not exist among them, which each check reads as a time it could not judge."""
    if not isinstance(value, str) or not value:
        return None
    m = re.match(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d+))?(Z|[+-]\d\d:\d\d)?$", value)
    if not m:
        return None
    frac = (m.group(2) or "0")[:6].ljust(6, "0")
    try:
        tz = timezone.utc if m.group(3) in (None, "Z") else datetime.strptime(m.group(3).replace(":", ""), "%z").tzinfo
        return datetime.strptime(f"{m.group(1)}.{frac}", "%Y-%m-%dT%H:%M:%S.%f").replace(tzinfo=tz)
    except ValueError:
        return None


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
    if success is None and oauth.get("lastKeySuccessfulRefresh"):   # a time held but not read is not a refresh that failed
        return _result("key_refresh", "unknown", "the last successful refresh's time does not read, so its age is not known", interval_h=hours, success_age_h=None)
    if success is None and not oauth.get("lastKeyRefreshAttempt"):
        return _result("key_refresh", "unknown", "no scheduled refresh yet; the first runs on the hour", interval_h=hours, success_age_h=None)
    if success is None:
        return _result("key_refresh", "fail", "refreshes have run and none has succeeded", interval_h=hours, success_age_h=None)
    whole_minutes = int((now - success).total_seconds() // 60)
    if hours and whole_minutes > (timedelta(hours=hours) + REFRESH_GRACE).total_seconds() // 60:
        return _result("key_refresh", "fail", f"the last successful refresh is {age} h old, past its {hours} h interval "
                       "plus an hour: refreshes are not succeeding", interval_h=hours, success_age_h=age)
    notes, state = [], "ok"
    if oauth.get("keyRefreshStrategy") != "ADD":
        notes.append(f"strategy {oauth.get('keyRefreshStrategy')}, not ADD")
        state = "warn"
    if not hours or hours > 1:
        notes.append(f"refresh every {hours} h: an emergency roll at the provider stops sign-in for up to the interval plus "
                     f"an hour ({hours + 1 if isinstance(hours, int) else '?'} h); set 1 h")
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
    written, and Entra refuses a secret it does not hold. No other secret stands in for it. When several of the app's
    secrets share the hint, which one the organization holds cannot be told, so each is judged and the earliest end
    stands: a pass on the later one could hide the one in use. Every secret the hint matches is judged, whether or not
    its end date reads: one whose end does not read leaves the earliest end not known (unknown, exit 3), unless one
    that reads has already ended, which fails whatever the other holds."""
    creds = app.get("passwordCredentials") or []
    held = [c for c in creds if c.get("in_use")]
    if not held:
        listed = f"none of the {len(creds)} secret(s) the app lists" if creds else "no secret: the app lists none"
        return _result("secret_end", "fail", f"the secret the organization holds matches {listed}; it was removed at Entra "
                       "or is another app's, and Entra refuses a secret it does not hold: write the app's current secret "
                       "into the organization", days_left=None, matched=False, listed=len(creds))
    which = ("the secret the organization holds" if len(held) == 1 else
             f"of the {len(held)} secrets that share the hint of the one the organization holds, the first to end,")
    others = [c for c in creds if not c.get("in_use") and when(c.get("endDateTime")) and when(c["endDateTime"]) < now]
    tail = f"; {len(others)} other listed secret(s) already expired" if others else ""
    shared = {"sharing_hint": len(held)} if len(held) > 1 else {}
    unread = [c for c in held if not when(c.get("endDateTime"))]
    if unread:
        ended = [when(c["endDateTime"]) for c in held if c not in unread and when(c["endDateTime"]) < now]
        if ended:
            days = _days(min(ended), now)
            return _result("secret_end", "fail", f"of the {len(held)} secrets that share the hint of the one the organization "
                           f"holds, one expired {-days} days ago, and {len(unread)} {'has' if len(unread) == 1 else 'have'} an end date "
                           f"that does not read{tail}",
                           days_left=days, matched=True, unread_end=len(unread), **shared)
        whose = ("the secret the organization holds has an end date that does not read" if len(held) == 1 else
                 f"{len(unread)} of the {len(held)} secrets that share the hint of the one the organization holds have an "
                 "end date that does not read")
        return _result("secret_end", "unknown", f"{whose}, so when the secret it holds ends is not known{tail}",
                       days_left=None, matched=True, unread_end=len(unread), **shared)
    judged = min(held, key=lambda c: when(c["endDateTime"]))
    days = _days(when(judged["endDateTime"]), now)
    if days < 0:
        return _result("secret_end", "fail", f"{which} expired {-days} days ago{tail}", days_left=days, matched=True, **shared)
    if days <= warn_days:
        return _result("secret_end", "warn", f"{which} ends in {days} days: rotate with overlap{tail}", days_left=days, matched=True, **shared)
    return _result("secret_end", "ok", f"{which} ends in {days} days{tail}", days_left=days, matched=True, **shared)


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


# During a rotation the token's user owns two refresh tokens, so the variable picks the one the watch runs on.
ROTATE = ("mint the next token under a new name, set VCFA_PROVIDER_TOKEN_NAME to that name and swap the file, run the "
          "watch once on it, then revoke this one")


def own_token(tokens: list[dict], user_id: str, name: str | None, now: datetime, warn_days: int) -> dict:
    """The watch's own provider API token, judged by its end date: the REFRESH token in the provider's token list that
    belongs to the session's own user, and carries `name` when one is given. None of them, or several, is undetermined
    (exit 3), never a pass: the end date of a token the run cannot single out is not known."""
    mine = [t for t in tokens if t.get("type") == "REFRESH" and (t.get("owner") or {}).get("id") == user_id]
    if name:
        mine = [t for t in mine if t.get("name") == name]
    if len(mine) != 1:
        which = "named VCFA_PROVIDER_TOKEN_NAME " if name else ""
        why = (f"{len(mine)} refresh tokens {which}belong to this credential's user: name the watch's own with "
               "VCFA_PROVIDER_TOKEN_NAME" if mine else f"no refresh token {which}of this credential's user is in the "
               "provider's token list")
        return _result("own_token", "unknown", f"the watch's own token's end date is not known: {why}",
                       candidates=len(mine), listed=len(tokens))
    end = when(mine[0].get("expirationTimeUtc"))
    counts = {"candidates": 1, "listed": len(tokens)}
    if end is None:
        return _result("own_token", "unknown", "the watch's own token's record carries no end date it could read", **counts)
    days = _days(end, now)
    if days < 0:
        return _result("own_token", "fail", f"the watch's own provider API token reads expired {-days} days ago: {ROTATE}",
                       days_left=days, **counts)
    if days <= warn_days:
        return _result("own_token", "warn", f"the watch's own provider API token ends in {days} days: {ROTATE}",
                       days_left=days, **counts)
    return _result("own_token", "ok", f"the watch's own provider API token ends in {days} days", days_left=days, **counts)


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


# ── reading ────────────────────────────────────────────────────────────────────────────────────────────────
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

    def session_user(self) -> str:
        """The user id of the session this credential opened."""
        return self.get("/cloudapi/1.0.0/sessions/current")["user"]["id"]

    def tokens(self) -> list[dict]:
        """The provider's token list, every page. A token value never travels in this list for a refresh token; any
        secret-bearing field is deleted on arrival all the same."""
        rows = self.pages("/cloudapi/1.0.0/tokens")
        for t in rows:
            t.pop("token", None)
        _strip(rows)
        return rows

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
        if REPLAY is not None:  # a replayed run reads no key or certificate: nothing is sent
            return REPLAY_CREDENTIAL
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
        """Every item of a Graph list, following @odata.nextLink until it is absent, as Microsoft's paging guidance
        says ("Paging Microsoft Graph data in your app": "To read all results, you must continue to call Microsoft
        Graph with the @odata.nextLink property returned in each response until the @odata.nextLink property is no
        longer returned", and "A page of results might contain zero or more results"). So a page holding no item, or
        only items already read (counted once, by id), is read on while it carries a next link. A page without its
        `value` list, a next link that is not a link or repeats one already followed (the pages would go round for
        ever), or a list still paging after MAX_PAGES pages, is a list not read (ReadError, exit 3), never an empty or
        a short one. The same rule as the tenant-federation companion's and the leaver job's pager."""
        qs = urllib.parse.urlencode({f"${k}": v for k, v in query.items()}, quote_via=urllib.parse.quote)
        url, out, followed, seen = f"{GRAPH}{path}" + (f"?{qs}" if qs else ""), [], set(), set()
        for _ in range(MAX_PAGES):
            followed.add(url)
            r = _fetch(url, {"Authorization": f"Bearer {self._bearer}", "Accept": "application/json"}, True)
            if not isinstance(r, dict) or not isinstance(r.get("value"), list):
                raise ReadError(f"a page of {path} came back without its list")
            new = [v for v in r["value"] if not (isinstance(v, dict) and v.get("id") and v["id"] in seen)]
            seen.update(v["id"] for v in new if isinstance(v, dict) and v.get("id"))
            out += new
            url = r.get("@odata.nextLink")
            if not url:
                return out
            if not isinstance(url, str):
                raise ReadError(f"a page of {path} gave a next link that is not a link, at {len(out)} items")
            if url in followed:
                raise ReadError(f"a next link of {path} came back a second time, so the list would never end")
        raise ReadError(f"{path}: more than {MAX_PAGES} pages")


def published_kids(jwks_uri: str) -> list[str]:
    verify = urllib.parse.urlparse(jwks_uri).hostname == ENTRA_HOST or _lab_verify()
    return [k["kid"] for k in (_fetch(jwks_uri, {"Accept": "application/json"}, verify).get("keys") or []) if k.get("kid")]


def metadata_thumbprints(xml: str) -> list[str]:
    """SHA-1 thumbprints (upper-case hex) of every certificate in SAML metadata, the form Entra names a certificate by."""
    return [hashlib.sha1(base64.b64decode(re.sub(r"\s", "", c))).hexdigest().upper()
            for c in re.findall(r"<(?:\w+:)?X509Certificate>([^<]+)<", xml or "")]


def _skipped(names: tuple[str, ...], why: str) -> list[dict]:
    """Each named check as not judged, with the reason; `unknown` is never a pass (exit_code)."""
    return [_result(n, "unknown", why) for n in names]


ENTRA_TENANT_IN = re.compile(r"(?:login\.microsoftonline\.com|sts\.windows\.net)/([0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})/")


def entra_tenant(protocol: str, oauth: dict, fed: dict) -> str | None:
    """The Entra tenant an organization is federated to: from the OIDC issuer, or from the issuer in the SAML metadata
    it holds. None when the provider is not Entra ID."""
    text = (oauth.get("issuerId") or "") if protocol == "oidc" else (fed.get("samlMetadata") or "") if protocol == "saml" else ""
    m = ENTRA_TENANT_IN.search(text)
    return m.group(1).lower() if m else None


def graph_skip(protocol: str, tenant: str | None, graph_tenant: str | None) -> str:
    """Why the Graph checks cannot run for this organization, or "" when they must. Whatever the reason, they are not
    run, and a check not run is never a pass: the organization is marked `not_run` (`owed` says what would let them
    run), and only a run declared --provider-only leaves that out of its exit. An organization federated to another
    tenant never reaches here: coverage() names it another tenant's, or uncovered. Anything else that keeps a Graph
    check from running is a failed read."""
    if tenant is None:
        return "the provider is not Entra ID"
    if graph_tenant is None:
        return "no Graph credential given"
    if tenant != graph_tenant.lower():
        return "the organization is federated to another Entra tenant than ENTRA_TENANT_ID"
    return ""


ROLLOVER_NOT_RUN = "rollover checks not run"
DECLARED = "a declared provider-only run"
OWED = {
    "no Graph credential given": "the tenant's read-only app is owed",
    DECLARED: "owed by the tenant: its administrator runs them and reports the dates",
    "the organization is federated to another Entra tenant than ENTRA_TENANT_ID":
        "that tenant's read-only app is owed: its own schedule reads it",
    "the provider is not Entra ID":
        "this watch reads the provider's side only on Entra ID: track that provider's secret, certificate and groups "
        "by its own means, or leave the organization out of ORGS",
}


def not_run(checks: tuple[str, ...], why: str, declared: bool = False) -> dict:
    """The record of rollover checks the run did not make: which, why, and what is owed for them to run. `declared` is
    set on a run declared --provider-only, which owes them to the tenant and leaves them out of its exit."""
    out = {"checks": list(checks), "why": why, "owed": OWED[DECLARED] if declared else OWED.get(why, why)}
    if declared:
        out["declared"] = True
    return out


# ── coverage: one schedule per tenant ──────────────────────────────────────────────────────────────────────
OTHER = "another tenant's: its own schedule reads it"
UNCOVERED = "uncovered: no schedule reads it"
TENANT_ID = re.compile(r"^[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$")
DOMAIN = re.compile(r"^(?=.{4,253}$)[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$")


class TenantError(Exception):
    """A tenant named on the command line or in ENTRA_TENANT_ID that names no Entra tenant: a usage error (exit 5)."""


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


def coverage(tenant: str | None, run_tenant: str | None, expected: set[str] | None) -> str:
    """Whose schedule reads an organization federated to `tenant`: "" this run's; OTHER another tenant's, which its own
    schedule reads and which leaves this run's exit alone; UNCOVERED a tenant outside the expected list, which no
    schedule reads (exit 3). An organization on a provider other than Entra ID, or a run that names no tenant, is this
    run's, apart from an expected list that leaves its tenant out."""
    if tenant is None:
        return ""
    if expected is not None and tenant not in expected and tenant != run_tenant:
        return UNCOVERED
    if run_tenant is not None and tenant != run_tenant:
        return OTHER
    return ""


def tenant_report(attested: date, today: date, max_days: int) -> dict:
    """The tenant's last report of its rollover dates, judged by its age: older than max_days warns (exit 1), because
    the dates it carried may have moved since; it never stands in for a check the run did not make."""
    age = (today - attested).days
    if age > max_days:
        return _result("tenant_report", "warn", f"the tenant's last report of its rollover dates is {age} days old, past "
                       f"the {max_days}-day limit: ask the tenant's administrator for a new one", age_days=age, max_days=max_days)
    return _result("tenant_report", "ok", f"the tenant reported its rollover dates {age} days ago, inside the "
                   f"{max_days}-day limit", age_days=age, max_days=max_days)


def side_read(group: list[dict]) -> str:
    """The organization-side checks that ran, by protocol, in the order they run: an OIDC organization's key refresh,
    keys and PKCE, and the local administrator under either protocol. Only what ran is named."""
    order = ("key_refresh", "keys_held", "pkce", "break_glass")
    parts = []
    for proto in ("oidc", "saml", None):
        ran = {c["check"] for r in group if r.get("protocol") == proto
               for c in r.get("checks") or [] if c["check"] in order and c["check"] not in r["not_run"]["checks"]}
        if ran:
            names = ", ".join(c for c in order if c in ran)
            parts.append(f"{names} ({proto.upper()})" if proto else names)
    return "; ".join(parts) if parts else "no check ran"


def provider_only_lines(results: list[dict], attested: dict | None = None) -> list[str]:
    """What a run that did not make the rollover checks could and could not see, and the organizations it left to
    another schedule or to none, for the end of its output."""
    out = []
    missed = [r for r in results if r.get("not_run") and not r["not_run"].get("declared")]
    owed = [r for r in results if (r.get("not_run") or {}).get("declared")]
    for group, head, tail in (
            (missed, ROLLOVER_NOT_RUN, "  a check not run is never a pass: exit 3 until they run"),
            (owed, ROLLOVER_NOT_RUN, "  a declared provider-only run: its exit is the organization's "
                   "side" + (", and the age of the tenant's last report" if attested else
                             "; give --tenant-attested to hold the tenant's reports to a date"))):
        if not group:
            continue
        why = sorted({r["not_run"]["owed"] for r in group})
        cannot = sorted({c for r in group for c in r["not_run"]["checks"]})
        out += [f"{head} on {len(group)} organization(s): {'; '.join(why)}",
                f"  read: the organization's side, {side_read(group)}",
                f"  not read: {', '.join(cannot)} ({', '.join(TENANT_READS[c] for c in cannot if c in TENANT_READS)})",
                tail]
    other = [r for r in results if r.get("coverage") == OTHER]
    if other:
        out.append(f"{OTHER}: {len(other)} organization(s) federated to another tenant, left out of this run's exit")
    lost = [r for r in results if r.get("coverage") == UNCOVERED]
    if lost:
        out.append(f"{UNCOVERED}: {len(lost)} organization(s) federated to a tenant outside --expect-tenants; exit 3 "
                   "until a schedule reads it")
    return out


def kept(result: dict, wanted: list[str]) -> bool:
    """Whether an organization belongs in the run: every one ORGS names; otherwise every federated one, and every one
    whose reads failed, since an organization that could not be read cannot be shown to be outside the watch. One left
    out is counted in the run's census, and a run that keeps none it can judge exits 3 (run_errors)."""
    return bool(wanted) or result.get("protocol") in ("oidc", "saml", "unread")


def watch_org(api: Vcfa, graph: Graph | None, org: dict, now: datetime, warn_days: int, seen: set,
              graph_error: str = "", run_tenant: str | None = None, expected: set[str] | None = None,
              declared: bool = False, attested: dict | None = None) -> dict:
    """Read one organization on both sides and run its checks. `seen` collects every estate value read, for the scrub.
    `graph_error` is set when a Graph credential was given and refused: every Graph check it would have run is unread.
    `run_tenant` is the tenant the run covers and `expected` the full tenant list (coverage()); `declared` marks a run
    declared --provider-only, and `attested` the tenant's last report ({date, max_days, today})."""
    uid = org["id"].rsplit(":", 1)[-1]
    seen.update({org["name"], org["id"], uid})
    out = {"org": org["name"], "org_type": "classic" if org.get("isClassicTenant") else "all-apps", "checks": [], "read_errors": []}
    try:
        oauth, prefix = api.oauth(uid)
        fed = api.federation(uid)
    except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
        out["protocol"] = "unread"   # kept by main(), so a refused read is never a silent pass
        out["read_errors"].append(f"VCF Automation: {type(e).__name__}")
        return out
    oidc = bool(oauth.get("enabled")) and not oauth.get("vidb")
    saml = bool(fed.get("enabled"))
    out["protocol"] = "oidc" if oidc else "saml" if saml else "none"
    seen.update(v for v in (oauth.get("issuerId"), oauth.get("clientId"), oauth.get("jwksUri"), oauth.get("orgRedirectUri")) if v)
    tenant = entra_tenant(out["protocol"], oauth, fed)
    if tenant:
        out["tenant"] = tenant
        seen.add(tenant)
    cover = coverage(tenant, run_tenant, expected) if (oidc or saml) else ""
    if cover:   # another schedule's organization, or none's: named, and read no further
        out["coverage"] = cover
        del prefix
        return out
    try:
        users = api.users(org["id"])
        groups = api.pages("/cloudapi/1.0.0/groups", org["id"])
        roles = api.roles(org["id"])
    except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
        out["read_errors"].append(f"VCF Automation: {type(e).__name__}")   # kept, named, and never a pass
        del prefix
        return out
    for u in users:
        seen.update(v for v in (u.get("username"), u.get("email"), u.get("fullName"), u.get("nameInSource")) if v)
    for g in groups:
        seen.update(v for v in (g.get("name"), g.get("nameInSource"), g.get("id")) if v)
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
    skip = DECLARED if declared else graph_skip(
        out["protocol"], tenant, graph.tenant if graph is not None else (run_tenant if graph_error else None))
    if not (oidc or saml):
        out["read_errors"].append("neither OIDC nor SAML is on for this organization")
    elif skip:   # not run, so never a pass: the organization carries why, and what would let them run
        out["not_run"] = not_run(graph_checks, skip, declared)
        checks += _skipped(graph_checks, f"{ROLLOVER_NOT_RUN}: {out['not_run']['owed']} ({skip})")
        if declared and attested:
            checks.append(tenant_report(attested["date"], attested["today"], attested["max_days"]))
    elif graph is None:   # a Graph credential was given and refused: each check it would have run is unread
        out["read_errors"].append(graph_error)
        checks += _skipped(graph_checks, "not run: the Graph credential given was refused")
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
            if len(apps) > 1:   # which app signs this organization's users in cannot be told: no check judges one
                out["read_errors"].append(f"Graph: {len(apps)} apps in the tenant carry {looked_for}")
            app = apps[0] if len(apps) == 1 else None
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
            elif not apps:   # an app the watch cannot find is a read it could not make, never a pass
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
            checks += _skipped(graph_checks, "not run: the app behind the organization could not be read in Graph")
        else:
            if oidc and not held_secret:
                out["read_errors"].append("VCF Automation: the organization's settings returned no client secret to match")
                checks += _skipped(("secret_end",), "not run: the organization's client secret was not in its settings read")
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


def judged(result: dict) -> bool:
    """Whether the run judged this organization: read, federated over OIDC or SAML, this run's own, and checked."""
    return (result.get("protocol") in ("oidc", "saml") and not result.get("coverage")
            and bool(result.get("checks")))


NONE_JUDGED = "the run judged no organization"


def run_errors(results: list[dict], run_tenant: str | None, census: dict | None = None) -> list[str]:
    """What is wrong with the run as a whole. A run tenant no organization in it names, which would otherwise read as
    every organization being another tenant's; and a run that judged no organization, which would otherwise exit 0
    having judged nothing (a wrong host, the tenant's only organization with its federation off, a credential that
    lists none it can judge). `census` is what the run listed and left out before reading: {listed, provider_own,
    off}, where `off` is an organization with neither OIDC nor SAML on, left out when ORGS does not name it."""
    out = []
    if run_tenant is not None and results and not any(r.get("tenant") == run_tenant and not r.get("coverage") for r in results) \
            and not all(r.get("protocol") == "unread" or not r.get("protocol") for r in results):
        out.append("no organization in the run is federated to the run's tenant (ENTRA_TENANT_ID): a wrong tenant would "
                   "read every organization as another tenant's")
    if not any(judged(r) for r in results):
        c = census or {}
        parts = [f"{c['listed']} listed"] if c.get("listed") is not None else []
        counts = (("off", "with neither OIDC nor SAML on (federation switched off, or signed in through VCF single "
                   "sign-on), left out"),
                  ("provider_own", "the provider's own, left out"))
        parts += [f"{c[k]} {what}" for k, what in counts if c.get(k)]
        named = (("another tenant's", sum(1 for r in results if r.get("coverage") == OTHER)),
                 ("uncovered", sum(1 for r in results if r.get("coverage") == UNCOVERED)),
                 ("not read", sum(1 for r in results if r.get("protocol") == "unread"
                                   or (r.get("read_errors") and not r.get("checks")))),
                 ("named in ORGS with neither OIDC nor SAML on", sum(1 for r in results if r.get("protocol") == "none")))
        parts += [f"{n} {what}" for what, n in named if n]
        out.append(f"{NONE_JUDGED} ({'; '.join(parts) or 'nothing listed'}): check VCFA_HOST, the credential and ORGS; "
                   "a run that judges nothing is never a pass")
    return out


def exit_code(results: list[dict], errors: list[str] | tuple = (), own: dict | None = None) -> int:
    """One code per state, the first that applies: a failure; then a read that failed, a check that could not judge
    (unknown) or rollover checks not run on an undeclared run, an organization no schedule reads, or a run error (a run
    that judged no organization among them), none of which is a pass; then a warning; then nothing to act on. Another
    tenant's organization, and the rollover checks a declared --provider-only run owes to the tenant, are left out.
    `own` is the run's check of its own provider API token, which counts like any other check."""
    mine = [r for r in results if r.get("coverage") != OTHER]
    states = [c["state"] for r in mine for c in r["checks"]
              if not ((r.get("not_run") or {}).get("declared") and c["check"] in r["not_run"]["checks"])]
    if own:
        states.append(own["state"])
    if "fail" in states:
        return EXIT_FAIL
    if ("unknown" in states or errors
            or any(r["read_errors"] or r.get("coverage") == UNCOVERED
                   or (r.get("not_run") and not r["not_run"].get("declared")) for r in mine)):
        return EXIT_UNREAD
    return EXIT_WARN if "warn" in states else EXIT_OK


# ── the record contract ────────────────────────────────────────────────────────────────────────────────────
UUIDISH = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
# Product vocabulary never becomes a placeholder, even when an estate object is named after it.
RESERVED = {"Organization Administrator", "Organization User", "Organization Member", "Organization Auditor", "Organization Owner",
            "Administrator", "administrator", "admin", "System", "OAUTH", "SAML", "LOCAL"}
HOSTISH = re.compile(r"\b[a-z0-9-]+(?:\.[a-z0-9-]+)+\.[a-z]{2,}\b", re.I)
PLACEHOLDER = re.compile(r"\{\{[a-z-]+(?:-\d+)?\}\}")  # every placeholder this script writes: {{org-1}}, {{estate}}
OWN = re.compile(f"({PLACEHOLDER.pattern})")  # splits a text into what lies outside the placeholders and each one


class ScrubError(Exception):
    """The record would carry an estate value, so it is not written."""


def placeholders(results: list[dict], run_tenant: str | None = None) -> dict:
    """A stable placeholder for each organization, and for each tenant (the run's own first), for the record and
    for --redact."""
    names = {r["org"]: f"{{{{org-{i}}}}}" for i, r in enumerate(results, 1)}
    tenants = [run_tenant] if run_tenant else []
    tenants += [t for t in dict.fromkeys(r.get("tenant") for r in results) if t and t not in tenants]
    names.update({t: f"{{{{tenant-{i}}}}}" for i, t in enumerate(tenants, 1)})
    return names


def one_pass(table: dict):
    """A text with every value in `table` replaced by its placeholder in one pass: one alternation, the longest value
    first, matched as spelled and with no boundary, and only outside the placeholders already in the text. The record
    carries each organization's placeholder before it is scrubbed, so an organization named org-1 would otherwise
    rewrite the {{org-1}} another was given; and a second scrub changes nothing. A value is in `table` once, under the
    first placeholder it got."""
    rx = re.compile("|".join(re.escape(k) for k in sorted(table, key=len, reverse=True))) if table else None
    if rx is None:
        return lambda text: text
    return lambda text: "".join(part if i % 2 else rx.sub(lambda m: table[m.group(0)], part)
                                for i, part in enumerate(OWN.split(text)))


def scrub(text: str, names: dict, seen: set) -> str:
    """Every estate value replaced in one longest-first pass outside the placeholders (one_pass); refuse when one
    survives outside them."""
    seen = {v for v in seen if len(v) >= 4 and v not in RESERVED}
    table = dict(names)
    for v in sorted(seen, key=len, reverse=True):
        table.setdefault(v, "{{estate}}")
    text = one_pass(table)(text)
    bare = PLACEHOLDER.sub(" ", text)   # a placeholder's own letters are not a surviving value
    left = [v for v in seen if v and v in bare] + UUIDISH.findall(bare) + HOSTISH.findall(bare)
    if left:
        raise ScrubError(f"refusing to write: {len(left)} estate value(s) survived the scrub")
    return text


def record(results: list[dict], warn_days: int, now: datetime, seen: set, run: dict | None = None) -> str:
    """The run's record: every organization under a placeholder, and the run's own terms (`run`: its mode, its tenant,
    how many tenants it expects, the tenant's report, and any run error), every estate value replaced."""
    run = run or {}
    names = placeholders(results, run.get("tenant"))
    errors = list(run.get("errors") or [])
    credential = run.get("credential") or {}
    # A record a replayed run writes says so: it shows no read of an estate, and a reader takes it as none.
    doc = {**({"replay": True} if REPLAY is not None else {}),
           "captured": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "warn_days": warn_days,
           "exit": exit_code(results, errors, credential.get("check")),
           "mode": run.get("mode", "with the tenant's app"), "tenant": run.get("tenant"),
           "expected_tenants": run.get("expected_tenants"), "tenant_attested": run.get("tenant_attested"),
           "credential": credential or None, "census": run.get("census"),
           "judged": sum(1 for r in results if judged(r)),
           "run_errors": errors, "organizations": [{**r, "org": names[r["org"]]} for r in results]}
    return scrub(json.dumps(doc, indent=2, ensure_ascii=False), names, seen | {os.environ.get("VCFA_HOST", "")} - {""})


LEFT_OUT = ("neither OIDC nor SAML is on (federation switched off, or signed in through VCF single sign-on): left out "
            "and not judged; name it in ORGS to read it")


def _print(results: list[dict], names: dict | None, attested: dict | None = None, errors: list[str] | tuple = (),
           own: dict | None = None, off: list[dict] | tuple = ()) -> None:
    """The run on stdout: the watch's own credential, each organization judged or kept, each one left out because its
    federation is off (named here, counted in the record's census), then the run's own lines."""
    if own:
        print(f"\nthe watch's own credential\n  {own['state'].upper():<8}{own['check']:<16}{own['detail']}")
    for r in results:
        label = names[r["org"]] if names else r["org"]
        print(f"\n{label}  ({r.get('protocol', '?')}, {r['org_type']})")
        if r.get("coverage"):
            t = r.get("tenant") or ""
            print(f"  TENANT  {r['coverage']} (tenant {names.get(t, t) if names else t})")
        for c in r["checks"]:
            print(f"  {c['state'].upper():<8}{c['check']:<16}{c['detail']}")
        for e in r["read_errors"]:
            print(f"  READ    {e}")
    for i, r in enumerate(off, 1):
        label = "{{off-" + str(i) + "}}" if names is not None else r["org"]
        print(f"\n{label}  (off, {r['org_type']})\n  OFF     {LEFT_OUT}")
    lines = provider_only_lines(results, attested)
    if lines:
        print("")
        print("\n".join(lines))
    for e in errors:
        print(f"\nREAD    {e}")


class _Parser(argparse.ArgumentParser):
    """argparse exits 2 on a usage error, the code this script gives a failure; it exits 5 here."""

    def __init__(self, *args, **kwargs):  # an abbreviation never parses as a whole flag name
        kwargs.setdefault("allow_abbrev", False)
        super().__init__(*args, **kwargs)

    def error(self, message: str):  # type: ignore[override]
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        raise SystemExit(EXIT_USAGE)


GRAPH_ENV = ("ENTRA_CLIENT_ID", "ENTRA_CLIENT_SECRET_FILE", "ENTRA_CERT_FILE", "ENTRA_KEY_FILE")


def credential_given(env: dict, *names: str) -> bool:
    """Whether a credential is given: one of the named variables is set, or the run is replayed, where the credential
    is the placeholder _secret_file returns and nothing is read."""
    return REPLAY is not None or any(env.get(n) for n in names)


def usage_problem(env: dict, provider_only: bool = False) -> str:
    """What is missing or inconsistent in the environment, or "". Checked before any call, so a run that could not
    have read is a usage error (exit 5), never a read failure or a pass. A run declared --provider-only takes no Graph
    credential, and its ENTRA_TENANT_ID, if set, only names the tenant it covers."""
    if not env.get("VCFA_HOST"):
        return "set VCFA_HOST"
    if not credential_given(env, "VCFA_PROVIDER_REFRESH_TOKEN_FILE", "VCFA_PROVIDER_BEARER_FILE"):
        return "set VCFA_PROVIDER_REFRESH_TOKEN_FILE or VCFA_PROVIDER_BEARER_FILE"
    days = env.get("WARN_DAYS", "30")
    if not days.isdigit():
        return f"WARN_DAYS must be a whole number of days, not {days!r}"
    graph = [k for k in GRAPH_ENV if env.get(k)]
    if provider_only and graph:
        return f"--provider-only takes no Graph credential, and {', '.join(graph)} is set: unset it, or drop --provider-only"
    if graph and not env.get("ENTRA_TENANT_ID"):
        return f"{', '.join(graph)} given without ENTRA_TENANT_ID: set it, or unset them for a provider-only run"
    if env.get("ENTRA_TENANT_ID"):
        if not tenant_form(env["ENTRA_TENANT_ID"]):
            return "ENTRA_TENANT_ID is neither a tenant id nor a domain name"
        if not provider_only and not env.get("ENTRA_CLIENT_ID"):
            return "ENTRA_TENANT_ID needs ENTRA_CLIENT_ID, the tenant's read-only app (or declare --provider-only)"
        if not provider_only and not (credential_given(env, "ENTRA_CLIENT_SECRET_FILE")
                                      or (env.get("ENTRA_CERT_FILE") and env.get("ENTRA_KEY_FILE"))):
            return "the tenant's read-only app needs ENTRA_CLIENT_SECRET_FILE, or ENTRA_CERT_FILE and ENTRA_KEY_FILE"
    for k in ("VCFA_PROVIDER_REFRESH_TOKEN_FILE", "VCFA_PROVIDER_BEARER_FILE", "ENTRA_CLIENT_SECRET_FILE",
              "ENTRA_CERT_FILE", "ENTRA_KEY_FILE"):
        if REPLAY is None and env.get(k) and not (Path(env[k]).is_file() and os.access(env[k], os.R_OK)):
            return f"{k} names a file that cannot be read"
    return ""


def args_problem(a: argparse.Namespace, today: date) -> str:
    """What is wrong with the run's own flags, or "": checked before any call, a usage error (exit 5)."""
    if a.tenant_attested is not None and not a.provider_only:
        return "--tenant-attested goes with --provider-only: with the tenant's app the watch reads the dates itself"
    if a.attested_max_days is not None and a.tenant_attested is None:
        return "--attested-max-days goes with --tenant-attested"
    if a.tenant_attested is not None:
        try:
            d = date.fromisoformat(a.tenant_attested)
        except ValueError:
            return f"--tenant-attested takes a date, YYYY-MM-DD, not {a.tenant_attested!r}"
        if d > today:
            return f"--tenant-attested {a.tenant_attested} is in the future"
    if a.attested_max_days is not None and a.attested_max_days < 1:
        return "--attested-max-days takes a whole number of days, 1 or more"
    if a.expect_tenants is not None:
        listed = [t.strip() for t in a.expect_tenants.split(",") if t.strip()]
        if not listed:
            return "--expect-tenants needs the tenant list: ids or domain names, comma separated"
        bad = [t for t in listed if not tenant_form(t)]
        if bad:
            return f"--expect-tenants: {', '.join(repr(t) for t in bad)} is neither a tenant id nor a domain name"
    return ""


def main(argv: list[str] | None = None) -> int:
    """The run, with two guards around it: a Python older than 3.9 is refused (exit 5) before anything is read, and an
    error the watch did not expect exits 3, the code for a result not known, never 1, the code for a warning."""
    if sys.version_info < (3, 9):  # noqa: UP036  the script is run by readers on their own Python
        print("watch.py needs Python 3.9 or later", file=sys.stderr)
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


def build_parser() -> _Parser:
    """The watch's flags, for its run and for anything that reads them (a page builder, a test): allow_abbrev stays
    off, so an abbreviation never parses as a whole flag name."""
    ap = _Parser(prog="watch.py", description="Will each federated VCF Automation organization keep signing in?")
    ap.add_argument("--redact", action="store_true", help="print with placeholders instead of your names")
    ap.add_argument("--why", metavar="TEXT", help="the sign-in router: what the user saw; reads nothing")
    ap.add_argument("--protocol", choices=("oidc", "saml", "any"), help="with --why: the organization's protocol")
    ap.add_argument("--expect-tenants", metavar="T1,T2", help="every Entra tenant a schedule covers (ids or domain "
                    "names); an organization federated to another is uncovered (exit 3)")
    ap.add_argument("--provider-only", action="store_true", help="declared: no Graph credential; the exit is the "
                    "organization's side, and the rollover checks are owed by the tenant")
    ap.add_argument("--tenant-attested", metavar="YYYY-MM-DD", help="with --provider-only: the date of the tenant's "
                    "last report of its rollover dates")
    ap.add_argument("--attested-max-days", type=int, metavar="N", help="with --tenant-attested: the report's "
                    "greatest age before it warns (default 30)")
    ap.add_argument("--replay", metavar="DIR",
                    help="answer every request from the recorded set in DIR (replay/watch beside this script is "
                         "one): nothing is sent and no credential is read")
    return ap


def _run(argv: list[str]) -> int:
    ap = build_parser()
    a = ap.parse_args(argv)
    if a.replay:
        try:
            replay_start(a.replay)
        except (OSError, ValueError) as e:
            print(f"--replay {a.replay}: {e}; nothing was sent", file=sys.stderr)
            return EXIT_USAGE
    if a.why is not None:
        if not a.why.strip():
            ap.error("--why needs what the user saw")
        rows = route(a.why, a.protocol or "any")
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
    if a.protocol:
        ap.error("--protocol goes with --why")
    now = replay_now()   # the time now, or the time a replayed set was recorded at
    problem = usage_problem(dict(os.environ), a.provider_only) or args_problem(a, now.date())
    if problem:
        print(f"{problem} (see the header); nothing was read", file=sys.stderr)
        return EXIT_USAGE
    warn_days = int(os.environ.get("WARN_DAYS", "30"))
    wanted = [o.strip() for o in os.environ.get("ORGS", "").split(",") if o.strip()]
    attested = None
    if a.tenant_attested is not None:
        attested = {"date": date.fromisoformat(a.tenant_attested), "today": now.date(),
                    "max_days": a.attested_max_days or 30}
    # The run's tenant and the tenant list, as ids: a domain Entra names no tenant for is a usage error; a resolution
    # that does not answer is a read that failed (exit 3, no record).
    try:
        run_tenant = resolve_tenant(os.environ["ENTRA_TENANT_ID"]) if os.environ.get("ENTRA_TENANT_ID") else None
        expected = ({resolve_tenant(t) for t in a.expect_tenants.split(",") if t.strip()}
                    if a.expect_tenants is not None else None)
    except TenantError as e:
        print(f"{e} (see the header); nothing was read", file=sys.stderr)
        return EXIT_USAGE
    except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
        print(f"READ FAILED: Entra's OpenID configuration, resolving a tenant's domain name: {type(e).__name__}; exit 3, no record written")
        return EXIT_UNREAD
    if expected is not None and run_tenant:
        expected.add(run_tenant)   # the run's own tenant is always covered: by this run
    # A credential refused, or an organization list that cannot be read, ends the run before any check: exit 3, no record.
    try:
        api = Vcfa(os.environ["VCFA_HOST"])
        listed = api.pages("/cloudapi/1.0.0/orgs")
    except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
        print(f"READ FAILED: VCF Automation, before any organization was read: {type(e).__name__}; exit 3, no record written")
        return EXIT_UNREAD
    if not listed:
        print("READ FAILED: the organization list came back empty, so the credential sees no organization; exit 3, no record written")
        return EXIT_UNREAD
    # The watch's own credential: a provider API token has an end date, read from the provider's token list; a read
    # that fails leaves it undetermined (exit 3) and the run goes on to the organizations.
    own = None
    if api.kind == "provider API token":
        try:
            own = own_token(api.tokens(), api.session_user(), os.environ.get("VCFA_PROVIDER_TOKEN_NAME", "").strip() or None,
                            now, warn_days)
        except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError) as e:
            own = _result("own_token", "unknown", f"the watch's own token's end date is not known: the token list could "
                          f"not be read ({type(e).__name__})")
    graph, graph_error = None, ""
    if os.environ.get("ENTRA_TENANT_ID") and not a.provider_only:
        try:
            graph = Graph()
            graph.tenant = run_tenant   # the id, so a domain given as ENTRA_TENANT_ID still matches an issuer
        except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
            graph_error = f"Graph: the token request failed ({type(e).__name__})"
    # By default the provider's own consumption organization is left out: its sign-in settings are the platform's.
    orgs = [o for o in listed if (o["name"] in wanted if wanted else not o.get("isProviderConsumptionOrg"))]
    seen = {os.environ.get("ENTRA_TENANT_ID", ""), os.environ.get("ENTRA_CLIENT_ID", ""), run_tenant or ""} | (expected or set())
    seen -= {""}
    results, off = [], []
    for o in orgs:
        r = watch_org(api, graph, o, now, warn_days, seen, graph_error, run_tenant, expected, a.provider_only, attested)
        if kept(r, wanted):
            results.append(r)
        else:
            off.append(r)   # federation off: named on stdout, counted in the record
    missing = sorted(set(wanted) - {r["org"] for r in results})
    for m in missing:
        results.append({"org": m, "org_type": "?", "checks": [], "read_errors": ["no organization by that name"]})
    census = {"listed": len(listed), "provider_own": 0 if wanted else len(listed) - len(orgs), "off": len(off)}
    errors = run_errors(results, run_tenant, census)
    _print(results, placeholders(results, run_tenant) if a.redact else None, attested, errors, own, off)
    code = exit_code(results, errors, own)
    run = {"mode": ("provider-only, declared" if a.provider_only else "with the tenant's app" if graph is not None or graph_error
                    else "provider-only, undeclared"),
           "tenant": run_tenant, "expected_tenants": len(expected) if expected is not None else None, "errors": errors,
           "census": census, "credential": {"kind": api.kind, "check": own},
           "tenant_attested": ({"date": attested["date"].isoformat(), "max_days": attested["max_days"],
                                "age_days": (attested["today"] - attested["date"]).days} if attested else None)}
    try:
        text = record(results, warn_days, now, seen, run)
    except ScrubError as e:   # the result above stands; the record does not, so the run is not on record
        code = code if code == EXIT_FAIL else EXIT_UNREAD
        print(f"\n{len(results)} organization(s); {e}; no record written; exit {code}")
        return code
    with open(os.environ.get("OUT") or ("watch.replay.json" if REPLAY is not None else "watch.json"), "w",
              encoding="utf-8") as f:
        f.write(text + "\n")
    print(f"\n{len(results)} organization(s), {sum(1 for r in results if judged(r))} judged; exit {code}; record written "
          "with every estate value replaced")
    return code


if __name__ == "__main__":
    sys.exit(main())
