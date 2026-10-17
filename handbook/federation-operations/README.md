# Will each federated organization keep signing in

Companion to the chapter
([privatecloudarchitect.com/handbook/federation-operations](https://privatecloudarchitect.com/handbook/federation-operations)):
one read-only script that reads both sides of every VCF Automation organization federated to Entra ID and says
which of them has drifted out of step, now or at the provider's next roll, with an exit code a scheduler can act
on. Stdlib Python 3.9 or later; the `cryptography` package only if Graph is reached with a certificate. No token,
secret or password is printed or written.

| File | What it is |
|---|---|
| `watch.py` | Reads each organization's OIDC or SAML settings, imported groups and local administrators from VCF Automation, the keys the provider publishes, and (optionally) the app behind the organization from Microsoft Graph, then runs nine checks: key refresh, keys held, PKCE, the client secret's end date, the SAML certificate's end date, whether the organization's metadata holds every signing certificate, imported group names against the groups assigned to the app, the app's own gate, and a local user holding the organization's top role (Organization Administrator in an All Apps organization, Organization Owner in a classic one) for the day the provider refuses; a run declared `--provider-only` with `--tenant-attested` adds a tenth, `tenant_report`, the age of the tenant's last report of its rollover dates. On a provider API token the run also checks that token's own end date (`own_token`). `--expect-tenants` names every tenant a schedule covers. `--why` is the sign-in router: what a user saw in, where it was refused and what to read first out. Writes `watch.json`, and refuses to write a record carrying any estate value. |
| `watch.json` | That record from the reference estate, 2026-10-16, four throwaway organizations (classic and All Apps, OIDC and SAML), read through the tenant's read-only app. |
| `watch_passing.json`, `watch_group_renamed.json`, `watch_restored.json` | The watch on one throwaway All Apps organization over OIDC built to pass, 2026-10-13: after its first scheduled key refresh (every check ok but `secret_end`, which warned because the run gave its rotated secret 30 days, inside the 30-day window; exit 1), with the entitled group renamed at Entra (`group_names` fails; exit 2), and with the name restored (exit 1 again). The day-2 writes that set it up are the tenant-federation companion's `update_*.json`. |
| `expected-output.md` | The transcript of that run, with what to read in it, and a replayed run. |
| `replay/watch/` | A recorded answer set built from `watch.json`, every name a placeholder, for `--replay`: the watch runs on it with no estate and sends nothing. |
| `inventory.py` | The provider's inventory across its Entra tenants: reads every organization's federation settings, as the watch reads them, against a file the provider keeps (each tenant's owners, its consent to the read-only app, its watch and leaver schedules, its organizations), and reports drift both ways. Read-only. See [The provider's inventory](#the-providers-inventory-tenants-consent-schedules-and-owners). |
| `inventory.example.json` | The shape of that file, placeholders only. |
| `replay/inventory/` | A recorded answer set built from the inventory's reference run (2026-10-16), every name a placeholder, and the inventory it was read against (`files/inventory.json`), its two schedules pointed at copies beside it of the records that run read (`files/watch.json`, the watch's record of 2026-10-12, and `files/leavers.json`, the leaver report's of 2026-10-15), for `--replay`. |

## Try it without an estate

`--replay DIR` answers every request from a recorded set instead of the estate, so you can run the watch before you
hold a provider credential or the tenant's read-only app, or see what it prints for a shape your estate has not shown
you. The set beside this README, `replay/watch/`, is the reference run of 2026-10-16 (`watch.json`) made into
answers, with a placeholder for every name: four organizations federated to one Entra tenant, read through the
tenant's app, beside the provider's own System organization, which the watch leaves out. `replay/inventory/` is the
inventory's reference run of 2026-10-16: ten organizations, the provider's file it was read against, which the set
names itself, and copies of the two schedule records that run read.

```bash
python3 watch.py --replay replay/watch            # read, print, and write watch.replay.json; exits 1, as the record did
python3 watch.py --replay replay/watch --redact   # the same, printed with placeholders
python3 inventory.py --replay replay/inventory    # the inventory against replay/inventory/files/inventory.json; exits 1
```

Nothing is sent and no credential is read: the set answers each request by its method, path and query, names the
placeholder hosts and tenant it was recorded on, and judges every date as of the record's time (for the inventory, the
age of each schedule's record). A request the set holds no answer for is a read that failed, so the run exits 3 and
names the read, never a pass. The inventory file a set names by a relative path is read from the set's folder; the
schedule records that file names are read from the disk as given. Each record goes to its `.replay.json` name
(`watch.replay.json`, `inventory.replay.json`) unless `OUT` names a file, so a replayed run never overwrites a real
record, and it carries `"replay": true`, so a reader never takes it for a run of the schedule: the inventory refuses
it as a run that did not read. The transcripts are under "A replayed run" in `expected-output.md`.

## Run it

```bash
export VCFA_HOST=<automation-fqdn>
export VCFA_PROVIDER_BEARER_FILE=/path/to/provider-bearer             # mode 0600; or VCFA_PROVIDER_REFRESH_TOKEN_FILE
                                                                    # a bearer: platform-identity's plate 04, "Your provider bearer"
export VCFA_PROVIDER_TOKEN_NAME=<the name the token was minted under>  # with a provider API token: which one is the watch's
export TLS_VERIFY=false                                             # only on a self-signed lab CA
# the rollover checks, through this tenant's read-only app (Microsoft Graph application permission Application.Read.All)
export ENTRA_TENANT_ID=<tenant-id or one of its domain names> ENTRA_CLIENT_ID=<app-id>
export ENTRA_CERT_FILE=/path/to/cert.pem ENTRA_KEY_FILE=/path/to/key.pem   # or ENTRA_CLIENT_SECRET_FILE
export ORGS=<org>,<org>                                             # optional; default every federated organization
export WARN_DAYS=30 OUT=watch.json

python3 watch.py --expect-tenants <tenant>,<tenant>   # read, print, record; the list names every tenant you serve
python3 watch.py --redact                             # the same, printed with placeholders, for a transcript you will share
python3 watch.py --why "Your Single Sign-On attempt failed" --protocol oidc

# a tenant that withholds the read-only app: declared, with no Graph credential set
unset ENTRA_CLIENT_ID ENTRA_CLIENT_SECRET_FILE ENTRA_CERT_FILE ENTRA_KEY_FILE
ENTRA_TENANT_ID=<that tenant> python3 watch.py --provider-only --expect-tenants <tenant>,<tenant> \
    --tenant-attested <YYYY-MM-DD, the date of the tenant's last report of its rollover dates>
```

Schedule it and read the exit code:

| Exit | Means |
|---|---|
| 0 | every check this run owns ran, on every organization it covers (at least one organization judged), and every one is ok, the watch's own provider API token's end date included when it runs on one |
| 1 | a warning: an end date inside `WARN_DAYS` (the watch's own provider API token's among them), a refresh interval over one hour, a signing certificate the organization does not yet hold, no local user holding the organization's top role, a tenant's report older than `--attested-max-days` |
| 2 | a failure that stops sign-in now or at the provider's next roll: a published key not held, refreshes not succeeding, an expired secret or certificate, a secret the organization holds that the app no longer lists, the active certificate missing from the organization's metadata, a renamed group, PKCE on, a disabled app |
| 3 | nothing failed, and a read failed or a result is undetermined: the rollover checks not run on a run not declared `--provider-only` (no Graph credential given, so the tenant's read-only app is owed; a provider other than Entra ID), an organization federated to a tenant outside `--expect-tenants`, a run whose own tenant no organization names, a run that judged no organization (a wrong host, the only organization's federation switched off, a credential that lists none it can judge), the watch's own provider API token's end date unread (its token list refused, or no token or several it could single out), an organization whose reads were refused or whose lists were not read to their end, the tenant's app not found in Graph or found twice (two apps carrying the organization's identifier), a settings read with no secret to match, a Graph credential refused, a check that could not judge (`unknown`, such as a new organization before its first scheduled key refresh, or a held client secret whose end date does not read), a provider credential refused or the organization list not read whole before any organization was read, or a record the scrub refused (no record is written in those two cases), or a request a `--replay` set holds no answer for. An error the watch did not expect exits 3 too, never 1 |
| 5 | not run as asked: an unknown or missing argument, `--protocol` without `--why`, a missing `VCFA_HOST` or provider credential, a credential or key file that cannot be read, a non-numeric `WARN_DAYS`, an Entra variable without `ENTRA_TENANT_ID` or `ENTRA_TENANT_ID` without the app's id and credential (unless `--provider-only`), a Graph credential with `--provider-only`, a tenant that is neither an id nor a domain name or a domain Entra names no tenant for, `--tenant-attested` without `--provider-only` or with a date that is malformed or in the future, a `--replay` directory that cannot be read or holds no replay set, a Python older than 3.9. Nothing is read from VCF Automation |

`--why` keeps its own two codes: 0 a row matched, 1 none did (it prints the first reads for a message no run showed).

**One schedule per tenant.** A provider with several Entra tenants runs the watch once per tenant, each run with that
tenant's `ENTRA_TENANT_ID` and read-only app, and each passing the full tenant list with `--expect-tenants` (ids or
domain names; a domain is resolved through Entra's public OpenID configuration for it). An organization federated to
another tenant prints `another tenant's: its own schedule reads it`: it is named, read no further and left out of this
run's exit, so onboarding a second tenant does not turn the first tenant's schedule red. An organization federated to a
tenant outside the list prints `uncovered: no schedule reads it` and exits 3, and a run whose own tenant no
organization names exits 3 too, since a wrong `ENTRA_TENANT_ID` would otherwise read every organization as another
tenant's and pass.

**Without the tenant's read-only app.** A run with no Graph credential reads the organization's side alone:
`key_refresh`, `keys_held`, `pkce` and `break_glass`, and runs none of the rollover checks, `secret_end`,
`saml_cert_end`, `saml_cert_held`, `app_gate` and `group_names`. Undeclared, each of those prints `rollover checks not
run: the tenant's read-only app is owed`, the run ends with what it read and what it did not, and it exits 3 every
time: a secret that ends next week is invisible to it, so its silence is not a pass. A tenant may withhold the app for
good, because `User.Read.All` and `GroupMember.Read.All` read its whole directory, and a code that stays 3 teaches
on-call staff to ignore it. Declare that run with `--provider-only`: it takes no Graph credential, its exit is the
organization's side (0, 1 or 2 on what it read), and the rollover checks are listed as owed by the tenant, whose
administrator runs them and reports the dates. `--tenant-attested YYYY-MM-DD` gives the date of the tenant's last
report of its rollover dates; a report older than `--attested-max-days` (default 30) warns, exit 1. The report is
optional, and it never stands in for a check the run did not make.

**The watch's own credential.** Scheduled, the watch holds a provider API token (`VCFA_PROVIDER_REFRESH_TOKEN_FILE`),
which has an end date: the one minted for the reference run ended 90 days after it was made. The watch reads that date
from the provider's token list (`GET /cloudapi/1.0.0/tokens`, every page): the `REFRESH` token of its own session's
user, the one named `VCFA_PROVIDER_TOKEN_NAME` when that user holds more than one (set it to the client name the token
was minted under). Inside `WARN_DAYS` the run warns, exit 1: mint the next token under a new name, set
`VCFA_PROVIDER_TOKEN_NAME` to that name and swap the 0600 file, run the watch once on it, then revoke the old one
(`DELETE /cloudapi/1.0.0/tokens/{id}`) and read the list back. Until the old one is revoked the user holds two refresh
tokens, and the variable is what picks the one the watch runs on: unset, the run cannot single its token out (exit 3). A token list it could not
read, or that holds none or several it could single out, leaves the date undetermined, exit 3. Each mint leaves a
client registration behind, which the API reference read offers no call to delete. On a provider bearer the check does
not run: a bearer is minted for a run, not held by a schedule.

**A run that judges nothing is never a pass.** By default the watch reads every organization with OIDC or SAML on and
leaves out the rest. A run that judged none, because `VCFA_HOST` names the wrong estate, because the tenant's only
organization had its federation switched off, or because the credential lists none it can judge, prints `the run judged
no organization`, with what it listed and why each was left out, and exits 3. Each organization left out because
neither OIDC nor SAML is on is printed as `OFF` with its name, and counted in the record's `census`. Every VCF
Automation list is read until its distinct items reach the total the answer states (`resultTotal`): a page that
answers without its list or its total, a page that comes back empty or short before the total, or a total that moves
between pages, is a read that failed (exit 3), never a short or an empty list, and so is a page that adds no item not
already read, at once rather than after thousands of requests. Graph lists are read to their last `@odata.nextLink`: a
page holding no item is read on, since Microsoft's paging guidance says "A page of results might contain zero or more
results" ([Paging Microsoft Graph data in your app](https://learn.microsoft.com/en-us/graph/paging)), and a 200 without
its `value` list, a next link that is not a link or comes back a second time, or a list still paging after 10,000 pages,
is a read that failed.

A read the watch could not make never passes. An organization whose reads fail stays in the run and the record,
named and counted, whether or not `ORGS` names it: with `ORGS` unset, an organization that could not be read cannot
be shown to be unfederated. The secret check judges only the secret the organization holds, found by its first
three characters against each secret's `hint`; when that secret matches none on the app, the state a rotation leaves
when the old secret is removed before the new one is written, the check fails rather than judging another secret.
When two or more of the app's secrets share that hint, which one the organization holds cannot be told, so each is
judged and the first to end stands (`sharing_hint` in the record). Every secret the hint matches is judged, whether
or not its end date reads: one whose end date does not read leaves the first end not known, so the check reads
`unknown` and the run exits 3 (`unread_end` in the record), unless another matched secret has already ended, which
fails whatever the unread one holds. A last successful key refresh whose time does not read is `unknown` too, not a
refresh that failed.

## Scope, stated plainly

- Read-only. Every call is a GET; nothing on VCF Automation or Entra changes.
- The secret dies where it arrives. VCF Automation returns an organization's OIDC client secret in clear to the
  provider; the script deletes it inside the function that read it, keeping its first three characters only long
  enough to match the `hint` Graph returns for each of the app's secrets, so `secret_end` judges the secret the
  organization actually holds.
- Organizations signed in through VCF single sign-on, and the provider's own consumption organization, are left out
  by default: their sign-in settings are the platform's (name one in `ORGS` to read it anyway). An
  organization federated to another OIDC provider gets the organization-side checks (key refresh, keys held,
  local administrator); the rollover checks run only where the issuer is Entra ID, so such an organization reads
  `not_run` and the run exits 3 (leave it out of `ORGS`, and track that provider's dates by its own means).
- The key-refresh signal is the age of the last *successful* refresh against the interval plus an hour. On a 24-hour interval
  the attempt timestamp moves every hour and the success timestamp once a day, so a difference between them is
  not a failure. On the cycle read (one organization), the refresh ran at the first hourly run a full interval after
  the last success, and a run 0.4 s short of the interval did not refresh, so a healthy success can be up to the
  interval plus an hour old. The check fails when the last success is older than the interval plus an hour, counted
  in whole minutes: every hourly run read recorded its success within the first three seconds of the hour, and a read
  in those seconds must not fail an organization whose refresh is under way. `keys_held` checks the outcome directly
  against the provider's published keys.
- What it cannot see: whether a provider that is unreachable (rather than refusing) would be survived; the claim
  form synchronized Active Directory groups need (not tested); a user's MFA state; Entra's sign-in log, which is
  where `--why` sends you first.
- Whose read each check is. `key_refresh`, `keys_held`, `pkce` and `break_glass` read the organization and the
  provider's public keys endpoint: the provider runs them alone. `secret_end`, `saml_cert_end`, `saml_cert_held`,
  `app_gate` and `group_names` read the tenant's Entra app in Microsoft Graph, so they run through a read-only app
  the tenant registers and consents in its own directory; without one, the run says they were not run and exits 3,
  and until the app is held the tenant runs them and reports them.
- The Graph application permission those checks need is `Application.Read.All`, measured on 2026-10-13 by narrowing:
  a throwaway app on the lab tenant ran this script read-only under six sets of `Application.Read.All`,
  `User.Read.All` and `GroupMember.Read.All`. With `Application.Read.All` alone every Graph check ran; in every set
  without it, none did. In one run holding `Application.Read.All` and `GroupMember.Read.All` the Graph checks were
  skipped with an HTTP error; that run was not repeated and is not explained. The app was deleted and purged.
- Measured on VCF Automation 9.1 against Entra ID, with a provider System Administrator's bearer, and with a Graph
  certificate (the reference run) and a Graph client secret (the permission measurement). On 2026-10-15 it ran once on
  a provider API token minted for the run from that bearer, on two standing organizations: no read was refused, every
  check read the same state as on the bearer, the token's own end date read 90 days out, and the token was revoked after. One
  schedule per tenant and the declared
  provider-only run were read on 2026-10-15 on two standing organizations of the lab's one Entra tenant, with a run
  tenant and a tenant list made up for the run; an organization federated to a second real tenant was not run. No provider identity narrower than an administrator was proven for a
  scheduled job: a dedicated local user of the System organization could not be made (the organization already held
  its one local user), and the System organization's existing local user and a directory account granted a provider
  role were not tried. Hold whatever credential the schedule uses as tier-0.

## Reading the record

A record a `--replay` run writes carries `"replay": true` at its top level, and a live run's carries no such key: a
replayed record shows no read of an estate, and the inventory takes it as a run that did not read.
`organizations` holds one entry per organization, named `{{org-1}}` and onward, with its `protocol` and
`org_type` and a `checks` list. Each check has a `state` (`ok`, `warn`, `fail`, `unknown`), a `detail` sentence
and a `measure` with its numbers: `interval_h` and `success_age_h` for key refresh, `held`, `published` and
`missing` for keys, `days_left` and `matched` (whether the organization's own secret was identified; when it was not, the check fails
and `days_left` is null), `sharing_hint` where several secrets share its hint, and `unread_end` where a matched secret's end date does not read, for the secret, `days_left` for the SAML certificate, `stored` and `others_not_held` for metadata, `imported`, `assigned`
and `unmatched` for group names, `local_admins` and `role` (the top role judged, read from the organization's own role list) for break-glass. `read_errors` names any plane that could not be
read. `not_run`, where present, names the rollover checks the run did not make for that organization, `why`, and
what is `owed` for them to run (for a run without a Graph credential, the tenant's read-only app; on a declared
`--provider-only` run, the tenant, with `declared` set). Each organization federated to Entra carries its `tenant` as
`{{tenant-1}}` and onward (the run's own first), and `coverage` where this run does not own it: `another tenant's: its
own schedule reads it`, or `uncovered: no schedule reads it`. A declared run given `--tenant-attested` adds a
`tenant_report` check with `age_days` and `max_days`. At the top, `mode` is `with the tenant's app`, `provider-only,
declared` or `provider-only, undeclared`; `tenant` the run's own; `expected_tenants` how many `--expect-tenants`
named, the run's own included; `tenant_attested` the report's date and age; `credential` the kind the run held and, on a provider API token,
its `own_token` check (`days_left`, and `candidates` and `listed`, the counts it singled the token out of); `census` what
the run listed and left out before reading (`listed`, `provider_own`, `off`); `judged` how many organizations it judged;
`run_errors` what is wrong with the run as a whole; and `exit` the code the run returned.

## The provider's inventory: tenants, consent, schedules and owners

The watch and the leaver report (the identity-lifecycle companion's `leavers.py`) each run once per Entra tenant, and
neither holds the list of tenants they run for. `inventory.py` holds that list in a file the provider keeps and reads
the estate against it both ways: an organization federated to a tenant the file has no row for, or missing from its
tenant's row, and a row or a declared organization that names no organization. Beside each tenant it holds the owners
on each side, the tenant's consent to the read-only app, and the last record each of the tenant's two schedules wrote.
Stdlib Python 3.9 or later. Read-only.

**What it reads.** `GET /cloudapi/1.0.0/orgs`, read whole with the watch's pager, and for each organization but the
provider's own consumption organization `GET /api/admin/org/{id}/settings/oauth` and `.../settings/federation`, read as
the watch reads them: OIDC is on when its settings are enabled and not signed in through VCF single sign-on (`vidb`),
SAML when its federation settings are enabled. The client secret the OIDC settings carry is deleted on arrival and
never read. The Entra tenant comes from the stored OIDC issuer or the stored SAML metadata, read whether or not the
protocol is switched on; an organization switched off whose stored settings name no Entra tenant reads as not
federated. On a provider API token the run first trades it at `/oauth/provider/token` (a POST that opens a session
and changes no setting). A tenant the file names by a domain is resolved through Entra's public OpenID configuration
for it, with no credential. From the local disk it reads the file and each schedule's last record. It takes no Graph
credential: a tenant's consent is read from the watch's own record.

**The file.** JSON, named by `INVENTORY_FILE`; `inventory.example.json` shows its shape with placeholders. Copy it to a
file of your own and keep that file private: it names your estate. One row per Entra tenant:

| Key | What it holds |
|---|---|
| `tenant` | the tenant's id, or one of its domain names, resolved as the watch resolves it |
| `consent` | `consented`, or `withheld` (the tenant's watch runs declared `--provider-only`) |
| `owners` | `tenant`, the tenant's identity administrator, and `provider`, the provider's owner of the tenant: each a role or a mailbox |
| `schedules` | `watch` and `leavers`, each `{"every_hours", "record", "slack_hours"}` or `null`. `record` is the path of the record that schedule writes, read from the file's own folder when it is not absolute; `slack_hours` defaults to 1. A tenant that withholds the app has `leavers: null`: the report needs the app, and a leaver is closed from the tenant's dated leaver notice |
| `organizations` | each organization declared under the tenant: a name, or `{"name", "id", "federation"}`. Give the `id` (`urn:vcloud:org:<uuid>`) so a name reused by a new organization is caught, and `"federation": "off"` for one switched off on purpose |

Keys starting with `_` are notes. Any other key not listed is refused (exit 5), so a misspelled key is never read as a
missing one; a tenant in two rows, an organization declared twice, and a `leavers` schedule for a tenant that withholds
the app are refused too.

```bash
export VCFA_HOST=<automation-fqdn>
export VCFA_PROVIDER_BEARER_FILE=/path/to/provider-bearer   # mode 0600; or VCFA_PROVIDER_REFRESH_TOKEN_FILE
export TLS_VERIFY=false                                    # only on a self-signed lab CA
export INVENTORY_FILE=/path/to/tenants.json                # your own copy of inventory.example.json
export OUT=inventory.json                                  # the run's record: never the file or a schedule's record

python3 inventory.py            # read, print, record
python3 inventory.py --redact   # the same, printed with placeholders, for a transcript you will share
```

**What it judges.** Each line carries a state: `OK`, `DRIFT`, `UNREAD`, or `NOTE`, which is information and changes no
exit.

- **Organizations.** One with OIDC or SAML on toward a tenant the file has no row for, or missing from its tenant's row,
  is drift; so is one declared under another tenant's row than the one its settings name, one switched off while
  declared on or on while declared off, and one declared while it signs in through VCF single sign-on. An organization
  switched off is reported as switched off, never as missing. One on toward a provider other than Entra ID, one signed
  in through VCF single sign-on, and one never federated are notes while undeclared. The provider's own consumption
  organization is listed as the provider's, as the watch leaves it out. One whose settings read was refused is named
  and unread.
- **Rows.** A declared organization nothing matches is drift: no organization by its name, its declared id held by an
  organization of another name, or its name held by an organization of another id (a name reused by a new
  organization, which only the declared id catches). A row no organization names, switched on or off, is drift; when
  an organization's settings were not read it is unread instead, since the unread one may name it.
- **Owners.** A blank or missing owner on either side is drift.
- **Schedules.** A schedule whose last record is past its interval plus its slack missed its run: drift, whatever the
  record holds, since no run has written it since. A record that is missing, does not read, carries no capture time
  that reads, or comes from a run that did not read is unread. No watch schedule is drift, and so is no leaver report
  for a tenant that consented.
- **Consent.** The file's consent against the mode the watch's last record carries: `consented` beside a run declared
  provider-only or run without the app, or `withheld` beside a run made with the tenant's app or not declared, is
  drift, and the line names the change. A record that did not pass its check is not compared.

**The record check.** Before it uses a schedule's record, the inventory checks that the run which wrote it read. The
record parses as a JSON object and carries the fields used here: the watch's `captured`, `exit`, `mode`, `judged`,
`run_errors` and `organizations`, each with its `read_errors`; the leaver report's `captured`, `exit`, `mode`,
`organizations`, `unreadable`, `summary` and `calls`. It does not declare itself replayed (`replay`: a run answered
from a recorded set is no run of the schedule). Its exit is one its tool writes, and not 3 or 5. The watch judged
at least one organization and names no run error and no organization's read error. The leaver record is a report (an
`--execute` or close-now record covers one organization), names no unreadable organization, no undetermined account and
no unread credential, judged at least one organization, and records no call refused or misshapen. A check that could
not run is never a pass. What a record found (the watch's warnings and failures, the report's open leavers and flags)
is its own schedule's to act on: the inventory prints the record's exit beside it and leaves it out of its own. A
record names its tenant by a placeholder, so the `record` path in the file is what ties a record to its tenant.

| Exit | Means |
|---|---|
| 0 | nothing for a person to act on: every organization read and placed as the file declares, every row matched, both owners named on every row, every declared schedule's last record inside its interval plus its slack and from a run that read, and each tenant's consent matching the watch's last record |
| 1 | drift a person acts on: an organization with no row or missing from its row, a row or a declared organization that names no organization, a reused name or a moved id, a declared state the estate does not hold, a blank owner, a missed schedule, a schedule not declared, a consent the watch's record contradicts |
| 3 | the run judged no organization (a wrong host, a credential that lists none it can read), whatever else it found; or nothing drifted, and a read failed or a result is undetermined: an organization's settings read refused (named), a row the unread organization may answer, a schedule's record missing, unreadable or from a run that did not read; or, with no record written, the credential refused, the organization list not read whole or empty, or a tenant's domain not resolved. A request a `--replay` set holds no answer for is a read that failed. A record the scrub refused is not written, never hides a 1, and turns a 0 into a 3. An error the run did not expect exits 3 too, never 1 |
| 5 | not run as asked: an unknown or abbreviated flag, a missing `VCFA_HOST`, provider credential or `INVENTORY_FILE`, a file that cannot be read, a file that is not valid JSON or not the shape above, a tenant that is neither an id nor a domain name or a domain Entra names no tenant for, a tenant or an organization declared twice, `OUT` naming the file or a schedule's record, a `--replay` directory that cannot be read or holds no replay set, a Python older than 3.9. Nothing is read from VCF Automation |

**Schedule it** once a day, after the tenants' watch and leaver schedules, and alert on any non-zero exit: on 1 the line
names what to change (the file, a schedule, or an organization), and on 3 fix the read it names. Give each schedule's
`slack_hours` the time its job takes plus the scheduler's jitter.

**What it never does.** It sends no write: every request but the API token's trade is a GET, and nothing on VCF
Automation or Entra changes. It takes no Graph credential. It prints and writes no secret, and its record carries no
owner's value (`named` or `blank` only), no record path and no estate value. It never writes the file or a schedule's
record: `OUT` naming either is refused before anything is read. It does not judge what a watch or leaver record found.

**Reading its record.** `census` counts what the run listed and read (`listed`, `provider_own`, `unread`, `judged`,
`oidc`, `saml`, `switched_off`, `vcf_sso`, `other_provider`, `tenants_named`, `rows`, `declared`). `tenants` holds each
row's `consent`, `owners` (`named` or `blank`), how many organizations it `declared`, and its schedules' terms.
`organizations` holds each organization's `state` (`oidc`, `saml`, `off`, `vcf-sso`, `provider` or `unread`) and
`tenant`. `findings` holds every line, with its `state` (`ok`, `drift`, `unread`, `note`), `subject`, `tenant`, `org`
and `detail`, and for a schedule a `measure`: `age_h`, `every_hours`, `slack_hours`, `record_exit`, `record_mode`, and
`problems` where the record failed its check. `run_errors` is what is wrong with the run as a whole, and `exit` the code
the run returned. Organizations are `{{org-1}}` and onward, tenants `{{tenant-1}}` and onward, the file's rows first. A
run under `--replay` writes `inventory.replay.json` and marks it `"replay": true` at its top level; a live run's record
carries no such key.

**Scope.** Run read-only on 2026-10-16 against the reference estate's VCF Automation and the lab's one Entra tenant,
on a provider bearer: ten organizations listed and nine read (four federated to the tenant, one over OIDC to another
provider, one on VCF single sign-on, three with neither protocol on and no Entra tenant stored), every request a GET.
The tenant's watch schedule, pointed at the `watch.json` this folder then held (written on 2026-10-12), read as a
missed run (its record about 95 hours old, and lacking `mode`, `judged` and `run_errors`); its leaver schedule,
pointed at the identity-lifecycle companion's `leavers.json`, read as on time and from a run that read; exit 1. Run
again that evening against the `watch.json` a new watch run had just written, it read the watch schedule as on time and
from a run that read and the consent as the file states, and the leaver schedule's record, by then 25.5 hours old, as
a missed run; exit 1. A second tenant, a tenant that withholds the app, a switched-off organization holding a stored
tenant, a reused name and a refused read are held by the companion's tests, not by a run.
