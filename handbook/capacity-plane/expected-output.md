# What `capacity.py` prints

Run against one VCF Automation 9.1.1.0100 organization on 2026-10-19, signed in with a session login. The first
block is the read-only run; it ran after the probe below and carried the probe's section of the record forward.
Your figures will differ; the shapes should not.

```
capacity.py: the capacity plane, added up rather than described

  zones: 3; units as returned: cpu in M, memory in Mi
  a zone asked for by its own object name: HTTP 404; the list returned it
  projects: 2; namespaces: 5
     {{project-1}}    5 namespace(s); bindings: regions 0, classes 0, vpcs 0
     {{project-2}}    0 namespace(s); bindings: regions 0, classes 0, vpcs 0

  the ledger, per zone (cpu first, then memory and what is left):
     {{zone-1}}       3 namespace(s); zone reports 48000 used; limits sum to 48000, reservations to 1000: the sum of the namespaces' limits
                      memory: limits sum to 76384, zone reports 76384 used; left: cpu 12000M, memory 54688Mi; reservation drawn 1000 of 6000
     {{zone-2}}       1 namespace(s); zone reports 10000 used; limits sum to 10000, reservations to 0: the sum of the namespaces' limits
                      memory: limits sum to 12000, zone reports 12000 used; left: cpu 50000M, memory 119072Mi; reservation drawn 0 of 6000
     {{zone-3}}       1 namespace(s); zone reports 60000 used; limits sum to 60000, reservations to 0: the sum of the namespaces' limits
                      memory: limits sum to 120000, zone reports 120000 used; left: cpu 0M, memory 11072Mi; reservation drawn 0 of 6000

  the contract: 3 class(es), 4 config(s)
     fields where the namespace holds exactly what its class promised: 7 of 25 (2 namespace(s) omit storage and take the class config's limit)
       cpuLimit             same  1   above the class  1   below it  3
       cpuReservation       same  1   above the class  0   below it  4
       memoryLimit          same  2   above the class  1   below it  2
       memoryReservation    same  1   above the class  0   below it  4
       storageLimit         same  2   above the class  0   below it  3
     widest departure: class large, memoryLimit promised 40000, namespace holds 120000 (3.0 times)

  storage ledgers: 3; VM classes: 16, of which 0 require a reservation
     {{storageclass-1}}         capacity    6332764Mi (6.04 TiB)   consumed         0Mi (0.0 TiB)
     {{storageclass-2}}         capacity   18830489Mi (17.96 TiB)   consumed   1500000Mi (1.43 TiB)
     {{storageclass-3}}         capacity   18830489Mi (17.96 TiB)   consumed         0Mi (0.0 TiB)

  overrides: not probed; pass --probe-overrides --project <name> to ask the platform at create (it creates namespaces there and deletes them again)
  carrying forward 'overrides' from an earlier run with the probe flag; this run did not re-probe it and has not erased it

wrote capacity.json (3 zones, 5 namespaces, 7 of 25 contract fields agreeing); every organization name replaced by a placeholder
```

## What each block tells you

- **zones** and the line after it: how many zones the region publishes and the unit each figure arrives in, and
  what a get of one zone by its own object name answers. The list is how to find a zone.
- **projects**: each project with the namespaces it hosts and the region, class and VPC bindings it holds.
- **the ledger**: per zone, what the namespaces' limits and reservations sum to against what the zone reports
  used, for cpu and then memory, with what is left and how much of the reservation budget is drawn.
- **the contract**: how often a namespace holds exactly what its class config promised, field by field. A
  namespace that omits its storage block takes the config's limit and is counted as holding it.
- **storage ledgers** and **VM classes**: the region's per-storage-class ledgers, and how many published machine
  classes require a reservation.

## `--probe-overrides --project <name>`: which way a create may depart

The same day, with the operator's approval, into a project that held no namespace. Every namespace a create made
was deleted, the script waited until each was gone, and it read the zones again.

```
  overrides: asking a create in {{project-2}} which way it may depart from class small's config
     cpu limit above the class config                               HTTP 200  accepted, holds cpu 20000M, storage the class config; deleted
     cpu limit below the class config                               HTTP 200  accepted, holds cpu 5000M, storage the class config; deleted
     no override at all                                             HTTP 400  refused: Zone should be specified in Namespace or in Namespace class
     the zone named, but no numbers with it                         HTTP 422  refused: SupervisorNamespace.infrastructure.cci.vmware.com "probe-ovr-" is invalid: [spec.classConfigOverrides.zones[0].memoryLim
     storage below the class config                                 HTTP 200  accepted, holds cpu 10000M, storage 50000Mi; deleted
     storage above the class config                                 HTTP 400  refused: Requested storage limit 200000MiB for {{storageclass-2}} is more than available storage limit 100000MiB. Override limits
     the class config's figures, in a zone with no limit budget left HTTP 400  refused: Requested CPU limit of 10000MHz exceeds the available 0MHz. Override limits to reduce the requested value or change the
     the class config's figures, sent as a dry run                  HTTP 400  refused: dryRun value of "All" is not supported
     still tearing down after 120s (3 left); delete re-issued
     3 probe namespace(s) created and deleted; all gone 186s after the last create
     the zones read as they did before the first create
```

The first six cases are the ones the 9.1 probe of 2026-09-18 asked, and each answered with the same status; that
run's section of the record is kept in [`records/capacity-overrides-vcf-9.1.json`](records/capacity-overrides-vcf-9.1.json).
The last two are new: the class config's own figures in a zone with no limit budget left, and the same create
sent with `dryRun=All`.
