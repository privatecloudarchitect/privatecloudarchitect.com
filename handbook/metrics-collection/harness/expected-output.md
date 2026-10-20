# Expected output

One run of each script on the reference instance, on VCF Operations 9.1.1.0 (build 25679751) on 2026-10-19. Names and identifiers are
replaced with placeholders; your adapters, VMs, figures, and UUIDs will differ.

## collection_planes.py

```
$ python3 collection_planes.py
COLLECTION PLANES - read 2026-10-19 17:05 UTC

  plane 1 · the vCenter adapters (pull, through vStats where enabled)
  adapter                        interval  vStats  sample   metrics  objects
  --------------------------------------------------------------------------
  vcenter-management-01             5 min    true    20 s     10423      149
  vcenter-workload-01               5 min    true    20 s      8686      261
  vcenter-secondary-01              5 min    true    20 s      2622       42
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
ROLL-UP CHECK - vm-busy-01, cpu|usagemhz_average, last 3 hours, read 2026-10-19 17:05 UTC

  native points: 36, spacing 300 to 302 s (median 300 s)
  explicit 5-minute buckets: 36 common timestamps; MIN and MAX equal AVG at 36 of them
  (one value per point survives the 20-second sampling; nothing inside a cycle is recoverable)

  hour bucket (end, UTC)         AVG  native mean       MAX  native max   result
  ------------------------------------------------------------------------------
  2026-10-19 15:59:59      23785.700    23785.700 25031.000   25031.000   exact
  2026-10-19 16:59:59      24027.861    24027.861 25497.867   25497.867   exact
  ------------------------------------------------------------------------------

  peak keys on this VM (13): 20_sec_peak_* keep a within-cycle maximum; peak_* are the busiest instance's 5-minute average
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
EXTRACTION COEFFICIENTS - read 2026-10-19 18:22 UTC, sequential calls

  call                                            points       bytes    secs    B/pt     pts/s
  --------------------------------------------------------------------------------------------
  1 VM x 1 key, 7 d, native 5-minute               2,014      58,581    0.65    29.1     3,099
  1 VM x 1 key, 7 d, hourly AVG (server-side)        169       5,683    0.53    33.6       317
  50 VMs x 4 keys, 1 d, native                    46,042   1,336,658    0.91    29.0    50,758  omitted 10 of 50 resources
  50 VMs x 4 keys, 1 d, hourly AVG                 4,000     152,041    0.67    38.0     6,001  omitted 10 of 50 resources
  --------------------------------------------------------------------------------------------

  sample VM: vm-busy-01. Latency has a fixed floor per call; batch wide rather than loop deep.
  An omitted resource had no data in the window: reconcile it against inventory and collector
  health, never land it as zero. These coefficients are inputs to your estimate, from your node.
```

Exit code 0. Bytes per point stay near 30 at either resolution; points per second rise with the
size of the call, which is the batch-wide rule in numbers. An omitted resource had no data in the
window (powered off, or created inside it); the run reports it and never lands it as zero.

## topology.py

```
$ python3 topology.py
COLLECTION TOPOLOGY - read 2026-10-19 21:40 UTC

  collector                    type                 state  persist  heartbeat  adapters  kinds
  --------------------------------------------------------------------------------------------------------
  node-collector-01            INTERNAL             UP     off      4 s ago          10  ManagementPackBuilderAdapter 1, vCenter Operations Adapter 1, DiagnosticsAdapter 1, VMWARE_INFRA_MANAGEMENT 1 ...
                               the node's own adapters: Container, DiagnosticsAdapter, ManagementPackBuilderAdapter, OrchestratorAdapter, PingAdapter, SERVICENOW_ADAPTER, VMWARE_INFRA_HEALTH, VMWARE_INFRA_MANAGEMENT, vCenter Operations Adapter, vRealizeOpsMgrAPI
  proxy-site-b-01              UNIFIED_CLOUD_PROXY  UP     on       15 s ago         13  LogAssistAdapter 1, VMWARE_INFRA_HEALTH 1, APPOSUCP 1, NSXTAdapter 1 ...
  proxy-site-a-01              UNIFIED_CLOUD_PROXY  UP     on       7 s ago          35  VMSP 2, NSXTAdapter 2, VMWARE_INFRA_MANAGEMENT 2, VirtualAndPhysicalSANAdapter 2 ...

  collector group                  members  HA   LB   system-defined
  ----------------------------------------------------------------
  Default collector group                1  off  off  yes
  Example Collector Group                0  off  off  no
  site-b collector group                 1  off  off  no
  site-a collector group                 1  off  off  no

  note: proxy proxy-site-b-01 has no partner in a group: no failover (a choice, not a defect)
  note: proxy proxy-site-a-01 has no partner in a group: no failover (a choice, not a defect)
  every proxy is up with persistence on, and the node's own collector holds no vCenter, NSX or vSAN adapter:
  the documented per-site pattern. A link outage under an hour is buffered; past it, the gap is real.
```

Exit code 0. Every proxy is up with persistence on, and the node's own collector runs only the platform's own
adapters (health, management, the integrations it hosts), none of them vCenter, NSX or vSAN. Each proxy is alone in its
group, so a site has no failover: that prints as a note and leaves the exit code at 0, because a second proxy and a 10-minute
failover are a choice. A proxy with persistence off, a proxy that is down, or a site adapter on the node's collector
prints FINDING and exits 1; a refused or short read exits 4.

## identity_keys.py

```
$ python3 identity_keys.py --vm vm-example-01
IDENTITY KEYS - vm-example-01

  Operations identifier     value                                     part of uniqueness
  ----------------------------------------------------------------------------------
  VMEntityVCID              <vcenter-instance-uuid>                   yes
  VMEntityObjectID          vm-20066                                  yes
  VMEntityInstanceUUID      <vm-instance-uuid>                        no
  VMEntityName              vm-example-01                             no
  Operations resource id    <operations-resource-id>                  (internal to this instance)
  vCenter adapter VCURL     vcenter-management-01.example             (a name, resolves to the UUID above)

  composite key: (vcenter_instance_uuid, moid) = (<vcenter-instance-uuid>, vm-20066)
  Real-Time Metrics carries the moid as a label and the vCenter half only as the query's
  sourceId; the CMDB stores the same pair as vcenter_uuid and object_id (or morid).
  both halves present: key every row on this pair, and carry the instance UUID as an attribute.
```

Exit code 0.

## rtm_query.py

```
$ python3 rtm_query.py --source-id <vcenter-instance-uuid>
REAL-TIME METRICS QUERY - read 2026-10-19 18:22 UTC, service JWT minted for this run (35-minute lifetime)

  metrics config: ESX Top (2-second) on 5 host MOID(s) of this source (0.40 s)
  metadata: 175 metric names collected for this source (0.41 s)
    e.g. cpu.capacity.contention.HOST, cpu.capacity.contention.VM, cpu.capacity.usage.HOST, cpu.capacity.usage.VM, cpu.corecount.contention.HOST

  instant query cpu.utilization.PCORE: 101 series returned (0.55 s)
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
    ESX_TOP_ESXi_SPEC_2_ESSENTIAL_ESX_METRICS: 91 points, 88 value changes, 2 s between changes: the served cadence (0.83 s)
    TROUBLESHOOTING_ESXi_SPEC_20_ESSENTIAL_ESX_METRICS: 91 points, 9 value changes, 20 s between changes: the served cadence (0.75 s)

  contrast, range vector cpu.utilization.PCORE[3m]: 10 raw samples in the first series, spacing 20 to 20 s (0.60 s)
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
