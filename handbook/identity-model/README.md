# Read your estate's identity model

Companion to the chapter
([privatecloudarchitect.com/handbook/identity-model](https://privatecloudarchitect.com/handbook/identity-model)):
one read-only script that reads a VCF 9.1 estate's identity model from the planes that own it and prints the lines
a reader of the chapter should be able to explain. Stdlib Python. No token, secret or password is printed or
written.

| File | What it is |
|---|---|
| `census.py` | Reads the brokers from the identity plane (never the fleet inventory), each realm and the VCF instances it covers, the realm's identity provider and its directories with protocol and port, the two ways a vCenter grant can spell a principal (the directory's domain and the realm's name, each in capitals) and the third string an API client's session carries (the broker tenant), the API clients with their tokens' lifetimes and each token's runway (its days left, and when it was last exchanged for a bearer), the emergency clients, the fleet's token settings and roles, each VCF Automation organization's ways in, and the broker each vCenter signs in through. `--orgs-only` reads only the organizations, on a VCF Automation provider credential alone. `--egress-metadata-url` asks each broker to fetch a SAML metadata URL itself, proving or refuting its reach to a cloud identity provider. Writes `census.json`, and refuses to write a record carrying any estate value. |
| `census.json` | That record from the reference estate, 2026-10-13. |
| `expected-output.md` | The transcript of that run, with what to read in it, and a run whose credential could not read the fleet identity plane. |

## Run it

```bash
export OPS_HOST=<operations-fqdn>
export OPS_API_TOKEN_FILE=/path/to/api-token          # mode 0600; an API token from VCF Operations: an API client holding VCF Administrator
export OPS_BROKER_HOST=<identity-broker-fqdn>           # where the token is traded for a bearer; default OPS_HOST
export BROKER_TENANT=CUSTOMER                          # the broker tenant, the realm's path segment at the broker (it was OPS_REALM)
# or, instead of the API token: export OPS_BEARER_FILE=/path/to/bearer   (a bearer you already hold)
# BROKER_HOST and API_TOKEN_FILE, the names integrations-identity's vcenter_exchange.py takes, are read when
# OPS_BROKER_HOST and OPS_API_TOKEN_FILE are unset, so one shell serves both companions
export VCFA_HOST=<automation-fqdn>                       # optional: each organization's ways in
export VCFA_PROVIDER_BEARER_FILE=/path/to/provider-bearer   # mode 0600; or VCFA_PROVIDER_REFRESH_TOKEN_FILE
export VC_HOSTS=<vcenter-fqdn>,<vcenter-fqdn>            # optional: the broker each vCenter signs in through
export VC_USER=<user@domain> VC_PASSWORD_FILE=/path/to/password   # mode 0600
export TLS_VERIFY=false                                  # only on a self-signed lab CA
export OUT=census.json

python3 census.py            # read, print, record
python3 census.py --redact   # the same, printed with placeholders, for a transcript you will share
python3 census.py --egress-metadata-url https://login.microsoftonline.com/<tenant-id>/FederationMetadata/2007-06/FederationMetadata.xml
```

### Only the organizations, as the provider

A VCF Automation provider administrator can read how every organization signs in without the fleet's most
privileged token. `--orgs-only` reads VCF Automation alone: no VCF Operations credential, no broker, no vCenter.

```bash
export VCFA_HOST=<automation-fqdn>
export VCFA_PROVIDER_BEARER_FILE=/path/to/provider-bearer      # mode 0600; or VCFA_PROVIDER_REFRESH_TOKEN_FILE, a provider API token
export BROKER_HOSTS=<instance-broker-fqdn>,<mgmt-vcenter-fqdn>,<mgmt-vcenter-fqdn>   # optional, see below
export TLS_VERIFY=false                                        # only on a self-signed lab CA

python3 census.py --orgs-only --redact    # the organizations block alone; exit 2 without a provider credential
```

It reads no broker, so it calls an organization's OIDC issuer the broker only when the issuer's host is in
`BROKER_HOSTS`. Name every broker there, the embedded broker inside each management vCenter included: on the
reference estate the provider consumption organization's issuer was on an embedded broker, and it read `oidc`
(issuer `other`) until `BROKER_HOSTS` named the management vCenters, then `oidc-broker`, as the full census reads it
(2026-10-15, one run).

### Joining the record to your credential catalog

Every name in `census.json` is a placeholder, numbered afresh on each run. To check each API client against the
credential catalog of the service-accounts companion (`catalog_check.py --census census.json`), set
`FINGERPRINT_KEY_FILE` to a secret of your own (mode 0600, kept off any shared disk) for the run: each API client then
carries a keyed fingerprint of its client id and its name, the same under that key in every record, and meaningless
without it. Give `catalog_check.py` the same file.

| Exit | Means |
|---|---|
| 0 | the record is written and every call answered |
| 1 | a call failed; the record is still written and names the call, and the run prints the server's reason. A refused fleet identity read opens the print with `NOT READ`, because the lines that count brokers and clients then count nothing |
| 2 | a usage error (with `--orgs-only`, no `VCFA_HOST` or no provider credential), or the record was refused because an estate value survived the scrub; nothing is written |

## Scope, stated plainly

- Read-only by default. Every call to VCF Operations and VCF Automation is a GET, or a POST to a `.../query`
  endpoint, which searches and changes nothing. On each vCenter the script opens a session and closes it. With
  `--orgs-only` it calls VCF Automation only: on the reference estate, 31 reads of ten organizations on a provider
  bearer, with no VCF Operations credential set (2026-10-15, one run).
- `--egress-metadata-url` sends one request per broker that is not a read: `POST .../iam/saml-metadata/validate`,
  which the contract describes as validating and parsing metadata. The script reads the brokers, realms and
  providers again after the requests and records any difference; on the reference run there was none.
- Brokers come from `GET .../iam/vidbs`. The fleet inventory lists the instance broker's appliance; an embedded
  broker lives inside a management vCenter and has no inventory row, so a count taken from the inventory is short.
  The API's `EXTERNAL` is the instance broker, and the census prints it as `instance`.
- Secrets die where they arrive. The fleet IAM API returns an emergency client's access token, an identity
  provider's client secret and bind password, and an API token's value; VCF Automation returns an organization's
  OIDC client secret. The reader deletes each from the body before any function sees it, and the record keeps only
  the fields the allow-lists in the script name. Of every URL it keeps only the host.
- An organization's ways in are read from its own three settings: `vcf-sso` when VCF Automation's `vidb` flag is
  on, `oidc-broker` when OIDC points at a broker without that flag, `oidc` for another OIDC provider, `saml`,
  `ldap-system` or `ldap-custom`, and `local` when none is on. `ldap-system` is VCF Automation's system LDAP
  service, the connection the provider administrator configures for organizations that belong to the provider; the
  census reads the organization's mode, not which directory that connection names. A Supervisor's issuer is read
  from each provider's own record; the Supervisor's provider list does not carry it.
- Measured on VCF 9.1.1 with the VCF Operations API token of a VCF single sign-on user holding the VCF
  Administrator role, and once with a bearer file from the same user. An API client holding VCF Administrator read
  every fleet line the same as that user's token, field by field (one run, 2026-10-13). An API client holding VCF
  Viewer was refused on every fleet identity read (403, five reads, 2026-10-13); a role between the two was not
  tried, so the census credential reads at the administrator's level: hold it as tier-0.
- The broker tenant (`BROKER_TENANT`, CUSTOMER by default) is the realm's path segment at the broker, where the API
  token is traded; on the reference estate an API client's own vCenter session read `CUSTOMER\<client id>`. It is
  not the realm's name, and the census prints both. `OPS_REALM`, its earlier name, is still read when `BROKER_TENANT` is unset, with a notice. VCF Automation was read with a provider bearer (the refresh-token path was not exercised
  on the reference estate), and vCenter with a VCF single sign-on user's password; the least privilege each plane
  needs was not tested. The egress option was run once, against Entra ID's federation metadata for one tenant.
- What it cannot see: whether an emergency client's token still works (the census reads its status, it does not
  use it), whether the directory accepts the bind it is configured for, and the roles a VCF Automation
  organization grants. NSX is not read directly: its binding to the realm is among the auth sources in the
  record. SDDC Manager is not read.

## Reading the record

`summary` holds the lines the run prints: `brokers` (each with its `kind` and the `realm` it holds, or none),
`realms` (the broker holding each, the VCF `instances` it covers, its component count and issues), `providers`
(`type`, `protocol`, `provisioning`), `directories` (`domains`, `protocol`, `port`, `host`, sync state; a directory
with a `host` is one the broker binds, and its domains in capitals are the directory spelling the print shows beside
the realm's name), `emergency_clients`
(an empty list means none), `api_clients` (roles; each token's `api_token_ttl_min` and `access_token_ttl_min`,
in minutes, and its runway: `expires` and `days_left`, `last_used` and `days_since_used`, counted from `captured`,
the moment of the read, so the record reads the same on any later day; `last_used` is the API's `lastUsedDate`, the
date the token was last exchanged for a bearer; and `fingerprints` when the run had `FINGERPRINT_KEY_FILE`), `user_tokens` (API tokens held by people), `settings` (the fleet's token lifetimes in minutes),
`organizations` (`type`, `sign_in`, and the `issuer` of an OIDC organization: `broker`, `entra` or `other`;
with `--orgs-only`, `broker` only for a host in `BROKER_HOSTS`),
`vcenters` (the host each vCenter's default provider discovers its issuer at, and that host's broker kind), and
`egress` when the option ran. `fleet`, `organizations` and `vcenters` hold what each plane answered, in the API's
own field names; `calls` holds every request with its status; `sent` names every request that was not a read.
Every estate value is a placeholder: `{{host-N}}`, `{{id-N}}`, `{{name-N}}`, `{{org-N}}`, `{{domain-N}}`,
`{{dn-N}}`, `{{role-N}}` (a custom role), `{{metadata-url-N}}`. The same value keeps the same placeholder
throughout, so a realm named after its broker reads as that broker's host.
