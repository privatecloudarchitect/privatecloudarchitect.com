# Expected output

Runs on the reference estate on 2026-10-19 (VCF Operations 9.1.1.0, build 25679751). Your counts will differ; the
shape will not. The record audit ran over this handbook's own failure record, saved as `failure-record.md`, as a worked example;
point it at yours.

## The thirty-second read, and the routing table's first rows

```
$ python3 triage.py --standing --rank
659 open alert(s) of 3,927 read; 659 of them OPEN, which nobody has assigned, suspended or suppressed. Oldest first:

    468 days  OPEN       HEALTH      CRITICAL
    452 days  OPEN       HEALTH      CRITICAL
    452 days  OPEN       HEALTH      CRITICAL
    368 days  OPEN       HEALTH      WARNING
    158 days  OPEN       HEALTH      CRITICAL
    158 days  OPEN       HEALTH      CRITICAL
    158 days  OPEN       HEALTH      CRITICAL
    143 days  OPEN       HEALTH      CRITICAL
    130 days  OPEN       HEALTH      CRITICAL
    118 days  OPEN       RISK        INFORMATION

Anything at the top of that list has been standing, not happening. It is a monitoring decision somebody made once, and it is not the thing to diagnose.

The definitions that fill the open queue, commonest first:

    93 open on  93 object(s)  RISK        median   14 days  Virtual Machine is violating CIS L1 Profile (v8 and above)
    93 open on  93 object(s)  RISK        median   14 days  Virtual Machine is violating CIS L1/L2 Profile (v8 and above)
    93 open on  93 object(s)  RISK        median   14 days  Virtual Machine is violating HIPAA (v7 and above)
    92 open on  92 object(s)  RISK        median   14 days  Virtual Machine is violating VMware vSphere Security Configuration Guide for vSphere version 8 and above
    86 open on  86 object(s)  RISK        median   14 days  Virtual Machine is violating DISA (v8 and above)
    21 open on  21 object(s)  RISK        median   14 days  vSphere Distributed Port Group is violating VMware vSphere Security Configuration Guide vSphere version 8 and above
    20 open on  10 object(s)  HEALTH      median   42 days  Operational Status Down
    11 open on  11 object(s)  HEALTH      median    3 days  ESX Host Disconnect
    11 open on  11 object(s)  RISK        median   14 days  ESXi Host is violating CIS L1 Profile (v8 and above)
    11 open on  11 object(s)  RISK        median   14 days  ESXi Host is violating CIS L1/L2 Profile (v8 and above)

Each row is a routing-table row to write: the symptom, the owner who gets it, and the first read.
```

The list answers newest first, so the run reads every page before it sorts: a single page would have held the newest
alerts and missed the oldest, which are the ones this read exists to find.

## The queue profile, and the record audit

```
$ python3 triage.py --corpus failure-record.md
triage.py: what is in the queue, and what the record kept

  THE QUEUE: 3,927 alert instance(s), read whole; 659 open, 3268 closed (by status {'ACTIVE': 659, 'CANCELED': 3268})
     the open ones are 14 days old at the median, oldest 468; 52 started in the last week and 45 have stood over a month
     they come from 59 definition(s) on 175 object(s); the six commonest account for 478 of 659
     control states {'OPEN': 659}, suspended 0
     EFFICIENCY     1 open, median age   14 days, oldest 14
     HEALTH        98 open, median age   13 days, oldest 468
     RISK         560 open, median age   14 days, oldest 118
     the 3185 closed ones lasted 1.26 hours at the median; 675 under an hour, 852 over a day

  THE RECORD: 560 recorded failure(s) in failure-record.md
      170 of 560 ( 30%)  symptom      the observation, stated before any cause
      134 of 560 ( 24%)  root cause   the cause, named
       63 of 560 ( 11%)  layer        the cause classified to a layer
      216 of 560 ( 39%)  fix          what to do instead
      102 of 560 ( 18%)  evidence     where the finding came from
      334 of 560 ( 60%)  cross-link   another entry this one depends on
       42 of 560 (  8%)  corrects an earlier reading
      180 of 560 ( 32%)  quotes an HTTP status
       64 of 560 ( 11%)  mentions a log
     layer tags among the 88 that carry one: {'information contract': 28, 'structural design': 27, 'other wording': 23, 'processing logic': 5, 'platform configuration': 2, 'architectural': 2, 'infrastructure': 1}

wrote triage.json; the queue is reported as counts, ages and definitions, and no object is named
```

Exit 0. Exit 4 means the alert list was refused or read short, and nothing was reported.

What each part is there to stop:

- **the open alerts' age beside the closed ones' lifetime.** The closed alerts are what an event looks like on your
  estate; open alerts many times older than that are conditions, not incidents.
- **the badge medians.** Health and risk alerts are handled on different clocks, which makes the badge a usable first
  routing dimension.
- **the ranking.** A few definitions produce most of the queue; each of the top rows is a routing-table row to write.
- **the record funnel.** It counts only the labels it is told to look for, so a record whose entries moved to other
  words (this one's newer entries write their fix as "The rule.") reads low on that step. Point `--entry` and the
  labels at the record you keep, or adopt `failure-record.template.md`, which the audit reads as written.
