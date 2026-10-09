# Log alerts: build them from identifiers, scope them to a group, prove them with a line

The chapter ([privatecloudarchitect.com/handbook/log-alerts](https://privatecloudarchitect.com/handbook/log-alerts))
teaches how to build VCF Operations log alerts on 9.1.1 that fire: find the identifier the platform writes for a
failure, try the query on stored events, write the condition the API accepts, cover both channels a host's events
travel on, switch the alert on for one custom group and confirm its monitors, and prove it with a labelled syslog line.
This folder holds the tools for each of those steps, and a catalog of storage path alerts built with them.

Proven on VCF 9.1.1 (VCF Operations and Log Management 9.1.1, three vCenters and their ESX hosts on 9.1.1) on
2026-10-09, with the exact files in this folder.

## What is here

| File | What it does | Writes |
|---|---|---|
| `signatures.py` | `catalog`: the event types each vCenter can emit, filtered by family or by a word in the message (`--grep`). `seen`: the identifiers your hosts' `vobd` records and vCenter's stream carried. `try`: one query over stored events, with counts by application and host, samples, and the object kind the records name. `fields`: whether every field a query names exists. `monitor`: what Log Management built from a symptom (its schedule, its window and the query each filter became), read from OpenSearch's own log of the definition | nothing |
| `deploy.py` | `plan`, `apply`, `status`, `teardown` for a bundle, scoped by a scope file | a custom group, a policy, log symptoms and alerts (with `--yes`) |
| `prove.py` | labelled lines in the host's own record format, then when they were indexed, which alerts raised on that host, and (with `--until-clear`) when each cleared; `--backdate N` stamps the lines N minutes old | syslog lines to the target you name (with `--send`) |
| `lmlib.py` | the sign-in, the Log Management token and the search, shared by the three | |
| `bundle/storage-path-health.json` | the storage path catalog: 24 log symptoms and 11 alerts, each identifier graded by how it was validated on 9.1.1 | |
| `bundle/storage-path-runbook.md` | what to do when each alert fires | |
| `scope.example.json` | the one file you edit: owner prefix, scope name, clusters, parent policy | |
| `records/` | the runs on the reference estate the chapter renders, every estate value replaced by a placeholder | |

## Run it

Standard library Python 3. The Operations sign-in and the service-token exchange are the metrics-collection harness's
and the scrubber is the log-collection harness's; the scripts find them in the folders beside this one, so run from
this folder of a full clone. `signatures.py catalog` also needs pyVmomi (`pip install pyvmomi`).

```
export OPS_HOST=<operations fqdn>  OPS_API_TOKEN=<api token>  OPS_TLS_VERIFY=false   # optional OPS_BROKER_HOST, OPS_REALM

# find the identifier
python3 signatures.py seen --days 7
export VC_HOST=<vcenter fqdn>  VC_USER=<account>  VC_PASSWORD=<password>  VC_TLS_VERIFY=false
python3 signatures.py catalog --grep permanently
python3 signatures.py fields --check appname,text,vc_event_type
python3 signatures.py monitor --name "PCA - Storage Path - Host - All paths down started, host record"

# try the query before it becomes an alert
python3 signatures.py try --vc-event esx.problem.storage.apd.start --days 7
python3 signatures.py try --app vobd --text esx.problem.storage.apd.start --days 7

# deploy the catalog to one group of hosts, read it back, prove it
cp scope.example.json scope.json        # then edit it
python3 deploy.py plan   --scope scope.json
python3 deploy.py apply  --scope scope.json --yes
python3 deploy.py status --scope scope.json
python3 prove.py --scope scope.json --host <esx fqdn> --target ssl://<the host's syslog listener>:<port>
python3 prove.py --scope scope.json --host <esx fqdn> --target ssl://<the host's syslog listener>:<port> --send --until-clear --minutes 30

# remove it: the scope's policy and group, or with --all the definitions every scope shares
python3 deploy.py teardown --scope scope.json --all --yes
```

`--only SP-02,SP-08` limits `plan`, `apply` and `prove.py` to those alerts. `--out ./records` writes a scrubbed record
from `signatures.py`, `deploy.py status` and `prove.py`.

## What each tool settles, and how to read it

- **An identifier, not a word.** `catalog --grep` turns a word you remember into the identifiers whose message
  contains it; `seen` shows which of them your hosts actually wrote. A condition anchored on one of those, with
  `appname` fixed for host records, matches the failure and nothing else. `try --text WORD` shows which applications
  write a bare word, which is why a condition never uses one alone.
- **The search before the alert.** `try` prints the same filters as a search: the event type matches exactly (a
  partial one matches nothing), and a phrase in text matches every identifier that begins with the same words. It
  also prints the object kind the records name, which is the kind the alert takes.
- **What a condition becomes.** `monitor` prints the query Log Management built: `CONTAINS` on `vc_event_type` or
  `appname` is an exact, case-insensitive match of the whole value; on `text` it is a phrase of whole words anywhere in
  the line, the syslog header included. The window is a range on the event's own timestamp.
- **The rules the API enforces.** `deploy.py plan` runs `check()` on the bundle and refuses to continue on a broken
  rule: `EQUAL` on a text field (refused with a 400 on 9.1.1), a trigger other than `COUNT` above a threshold (only
  that raised an alert), a window outside 5, 15, 30, 60 and 360 minutes, a text condition without `appname`, a
  hostname condition, or an auto-cancel time below 1.
- **Scope and the monitor read-back.** `apply` switches each alert on in the scope's own policy, which inherits the
  hosts' current policy, and touches no other policy: an alert left unset elsewhere fires nowhere else. It then reads
  the alert's monitors in Log Management (`GET /api/v2/ops-alerts`) and switches the alert off and on until they read
  enabled; on 9.1.1 the first switch-on of a new alert left its new symptoms' monitors disabled, and an alert whose
  monitors are disabled never fires while the policy shows it enabled. A second `apply` changes nothing.
- **The timing.** Log Management counts each log symptom on a schedule its window sets (a 5-minute window every
  minute, 15 and 30 every five minutes, 60 every ten, 360 every minute), over the lines whose own timestamp falls inside
  the window, and hands the result to VCF Operations through a queue. Expect minutes: `prove.py` prints when the lines
  were indexed, when each alert raised and, with `--until-clear`, when it cleared, so you can write each alert's
  expected delay into its runbook. `--backdate` longer than the window shows that a late line (buffered through an
  outage, or from a host whose clock is behind) raises nothing.
- **The proof.** `prove.py` sends, for every host-record symptom that carries a `prove` sample, the line the host
  writes, with a label, one more time than the symptom's threshold, to the target you name; the line's HOSTNAME
  decides which host the alert raises on. It refuses to send while an enabled notification rule selects every alert.
  vCenter-channel symptoms cannot be fed by a syslog line and wait for the first real event.

## The bundle

Names follow `<Owner> - <Bundle> - <Kind> - <Condition>` for symptoms and alerts and `<Owner> - <Bundle> - <Scope>` for
the policy, with your owner prefix from the scope file, so one filter finds everything the bundle created. Each
symptom's `validated` key says how its identifier was checked on 9.1.1: `catalog9.1.1` (in the vCenter event catalog),
`seen9.1.1` (read in a host's records or vCenter's stream), or `family9.1.1` (a sibling read on 9.1.1, the identifier
itself from the vendor's knowledge base, proven by a labelled line). To add an alert, add its symptoms and the alert to
the JSON (the chapter's workshop builds the entries), run `plan`, then `apply --only <ID>`.

## What it does not cover

- Notification routing: the alerts are created with no outbound rule. Route them with VCF Operations notification
  rules once an alert has been proven to reach the right person.
- Spread across hosts as one alert: Log Management created no monitor for a unique count on 9.1.1, so a fabric-wide failure is read from the
  same alert raising on several hosts.
- Silence as an alert: a count below a threshold never fired on 9.1.1, with its monitor enabled. Detect a host that has
  stopped sending with the log-collection folder's source proof, run on a schedule.
- Proof of the vCenter-channel alerts (SP-05, SP-06, SP-07, SP-C2) by a labelled line: they are deployed with their
  monitors enabled and wait for a real event.
- The labelled lines stay in Log Management until its retention removes them; each raised alert cancels itself after
  its window and the bundle's auto-cancel time.

## Expected output

[`expected-output.md`](expected-output.md) holds the runs on the reference estate the chapter shows: the identifiers
seen, a catalog search by word, the tries, the deploy (first run and second run), status, and the proof.
