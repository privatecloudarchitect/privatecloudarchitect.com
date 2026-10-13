# Find the people who left, and close what they kept

Companion to the chapter
([privatecloudarchitect.com/handbook/identity-lifecycle](https://privatecloudarchitect.com/handbook/identity-lifecycle)):
one script that finds every VCF Automation account whose person has left at Entra ID, says what each still holds,
and, when asked for one organization, revokes the account's API tokens and disables it, reading both back. Report
only by default. Stdlib Python; the `cryptography` package only if Graph is reached with a certificate. No token,
secret or password is printed or written.

| File | What it is |
|---|---|
| `leavers.py` | Finds every organization federated to one Entra tenant from the organization's own settings (OIDC by an issuer on the tenant, SAML by metadata naming it), reads each account against Entra and both gates a sign-in passes (the app's assignment, and a group imported into the organization that the sign-in can carry), and reports every leaver, the tokens it holds (how many, and the last one's end date, for every account) and what the run would do. It lists every role granted to a federated account directly, and flags an account disabled here whose name an enabled, entitled Entra user now holds. `--execute --org` closes the confirmed leavers of one organization. Writes `leavers.json`, and refuses to write a record carrying any estate value. |
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
```

Schedule the report and read the exit code:

| Exit | Means |
|---|---|
| 0 | nothing open and nothing flagged |
| 1 | an open leaver to close (an account still enabled, or holding a token, whose person has left), or a flag: a role granted to a federated account directly, or a name in use again |
| 2 | with `--execute`, a close that did not hold on read-back (a token left, the account still enabled, or another field changed) |
| 3 | a read failed (an organization, a gate or an account could not be read) and nothing worse |
| 4 | a usage error, or the record was refused because an estate value survived the scrub; nothing is written |

## What it decides, and when it acts

- **A leaver** is a federated account whose name Entra no longer holds, whose Entra user is disabled, or whose user
  can no longer pass both gates: the app's assignment (when the app requires one) and a group imported into the
  organization that the sign-in carries. With the app's group claims set to `ApplicationGroup`, only an imported
  group that is also assigned to the app is carried. Accounts are matched to Entra by user name, the way VCF
  Automation matches a returning user. Local accounts are out of scope.
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
  leaver, and an account whose name does not fit its organization's key is undetermined too. Matching by object id is
  tested, not run on a live organization.
- What it cannot see: whether a revoked token was in use, sessions a leaver already holds (they run to their own
  expiry), and the fleet's own users behind the identity broker (that half of the job is a design today). It cannot
  tell whether a name in use again belongs to the same person; it flags the case and acts on nothing.
- Measured on VCF Automation 9.1 against Entra ID with a provider bearer and a Graph certificate; the provider
  refresh-token and Graph client-secret paths were not exercised on the reference estate. The Graph application
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
