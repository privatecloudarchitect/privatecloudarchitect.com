# Find the people who left, and close what they kept

Companion to the chapter
([privatecloudarchitect.com/handbook/identity-lifecycle](https://privatecloudarchitect.com/handbook/identity-lifecycle)):
one script that finds every VCF Automation account whose person has left at Entra ID, says what each still holds,
and, when asked for one organization, revokes the account's API tokens and disables it, reading both back. Report
only by default. Python 3.10 or later, standard library only; the `cryptography` package only if Graph is reached
with a certificate. No token, secret or password is printed or written.

| File | What it is |
|---|---|
| `leavers.py` | Finds every organization federated to one Entra tenant from the organization's own settings (OIDC by an issuer on the tenant, SAML by metadata naming it), reads each account against Entra and both gates a sign-in passes (the app's assignment, and a group imported into the organization that the sign-in can carry), and reports every leaver, the tokens it holds (how many, and the last one's end date, for every account) and what the run would do. It lists every role granted to a federated account directly, and flags an account disabled here whose name an enabled, entitled Entra user now holds; `--ack` silences a flag a person has decided on, until a date. `--execute --org` closes the confirmed leavers of one organization, and refuses an organization where an unusual share reads gone; `--close-now --org --user` closes one named, federated account at once, without asking Entra (under `oid`, by the object id the leaver notice carries, or a principal name with `--left-on` and its guard). On a provider API token it reads the token's own end date and flags it inside `WARN_DAYS`. Each state has its own exit code. Writes `leavers.json`, and refuses to write a record carrying any estate value. |
| `leavers.json` | That record from the reference estate, a read-only run on 2026-10-15 of the script as it stands (every open leaver confirmed over three reads before it counts): every organization federated to the lab tenant. |
| `expected-output.md` | The transcripts of that run, of the same run with its one flag acknowledged, of a closed leaver, of the urgent close on a Basic provider session's bearer, and of a run given `--expect-tenants`, with what to read in them. |

## Run it

```bash
export VCFA_HOST=<automation-fqdn>
export VCFA_PROVIDER_BEARER_FILE=/path/to/provider-bearer             # mode 0600; or VCFA_PROVIDER_REFRESH_TOKEN_FILE
export TLS_VERIFY=false                                             # only on a self-signed lab CA
export ENTRA_TENANT_ID=<tenant-id> ENTRA_CLIENT_ID=<app-id>         # the id (any case) or a domain name; the app reads users, groups and apps
export ENTRA_CERT_FILE=/path/to/cert.pem ENTRA_KEY_FILE=/path/to/key.pem   # or ENTRA_CLIENT_SECRET_FILE
export ORGS=<org>,<org>                                             # optional; default every federated organization
export OUT=leavers.json
export WARN_DAYS=30                # optional; on a provider API token, flag the run's own token this near its end

python3 leavers.py                     # report, print, record
python3 leavers.py --redact            # the same, printed with placeholders, for a transcript you will share
python3 leavers.py --name-claim <org>=mail   # the same, for an organization whose name claim carries mail (repeatable)
python3 leavers.py --ack acks.json     # the same, with the flags a person has decided on acknowledged until a date
python3 leavers.py --expect-tenants <t1>,<t2>   # the same, exiting 3 on an organization federated to a tenant outside the list
python3 leavers.py --execute --org <org> --user <account>   # close one confirmed leaver of one organization
python3 leavers.py --execute --org <org>                # close every confirmed leaver of that organization
python3 leavers.py --execute --org <org> --max-leavers 10   # the same, past the guard, once you know why so many left

# the urgent close, for a person who must lose access now, whether or not Entra has let them go yet:
python3 leavers.py --close-now --org <org> --user <account>             # the plan: the account, its tokens, the disable
python3 leavers.py --close-now --org <org> --user <account> --execute   # close that one account now, reading both back
# under oid by a principal name, with the departure date the leaver notice gives (see below):
python3 leavers.py --close-now --org <org> --user <principal name> --left-on <YYYY-MM-DD>
```

`<account>` names one account, in any case: its user name in VCF Automation (a principal name, or the object id in an
organization keyed on `oid`), the person's principal name in an organization keyed on `oid`, or the account's id
(`urn:vcloud:user:...`, in the record). The match (the name, the object id, the account it selects, and the dates
below) is printed before anything is sent. A name that selects no account, or more than one, refuses the run (exit 5)
and nothing is sent; pass the account's id from the record to choose between two. `--close-now` touches only that
account's tokens and record. Then remove the person at the provider, so the next report finds them in step.

Under `oid`, close by the object id the leaver notice or your last report carries. An account there is named by its
person's Entra object id, and a principal name resolves through the tenant's app (`GET /users/{principal name}`,
Microsoft Graph's Get user call, `User.Read.All`) to whoever holds the name now. If the name has gone to someone new
who has signed in, that is the new person's account: `--close-now` asks Entra nothing, so it would lock out the new
person and leave the departed person's account open. So a principal name is taken only with `--left-on`, the
departure date the notice gives, and the run is refused (exit 5, nothing sent) when the Entra user holding the name now
was created on or after that date, when the account it selects was made on or after it, or when that Entra user is
newer than the account (an account named by the name before the organization was keyed on `oid`). The printed match
gives both dates beside the object id: the Entra user's `createdDateTime`, and the account's creation as the audit
trail records it (`GET /cloudapi/1.0.0/auditTrail`, the account's import event at its first sign-in, or its create
event; the account record itself carries no creation time). An account older than the audit trail's reach has no such
event, and the trail's oldest event bounds it (on the reference estate the trail reached back about 39 days on
2026-10-15). A date the guard needs that did not read is a read that failed (exit 3), never a pass. Keyed on a name
(`preferred_username`, or SAML), the name is the account's key: the account a name selects is the one every holder of
that name signs in to, so no guard can choose between people, none runs, and no Graph variable is needed.

`--close-now` is for a federated account. It reads the account before anything is sent and refuses one that is not
federated (`LOCAL`, or anything but `OAUTH` or `SAML`) at the plan, with exit 5 and nothing sent. Before that check,
a run on a local account revoked its tokens and then had its disable refused (400, "You must set a password for local
users", 2026-10-15, one run), because the script keeps no password field from the record it writes back. Disable a
local account in the organization's own administration.

### A tenant that withholds the read-only app

The report needs the tenant's read-only app; without it, no report runs and nothing is judged. The close does not:
the tenant sends the provider a dated leaver notice naming the account and the departure date, and the provider runs
`--close-now` with the account's user name (its principal name, over SAML or OIDC keyed on `preferred_username`), the
object id the notice carries (under `oid`), or the account's id. None of the three reads Entra, so no Graph variable
is set. Under `oid`, ask the tenant for the object id: a principal name needs the tenant's app to resolve, and is
taken only with `--left-on` (above). A close by user name with no Graph variable set held on 2026-10-15 (one run); the
object id and the account's id are held by the script's tests.

### Many tenants

One run reads one Entra tenant. Where your organizations federate to several, run one schedule per tenant, each with
that tenant's read-only app, and pass every schedule the same full list: `--expect-tenants <t1>,<t2>,...` (tenant ids,
or domain names; the run's own `ENTRA_TENANT_ID` is taken as the run resolved it, any other domain name from Entra's
OpenID discovery document, `https://login.microsoftonline.com/<domain>/v2.0/.well-known/openid-configuration`, whose
issuer names the tenant id, with no credential). An organization federated to an Entra tenant outside the list, or
to this tenant in a form the script does not read, then reads `uncovered: no schedule reads it` and the run exits 3;
one on another provider is counted and not read. Without the flag, an organization federated elsewhere is counted
and not read, and changes no exit: tenant A's schedule can exit 0 while tenant B's leavers go unread. A list that
leaves out the run's own tenant, or a domain name Entra knows as no tenant, is a usage error (exit 5); a discovery
read that failed is 3. On the reference estate, which has one Entra tenant, the flag read the same organizations and
exited as without it (2026-10-15), by the tenant's id and by its domain name; an uncovered organization is held by
the script's tests.

### Your provider credential

By hand, the script runs on a provider bearer (`VCFA_PROVIDER_BEARER_FILE`, a file of mode 0600), the credential a
provider call presents. It acts in every organization, so hold it as tier-0 and delete it when the work ends. Two
sign-ins give one, and a close held on each on the reference estate:

- **The provider portal's sign-in.** Sign in at `https://<automation-fqdn>/provider`; the bearer is what the portal
  sends, the `Authorization` header of any `/cloudapi/` call in the browser's developer tools, after `Bearer `. The
  reference runs made this sign-in by script, so the capture by hand was not itself run. It lives an hour. The
  portal's own token page (My Account, then API Tokens, then New) issues an API refresh token, not a bearer: the
  provider API token below.
- **A Basic provider session**, for a System organization user whose password VCF Automation checks. curl asks for
  the password:

```bash
umask 077                                   # both files are created mode 0600
curl -s -X POST -u '<user>@System' -D - -o /dev/null -H 'Accept: application/json;version=9.1.0' \
     https://<automation-fqdn>/cloudapi/1.0.0/sessions/provider \
  | awk 'tolower($1)=="x-vmware-vcloud-access-token:" {sub(/\r$/, "", $2); print $2 > "provider-bearer";
         print "Authorization: Bearer " $2 > "provider-bearer-header"}'
# add -k only on a self-signed lab CA. The bearer never reaches a command line: a tool reads provider-bearer
# (VCFA_PROVIDER_BEARER_FILE), and curl reads the header from its file (-H @file, curl 7.55 or later).
# When the work is done, end the session, then remove both files; skip the end and remove them anyway,
# since the bearer stays valid until its hour runs out.
curl -s -X DELETE -H @provider-bearer-header -H 'Accept: application/json;version=9.1.0' \
     https://<automation-fqdn>/cloudapi/1.0.0/sessions/current
rm -f provider-bearer provider-bearer-header
```

  Run on 2026-10-15 as a directory account holding System Administrator, the credential given on standard input in
  place of curl's prompt: both files were written at mode 0600, the session read 200 with the bearer, the end as
  printed answered 204, the same read was then refused (401), and no file was left. An end sent without the
  `Accept` header answered 406 and left the session live, which is why the header is there. On such a bearer, with no Graph variable set,
  `--close-now --execute` disabled a federated account the provider made for the run and read it back (one run; the
  account held no token, so the revoke was not exercised). The System organization's local administrator was not
  tried. The Basic session's bearer lifetime was not read; plan for the hour.

A scheduled report holds a provider API token instead (`VCFA_PROVIDER_REFRESH_TOKEN_FILE`), which the script trades
at `/oauth/provider/token` for a bearer each run. The close does not run on one (below): run `--execute` and
`--close-now --execute` on a provider bearer.

The token ends. The one the reference estate holds ended 90 days after it was saved, less the three minutes between
its mint and its file being written; the site setting `apiTokenDurationMinutes` (read at `GET
/api/admin/extension/settings/general`) held 129600, which is 90 days, and whether that setting sets a provider token's
lifetime was not tested by changing it (2026-10-15, one token). Neither the mint calls below nor the token API's create
body offer a lifetime, and the portal's create box asks for a name. So the report reads its own token's end date on
every run: its session's user (`GET /cloudapi/1.0.0/sessions/current`), then the provider's token list (`GET
/cloudapi/1.0.0/tokens`, no tenant context), and the one `REFRESH` token that user owns (set
`VCFA_PROVIDER_TOKEN_NAME` to the name it was minted with when the user owns several); `expirationTimeUtc` is the end.
Inside `WARN_DAYS` (default 30, the federation watch's) the report flags it, exit 4, and a read of it that failed is
exit 3; the record's `credential` names the token (as a placeholder), its end and the days left, and the report prints
it as a `credential:` line. Run on the reference estate's token on 2026-10-15, the report read an end of 2026-11-04
(20.4 days): flagged at the default window, not at a window of 5 days, and on a provider bearer it said there is no
end date to read. Rotate it as the platform-identity chapter's plate 04, "Your provider API token", shows
([privatecloudarchitect.com/handbook/platform-identity](https://privatecloudarchitect.com/handbook/platform-identity)): record the rotation date before you issue the
new token, mint it, swap the 0600 file, run the report once on it, revoke the old one and read the list back.
The token measured was minted for a provider System Administrator and reads every organization, so hold it as
tier-0. A provider identity of the report's own, rather than a person's token, is the aim, and no path to one is
proven yet: a dedicated local user of the provider's System organization could not be made, the organization already
holding its one local user (2026-10-13), and the two other candidates, that existing local user and a directory
account granted a provider role, were not tried. Until one is proven, mint the token for a provider System
Administrator. The programmatic mint is two calls, with a provider bearer of the identity you mint it for:

```text
POST https://<automation-fqdn>/oauth/provider/register   Authorization: Bearer <provider bearer>
     {"client_name": "<the job's name>"}                  -> client_id
POST https://<automation-fqdn>/oauth/provider/token      (form)
     grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer&client_id=<client_id>&assertion=<the same bearer>
                                                          -> refresh_token: write it to a file of mode 0600
```

The token appears in the provider's token list (`GET /cloudapi/1.0.0/tokens`) under the client's name, type
`REFRESH`; retire it with `DELETE /cloudapi/1.0.0/tokens/{id}`, after which its refresh answers 400 `invalid_grant`.
The registered client stays: the API reference has no delete path for it. On the reference estate, 2026-10-13, a
token minted this way for a provider System Administrator carried a report run over every federated organization with
no call refused, reaching the provider bearer's decision on 11 of 12 accounts (the twelfth made between the two runs),
and read back with rotation not required. The close was refused on such a token: the write that disables the account answered 403 and the
account stayed enabled (a local user in a classic organization, one run; a federated account's close on that token was
not run), so the script reported that the close did not hold. The closes that held in the two end-to-end runs (2026-10-13: a leaver closed with `--execute --org --user`,
and an organization keyed on `oid`) ran on a provider bearer from the provider portal's sign-in: each run's harness
passed the script one, though the runs' records do not name the credential. No credential short of an
administrator's was found to carry the close: the token was refused it, and a dedicated local user of the provider's
own organization could not be made, the organization already holding its one local user (2026-10-13). A Basic
provider session carried it (above), but as a System Administrator, with that person's password. Not tried: that
existing local user, and a directory service account granted a provider role through the portal flow. The narrowest
provider role that lets the job pass was not measured. Scheduling the close would mean holding an administrator's
credential in the scheduler: the reference estate's own job signs in as the SSO administrator through the provider
portal's sign-in.

So the close is a person's step. Schedule the report on the token and alert on any non-zero exit: on 1 run the close,
`--execute --org` (or `--close-now`) on a provider bearer (above); on 3 fix the read before trusting any
decision (a leaver whose three reads disagreed is read again by the next run); on 4 decide each flag and acknowledge
it until a date; on 2 finish the close by hand. Each state has its own code, and the first that applies wins, so a
flag never hides a failed read or an open leaver. The codes keep the contract every identity companion keeps: 0
nothing for a person to act on, 3 a read failed or a result is undetermined (never a finding), 5 a usage error; 1, 2
and 4 are this script's own; an error the script did not expect exits 3, never 1.

| Exit | Means | What the scheduler does with it |
|---|---|---|
| 2 | with `--execute`, a close that did not hold on read-back (a token left, the account still enabled, or another field changed), or whose read-back did not read (refused, or a list answered without its values), the `result` naming which read | alert whoever ran the close: read the account's `result` in the record and finish it by hand |
| 1 | an open leaver: an account still enabled, or holding a token, whose person has left, on three reads that agree, including one `--execute` refused under the guard | alert whoever closes leavers: they run `--execute --org` on a provider bearer |
| 3 | a read failed (an organization, a gate, an account, a list answered without its values, a `--user` resolution, an `--expect-tenants` discovery read, the credential itself, the run's own provider API token's end date, or a date `--close-now`'s name guard needs), a tenant no organization names, an organization `--expect-tenants` leaves uncovered, an error the script did not expect, or an account is undetermined, among them a leaver whose three reads disagreed; and a run whose record was refused for a surviving estate value when it found nothing else | alert the job's owner: nothing is known about what was not read, so fix the read (a Graph permission, a credential, the tenant, the organization's user key, a `--name-claim` the reason names, `VCFA_PROVIDER_TOKEN_NAME`, or the schedule an uncovered organization's tenant lacks); a leaver whose reads disagreed is read again by the next run |
| 4 | a flag nobody acknowledged: a role granted to a federated account directly, or a name in use again; or the run's own provider API token inside `WARN_DAYS` of its end | open a ticket for the account's owner; once decided, acknowledge it in `--ack` until a date. For the token, rotate it; that flag is not acknowledged, and the rotation clears it |
| 0 | nothing open, nothing unread, nothing flagged; with `--close-now`, the plan printed or the close held | nothing |
| 5 | a usage error (a malformed `--name-claim`, `WARN_DAYS` or `--left-on` among them), a Python older than 3.10, an unreadable `--ack` file, a `--user` that selects no account or more than one, an `--expect-tenants` list that leaves out the run's own tenant or names a domain Entra knows as no tenant, and with `--close-now` an account that is not federated, or under `oid` a principal name given without `--left-on` or refused by the name guard; nothing is sent and nothing is written | fix the invocation; under `oid`, close by the object id |

A record the script refuses to write because an estate value survived its scrub never hides what the run found: the
run's own code stands when it is 1, 2, 3 or 4, and a run that found nothing exits 3, because the record a later tool
reads was not written.

An acknowledgement file is a JSON list; each entry names the organization, the account, the flag (`direct-role` or
`name-in-use-again`) and the last day it holds:

```json
[{"org": "<org>", "account": "<account>", "flag": "direct-role", "until": "2026-12-31"}]
```

The report still lists an acknowledged flag, marked `acknowledged until` its date; from the day after, it counts again.
An entry that matches no flag is counted on the report, so a stale file is noticed.

## What it decides, and when it acts

- **A leaver** is a federated account whose name Entra no longer holds, whose Entra user is disabled, or whose user
  can no longer pass both gates: the app's assignment (when the app requires one) and a group imported into the
  organization that the sign-in carries, or a role granted to the account directly. Accounts are matched to Entra by
  the key the organization names them with (see Scope). Local accounts are out of scope.
- **Entra's gate is read from direct membership.** Entra admits only a direct member of a group assigned to the app;
  a user whose only path is a group nested inside an assigned one was refused at Entra on the reference estate,
  although Graph's transitive read counted it a member. So the script reads each gate group's direct members
  (`GET /groups/{id}/members`, every page), and such a user reads leaver, its reason saying to make the user a
  direct member. With the app's group claims set to `ApplicationGroup`, only an imported group that is also assigned
  to the app, and that the user is a direct member of, is carried; with any other setting, groups reached through
  nesting are carried too.
- **A direct role keeps an account.** VCF Automation refuses a federated user who maps to no imported group and holds
  no direct role. An account that passes Entra's gate, is carried by no imported group and holds a role directly is
  the other case, so it reads keep (`assigned at Entra and holds a direct role`) and is flagged `direct-role`, exit 4,
  for a person to decide and acknowledge. It is never closed as a leaver.
- **How a name is looked up.** By `userPrincipalName`, then by `mail`, then by `otherMails`, each a `/users` filter
  Microsoft Graph serves by default (no `ConsistencyLevel` header, no `$count`). Every lookup is read, and exactly one
  Entra user across them is the person; more than one reads undetermined. The user found is the person only when the
  attribute the organization's name claim carries holds the name. The script cannot read which attribute that is, so
  it takes `userPrincipalName` unless you declare otherwise with `--name-claim <org>=mail` (or `otherMails`,
  repeatable, one per organization). Undeclared, a user found only by `mail` or `otherMails` whose
  `userPrincipalName` is another name reads undetermined, with a reason naming the mismatch and the flag to set,
  because a departed person's address left on a new hire would otherwise read as the departed person. Declared, a
  guest or an organization whose name claim carries mail resolves by mail, and a user found only by its principal
  name whose `mail` is another name is the one that reads undetermined. The record names each organization's
  declaration (`name_claim`) and counts declarations that matched no organization read (`name_claims`). A name none of them finds is a leaver only
  when another federated account of the same organization was found. When none was, every account of the
  organization reads undetermined, and the reason names the organization's user key: its names are not ones the
  lookups read.
- **The tenant is read the way you write it.** `ENTRA_TENANT_ID` may be the id in any case or a domain name of the
  tenant; a domain name is resolved to the id from the Graph token's `tid` claim, read in memory and never printed, or
  else Graph's `/organization` (which needs `Organization.Read.All`). An organization is federated to the tenant when
  its issuer or metadata names that id, compared without regard to case. A run in which no organization names it
  exits 3, never 0: a wrong tenant would otherwise read as nothing to do.
- **It fails closed.** An organization whose gate cannot be read, or an account whose user cannot be read, is
  reported undetermined and never acted on.
- **It alerts, and acts, only on what three reads agree on.** Entra's directory reads settle after a change. Every
  leaver still enabled or holding a token is read again three times, ten seconds apart, in a report as with
  `--execute`, and counts as open (exit 1), or is closed, only when every read says leaver; a leaver whose reads
  disagree reads undetermined (exit 3), its reason naming the reads, and the next run reads it again. An
  organization's leavers are read in the same three rounds, so the wait does not grow with their number: on the
  reference estate three such reads of an organization's leaver took 22 to 23 s (2026-10-15). A leaver already
  disabled with no token is not read again.
- **It acts only on a named organization.** `--execute` needs `--org`; `--user` narrows it to one account, chosen and
  printed before anything is judged or sent, as for `--close-now` above. Every account is still read and reported.
- **It refuses a mass close.** `--execute` refuses an organization whose open leavers number more than three and more
  than a quarter of its federated accounts (or more than `--max-leavers N`): it closes none of them, each reads
  `refused` with the reason, and the run exits 1. A share that size is more often a wrong lookup than a bad week, and
  naming one account with `--user` does not step around it. Read why so many read gone, then close them by name or
  rerun with `--max-leavers`.
- **A close** reads the account first and sends nothing to one that is not federated, then revokes each API token the
  account holds, then disables the account by writing its full record back with `enabled` false, then reads both
  back: no token left, the account disabled, and no other field changed. A read-back that did not read (refused, or
  a list answered without its values) is a close that did not hold, exit 2, its `error` naming the read. A
  SAML account created at first sign-in while the provider sent no email claim holds a value the platform refuses on
  update; when the write is refused naming the email field, it goes again with the email cleared, the one other field
  it changes, and the record's `email_cleared` marks it. A leaver already disabled with no
  token is in step, so a re-run changes nothing. A close leaves roles granted directly in place: the account closed
  on the reference estate kept its direct role, and the report flags it until a person removes it.
- **What it never acts on.** A role granted to a federated account directly is listed and flagged, because a new
  person later given the same name signed in to the same account and held it (over SAML and over OIDC keyed on
  `preferred_username`, with the account enabled; whether a disabled account turns that person away was not run). An account disabled here whose name
  an enabled, entitled Entra user now holds is flagged, because if that is a different person, enabling the account
  hands them its roles. Both are decisions for a person.
- **What the name check cannot see.** The flag above fires only on an account disabled here. An account never closed,
  still enabled, that a new person signed in to under a reused name reads keep like any entitled account: the user
  record in the provider API reference carries no creation time to compare with the Entra user's, so the script
  cannot tell the two people apart. Close a leaver's account when the person leaves, before the name can come back.

## What "direct" means here

Read from the API on one classic and one All Apps organization over each protocol (four organizations, 2026-10-13),
not inferred: each account's record carries `roleEntityRefs`, the roles granted to that account by name, and
`effectiveRoleEntityRefs`, those plus the roles that reach it through imported groups. On both organization types a
federated account entitled only through a group read `roleEntityRefs` empty and `effectiveRoleEntityRefs` naming the
group's role (Organization Member in the classic organizations, Organization User in the All Apps ones), and the
local administrator read Organization Administrator in both. "Direct" in the report is `roleEntityRefs`; the record
keeps both lists by name. A local account's roles are always direct, so local accounts are counted apart and not
flagged.

## Scope, stated plainly

- Read-only unless `--execute` is given. Its writes are `DELETE` of each of the leaver's API tokens and one `PUT` of
  the account's record; the record's `sent` lists every one.
- Entra ID only, one tenant per run: run one schedule per tenant, each given the same full `--expect-tenants` list
  (Many tenants, above). An organization federated to another provider, or signed in through VCF single sign-on, is
  counted as federated elsewhere and not read.
- Each organization's accounts are matched to Entra by the key the organization names them with, read from its own
  settings: by name for OIDC keyed on `preferred_username` and for SAML keyed on Entra's name claim, and by object id
  for OIDC keyed on `oid`. An organization keyed on anything else has every account undetermined, never a leaver, and
  an account whose name does not fit its organization's key is undetermined too. Matching by object id ran once on
  the reference estate (2026-10-13), on an All Apps organization keyed on `oid` for the run: two accounts named by
  object id read keep, one was closed with `--close-now`, the other read leaver once disabled at Entra and was closed;
  the accounts named by principal name read undetermined. A principal name given to `--user` under `oid` is resolved
  as above; that resolution ran read-only against the lab tenant on 2026-10-15, where each of ten federated accounts'
  principal names selected that account from a copy of its organization's list renamed to object ids, in both jobs.
  No organization federated to the lab tenant was keyed on `oid` that day, so selection on a live one was not run.
  `--close-now`'s name guard (`--left-on`) is held by the script's tests, among them a name reused by a newer Entra
  user; the audit trail's import and create events it reads were each found, read-only, for every account of the
  lab's four throwaway organizations on 2026-10-15, and Entra's `createdDateTime` on every user the lab tenant's app
  read; the guard was not run against a live reused name.
- What the name match covers, and what it was tested on. Every federated account on the reference estate was found
  by its `userPrincipalName` (2026-10-15). The `mail` and `otherMails` lookups found a throwaway member user whose
  `mail` and `otherMails` each held an address other than its `userPrincipalName`, the shape of a name claim sourced
  from mail: three reads each, once Graph's reads had settled after the user was made (2026-10-15). Such a find reads
  undetermined unless its organization is declared with `--name-claim <org>=mail`, so an organization whose name
  claim is sourced from mail, or whose people include Entra guests (their `userPrincipalName` in the tenant carries
  `#EXT#`), is declared once and then reads like any other. That user was never signed in to VCF Automation, so no
  organization whose name claim is sourced from another attribute was run end to end, declared or not; the
  declaration is held by the script's tests. An Entra guest was not tested: the reference tenant refused the
  throwaway guest's invitation. A name no lookup finds is judged as above: undetermined when no account
  of the organization is found, and a leaver otherwise, with the mass-close guard between it and `--execute`.
- What it cannot see: whether a revoked token was in use, sessions a leaver already holds, and the fleet's own users
  behind the identity broker (that half of the job is a design today). Of the sessions: a user disabled at the
  provider while signed in kept the session bearer it held to the end of its hour; disabling a local user's account
  in VCF Automation ended the session-login bearer it held at once (one run); whether the close ends a federated
  user's browser session was not tried. It cannot tell whether a name in use again belongs to the same person; it
  flags the case and acts on nothing.
- Measured on VCF Automation 9.1 against Entra ID with a provider bearer and a Graph certificate, and with a provider
  API token (2026-10-13: a report run held; a close was refused 403); the Graph client-secret path was not exercised
  on the reference estate. The Graph application permissions the reads need were measured on a throwaway app before
  the `mail` and `otherMails` lookups were added: `Application.Read.All`, `User.Read.All` and `GroupMember.Read.All`,
  and with the last one missing every account reads undetermined. The two newer lookups and the direct-member reads
  ran on the lab's automation app, which holds wider permissions; that the three suffice for them was not measured,
  though Microsoft Graph's reference lists `GroupMember.Read.All` among the application permissions for a group's
  members. On 2026-10-15 the report exited 4 on the reference estate (one flag, nothing open, nothing unread), and 0
  with that flag acknowledged; re-run that day with the direct-member reads, it reached the same decision on every
  account, no gate group had a group among its direct members, and no federated user was in a gate group only
  through nesting. Re-run once more with every open leaver confirmed over three reads, it reached the same decision
  on every account again and exited 4, in 30.2 s against 30.7 s for the version before (95 calls each); no leaver was
  open, so none was read again, and the three reads, timed apart on each organization's in-step leaver, took 22 to
  23 s and agreed.

## Reading the record

`organizations` holds one entry per organization, named `{{org-1}}` and onward, with its `protocol`, its `gate`
(whether the app requires assignment, its group claims, the groups assigned to it, the groups imported into the
organization and which of those a sign-in can carry) and a `users` list. Each account has its `providerType`,
`enabled`, `direct_roles` and `effective_roles` by name, its `tokens` by name and type, the `decision` and its
`reason`, `found` (whether a lookup found its Entra user) and `matched_by` (which lookup), any `flags`, with the
ones `--ack` covers under `acknowledged` (and an expired one under `ack_expired`), and, where the run did something or
would, its `action`; every leaver that was open carries `confirm_reads`, the three reads that confirmed it (or, for
one now undetermined, that disagreed), and a closed account a `result` with what was revoked and the read-back.
Each organization carries its `leaver_guard`: its open leavers, its federated accounts, the limit, and whether
`--execute` refuses it and why; one whose leavers were read again carries `confirm_seconds`. A run given `--user`
carries `user_match`: the name given, how it was resolved, the object id, and the account it selected. A run given
`--expect-tenants` carries `expected_tenants` and `elsewhere`: each organization federated elsewhere, its protocol,
the Entra tenant its issuer or metadata names (or none, for another provider) and who reads it (`read_by`), and
`summary` adds `other_tenants`, `other_provider` and `uncovered`. `summary` holds the totals (`keep`, `leaver`, `out_of_scope`, `undetermined`,
`open_leavers`, `refused`, `closed`, `not_held`, `in_step`, `direct_role`, `name_in_use_again`, `acknowledged`, and
`flagged`, the flags no acknowledgement covers) and `per_org`: per organization, its accounts, how many are federated,
found, kept, leavers, open and flagged, whether the guard refuses it, the federated accounts holding a direct role
with those roles (`direct_federated`), and how many local accounts hold one (`direct_local`). `acks` counts the
acknowledgement file's entries and the ones that matched no flag. `calls` holds every request with its status; `sent`
names every request that was not a read; `exit` is the code the run returned.
