# Find the people who left, and close what they kept

Companion to the chapter
([privatecloudarchitect.com/handbook/identity-lifecycle](https://privatecloudarchitect.com/handbook/identity-lifecycle)):
one script that finds every VCF Automation account whose person has left at Entra ID, says what each still holds,
and, when asked for one organization, revokes the account's API tokens and disables it, reading both back. Report
only by default. Python 3.10 or later, standard library only; the `cryptography` package only if Graph is reached
with a certificate. No token, secret or password is printed or written.

| File | What it is |
|---|---|
| `leavers.py` | Finds every organization federated to one Entra tenant from the organization's own settings (OIDC by an issuer on the tenant, SAML by metadata naming it), reads each account against Entra and both gates a sign-in passes (the app's assignment, and a group imported into the organization that the sign-in can carry), and reports every leaver, the tokens it holds (how many, and the last one's end date, for every account) and what the run would do. It lists every role granted to a federated account directly, and flags an account disabled here whose name an enabled, entitled Entra user now holds; `--ack` silences a flag a person has decided on, until a date. `--execute --org` closes the confirmed leavers of one organization, and refuses an organization where an unusual share reads gone; `--close-now --org --user` closes one named, federated account at once, without asking Entra (under `oid`, by the object id the leaver notice carries; a principal name is resolved and checked by the plan only). An organization with its federation switched off is listed, and exits 3 while it still holds an enabled federated account or a token of one. Every list is read to the total it states, or the run exits 3. On a provider API token it reads the token's own end date and flags it inside `WARN_DAYS`. Each state has its own exit code. Writes `leavers.json`, and refuses to write a record carrying any estate value. |
| `leavers.json` | That record from the reference estate: a read-only run on 2026-10-15 at 21:14 UTC of the script as it stands, on the provider API token the estate keeps, covering every organization federated to the lab tenant and the three with their federation switched off. |
| `replay/leavers/` | A recorded answer set made from `leavers.json`, every name a placeholder, for `--replay`: `leavers.py` runs on it with no estate, reaches every decision the record holds, and sends nothing. |
| `expected-output.md` | The transcript of that run, and of earlier runs of earlier versions, each labeled with its date: the report with its one flag acknowledged, a closed leaver, the urgent close on a Basic provider session's bearer, a run given `--expect-tenants`, and the leaver test before and after a close, with what to read in them; and a replayed run of each script on its recorded set. |
| `leaver_test.py` | The leaver test, read-only: for one test user removed at Entra, reads that its account is disabled with no API token left, that its own API token no longer refreshes, and that Entra's sign-in log holds a refused sign-in to the organization's app, each against the deadline you promise (below). |
| `replay/leaver_test/` | A recorded answer set made from the passing run of the leaver test over SAML on the reference estate (2026-10-15), every name a placeholder, for `--replay`: `leaver_test.py` runs on it with no estate and sends nothing. |

## Try it without an estate

`--replay DIR` answers every request from a recorded set instead of the estate, so you can run a script before you
have an estate to read, or see what it prints for a shape your estate has not shown you. Each set beside this README
is a run on the reference estate made into answers, with a placeholder for every name:

```bash
python3 leavers.py --replay replay/leavers --redact                 # the report behind leavers.json: exit 4
python3 leavers.py --replay replay/leavers --execute --org org-3    # the close's plan alone: nothing is sent
python3 leavers.py --replay replay/leavers --close-now --org org-3 --user user-4@domain-1.example.test --execute  # the urgent close's plan alone
python3 leaver_test.py --replay replay/leaver_test --org org-1 --user name-1@domain-1.example.test --app 00000000-0000-4000-8000-000000000003 --removed-at 2026-10-15T23:50:27Z --latency 30  # every check passes: exit 0
python3 leaver_test.py --replay replay/leaver_test --org org-1 --user name-1@domain-1.example.test --app 00000000-0000-4000-8000-000000000003 --removed-at 2026-10-15T23:50:27Z --latency 5  # the same reads after a 5-minute deadline: exit 3
```

Nothing is sent and no credential is read: the set answers each request by its method, path and query (a read in an
organization's tenant context only from that organization's answers), and names the placeholder hosts it was recorded
on. A run judges its dates at the time the set was recorded: `replay/leavers/` is the report behind `leavers.json`,
read at 21:14 UTC with the run's own provider API token 20.1 days from its end, and `replay/leaver_test/` is the leaver
test's passing run over SAML, read at 23:57:34 UTC, seven minutes after the removal, so a 5-minute latency puts the
deadline before the reads and the run proves nothing about it. `--execute`, alone or with `--close-now`, runs its plan
alone under `--replay`: the run prints one line naming the plan, reads what the plan reads, sends no write, and never
reports a close. Its exit line says the run was a replay and, unless a read failed, how to run the close for real: on
your own estate, without `--replay`, on a provider bearer, as `python3 leavers.py --execute --org <org>` or
`python3 leavers.py --close-now --org <org> --user <account> --execute` (under `oid`, `<account>` is the object id or
the account's id). The set's organizations and accounts are its own placeholders, so the line names yours. A request the set holds no answer for is a read that failed, so the run exits 3 and names the
call, never a pass. The record goes to `leavers.replay.json` or `leaver-test.replay.json` unless `OUT` names a file,
so a replayed run never overwrites a real record, and it carries `"replay": true` at its top level, a key no live
run's record holds, so a tool that reads it never takes a replayed run for a live one. The transcripts are under "A replayed run" in `expected-output.md`.

## Run it

```bash
export VCFA_HOST=<automation-fqdn>
export VCFA_PROVIDER_BEARER_FILE=~/.vcf/provider-bearer              # mode 0600, outside the clone (below); or VCFA_PROVIDER_REFRESH_TOKEN_FILE
export TLS_VERIFY=false                                             # only on a self-signed lab CA
export ENTRA_TENANT_ID=<tenant-id> ENTRA_CLIENT_ID=<app-id>         # the id (any case) or a domain name; the app reads users, groups and apps
export ENTRA_CERT_FILE=/path/to/cert.pem ENTRA_KEY_FILE=/path/to/key.pem   # the key mode 0600; or ENTRA_CLIENT_SECRET_FILE
export ORGS=<org>,<org>                                             # optional; default every federated organization
export OUT=leavers.json
export WARN_DAYS=30                # optional; on a provider API token, flag the run's own token this near its end
export VCFA_PROVIDER_TOKEN_NAME=<name>   # the job's token name, when its user owns more than one REFRESH token (below)
# every secret's file is read only at mode 0600: one open to group or other is refused unread, exit 5, nothing sent

python3 leavers.py                     # report, print, record
python3 leavers.py --redact            # the same, printed with placeholders, for a transcript you will share
python3 leavers.py --name-claim <org>=mail   # the same, for an organization whose name claim carries mail (repeatable)
python3 leavers.py --ack acks.json     # the same, with the flags a person has decided on acknowledged until a date
python3 leavers.py --expect-tenants <t1>,<t2>   # the same, exiting 3 on an organization federated to a tenant outside the list
python3 leavers.py --execute --org <org> --user <account>   # close one confirmed leaver of one organization
python3 leavers.py --execute --org <org>                # close every confirmed leaver of that organization
python3 leavers.py --execute --org <org> --max-leavers 10   # the same, past the guard, once you know why so many left

# the urgent close, for a person who must lose access now, whether or not Entra has let them go yet:
python3 leavers.py --close-now --org <org> --user <account>             # the plan, nothing sent: the account, its tokens, the disable
python3 leavers.py --close-now --org <org> --user <account> --execute   # close that one account now, reading both back
# under oid, a principal name in the plan only, with the departure date the leaver notice gives (see below);
# it prints the object id to close by:
python3 leavers.py --close-now --org <org> --user <principal name> --left-on <YYYY-MM-DD>
python3 leavers.py --close-now --org <org> --user <object id> --execute
```

`<account>` names one account, in any case: its user name in VCF Automation (a principal name, or the object id in an
organization keyed on `oid`), the person's principal name in an organization keyed on `oid`, or the account's id
(`urn:vcloud:user:...`, in the record). The match (the name, the object id, the account it selects, and the dates
below) is printed before anything is sent. A name that selects no account, or more than one, refuses the run (exit 5)
and nothing is sent; pass the account's id from the record to choose between two. `--close-now` touches only that
account's tokens and record. Its plan sends nothing, and two lines state it: its header reads `CLOSE-NOW PLAN, nothing sent` and
its last line `plan only: nothing was sent and nothing was closed`, with how to close. The account's line in the plan
reads `close on request`; only a close that ran reads `closed on request`. Then remove the person at the provider, so
the next report finds them in step.

Under `oid`, close by the object id the leaver notice or your last report carries. An account there is named by its
person's Entra object id, and a principal name resolves through the tenant's app (`GET /users/{principal name}`,
Microsoft Graph's Get user call, `User.Read.All`) to whoever holds the name now. If the name has gone to someone new
who has signed in, that is the new person's account: `--close-now` asks Entra nothing, so it would lock out the new
person and leave the departed person's account open. So under `oid` a principal name is taken by the plan only, and
only with `--left-on`, the departure date the notice gives; the plan is refused (exit 5, nothing sent) when the Entra
user holding the name now was created on or after that date, when the account it selects was made on or after it, or
when that Entra user is newer than the account (an account named by the name before the organization was keyed on
`oid`). The printed match gives both dates beside the object id: the Entra user's `createdDateTime`, and the account's
creation as the audit trail records it (`GET /cloudapi/1.0.0/auditTrail`, the account's import event at its first
sign-in, or its create event; the account record itself carries no creation time). An account older than the audit
trail's reach has no such event, and the trail's oldest event bounds it (on the reference estate the trail reached back
about 39 days on 2026-10-15). A date the guard needs that did not read, or that carries no time stamp, is a read that
failed (exit 3), never a pass. The dates catch a name given to someone new after the departure. They do not catch an
existing person renamed onto the name, whose Entra user and account both predate the departure: a close by that name
would disable that person and leave the departed person's account open. So `--close-now --execute` under `oid` takes
the object id, or the account's id, only. Given anything else it is refused (exit 5) before the name is resolved and
before anything is sent, whatever Entra holds under the name: run the plan, which resolves it and prints the object id,
check that against the leaver notice, then run again with `--user <object id> --execute`. The key is the one the
organization's settings store, read whether its OIDC is switched on or off, so an organization switched off is never
taken as keyed on a name. Under `oid`, a name no Entra user holds (Graph answers 404, as for a
person deleted at Entra) that an account still carries selects an account named before the organization was keyed on
`oid`, not the one the person signs in to; the plan refuses it (exit 5), naming that account's id, and points to the
object id the leaver notice carries. The plan refuses the same way when the name resolves to an object id that names
no account while the name selects such an account: the name may belong to someone else now, so the account's id is
named only for you to check against the notice, never offered as the next step. Keyed on a name (OIDC on `preferred_username`, or SAML on Entra's name claim,
read from the organization's stored settings for the protocol of the account the name selects), the name is the
account's key: the account a name selects is the one every holder of that name signs in to, so no guard can choose
between people, none runs, and no Graph variable is needed. Stored as keyed on anything else (`sub`, an object-id
claim, or no key at all), the script does not take a principal name as that protocol's account key, so a name that
selects one of its accounts is refused (exit 5, in the plan and with `--execute`, nothing sent), and the refusal names
the account's id to check against the notice and close by.

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
taken only by the plan, with `--left-on` (above). A close by user name with no Graph variable set held on 2026-10-15 (one run); the
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

By hand, the script runs on a provider bearer (`VCFA_PROVIDER_BEARER_FILE`, a file of mode 0600 under your home,
outside any clone, where no commit can carry it), the credential a provider call presents. It acts in every organization, so hold it as tier-0 and delete it when the work ends. Two
sign-ins give one, and a close held on each on the reference estate:

- **The provider portal's sign-in.** Sign in at `https://<automation-fqdn>/provider`; the bearer is what the portal
  sends, the `Authorization` header of any `/cloudapi/` call in the browser's developer tools, after `Bearer `. The
  reference runs made this sign-in by script, so the capture by hand was not itself run. It lives an hour. The
  portal's own token page (My Account, then API Tokens, then New) issues an API refresh token, not a bearer: the
  provider API token below.
- **A Basic provider session**, for a System organization user whose password VCF Automation checks. curl asks for
  the password:

```bash
( umask 077; mkdir -p ~/.vcf &&             # both files mode 0600, under your home and outside any clone
  curl -s -X POST -u '<user>@System' -D - -o /dev/null -H 'Accept: application/json;version=9.1.0' \
       https://<automation-fqdn>/cloudapi/1.0.0/sessions/provider \
  | awk -v dir="$HOME/.vcf" 'tolower($1)=="x-vmware-vcloud-access-token:" {sub(/\r$/, "", $2);
         print $2 > (dir "/provider-bearer"); print "Authorization: Bearer " $2 > (dir "/provider-bearer-header")}' )
export VCFA_PROVIDER_BEARER_FILE=~/.vcf/provider-bearer
# add -k only on a self-signed lab CA. The bearer never reaches a command line: a tool reads provider-bearer
# (VCFA_PROVIDER_BEARER_FILE), and curl reads the header from its file (-H @file, curl 7.55 or later).
# When the work is done, end the session, then remove both files; skip the end and remove them anyway,
# since the bearer stays valid until its hour runs out.
curl -s -X DELETE -H "@$HOME/.vcf/provider-bearer-header" -H 'Accept: application/json;version=9.1.0' \
     https://<automation-fqdn>/cloudapi/1.0.0/sessions/current
rm -f ~/.vcf/provider-bearer ~/.vcf/provider-bearer-header
```

  Run on 2026-10-15 as a directory account holding System Administrator, with the two files in the working folder
  rather than `~/.vcf`, the credential given on standard input in place of curl's prompt: both files were written at
  mode 0600, the session read 200 with the bearer, the end as printed answered 204, the same read was then refused
  (401), and no file was left. An end sent without the `Accept` header answered 406 and left the session live, which
  is why the header is there. On such a bearer, with no Graph variable set, `--close-now --execute` disabled a federated account the provider made for the run and read it back (one run; the
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
new token, mint it, swap the 0600 file and set `VCFA_PROVIDER_TOKEN_NAME` to the new token's name in the same change,
run the report once on it, revoke the old one and read the list back. Until the old one is revoked the job's user owns
both, and the report judges the one the variable names; unset, with two tokens, it exits 3 naming the variable. Set
the variable too where one administrator mints the leaver report's and the federation watch's tokens, since that user
then owns two for good. The name picks the token the report judges, not the one it runs on, which its reads do not
give, so change the name with the file.
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
it until a date; on 2 run the `finish:` line the run prints under the close (below). Each state has its own code, and the first that applies wins, so a
flag never hides a failed read or an open leaver. The codes keep the contract every identity companion keeps: 0
nothing for a person to act on, 3 a read failed or a result is undetermined (never a finding), 5 a usage error; 1, 2
and 4 are this script's own; an error the script did not expect exits 3, never 1.

| Exit | Means | What the scheduler does with it |
|---|---|---|
| 2 | with `--execute`, a close that did not hold on read-back (a token left, the account still enabled, or another field changed), or whose read-back did not read (refused, or a list answered without its values), the `result` naming which read | alert whoever ran the close: they run the `finish:` line the run prints under it (below) |
| 1 | an open leaver: an account still enabled, or holding a token, whose person has left, on three reads that agree, including one `--execute` refused under the guard | alert whoever closes leavers: they run `--execute --org` on a provider bearer |
| 3 | a read failed (an organization, a gate, an account, a list read in part, a `--user` resolution, an `--expect-tenants` discovery read, the credential itself, the run's own provider API token's end date, a date `--close-now`'s name guard needs, or a request a `--replay` set holds no answer for), a tenant no organization names, an organization `--expect-tenants` leaves uncovered, an organization with its federation switched off that still holds an enabled federated account or a token of one, an error the script did not expect, or an account is undetermined, among them a leaver whose three reads disagreed; and a run whose record was refused for a surviving estate value when its own code was 0 (a close that held among them, which prints what its writes did) | alert the job's owner: nothing is known about what was not read, so fix the read (a Graph permission, a credential, the tenant, the organization's user key, a `--name-claim` the reason names, `VCFA_PROVIDER_TOKEN_NAME`, or the schedule an uncovered organization's tenant lacks); close a leaver's account in a switched-off organization with `--close-now` (under `oid` by the object id, never the name), or switch its federation back on; a leaver whose reads disagreed is read again by the next run |
| 4 | a flag nobody acknowledged: a role granted to a federated account directly, or a name in use again; or the run's own provider API token inside `WARN_DAYS` of its end | open a ticket for the account's owner; once decided, acknowledge it in `--ack` until a date. For the token, rotate it and set `VCFA_PROVIDER_TOKEN_NAME` to the new name; that flag is not acknowledged, and the rotation clears it |
| 0 | nothing open, nothing unread, nothing flagged; with `--close-now`, the close held, or the plan printed (its last line says nothing was sent and nothing was closed) | nothing |
| 5 | a usage error (a malformed `--name-claim`, `WARN_DAYS` or `--left-on` among them), a Python older than 3.10, an unreadable `--ack` file, a credential file open to group or other (refused unread, with the fix: `chmod 600`), a `--user` that selects no account or more than one, an `--expect-tenants` list that leaves out the run's own tenant or names a domain Entra knows as no tenant, and with `--close-now` an account that is not federated; under `oid`, a `--user` given to `--execute` that is not an object id or the account's id, a principal name given without `--left-on` or refused by the name guard, or a name no Entra user holds that an account still carries; and a name that selects an account whose protocol the organization stores as keyed on anything but a name; and a `--replay` directory that cannot be read or holds no replay set; nothing is sent and nothing is written | fix the invocation; under `oid`, close by the object id the plan printed, or the account's id the refusal names |

A record the script refuses to write because an estate value survived its scrub never hides what the run found: the
run's own code stands when it is 1, 2, 3 or 4, and a run whose code was 0 exits 3, because the record a later tool
reads was not written. A run that closed something prints, in counts and with no estate value, the
writes it sent, the tokens revoked, the accounts disabled and on how many the close held, and that the record was
not written.

### Finishing a close that did not hold

Under each close that did not hold, the run prints a `finish:` line. Most read like this, with what was left in the
brackets:

```text
      finish: python3 leavers.py --close-now --org <org> --user <account id> --execute  (1 token(s) left: ...)
```

That is the close again, for that one account by its id, which `--close-now --execute` takes whatever user key the
organization stores, `oid` included. It reads the account afresh, revokes each token it still owns, writes only if
the account is still enabled, and reads both back, so a close that stopped part way is finished and one that went
through changes nothing. Where the write was refused 403, the line says to run it on a provider bearer: on a provider
API token the close's write was refused (above). Two results are not finished by running it again. A field the close
did not ask that changed reads `finish by hand`: put the field back with a round trip of the account's record, because
a second close compares with its own read and would not see the change. An account that is not federated is closed in
the organization's own administration. The suggested command is parsed by the script's own parser in its tests, and
the re-run is held there too, on more than one page of accounts and tokens, under `oid` and with OIDC switched off.

Without the script, the calls are the close's own, in this order, each with `Accept:
application/json;version=10.0.0.0-alpha` and `X-VMWARE-VCLOUD-TENANT-CONTEXT: <org id>`, on a provider bearer:

```text
GET    /cloudapi/1.0.0/users/<account id>    the account's record as it stands
DELETE /cloudapi/1.0.0/tokens/<token id>     each API token the account still holds
PUT    /cloudapi/1.0.0/users/<account id>    that record, with enabled false
GET    /cloudapi/1.0.0/users/<account id>    read back: disabled, no other field changed
GET    /cloudapi/1.0.0/tokens                read back: no token the account owns
```

An acknowledgement file is a JSON list; each entry names the organization, the account, the flag (`direct-role` or
`name-in-use-again`) and the last day it holds:

```json
[{"org": "<org>", "account": "<account>", "flag": "direct-role", "until": "2026-12-31"}]
```

The report still lists an acknowledged flag, marked `acknowledged until` its date; from the day after, it counts again.
An entry that matches no flag is counted on the report, so a stale file is noticed.

## Prove a leaver is out: `leaver_test.py`

The close is proven by a test leaver: a test user who signs in to the organization through Entra and holds one API
token of its own, minted before the removal with the bearer its browser sign-in holds (`POST
/oauth/tenant/<org>/register` with that bearer gives a client id; `POST /oauth/tenant/<org>/token` with
`grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer`, that client id and the same bearer as the assertion gives the
refresh token; the chapter's leaver test shows both). Remove the user at
Entra (disable it, or take it out of the entitled group) and note the time; close the account (`--execute --org
--user`, or `--close-now`); sign in as the test user once in a browser; then, before the deadline:

```bash
export TEST_REFRESH_TOKEN_FILE=~/.vcf/test-user-api-token   # the test user's API token, mode 0600, outside any clone
python3 leaver_test.py --org <org> --user <account> --app <app client id> \
        --removed-at 2026-10-16T09:00:00Z --latency 30
```

It takes the same `VCFA_HOST`, provider credential and Entra variables as `leavers.py`, and every VCF Automation call it
makes as the provider is a read (the runs below held a provider bearer; a provider API token was not tried with it).
The Entra app must be one that may read Entra's sign-in log:
`AuditLog.Read.All`, which Microsoft Graph's List signIns reference names as the least privileged application
permission. `<account>` is the account's user name (the object id under `oid`) or its id, as for `--close-now`;
`<app client id>` is the application (client) id of the Entra app the organization signs in through. Three checks, each
with the time of its evidence; the deadline is `--removed-at` plus `--latency` minutes:

| Check | Reads | Passes when |
|---|---|---|
| account disabled, no token | `GET /cloudapi/1.0.0/users/{id}`, and `GET /cloudapi/1.0.0/tokens` read whole | `enabled` is false and no token the account owns is listed, read at or before the deadline |
| token refused | one refresh grant with the test user's token, `POST /oauth/tenant/<org>/token` | it answers 400 `invalid_grant`, at or before the deadline; an access token a 200 returns is deleted unread |
| sign-in refused | `GET /auditLogs/signIns`, filtered to the app, the person and the time since the removal, every page | Entra refused an attempt at or before the deadline with 50057 (a disabled user) or 50105 (a user not assigned to the app) |

A refusal for any other reason, a wrong password among them, proves nothing about the removal and is not counted.

| Exit | Means | What you do with it |
|---|---|---|
| 1 | a way in remains: the account reads enabled, a token it owns is listed, the refresh answered 200, or Entra admitted a sign-in after the deadline or after it had refused one | close the account (`--close-now`, under `oid` by the object id), remove the person at Entra, and test again |
| 3 | not proven: a read refused or not read whole, a grant answered with anything but 200 or 400 `invalid_grant`, no refused sign-in in the log yet, the run made after the deadline (its reads show the state now, not inside the latency), or a request a `--replay` set holds no answer for | read the reason. Entra's sign-in log lags the attempt by minutes: run again before the deadline. A run after the deadline proves nothing about the latency: repeat the test |
| 0 | every check passed, each by the deadline | keep the record (`leaver-test.json`) as the test's evidence |
| 5 | a usage error: a missing or bad argument or variable, an unreadable file, a credential file open to group or other (refused unread, with the fix: `chmod 600`), a `--user` that selects no account or more than one, a `--replay` directory that cannot be read or holds no replay set; nothing is sent | fix the invocation |

On the reference estate, 2026-10-15, the test ran once over each protocol, on a throwaway All Apps organization built
for it with its own app and entitled group: over OIDC the test user was disabled at Entra, over SAML taken out of the
entitled group. Before the removal the script exited 1 both times (the account enabled, its token listed, the refresh
answered 200). After `leavers.py` closed the account it exited 3 while Entra's log did not yet hold the refused
attempt, then 0: 6.5 minutes after the removal over OIDC (refused with 50057, logged for an attempt 19 s after the
removal) and 7.1 minutes after over SAML (50105, 17 s after). The disabled user's browser sign-in stopped at the user
name page, and Entra still logged the attempt as refused. The log was read by the lab's automation app, which holds
`AuditLog.Read.All` among wider permissions, in a tenant holding an Entra ID P2 trial licence: a tenant without one, and
an app holding only `AuditLog.Read.All`, were not tested.

What the test does not cover: a session the leaver already holds (an open browser session's bearer is not read; see
the chapter for what ends one), API tokens on other planes, and the fleet's own users behind the identity broker.

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
  for a person to decide and acknowledge. It is never closed as a leaver. On the reference estate such a user, assigned
  to the app directly, signed in holding that role alone, and was refused at sign-in once the role was dropped
  (2026-10-15, classic and All Apps organizations over OIDC and SAML, one run each); the keep and the flag are held
  by the script's tests.
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
- **A list is read whole, or it did not read.** A VCF Automation list is read page by page until its distinct items
  (by id) number the total the answer states (`resultTotal`). An answer without its values or its total, a page that
  comes back empty or short of its page size before the total, a page that adds no item not already read (the list
  served again, or moved under the read: unread at that page), or a total that changes between pages, is a list read
  in part: its organization is unreadable, or a close's read-back did not read, never a shorter list. A Microsoft
  Graph list follows `@odata.nextLink` to its end, and a 200 without its `value` list is a read that failed, as is a
  next link that repeats one already followed, which would go round for ever (a page holding no items is read on:
  Microsoft Graph's paging guidance says a page may hold none); so is a membership answer (`checkMemberGroups`)
  without its list, which leaves the account undetermined. The call that ended a
  read in part carries a `shape` in the record naming why. A page size of 1 over more than 50 items is held by the
  script's tests; the reference estate's lists fit on one page.
- **A federation switched off is listed, never dropped.** An organization with OIDC and SAML both off is not judged:
  the script cannot ask Entra about people who cannot sign in through it. It reads the organization's accounts and
  tokens instead, because an enabled federated account comes back when the federation is switched on, and whether
  an API token of a federated account stops refreshing while it is off was not tested. One that holds either is unreadable (exit 3), its
  reason naming the counts: close a leaver's account there with `--close-now`, by the object id where the
  organization stores `oid` as its key (the close reads the key it stores, switched off or not), or switch the
  federation back on so the report judges them. One that holds neither is listed (`nothing for this report to judge`) and changes no exit. On the
  reference estate, 2026-10-15, three organizations were listed, none holding anything federated.
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
  naming one account with `--user` does not step around it. Read why so many read gone, then close each with
  `--close-now` (under `oid` by its object id, never the name) or rerun with `--max-leavers`.
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
  `preferred_username`, with the account enabled). The flag's words follow the organization's user key: keyed on a
  name, an enabled account hands a later holder of the name its roles and a disabled one turns that person away until
  it is enabled again; under `oid`, a later holder of the name signs in to a new account and does not reach them. An
  account disabled here whose name an enabled, entitled Entra
  user now holds is flagged, because if that is a different person, enabling the account hands them its roles: on
  the reference estate (2026-10-15, All Apps organizations over SAML and over OIDC keyed on `preferred_username`, one
  run each), a new person given a departed person's name was refused at sign-in while the closed account stayed
  disabled, and no account was made for them; enabled again, the account let them in holding its direct role. Both
  are decisions for a person.
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

To drop a direct role the report flags, write the account's record back without it: read the record (`GET
/cloudapi/1.0.0/users/<account id>`), take the role out of `roleEntityRefs`, write the whole record back (`PUT` to the
same path) and read it again, each call with the headers a close sends (above) on a provider bearer. The same round
trip with the role added granted the direct role the closed test leaver still holds (2026-10-13, a classic OIDC
organization, one run). Taken out the same way, a role left an enabled account and a closed one, every other field
read back as it was (2026-10-15: a classic and an All Apps organization over OIDC and an All Apps organization over
SAML, one run each). The last direct role of an account the provider had made, which no sign-in had placed in a
group, was refused (400, `Users/Groups must be provided with at least one role.`) and nothing changed; on an account
a federated sign-in had made it was taken, in a group and in none, and the record's `stranded` read `true` until a
role was granted again (classic and All Apps organizations over OIDC and SAML, one run each). Why the two differ is
not established. Count a role gone only when the read-back no longer names it. Or delete the account (`DELETE
/cloudapi/1.0.0/users/<account id>`, 202) and read the account list until it is gone (a read of the deleted id
answered 403, not 404): deleted before its name came back, an account gave way to a new one holding only its groups'
roles (2026-10-15, All Apps organizations over SAML and over OIDC keyed on `preferred_username`, one run each). The
script itself never removes a role.

## Scope, stated plainly

- Read-only unless `--execute` is given. Its writes are `DELETE` of each of the leaver's API tokens and a `PUT` of
  the account's record, sent a second time with the email cleared when the platform refuses the email field (a SAML
  account, above); the record's `sent` lists every one.
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
  Selection on a live organization keyed on `oid` ran later that day, on an All Apps organization built keyed on
  `oid` for the run, with two throwaway users: the report kept both accounts by object id; the plan given a
  principal name, with `--left-on` after the user's creation, resolved it through Graph and selected that account,
  sending nothing; `--close-now --execute` refused the name before any Graph call (exit 5) and, given the object id,
  closed only that account; and `--execute --org --user` given the second user's principal name, once that user was
  disabled at Entra, closed its account. `--close-now`'s name guard (`--left-on`) is held by the script's tests, among
  them a name reused by a newer Entra user, and an existing person renamed onto the name, whom the dates pass and
  whose name `--execute` refuses; the audit trail's import and create events it reads were each found, read-only,
  for every account of the lab's four throwaway organizations on 2026-10-15, and Entra's `createdDateTime` on every
  user the lab tenant's app read. Live, once the first user's name went to a new Entra user, who signed in to a new
  account, the plan with `--left-on` the departure day refused the name (exit 5); both users were made that day, so
  the first user's own name was refused the same way before the reuse, and a reuse long after a departure was not
  run live.
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
  in VCF Automation ended the session-login bearer it held at once (one run); and `--close-now --execute` ended a
  federated user's browser-session bearer at once, 7 s after its sign-in (an All Apps OIDC organization, one run,
  2026-10-15). A bearer already traded from the account's own API token ended at the disable too, for a local user (a
  classic organization) and for a federated user (an All Apps OIDC organization keyed on `oid`), one run each on
  2026-10-16, each disable sent without the revoke the close sends first. The same held for a federated user over SAML
  in an All Apps organization and for one over OIDC in a classic organization (2026-10-17, one run each). Enabling such
  an account again let its still-listed token trade at once, so the close revokes the account's tokens before it
  disables it. It cannot tell whether a name in use again
  belongs to the same person; it
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
  23 s and agreed. Run again at 21:14 UTC as the script stands, on the provider API token the estate keeps, it made
  103 calls with none refused, listed three organizations with their federation switched off and nothing federated in
  them, reached the same decision on every account, and exited 4 on that flag and on its own token, 20.1 days from its
  end (`leavers.json`); each SAML organization's user key is recorded as Entra's name claim, whose namespace the scrub
  keeps as product vocabulary.

## Reading the record

`organizations` holds one entry per organization, named `{{org-1}}` and onward, with its `protocol`, its `gate`
(whether the app requires assignment, its group claims, the groups assigned to it, the groups imported into the
organization and which of those a sign-in can carry) and a `users` list. Each account has its `providerType`,
`enabled`, `direct_roles` and `effective_roles` by name, its `tokens` by name and type, the `decision` (for the
account `--close-now` names, `close on request` in its plan and `closed on request` once the close ran) and its
`reason`, `found` (whether a lookup found its Entra user) and `matched_by` (which lookup), any `flags`, with the
ones `--ack` covers under `acknowledged` (and an expired one under `ack_expired`), and, where the run did something or
would, its `action`; every leaver that was open carries `confirm_reads`, the three reads that confirmed it (or, for
one now undetermined, that disagreed), and a closed account a `result` with what was revoked and the read-back.
Each organization carries its `leaver_guard`: its open leavers, its federated accounts, the limit, and whether
`--execute` refuses it and why; one whose leavers were read again carries `confirm_seconds`. A run given `--user`
carries `user_match`: the name given, how it was resolved, the object id, and the account it selected. A run given
`--expect-tenants` carries `expected_tenants` and `elsewhere`: each organization federated elsewhere, its protocol,
the Entra tenant its issuer or metadata names (or none, for another provider) and who reads it (`read_by`), and
`summary` adds `other_tenants`, `other_provider` and `uncovered`. `switched_off` lists each organization with its
federation switched off, with its enabled federated accounts and the API tokens of its federated accounts (both null
when they could not be read), and `summary` counts them (`switched_off`) and those it could not judge
(`switched_off_unjudged`). `credential` names the run's own credential, its end and days left, and any flag or unread
reason. `summary` holds the totals (`keep`, `leaver`, `out_of_scope`, `undetermined`,
`open_leavers`, `refused`, `closed`, `not_held`, `in_step`, `direct_role`, `name_in_use_again`, `acknowledged`, and
`flagged`, the flags no acknowledgement covers) and `per_org`: per organization, its accounts, how many are federated,
found, kept, leavers, open and flagged, whether the guard refuses it, the federated accounts holding a direct role
with those roles (`direct_federated`), and how many local accounts hold one (`direct_local`). `acks` counts the
acknowledgement file's entries and the ones that matched no flag. `calls` holds every request with its status; `sent`
names every request that was not a read; `exit` is the code the run returned.
