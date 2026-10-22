# What protects the management plane, and whether it actually ran

Companion to the chapter
([privatecloudarchitect.com/handbook/platform-backup](https://privatecloudarchitect.com/handbook/platform-backup)):
one read-only script that reads the backup configuration **and** the run history of every plane that will
answer, and reports the difference. Stdlib Python only; no credential is printed or written.

| File | What it is |
|---|---|
| `recovery.py` | Reads each plane's schedule in its own encoding, counts the calendar days its run history covers and the days it does not, checks the age of each plane's newest successful copy against the longest wait its schedule allows, computes the span the retained copies cover, diffs the copy's scope against the parts catalog where the plane publishes one, normalises the targets before comparing them, and asks each plane whether a restore has ever run on it. Exits 1 when a newest copy is overdue: that is the alert. Every response passes through `strip_secrets` inside the function that performs the request. Writes `recovery.json`, and refuses to write a record carrying an address, a path or an account name. |
| `recovery.json` | That record from the reference estate, 2026-10-22, three planes on VCF 9.1.1. The chapter's plates render it. |
| `expected-output.md` | What the script printed for that record. |
| `rehearsal.md` | A record template for the restore rehearsal: what to write down before, during and after, so the result is a list rather than an impression. |

## Run it

```bash
export SDDC_HOST=<sddc-manager-fqdn>  SDDC_TOKEN_FILE=~/.secrets/sddc-bearer                   # mode 0600
export VC_HOST=<vcenter-fqdn>   VC_USER=<sso-user>  VC_PASSWORD_FILE=~/.secrets/vc            # mode 0600
export NSX_HOST=<nsx-manager-fqdn>  NSX_USER=<user>  NSX_PASSWORD_FILE=~/.secrets/nsx          # mode 0600
export TLS_VERIFY=false                                                                        # only on a self-signed lab CA

python3 recovery.py; echo "exit $?"
```

`VC_SESSION_FILE` (a session id) and `NSX_BASIC_FILE` (`user:password`) still work in place of the user and password
file. Every credential file is refused, unread, if it is open to group or other. Each plane is optional. Anything the
script cannot reach it **names** rather than omits, because a comparison missing a column still looks complete.

`BACKUP_AGE_MARGIN_HOURS` (default 6) is the slack past the longest scheduled wait before a copy counts as overdue: a
daily schedule allows 30 hours, a weekdays-only schedule 78, because Friday to Monday is its longest wait.

**Exit codes.** 0 every plane read holds a copy younger than its schedule allows; 1 a plane's newest copy is overdue,
or a plane read holds no successful copy (page on this one); 2 a setting is missing, or a secret file is open to group
or other; 3 a sign-in or a read failed; 4 the record refused to write, because an estate value survived the scrub or the
run read fewer planes than the record on disk.

## The schedule is not the cadence

Every plane encodes "when" differently, and the field that names the cadence is not the field that sets it:

| plane | the field that names it | what it says | the day list beside it | what actually happens |
|---|---|---|---|---|
| lifecycle manager | `frequency` | `WEEKLY` | all seven days named | **daily** |
| vCenter | none | nothing | empty list | **daily** (empty means every day here) |
| network manager | `resource_type` | `WeeklyBackupSchedule` | five integers | **weekdays only** |

So the script takes the timestamps. It collapses every recorded run to a calendar day, then reports the days
**between** the first and the last that carry nothing. That number is the one worth having, and it exists
nowhere in any status field.

## Why a gap never alerts

A failed backup is a record. A backup that never started is the absence of one, and absences are not in the
list anybody is watching. On the estate this was written against, every recorded run succeeded, no run carried
an error, and there were still stretches of more than two weeks with no copy at all. Every dashboard built on
last-run-status was correctly green throughout.

**Alert on the age of the newest copy, not on the status of the last run.** It is two timestamps and one
comparison, and it is the only signal that separates a healthy estate from a silent one. `recovery.py` makes that
comparison per plane and exits 1 when a copy is overdue, so a scheduled run of it is the alert.

## Retention is copies, not days

A plane that keeps the 30 most recent copies keeps 30 days only when 30 runs happened on 30 consecutive days. The
script computes the span the retained copies actually cover from the run history (`recoveryWindow`), on the planes
that publish both a retention count and a history to count it against.

## The history has a horizon

From 9.1.1 the lifecycle manager cleans up tasks older than a retention setting (`taskRetentionDays`; 365 on the
reference estate). A count of runs, a coverage figure and the absence of a restore task all reach back that far at most,
so read the window's first day beside the count.

## Scope, stated plainly

- Read-only. Every call is a `GET`, apart from opening (and then closing) a vCenter session when you sign in with a
  user and password file. Nothing here takes, deletes or restores a backup.
- Backup configurations carry credentials for the target, so every secret-bearing key is deleted inside the
  function that performs the request and only a boolean survives. Extend `SECRET_KEYS` before adding a read.
- A field absent from a `GET` is not proof the setting is unset: several of these planes accept values they
  never return. The script reports what the response contains and does not infer from what it omits.
- Where a plane reports only its most recent backup, no coverage figure is computed for it and the record says
  why rather than leaving the column out.
- **A run that reached fewer planes than the record on disk refuses to write.** Each plane needs its own
  credentials, so a partial run is ordinary. The record counts its own coverage in `planesRead`, and the
  script compares that number before writing rather than replacing a fuller reading with a thinner one.
- Every address, directory path, fingerprint and account name in the record is a placeholder, and the script
  refuses to write a record in which one survived.

## Reading the record

`planes` holds one entry per plane, each with `reached` (and `why` when it was not). Inside a reached plane:
`schedule` carries the field that names the cadence, what it says, the day list and the time; `runs` carries
the counts and statuses; `coverage` is the important one (`windowDays`, `daysCovered`, `daysUncovered`, `gaps`,
`longestGap` and `gapsBySize` with dates); `parts` carries the catalog, the selection and
`deselectedDefaults`, which is the subtraction the schedule never mentions; `target` is normalised so the
planes can be compared; and `restoreEvidence` is each plane's answer to whether a restore has ever run, quoted
rather than summarised. `age` is the alert's arithmetic (`newestCopyUtc`, `ageHours`, `allowedHours`, `overdue`), and
`recoveryWindow` is the span the retained copies cover. At the top, `distinctTargets` against `planesRead` is how many
separate places the management plane's copies actually land, and `planesOverdue` is the number the exit code acts on.

## After the reads: the rehearsal

No read says whether a copy can be put back. Book a restore rehearsal on the rehearsal instance, follow the vendor's
procedure for the component at the build you run, and fill in [`rehearsal.md`](rehearsal.md): what came back, what
needed replaying by hand, how long it took, and what the restored component (not the restore task) shows.
