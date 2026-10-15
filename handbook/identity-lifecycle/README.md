# Find the people who left, and close what they kept

Companion to the chapter
([privatecloudarchitect.com/handbook/identity-lifecycle](https://privatecloudarchitect.com/handbook/identity-lifecycle)):
one script that finds every VCF Automation account whose person has left at Entra ID, says what each still holds,
and, when asked for one organization, revokes the account's API tokens and disables it, reading both back. Report
only by default. Stdlib Python; the `cryptography` package only if Graph is reached with a certificate. No token,
secret or password is printed or written.

| File | What it is |
|---|---|
| `leavers.py` | Finds every organization federated to one Entra tenant from the organization's own settings (OIDC by an issuer on the tenant, SAML by metadata naming it), reads each account against Entra and both gates a sign-in passes (the app's assignment, and a group imported into the organization that the sign-in can carry), and reports every leaver, the tokens it holds (how many, and the last one's end date, for every account) and what the run would do. It lists every role granted to a federated account directly, and flags an account disabled here whose name an enabled, entitled Entra user now holds; `--ack` silences a flag a person has decided on, until a date. `--execute --org` closes the confirmed leavers of one organization, and refuses an organization where an unusual share reads gone; `--close-now --org --user` closes one named account at once, without asking Entra. Each state has its own exit code. Writes `leavers.json`, and refuses to write a record carrying any estate value. |
| `leavers.json` | That record from the reference estate, a read-only run on 2026-10-15: every organization federated to the lab tenant. |
| `expected-output.md` | The transcripts of that run, of the same run with its one flag acknowledged, and of a closed leaver, with what to read in them. |

## Run it

```bash
export VCFA_HOST=<automation-fqdn>
export VCFA_PROVIDER_BEARER_FILE=/path/to/provider-bearer             # mode 0600; or VCFA_PROVIDER_REFRESH_TOKEN_FILE
export TLS_VERIFY=false                                             # only on a self-signed lab CA
export ENTRA_TENANT_ID=<tenant-id> ENTRA_CLIENT_ID=<app-id>         # an app that can read users, groups and apps
export ENTRA_CERT_FILE=/path/to/cert.pem ENTRA_KEY_FILE=/path/to/key.pem   # or ENTRA_CLIENT_SECRET_FILE
export ORGS=<org>,<org>                                             # optional; default every federated organization
export OUT=leavers.json

python3 leavers.py                     # report, print, record
python3 leavers.py --redact            # the same, printed with placeholders, for a transcript you will share
python3 leavers.py --ack acks.json     # the same, with the flags a person has decided on acknowledged until a date
python3 leavers.py --execute --org <org> --user <upn>   # close one confirmed leaver of one organization
python3 leavers.py --execute --org <org>                # close every confirmed leaver of that organization
python3 leavers.py --execute --org <org> --max-leavers 10   # the same, past the guard, once you know why so many left

# the urgent close, for a person who must lose access now, whether or not Entra has let them go yet:
python3 leavers.py --close-now --org <org> --user <account>             # the plan: the account, its tokens, the disable
python3 leavers.py --close-now --org <org> --user <account> --execute   # close that one account now, reading both back
```

`<account>` is the account's user name in VCF Automation: a principal name, or the object id in an organization keyed
on `oid`. `--close-now` needs no Graph credential, acts on exactly one account the name matches (it refuses a name
that matches none or several), and touches only that account's tokens and record. Then remove the person at the
provider, so the next report finds them in step.

### Your provider credential

By hand, a provider bearer (`VCFA_PROVIDER_BEARER_FILE`) lasts an hour. A scheduled report holds a provider API token
instead (`VCFA_PROVIDER_REFRESH_TOKEN_FILE`), which the script trades at `/oauth/provider/token` for a bearer each run.
The close does not run on one (below): run `--execute` and `--close-now --execute` on a provider bearer.
Mint it for the identity the report runs as, a provider identity of its own and never a person's, and hold it as
tier-0: it is minted for a provider System Administrator and reads every organization. The programmatic mint is two
calls, with a provider bearer of that identity:

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
account stayed enabled (a local user in a classic organization, one run), so the script reported that the close did
not hold. Every close that held on the reference estate ran on a provider bearer from the provider portal's sign-in.
No credential short of an administrator's was found to carry the close: the token was refused it, and a dedicated
local user of the provider's own organization could not be made, the organization already holding its one local user
(2026-10-13). Not tried: that existing local user, and a directory service account granted a provider role through the
portal flow. The narrowest provider role that lets the job pass was not measured. Scheduling the close would mean
holding an administrator's credential in the scheduler: the reference estate's own job signs in as the SSO
administrator through the provider portal's sign-in.

So the close is a person's step. Schedule the report on the token and act on its exit code; exit 1 is the alert, and
whoever receives it runs `--execute --org` (or `--close-now`) on a provider bearer from a portal sign-in. Each state has
its own code, and the first that applies wins, so a flag never hides a failed read or an open leaver:

| Exit | Means | What the scheduler does with it |
|---|---|---|
| 2 | with `--execute`, a close that did not hold on read-back (a token left, the account still enabled, or another field changed) | alert whoever ran the close: read the account's `result` in the record and finish it by hand |
| 1 | an open leaver: an account still enabled, or holding a token, whose person has left, including one `--execute` refused under the guard | alert whoever closes leavers: they run `--execute --org` on a provider bearer |
| 3 | a read failed (an organization, a gate, an account, or the credential itself), or an account is undetermined | alert the job's owner: nothing is known about what was not read, so fix the read (a Graph permission, a credential, the organization's user key) |
| 4 | a flag nobody acknowledged: a role granted to a federated account directly, or a name in use again | open a ticket for the account's owner; once decided, acknowledge it in `--ack` until a date |
| 0 | nothing open, nothing unread, nothing flagged; with `--close-now`, the plan printed or the close held | nothing |
| 5 | a usage error, an unreadable `--ack` file, an account `--close-now` cannot name exactly once, or the record refused because an estate value survived the scrub; nothing is written | fix the invocation |

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
  organization that the sign-in carries. With the app's group claims set to `ApplicationGroup`, only an imported
  group that is also assigned to the app is carried. Accounts are matched to Entra by the key the organization
  names them with (see Scope). Local accounts are out of scope.
- **How a name is looked up.** By `userPrincipalName`, then by `mail`, then by `otherMails`, each a `/users` filter
  Microsoft Graph serves by default (no `ConsistencyLevel` header, no `$count`). Every lookup is read, and exactly one
  Entra user across them is the person; more than one reads undetermined. A name none of them finds is a leaver only
  when another federated account of the same organization was found. When none was, every account of the
  organization reads undetermined, and the reason names the organization's user key: its names are not ones the
  lookups read.
- **It fails closed.** An organization whose gate cannot be read, or an account whose user cannot be read, is
  reported undetermined and never acted on.
- **It acts only on what three reads agree on.** Entra's directory reads settle after a change. With `--execute`,
  each leaver is read again three times, ten seconds apart, and closed only when every read says leaver; otherwise
  it is left for the next run.
- **It acts only on a named organization.** `--execute` needs `--org`; `--user` narrows it to one account. Every
  account is still read and reported.
- **It refuses a mass close.** `--execute` refuses an organization whose open leavers number more than three and more
  than a quarter of its federated accounts (or more than `--max-leavers N`): it closes none of them, each reads
  `refused` with the reason, and the run exits 1. A share that size is more often a wrong lookup than a bad week, and
  naming one account with `--user` does not step around it. Read why so many read gone, then close them by name or
  rerun with `--max-leavers`.
- **A close** revokes each API token the account holds, then disables the account by writing its full record back
  with `enabled` false, then reads both back: no token left, the account disabled, and no other field changed. A
  SAML account created at first sign-in while the provider sent no email claim holds a value the platform refuses on
  update; when the write is refused naming the email field, it goes again with the email cleared, the one other field
  it changes, and the record's `email_cleared` marks it. A leaver already disabled with no
  token is in step, so a re-run changes nothing. A close leaves roles granted directly in place: the account closed
  on the reference estate kept its direct role, and the report flags it until a person removes it.
- **What it never acts on.** A role granted to a federated account directly is listed and flagged, because a new
  person later given the same name signs in to the same account and holds it. An account disabled here whose name
  an enabled, entitled Entra user now holds is flagged, because if that is a different person, enabling the account
  hands them its roles. Both are decisions for a person.

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
- Entra ID only, one tenant per run. An organization federated to another provider, or signed in through VCF single
  sign-on, is counted as federated elsewhere and not read.
- Each organization's accounts are matched to Entra by the key the organization names them with, read from its own
  settings: by name for OIDC keyed on `preferred_username` and for SAML keyed on Entra's name claim, and by object id
  for OIDC keyed on `oid`. An organization keyed on anything else has every account undetermined, never a leaver, and
  an account whose name does not fit its organization's key is undetermined too. Matching by object id ran once on
  the reference estate (2026-10-13), on an All Apps organization keyed on `oid` for the run: two accounts named by
  object id read keep, one was closed with `--close-now`, the other read leaver once disabled at Entra and was closed;
  the accounts named by principal name read undetermined.
- What the name match covers, and what it was tested on. Every federated account on the reference estate was found
  by its `userPrincipalName` (2026-10-15). The `mail` and `otherMails` lookups found a throwaway member user whose
  `mail` and `otherMails` each held an address other than its `userPrincipalName`, the shape of a name claim sourced
  from mail: three reads each, once Graph's reads had settled after the user was made (2026-10-15). That user was
  never signed in to VCF Automation, so no organization whose name claim is sourced from another attribute was run
  end to end. An Entra guest was not tested: the reference tenant refused the throwaway guest's invitation. A guest's
  `userPrincipalName` in the tenant carries `#EXT#` while it signs in with its own address; where the guest's `mail`
  or `otherMails` holds that address the lookup finds it, and whether Entra puts it there was not read. In either
  untested case, a name no lookup finds is judged as above: undetermined when no account of the organization is
  found, and a leaver otherwise, with the mass-close guard between it and `--execute`.
- What it cannot see: whether a revoked token was in use, sessions a leaver already holds (they run to their own
  expiry), and the fleet's own users behind the identity broker (that half of the job is a design today). It cannot
  tell whether a name in use again belongs to the same person; it flags the case and acts on nothing.
- Measured on VCF Automation 9.1 against Entra ID with a provider bearer and a Graph certificate, and with a provider
  API token (2026-10-13: a report run held; a close was refused 403); the Graph client-secret path was not exercised
  on the reference estate. The Graph application permissions the reads need were measured on a throwaway app before
  the `mail` and `otherMails` lookups were added: `Application.Read.All`, `User.Read.All` and `GroupMember.Read.All`,
  and with the last one missing every account reads undetermined. The two newer lookups ran on the lab's automation
  app, which holds wider permissions; that the three suffice for them was not measured. On 2026-10-15 the report
  exited 4 on the reference estate (one flag, nothing open, nothing unread), and 0 with that flag acknowledged.

## Reading the record

`organizations` holds one entry per organization, named `{{org-1}}` and onward, with its `protocol`, its `gate`
(whether the app requires assignment, its group claims, the groups assigned to it, the groups imported into the
organization and which of those a sign-in can carry) and a `users` list. Each account has its `providerType`,
`enabled`, `direct_roles` and `effective_roles` by name, its `tokens` by name and type, the `decision` and its
`reason`, `found` (whether a lookup found its Entra user) and `matched_by` (which lookup), any `flags`, with the
ones `--ack` covers under `acknowledged` (and an expired one under `ack_expired`), and, where the run did something or
would, its `action`; a closed account carries `confirm_reads` and a `result` with what was revoked and the read-back.
Each organization carries its `leaver_guard`: its open leavers, its federated accounts, the limit, and whether
`--execute` refuses it and why. `summary` holds the totals (`keep`, `leaver`, `out_of_scope`, `undetermined`,
`open_leavers`, `refused`, `closed`, `not_held`, `in_step`, `direct_role`, `name_in_use_again`, `acknowledged`, and
`flagged`, the flags no acknowledgement covers) and `per_org`: per organization, its accounts, how many are federated,
found, kept, leavers, open and flagged, whether the guard refuses it, the federated accounts holding a direct role
with those roles (`direct_federated`), and how many local accounts hold one (`direct_local`). `acks` counts the
acknowledgement file's entries and the ones that matched no flag. `calls` holds every request with its status; `sent`
names every request that was not a read; `exit` is the code the run returned.
