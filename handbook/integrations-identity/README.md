# An integration's own identity, and who signs in to vCenter

Companion to the chapter
([privatecloudarchitect.com/handbook/integrations-identity](https://privatecloudarchitect.com/handbook/integrations-identity)):
three scripts. `vcenter_exchange.py` reads every vCenter's session list, so an integration still signing in as a person's
directory account shows up beside the machine identities, and takes a VCF single sign-on API client through each
vCenter's token exchange into a REST and a SOAP session. `api_client.py` makes the API client an integration moves to,
with one role and a token whose two lifetimes are set, and removes it when the integration retires.
`service_account.py` does the same in VCF Automation: one service account with one role, activated through the device
grant, and revoked and removed when the integration retires. Standard library Python 3.10 or later. No token,
assertion or password is printed or written.

**One exit contract.** Every identity companion exits 0 when there is nothing for a person to act on, 3 when a read
failed or a result is undetermined (an error a script did not expect is one, never a finding), and 5 on a usage error
(a missing or bad argument or environment variable, a Python older than 3.10) or a record refused because an estate value
survived its scrub. The other codes are each script's own, in its table below. The codes were renumbered on
2026-10-15: a record written before then carries the old code in its `exit` field.

| File | What it is |
|---|---|
| `vcenter_exchange.py` | The session census and the exchange. Read-only. Writes `exchange.json` with every estate name replaced, and refuses to write a record in which one survived. |
| `api_client.py` | One API client for one integration: plan it (the default), create it, rotate its token, retire the old one, remove it. Writes `api_client.json` the same way, and a state file you keep and do not publish. |
| `exchange.json` | The census and the exchange on the reference estate, 2026-10-13, read as an API client. The chapter's plates render it. |
| `api_client.json`, `api_client_overlap.json`, `api_client_retire.json`, `api_client_teardown.json` | One throwaway client made, its token rotated with the old one still trading, the old one retired, and the client removed, on the reference estate, 2026-10-15. |
| `api_client_rotate.json` | The earlier `--rotate` of 2026-10-13, which deleted the old token in the same run; kept as the register's evidence for the overlap it showed. |
| `service_account.py` | One VCF Automation service account for one integration: plan it (the default), create it, revoke and remove it. Writes `service_account.json` the same way, and a state file you keep and do not publish. |
| `service_account.json`, `service_account_teardown.json` | One throwaway service account made, revoked and removed in a throwaway All Apps organization on the reference estate, 2026-10-13. |
| `expected-output.md` | The transcripts of those runs, with what to read in them. |

## Start here: the census, with no API client

The census needs no API client, so it can run before one exists. It reads the session list as an account you name.

```bash
export VC_HOSTS=<vcenter-fqdn>[,<another>]
export VC_USER=<user@domain>                        # an account that may read every session
export VC_PASSWORD_FILE=/path/to/password           # mode 0600
export DIRECTORY_DOMAINS=<directory domain>[,<another>]   # as vCenter spells it; required with --sessions
export TLS_VERIFY=false                             # only on a self-signed lab CA

python3 vcenter_exchange.py --sessions --redact     # the census, printed with placeholders, for a transcript you will share
```

The census flags every directory-account session from a client other than the vSphere Client: a REST integration on
a password (`vAPI`, `curl`, a product's own agent) as much as a vSphere SDK. On the reference estate the vSphere Client's
sessions read `vSphereUI`, and that is the only agent the census treats as a person's. Name another in
`INTERACTIVE_AGENTS` (comma-separated, versions left off) only if your vSphere Client's agent reads another name; never
name a scripting client there, because every account's sessions from it would then pass unflagged, and the run prints a
note when the variable is set. A person who signs in with PowerCLI is flagged too: once its owner confirms it is that
person, acknowledge that one pair with `--ack` (below).

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
list that holds only the census's own session is reported as a failed read (exit 3), never as an empty estate. If the
census's client holds `vcf_administrator`, give it nothing else to do and keep its token on its own rotation.

`BROKER_TENANT` (the broker tenant, default `CUSTOMER`), `INTERACTIVE_AGENTS` (default `vSphereUI`), `LOCAL_DOMAIN`
(the vCenter's own SSO domain, default `VSPHERE.LOCAL`) and `OUT` (default `exchange.json`) are optional. `VC_PASSWORD`
and `API_TOKEN` are read when their `_FILE` forms are unset.

**One shell for every companion.** `vcenter_exchange.py` also reads the names `api_client.py` and identity-model's
`census.py` take: `OPS_BROKER_HOST`, then `OPS_HOST`, when `BROKER_HOST` is unset; `OPS_API_TOKEN_FILE` (or
`OPS_API_TOKEN`) when `API_TOKEN_FILE` and `API_TOKEN` are unset; `OPS_BEARER_FILE` when `BEARER_FILE` is unset. Its
own names win. When it falls back to `OPS_API_TOKEN_FILE` it prints a note, because the exchange, and a census without
`VC_USER`, then run as whoever holds that token: your own token if it is the one `api_client.py` used. `census.py` reads
`BROKER_HOST` and `API_TOKEN_FILE` the same way when its `OPS_` names are unset.

**The broker tenant is not the realm's name.** The broker tenant is the realm's path segment in the broker's token URL,
`CUSTOMER` unless your broker says otherwise, and an API client's vCenter session carries it as its domain:
`CUSTOMER\<client id>`. The realm's name is the broker realm as the fleet identity plane names it, and a vCenter grant
spelled with it in capitals applied to nobody behind an AD/LDAP provider (behind a federated provider it was not
measured); that is the string `REALM_DOMAIN` takes in vcenter-authorization's
`authz.py`. This script reads `BROKER_TENANT` (`BROKER_REALM`, its earlier name, is still read), takes the tenant from
the client's own session when one is opened, and only notes a `REALM_DOMAIN` left in the shell. Whether a grant spelled
`CUSTOMER\<name>` applies to anyone was not tested.

The exit is the first of these that applies, so a scheduler reads one state from one number:

| Exit | Means | What a person does |
|---|---|---|
| 1 | `--sessions` found a directory account signing in from a client other than the vSphere Client, a pair no acknowledgement covers: an integration on a person's or a directory account's password, until its owner says otherwise | find its owner (`--where`), and move it to an identity of its own; a person's own pair, once confirmed, goes in `--ack` |
| 2 | a vCenter answered the API client's exchange, or one of its sessions, and did not take the client | read the client's role and the realm's coverage of that vCenter |
| 3 | a read failed or is undetermined: a vCenter that did not answer the exchange, a session list not read, a census identity that could read only its own session, a vCenter on which `DIRECTORY_DOMAINS` named no session while another provider's sessions were there (the domains name nothing there, so the census saw nothing it was asked to see), no vCenter read, a credential the broker did not trade, or an error the script did not expect | fix the read and run again; nothing is known of what was not read |
| 4 | `--sessions` found the local administrator signing in from a client other than the vSphere Client: an account in automated use is not a break-glass account | find the client (`--where`) and move it |
| 0 | every vCenter took the client through both sessions (when a client is given), and with `--sessions` every directory-account session is from the vSphere Client or acknowledged, and the local administrator signs in from no other client | nothing |
| 5 | a usage error (`--sessions` without `DIRECTORY_DOMAINS`, an `--ack` file that cannot be read or breaks its format, a credential file named that cannot be read or is empty, `--ack` without `--sessions`, among them), a Python older than 3.10, or the record was refused because an estate value survived the scrub; nothing is written | fix the invocation |

The exit reads each session list at one moment, and an integration that is not signed in at that moment is not seen: a
job that runs at 02:00 for ten minutes is absent from a read at 10:00 on any number of days. So schedule the census more
often than your shortest job runs, for at least your longest job cycle (a week for a weekly job, a month for a month-end
one), and let `--compare` hold the records to that coverage (below). The gate before the broker federates is
`--compare` exiting 0 at the coverage you declared: every vCenter read in every record, no directory account from a
client other than the vSphere Client unless it is a person's pair acknowledged, and the local administrator in no
automated use.

### Whose client is it: `--where`

The client agent alone does not name a product: `VMware vim-java`, `XML-WS Runtime` and `vAPI` are shared by many.
`--where` (with `--sessions`) also prints, for each directory and local administrator session, the two `UserSession`
properties that lead to its client: `ipAddress`, where it came from, and `lastActiveTime`, when it last ran a command.
Resolve each address to a host, and the host to its owner, while the session is still there.

```bash
python3 vcenter_exchange.py --sessions --where      # never with --redact: --where exists to print what --redact hides
```

The addresses and times are printed on your terminal only and are never written to `exchange.json`, so a record you
share carries none of them. Two things the address cannot do. The
[vSphere Web Services API reference for `UserSession`](https://developer.broadcom.com/xapis/vsphere-web-services-api/latest/vim.UserSession.html)
describes `ipAddress` as "The client identity. It could be IP address, or pipe name depended on client binding". And
on the reference estate the two local administrator sessions from the `vAPI` agent gave a loopback address, while the
four from the Java and XML-WS agents gave private addresses (one management vCenter, 2026-10-15, one read): a loopback
address names the vCenter itself, so the client behind those sessions has to be found another way.

### A person's pair, acknowledged: `--ack`

A person who signs in with PowerCLI, or another scripting client, is flagged like any program, because the agent alone
cannot tell them apart. Once the account's owner confirms that the sessions are that person's own, acknowledge that one
pair, the account and the agent, until a date:

```json
[{"account": "<DOMAIN>\\<name>", "agent": "PowerCLI", "until": "2026-12-31", "note": "a person, confirmed by <owner>"}]
```

```bash
python3 vcenter_exchange.py --sessions --redact --ack acks.json
python3 vcenter_exchange.py --compare sessions-*.json --ack acks.json      # needs FINGERPRINT_KEY_FILE, below
```

Write the account as the census prints it without `--redact` (`DOMAIN\name`, in any case) and the agent as it prints it
(a version is dropped). An entry with a wildcard, an account without its domain, a field other than `account`, `agent`,
`until` and `note`, or a date that is not `YYYY-MM-DD` is refused with exit 5, and nothing of the file is read. The pair
is still listed, marked `acknowledged until` its date; from the day after, it counts again. It covers that account from
that agent and nothing else: the same account from another agent, or another account from the same agent, is flagged
as before. The report counts the acknowledgements that matched no pair read, so a stale one can be removed. Do not use
`INTERACTIVE_AGENTS` for this: it names agents for every account at once.

### The same sessions across your job cycle: `--compare`

The census is a sample: what signs in between two reads is not seen. Read it on a schedule, more often than your
shortest job runs, across your longest job cycle. Every name in a record is a placeholder numbered afresh on each run,
so two records cannot be compared on their names. Set `FINGERPRINT_KEY_FILE` to a secret of your own (mode 0600, kept
off any shared disk, the same file on every read): each vCenter and each directory account in the record then carries a
keyed fingerprint, the same in every record made under that key. Then compare:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))" > fingerprint.key && chmod 600 fingerprint.key   # once
export FINGERPRINT_KEY_FILE=$PWD/fingerprint.key
OUT=sessions-$(date -u +%FT%H%M).json python3 vcenter_exchange.py --sessions --redact    # on a schedule
python3 vcenter_exchange.py --compare sessions-*.json --ack acks.json \
    --cover-hours 24 --span-days 7 --max-gap-minutes 30
```

It prints the coverage its records give: the hours of day (UTC) at which a read was taken, the span from the first
read to the last, and the largest gap between two reads. It holds them to the coverage you ask: `--cover-hours N` (the
hours of day that must each hold a read, default 24), `--span-days N` (the days from the first read to the last,
default 7) and `--max-gap-minutes N` (the longest gap allowed between two reads, none by default). A job shorter than
the largest gap can run unseen between two reads, and a job whose cycle is longer than the span can fall outside it, so
ask for both: a gap below your shortest job, and a span over your longest cycle. Three reads at 10:00 on three days cover
one hour of day and a span of two days, and show nothing of a 02:00 backup or a month-end job; `--compare` reports
them short (exit 3), never as a pass. Hourly reads from one Monday 00:00 to the next cover every hour and the
seven-day span.

It lists, per vCenter, the sessions (a directory account or the local administrator, with its client agent) present in
every record, and those that came and went with the dates each was seen. The unit it compares is one account with one
client agent: several sessions an account holds open from the same agent count once, so on the reference estate's read
six local administrator sessions from three agents compared as three. A directory account appears by its placeholder
in the latest record and its fingerprint; a run without `--redact` prints each directory account's fingerprint beside
its name, which is how you match them. Then it lists every pair from a client other than the vSphere Client seen in any
record, with how many records it was seen in: a directory account's marked acknowledged until a date or not
acknowledged, the local administrator's marked as a break-glass account in automated use. Local accounts other than the
administrator, and API clients, are counted in each record and not compared.

`--compare` first checks what each record read. A vCenter whose census failed in a record (its list not read, only
the census's own session visible, `DIRECTORY_DOMAINS` naming nothing there, or no fingerprint) is not a read of that
vCenter, and the report says which record missed it: what came and went there is not known.

| `--compare` exit, the first that applies | Means | What a person does |
|---|---|---|
| 1 | a directory account from a client other than the vSphere Client in any record, a pair no acknowledgement covers | find its owner (`--where` on the next read) and move it, or acknowledge a person's pair |
| 3 | a vCenter not read in every record, a record holding no session census read on any vCenter, or the records short of the coverage asked | read again, more often or for longer; nothing is known of what was not read |
| 4 | the local administrator from a client other than the vSphere Client in any record | find the client (`--where`) and move it |
| 0 | every vCenter read in every record, the coverage met, and none of the above | nothing: this is the census's gate before the broker federates |
| 5 | fewer than two records, an option that is not `--compare`'s, a record that cannot be read or parsed, records without fingerprints, records made under two keys, or `--ack` without `FINGERPRINT_KEY_FILE` or under another key | fix the invocation |

### What the census does not read: vCenter's sign-in events

vCenter's sign-in and sign-out events reach back further than a session list, and the census does not read them. On
one management vCenter of the reference estate (VCF 9.1.1, build 25712839, 2026-10-15, read-only) the event retention
read `event.maxAge` 30 with `event.maxAgeEnabled` true, and seven days of sign-in events held four directory accounts,
each with sign-ins from an agent other than the vSphere Client, while the session list held none of them at that
moment. Two things kept those events out of the census. A REST session (`POST /api/session`, and the older
`/rest/com/vmware/cis/session`) left no sign-in event, only a sign-out event once it was closed, under the agent
`vapi-endpoint` whatever agent the client sent; and of the 96 `VMware vim-java` and `VcApiGw` sign-ins of the three
accounts that also signed in at the vSphere Client, 92 fell within ten seconds of a `vSphereUI` sign-in of the same
account. Whether those are the vSphere Client's own sessions was not settled, so a census of the events would flag the people it exists to clear. Until
it is, read the events by hand when the list leaves a question: the
[vSphere Web Services API reference for `UserLoginSessionEvent`](https://developer.broadcom.com/xapis/vsphere-web-services-api/latest/vim.event.UserLoginSessionEvent.html)
describes it as "This event records a user logon", with `userAgent` "The user agent or application".

## The API client an integration moves to: `api_client.py`

Plan first. With no `--execute` it prints every call it would send, with its body, and sends nothing.

```bash
export OPS_HOST=<vcf-operations-fqdn>
export OPS_BROKER_HOST=<identity-broker-fqdn>       # the broker that trades your token; unset, OPS_HOST is tried
export OPS_API_TOKEN_FILE=/path/to/ops-api-token    # mode 0600; your own VCF Operations API token, never the client's
export TLS_VERIFY=false                             # only on a self-signed lab CA

python3 api_client.py --client-id backup-01 --role vcf_viewer --api-token-ttl 43200 --access-token-ttl 60
python3 api_client.py --client-id backup-01 --role vcf_viewer --api-token-ttl 43200 --access-token-ttl 60 \
    --token-file /path/to/backup-01-token --execute
python3 api_client.py --client-id backup-01 --rotate --api-token-ttl 43200 --access-token-ttl 60 \
    --token-file /path/to/backup-01-token-new --old-token-file /path/to/backup-01-token --execute   # before the old one ends
# point the integration at backup-01-token-new and run one job on it, then:
python3 api_client.py --client-id backup-01 --retire-old --old-token-file /path/to/backup-01-token --execute
python3 api_client.py --client-id backup-01 --teardown              # the teardown's plan
python3 api_client.py --client-id backup-01 --teardown --execute    # when the integration retires
```

| Flag | What it does |
|---|---|
| `--client-id ID` | the client's id, also its name; one per integration (required) |
| `--role ROLE` | the one VCF role the client holds, for example `vcf_viewer` (required to create) |
| `--scope realm\|instance` | where the role applies: the whole realm (the default), or one VCF instance with `--instance` |
| `--instance NAME` | with `--scope instance`: the VCF instance's name as the realm's coverage names it; a name the realm does not cover is refused before any write |
| `--api-token-ttl MIN` | the API token's lifetime in minutes, 1,440 to 259,200 (required to create) |
| `--access-token-ttl MIN` | the lifetime in minutes of each bearer the token yields, 30 to 60 (required to create) |
| `--token-file PATH` | where the token is written, mode 0600; the file must not exist (required with `--execute`) |
| `--description TEXT` | the client's description (default `an integration's own identity`) |
| `--rotate` | issue the client a new token with both lifetimes and prove it, deleting nothing (needs both lifetimes and `--token-file`; no `--role`) |
| `--retire-old` | once the integration runs on the newest token, delete every token of the client older than it, and read back that one is left |
| `--old-token-file PATH` | with `--rotate`: the token the integration holds now, shown still trading in the overlap; with `--retire-old`: shown trading before the delete and refused after it |
| `--teardown` | remove the client and its tokens instead of creating them |
| `--execute` | send the calls; without it the plan is printed |
| `--redact` | print with placeholders instead of your host and client id |

| Env | Meaning |
|---|---|
| `OPS_HOST` | the VCF Operations FQDN (required to execute) |
| `OPS_API_TOKEN_FILE` | your VCF Operations API token, mode 0600 (`OPS_API_TOKEN` is read if it is unset, then `API_TOKEN_FILE` and `API_TOKEN`), traded at the broker for a bearer |
| `OPS_BROKER_HOST` | the broker that trades it (`BROKER_HOST` is read when it is unset; default `OPS_HOST`) |
| `BROKER_TENANT` | the broker tenant, the realm's path segment in the broker's token URL (default `CUSTOMER`; `OPS_REALM`, its earlier name, is still read) |
| `OPS_BEARER_FILE` | instead of the API token, a bearer you already hold |
| `STATE` | the state file the create writes and every later write reads (default `api_client.<client id>.state.json`) |
| `TLS_VERIFY` | `false` only on a self-signed lab CA |
| `OUT` | the record (default `api_client.json`) |

**The token the writes run on.** Your own: a VCF single sign-on user's API token whose role may manage the fleet's API
clients. The reference runs sent every write on a user's API token whose user holds one fleet role, VCF Administrator,
through a group (read 2026-10-15); no narrower role was tried. Never the client's own token: every write after the
create, `--rotate` as much as `--retire-old` and `--teardown`, refuses to run signed in as the client it would change,
read from the `azp` claim of the run's own bearer, and refuses a bearer it cannot read as a JWT.

**A dead token.** When the broker stops trading a token, check that the token still exists, then its expiry, before the
service. A deleted API token is refused at the broker, not with 401: HTTP 500 on VCF 9.1.0 (2026-09-16, the
service-accounts companion's run), HTTP 400 for a deleted API client token on 9.1.1 (2026-10-13 and 2026-10-15).

**What the script made, and nothing else.** The create writes a state file (mode 0600: the client's id and uuid and the
ids of the tokens this script issued; no secret). `--rotate`, `--retire-old` and `--teardown` act only on a client that
file records with the same uuid, so a mistyped id, or a client someone made under that id in the console, is refused
before anything is sent. Run them from the folder the create ran in, or set `STATE`. A client made in the console is
rotated and removed in the console.

| Exit | Means |
|---|---|
| 0 | the plan printed; or the run held on read-back: the client with its one role and an active token with both lifetimes; for a rotation, the new token proved and active beside the old ones and, when given, the old token still trading; for a retirement, one token left and, when given, the old token refused; for a teardown, no client and no token left |
| 1 | the run did not hold: a write was refused, or the read-back was not what was asked; a create that stopped part way prints where it stopped and the teardown to run before trying again |
| 2 | refused by this script before any write: a client that already exists (refused, never adopted); for a rotation, a retirement or a teardown, a client the state file does not record; a run signed in as the client it would change, or on a bearer it cannot read, for every write after the create, a rotation included; a retirement while the client holds one token or whose newest token this script did not issue; or a fleet with no realm to make a client in |
| 3 | a read failed or is undetermined: a list or the realm not read, the read-back not read, your token not traded for a bearer, or an error the script did not expect |
| 5 | a usage error (a missing or bad argument or variable, a lifetime outside the bounds, a token file that exists), a Python older than 3.10, or the record refused because an estate value survived the scrub; nothing is written |

### What it sends, and in what order

Every path is under `/api/fleet-management/iam` on VCF Operations.

1. `GET /ssorealms`: the realm's id. Then a query of the realm's API clients; a client with the id you gave is refused,
   so a run cannot take over an identity someone else made.
2. `POST /ssorealms/{realm}/api-clients` with `clientId`, `clientName` and `clientDescription`.
3. `PUT /ssorealms/{realm}/principals/{client uuid}/roles`: one role, `scopeType` `SSO_REALM`, or with `--scope instance`
   `VCF_INSTANCE` with the instance's id, read first from `GET /ssorealms/{realm}`'s coverage. The fleet takes only these
   two scopes, never a folder. On the reference estate it refused `vcf_viewer` at an instance's scope ("Invalid role
   scope for the given role") and took `sddc_viewer`, which bundles only an instance's components (vCenter ReadOnly, NSX
   auditor). Holding it at one instance, the client reached that instance's vCenters (a REST session seeing their VMs, a
   SOAP sign-in); on the vCenter outside it a REST session still opened and saw no VM, and the SOAP sign-in was refused.
   Which other roles take an instance's scope was not read. A refused call's reason is kept in the record.
4. `POST /ssorealms/{realm}/api-tokens` with `tokenType` `API_CLIENT`, `apiTokenTtl` and `accessTokenTtl` in minutes. The
   token is written to `--token-file`, created exclusively at mode 0600, and never printed.
5. The token traded at the broker once (`POST /acs/t/{broker tenant}/token`, the API token grant), to prove it; the record keeps
   the status, the bearer's principal type and its lifetime, never the bearer.
6. The client and its token read back: present, its roles and their scope, the token's status and both lifetimes.

A rotation is two runs, with the integration's switch between them. `--rotate` queries the client and the tokens it
holds, and refuses a client that is not there (it never creates one), that the state file does not record, or that
the run is signed in as. It then
issues a new token (`POST /ssorealms/{realm}/api-tokens`, a name stamped with the time, both lifetimes), writes it to
`--token-file`, trades it at the broker once and reads back that it is active beside the old ones. It deletes nothing:
with `--old-token-file` it trades the old token too, so the record shows both working in the overlap. If the new token
does not trade, nothing is pointed at it and the run stops with exit 1, the run that did not hold. Point the integration at the new token and run
one job on it. Then `--retire-old` deletes every token of the client older than its newest, by the fleet's creation
date, and reads back that one is left; with `--old-token-file` it trades the old token before the delete and again
after, when it must be refused. It refuses a client holding one token, and a client whose newest token is not the one
this script issued last, since that may not be the token the integration holds.

A teardown queries the client's tokens and deletes each, deletes the client, then reads both lists again and records
the residue. A teardown of a client that is not there removes nothing and exits 0, so it is safe to re-run. Run it on
the token of the administrator who made the client: signed in as the client itself, nothing would outlive the removal
to read the residue, and the script refuses.

## The VCF Automation service account an integration moves to: `service_account.py`

In VCF Automation an integration signs in as a service account of its own. Plan first: with no `--execute` it prints
every call it would send, with its body, and sends nothing. The role is the role's name in the organization, never its
id; the script refuses an id.

```bash
export VCFA_HOST=<vcf-automation-fqdn>
export VCFA_PROVIDER_BEARER_FILE=/path/to/provider-bearer   # mode 0600; a provider System Administrator's bearer, as the
                                                            # reference runs used
export TLS_VERIFY=false                                     # only on a self-signed lab CA

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
| `VCFA_PROVIDER_BEARER_FILE` | a provider bearer you already hold, mode 0600: the credential every reference run used |
| `VCFA_PROVIDER_REFRESH_TOKEN_FILE` | instead, a provider API token, mode 0600, traded at `/oauth/provider/token` for a bearer; untried for these writes (how to mint one is platform-identity's plate 04) |
| `STATE` | the state file the create writes and the teardown reads (default `service_account.<org>.<name>.state.json`) |
| `TLS_VERIFY` | `false` only on a self-signed lab CA |
| `OUT` | the record (default `service_account.json`) |

**The credential its calls run on.** A provider credential: the reference runs sent every call on a provider bearer
whose session reads the System organization and the role System Administrator (read 2026-10-15); no narrower provider
role was tried, and no run sent these writes on a provider API token. The create writes a state file (mode 0600: the organization, the account's name and its OAuth client
id; no secret), and the teardown revokes and deletes only an account that file records with the same client id.

| Exit | Means |
|---|---|
| 0 | the plan printed; or the run held on read-back: the account active, its bearer's session holding exactly the role, the stored token refreshing; or, for a teardown, no account left and the revoked token refused |
| 1 | the run did not hold: a write was refused, or the read-back was not what was asked; a create that stopped part way prints where it stopped and the teardown to run before trying again |
| 2 | refused by this script before any write: an account that already exists (refused, never adopted), for a teardown an account the state file does not record, or no organization by that name |
| 3 | a read failed or is undetermined: the organization or the account list not read, the residue not read back, the provider's credential not traded for a bearer, or an error the script did not expect |
| 5 | a usage error (a missing or bad argument or variable, a role given as an id, a token file that exists), a Python older than 3.10, or the record refused because an estate value survived the scrub; nothing is written |

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

A teardown first refuses an account the state file does not record. It then revokes the account's token
(`POST /cloudapi/1.0.0/serviceAccounts/{id}/revoke`), deletes the account, reads the list until it is empty, and with
`--token-file` refreshes once with the revoked token to show it is refused. A teardown of an account that is not there
removes nothing and exits 0, so it is safe to re-run.

## What `vcenter_exchange.py` does, and in what order

1. `GET /api/vcenter/datacenter` with the broker's bearer as presented. vCenter refuses it; that is the expected answer,
   and the record keeps the status.
2. `POST /api/vcenter/authentication/token`, form-encoded, with the access token alone. vCenter answers a SAML token of
   the Bearer type that lives minutes.
3. `POST /api/session` with `Authorization: SIGN token="<base64(gzip(assertion))>"`: who the session is, whether it reads
   the VM list and how many VMs it sees (a count, never names: vCenter filters the list by the session's permissions, so a
   session with none reads an empty list with HTTP 200), then `DELETE /api/session`.
4. A second exchange, then `SessionManager.LoginByToken` over SOAP with the assertion in a WS-Security header, its XML
   declaration removed: who the session is, then `Logout`.
5. With `--sessions`: a SOAP session as `VC_USER` or, without it, a third exchange and `LoginByToken` as the client;
   `SessionManager.sessionList` read with `RetrievePropertiesEx`, the census's own session left out by its key, then
   `Logout`.

Steps 1 to 4 run only when an API client's credential is given.

## Scope, stated plainly

- `vcenter_exchange.py` is read-only. It opens sessions and closes them, and changes no configuration. The token
  exchanges mint tokens that live minutes and are not stored.
- `api_client.py` writes only with `--execute`: one client, one role binding, one token, a new token, the old tokens'
  removal, or the client's. A create refuses a client id that exists; every later write acts only on a client its state
  file records, and never on the client the run is signed in as, a rotation included.
- The lifetime bounds are the ones the broker held a create to on the reference estate, not documented ranges.
- A rotation was run on VCF 9.1.1 twice. On 2026-10-13 the earlier one-step `--rotate` showed the client holding two
  active tokens, the old token trading before the delete and refused after it (HTTP 400). On 2026-10-15 the two-step
  form ran: `--rotate` left two active tokens with the old one still trading and deleted nothing, `--retire-old` then
  deleted the old token, refused after (HTTP 400), and refused both a client no state file recorded and a client holding
  one token. The same day a second throwaway client, holding VCF Administrator and run on its own token, was refused its
  teardown before any delete; made by hand on that client's own bearer, the delete of its only token answered 204, the
  bearer still listed clients after the delete and then deleted its own client: the bearer outlived its token in that
  run, which is why the refusal rests on the residue read and not on a measured failure. The fleet API's in-place regenerate
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
  apart, and accounts named `svc-` counted as VCF's integration accounts), any other domain is another provider's, and a
  principal with no domain is counted apart as one. Each session's client agent is recorded
  without its version. Every agent but `vSphereUI` counts as a program; that rule comes from the agents seen on the
  reference estate's lists, where the one session from the vSphere Client read `vSphereUI`, not from a vendor list, so
  read the agents yourself.
- No local account is named in the record, because a local account's name can carry estate names; the census counts
  them. Directory accounts and API clients are recorded as placeholders, with their agents.
- A session list shows what is signed in at the moment of the read; the census is a sample, and `--compare` states how
  much of the clock and the calendar its samples cover. `--where` and `--compare` were first run on one management
  vCenter on 2026-10-15: six local administrator sessions placed, the record holding no address, and two keyed reads a
  minute apart compared. Later that day three reads of all three vCenters, minutes apart, compared with the default
  coverage and reported short of it. A comparison across a full job cycle has not been run, and `--ack` and the
  coverage options are held by the companion's tests.
- Measured on VCF 9.1.1 (three vCenters, build 25712839), 2026-10-13: the exchange with an API client holding
  `vcf_viewer`; the census read as that client holding `vcf_administrator`, and once with no API client, as a directory
  account's password. `api_client.py` ran on a VCF single sign-on user's API token whose user holds VCF Administrator
  through a group (read 2026-10-15); which narrower operator role may manage API clients was not tried, nor
  `OPS_BEARER_FILE`, nor a broker federated to a cloud provider. `service_account.py` ran on VCF Automation 9.1.1 with a provider bearer (the System organization's
  System Administrator, read 2026-10-15), in a throwaway All Apps
  organization federated to Entra ID, as `Organization User`; a classic organization and
  `VCFA_PROVIDER_REFRESH_TOKEN_FILE` were not tried with it.

## Reading the records

`exchange.json`: `summary` holds the lines the run exists for: `census_as` (`client` or `password`), `client_tried` and
`client_took_both_sessions` of `vcenters`, `bearer_as_presented` (the statuses seen), `saml_lifetime_s`, `session_users`
(who the client's sessions were), and with `--sessions` `sessions_read`, `census_only_own_session`, `sessions_by_class`,
`local_administrator_by_agent`, `local_administrator_not_interactive` (its sessions from clients other than the vSphere
Client), `directory_principals` and `directory_not_interactive` (the accounts with a pair from a client other than the
vSphere Client that no acknowledgement covers); with `--ack`, `directory_acknowledged`. `broker_tenant`, when present, records a tenant the
client's own session named that differed from the one set. `interactive_agents` is the agent set the run judged by,
`acks` how many acknowledgements were given and how many matched no pair read. `vcenters` holds each vCenter's steps:
each directory account carries its `agents`, `not_interactive_agents`, and with `--ack` the pairs `acknowledged` and
`ack_expired`. `sent` names every request that was not a plain read.

`api_client.json` (and `api_client_instance.json`, the same at one instance's scope): `asked` (the role, its scope, the
instance when one was named, and both lifetimes), `calls` (each call's method, templated path and status, and the
fleet's reason when it refused), `exchange` (the broker's status, the bearer's principal type and lifetime), `readback` and `exit`. A teardown's
record holds `calls`, `residue` (`client_present`, `tokens_left`) and `exit`. A rotation's record holds `asked` (both
lifetimes, and whether an old token was given), `calls`, `signed_in_as` (a person's token, another API client, or the
client itself; no name), `tokens_before`, `exchange` (the new token at the broker), `overlap` (the active tokens once
the new one was issued), `old_token_in_overlap` (the old token's status at the broker, the old ones kept), `next`,
`readback` and `exit`. A retirement's record (`api_client_retire.json`) holds `calls`, `signed_in_as`, `tokens_before`,
`deleted`, `old_token_before_delete` and `old_token_after_delete`, `readback` and `exit`. `api_client_rotate.json`, the
earlier one-step form, holds `old_token_before_delete` and `old_token_after_delete` in place of `old_token_in_overlap`.

`service_account.json`: `asked` (the role and its scope), `calls`, `registered` and `readback` (present, status, roles,
`require_rotation`), `device_grant` (its status, whether a refresh token came back, the bearer's lifetime in seconds),
`session` (the bearer's principal and roles), `refresh` (its status, the form that answered, whether the refresh token
was replaced) and `exit`. A teardown's record holds `calls`, `residue` (`account_present`), `revoked_token` (each
form of the refresh, with and without the client id, tried after the revoke and again after the delete, with its status
and OAuth error) and `exit`.

`exit` is the code the run exited with, under the table of its day. The codes were renumbered on 2026-10-15 to the
one contract above, and `exchange.json` predates that: its `exit` of 3 was then a directory account signing in from a
client other than the vSphere Client, which exits 1 now (the census does not change; `vcenter_exchange.py`'s
`exit_code()` reads 1 from the same record). The `api_client` and `service_account` records exited 0, which means the
same under both tables.

Every estate value is a placeholder: `{{host-N}}`, `{{client-N}}`, `{{name-N}}`, `{{domain-N}}`, `{{org-N}}`.
