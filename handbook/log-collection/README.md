# Log collection: prove every source from the destination

The chapter ([privatecloudarchitect.com/handbook/log-collection](https://privatecloudarchitect.com/handbook/log-collection))
teaches log collection on VCF 9.1 as two planes and an order of operations: logs travel from each source to Log
Management, and the configuration that decides how they travel goes the other way. This folder is its checkpoint.
One read-only script shows which path each log source takes and what the proxies keep, proves, host by host,
that each ESX host's own logs reach Log Management, reads the owner's setting the forwarder applies, and checks that
every host would trust its target's certificate the next time it connects. Run it on a schedule: it exits 1 when it
finds something.

Proven on VCF 9.1.1 (VCF Operations 9.1.1.0100, two unified cloud proxies, Log Management 9.1.1.0 on the services
runtime, vCenter 9.1.1) on 2026-10-22, with the exact files in this folder.

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
   lines about its hosts, and they keep arriving after a host's own logs have stopped. The search caps a count at
   10,000 per query and does not say so, so a count is a floor.
5. With `--verify-config`, Log Management's stored log collection configuration for vCenters
   (`GET /api/v2/log-configs/config/vc` on port 9543) beside its recommended one
   (`GET /api/v2/log-configs/recommended-config/vc`): per vCenter, whether collection is on, the protocol and whether
   TLS is set. That is the owner's setting the forwarder applies to every host of the vCenter. It needs a token whose
   role can read Log Management's configuration; a viewer is refused (403). Each entry's credentials are dropped unread.
6. With `--verify-trust`, through each vCenter you name (pyVmomi): every ESX host's syslog target
   (`Syslog.global.logHost`) and trusted CAs (`certificateManager.ListCACertificates()`), and then the host's own TLS
   check replayed from where the script runs: a handshake to the target, verified against exactly that host's CAs. A
   host that would fail it delivers on its open session and goes silent at its next reconnect, so the source proof
   alone cannot see it coming. The replay checks the chain to the host's own CAs, not the certificate's names.

## Run it

```
( umask 077; mkdir -p ~/.vcf && cat > ~/.vcf/ops-api-token )   # paste your api-token, then Ctrl-D
export OPS_HOST=<operations fqdn> OPS_API_TOKEN_FILE=~/.vcf/ops-api-token OPS_TLS_VERIFY=false   # optional OPS_BROKER_HOST, OPS_REALM
python3 log_paths.py --out ./records --verify-sources
python3 log_paths.py --out ./records --verify-sources --minutes 4320   # when a host reads zero

# the owner's setting, and every host's trust (pyVmomi for the second)
export VC_HOSTS=<vcenter fqdn>[,<another>] VC_USER=<user> VC_PASSWORD_FILE=./vc.pw   # mode 0600
python3 log_paths.py --out ./records --verify-sources --verify-config --verify-trust
```

Exit status: 0 when every read completed and nothing was found; 1 when a host delivered none of its own events in
the window, would fail its TLS check, or sits under an enabled vCenter whose stored TLS setting differs from the
recommended one (each printed under `findings`); 2 when the read did not complete (a setting, a secret, a sign-in or
the scrubber stopped it). Schedule the full run and alarm on a non-zero exit: vCenter replaces every host's CAs
whenever its own trusted roots change, whoever changed them, so a run after your own changes only misses the case
that matters.

The api-token is read from `OPS_API_TOKEN_FILE`, a file of mode 0600, when it is set; a wider mode is refused.
The value itself in `OPS_API_TOKEN` still works, but it lands in the shell's history and the process list, so
keep it for a throwaway credential.

Standard library only. The Operations sign-in and request helpers are the metrics-collection harness's, which ships
in this repository at `../metrics-collection/harness/`; the script finds them there, so run it from this folder of a
full clone.

## Reading the result

- **The source proof.** A host passes when its own applications arrive with its proxy as the forwarder. A host at
  zero over the last hour is a finding only once the long window shows the same host delivering before; then walk the
  chapter's diagnostic ladder for it (Plate 05): the target it holds and whether the proxy listens there, what the log
  collection configuration says, and whether the host trusts the listener's certificate.
- **The trust proof.** A host marked `WOULD FAIL` does not trust the certificate its target serves. vCenter pushes its
  trusted roots to every host it manages when a root is added to it, and the push replaces the host's own list, so a
  root the forwarder added to a host is gone after the next push. Put each proxy's forwarder root in the trusted roots
  of the vCenters whose hosts send to it, and read the trust proof on the same schedule as the source proof, and again
  after every VCF Operations upgrade or patch and every change to vCenter's trusted roots.
- **Getting a proxy's forwarder root.** The forwarder's certificate is its own, self-signed chain, not the proxy's TLS
  certificate, and every proxy's root carries the same name, so take it from the listener each host targets and
  tell roots apart by key identifier:

  ```
  openssl s_client -connect <proxy fqdn>:1514 -showcerts </dev/null 2>/dev/null \
    | awk '/BEGIN CERTIFICATE/{n++; p=1} p {print > ("forwarder-" n ".pem")} /END CERTIFICATE/{p=0}'
  for f in forwarder-*.pem; do echo "$f"; openssl x509 -in "$f" -noout -subject -issuer; done
  openssl x509 -in forwarder-2.pem -noout -text | grep -A1 'Subject Key Identifier'   # the self-signed one
  ```

  The root is the file whose subject and issuer are the same. Add it in the vSphere Client (Administration ▸
  Certificates ▸ Certificate Management ▸ Trusted Root ▸ Add Trusted Root Certificate) or with `POST
  /api/vcenter/certificate-management/vcenter/trusted-root-chains`, on every vCenter whose hosts send to that proxy;
  vCenter then pushes it to each of them. Remove it when the proxy is retired.
- **The stored configuration.** A vCenter whose entry reads TLS false while the recommendation reads true sends plain
  TCP to a proxy that may accept syslog only over TLS. Change it at the owner, in VCF Operations, not on the hosts.
- **The path.** A site whose sources read `DIRECT` has no site collector and no site buffer between them and Log
  Management; read the setting per adapter instance and decide it per site (Plate 02).
- **The record** (`log-paths.record.json`): `collectors` (type, `data_persistence`, state), `adapter_instances` (how
  many exist), `log_collection` (one row per adapter kind and path, with its instance count), `components` (the Fleet
  LCM rows for `OPS` and `OPS_LOGS`), with `--verify-sources` a `source_proof` block (`window_minutes`,
  `applications`, and per host `own_events` and `forwarders`), with `--verify-config` a `stored_config` block
  (`vcenters`: `enabled`, `protocol`, `ssl_enabled`, `esx_logs`; and `recommended`), and with `--verify-trust` a
  `trust_proof` block (per host `target`, `trusted_cas`, `trusts_target` and `why`). The folder carries two: the run
  after the repair, and `log-paths-silent-host.record.json`, the source proof with one host silent.

Every estate value in the record is replaced by a placeholder (`{{esx-1}}`, `{{collector-host-1}}`), and the script
refuses to write a record in which one survived (`scrub.py`).

## What it does not cover

- The proxy-side data persistence settings (the `fqDataForwarder*` keys in the proxy's `collector.properties`): a
  root shell on the proxy reads them, and the API exposes only the on and off flag.
- Log Management's replica count, which Fleet LCM does not report: `kubectl get sts -n ops-logs` on a control-plane
  node of the services runtime.
- Each ESX host's certificate options (`Syslog.global.certificate.*`) and its syslog daemon's own counters, which a
  shell on the host reads (`/bin/viewScoreboard.py /var/log/vmsyslog2_stats.scoreboard`).
- Whether the certificate's names match the target the host holds: the trust proof checks the chain only.
- The host's own events about its remote logging (`esx.problem.vmsyslogd.remote.failure`,
  `esx.problem.vmsyslogd.remote.logmessages.dropped`), which vCenter keeps per host: an early word for some failures,
  not a test (the log-alerts chapter alerts on them).

## Expected output

[`expected-output.md`](expected-output.md) holds two runs against the reference estate: the source proof with one host
gone silent, and every read after the repair, with notes on reading them.
