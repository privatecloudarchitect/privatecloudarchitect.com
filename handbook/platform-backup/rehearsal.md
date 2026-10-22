# Restore rehearsal record

One record per rehearsal, kept beside the `recovery.json` it was planned from. Every read `recovery.py` makes is
repeatable on an ordinary afternoon; whether a copy can be put back is known only from a restore, so this record is the
half of the recovery posture no read replaces.

Hold the rehearsal on an instance where a restore that goes wrong costs an afternoon: the rehearsal instance the
platform-lifecycle chapter teaches you to keep, never the instance the copies protect. Follow the vendor's documented
restore procedure for that component at the build you run, and write down which one.

## Before

| Field | Fill in |
|---|---|
| Date and window (UTC) | |
| Instance rehearsed on | |
| Plane restored | the lifecycle manager, the vCenter, or the network manager |
| Build of that plane | |
| Copy restored from | its time (`newestCopyUtc` in `recovery.json`, or the copy you chose) and its age when you start |
| What the copy holds | for a vCenter copy, the parts it was taken with (`parts.selected`); a part left out does not come back |
| Procedure followed | the vendor's restore procedure for this component, by title and the version it applies to |
| Changes made since the copy | what you expect to replay by hand, and where you will find it |

## During

| Moment | Time (UTC) |
|---|---|
| Restore started | |
| Plane answering again | |
| Checks passed | |

## After

| Field | Fill in |
|---|---|
| What came back cleanly | |
| What needed replaying by hand | |
| Checks on the restored component | read the component itself, not the restore task: its inventory, its own reads, and for the network manager its segments, gateways, firewall rules and any load-balancer controllers it deployed |
| What the task reported | a restore task can report a result the component contradicts; record both |
| What `recovery.py` says now | its `HAS A RESTORE EVER RUN HERE?` lines after the rehearsal |
| Gaps found | each with an owner |
| Next rehearsal | a date |

The time from "restore started" to "checks passed" is the recovery time you can actually promise, and "what needed
replaying by hand" is what the age of the copy cost.
