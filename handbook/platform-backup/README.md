# What protects the management plane, and whether it actually ran

Companion to the chapter
([privatecloudarchitect.com/handbook/platform-backup](https://privatecloudarchitect.com/handbook/platform-backup)):
one read-only script that reads the backup configuration **and** the run history of every plane that will
answer, and reports the difference. Stdlib Python only; no credential is printed or written.

| File | What it is |
|---|---|
| `recovery.py` | Reads each plane's schedule in its own encoding, counts the calendar days its run history covers and the days it does not, diffs the copy's scope against the parts catalog where the plane publishes one, normalises the targets before comparing them, and asks each plane whether a restore has ever run on it. Every response passes through `strip_secrets` inside the function that performs the request. Writes `recovery.json`, and refuses to write a record carrying an address, a path or an account name. |
| `recovery.json` | That record from the reference estate, 2026-09-19, three planes. The chapter's plates render it. |

## Run it

```bash
export SDDC_HOST=<sddc-manager-fqdn>  SDDC_TOKEN_FILE=/path/to/bearer        # mode 0600
export VC_HOST=<vcenter-fqdn>         VC_SESSION_FILE=/path/to/session-id    # optional
export NSX_HOST=<nsx-manager-fqdn>    NSX_BASIC_FILE=/path/to/user:password  # optional, mode 0600
export TLS_VERIFY=false                                                      # only on a self-signed lab CA

python3 recovery.py
```

Each plane is optional. Anything the script cannot reach it **names** rather than omits, because a comparison
missing a column still looks complete.

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
comparison, and it is the only signal that separates a healthy estate from a silent one.

## Scope, stated plainly

- Read-only. Every call is a `GET`. Nothing here takes, deletes or restores a backup.
- Backup configurations carry credentials for the target, so every secret-bearing key is deleted inside the
  function that performs the request and only a boolean survives. Extend `SECRET_KEYS` before adding a read.
- A field absent from a `GET` is not proof the setting is unset: several of these planes accept values they
  never return. The script reports what the response contains and does not infer from what it omits.
- Where a plane reports only its most recent backup, no coverage figure is computed for it and the record says
  why rather than leaving the column out.
- Every address, directory path, fingerprint and account name in the record is a placeholder, and the script
  refuses to write a record in which one survived.

## Reading the record

`planes` holds one entry per plane, each with `reached` (and `why` when it was not). Inside a reached plane:
`schedule` carries the field that names the cadence, what it says, the day list and the time; `runs` carries
the counts and statuses; `coverage` is the important one (`windowDays`, `daysCovered`, `daysUncovered`, `gaps`,
`longestGap` and `gapsBySize` with dates); `parts` carries the catalog, the selection and
`deselectedDefaults`, which is the subtraction the schedule never mentions; `target` is normalised so the
planes can be compared; and `restoreEvidence` is each plane's answer to whether a restore has ever run, quoted
rather than summarised. At the top, `distinctTargets` against `planesRead` is how many separate places the
management plane's copies actually land.
