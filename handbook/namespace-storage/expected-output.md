# What `ledgers.py` prints

Run against one VCF Automation 9.1.1.0100 organization on 2026-10-19 with all four credentials: a session login
for the tenant, a provider bearer, and a vCenter sign-in to the vCenter behind the Supervisor. Your figures will
differ; the shapes should not.

```
ledgers.py: every plane that will answer how much storage is used

  TENANT CLAIMED        451,584 MiB (  0.43 TiB)  from 27 volume claim(s) in 5 of 5 namespace(s)
  TENANT GRANTED      1,500,000 MiB (  1.43 TiB)  the quota ledger's own figure
     the namespaces' storage limits sum to 1,500,000 MiB (2 of 5 at their class config's), so the quota ledger is counting the namespaces' storage limits
  PROVIDER ALLOC     46,240,787 MiB (  44.1 TiB)  largest of 3 class(es); 1 report the capacity of another class, consumption within 2,048 MiB of it, so these do not add up
     class capacity  5,053,879 consumed  16,456,172 ratio 3.256 zones 3
     class capacity 13,704,125 consumed  46,240,787 ratio 3.374 zones 3
     class capacity 13,704,125 consumed  46,238,739 ratio 3.374 zones 3
  PHYSICAL              855,399 MiB (  0.82 TiB) used of 17.89 TiB across 4 datastore(s), types NFS

  each plane's percentage, both halves from that plane:
     tenant    {{storageclass-2}}      1,500,000 of   18,830,489 MiB  8.0%
     provider  {{storageclass-2}}     46,240,787 of   13,704,125 MiB  337.4%
     physical  every datastore           855,399 of   18,758,003 MiB  4.6%

  4 answers to one question, spanning 102.4 times: tenantClaimed 0.43 TiB, tenantGranted 1.43 TiB, providerAllocation 44.1 TiB, physicalUsed 0.82 TiB

wrote out/ledgers.json (4 ledger(s) reached); every organization name replaced by a placeholder
```

## What each block tells you

- **TENANT CLAIMED** and **TENANT GRANTED**: what the volume claims ask for, read at each namespace's own
  endpoint, and the quota ledger's figure, with the check between them: the namespaces' storage limits summed
  (a namespace that sets none at its class config's limit) and the sum the quota figure equals.
- **PROVIDER ALLOC**: the provider plane's consumption, the largest single class, every class with its ratio of
  consumption to capacity and its zone count. Classes that report the same capacity read as one pool seen twice.
- **PHYSICAL**: what every datastore in that vCenter holds, used against capacity.
- **each plane's percentage**: used against capacity with both halves from one plane.
- **answers to one question**: the four figures side by side and the multiple between the smallest and largest.

## `--compare`: the weekly check

The same run a minute later with `--compare records/ledgers-vcf-9.1.json`, the 9.1 record of 2026-09-21 kept in
this folder. Each ledger is set as a multiple of the quota figure, then and now; a move of more than a tenth is
marked, and the run exits 1.

```
  compared with the record of 2026-09-21T07:58:26Z, each ledger as a multiple of the quota figure:
     tenantClaimed            0.57 then,     0.30 now  (-47%)  MOVED
     providerAllocation      40.96 then,    30.83 now  (-25%)  MOVED
     physicalUsed             0.83 then,     0.57 now  (-31%)  MOVED

wrote compare-out/ledgers.json (4 ledger(s) reached); every organization name replaced by a placeholder
```
