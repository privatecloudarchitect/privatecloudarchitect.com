# An integration's own identity, and who signs in to vCenter

Companion to the chapter
([privatecloudarchitect.com/handbook/integrations-identity](https://privatecloudarchitect.com/handbook/integrations-identity)):
three scripts. `vcenter_exchange.py` reads every vCenter's session list, so an integration still signing in as a person's
directory account shows up beside the machine identities, and takes a VCF single sign-on API client through each
vCenter's token exchange into a REST and a SOAP session. `api_client.py` makes the API client an integration moves to,
with one role and a token whose two lifetimes are set, and removes it when the integration retires.
`service_account.py` does the same in VCF Automation: one service account with one role, activated through the device
grant, and revoked and removed when the integration retires. Standard library Python only. No token, assertion or
password is printed or written.

| File | What it is |
|---|---|
| `vcenter_exchange.py` | The session census and the exchange. Read-only. Writes `exchange.json` with every estate name replaced, and refuses to write a record in which one survived. |
| `api_client.py` | One API client for one integration: plan it (the default), create it, remove it. Writes `api_client.json` the same way. |
| `exchange.json` | The census and the exchange on the reference estate, 2026-10-13, read as an API client. The chapter's plates render it. |
| `api_client.json`, `api_client_teardown.json` | One throwaway client made and removed on the reference estate, 2026-10-13. |
| `service_account.py` | One VCF Automation service account for one integration: plan it (the default), create it, revoke and remove it. Writes `service_account.json` the same way. |
| `service_account.json`, `service_account_teardown.json` | One throwaway service account made, revoked and removed in a throwaway All Apps organization on the reference estate, 2026-10-13. |
| `expected-output.md` | The transcripts of those runs, with what to read in them. |

## Start here: the census, with no API client

The census needs no API client, so it can run before one exists. It reads the session list as an account you name.

```bash
export VC_HOSTS=<vcenter-fqdn>[,<another>]
export VC_USER=<user@domain>                        # an account that may read every session
export VC_PASSWORD_FILE=/path/to/password           # mode 0600
export DIRECTORY_DOMAINS=<directory domain>[,<another>]   # as vCenter spells it
export TLS_VERIFY=false                             # only on a self-signed lab CA

python3 vcenter_exchange.py --sessions --redact     # the census, printed with placeholders, for a transcript you will share
```

The census flags every directory-account session from a client other than the vSphere Client: a REST integration on
a password (`vAPI`, `curl`, a product's own agent) as much as a vSphere SDK. On the reference estate the vSphere Client's
sessions read `vSphereUI`, and that is the only agent the census treats as a person's; name others in
`INTERACTIVE_AGENTS` (comma-separated, versions left off) only for a client people sign in from by hand. A person who
signs in with PowerCLI is flagged too, and is cleared by confirming who it is.

The census reads vCenter only. NSX, VCF Operations, the SDDC Manager API and VCF Automation each keep their own
sign-ins, and it does not read them.

## Then as the API client

With an API client's credential and no `VC_USER`, the same command takes the client through each vCenter's exchange and
reads the session lists as the client's own session, so a scheduled census runs as a machine identity rather than on a
person's password.

```bash
unset VC_USER VC_PASSWORD_FILE                      # the census then reads as the client
export BROKER_HOST=<identity-broker-fqdn>           # trades the API client's token for a bearer
export API_TOKEN_FILE=/path/to/api-token            # mode 0600; the API client's API token
# or, instead of the API token: export BEARER_FILE=/path/to/bearer   (a broker bearer you already hold)

python3 vcenter_exchange.py                         # the exchange and both sessions, on every vCenter
python3 vcenter_exchange.py --sessions --redact     # and the census, read as the client
```

**Which role the census needs, as tested.** On the reference estate an API client holding `vcf_viewer` at realm scope
saw only its own session in every vCenter's session list, on three of three vCenters; the same client rebound to
`vcf_administrator` read every list. A role between the two was not tried, nor a vCenter outside VCF single sign-on. A
list that holds only the census's own session is reported as a failed read (exit 1), never as an empty estate. If the
census's client holds `vcf_administrator`, give it nothing else to do and keep its token on its own rotation.

`BROKER_TENANT` (the broker tenant, default `CUSTOMER`), `INTERACTIVE_AGENTS` (default `vSphereUI`), `LOCAL_DOMAIN`
(the vCenter's own SSO domain, default `VSPHERE.LOCAL`) and `OUT` (default `exchange.json`) are optional. `VC_PASSWORD`
and `API_TOKEN` are read when their `_FILE` forms are unset.

**The broker tenant is not the realm's name.** The broker tenant is the realm's path segment in the broker's token URL,
`CUSTOMER` unless your broker says otherwise, and an API client's vCenter session carries it as its domain:
`CUSTOMER\<client id>`. The realm's name is the broker realm as the fleet identity plane names it, and a vCenter grant
spelled with it in capitals applies to nobody; that is the string `REALM_DOMAIN` takes in vcenter-authorization's
`authz.py`. This script reads `BROKER_TENANT` (`BROKER_REALM`, its earlier name, is still read), takes the tenant from
the client's own session when one is opened, and only notes a `REALM_DOMAIN` left in the shell. Whether a grant spelled
`CUSTOMER\<name>` applies to anyone was not tested.

| Exit | Means |
|---|---|
| 0 | every vCenter took the client through both sessions (when a client is given), and with `--sessions` every directory-account session is from the vSphere Client and the local administrator signs in from no other client |
| 1 | a vCenter refused the client, a read failed, or the census's identity could read only its own session |
| 2 | a usage error, or the record was refused because an estate value survived the scrub; nothing is written |
| 3 | `--sessions` found a directory account signing in from a client other than the vSphere Client: an integration on a person's or a directory account's password, until its owner says otherwise |
| 4 | `--sessions` found the local administrator signing in from a client other than the vSphere Client, and nothing worse: an account in automated use is not a break-glass account |

The exit reads each session list at one moment. An integration that is not signed in at that moment is not seen, so
the gate before the broker federates is exit 0 on several days, with every remaining directory session owned and
confirmed as a person.

## The API client an integration moves to: `api_client.py`

Plan first. With no `--execute` it prints every call it would send, with its body, and sends nothing.

```bash
export OPS_HOST=<vcf-operations-fqdn>
export OPS_API_TOKEN_FILE=/path/to/ops-api-token    # mode 0600; your own VCF Operations API token, of a user who may manage API clients
export TLS_VERIFY=false                             # only on a self-signed lab CA

python3 api_client.py --client-id backup-01 --role vcf_viewer --api-token-ttl 43200 --access-token-ttl 60
python3 api_client.py --client-id backup-01 --role vcf_viewer --api-token-ttl 43200 --access-token-ttl 60 \
    --token-file /path/to/backup-01-token --execute
python3 api_client.py --client-id backup-01 --rotate --api-token-ttl 43200 --access-token-ttl 60 \
    --token-file /path/to/backup-01-token-new --old-token-file /path/to/backup-01-token --execute   # before the old one ends
python3 api_client.py --client-id backup-01 --teardown              # the teardown's plan
python3 api_client.py --client-id backup-01 --teardown --execute    # when the integration retires
```

| Flag | What it does |
|---|---|
| `--client-id ID` | the client's id, also its name; one per integration (required) |
| `--role ROLE` | the one VCF role the client holds, at realm scope, for example `vcf_viewer` (required to create) |
| `--api-token-ttl MIN` | the API token's lifetime in minutes, 1,440 to 259,200 (required to create) |
| `--access-token-ttl MIN` | the lifetime in minutes of each bearer the token yields, 30 to 60 (required to create) |
| `--token-file PATH` | where the token is written, mode 0600; the file must not exist (required with `--execute`) |
| `--description TEXT` | the client's description (default `an integration's own identity`) |
| `--rotate` | issue the client a new token with both lifetimes, prove it, then delete every token it held before (needs both lifetimes and `--token-file`; no `--role`) |
| `--old-token-file PATH` | with `--rotate`: the token the integration holds now, shown trading before the delete and refused after it |
| `--teardown` | remove the client and its tokens instead of creating them |
| `--execute` | send the calls; without it the plan is printed |
| `--redact` | print with placeholders instead of your host and client id |

| Env | Meaning |
|---|---|
| `OPS_HOST` | the VCF Operations FQDN (required to execute) |
| `OPS_API_TOKEN_FILE` | your VCF Operations API token, mode 0600 (`OPS_API_TOKEN` is read if it is unset), traded at the broker for a bearer |
| `OPS_BROKER_HOST` | the broker that trades it (default `OPS_HOST`) |
| `BROKER_TENANT` | the broker tenant, the realm's path segment in the broker's token URL (default `CUSTOMER`; `OPS_REALM`, its earlier name, is still read) |
| `OPS_BEARER_FILE` | instead of the API token, a bearer you already hold |
| `TLS_VERIFY` | `false` only on a self-signed lab CA |
| `OUT` | the record (default `api_client.json`) |

| Exit | Means |
|---|---|
| 0 | the plan printed; or the run held on read-back: the client with its one role and an active token with both lifetimes; for a rotation, the new token proved, one token left and, when given, the old token refused; for a teardown, no client and no token left |
| 1 | a call failed, or the read-back did not hold; a create that stopped part way prints where it stopped and the teardown to run before trying again |
| 2 | a usage error, a refusal before anything is sent (a lifetime outside the bounds, a token file that exists), a client that already exists (refused, never adopted), for a rotation a client that does not exist, or the record was refused because an estate value survived the scrub |

### What it sends, and in what order

Every path is under `/api/fleet-management/iam` on VCF Operations.

1. `GET /ssorealms`: the realm's id. Then a query of the realm's API clients; a client with the id you gave is refused,
   so a run cannot take over an identity someone else made.
2. `POST /ssorealms/{realm}/api-clients` with `clientId`, `clientName` and `clientDescription`.
3. `PUT /ssorealms/{realm}/principals/{client uuid}/roles`: one role, `scopeType` `SSO_REALM`.
4. `POST /ssorealms/{realm}/api-tokens` with `tokenType` `API_CLIENT`, `apiTokenTtl` and `accessTokenTtl` in minutes. The
   token is written to `--token-file`, created exclusively at mode 0600, and never printed.
5. The token traded at the broker once (`POST /acs/t/{realm}/token`, the API token grant), to prove it; the record keeps
   the status, the bearer's principal type and its lifetime, never the bearer.
6. The client and its token read back: present, its roles and their scope, the token's status and both lifetimes.

A rotation queries the client and the tokens it holds, and refuses a client that is not there (it never creates
one). It then issues a new token (`POST /ssorealms/{realm}/api-tokens`, a name stamped with the time, both lifetimes),
writes it to `--token-file` and trades it at the broker once. With `--old-token-file` it trades the old token too, so
the record shows both working in the overlap. Only once the new token has traded does it delete each token the client
held before; with `--old-token-file` it trades the old token again, which must be refused, and it reads back that one
token is left. If the new token does not trade, the old ones are kept and the run stops with exit 1. Point the
integration at the new token between the issue and the delete, or run the rotation in two steps: the issue, then the
delete once the integration has switched.

A teardown queries the client's tokens and deletes each, deletes the client, then reads both lists again and records
the residue. A teardown of a client that is not there removes nothing and exits 0, so it is safe to re-run.

## The VCF Automation service account an integration moves to: `service_account.py`

In VCF Automation an integration signs in as a service account of its own. Plan first: with no `--execute` it prints
every call it would send, with its body, and sends nothing. The role is the role's name in the organization, never its
id; the script refuses an id.

```bash
export VCFA_HOST=<vcf-automation-fqdn>
export VCFA_PROVIDER_REFRESH_TOKEN_FILE=/path/to/provider-api-token   # mode 0600; or VCFA_PROVIDER_BEARER_FILE
export TLS_VERIFY=false                                               # only on a self-signed lab CA

python3 service_account.py --org tenant-a --name backup-01 --role "Organization User"
python3 service_account.py --org tenant-a --name backup-01 --role "Organization User" \
    --token-file /path/to/backup-01-refresh-token --execute
python3 service_account.py --org tenant-a --name backup-01 --teardown --token-file /path/to/backup-01-refresh-token --execute
```

| Flag | What it does |
|---|---|
| `--org ORG` | the organization's name (required) |
| `--name NAME` | the service account's name; one per integration (required) |
| `--role "ROLE NAME"` | the one role it holds, by name, for example `Organization User` in an All Apps organization or `Organization Member` in a classic one (required to create) |
| `--token-file PATH` | where the refresh token is written, mode 0600; the file must not exist (required with `--execute` to create). With `--teardown`, the token to refresh once after the revoke, to show it is refused |
| `--teardown` | revoke the account's token and delete the account instead |
| `--execute` | send the calls; without it the plan is printed |
| `--redact` | print with placeholders instead of your host, organization and account name |

| Env | Meaning |
|---|---|
| `VCFA_HOST` | the VCF Automation FQDN (required to execute) |
| `VCFA_PROVIDER_REFRESH_TOKEN_FILE` | a provider API token, mode 0600, traded at `/oauth/provider/token` for a bearer |
| `VCFA_PROVIDER_BEARER_FILE` | instead, a provider bearer you already hold |
| `TLS_VERIFY` | `false` only on a self-signed lab CA |
| `OUT` | the record (default `service_account.json`) |

| Exit | Means |
|---|---|
| 0 | the plan printed; or the run held on read-back: the account active, its bearer's session holding exactly the role, the stored token refreshing; or, for a teardown, no account left and the revoked token refused |
| 1 | a call failed, or the read-back did not hold; a create that stopped part way prints where it stopped and the teardown to run before trying again |
| 2 | a usage error, a refusal before anything is sent (a role given as an id, a token file that exists), an account that already exists (refused, never adopted), or the record was refused because an estate value survived the scrub |

### What it sends, and in what order

1. `GET /cloudapi/1.0.0/orgs` filtered by name: the organization's id, which every organization-scoped call carries in
   `X-VMWARE-VCLOUD-TENANT-CONTEXT`. Then the organization's service accounts filtered by name; one with the name you
   gave is refused.
2. `POST /oauth/tenant/{org}/register` with `client_name`, a new `software_id`, `software_version` and `scope`
   `urn:vcloud:role:<the role's name, URL-encoded>`.
3. `POST /oauth/tenant/{org}/device_authorization` with the new `client_id`: a device code and a user code.
4. `POST /cloudapi/1.0.0/deviceLookup/grant` with the user code: you, as the provider, grant it.
5. `POST /oauth/tenant/{org}/token` with the device-code grant, polled until the grant lands: a refresh token and a
   bearer. The refresh token is written to `--token-file`, created exclusively at mode 0600, and never printed.
6. `GET /cloudapi/1.0.0/sessions/current` with the bearer: the session's principal and roles.
7. One refresh with the stored token (`grant_type=refresh_token`, with the `client_id`), as the integration will make
   it. When the answer carries a new refresh token, it is written over the stored one.
8. The account read back: present, its status, its roles and whether rotation is required on every refresh.

A teardown revokes the account's token (`POST /cloudapi/1.0.0/serviceAccounts/{id}/revoke`), deletes the account, reads
the list until it is empty, and with `--token-file` refreshes once with the revoked token to show it is refused. A
teardown of an account that is not there removes nothing and exits 0, so it is safe to re-run.

## What `vcenter_exchange.py` does, and in what order

1. `GET /api/vcenter/datacenter` with the broker's bearer as presented. vCenter refuses it; that is the expected answer,
   and the record keeps the status.
2. `POST /api/vcenter/authentication/token`, form-encoded, with the access token alone. vCenter answers a SAML token of
   the Bearer type that lives minutes.
3. `POST /api/session` with `Authorization: SIGN token="<base64(gzip(assertion))>"`: who the session is, whether it reads
   the VM list, then `DELETE /api/session`.
4. A second exchange, then `SessionManager.LoginByToken` over SOAP with the assertion in a WS-Security header, its XML
   declaration removed: who the session is, then `Logout`.
5. With `--sessions`: a SOAP session as `VC_USER` or, without it, a third exchange and `LoginByToken` as the client;
   `SessionManager.sessionList` read with `RetrievePropertiesEx`, the census's own session left out by its key, then
   `Logout`.

Steps 1 to 4 run only when an API client's credential is given.

## Scope, stated plainly

- `vcenter_exchange.py` is read-only. It opens sessions and closes them, and changes no configuration. The token
  exchanges mint tokens that live minutes and are not stored.
- `api_client.py` writes only with `--execute`: one client, one role binding, one token, or their removal. A create
  refuses a client id that exists; a teardown removes the client you name and its tokens, so name only one you made.
- The lifetime bounds are the ones the broker held a create to on the reference estate, not documented ranges.
- A rotation was run once, on VCF 9.1.1: the client held two active tokens in the overlap, the old token traded before
  the delete and was refused after it (HTTP 400). The fleet API's in-place regenerate
  (`POST /ssorealms/{realm}/api-tokens/{token id}/regenerate`), called outside the script in the same run, answered a
  token under a new id with a new end date, and the value from before was refused three seconds later: it leaves no
  overlap, so the script does not use it. How long an overlap may last is bounded only by the old token's own end date,
  which was not waited out.
- `service_account.py` writes only with `--execute`: one service account and its token, or their revocation and
  removal. Rotation: the account read back with rotation required on every refresh, and each refresh returned a new
  refresh token, which the script stores. In the same run the token a refresh had replaced still refreshed, so retire
  an account by revoking it, never by deleting the file that holds its token. One run, in one All Apps organization;
  how long a replaced token keeps working was not read.
- Read as an API client, the census needs a role that sees every session: VCF Viewer saw only its own, VCF
  Administrator read every list. That makes the census client an administrator on every vCenter, so hold it as tier-0.
  On one vCenter, a directory account holding a role of `Sessions.TerminateSession` on the root folder read every session
  and read only its own without it; by its name that privilege also ends sessions, which was not exercised here, and
  carrying it to an API client takes a custom VCF role bundling a custom vCenter role, which was not built here.
- The census reads vCenter only. VCF Automation's API reference lists the caller's own sessions and an audit trail of
  events, and no session list for every user was found in it; VCF Operations' lists a system audit report and a call
  that ends the caller's own session, and no session list; whether either audit records each sign-in was not read. NSX
  and SDDC Manager were not searched.
- The census classifies each session by its principal's domain: the broker tenant is an API client, a domain in
  `DIRECTORY_DOMAINS` is a directory account, the vCenter's own SSO domain is a local account (the local administrator
  apart, and accounts named `svc-` counted as VCF's integration accounts). Each session's client agent is recorded
  without its version. Every agent but `vSphereUI` counts as a program; that rule comes from the agents seen on the
  reference estate's lists, where the one session from the vSphere Client read `vSphereUI`, not from a vendor list, so
  read the agents yourself.
- No local account is named in the record, because a local account's name can carry estate names; the census counts
  them. Directory accounts and API clients are recorded as placeholders, with their agents.
- A session list shows what is signed in at the moment of the read. Run it on several days, and on a schedule, before
  you conclude that no integration signs in as a person.
- Measured on VCF 9.1.1 (three vCenters, build 25712839), 2026-10-13: the exchange with an API client holding
  `vcf_viewer`; the census read as that client holding `vcf_administrator`, and once with no API client, as a directory
  account's password. `api_client.py` ran on a VCF Operations API token held by the estate's administrator; which
  narrower operator role may manage API clients was not tried, nor `OPS_BEARER_FILE`, nor a broker federated to a
  cloud provider. `service_account.py` ran on VCF Automation 9.1.1 with a provider bearer, in a throwaway All Apps
  organization federated to Entra ID, as `Organization User`; a classic organization and
  `VCFA_PROVIDER_REFRESH_TOKEN_FILE` were not tried with it.

## Reading the records

`exchange.json`: `summary` holds the lines the run exists for: `census_as` (`client` or `password`), `client_tried` and
`client_took_both_sessions` of `vcenters`, `bearer_as_presented` (the statuses seen), `saml_lifetime_s`, `session_users`
(who the client's sessions were), and with `--sessions` `sessions_read`, `census_only_own_session`, `sessions_by_class`,
`local_administrator_by_agent`, `local_administrator_not_interactive` (its sessions from clients other than the vSphere
Client), `directory_principals` and `directory_not_interactive`. `broker_tenant`, when present, records a tenant the
client's own session named that differed from the one set. `vcenters` holds each vCenter's steps; `sent` names every
request that was not a plain read.

`api_client.json`: `asked` (the role, its scope and both lifetimes), `calls` (each call's method, templated path and
status), `exchange` (the broker's status, the bearer's principal type and lifetime), `readback` and `exit`. A teardown's
record holds `calls`, `residue` (`client_present`, `tokens_left`) and `exit`. A rotation's record holds `asked` (both
lifetimes, and whether an old token was given), `calls`, `tokens_before`, `exchange` (the new token at the broker),
`overlap` (the active tokens once the new one was issued), `old_token_before_delete` and `old_token_after_delete` (the
old token's status at the broker), `readback` and `exit`.

`service_account.json`: `asked` (the role and its scope), `calls`, `registered` and `readback` (present, status, roles,
`require_rotation`), `device_grant` (its status, whether a refresh token came back, the bearer's lifetime in seconds),
`session` (the bearer's principal and roles), `refresh` (its status, the form that answered, whether the refresh token
was replaced) and `exit`. A teardown's record holds `calls`, `residue` (`account_present`), `revoked_token` (each
form of the refresh, with and without the client id, tried after the revoke and again after the delete, with its status
and OAuth error) and `exit`.

Every estate value is a placeholder: `{{host-N}}`, `{{client-N}}`, `{{name-N}}`, `{{domain-N}}`, `{{org-N}}`.
