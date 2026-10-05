# Log collection: prove every source from the destination

The chapter ([privatecloudarchitect.com/handbook/log-collection](https://privatecloudarchitect.com/handbook/log-collection))
teaches log collection on VCF 9.1 as two planes and an order of operations: logs travel from each source to Log
Management, and the configuration that decides how they travel goes the other way. This folder is its checkpoint.
One read-only script shows which path each log source takes and what the proxies keep, and proves, host by host,
that each ESX host's own logs reach Log Management.

Proven on VCF 9.1.1 (VCF Operations 9.1.1.0, two unified cloud proxies, Log Management 9.1.1.0 on the services
runtime) on 2026-10-05, with the exact files in this folder.

## What it reads

Every call is a read, plus the token exchanges the platform requires to issue a read token, which change nothing.

1. `GET /suite-api/api/collectors`: each collector's type and its data persistence flag.
2. `GET /suite-api/api/adapters`: the `LOG_COLLECTION` setting (`CLOUD_PROXY` or `DIRECT`) on every adapter instance
   that carries one, tallied by adapter kind. This is the per-source path the chapter's Plate 02 describes.
3. `GET /fleet-lcm/v1/components`, with a token for the fleet service found through
   `GET /suite-api/api/integrations/services`: Log Management's deployment type, version, size and node count, beside
   VCF Operations' own.
4. With `--verify-sources`, the source proof of the chapter's Plate 05: for every ESX host VCF Operations knows, the
   host's **own** application events (`Hostd`, `Vpxa`, `vmkernel`, `vobd`, `Fdm`) in Log Management over the last N
   minutes, through `POST /api/v2/logs/search` on port 9543 with a token for the Log Management service, and the
   `forwarder` field that names who relayed them. Events that only carry the host's name do not count: vCenter writes
   lines about its hosts, and they keep arriving after a host's own logs have stopped.

## Run it

```
export OPS_HOST=<operations fqdn> OPS_API_TOKEN=<api token> OPS_TLS_VERIFY=false   # optional OPS_BROKER_HOST, OPS_REALM
python3 log_paths.py --out ./records --verify-sources
python3 log_paths.py --out ./records --verify-sources --minutes 4320   # when a host reads zero
```

Standard library only. The Operations sign-in and request helpers are the metrics-collection harness's, which ships
in this repository at `../metrics-collection/harness/`; the script finds them there, so run it from this folder of a
full clone.

## Reading the result

- **The source proof.** A host passes when its own applications arrive with its proxy as the forwarder. A host at
  zero over the last hour is a finding only once the long window shows the same host delivering before; then walk the
  chapter's diagnostic ladder for it (Plate 05): the target it holds and whether the proxy listens there, what the log
  collection configuration says, and whether the host trusts the listener's certificate.
- **The path.** A site whose sources read `DIRECT` has no site collector and no site buffer between them and Log
  Management; read the setting per adapter instance and decide it per site (Plate 02).
- **The record** (`log-paths.record.json`): `collectors` (type, `data_persistence`, state), `adapter_instances` (how
  many exist), `log_collection` (one row per adapter kind and path, with its instance count), `components` (the Fleet
  LCM rows for `OPS` and `OPS_LOGS`), and with `--verify-sources` a `source_proof` block (`window_minutes`,
  `applications`, and per host `own_events` and `forwarders`).

Every estate value in the record is replaced by a placeholder (`{{esx-1}}`, `{{collector-host-1}}`), and the script
refuses to write a record in which one survived (`scrub.py`).

## What it does not cover

- The proxy-side data persistence settings (the `fqDataForwarder*` keys in the proxy's `collector.properties`): a
  root shell on the proxy reads them, and the API exposes only the on and off flag.
- Log Management's replica count, which Fleet LCM does not report: `kubectl get sts -n ops-logs` on a control-plane
  node of the services runtime.
- Each ESX host's syslog target, certificate options and trusted CAs: the vSphere API through vCenter
  (`Syslog.global.logHost`, the `Syslog.global.certificate.*` options, `certificateManager.ListCACertificates()`),
  which the chapter's Plates 04 and 05 read.

## Expected output

[`expected-output.md`](expected-output.md) holds three runs against the reference estate: the source proof during an
outage (no host delivering), after the repair the chapter's worked case describes, and over a window that reaches
back before the stop.
