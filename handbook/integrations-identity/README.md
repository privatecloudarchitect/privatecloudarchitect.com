# An integration's own identity, and who signs in to vCenter

Companion to the chapter
([privatecloudarchitect.com/handbook/integrations-identity](https://privatecloudarchitect.com/handbook/integrations-identity)):
two scripts. `vcenter_exchange.py` reads every vCenter's session list, so an integration still signing in as a person's
directory account shows up beside the machine identities, and takes a VCF single sign-on API client through each
vCenter's token exchange into a REST and a SOAP session. `api_client.py` makes the API client an integration moves to,
with one role and a token whose two lifetimes are set, and removes it when the integration retires. Standard library
Python only. No token, assertion or password is printed or written.

| File | What it is |
|---|---|
| `vcenter_exchange.py` | The session census and the exchange. Read-only. Writes `exchange.json` with every estate name replaced, and refuses to write a record in which one survived. |
| `api_client.py` | One API client for one integration: plan it (the default), create it, remove it. Writes `api_client.json` the same way. |
| `exchange.json` | The census and the exchange on the reference estate, 2026-10-13, read as an API client. The chapter's plates render it. |
| `api_client.json`, `api_client_teardown.json` | One throwaway client made and removed on the reference estate, 2026-10-13. |
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

`BROKER_REALM` (default `CUSTOMER`), `REALM_DOMAIN` (how a session spells the realm, default `CUSTOMER`),
`LOCAL_DOMAIN` (the vCenter's own SSO domain, default `VSPHERE.LOCAL`) and `OUT` (default `exchange.json`) are optional.
`VC_PASSWORD` and `API_TOKEN` are read when their `_FILE` forms are unset.

| Exit | Means |
|---|---|
| 0 | every vCenter took the client through both sessions (when a client is given), and with `--sessions` no directory account signs in from a vSphere SDK |
| 1 | a vCenter refused the client, a read failed, or the census's identity could read only its own session |
| 2 | a usage error, or the record was refused because an estate value survived the scrub; nothing is written |
| 3 | `--sessions` found a directory account signing in from a vSphere SDK: an integration on a person's or a directory account's password |

## The API client an integration moves to: `api_client.py`

Plan first. With no `--execute` it prints every call it would send, with its body, and sends nothing.

```bash
export OPS_HOST=<vcf-operations-fqdn>
export OPS_API_TOKEN_FILE=/path/to/ops-api-token    # mode 0600; your own VCF Operations API token, of a user who may manage API clients
export TLS_VERIFY=false                             # only on a self-signed lab CA

python3 api_client.py --client-id backup-01 --role vcf_viewer --api-token-ttl 43200 --access-token-ttl 60
python3 api_client.py --client-id backup-01 --role vcf_viewer --api-token-ttl 43200 --access-token-ttl 60 \
    --token-file /path/to/backup-01-token --execute
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
| `--teardown` | remove the client and its tokens instead of creating them |
| `--execute` | send the calls; without it the plan is printed |
| `--redact` | print with placeholders instead of your host and client id |

| Env | Meaning |
|---|---|
| `OPS_HOST` | the VCF Operations FQDN (required to execute) |
| `OPS_API_TOKEN_FILE` | your VCF Operations API token, mode 0600 (`OPS_API_TOKEN` is read if it is unset), traded at the broker for a bearer |
| `OPS_BROKER_HOST` | the broker that trades it (default `OPS_HOST`) |
| `OPS_REALM` | the broker's realm path segment (default `CUSTOMER`) |
| `OPS_BEARER_FILE` | instead of the API token, a bearer you already hold |
| `TLS_VERIFY` | `false` only on a self-signed lab CA |
| `OUT` | the record (default `api_client.json`) |

| Exit | Means |
|---|---|
| 0 | the plan printed; or the run held on read-back: the client with its one role and an active token with both lifetimes, or, for a teardown, no client and no token left |
| 1 | a call failed, or the read-back did not hold; a create that stopped part way prints where it stopped and the teardown to run before trying again |
| 2 | a usage error, a refusal before anything is sent (a lifetime outside the bounds, a token file that exists), a client that already exists (refused, never adopted), or the record was refused because an estate value survived the scrub |

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

A teardown queries the client's tokens and deletes each, deletes the client, then reads both lists again and records
the residue. A teardown of a client that is not there removes nothing and exits 0, so it is safe to re-run.

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
- The census classifies each session by its principal's domain: the realm's domain is an API client, a domain in
  `DIRECTORY_DOMAINS` is a directory account, the vCenter's own SSO domain is a local account (the local administrator
  apart, and accounts named `svc-` counted as VCF's integration accounts). Each session's client agent is recorded
  without its version. An agent naming pyvmomi, govmomi, vim-java, XML-WS, PowerCLI or rbvmomi counts as a vSphere SDK;
  that list is a judgment from the agents seen, not a vendor list, so read the agents yourself.
- No local account is named in the record, because a local account's name can carry estate names; the census counts
  them. Directory accounts and API clients are recorded as placeholders, with their agents.
- A session list shows what is signed in at the moment of the read. Run it on several days, and on a schedule, before
  you conclude that no integration signs in as a person.
- Measured on VCF 9.1.1 (three vCenters, build 25712839), 2026-10-13: the exchange with an API client holding
  `vcf_viewer`; the census read as that client holding `vcf_administrator`, and once with no API client, as a directory
  account's password. `api_client.py` ran on a VCF Operations API token held by the estate's administrator; which
  narrower operator role may manage API clients was not tried, nor `OPS_BEARER_FILE`, nor a broker federated to a
  cloud provider.

## Reading the records

`exchange.json`: `summary` holds the lines the run exists for: `census_as` (`client` or `password`), `client_tried` and
`client_took_both_sessions` of `vcenters`, `bearer_as_presented` (the statuses seen), `saml_lifetime_s`, `session_users`
(who the client's sessions were), and with `--sessions` `sessions_read`, `census_only_own_session`, `sessions_by_class`,
`local_administrator_by_agent`, `directory_principals` and `directory_from_sdk`. `vcenters` holds each vCenter's steps;
`sent` names every request that was not a plain read.

`api_client.json`: `asked` (the role, its scope and both lifetimes), `calls` (each call's method, templated path and
status), `exchange` (the broker's status, the bearer's principal type and lifetime), `readback` and `exit`. A teardown's
record holds `calls`, `residue` (`client_present`, `tokens_left`) and `exit`.

Every estate value is a placeholder: `{{host-N}}`, `{{client-N}}`, `{{name-N}}`, `{{domain-N}}`.
