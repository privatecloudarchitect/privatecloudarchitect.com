# Expected output

What `recovery.py` printed on the reference estate on 2026-11-19 at 05:24Z: VCF 9.1.1, one instance's
lifecycle manager, management vCenter and network manager, read-only. vCenter and the network manager signed in with
a user and a password file; the lifecycle manager took a bearer file.

```
$ python3 recovery.py
recovery.py: what protects the management plane, and whether it actually ran

  the lifecycle manager      frequency says 'WEEKLY', 7 day(s) listed, at 04:00
                             321 run(s); 321 of 366 days covered, 45 NOT, in 5 gap(s); longest 19 days (2026-08-19 .. 2026-09-06)
  the management vCenter     recurrence_info.days says 'None', 0 day(s) listed, at 23:59
                             424 run(s); 418 of 447 days covered, 29 NOT, in 5 gap(s); longest 20 days (2026-08-18 .. 2026-09-06)
                             copy contains ['common']; deselected defaults: ['supervisors', 'seat']
  the network manager        resource_type says 'WeeklyBackupSchedule', 5 day(s) listed, at 07:00
                             {'overall': 'SUCCESS', 'clusterBackupsReported': 1, 'inventoryBackupsReported': 1, 'mostRecentClusterBackupUtc': '2026-11-18T07:00:00Z', 'historyDepth': 'only the most recent is reported'}

  TARGETS: 3 plane(s) read, 1 distinct target description(s)
     every plane read writes to the same place, so the recovery plan has one target and as many dependants as there are planes

  AGE OF THE NEWEST COPY, against the longest scheduled wait plus 6 h
     the lifecycle manager      newest 2026-11-19T04:00:00Z, 1.4 h old, allowed 30 h: within
     the management vCenter     newest 2026-11-19T00:02:43Z, 5.4 h old, allowed 30 h: within
     the network manager        newest 2026-11-18T07:00:43Z, 22.4 h old, allowed 78 h: within

  RECOVERY WINDOW, if every retained copy is still on the target
     the lifecycle manager      keeps the 14 most recent: they span 13 days, back to 2026-11-06
     the management vCenter     keeps the 30 most recent: they span 30 days, back to 2026-10-20
     the network manager        not computed: the plane reports only its most recent backup

  HAS A RESTORE EVER RUN HERE?
     the lifecycle manager      no list at /v1/restores/tasks (HTTP 404): VMware's procedure reads a restore by the id its start returned; set SDDC_RESTORE_ID to read one
                                its task list, 1022 read, kept 365 days: types naming a restore: none; 284 carry no type
     the management vCenter     HTTP 500   {"messages": [{"args": ["RESTORE"], "default_message": "Status for 'RESTORE' does not exis
     the network manager        HTTP 200  INITIAL Restore process didn't yet start

wrote recovery.json (3 of 3 plane(s) read); every address, path and account name replaced by a placeholder
```

It exited 0: every plane's newest copy was younger than its schedule allows. It exits 1 the day one is not, which is
the alert to schedule. Your run prints the same sections for your planes; its counts are yours. The run counts and
coverage are counts within each plane's history: the lifecycle manager keeps tasks for as long as its task retention
setting says (365 days on that run), so its window moves forward a day at a time, and the network manager reports only
its most recent backup.
