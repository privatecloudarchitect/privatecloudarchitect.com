# What a run looks like

The reference estate, 2026-10-15 (UTC): VCF Automation 9.1 with seven organizations federated somewhere, four of
them to one Entra ID tenant (a classic and an All Apps organization over OIDC, and one of each over SAML). Run with
`--redact`, so the names are placeholders; the record path is shortened to its file name. Placeholders are numbered
per run, so the same person can carry a different number in each transcript.

## The report

The run behind `leavers.json`, read-only, by the script as it stands: it reads each gate group's direct members, so
it makes four calls more than the run in the next section, made earlier the same day before those reads were added,
and it reached the same decision on every account. It confirms every open leaver over three reads before it counts
one; none was open, so no account was read again and the printed lines are those of the version before, which took
30.7 s to this run's 30.2 s. Exit 4: nothing is open and nothing went unread, and one federated account holds a role
granted to it directly, a flag nobody has acknowledged yet. Every federated account was found at Entra by its
userPrincipalName.

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
$ python3 leavers.py --redact --execute --org <org> --user <account>
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

How long each step took, from the disable at Entra (one run, by the version before a report confirmed its leavers;
a report now reads an open leaver three times before it calls it open, which took 22 to 23 s on the reference estate,
2026-10-15):

| Step | Seconds after the disable |
|---|---|
| A report calls the account a leaver (`the Entra account is disabled`) | 24 |
| `--execute` closes it, the three confirming reads included | 55 |
| The token's next refresh is refused (`invalid_grant`) | 55 |
| A re-run: `in step: already disabled, no token` | 64 |

## The urgent close, on a Basic provider session's bearer

Recorded on 2026-10-15 (VCF Automation 9.1.1.0100). The bearer came from a Basic provider session
(`POST /cloudapi/1.0.0/sessions/provider`, Basic `<user>@System`, as plate 04 of the platform-identity chapter
prints it) of a directory account holding System Administrator, and no Graph variable was set. The account was one
the provider made for the run in a classic OIDC organization, holding no token, so only the disable was exercised.

```
$ python3 leavers.py --redact --close-now --org <org> --user <account> --execute
Leavers · CLOSE-NOW · one named account, closed without asking Entra
  --user {{user-1}} (resolved as given) selects account {{user-1}}
  {{org-1}}: one account named for --close-now; Entra not asked
    direct role assignments on federated accounts: {{user-1}} (Organization Member)
    {{user-1}}: closed on request (named with --close-now; Entra was not asked whether the person has left) -> closed
      revoked 0 of 0 token(s); read back: enabled False, tokens left 0, other fields changed 0; held True
  totals: keep 0, leaver 0, out of scope 0, undetermined 0, open leavers 0, refused 0, closed 1, not held 0, in step 0, direct role 0, name in use again 0, acknowledged 0, flagged 0
  exit 0: nothing open, nothing unread, nothing flagged
```

The same close named a local account in the same run's first try, and did not hold: the write answered 400 ("You
must set a password for local users"), the account stayed enabled, and the run exited 2 with `held False (the write
was refused (400))`. Local accounts are outside the script's scope; disable one on the platform.

## Many tenants

Recorded on 2026-10-15, read-only, on the reference estate's one Entra tenant. With `--expect-tenants` naming every
tenant a schedule runs for, the header says who reads each organization federated elsewhere. Here the three
organizations federated elsewhere sign in through another provider, so none is uncovered and the exit is the
report's own, 4, as without the flag. The same run with the tenant written as its domain name read the same.

```
$ python3 leavers.py --redact --expect-tenants <this tenant's id>
Leavers · REPORT · 4 organization(s) federated to the tenant, 3 federated elsewhere: 0 to another expected tenant, read by its own schedule; 3 to another provider (not read); 0 uncovered

$ python3 leavers.py --expect-tenants <another tenant's id>
--expect-tenants does not name this run's own tenant (ENTRA_TENANT_ID): pass the full list, the same on every schedule
```

The second command exits 5 and reads no organization. An organization federated to an Entra tenant the list leaves
out reads like this, and the run exits 3 (from the script's tests: the reference estate has one tenant):

```
  {{org-5}}: unreadable (uncovered: no schedule reads it (its Entra tenant is not in --expect-tenants))
```

## What to read in it

- **Leavers in step are the goal.** Each leaver above is disabled and holds no token, so the run changes nothing and
  says `in step`. A leaver still enabled, or still holding a token, is read three times more, ten seconds apart;
  when every read agrees it reads `would revoke its tokens and disable it` and sets the exit code to 1: that is the
  line a scheduled report exists to catch, and a person runs the close on it. When the reads disagree, as Entra's do
  for seconds after a change, it reads undetermined (`Entra's reads disagree: ...`) and sets 3, and the next run
  reads it again.
- **Each exit code is one state, and every one but 0 is an alert.** 1 an open leaver, three reads agreeing: run the
  close. 3 a read that failed or an account undetermined, a leaver whose reads disagreed among them: fix the read
  before trusting any decision. 4 a flag nobody acknowledged: decide
  it and acknowledge it until a date. With `--execute`, 2 a close that did not hold: finish it by hand. The first that
  applies wins, so a flag never hides a lost Graph permission (3) or an open leaver (1).
- **A direct role is a flag, never a leaver by itself.** An account that passes Entra's gate and holds a role directly
  reads keep even when no imported group carries it, because VCF Automation refuses only a user with neither; it is
  flagged `direct-role` for a person to decide. A user found only by `mail` or `otherMails` whose principal name is
  another name reads undetermined, with the mismatch as its reason, until its organization is declared with
  `--name-claim <org>=mail`.
- **Closing an account does not drop its direct roles.** After the close, the throwaway account still holds Service
  Broker User, granted to it by name. A new person given a departed person's name reached the account and its direct
  role while the account was enabled (over SAML and over OIDC keyed on `preferred_username`); whether this disabled
  account would turn that person away was not run. So the report keeps flagging it until someone drops the role or
  deletes the account. The `direct role assignments` line in every organization is the check that roles arrive only
  through groups: it should read `none`.
- **Two kinds of leaver.** The account in `{{org-3}}` left at Entra (its Entra account is disabled). The two accounts
  in `{{org-1}}` and `{{org-2}}` still exist and are enabled at Entra, but no group assigned to those apps carries
  them any more, so a sign-in would be refused at Entra's gate. Both count, because either stops the next sign-in
  while leaving the account and any token behind.
- **Federated elsewhere is not read.** Three organizations on the estate sign in through VCF single sign-on, the
  identity broker, or another provider; they are counted, not judged. Run the script once per Entra tenant, and give
  every schedule the same full `--expect-tenants` list, so an organization on a tenant no schedule reads exits 3
  instead of passing unread.
- **The local account is out of scope.** `{{user-1}}` is an organization's local administrator, the way in when the
  provider refuses; its role is direct by nature and is counted apart (`direct_local` in the record), never flagged.
