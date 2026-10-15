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
| `watch.json` | That record from the reference estate, 2026-10-12, four throwaway organizations (classic and All Apps, OIDC and SAML). |
| `watch_passing.json`, `watch_group_renamed.json`, `watch_restored.json` | The watch on one throwaway All Apps organization over OIDC built to pass, 2026-10-13: after its first scheduled key refresh (every check ok but `secret_end`, which warned because the run gave its rotated secret 30 days, inside the 30-day window; exit 1), with the entitled group renamed at Entra (`group_names` fails; exit 2), and with the name restored (exit 1 again). The day-2 writes that set it up are the tenant-federation companion's `update_*.json`. |
| `expected-output.md` | The transcript of that run, with what to read in it. |

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
| 3 | nothing failed, and a read failed or a result is undetermined: the rollover checks not run on a run not declared `--provider-only` (no Graph credential given, so the tenant's read-only app is owed; a provider other than Entra ID), an organization federated to a tenant outside `--expect-tenants`, a run whose own tenant no organization names, a run that judged no organization (a wrong host, the only organization's federation switched off, a credential that lists none it can judge), the watch's own provider API token's end date unread (its token list refused, or no token or several it could single out), an organization whose reads were refused or whose lists were not read to their end, the tenant's app not found in Graph or found twice (two apps carrying the organization's identifier), a settings read with no secret to match, a Graph credential refused, a check that could not judge (`unknown`, such as a new organization before its first scheduled key refresh, or a held client secret whose end date does not read), a provider credential refused or the organization list not read whole before any organization was read, or a record the scrub refused (no record is written in those two cases). An error the watch did not expect exits 3 too, never 1 |
| 5 | not run as asked: an unknown or missing argument, `--protocol` without `--why`, a missing `VCFA_HOST` or provider credential, a credential or key file that cannot be read, a non-numeric `WARN_DAYS`, an Entra variable without `ENTRA_TENANT_ID` or `ENTRA_TENANT_ID` without the app's id and credential (unless `--provider-only`), a Graph credential with `--provider-only`, a tenant that is neither an id nor a domain name or a domain Entra names no tenant for, `--tenant-attested` without `--provider-only` or with a date that is malformed or in the future, a Python older than 3.9. Nothing is read from VCF Automation |

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
between pages, is a read that failed (exit 3), never a short or an empty list. Graph lists are read to their last
`@odata.nextLink`. Every pager is bounded: a page that adds no item not already read, or a next link that comes back,
is a read that failed at once, not after thousands of requests.

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
