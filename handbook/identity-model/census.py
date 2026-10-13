#!/usr/bin/env python3
"""census.py - read a VCF 9.1 estate's identity model from the planes that own it. Read-only by default.

The model: an identity broker holds one single sign-on realm; the realm covers whole VCF instances; one identity
provider sits under the realm, with its directories under it; VCF Automation's organizations each choose their own
way in. This script reads each piece from the API that answers for it, so every line it prints can be checked
against that API, and prints the lines a reader should be able to explain: which brokers exist and of which kind,
which realm covers which instances, the provider's type and protocol, each directory's protocol and port, the two
ways a vCenter grant can spell a principal (a bound directory's domain, which a broker session carries, and the
realm's name, which a grant accepts and nobody signs in as), whether an emergency client exists, the API clients and
their tokens' lifetimes, and how each organization signs in.

Fleet IAM, through VCF Operations (/suite-api/api/fleet-management/iam):
  GET  /vidbs                                 the brokers, instance or embedded. Read here, never from the fleet
                                              inventory: an embedded broker lives inside a management vCenter and
                                              has no inventory row of its own
  GET  /ssorealms, /ssorealms/{id}            each realm, the instances and components it covers, its issues
  GET  /identity-providers/{id}               the realm's provider: protocol, type, provisioning, and each
                                              directory's domain controllers with protocol and port
  GET  /identity-providers/{id}/ldap-directories   each directory's sync state
  POST /ssorealms/{id}/api-clients/query, /ssorealms/{id}/api-tokens/query   API clients, roles, token lifetimes
  GET  /ssorealms/{id}/emergency-clients, /ssorealms/{id}/oauth-apps
  POST /components/auth-sources/query         which component signs in through which realm
  GET  /settings, /roles                      the fleet's token lifetimes; the VCF roles, built in or custom
VCF Automation, as the provider (optional): each organization's LDAP, OIDC and SAML settings.
vCenter (optional): each vCenter's identity provider and the broker it points at, and each Supervisor's providers
with the host of each one's issuer (read from the provider's own record: the Supervisor's list carries no issuer).

The POSTs to .../query are searches and change nothing. vCenter is read under a session the script opens and closes.
--egress-metadata-url URL sends one request per broker that is not a read: POST /saml-metadata/validate asks the
broker to fetch that SAML metadata URL itself, so 200 proves the broker reaches the identity provider and a failure
says it does not. The contract describes the call as validating and parsing metadata; the script reads the brokers,
realms and providers again after it and records any difference, so the run itself shows whether anything changed.

Secrets die where they arrive. The API returns some in clear (an emergency client's access token, a provider's
client secret and bind password, an API token's value); the reader deletes each from the body before any function
sees it, and the record keeps only the fields the allow-lists below name.

Env:  OPS_HOST                 VCF Operations FQDN (required)
      OPS_API_TOKEN_FILE       an API token from VCF Operations (mode 0600; OPS_API_TOKEN is read if it is unset),
                               traded at the broker for a bearer: OPS_BROKER_HOST (default OPS_HOST), OPS_REALM
                               (default CUSTOMER)
      OPS_BEARER_FILE          instead, a bearer you already hold (it lives an hour unless the fleet says otherwise)
      VCFA_HOST                optional, with VCFA_PROVIDER_BEARER_FILE or VCFA_PROVIDER_REFRESH_TOKEN_FILE
      VC_HOSTS                 optional, comma-separated, with VC_USER (user@domain) and VC_PASSWORD_FILE (mode
                               0600; VC_PASSWORD is read if it is unset)
      TLS_VERIFY=false         only on a self-signed lab CA (the metadata URL is fetched by the broker, not here)
      OUT                      the record (default census.json)
Use:  python3 census.py [--redact] [--egress-metadata-url URL]
Exit: 0 recorded, every call answered · 1 a call failed (the record is still written and names the call; a refused
      fleet read opens the print with NOT READ, so its zero counts are not taken for the estate's) · 2 a usage error,
      or the record refused because an estate value survived the scrub (nothing is written)
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

IAM = "/api/fleet-management/iam"
CLOUDAPI = "application/json;version=9.1.0"
VCD_JSON = "application/*+json;version=9.1.0"
API_TOKEN_GRANT = "urn:custom:vcf:params:oauth:grant-type:api-token"
SECRET_KEYS = {"accessToken", "token", "bindDnPassword", "clientSecret", "client_secret", "password",
               "refreshToken", "refresh_token", "privateKey"}
KIND = {"EXTERNAL": "instance", "EMBEDDED": "embedded"}

# ── the allow-lists: a field not named here never reaches the record ───────────────────────────────────────────
DC = ("host", "port", "protocol", "certificateName")
BROKER = ("id", "displayName", "fqdn", "deploymentType", "version", "healthy", "vcfInstanceId",
          {"vidbStatus": ("eligibilityStatus", "reasons")})
REALM = ("id", "name", "idpId", "vcfInstanceId", "vidbResourceId", "totalConfiguredComponents",
         {"ssoRealmCoverage": ("id", "name", "ssoEntityType")}, {"issues": ("name", "severity")})
PROVIDER = ("id", "name", "idpProtocol", "idpType", "provisionType", "ssoRealmId",
            {"directories": ("id", "name", "domains", "defaultDomain")},
            {"idpConfig": ({"oidcConfiguration": ("clientId", "internalUserIdentifierAttribute",
                                                  "openIdUserIdentifierAttribute")},
                           {"samlConfiguration": ("metadataSourceType", "nameIdFormatType", "authenticationContext")})},
            {"provisioningConfig": ({"ldapConfigurations": (
                "name", "domains", "ldapConfigurationId",
                {"ldapBindConfiguration": ("type", "baseDn", "bindDn", "communicationMode", "directorySearchAttribute",
                                           {"primaryDomainController": DC}, {"secondaryDomainController": DC})})},)})
DIRECTORY = ("name", "domains", "domainControllerHost", "domainControllerPort", "lastSyncStatus", "lastSyncDateTime",
             "numberOfUsers", "numberOfGroups", "setupStatus", "ldapConfigurationId")
ROLES = {"roles": ("roleName", "expiresAt")}
API_CLIENT = ("clientId", "clientUuid", "clientName", ROLES)
API_TOKEN = ("tokenName", "tokenType", "tokenStatus", "principalName", "principalStatus", "apiClientId",
             "apiTokenTtl", "accessTokenTtl", "expirationDate", "lastUsedDate")
EMERGENCY = ("clientId", "clientName", "accessTokenStatus", "accessTokenTtl", "accessTokenExpirationDate", ROLES)
AUTH_SOURCE = ("componentType", "status", "authSourceType", "ssoRealmId", "vcfComponentId")
SETTINGS = ("accessTokenTtl", "apiTokenTtl", "apiTokenRetentionPeriod", "allUsersGroupEnabled",
            "jitInactiveUserEnabled", "jitInactiveUserTtl")
VC_PROVIDER = ("name", "config_tag", "federation_type", "is_default", "domain_names", "upn_claim", "groups_claim")


def keep(obj: object, spec: tuple) -> object:
    """Only the fields `spec` names. A {field: spec} entry keeps that sub-object, or each item of that list, by its
    own spec, so a field the API adds later never reaches the record."""
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


def host_of(url: str | None) -> str | None:
    return urllib.parse.urlparse(url).hostname if url else None


def items(body: object, key: str | None = None) -> list:
    """The list in an answer: the answer itself, the list under `key` (a named key is authoritative), or the first."""
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        if key is not None:
            return body[key] if isinstance(body.get(key), list) else []
        return next((v for v in body.values() if isinstance(v, list)), [])
    return []


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


class Reader:
    """One plane's API under one credential. Every call is recorded with its answer, a refusal included; secrets are
    deleted from each body as it arrives; nothing raises."""

    def __init__(self, plane: str, base: str, headers: dict, calls: list):
        self.plane, self.base, self.headers, self.calls = plane, base, headers, calls

    def call(self, method: str, path: str, body: object = None, accept: str = "application/json",
             headers: dict | None = None, timeout: int = 60) -> object:
        rec = {"plane": self.plane, "method": method, "path": path, "status": None}
        self.calls.append(rec)
        data = json.dumps(body).encode() if body is not None else None
        h = {**self.headers, "Accept": accept, **(headers or {})}
        if data is not None:
            h["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data, headers=h, method=method)
        try:
            with urllib.request.urlopen(req, context=_ctx(), timeout=timeout) as r:
                rec["status"], raw = r.status, r.read()
        except urllib.error.HTTPError as e:
            rec["status"], rec["error"], rec["message"] = e.code, str(e.reason), _message(e)
            return None
        except (urllib.error.URLError, OSError) as e:
            rec["error"] = str(getattr(e, "reason", e))[:120]
            return None
        try:
            answer = json.loads(raw) if raw else {}
        except ValueError:
            return raw.decode(errors="replace")
        strip_secrets(answer)
        return answer

    def get(self, path: str, accept: str = "application/json") -> object:
        return self.call("GET", path, accept=accept)


def _message(e: urllib.error.HTTPError) -> str:
    """The server's own words for a refusal, printed for the operator and never recorded."""
    try:
        body = json.loads(e.read() or b"{}")
        return str(body.get("message") or body.get("error") or body)[:240] if isinstance(body, dict) else ""
    except (ValueError, OSError):
        return ""


def fleet_pages(ops: Reader, method: str, path: str, key: str, body: object = None) -> list:
    """Every page of a fleet IAM list: `page` counts from 0, and pageInfo.totalCount says when to stop."""
    out, page = [], 0
    while True:
        answer = ops.call(method, f"{path}?page={page}" if page else path, body)
        got = items(answer, key)
        out += got
        total = (answer.get("pageInfo") or {}).get("totalCount") if isinstance(answer, dict) else None
        if not got or not isinstance(total, int) or len(out) >= total:
            return out
        page += 1


def vcfa_pages(vcfa: Reader, path: str) -> list:
    out, page = [], 1
    while True:
        answer = vcfa.call("GET", f"{path}?page={page}&pageSize=128", accept=CLOUDAPI)
        out += items(answer, "values")
        if not isinstance(answer, dict) or page >= (answer.get("pageCount") or 1):
            return out
        page += 1


# ── credentials ──────────────────────────────────────────────────────────────────────────────────────────────────
def _form(url: str, fields: dict) -> dict:
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
    with urllib.request.urlopen(req, context=_ctx(), timeout=60) as r:
        return json.loads(r.read())


def ops_bearer() -> str:
    """A bearer for VCF Operations: the one in OPS_BEARER_FILE, or an API token traded at the broker for one."""
    if os.environ.get("OPS_BEARER_FILE"):
        return _secret("OPS_BEARER").removeprefix("Bearer ").strip()
    broker = os.environ.get("OPS_BROKER_HOST") or os.environ["OPS_HOST"]
    realm = os.environ.get("OPS_REALM", "CUSTOMER")
    answer = _form(f"https://{broker}/acs/t/{realm}/token",
                   {"grant_type": API_TOKEN_GRANT, "api_token": _secret("OPS_API_TOKEN")})
    return answer["access_token"]


def vcfa_bearer(host: str) -> str:
    if os.environ.get("VCFA_PROVIDER_BEARER_FILE"):
        return _secret("VCFA_PROVIDER_BEARER").removeprefix("Bearer ").strip()
    answer = _form(f"https://{host}/oauth/provider/token",
                   {"grant_type": "refresh_token", "refresh_token": _secret("VCFA_PROVIDER_REFRESH_TOKEN")})
    return answer["access_token"]


def vc_session(host: str, user: str, password: str, calls: list) -> Reader | None:
    vc = Reader(f"vcenter:{host}", f"https://{host}", {}, calls)
    basic = base64.b64encode(f"{user}:{password}".encode()).decode()
    sid = vc.call("POST", "/api/session", headers={"Authorization": f"Basic {basic}"})
    if not isinstance(sid, str):
        return None
    vc.headers["vmware-api-session-id"] = sid
    return vc


# ── the planes ───────────────────────────────────────────────────────────────────────────────────────────────────
def brokers(ops: Reader) -> list[dict]:
    """The identity plane's brokers. The fleet inventory lists an appliance; an embedded broker lives inside a
    management vCenter and appears only here."""
    found = [keep(v, BROKER) for v in items(ops.get(f"{IAM}/vidbs"), "vidbs")]
    return sorted(found, key=lambda b: b.get("fqdn") or "")


def realms(ops: Reader) -> list[dict]:
    """Each realm in full: the list carries a summary, the realm's own read carries its coverage and issues."""
    out = []
    for r in items(ops.get(f"{IAM}/ssorealms"), "ssoRealms"):
        detail = ops.get(f"{IAM}/ssorealms/{r['id']}")
        out.append(keep(detail if isinstance(detail, dict) and detail.get("id") else r, REALM))
    return sorted(out, key=lambda r: r.get("id") or "")


def provider(ops: Reader, idp_id: str) -> dict:
    """The realm's identity provider. Of a federated provider's URLs only the host is kept."""
    p = ops.get(f"{IAM}/identity-providers/{idp_id}")
    p = p if isinstance(p, dict) else {"id": idp_id}
    cfg = p.get("idpConfig") or {}
    out = keep(p, PROVIDER)
    hosts = {"discoveryHost": host_of((cfg.get("oidcConfiguration") or {}).get("discoveryEndpoint")),
             "metadataHost": host_of((cfg.get("samlConfiguration") or {}).get("metadataUrl"))}
    return {**out, **{k: v for k, v in hosts.items() if v}}


def identity_plane(ops: Reader) -> dict:
    """Brokers, realms and providers: the part of the fleet a reach check must leave unchanged."""
    rs = realms(ops)
    return {"brokers": brokers(ops), "realms": rs, "providers": [provider(ops, r["idpId"]) for r in rs if r.get("idpId")]}


def realm_clients(ops: Reader, realm_id: str) -> dict:
    """What can sign in to a realm without a person: API clients and their tokens, emergency clients, OAuth apps."""
    base = f"{IAM}/ssorealms/{realm_id}"
    apps = items(ops.get(f"{base}/oauth-apps"), "oauthApps")
    return {
        "realmId": realm_id,
        "api_clients": [keep(c, API_CLIENT) for c in fleet_pages(ops, "POST", f"{base}/api-clients/query", "apiClients", {})],
        "api_tokens": [keep(t, API_TOKEN) for t in fleet_pages(ops, "POST", f"{base}/api-tokens/query", "apiTokens", {})],
        "emergency_clients": [keep(e, EMERGENCY) for e in items(ops.get(f"{base}/emergency-clients"), "emergencyClients")],
        "oauth_apps": [{**keep(a, ("clientName", "clientId")),
                        "redirectHosts": sorted({h for h in map(host_of, a.get("redirectUrls") or []) if h})}
                       for a in apps],
    }


def fleet(ops: Reader) -> dict:
    """The whole fleet IAM plane, read once."""
    out = identity_plane(ops)
    out["directories"] = [{"idpId": p["id"], **keep(d, DIRECTORY)} for p in out["providers"]
                          for d in items(ops.get(f"{IAM}/identity-providers/{p['id']}/ldap-directories"), "ldapDirectories")]
    out["clients"] = [realm_clients(ops, r["id"]) for r in out["realms"]]
    out["auth_sources"] = [keep(a, AUTH_SOURCE) for a in
                           items(ops.call("POST", f"{IAM}/components/auth-sources/query", {}), "iamComponentAuthSources")]
    settings = ops.get(f"{IAM}/settings")
    out["settings"] = keep(settings, SETTINGS) if isinstance(settings, dict) else None
    out["roles"] = [keep(r, ("roleName", "type")) for r in fleet_pages(ops, "GET", f"{IAM}/roles", "vcfRoles")]
    return out


def organization(org: dict, ldap: dict, oauth: dict, saml: dict) -> dict:
    """One organization's ways in, from its own three settings reads. Of the OIDC issuer only the host is kept."""
    custom = ldap.get("customOrgLdapSettings") or {}
    return {"name": org.get("name"), "id": org.get("id"), "classic": org.get("isClassicTenant"),
            "providerConsumption": bool(org.get("isProviderConsumptionOrg")), "enabled": org.get("isEnabled"),
            "ldapMode": ldap.get("orgLdapMode"), "ldapHost": custom.get("hostName"), "ldapPort": custom.get("port"),
            "ldapSsl": custom.get("isSsl"), "oidc": bool(oauth.get("enabled")), "oidcVidb": bool(oauth.get("vidb")),
            "issuerHost": host_of(oauth.get("issuerId")), "saml": bool(saml.get("enabled"))}


def organizations(vcfa: Reader) -> list[dict]:
    """Every VCF Automation organization's LDAP, OIDC and SAML settings, read as the provider."""
    out = []
    for org in vcfa_pages(vcfa, "/cloudapi/1.0.0/orgs"):
        uid = str(org.get("id", "")).rsplit(":", 1)[-1]
        reads = [vcfa.get(f"/api/admin/org/{uid}/settings/{s}", VCD_JSON) for s in ("ldap", "oauth", "federation")]
        out.append(organization(org, *[r if isinstance(r, dict) else {} for r in reads]))
    return out


def supervisor_providers(vc: Reader, sid: str) -> list[dict]:
    """A Supervisor's identity providers. The list names each one; its issuer is only in the provider's own read."""
    base = f"/api/vcenter/namespace-management/supervisors/{sid}/identity/providers"
    out = []
    for i in items(vc.get(base)):
        d = vc.get(f"{base}/{i.get('provider')}")
        d = d if isinstance(d, dict) else i
        out.append({"display_name": d.get("display_name"), "provider": i.get("provider"),
                    "issuerHost": host_of(d.get("issuer_URL")), "username_claim": d.get("username_claim"),
                    "groups_claim": d.get("groups_claim")})
    return out


def vcenter(vc: Reader, host: str) -> dict:
    """A vCenter's identity providers, the host each one discovers its issuer at, and each Supervisor's providers."""
    providers = [{**keep(p, VC_PROVIDER), "discoveryHost": host_of((p.get("oidc") or {}).get("discovery_endpoint"))}
                 for p in items(vc.get("/api/vcenter/identity/providers"))]
    supervisors = [{"supervisor": s.get("supervisor"), "name": (s.get("info") or {}).get("name"),
                    "identity_providers": supervisor_providers(vc, s.get("supervisor"))}
                   for s in items(vc.get("/api/vcenter/namespace-management/supervisors/summaries"), "items")]
    return {"vcenter": host, "identity_providers": providers, "supervisors": supervisors}


def egress(ops: Reader, found: list[dict], url: str) -> list[dict]:
    """Ask each broker to fetch a SAML metadata URL itself (a request, not a read): 200 proves it reaches the
    identity provider; a failure says it does not."""
    out = []
    for b in found:
        answer = ops.call("POST", f"{IAM}/saml-metadata/validate", {"metadata": url, "vidbResourceId": b.get("id")},
                          timeout=120)
        last = ops.calls[-1]
        out.append({"broker": b.get("fqdn"), "status": last["status"], "error": last.get("error"),
                    "preferredBinding": answer.get("preferredBinding") if isinstance(answer, dict) else None})
    return out


def diff(before: object, after: object, at: str = "") -> list[str]:
    """The paths at which two reads differ; an empty list means they are the same."""
    if isinstance(before, dict) and isinstance(after, dict):
        return [p for k in sorted(set(before) | set(after)) for p in diff(before.get(k), after.get(k), f"{at}.{k}".lstrip("."))]
    if isinstance(before, list) and isinstance(after, list) and len(before) == len(after):
        return [p for i, (x, y) in enumerate(zip(before, after)) for p in diff(x, y, f"{at}[{i}]")]
    return [] if before == after else [at or "."]


def reach(ops: Reader, before: dict, url: str) -> dict:
    """The egress check with its proof of no change: the identity plane read before, the requests, the read after."""
    results = egress(ops, before["brokers"], url)
    after = identity_plane(ops)
    changed = {k: diff(before[k], after[k]) for k in ("brokers", "realms", "providers")}
    return {"metadata_url": url, "results": results, "unchanged": not any(changed.values()),
            "differences": {k: v for k, v in changed.items() if v}}


# ── what a reader should be able to explain ──────────────────────────────────────────────────────────────────────
def broker_kind(deployment_type: str | None) -> str:
    """The API's EXTERNAL is the instance broker; EMBEDDED lives inside a management vCenter."""
    return KIND.get(deployment_type or "", (deployment_type or "unknown").lower())


def broker_lines(f: dict) -> list[dict]:
    """Each broker, its kind, and the realm it holds: a broker holds one realm or none."""
    holder = {r.get("vidbResourceId"): r.get("name") for r in f.get("realms") or []}
    return [{"fqdn": b.get("fqdn"), "kind": broker_kind(b.get("deploymentType")), "realm": holder.get(b.get("id")),
             "healthy": b.get("healthy")} for b in f.get("brokers") or []]


def realm_lines(f: dict) -> list[dict]:
    """Each realm, the broker holding it, and the VCF instances it covers: whole instances, never part of one."""
    by_id = {b.get("id"): b for b in f.get("brokers") or []}
    out = []
    for r in f.get("realms") or []:
        b = by_id.get(r.get("vidbResourceId")) or {}
        cover = r.get("ssoRealmCoverage") or []
        out.append({"name": r.get("name"), "broker": b.get("fqdn"), "broker_kind": broker_kind(b.get("deploymentType")),
                    "instances": [c.get("name") for c in cover if c.get("ssoEntityType") == "VCF_INSTANCE"],
                    "components": r.get("totalConfiguredComponents"),
                    "issues": [i.get("name") for i in r.get("issues") or []]})
    return out


def provider_lines(f: dict) -> list[dict]:
    """Each realm's provider: what it is (type), how the broker speaks to it (protocol), how users arrive."""
    realm = {r.get("id"): r.get("name") for r in f.get("realms") or []}
    return [{"realm": realm.get(p.get("ssoRealmId")), "name": p.get("name"), "type": p.get("idpType"),
             "protocol": p.get("idpProtocol"), "provisioning": p.get("provisionType")} for p in f.get("providers") or []]


def directory_lines(p: dict, synced: list[dict]) -> list[dict]:
    """Each directory under a provider with the protocol and port the broker binds over. An LDAP provider names its
    domain controllers; a federated provider's directory has none, and its protocol is the provider's."""
    state = {d.get("ldapConfigurationId"): d for d in synced if d.get("idpId") == p.get("id")}
    out = []
    for c in (p.get("provisioningConfig") or {}).get("ldapConfigurations") or []:
        bind, d = c.get("ldapBindConfiguration") or {}, state.get(c.get("ldapConfigurationId")) or {}
        dc, second = bind.get("primaryDomainController") or {}, bind.get("secondaryDomainController")
        out.append({"name": c.get("name"), "domains": c.get("domains") or [], "protocol": dc.get("protocol"),
                    "port": dc.get("port"), "host": dc.get("host"),
                    "secondary": {k: second.get(k) for k in ("host", "protocol", "port")} if second else None,
                    "sync": d.get("lastSyncStatus"), "users": d.get("numberOfUsers"), "groups": d.get("numberOfGroups")})
    for d in p.get("directories") or []:
        out.append({"name": d.get("name"), "domains": d.get("domains") or [], "protocol": p.get("idpProtocol"),
                    "port": None, "host": None, "secondary": None, "sync": None, "users": None, "groups": None})
    return out


def token_line(t: dict) -> dict:
    """A token's two lifetimes, in minutes: the API token's own, and that of each bearer traded for it."""
    return {"name": t.get("tokenName"), "principal": t.get("principalName"), "status": t.get("tokenStatus"),
            "api_token_ttl_min": t.get("apiTokenTtl"), "access_token_ttl_min": t.get("accessTokenTtl")}


def client_lines(c: dict) -> list[dict]:
    """Each API client with its roles and the tokens issued to it."""
    out = []
    for a in c.get("api_clients") or []:
        ids = (a.get("clientId"), a.get("clientUuid"))
        mine = [t for t in c.get("api_tokens") or [] if t.get("tokenType") == "API_CLIENT"
                and (t.get("apiClientId") in ids or t.get("principalName") == a.get("clientId"))]
        out.append({"name": a.get("clientName") or a.get("clientId"),
                    "roles": [r.get("roleName") for r in a.get("roles") or []], "tokens": [token_line(t) for t in mine]})
    return out


def emergency_lines(c: dict) -> list[dict]:
    """The realm's emergency clients: the way in when the identity provider is down. None is an answer too."""
    return [{"name": e.get("clientName") or e.get("clientId"), "status": e.get("accessTokenStatus"),
             "access_token_ttl_min": e.get("accessTokenTtl")} for e in c.get("emergency_clients") or []]


def settings_line(s: dict) -> dict:
    """The fleet's token lifetimes, in minutes, and its two group switches."""
    return {"access_token_ttl_min": s.get("accessTokenTtl"), "api_token_ttl_min": s.get("apiTokenTtl"),
            "api_token_retention_min": s.get("apiTokenRetentionPeriod"), "all_users_group": s.get("allUsersGroupEnabled"),
            "jit_inactive_user_ttl_min": s.get("jitInactiveUserTtl") if s.get("jitInactiveUserEnabled") else None}


def sign_in(org: dict, broker_hosts: set) -> list[str]:
    """How an organization's people get in: VCF single sign-on (VCF Automation's own flag), OIDC to the broker or
    to another provider, SAML, the system or the organization's own LDAP; local accounts only if none."""
    ways = []
    if org.get("oidc"):
        ways.append("vcf-sso" if org.get("oidcVidb") else "oidc-broker" if org.get("issuerHost") in broker_hosts
                    else "oidc")
    if org.get("saml"):
        ways.append("saml")
    if org.get("ldapMode") in ("SYSTEM", "CUSTOM"):
        ways.append(f"ldap-{org['ldapMode'].lower()}")
    return ways or ["local"]


def issuer_kind(org: dict, broker_hosts: set) -> str | None:
    if not org.get("oidc"):
        return None
    host = org.get("issuerHost")
    return "broker" if host in broker_hosts else "entra" if host == "login.microsoftonline.com" else "other"


def org_lines(orgs: list[dict], broker_hosts: set) -> list[dict]:
    """Each organization's type and its ways in."""
    return [{"name": o.get("name"), "type": "classic" if o.get("classic") else "all-apps",
             "provider_consumption": o.get("providerConsumption"), "sign_in": sign_in(o, broker_hosts),
             "issuer": issuer_kind(o, broker_hosts)} for o in orgs]


def vcenter_lines(vcenters: list[dict], kinds: dict) -> list[dict]:
    """The broker each vCenter's default provider points at, and each Supervisor's issuers."""
    out = []
    for v in vcenters:
        default = next((p for p in v.get("identity_providers") or [] if p.get("is_default")), {})
        through = default.get("discoveryHost")
        out.append({"vcenter": v.get("vcenter"), "config_tag": default.get("config_tag"), "through": through,
                    "broker_kind": kinds.get(through, "not a broker") if through else None,
                    "supervisors": [{"name": s.get("name"), "issuers": [i.get("issuerHost") for i in s.get("identity_providers") or []]}
                                    for s in v.get("supervisors") or []]})
    return out


def summary(record: dict) -> dict:
    """The lines the census exists for, each from the plane that owns it."""
    f = record.get("fleet") or {}
    kinds = {b.get("fqdn"): broker_kind(b.get("deploymentType")) for b in f.get("brokers") or []}
    clients = f.get("clients") or []
    tokens = [t for c in clients for t in c.get("api_tokens") or []]
    egress_read = record.get("egress")
    return {
        "brokers": broker_lines(f),
        "realms": realm_lines(f),
        "providers": provider_lines(f),
        "directories": [d for p in f.get("providers") or [] for d in directory_lines(p, f.get("directories") or [])],
        "emergency_clients": [e for c in clients for e in emergency_lines(c)],
        "api_clients": [a for c in clients for a in client_lines(c)],
        "user_tokens": [token_line(t) for t in tokens if t.get("tokenType") == "USER"],
        "settings": settings_line(f.get("settings") or {}),
        "organizations": org_lines(record.get("organizations") or [], set(kinds)),
        "vcenters": vcenter_lines(record.get("vcenters") or [], kinds),
        "egress": None if not egress_read else {
            "reached": [{"broker": r.get("broker"), "status": r.get("status")} for r in egress_read["results"]],
            "unchanged": egress_read["unchanged"]},
    }


def _minutes(n: object) -> str:
    if not isinstance(n, int):
        return "?"
    return f"{n} min ({n / 1440:g} d)" if n >= 1440 else f"{n} min"


def spelled(value: str | None) -> str:
    """A domain as a vCenter grant spells it, in capitals. A placeholder stays as it is, so a redacted line still
    names the value its record replaced."""
    return value if not value or PLACEHOLDER.fullmatch(value) else value.upper()


def spellings(s: dict) -> str | None:
    """The two ways to spell a principal in a vCenter grant under this estate's realm: each bound directory's domain,
    which a broker session carries, and the realm's name, which a grant accepts and nobody signs in as."""
    if not s["realms"]:
        return None
    bound = sorted({x for d in s["directories"] if d["host"] for x in d["domains"] if x})
    return "vCenter grant spellings: " + "; ".join(
        [f"{spelled(x)}\\<name> (directory)" for x in bound]
        + [f"{spelled(r['name'])}\\<name> (realm, inert)" for r in s["realms"]])


def _token_text(t: dict) -> str:
    return (f"token {t['name']} {t['status']}: API token {_minutes(t['api_token_ttl_min'])}, "
            f"access token {_minutes(t['access_token_ttl_min'])}")


def report(s: dict) -> list[str]:
    """The summary as the lines the census prints."""
    n = Counter(b["kind"] for b in s["brokers"])
    lines = [f"Brokers, from the identity plane: {len(s['brokers'])} "
             f"({', '.join(f'{v} {k}' for k, v in sorted(n.items()))})"]
    lines += [f"  {b['fqdn']}  {b['kind']}  " + (f"holds realm {b['realm']}" if b["realm"] else "holds no realm")
              + ("" if b["healthy"] else "  NOT HEALTHY") for b in s["brokers"]]
    lines += [f"Realm {r['name']} on the {r['broker_kind']} broker {r['broker']}: covers {len(r['instances'])} VCF "
              f"instance(s) ({', '.join(r['instances'])}), {r['components']} component(s); "
              f"issues: {', '.join(r['issues']) or 'none'}" for r in s["realms"]]
    lines += [f"Provider {p['name']}: type {p['type']}, protocol {p['protocol']}, provisioning {p['provisioning']}"
              for p in s["providers"]]
    for d in s["directories"]:
        where = f" to {d['host']}" if d["host"] else ""
        extra = f"; secondary {d['secondary']['protocol']} port {d['secondary']['port']}" if d["secondary"] else ""
        sync = f"; sync {d['sync']}, {d['users']} users, {d['groups']} groups" if d["sync"] else ""
        lines.append(f"  directory {d['name']} ({', '.join(d['domains'])}): {d['protocol']} "
                     f"port {d['port'] or 'none'}{where}{extra}{sync}")
    if spellings(s):
        lines.append(spellings(s))
    lines.append("Emergency client: " + (", ".join(
        f"{e['name']} ({e['status']}, access token {_minutes(e['access_token_ttl_min'])})"
        for e in s["emergency_clients"]) or "none"))
    lines.append(f"API clients: {len(s['api_clients'])}")
    lines += [f"  {c['name']}: roles {', '.join(c['roles']) or 'none'}; "
              + ("; ".join(_token_text(t) for t in c["tokens"]) or "no token") for c in s["api_clients"]]
    lines += [f"User API token of {t['principal']}: {_token_text(t)}" for t in s["user_tokens"]]
    st = s["settings"]
    lines.append(f"Fleet settings: access token {_minutes(st['access_token_ttl_min'])}, API token "
                 f"{_minutes(st['api_token_ttl_min'])}, retention {_minutes(st['api_token_retention_min'])}, "
                 f"all-users group {'on' if st['all_users_group'] else 'off'}")
    if s["organizations"]:
        lines.append(f"Organizations: {len(s['organizations'])}")
        lines += [f"  {o['name']}  {o['type']}{', provider consumption' if o['provider_consumption'] else ''}: "
                  f"{', '.join(o['sign_in'])}" + (f" (issuer: {o['issuer']})" if o["issuer"] else "")
                  for o in s["organizations"]]
    for v in s["vcenters"]:
        through = f"{v['through']} ({v['broker_kind']})" if v["through"] else "no default provider"
        sups = "; ".join(f"Supervisor {x['name']}: {', '.join(i or '?' for i in x['issuers']) or 'no provider'}"
                         for x in v["supervisors"])
        lines.append(f"vCenter {v['vcenter']} signs in through {through}" + (f"; {sups}" if sups else ""))
    if s["egress"]:
        got = ", ".join(f"{r['broker']} {r['status'] or 'no answer'}" for r in s["egress"]["reached"])
        lines.append(f"Egress (each broker fetched the metadata URL): {got}; identity plane "
                     + ("unchanged" if s["egress"]["unchanged"] else "CHANGED, see the record"))
    return lines


# ── the record contract: every estate value replaced, or nothing written ─────────────────────────────────────────
# Product vocabulary is never registered, so it is never replaced and never mistaken for a surviving value. It is
# matched without regard to case (vCenter spells its OIDC config tag "Oidc"), and it includes every way in, protocol,
# kind and type the census prints: a type is not an identity.
PRODUCT = {w.lower() for w in (
    "CUSTOMER", "System", "admin", "Administrator", "Administrators", "default", "vsphere.local", "localos",
    "login.microsoftonline.com", "graph.microsoft.com",
    "Automation Appliance", "Operations Appliance", "VCF Operations for Networks", "VCF Operations for Logs",
    "oidc", "saml", "ldap", "ldaps", "ldap_bind", "vcf-sso", "oidc-broker", "ldap-system", "ldap-custom", "local",
    "classic", "all-apps", "instance", "embedded", "external", "broker", "entra", "other", "unknown",
    "adldap", "openldap", "entra_id", "okta", "ping", "adfs", "symantec_idsp", "jit", "scim",
    "active_directory_ldap")}
# Fields whose value is an estate value of a known kind; anything shaped like one, anywhere, is registered too.
FIELDS = {"fqdn": "host", "host": "host", "domainControllerHost": "host", "ldapHost": "host", "issuerHost": "host",
          "discoveryHost": "host", "metadataHost": "host", "redirectHosts": "host", "vcenter": "host",
          "id": "id", "vcfInstanceId": "id", "vidbResourceId": "id", "idpId": "id", "ssoRealmId": "id", "realmId": "id",
          "ldapConfigurationId": "id", "vcfComponentId": "id", "clientUuid": "id", "supervisor": "id",
          "name": "name", "displayName": "name", "display_name": "name", "clientName": "name", "clientId": "name",
          "apiClientId": "name", "tokenName": "name", "principalName": "name", "certificateName": "name",
          "domains": "domain", "defaultDomain": "domain", "domain_names": "domain", "baseDn": "dn", "bindDn": "dn",
          "roleName": "role"}
PATTERNS = [("id", re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")),
            ("host", re.compile(r"\b[a-z0-9-]+(?:\.[a-z0-9-]+)+\.[a-z]{2,}\b", re.I)),
            ("ip", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
            ("name", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)*\b"))]
NOT_SHAPED = {"version"}  # a version string is shaped like an address and is not one
PLACEHOLDER = re.compile(r"\{\{[a-z-]+-\d+\}\}")


def _strings(obj: object, field: str | None = None):
    """Every (field, string) in a record, the field being the key the string sits under."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _strings(v, k)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v, field)
    elif isinstance(obj, str):
        yield field, obj


def estate_values(record: dict, given: list[tuple[str, str]]) -> dict[str, str]:
    """Each estate value in the record, and each the reader was given (hosts, a user, the metadata URL), mapped to
    its placeholder. Organizations first, then by field, then anything shaped like an id, host, address or user."""
    table, seen, count = {}, set(), Counter()
    built_in = {str(r.get("roleName")).lower() for r in (record.get("fleet") or {}).get("roles") or [] if r.get("type") == "BUILT_IN"}
    spare = PRODUCT | built_in

    def add(value: str, kind: str) -> None:
        if value and len(value) >= 3 and value.lower() not in spare and value.lower() not in seen:
            seen.add(value.lower())
            count[kind] += 1
            table[value] = f"{{{{{kind}-{count[kind]}}}}}"

    for o in record.get("organizations") or []:
        add(o.get("name"), "org")
    for value, kind in given:
        add(value, kind)
    for part in ("fleet", "organizations", "vcenters", "egress", "calls", "summary"):
        for field, s in _strings(record.get(part)):
            if field in FIELDS:
                add(s, FIELDS[field])
    for field, s in _strings(record):
        if field not in NOT_SHAPED:
            for kind, rx in PATTERNS:
                for m in rx.findall(s):
                    add(m, kind)
    return table


def _pattern(table: dict) -> re.Pattern | None:
    """One alternation, longest first, matched only where it is not part of a longer word."""
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
    value under an identity field that is not a placeholder, so a value the registration missed is caught too."""
    rx, found = _pattern(table), []
    kind_of = {k.lower(): v.strip("{}").rsplit("-", 1)[0] for k, v in table.items()}
    roles = (obj.get("fleet") or {}).get("roles") or [] if isinstance(obj, dict) else []
    spare = PRODUCT | {str(r.get("roleName")).lower() for r in roles if r.get("type") == "BUILT_IN"}
    for field, s in _strings(obj):
        rest = PLACEHOLDER.sub(" ", s)  # a placeholder's own letters are not a surviving value
        found += [kind_of[m.group(0).lower()] for m in rx.finditer(rest)] if rx else []
        if field not in NOT_SHAPED:
            found += [kind for kind, p in PATTERNS for m in p.findall(rest) if m.lower() not in PRODUCT]
        if field in FIELDS and len(s) >= 3 and s.lower() not in spare and re.search(r"[A-Za-z0-9]", rest):
            found.append(FIELDS[field])
    return found


# ── the run ──────────────────────────────────────────────────────────────────────────────────────────────────────
def census(egress_url: str | None, ops_token: str, vcfa_token: str | None) -> dict:
    """Read every plane the environment names; the egress check, when asked, runs straight after the fleet read."""
    calls: list = []
    record = {"captured": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "sent": [], "fleet": {},
              "organizations": [], "vcenters": [], "egress": None, "calls": calls}
    ops = Reader("vcf-operations", f"https://{os.environ['OPS_HOST']}/suite-api", {"Authorization": f"Bearer {ops_token}"}, calls)
    record["fleet"] = fleet(ops)
    if egress_url:
        record["sent"].append("POST /suite-api/api/fleet-management/iam/saml-metadata/validate, once per broker")
        record["egress"] = reach(ops, record["fleet"], egress_url)
    if vcfa_token:
        vcfa = Reader("vcf-automation", f"https://{os.environ['VCFA_HOST']}", {"Authorization": f"Bearer {vcfa_token}"}, calls)
        record["organizations"] = organizations(vcfa)
    hosts = [h.strip() for h in os.environ.get("VC_HOSTS", "").split(",") if h.strip()]
    if hosts:
        record["sent"].append("POST and DELETE /api/session on each vCenter: a session opened and closed")
    for host in hosts:
        vc = vc_session(host, os.environ["VC_USER"], _secret("VC_PASSWORD"), calls)
        if vc:
            record["vcenters"].append(vcenter(vc, host))
            vc.call("DELETE", "/api/session")
    record["summary"] = summary(record)
    record["exit"] = 1 if failed(calls) else 0
    return record


def failed(calls: list[dict]) -> list[dict]:
    return [c for c in calls if c["status"] is None or c["status"] >= 400]


def unread(bad: list[dict]) -> str | None:
    """A refused fleet read leaves its lines counting nothing: 0 brokers, no emergency client. Said first, so a count
    is never read as the estate's when the identity plane did not answer."""
    n = sum(1 for c in bad if c.get("plane") == "vcf-operations")
    return (f"NOT READ: {n} fleet identity read(s) refused or failed; a line below that counts 0 or none is unread, "
            "not empty. The credential's role must read the fleet identity plane.") if n else None


def given_values(egress_url: str | None) -> list[tuple[str, str]]:
    hosts = [os.environ.get(k, "") for k in ("OPS_HOST", "OPS_BROKER_HOST", "VCFA_HOST")]
    hosts += os.environ.get("VC_HOSTS", "").split(",")
    out = [(h.strip(), "host") for h in hosts if h.strip()]
    out += [(os.environ.get("VC_USER", ""), "name")] + ([(egress_url, "metadata-url")] if egress_url else [])
    return [(v, k) for v, k in out if v]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Read a VCF 9.1 estate's identity model, read-only by default.")
    ap.add_argument("--redact", action="store_true", help="print with placeholders instead of your names")
    ap.add_argument("--egress-metadata-url", metavar="URL",
                    help="ask each broker to fetch this SAML metadata URL (sends one request per broker)")
    a = ap.parse_args(argv)
    if not os.environ.get("OPS_HOST") or not (os.environ.get("OPS_BEARER_FILE") or _secret("OPS_API_TOKEN")):
        print("OPS_HOST and a VCF Operations credential (OPS_API_TOKEN_FILE or OPS_BEARER_FILE) are required", file=sys.stderr)
        return 2
    if a.egress_metadata_url:
        print("--egress-metadata-url: each broker will be asked to fetch the URL; this sends a request per broker")
    try:
        ops_token = ops_bearer()
        vcfa_token = vcfa_bearer(os.environ["VCFA_HOST"]) if os.environ.get("VCFA_HOST") else None
    except (urllib.error.URLError, OSError, KeyError, ValueError) as e:
        print(f"could not obtain a credential: {type(e).__name__} {getattr(e, 'code', '')}".rstrip(), file=sys.stderr)
        return 1
    record = census(a.egress_metadata_url, ops_token, vcfa_token)
    bad = failed(record["calls"])
    table = estate_values(record, given_values(a.egress_metadata_url))
    clean = scrub({**record, "calls": [{k: v for k, v in c.items() if k != "message"} for c in record["calls"]]}, table)
    left = leaks(clean, table)
    out = os.environ.get("OUT", "census.json")
    if not (left and a.redact):  # a redacted print with a surviving value would print that value
        shown = clean if a.redact else record
        print("\n".join(([unread(bad)] if unread(bad) else []) + report(shown["summary"])))
        for c, shown_call in zip(bad, failed(shown["calls"])):
            print(f"FAILED {shown_call['plane']} {c['method']} {shown_call['path']}: {c['status'] or ''} "
                  f"{c.get('error') or ''} {'' if a.redact else c.get('message') or ''}".rstrip())
    if left:
        print(f"refusing to write {out}: {len(left)} estate value(s) survived the scrub ({', '.join(sorted(set(left)))})",
              file=sys.stderr)
        return 2
    with open(out, "w", encoding="utf-8") as f:
        f.write(json.dumps(clean, indent=1, ensure_ascii=False) + "\n")
    print(f"\n{len(record['calls'])} call(s), {len(bad)} failed; {out} written with every estate value replaced")
    return record["exit"]


if __name__ == "__main__":
    sys.exit(main())
