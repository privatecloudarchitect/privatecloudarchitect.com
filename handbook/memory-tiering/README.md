# Memory tiering candidacy: the lens's verdict metrics

The runnable companion to
[Memory tiering candidacy is an active-memory question](https://privatecloudarchitect.com/handbook/memory-tiering).
The three super metrics that produce the lens's verdicts, in the exact formulas proven live.

**Provenance:** formulas derived and validated against a live VCF Operations instance (11 hosts,
5 clusters, ESXi 9.1), 2026-07-02 through 2026-07-08, including the denominator correction the
sheet teaches. Thresholds (the 50 gate, the 80 trigger) are from the vSphere 9.1 memory-tiering
best-practices documentation.

## The three metrics

| Metric | Question it answers | Unit |
|---|---|---|
| Active pct of DRAM | Candidacy: is the hot working set inside the 0 to 50 gate? | percent |
| Recoverable Cold DRAM GB | Payoff: how much DRAM is backing cold pages tiering can relocate? | GB |
| Consumed pct of DRAM | Activation readiness: how close is consumption to the 80 trigger? | percent |

The artifacts, and the order they import in (metrics before views before the dashboard, because
each layer references the previous one by id):

- `supermetrics/editor-formulas.yaml`: the three verdict metrics' exact formulas in super-metric
  editor syntax, object types, and units, for building them by hand.
- `supermetrics/memory-tiering-supermetrics.import.json`: the readable form of the full six-metric
  set the lens's views reference: the three verdict metrics plus three qualifiers (reserved and
  pinned memory, NVMe tier size, NVMe tier used). Id-keyed; the ids are what the views bind to.
- `supermetrics/memory-tiering-supermetrics.contentpkg.zip`: the same six metrics as an
  **id-preserving content package**, importable via the content-import UI or
  `POST /suite-api/api/content/operations/import` (multipart field `contentFile`). The import
  creates any absent metric with its shipped id; the `force` flag affects only a metric that
  already exists: `force=false` skips it (safe, non-destructive), `force=true` overwrites it (only
  to push an update). The API defaults the flag to `true`/overwrite, so pass `force=false` for a
  non-destructive import. Built by filtering the reference instance's own export, so what ships is
  the export format verbatim; a no-force test-import on the reference instance recognized all six
  with zero failures and zero changes.
- `views/memory-tiering-views.contentpkg.zip`: the lens's three views (host candidates, capex
  avoidance, cluster readiness) as the same kind of id-preserving package; no-force test-import
  recognized all three, zero failures. The views reference the metrics by id, which is why the
  package pair imports in order.
- `dashboard/memory-tiering-readiness.import.zip`: the readiness dashboard in the Dashboards,
  Manage, Import shape (dashboard import is UI-only on this build; import the zip directly, do
  not unzip it). This is the reference estate's own deploy artifact: its runbook deploys exactly
  this file through Manage, Import, and the live dashboard matches the committed contents. It
  references the views and metrics by id, so import it last, after both packages. Blank rows
  right after import mean the super metrics are not yet activated in the collecting policy,
  which is the activation step above.

## The rules the formulas encode

- **The denominator is the DRAM tier's own capacity key**, never total memory capacity. On a host
  that already tiers, total capacity includes the NVMe tier and understates percent-of-DRAM by up
  to half at a 1:1 ratio, quietly qualifying hosts that should have failed the gate. Proven live.
- **Candidacy and activation readiness are two columns, not one.** Candidacy reads active against
  the 50 gate; readiness reads consumed against the 80 trigger. Reporting both is what turns
  "we activated it and nothing happened" into expected behavior.
- **The consumed-percent metric does not compute at cluster scope.** The DRAM-tier denominator
  does not roll up; proven live. Read it per host, or aggregate host values deliberately.

## Importing, and the step that is easy to miss

1. Import each super metric (or create it in the editor from `editor-formulas.yaml`, binding it
   to the object types listed there: hosts, rolling to clusters where the metric supports it).
2. **Activate each super metric in the policy that collects for its object types.** A super
   metric that exists but is not activated in the collecting policy collects nothing and raises
   no error; it simply stays empty. This is the single most common reason a freshly built lens
   shows no data.
3. First values appear after the following collection cycles (five minutes each by vendor
   default). Validate one host by hand before trusting a fleet-wide read: pick a host you know,
   and check the metric against its raw statkeys.
