# Expected output

## The self-test, offline

```
$ python3 reconcile.py --self-test
self-test OK: a definition with its keys reordered normalizes to the committed copy (no diff), one edited value shows as a 11-line diff, of five listed executions the 2 not ended count as in flight, and the 1 action call and 1 configuration read the deploy checks are found, offline
```

## The reference estate, 2026-10-21

One workflow on the embedded Orchestrator of VCF Automation 9.1.1, against its committed copy. The diff's own lines
are the estate's content and are left out here; the records in `records/` carry the counts.

```
$ python3 reconcile.py <workflow> --diff --record records/1-before.json          # 19:51Z
DRIFT: the committed copy (version 1.4.0, 39 items) and the running definition (version 1.2.0, 31 items) differ
  [60 diff lines printed here, the estate's content, left out; the full diff is 858 lines]
exit 1

$ python3 reconcile.py <workflow> --deploy --apply --record records/2-restore.json   # 20:17Z
pre-flight: 0 execution(s) running, waiting or suspended; 60 diff line(s) to send
PUT /content -> HTTP 204; read back matches the copy
exit 0

$ python3 reconcile.py <workflow> --diff --record records/3-after.json            # 20:17Z
IN AGREEMENT: the committed copy is the running definition (version 1.4.0)
exit 0

$ python3 reconcile.py <workflow> --deploy --apply --record records/4-rerun.json   # 20:26Z, this build
references: 7 of 7 action(s) present; 3 of 3 configuration read(s) resolve
pre-flight: 0 execution(s) not ended; 0 diff line(s) to send
NOTHING TO SEND: the running definition already is the committed copy (version 1.4.0)
exit 0
```

The restore ran on the build before this one, which printed its pre-flight in those words and counted at most 60
diff lines; its in-flight count compared upper-case state names and could not have counted a run. The 0 was
confirmed separately: of the 50 executions listed, 26 had completed and 24 had failed. The action and configuration
references this build checks were read the same way before the restore, and all resolved.
