# Expected output

What `recovery.py` printed on the reference estate on 2026-10-22 at 08:32Z: VCF 9.1.1, the primary instance's
lifecycle manager, management vCenter and network manager, read-only. vCenter and the network manager signed in with
a user and a password file; the lifecycle manager took a bearer file.

```
$ python3 recovery.py
recovery.py: what protects the management plane, and whether it actually ran

  the lifecycle manager      frequency says 'WEEKLY', 7 day(s) listed, at 04:00
                             320 run(s); 320 of 364 days covered, 44 NOT, in 4 gap(s); longest 19 days (2026-08-19 .. 2026-09-06)
  the management vCenter     recurrence_info.days says 'None', 0 day(s) listed, at 23:59
                             397 run(s); 391 of 419 days covered, 28 NOT, in 4 gap(s); longest 20 days (2026-08-18 .. 2026-09-06)
                             copy contains ['common']; deselected defaults: ['supervisors', 'seat']
  the network manager        resource_type says 'WeeklyBackupSchedule', 5 day(s) listed, at 07:00
                             {'overall': 'SUCCESS', 'clusterBackupsReported': 1, 'inventoryBackupsReported': 1, 'mostRecentClusterBackupUtc': '2026-10-22T07:00:00Z', 'historyDepth': 'only the most recent is reported'}

  TARGETS: 3 plane(s) read, 1 distinct target description(s)
     every plane read writes to the same place, so the recovery plan has one target and as many dependants as there are planes

  AGE OF THE NEWEST COPY, against the longest scheduled wait plus 6 h
     the lifecycle manager      newest 2026-10-22T04:00:01Z, 4.5 h old, allowed 30 h: within
     the management vCenter     newest 2026-10-22T00:03:19Z, 8.5 h old, allowed 30 h: within
     the network manager        newest 2026-10-22T07:00:47Z, 1.5 h old, allowed 78 h: within

  RECOVERY WINDOW, if every retained copy is still on the target
     the lifecycle manager      keeps the 14 most recent: they span 13 days, back to 2026-10-09
     the management vCenter     keeps the 30 most recent: they span 29 days, back to 2026-09-23
     the network manager        not computed: the plane reports only its most recent backup

  HAS A RESTORE EVER RUN HERE?
     the lifecycle manager      no task of that type among 1130 read, and it keeps tasks for 365 days
     the management vCenter     HTTP 500   {"messages": [{"args": ["RESTORE"], "default_message": "Status for 'RESTORE' does not exis
     the network manager        HTTP 200  INITIAL Restore process didn't yet start

wrote recovery.json (3 of 3 plane(s) read); every address, path and account name replaced by a placeholder
```

It exited 0: every plane's newest copy is younger than its schedule allows. It exits 1 the day one is not, which is
the alert to schedule. The run counts and coverage are counts within each plane's history: the lifecycle manager keeps
tasks for 365 days, so its window moves forward a day at a time, and the network manager reports only its most recent
backup.
