# Find the people who left, and close what they kept

Companion to the chapter
([privatecloudarchitect.com/handbook/identity-lifecycle](https://privatecloudarchitect.com/handbook/identity-lifecycle)):
one script that finds every VCF Automation account whose person has left at Entra ID, says what each still holds,
and, when asked for one organization, revokes the account's API tokens and disables it, reading both back. Report
only by default. Stdlib Python; the `cryptography` package only if Graph is reached with a certificate. No token,
secret or password is printed or written.

| File | What it is |
|---|---|
| `leavers.py` | Finds every organization federated to one Entra tenant from the organization's own settings (OIDC by an issuer on the tenant, SAML by metadata naming it), reads each account against Entra and both gates a sign-in passes (the app's assignment, and a group imported into the organization that the sign-in can carry), and reports every leaver, the tokens it holds (how many, and the last one's end date, for every account) and what the run would do. It lists every role granted to a federated account directly, and flags an account disabled here whose name an enabled, entitled Entra user now holds. `--execute --org` closes the confirmed leavers of one organization; `--close-now --org --user` closes one named account at once, without asking Entra. Writes `leavers.json`, and refuses to write a record carrying any estate value. |
| `leavers.json` | That record from the reference estate, a read-only run on 2026-10-13: every organization federated to the lab tenant. |
| `expected-output.md` | The transcripts of that run and of a closed leaver, with what to read in them. |

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
python3 leavers.py --execute --org <org> --user <upn>   # close one confirmed leaver of one organization
python3 leavers.py --execute --org <org>                # close every confirmed leaver of that organization

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
account stayed enabled (a local user in a classic organization, one run), so the script exited 2. Every close that
held on the reference estate ran on a provider bearer from the provider portal's sign-in. Neither credential tried
could carry the close: the token was refused it, and a dedicated local user of the provider's own organization could
not be made, the organization already holding its one local user (2026-10-13). Not tried: that existing local user,
the provider administrator, and a directory service account granted a provider role through the portal flow. The
narrowest provider role that lets the job pass was not measured.

So the close is a person's step. Schedule the report on the token and read its exit code; exit 1 is the alert, and
whoever receives it runs `--execute --org` (or `--close-now`) on a provider bearer from a portal sign-in:

| Exit | Means |
|---|---|
| 0 | nothing open and nothing flagged; with `--close-now`, the plan printed or the close held |
| 1 | an open leaver to close (an account still enabled, or holding a token, whose person has left), or a flag: a role granted to a federated account directly, or a name in use again |
| 2 | with `--execute`, a close that did not hold on read-back (a token left, the account still enabled, or another field changed) |
| 3 | a read failed (an organization, a gate or an account could not be read) and nothing worse |
| 4 | a usage error, an account `--close-now` cannot name exactly once, or the record was refused because an estate value survived the scrub; nothing is written |

## What it decides, and when it acts

- **A leaver** is a federated account whose name Entra no longer holds, whose Entra user is disabled, or whose user
  can no longer pass both gates: the app's assignment (when the app requires one) and a group imported into the
  organization that the sign-in carries. With the app's group claims set to `ApplicationGroup`, only an imported
  group that is also assigned to the app is carried. Accounts are matched to Entra by the key the organization
  names them with (see Scope). Local accounts are out of scope.
- **It fails closed.** An organization whose gate cannot be read, or an account whose user cannot be read, is
  reported undetermined and never acted on.
- **It acts only on what three reads agree on.** Entra's directory reads settle after a change. With `--execute`,
  each leaver is read again three times, ten seconds apart, and closed only when every read says leaver; otherwise
  it is left for the next run.
- **It acts only on a named organization.** `--execute` needs `--org`; `--user` narrows it to one account. Every
  account is still read and reported.
- **A close** revokes each API token the account holds, then disables the account by writing its full record back
  with `enabled` false, then reads both back: no token left, the account disabled, and no other field changed. A
  SAML account created at first sign-in can hold an email the platform refuses on update; the write then goes again
  with the email cleared, the one other field it changes, and the record's `email_cleared` marks it. A leaver already disabled with no
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
  settings: by principal name for OIDC keyed on `preferred_username` and for SAML keyed on Entra's name claim, and by
  object id for OIDC keyed on `oid`. An organization keyed on anything else has every account undetermined, never a
  leaver, and an account whose name does not fit its organization's key is undetermined too. Matching by object id ran
  once on the reference estate (2026-10-13), on an All Apps organization keyed on `oid` for the run: two accounts
  named by object id read keep, one was closed with `--close-now`, the other read leaver once disabled at Entra and
  was closed; the accounts named by principal name read undetermined.
- What it cannot see: whether a revoked token was in use, sessions a leaver already holds (they run to their own
  expiry), and the fleet's own users behind the identity broker (that half of the job is a design today). It cannot
  tell whether a name in use again belongs to the same person; it flags the case and acts on nothing.
- Measured on VCF Automation 9.1 against Entra ID with a provider bearer and a Graph certificate, and with a provider
  API token (2026-10-13: a report run held; a close was refused 403); the Graph client-secret path was not exercised
  on the reference estate. The Graph application
  permissions the reads need were measured on a throwaway app: `Application.Read.All`, `User.Read.All` and
  `GroupMember.Read.All`, and with the last one missing every account reads undetermined.

## Reading the record

`organizations` holds one entry per organization, named `{{org-1}}` and onward, with its `protocol`, its `gate`
(whether the app requires assignment, its group claims, the groups assigned to it, the groups imported into the
organization and which of those a sign-in can carry) and a `users` list. Each account has its `providerType`,
`enabled`, `direct_roles` and `effective_roles` by name, its `tokens` by name and type, the `decision` and its
`reason`, any `flags`, and, where the run did something or would, its `action`; a closed account carries
`confirm_reads` and a `result` with what was revoked and the read-back. `summary` holds the totals (`keep`,
`leaver`, `out_of_scope`, `undetermined`, `open_leavers`, `closed`, `not_held`, `in_step`, `direct_role`,
`name_in_use_again`, `flagged`) and `per_org`: per organization, its accounts, how many are federated, kept,
leavers, open and flagged, the federated accounts holding a direct role with those roles (`direct_federated`), and
how many local accounts hold one (`direct_local`). `calls` holds every request with its status; `sent` names every
request that was not a read; `exit` is the code the run returned.
