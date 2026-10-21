# What the arbitration printed on the reference estate

Run on 2026-10-21, read-only, against VCF Operations for Networks over a 168-hour window, with the supervisor lens's
export from VCF Automation 9.1.1.0100 as the declared lens; then the write-back read the hand-off as two dry runs on
the workload domain's vCenter (vCenter 9.1.1.0.25712839), which create no category and attach no tag. Each password
was read from a file of mode 0600. File paths are shortened to the file's name. Only the summary lines are shown:
the review queue, the confident rows and the write-back's table name the estate's machines. The records each run
wrote are beside this file.

## Offline

`python3 discover_arbitration.py --self-test`

```text
self-test OK: the fixture (13 flows, 5 VM records) reproduces the golden arbitration exactly, 7 workloads classified, 2 in the review queue; with 5 confirmations (1 for a workload not seen), the hand-off carries 13 rows, 4 approve and 9 confirm, entirely offline.
```

## The arbitration, read-only

`python3 discover_arbitration.py --hours 168 --declared recs.json --export report.json --export-recommendations handoff.json --record arbitration.json`

```text
  identity anchor: 27 VCF component(s) typed {'nsx-transport-node': 13, 'vcenter': 3, 'esxi-host': 7, 'nsx-manager': 2, 'nsx-edge': 2}

  Arbitration: 110 VMs classified over 168h.
  roles       : {'application': 21, 'isolated': 52, 'shared-service': 37}
  confidence  : {'high': 28, 'low': 4, 'medium': 38, 'none': 40}
  needs review: 44 (a conflict, or too few lenses to trust)

  REVIEW QUEUE (confirm these before any write-back): 44

  CONFIDENT (66, safe to hand to write-back):

  Nothing was written. Work the review queue into a confirmations file (--confirmations), then hand the confident rows to the write-back: --export-recommendations, then ../writeback_tags.py --recommendations <file> --approve-file <file> (dry-run first).

  report written to report.json
  hand-off written to handoff.json: 42 rows, 6 approve, 36 confirm; 44 workloads held for review
  record written to arbitration.json (counts only)
```

## The write-back reads the hand-off: the approve subset, dry run

`CARTOGRAPHY_TAXONOMY=<the estate's taxonomy> python3 writeback_tags.py --recommendations handoff.json --approve recommended --record handoff-dry-recommended.json`

```text
write-back · DRY-RUN · 6 approved recommendation(s) from handoff.json

  DEFINE (vCenter-native):
    identity.app                         exists
    identity.app-layer                   would-create  +3 (presentation,logic,data)

  summary: 6 decision(s) over 3 resolvable VM(s) (0 skipped): already-set=3, attach=3
  DRY-RUN: 3 native tag(s) would be attached via the VCENTER_* identity. Re-run with --execute; to land on Supervisor-managed VMs, re-run with --actuate-as-tag-authority.
```

## The whole hand-off, approve and confirm alike, dry run

`CARTOGRAPHY_TAXONOMY=<the estate's taxonomy> python3 writeback_tags.py --recommendations handoff.json --approve all --record handoff-dry-all.json`

```text
write-back · DRY-RUN · 42 approved recommendation(s) from handoff.json

  DEFINE (vCenter-native):
    identity.app                         exists
    identity.app-layer                   would-create  +3 (presentation,logic,data)
    lifecycle.env-observed               would-create  +6 (prod,stage,dev,test,dr,lab)

  summary: 23 decision(s) over 11 resolvable VM(s) (12 skipped): already-set=3, attach=17, hold-change=3
  DRY-RUN: 17 native tag(s) would be attached via the VCENTER_* identity. Re-run with --execute; to land on Supervisor-managed VMs, re-run with --actuate-as-tag-authority.
```
