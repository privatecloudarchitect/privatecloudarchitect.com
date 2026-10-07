# Expected output

Three runs on the reference estate, all read-only. The figures are one modified lab's state on one date, shown for
the transcript's shape only; they are not the product's out-of-the-box state and not a target. Your run reports
your estate, and the audit question is whether your counts match your intent.

## hardening.py, 2026-10-07, three planes

All three planes set, and `AUDIT_MIN_DAYS=90`: a quarter, the least window that answers a quarterly audit request
from the trail itself. `--record` also wrote [`hardening.json`](hardening.json), the same run as counts, dates and
product words only.

```text
$ export AUDIT_MIN_DAYS=90
$ python3 hardening.py --record hardening.json
HARDENING LOOP - 2026-10-07

  read certificates     clean
  read credentials      1 finding(s)
  read backup           1 finding(s)
  read alert-scope      1 finding(s)
  read firewall-floor   clean
  read access           clean
  read audit-trail      1 finding(s)
  read against        SDDC Manager 9.1.1.0.25713928, VCF Operations 9.1.1.0, VCF Automation API 9.1.1

posture folder: ./posture-2026-10-07  (7 reads, 4 finding(s), 0 skip(s))
  ! credentials: rotation is opt-in and only 6 of 49 carry an auto-rotate policy; make the split deliberate
  ! backup: encryption passphrase UNSET; backups carry the credential vault and leave the platform unencrypted
  ! alert scope: 65 of 77 alert definitions are ENABLED in the default policy; each is a page on every object no other policy claims
  ! audit trail: the oldest event this session can read is 30 day(s) old, short of the 90 decided; an incident older than that cannot be answered from this trail
```

Exit code 1: every read was made and findings are present. The posture folder holds the evidence:

```text
posture-2026-10-07/
  report.md     the build each plane answered with, findings, skips, and the reads-to-controls table
  reads.json    the distilled records (counts, horizons, names; never secrets)
```

## hardening.py, 2026-10-07, an Operations token that may not export a policy

The same run with the Operations plane's token taken from a fleet API client that holds only a viewer role. It lists
the policies and is refused the export, so the alert-scope read is a skip that quotes the platform's refusal, and
the run exits 2: the folder is incomplete. A skip names a plane without an owner, or an owner whose credential
lacks a right:

```text
$ python3 hardening.py
HARDENING LOOP - 2026-10-07

  read certificates     clean
  read credentials      1 finding(s)
  read backup           1 finding(s)
  SKIP alert-scope      (RuntimeError: policy export -> HTTP 403: User does not have the required privileges to perform this operation.)
  read firewall-floor   clean
  read access           clean
  read audit-trail      1 finding(s)
  read against        SDDC Manager 9.1.1.0.25713928, VCF Operations 9.1.1.0, VCF Automation API 9.1.1

posture folder: ./posture-2026-10-07  (6 reads, 3 finding(s), 1 skip(s))
  ! credentials: rotation is opt-in and only 6 of 49 carry an auto-rotate policy; make the split deliberate
  ! backup: encryption passphrase UNSET; backups carry the credential vault and leave the platform unencrypted
  ! audit trail: the oldest event this session can read is 30 day(s) old, short of the 90 decided; an incident older than that cannot be answered from this trail
```

## hardening.py, 2026-08-15, three planes (an earlier run)

The first run of the loop, as published with it. Two of its findings are in the run above unchanged, and the third
(alert scope) with different counts: a finding with no owner and no dated fix is reported again on the next run.
The audit trail read then reported only its count; the window it holds was added to the read later.

```text
$ python3 hardening.py
HARDENING LOOP - 2026-08-15

  read certificates     clean
  read credentials      1 finding(s)
  read backup           1 finding(s)
  read alert-scope      1 finding(s)
  read firewall-floor   clean
  read access           clean
  read audit-trail      clean

posture folder: ./posture-2026-08-15  (7 reads, 3 finding(s), 0 skip(s))
  ! credentials: rotation is opt-in and only 6 of 49 carry an auto-rotate policy; make the split deliberate
  ! backup: encryption passphrase UNSET; backups carry the credential vault and leave the platform unencrypted
  ! alert scope: 64 of 74 alert definitions are ENABLED in the default policy (Default Policy); each is a page on every object no other policy claims
```
