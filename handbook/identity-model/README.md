# Read your estate's identity model

Companion to the chapter
([privatecloudarchitect.com/handbook/identity-model](https://privatecloudarchitect.com/handbook/identity-model)):
one read-only script that reads a VCF 9.1 estate's identity model from the planes that own it and prints the lines
a reader of the chapter should be able to explain. Stdlib Python. No token, secret or password is printed or
written.

| File | What it is |
|---|---|
| `census.py` | Reads the brokers from the identity plane (never the fleet inventory), each realm and the VCF instances it covers, the realm's identity provider and its directories with protocol and port, the two ways a vCenter grant can spell a principal (the directory's domain and the realm's name, each in capitals) and the third string an API client's session carries (the broker tenant), the API clients with their tokens' lifetimes and each token's runway (its days left, and when it was last exchanged for a bearer), the emergency clients, the fleet's token settings and roles, each VCF Automation organization's ways in, and the broker each vCenter signs in through. `--orgs-only` reads only the organizations, on a VCF Automation provider credential alone. `--egress-metadata-url` asks each broker to fetch a SAML metadata URL itself, proving or refuting its reach to a cloud identity provider. Writes `census.json`, and refuses to write a record carrying any estate value. |
| `census.json` | That record from the reference estate, 2026-10-15, written by `census.py` as it stands: every call answered, and every paged list's pages carry the total stated and the distinct entries read (`listed`). It was made without `FINGERPRINT_KEY_FILE`, so it carries no fingerprints and `catalog_check.py --census` refuses it as a usage error (exit 5); join a record from your own run, made with your key. |
| `expected-output.md` | The transcript of that run, with what to read in it, a run whose credential could not read the fleet identity plane, and a replayed run. |
| `replay/census/` | A recorded answer set made from `census.json`, every name a placeholder, for `--replay`: the census runs on it with no estate and sends nothing. |

## Try it without an estate

`--replay DIR` answers every request from a recorded set instead of the estate, so you can run the census before
you have an estate to read, or see what it prints for a shape your estate has not shown you. The set beside this
README, `replay/census/`, is the reference estate's record (`census.json`) made into answers, with a placeholder for
every name:

```bash
python3 census.py --replay replay/census                 # the whole census; writes census.replay.json
python3 census.py --replay replay/census --orgs-only     # the organizations alone, as the provider
```

Nothing is sent and no credential is read: the set answers each request by its method, path and query, and names
the placeholder hosts it was recorded on. A request the set holds no answer for is a read that failed, so the run
exits 3 and names the call, never a pass. The record goes to `census.replay.json` unless `OUT` names a file, so a
replayed run never overwrites a real `census.json`, and it carries `"replay": true`, so a tool that reads census
records (`catalog_check.py --census`) refuses it as no read of an estate. The transcript is under "A replayed run"
in `expected-output.md`.

## Run it

```bash
export OPS_HOST=<operations-fqdn>
export OPS_API_TOKEN_FILE=/path/to/api-token          # mode 0600; an API token from VCF Operations: an API client holding VCF Administrator
export OPS_BROKER_HOST=<identity-broker-fqdn>           # where the token is traded for a bearer; default OPS_HOST
export BROKER_TENANT=CUSTOMER                          # the broker tenant, the realm's path segment at the broker (it was OPS_REALM)
# or, instead of the API token: export OPS_BEARER_FILE=/path/to/bearer   (a bearer you already hold, mode 0600)
# BROKER_HOST and API_TOKEN_FILE, the names integrations-identity's vcenter_exchange.py takes, are read when
# OPS_BROKER_HOST and OPS_API_TOKEN_FILE are unset, so one shell serves both companions
export VCFA_HOST=<automation-fqdn>                       # optional: each organization's ways in
export VCFA_PROVIDER_BEARER_FILE=/path/to/provider-bearer   # mode 0600; or VCFA_PROVIDER_REFRESH_TOKEN_FILE
export VC_HOSTS=<vcenter-fqdn>,<vcenter-fqdn>            # optional: the broker each vCenter signs in through
export VC_USER=<user@domain> VC_PASSWORD_FILE=/path/to/password   # mode 0600
export TLS_VERIFY=false                                  # only on a self-signed lab CA
export OUT=census.json
# every credential file, and FINGERPRINT_KEY_FILE below, is read only at mode 0600: one open to group or other is
# refused unread, with the fix (chmod 600 "$OPS_API_TOKEN_FILE"), exit 5 and nothing sent

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
export BROKER_HOSTS=<instance-broker-fqdn>,<mgmt-vcenter-fqdn>,<mgmt-vcenter-fqdn>   # required, see below
export TLS_VERIFY=false                                        # only on a self-signed lab CA

python3 census.py --orgs-only --redact    # the organizations block alone; exit 5 without a provider credential or BROKER_HOSTS
```

It reads no broker, so it calls an organization's OIDC issuer the broker only when the issuer's host is in
`BROKER_HOSTS`. Name every broker there, the embedded broker inside each management vCenter included: on the
reference estate the provider consumption organization's issuer was on an embedded broker, and it read `oidc`
(issuer `other`) until `BROKER_HOSTS` named the management vCenters, then `oidc-broker`, as the full census reads it
(2026-10-15, one run). So `--orgs-only` refuses to start without `BROKER_HOSTS`: unset, an organization on a broker
reads as on a provider of its own and the run exits 0 on a reading it was never given the means to make. And an
organization signing in through VCF single sign-on, whose issuer is a broker by definition, read with an issuer
`BROKER_HOSTS` does not name fails the read (`NOT PLACED`, exit 3): the brokers given miss the one the platform signs in
through. An embedded broker left out is not caught that way, so name every one.

### Joining the record to your credential catalog

Every name in `census.json` is a placeholder, numbered afresh on each run. To check each API client against the
credential catalog of the service-accounts companion (`catalog_check.py --census census.json`), set
`FINGERPRINT_KEY_FILE` to a secret of your own (mode 0600, kept off any shared disk) for the run: each API client then
carries a keyed fingerprint of its client id and its name, the same under that key in every record, and meaningless
without it. Give `catalog_check.py` the same file.

| Exit | Means | What a scheduler does |
|---|---|---|
| 0 | the record is written and every call answered | nothing |
| 3 | a read failed or is not known: a call failed, or answered without what the read needs, such as a vCenter session sign-in that returned no session id, a list whose answer has no list under its key (a 200 without its list key is not an empty list), a paged list not read whole (below), an organization listed without `isClassicTenant` (its type prints `type not read`) or without `isProviderConsumptionOrg` (it prints `provider consumption not read`), a broker listed without `healthy` (it prints `health not read`), or a list of no broker or, as the provider, of no organization, where the census's own bearer came from a broker and the provider's System organization is one (the record is still written and names the call, and the run prints the server's reason; a fleet identity read refused or read in part opens the print with `NOT READ`, because the lines that count brokers and clients then count nothing, or only part); the credential could not be obtained; with `--orgs-only` an organization signing in through VCF single sign-on whose issuer `BROKER_HOSTS` does not name; the record refused because an estate value survived the scrub (nothing is written, so a tool that reads it has nothing to read); under `--replay`, a request the set holds no answer for; or an error the script did not expect | fix the read; take no count from this run |
| 5 | a usage error, found before anything is sent (a missing host or credential; a credential file that cannot be read or holds nothing; a credential file open to group or other, refused unread with the fix, `chmod 600`; `VC_HOSTS` without `VC_USER` and a password; with `--orgs-only`, no `VCFA_HOST`, no provider credential or no `BROKER_HOSTS`; a `FINGERPRINT_KEY_FILE` unreadable or open to group or other; a `--replay` directory that cannot be read or holds no replay set; a Python older than 3.10); nothing is written | fix the invocation |

These are the codes every identity companion uses: 0 nothing to act on, 3 a read that failed, 5 a usage error. The
census judges nothing, so it has no finding code of its own. A tool that reads `census.json`, as
`catalog_check.py --census` does, takes it as a read only when its `exit` is 0, no fleet call failed, each paged
list's last call states it was read whole (`listed`) and the lines it needs are there.

### Before your estate has a realm

The fleet read runs on a bearer the broker trades for an API token, and an API token is made for an API client of a
realm or for a VCF single sign-on user, so this census starts once VCF single sign-on has a realm. Before that, read
what does not wait for one: `--orgs-only` above, on a VCF Automation provider credential, and the vcenter-authorization
companion's `authz.py`, which runs with `--no-realm` and reports the realm-spelled class as not applicable.
Whether VCF Operations' own local administrator, through `POST /suite-api/api/auth/token/acquire`, can read the fleet
identity plane was not tried.

## Scope, stated plainly

- Read-only by default. Every call to VCF Operations and VCF Automation is a GET, or a POST to a `.../query`
  endpoint, which searches and changes nothing. On each vCenter the script opens a session and closes it. With
  `--orgs-only` it calls VCF Automation only: on the reference estate, 31 reads of ten organizations on a provider
  bearer, with no VCF Operations credential set (2026-10-15, one run).
- A list is complete only when it is read whole: the fleet's roles, API clients and API tokens page by page (page
  from 0, `pageSize` in the query) and VCF Automation's organizations (page from 1), until the count of distinct
  entries, a duplicate counted once by its id, equals the total the answer states (`pageInfo.totalCount`,
  `resultTotal`). An answer without its list or without a stated total, a page that comes back empty or short before
  the total, a page that adds no new entry, and a total that changes between pages are an unread list: the call is
  marked, the run exits 3, and what was read so far never stands for the list. Each page call in the record carries
  `listed`, the total stated and the distinct entries read, so a tool that reads the record can check the list was
  read whole. Forced to a page size of one, the fleet's three lists and the organizations each read one entry per
  call and the same entries as at the default size, none twice (2026-10-15, one run on the reference estate, whose
  lists are shorter than one default page, made before the distinct count and the `listed` numbers were added);
  more than a page, the shapes above and a page the server serves smaller than asked are held by the tests. On that
  run every list answer carried its list, the empty ones included. The committed record's run (2026-10-15, one run)
  carries `listed` on each list's pages, every one read to the total it stated.
- `--egress-metadata-url` sends one request per broker that is not a read: `POST .../iam/saml-metadata/validate`,
  which the contract describes as validating and parsing metadata. The script reads the brokers, realms and
  providers again after the requests and records any difference; on the reference run there was none.
- Brokers come from `GET .../iam/vidbs`. The fleet inventory lists the instance broker's appliance; an embedded
  broker lives inside a management vCenter and has no inventory row, so a count taken from the inventory is short.
  The API's `EXTERNAL` is the instance broker, and the census prints it as `instance`. Each broker's line ends in
  `NOT HEALTHY` when the list gives it `healthy` false, in nothing when true, and in `health not read` when its entry
  carries no such flag, which fails the read (exit 3), as an absent flag is not false. What the flag measures is the
  identity plane's; the census prints it and judges nothing. In the committed record every broker read `healthy` true.
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
- The flag and the issuer's host are read together because they answer different questions. On the reference estate
  (2026-10-15, one read), the System organization's OIDC settings carried the `vidb` flag on, with its issuer on the
  instance broker that holds the realm; the provider consumption organization's carried it off, with its issuer on an
  embedded broker that holds no realm, whose discovery document answered and named that issuer. The census calls the
  second `oidc-broker` only because its issuer's host is a broker's; whether its people are the realm's people was
  not tested.
- Measured on VCF 9.1.1 with the VCF Operations API token of a VCF single sign-on user holding the VCF
  Administrator role, and once with a bearer file from the same user. An API client holding VCF Administrator read
  every fleet line the same as that user's token, field by field (one run, 2026-10-13). An API client holding VCF
  Viewer was refused on every fleet identity read (403, five reads, 2026-10-13); a role between the two was not
  tried, so the census credential reads at the administrator's level: hold it as tier-0. A client you made in the
  console for one read is removed in the console, on the API Clients tab, as the administrator who made it, never on
  its own token: integrations-identity's `api_client.py --teardown` refuses a client it did not make and the client the
  run is signed in as.
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

`summary` holds the lines the run prints: `brokers` (each with its `kind`, the `realm` it holds, or none, and
`healthy` as the list gave it, null when the entry carried no such flag),
`realms` (the broker holding each, the VCF `instances` it covers, its component count and issues), `providers`
(`type`, `protocol`, `provisioning`), `directories` (`domains`, `protocol`, `port`, `host`, sync state; a directory
with a `host` is one the broker binds, and its domains in capitals are the directory spelling the print shows beside
the realm's name), `emergency_clients`
(an empty list means none), `api_clients` (roles; each token's `api_token_ttl_min` and `access_token_ttl_min`,
in minutes, and its runway: `expires` and `days_left`, `last_used` and `days_since_used`, counted from `captured`,
the moment of the read, so the record reads the same on any later day; `last_used` is the API's `lastUsedDate`, the
date the token was last exchanged for a bearer; and `fingerprints` when the run had `FINGERPRINT_KEY_FILE`), `user_tokens` (API tokens held by people), `settings` (the fleet's token lifetimes in minutes),
`organizations` (`type`: `classic` or `all-apps` from `isClassicTenant`, or `type not read` when the list entry
carried no such flag; `provider_consumption`: `isProviderConsumptionOrg` as read, true, false, or null when the entry
carried no such flag, which prints `provider consumption not read`; `sign_in`; and the `issuer` of an OIDC organization: `broker`, `entra` or `other`;
with `--orgs-only`, `broker` only for a host in `BROKER_HOSTS`),
`vcenters` (the host each vCenter's default provider discovers its issuer at, and that host's broker kind), and
`egress` when the option ran. `fleet`, `organizations` and `vcenters` hold what each plane answered, in the API's
own field names; `calls` holds every request with its status, a paged list's pages with `listed` (the total the
answer stated and the distinct entries read so far) and a call that did not read with `shape`, the reason; `sent`
names every request that was not a read.
Every estate value is a placeholder: `{{host-N}}`, `{{id-N}}`, `{{name-N}}`, `{{org-N}}`, `{{domain-N}}`,
`{{dn-N}}`, `{{role-N}}` (a custom role), `{{metadata-url-N}}`. The same value keeps the same placeholder
throughout, so a realm named after its broker reads as that broker's host.
