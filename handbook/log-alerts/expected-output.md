# Expected output

The runs on the reference estate that the chapter shows, 2026-10-09: VCF Operations and Log Management 9.1.1, three
vCenters and their hosts on 9.1.1. Host names, the scope name and the test label are replaced; every other line is as
printed, and lines longer than 220 characters are cut.

## signatures.py seen --days 7

```
vobd over 7 days: 2771 records, 79 identifiers, 1 truncated slices
      191    1 host   vob.scsi.scsipath.por
      187    6 hosts  esx.clear.net.dvport.redundancy.restored
      163    6 hosts  esx.clear.net.vmnic.linkstate.up
      161    6 hosts  esx.clear.net.dvport.connectivity.restored
      160    6 hosts  esx.clear.net.connectivity.restored
      150    6 hosts  esx.clear.net.redundancy.restored
      147   11 hosts  esx.problem.vmsyslogd.remote.failure
      126   11 hosts  vob.user.vmsyslogd.remote.failure
      114    3 hosts  esx.problem.vm.kill.unexpected.vmx.fault.failure.2
       96    6 hosts  esx.audit.net.firewall.port.hooked
       60    6 hosts  vob.net.dvport.uplink.transition.up
       57    3 hosts  vob.vm.kill.unexpected.vmx.fault.failure
       55    6 hosts  vob.net.dvport.uplink.transition.down
       54    6 hosts  vob.net.vmnic.linkstate.up
       50    6 hosts  esx.clear.vmfs.nfs.server.restored
       42   11 hosts  esx.problem.clock.correction.adjtime.sync
       38    3 hosts  esx.problem.net.firewall.config.failed
       37    9 hosts  esx.audit.maintenancemode.exited
       36    9 hosts  vob.user.maintenancemode.exited
       36    6 hosts  esx.problem.net.dvport.redundancy.lost
       34    6 hosts  esx.clear.coredump.configured2
       32    6 hosts  esx.problem.net.vmnic.linkstate.down
       30    5 hosts  vob.net.firewall.port.hooked
       30    9 hosts  esx.audit.esximage.software.apply.succeeded
       30    9 hosts  vob.user.esximage.software.apply.succeeded
vc_event_type over 7 days: 240 types
wrote signatures-seen.record.json
```

## signatures.py try --vc-event esx.problem.storage.apd.start --days 7

The search body it sent is its first line; the summary follows.

```
{"query": {"bool": {"must": [{"term": {"vc_event_type": "esx.problem.storage.apd.start"}}], "must_not": [{"match_phrase": {"text": "labelled test line"}}], "filter": [{"range": {"timestamp": {"gte": 1790923020779, "lte":
2 events; by application: vcenter-server 2
       2  vcenter-server {{host-1}}
  the records name: {'HostSystem': 1} (the object kind an alert on them takes)
  sample: 2026-10-06 14:11:10.175 {{host-1}} vcenter-server: <the catalog text of esx.problem.storage.apd.start>
```

## signatures.py try --app vobd --text storage.apd --days 7

A partial identifier in text matches its siblings: the starts and the exits, in both forms.

```
12 events; by application: vobd 12
      12  vobd       {{host-1}}
  the records name: {'HostSystem': 3} (the object kind an alert on them takes)
  sample: 2026-10-06T14:11:33.123Z {{host-1}} vobd 2097451 - [esx@4413 threadName="APDCorrelator"] 4846243989us: [vob.storage.apd.exit] Device or filesystem with identifi
  sample: 2026-10-06T14:11:33.123Z {{host-1}} vobd 2097451 - [esx@4413 threadName="APDCorrelator"] 4846448728us: [esx.clear.storage.apd.exit] Device or filesystem with id
  sample: 2026-10-06T14:11:33.123Z {{host-1}} vobd 2097451 - [esx@4413 threadName="APDCorrelator"] The event ([esx.clear.storage.apd.exit] Device or filesystem with ident
```

## signatures.py try --vc-event esx.problem.storage.apd --days 7

A partial event type matches nothing.

```
0 events; by application:
  the records name: {} (the object kind an alert on them takes)
```

## signatures.py try --text APD --days 7

A bare word, with one record from each application that writes it.

```
211 events; by application: vmkernel 81, vobd 12, Hostd 8, audit 1
      20  vmkernel   {{host-1}}
      13  vmkernel   {{host-2}}
      13  vmkernel   {{host-4}}
      12  vobd       {{host-2}}
      10  vmkernel   {{host-5}}
       8  Hostd      {{host-2}}
       5  vmkernel   {{host-6}}
       5  vmkernel   {{host-7}}
       5  vmkernel   {{host-8}}
       5  vmkernel   {{host-9}}
       5  vmkernel   {{host-10}}
       1  audit      {{host-3}}
  the records name: {'HostSystem': 3, 'VirtualMachine': 1} (the object kind an alert on them takes)
  sample: 2026-10-06T14:56:57.843Z {{host-1}} vmkernel - - [esx@4413] cpu2:2097963)StorageApdHandler: 967: APD Handle 9093fe95-3a4075e7 Created with lock[StorageApd-0x431
  sample: 2026-10-06T14:11:33.123Z {{host-2}} vobd 2097451 - [esx@4413 threadName="APDCorrelator"] 4846243989us: [vob.storage.apd.exit] Device or filesystem with identifi
  sample: 2026-10-06T14:11:34.123Z {{host-2}} Hostd 2098516 - [esx@4413 sub="Hostsvc.DatastoreSystem"] StorageApdUpdateInt: Processing Storage APD msg [N11HostdCommon24Vm
  sample: 2026-10-08T22:54:05.107Z INFO audit 5916 [ops@4413 auditID="ALERT_DEFINITION.CREATE" threadId="203530" userID="{{uuid-2}}" subject="{{account-1}}" authSource="V
wrote signatures-try-word-apd.record.json
```

## deploy.py apply --scope scope.json --yes, first run

Every new alert's first switch-on left its new symptoms' monitors disabled, and the switch off and on enabled them.
An alert whose symptoms another alert had already brought up was enabled at the first attempt. The symptom and alert
create lines are left out.

```
create group PCA - Storage Path - <scope> (Hosts)
group PCA - Storage Path - <scope> (Hosts): 2 members
create policy PCA - Storage Path - <scope>
monitors present: 24 of 24
  monitors not enabled {'PCA - Storage Path - Host - Device permanently lost, vCenter event': False, 'PCA - Storage Path - Host - Psastor device permanently lost, vCenter event': False, 'PCA - Storage Path - Host - Devic
SP-01: on in PCA - Storage Path - <scope>, monitors enabled 4 of 4 (attempt 2)
  monitors not enabled {'PCA - Storage Path - Host - All paths down started, vCenter event': False, 'PCA - Storage Path - Host - All paths down started, host record': False}; switching the alert off and on
SP-02: on in PCA - Storage Path - <scope>, monitors enabled 2 of 2 (attempt 2)
  monitors not enabled {'PCA - Storage Path - Host - All paths down timed out, vCenter event': False, 'PCA - Storage Path - Host - All paths down timed out, host record': False}; switching the alert off and on
SP-03: on in PCA - Storage Path - <scope>, monitors enabled 2 of 2 (attempt 2)
  monitors not enabled {'PCA - Storage Path - Host - SCSI paths dead, host record': False, 'PCA - Storage Path - Host - Psastor paths dead, host record': False, 'PCA - Storage Path - Host - Path state changing frequently
SP-04: on in PCA - Storage Path - <scope>, monitors enabled 3 of 3 (attempt 2)
  monitors not enabled {'PCA - Storage Path - Host - Path redundancy degraded, vCenter event': False, 'PCA - Storage Path - Host - Path redundancy lost, vCenter event': False, 'PCA - Storage Path - Host - Device connecti
SP-05: on in PCA - Storage Path - <scope>, monitors enabled 3 of 3 (attempt 2)
  monitors not enabled {'PCA - Storage Path - Host - VMFS heartbeat timed out, vCenter event': False, 'PCA - Storage Path - Host - VMFS heartbeat unrecoverable, vCenter event': False, 'PCA - Storage Path - Host - NFS ser
SP-06: on in PCA - Storage Path - <scope>, monitors enabled 3 of 3 (attempt 2)
  monitors not enabled {'PCA - Storage Path - Host - Device power-on resets frequent, vCenter event': False, 'PCA - Storage Path - Host - Path power-on resets frequent, vCenter event': False}; switching the alert off and
SP-07: on in PCA - Storage Path - <scope>, monitors enabled 2 of 2 (attempt 2)
  monitors not enabled {'PCA - Storage Path - Host - SCSI host status H:0x1 no connect over 4, host record': False, 'PCA - Storage Path - Host - SCSI host status H:0x1 no connect over 10, host record': False, 'PCA - Stor
SP-08: on in PCA - Storage Path - <scope>, monitors enabled 4 of 4 (attempt 2)
SP-C1: on in PCA - Storage Path - <scope>, monitors enabled 7 of 7 (attempt 1)
  monitors not enabled {'PCA - Storage Path - Host - Host connection lost, vCenter event': False, 'PCA - Storage Path - Host - All paths down started, vCenter event': True, 'PCA - Storage Path - Host - All paths down tim
SP-C2: on in PCA - Storage Path - <scope>, monitors enabled 3 of 3 (attempt 2)
SP-C3: on in PCA - Storage Path - <scope>, monitors enabled 6 of 6 (attempt 1)
apply: 37 created, 0 unchanged
```

## deploy.py apply --scope scope.json --yes, second run

```
group PCA - Storage Path - <scope> (Hosts): 2 members
monitors present: 24 of 24
SP-01: on in PCA - Storage Path - <scope>, monitors enabled 4 of 4 (attempt 1)
SP-02: on in PCA - Storage Path - <scope>, monitors enabled 2 of 2 (attempt 1)
SP-03: on in PCA - Storage Path - <scope>, monitors enabled 2 of 2 (attempt 1)
SP-04: on in PCA - Storage Path - <scope>, monitors enabled 3 of 3 (attempt 1)
SP-05: on in PCA - Storage Path - <scope>, monitors enabled 3 of 3 (attempt 1)
SP-06: on in PCA - Storage Path - <scope>, monitors enabled 3 of 3 (attempt 1)
SP-07: on in PCA - Storage Path - <scope>, monitors enabled 2 of 2 (attempt 1)
SP-08: on in PCA - Storage Path - <scope>, monitors enabled 4 of 4 (attempt 1)
SP-C1: on in PCA - Storage Path - <scope>, monitors enabled 7 of 7 (attempt 1)
SP-C2: on in PCA - Storage Path - <scope>, monitors enabled 3 of 3 (attempt 1)
SP-C3: on in PCA - Storage Path - <scope>, monitors enabled 6 of 6 (attempt 1)
apply: 0 created, 37 unchanged
```

## signatures.py monitor --name "PCA - Storage Path - Host - All paths down started, host record"

What Log Management built from the condition, read from OpenSearch's own log of the monitor definition.

```
monitor PCA - Storage Path - Host - All paths down started, host record: enabled True; runs every 1 minute; counts lines whose own timestamp is within the last 5m by logDate
  term          appname                vobd
  match_phrase  originalText           esx.problem.storage.apd.start
wrote signatures-monitor-host-apd-start.record.json
```

## signatures.py monitor --name "PCA - Storage Path - Host - Host connection lost, vCenter event"

```
monitor PCA - Storage Path - Host - Host connection lost, vCenter event: enabled True; runs every 5 minutes; counts lines whose own timestamp is within the last 15m by logDate
  term          vc_event_type          com.vmware.vim25.HostConnectionLostEvent
wrote signatures-monitor-vc-host-lost.record.json
```

## prove.py --scope scope.json --host <esx fqdn> --target ssl://<listener>:<port> --send --until-clear --minutes 30

The preview lines (one per distinct line, with its copy count) and the minute-by-minute reads after every alert had
raised are shortened.

```
can raise: {'SP-01': 2, 'SP-02': 1, 'SP-03': 1, 'SP-04': 2, 'SP-08': 4, 'SP-C1': 4, 'SP-C3': 3}
sent 29 lines naming <esx fqdn> at 2026-10-09T07:43:29.467Z, label pcalmtest<nonce>
07:44:35Z raised: [] cleared: []
07:45:41Z raised: ['SP-02', 'SP-03', 'SP-04', 'SP-08', 'SP-C1', 'SP-C3'] cleared: []
07:46:47Z raised: ['SP-01', 'SP-02', 'SP-03', 'SP-04', 'SP-08', 'SP-C1', 'SP-C3'] cleared: []
07:47:53Z raised: ['SP-01', 'SP-02', 'SP-03', 'SP-04', 'SP-08', 'SP-C1', 'SP-C3'] cleared: []
...
08:06:34Z raised: ['SP-01', 'SP-02', 'SP-03', 'SP-04', 'SP-08', 'SP-C1', 'SP-C3'] cleared: ['SP-08', 'SP-C1', 'SP-C3']
08:07:40Z raised: ['SP-01', 'SP-02', 'SP-03', 'SP-04', 'SP-08', 'SP-C1', 'SP-C3'] cleared: ['SP-01', 'SP-02', 'SP-03', 'SP-04', 'SP-08', 'SP-C1', 'SP-C3']
indexed: 29 of 29 lines, the first 1.6 s after sending
SP-01: raised 136 s after the lines, CRITICAL, cleared at 1382 s
SP-02: raised 76 s after the lines, WARNING, cleared at 1382 s
SP-03: raised 76 s after the lines, CRITICAL, cleared at 1382 s
SP-04: raised 76 s after the lines, WARNING, cleared at 1382 s
SP-05: no host-record line; waits for a real event
SP-06: no host-record line; waits for a real event
SP-07: no host-record line; waits for a real event
SP-08: raised 76 s after the lines, CRITICAL, cleared at 1238 s
SP-C1: raised 76 s after the lines, CRITICAL, cleared at 1238 s
SP-C2: no host-record line; waits for a real event
SP-C3: raised 76 s after the lines, WARNING, cleared at 1238 s
wrote proof.record.json
```
