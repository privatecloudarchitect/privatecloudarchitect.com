#!/usr/bin/env python3
"""org_federation.py - give a VCF Automation organization its own identity provider: planned, built, checked and
torn down, with Microsoft Entra ID as the provider.

A tenant whose people sign in with their own Entra ID accounts gets an organization that trusts Entra directly,
over OIDC or SAML. Two gates admit a user: assignment required on the Entra app, and a narrow group imported into
the organization with a role. This script does both sides in the order that works:

  plan (default)         prints every body it would send, the tenant's Entra checklist, the provider's organization
                         checklist and the proof checklist, each with its owner; changes nothing
  --execute              builds a throwaway organization, an Entra app and one entitlement group, wires them, imports
                         the group with the member-level role the organization type holds; written to re-run over its
                         own build, though a re-run over a finished build was not exercised on the reference estate
  --prove                reads both sides back and checks each setting the build depends on, then prints the
                         browser steps that prove it (a sign-in is a browser protocol; this script does not drive one)
  --prove --org NAME     an existing organization, built by anyone, proven read-only with no state file: its settings
                         read back against the plan for the protocol it is federated over, its type and its user key;
                         every imported group holding roles of its own role list (and each --group ROLE=NAME the role
                         its type defines); an enabled local user holding its top role; over SAML, every enabled SAML
                         user's stored email an address rather than its NameID, the state in which a round trip of the
                         user's record was refused (the round trip itself is a write, which it never sends; with no
                         enabled SAML user yet that check is not run, and the run exits 3 until one has signed in). Never touches Entra beyond its
                         public discovery and keys endpoints, and needs no Graph app, so whether each imported group is
                         assigned to the app at Entra is left to the federation watch's group_names check
  --configure --org NAME the provider's side of an existing organization, from what the tenant's administrator handed
                         over: APP_CLIENT_ID and APP_SECRET_FILE over OIDC (the secret it holds is kept when the app is
                         the one it holds), METADATA_FILE over SAML. Prints the plan, each changing field's old and new
                         value; with --execute it writes the settings as a round trip (only when a field differs),
                         imports each --group ROLE=NAME with the role its organization type defines, resolved from the
                         organization's own role list, and reads every write back. The OIDC user key defaults to the one
                         the organization holds (oid when it holds none). It refuses to switch an organization's
                         protocol, OIDC user key or SAML user-name claim under the users it holds, judged on what it
                         stores, enabled or not (a federation switched off still holds its key, its mapping, its metadata
                         and its users); a named group that already exists under the other protocol or with other roles;
                         and a new client secret Entra does not accept, asked at Entra's token endpoint before anything is
                         written. A federation that is switched off stays off: a settings write to it needs --enable,
                         which the plan shows as "enabled: off -> on", and without it only the named groups are imported.
                         Over SAML without METADATA_FILE it prints the organization's own service-provider identifier
                         and reply URL for the tenant, and stops. It never writes to Entra
  --teardown --execute   deletes what --execute created (only that), purges it from Entra's recycle bin, and reads
                         each object back to confirm nothing is left
  --update               day 2 on an existing organization federated to the tenant (it need not be one this script
                         built): reads its settings, changes only the fields named by --key-refresh [HOURS] (automatic
                         refresh on, strategy ADD, every HOURS, default 1), --keys (the keys the provider publishes now,
                         the write after an emergency roll), --secret (the client secret in NEW_SECRET_FILE, which the
                         tenant's administrator rotated) or --metadata (the SAML metadata in METADATA_FILE), and prints
                         the plan; with --execute it writes the whole body back, with the secret the organization holds
                         or the new one, and reads every changed field back; when the organization already holds what
                         was asked it writes nothing and says "nothing to change". It never writes to Entra: a new
                         secret is first proven at Entra's token endpoint, and one Entra refuses is not written.

Writes `federation.json`: the steps, their HTTP statuses, the waits Entra imposed, the setting names stored on
read-back and any refusal verbatim. Every value from your estate (host, organization, tenant, users, ids) is replaced
by a placeholder, and the script refuses to write a record in which one survived. No secret or token is printed or
written: the OIDC client secret is minted, handed to VCF Automation and dropped, and a settings read deletes the
secret VCF Automation returns before anything else sees the response.

Safety: --execute refuses an organization, app or group name that already exists unless this script created it (its
state file says so), and --teardown deletes only objects that state file records. The state file holds object ids,
not secrets; keep it beside the record and do not publish it. A real tenant's organization is proven with --prove
--org and configured with --configure --org, which write nothing to Entra and delete nothing anywhere.

Env:  VCFA_HOST; VCFA_PROVIDER_BEARER_FILE (a provider bearer, minted as platform-identity's plate 04, "Your provider
      bearer", shows) or VCFA_PROVIDER_REFRESH_TOKEN_FILE (a provider api-token); the bearer wins when both are set, since
      every write here was run on one; TLS_VERIFY=false on a self-signed lab CA; ENTRA_TENANT_ID; ENTRA_CLIENT_ID and either
      ENTRA_CLIENT_SECRET_FILE or ENTRA_CERT_FILE + ENTRA_KEY_FILE (the certificate form needs the `cryptography`
      package); ORG (the throwaway organization's name); ENTITLED_UPN and UNENTITLED_UPN (your test users);
      APP_NAME (the Entra app it makes, default vcfa-<ORG>); GROUP_NAME (the entitled group it makes, default
      vcfa-<ORG>-users); SECRET_DAYS (OIDC secret life, default 180); OUT (default federation.json); STATE (default
      org_federation.<ORG>.state.json). --update needs VCFA_HOST, the provider credential, ENTRA_TENANT_ID and ORG
      (the existing organization), NEW_SECRET_FILE for --secret, METADATA_FILE for --metadata; it writes OUT
      (default update.json). --prove --org and --configure --org need VCFA_HOST, the provider credential and
      ENTRA_TENANT_ID; --configure also APP_CLIENT_ID and, for a new app, APP_SECRET_FILE (OIDC) or METADATA_FILE
      (SAML); they write OUT (default prove.json, configure.json)
Exit: 0 done · 1 a check failed, or a write refused while building, configuring, updating or tearing down · 2 refused
      by what it read (a name this script did not create; no state file to tear down; for --update, an organization not
      federated to ENTRA_TENANT_ID or a change its protocol does not take; for --org, no such organization, a protocol,
      key or SAML user-name claim switch judged on what the organization stores and the users it holds, enabled or not,
      a settings write to a switched-off federation without --enable, a role its type lacks, a named group held another
      way, or SAML with no metadata yet, when it prints what the tenant needs; for --configure and --update, a client
      secret Entra refused), with nothing sent · 3 a result not known: a credential refused before anything was read, a
      read refused or a list not read whole in any mode (a proof only reads), Entra out of reach when asked about a
      secret, a check with nothing to read yet (--prove --org over SAML before any enabled SAML user has signed in), a
      record the scrub refused to write, or an error it did not expect (never 1) · 5 not run as asked: an unknown,
      missing or malformed argument (--enable without --configure among them), a missing environment variable
      or a file that cannot be read, metadata that is not the tenant's, SECRET_DAYS of a year or more, or a Python
      older than 3.9. Nothing is sent on a 5.
"""

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
from datetime import datetime, timedelta, timezone

# The identity companions' shared exit contract: 3 is a result not known (never a finding), 5 is not run as asked.
EXIT_DONE, EXIT_FAILED, EXIT_REFUSED, EXIT_UNREAD, EXIT_USAGE = 0, 1, 2, 3, 5


class UsageError(Exception):
    """Not run as asked: a missing or malformed argument, environment variable or file. Exit 5, nothing sent."""


class ScrubError(Exception):
    """The record would carry an estate value, so it is not written. Exit 3: the run is not on record."""

CLOUDAPI = "application/json;version=9.1.0"
PAGE_SIZE = 128  # a cloudapi list is read page by page to its pageCount, so a list longer than one page is read whole
GROUPS_ACCEPT = "application/json;version=10.0.0.0-alpha"  # the version the live group import answered on 9.1
VCD_JSON = "application/*+json;version=9.1.0"
OAUTH_SETTINGS = "application/vnd.vmware.admin.organizationOAuthSettings+json;version=9.1.0"
FEDERATION_SETTINGS = "application/vnd.vmware.admin.organizationFederationSettings+json;version=9.1.0"
SAML_METADATA = "application/samlmetadata+xml"
AUTHORITY = "https://login.microsoftonline.com"
GRAPH = "https://graph.microsoft.com/v1.0"
GRAPH_BETA = "https://graph.microsoft.com/beta"
GRAPH_APP_ID = "00000003-0000-0000-c000-000000000000"  # Microsoft Graph, the same in every tenant
CUSTOM_TEMPLATE = "8adf8e6e-67b2-4cf2-a259-e3dc5476c621"  # the Custom (non-gallery) enterprise app template
DEFAULT_ACCESS_ROLE = "00000000-0000-0000-0000-000000000000"
CLAIMS = "http://schemas.xmlsoap.org/ws/2005/05/identity/claims"
SAML_GROUPS_CLAIM = "http://schemas.microsoft.com/ws/2008/06/identity/claims/groups"

# Role names by organization type, read from /cloudapi/1.0.0/roles in a new organization of each type on VCF
# Automation 9.1. A classic organization has no organization-level auditor and names its top role Organization
# Owner; an All Apps organization names its member role Organization User.
ROLES = {
    "classic": {"member": "Organization Member", "auditor": None, "administrator": "Organization Owner"},
    "all-apps": {
        "member": "Organization User",
        "auditor": "Organization Auditor",
        "administrator": "Organization Administrator",
    },
}

ENTRA_SAML_MAPPING = {  # Entra's SAML claim types, as the organization maps them to its user fields
    "emailAttributeName": f"{CLAIMS}/emailaddress",
    "userNameAttributeName": f"{CLAIMS}/name",
    "firstNameAttributeName": f"{CLAIMS}/givenname",
    "surnameAttributeName": f"{CLAIMS}/surname",
    "groupAttributeName": SAML_GROUPS_CLAIM,
}
SAML_USER_NAME_CLAIM = ENTRA_SAML_MAPPING["userNameAttributeName"]   # the claim a returning SAML user is matched on


# ── what each side is sent: pure functions, no network ──────────────────────────────────────────────────────────
def entra_oidc_app(name, redirect_uri):
    """The Entra app registration: the organization's redirect, and a groups claim that carries only groups assigned
    to the app, by display name (cloud-only groups), which is the name the organization imports."""
    return {
        "displayName": name,
        "signInAudience": "AzureADMyOrg",
        "web": {"redirectUris": [redirect_uri]},
        "groupMembershipClaims": "ApplicationGroup",
        "optionalClaims": {
            "idToken": [
                {"name": "email", "essential": False},
                {"name": "given_name", "essential": False},
                {"name": "family_name", "essential": False},
                {"name": "preferred_username", "essential": False},
                {"name": "groups", "essential": False, "additionalProperties": ["cloud_displayname"]},
            ]
        },
    }


def entra_saml_app(entity_id, acs_url):
    """The application half of the SAML enterprise app: the organization's entity id and assertion consumer, and the
    same assigned-groups-by-name claim in the SAML token."""
    return {
        "identifierUris": [entity_id],
        "web": {"redirectUris": [acs_url]},
        "groupMembershipClaims": "ApplicationGroup",
        "optionalClaims": {
            "saml2Token": [{"name": "groups", "essential": False, "additionalProperties": ["cloud_displayname"]}]
        },
    }


def entra_saml_email_claim():
    """The service principal's claims policy (Graph beta, PUT .../claimsPolicy): an emailaddress claim from the
    user's mail. Without it VCF Automation stores the NameID as the user's email and refuses later updates of the
    user, so it goes on before anyone signs in."""
    return {
        "@odata.type": "#microsoft.graph.customClaimsPolicy",
        "includeBasicClaimSet": True,
        "claims": [
            {
                "@odata.type": "#microsoft.graph.customClaim",
                "name": "emailaddress",
                "namespace": CLAIMS,
                "tokenFormat": ["saml"],
                "configurations": [
                    {
                        "@odata.type": "#microsoft.graph.customClaimConfiguration",
                        "attribute": {
                            "@odata.type": "#microsoft.graph.sourcedAttribute",
                            "id": "mail",
                            "source": "user",
                            "isExtensionAttribute": False,
                        },
                    }
                ],
            }
        ],
    }


def oidc_settings(current, discovery, keys, client_id, client_secret, subject_claim):
    """The organization's OIDC settings: the GET body with the named fields replaced, so a field this script does
    not know is carried through. PKCE stays off (an Entra web app's code exchange fails with it on); the secret goes
    on every write (VCF Automation refuses a write without it); keys refresh every hour and are added, not replaced,
    so a key Entra rolls is held from the next scheduled refresh: a refresh waits a full interval after the last
    success and runs on the hour, so at most the interval plus an hour after it."""
    body = {k: v for k, v in current.items() if k not in ("link", "href", "type", "clientSecret")}
    body.update(
        {
            "enabled": True,
            "issuerId": discovery["issuer"],
            "clientId": client_id,
            "clientSecret": client_secret,
            "userAuthorizationEndpoint": discovery["authorization_endpoint"],
            "accessTokenEndpoint": discovery["token_endpoint"],
            "userInfoEndpoint": discovery.get("userinfo_endpoint"),
            "jwksUri": discovery["jwks_uri"],
            "endSessionEndpoint": discovery.get("end_session_endpoint"),
            "scope": ["openid", "profile", "email"],
            "maxClockSkew": 60,
            "enableIdTokenClaims": True,
            "usePKCE": False,
            "sendClientCredentialsAsAuthorizationHeader": False,
            "autoRefreshKey": True,
            "keyRefreshStrategy": "ADD",
            "keyRefreshFrequencyInHours": 1,
            "keyExpireDurationInHours": 24,
            "oAuthKeyConfigurations": {"oAuthKeyConfiguration": keys},
        }
    )
    mapping = {k: v for k, v in (current.get("oidcAttributeMapping") or {}).items() if k not in ("link", "href", "type")}
    mapping.update(
        {
            "subjectAttributeName": subject_claim,
            "emailAttributeName": "email",
            "fullNameAttributeName": "name",
            "firstNameAttributeName": "given_name",
            "lastNameAttributeName": "family_name",
            "groupsAttributeName": "groups",
        }
    )
    body["oidcAttributeMapping"] = mapping
    return body


def saml_settings(current, idp_metadata, button, mapping=ENTRA_SAML_MAPPING):
    """The organization's SAML settings: the GET body with the provider's metadata, the attribute mapping and the
    sign-in button replaced. VCF Automation refuses a button label over 24 characters."""
    if len(button) > 24:
        raise ValueError(f"button label {button!r} is over VCF Automation's 24 characters")
    body = {k: v for k, v in current.items() if k not in ("link", "href", "type")}
    mapped = {k: v for k, v in (current.get("samlAttributeMapping") or {}).items() if k not in ("link", "href", "type")}
    mapped.update(mapping)
    body.update({"enabled": True, "samlMetadata": idp_metadata, "samlAttributeMapping": mapped, "customUiButtonLabel": button})
    return body


def group_import(group_name, provider_type, role_ref):
    """The import of one provider group with one organization role (POST /cloudapi/1.0.0/groups, the organization
    in the tenant-context header). The name is the group's display name at the provider, exactly."""
    return {
        "name": group_name,
        "providerType": provider_type,
        "description": "imported from the identity provider with its role",
        "roleEntityRefs": [role_ref],
    }


# Who sets what. On a real tenant two administrators build a federation: the tenant's identity administrator owns the
# app on Entra ID, its claims, credentials and groups; the provider administrator owns the organization. Every part of
# the plan names its owner, so the plan is also the hand-off.
TENANT_ADMIN = "the tenant's identity administrator, on Entra ID"
PROVIDER_ADMIN = "you, the provider administrator, in the organization"
BOTH = "both: the tenant's administrator makes the test users, and you run the sign-ins and keep the record"
READ_ONLY_PERMISSIONS = {  # Microsoft Graph application permissions, measured by narrowing on the lab tenant (X-143)
    "watch.py": ["Application.Read.All"],
    "leavers.py": ["Application.Read.All", "User.Read.All", "GroupMember.Read.All"],
}
# The name an account is known by stays the user principal name: the organization names each account by it, and the
# leaver job (identity-lifecycle's leavers.py) asks Entra for the person behind an account by that name, as a
# userPrincipalName first, then as a mail address, then among otherMails, so a name claim sourced from an attribute
# none of the three holds would read every entitled account as nobody Entra knows. Entra sends the principal name in
# both by default (Microsoft's SAML claims customization page; the reference runs read the SAML name claim equal to the
# principal name). Microsoft treats that name as one that can change and be reused, not a lasting key, which is why the
# protocol rule turns on whether a name ever comes back.
NAME_CLAIM_SAML = (f"The name claim ({CLAIMS}/name) left sourced from user.userprincipalname, Entra's default, because the "
                   "organization names each account by it and the leaver job looks each account up by it first")
NAME_CLAIM_OIDC = ("preferred_username left as Entra sends it, the user principal name, with no claims mapping over it, "
                   "because the organization names each account by it and the leaver job looks each account up by it first")


def entra_checklist(protocol, org_type, user_key):
    """What the tenant's identity administrator sets on Entra ID before the first sign-in, for this protocol. The
    organization type and user key are the provider's settings and appear in organization_checklist()."""
    out = [
        "One app for this organization, with assignment required on its service principal",
        "One cloud-only security group per organization role, assigned to the app; users as direct members, "
        "because a member only through a nested group is refused at Entra (a group synchronized from on-premises AD "
        "was not measured)",
        "The groups claim limited to groups assigned to the app (ApplicationGroup), carrying display names "
        "(cloud_displayname), so the claim holds the name the organization imports",
        "Conditional Access MFA on the app, with any exemption group kept apart from the entitlement group",
    ]
    if protocol == "oidc":
        out += [
            "A web redirect URI of https://<automation-host>/login/oauth?service=tenant:<org>",
            "Admin consent for openid profile email, so no user is asked to consent",
            "A client secret that ends in under 12 months, handed to the provider for the organization's settings, its end "
            "date tracked, rotated with overlap",
        ]
        if user_key == "preferred_username":
            out.append(NAME_CLAIM_OIDC)
    else:
        out += [
            "An enterprise app from the Custom template, single sign-on mode SAML, identifier and reply URL taken from "
            "the organization's own service-provider metadata, which the provider fetches and sends once the organization "
            "exists",
            "An emailaddress claim from the user's mail, added before any user signs in",
            NAME_CLAIM_SAML,
            "The signing certificate's expiry notices sent to a monitored mailbox",
        ]
    watch, leavers = READ_ONLY_PERMISSIONS["watch.py"], READ_ONLY_PERMISSIONS["leavers.py"]
    out.append(
        "A read-only app registration for the provider, consented in this directory with the Microsoft Graph application "
        f"permission {' and '.join(watch)} for the watch, and {', '.join(leavers[:-1])} and {leavers[-1]} for the leaver "
        "job; none of them grants a write"
    )
    return out


# Over SAML the tenant's app is built from the organization's own service-provider metadata, so the provider's first
# step comes before the tenant's: the order _sp_metadata() follows on --execute, retrying while a new organization's
# metadata answers 500.
SP_METADATA_STEP = ("First, once the organization reads back, its own service-provider metadata fetched from the link in "
                    "its federation settings, retried while a new organization still answers 500 in its first seconds, and "
                    "sent to the tenant's administrator, whose app takes its identifier and reply URL from it")


def organization_checklist(protocol, org_type, user_key):
    """What the provider administrator sets in the organization, for this protocol, organization type and user key."""
    role = ROLES[org_type]["member"]
    out = []
    if protocol == "oidc":
        out += [
            "The settings written as a round trip with the app's client id and secret from the tenant's administrator, "
            "signing keys refreshed hourly with strategy ADD, and PKCE off",
            f"Users keyed on {user_key}, agreed with the tenant's administrator before the first sign-in"
            + (": a renamed user keeps the same account, and usernames read as object ids" if user_key == "oid"
               else ": readable usernames, chosen only where a person's name never comes back. A renamed user gets a second "
                    "account, so plan a rename as a leaver and a joiner; and a departed person's name given to someone new "
                    "reaches the departed person's account with its direct roles, so delete that account before the name "
                    "returns, or key on oid"),
        ]
    else:
        out += [
            SP_METADATA_STEP,
            "The settings written as a round trip with the app's federation metadata from the tenant's administrator",
        ]
    out += [
        f"Each Entra group imported into the organization with its role, the member-level group with {role}, the "
        "member-level role this organization type holds",
        "The organization's local administrator kept, vaulted and drilled: it signs in when Entra refuses the app",
    ]
    return out


def proof_checklist(protocol):
    """How the build is proven: in a browser, with test users made for the purpose."""
    out = [
        "An entitled test user signs in through a browser and holds its group's role",
        "A test user in no assigned group is refused at Entra with AADSTS50105",
        "After any settings change, several sign-ins spread over minutes",
    ]
    if protocol == "saml":
        out.insert(2, "The new user's stored email is its address, and a round-trip update of its record succeeds")
    return out


TENANT = "{{tenant-id}}"
DISCOVERY_SHAPE = {  # Entra's v2.0 discovery fields the settings use, with the tenant left as a placeholder
    "issuer": f"{AUTHORITY}/{TENANT}/v2.0",
    "authorization_endpoint": f"{AUTHORITY}/{TENANT}/oauth2/v2.0/authorize",
    "token_endpoint": f"{AUTHORITY}/{TENANT}/oauth2/v2.0/token",
    "userinfo_endpoint": "https://graph.microsoft.com/oidc/userinfo",
    "jwks_uri": f"{AUTHORITY}/{TENANT}/discovery/v2.0/keys",
    "end_session_endpoint": f"{AUTHORITY}/{TENANT}/oauth2/v2.0/logout",
}


def plan(protocol, org_type, user_key="oid"):
    """Everything both sides are sent for one protocol, organization type and user key, with placeholders where your
    values go, and who sets each part (owners): what an in-page builder embeds, so a page cannot assemble a body this
    script would not send. The settings fields are exactly those the round trip changes; every other field of the
    organization's settings is carried through as read. The Entra app bodies are entra_oidc_app(), entra_saml_app()
    and entra_saml_email_claim()."""
    if protocol == "oidc":
        keys = [{"keyId": "{{key-id}}", "algorithm": "RSA", "key": "{{public-key-pem}}"}]
        fields = oidc_settings({}, DISCOVERY_SHAPE, keys, "{{client-id}}", "{{client-secret}}", user_key)
        path, provider_type = "/api/admin/org/{id}/settings/oauth", "OAUTH"
    else:
        fields = saml_settings({}, "{{idp-metadata}}", "Sign in with Entra ID")
        path, provider_type = "/api/admin/org/{id}/settings/federation", "SAML"
    return {
        "protocol": protocol,
        "org_type": org_type,
        "user_key": user_key if protocol == "oidc" else None,
        "entra": entra_checklist(protocol, org_type, user_key),
        "organization": organization_checklist(protocol, org_type, user_key),
        "settings": {"method": "PUT", "path": path, "fields": fields},
        "group_import": {
            "method": "POST",
            "path": "/cloudapi/1.0.0/groups",
            "headers": {"X-VMWARE-VCLOUD-TENANT-CONTEXT": "{{org-id}}"},
            "body": group_import("{{group}}", provider_type, {"id": "{{role-id}}", "name": "{{role}}"}),
        },
        "roles": dict(ROLES[org_type]),
        "proof": proof_checklist(protocol),
        "owners": {"entra": TENANT_ADMIN, "organization": PROVIDER_ADMIN, "settings": PROVIDER_ADMIN,
                   "group_import": PROVIDER_ADMIN, "proof": BOTH},
    }


# ── a signing key from a JWKS, as the PEM public key VCF Automation stores (stdlib only) ──────────────────────
def _tlv(buf, i):
    """One DER element at i: (tag, content start, content end)."""
    tag, ln = buf[i], buf[i + 1]
    i += 2
    if ln & 0x80:
        n = ln & 0x7F
        ln = int.from_bytes(buf[i : i + n], "big")
        i += n
    return tag, i, i + ln


def spki_pem(cert_der):
    """The certificate's SubjectPublicKeyInfo as a PEM public key: walk the DER past the version, serial,
    signature algorithm, issuer, validity and subject, and wrap the next element."""
    _, start, _ = _tlv(cert_der, 0)
    _, i, _ = _tlv(cert_der, start)  # tbsCertificate's content
    tag, _, end = _tlv(cert_der, i)
    if tag == 0xA0:  # [0] version, present on v3 certificates
        i = end
    for _ in range(5):  # serialNumber, signature, issuer, validity, subject
        _, _, i = _tlv(cert_der, i)
    _, _, end = _tlv(cert_der, i)
    b64 = base64.b64encode(cert_der[i:end]).decode()
    return "-----BEGIN PUBLIC KEY-----\n" + "\n".join(b64[k : k + 64] for k in range(0, len(b64), 64)) + "\n-----END PUBLIC KEY-----\n"


def jwks_keys(jwks):
    """The provider's RSA signing keys in the form the organization's settings take."""
    return [
        {"keyId": k["kid"], "algorithm": "RSA", "key": spki_pem(base64.b64decode(k["x5c"][0]))}
        for k in jwks.get("keys", [])
        if k.get("kty") == "RSA" and k.get("x5c")
    ]


# ── the record contract: estate values out, refuse a record that keeps one ─────────────────────────────────────
UUID_RX = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
IPV4_RX = re.compile(r"(?<![\d.])\d{1,3}(?:\.\d{1,3}){3}(?![\d.])")


class Scrubber:
    """Replaces each registered estate value with its placeholder in one longest-first pass, then any remaining
    uuid with {{id}}, and refuses text in which a registered value or an address survived. Product vocabulary
    (role names, AADSTS codes, Microsoft endpoints, claim names) is never registered."""

    def __init__(self):
        self.values = {}

    def add(self, value, placeholder):
        if value and len(str(value)) >= 3:
            self.values[str(value)] = placeholder

    def scrub(self, text):
        if self.values:
            rx = re.compile("|".join(re.escape(v) for v in sorted(self.values, key=len, reverse=True)), re.I)
            lower = {k.lower(): p for k, p in self.values.items()}
            text = rx.sub(lambda m: lower[m.group(0).lower()], text)
        return UUID_RX.sub("{{id}}", text)

    def check(self, text):
        left = [v for v in self.values if v.lower() in text.lower()]
        left += IPV4_RX.findall(text)
        if left:
            raise ScrubError(f"refusing to write the record: {len(left)} estate value(s) survived the scrub")


# ── HTTP, standard library only ────────────────────────────────────────────────────────────────────────────────
def _ctx():
    verify = os.environ.get("TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")
    return ssl.create_default_context() if verify else ssl._create_unverified_context()


def _send(method, url, headers, data=None, ctx=None):
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=90) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def _parse(raw):
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return raw.decode(errors="replace")


class CallError(RuntimeError):
    pass


class ReadError(CallError):
    """A read that did not answer whole: a refused GET, a list not read to its end, or Entra out of reach when asked
    whether it accepts a secret. What it would have read is not known, so exit 3: never 1, the code for a write the
    platform refused, and never a pass."""


MAX_PAGES = 10000


def whole_list(fetch, what):
    """Every item of a VCF Automation cloudapi list, read page by page (fetch(page), pages counted from 1) until the
    count of distinct items, by id, equals the total the answer states (resultTotal). A list is read whole or not at
    all: an answer without its list or without a stated total, a page that comes back empty or short before the total
    is reached, pages that end (pageCount) short of it, or a total that changes between pages, is a list not read
    (ReadError, exit 3), never a short or an empty one."""
    seen, out, total, size = set(), [], None, None
    for page in range(1, MAX_PAGES + 1):
        data = fetch(page)
        if not isinstance(data, dict) or not isinstance(data.get("values"), list):
            raise ReadError(f"{what}: page {page} answered without its list")
        stated = data.get("resultTotal")
        if isinstance(stated, bool) or not isinstance(stated, int):
            raise ReadError(f"{what}: page {page} states no total, so a short list could not be told from a whole one")
        if total is None:
            total = stated
        elif stated != total:
            raise ReadError(f"{what}: the stated total moved from {total} to {stated} between pages")
        rows = data["values"]
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
    raise ReadError(f"{what}: more than {MAX_PAGES} pages")


def _read_file(var):
    path = os.environ.get(var)
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError as e:   # a variable that names no readable file is a usage error, not a failed read
        raise UsageError(f"{var} names a file that cannot be read ({type(e).__name__})") from None


class Vcfa:
    """The provider side of VCF Automation, as a provider System Administrator."""

    def __init__(self, host):
        self.host, self.ctx = host, _ctx()
        # The bearer wins when both are set: every write here was run on a provider bearer, and in the identity-lifecycle
        # companion a provider API token's bearer was refused an account write that a provider bearer carried.
        bearer = _read_file("VCFA_PROVIDER_BEARER_FILE")
        if bearer:
            self.bearer, self.kind = bearer.removeprefix("Bearer ").strip(), "provider bearer"
            return
        refresh = _read_file("VCFA_PROVIDER_REFRESH_TOKEN_FILE")
        if not refresh:
            raise UsageError("set VCFA_PROVIDER_BEARER_FILE or VCFA_PROVIDER_REFRESH_TOKEN_FILE")
        form = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": refresh}).encode()
        st, _, raw = _send("POST", f"https://{host}/oauth/provider/token",
                           {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}, form, self.ctx)
        if st != 200:
            raise CallError(f"the provider token exchange answered {st}")
        self.bearer, self.kind = json.loads(raw)["access_token"], "provider API token"

    def call(self, method, path, body=None, accept=CLOUDAPI, ctype=None, tenant=None, params=None):
        url = path if path.startswith("https://") else f"https://{self.host}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        h = {"Authorization": f"Bearer {self.bearer}", "Accept": accept}
        if tenant:
            h["X-VMWARE-VCLOUD-TENANT-CONTEXT"] = tenant
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = ctype or "application/json"
        st, hdrs, raw = _send(method, url, h, data, self.ctx)
        return st, _parse(raw), hdrs

    def ok(self, method, path, step, **kw):
        """The call, or CallError when the platform refuses it: ReadError for a refused GET, a read that did not happen
        (exit 3), and CallError for a refused write (exit 1)."""
        st, data, hdrs = self.call(method, path, **kw)
        if st >= 400:
            msg = data.get("message") if isinstance(data, dict) else str(data)[:240]
            raise (ReadError if method == "GET" else CallError)(f"{step}: HTTP {st}: {str(msg)[:300]}")
        return st, data, hdrs

    def wait_task(self, href, timeout=300):
        path = "/" + href.split("://", 1)[-1].split("/", 1)[-1]
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            _, task, _ = self.ok("GET", path, "read task", accept=VCD_JSON)
            if task.get("status") == "success":
                return
            if task.get("status") in ("error", "aborted", "canceled"):
                raise CallError(f"task {task.get('operationName')} ended {task.get('status')}")
            time.sleep(3)
        raise CallError("a task did not finish in time")

    def org(self, name):
        _, data, _ = self.ok("GET", "/cloudapi/1.0.0/orgs", "find organization", params={"filter": f"name=={name}", "pageSize": 10})
        rows = data.get("values", [])
        return rows[0] if rows else None

    def settings(self, uuid_, kind):
        """GET the organization's oauth or federation settings; the client secret is deleted on arrival."""
        _, data, _ = self.ok("GET", f"/api/admin/org/{uuid_}/settings/{kind}", f"read {kind} settings", accept=VCD_JSON)
        data.pop("clientSecret", None)
        return data

    def settings_for_write(self, uuid_, kind):
        """GET the settings for a round trip: the body and the client secret apart, the secret kept only in memory
        for the write that needs it (VCF Automation refuses an OIDC settings write without it)."""
        _, data, _ = self.ok("GET", f"/api/admin/org/{uuid_}/settings/{kind}", f"read {kind} settings", accept=VCD_JSON)
        secret = data.pop("clientSecret", None)
        return data, secret

    def pages(self, path, step, tenant=None, accept=CLOUDAPI):
        """Every item of a cloudapi list, read whole (whole_list): a page refused midway, a 200 without its list, or
        pages that end short of the stated total raise ReadError, never a short list."""
        def fetch(page):
            return self.ok("GET", path, step, accept=accept, tenant=tenant, params={"page": page, "pageSize": PAGE_SIZE})[1]
        return whole_list(fetch, step)

    def role(self, org_urn, name):
        _, data, _ = self.ok("GET", "/cloudapi/1.0.0/roles", "find role", tenant=org_urn, params={"filter": f"name=={name}", "pageSize": 10})
        rows = data.get("values", [])
        return {"id": rows[0]["id"], "name": rows[0]["name"]} if rows else None

    def role_names(self, org_urn):
        return sorted(r["name"] for r in self.pages("/cloudapi/1.0.0/roles", "list roles", org_urn))


class Graph:
    """Microsoft Graph as an app (client credentials), with a retry while Entra settles: a just-made object can be
    briefly unknown (404) or busy (409), and a service principal made right after its app can be refused (400)."""

    TRANSIENT = ("Request_ResourceNotFound", "Directory_ConcurrencyViolation", "Directory_ObjectNotFound",
                 "does not reference a valid application object")

    def __init__(self, tenant, client_id):
        self.tenant, self.client_id, self.ctx, self.status = tenant, client_id, ssl.create_default_context(), None
        self.token = self._mint()

    def _mint(self):
        form = {"client_id": self.client_id, "scope": "https://graph.microsoft.com/.default", "grant_type": "client_credentials"}
        secret = _read_file("ENTRA_CLIENT_SECRET_FILE")
        if secret:
            form["client_secret"] = secret
        else:
            form["client_assertion_type"] = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
            form["client_assertion"] = self._assertion()
        st, _, raw = _send("POST", f"{AUTHORITY}/{self.tenant}/oauth2/v2.0/token",
                           {"Content-Type": "application/x-www-form-urlencoded"}, urllib.parse.urlencode(form).encode(), self.ctx)
        if st != 200:
            err = _parse(raw) or {}
            raise CallError(f"Entra token endpoint answered {st} ({err.get('error') if isinstance(err, dict) else ''})")
        return json.loads(raw)["access_token"]

    def _assertion(self):
        from cryptography.hazmat.primitives import hashes, serialization  # only the certificate form needs it
        from cryptography.hazmat.primitives.asymmetric import padding

        with open(os.environ["ENTRA_CERT_FILE"], "rb") as f:
            pem = f.read()
        with open(os.environ["ENTRA_KEY_FILE"], "rb") as f:
            key = serialization.load_pem_private_key(f.read(), password=None)
        der = base64.b64decode(b"".join(line for line in pem.splitlines() if not line.startswith(b"-----")))
        b64u = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()  # noqa: E731
        now = int(time.time())
        head = {"alg": "PS256", "typ": "JWT", "x5t#S256": b64u(hashlib.sha256(der).digest())}
        claims = {"aud": f"{AUTHORITY}/{self.tenant}/oauth2/v2.0/token", "iss": self.client_id, "sub": self.client_id,
                  "jti": str(uuid.uuid4()), "nbf": now, "iat": now, "exp": now + 600}
        signing = b64u(json.dumps(head, separators=(",", ":")).encode()) + "." + b64u(json.dumps(claims, separators=(",", ":")).encode())
        sig = key.sign(signing.encode(), padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH), hashes.SHA256())
        return signing + "." + b64u(sig)

    def call(self, method, path, body=None):
        url = path if path.startswith("https://") else f"{GRAPH}{path}"
        for attempt in range(6):
            h = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
            data = None
            if body is not None:
                data, h["Content-Type"] = json.dumps(body).encode(), "application/json"
            st, hdrs, raw = _send(method, url, h, data, self.ctx)
            if st == 401 and attempt == 0:
                self.token = self._mint()
                continue
            if st == 429:
                time.sleep(min(60.0, float(hdrs.get("Retry-After") or 10)))
                continue
            return st, _parse(raw)
        return st, _parse(raw)

    def req(self, method, path, body=None, settle_s=90):
        deadline = time.monotonic() + settle_s
        while True:
            st, data = self.call(method, path, body)
            self.status = st
            if st < 400:
                return data or {}
            err = (data or {}).get("error", {}) if isinstance(data, dict) else {}
            detail = f"{err.get('code')}: {str(err.get('message', ''))[:240]}"
            if not any(t in detail for t in self.TRANSIENT) or time.monotonic() > deadline:
                raise (ReadError if method == "GET" else CallError)(
                    f"Graph {method} {path.split('?')[0].replace(GRAPH, '')} answered {st} ({detail})")
            time.sleep(5)

    def values(self, path):
        """Every item of a Graph list, following @odata.nextLink until it is absent. A 200 without its `value` list is
        a list not read (ReadError, exit 3), never an empty one."""
        out, url = [], path
        for _ in range(MAX_PAGES):
            data = self.req("GET", url)
            if not isinstance(data, dict) or not isinstance(data.get("value"), list):
                raise ReadError(f"Graph GET {path.split('?')[0]}: a page answered without its list")
            out += data["value"]
            url = data.get("@odata.nextLink")
            if not url:
                return out
        raise ReadError(f"Graph GET {path.split('?')[0]}: more than {MAX_PAGES} pages")

    def one(self, collection, filt, select="id,displayName"):
        q = urllib.parse.urlencode({"$filter": filt, "$select": select})
        rows = self.values(f"{collection}?{q}")
        if len(rows) > 1:
            raise CallError(f"{len(rows)} objects match in {collection}")
        return rows[0] if rows else None

    def exists(self, path):
        st, _ = self.call("GET", path)
        return st == 200


# A client secret is proven before it is written anywhere: Entra is asked for a client-credentials token with it, the
# one check short of a sign-in, and the token is dropped unread. Entra refused a secret it had just added, for seconds,
# with the same code as a wrong one (AADSTS7000215), so that code is asked again for a while; a value shaped like a GUID
# is a Secret ID pasted where the Value belongs, and is refused at once.
SECRET_SETTLE_S = 120
SECRET_ID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def secret_refusal(tenant, client_id, secret, settle_s=SECRET_SETTLE_S):
    """Why Entra refuses `secret` for the app `client_id` in `tenant`, or "" once it accepts it. Raises ReadError
    when Entra cannot be asked (exit 3): a secret Entra never confirmed is not written."""
    secret_id = bool(SECRET_ID.match(secret.strip()))
    form = urllib.parse.urlencode({"client_id": client_id, "client_secret": secret, "grant_type": "client_credentials",
                                   "scope": "https://graph.microsoft.com/.default"}).encode()
    start = time.monotonic()
    while True:
        try:
            st, _, raw = _send("POST", f"{AUTHORITY}/{tenant}/oauth2/v2.0/token",
                               {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
                               form, ssl.create_default_context())
        except (urllib.error.URLError, OSError) as e:
            raise ReadError(f"Entra's token endpoint could not be asked whether it accepts the secret ({type(e).__name__})") from None
        if st == 200:
            del raw   # a token minted only to prove the secret: never read, never kept
            return ""
        err = _parse(raw)
        codes = [c for c in ((err.get("error_codes") if isinstance(err, dict) else None) or []) if isinstance(c, int)]
        if st >= 500 or not codes:
            raise ReadError(f"Entra's token endpoint answered {st} without a refusal code, so the secret is not confirmed")
        if 7000215 in codes and not secret_id and time.monotonic() - start < settle_s:
            time.sleep(10)
            continue
        named = ", ".join(f"AADSTS{c}" for c in codes)
        if secret_id and 7000215 in codes:
            return (f"Entra refused it ({named}), and it is shaped like a Secret ID, a GUID, not the secret's Value: ask "
                    "the tenant's administrator for the Value, which Entra shows once, when the secret is added")
        return f"Entra refused it ({named})" + (f", after {round(time.monotonic() - start)} s of asking again"
                                               if 7000215 in codes and settle_s else "")


def _settled(read, want, wait_s=90):
    """True once read() returns want, re-reading every 10 s for up to wait_s."""
    deadline = time.monotonic() + wait_s
    while True:
        if read() == want:
            return True
        if time.monotonic() > deadline:
            return False
        time.sleep(10)


# ── the run ─────────────────────────────────────────────────────────────────────────────────────────────────────
class Run:
    def __init__(self, args):
        self.args, self.steps, self.t0 = args, [], time.monotonic()
        self.host, self.org_name = os.environ["VCFA_HOST"], os.environ["ORG"]
        self.tenant, self.client = os.environ["ENTRA_TENANT_ID"], os.environ["ENTRA_CLIENT_ID"]
        self.app_name = os.environ.get("APP_NAME", f"vcfa-{self.org_name}")
        self.group_name = os.environ.get("GROUP_NAME", f"vcfa-{self.org_name}-users")
        self.state_path = os.environ.get("STATE", f"org_federation.{self.org_name}.state.json")
        self.state = json.load(open(self.state_path, encoding="utf-8")) if os.path.exists(self.state_path) else {}
        self.san = Scrubber()
        for v, p in ((self.host, "{{host}}"), (self.org_name, "{{org}}"), (self.app_name, "{{app-name}}"),
                     (self.group_name, "{{group}}"), (self.tenant, "{{tenant-id}}"), (self.client, "{{automation-app}}")):
            self.san.add(v, p)
        for var, p in (("ENTITLED_UPN", "{{entitled-user}}"), ("UNENTITLED_UPN", "{{unentitled-user}}")):
            upn = os.environ.get(var)
            if upn:
                self.san.add(upn, p)
                self.san.add(upn.split("@", 1)[1], "{{tenant-domain}}")
                self.san.add(upn.split("@", 1)[0], p.replace("}}", "-name}}"))
        for k, p in (("app_id", "{{client-id}}"), ("app_object_id", "{{app-object-id}}"), ("sp_id", "{{sp-id}}"),
                     ("group_id", "{{group-id}}"), ("org_uuid", "{{org-uuid}}"),
                     ("signing_thumbprint", "{{thumbprint}}")):
            self.san.add(self.state.get(k), p)

    def step(self, name, status, **facts):
        self.steps.append({"step": name, "status": status, "at_s": round(time.monotonic() - self.t0, 1), **facts})
        print(f"  {name}: {status}" + (f"  {facts}" if facts else ""), flush=True)

    def save_state(self):
        with open(self.state_path, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=1)
        os.chmod(self.state_path, 0o600)
        for k, p in (("app_id", "{{client-id}}"), ("app_object_id", "{{app-object-id}}"), ("sp_id", "{{sp-id}}"),
                     ("group_id", "{{group-id}}"), ("org_uuid", "{{org-uuid}}"),
                     ("signing_thumbprint", "{{thumbprint}}")):
            self.san.add(self.state.get(k), p)

    def mine(self, kind, found_id):
        """An existing object is used only when this script created it; anything else is refused."""
        if found_id and self.state.get(f"{kind}_created") != found_id:
            print(f"refused: a {kind} with this name exists and this script did not create it; choose another ORG")
            sys.exit(2)

    # ── build ──────────────────────────────────────────────────────────────────────────────────────────
    def build(self, vcfa, g):
        a = self.args
        roles = ROLES[a.org_type]
        org = vcfa.org(self.org_name)
        self.mine("org", org and org["id"])
        if org is None:
            st, _, hdrs = vcfa.ok("POST", "/cloudapi/1.0.0/orgs", "create organization",
                                  body={"name": self.org_name, "displayName": self.org_name, "isEnabled": True,
                                        "isClassicTenant": a.org_type == "classic", "description": "throwaway, org_federation.py"})
            if st == 202 and hdrs.get("Location"):
                vcfa.wait_task(hdrs["Location"])
            org = vcfa.org(self.org_name)
            self.state.update(org_created=org["id"], org_urn=org["id"], org_uuid=org["id"].rsplit(":", 1)[-1])
            self.save_state()
            self.step("organization created", st, classic=a.org_type == "classic")
        else:
            self.step("organization exists (created by this script)", "done")
        urn, uid = org["id"], org["id"].rsplit(":", 1)[-1]
        names = vcfa.role_names(urn)
        missing = [r for r in roles.values() if r and r not in names]
        self.step("organization roles read", "done", count=len(names), expected_present=not missing)
        if missing:
            raise CallError(f"the organization lacks the roles {missing}; ROLES does not match this build")

        group = g.one("/groups", f"displayName eq '{self.group_name}'")
        self.mine("group", group and group["id"])
        if group is None:
            group = g.req("POST", "/groups", {"displayName": self.group_name, "description": "entitled to sign in to the organization",
                                              "mailEnabled": False, "mailNickname": re.sub(r"[^A-Za-z0-9-]", "-", self.group_name),
                                              "securityEnabled": True})
            self.state.update(group_created=group["id"], group_id=group["id"])
            self.save_state()
            self.step("entitlement group created", g.status)

        if a.protocol == "oidc":
            app, sp, secret = self._entra_oidc(g)
        else:
            entity_id, acs = self._sp_metadata(vcfa, uid)
            app, sp = self._entra_saml(g, entity_id, acs)
        self._assign_only(g, sp["id"], group["id"])
        self._members(g, group["id"])

        if a.protocol == "oidc":
            disc_url = f"{AUTHORITY}/{self.tenant}/v2.0/.well-known/openid-configuration"
            disc_raw = json.loads(_send("GET", disc_url, {"Accept": "application/json"}, None, ssl.create_default_context())[2])
            keys = jwks_keys(json.loads(_send("GET", disc_raw["jwks_uri"], {"Accept": "application/json"}, None, ssl.create_default_context())[2]))
            self.step("Entra discovery and signing keys read", "done", keys=len(keys))
            body = oidc_settings(vcfa.settings(uid, "oauth"), disc_raw, keys, app["appId"], secret, a.user_key)
            put_st, _, _ = vcfa.ok("PUT", f"/api/admin/org/{uid}/settings/oauth", "write OIDC settings", body=body, accept=VCD_JSON, ctype=OAUTH_SETTINGS)
            del secret, body
            back = vcfa.settings(uid, "oauth")
            stored = {k: back.get(k) for k in ("enabled", "usePKCE", "autoRefreshKey", "keyRefreshStrategy",
                                                 "keyRefreshFrequencyInHours", "keyExpireDurationInHours", "enableIdTokenClaims")}
            stored["subjectAttributeName"] = (back.get("oidcAttributeMapping") or {}).get("subjectAttributeName")
            stored["signing_keys"] = len(((back.get("oAuthKeyConfigurations") or {}).get("oAuthKeyConfiguration")) or [])
            self.step("OIDC settings written and read back", put_st, stored=stored)
            provider_type = "OAUTH"
        else:
            meta = self._metadata(g, app["appId"], sp["id"])
            put_st, _, _ = vcfa.ok("PUT", f"/api/admin/org/{uid}/settings/federation", "write SAML settings",
                    body=saml_settings(vcfa.settings(uid, "federation"), meta, "Sign in with Entra ID"),
                    accept=VCD_JSON, ctype=FEDERATION_SETTINGS)
            back = vcfa.settings(uid, "federation")
            stored = {"enabled": back.get("enabled"),
                      "mapping": sorted(k for k, v in (back.get("samlAttributeMapping") or {}).items() if k.endswith("AttributeName") and v)}
            self.step("SAML settings written and read back", put_st, stored=stored)
            provider_type = "SAML"

        _, rows, _ = vcfa.ok("GET", "/cloudapi/1.0.0/groups", "find imported group", accept=GROUPS_ACCEPT, tenant=urn,
                             params={"filter": f"name=={self.group_name}", "pageSize": 10})
        if rows.get("values"):
            self.step("group already imported", "done")
        else:
            role_ref = vcfa.role(urn, roles["member"])
            st, made, _ = vcfa.ok("POST", "/cloudapi/1.0.0/groups", "import group", accept=GROUPS_ACCEPT, tenant=urn,
                                  body=group_import(self.group_name, provider_type, role_ref))
            self.step("group imported with its role", st, role=roles["member"], providerType=made.get("providerType"))

    def _entra_oidc(self, g):
        redirect = f"https://{self.host}/login/oauth?service=tenant:{self.org_name}"
        app = g.one("/applications", f"displayName eq '{self.app_name}'", "id,appId,displayName")
        self.mine("app", app and app["id"])
        if app is None:
            app = g.req("POST", "/applications", entra_oidc_app(self.app_name, redirect))
            self.state.update(app_created=app["id"], app_object_id=app["id"], app_id=app["appId"])
            self.save_state()
            self.step("Entra app registered", g.status)
        sp = g.one("/servicePrincipals", f"appId eq '{app['appId']}'", "id,appId")
        if sp is None:
            sp = g.req("POST", "/servicePrincipals", {"appId": app["appId"], "appRoleAssignmentRequired": True})
            self.step("service principal created, assignment required", g.status)
        self.state.update(sp_id=sp["id"])
        self.save_state()
        graph_sp = g.one("/servicePrincipals", f"appId eq '{GRAPH_APP_ID}'", "id")
        q = urllib.parse.urlencode({"$filter": f"clientId eq '{sp['id']}' and consentType eq 'AllPrincipals'"})
        if [r for r in g.values(f"/oauth2PermissionGrants?{q}") if r.get("resourceId") == graph_sp["id"]]:
            self.step("admin consent for openid profile email already granted", g.status)
        else:
            g.req("POST", "/oauth2PermissionGrants", {"clientId": sp["id"], "consentType": "AllPrincipals",
                                                      "resourceId": graph_sp["id"], "scope": "email openid profile"})
            self.step("admin consent for openid profile email", g.status)
        days = int(os.environ.get("SECRET_DAYS", "180"))
        if days >= 365:
            raise UsageError("SECRET_DAYS must be under a year")
        cur = g.req("GET", f"/applications/{app['id']}?$select=passwordCredentials")
        for cred in cur.get("passwordCredentials") or []:
            if cred.get("displayName") == "vcf-automation":
                g.req("POST", f"/applications/{app['id']}/removePassword", {"keyId": cred["keyId"]})
        end = (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        secret = g.req("POST", f"/applications/{app['id']}/addPassword",
                       {"passwordCredential": {"displayName": "vcf-automation", "endDateTime": end}})["secretText"]
        live = self._secret_live(app["appId"], secret)
        self.step("client secret added, and accepted by Entra", "done", days=days, live_after_s=live)
        return app, sp, secret

    def _secret_live(self, app_id, secret):
        """A new secret is refused (AADSTS7000215) until Entra propagates it; wait, so it is never handed on dead."""
        start = time.monotonic()
        why = secret_refusal(self.tenant, app_id, secret, settle_s=300)
        if why:
            raise CallError(f"the new client secret was refused: {why}")
        return round(time.monotonic() - start)

    def _sp_metadata(self, vcfa, uid):
        fed = vcfa.settings(uid, "federation")
        href = next((ln["href"] for ln in fed.get("link") or [] if ln.get("type") == SAML_METADATA), None)
        if href is None:
            raise CallError("the organization's federation settings carry no SAML metadata link")
        # A new organization's metadata can answer 500 (a redirect page to /login/loginFailure) for its first seconds:
        # the login service has not taken the organization yet. Read until it answers.
        start = time.monotonic()
        while True:
            st, xml, _ = vcfa.call("GET", "/" + href.split("://", 1)[-1].split("/", 1)[-1], accept=SAML_METADATA)
            if st == 200 and isinstance(xml, str) and "entityID" in xml:
                break
            if time.monotonic() - start > 180:
                raise CallError(f"read SP metadata: HTTP {st} for 180 s")
            time.sleep(5)
        entity = re.search(r'entityID="([^"]+)"', xml)
        acs = re.search(r'AssertionConsumerService[^>]*Binding="urn:oasis:names:tc:SAML:2\.0:bindings:HTTP-POST"[^>]*Location="([^"]+)"', xml)
        if not entity or not acs:
            raise CallError("the organization's SAML metadata names no entity id or HTTP-POST consumer")
        self.san.add(entity.group(1), "{{sp-entity-id}}")
        self.san.add(acs.group(1), "{{sp-assertion-consumer-url}}")
        self.step("organization's service-provider metadata read", st, after_s=round(time.monotonic() - start))
        return entity.group(1), acs.group(1)

    def _entra_saml(self, g, entity_id, acs):
        app = g.one("/applications", f"displayName eq '{self.app_name}'", "id,appId,displayName")
        self.mine("app", app and app["id"])
        if app is None:
            made = g.req("POST", f"/applicationTemplates/{CUSTOM_TEMPLATE}/instantiate", {"displayName": self.app_name})
            app, sp = made["application"], made["servicePrincipal"]
            self.state.update(app_created=app["id"], app_object_id=app["id"], app_id=app["appId"], sp_id=sp["id"])
            self.save_state()
            self.step("enterprise app created from the Custom template", g.status)
        sp = {"id": self.state["sp_id"]}
        g.req("PATCH", f"/servicePrincipals/{sp['id']}", {"preferredSingleSignOnMode": "saml", "appRoleAssignmentRequired": True})
        g.req("PATCH", f"/applications/{app['id']}", entra_saml_app(entity_id, acs))
        self.step("single sign-on SAML, identifier and reply URL set, assignment required", g.status)
        cur = g.req("GET", f"/servicePrincipals/{sp['id']}?$select=preferredTokenSigningKeyThumbprint")
        if not cur.get("preferredTokenSigningKeyThumbprint"):
            end = (datetime.now(timezone.utc) + timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%SZ")
            cert = g.req("POST", f"/servicePrincipals/{sp['id']}/addTokenSigningCertificate",
                         {"displayName": f"CN={self.app_name}", "endDateTime": end})
            g.req("PATCH", f"/servicePrincipals/{sp['id']}", {"preferredTokenSigningKeyThumbprint": cert["thumbprint"]})
            self.state["signing_thumbprint"] = cert["thumbprint"]
            self.save_state()
            self.step("signing certificate added and made preferred", g.status)
        else:
            self.state["signing_thumbprint"] = cur["preferredTokenSigningKeyThumbprint"]
            self.save_state()
        start = time.monotonic()
        g.req("PUT", f"{GRAPH_BETA}/servicePrincipals/{sp['id']}/claimsPolicy", entra_saml_email_claim())
        policy = g.req("GET", f"{GRAPH_BETA}/servicePrincipals/{sp['id']}/claimsPolicy")
        names = sorted(c.get("name") for c in policy.get("claims") or [])
        self.step("email claim set before any sign-in, read back", g.status, claims=names, seconds=round(time.monotonic() - start))
        return app, sp

    def _metadata(self, g, app_id, sp_id):
        """Entra's app-specific metadata, once it names the app's preferred signing certificate."""
        # the thumbprint comes from the step that set it: a read seconds after the write can still answer null
        thumb = self.state.get("signing_thumbprint")
        url = f"{AUTHORITY}/{self.tenant}/federationmetadata/2007-06/federationmetadata.xml?appid={app_id}"
        start = time.monotonic()
        while True:
            st, _, raw = _send("GET", url, {"Accept": "application/xml"}, None, ssl.create_default_context())
            text = raw.decode(errors="replace")
            certs = re.findall(r"<X509Certificate>([^<]+)</X509Certificate>", text)
            if st == 200 and any(hashlib.sha1(base64.b64decode(c)).hexdigest().upper() == thumb.upper() for c in certs):
                self.step("Entra's metadata names the signing certificate", 200, after_s=round(time.monotonic() - start))
                return text
            if time.monotonic() - start > 300:
                raise CallError(f"Entra's app metadata did not name the signing certificate (HTTP {st})")
            time.sleep(10)

    def _assign_only(self, g, sp_id, group_id):
        sp = g.req("GET", f"/servicePrincipals/{sp_id}?$select=appRoles")
        roles = [r for r in sp.get("appRoles") or [] if r.get("isEnabled") and "User" in (r.get("allowedMemberTypes") or [])]
        role_id = str(([r for r in roles if r.get("displayName") == "User"] or roles)[0]["id"]) if roles else DEFAULT_ACCESS_ROLE
        have = g.values(f"/servicePrincipals/{sp_id}/appRoleAssignedTo")
        if group_id not in {x.get("principalId") for x in have}:
            g.req("POST", f"/servicePrincipals/{sp_id}/appRoleAssignedTo", {"principalId": group_id, "resourceId": sp_id, "appRoleId": role_id})
        removed = 0
        for x in have:
            if x.get("principalId") != group_id:
                g.req("DELETE", f"/servicePrincipals/{sp_id}/appRoleAssignedTo/{x['id']}")
                removed += 1
        self.step("entitlement group is the app's only assignment", "done", others_removed=removed)

    def _members(self, g, group_id):
        upn = os.environ.get("ENTITLED_UPN")
        if not upn:
            return
        user = g.one("/users", f"userPrincipalName eq '{upn}'", "id")
        members = {m["id"] for m in g.values(f"/groups/{group_id}/members?$select=id")}
        if user["id"] not in members:
            g.req("POST", f"/groups/{group_id}/members/$ref", {"@odata.id": f"{GRAPH}/directoryObjects/{user['id']}"})
            self.step("entitled test user added as a direct member of the group", g.status)
        else:
            self.step("entitled test user already a direct member of the group", "done")

    # ── prove ──────────────────────────────────────────────────────────────────────────────────────────
    def prove(self, vcfa, g):
        """Reads both sides back; a failed check names the setting. The sign-in itself is a browser's to make."""
        a, checks = self.args, {}
        org = vcfa.org(self.org_name)
        checks["organization exists and is enabled"] = bool(org and org.get("isEnabled"))
        sp_id, group_id = self.state.get("sp_id"), self.state.get("group_id")
        if not (sp_id and group_id):
            self.step("nothing to prove", "this script holds no finished build under this name: run --execute again, or "
                      "--teardown --execute; for an organization it did not build, run --prove --org NAME")
            return False
        sp = g.req("GET", f"/servicePrincipals/{sp_id}?$select=appRoleAssignmentRequired")
        checks["assignment required on the app"] = sp.get("appRoleAssignmentRequired") is True
        # Entra's list reads lag a write by seconds, so each read is repeated for up to 90 s before it counts as a FAIL
        checks["the entitlement group is the only assignment"] = _settled(
            lambda: [x.get("principalId") for x in g.values(f"/servicePrincipals/{sp_id}/appRoleAssignedTo")],
            [group_id])
        for var, want in (("ENTITLED_UPN", True), ("UNENTITLED_UPN", False)):
            if os.environ.get(var):
                u = g.one("/users", f"userPrincipalName eq '{os.environ[var]}'", "id")
                checks[f"the {'entitled' if want else 'unentitled'} user is {'' if want else 'not '}in the group"] = _settled(
                    lambda u=u: u["id"] in {m["id"] for m in g.values(f"/groups/{group_id}/members?$select=id")},
                    want)
        uid = org["id"].rsplit(":", 1)[-1] if org else None
        if a.protocol == "oidc" and uid:
            s = vcfa.settings(uid, "oauth")
            checks["OIDC enabled"] = s.get("enabled") is True
            checks["PKCE off"] = s.get("usePKCE") is False
            checks["keys refresh every hour, added"] = (s.get("autoRefreshKey"), s.get("keyRefreshStrategy"), s.get("keyRefreshFrequencyInHours")) == (True, "ADD", 1)
            checks[f"users keyed on {a.user_key}"] = (s.get("oidcAttributeMapping") or {}).get("subjectAttributeName") == a.user_key
            checks["signing keys held"] = bool(((s.get("oAuthKeyConfigurations") or {}).get("oAuthKeyConfiguration")))
        elif uid:
            s = vcfa.settings(uid, "federation")
            checks["SAML enabled"] = s.get("enabled") is True
            checks["email mapped"] = bool((s.get("samlAttributeMapping") or {}).get("emailAttributeName"))
            policy = g.req("GET", f"{GRAPH_BETA}/servicePrincipals/{sp_id}/claimsPolicy")
            checks["the app emits an email claim"] = any(c.get("name") == "emailaddress" for c in policy.get("claims") or [])
        if org:
            _, rows, _ = vcfa.ok("GET", "/cloudapi/1.0.0/groups", "read imported group", accept=GROUPS_ACCEPT, tenant=org["id"],
                                 params={"filter": f"name=={self.group_name}", "pageSize": 10})
            got = rows.get("values") or []
            roles = sorted(r.get("name") for r in (got[0].get("roleEntityRefs") or [])) if got else []
            checks["group imported with the member-level role"] = roles == [ROLES[a.org_type]["member"]]
        for name, ok in checks.items():
            self.step(f"check: {name}", "pass" if ok else "FAIL")
        print("\nNow prove it in a browser, at https://<automation-host>/tenant/<org>:")
        for line in proof_checklist(a.protocol):
            print(f"  - {line}")
        return all(checks.values())

    # ── teardown ───────────────────────────────────────────────────────────────────────────────────────
    def teardown(self, vcfa, g):
        s = self.state
        if not s:
            print("refused: no state file, so nothing here was created by this script")
            sys.exit(2)
        org = vcfa.org(self.org_name)
        if org and s.get("org_created") == org["id"]:
            _, body, _ = vcfa.ok("GET", f"/cloudapi/1.0.0/orgs/{org['id']}", "read organization")
            body["isEnabled"] = False  # a trimmed body is refused; the full record goes back with one field changed
            vcfa.ok("PUT", f"/cloudapi/1.0.0/orgs/{org['id']}", "disable organization", body=body)
            st, _, hdrs = vcfa.ok("DELETE", f"/cloudapi/1.0.0/orgs/{org['id']}", "delete organization", params={"force": "true", "recursive": "true"})
            if st == 202 and hdrs.get("Location"):
                vcfa.wait_task(hdrs["Location"])
            self.step("organization disabled and deleted", st)
        for kind, path in (("app", f"/applications/{s.get('app_created')}"), ("group", f"/groups/{s.get('group_created')}")):
            oid = s.get(f"{kind}_created")
            if oid and g.exists(path):
                g.req("DELETE", path)
                self.step(f"Entra {kind} deleted by object id", g.status)
        for kind in ("app", "service principal", "group"):  # deleted objects wait in the recycle bin; these are ours
            oid = s.get("sp_id") if kind == "service principal" else s.get(f"{kind}_created")
            if not oid:
                continue
            # The bin's reads lag the delete (seconds to minutes), so ask for the purge until it is done, not until a
            # read shows the object there: a read-first loop skipped an app that had not reached the bin's view yet.
            start, st = time.monotonic(), None
            while time.monotonic() - start < 180:
                st, _ = g.call("DELETE", f"/directory/deletedItems/{oid}")
                if st == 204:
                    break
                time.sleep(10)
            self.step(f"Entra {kind} purged from the recycle bin", st, after_s=round(time.monotonic() - start))
        return self.residue(vcfa, g)

    def residue(self, vcfa, g):
        s, left = self.state, []
        deadline = time.monotonic() + 180
        while True:
            left = []
            if vcfa.org(self.org_name):
                left.append("organization")
            for kind, coll, oid in (("app", "applications", s.get("app_created")), ("service principal", "servicePrincipals", s.get("sp_id")),
                                    ("group", "groups", s.get("group_created"))):
                if oid and g.exists(f"/{coll}/{oid}"):
                    left.append(kind)
            for kind, oid in (("app", s.get("app_created")), ("service principal", s.get("sp_id")), ("group", s.get("group_created"))):
                if oid and g.exists(f"/directory/deletedItems/{oid}"):
                    left.append(f"{kind} in the recycle bin")
            if not left or time.monotonic() > deadline:
                break
            time.sleep(15)  # Entra's reads lag its deletes by seconds
        self.step("residue check", "none" if not left else "LEFT", left=left)
        return not left

    def write(self):
        """One record per organization: each mode (execute, prove, teardown) writes its steps under its own key, so a
        build, its check and its teardown read as one run. A record for another protocol or type is replaced."""
        out = os.environ.get("OUT", "federation.json")
        a, mode = self.args, "teardown" if self.args.teardown else ("prove" if self.args.prove else "execute")
        head = {"protocol": a.protocol, "org_type": a.org_type, "user_key": a.user_key if a.protocol == "oidc" else None}
        rec = {}
        if os.path.exists(out):
            with open(out, encoding="utf-8") as f:
                rec = json.load(f)
            if {k: rec.get(k) for k in head} != head:
                rec = {}
        rec.update(head)
        rec.setdefault("runs", {})[mode] = {"captured": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "steps": self.steps}
        text = self.san.scrub(json.dumps(rec, indent=1, ensure_ascii=False))
        self.san.check(text)
        with open(out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print(f"\nrecorded {len(self.steps)} steps to {out}; every estate value replaced by a placeholder")


# ── day 2: change an existing organization's federation, only the named fields ─────────────────────────────────
def federated_to(oauth, fed, tenant):
    """The protocol the organization is federated to this tenant over, or None: OIDC by its issuer, SAML by the issuer
    in the metadata it holds. An organization signed in through VCF single sign-on is neither."""
    if oauth.get("enabled") and not oauth.get("vidb") and f"login.microsoftonline.com/{tenant}" in str(oauth.get("issuerId") or ""):
        return "oidc"
    if fed.get("enabled") and f"sts.windows.net/{tenant}" in str(fed.get("samlMetadata") or ""):
        return "saml"
    return None


def oidc_update(current, secret, refresh_hours=None, keys=None):
    """The OIDC settings for a day-2 write: the GET body with only the named fields changed and every other field
    carried through, the client secret on the write because VCF Automation refuses one without it. Returns the body
    and the names of the fields whose value changes."""
    body = {k: v for k, v in current.items() if k not in ("link", "href", "type", "clientSecret")}
    changed = []
    if refresh_hours is not None:
        want = {"autoRefreshKey": True, "keyRefreshStrategy": "ADD", "keyRefreshFrequencyInHours": refresh_hours}
        changed += [k for k, v in want.items() if current.get(k) != v]
        body.update(want)
    if keys is not None:
        held = sorted(k.get("keyId") for k in ((current.get("oAuthKeyConfigurations") or {}).get("oAuthKeyConfiguration") or []))
        if held != sorted(k["keyId"] for k in keys):
            changed.append("oAuthKeyConfigurations")
        body["oAuthKeyConfigurations"] = {"oAuthKeyConfiguration": keys}
    body["clientSecret"] = secret
    return body, changed


def saml_update(current, metadata):
    """The SAML settings for a day-2 write: the GET body with the provider's metadata replaced."""
    body = {k: v for k, v in current.items() if k not in ("link", "href", "type")}
    changed = ["samlMetadata"] if current.get("samlMetadata") != metadata else []
    body["samlMetadata"] = metadata
    return body, changed


def metadata_certs(xml):
    """The signing certificates a SAML metadata document names, as the base64 text between its X509Certificate tags."""
    return sorted({"".join(c.split()) for c in re.findall(r"<(?:\w+:)?X509Certificate>([^<]+)</(?:\w+:)?X509Certificate>", xml or "")})


def update(a):
    """--update: one existing organization's federation settings, only the named fields; a plan unless --execute."""
    host, org_name, tenant = os.environ.get("VCFA_HOST"), os.environ.get("ORG"), os.environ.get("ENTRA_TENANT_ID")
    asked = [n for n, on in (("key refresh", a.key_refresh is not None), ("keys", a.keys), ("secret", a.secret),
                             ("metadata", a.metadata)) if on]
    if not (host and org_name and tenant) or not asked:
        print("--update needs VCFA_HOST, ORG, ENTRA_TENANT_ID and at least one of --key-refresh, --keys, --secret, --metadata")
        return EXIT_USAGE
    new_secret = _read_file("NEW_SECRET_FILE") if a.secret else None
    metadata = _read_file("METADATA_FILE") if a.metadata else None
    if (a.secret and not new_secret) or (a.metadata and not metadata):
        print("not run: --secret needs NEW_SECRET_FILE and --metadata needs METADATA_FILE")
        return EXIT_USAGE
    san, steps, t0 = Scrubber(), [], time.monotonic()
    for v, ph in ((host, "{{host}}"), (org_name, "{{org}}"), (tenant, "{{tenant-id}}")):
        san.add(v, ph)

    def step(name, status, **facts):
        steps.append({"step": name, "status": status, "at_s": round(time.monotonic() - t0, 1), **facts})
        print(f"  {name}: {status}" + (f"  {facts}" if facts else ""), flush=True)

    def write(proto, ok):
        out = os.environ.get("OUT", "update.json")
        rec = {"mode": "update" if a.execute else "update plan", "protocol": proto, "asked": asked,
               "captured": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "steps": steps, "held": ok}
        text = san.scrub(json.dumps(rec, indent=1, ensure_ascii=False))
        san.check(text)
        with open(out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print(f"\nrecorded {len(steps)} steps to {out}; every estate value replaced by a placeholder")

    vcfa = Vcfa(host)
    org = vcfa.org(org_name)
    if org is None:
        print("refused: no organization by that name")
        return 2
    uid = org["id"].rsplit(":", 1)[-1]
    san.add(org["id"], "{{org-id}}")
    oauth, fed = vcfa.settings(uid, "oauth"), vcfa.settings(uid, "federation")
    proto = federated_to(oauth, fed, tenant)
    san.add(oauth.get("clientId"), "{{client-id}}")
    if proto is None:
        print("refused: the organization is not federated to ENTRA_TENANT_ID over OIDC or SAML")
        return 2
    wrong = [n for n in asked if (proto == "oidc") == (n == "metadata")]
    if wrong:
        print(f"refused: an organization federated over {proto.upper()} does not take {', '.join(wrong)}")
        return 2
    try:
        if proto == "oidc":
            if a.secret:   # proven at Entra before it is written anywhere, in the plan too
                why = secret_refusal(tenant, oauth.get("clientId"), new_secret)
                if why:
                    why = f"the secret in NEW_SECRET_FILE was not written: {why}. Nothing was sent to VCF Automation"
                    step("refused", why)
                    write(proto, False)
                    return 2
                step("the secret in NEW_SECRET_FILE, accepted by Entra for the organization's app", "done")
            keys = None
            if a.keys:
                st, _, raw = _send("GET", oauth["jwksUri"], {"Accept": "application/json"}, None, ssl.create_default_context())
                if st != 200:
                    raise ReadError(f"the provider's keys endpoint answered {st}")
                keys = jwks_keys(json.loads(raw))
            held = [k.get("keyId") for k in ((oauth.get("oAuthKeyConfigurations") or {}).get("oAuthKeyConfiguration") or [])]
            step("plan", "read", protocol="OIDC",
                 key_refresh={"now": [oauth.get("autoRefreshKey"), oauth.get("keyRefreshStrategy"), oauth.get("keyRefreshFrequencyInHours")],
                              "to": [True, "ADD", a.key_refresh]} if a.key_refresh is not None else None,
                 keys={"held": len(held), "published": len(keys), "published_not_held": len(set(k["keyId"] for k in keys) - set(held))} if keys is not None else None,
                 secret="the organization's secret is replaced by the one in NEW_SECRET_FILE (no value shown)" if a.secret else None,
                 would_change=oidc_update(oauth, None, a.key_refresh, keys)[1] + (["clientSecret, if it differs from the one held"] if a.secret else []))
            if not a.execute:
                print("\nplan only: nothing was changed. Add --execute to write it and read it back.")
                write(proto, None)
                return 0
            current, held_secret = vcfa.settings_for_write(uid, "oauth")
            body, changed = oidc_update(current, new_secret or held_secret, a.key_refresh, keys)
            if a.secret and new_secret != held_secret:
                changed.append("clientSecret")
            del held_secret
            if changed:
                put_st, _, _ = vcfa.ok("PUT", f"/api/admin/org/{uid}/settings/oauth", "write OIDC settings", body=body, accept=VCD_JSON, ctype=OAUTH_SETTINGS)
                step("OIDC settings written", put_st, changed=changed)
            else:   # the organization already holds what was asked: a write would change nothing, so none is sent
                step("nothing to change", "nothing written", changed=changed)
            del body
            back, back_secret = vcfa.settings_for_write(uid, "oauth")
            checks = {}
            if a.key_refresh is not None:
                checks[f"keys refresh every {a.key_refresh} h, added"] = (back.get("autoRefreshKey"), back.get("keyRefreshStrategy"), back.get("keyRefreshFrequencyInHours")) == (True, "ADD", a.key_refresh)
            if keys is not None:
                stored = {k.get("keyId") for k in ((back.get("oAuthKeyConfigurations") or {}).get("oAuthKeyConfiguration") or [])}
                checks["the organization holds every key the provider publishes"] = {k["keyId"] for k in keys} <= stored
            if a.secret:
                checks["the organization holds the new secret"] = back_secret == new_secret
            checks["every settings field but the key refresh, the keys and the secret read back unchanged"] = all(
                back.get(k) == current.get(k) for k in current
                if k not in ("link", "href", "type", "autoRefreshKey", "keyRefreshStrategy", "keyRefreshFrequencyInHours",
                             "oAuthKeyConfigurations", "lastKeyRefreshAttempt", "lastKeySuccessfulRefresh"))
            del back_secret, new_secret
        else:
            certs = metadata_certs(metadata)
            if f"sts.windows.net/{tenant}" not in metadata or not certs:
                print("not run: the metadata in METADATA_FILE is not this tenant's, or names no signing certificate")
                return EXIT_USAGE
            step("plan", "read", protocol="SAML", metadata={"certificates_now": len(metadata_certs(fed.get("samlMetadata"))),
                                                             "certificates_new": len(certs),
                                                             "new_not_held": len(set(certs) - set(metadata_certs(fed.get("samlMetadata"))))},
                 would_change=["samlMetadata"] if fed.get("samlMetadata") != metadata else [])
            if not a.execute:
                print("\nplan only: nothing was changed. Add --execute to write it and read it back.")
                write(proto, None)
                return 0
            current = vcfa.settings(uid, "federation")
            body, changed = saml_update(current, metadata)
            if changed:
                put_st, _, _ = vcfa.ok("PUT", f"/api/admin/org/{uid}/settings/federation", "write SAML settings", body=body, accept=VCD_JSON, ctype=FEDERATION_SETTINGS)
                step("SAML settings written", put_st, changed=changed)
            else:   # the organization already holds this metadata: nothing is sent
                step("nothing to change", "nothing written", changed=changed)
            back = vcfa.settings(uid, "federation")
            checks = {"the organization holds the new metadata's certificates": set(certs) <= set(metadata_certs(back.get("samlMetadata"))),
                      "SAML still enabled": back.get("enabled") is True}
    except ReadError as e:   # a read that did not answer: what it would have shown is not known
        step("read failed", str(e))
        write(proto, False)
        print(f"\nnot known: a read failed ({e}) (exit 3)")
        return EXIT_UNREAD
    except CallError as e:
        step("refused", str(e))
        write(proto, False)
        return 1
    for name, ok in checks.items():
        step(f"check: {name}", "pass" if ok else "FAIL")
    write(proto, all(checks.values()))
    return 0 if all(checks.values()) else 1


# ── an organization this script did not build: prove it, or configure it ────────────────────────────────────────
# A real tenant's organization is never built by --execute, which refuses any name it did not create. These two modes
# take an existing organization by name (--org) and need no state file. --prove --org reads the organization's
# settings back against the plan, its imported groups and their roles against its own role list, and its local
# administrator. --configure --org writes the organization's side from what the tenant's administrator handed over
# (the app's client id and secret over OIDC, its federation metadata over SAML) as a round trip, imports each named
# group with the role its organization type defines, resolved from the organization's own role list, and reads every
# write back. Neither calls Entra ID beyond its public discovery and keys endpoints, and neither needs a Graph app.

# The settings each protocol's sign-in depends on: a difference here fails the proof. Every other field the plan sets
# is reported when it differs, without failing (a console-built organization may hold another clock skew or label).
REQUIRED = {
    "oidc": ("enabled", "issuerId", "jwksUri", "scope", "usePKCE", "autoRefreshKey", "keyRefreshStrategy",
             "keyRefreshFrequencyInHours", "oidcAttributeMapping.subjectAttributeName",
             "oidcAttributeMapping.emailAttributeName", "oidcAttributeMapping.groupsAttributeName"),
    "saml": ("enabled", "samlAttributeMapping.userNameAttributeName", "samlAttributeMapping.emailAttributeName",
             "samlAttributeMapping.groupAttributeName"),
}
NOT_COMPARED = ("link", "href", "type", "clientSecret", "oAuthKeyConfigurations", "samlMetadata")
# Both modes read the organization only. VCF Automation imported a group name no group assigned to the app carried
# (X-192), and a proof of the organization's side passed it; the federation watch's group_names, which reads the app's
# assignments through the tenant's read-only app, failed on it. So the Entra side of every group is the watch's to prove.
ENTRA_SIDE = ("This proves the organization's side. That each imported group is a group assigned to the app at Entra is "
              "the federation-operations watch's group_names check, through the tenant's read-only app: run it next.")
ROLE_KEYS = ("member", "auditor", "administrator")


def _flat(fields, prefix=""):
    """A settings body as dotted field names to values, one level into the attribute mappings."""
    out = {}
    for k, v in fields.items():
        if k in NOT_COMPARED:
            continue
        if isinstance(v, dict) and k.endswith("AttributeMapping"):
            out.update(_flat(v, f"{k}."))
        else:
            out[prefix + k] = v
    return out


def _same(a, b):
    if isinstance(a, list) and isinstance(b, list):
        return sorted(map(str, a)) == sorted(map(str, b))
    return a == b


def against_plan(read, planned, protocol):
    """Each planned settings field against the organization's read: (failed, differing). A field whose planned value
    is a placeholder ({{...}}) is the reader's own and is not compared; a required field that differs fails."""
    want, got = _flat(planned), _flat(read)
    failed, differing = [], []
    for name, value in want.items():
        if "{{" in json.dumps(value):
            continue
        if not _same(got.get(name), value):
            (failed if name in REQUIRED[protocol] else differing).append(name)
    return failed, differing


def settings_changes(current, body):
    """The dotted names of the fields a settings write changes; the secret and the metadata are counted apart."""
    now, then = _flat(current), _flat(body)
    return sorted(k for k, v in then.items() if not _same(now.get(k), v))


def _shown(name, value):
    """A settings value as the plan prints it: `enabled` as on or off, nothing stored as (none)."""
    if name == "enabled":
        return "on" if value is True else "off"
    if value is None or value == "" or value == []:
        return "(none)"
    return ", ".join(map(str, value)) if isinstance(value, list) else str(value)


def old_and_new(current, body, changes, published=None):
    """Each field a write changes, as `old -> new`, so the plan holds what a rollback writes back by hand. The secret is
    never shown, and the keys and the metadata are counted."""
    now, then, out = _flat(current), _flat(body), {}
    for name in changes:
        if name == "clientSecret":
            out[name] = "replaced by the secret in APP_SECRET_FILE (no value shown)"
        elif name == "oAuthKeyConfigurations":
            held = {k.get("keyId") for k in ((current.get("oAuthKeyConfigurations") or {}).get("oAuthKeyConfiguration") or [])}
            pub = {k["keyId"] for k in published or []}
            out[name] = f"{len(held)} held -> the {len(pub)} Entra publishes ({len(pub - held)} not held)"
        elif name == "samlMetadata":
            out[name] = (f"{len(metadata_certs(current.get('samlMetadata')))} signing certificate(s) -> "
                         f"{len(metadata_certs(body.get('samlMetadata')))} in METADATA_FILE")
        else:
            out[name] = f"{_shown(name, now.get(name))} -> {_shown(name, then.get(name))}"
    return out


def parse_groups(pairs):
    """--group ROLE=NAME, repeated, as {role key: group name}; refuses an unknown role key or a role named twice."""
    out = {}
    for pair in pairs or []:
        role, sep, name = pair.partition("=")
        role, name = role.strip(), name.strip()
        if not sep or role not in ROLE_KEYS or not name or role in out:
            raise ValueError(f"--group takes ROLE=NAME once per role, ROLE one of {', '.join(ROLE_KEYS)}: {pair!r}")
        out[role] = name
    return out


def group_findings(groups, provider_type, role_names, wanted):
    """The organization's groups against its own role list and the groups asked for. `wanted` maps a group name to the
    role name it should hold. Returns check name to pass."""
    mine = [g for g in groups if g.get("providerType") == provider_type]
    checks = {f"at least one group imported over {provider_type}": bool(mine)}
    for g in mine:
        roles = sorted(r.get("name") for r in g.get("roleEntityRefs") or [])
        checks[f"imported group {g.get('name')} holds roles of the organization's own list"] = bool(roles) and set(roles) <= set(role_names)
    for name, role in wanted.items():
        found = [g for g in groups if g.get("name") == name]
        roles = sorted(r.get("name") for r in (found[0].get("roleEntityRefs") or [])) if found else []
        checks[f"group {name} imported over {provider_type} holding {role}"] = (
            len(found) == 1 and found[0].get("providerType") == provider_type and roles == [role])
    return checks


EMAIL_ADDRESS = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s.]+$")


def saml_emails(users):
    """Over SAML, each enabled user's stored email against what a round trip of its record needs, as counts:
    saml_users, enabled, not_an_address (enabled users whose stored email is empty, not an address, or the NameID), and
    disabled_not_judged. Without an email claim VCF Automation stored a new user's NameID as its email and refused a
    round trip of the record; with the claim, the address was stored and the round trip answered 200. A disabled
    account is not judged: the leaver close clears an email the platform refuses (G-316). This reads the stored state
    only: the round trip itself is a write, and --prove never sends one."""
    saml = [u for u in users if u.get("providerType") == "SAML"]
    live = [u for u in saml if u.get("enabled")]
    bad = [u for u in live
           if not EMAIL_ADDRESS.match((u.get("email") or "").strip()) or (u.get("email") or "") == (u.get("nameInSource") or "")]
    return {"saml_users": len(saml), "enabled": len(live), "not_an_address": len(bad),
            "disabled_not_judged": len(saml) - len(live)}


def local_admin_held(users, top_role):
    """An enabled local user holding the organization's top role: the way in when the provider refuses it."""
    return any(u.get("providerType") == "LOCAL" and u.get("enabled")
               and any(r.get("name") == top_role for r in u.get("roleEntityRefs") or []) for u in users)


def switch_refusal(oauth, fed, tenant, protocol, user_key, users=()):
    """Why --configure leaves this organization's sign-in alone, or "". A protocol, an OIDC user key or the SAML
    user-name claim is never switched in place under the users it keys (a SAML organization moved to OIDC refused its
    users; a move to oid split an account; a renamed SAML user was refused), and that is judged on what the organization
    stores and on the users it holds, whatever `enabled` says: a federation switched off during an incident still holds
    its key, its metadata, its mapping and its users. An organization signed in through VCF single sign-on is that
    provider's, and one whose stored settings name another provider is not this tenant's. A fresh organization, with
    nothing stored and no federated user, is configured."""
    oidc_on, saml_on = bool(oauth.get("enabled")) and not oauth.get("vidb"), bool(fed.get("enabled"))
    now = federated_to(oauth, fed, tenant)
    kinds = {u.get("providerType") for u in users or ()}
    issuer = str(oauth.get("issuerId") or "")
    held_key = (oauth.get("oidcAttributeMapping") or {}).get("subjectAttributeName")
    metadata = str(fed.get("samlMetadata") or "")
    if oauth.get("vidb"):
        if protocol == "oidc":
            return "the organization signs in through VCF single sign-on, which excludes OIDC in one organization"
        return ("the organization signs in through VCF single sign-on, and its users are that provider's: federate a "
                "tenant directly in a new organization")
    if (oidc_on or saml_on) and now is None:
        return "the organization is federated to a provider other than ENTRA_TENANT_ID"
    if now and now != protocol:
        return f"the organization is federated over {now.upper()}: move a tenant to another protocol through a new organization"
    # With neither protocol live (now is None), what the organization stores and the users it holds decide: the write
    # would switch the federation on under this run's protocol and key.
    if protocol == "oidc":
        if now is None:
            held = [what for what, on in (("SAML metadata", bool(metadata)), ("a SAML entity id", bool(fed.get("samlSPEntityId"))),
                                          ("SAML users", "SAML" in kinds)) if on]
            if held:
                return (f"the organization holds {' and '.join(held)}, enabled or not: move a tenant to another protocol "
                        "through a new organization")
            if issuer and f"login.microsoftonline.com/{tenant}" not in issuer:
                return "the organization holds OIDC settings for a provider other than ENTRA_TENANT_ID, enabled or not"
        if held_key and held_key != user_key:
            return (f"the organization keys its users on {held_key} in the OIDC settings it holds, enabled or not: run "
                    f"--configure with --user-key {held_key}, or without --user-key, to keep it; a move to another key "
                    "goes through a new organization")
        if not held_key and (now == "oidc" or "OAUTH" in kinds):
            return ("the organization holds OIDC users or a live OIDC federation and stores no user key, so the key they "
                    "were made under cannot be read: move the tenant through a new organization")
        return ""
    if now is None:
        if "OAUTH" in kinds:
            return ("the organization holds OIDC users, enabled or not, and SAML would refuse them: move a tenant to "
                    "another protocol through a new organization")
        other = re.search(r"sts\.windows\.net/([0-9a-fA-F-]{36})/", metadata)
        if other and other.group(1).lower() != str(tenant).lower():
            return "the organization holds SAML metadata for a provider other than ENTRA_TENANT_ID, enabled or not"
    # Over SAML the organization matched a returning user on its user name (a renamed user was refused, and a new NameID
    # under the same name reached the same account), and the user name comes from the claim its mapping names. A write
    # that changes that claim under the SAML users it holds, enabled or not, would refuse each one whose two values
    # differ, so it is refused; with no SAML user it goes ahead, the old and new claim printed in the plan. The other
    # mapped claims (email, names, groups) were not measured as a match key: the plan prints their old and new values.
    held_claim = (fed.get("samlAttributeMapping") or {}).get("userNameAttributeName")
    want = SAML_USER_NAME_CLAIM
    if "SAML" in kinds and held_claim != want:
        if held_claim:
            return (f"the organization matches its SAML users on the user-name claim {held_claim}, enabled or not, and "
                    f"this run would write {want}: a returning user whose two values differ would be refused. --update "
                    "--metadata changes the metadata alone; a move to another claim goes through a new organization")
        return ("the organization holds SAML users and stores no user-name claim, so the claim they were matched on "
                f"cannot be read, and this run would write {want}: move the tenant through a new organization")
    return ""


def sp_metadata_names(xml):
    """The entity id and HTTP-POST assertion consumer an organization's service-provider metadata names."""
    entity = re.search(r'entityID="([^"]+)"', xml or "")
    acs = re.search(r'AssertionConsumerService[^>]*Binding="urn:oasis:names:tc:SAML:2\.0:bindings:HTTP-POST"[^>]*Location="([^"]+)"', xml or "")
    return (entity.group(1) if entity else None), (acs.group(1) if acs else None)


class _Log:
    """The steps of one run and the record they make, scrubbed, for the two existing-organization modes."""

    def __init__(self, mode, host, org_name, tenant, out_default):
        self.mode, self.steps, self.t0 = mode, [], time.monotonic()
        self.out = os.environ.get("OUT", out_default)
        self.san = Scrubber()
        for v, ph in ((host, "{{host}}"), (org_name, "{{org}}"), (tenant, "{{tenant-id}}")):
            self.san.add(v, ph)

    def step(self, name, status, quiet=(), **facts):
        """One step, recorded with every fact and printed without the facts named in `quiet` (printed apart, or not)."""
        self.steps.append({"step": name, "status": status, "at_s": round(time.monotonic() - self.t0, 1), **facts})
        shown = {k: v for k, v in facts.items() if k not in quiet}
        if quiet != "all":
            print(f"  {name}: {status}" + (f"  {shown}" if shown else ""), flush=True)

    def write(self, **head):
        rec = {"mode": self.mode, **head, "captured": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "steps": self.steps}
        text = self.san.scrub(json.dumps(rec, indent=1, ensure_ascii=False))
        self.san.check(text)
        with open(self.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print(f"\nrecorded {len(self.steps)} steps to {self.out}; every estate value replaced by a placeholder")


def _org_reads(vcfa, org, log):
    """What both modes read of one organization: its type, roles, settings (the secret dropped), groups and users.
    Every name read is registered with the record's scrubber before anything is recorded."""
    urn, uid = org["id"], org["id"].rsplit(":", 1)[-1]
    groups = vcfa.pages("/cloudapi/1.0.0/groups", "read imported groups", urn, GROUPS_ACCEPT)
    users = vcfa.pages("/cloudapi/1.0.0/users", "read users", urn)
    for u in users:  # a user record can carry a password field; it goes the moment it arrives
        u.pop("password", None)
        for k in ("username", "email", "fullName", "nameInSource"):
            log.san.add(u.get(k), "{{user}}")
    for g in groups:
        log.san.add(g.get("name"), "{{group}}")
    oauth = vcfa.settings(uid, "oauth")
    log.san.add(oauth.get("clientId"), "{{client-id}}")
    return {"urn": urn, "uid": uid, "org_type": "classic" if org.get("isClassicTenant") else "all-apps",
            "roles": vcfa.role_names(urn), "oauth": oauth, "fed": vcfa.settings(uid, "federation"),
            "groups": groups, "users": users}


def _discovery(tenant):
    """Entra's v2.0 discovery document and signing keys for the tenant: public reads, no credential."""
    url = f"{AUTHORITY}/{tenant}/v2.0/.well-known/openid-configuration"
    st, _, raw = _send("GET", url, {"Accept": "application/json"}, None, ssl.create_default_context())
    if st != 200:
        raise ReadError(f"Entra's discovery document answered {st}")
    disc = json.loads(raw)
    st, _, raw = _send("GET", disc["jwks_uri"], {"Accept": "application/json"}, None, ssl.create_default_context())
    if st != 200:
        raise ReadError(f"Entra's keys endpoint answered {st}")
    return disc, jwks_keys(json.loads(raw))


SAML_EMAIL_CHECK = "every enabled SAML user's stored email is an address, not its NameID"
SAML_ROUND_TRIP_NOTE = ("A round trip of a SAML user's record is a write, so --prove sends none. Where it was measured, a "
                        "record whose stored email was the NameID was refused, and one whose stored email was the address "
                        "answered 200; this run reads the stored email, and a round trip on this organization was not sent.")


def prove_existing(a):
    """--prove --org: an existing organization proven read-only, with no state file. Its settings are read back
    against the plan for the protocol it is federated over, its type and its user key (--user-key, or the key it
    holds); every imported group must hold roles of the organization's own list, and each --group ROLE=NAME the role
    its type defines; an enabled local user must hold the top role. A browser makes the sign-in: the steps print last."""
    host, tenant, org_name = os.environ.get("VCFA_HOST"), os.environ.get("ENTRA_TENANT_ID"), a.org
    if not (host and tenant and org_name):
        print("--prove --org needs VCFA_HOST, ENTRA_TENANT_ID and the organization's name")
        return EXIT_USAGE
    try:
        wanted_keys = parse_groups(a.group)
    except ValueError as e:
        print(f"not run: {e}")
        return EXIT_USAGE
    log = _Log("prove existing", host, org_name, tenant, "prove.json")
    vcfa = Vcfa(host)
    org = vcfa.org(org_name)
    if org is None:
        print("refused: no organization by that name")
        return 2
    log.san.add(org["id"], "{{org-id}}")
    for name in wanted_keys.values():
        log.san.add(name, "{{group}}")
    checks, proto, org_type, unrun, emails = {}, None, None, [], None
    try:
        r = _org_reads(vcfa, org, log)
        proto, org_type = federated_to(r["oauth"], r["fed"], tenant), r["org_type"]
        roles = ROLES[org_type]
        checks["organization enabled"] = org.get("isEnabled") is True
        checks["federated to ENTRA_TENANT_ID over OIDC or SAML"] = proto is not None
        if a.protocol:
            checks[f"federated over {a.protocol.upper()}, as planned"] = proto == a.protocol
        if a.org_type:
            checks[f"a {a.org_type} organization, as planned"] = org_type == a.org_type
        for k in wanted_keys:
            checks[f"--group {k}: a role a {org_type} organization has"] = bool(roles.get(k))
        wanted = {name: roles[k] for k, name in wanted_keys.items() if roles.get(k)}
        held_key = (r["oauth"].get("oidcAttributeMapping") or {}).get("subjectAttributeName")
        key = a.user_key or held_key or "oid"
        failed, differing, kept_claim = [], [], None
        if proto == "oidc":
            disc, keys = _discovery(tenant)
            planned = oidc_settings({}, disc, [], "{{client-id}}", "{{client-secret}}", key)
            stored = {k.get("keyId") for k in ((r["oauth"].get("oAuthKeyConfigurations") or {}).get("oAuthKeyConfiguration") or [])}
            checks["the organization holds every signing key Entra publishes"] = bool(keys) and {k["keyId"] for k in keys} <= stored
            checks[f"users keyed on {key}" + ("" if a.user_key else ", the key it holds")] = held_key == key
            failed, differing = against_plan(r["oauth"], planned, "oidc")
        elif proto == "saml":
            planned = plan("saml", org_type, None)["settings"]["fields"]
            # The claim its SAML users are matched on is judged as held, as an OIDC organization's key is: a different
            # claim under existing users is the organization's own, and --configure refuses to change it.
            held_claim = (r["fed"].get("samlAttributeMapping") or {}).get("userNameAttributeName")
            if held_claim and held_claim != SAML_USER_NAME_CLAIM and any(u.get("providerType") == "SAML" for u in r["users"]):
                planned["samlAttributeMapping"] = {**planned["samlAttributeMapping"], "userNameAttributeName": held_claim}
                kept_claim = held_claim
                print(f"  its SAML users are matched on {held_claim}, not the plan's {SAML_USER_NAME_CLAIM}: judged as "
                      "held, since a change would refuse each user whose two values differ")
            checks["the metadata it holds names a signing certificate"] = bool(metadata_certs(r["fed"].get("samlMetadata")))
            failed, differing = against_plan(r["fed"], planned, "saml")
            emails = saml_emails(r["users"])
            if emails["enabled"]:
                checks[SAML_EMAIL_CHECK] = emails["not_an_address"] == 0
            else:   # nothing to read yet is not a pass: it runs once a SAML user has signed in
                unrun.append(f"{SAML_EMAIL_CHECK}: no enabled SAML user has signed in yet; run --prove --org again "
                             "after the first browser sign-in")
        if proto:
            checks["every setting the sign-in depends on reads as planned"] = not failed
            checks.update(group_findings(r["groups"], "OAUTH" if proto == "oidc" else "SAML", r["roles"], wanted))
        checks[f"an enabled local user holds {roles['administrator']}"] = local_admin_held(r["users"], roles["administrator"])
        log.step("read", "done", protocol=proto, org_type=org_type, user_key=key if proto == "oidc" else None,
                 imported_groups=len(r["groups"]), roles=len(r["roles"]), failed_fields=failed, differing_fields=differing,
                 **({"saml_emails": emails} if emails else {}),
                 **({"user_name_claim_kept": kept_claim} if kept_claim else {}))
    except CallError as e:   # a proof only reads, so a read it could not make leaves the result not known: exit 3
        log.step("read refused", str(e))
        log.write(protocol=proto, org_type=org_type, held=False, read_failed=True)
        print(f"\nnot proven: a read was refused ({e}); nothing is known of what it did not read (exit 3)")
        return EXIT_UNREAD
    for name, ok in checks.items():
        log.step(f"check: {name}", "pass" if ok else "FAIL")
    for line in unrun:
        log.step(f"check: {line}", "NOT RUN")
    if proto == "saml":
        print(f"\n{SAML_ROUND_TRIP_NOTE}")
    print(f"\n{ENTRA_SIDE}\nThen prove it in a browser, at https://<automation-host>/tenant/<org>:")
    for line in proof_checklist(proto or "oidc"):
        print(f"  - {line}")
    held = all(checks.values()) and not unrun
    log.write(protocol=proto, org_type=org_type, held=held, **({"not_run": unrun} if unrun else {}))
    if not all(checks.values()):
        return 1
    if unrun:   # a check that could not run is never a pass
        print("\nnot run: " + "; ".join(unrun) + " (exit 3)")
        return EXIT_UNREAD
    return 0


def configure_existing(a):
    """--configure --org: the provider's side of an existing organization, from what the tenant handed over. Plan by
    default; with --execute, a settings round trip (only when a field differs), the named groups imported with the
    role the organization type defines, resolved from the organization's own role list, and every write read back.
    It refuses a protocol, OIDC user key or SAML user-name claim switch, judged on what the organization stores and the
    users it holds whether or not its federation is switched on; a named group that exists another way; a client secret
    Entra does not accept; and any settings write to a federation that is switched off, unless --enable is given, so a
    group import alone never switches a federation on. The user key defaults to the one the organization holds."""
    host, tenant, org_name = os.environ.get("VCFA_HOST"), os.environ.get("ENTRA_TENANT_ID"), a.org
    if not (host and tenant and org_name and a.protocol):
        print("--configure --org needs VCFA_HOST, ENTRA_TENANT_ID, --protocol and the organization's name")
        return EXIT_USAGE
    try:
        wanted_keys = parse_groups(a.group)
    except ValueError as e:
        print(f"not run: {e}")
        return EXIT_USAGE
    client_id, new_secret, metadata = os.environ.get("APP_CLIENT_ID"), _read_file("APP_SECRET_FILE"), _read_file("METADATA_FILE")
    if a.protocol == "oidc" and not client_id:
        print("not run: --configure --protocol oidc needs APP_CLIENT_ID, the client id of the app the tenant's administrator built")
        return EXIT_USAGE
    if metadata and (f"sts.windows.net/{tenant}" not in metadata or not metadata_certs(metadata)):
        print("not run: the metadata in METADATA_FILE is not this tenant's, or names no signing certificate")
        return EXIT_USAGE
    log = _Log("configure" if a.execute else "configure plan", host, org_name, tenant, "configure.json")
    log.san.add(client_id, "{{client-id}}")
    for name in wanted_keys.values():
        log.san.add(name, "{{group}}")
    vcfa = Vcfa(host)
    org = vcfa.org(org_name)
    if org is None:
        print("refused: no organization by that name")
        return 2
    log.san.add(org["id"], "{{org-id}}")
    org_type, wrote = None, False
    try:
        r = _org_reads(vcfa, org, log)
        org_type, roles = r["org_type"], ROLES[r["org_type"]]
        held_key = (r["oauth"].get("oidcAttributeMapping") or {}).get("subjectAttributeName")
        key = (a.user_key or held_key or "oid") if a.protocol == "oidc" else None

        def refuse(why):
            print(f"refused: {why}")
            log.step("refused", why, quiet="all")
            log.write(protocol=a.protocol, org_type=org_type, held=False)
            return 2

        if a.org_type and a.org_type != org_type:
            return refuse(f"the organization is a {org_type} organization, not {a.org_type}")
        why = switch_refusal(r["oauth"], r["fed"], tenant, a.protocol, key, r["users"])
        if why:
            return refuse(why)
        if a.protocol == "saml" and not metadata:
            href = next((ln["href"] for ln in r["fed"].get("link") or [] if ln.get("type") == SAML_METADATA), None)
            if href:
                _, xml, _ = vcfa.call("GET", "/" + href.split("://", 1)[-1].split("/", 1)[-1], accept=SAML_METADATA)
                entity, acs = sp_metadata_names(xml if isinstance(xml, str) else "")
                print(f"Send the tenant's administrator this organization's service-provider metadata: identifier {entity}, "
                      f"reply URL {acs}; a new organization answers 500 here for its first seconds, so run again if either is None.")
            return refuse("--configure --protocol saml needs METADATA_FILE, the app's federation metadata from the tenant's administrator")
        absent = [k for k in wanted_keys if not roles.get(k) or roles[k] not in r["roles"]]
        if absent:
            return refuse(f"this {org_type} organization's role list has no role for {', '.join(absent)}")
        provider_type = "OAUTH" if a.protocol == "oidc" else "SAML"
        imports, held_ok, clashes = [], [], []
        for k, name in wanted_keys.items():
            found = [g for g in r["groups"] if g.get("name") == name]
            have = sorted(x.get("name") for x in (found[0].get("roleEntityRefs") or [])) if found else []
            if not found:
                imports.append((k, name))
            elif found[0].get("providerType") == provider_type and have == [roles[k]]:
                held_ok.append(name)
            else:
                clashes.append(name)
        if clashes:
            return refuse(f"{len(clashes)} named group(s) exist under another protocol or with other roles; change them by hand, "
                          "because an import of a name the organization holds answered 201 with the group it already had")
        secret, keys, secret_changes = None, [], False
        if a.protocol == "oidc":
            current, held_secret = vcfa.settings_for_write(r["uid"], "oauth")
            same_app = current.get("clientId") == client_id
            secret = new_secret or (held_secret if same_app else None)
            secret_changes = bool(secret) and secret != held_secret
            del held_secret
            disc, keys = _discovery(tenant)
            body = oidc_settings(current, disc, keys, client_id, secret, key)
            planned = oidc_settings({}, disc, [], "{{client-id}}", "{{client-secret}}", key)
            kind, ctype = "oauth", OAUTH_SETTINGS
        else:
            current = vcfa.settings(r["uid"], "federation")
            body = saml_settings(current, metadata, "Sign in with Entra ID")
            planned = plan("saml", org_type, None)["settings"]["fields"]
            kind, ctype = "federation", FEDERATION_SETTINGS
        # A federation switched off stays off unless --enable: the body carries `enabled` as stored, so a run that only
        # imports a group (a rename's repair) writes no settings, and a settings write to it without --enable is refused.
        was_on = current.get("enabled") is True
        if not was_on and not a.enable:
            body["enabled"] = planned["enabled"] = current.get("enabled")
        changes = settings_changes(current, body) + (["clientSecret"] if secret_changes else [])
        held_keys = {k.get("keyId") for k in ((current.get("oAuthKeyConfigurations") or {}).get("oAuthKeyConfiguration") or [])}
        if a.protocol == "oidc" and not {k["keyId"] for k in keys} <= held_keys:   # a key Entra publishes and it lacks
            changes.append("oAuthKeyConfigurations")
        if a.protocol == "saml" and current.get("samlMetadata") != metadata:
            changes.append("samlMetadata")
        shown = old_and_new(current, body, changes, keys)
        log.step("plan", "read", protocol=a.protocol.upper(), org_type=org_type,
                 user_key=key and (key + ("" if a.user_key else ", the key it holds" if held_key else ", the default")),
                 settings_to_change=changes, old_and_new=shown, quiet=("old_and_new",),
                 groups_to_import=[roles[k] for k, _n in imports], groups_already_held=len(held_ok))
        for name, change in shown.items():   # the values a rollback writes back by hand
            print(f"    {name}: {change}")
        if imports:
            print("  each group is imported by the name the tenant's administrator gave; VCF Automation does not check it "
                  "against Entra, so confirm it is assigned to the app, and run the watch after")
        if changes and not was_on and not a.enable:
            return refuse(f"the organization's {a.protocol.upper()} federation is switched off (enabled: "
                          f"{_shown('enabled', current.get('enabled'))}), and this run would write its settings "
                          f"({', '.join(changes)}): add --enable to write them and switch it on (enabled: off -> on). "
                          "Without --enable, --configure writes no settings to a switched-off federation, so an import "
                          "alone leaves it off")
        if changes and a.protocol == "oidc" and not secret:
            return refuse("APP_SECRET_FILE is needed: the organization holds no secret for this app")
        if secret_changes:   # proven at Entra before it is written anywhere
            why = secret_refusal(tenant, client_id, secret)
            if why:
                return refuse(f"the secret in APP_SECRET_FILE was not written: {why}. Nothing was sent to VCF Automation")
            log.step("the secret in APP_SECRET_FILE, accepted by Entra for APP_CLIENT_ID", "done")
        if not a.execute:
            del body, secret
            print("\nplan only: nothing was changed. Add --execute to write it and read it back.")
            log.write(protocol=a.protocol, org_type=org_type, held=None)
            return 0
        if changes:
            put_st, _, _ = vcfa.ok("PUT", f"/api/admin/org/{r['uid']}/settings/{kind}", f"write {a.protocol.upper()} settings",
                                   body=body, accept=VCD_JSON, ctype=ctype)
            wrote = True
            log.step("settings written as a round trip", put_st, changed=changes)
        else:
            log.step("settings already as planned" if was_on or a.enable else
                     "settings left as stored: nothing to change, and the federation stays switched off", "nothing written")
        del body
        checks = {}
        if a.protocol == "oidc":
            back, back_secret = vcfa.settings_for_write(r["uid"], "oauth")
            checks["the organization holds the app's client id"] = back.get("clientId") == client_id
            if changes:
                checks["the organization holds the secret it was given"] = back_secret == secret
            stored = {k.get("keyId") for k in ((back.get("oAuthKeyConfigurations") or {}).get("oAuthKeyConfiguration") or [])}
            checks["the organization holds every signing key Entra publishes"] = {k["keyId"] for k in keys} <= stored
            del back_secret, secret
        else:
            back = vcfa.settings(r["uid"], "federation")
            checks["the organization holds the metadata's certificates"] = set(metadata_certs(metadata)) <= set(metadata_certs(back.get("samlMetadata")))
        failed, _differing = against_plan(back, planned, a.protocol)
        checks["every setting the sign-in depends on reads back as planned"] = not failed
        for k, name in imports:
            role_ref = vcfa.role(r["urn"], roles[k])   # resolved by name from this organization's own role list
            if role_ref is None:
                raise CallError(f"the role {roles[k]} was not found in the organization's role list")
            st, made, _ = vcfa.ok("POST", "/cloudapi/1.0.0/groups", "import group", accept=GROUPS_ACCEPT, tenant=r["urn"],
                                  body=group_import(name, provider_type, role_ref))
            wrote = True
            log.step("group imported with its role", st, role=roles[k], providerType=(made or {}).get("providerType"))
        rows = vcfa.pages("/cloudapi/1.0.0/groups", "read imported groups back", r["urn"], GROUPS_ACCEPT)
        wanted = {name: roles[k] for k, name in wanted_keys.items()}
        checks.update({n: ok for n, ok in group_findings(rows, provider_type, r["roles"], wanted).items() if n.startswith("group ")})
    except ReadError as e:   # a read that did not answer whole: what it would have shown is not known
        log.step("read failed", str(e))
        log.write(protocol=a.protocol, org_type=org_type, held=False, read_failed=True)
        print(f"\nnot known: a read failed ({e}); " + ("a write was sent before it, so read the organization back "
              "before running again" if wrote else "nothing was written") + " (exit 3)")
        return EXIT_UNREAD
    except CallError as e:
        log.step("refused", str(e))
        log.write(protocol=a.protocol, org_type=org_type, held=False)
        return 1
    for name, ok in checks.items():
        log.step(f"check: {name}", "pass" if ok else "FAIL")
    log.write(protocol=a.protocol, org_type=org_type, held=all(checks.values()))
    return 0 if all(checks.values()) else 1


class _Parser(argparse.ArgumentParser):
    """argparse exits 2 on a usage error, the code this script gives a refusal; here it is a UsageError, exit 5."""

    def error(self, message):
        self.print_usage(sys.stderr)
        raise UsageError(message)


BUILD_ENV = ("VCFA_HOST", "ORG", "ENTRA_TENANT_ID", "ENTRA_CLIENT_ID")


def credential_problem(entra):
    """What is missing for the credentials a mode needs, or "": the provider's, and for a build Entra's."""
    if not (os.environ.get("VCFA_PROVIDER_REFRESH_TOKEN_FILE") or os.environ.get("VCFA_PROVIDER_BEARER_FILE")):
        return "a provider credential (VCFA_PROVIDER_BEARER_FILE or VCFA_PROVIDER_REFRESH_TOKEN_FILE)"
    if entra and not (os.environ.get("ENTRA_CLIENT_SECRET_FILE")
                      or (os.environ.get("ENTRA_CERT_FILE") and os.environ.get("ENTRA_KEY_FILE"))):
        return "an Entra credential (ENTRA_CLIENT_SECRET_FILE, or ENTRA_CERT_FILE and ENTRA_KEY_FILE)"
    return ""


def main(argv=None):
    """The run, with two guards around it: a Python older than 3.9 is refused (exit 5) before anything is sent, and an
    error the script did not expect exits 3, a result not known, never 1, the code for a call or a check that failed."""
    if sys.version_info < (3, 9):  # noqa: UP036  the script is run by readers on their own Python
        print("org_federation.py needs Python 3.9 or later", file=sys.stderr)
        return EXIT_USAGE
    try:
        return _run(argv)
    except UsageError as e:
        print(f"not run: {e} (see the header); exit 5", file=sys.stderr)
        return EXIT_USAGE
    except ScrubError as e:
        print(f"{e}; exit 3", file=sys.stderr)
        return EXIT_UNREAD
    except ReadError as e:   # raised outside a mode's own handling: the organization's lookup, its first read
        print(f"a read failed: {e}; nothing is known of what it did not read (exit 3)", file=sys.stderr)
        return EXIT_UNREAD
    except CallError as e:   # raised outside a mode's own handling: the provider credential's exchange
        print(f"a credential was refused before anything was read: {e}; exit 3", file=sys.stderr)
        return EXIT_UNREAD
    except Exception as e:  # the last guard: whatever was not expected is not known, so exit 3
        print(f"the run stopped on an error it did not expect: {type(e).__name__}; what it had not done is not known "
              "(exit 3)", file=sys.stderr)
        return EXIT_UNREAD


def _run(argv=None):
    p = _Parser(prog="org_federation.py", description=__doc__.split("\n\n")[0])
    p.add_argument("--protocol", choices=("oidc", "saml"))
    p.add_argument("--org-type", choices=("classic", "all-apps"))
    p.add_argument("--user-key", choices=("oid", "preferred_username"))
    p.add_argument("--execute", action="store_true")
    p.add_argument("--prove", action="store_true")
    p.add_argument("--teardown", action="store_true")
    p.add_argument("--update", action="store_true", help="day 2 on an existing organization (see the docstring)")
    p.add_argument("--configure", action="store_true", help="the provider's side of an existing organization (see the docstring)")
    p.add_argument("--org", metavar="NAME", help="an existing organization, for --prove and --configure; needs no state file")
    p.add_argument("--group", action="append", metavar="ROLE=NAME", help="with --org: a group and its role key, repeated")
    p.add_argument("--key-refresh", type=int, nargs="?", const=1, metavar="HOURS")
    p.add_argument("--keys", action="store_true")
    p.add_argument("--secret", action="store_true")
    p.add_argument("--metadata", action="store_true")
    p.add_argument("--enable", action="store_true",
                   help="with --configure: write the settings of a federation that is switched off, and switch it on")
    a = p.parse_args(argv)
    if a.enable and not a.configure:
        p.error("--enable goes with --configure")
    if a.org or a.configure:
        if a.update or a.teardown or (a.prove and a.configure) or not (a.prove or a.configure):
            p.error("--org goes with --prove or --configure, and --configure with --org")
        if not a.org:
            p.error("--configure needs --org NAME")
        if credential_problem(entra=False):
            raise UsageError(f"--org needs {credential_problem(entra=False)}")
        return prove_existing(a) if a.prove else configure_existing(a)
    if a.group:
        p.error("--group goes with --org")
    a.user_key = a.user_key or "oid"
    if a.update:
        if a.prove or a.teardown:
            p.error("--update does not combine with --prove or --teardown")
        if credential_problem(entra=False):
            raise UsageError(f"--update needs {credential_problem(entra=False)}")
        return update(a)
    if a.key_refresh is not None or a.keys or a.secret or a.metadata:
        p.error("--key-refresh, --keys, --secret and --metadata go with --update")
    if not (a.protocol and a.org_type):
        p.error("--protocol and --org-type are required")
    if a.teardown and not a.execute:
        state = os.environ.get("STATE", f"org_federation.{os.environ.get('ORG', '<org>')}.state.json")
        print(f"teardown plan: delete the organization, the Entra app and the group recorded as created in {state},")
        print("purge the app, its service principal and the group from Entra's recycle bin, then read each back. Add --execute.")
        return 0
    if not (a.execute or a.prove):
        print(json.dumps(plan(a.protocol, a.org_type, a.user_key), indent=1))
        print("\nplan only: nothing was changed. Add --execute to build, --prove to check, --teardown --execute to remove.")
        return 0
    missing = [k for k in BUILD_ENV if not os.environ.get(k)] + ([credential_problem(entra=True)] if credential_problem(entra=True) else [])
    if missing:
        raise UsageError(f"--execute, --prove and --teardown need {', '.join(missing[:-1]) + ' and ' if len(missing) > 1 else ''}{missing[-1]}")
    days = os.environ.get("SECRET_DAYS", "180")
    if not (days.isdigit() and 0 < int(days) < 365):   # checked before anything is sent, not at the secret step
        raise UsageError(f"SECRET_DAYS must be a whole number of days under a year, not {days!r}")
    run = Run(a)
    vcfa, g = Vcfa(run.host), Graph(run.tenant, run.client)
    unread = False
    try:
        if a.teardown:
            ok = run.teardown(vcfa, g)
        elif a.prove:
            ok = run.prove(vcfa, g)
        else:
            run.build(vcfa, g)
            ok = True
    except ReadError as e:   # a refused read or a list not read whole, in any mode: a result not known, exit 3
        run.step("read failed", str(e))
        ok, unread = False, True
    except CallError as e:
        run.step("refused", str(e))
        ok = False
        unread = bool(a.prove and not a.teardown)   # --prove only reads: a refused read is a result not known, exit 3
    run.write()
    if unread:
        print("not known: a read was refused or not read whole; nothing is known of what it did not read (exit 3)")
        return EXIT_UNREAD
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
