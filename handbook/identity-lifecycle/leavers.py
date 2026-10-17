#!/usr/bin/env python3
"""leavers.py - who has left at the identity provider and can still get into VCF Automation. Report-only by default.

Removing someone at the identity provider stops their next sign-in. It does not touch the account VCF Automation
created at their first sign-in, which stays enabled, nor an API token that account holds, which keeps working until
it is revoked. And over SAML, and over OIDC keyed on preferred_username, VCF Automation finds a returning account by
its user name: a new person later given a departed person's name reached the old account while it was enabled, and
held every role granted to it directly; closed, the account turned that person away, and enabled again, it let them in
holding its direct role (All Apps organizations, one run per protocol). This script
closes that gap from the platform's side, for every organization federated to one Entra ID tenant, of either type
and either protocol.

Each organization is found from its own settings: OIDC by an issuer on the tenant (its client id names the Entra
app), SAML by identity-provider metadata naming the tenant (its service-provider entity id names the app). Nothing
is declared by hand, so an organization federated later is covered on the first run after.

The rule. A federated account is a LEAVER when Entra has no user by its name, that user is disabled, or the user can
no longer pass both gates a sign-in passes:
  Entra's gate          when the app requires assignment, the user is assigned to it, directly or as a DIRECT member
                        of an assigned group (Entra does not admit a member of a group nested inside one)
  VCF Automation's      the sign-in carries a group imported into the organization, or the account holds a role
                        directly (a user with neither is refused); with groupMembershipClaims ApplicationGroup the
                        claim carries only groups assigned to the app that the user is a direct member of, and with
                        any other setting the groups it is in through nesting too
So an account that passes Entra's gate and holds a role directly is KEPT even when no imported group carries it, and
flagged (direct-role) for a person to decide. Accounts are matched to Entra by the key the organization names them
with, read from its own settings: by name for OIDC keyed on preferred_username and for SAML keyed on Entra's name
claim, by object id for OIDC keyed on oid. A name is looked up by userPrincipalName, then by mail, then by
otherMails; exactly one Entra user across the three is the person, and more than one is undetermined. The user found
is the person only when the attribute the organization's name claim carries holds the name: userPrincipalName unless
--name-claim ORG=mail (or otherMails) declares otherwise, because this job cannot read which attribute a claim is
sourced from. A user found only by another attribute is undetermined, its reason naming the mismatch; declared, a
guest or an organization whose name claim carries mail resolves by mail. A name no lookup finds is a leaver only when another federated account of the same organization was found:
when none was, every account of the organization is undetermined, because the name its user key carries is not one
the lookups can read. Any other key, or an account whose name does not fit its organization's key, is undetermined.
Local accounts are out of scope. Two more things are flagged and never acted on: a federated account holding a role
directly (keyed on a name, a reused name reached such a role on an enabled account, and a close leaves it in place;
under oid, a later holder of the name signs in to a new account and does not reach it), and an account disabled here whose name an
enabled, entitled Entra user now holds (if that is a different person, re-enabling the account hands them its
roles). An enabled account whose name a new person was given reads keep like any entitled account: the user record
carries no creation time to compare with the Entra user's, and the report does not read the audit trail for one (only
--close-now's name guard does), so the report cannot tell the two people apart. A flag a
person has decided on can be acknowledged until a date with --ack; the report still lists it, as such.

The tenant. ENTRA_TENANT_ID may be the tenant's id in any case or one of its domain names; a domain name is resolved
to the id from the Graph token's tid claim (read in memory, never printed), or else Graph's /organization. An
organization is federated to the tenant when its issuer or metadata names that id, compared without regard to case.
A run in which no organization names the tenant exits 3: a wrong tenant reads as nothing to do.

Many tenants. One run reads one tenant, so a provider whose organizations federate to several Entra tenants runs one
schedule per tenant, each with that tenant's read-only app, and passes every schedule the same full list:
--expect-tenants T1,T2,... (ids, or domain names: this run's own ENTRA_TENANT_ID is taken as resolved, any other domain
from Entra's OpenID discovery document, GET https://login.microsoftonline.com/{domain}/v2.0/.well-known/openid-
configuration, whose issuer names the tenant id, no credential). An organization federated elsewhere is then read by
its own tenant's schedule when the list names that tenant; one federated to an Entra tenant outside the list, or to
this tenant in a form the job does not read, is "uncovered: no schedule reads it" and exits 3; one on another provider
(no Entra tenant in its issuer or metadata) is counted and not read. Without the flag, every organization federated
elsewhere is counted and not read, and does not change the exit: so a schedule for tenant A can exit 0 while tenant B's
leavers go unread. A list that leaves out this run's own tenant, or names a domain Entra knows as no tenant, is a usage
error (exit 5); a discovery read that failed is 3.

Switched off. An organization with OIDC and SAML both switched off is not judged, and it is never dropped: the run
lists it, and reads its accounts and tokens for what federated sign-in left there. An enabled federated account
comes back when the federation is switched on, and whether an API token of a federated account stops refreshing while
the federation is off was not tested, so an organization holding either is unreadable (exit 3): this report cannot
judge what it skipped. Close a leaver's account there with --close-now (below), which reads the key the organization
stores whether or not it is switched on: under oid by the object id the leaver notice carries, never the name; or
switch the federation back on so the report reads them.
One that holds neither is listed and changes no exit.

Fail closed. An organization whose gate cannot be read, or an account whose state cannot be read, is reported
undetermined and never acted on. A list is read whole or not at all: a VCF Automation list is read page by page until
its distinct items (by id) number the total the answer states (resultTotal), and an answer without its values or its
total, a page that comes back empty or short before the total, a page that adds no item not already read, or a total
that changes between pages, is a list that did not read; a Microsoft Graph list follows @odata.nextLink to its end,
and a 200 without its value list, or a next link that repeats one already followed, did not read. Entra's directory
reads settle after a change, so every leaver still enabled or
holding a token is read again CONFIRM_READS times, CONFIRM_PAUSE seconds apart (all of an organization's in the same
rounds), in a report and with --execute alike: it counts as an open leaver (exit 1), or is closed, only when every
read agrees, and a leaver whose reads disagree is undetermined (exit 3), its reason naming the reads, for the next
run to settle. Acting needs a named organization (--org): the script never acts on every organization it can see.
And it refuses an organization whose open leavers exceed a share no ordinary week produces (more than MAX_LEAVERS and
more than a quarter of its federated accounts, or more than --max-leavers N), closing none of them and saying why: a
wrong lookup reads everyone as gone. A leaver already disabled with no token is in step, so a re-run changes nothing.

Naming one account (--user, with --execute or --close-now). The value is compared with each account's user name, in any
case, and with its id (urn:vcloud:user:...). In an organization keyed on oid each account is named by its person's Entra object id, so a
value that is not an object id is taken as a principal name and resolved through Graph (GET /users/{principal name},
which needs User.Read.All), and the account named by that object id is a candidate beside any named by the value
itself. The match is printed (the name, the object id and when that Entra user was created, the account and when it
was made) before anything is sent; no account, or more than one, refuses the run (exit 5), and a resolution Graph
refused is a read that failed (exit 3). --execute closes only an account Entra reads as a leaver on three reads, so a
name resolved to someone else selects an account that reads keep. --close-now asks Entra nothing, so under oid it is
run by the object id the leaver notice or the last report carries: a name resolves to whoever holds it now, and after
a reuse that is a new person (G-430). So under oid a principal name is taken by the plan only, and only with
--left-on, the departure date the notice gives: the plan resolves it, prints the object id and both dates, and is
refused (exit 5) when the Entra user holding the name now was created on or after that date, when the account it
selects was made on or after it, or when that user is newer than the account; when a date the guard needs did not
read, or did not parse, the run is unread (exit 3). The dates catch a name given to someone new after the departure;
they do not catch an existing person renamed onto the name, whose user and account both predate it. So --close-now
--execute under oid takes an object id or the account's id only: given anything else it is refused before any name is
resolved and before anything is sent (exit 5), whatever Graph would answer, and the plan, run without --execute, is
where a name is resolved and the object id printed, for the operator to check against the leaver notice and close by.
The key is the one the organization's settings store, read whether its OIDC is switched on or off, so an
organization switched off is never taken as keyed on a name. Under oid, a name Graph knows no user by, which an account still
carries, selects an account named before the organization was keyed on oid, not the one the person signs in to: the
plan refuses it (exit 5), naming that account's id and pointing to the object id the notice carries. The account's
date is its import (first sign-in) or create event in the audit trail, the account record carrying none; an account
older than the trail's reach is bounded by the trail's oldest event. Keyed on a name (OIDC on preferred_username,
SAML on Entra's name claim, each read from the organization's stored settings for the protocol of the account the name
selects), the name is the account's key: the account it selects is the one every holder of the name signs in to, so
no guard can choose between people and none runs. Under any other stored key (sub, an object-id claim, none stored)
the script does not take a principal name as the account's key, so a name that selects an account of that protocol
is refused (exit 5, in the plan and with --execute, nothing sent) and the account's id closes it. --close-now refuses,
at the plan and before any write, an account that is not federated (LOCAL, or anything but OAUTH or SAML): on a local
account the disable was refused (400) after its tokens had been revoked.

VCF Automation, as the provider:
  GET    /cloudapi/1.0.0/orgs                                 the organizations
  GET    /api/admin/org/{id}/settings/oauth, .../federation   each one's OIDC and SAML settings (and, for SAML, its
                                                              service-provider metadata, for the entity id)
  GET    /cloudapi/1.0.0/users, /groups, /tokens              per organization, in its tenant context (users and
                                                              tokens only, for one with its federation switched off)
  GET    /cloudapi/1.0.0/sessions/current, /tokens            on a provider API token: the run's own token record,
                                                              for its end date (expirationTimeUtc)
  GET    /cloudapi/1.0.0/auditTrail                           only for --close-now by a principal name under oid: the
                                                              account's import or create event, else the oldest event
  with --execute, for each confirmed leaver:
  GET    /cloudapi/1.0.0/users/{id}                           the account, read first: nothing is sent to one that
                                                              is not federated
  DELETE /cloudapi/1.0.0/tokens/{id}                          each API token the account holds
  PUT    /cloudapi/1.0.0/users/{id}                           the account's full record with enabled false, then
                                                              read back: disabled, nothing else changed, no token
                                                              (a read-back that did not read is a close that did
                                                              not hold, never "no token left")
Microsoft Graph (an app permitted to read users, groups, applications and service principals):
  GET /servicePrincipals, /applications, /servicePrincipals/{id}/appRoleAssignedTo, /groups (filtered)
  GET /groups/{id}/members                                    each gate group's direct members, every page, with no
                                                              query parameter (the form Graph serves without
                                                              advanced query parameters)
  GET /users?$filter=userPrincipalName eq '{name}', mail eq '{name}', otherMails/any(m:m eq '{name}')
                                                              each a filter Graph serves without advanced query
                                                              parameters (no ConsistencyLevel header, no $count)
  POST /users/{id}/checkMemberGroups                          a read: which of the gate's groups the user is in,
                                                              nested groups included
  GET /organization                                           only when ENTRA_TENANT_ID is a domain name and the
                                                              token carries no tid (it needs Organization.Read.All)
  GET /users/{principal name}?$select=id,userPrincipalName,createdDateTime
                                                              only for --user in an organization keyed on oid, to
                                                              find the object id that names the account, and when
                                                              that Entra user was created

Secrets die where they arrive: the OIDC settings carry the client secret in clear, a token list can carry a token's
value and a user record a password field; each is deleted from the answer before any function sees it, and the
record keeps only the fields the allow-lists below name.

Needs Python 3.10 or later and nothing outside the standard library (the `cryptography` package only for a
certificate credential).
Env:  VCFA_HOST; VCFA_PROVIDER_REFRESH_TOKEN_FILE (a provider API token, traded at /oauth/provider/token) or
      VCFA_PROVIDER_BEARER_FILE (a provider bearer, below); TLS_VERIFY=false only on a self-signed lab CA
      (VCF Automation only; Entra and Graph are always verified); ENTRA_TENANT_ID (the id, or a domain name), ENTRA_CLIENT_ID and
      ENTRA_CLIENT_SECRET_FILE, or ENTRA_CERT_FILE and ENTRA_KEY_FILE (PEM; needs the `cryptography` package);
      ORGS (comma list, to read fewer organizations); OUT (default leavers.json; leavers.replay.json under --replay);
      WARN_DAYS (default 30, the watch's): on a provider API token, the run flags its own token inside this many days
      of its end; VCFA_PROVIDER_TOKEN_NAME,
      the name the job's token was minted with (its client_name): set it whenever the run's user owns more than one
      REFRESH token, as during a rotation's overlap or when one administrator mints both scheduled jobs' tokens, or
      the run cannot tell which token it holds and exits 3; change it with the token file at every rotation
      VCFA_PROVIDER_BEARER_FILE holds a provider bearer, mode 0600, for an hour (the portal's states an hour; the Basic
      session's life was not read). Two ways to one, and a close held on each on the reference estate: the provider portal's sign-in (the bearer is what the portal sends as the
      Authorization header of its /cloudapi/ calls, after "Bearer "; the reference runs made that sign-in by script),
      and a Basic provider session, POST /cloudapi/1.0.0/sessions/provider with Basic <user>@System, whose response
      header X-VMWARE-VCLOUD-ACCESS-TOKEN is the bearer. A provider API token was refused the close (403, on a local
      account; a federated account's close on that token was not run).
Use:  python3 leavers.py                                   report every federated organization, write the record
      python3 leavers.py --redact                          the same, printed with placeholders, to share
      python3 leavers.py --name-claim ORG=mail             the same, for an organization whose name claim carries mail
                                                           (repeatable; also userPrincipalName or otherMails): a user
                                                           found by that attribute is the person
      python3 leavers.py --expect-tenants T1,T2            the same, failing (exit 3) on an organization federated to
                                                           an Entra tenant outside the list: every tenant a schedule
                                                           runs for, this one among them, the same list on each
      python3 leavers.py --ack acks.json                   the same, with the flags a person has decided on silenced
                                                           until their date (a JSON list of {"org", "account", "flag",
                                                           "until": "YYYY-MM-DD"}; flag direct-role or
                                                           name-in-use-again); the report lists them as acknowledged
      python3 leavers.py --execute --org NAME [--user ACCOUNT]
                                                           close the confirmed leavers of one organization (with
                                                           --user, only that account; every account is still read)
                     [--max-leavers N]                     refuse the organization when more than N leavers are open
                                                           (default: more than MAX_LEAVERS and more than a quarter)
      python3 leavers.py --close-now --org NAME --user ACCOUNT [--execute]
                                                           the urgent close: one named, federated account, closed now
                                                           without asking Entra whether the person has left; plan only
                                                           without --execute. Needs no Graph credential, except for the
                                                           plan to resolve a principal name in an organization keyed on
                     [--left-on YYYY-MM-DD]                oid, which needs the departure date the leaver notice gives;
                                                           under oid --execute takes the object id or the account id
      ACCOUNT is the account's user name (a principal name, or under oid the object id), a principal name under oid
      (resolved through Graph to the object id; for --close-now, in the plan only), or the account's id
      (urn:vcloud:user:...).
      python3 leavers.py --replay replay/leavers [...]    any of the above without an estate: every answer from the
                                                           recorded set beside this script (its hosts are placeholders),
                                                           dates judged at the time it was recorded; nothing is sent and
                                                           no credential is read, a request the set holds no answer for
                                                           is a read that failed (exit 3), and --execute runs its plan
                                                           alone (with --close-now too): nothing is closed
Exit, the first that applies, so a scheduler reads one state from one number:
      2 with --execute, a close that did not hold on read-back, among them a read-back that did not read; under each
        the run prints how to finish it: the close again for that one account by its id (--close-now --org ORG --user
        ID --execute: it reads the account afresh, revokes what it still holds, writes only if it is still enabled,
        and reads both back), on a provider bearer where the write was refused 403, or, for a field the close did not
        ask that changed, the field put back by hand (a re-run compares with its own read and would not see it)
      1 an open leaver: an account to close (still enabled or holding a token) that three reads agree on, including
        one --execute refused
      3 a read failed, or an account is undetermined (among them a leaver whose reads disagree): nothing is known about
        what was not read (a credential that could not be obtained is one, a tenant no organization names is one, an
        organization --expect-tenants leaves uncovered is one, an organization with its federation switched off that
        still holds an enabled federated account or a token of one is one, a list read in part is one, and so is an
        error the script did not expect: nothing is read, or nothing is trusted, and nothing is written); also the
        run's own provider API token's end date unread (two REFRESH tokens of its user and no
        VCFA_PROVIDER_TOKEN_NAME among the causes), a --close-now name guard that could not read a date, and a
        request a --replay set holds no answer for
      4 a flag (a direct role, a name in use again) not acknowledged in --ack, or the run's own provider API token
        inside WARN_DAYS of its end (rotate it; that flag is not acknowledged, the rotation clears it)
      0 nothing open, nothing unread, nothing flagged (with --close-now: the close held, or the plan printed, which
        says it sent nothing and closed nothing)
      5 a usage error, a Python older than 3.10, an unreadable --ack file, a --user that names no account or more than
        one, an --expect-tenants list that leaves out this run's tenant or names no tenant, a bad WARN_DAYS or
        --left-on, and with --close-now an account that is not federated, under oid a --user given to --execute that
        is not an object id or the account's id, a principal name without --left-on, one the name guard refuses, or
        one no Entra user holds while an account carries it, and a name that selects an account whose protocol is
        stored as keyed on anything but a name, and a --replay directory that cannot be read or holds no replay set
        (nothing is sent, nothing is written)
      A record refused because an estate value survived the scrub is not written, and never hides a finding: the
      run's code stands when it is 1, 2, 3 or 4, and a run whose code was 0 exits 3 (the record was not written); a
      run that closed something prints what its writes did, in counts, and that the record was not written.
The contract every identity companion keeps: 0 nothing for a person to act on, 3 a read failed or a result is
undetermined (never a finding), 5 a usage error; 1, 2 and 4 are this script's own, above; an unexpected error is 3.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shlex
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
# The Entra tenant an organization federated elsewhere names, in its OIDC issuer or its SAML metadata (either host
# Entra issues under), read only to say which schedule reads it (--expect-tenants); never compared any looser.
ENTRA_TENANT_IN = re.compile(r"(?:login\.microsoftonline\.com|sts\.windows\.net)/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
                             r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})(?![\w-])", re.I)
DOMAIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+$")
UNCOVERED = "uncovered: no schedule reads it"
# The lookups a name goes through, in order: the filter each sends to /users. Each is a form Microsoft Graph's user
# resource documents for $filter and serves by default, without the ConsistencyLevel header or $count.
NAME_LOOKUPS = (("userPrincipalName", "userPrincipalName eq '{}'"), ("mail", "mail eq '{}'"),
                ("otherMails", "otherMails/any(m:m eq '{}')"))
NO_SUCH_NAME = "no Entra user has this name"
NAME_CLAIMS = tuple(how for how, _form in NAME_LOOKUPS)  # what --name-claim may declare an organization's claim carries
# VCF Automation refuses a federated sign-in that maps to no imported group and holds no direct role (IAM-F11); an
# account that passes Entra's gate and holds a direct role is the other case, so it is kept, and flagged direct-role.
DIRECT_ROLE_KEEP = "assigned at Entra and holds a direct role"
DIRECT_ROLE_KEEP_OPEN = "Entra requires no assignment for the app, and the account holds a direct role"
NOT_ASSIGNED = "not assigned to the app, directly or through a group"
NESTED_ONLY = ("assigned to the app only through a group nested inside an assigned one, which Entra does not admit; "
               "make the user a direct member")
APPLICATION_GROUP = "ApplicationGroup"
CONFIRM_READS = 3   # reads that must all say "leaver" before the script acts
CONFIRM_PAUSE = 10  # seconds between them
MAX_LEAVERS = 3     # --execute refuses an organization with more open leavers than this and than a quarter of it
FLAG_KINDS = ("direct-role", "name-in-use-again")
EXIT_HELD_NOT, EXIT_OPEN, EXIT_UNREAD, EXIT_FLAGGED, EXIT_USAGE = 2, 1, 3, 4, 5
PAGE_SIZE = 128     # items per page of a cloudapi list asked for; a list is read to the total it states (pages)
MAX_PAGES = 10000   # a bound on one list read: a list that has not reached its stated total by then did not read
SWITCHED_OFF = "federation switched off (OIDC and SAML both disabled)"
PLAN_ONLY = "plan only: nothing was sent and nothing was closed"
# The urgent close's decision: the plan names what it would do, and only a close that ran says it closed.
CLOSE_ON_REQUEST, CLOSED_ON_REQUEST = "close on request", "closed on request"
OID_EXECUTE = ("the organization is keyed on oid, so --execute takes an object id or the account's id "
               "(urn:vcloud:user:...), never a name: {given} is refused before it is resolved and before anything is "
               "sent, whatever Entra holds under it. Run the plan without --execute, with --left-on (the departure date "
               "the leaver notice gives), to resolve the name and print its object id; check that object id against "
               "the leaver notice, then run again with --user <object id> --execute")
UNHELD_NAME = ("no Entra user holds {given} now (Graph answered 404), so it resolves to no object id; the account it "
               "selects, {account}, is named by the name itself, made before the organization was keyed on oid, and is "
               "not the account a person signs in to under oid. Close the person's own account by the object id the "
               "leaver notice or the last report carries; close this one, if it is theirs too, by its id: --user {id}")
RESOLVED_ELSEWHERE = ("{given} resolves to the Entra object id {oid} now, which names no account in the organization; the "
                      "account the name selects, {account}, is named by the name itself, made before the organization was "
                      "keyed on oid, and is not the account a person signs in to under oid. The name may have been given "
                      "to someone else since the departure, so close the departed person's own account by the object id "
                      "the leaver notice or the last report carries; close {account}, if it is theirs too, by its id after "
                      "checking it against the notice: --user {id}")
NOT_NAME_KEYED = ("account {account} signs in over the organization's {protocol}, which it stores as keyed on {key}, "
                  "not on a principal name, so the account a name selects may not be the one a person signs in to: "
                  "check it against the leaver notice, then close it by its id: --user {id}")
WARN_DAYS = 30     # the run's own provider API token flags (exit 4) inside this many days of its end; the watch's default
# An account's creation, as the audit trail records it: a federated account is imported at its first sign-in, a local
# one created. The account record itself carries no creation time (read 2026-10-15, X-212).
CREATED_EVENTS = ("com/vmware/vcloud/event/user/import", "com/vmware/vcloud/event/user/create")
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


def decide(user: dict, found: dict | None, member_of: set | None, gate: dict | None,
           transitive: set | None = None) -> tuple[str, str]:
    """One account, what Entra holds for its name, the watched groups that Entra user is a DIRECT member of (None when
    unread), the organization's gate, and the watched groups it is in through nesting too (None: the same as direct):
    (decision, reason). Decisions: keep, leaver, out of scope, undetermined.

    Entra's gate reads direct membership, because Entra admits only direct members of an assigned group (IAM-F76).
    The groups a sign-in carries are the direct ones under ApplicationGroup claims, which leave nested groups out,
    and the nested ones too under any other claim setting. An account that passes Entra's gate, is carried by no
    imported group and holds a role directly is kept: VCF Automation refuses only a user with neither (IAM-F11)."""
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
    nested = member_of if transitive is None else transitive
    assigned = set(gate["assigned_groups"])
    entra_gate = (not gate["assignment_required"] or found.get("id") in gate["assigned_users"]
                  or bool(member_of & assigned))
    if not entra_gate:
        return "leaver", NESTED_ONLY if nested & assigned else NOT_ASSIGNED
    reach = member_of if gate["group_claims"] == APPLICATION_GROUP else nested
    carried = reach & set(claim_groups(gate))
    if not carried and user.get("roleEntityRefs"):
        return "keep", DIRECT_ROLE_KEEP if gate["assignment_required"] else DIRECT_ROLE_KEEP_OPEN
    if not carried and gate.get("unresolved"):
        return "undetermined", ("an imported group matches no single Entra group ("
                                + ", ".join(gate["unresolved"]) + "), so membership through it cannot be read")
    if not carried:
        return "leaver", "in no imported group the sign-in can carry"
    return "keep", "entitled through " + ", ".join(sorted(claim_groups(gate)[g] for g in carried))


DIRECT_ROLE_OID = ("direct-role: granted to the account directly; the organization is keyed on oid, so a person later "
                   "given this name signs in to a new account and does not reach these roles")
DIRECT_ROLE_ENABLED = ("direct-role: granted to the account by name; while it is enabled, a person later given this name "
                       "signs in to it and holds these roles (shown over SAML and OIDC keyed on preferred_username); a "
                       "disabled account turned the name away")
DIRECT_ROLE_DISABLED = ("direct-role: granted to the account by name; disabled, it turned a person later given this name "
                        "away (shown over SAML and OIDC keyed on preferred_username), and enabling it again hands that "
                        "person these roles")


def flags(user: dict, decision: str, key: str | None = None) -> list[str]:
    """What the script reports and never acts on (IAM-F70: a name in use again takes over the account). The direct-role
    flag says what a later holder of the name reaches, by the organization's user key (`key`, as its settings store it,
    None when they store none): under oid a new account, never these roles; keyed on a name, the account itself while
    it is enabled, and a turned-away sign-in while it is disabled, until it is enabled again."""
    out = []
    if user.get("providerType") in FEDERATED and user.get("roleEntityRefs"):
        out.append(DIRECT_ROLE_OID if key in BY_ID
                   else DIRECT_ROLE_DISABLED if user.get("enabled") is False else DIRECT_ROLE_ENABLED)
    if user.get("providerType") in FEDERATED and user.get("enabled") is False and decision == "keep":
        out.append("name-in-use-again: disabled here, and an enabled, entitled Entra user holds this name; if that "
                   "is a different person, delete the account or drop its direct roles before enabling it")
    return out


def open_leaver(user: dict, decision: str, tokens: list) -> bool:
    """A leaver still enabled or holding a token: the one kind of leaver confirmed, reported open and closed."""
    return decision == "leaver" and (user.get("enabled") is not False or bool(tokens))


def action(user: dict, decision: str, tokens: list, execute: bool, act_ids: set | None) -> str | None:
    """What the run does with an account once every open leaver has been confirmed (a leaver whose reads disagreed
    is undetermined by then): None for a kept one. `act_ids` holds the id of the account --user selected."""
    if decision != "leaver":
        return None
    if not open_leaver(user, decision, tokens):
        return "in step: already disabled, no token"
    if not execute:
        return "would revoke its tokens and disable it"
    if act_ids is not None and user.get("id") not in act_ids:
        return "would revoke its tokens and disable it (outside --user)"
    return "close"


def unconfirmed(seen: list[str]) -> str:
    """The reason a leaver whose reads disagree is undetermined, naming the reads."""
    return (f"Entra's reads disagree: leaver on the first read, then {', '.join(seen)}; reads settle seconds after a "
            "change, so the next run reads it again")


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
                    "why so many read gone (a name claim from another attribute, a lookup refused), then close each "
                    "with --close-now (under oid by its object id, never the name) or rerun with --max-leavers")
            if exceeded else ""}


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
    an account undetermined (or the run's own credential's end date unread), a flag nobody acknowledged (or the run's
    own provider API token inside WARN_DAYS of its end), nothing. A flag never hides a failed read or a leaver."""
    if execute and summary.get("not_held"):
        return EXIT_HELD_NOT
    if summary.get("open_leavers"):
        return EXIT_OPEN
    if summary.get("undetermined") or summary.get("unreadable") or summary.get("credential_unread"):
        return EXIT_UNREAD
    if summary.get("flagged") or summary.get("credential_flagged"):
        return EXIT_FLAGGED
    return 0


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
def _ctx(verify: bool) -> ssl.SSLContext | None:
    if REPLAY is not None:  # a replayed run opens no connection, so it makes no TLS context
        return None
    return ssl.create_default_context() if verify else ssl._create_unverified_context()


def _lab_verify() -> bool:
    return os.environ.get("TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")


def _secret_file(name: str) -> str:
    if REPLAY is not None:  # a replayed run reads no credential: nothing is sent
        return REPLAY_CREDENTIAL
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
            with _urlopen(urllib.request.Request(url, data=data, headers=h, method=method),
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
    credential = "provider bearer"   # or "provider API token": which one the run holds, for its own end-date check

    def __init__(self, host: str, calls: list):
        verify = _lab_verify()
        if os.environ.get("VCFA_PROVIDER_BEARER_FILE"):
            bearer = _secret_file("VCFA_PROVIDER_BEARER_FILE").removeprefix("Bearer ").strip()
        else:
            self.credential = "provider API token"
            form = urllib.parse.urlencode({"grant_type": "refresh_token",
                                           "refresh_token": _secret_file("VCFA_PROVIDER_REFRESH_TOKEN_FILE")}).encode()
            req = urllib.request.Request(f"https://{host}/oauth/provider/token", data=form, method="POST", headers={
                "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
            with _urlopen(req, context=_ctx(verify), timeout=60) as r:
                bearer = json.loads(r.read())["access_token"]
        super().__init__("vcf-automation", f"https://{host}", {"Authorization": f"Bearer {bearer}"}, verify, calls)
        del bearer

    def pages(self, path: str, org_urn: str | None = None) -> list | None:
        """Every item of a cloudapi list, read to the total the list states: pages count from 1, PAGE_SIZE items
        asked of each, and the list is read when its distinct items (by id) number the answer's resultTotal. None,
        never a shorter list, when a page is refused, an answer carries no `values` list or no resultTotal, the total
        changes between pages, a page comes back empty or short of the page size it states before the total is
        reached, a page adds no item not already read (the list served again, or moved under the read: it is unread at
        that page, never after MAX_PAGES more), or the distinct items pass the total: a list read in part is not a list
        (G-431, B11-S3). An empty list carries `values` and a resultTotal of 0. The call that ended a read in part is
        marked with why."""
        seen: dict[str, dict] = {}
        total, hdr = None, ({TENANT_HEADER: org_urn} if org_urn else {})
        for page in range(1, MAX_PAGES + 1):
            _status, answer = self.call("GET", f"{path}?page={page}&pageSize={PAGE_SIZE}",
                                        accept=TENANT_JSON if org_urn else CLOUDAPI, headers=hdr)
            why = list_shape(answer, "values", total)
            if why is None:
                total, rows, before = answer["resultTotal"], answer["values"], len(seen)
                for r in rows:
                    seen.setdefault(item_key(r), r)
                if len(seen) == total:
                    return list(seen.values())
                size = answer.get("pageSize")
                size = size if isinstance(size, int) and not isinstance(size, bool) and size > 0 else PAGE_SIZE
                if len(seen) > total:
                    why = f"{len(seen)} distinct items, more than the {total} the answer states"
                elif len(rows) < size:
                    why = f"the pages ended at {len(seen)} of the {total} the answer states"
                elif len(seen) == before:
                    why = f"page {page} added nothing to the {len(seen)} of the {total} the answer states"
            if why is not None:
                if self.calls and self.calls[-1].get("status") == 200:
                    self.calls[-1]["shape"] = why
                return None
        if self.calls:
            self.calls[-1]["shape"] = f"no end after {MAX_PAGES} pages"
        return None


def item_key(item: object) -> str:
    """What makes a list item distinct: its id, or, for one that carries none, its whole content."""
    if isinstance(item, dict) and item.get("id") is not None:
        return "id:" + str(item["id"])
    return "item:" + json.dumps(item, sort_keys=True, default=str)


def list_shape(answer: object, key: str, total: int | None) -> str | None:
    """Why one page of a cloudapi list did not read, or None: the answer carries its list under `key` and a whole
    resultTotal of 0 or more, the same total as the pages before it (`total`, None on the first page)."""
    if not isinstance(answer, dict) or not isinstance(answer.get(key), list):
        return f"no {key} list in the answer"
    stated = answer.get("resultTotal")
    if not isinstance(stated, int) or isinstance(stated, bool) or stated < 0:
        return "no resultTotal in the answer"
    if total is not None and stated != total:
        return f"the total changed between pages ({total}, then {stated})"
    return None


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
        with _urlopen(req, context=_ctx(True), timeout=60) as r:
            bearer = json.loads(r.read())["access_token"]
        del form
        self.tid = token_tenant(bearer)
        super().__init__("graph", GRAPH, {"Authorization": f"Bearer {bearer}"}, True, calls)
        del bearer

    def values(self, path: str, **query: str) -> list | None:
        """Every item of a Graph list, following @odata.nextLink until an answer carries none; None, never a shorter
        list, when a page was refused, a 200 came back without its `value` list (B11-S3), a next link repeats one
        already followed (the pages would go round for ever), or MAX_PAGES pass: a list read in part is not a list.
        A page with no items and a next link is read on, since Graph's paging guidance says a page may hold none.
        The page that did not read is marked with why."""
        qs = urllib.parse.urlencode({f"${k}": v for k, v in query.items()}, quote_via=urllib.parse.quote)
        url, out, followed = f"{GRAPH}{path}" + (f"?{qs}" if qs else ""), [], set()
        for _page in range(MAX_PAGES):
            _status, answer = self.call("GET", url)
            if not isinstance(answer, dict) or not isinstance(answer.get("value"), list):
                if self.calls and self.calls[-1].get("status") == 200:
                    self.calls[-1]["shape"] = "no value list in the answer"
                return None
            out += answer["value"]
            followed.add(url)
            url = answer.get("@odata.nextLink")
            if not url:
                return out
            if not isinstance(url, str):
                self.calls[-1]["shape"] = "a next page link that is not a link"
                return None
            if url in followed:
                self.calls[-1]["shape"] = "the next page link repeats one already read"
                return None
        self.calls[-1]["shape"] = f"no end after {MAX_PAGES} pages"
        return None

    def one(self, path: str, flt: str, select: str) -> dict | None:
        rows = self.values(path, filter=flt, select=select)
        if rows is None:
            raise LookupError(f"Graph refused {path}")
        return rows[0] if len(rows) == 1 else None


def token_tenant(bearer: str) -> str | None:
    """The `tid` claim of a Graph access token, lower case, read in memory and never printed or kept beside the token;
    None when the token's payload is not readable JSON or carries no tid shaped like a tenant id."""
    try:
        part = bearer.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    except (IndexError, ValueError):
        return None
    tid = str(claims.get("tid") or "") if isinstance(claims, dict) else ""
    return tid.lower() if OBJECT_ID.match(tid) else None


def resolve_tenant(given: str, graph: Graph) -> tuple[str | None, str]:
    """The tenant's id in lower case, and how it was had. An id given in any case is taken as it is; a domain name is
    resolved from the Graph token's tid claim, or else from Graph's /organization (which needs Organization.Read.All).
    (None, why) when neither gives one: the run then reads nothing, because an organization is matched by this id."""
    g = given.strip()
    if OBJECT_ID.match(g):
        return g.lower(), "ENTRA_TENANT_ID"
    if getattr(graph, "tid", None):
        return graph.tid, "the Graph token's tid claim"
    rows = graph.values("/organization", select="id")
    if rows and len(rows) == 1 and OBJECT_ID.match(str(rows[0].get("id") or "")):
        return str(rows[0]["id"]).lower(), "Graph's /organization"
    return None, ("ENTRA_TENANT_ID is not a tenant id, and neither the Graph token's tid claim nor Graph's /organization "
                  "(which needs Organization.Read.All) gave the id it names; set ENTRA_TENANT_ID to the tenant's id")


def _assertion(tenant: str, client: str) -> str:
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
    claims = {"aud": f"{ENTRA}/{tenant}/oauth2/v2.0/token", "iss": client, "sub": client, "jti": str(uuid.uuid4()),
              "nbf": now, "iat": now, "exp": now + 600}
    signing = b64(json.dumps(head, separators=(",", ":")).encode()) + "." + b64(json.dumps(claims, separators=(",", ":")).encode())
    sig = key.sign(signing.encode(), padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
                   hashes.SHA256())
    return signing + "." + b64(sig)


# ── reading the two planes ───────────────────────────────────────────────────────────────────────────────────────
def parse_expect_tenants(value: str) -> list[str]:
    """--expect-tenants T1,T2,...: each a tenant id (in any case) or a domain name, as ENTRA_TENANT_ID may be. Anything
    else, or an empty list, is refused (ValueError), never half read. Ids come back in lower case, duplicates once."""
    out: list[str] = []
    for v in (x.strip() for x in value.split(",")):
        if not (OBJECT_ID.match(v) or DOMAIN.match(v)):
            raise ValueError(f"--expect-tenants {value!r}: write a comma list of tenant ids or domain names ({v!r} is neither)")
        v = v.lower()
        if v not in out:
            out.append(v)
    return out


def resolve_expected(values: list[str], tenant: str, given: str, calls: list,
                     fetch=None) -> tuple[list[str] | None, str, bool]:
    """Each --expect-tenants value as a tenant id: an id as it is; this run's own ENTRA_TENANT_ID as the tenant the run
    resolved; any other domain name from Entra's OpenID discovery document for it, whose issuer names the tenant id.
    Returns (ids, why, usage): ids None when one could not be had, `usage` True when Entra named no such tenant (a
    bad argument, exit 5) and False when the read itself failed (exit 3). `fetch` is the HTTP read, for tests."""
    out: list[str] = []
    for v in values:
        if OBJECT_ID.match(v):
            out.append(v.lower())
            continue
        if v == given.strip().lower():
            out.append(tenant)
            continue
        rec = {"plane": "entra", "method": "GET", "path": "/<tenant>/v2.0/.well-known/openid-configuration", "status": None}
        calls.append(rec)
        status, doc = (fetch or _discovery)(v)
        rec["status"] = status
        m = ENTRA_TENANT_IN.search(str((doc or {}).get("issuer") or "")) if isinstance(doc, dict) else None
        if m:
            out.append(m.group(1).lower())
        elif status == 400:
            return None, f"--expect-tenants names {v}, which Entra knows as no tenant", True
        else:
            return None, f"--expect-tenants {v}: Entra's discovery document did not give its tenant id ({status})", False
    return sorted(set(out)), "", False


def _discovery(domain: str) -> tuple[int | None, dict | None]:
    """Entra's OpenID discovery document for a tenant named by a domain: GET {ENTRA}/{domain}/v2.0/.well-known/
    openid-configuration, no credential. 400 names no tenant; the issuer carries the tenant id."""
    url = f"{ENTRA}/{urllib.parse.quote(domain)}/v2.0/.well-known/openid-configuration"
    try:
        with _urlopen(url, context=_ctx(True), timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, None
    except (urllib.error.URLError, OSError, ValueError):
        return None, None


def coverage(others: list[dict], tenant: str, expected: list[str]) -> tuple[list[dict], list[dict]]:
    """Who reads each organization federated elsewhere, given every tenant a schedule runs for: the schedule of its
    own tenant when --expect-tenants names it; no Entra tenant, another provider this job does not read; otherwise
    nobody, so it is uncovered and unreadable (exit 3). An organization naming this run's tenant in a form the job
    does not read (an OIDC issuer on sts.windows.net, or no client id) is uncovered too: no schedule reads it."""
    shown, uncovered = [], []
    for o in others:
        t = o.get("tenant")
        if t is None:
            read_by = "another provider, not Entra ID: not read by this job"
        elif t == tenant:
            read_by = UNCOVERED + " (it names this run's tenant in a form this job does not read)"
        elif t in expected:
            read_by = "the schedule for its own tenant"
        else:
            read_by = UNCOVERED + " (its Entra tenant is not in --expect-tenants)"
        shown.append({**o, "read_by": read_by})
        if read_by.startswith(UNCOVERED):
            uncovered.append({"org": o["org"], "reason": read_by})
    return shown, uncovered


def federated_orgs(vcfa: Vcfa, tenant: str, only: list[str], others: list | None = None,
                   off: list | None = None) -> tuple[list[dict], list[dict], int]:
    """The organizations federated to the tenant, found from their own settings; the ones that could not be read;
    and how many others have OIDC or SAML on toward another provider (each appended to `others`, when given, with
    the Entra tenant its issuer or metadata names, or None). Each organization with OIDC and SAML both switched off is
    appended to `off`, when given, so that it is listed and read (read_switched_off), never dropped (B11-S2). The
    tenant id is compared without regard to case and up to its end, so an id in capitals matches and a longer one
    never does."""
    found, unreadable, elsewhere = [], [], 0
    t = re.escape(tenant.strip().lower())
    oidc_issuer = re.compile(rf"login\.microsoftonline\.com/{t}(?![\w-])", re.I)
    saml_issuer = re.compile(rf"sts\.windows\.net/{t}(?![\w-])", re.I)
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
        if oauth.get("enabled") and oidc_issuer.search(str(oauth.get("issuerId") or "")) and oauth.get("clientId"):
            found.append({"org": name, "urn": urn, "protocol": "OIDC", "app": oauth["clientId"],
                          "key": (oauth.get("oidcAttributeMapping") or {}).get("subjectAttributeName")})
        elif fed.get("enabled") and saml_issuer.search(str(fed.get("samlMetadata") or "")):
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
            if others is not None:
                text = str(oauth.get("issuerId") or "") if oauth.get("enabled") else str(fed.get("samlMetadata") or "")
                m = ENTRA_TENANT_IN.search(text)
                others.append({"org": name, "protocol": "OIDC" if oauth.get("enabled") else "SAML",
                               "tenant": m.group(1).lower() if m else None})
        elif off is not None:
            off.append({"org": name, "urn": urn})
    listed_off = {o["org"] for o in off or []}
    for n in sorted(set(only) - {o["org"] for o in found} - {u["org"] for u in unreadable} - listed_off):
        unreadable.append({"org": n, "reason": "not found, or not federated to this tenant"})
    return found, unreadable, elsewhere


def read_switched_off(vcfa: Vcfa, off: list[dict]) -> tuple[list[dict], list[dict]]:
    """Each organization with its federation switched off, read for what federated sign-in left in it: its enabled
    federated accounts, and the API tokens of its federated accounts (whether such a token stops refreshing while the
    federation is off was not tested).
    The report does not judge them (it does not know whose they are at Entra), so an organization that holds either
    is unreadable (exit 3), and one that holds neither is listed and changes no exit. Returns (rows, unreadable)."""
    rows, unread = [], []
    for o in off:
        users = vcfa.pages("/cloudapi/1.0.0/users", o["urn"])
        tokens = vcfa.pages("/cloudapi/1.0.0/tokens", o["urn"]) if users is not None else None
        if users is None or tokens is None:
            rows.append({"org": o["org"], "enabled_federated": None, "federated_tokens": None})
            unread.append({"org": o["org"], "reason": "federation switched off, and its users or tokens could not be read"})
            continue
        federated = {u.get("id") for u in users if u.get("providerType") in FEDERATED}
        n = sum(1 for u in users if u.get("providerType") in FEDERATED and u.get("enabled") is not False)
        m = sum(1 for t in tokens if (t.get("owner") or {}).get("id") in federated)
        rows.append({"org": o["org"], "enabled_federated": n, "federated_tokens": m})
        if n or m:
            unread.append({"org": o["org"], "reason": (
                f"{SWITCHED_OFF}, and it still holds {n} enabled federated account(s) and {m} API token(s) of federated "
                "accounts: this report does not judge them; close a leaver's account with --close-now (it reads the "
                "key the organization stores, so under oid by the object id, never the name), or switch federation "
                "back on so the report reads them")})
    return rows, unread


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
    gate = {"user_key": key, "lookup": "name" if key in BY_NAME else "id" if key in BY_ID else None,
            "assignment_required": bool(sp.get("appRoleAssignmentRequired")),
            "group_claims": app.get("groupMembershipClaims"),
            "assigned_groups": {a["principalId"]: str(a.get("principalDisplayName")) for a in assigned
                                if a.get("principalType") == "Group"},
            "assigned_users": {a["principalId"] for a in assigned if a.get("principalType") == "User"},
            "imported": imported, "imported_ids": ids, "unresolved": unresolved}
    gate["direct"] = direct_members(graph, watched(gate))
    if gate["direct"] is None:  # refused: who is a direct member is unknown, so nothing is judged
        raise LookupError("Graph refused a gate group's direct members")
    return gate


def direct_members(graph: Graph, groups: list[str]) -> dict[str, set] | None:
    """Each group's direct members by object id (GET /groups/{id}/members, every page, no query parameter: the
    plain form Graph serves without advanced query parameters); None when a read was refused."""
    out = {}
    for gid in groups:
        rows = graph.values(f"/groups/{gid}/members")
        if rows is None:
            return None
        out[gid] = {str(r.get("id")) for r in rows}
    return out


def direct_of(gate: dict, user_id: str) -> set:
    """The watched groups a user is a direct member of, from the gate's read of each group's members."""
    return {g for g, members in (gate.get("direct") or {}).items() if user_id in members}


def carries_name(row: dict, attribute: str, name: str) -> bool:
    """Whether an Entra user's `attribute` (userPrincipalName, mail, or one of otherMails) is `name`, in any case."""
    value = row.get(attribute)
    values = value if isinstance(value, list) else [value]
    return name.lower() in {str(v).lower() for v in values if v}


def entra_user(graph: Graph, username: str, lookup: str = "name",
               claim: str | None = None) -> tuple[dict | None, str | None]:
    """The Entra user an account names, and how it was found. Under oid, by object id. By name, by userPrincipalName,
    then mail, then otherMails: every lookup is read, and exactly one Entra user across them is the person (the first
    lookup that found it says how). (None, None): no lookup found anyone. A refused read, or more than one user,
    raises LookupError, so the account is undetermined and never a leaver.

    `claim` is the attribute the organization's name claim carries, as the operator declared it (--name-claim); the
    job cannot read it, so undeclared means userPrincipalName. The user found is the person only when that attribute
    holds the name; otherwise NameMismatchError, undetermined with the mismatch as its reason."""
    select = "id,userPrincipalName,accountEnabled,mail,otherMails"
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
    if not found:
        return None, None
    row, how = next(iter(found.values()))
    carried = claim or "userPrincipalName"
    if how != carried and not carries_name(row, carried, username):
        if claim:
            raise NameMismatchError(f"found only by {how}, and the organization's name claim carries {claim}, which on that "
                                    "Entra user is another name, so it is not the person who signs in under this name")
        raise NameMismatchError(f"found only by {how}, and that Entra user's userPrincipalName is another name; whether the "
                                f"organization's name claim carries {how} is not something this job can read: declare it "
                                f"with --name-claim <org>={how}")
    return row, how


class NameMismatchError(LookupError):
    """A name found only by mail or otherMails on an Entra user whose principal name differs: undetermined, not a
    read that failed (the reason says so), and never taken as the person."""


def member_of(graph: Graph, user_id: str, groups: list[str]) -> set | None:
    """Which of the given groups the user is in, nested groups included (Graph's checkMemberGroups, at most 20 group
    ids per call). Entra's gate reads direct membership instead (direct_of). None when a call was refused or a 200
    came back without its `value` list, which is a read that failed, never "in no group" (B11-S3)."""
    out = set()
    for i in range(0, len(groups), 20):
        _s, answer = graph.call("POST", f"/users/{user_id}/checkMemberGroups", {"groupIds": groups[i:i + 20]})
        if not isinstance(answer, dict) or not isinstance(answer.get("value"), list):
            if graph.calls and graph.calls[-1].get("status") == 200:
                graph.calls[-1]["shape"] = "no value list in the answer"
            return None
        out |= set(answer["value"])
    return out


class Verdict(tuple):
    """(decision, reason, found, matched_by): found is True when Entra holds the account's user, False when no lookup
    found one, None when none was made; matched_by names the lookup that found it."""

    def __new__(cls, decision: str, reason: str, found: bool | None = None, matched_by: str | None = None):
        return super().__new__(cls, (decision, reason, found, matched_by))


def judge(graph: Graph, user: dict, gate: dict | None) -> Verdict:
    """Read Entra for one account and apply the rule: direct membership from the gate groups' members (read once per
    organization, in read_gate), membership through nesting from checkMemberGroups. A refused read makes the account
    undetermined, and so does a name found only by mail or otherMails on a user of another principal name."""
    if user.get("providerType") not in FEDERATED or gate is None:
        return Verdict(*decide(user, None, None, gate))
    lookup = gate.get("lookup")
    if lookup is None:
        return Verdict("undetermined", f"the organization's user key ({gate.get('user_key') or 'not set'}) is not one "
                                       "this job matches to Entra, so no account of it is judged")
    if lookup == "id" and not OBJECT_ID.match(str(user.get("username"))):
        return Verdict("undetermined", "the organization is keyed on the object id and this account's name is not one")
    try:
        found, how = entra_user(graph, user["username"], lookup, gate.get("name_claim"))
    except NameMismatchError as e:
        return Verdict("undetermined", str(e))
    except LookupError as e:
        return Verdict("undetermined", f"Entra could not be read for this user: {e}")
    if not found:
        return Verdict(*decide(user, None, set(), gate), False, how)
    nested = member_of(graph, found["id"], watched(gate))
    if nested is None:  # a read that failed is never a pass, whichever group claims the app sends
        return Verdict("undetermined", "the user's group membership through nested groups could not be read", True, how)
    return Verdict(*decide(user, found, direct_of(gate, found["id"]), gate, nested), True, how)


def confirm_all(graph: Graph, users: list[dict], gate: dict, reads: int | None = None, pause: float | None = None,
                sleep=time.sleep) -> dict[str, tuple[bool, list[str]]]:
    """Read each account's state again `reads` times, `pause` seconds apart, in rounds: each round reads the gate
    groups' direct members afresh, then judges every account on that read, so an organization's leavers cost the
    same wall time as one. {account id: (True only when every read says leaver, the reads)}."""
    reads = CONFIRM_READS if reads is None else reads
    if pause is None:  # recorded answers do not settle: a replayed run reads them again without waiting
        pause = 0 if REPLAY is not None else CONFIRM_PAUSE
    seen: dict[str, list[str]] = {str(u.get("id")): [] for u in users}
    for i in range(reads):
        if i:
            sleep(pause)
        direct = direct_members(graph, watched(gate))
        for u in users:
            seen[str(u.get("id"))].append("undetermined" if direct is None
                                          else judge(graph, u, {**gate, "direct": direct})[0])
    return {k: (all(d == "leaver" for d in v), v) for k, v in seen.items()}


def confirm(graph: Graph, user: dict, gate: dict, reads: int | None = None, pause: float | None = None,
            sleep=time.sleep) -> tuple[bool, list[str]]:
    """One account's confirmation (confirm_all for one)."""
    return confirm_all(graph, [user], gate, reads, pause, sleep)[str(user.get("id"))]


def user_path(name: str) -> str:
    """Graph's path for one user by object id or principal name, as its Get user reference gives it (GET
    /users/{id | userPrincipalName}): `#` sent as %23 (a guest's principal name), and a name beginning with `$` in
    the /users('...') form, since /users/$x fails."""
    if name.startswith("$"):
        return "/users('" + urllib.parse.quote(name.replace("'", "''"), safe="@$'") + "')"
    return "/users/" + urllib.parse.quote(name, safe="@")


def select_account(users: list[dict], given: str, key: str | None, graph: Graph | None) -> dict:
    """The one account `given` (--user) names in an organization, and how it was found; never a guess.

    The value is compared with each account's user name in any case, and with its id. In an organization keyed on oid each account is named
    by its person's Entra object id, so a value that is not an object id (nor an account id) is taken as a principal
    name and resolved through Graph, and the account named by that object id is a candidate beside any account named
    by the value itself (one made before the organization was keyed on oid). Exactly one candidate is `account`;
    none, or more than one, is `refused` (a usage error, exit 5); a resolution Graph refused is `unread` (exit 3)."""
    m: dict = {"given": given, "user_key": key, "resolved_by": "as given", "object_id": None, "accounts": []}
    low = given.lower()
    cands = {str(u.get("id")): u for u in users
             if str(u.get("username", "")).lower() == low or str(u.get("id", "")).lower() == low}
    if key in BY_ID and not OBJECT_ID.match(given) and not low.startswith("urn:vcloud:user:"):
        if graph is None:
            m["refused"] = ("the organization is keyed on oid, so its accounts are named by object id: pass the object "
                            "id, or set ENTRA_TENANT_ID, ENTRA_CLIENT_ID and a credential (see the header) so the "
                            "principal name can be resolved")
            return m
        m["resolved_by"] = "Graph GET /users/{principal name}"
        status, answer = graph.call("GET", user_path(given) + "?$select=id,userPrincipalName,createdDateTime")
        if status == 404:
            m["entra"] = "no Entra user has this principal name"
        elif isinstance(answer, dict) and OBJECT_ID.match(str(answer.get("id") or "")):
            m["object_id"], m["principal_name"] = str(answer["id"]), answer.get("userPrincipalName")
            m["entra_created"] = answer.get("createdDateTime")  # whoever holds the name now: the guard reads it
            cands.update({str(u.get("id")): u for u in users
                          if str(u.get("username", "")).lower() == m["object_id"].lower()})
        else:
            m["unread"] = f"Graph did not answer GET /users/{{principal name}} ({status}), so the object id is not known"
            return m
    m["accounts"] = sorted(str(u.get("username")) for u in cands.values())
    if len(cands) == 1:
        (aid, u), = cands.items()
        m["id"], m["account"] = aid, str(u.get("username"))
    elif not cands:
        m["refused"] = (f"--user {given} names no account of the organization"
                        + (f" (nor does its object id {m['object_id']})" if m["object_id"] else "")
                        + (f"; {m['entra']}: the person may have been deleted at Entra, so close by the object id the "
                           "leaver notice or the last report carries" if m.get("entra") else
                           ": the person may never have signed in; the report lists every account by its user name"))
    else:
        m["refused"] = (f"--user {given} names {len(cands)} accounts ({', '.join(m['accounts'])}); it acts on exactly "
                        "one and never guesses: pass that account's id (urn:vcloud:user:...) from the record")
    return m


def match_line(m: dict) -> str:
    """The match, as printed before anything is sent: the name given, the object id it resolved to and when that Entra
    user was created, the account, and when the account was created, as far as each was read."""
    how = (f", Entra user {m.get('principal_name')}, object id {m['object_id']}, created "
           f"{m.get('entra_created') or 'not given'}" if m.get("object_id")
           else f", {m['entra']}" if m.get("entra") else "")
    where = (f" selects account {m['account']}" + (f", created {m['account_created']}" if m.get("account_created") else "")
             if m.get("account") else "")
    if m.get("refused"):
        where += f": refused ({m['refused']})"
    elif m.get("unread"):
        where += f": unread ({m['unread']})"
    return f"  --user {m['given']} (resolved {m['resolved_by']}{how}){where}"


def _day(stamp: str | None) -> str | None:
    """The UTC date of an ISO 8601 time stamp (Graph's createdDateTime, the audit trail's timestamp), or None."""
    return stamp[:10] if isinstance(stamp, str) and re.match(r"\d{4}-\d{2}-\d{2}", stamp) else None


def account_created(vcfa: Vcfa, user_id: str) -> dict:
    """When VCF Automation made an account, from the audit trail: the account's import event (a federated account,
    at its first sign-in) or create event (a local one). The account record carries no creation time. An account
    older than the trail's reach has no such event, so the trail's oldest event bounds it: made before then.
    {"at": stamp} or {"before": stamp}, or {"unread": why} when a read failed (X-212: the trail on the reference
    estate held every lab account's event and reached back some 39 days)."""
    flt = f"eventEntity.id=={user_id};(" + ",".join(f"eventType=={e}" for e in CREATED_EVENTS) + ")"
    q = urllib.parse.urlencode({"filter": flt, "sortAsc": "timestamp", "page": 1, "pageSize": 1})
    _s, answer = vcfa.call("GET", f"/cloudapi/1.0.0/auditTrail?{q}", accept=CLOUDAPI)
    if not isinstance(answer, dict) or not isinstance(answer.get("values"), list):
        return {"unread": f"the audit trail did not answer for the account ({vcfa.calls[-1].get('status')})"}
    if answer["values"]:
        return {"at": answer["values"][0].get("timestamp")}
    q = urllib.parse.urlencode({"sortAsc": "timestamp", "page": 1, "pageSize": 1})
    _s, oldest = vcfa.call("GET", f"/cloudapi/1.0.0/auditTrail?{q}", accept=CLOUDAPI)
    if not isinstance(oldest, dict) or not isinstance(oldest.get("values"), list) or not oldest["values"]:
        return {"unread": f"the audit trail's oldest event did not read ({vcfa.calls[-1].get('status')})"}
    return {"before": oldest["values"][0].get("timestamp")}


def name_guard(m: dict, made: dict, left_on: str | None) -> dict:
    """Whether a principal name under oid may name the account for an urgent close. Graph resolves a name to whoever
    holds it now; after a reuse that is a new person, whose own account the name then selects, and a close would lock
    that person out while the departed person's account stays open (G-430). So the name is taken only beside the
    departure date the leaver notice gives (--left-on), and refused when the Entra user holding it now was created on
    or after that date, when the account it selects was made on or after it (someone who signed in after the person
    left), or when that user is newer than the account (an account made before the organization was keyed on oid,
    named by the name, which an earlier holder made). {"ok": True}, {"refused": why}, or {"unread": why} when a date
    the guard needs could not be read or did not parse: a guard that could not run never passes (A11-S3). What the
    dates cannot catch is an existing person renamed onto the name, whose user and account both predate the
    departure; so a name that passes is still only a plan, and close_now's --execute takes the object id."""
    if not left_on:
        return {"refused": "the organization is keyed on oid: close by the object id the leaver notice or the last report "
                           "carries; a principal name resolves to whoever holds it now, so the plan takes one only with "
                           "--left-on YYYY-MM-DD, the departure date the notice gives, and --execute never takes one"}
    held = _day(m.get("entra_created"))
    if held is None:
        return {"unread": "Graph gave no createdDateTime for the Entra user who holds the name, so the guard could not run"}
    if made.get("unread"):
        return {"unread": made["unread"] + ", so the guard could not run"}
    if held >= left_on:
        return {"refused": f"the Entra user who holds {m['given']} now was created {held}, on or after the departure on "
                           f"{left_on}: the name was given to someone after the person left; close by the object id the "
                           "notice or the last report carries"}
    made_on, bound = _day(made.get("at")), _day(made.get("before"))
    if made_on is None and bound is None:
        return {"unread": "the audit trail's event for the account, or its oldest event, carried no time stamp that "
                          "reads as a date, so the guard could not run"}
    if made_on and made_on >= left_on:
        return {"refused": f"the account was made {made_on}, on or after the departure on {left_on}: it belongs to someone "
                           "who signed in after the person left; close by the object id the notice or the last report "
                           "carries"}
    if (made_on and held > made_on) or (bound and held > bound):
        return {"refused": f"the account was made {made_on or 'before ' + bound}, before the Entra user who holds the name "
                           f"now was created ({held}): an earlier holder of the name made it; close by the account's id "
                           "from the last report"}
    return {"ok": True}


def close(vcfa: Vcfa, urn: str, user: dict, tokens: list[dict]) -> dict:
    """Read the account, and only when it reads as a federated account revoke its tokens, then disable it by a round
    trip of its full record; read both back. The record must come back unchanged apart from `enabled`; a refused call
    ends this close, and a read-back that did not read (refused, or a 200 without its list) is a close that did not
    hold, naming the read (G-431). Nothing is sent to an account that is not federated: on a local one the disable was
    refused (400) after its tokens were gone."""
    hdr, out = {TENANT_HEADER: urn}, {"revoked": [], "disabled": False}
    path = f"/cloudapi/1.0.0/users/{user['id']}"
    _s, before = vcfa.call("GET", path, accept=TENANT_JSON, headers=hdr)
    if not isinstance(before, dict):
        return {**out, "held": False, "error": f"the account could not be read ({vcfa.calls[-1].get('status')}); nothing sent"}
    if before.get("providerType") not in FEDERATED:
        return {**out, "held": False, "error": f"a {before.get('providerType') or 'unknown'} account, not federated; nothing sent"}
    for t in tokens:
        status, _a = vcfa.call("DELETE", f"/cloudapi/1.0.0/tokens/{t['id']}", accept=TENANT_JSON, headers=hdr)
        out["revoked"].append({"name": t.get("name"), "type": t.get("type"), "status": status})
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
    if not isinstance(after, dict):
        out["read_back"] = {"enabled": None, "changed_unasked": None, "tokens_left": None}
        return {**out, "held": False, "error": f"the account read-back did not read ({vcfa.calls[-1].get('status')})"}
    moved = sorted(k for k in set(before) | set(after) if k not in allowed and before.get(k) != after.get(k))
    listed = vcfa.pages("/cloudapi/1.0.0/tokens", urn)
    left = None if listed is None else [t.get("name") for t in listed if (t.get("owner") or {}).get("id") == user["id"]]
    out["read_back"] = {"enabled": after.get("enabled"), "changed_unasked": moved, "tokens_left": left}
    if left is None:
        st = vcfa.calls[-1].get("status")
        return {**out, "held": False, "error": "the token read-back did not read ("
                + (f"{st}, no token list" if st == 200 else f"{st or 'no answer'}") + "), so no token left is not known"}
    out["held"] = after.get("enabled") is False and not moved and not left \
        and all(r["status"] in (200, 204) for r in out["revoked"])
    return out


# Exit 2, finished: the command the run prints under each close that did not hold, and the calls a close sends, in its
# order, for a person finishing one without the script. Each call carries the organization's tenant-context header.
FINISH = "python3 leavers.py --close-now --org {org} --user {account} --execute"
CLOSE_CALLS = (
    ("GET", "/cloudapi/1.0.0/users/<account id>", "the account's record as it stands"),
    ("DELETE", "/cloudapi/1.0.0/tokens/<token id>", "each API token the account still holds"),
    ("PUT", "/cloudapi/1.0.0/users/<account id>", "that record, with enabled false"),
    ("GET", "/cloudapi/1.0.0/users/<account id>", "read back: disabled, no other field changed"),
    ("GET", "/cloudapi/1.0.0/tokens", "read back: no token the account owns"),
)


def finish_lines(org: str, row: dict) -> list[str]:
    """What a person does with a close that did not hold (exit 2), from the row's result alone, printed under it.

    Most such closes are finished by running the close again for that one account by its id, which `--close-now`
    takes whatever key the organization stores: it reads the account afresh, revokes each token it still owns, writes
    only if the account is still enabled, and reads both back, so a run that stopped part way is finished and one that
    went through changes nothing. Three results are not: a write refused 403 (on a provider API token the close's write
    was refused, so it is run on a provider bearer); an account that is not federated (no close of this script's
    takes it); and a field the close did not ask that changed, which a re-run cannot see because it compares with its
    own read, so the field is put back by hand. A close that held, or a row nothing closed, prints nothing."""
    res = row.get("result") or {}
    if row.get("action") != "closed" or res.get("held") is not False:
        return []
    err, rb = str(res.get("error") or ""), res.get("read_back") or {}
    moved = rb.get("changed_unasked") or []
    if "not federated" in err:
        return [f"      finish: by hand in the organization's own administration: {err.split(';', 1)[0]}, which no close "
                "of this script takes"]
    out = []
    if moved:
        out.append(f"      finish by hand: the close changed {', '.join(moved)}, which it did not ask: read the account "
                   "(GET /cloudapi/1.0.0/users/<account id>) and put the field back with a PUT of its record; a re-run "
                   "compares with its own read and would not see the change")
    left = [err] if err else []
    failed = sum(1 for t in res.get("revoked") or [] if t.get("status") not in (200, 204))
    if failed:
        left.append(f"{failed} token revoke(s) refused")
    if rb.get("tokens_left"):
        left.append(f"{len(rb['tokens_left'])} token(s) left")
    if rb.get("enabled") is True:
        left.append("the account still enabled")
    if left or not moved:
        cmd = FINISH.format(org=shlex.quote(str(org)), account=shlex.quote(str(row.get("id"))))
        bearer = " on a provider bearer (a provider API token was refused the close's write)" if "(403)" in err else ""
        out.append(f"      finish: {cmd}{bearer}  ({'; '.join(left) or 'the close did not hold'}: the re-run reads "
                   "the account afresh, revokes what it still holds, writes only if it is still enabled, and reads "
                   "both back)")
    return out


def org_key(vcfa: Vcfa, urn: str) -> tuple[bool, str | None]:
    """An organization's OIDC user key as its settings store it: (read, key), whatever `enabled` says. An organization
    switched off that stores oid is treated as keyed on oid, never as keyed on a name (N2: read only while OIDC was on,
    the key of one switched off was None, so a name was taken as the key and an account made before the key closed by
    it). None when the settings store no key."""
    _s, oauth = vcfa.call("GET", f"/api/admin/org/{urn.rsplit(':', 1)[-1]}/settings/oauth", accept=VCD_JSON)
    if not isinstance(oauth, dict):
        return False, None
    mapping = oauth.get("oidcAttributeMapping")
    return True, (mapping.get("subjectAttributeName") if isinstance(mapping, dict) else None)


def saml_key(vcfa: Vcfa, urn: str) -> tuple[bool, str | None]:
    """An organization's SAML user-name key as it stores it (samlAttributeMapping's userNameAttributeName): (read, key),
    whatever `enabled` says; None when it stores none."""
    _s, fed = vcfa.call("GET", f"/api/admin/org/{urn.rsplit(':', 1)[-1]}/settings/federation", accept=VCD_JSON)
    if not isinstance(fed, dict):
        return False, None
    mapping = fed.get("samlAttributeMapping")
    return True, (mapping.get("userNameAttributeName") if isinstance(mapping, dict) else None)


def exact(given: str) -> bool:
    """Whether --user names an account exactly, with no name to resolve: an Entra object id, or the account's id."""
    return bool(OBJECT_ID.match(given)) or given.lower().startswith("urn:vcloud:user:")


def close_now(vcfa: Vcfa, org_name: str, account: str, execute: bool, make_graph=None, announce=None,
              left_on: str | None = None) -> dict:
    """The urgent close: one account of one organization, named exactly, closed now without asking Entra whether the
    person has left (they may still be entitled there, so remove them at the provider too). Plan only unless
    `execute`. Reads the organization's accounts and tokens, and touches the named account's tokens and record only.
    The account is chosen by select_account, and the match is announced before anything is sent; a name that selects
    no account or more than one is refused (exit 5), never guessed, and a read that failed stops the run (exit 3).
    An account that is not federated (providerType LOCAL, or anything but OAUTH or SAML) is refused at the plan, before
    any write (exit 5). Under oid a principal name passes name_guard first, with `left_on`, the departure date the
    leaver notice gives: refused (exit 5) when the Entra user holding the name now was created on or after that date,
    or the account it selects was made on or after it or before that user; unread (exit 3) when a date it needs did
    not read or did not parse. Those dates do not catch an existing person renamed onto the name (B11-S1), so under
    oid a principal name is taken by the plan only: with `execute`, a --user that is not an object id or the account's
    id is refused (exit 5) before it is resolved and before anything is sent, whatever Graph would answer (N2); the
    plan resolves it and prints the object id, which the operator checks against the leaver notice and closes by. The
    key is the one the organization stores, switched on or off (org_key). Under oid, a name Graph answers 404 for that
    an account still carries selects an account named before the key was oid, not the one the person signs in to, so
    the plan refuses it (exit 5), naming that account's id (N2 shape A). Keyed on a name (OIDC on preferred_username,
    SAML on Entra's name claim, read for the protocol of the account the name selects) the name is the account's key,
    so the account it selects is the one every holder of the name signs in to and no other person's account can be
    chosen: no guard runs and no Graph is read. Under any other stored key a name is refused (exit 5), and the
    account's id closes the account. `make_graph` gives the Graph reader, made only when a principal name must be
    resolved under oid."""
    record = {"captured": replay_now().strftime("%Y-%m-%dT%H:%M:%SZ"),
              "mode": "close-now" if execute else "close-now plan", "organizations": [], "unreadable": [],
              "federated_elsewhere": 0, "sent": []}

    def stop(**why: str) -> dict:
        if why.get("unread"):
            record["unreadable"].append({"org": org_name, "reason": why["unread"]})
        if why.get("refused"):
            record["refused"] = why["refused"]
        record["summary"] = summary(record)
        return record

    orgs = vcfa.pages("/cloudapi/1.0.0/orgs")
    if orgs is None:
        return stop(unread="the organization list was refused")
    org = [o for o in orgs if str(o.get("name")) == org_name]
    if len(org) != 1:
        return stop(refused=f"no single organization is named {org_name}")
    urn, named = str(org[0]["id"]), exact(account)
    key = None
    if not named:
        read, key = org_key(vcfa, urn)
        if not read:
            return stop(unread="the organization's OIDC settings were refused, so how it names its accounts is not known")
        if execute and key in BY_ID:  # N2: refused before any name is resolved, whatever Graph would answer
            m = record["user_match"] = {"given": account, "user_key": key, "object_id": None, "accounts": [],
                                        "resolved_by": "not at all: under oid, --execute resolves no name",
                                        "refused": OID_EXECUTE.format(given=account)}
            if announce:
                announce(match_line(m))
            return stop(refused=m["refused"])
    users = vcfa.pages("/cloudapi/1.0.0/users", urn)
    tokens = vcfa.pages("/cloudapi/1.0.0/tokens", urn)
    if users is None or tokens is None:
        return stop(unread="the organization's users or tokens were refused")
    graph = None
    if key in BY_ID and not named and make_graph is not None:
        try:
            graph = make_graph()
        except (urllib.error.URLError, OSError, KeyError, ValueError) as e:
            return stop(unread=f"the Graph credential could not be obtained ({type(e).__name__})")
    m = select_account(users, account, key, graph)
    record["user_match"] = m
    user = next((u for u in users if str(u.get("id")) == m.get("id")), None)
    if user is not None and m.get("object_id"):  # a principal name resolved under oid: the guard reads both dates
        made = account_created(vcfa, str(user.get("id"))) if left_on else {}
        if made:
            m["account_created"] = made.get("at") or (f"before {made['before']}" if made.get("before") else "unread")
        guard = m["guard"] = name_guard(m, made, left_on)
        m["left_on"] = left_on
        if guard.get("refused") or guard.get("unread"):
            m["refused" if guard.get("refused") else "unread"] = guard.get("refused") or guard.get("unread")
        elif key in BY_ID and str(m.get("account") or "").lower() != str(m["object_id"]).lower():
            # re-check A1: the dates pass, yet the object id the name resolves to names no account, and the name selects
            # a legacy account named before the key was oid. Suggesting that account's id closed a dead account and left
            # the leaver's own open, so the plan refuses it (exit 5) and points to the object id the notice carries.
            m["refused"] = RESOLVED_ELSEWHERE.format(given=account, oid=m["object_id"], account=m["account"], id=m["id"])
            m["guard"] = {**guard, "refused": m["refused"]}
    elif user is not None and named:
        m["guard"] = {"ok": True, "why": "named by its object id or its account id: no name was resolved"}
    elif user is not None and key in BY_ID:  # N2 shape A: Graph knows no user by the name, and an account carries it
        m["refused"] = UNHELD_NAME.format(given=account, account=m["account"], id=m["id"])
        m["guard"] = {"refused": m["refused"]}
    elif user is not None and user.get("providerType") in FEDERATED:
        protocol = "OIDC" if user.get("providerType") == "OAUTH" else "SAML"
        read, pkey = (True, key) if protocol == "OIDC" else saml_key(vcfa, urn)
        if not read:
            m["unread"] = "the organization's SAML settings were refused, so how it names its SAML accounts is not known"
        elif pkey in BY_NAME:
            m["guard"] = {"ok": True, "why": f"the organization is not keyed on oid, and names its {protocol} accounts by "
                                             f"{pkey}, a name: the account a name selects is the one every holder of "
                                             "that name signs in to"}
        else:
            m["refused"] = NOT_NAME_KEYED.format(account=m["account"], protocol=protocol, id=m["id"],
                                                 key=pkey or "no key it stores")
            m["guard"] = {"refused": m["refused"]}
    if user is not None and user.get("providerType") not in FEDERATED and not m.get("refused") and not m.get("unread"):
        m["refused"] = (f"account {m['account']} is a {user.get('providerType') or 'unknown'} account: --close-now closes a "
                        "federated account (OAUTH or SAML), and nothing is sent to any other; close a local account in "
                        "the organization's own administration")
    if announce:
        announce(match_line(m))
    if m.get("unread") or m.get("refused"):
        return stop(unread=m.get("unread", ""), refused=m.get("refused", ""))
    mine = [t for t in tokens if (t.get("owner") or {}).get("id") == user.get("id")]
    row = {**keep(user, USER), "tokens": keep(mine, TOKEN), "decision": CLOSED_ON_REQUEST if execute else CLOSE_ON_REQUEST,
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
    record["organizations"].append({"org": org_name, "protocol": user.get("providerType"), "user_key": key,
                                    "close_now": True, "users": [row]})
    record["summary"] = summary(record)
    record["sent"] = [f"{c['method']} {c['path']}" for c in vcfa.calls if c["method"] in ("PUT", "DELETE")]
    return record


def own_credential(vcfa: Vcfa, warn_days: int, now: datetime | None = None, name: str | None = None) -> dict:
    """The run's own credential and when it ends (G-432). A provider bearer lives an hour from its sign-in, so there is
    no end date to read. A provider API token ends on the date its token record gives: the run reads its session's user
    (GET /cloudapi/1.0.0/sessions/current), then the provider's token list (GET /cloudapi/1.0.0/tokens, no tenant
    context, every page), and takes the one REFRESH token that user owns, or the one named `name`
    (VCFA_PROVIDER_TOKEN_NAME) when the user owns several, as during a rotation's overlap or when one administrator
    mints both scheduled jobs' tokens. Inside `warn_days` of its end it is flagged (exit 4: mint the successor and
    rotate); a read that failed, no such token or several (the unread reason then names VCFA_PROVIDER_TOKEN_NAME as the
    fix), or a record with no end date is unread (exit 3), never a pass. The name picks the token judged, not the one
    the run holds, which the reads it makes do not give: change the name with the token file at every rotation.
    {"kind", "name", "ends", "days_left", "warn_days", "flag" or "unread"}."""
    out: dict = {"kind": vcfa.credential, "warn_days": warn_days}
    if vcfa.credential != "provider API token":
        out["ends"] = "an hour after its sign-in: no end date to read"
        return out
    _s, cur = vcfa.call("GET", "/cloudapi/1.0.0/sessions/current", accept=CLOUDAPI)
    me = ((cur or {}).get("user") or {}).get("id") if isinstance(cur, dict) else None
    if not me:
        out["unread"] = f"the run's own session did not read ({vcfa.calls[-1].get('status')}), so its token is not known"
        return out
    listed = vcfa.pages("/cloudapi/1.0.0/tokens")
    if listed is None:
        out["unread"] = f"the provider's token list did not read ({vcfa.calls[-1].get('status')})"
        return out
    mine = [t for t in listed if (t.get("owner") or {}).get("id") == me and t.get("type") == "REFRESH"
            and (name is None or t.get("name") == name)]
    if len(mine) != 1:
        out["unread"] = ((f"{len(mine)} REFRESH tokens belong to the run's user"
                          + ("" if name else ": set VCFA_PROVIDER_TOKEN_NAME to the name this one was minted with"))
                         if mine else ("no REFRESH token of the run's user"
                                       + (f" is named {name}" if name else " is in the provider's token list")))
        return out
    tok = mine[0]
    out["name"], end = tok.get("name"), tok.get("expirationTimeUtc")
    m = re.match(r"(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(?:\.\d+)?(Z|[+-]00:?00)?$", str(end or ""))
    when = datetime.strptime(f"{m.group(1)}T{m.group(2)}", "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc) if m else None
    if when is None:
        out["unread"] = "its token record gives no end date, so when it stops is not known"
        return out
    now = now or replay_now()  # a replayed run judges the end date as the recorded run did
    out["ends"] = when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out["days_left"] = round((when - now).total_seconds() / 86400, 1)
    if out["days_left"] <= warn_days:
        out["flag"] = (f"credential-ends: this run's provider API token ends {out['ends'][:10]}, in {out['days_left']} "
                       f"days, inside WARN_DAYS ({warn_days}): mint its successor, point VCFA_PROVIDER_REFRESH_TOKEN_FILE "
                       "at its file and VCFA_PROVIDER_TOKEN_NAME at its name (the user owns both until the old one "
                       "goes), run once on it, and revoke this one")
    return out


def reconcile(vcfa: Vcfa, graph: Graph, tenant: str, only: list[str], execute: bool, act_on: str | None,
              say=print, max_leavers: int | None = None, name_claims: dict[str, str] | None = None,
              announce=None, expect: list[str] | None = None) -> dict:
    """Report every federated organization's leavers, each open one confirmed over CONFIRM_READS reads before it
    counts; with `execute`, close the confirmed ones of `only` (with `act_on`, the one account it selects, announced
    before anything is sent), unless the organization's open leavers exceed the guard (leaver_guard). With `expect`,
    every tenant a schedule runs for (ids), an organization federated to an Entra tenant outside it, or to this tenant
    in a form the job does not read, is uncovered and unreadable (exit 3); without it, it is counted and not read."""
    others: list[dict] = []
    off: list[dict] = []
    orgs, unreadable, elsewhere = federated_orgs(vcfa, tenant, only, others, off)
    if not orgs and not unreadable:  # a wrong tenant id reads as nothing to do: it is a read that failed (exit 3)
        unreadable.append({"org": None, "reason": f"no organization names this tenant ({elsewhere} federated "
                                                  "elsewhere): check ENTRA_TENANT_ID"})
    record = {"captured": replay_now().strftime("%Y-%m-%dT%H:%M:%SZ"),
              "mode": "execute" if execute else "report", "tenant": tenant, "organizations": [],
              "unreadable": unreadable, "federated_elsewhere": elsewhere, "sent": []}
    if expect is not None:
        record["expected_tenants"] = sorted(expect)
        record["elsewhere"], uncovered = coverage(others, tenant, expect)
        unreadable += uncovered
    record["switched_off"], held = read_switched_off(vcfa, off)
    unreadable += held
    say(f"Leavers · {'EXECUTE' if execute else 'REPORT'} · {len(orgs)} organization(s) federated to the tenant"
        + elsewhere_text(record) + off_text(record))
    for u in unreadable:
        say(f"  {u['org'] or 'the run'}: unreadable ({u['reason']})")
    for line in off_lines(record):
        say(line)
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
        act_ids = None
        if act_on:  # the one account --user names (--execute's, or its plan's under --replay), chosen and announced first
            m = entry["user_match"] = select_account(users, act_on, of.get("key"), graph)
            if announce:
                announce(match_line(m))
            if m.get("unread"):
                record["unreadable"].append({"org": of["org"], "reason": m["unread"]})
            if m.get("refused"):
                record["refused"] = m["refused"]
            if m.get("unread") or m.get("refused"):  # nothing judged, nothing sent: the run stops at the name
                record["user_match"] = entry.pop("user_match")
                break
            act_ids = {m["id"]}
        try:
            gate = read_gate(graph, of, groups)
        except LookupError as e:
            gate, entry["gate_error"] = None, str(e)[:160]
        claim = (name_claims or {}).get(of["org"])
        if gate is not None and claim:
            gate["name_claim"] = entry["name_claim"] = claim
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
        # every open leaver is read again before it counts, in a report as with --execute: Entra's reads disagree for
        # seconds after a change, so one read never raises the alert (exit 1) and never closes an account
        pending = [u for u, r in zip(users, entry["users"], strict=True)
                   if open_leaver(u, r["decision"], mine[u.get("id")])]
        if pending:
            t0 = time.monotonic()
            checked = confirm_all(graph, pending, gate)
            entry["confirm_seconds"] = round(time.monotonic() - t0)
            for user, row in zip(users, entry["users"], strict=True):
                if str(user.get("id")) in checked:
                    ok, reads = checked[str(user.get("id"))]
                    row["confirm_reads"] = reads
                    if not ok:
                        row["decision"], row["reason"] = "undetermined", unconfirmed(reads)
        todo = {}
        for user, row in zip(users, entry["users"], strict=True):
            row["flags"] = flags(user, row["decision"], of.get("key"))
            todo[user.get("id")] = action(user, row["decision"], mine[user.get("id")], execute, act_ids)
        federated = sum(1 for u in users if u.get("providerType") in FEDERATED)
        entry["leaver_guard"] = leaver_guard(sum(1 for t in todo.values() if t and not t.startswith("in step")),
                                             federated, max_leavers)
        for user, row in zip(users, entry["users"], strict=True):
            t = todo[user.get("id")]
            if t == "close" and entry["leaver_guard"]["exceeded"]:
                row["action"] = "refused: " + entry["leaver_guard"]["why"]
            elif t == "close":
                row["action"] = "closed"
                row["result"] = close(vcfa, of["urn"], user, mine[user.get("id")])
            elif t:
                row["action"] = t
            say(f"    {user.get('username')}: {row['decision']} ({row['reason']})"
                + (f" -> {row['action']}" if row.get("action") else "")
                + "".join(f"  FLAG {f.split(':', 1)[0]}" for f in row["flags"]))
        record["organizations"].append(entry)
    if name_claims:  # a declaration naming no organization read is a typo, or an organization federated elsewhere
        record["name_claims"] = {"declared": len(name_claims), "unmatched": len(set(name_claims) - {o["org"] for o in orgs})}
    record["summary"] = summary(record)
    record["sent"] = [f"{c['method']} {c['path']}" for c in vcfa.calls if c["method"] in ("PUT", "DELETE")]
    return record


def parse_name_claims(values: list[str]) -> dict[str, str]:
    """--name-claim ORG=ATTRIBUTE, repeatable: the attribute each named organization's name claim carries, one of the
    attributes the lookups read. Anything else is refused (ValueError), never half read."""
    out: dict[str, str] = {}
    for v in values:
        org, sep, attribute = v.partition("=")
        if not (sep and org.strip() and attribute.strip() in NAME_CLAIMS):
            raise ValueError(f"--name-claim {v!r}: write ORG=ATTRIBUTE, the attribute one of {', '.join(NAME_CLAIMS)}")
        if out.get(org.strip(), attribute.strip()) != attribute.strip():
            raise ValueError(f"--name-claim names {org.strip()!r} twice with different attributes")
        out[org.strip()] = attribute.strip()
    return out


def summary(record: dict) -> dict:
    """The counts a scheduler and a reader act on, by organization and in total."""
    rows = [r for o in record["organizations"] for r in o["users"]]
    is_open = ("would", "refused")  # a leaver counts open only once its reads agree (reconcile)

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
    if "credential" in record:  # a report or --execute reads its own credential's end date (G-432)
        s["credential_unread"] = int(bool(record["credential"].get("unread")))
        s["credential_flagged"] = int(bool(record["credential"].get("flag")))
    if "switched_off" in record:  # a report or --execute lists every organization with its federation switched off
        off = record["switched_off"] or []
        s.update(switched_off=len(off),
                 switched_off_unjudged=sum(1 for o in off if o.get("enabled_federated") != 0
                                          or o.get("federated_tokens") != 0))
    if "expected_tenants" in record:  # only a run given --expect-tenants says who reads the others
        shown = record.get("elsewhere") or []
        s.update(other_tenants=sum(1 for o in shown if o["read_by"] == "the schedule for its own tenant"),
                 other_provider=sum(1 for o in shown if o.get("tenant") is None),
                 uncovered=sum(1 for o in shown if o["read_by"].startswith(UNCOVERED)))
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
# matched without regard to case, and it includes every decision, protocol and type the script prints (G-356). The
# claim namespaces are product vocabulary too: a SAML organization's user key is a claim URI such as
# http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name (or, for Entra's own claims, one under
# schemas.microsoft.com), whose host the host pattern would otherwise take for an estate's and replace, leaving a
# record that no longer says which claim the organization is keyed on.
CLAIM_HOSTS = ("schemas.xmlsoap.org", "schemas.microsoft.com")
PRODUCT = {w.lower() for w in (
    "System", "admin", "administrator", "default", "login.microsoftonline.com", "graph.microsoft.com",
    "sts.windows.net", *CLAIM_HOSTS, "OIDC", "SAML", "OAUTH", "LOCAL", "LDAP", "ApplicationGroup", "SecurityGroup", "All", "None",
    "DirectoryRole", "keep", "leaver", "out of scope", "undetermined", "report", "execute", "Group", "User",
    "Organization Administrator", "Organization Owner", "Organization Member", "Organization User",
    "Organization Auditor", "Project Administrator", "Project User", "Service Broker User", "Catalog Author",
    "Organization Viewer", "Console Access Only", "Defer to Identity Provider", "ProviderConsumptionOrg")}
FIELDS = {"org": "org", "urn": "id", "id": "id", "username": "user", "user": "user", "name": "name", "tenant": "id", "app": "name",
          "given": "user", "account": "user", "accounts": "user", "principal_name": "user", "object_id": "id",
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


def elsewhere_text(record: dict) -> str:
    """The header's account of the organizations federated elsewhere. Without --expect-tenants they are counted and
    not read; with it, each is read by its own tenant's schedule, belongs to another provider, or is uncovered."""
    n = record.get("federated_elsewhere") or 0
    if "expected_tenants" not in record:
        return f", {n} federated elsewhere (not read)" if n else ""
    shown = record.get("elsewhere") or []
    mine = sum(1 for o in shown if o["read_by"] == "the schedule for its own tenant")
    other = sum(1 for o in shown if o.get("tenant") is None)
    loose = sum(1 for o in shown if o["read_by"].startswith(UNCOVERED))
    return (f", {n} federated elsewhere: {mine} to another expected tenant, read by its own schedule; {other} to "
            f"another provider (not read); {loose} uncovered")


def off_text(record: dict) -> str:
    """The header's count of organizations with their federation switched off, when the run read any."""
    n = len(record.get("switched_off") or [])
    return f", {n} with federation switched off" if n else ""


def off_lines(record: dict) -> list[str]:
    """One line for each organization with its federation switched off that holds nothing federated; one that holds
    something, or could not be read, is printed among the unreadable lines with its reason."""
    return [f"  {o['org']}: {SWITCHED_OFF}; no enabled federated account and no API token of one: nothing for this "
            "report to judge" for o in record.get("switched_off") or []
            if o.get("enabled_federated") == 0 and o.get("federated_tokens") == 0]


def report_lines(record: dict) -> list[str]:
    """The run as the lines it prints, from the record alone (so a redacted record prints the same way)."""
    s = record["summary"]
    if record["mode"] == "close-now plan":
        out = ["Leavers · CLOSE-NOW PLAN, nothing sent · one named account, to be closed without asking Entra"]
    elif record["mode"].startswith("close-now"):
        out = [f"Leavers · {record['mode'].upper()} · one named account, closed without asking Entra"]
    else:
        out = [f"Leavers · {record['mode'].upper()} · {s['organizations']} organization(s) federated to the tenant"
               + elsewhere_text(record) + off_text(record)]
    out += [f"  {u['org'] or 'the run'}: unreadable ({u['reason']})" for u in record.get("unreadable") or []]
    out += off_lines(record)
    if record.get("user_match"):
        out.append(match_line(record["user_match"]))
    if record.get("refused"):
        out.append(f"  refused: {record['refused']}")
    for o in record["organizations"]:
        g = o.get("gate")
        if o.get("user_match"):
            out.append(match_line(o["user_match"]))
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
                left = "unread" if rb.get("tokens_left") is None else len(rb["tokens_left"])
                moved = "unread" if rb.get("changed_unasked") is None else len(rb["changed_unasked"])
                out.append(f"      revoked {sum(1 for t in res.get('revoked') or [] if t.get('status') in (200, 204))} of "
                           f"{len(res.get('revoked') or [])} token(s); read back: enabled {rb.get('enabled')}, "
                           f"tokens left {left}, other fields changed {moved}; held {res.get('held')}"
                           + (f" ({res['error']})" if res.get("error") else ""))
                out += finish_lines(o["org"], r)
    cred = record.get("credential")
    if cred:
        out.append(f"  credential: {cred['kind']}"
                   + (f" {cred['name']}" if cred.get("name") else "")
                   + (f": unread ({cred['unread']})" if cred.get("unread")
                      else f", ends {cred['ends']}" + (f" ({cred['days_left']} days; WARN_DAYS {cred['warn_days']})"
                                                         if "days_left" in cred else ""))
                   + ("  FLAG credential-ends" if cred.get("flag") else ""))
    keys = ("keep", "leaver", "out_of_scope", "undetermined", "open_leavers", "refused", "closed", "not_held", "in_step",
            "direct_role", "name_in_use_again", "acknowledged", "flagged")
    out.append("  totals: " + ", ".join(f"{k.replace('_', ' ')} {s.get(k, 0)}" for k in keys))
    if (record.get("acks") or {}).get("unmatched"):
        out.append(f"  acknowledgements matching no flag: {record['acks']['unmatched']} (remove them from the --ack file)")
    if "exit" in record:
        out.append(f"  exit {record['exit']}: {exit_means(record)}")
    return out


EXIT_MEANS = {0: "nothing open, nothing unread, nothing flagged", EXIT_OPEN: "an open leaver: run the close",
              EXIT_HELD_NOT: "a close did not hold on read-back: run the finish line printed under it",
              EXIT_UNREAD: "a read failed, an account is undetermined, or an organization no schedule reads: fix the "
                           "read, nothing is known about it",
              EXIT_FLAGGED: "a flag nobody acknowledged, or this run's own API token near its end: decide and --ack "
                            "the flag; rotate the token, naming its successor in VCFA_PROVIDER_TOKEN_NAME",
              EXIT_USAGE: "not run as asked"}


def exit_means(record: dict) -> str:
    """What the run's exit means, as its last line says it. A --close-now plan that printed exits 0 like a close that
    held, so its line says it is a plan, and how to close: under oid, by the object id the plan resolved (B11-S4)."""
    code = record.get("exit")
    if record.get("mode") == "close-now plan" and code == 0:
        m = record.get("user_match") or {}
        oid = m.get("object_id")
        if oid and str(m.get("account") or "").lower() == str(oid).lower():
            return PLAN_ONLY + f"; to close, run it again with --user {oid} (the object id, never the name) and --execute"
        return PLAN_ONLY + "; to close, run it again with --execute"   # a name selecting another account is refused
    return EXIT_MEANS.get(code, "")


def given_values() -> list[tuple[str, str]]:
    out = [(os.environ.get("VCFA_HOST", ""), "host"), (os.environ.get("ENTRA_TENANT_ID", ""), "id"),
           (os.environ.get("ENTRA_CLIENT_ID", ""), "id")]
    return [(v, k) for v, k in out if v]


def done_text(record: dict, calls: list) -> str:
    """What a run's writes did, in counts and without an estate value, so it can be printed under --redact too: how
    many writes were sent, how many tokens were revoked and accounts disabled, and on how many accounts the close held.
    Empty when nothing was sent."""
    sent = [c for c in calls if c.get("method") in ("PUT", "DELETE", "POST", "PATCH") and c.get("plane") != "graph"]
    if not sent:
        return ""
    results = [r["result"] for o in record.get("organizations") or [] for r in o.get("users") or [] if r.get("result")]
    revoked = sum(1 for r in results for t in r.get("revoked") or [] if t.get("status") in (200, 204))
    disabled = sum(1 for r in results if r.get("disabled"))
    held = sum(1 for r in results if r.get("held"))
    return (f"the run sent {len(sent)} write(s): {revoked} token(s) revoked and {disabled} account(s) disabled, and the "
            f"close held on {held} of the {len(results)} account(s) it closed")


def _write(record: dict, calls: list, redact: bool) -> int:
    """Print the run, scrub the record and write it; refuse to write one in which an estate value survived. A run
    refused as a usage error (a --user that names no account, or several) is printed and not written. A record refused
    for a surviving value never masks what the run found: the run's code stands when it is 1, 2 or 4 (or 3), and a
    run whose code was 0 exits 3, because the record a later tool reads was not written (G-456). A run that wrote
    says what its writes did (done_text), counts only, whether or not the report itself was printed: a close that held
    is never reported as a run that found nothing."""
    record["calls"] = [{k: v for k, v in c.items() if k != "message"} for c in calls]
    if REPLAY is not None:  # a replayed run's record never passes for a live one: a reader refuses it as no run
        record = {"replay": True, **record}
    table = estate_values(record, given_values())
    clean = scrub(record, table)
    left = leaks(clean, table)
    out = os.environ.get("OUT") or ("leavers.replay.json" if REPLAY is not None else "leavers.json")
    if not (left and redact):  # a redacted print with a surviving value would print that value
        print("\n".join(report_lines(clean if redact else record)))
        for c in calls:
            if c["status"] is None or c["status"] >= 400 or c.get("shape"):
                where = scrub(c["path"], table) if redact else c["path"]
                print(f"  FAILED {c['plane']} {c['method']} {where}: {c['status'] or c.get('error') or ''}"
                      + (f" ({c['shape']})" if c.get("shape") else "") + ("" if redact else f" {c.get('message') or ''}"))
    if record.get("refused"):
        print(f"\nnot run as asked; {out} not written; exit {EXIT_USAGE}")
        return EXIT_USAGE
    if left:
        code = record["exit"] if record.get("exit") in (EXIT_OPEN, EXIT_HELD_NOT, EXIT_FLAGGED, EXIT_UNREAD) else EXIT_UNREAD
        done = done_text(record, calls)
        if code == record.get("exit"):
            why = "the run's own code stands"
        elif done:
            why = "the close held, and the record a later tool reads was not written"
        else:
            why = "the run found nothing to act on, and the record a later tool reads was not written"
        print(f"refusing to write {out}: {len(left)} estate value(s) survived the scrub ({', '.join(sorted(set(left)))}); "
              + (f"{done}; {out} not written; " if done else "") + f"exit {code}: {why}", file=sys.stderr)
        return code
    with open(out, "w", encoding="utf-8") as f:
        f.write(json.dumps(clean, indent=1, ensure_ascii=False) + "\n")
    failed = sum(1 for c in calls if c["status"] is None or c["status"] >= 400 or c.get("shape"))
    print(f"\n{len(calls)} call(s), {failed} refused; "
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
    _plan_alone(a)
    calls: list = []
    try:
        vcfa = Vcfa(os.environ["VCFA_HOST"], calls)
    except (urllib.error.URLError, OSError, KeyError, ValueError) as e:
        return _no_credential(e)
    graph_set = all(os.environ.get(k) for k in ("ENTRA_TENANT_ID", "ENTRA_CLIENT_ID"))
    record = close_now(vcfa, a.org, a.user, a.execute, make_graph=(lambda: Graph(calls)) if graph_set else None,
                       announce=_announcer(a.redact), left_on=a.left_on)
    record["exit"] = EXIT_USAGE if record.get("refused") else exit_code(record["summary"], a.execute)
    return _write(record, calls, a.redact)


def _announcer(redact: bool):
    """How the --user match is printed before anything is sent: in full, or under --redact without its values (the
    report printed at the end carries them as placeholders)."""
    if not redact:
        return lambda line: print(line, flush=True)

    def say(line: str) -> None:
        if ": refused (" in line or ": unread (" in line:
            print(f"  --user: {'refused' if ': refused (' in line else 'unread'} (see the report below)", flush=True)
        else:
            print("  --user: matched (values withheld under --redact; the report below names them as placeholders)",
                  flush=True)
    return say


def _iso_day(value: str) -> str:
    """A date given as YYYY-MM-DD, as written; anything else is refused (argparse's error, exit 5)."""
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not a date written YYYY-MM-DD") from None


class _Parser(argparse.ArgumentParser):
    """argparse exits 2 on a usage error, the code this script gives a close that did not hold; it exits 5 here."""

    def __init__(self, *args, **kwargs):  # an abbreviation never parses as a whole flag name
        kwargs.setdefault("allow_abbrev", False)
        super().__init__(*args, **kwargs)

    def error(self, message: str):
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        raise SystemExit(EXIT_USAGE)


def main(argv: list[str] | None = None) -> int:
    """The run, with two guards around it: a Python older than 3.10 is refused (exit 5) before anything is read, and an
    error the script did not expect exits 3, the code for a read that failed, never 1, the code for an open leaver."""
    if sys.version_info < (3, 10):  # noqa: UP036  the script is run by readers on their own Python
        print("leavers.py needs Python 3.10 or later", file=sys.stderr)
        return EXIT_USAGE
    try:
        return _run(argv)
    except Exception as e:  # the last guard: whatever was not expected is not known, so exit 3
        print(f"the run stopped on an error it did not expect: {type(e).__name__}: {str(e)[:160]}; nothing is known "
              "about what it had not read (exit 3)", file=sys.stderr)
        return EXIT_UNREAD
    finally:
        replay_stop()


def build_parser() -> _Parser:
    """The command line, built in one place so a test can parse every command the script suggests (G-463)."""
    ap = _Parser(description="Report, and on request close, VCF Automation accounts of people who have left at "
                             "Entra ID.")
    ap.add_argument("--execute", action="store_true", help="close the confirmed leavers of the organization --org names")
    ap.add_argument("--org", help="the one organization --execute acts on")
    ap.add_argument("--user", metavar="ACCOUNT",
                    help="with --execute or --close-now, the one account to act on: its user name, a principal name "
                         "(resolved to the object id under oid), or its id (every account is still read)")
    ap.add_argument("--redact", action="store_true", help="print with placeholders instead of your names")
    ap.add_argument("--ack", metavar="FILE", help="acknowledged flags: a JSON list of {org, account, flag, until}")
    ap.add_argument("--max-leavers", type=int, metavar="N",
                    help=f"with --execute, refuse an organization with more than N open leavers (default: more than "
                         f"{MAX_LEAVERS} and more than a quarter of its federated accounts)")
    ap.add_argument("--name-claim", action="append", default=[], metavar="ORG=ATTRIBUTE",
                    help="the attribute an organization's name claim carries (userPrincipalName, mail or otherMails), "
                         "which the job cannot read for itself; repeatable. Undeclared means userPrincipalName")
    ap.add_argument("--close-now", action="store_true",
                    help="close the one account --user names in --org now, without asking Entra; plan only without --execute")
    ap.add_argument("--left-on", metavar="YYYY-MM-DD", type=_iso_day,
                    help="with --close-now, the departure date the leaver notice gives: under oid the plan takes a "
                         "principal name only with it, and refuses the name when the Entra user holding it now, or the "
                         "account it selects, was made on or after it; --execute under oid takes the object id only")
    ap.add_argument("--expect-tenants", metavar="T1,T2,...",
                    help="every Entra tenant a schedule of this job runs for (ids or domain names, this run's own "
                         "among them): an organization federated to any other is uncovered, and the run exits 3")
    ap.add_argument("--replay", metavar="DIR",
                    help="answer every request from the recorded set in DIR (replay/leavers beside this script is "
                         "one): nothing is sent and no credential is read")
    return ap


def _plan_alone(a: argparse.Namespace) -> bool:
    """Under --replay a writing mode runs its plan alone: --execute is turned off before anything is read, so a
    replayed run sends no write and never says a close happened. True when it was turned off."""
    if REPLAY is None or not a.execute:
        return False
    print("replay: --execute runs its plan alone under --replay; nothing is sent", file=sys.stderr)
    a.execute = False
    return True


def _run(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    if a.replay:
        try:
            replay_start(a.replay)
        except (OSError, ValueError) as e:
            print(f"--replay {a.replay}: {e}; nothing was sent", file=sys.stderr)
            return EXIT_USAGE
    if a.left_on and not a.close_now:
        print("--left-on is for --close-now: it guards a principal name under oid", file=sys.stderr)
        return EXIT_USAGE
    if a.close_now and a.expect_tenants:
        print("--expect-tenants is for a report or --execute: --close-now reads one named account, not the tenants",
              file=sys.stderr)
        return EXIT_USAGE
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
    try:
        name_claims = parse_name_claims(a.name_claim)
        expect_given = parse_expect_tenants(a.expect_tenants) if a.expect_tenants is not None else None
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return EXIT_USAGE
    missing = [k for k in ("VCFA_HOST", "ENTRA_TENANT_ID", "ENTRA_CLIENT_ID") if not os.environ.get(k)]
    if missing:
        print(f"set {', '.join(missing)} (see the header)", file=sys.stderr)
        return EXIT_USAGE
    warn = os.environ.get("WARN_DAYS", str(WARN_DAYS)).strip()
    if not warn.isdigit():
        print(f"WARN_DAYS {warn!r}: a whole number of days, 0 or more", file=sys.stderr)
        return EXIT_USAGE
    planned = _plan_alone(a)
    calls: list = []
    try:
        vcfa, graph = Vcfa(os.environ["VCFA_HOST"], calls), Graph(calls)
    except (urllib.error.URLError, OSError, KeyError, ValueError) as e:
        return _no_credential(e)
    tenant, why = resolve_tenant(os.environ["ENTRA_TENANT_ID"], graph)
    if tenant is None:  # nothing can be matched to a tenant that is not known: a read that failed, nothing written
        print(f"the tenant could not be resolved: {why}", file=sys.stderr)
        return EXIT_UNREAD
    expect = None
    if expect_given is not None:
        expect, why, usage = resolve_expected(expect_given, tenant, os.environ["ENTRA_TENANT_ID"], calls)
        if expect is None:  # a name Entra knows as no tenant is a bad argument (5); a read that failed is 3
            print(why, file=sys.stderr)
            return EXIT_USAGE if usage else EXIT_UNREAD
        if tenant not in expect:
            print("--expect-tenants does not name this run's own tenant (ENTRA_TENANT_ID): pass the full list, the "
                  "same on every schedule", file=sys.stderr)
            return EXIT_USAGE
    only = [a.org] if a.org else [o.strip() for o in os.environ.get("ORGS", "").split(",") if o.strip()]
    record = reconcile(vcfa, graph, tenant, only, a.execute, a.user, say=lambda _m: None, max_leavers=a.max_leavers,
                       name_claims=name_claims, announce=_announcer(a.redact), expect=expect)
    if a.ack:
        apply_acks(record, acks, record["captured"][:10])  # the run's own UTC date
    if not record.get("refused"):  # the run's own credential: when a provider API token ends (G-432)
        record["credential"] = own_credential(vcfa, int(warn), name=os.environ.get("VCFA_PROVIDER_TOKEN_NAME") or None)
    record["summary"] = summary(record)
    record["exit"] = EXIT_USAGE if record.get("refused") else exit_code(record["summary"], a.execute)
    if planned:  # --execute's plan under --replay: what it would close, nothing sent
        record["mode"] = "execute plan"
    return _write(record, calls, a.redact)


if __name__ == "__main__":
    sys.exit(main())
