# Expected output

One run of each script on the reference instance (VCF Operations 9.1.0, proven 2026-09-15). Names
and identifiers are replaced with placeholders; your adapters, VMs, figures, and UUIDs will differ.

## collection_planes.py

```
$ python3 collection_planes.py
COLLECTION PLANES - read 2026-09-15 01:03 UTC

  plane 1 · the vCenter adapters (pull, through vStats where enabled)
  adapter                        interval  vStats  sample   metrics  objects
  --------------------------------------------------------------------------
  vcenter-workload-01               5 min    true    20 s      7212      210
  vcenter-secondary-01              5 min    true    20 s      2603       40
  vcenter-management-01             5 min    true    20 s      9610      143
  the interval is the stored cadence; the sample is the vStats rate the adapter averages
  into it. Neither depends on the vCenter statistics level.

  plane 2 · the store's retention (global settings)
  setting                                      configured  default   meaning
  ----------------------------------------------------------------------------------
  TIME_SERIES_DATA_RETENTION_IN_MONTHS                  6        6   5-minute data kept for
  ROLLUP_TIME_SERIES_DATA_RETENTION_IN_MONTHS          36       36   hourly roll-ups kept for
  REALTIME_DATA_RETENTION_IN_DAYS                      15       15   real-time metrics kept for
  ESX_TOP_DATA_RETENTION_IN_HOURS                      24       24   2-second ESX Top kept for
  DELETED_OBJECTS_RETENTION_IN_HOURS                  168      168   deleted objects linger for
  OBJECT_HISTORY_RETENTION_IN_DAYS                     90       90   object history kept for

  plane 3 · the ruler: 'Default Policy', cluster allocation model
    cpu overcommit ratio              4.0
    memory overcommit ratio           1.0
    disk overcommit ratio             2.0
    powered-off VMs counted           False
    inherited from a parent policy    False

  capacity runway rides this allocation model; rightsizing rides demand. Confirm the
  model per cluster before trusting either number.

  every retention key sits at its product default; the sheet's figures apply as written.
```

Exit code 0. A tuned retention value prints `TUNED` beside it and the exit code is 1.

## rollup_check.py

```
$ python3 rollup_check.py
ROLL-UP CHECK - vm-busy-01, cpu|usagemhz_average, last 3 hours, read 2026-09-15 01:05 UTC

  native points: 36, spacing 300 to 302 s (median 300 s)
  explicit 5-minute buckets: 36 common timestamps; MIN and MAX equal AVG at 36 of them
  (one value per point survives the 20-second sampling; nothing inside a cycle is recoverable)

  hour bucket (end, UTC)         AVG  native mean       MAX  native max   result
  ------------------------------------------------------------------------------
  2026-09-14 23:59:59      16092.589    16092.589 17310.801   17310.801   exact
  2026-09-15 00:59:59      16747.472    16747.472 18109.268   18109.268   exact
  ------------------------------------------------------------------------------

  peak keys on this VM (13): the only within-cycle maxima kept at 5-minute cadence
    cpu|20_sec_peak_costopPct
    cpu|20_sec_peak_iowaitPct
    cpu|20_sec_peak_overlap
    cpu|20_sec_peak_readyPct
    cpu|peak_vcpu_ready
    cpu|peak_vcpu_usage
    mem|20_sec_peak_host_contentionPct
    net|20_sec_peak_packetsPerSec
    net|20_sec_peak_usage_average
    virtualDisk|20_sec_peak_totalLatency_average
    virtualDisk|peak_vDisk_iops
    virtualDisk|peak_vDisk_readLatency
    virtualDisk|peak_vDisk_writeLatency

  VERDICT: 2 of 2 full hourly buckets match the native points exactly;
  downsample on the server, and read peaks from the peak keys or the 20-second path.
```

Exit code 0. Buckets are end-stamped on the fixed grid, which is why they land on `:59:59`; a
partial bucket at the window's edge is skipped rather than judged.

## extract_measure.py

```
$ python3 extract_measure.py --vms 50
EXTRACTION COEFFICIENTS - read 2026-09-15 01:05 UTC, sequential calls

  call                                            points       bytes    secs    B/pt     pts/s
  --------------------------------------------------------------------------------------------
  1 VM x 1 key, 7 d, native 5-minute               2,012      59,868    0.63    29.8     3,219
  1 VM x 1 key, 7 d, hourly AVG (server-side)        169       5,753    0.84    34.0       201
  50 VMs x 4 keys, 1 d, native                    41,336   1,200,197    2.33    29.0    17,776  omitted 14 of 50 resources
  50 VMs x 4 keys, 1 d, hourly AVG                 3,600     135,880    0.93    37.7     3,876  omitted 14 of 50 resources
  --------------------------------------------------------------------------------------------

  sample VM: vm-busy-01. Latency has a fixed floor per call; batch wide rather than loop deep.
  An omitted resource had no data in the window: reconcile it against inventory and collector
  health, never land it as zero. These coefficients are inputs to your estimate, from your node.
```

Exit code 0. Bytes per point stay near 30 at either resolution; points per second rise with the
size of the call, which is the batch-wide rule in numbers. The fourteen omitted resources were
powered off or newly created in that window, not an error.

## identity_keys.py

```
$ python3 identity_keys.py --vm vm-example-01
IDENTITY KEYS - vm-example-01

  Operations identifier     value                                     part of uniqueness
  ----------------------------------------------------------------------------------
  VMEntityVCID              <vcenter-instance-uuid>                   yes
  VMEntityObjectID          vm-20081                                  yes
  VMEntityInstanceUUID      <vm-instance-uuid>                        no
  VMEntityName              vm-example-01                             no
  Operations resource id    <operations-resource-id>                  (internal to this instance)
  vCenter adapter VCURL     vcenter-management-01.example             (a name, resolves to the UUID above)

  composite key: (vcenter_instance_uuid, moid) = (<vcenter-instance-uuid>, vm-20081)
  Real-Time Metrics carries the moid as a label and the vCenter half only as the query's
  sourceId; the CMDB stores the same pair as vcenter_uuid and object_id (or morid).
  both halves present: key every row on this pair, and carry the instance UUID as an attribute.
```

Exit code 0.

## rtm_query.py

```
$ python3 rtm_query.py --source-id <vcenter-instance-uuid>
REAL-TIME METRICS QUERY - read 2026-09-15 06:25 UTC, service JWT minted for this run (35-minute lifetime)

  metrics config: ESX Top (2-second) on 5 host MOID(s) of this source (0.47 s)
  metadata: 175 metric names collected for this source (0.35 s)
    e.g. cpu.capacity.contention.HOST, cpu.capacity.contention.VM, cpu.capacity.usage.HOST, cpu.capacity.usage.VM, cpu.corecount.contention.HOST

  instant query cpu.utilization.PCORE: 101 series returned (0.56 s)
    labels: cluster, core, datacenter, feature, host, host_fqdn, host_ip, profile, provider, vc_ip
    object identity is the MOID label (vm, host, cluster, datacenter); the vCenter half
    is the sourceId you passed, so stamp every row with it.

  count by (profile): 288 series in the store
    ESX_TOP_ESXi_SPEC_2_ESSENTIAL_ESX_METRICS: 144
    TROUBLESHOOTING_ESXi_SPEC_20_ESSENTIAL_ESX_METRICS: 144
    the instant query returned 101 of 288 and warned 'Results truncated due to limit.':
    one call returns at most 101 series; read a large object set one host at a time
    (a label matcher such as {host="host-123"}), and treat the warning as an error in a pipeline.

  cadence, cpu.utilization.PCORE at step 2s over 3 minutes, first series per profile:
    ESX_TOP_ESXi_SPEC_2_ESSENTIAL_ESX_METRICS: 91 points, 86 value changes, 2 s between changes: the served cadence (0.82 s)
    TROUBLESHOOTING_ESXi_SPEC_20_ESSENTIAL_ESX_METRICS: 91 points, 9 value changes, 20 s between changes: the served cadence (0.73 s)

  contrast, range vector cpu.utilization.PCORE[3m]: 10 raw samples in the first series, spacing 20 to 20 s (0.59 s)
    a range vector returns the 20-second grid for every profile; it cannot show the 2-second data.
```

Exit code 0. A wrong `--source-id` returns a successful answer with no series and exit code 1.
The default metric is served under two acquisition profiles on purpose: the run shows the profile
split, the two cadences, and the 101-series ceiling in one read (three hosts of 48 cores here).
A metric under one profile prints one cadence line; a name that is idle in the window prints
"no value change" rather than a cadence, which is a fact about the object, not the store.
The metrics-config line counts the host MOIDs the 2-second set is switched on for; a MOID that no
longer exists in vCenter still counts (five listed here, three hosts present), so read it as the
configuration, not the inventory.
