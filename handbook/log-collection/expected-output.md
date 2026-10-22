# Expected output: log_paths.py

Two runs of the log harness against the reference estate on 2026-10-22, before and after a repair. Each transcript
is the script's own report of that run's record (`records/log-paths-silent-host.record.json`, then
`records/log-paths.record.json`), so it matches the record exactly, with every estate value replaced by a
placeholder. Counts and versions are this estate's; the shape is what any 9.1 estate returns. Placeholders are
numbered per run, so `{{esx-7}}` in one run is not the same host as in the other; a vCenter shows as `{{vcenter-N}}`
or, where the adapter list named it first, `{{source-N}}`.

## A host gone silent: `--verify-sources` (11:10Z, last 60 minutes)

One host delivered nothing in the hour, so the run exits 1. Over three days it had delivered (`--minutes 4320`), so
the zero is a finding: its own events stop at 00:07Z. The host's own vCenter events said the same thing first
(`esx.problem.vmsyslogd.remote.failure`, "Remote logging to this host has stopped"), and its syslog log said why:
`certificate verify failed` against the forwarder's certificate. vCenter had pushed its trusted roots to every host
the evening before, which replaced each host's CAs without the forwarder's root. The other ten hosts were still
delivering on sessions opened before that push; read that afternoon, none of them held the root either, so each was
one reconnect from the same silence, which this run cannot see and the trust proof can.

```
$ python3 log_paths.py --out ./records --verify-sources
read at 2026-10-22T11:10:57Z
  collector UNIFIED_CLOUD_PROXY  data persistence True
  collector UNIFIED_CLOUD_PROXY  data persistence True
  collector INTERNAL             data persistence False
  9 of 60 adapter instances carry LOG_COLLECTION:
    NSXTAdapter          CLOUD_PROXY  x3
    SupervisorAdapter    CLOUD_PROXY  x1
    VMWARE               CLOUD_PROXY  x3
    VcfAdapter           DIRECT       x2
  OPS      deployment OVA, 9.1.1.0100.25795063, size medium, 3 node(s) listed
  OPS_LOGS deployment VSP, 9.1.1.0.25679624, size small, 0 node(s) listed
  source proof, last 60 min: 10 of 11 ESX hosts delivered their own logs
    {{esx-1}}      own events  15850  via {{collector-host-1}}
    {{esx-2}}      own events  12409  via {{collector-host-1}}
    {{esx-3}}      own events  12209  via {{collector-host-1}}
    {{esx-4}}      own events  12600  via {{collector-host-1}}
    {{esx-5}}      own events  14219  via {{collector-host-1}}
    {{esx-6}}      own events  12547  via {{collector-host-1}}
    {{esx-7}}      own events      0  via -
    {{esx-8}}      own events   6191  via {{collector-host-2}}
    {{esx-9}}      own events  14128  via {{collector-host-1}}
    {{esx-10}}     own events  10411  via {{collector-host-1}}
    {{esx-11}}     own events  14499  via {{collector-host-1}}
  findings: 1
    {{esx-7}} delivered none of its own events in the window
  record: ./records/log-paths.record.json
$ echo $?
1
```

## After the repair: every read (18:17Z, last 60 minutes)

Each proxy's forwarder root was added to the trusted roots of the vCenters whose hosts send to it, and vCenter pushed
it to every host. The trust proof replays each host's own TLS check against its own CAs: a host that would fail it
is silent at its next reconnect, while its open session still delivers, which is why the source proof alone does
not see it coming. The stored configuration is the owner's setting the forwarder applies; the entry with collection
off is a retired vCenter, so its TLS setting is not a finding. This run used a token whose role can read Log
Management's configuration; a viewer is refused that read (403) and every other read works with it.

```
$ python3 log_paths.py --out ./records --verify-sources --verify-config --verify-trust
read at 2026-10-22T18:17:30Z
  collector UNIFIED_CLOUD_PROXY  data persistence True
  collector UNIFIED_CLOUD_PROXY  data persistence True
  collector INTERNAL             data persistence False
  9 of 60 adapter instances carry LOG_COLLECTION:
    NSXTAdapter          CLOUD_PROXY  x3
    SupervisorAdapter    CLOUD_PROXY  x1
    VMWARE               CLOUD_PROXY  x3
    VcfAdapter           DIRECT       x2
  OPS      deployment OVA, 9.1.1.0100.25795063, size medium, 3 node(s) listed
  OPS_LOGS deployment VSP, 9.1.1.0.25679624, size small, 0 node(s) listed
  source proof, last 60 min: 11 of 11 ESX hosts delivered their own logs
    {{esx-1}}      own events  27564  via {{collector-host-1}}
    {{esx-2}}      own events  22923  via {{collector-host-1}}
    {{esx-3}}      own events  14767  via {{collector-host-1}}
    {{esx-4}}      own events  15364  via {{collector-host-1}}
    {{esx-5}}      own events  19618  via {{collector-host-1}}
    {{esx-6}}      own events  15480  via {{collector-host-1}}
    {{esx-7}}      own events   6914  via {{collector-host-2}}
    {{esx-8}}      own events   8173  via {{collector-host-2}}
    {{esx-9}}      own events  18045  via {{collector-host-1}}
    {{esx-10}}     own events  15190  via {{collector-host-1}}
    {{esx-11}}     own events  19993  via {{collector-host-1}}
  stored configuration, vCenters (recommended: syslog_tcp, TLS True):
    {{vcenter-1}}  collection False  syslog_tcp  TLS False  ESX logs True
    {{source-6}}   collection True   syslog_tcp  TLS True   ESX logs True
    {{vcenter-2}}  collection True   syslog_tcp  TLS True   ESX logs True
    {{source-9}}   collection True   syslog_tcp  TLS True   ESX logs True
  trust proof: 11 of 11 TLS hosts would trust their target's certificate on reconnect
    {{esx-7}}      11 CAs  trusts      verified
    {{esx-8}}      11 CAs  trusts      verified
    {{esx-9}}      11 CAs  trusts      verified
    {{esx-10}}     11 CAs  trusts      verified
    {{esx-11}}     11 CAs  trusts      verified
    {{esx-1}}      11 CAs  trusts      verified
    {{esx-2}}      11 CAs  trusts      verified
    {{esx-3}}      11 CAs  trusts      verified
    {{esx-4}}      11 CAs  trusts      verified
    {{esx-5}}      11 CAs  trusts      verified
    {{esx-6}}      11 CAs  trusts      verified
  findings: 0
  record: ./records/log-paths.record.json
$ echo $?
0
```

## Reading it

- **Run it on a schedule.** Exit 1 means a finding, printed under `findings`; exit 2 means the read did not
  complete. vCenter replaces every host's CAs whenever its own trusted roots change, whoever changed them, so a run
  after your own changes only is not enough.
- **A count is a floor.** Log Management's search caps a count at 10,000 per query and does not say so, so a
  long window can show every host near 40,000 (four applications at the cap). The proof needs one event.
- **A zero is a finding** only once a longer window shows the same host delivering before.
- **`WOULD FAIL`** in the trust proof names a host that will go silent at its next reconnect: add its target's root
  to the trusted roots of the host's vCenter, which pushes it to every host it manages.
