# WTPC starter estate

The adoptable framework estate behind the Well-Tuned Private Cloud chapter series
([privatecloudarchitect.com/handbook/wtpc](https://privatecloudarchitect.com/handbook/wtpc)).
Where a harness proves one sheet's claims and leaves your estate as it found it, this directory
converges desired state you intend to keep: the posture catalog, the tag taxonomy, and the
generators and reconcilers that build the groups, policies, super metrics, views, dashboards, and
alerts of the framework on your own VCF Operations instance.

Proven by a full converge, verify, scoped-teardown, re-converge round trip on a live VCF
Operations 9.1 estate on 2026-08-15, on exactly these bytes.

## What adopting means

Everything here is level-triggered desired-state reconciliation. Every object is adopted-or-created
against its stable NAME (`PCA - WTPC - ...`, `PCA - Shared - ...`, `PCA - Rightsizing - ...`), so a
re-run converges instead of duplicating, and instance ids are output records, never inputs. The
portable key is the generators plus the data files; the id-bearing records they emit
(`supermetrics.*.yaml`, `groups.*.yaml`, `policies.*.yaml`) describe YOUR instance and regenerate
on any other.

Dependencies: Python 3 plus exactly one library, `PyYAML` (`pip install pyyaml`). Nothing else.

## Environment

```bash
# VCF Operations (all Operations steps) - the api-token flow the handbook's Part 0 chapter teaches
export OPS_HOST=<ops-fqdn> OPS_BROKER_HOST=<broker-fqdn> OPS_API_TOKEN=<api-token>
# vCenter (the tag-definition step only)
export VCENTER_HOST=<vcenter-fqdn> VCENTER_USERNAME=<sso-user> VCENTER_PASSWORD=<password>
export OPS_TLS_VERIFY=false  # only on a self-signed lab CA
```

`OPS_REALM` defaults to `CUSTOMER`; `VCENTER_TLS_VERIFY` defaults to `OPS_TLS_VERIFY`.

## Tags

Three vCenter tag categories drive posture membership, declared in `taxonomy.yaml` (concept,
live category name, object scope, closed value list):

| Concept | Values | Meaning |
|---|---|---|
| `env` | `prod` / `stage` / `dev` / `test` / `dr` / `lab` | environment tier |
| `function` | `db` / `web` / `app` / `vdi` / `k8s` / `infra` | workload archetype |
| `sla` | `sla-1` (latency-critical) ... `sla-4` (best-effort) | service-domain SLA |

If your estate already carries a taxonomy or namespaces its category names, rename the `category`
fields in `taxonomy.yaml` (or point `WTPC_TAXONOMY` at an alternate copy) - every script resolves
concept to category through that file, and no posture or script ever edits. Group rules match the
exact `category|value` strings, so after tagging a canary object read its `summary|tag` property
in Operations and confirm the strings before you expect members. Membership follows tagging on the
group re-resolution interval (minutes, not seconds).

## Reproduce (the adopt recipe)

`apply.py` sequences everything; run it once in dry-run and read the plan before executing:

```bash
python3 apply.py                                 # dry-run by default: every step previews, nothing mutates
python3 apply.py prod-latency-critical-db --create --execute    # bootstrap the strict exemplar
python3 apply.py --execute                       # converge the exemplar pair (no-op once converged)
```

The order it drives, and what each step is:

1. `ensure_tag_definitions.py` - the three categories + values, natively on the vCenter.
2. `adopt_shared.py` - the shared and lens super metrics posture content references, upserted by
   name; emits `supermetrics.shared.yaml` and regenerates the lens view for YOUR instance ids.
3. `instantiate_posture.py postures/<P>.yaml` - the posture's three groups (VMs by tag rule;
   Hosts and Clusters born empty, derived next).
4. `reconcile_policy.py --posture <P> [--create <P>]` - adopt-or-create the posture policy (a
   clone of your Default), global priority strict-first, group bindings.
5. `build.py postures/<P>.yaml` - the posture's super-metric DAG, created and activated in the
   posture policy programmatically.
6. `reconcile_infra_groups.py --posture <P>` - Host and Cluster membership derived from where the
   tagged VMs actually run (membership follows the workload; no infrastructure re-tagging for posture membership).
7. `apply_policy_capacity.py` - each policy's capacity allocation, PATCHed from the envelope.
8. `build_alerts.py` + `deploy_alerts.py` - the alert bundle, built offline from `alerts.yaml`
   and the exemplar's SM record, then enabled in the posture policy ONLY and disabled in
   Default: per-policy enablement is the scoping, and an alert left enabled in Default pages on
   every object in the fleet.

Views and dashboards are offline generators, run after a posture's SMs exist, then imported
through the UI (`Views / Dashboards > Manage > Import`) - views before dashboards, because a
dashboard references its views by id:

```bash
python3 build_views.py <posture>          # the five per-posture ViewDefs
python3 build_view_bundles.py             # one-click per-posture view bundles
python3 build_dashboard.py <posture> --resolve-groups   # the scorecard, widgets scoped to YOUR group ids
```

Import order: the lens bundle (`content/wtpc-views-lens-oversized.import.zip`), the posture's view
bundle, then the posture's dashboard zip. Regeneration is the adoption path by design: views read
super metrics by id and ids mint per instance, so imported content built from another instance's
records would render blank. Id-preserving import is the same-instance restore and cross-instance
transfer path, not the adoption path.

## Verify

`apply.py` ends with the read-only gates, also runnable alone:

```bash
python3 governance.py --priority-parity   # posture policies ranked strict-first, live
python3 governance.py --config-parity     # live capacity allocation matches the envelope payloads
python3 validate_live.py --posture <P>    # every member's effective policy IS the posture policy
python3 reconcile_infra_groups.py --analyze   # occupancy, mixed-posture feasibility, reservations
python3 compliance_rollup.py              # one ranked row per posture on the normalized scale
```

## Teardown, scoped

`destroy.py` is the deliberate inverse, never a build phase: reverse dependency order, only
objects carrying the WTPC name marker, re-checked immediately before each DELETE. `--posture <P>`
scopes to one posture; a full wipe additionally demands `--yes-full-teardown`. Three things are
left intact by design: the tag categories (remove with `ensure_tag_definitions.py --teardown`
after detaching assignments), the `PCA - Shared - *` / `PCA - Rightsizing - *` super metrics
(other content may consume them; delete by name if you truly mean to), and any UI-imported views
and dashboards (remove in the UI).

## Files

`postures/*.yaml` are the portable posture sources (envelope, membership, policy, stable content
ids) - the catalog the sheet's table publishes, plus three further proposed postures. `alerts.yaml`
and `shared/supermetrics.yaml` are the portable alert and shared-SM sources. `taxonomy.yaml` is
yours to edit. Generated per-instance: the `supermetrics.*.yaml` / `groups.*.yaml` /
`policies.*.yaml` records, `content/` views and bundles and dashboards, and
`.reconcile-state.json` (the infra reconciler's dwell bookkeeping; keep it out of version
control). One super-metric caveat: the REST surface carries no display-unit field, so confirm
units once in the UI per the generators' record comments.

## What this slice does not carry (yet)

The hardware-tier unit (tier catalogs, tier policies, host tier alerts) and the cross-posture
estate governance hub are later slices of the same framework; the posture sources already carry
`min_tier` fields those slices consume. Nothing in this slice depends on them.
