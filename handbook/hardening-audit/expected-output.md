# Expected output

A full three-plane run. The figures below are one modified lab's state on one date, shown for the transcript's shape only; they are not the product's out-of-the-box state and not a target. Your run reports your estate, and the audit question is whether your counts match your intent:

```
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

Exit code 1: findings are present, and the posture folder holds the evidence:

```
posture-2026-08-15/
  report.md     findings, skips, and the reads-to-controls mapping
  reads.json    the distilled records (counts, horizons, names; never secrets)
```

With only one plane's environment set, the other reads record as skips and the run still
succeeds; the skip list prints in the transcript and lands in the report, because an audit
folder that silently omits reads is worse than one that names what it could not produce:

```
  read certificates     clean
  read credentials      1 finding(s)
  read backup           1 finding(s)
  SKIP alert-scope      (ops environment not set)
  SKIP firewall-floor   (vcfa environment not set)
  SKIP access           (vcfa environment not set)
  SKIP audit-trail      (vcfa environment not set)
```
