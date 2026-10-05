# Expected output: log_paths.py

Runs of the log harness against the reference estate, with every estate value replaced by a placeholder as in the
record beside this file (`records/log-paths.record.json`). Counts and versions are this estate's; the shape is what
any 9.1 estate returns. The three runs are the same check before the repair, after it, and over a window that
reaches back before the stop, which is how a zero is read as a finding rather than a broken query.

## `log_paths.py --verify-sources` (last 60 minutes)

```
read at 2026-10-04T18:02:44Z
  collector UNIFIED_CLOUD_PROXY  data persistence True
  collector UNIFIED_CLOUD_PROXY  data persistence True
  collector INTERNAL             data persistence False
  9 of 59 adapter instances carry LOG_COLLECTION:
    NSXTAdapter          CLOUD_PROXY  x3
    SupervisorAdapter    CLOUD_PROXY  x1
    VMWARE               CLOUD_PROXY  x3
    VcfAdapter           DIRECT       x2
  OPS      deployment OVA, 9.1.1.0.25679751, size medium, 3 node(s) listed
  OPS_LOGS deployment VSP, 9.1.1.0.25679624, size small, 0 node(s) listed
  source proof, last 60 min: 0 of 11 ESX hosts delivered their own logs
    {{esx-1}}            own events      0  via -
    {{esx-2}}            own events      0  via -
    {{esx-3}}            own events      0  via -
    {{esx-4}}            own events      0  via -
    {{esx-5}}            own events      0  via -
    {{esx-6}}            own events      0  via -
    {{esx-7}}        own events      0  via -
    {{esx-8}}        own events      0  via -
    {{esx-9}}        own events      0  via -
    {{esx-10}}        own events      0  via -
    {{esx-11}}        own events      0  via -
  record: ./log-paths.record.json
```

## `log_paths.py --verify-sources` after the repair (last 60 minutes, 2026-10-05)

The same check after the log collection configuration was set to TLS on every live vCenter (the internal
`log-collection` chapter, Plate 05; the case study `docs/case-studies/esx-logs-silent-at-a-tls-listener.md`). The
host at zero is down for an unrelated reason; every other host delivers its own logs through its proxy.

```
read at 2026-10-05T01:24:40Z
  collector UNIFIED_CLOUD_PROXY  data persistence True
  collector UNIFIED_CLOUD_PROXY  data persistence True
  collector INTERNAL             data persistence False
  9 of 59 adapter instances carry LOG_COLLECTION:
    NSXTAdapter          CLOUD_PROXY  x3
    SupervisorAdapter    CLOUD_PROXY  x1
    VMWARE               CLOUD_PROXY  x3
    VcfAdapter           DIRECT       x2
  OPS      deployment OVA, 9.1.1.0.25679751, size medium, 3 node(s) listed
  OPS_LOGS deployment VSP, 9.1.1.0.25679624, size small, 0 node(s) listed
  source proof, last 60 min: 10 of 11 ESX hosts delivered their own logs
    {{esx-1}}            own events  15972  via {{collector-host-1}}
    {{esx-2}}            own events  22152  via {{collector-host-1}}
    {{esx-3}}            own events      0  via -
    {{esx-4}}            own events  14886  via {{collector-host-1}}
    {{esx-5}}            own events  14603  via {{collector-host-1}}
    {{esx-6}}            own events  11641  via {{collector-host-1}}
    {{esx-7}}        own events   6536  via {{collector-host-2}}
    {{esx-8}}        own events   8186  via {{collector-host-2}}
    {{esx-9}}        own events  13226  via {{collector-host-1}}
    {{esx-10}}        own events  21217  via {{collector-host-1}}
    {{esx-11}}        own events  13778  via {{collector-host-1}}
  record: ./log-paths.record.json
```

## `log_paths.py --verify-sources --minutes 4320` (3 days, reaching back before the stop)

The same check passes over a window that includes the days before the hosts' own logs stopped, which is how a
reader knows the zero above is a finding and not a broken query.

```
  source proof, last 4320 min: 11 of 11 ESX hosts delivered their own logs
    {{esx-1}}            own events  40051  via {{collector-host-1}}
    {{esx-2}}            own events  30701  via {{collector-host-1}}
    {{esx-3}}            own events  37412  via {{collector-host-1}}
    {{esx-4}}            own events  27887  via {{collector-host-1}}
    {{esx-5}}            own events  37276  via {{collector-host-1}}
    {{esx-6}}            own events  25685  via {{collector-host-1}}
    {{esx-7}}        own events  36602  via {{collector-host-2}}
    {{esx-8}}        own events  29111  via {{collector-host-2}}
    {{esx-9}}        own events  40134  via {{collector-host-1}}
    {{esx-10}}        own events  32360  via {{collector-host-1}}
    {{esx-11}}        own events  34373  via {{collector-host-1}}
```
