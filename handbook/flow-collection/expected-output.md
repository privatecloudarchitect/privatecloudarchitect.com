# Expected output: flow_paths.py and exporters.py

A run of each script against the reference estate, with every estate value replaced by a placeholder as in the
records beside this file (`records/flow-paths.record.json`, `records/exporters.record.json`). Counts and versions are
this estate's; the shape is what any 9.1 estate returns. Each script keeps its own placeholders, so `{{esx-3}}` in
one run is not the same host as `{{esx-3}}` in the other.

## `flow_paths.py` (2026-10-22)

Every source is VCF-managed, so every change goes through VCF Operations. The workload NSX exports through the
distributed firewall's IPFIX (observation domain 38416); the management NSX exports nothing. Four switches carry the
collector; the fifth carries none and exports on no port group, so every host on it is a blind spot. Four hosts on
switches that carry the collector read zero in the tally: the platform does not hold them in its inventory, so it
cannot name their workloads, although they export (the exporter run below shows them).

```
read at 2026-10-22T04:35:25Z
  node PROXY_VM   9.1.1.0.25682214  health HEALTHY  physical flow collector False
  5 data sources over 1 collector(s)
    VCenterDataSource      IPFIX: {{switch-moid-1}}; VCF-managed: True
    VCenterDataSource      IPFIX: None; VCF-managed: True
    VCenterDataSource      IPFIX: {{switch-moid-2}}, {{switch-moid-3}}, {{switch-moid-4}}; VCF-managed: True
    NSXTManagerDataSource  IPFIX: False; VCF-managed: True
    NSXTManagerDataSource  IPFIX: True; VCF-managed: True
  flows in the last hour: 1482
  flows read for the host tally: 1482, naming an endpoint on 7 host(s), 132 naming no host
  NSX IPFIX in use: none; profiles {'ipfix-l2-collector-profiles': 0, 'ipfix-dfw-collector-profiles': 0, 'ipfix-l2-profiles': 0, 'ipfix-dfw-profiles': 0}
  NSX IPFIX in use: none; profiles {'ipfix-l2-collector-profiles': 0, 'ipfix-dfw-collector-profiles': 0, 'ipfix-l2-profiles': 0, 'ipfix-dfw-profiles': 0}
  NSX IPFIX in use: distributed firewall, observation domain 38416; profiles {'ipfix-l2-collector-profiles': 0, 'ipfix-dfw-collector-profiles': 1, 'ipfix-l2-profiles': 0, 'ipfix-dfw-profiles': 1}
  switch: collector set True, port 2055, sampling 0, 6 of 31 port groups exporting (0 uplink)
    hosts, by flows naming an endpoint there: {{esx-3}} 395, {{esx-1}} 347, {{esx-2}} 596
  switch: collector set True, port 2055, sampling 0, 4 of 32 port groups exporting (0 uplink)
    hosts, by flows naming an endpoint there: {{esx-4}} 66, {{esx-5}} 134
  switch: collector set True, port 2055, sampling 0, 3 of 28 port groups exporting (0 uplink)
    hosts, by flows naming an endpoint there: {{esx-8}} 0, {{esx-9}} 0
  switch: collector set True, port 2055, sampling 0, 3 of 28 port groups exporting (0 uplink)
    hosts, by flows naming an endpoint there: {{esx-10}} 0, {{esx-11}} 0
  switch: collector set False, port 0, sampling 0, 0 of 13 port groups exporting (0 uplink)
    hosts, by flows naming an endpoint there: {{esx-12}} 0, {{esx-13}} 0
  record: ./flow-paths.record.json
```

## `exporters.py --redact` (2026-10-22)

The collector's own view of the hour. Every workload host sends switch IPFIX under domain 0, and two of them also send
the distributed firewall's under 38416; the other four are registered under 38416 and sent nothing there in the hour.
Domain 38417, the switch profile NSX used before it moved to the firewall's, is registered and silent. The two hosts
of the switch without a collector sent nothing at all. Every switch exporter shows sequence failures; the NSX
profile's show none.

```
read at 2026-10-22T04:38:10Z: 60 minute files on the collector, nfcapd.202610220338 to nfcapd.202610220437
  {{esx-8}}: domain 0 (switch) 4,664 records, 2,341 packets, 1,934 sequence failures; domain 38416 (NSX profile) 26,062 records, 2,964 packets, 0 sequence failures; domain 38417 (NSX profile) registered, nothing in the window
  {{esx-7}}: domain 0 (switch) 16,180 records, 3,467 packets, 2,692 sequence failures; domain 38416 (NSX profile) 43,055 records, 4,854 packets, 0 sequence failures; domain 38417 (NSX profile) registered, nothing in the window
  {{esx-6}}: domain 0 (switch) 19,559 records, 3,446 packets, 2,593 sequence failures; domain 38416 (NSX profile) registered, nothing in the window; domain 38417 (NSX profile) registered, nothing in the window
  {{esx-5}}: domain 0 (switch) 2,420 records, 1,255 packets, 564 sequence failures; domain 38416 (NSX profile) registered, nothing in the window; domain 38417 (NSX profile) registered, nothing in the window
  {{esx-10}}: domain 0 (switch) 14,305 records, 3,178 packets, 2,500 sequence failures; domain 38416 (NSX profile) registered, nothing in the window; domain 38417 (NSX profile) registered, nothing in the window
  {{esx-9}}: domain 0 (switch) 4,579 records, 1,439 packets, 557 sequence failures; domain 38416 (NSX profile) registered, nothing in the window; domain 38417 (NSX profile) registered, nothing in the window
  {{esx-3}}: domain 0 (switch) 149,386 records, 18,583 packets, 14,433 sequence failures
  {{esx-4}}: domain 0 (switch) 27,792 records, 4,658 packets, 3,349 sequence failures
  {{esx-1}}: domain 0 (switch) 139,861 records, 12,408 packets, 5,767 sequence failures
  hosts that sent nothing: {{esx-11}}, {{esx-2}}
  record: ./exporters.record.json
```
