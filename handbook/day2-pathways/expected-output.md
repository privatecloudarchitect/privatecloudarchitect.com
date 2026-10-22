# Expected output

What `pathways.py` printed on the reference estate at 2026-10-22T01:16:11Z: VCF 9.1.1, one organization, signed in with a session login, read-only (no `--probe-pathways`). It exited 1 for the two tombstones. Every estate name is a placeholder.

```
$ python3 pathways.py
pathways.py: the same Day-2 change through each plane, and what stays true

  DRIFT AUDIT: 3 machine(s) claimed by a deployment
     1 where the record's manifest, its cached object and the live machine all agree
     2 whose object is gone, which syncStatus does report
     0 where the machine no longer matches the manifest AND syncStatus says nothing,
        of which 0 are provable from the record alone, with no Supervisor read
       {{machine-1}}    sync=MISSING  object gone
       {{machine-2}}    sync=MISSING  object gone
       {{machine-3}}    sync=None     agrees

  THE CONTRACT against what this estate shows:
     Deployment.status      seen {'DELETE_SUCCESSFUL': 2, 'CREATE_SUCCESSFUL': 2}
                            documented but never seen here: CREATE_INPROGRESS, CREATE_FAILED, UPDATE_SUCCESSFUL, UPDATE_INPROGRESS, UPDATE_FAILED, DELETE_INPROGRESS, DELETE_FAILED
     resource.syncStatus    seen {'MISSING': 2, 'SUCCESS': 5, None: 1}
                            documented but never seen here: STALE
     resource.state         seen {'OK': 8}
                            documented but never seen here: PARTIAL, TAINTED
     resource.origin        seen {'DEPLOYED': 8}
                            documented but never seen here: DISCOVERED, ONBOARDED, MIGRATED, SIMULATED, CCS

  TOMBSTONES: 2 deployment(s) report DELETE_SUCCESSFUL and still hold a resource
     {{deployment-1}} resources still listed: 1 ['MISSING']
     {{deployment-2}} resources still listed: 1 ['MISSING']
     These cannot be retired through this API. Plate 05 documents the sequence that makes one.

  probe: not run (pass --probe-pathways to make the same change through each pathway)
```

`records/pathways-2026-09-21.json` is the probe run of 2026-09-21 on VCF 9.1: one machine built, changed through each pathway and timed, deleted three ways, and given two disks before a delete.
