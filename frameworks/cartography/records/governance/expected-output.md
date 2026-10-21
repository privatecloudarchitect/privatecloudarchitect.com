# What the governance runs printed on the reference estate

Run on 2026-10-21 against VCF Automation 9.1.1.0100 and the workload domain's vCenter (vCenter 9.1.1.0.25712839), each
password read from a file of mode 0600. File paths are shortened to the file's name; nothing else is changed except
where a note marks a change. The records each run wrote are beside this file.

## Read-only: the ratification queue and the backlog

`python3 classify_supervisor.py --project <project> --export recs.json --record classify.json`, then
`CARTOGRAPHY_TAXONOMY=<the estate's taxonomy> python3 writeback_tags.py --recommendations recs.json --coverage --record coverage.json`.
Only the classifier's summary lines are shown: the queue table below them names the estate's machines. The coverage
read used the estate's own category names, the namespaced form `taxonomy.yaml` describes.

```text
supervisor lens · 3 namespace(s), 11 VM(s): 9 tag-ready, 2 held (no signal)
  recommendations: 11 safe to approve, 11 flagged for confirmation  {'app': 3, 'env': 7, 'function': 9, 'tier': 3}
wrote classify.json (counts only)
coverage · 11 workload(s) walked (2 held, no signal); 9 found on this vCenter
  governed categories defined here: 2 of 4
    identity.app                         9 of 9
    identity.app-layer                   0 of 9
    identity.function                    9 of 9
    lifecycle.env-observed               0 of 9
  with any governed tag 9, with every one 0; unclassified backlog 2
wrote coverage.json (counts only)
```

## The round trip, on one throwaway VM

The VM was made for the run with labels the classifier reads (part-of `cartography-probe`, component `database`) and
deleted afterwards; the approve file named only its four rows. The categories did not exist before the run, which
created and then deleted them.

`python3 writeback_tags.py --recommendations recs.json --approve-file approve.txt --actuate-as-tag-authority --execute --record writeback.json`

```text
write-back · EXECUTE · 4 approved recommendation(s) from recs.json
  DEFINE (vCenter-native):
    app                                  create
    app-layer                            create        +3 (presentation,logic,data)
    env-observed                         create        +6 (prod,stage,dev,test,dr,lab)
    function                             create        +6 (db,web,app,vdi,k8s,infra)
  VM                           CATEGORY         VALUE            CURRENT      ACTION
  ---------------------------- ---------------- ---------------- ------------ --------------------------
  cartography-probe-vm         app              cartography-prob -            attach APPLIED (verified in vCenter)
  cartography-probe-vm         app-layer        data             -            attach APPLIED (verified in vCenter)
  cartography-probe-vm         env-observed     dev              -            attach APPLIED (verified in vCenter)
  cartography-probe-vm         function         db               -            attach APPLIED (verified in vCenter)
  summary: 4 decision(s) over 1 resolvable VM(s) (0 skipped): attach=4
  Applied 4 native tag(s), each verified against the vCenter source of truth. Group re-resolution then settles on its own interval (minutes).
wrote writeback.json (counts only)
```

`python3 writeback_tags.py --probe-tag-authority-define --record define-probe.json`

```text
define as the tag authority: HTTP 403, refused, as the split says; absent afterwards: True
wrote define-probe.json (counts only)
```

`python3 writeback_tags.py --recommendations recs.json --approve-file approve.txt --actuate-as-tag-authority --teardown --remove-categories --execute --record teardown.json`

```text
TEARDOWN · EXECUTE · 4 approved recommendation(s) from recs.json
  VM                           CATEGORY         VALUE            CURRENT      ACTION
  ---------------------------- ---------------- ---------------- ------------ --------------------------
  cartography-probe-vm         app              cartography-prob cartography-probe DETACHED (verified gone)
  cartography-probe-vm         app-layer        data             data         DETACHED (verified gone)
  cartography-probe-vm         env-observed     dev              dev          DETACHED (verified gone)
  cartography-probe-vm         function         db               db           DETACHED (verified gone)
  CATEGORIES (this framework's only):
    app                                  delete
    app-layer                            delete
    env-observed                         delete
    function                             delete
  summary: 4 decision(s) over 1 resolvable VM(s) (0 skipped): detach=4
  Detached 4 native tag(s), each verified gone from the vCenter source of truth. The tag categories and values remain defined (estate vocabulary).
wrote teardown.json (counts only)
```

Note: the closing sentence of that teardown summary said the categories "remain defined", which the CATEGORIES block
above it contradicts; the script has since been corrected to say they were deleted when `--remove-categories` ran.
