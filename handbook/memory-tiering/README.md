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

Two artifact forms ship in `supermetrics/`:

- `editor-formulas.yaml`: each metric's exact formula in super-metric editor syntax, its object
  types, and its unit, for building the metrics by hand in the editor.
- `memory-tiering-supermetrics.import.json`: the canonical import form, an id-keyed map carrying
  `resourceKinds` (the object-type association) and `unitId` alongside name, formula, and
  description. On a clean instance, import it through Administration, Content, Import
  (super metrics), and the metrics land already unit-labelled and object-type-associated. The
  ids are preserved on import, which is what lets views and dashboards reference the metrics
  by id in a later wave. Alternatively, create each metric over REST
  (`POST /api/supermetrics` with the entry's name, formula, and description) and assign its
  object types afterward; that path mints new ids on your instance.

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
