# A VCF SSO API client into vCenter, and who else signs in there

Companion to the chapter
([privatecloudarchitect.com/handbook/integrations-identity](https://privatecloudarchitect.com/handbook/integrations-identity)):
one read-only script that takes a VCF single sign-on API client through each vCenter's token exchange into a REST and a
SOAP session, and reads every vCenter's session list so an integration still signing in as a person's directory account
shows up beside the machine identities. Standard library Python only. No token, assertion or password is printed or
written.

| File | What it is |
|---|---|
| `vcenter_exchange.py` | The exchange and the session census. Writes `exchange.json` with every estate name replaced, and refuses to write a record in which one survived. |
| `exchange.json` | That record from the reference estate, 2026-10-13. The chapter's plates render it. |
| `expected-output.md` | The transcript of that run, with what to read in it. |

## Run it

```bash
export BROKER_HOST=<identity-broker-fqdn>           # trades the API client's token for a bearer
export API_TOKEN_FILE=/path/to/api-token            # mode 0600; the API client's API token
# or, instead of the API token: export BEARER_FILE=/path/to/bearer   (a broker bearer you already hold)
export VC_HOSTS=<vcenter-fqdn>[,<another>]
export VC_USER=<an administrator, user@domain>      # for --sessions: the session list needs one
export VC_PASSWORD_FILE=/path/to/password           # mode 0600
export DIRECTORY_DOMAINS=<directory domain>[,<another>]   # as vCenter spells it, for --sessions
export TLS_VERIFY=false                             # only on a self-signed lab CA

python3 vcenter_exchange.py                         # the exchange and both sessions, on every vCenter
python3 vcenter_exchange.py --sessions              # and the session census
python3 vcenter_exchange.py --sessions --redact     # the same, printed with placeholders, for a transcript you will share
```

`BROKER_REALM` (default `CUSTOMER`), `REALM_DOMAIN` (how a session spells the realm, default `CUSTOMER`),
`LOCAL_DOMAIN` (the vCenter's own SSO domain, default `VSPHERE.LOCAL`) and `OUT` (default `exchange.json`) are optional.

| Exit | Means |
|---|---|
| 0 | the client took both sessions on every vCenter, and with `--sessions` no directory account signs in from a vSphere SDK |
| 1 | a vCenter refused the client, or a read failed |
| 2 | a usage error, or the record was refused because an estate value survived the scrub; nothing is written |
| 3 | `--sessions` found a directory account signing in from a vSphere SDK: an integration on a person's or a directory account's password |

## What it does, and in what order

1. `GET /api/vcenter/datacenter` with the broker's bearer as presented. vCenter refuses it; that is the expected answer,
   and the record keeps the status.
2. `POST /api/vcenter/authentication/token`, form-encoded, with the access token alone. vCenter answers a SAML token of
   the Bearer type that lives minutes.
3. `POST /api/session` with `Authorization: SIGN token="<base64(gzip(assertion))>"`: who the session is, whether it reads
   the VM list, then `DELETE /api/session`.
4. A second exchange, then `SessionManager.LoginByToken` over SOAP with the assertion in a WS-Security header, its XML
   declaration removed: who the session is, then `Logout`.
5. With `--sessions`: a SOAP session as `VC_USER`, `SessionManager.sessionList` read with `RetrievePropertiesEx`, the
   census's own session left out by its key, then `Logout`.

## Scope, stated plainly

- Read-only. It opens sessions and closes them, and changes no configuration. The token exchanges mint tokens that live
  minutes and are not stored.
- The census classifies each session by its principal's domain: the realm's domain is an API client, a domain in
  `DIRECTORY_DOMAINS` is a directory account, the vCenter's own SSO domain is a local account (the local administrator
  apart, and accounts named `svc-` counted as VCF's integration accounts). Each session's client agent is recorded
  without its version. An agent naming pyvmomi, govmomi, vim-java, XML-WS, PowerCLI or rbvmomi counts as a vSphere SDK;
  that list is a judgment from the agents seen, not a vendor list, so read the agents yourself.
- No local account is named in the record, because a local account's name can carry estate names; the census counts
  them. Directory accounts and API clients are recorded as placeholders, with their agents.
- A session list shows what is signed in at the moment of the read. Run it on several days, and on a schedule, before
  you conclude that no integration signs in as a person.
- Measured on VCF 9.1.1 (three vCenters, build 25712839), with an API client holding the fleet role `vcf_viewer` and the
  session lists read by a directory administrator. A narrower account's right to read the session list was not tested,
  nor a vCenter outside VCF single sign-on, nor a broker federated to a cloud provider.

## Reading the record

`summary` holds the lines the run exists for: `client_took_both_sessions` of `vcenters`, `bearer_as_presented` (the
statuses seen), `saml_lifetime_s`, `session_users` (who the client's sessions were), and with `--sessions`
`sessions_by_class`, `local_administrator_by_agent`, `directory_principals` and `directory_from_sdk`. `vcenters` holds each
vCenter's steps; `sent` names every request that was not a plain read. Every estate value is a placeholder: `{{host-N}}`,
`{{client-N}}`, `{{name-N}}`, `{{domain-N}}`.
