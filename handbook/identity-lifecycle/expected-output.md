# What a run looks like

The reference estate, 2026-10-15 (UTC): VCF Automation 9.1 with seven organizations federated somewhere, four of
them to one Entra ID tenant (a classic and an All Apps organization over OIDC, and one of each over SAML); three
more have their federation switched off. Run with `--redact`, so the names are placeholders; the record path is shortened
to its file name. Placeholders are numbered per run, so the same person can carry a different number in each
transcript. The first transcript is the script as it stands; each one after it says which run, and which version of
the script, it comes from.

## The report

The run behind `leavers.json`, read-only, on 2026-10-15 at 21:14 UTC, by the script as it stands, on the provider API
token the reference estate keeps (`VCFA_PROVIDER_REFRESH_TOKEN_FILE`, `WARN_DAYS` at its default). It took 34.6 s.
It lists the three organizations with their federation switched off and reads their accounts and tokens, none of
them federated, so they change no exit; it confirms every open leaver over three reads before it counts one, and none
was open; and it reads its own token's end date, 20.1 days off, inside the 30-day window. Exit 4: nothing is open and
nothing went unread, one federated account holds a role granted to it directly, a flag nobody has acknowledged yet,
and the run's own token needs rotating. Every federated account was found at Entra by its userPrincipalName, and
every account reached the decision the run before it reached (that run made 95 calls; this one makes 103, adding the
switched-off organizations' reads and its own token's). Each SAML organization's `user_key` in the record is Entra's
name claim, `http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name`: the scrub keeps the claim namespaces, which
name no estate, where a run of the version before replaced that host with a placeholder.

```
$ python3 leavers.py --redact
Leavers · REPORT · 4 organization(s) federated to the tenant, 3 federated elsewhere (not read), 3 with federation switched off
  {{org-5}}: federation switched off (OIDC and SAML both disabled); no enabled federated account and no API token of one: nothing for this report to judge
  {{org-6}}: federation switched off (OIDC and SAML both disabled); no enabled federated account and no API token of one: nothing for this report to judge
  {{org-7}}: federation switched off (OIDC and SAML both disabled); no enabled federated account and no API token of one: nothing for this report to judge
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
  credential: provider API token {{name-1}}, ends 2026-11-04T22:31:54Z (20.1 days; WARN_DAYS 30)  FLAG credential-ends
  totals: keep 7, leaver 3, out of scope 1, undetermined 0, open leavers 0, refused 0, closed 0, not held 0, in step 3, direct role 1, name in use again 0, acknowledged 0, flagged 1
  exit 4: a flag nobody acknowledged, or this run's own API token near its end: decide and --ack the flag; rotate the token, naming its successor in VCFA_PROVIDER_TOKEN_NAME

103 call(s), 0 refused; leavers.json written with every estate value replaced; exit 4
```

## The same report, with the flag acknowledged

Recorded earlier the same day (04:48 UTC) by an earlier version of the script, on a provider bearer: it did not yet
list the organizations with their federation switched off, and on a bearer there is no token end date to flag. The
flag above is the closed test leaver of the next section, kept to show it. Once a person has decided on a flag, an
acknowledgement file silences it until a date; the report still lists it, and that run exited 0. Only the lines the
acknowledgement changes are shown. On a provider API token inside `WARN_DAYS`, as in the run above, the token's own
flag still sets 4: it is not acknowledged, and the rotation clears it.

```
$ cat acks.json
[{"org": "<org>", "account": "<account>", "flag": "direct-role", "until": "2026-12-31"}]
$ python3 leavers.py --redact --ack acks.json
    {{user-4}}: leaver (the Entra account is disabled) -> in step: already disabled, no token  FLAG direct-role (acknowledged until 2026-12-31)
  totals: keep 7, leaver 3, out of scope 1, undetermined 0, open leavers 0, refused 0, closed 0, not held 0, in step 3, direct role 1, name in use again 0, acknowledged 1, flagged 0
  exit 0: nothing open, nothing unread, nothing flagged
```

## A leaver, closed

Recorded on 2026-10-13 with the version before each state had its own exit code, so its totals line is shorter and it
ends at exit 1; the same state, closed with nothing open and one flag, now exits 4. That version also listed no
organization with its federation switched off and read no end date of its own credential. A throwaway user on the reference
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

Recorded on 2026-10-15 (VCF Automation 9.1.1.0100), by an earlier version whose close printed the same lines as the
script does now. The bearer came from a Basic provider session
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

That run's first try named a local account, on a version that did not yet refuse one: it revoked the account's tokens,
the write answered 400 ("You must set a password for local users"), the account stayed enabled, and that version
exited 2. The script now refuses a local account at the plan, before anything is sent, with exit 5 (from the script's
tests):

```
$ python3 leavers.py --redact --close-now --org <org> --user <a local account> --execute
  --user: refused (see the report below)
Leavers · CLOSE-NOW · one named account, closed without asking Entra
  --user {{user-1}} (resolved as given) selects account {{user-1}}: refused (account {{user-1}} is a LOCAL account: --close-now closes a federated account (OAUTH or SAML), and nothing is sent to any other; close a local account in the organization's own administration)
  refused: account {{user-1}} is a LOCAL account: --close-now closes a federated account (OAUTH or SAML), and nothing is sent to any other; close a local account in the organization's own administration
  totals: keep 0, leaver 0, out of scope 0, undetermined 0, open leavers 0, refused 0, closed 0, not held 0, in step 0, direct role 0, name in use again 0, acknowledged 0, flagged 0
  exit 5: not run as asked

not run as asked; leavers.json not written; exit 5
```

Local accounts are outside the script's scope; disable one in the organization's own administration.

## The urgent close's plan, and a principal name under `oid`

From the script's tests: no organization federated to the reference estate's tenant was keyed on `oid` on
2026-10-15. Without `--execute` the close is a plan. It sends nothing, and two lines state it: its header reads `CLOSE-NOW
PLAN, nothing sent`, and its last line says nothing was sent and nothing was closed, and how to close. Under `oid` a
principal name is taken by the plan only, beside `--left-on`, the departure date the leaver notice gives. The plan
prints the object id the name resolved to, when that Entra user was created and when the account was made, and it
refuses a name given to someone after the departure. Here an existing person was renamed onto the departed person's
name. Their Entra user (2025-01-10) and their account (2025-02-01) both predate the departure (2026-09-01), so the
dates pass:

```
$ python3 leavers.py --redact --close-now --org <org> --user <principal name> --left-on 2026-09-01
  --user: matched (values withheld under --redact; the report below names them as placeholders)
Leavers · CLOSE-NOW PLAN, nothing sent · one named account, to be closed without asking Entra
  --user {{user-2}} (resolved Graph GET /users/{principal name}, Entra user {{user-2}}, object id {{user-1}}, created 2025-01-10T10:00:00Z) selects account {{user-1}}, created 2025-02-01T08:00:00.000Z
  {{org-1}}: one account named for --close-now; Entra not asked
    direct role assignments on federated accounts: none
    {{user-1}}: closed on request (named with --close-now; Entra was not asked whether the person has left) -> planned: revoke 0 token(s) (DELETE /cloudapi/1.0.0/tokens/{id} each), then disable the account (PUT /cloudapi/1.0.0/users/{id} with enabled false); nothing sent
  totals: keep 0, leaver 0, out of scope 0, undetermined 0, open leavers 0, refused 0, closed 0, not held 0, in step 0, direct role 0, name in use again 0, acknowledged 0, flagged 0
  exit 0: plan only: nothing was sent and nothing was closed; to close, run it again with --user {{user-1}} (the object id, never the name) and --execute
```

The same name given to `--execute` is refused, exit 5, before it is resolved and before anything is sent, whatever
Entra holds under it: under `oid`, `--execute` takes an object id or the account's id only. The dates cannot tell this
person from the one who left, so the close takes the object id the notice carries, which the plan above printed for
checking, never the name. The close reads the key the organization stores whether or not its federation is switched
on, so the same refusal holds on one switched off:

```
$ python3 leavers.py --redact --close-now --org <org> --user <principal name> --left-on 2026-09-01 --execute
  --user: refused (see the report below)
Leavers · CLOSE-NOW · one named account, closed without asking Entra
  refused: the organization is keyed on oid, so --execute takes an object id or the account's id (urn:vcloud:user:...), never a name: {{user-1}} is refused before it is resolved and before anything is sent, whatever Entra holds under it. Run the plan without --execute, with --left-on (the departure date the leaver notice gives), to resolve the name and print its object id; check that object id against the leaver notice, then run again with --user <object id> --execute
  exit 5: not run as asked
```

Only the header, the refusal and the exit line are shown; the match line, which carries the same refusal after it,
and the totals are left out.

## Many tenants

Recorded on 2026-10-15, read-only, on the reference estate's one Entra tenant, by an earlier version that did not yet
list the organizations with their federation switched off; the script as it stands adds them to the header, as in
the first transcript. With `--expect-tenants` naming every
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

## The run's own provider API token

The report run read-only on 2026-10-15 at 13:18 UTC on the provider API token the reference estate keeps, a token
the platform's token list gave an end of 2026-11-04: once with `WARN_DAYS=5`, once at the default 30, and once on a
provider bearer. Only the lines this part adds are shown; the organizations read as that day's estate stood (five
organizations, nine accounts kept, three leavers in step, one direct-role flag), so each run exited 4 on that flag.

```
$ WARN_DAYS=5 python3 leavers.py --redact          # VCFA_PROVIDER_REFRESH_TOKEN_FILE set
  credential: provider API token {{name-1}}, ends 2026-11-04T22:31:54Z (20.4 days; WARN_DAYS 5)
$ python3 leavers.py --redact                      # the same token, WARN_DAYS at its default
  credential: provider API token {{name-1}}, ends 2026-11-04T22:31:54Z (20.4 days; WARN_DAYS 30)  FLAG credential-ends
$ python3 leavers.py --redact                      # VCFA_PROVIDER_BEARER_FILE set instead
  credential: provider bearer, ends an hour after its sign-in: no end date to read
```

An earlier run of the same three, at 13:16 UTC, read the same end and the same flags on the token; its provider
bearer leg exited 3 with one call refused, which that run's driver counted without naming, and the run above found
no call refused.

## The leaver test, before and after a close

`leaver_test.py` on 2026-10-15, on a throwaway All Apps organization over SAML built for the test, with a throwaway
test user that had signed in and minted its own API token. First run before anything was removed, with the planned
removal time; then the user was taken out of the entitled group at Entra at 23:50:27 UTC, signed in once in a browser
(Entra refused it with AADSTS50105), and `leavers.py --execute --org --user` closed the account; then the script was
run once a minute. The runs printed names; they are replaced here with the placeholders `--redact` prints, and the
record path shortened to its file name.

```text
$ python3 leaver_test.py --org {{org-1}} --user {{user-1}} --app {{id-3}} --removed-at 2026-10-15T23:50:19Z --latency 30
leaver test: {{user-1}} in {{org-1}}, removed 2026-10-15T23:50:19Z, latency 30 min (deadline 2026-10-16T00:20:19Z); read 2026-10-15T23:50:22Z
  FAIL    account disabled, no token: the account reads enabled and 1 API token(s) it owns are listed
  FAIL    token refused: the token still yields an access token (dropped unread)
  UNREAD  sign-in refused: no sign-in to the app since the removal is in the log yet: sign in as the test user, then run again before the deadline
exit 1: the leaver still has a way in

$ python3 leaver_test.py --org {{org-1}} --user {{user-1}} --app {{id-3}} --removed-at 2026-10-15T23:50:27Z --latency 30
leaver test: {{user-1}} in {{org-1}}, removed 2026-10-15T23:50:27Z, latency 30 min (deadline 2026-10-16T00:20:27Z); read 2026-10-15T23:51:58Z
  PASS    account disabled, no token: disabled, and no API token it owns is listed
  PASS    token refused: refused: 400 invalid_grant
  UNREAD  sign-in refused: no sign-in to the app since the removal is in the log yet: sign in as the test user, then run again before the deadline
exit 3: not proven: a check could not be made (nothing is known about it)

(the same, four more times, a minute apart)

$ python3 leaver_test.py --org {{org-1}} --user {{user-1}} --app {{id-3}} --removed-at 2026-10-15T23:50:27Z --latency 30
leaver test: {{user-1}} in {{org-1}}, removed 2026-10-15T23:50:27Z, latency 30 min (deadline 2026-10-16T00:20:27Z); read 2026-10-15T23:57:34Z
  PASS    account disabled, no token: disabled, and no API token it owns is listed
  PASS    token refused: refused: 400 invalid_grant
  PASS    sign-in refused: refused with 50105 (the user is not assigned to the app), 17 s after the removal
exit 0: every check passed inside the latency
6 call(s), 0 read(s) refused or not read whole (the refresh grant's 400 invalid_grant is the token check passing, not a failed read); leaver-test.json written with every estate value replaced
```

The run over OIDC the same day, with the test user disabled at Entra instead, read the same way: exit 1 before, exit 3
twice while the log caught up, then exit 0 at 23:45:57 UTC, the refusal logged as 50057 for an attempt 19 s after the
removal. Read it as: the account and the token checks pass as soon as the close holds, and the sign-in check waits for
Entra's log, which held the refused attempt some six to seven minutes after it was made; a run that finds nothing in
the log yet is unproven, never a pass. The last line's wording is the script as it stands; the runs above printed
the count of refused calls without separating the grant's 400 from a failed read.

## What to read in it

- **Leavers in step are the goal.** Each leaver above is disabled and holds no token, so the run changes nothing and
  says `in step`. A leaver still enabled, or still holding a token, is read three times more, ten seconds apart;
  when every read agrees it reads `would revoke its tokens and disable it` and sets the exit code to 1: that is the
  line a scheduled report exists to catch, and a person runs the close on it. When the reads disagree, as Entra's do
  for seconds after a change, it reads undetermined (`Entra's reads disagree: ...`) and sets 3, and the next run
  reads it again.
- **Each exit code is one state, and every one but 0 is an alert.** 1 an open leaver, three reads agreeing: run the
  close. 3 a read that failed or an account undetermined, a leaver whose reads disagreed among them (the next run
  reads it again), a list read in part, and an organization with its federation switched off that still holds an
  enabled federated account or a token of one: fix the read before trusting any decision. 4 a flag nobody acknowledged: decide
  it and acknowledge it until a date. With `--execute`, 2 a close that did not hold: run the `finish:` line printed
  under it, the close again for that account by its id (the README says when to finish by hand). The first that
  applies wins, so a flag never hides a lost Graph permission (3) or an open leaver (1).
- **The `credential:` line is the job's own token.** On a provider API token it gives the end the token record holds
  and the days left; `FLAG credential-ends` inside `WARN_DAYS` sets 4, and the fix is a rotation, not an
  acknowledgement: mint the successor, point `VCFA_PROVIDER_REFRESH_TOKEN_FILE` at its file and
  `VCFA_PROVIDER_TOKEN_NAME` at its name, run once, and revoke the old one. A line reading `unread` sets 3: the job does
  not know when its own credential stops. With two `REFRESH` tokens on the job's user, during a rotation or when one
  administrator mints both scheduled jobs' tokens, the unread reason names `VCFA_PROVIDER_TOKEN_NAME` as the fix.
- **A federation switched off is listed, not judged.** Each such organization gets a line. One with an enabled
  federated account, or an API token of one, reads `unreadable` with the counts and sets 3, because that account
  comes back when the federation does, and whether that token stops meanwhile was not tested; one with neither reads `nothing for this report
  to judge`. The three on the reference estate held neither.
- **A close reads back what it did, and a read-back that did not read is not a pass.** `held True` needs the account
  read back disabled with no other field changed and the token list read back with none left; when either read is
  refused or answers without its list, the line reads `tokens left unread` (or `enabled None`), `held False`, the
  reason names the read, and the run exits 2, with a `finish:` line under it naming what was left and the command
  that finishes it.
- **A direct role is a flag, never a leaver by itself.** An account that passes Entra's gate and holds a role directly
  reads keep even when no imported group carries it, because VCF Automation refuses only a user with neither; it is
  flagged `direct-role` for a person to decide. A user found only by `mail` or `otherMails` whose principal name is
  another name reads undetermined, with the mismatch as its reason, until its organization is declared with
  `--name-claim <org>=mail`.
- **Closing an account does not drop its direct roles.** After the close, the throwaway account still holds Service
  Broker User, granted to it by name. A new person given a departed person's name reached the account and its direct
  role while the account was enabled (over SAML and over OIDC keyed on `preferred_username`); a closed account turned
  that person away, and enabled again, let them in holding its direct role (All Apps organizations, one run per
  protocol). So the report keeps flagging it until someone drops the role or deletes the account. The `direct role assignments` line in every organization is the check that roles arrive only
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

## A replayed run

Each script on the set beside it, run from the companion folder: the recorded runs above, every name a placeholder,
read from recorded answers with nothing sent and judged at the time each set was recorded. The first line of each run
is written to standard error, and so is the second line of a run given `--execute`.

`leavers.py --replay replay/leavers` reaches every decision `leavers.json` holds, with the same 103 calls, and exits 4,
as the recorded run did. Given `--execute`, alone or with `--close-now`, it runs the close's plan alone: the
organization's accounts are read and judged, nothing is sent, and the plan's own exit stands (the flags here, 4; a
`--close-now` plan, 0).

```text
$ python3 leavers.py --replay replay/leavers --redact
replay: 87 recorded answers from replay/leavers; nothing is sent and no credential is read
Leavers · REPORT · 4 organization(s) federated to the tenant, 3 federated elsewhere (not read), 3 with federation switched off
  {{org-5}}: federation switched off (OIDC and SAML both disabled); no enabled federated account and no API token of one: nothing for this report to judge
  {{org-6}}: federation switched off (OIDC and SAML both disabled); no enabled federated account and no API token of one: nothing for this report to judge
  {{org-7}}: federation switched off (OIDC and SAML both disabled); no enabled federated account and no API token of one: nothing for this report to judge
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
  credential: provider API token {{name-1}}, ends 2026-11-04T22:31:54Z (20.1 days; WARN_DAYS 30)  FLAG credential-ends
  totals: keep 7, leaver 3, out of scope 1, undetermined 0, open leavers 0, refused 0, closed 0, not held 0, in step 3, direct role 1, name in use again 0, acknowledged 0, flagged 1
  exit 4: a flag nobody acknowledged, or this run's own API token near its end: decide and --ack the flag; rotate the token, naming its successor in VCFA_PROVIDER_TOKEN_NAME

103 call(s), 0 refused; leavers.replay.json written with every estate value replaced; exit 4

$ python3 leavers.py --replay replay/leavers --execute --org org-3
replay: 87 recorded answers from replay/leavers; nothing is sent and no credential is read
replay: --execute runs its plan alone under --replay; nothing is sent
Leavers · EXECUTE PLAN · 1 organization(s) federated to the tenant
  org-3 (OIDC): 3 account(s); gate group-3
    direct role assignments on federated accounts: user-4@domain-1.example.test (Service Broker User)
    user-2@domain-1.example.test: keep (entitled through group-3)
    user-3@domain-1.example.test: keep (entitled through group-3)
    user-4@domain-1.example.test: leaver (the Entra account is disabled) -> in step: already disabled, no token  FLAG direct-role
  credential: provider API token name-1, ends 2026-11-04T22:31:54Z (20.1 days; WARN_DAYS 30)  FLAG credential-ends
  totals: keep 2, leaver 1, out of scope 0, undetermined 0, open leavers 0, refused 0, closed 0, not held 0, in step 1, direct role 1, name in use again 0, acknowledged 0, flagged 1
  exit 4: a flag nobody acknowledged, or this run's own API token near its end: decide and --ack the flag; rotate the token, naming its successor in VCFA_PROVIDER_TOKEN_NAME

25 call(s), 0 refused; leavers.replay.json written with every estate value replaced; exit 4

$ python3 leavers.py --replay replay/leavers --close-now --org org-3 --user user-4@domain-1.example.test --execute
replay: 87 recorded answers from replay/leavers; nothing is sent and no credential is read
replay: --execute runs its plan alone under --replay; nothing is sent
  --user user-4@domain-1.example.test (resolved as given) selects account user-4@domain-1.example.test
Leavers · CLOSE-NOW PLAN, nothing sent · one named account, to be closed without asking Entra
  --user user-4@domain-1.example.test (resolved as given) selects account user-4@domain-1.example.test
  org-3: one account named for --close-now; Entra not asked
    direct role assignments on federated accounts: user-4@domain-1.example.test (Service Broker User)
    user-4@domain-1.example.test: closed on request (named with --close-now; Entra was not asked whether the person has left) -> planned: revoke 0 token(s) (DELETE /cloudapi/1.0.0/tokens/{id} each), then disable the account (PUT /cloudapi/1.0.0/users/{id} with enabled false); nothing sent
  totals: keep 0, leaver 0, out of scope 0, undetermined 0, open leavers 0, refused 0, closed 0, not held 0, in step 0, direct role 0, name in use again 0, acknowledged 0, flagged 0
  exit 0: plan only: nothing was sent and nothing was closed; to close, run it again with --execute

4 call(s), 0 refused; leavers.replay.json written with every estate value replaced; exit 0
```

`leaver_test.py --replay replay/leaver_test` on the leaver test's passing run over SAML. The first run exits 0, as the
recorded run did; the second asks for a 5-minute latency, so its deadline falls before the reads and it exits 3.

```text
$ python3 leaver_test.py --replay replay/leaver_test --org org-1 --user name-1@domain-1.example.test --app 00000000-0000-4000-8000-000000000003 --removed-at 2026-10-15T23:50:27Z --latency 30
replay: 8 recorded answers from replay/leaver_test; nothing is sent and no credential is read
leaver test: name-1@domain-1.example.test in org-1, removed 2026-10-15T23:50:27Z, latency 30 min (deadline 2026-10-16T00:20:27Z); read 2026-10-15T23:57:34Z
  PASS    account disabled, no token: disabled, and no API token it owns is listed
  PASS    token refused: refused: 400 invalid_grant
  PASS    sign-in refused: refused with 50105 (the user is not assigned to the app), 17 s after the removal
exit 0: every check passed inside the latency
6 call(s), 0 read(s) refused or not read whole (the refresh grant's 400 invalid_grant is the token check passing, not a failed read); leaver-test.replay.json written with every estate value replaced

$ python3 leaver_test.py --replay replay/leaver_test --org org-1 --user name-1@domain-1.example.test --app 00000000-0000-4000-8000-000000000003 --removed-at 2026-10-15T23:50:27Z --latency 5
replay: 8 recorded answers from replay/leaver_test; nothing is sent and no credential is read
leaver test: name-1@domain-1.example.test in org-1, removed 2026-10-15T23:50:27Z, latency 5 min (deadline 2026-10-15T23:55:27Z); read 2026-10-15T23:57:34Z
  UNREAD  account disabled, no token: read after the deadline: disabled with no token now, which does not show it inside the latency
  UNREAD  token refused: refused now, read after the deadline: not shown inside the latency
  PASS    sign-in refused: refused with 50105 (the user is not assigned to the app), 17 s after the removal
exit 3: not proven: a check could not be made (nothing is known about it)
6 call(s), 0 read(s) refused or not read whole (the refresh grant's 400 invalid_grant is the token check passing, not a failed read); leaver-test.replay.json written with every estate value replaced
```
