# Expected output: flow_paths.py

A run of the flow harness against the reference estate, with every estate value replaced by a placeholder as in
the record beside this file (`records/flow-paths.record.json`). Counts and versions are this estate's; the shape is
what any 9.1 estate returns.

## `flow_paths.py` (2026-10-05)

The hour's flows counted by the host they were observed on, joined to each distributed switch's member
hosts. A host at zero on a switch without the collector is the blind spot the chapter's Plate 04 describes.

```
read at 2026-10-05T01:25:09Z
  node PROXY_VM   9.1.1.0.25682214  health HEALTHY  physical flow collector False
  5 data sources over 1 collector(s)
    VCenterDataSource      IPFIX: {{switch-moid-1}}
    VCenterDataSource      IPFIX: {{switch-moid-2}}
    VCenterDataSource      IPFIX: {{switch-moid-3}}
    NSXTManagerDataSource  IPFIX: False
    NSXTManagerDataSource  IPFIX: True
  flows in the last hour: 1459
  flows read for the host tally: 1459, observed on 7 host(s), 342 with no host
  NSX IPFIX profiles: {'ipfix-l2-collector-profiles': 0, 'ipfix-dfw-collector-profiles': 0, 'ipfix-l2-profiles': 0, 'ipfix-dfw-profiles': 0}
  NSX IPFIX profiles: {'ipfix-l2-collector-profiles': 1, 'ipfix-dfw-collector-profiles': 0, 'ipfix-l2-profiles': 1, 'ipfix-dfw-profiles': 0}
  switch: collector set True, port 2055, sampling 0, 6 of 31 port groups exporting (0 uplink)
    hosts: {{esx-3}} 249 flows, {{esx-2}} 588 flows, {{esx-1}} 275 flows
  switch: collector set True, port 2055, sampling 0, 3 of 29 port groups exporting (0 uplink)
    hosts: {{esx-4}} 101 flows, {{esx-5}} 101 flows
  switch: collector set False, port 0, sampling 4096, 0 of 26 port groups exporting (0 uplink)
    hosts: {{esx-8}} 0 flows, {{esx-9}} 0 flows
  switch: collector set False, port 0, sampling 4096, 0 of 26 port groups exporting (0 uplink)
    hosts: {{esx-10}} 0 flows, {{esx-11}} 0 flows
  switch: collector set True, port 2055, sampling 0, 4 of 13 port groups exporting (0 uplink)
    hosts: {{esx-12}} 0 flows, {{esx-13}} 0 flows
  record: ./flow-paths.record.json
```
