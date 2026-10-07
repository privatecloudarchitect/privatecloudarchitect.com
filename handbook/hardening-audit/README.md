# Hardening loop harness

Backs the hardening and audit sheet
([privatecloudarchitect.com/handbook/hardening-audit](https://privatecloudarchitect.com/handbook/hardening-audit)).
The sheet's doctrine is that posture is a set of reads, run on a cadence, with owners, and that
the quarterly audit request should be a folder of dated outputs instead of a fire drill. This
harness is that doctrine as one command: the loop's reads, executed read-only, distilled into a
dated posture folder.

## What one run produces

`posture-<date>/` containing `report.md` (findings first, then the skips, then the
reads-to-controls mapping) and `reads.json` (the distilled records). Everything stored is a
distillation: counts, horizons, names of policies and sections, rotation coverage. Secret
material in the underlying responses is never read into the records; what lands on disk is the
evidence an auditor consumes, not a data dump.

## The reads, and where each is taught

| read | instrument | chapter |
|---|---|---|
| certificates | `GET /v1/domains/{id}/resource-certificates` per domain | [certs-credentials](https://privatecloudarchitect.com/handbook/certs-credentials) |
| credentials | `GET /v1/credentials` (distilled: counts + rotation coverage) | [certs-credentials](https://privatecloudarchitect.com/handbook/certs-credentials) |
| backup | `GET /v1/system/backup-configuration` (encryption reads as key absence) | [platform-backup](https://privatecloudarchitect.com/handbook/platform-backup) |
| alert-scope | default policy via the `defaultPolicy` flag, then `GET /api/policies/export?id=` and count `<Alert enabled="true">` entries | [alerting-doctrine](https://privatecloudarchitect.com/handbook/alerting-doctrine) |
| firewall-floor | `firewallpolicies` (single-get carries the rules) + `securityprofileattachments` at the org gateway | [microsegmentation](https://privatecloudarchitect.com/handbook/microsegmentation) |
| access | `projects`, then `projectrolebindings` per project | [access-control](https://privatecloudarchitect.com/handbook/access-control) |
| audit-trail | `GET /cloudapi/1.0.0/auditTrail` (versioned Accept), total event count | [hardening-audit](https://privatecloudarchitect.com/handbook/hardening-audit) |

## What the numbers mean

Every figure the loop reports is YOUR estate's current state at the run date, nothing more. The
audit question each finding asks is "is this intended," answered against your own records or the
vendor's documented defaults, never against another estate's counts: a reference estate is a
modified instance whose own tooling has toggled the very surfaces this loop reads.

## Three planes, each optional

The loop spans three token planes by nature, and each is optional: set what you have, and the
reads you cannot run are recorded as skips with their reasons inside the posture folder, which
is itself part of the posture.

```bash
# SDDC Manager plane (certificates, credentials, backup)
export SDDC_HOST=<sddc-manager-fqdn> SDDC_USERNAME=<sso-user> SDDC_PASSWORD=<password>
# Operations plane (alert scope) - the api-token flow from the identity chapter
export OPS_HOST=<ops-fqdn> OPS_BROKER_HOST=<broker-fqdn> OPS_API_TOKEN=<api-token>
# Consumption plane (firewall floor, access, audit trail) - an org session
export VCFA_HOST=<vcfa-fqdn> VCFA_ORG=<org> VCFA_USER=<user> VCFA_PASSWORD=<password>
export OPS_TLS_VERIFY=false  # only on a self-signed lab CA

python3 hardening.py
```

Exit code 0 when the loop is clean, 1 when findings are present; skips never fail the run.
Stdlib Python only.

## Fixes with dates

Every finding gets an owner and a fix with a date, and the harness keeps no state between runs, so the fix log is
a file you keep beside the posture folders: [`fix-log.csv`](fix-log.csv), one row per finding, with the run that
found it, the read, the owner (one per token plane: lifecycle, operations, tenancy), the fix, the date it was
fixed and the later run that no longer reports it. A row with no `fixed_on` is a risk somebody chose to keep; a
row with no `verified_by_run` is a fix nobody has read back.

## Two shapes the docs will not tell you

- **The policy export is the alert audit surface.** The policy settings API's `type` enum
  carries no alert-definition type, and enable/disable are write-only; which definitions the
  default policy enables reads from `GET /api/policies/export?id=` (a zip of
  `exportedPolicies.xml`, where each `<Alert enabled=...>` entry is one definition's state).
- **Backup encryption reads as absence.** An estate without the passphrase set returns no
  encryption key at all in the configuration; the finding is the missing key, not a false.

## Expected output

See [`expected-output.md`](expected-output.md) for the transcript and folder shape.
