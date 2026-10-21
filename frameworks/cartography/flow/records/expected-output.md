# What the flow lens printed on the reference estate

Run read-only on 2026-10-21 against VCF Operations for Networks on the reference estate, the password read from a file
of mode 0600. Only the summary and count lines are shown: the lines under each heading name destinations and
workloads, and the full findings file it also wrote names them, so it is not published. The counts-only record the run wrote is [`flows.json`](flows.json).

## Offline: `python3 discover_flows.py --self-test`

```text
self-test OK: the fixture (22 synthetic flows) reproduces the golden findings exactly, 2 shared service(s) quarantined and 3 application boundary(ies) resolved, entirely offline.
```

## Live: `python3 discover_flows.py --hours 168 --export findings.json --record flows.json`

```text
Flow lens: 1851 raw flows, 1330 resolved to src->dst edges over 168h; 155 sources talking to 579 destinations.
SHARED SERVICES (quarantined before boundary detection): 26
REVIEW (high fan-in on web ports, a shared service OR a popular front-end): 18
APPLICATIONS (2 candidate boundaries from 49 VM-to-VM flows, 26 shared services excluded):
Nothing was written. Confirm these candidates, then hand the confident ones to the supervisor lens's write-back (../writeback_tags.py) or your own tagging.
```
