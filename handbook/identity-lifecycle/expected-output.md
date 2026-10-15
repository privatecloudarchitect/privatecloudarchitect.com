# What a run looks like

The reference estate, 2026-10-15 (UTC): VCF Automation 9.1 with seven organizations federated somewhere, four of
them to one Entra ID tenant (a classic and an All Apps organization over OIDC, and one of each over SAML). Run with
`--redact`, so the names are placeholders; the record path is shortened to its file name. Placeholders are numbered
per run, so the same person can carry a different number in each transcript.

## The report

The run behind `leavers.json`, read-only, by the script as it stands: it reads each gate group's direct members, so
it makes four calls more than the run in the next section, made earlier the same day before those reads were added,
and it reached the same decision on every account. Exit 4: nothing is open and nothing went unread, and one federated
account holds a role granted to it directly, a flag nobody has acknowledged yet. Every federated account was found at
Entra by its userPrincipalName.

```
$ python3 leavers.py --redact
Leavers · REPORT · 4 organization(s) federated to the tenant, 3 federated elsewhere (not read)
  {{org-1}} (OIDC): 3 account(s); gate {{group-1}}
    direct role assignments on federated accounts: none
    {{user-1}}: out of scope (LOCAL account, not federated)
    {{user-2}}: keep (entitled through {{group-1}})
    {{user-3}}: leaver (not assigned to the app, directly or through a group) -> in step: already disabled, no token
  {{org-2}} (SAML): 2 account(s); gate {{group-2}}
    direct role assignments on federated accounts: none
    {{user-2}}: keep (entitled through {{group-2}})
    {{user-3}}: leaver (not assigned to the app, directly or through a group) -> in step: already disabled, no token
  {{org-3}} (OIDC): 3 account(s); gate {{group-3}}
    direct role assignments on federated accounts: {{user-4}} (Service Broker User)
    {{user-2}}: keep (entitled through {{group-3}})
    {{user-3}}: keep (entitled through {{group-3}})
    {{user-4}}: leaver (the Entra account is disabled) -> in step: already disabled, no token  FLAG direct-role
  {{org-4}} (SAML): 3 account(s); gate {{group-4}}
    direct role assignments on federated accounts: none
    {{user-2}}: keep (entitled through {{group-4}})
    {{user-3}}: keep (entitled through {{group-4}})
    {{user-5}}: keep (entitled through {{group-4}})
  totals: keep 7, leaver 3, out of scope 1, undetermined 0, open leavers 0, refused 0, closed 0, not held 0, in step 3, direct role 1, name in use again 0, acknowledged 0, flagged 1
  exit 4: a flag nobody acknowledged: decide it, then acknowledge it with --ack

95 call(s), 0 refused; leavers.json written with every estate value replaced; exit 4
```

## The same report, with the flag acknowledged

The flag above is the closed test leaver of the next section, kept to show it. Once a person has decided on a flag,
an acknowledgement file silences it until a date; the report still lists it, and the run exits 0.

```
$ cat acks.json
[{"org": "<org>", "account": "<account>", "flag": "direct-role", "until": "2026-12-31"}]
$ python3 leavers.py --redact --ack acks.json
Leavers · REPORT · 4 organization(s) federated to the tenant, 3 federated elsewhere (not read)
  {{org-1}} (OIDC): 3 account(s); gate {{group-1}}
    direct role assignments on federated accounts: none
    {{user-1}}: out of scope (LOCAL account, not federated)
    {{user-2}}: keep (entitled through {{group-1}})
    {{user-3}}: leaver (not assigned to the app, directly or through a group) -> in step: already disabled, no token
  {{org-2}} (SAML): 2 account(s); gate {{group-2}}
    direct role assignments on federated accounts: none
    {{user-2}}: keep (entitled through {{group-2}})
    {{user-3}}: leaver (not assigned to the app, directly or through a group) -> in step: already disabled, no token
  {{org-3}} (OIDC): 3 account(s); gate {{group-3}}
    direct role assignments on federated accounts: {{user-4}} (Service Broker User)
    {{user-2}}: keep (entitled through {{group-3}})
    {{user-3}}: keep (entitled through {{group-3}})
    {{user-4}}: leaver (the Entra account is disabled) -> in step: already disabled, no token  FLAG direct-role (acknowledged until 2026-12-31)
  {{org-4}} (SAML): 3 account(s); gate {{group-4}}
    direct role assignments on federated accounts: none
    {{user-2}}: keep (entitled through {{group-4}})
    {{user-3}}: keep (entitled through {{group-4}})
    {{user-5}}: keep (entitled through {{group-4}})
  totals: keep 7, leaver 3, out of scope 1, undetermined 0, open leavers 0, refused 0, closed 0, not held 0, in step 3, direct role 1, name in use again 0, acknowledged 1, flagged 0
  exit 0: nothing open, nothing unread, nothing flagged

91 call(s), 0 refused; leavers-ack.json written with every estate value replaced; exit 0
```

## A leaver, closed

Recorded on 2026-10-13 with the version before each state had its own exit code, so its totals line is shorter and it
ends at exit 1; the same state, closed with nothing open and one flag, now exits 4. A throwaway user on the reference
estate, end to end. It was created at Entra, entitled through `{{org-1}}`'s group,
signed in once in a browser (which created its VCF Automation account), given an API token minted from that sign-in,
and given a role directly (Service Broker User); then its Entra account was disabled.

```
$ python3 leavers.py --redact --execute --org <org> --user <upn>
Leavers · EXECUTE · 1 organization(s) federated to the tenant
  {{org-1}} (OIDC): 3 account(s); gate {{group-1}}
    direct role assignments on federated accounts: {{user-3}} (Service Broker User)
    {{user-1}}: keep (entitled through {{group-1}})
    {{user-2}}: keep (entitled through {{group-1}})
    {{user-3}}: leaver (the Entra account is disabled) -> closed  FLAG direct-role
  totals: keep 2, leaver 1, out of scope 0, undetermined 0, open leavers 0, closed 1, not held 0, in step 0, direct role 1, name in use again 0

27 call(s), 0 refused; leavers.json written with every estate value replaced; exit 1
```

The record's entry for that account: three reads, ten seconds apart, all `leaver`; one API token revoked (204), then
the account's record written back with `enabled` false; read back, the account disabled, no other field changed and
no token left. Its `sent` lists exactly those two writes.

How long each step took, from the disable at Entra (one run):

| Step | Seconds after the disable |
|---|---|
| A report calls the account a leaver (`the Entra account is disabled`) | 24 |
| `--execute` closes it, the three confirming reads included | 55 |
| The token's next refresh is refused (`invalid_grant`) | 55 |
| A re-run: `in step: already disabled, no token` | 64 |

## What to read in it

- **Leavers in step are the goal.** Each leaver above is disabled and holds no token, so the run changes nothing and
  says `in step`. A leaver still enabled, or still holding a token, reads `would revoke its tokens and disable it`
  and sets the exit code to 1: that is the line a scheduled report exists to catch, and a person runs the close on it.
- **Each exit code is one state, and every one but 0 is an alert.** 1 an open leaver: run the close. 3 a read that
  failed or an account undetermined: fix the read before trusting any decision. 4 a flag nobody acknowledged: decide
  it and acknowledge it until a date. With `--execute`, 2 a close that did not hold: finish it by hand. The first that
  applies wins, so a flag never hides a lost Graph permission (3) or an open leaver (1).
- **A direct role is a flag, never a leaver by itself.** An account that passes Entra's gate and holds a role directly
  reads keep even when no imported group carries it, because VCF Automation refuses only a user with neither; it is
  flagged `direct-role` for a person to decide. A user found only by `mail` or `otherMails` whose principal name is
  another name reads undetermined, with the mismatch as its reason, until its organization is declared with
  `--name-claim <org>=mail`.
- **Closing an account does not drop its direct roles.** After the close, the throwaway account still holds Service
  Broker User, granted to it by name. A new person later given that name signs in to the same account and holds the
  role, so the report keeps flagging it until someone deletes the account or drops the role. The `direct role
  assignments` line in every organization is the check that roles arrive only through groups: it should read `none`.
- **Two kinds of leaver.** The account in `{{org-3}}` left at Entra (its Entra account is disabled). The two accounts
  in `{{org-1}}` and `{{org-2}}` still exist and are enabled at Entra, but no group assigned to those apps carries
  them any more, so a sign-in would be refused at Entra's gate. Both count, because either stops the next sign-in
  while leaving the account and any token behind.
- **Federated elsewhere is not read.** Three organizations on the estate sign in through VCF single sign-on, the
  identity broker, or another provider; they are counted, not judged. Run the script once per Entra tenant.
- **The local account is out of scope.** `{{user-1}}` is an organization's local administrator, the way in when the
  provider refuses; its role is direct by nature and is counted apart (`direct_local` in the record), never flagged.
