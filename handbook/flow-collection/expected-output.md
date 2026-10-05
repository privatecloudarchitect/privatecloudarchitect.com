# Expected output: flow_paths.py

A run of the flow harness against the reference estate, with every estate value replaced by a placeholder as in
the record beside this file (`records/flow-paths.record.json`). Counts and versions are this estate's; the shape is
what any 9.1 estate returns.

## `flow_paths.py` (2026-10-05)

The hour's flows counted by the host each endpoint runs on, joined to each distributed switch's member hosts. A
flow names where its endpoints run, never the host that exported it, so a host at zero has no named workloads: it
may export nothing, or Operations for Networks may be unable to name its VMs. The collector's exporter list tells
the two apart (README, "What it does not cover"). On this estate six hosts read zero; in the same hour the
collector heard four of them, one host was down, and one sends nothing.

```
read at 2026-10-05T02:18:53Z
  node PROXY_VM   9.1.1.0.25682214  health HEALTHY  physical flow collector False
  5 data sources over 1 collector(s)
    VCenterDataSource      IPFIX: {{switch-moid-1}}
    VCenterDataSource      IPFIX: {{switch-moid-2}}
    VCenterDataSource      IPFIX: {{switch-moid-3}}
    NSXTManagerDataSource  IPFIX: False
    NSXTManagerDataSource  IPFIX: True
  flows in the last hour: 1476
  flows read for the host tally: 1476, naming an endpoint on 7 host(s), 353 naming no host
  NSX IPFIX profiles: {'ipfix-l2-collector-profiles': 0, 'ipfix-dfw-collector-profiles': 0, 'ipfix-l2-profiles': 0, 'ipfix-dfw-profiles': 0}
  NSX IPFIX profiles: {'ipfix-l2-collector-profiles': 1, 'ipfix-dfw-collector-profiles': 0, 'ipfix-l2-profiles': 1, 'ipfix-dfw-profiles': 0}
  switch: collector set True, port 2055, sampling 0, 6 of 31 port groups exporting (0 uplink)
    hosts, by flows naming an endpoint there: {{esx-3}} 252, {{esx-1}} 588, {{esx-2}} 281
  switch: collector set True, port 2055, sampling 0, 3 of 29 port groups exporting (0 uplink)
    hosts, by flows naming an endpoint there: {{esx-4}} 101, {{esx-5}} 101
  switch: collector set False, port 0, sampling 4096, 0 of 26 port groups exporting (0 uplink)
    hosts, by flows naming an endpoint there: {{esx-8}} 0, {{esx-9}} 0
  switch: collector set False, port 0, sampling 4096, 0 of 26 port groups exporting (0 uplink)
    hosts, by flows naming an endpoint there: {{esx-10}} 0, {{esx-11}} 0
  switch: collector set True, port 2055, sampling 0, 4 of 13 port groups exporting (0 uplink)
    hosts, by flows naming an endpoint there: {{esx-12}} 0, {{esx-13}} 0
  record: ./flow-paths.record.json
```
