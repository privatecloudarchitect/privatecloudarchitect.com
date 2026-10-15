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
  --teardown --execute   deletes what --execute created (only that), purges it from Entra's recycle bin, and reads
                         each object back to confirm nothing is left
  --update               day 2 on an existing organization federated to the tenant (it need not be one this script
                         built): reads its settings, changes only the fields named by --key-refresh [HOURS] (automatic
                         refresh on, strategy ADD, every HOURS, default 1), --keys (the keys the provider publishes now,
                         the write after an emergency roll), --secret (the client secret in NEW_SECRET_FILE, which the
                         tenant's administrator rotated) or --metadata (the SAML metadata in METADATA_FILE), and prints
                         the plan; with --execute it writes the whole body back, with the secret the organization holds
                         or the new one, and reads every changed field back. It never touches Entra.

Writes `federation.json`: the steps, their HTTP statuses, the waits Entra imposed, the setting names stored on
read-back and any refusal verbatim. Every value from your estate (host, organization, tenant, users, ids) is replaced
by a placeholder, and the script refuses to write a record in which one survived. No secret or token is printed or
written: the OIDC client secret is minted, handed to VCF Automation and dropped, and a settings read deletes the
secret VCF Automation returns before anything else sees the response.

Safety: --execute refuses an organization, app or group name that already exists unless this script created it (its
state file says so), and --teardown deletes only objects that state file records. The state file holds object ids,
not secrets; keep it beside the record and do not publish it.

Env:  VCFA_HOST; VCFA_PROVIDER_REFRESH_TOKEN_FILE (a provider api-token) or VCFA_PROVIDER_BEARER_FILE (a provider
      bearer you already hold); TLS_VERIFY=false on a self-signed lab CA; ENTRA_TENANT_ID; ENTRA_CLIENT_ID and either
      ENTRA_CLIENT_SECRET_FILE or ENTRA_CERT_FILE + ENTRA_KEY_FILE (the certificate form needs the `cryptography`
      package); ORG (the throwaway organization's name); ENTITLED_UPN and UNENTITLED_UPN (your test users);
      SECRET_DAYS (OIDC secret life, default 180); OUT (default federation.json); STATE (default
      org_federation.<ORG>.state.json). --update needs VCFA_HOST, the provider credential, ENTRA_TENANT_ID and ORG
      (the existing organization), NEW_SECRET_FILE for --secret, METADATA_FILE for --metadata; it writes OUT
      (default update.json)
Exit: 0 done · 1 a call or a check failed · 2 refused (a name this script did not create; for --update, an
      organization not federated to ENTRA_TENANT_ID, a change its protocol does not take, or a missing file)
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

CLOUDAPI = "application/json;version=9.1.0"
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
    so a rolled Entra key is held within the hour."""
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
# leaver job (identity-lifecycle's leavers.py) asks Entra for the person behind an account by it as a principal name,
# so a name claim sourced from another attribute would read every entitled account as nobody Entra knows. Entra sends
# the principal name in both by default (Microsoft's SAML claims customization page; the reference runs read the SAML
# name claim equal to the principal name).
NAME_CLAIM_SAML = (f"The name claim ({CLAIMS}/name) left sourced from user.userprincipalname, Entra's default, because the "
                   "organization names each account by it and the leaver job looks each account up by it")
NAME_CLAIM_OIDC = ("preferred_username left as Entra sends it, the user principal name, with no claims mapping over it, "
                   "because the organization names each account by it and the leaver job looks each account up by it")


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
               else ": readable usernames, and a renamed user gets a second account, so plan a rename as a leaver and a joiner"),
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
            raise SystemExit(f"refusing to write the record: {len(left)} estate value(s) survived the scrub")


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


def _read_file(var):
    path = os.environ.get(var)
    if not path:
        return None
    with open(path, encoding="utf-8") as f:
        return f.read().strip()


class Vcfa:
    """The provider side of VCF Automation, as a provider System Administrator."""

    def __init__(self, host):
        self.host, self.ctx = host, _ctx()
        refresh = _read_file("VCFA_PROVIDER_REFRESH_TOKEN_FILE")
        if refresh:
            form = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": refresh}).encode()
            st, _, raw = _send("POST", f"https://{host}/oauth/provider/token",
                               {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}, form, self.ctx)
            if st != 200:
                raise CallError(f"the provider token exchange answered {st}")
            self.bearer = json.loads(raw)["access_token"]
        else:
            self.bearer = _read_file("VCFA_PROVIDER_BEARER_FILE")
        if not self.bearer:
            raise SystemExit("set VCFA_PROVIDER_REFRESH_TOKEN_FILE or VCFA_PROVIDER_BEARER_FILE")

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
        st, data, hdrs = self.call(method, path, **kw)
        if st >= 400:
            msg = data.get("message") if isinstance(data, dict) else str(data)[:240]
            raise CallError(f"{step}: HTTP {st}: {str(msg)[:300]}")
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

    def role(self, org_urn, name):
        _, data, _ = self.ok("GET", "/cloudapi/1.0.0/roles", "find role", tenant=org_urn, params={"filter": f"name=={name}", "pageSize": 10})
        rows = data.get("values", [])
        return {"id": rows[0]["id"], "name": rows[0]["name"]} if rows else None

    def role_names(self, org_urn):
        _, data, _ = self.ok("GET", "/cloudapi/1.0.0/roles", "list roles", tenant=org_urn, params={"pageSize": 128})
        return sorted(r["name"] for r in data.get("values", []))


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
                raise CallError(f"Graph {method} {path.split('?')[0]} answered {st} ({detail})")
            time.sleep(5)

    def one(self, collection, filt, select="id,displayName"):
        q = urllib.parse.urlencode({"$filter": filt, "$select": select})
        rows = self.req("GET", f"{collection}?{q}").get("value", [])
        if len(rows) > 1:
            raise CallError(f"{len(rows)} objects match in {collection}")
        return rows[0] if rows else None

    def exists(self, path):
        st, _ = self.call("GET", path)
        return st == 200


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
        if [r for r in g.req("GET", f"/oauth2PermissionGrants?{q}").get("value", []) if r.get("resourceId") == graph_sp["id"]]:
            self.step("admin consent for openid profile email already granted", g.status)
        else:
            g.req("POST", "/oauth2PermissionGrants", {"clientId": sp["id"], "consentType": "AllPrincipals",
                                                      "resourceId": graph_sp["id"], "scope": "email openid profile"})
            self.step("admin consent for openid profile email", g.status)
        days = int(os.environ.get("SECRET_DAYS", "180"))
        if days >= 365:
            raise SystemExit("SECRET_DAYS must be under a year")
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
        form = urllib.parse.urlencode({"client_id": app_id, "client_secret": secret, "grant_type": "client_credentials",
                                       "scope": "https://graph.microsoft.com/.default"}).encode()
        while True:
            st, _, raw = _send("POST", f"{AUTHORITY}/{self.tenant}/oauth2/v2.0/token",
                               {"Content-Type": "application/x-www-form-urlencoded"}, form, ssl.create_default_context())
            if st == 200:
                return round(time.monotonic() - start)
            codes = (_parse(raw) or {}).get("error_codes") or []
            if 7000215 not in codes or time.monotonic() - start > 300:
                raise CallError(f"the new client secret was refused ({codes})")
            time.sleep(10)

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
        have = g.req("GET", f"/servicePrincipals/{sp_id}/appRoleAssignedTo").get("value", [])
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
        members = {m["id"] for m in g.req("GET", f"/groups/{group_id}/members?$select=id").get("value", [])}
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
            self.step("nothing to prove", "the build did not finish: run --execute again, or --teardown --execute")
            return False
        sp = g.req("GET", f"/servicePrincipals/{sp_id}?$select=appRoleAssignmentRequired")
        checks["assignment required on the app"] = sp.get("appRoleAssignmentRequired") is True
        # Entra's list reads lag a write by seconds, so each read is repeated for up to 90 s before it counts as a FAIL
        checks["the entitlement group is the only assignment"] = _settled(
            lambda: [x.get("principalId") for x in g.req("GET", f"/servicePrincipals/{sp_id}/appRoleAssignedTo").get("value", [])],
            [group_id])
        for var, want in (("ENTITLED_UPN", True), ("UNENTITLED_UPN", False)):
            if os.environ.get(var):
                u = g.one("/users", f"userPrincipalName eq '{os.environ[var]}'", "id")
                checks[f"the {'entitled' if want else 'unentitled'} user is {'' if want else 'not '}in the group"] = _settled(
                    lambda u=u: u["id"] in {m["id"] for m in g.req("GET", f"/groups/{group_id}/members?$select=id").get("value", [])},
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
        return 2
    new_secret = _read_file("NEW_SECRET_FILE") if a.secret else None
    metadata = _read_file("METADATA_FILE") if a.metadata else None
    if (a.secret and not new_secret) or (a.metadata and not metadata):
        print("refused: --secret needs NEW_SECRET_FILE and --metadata needs METADATA_FILE")
        return 2
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
            keys = None
            if a.keys:
                st, _, raw = _send("GET", oauth["jwksUri"], {"Accept": "application/json"}, None, ssl.create_default_context())
                if st != 200:
                    raise CallError(f"the provider's keys endpoint answered {st}")
                keys = jwks_keys(json.loads(raw))
            held = [k.get("keyId") for k in ((oauth.get("oAuthKeyConfigurations") or {}).get("oAuthKeyConfiguration") or [])]
            step("plan", "read", protocol="OIDC",
                 key_refresh={"now": [oauth.get("autoRefreshKey"), oauth.get("keyRefreshStrategy"), oauth.get("keyRefreshFrequencyInHours")],
                              "to": [True, "ADD", a.key_refresh]} if a.key_refresh is not None else None,
                 keys={"held": len(held), "published": len(keys), "published_not_held": len(set(k["keyId"] for k in keys) - set(held))} if keys is not None else None,
                 secret="the organization's secret is replaced by the one in NEW_SECRET_FILE (no value shown)" if a.secret else None)
            if not a.execute:
                print("\nplan only: nothing was changed. Add --execute to write it and read it back.")
                write(proto, None)
                return 0
            current, held_secret = vcfa.settings_for_write(uid, "oauth")
            body, changed = oidc_update(current, new_secret or held_secret, a.key_refresh, keys)
            if a.secret and new_secret != held_secret:
                changed.append("clientSecret")
            del held_secret
            put_st, _, _ = vcfa.ok("PUT", f"/api/admin/org/{uid}/settings/oauth", "write OIDC settings", body=body, accept=VCD_JSON, ctype=OAUTH_SETTINGS)
            del body
            step("OIDC settings written", put_st, changed=changed)
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
                print("refused: the metadata in METADATA_FILE is not this tenant's, or names no signing certificate")
                return 2
            step("plan", "read", protocol="SAML", metadata={"certificates_now": len(metadata_certs(fed.get("samlMetadata"))),
                                                             "certificates_new": len(certs),
                                                             "new_not_held": len(set(certs) - set(metadata_certs(fed.get("samlMetadata"))))})
            if not a.execute:
                print("\nplan only: nothing was changed. Add --execute to write it and read it back.")
                write(proto, None)
                return 0
            current = vcfa.settings(uid, "federation")
            body, changed = saml_update(current, metadata)
            put_st, _, _ = vcfa.ok("PUT", f"/api/admin/org/{uid}/settings/federation", "write SAML settings", body=body, accept=VCD_JSON, ctype=FEDERATION_SETTINGS)
            step("SAML settings written", put_st, changed=changed)
            back = vcfa.settings(uid, "federation")
            checks = {"the organization holds the new metadata's certificates": set(certs) <= set(metadata_certs(back.get("samlMetadata"))),
                      "SAML still enabled": back.get("enabled") is True}
    except CallError as e:
        step("refused", str(e))
        write(proto, False)
        return 1
    for name, ok in checks.items():
        step(f"check: {name}", "pass" if ok else "FAIL")
    write(proto, all(checks.values()))
    return 0 if all(checks.values()) else 1


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--protocol", choices=("oidc", "saml"))
    p.add_argument("--org-type", choices=("classic", "all-apps"))
    p.add_argument("--user-key", choices=("oid", "preferred_username"), default="oid")
    p.add_argument("--execute", action="store_true")
    p.add_argument("--prove", action="store_true")
    p.add_argument("--teardown", action="store_true")
    p.add_argument("--update", action="store_true", help="day 2 on an existing organization (see the docstring)")
    p.add_argument("--key-refresh", type=int, nargs="?", const=1, metavar="HOURS")
    p.add_argument("--keys", action="store_true")
    p.add_argument("--secret", action="store_true")
    p.add_argument("--metadata", action="store_true")
    a = p.parse_args()
    if a.update:
        if a.prove or a.teardown:
            p.error("--update does not combine with --prove or --teardown")
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
    run = Run(a)
    vcfa, g = Vcfa(run.host), Graph(run.tenant, run.client)
    try:
        if a.teardown:
            ok = run.teardown(vcfa, g)
        elif a.prove:
            ok = run.prove(vcfa, g)
        else:
            run.build(vcfa, g)
            ok = True
    except CallError as e:
        run.step("refused", str(e))
        ok = False
    run.write()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
