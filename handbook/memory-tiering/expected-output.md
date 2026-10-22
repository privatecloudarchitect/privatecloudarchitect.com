# Expected output: candidacy.py

A run against the reference estate on 2026-10-22 (VCF Operations 9.1.1, every host on ESX 9.1.1), the run that wrote
`candidacy.json` beside this file. Hosts are numbered by consumption rank; the script reads no host, cluster or
instance name. Counts and percentages are this estate's; the shape is what any 9.1 instance returns.

```
$ python3 candidacy.py --days 60
candidacy.py: the memory-tiering lens, run against your own hosts

  hosts listed: 11; measured: 11

  CANDIDACY: 11 of 11 host(s) sit under the 50 percent gate
  READINESS: 1 of 11 host(s) are at or past the 80 percent trigger
  TIER:      2 of 11 host(s) have an NVMe tier configured
    host  1 TIER  active  15.1%  consumed  65.8%  cold   356.6 GiB  tier 175.8 GiB (ratio 1:0.25)
    host  2       active   7.8%  consumed  59.4%  cold   395.3 GiB
    host  3 TIER  active  17.4%  consumed  87.3%  cold   312.6 GiB  tier 447.4 GiB (ratio 1:1)
    host  4       active  14.1%  consumed  69.3%  cold    70.7 GiB
    host  5       active  15.6%  consumed  52.7%  cold    47.5 GiB
    host  6       active   6.0%  consumed  40.3%  cold    43.8 GiB
    host  7       active   8.5%  consumed  43.7%  cold    33.8 GiB
    host  8       active   6.0%  consumed  28.0%  cold    28.2 GiB
    host  9       active   4.5%  consumed  25.7%  cold    27.1 GiB
    host 10       active   2.5%  consumed  11.6%  cold    11.6 GiB
    host 11       active   1.2%  consumed   8.9%  cold     9.8 GiB
    ESX versions: 9.1.1-25714478 on 11

  DENOMINATOR: recomputing candidacy against total capacity instead of the DRAM tier
    on a host WITH a tier:    -48.0% to -16.4%  (the total counts the tier: understates)
    on a host WITHOUT a tier: +5.4% to +29.4%  (the total is net of overhead: overstates)
    the error CHANGES SIGN at activation, so a single correction factor cannot fix it

  USE: of 2 host(s) with a tier configured, 1 read zero on all 5 NVMe-side counters right now, and 2 carry live DRAM-side traffic
    host  1 (1:0.25): no page in the tier on any of 46 days; 2 day(s) at or past the 80 trigger, peak consumption 84.4% of DRAM; 4 of 12999 five-minute samples (0.0%) at or past the trigger
    host  3 (1:1): pages in the tier on 22 of 46 days, first on 2026-10-01; peak 147.9 GiB on 2026-10-06, 28.9 GiB on the last day
      before the first page: 22 day(s) at or past the 80 trigger, peak consumption 90.0% of DRAM; 6421 of 7180 five-minute samples (89.4%) before the first page at or past the trigger
      first five-minute sample with pages: 2026-10-01T23:29Z, 19.5 GiB in the tier, consumption 82.3% of DRAM (the sample before: 69.5%)
    host  1: consumed 65.8% of DRAM; DRAM tier 462.7 GiB + NVMe tier 0.0 GiB differs from consumed by 0.02%; DRAM alone is 65.8% of DRAM
    host  3: consumed 87.3% of DRAM; DRAM tier 385.6 GiB + NVMe tier 4.8 GiB differs from consumed by 0.0%; DRAM alone is 86.2% of DRAM

  SURFACE: 6 mem key(s) are on every host with a tier and on none of the 9 without one
    mem:NVMe|bandwidth.read_latest
    mem:NVMe|bandwidth.write_latest
    mem:NVMe|latency.read_latest
    mem:NVMe|latency.write_latest
    mem:NVMe|memory_tier_size
    mem:NVMe|tier.usage
    not a detector: mem:DRAM|bandwidth.read_latest is also on 1 of the 9 untiered host(s)
    not a detector: mem:DRAM|bandwidth.write_latest is also on 1 of the 9 untiered host(s)
    not a detector: mem:DRAM|latency.read_latest is also on 1 of the 9 untiered host(s)
    not a detector: mem:DRAM|latency.write_latest is also on 1 of the 9 untiered host(s)
    not a detector: mem:DRAM|tier.usage is also on 7 of the 9 untiered host(s)
    mem:NVMe|memory_tier_total_capacity is present on 11 host(s) and non-zero on 2, reading [745.2] GiB on the tiered ones: compare that with their tier sizes above before reading it as the tier
    mem|guest_demand: on a VM True, on a host False; mem:DRAM|memory_tier_total_capacity: on a VM False, on a host True

wrote candidacy.json; hosts are numbered by consumption rank and no name is recorded
```

## Reading it

- `measured` counts the hosts the lens read. A host whose resource an adapter reports as NOT_EXISTING, or with no
  consumption sample in the last hour, is skipped and counted under its reason, because a removed host keeps its last
  values.
- `46 days` is how many daily maxima the instance held in the 60-day window asked for. A daily maximum past the
  trigger can be one spike; the five-minute share beside it says whether the host stayed there.
- `differs from consumed by` compares host consumed memory with the DRAM tier's usage plus the NVMe tier's. Near zero
  means consumed counts the pages held on NVMe too, which is why consumed as a percent of DRAM can pass 100 on a host
  whose tier holds pages, and why `DRAM alone` is the readiness figure on such a host.
- `not a detector` lists keys found on the hosts with a tier and also on some without one, so their presence does not
  say a tier is configured.
