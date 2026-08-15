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

| read | instrument | sheet |
|---|---|---|
| certificates | `GET /v1/domains/{id}/resource-certificates` per domain | III.2 |
| credentials | `GET /v1/credentials` (distilled: counts + rotation coverage) | III.2 |
| backup | `GET /v1/system/backup-configuration` (encryption reads as key absence) | III.3 |
| alert-scope | default policy via the `defaultPolicy` flag, then `GET /api/policies/export?id=` and count `<Alert enabled="true">` entries | IV.2 |
| firewall-floor | `firewallpolicies` (single-get carries the rules) + `securityprofileattachments` at the org gateway | VII.1 |
| access | `projects`, then `projectrolebindings` per project | I |
| audit-trail | `GET /cloudapi/1.0.0/auditTrail` (versioned Accept), total event count | VII.2 |

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
export OPS_INSECURE=1        # only on a self-signed lab CA

python3 hardening.py
```

Exit code 0 when the loop is clean, 1 when findings are present; skips never fail the run.
Stdlib Python only.

## Two shapes the docs will not tell you

- **The policy export is the alert audit surface.** The policy settings API's `type` enum
  carries no alert-definition type, and enable/disable are write-only; which definitions the
  default policy enables reads from `GET /api/policies/export?id=` (a zip of
  `exportedPolicies.xml`, where each `<Alert enabled=...>` entry is one definition's state).
- **Backup encryption reads as absence.** An estate without the passphrase set returns no
  encryption key at all in the configuration; the finding is the missing key, not a false.

## Expected output

See [`expected-output.md`](expected-output.md) for the transcript and folder shape.
