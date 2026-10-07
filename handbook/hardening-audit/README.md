# Hardening loop harness

Backs the hardening and audit chapter
([privatecloudarchitect.com/handbook/hardening-audit](https://privatecloudarchitect.com/handbook/hardening-audit)).
The chapter's doctrine is that posture is a set of reads, run on a cadence, with owners, and that
the quarterly audit request should be a folder of dated outputs instead of a fire drill. This
harness is that doctrine as one command: the loop's seven reads, executed read-only, distilled into
a dated posture folder.

## What one run produces

`posture-<date>/` containing `report.md` (the build each plane answered with, findings first, then
the skips, then the reads-to-controls table) and `reads.json` (the distilled records). Everything
stored is a distillation: counts, horizons, dates, names of policies, sections and projects, rotation
coverage. Secret material in the underlying responses is never read into the records; what lands
on disk is the evidence an auditor consumes, not a data dump.

`--record FILE` also writes the run as counts, dates and product words only, with every host,
object and principal name left out, and refuses to write the file if a name it read survived.
[`hardening.json`](hardening.json) is that record from the reference estate, and it is what the
chapter renders.

## The reads, and where each is taught

| read | instrument | owner (token plane) | chapter |
|---|---|---|---|
| certificates | `GET /v1/domains/{id}/resource-certificates` per domain: expiry status, days to the nearest expiry, how many fall inside a 90-day horizon | lifecycle | [certs-credentials](https://privatecloudarchitect.com/handbook/certs-credentials) |
| credentials | `GET /v1/credentials` (distilled: counts by resource type and rotation coverage) | lifecycle | [certs-credentials](https://privatecloudarchitect.com/handbook/certs-credentials) |
| backup | `GET /v1/system/backup-configuration`: schedules, and whether an encryption key exists anywhere in the structure | lifecycle | [platform-backup](https://privatecloudarchitect.com/handbook/platform-backup), and plate 05 of [certs-credentials](https://privatecloudarchitect.com/handbook/certs-credentials) for encryption |
| alert-scope | the default policy by its `defaultPolicy` flag, then `GET /api/policies/export?id=` and count `<Alert enabled="true">` entries | operations | [alerting-doctrine](https://privatecloudarchitect.com/handbook/alerting-doctrine) |
| firewall-floor | `firewallpolicies` (the single get carries the rules) and `securityprofileattachments` at the organization gateway | tenancy | [microsegmentation](https://privatecloudarchitect.com/handbook/microsegmentation) |
| access | `projects`, then `projectrolebindings` per project: each binding's role and the kind of each subject | tenancy | [access-control](https://privatecloudarchitect.com/handbook/access-control) |
| audit-trail | `GET /cloudapi/1.0.0/auditTrail` sorted both ways: the event count and the oldest and newest event this session can read | tenancy | [hardening-audit](https://privatecloudarchitect.com/handbook/hardening-audit) |

## What the numbers mean

Every figure the loop reports is YOUR estate's current state at the run date, nothing more. The
audit question each finding asks is "is this intended," answered against your own records or the
vendor's documented defaults, never against another estate's counts: a reference estate is a
modified instance whose own tooling has toggled the very surfaces this loop reads.

## Three planes, each optional, one owner each

The loop spans three token planes, and each is optional: set what you have, and the reads you
cannot run are recorded as skips with their reasons inside the posture folder, which is itself part
of the posture, and the run exits 2 so a schedule notices. Whoever operates a plane owns its reads,
so the loop has three owners.

```bash
# Lifecycle plane (certificates, credentials, backup): an SSO user SDDC Manager accepts
export SDDC_HOST=<sddc-manager-fqdn> SDDC_USERNAME=<user@sso-domain>
read -rs SDDC_PASSWORD && export SDDC_PASSWORD
# Operations plane (alert scope): the api-token flow from the identity chapter
export OPS_HOST=<ops-fqdn> OPS_BROKER_HOST=<broker-fqdn> OPS_API_TOKEN=<api-token>
# Tenancy plane (firewall floor, access, audit trail): an organization session
export VCFA_HOST=<automation-fqdn> VCFA_ORG=<organization> VCFA_USER=<account, without @domain>
read -rs VCFA_PASSWORD && export VCFA_PASSWORD
# How far back the audit trail must answer (optional; a shorter trail is a finding)
export AUDIT_MIN_DAYS=90
export OPS_TLS_VERIFY=false  # only on a self-signed lab CA

python3 hardening.py
```

Two details decide whether a plane reads or skips:

- **The Operations token's role must be allowed to export a policy.** A fleet API client holding
  only a viewer role lists the policies and is refused the export with HTTP 403, and the alert-scope
  read becomes a skip that quotes the refusal. A skip of this kind names an owner whose credential
  lacks a right, not a plane without an owner.
- **`VCFA_USER` is the bare account name.** The login principal is `<VCFA_USER>@<VCFA_ORG>`, so an
  account written as `user@domain` is refused at sign-in.

Exit code 0 when every read was made and none found anything, 1 when every read was made and findings are
present, and 2 when a read was skipped: the folder is incomplete, and a scheduler that watched only for
findings would file it as clean. Stdlib Python only.

## Fixes with dates

Every finding gets an owner and a fix with a date, and the harness keeps no state between runs, so the fix log is
a file you keep beside the posture folders: [`fix-log.csv`](fix-log.csv), one row per finding, with the run that
found it, the read, the owner (one per token plane: lifecycle, operations, tenancy), the fix, the date it was
fixed and the later run that no longer reports it. A row with no `fixed_on` is a risk somebody chose to keep; a
row with no `verified_by_run` is a fix nobody has read back.

## How far back the trail answers

The audit trail answers only as far back as its oldest event. The audit-trail read reports that event's date beside the count, and `AUDIT_MIN_DAYS` turns the
window you decided into a check: when the oldest event this session can read is younger than the
window, the run reports a finding. The read cannot say why a window is short (a retention setting,
a purge, a rebuilt service); it says how far back an investigation can go today.

## Three response shapes worth knowing

- **The policy export is the alert audit surface.** The policy settings API's `type` enum
  carries no alert-definition type, and enable/disable are write-only; which definitions the
  default policy enables reads from `GET /api/policies/export?id=` (a zip of
  `exportedPolicies.xml`, where each `<Alert enabled=...>` entry is one definition's state).
- **Backup encryption reads as absence.** An estate without the passphrase set returns no
  encryption key at all in the configuration; the finding is the missing key, not a false.
- **A project role binding has the Kubernetes RoleBinding shape.** Its `roleRef` and `subjects`
  sit at the top level beside `metadata`, and the object carries no `spec`.

## Expected output

See [`expected-output.md`](expected-output.md) for both reference runs and the folder shape.
