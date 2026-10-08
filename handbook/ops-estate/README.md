# Operations content as code: converge it, then audit it

Backs the operations-content chapter
([privatecloudarchitect.com/handbook/ops-estate](https://privatecloudarchitect.com/handbook/ops-estate)).

**What you get.** A declaration file your VCF Operations instance converges to, so a repair keeps every
reference; a naming standard you can measure; and a weekly read-only check that fails the day a reference
breaks. Stdlib Python 3, run against your own instance.

## Start here: audit what you have

Read-only. It changes nothing on the instance and writes one file, `content.json`.

```bash
export OPS_HOST=<your-ops-fqdn>
export OPS_BROKER_HOST=<your-broker-fqdn>    # omit if the broker shares the Ops FQDN
export OPS_API_TOKEN=<your-api-token>        # minted in the operations console; OPS_REALM defaults to CUSTOMER
export OPS_OWNER=<your-owner-prefix>         # the first field of every name you author
export OPS_NAMING=naming.example.json        # your bundles, kinds and scope values; copy it and edit
export OPS_TLS_VERIFY=false                  # only on a self-signed lab CA
python3 content.py
```

The api-token is exchanged at the identity broker for a short-lived bearer, the flow the handbook's Part 0
identity chapter teaches. On 9.1 the older username and password token-acquire flow is rejected for federated
users.

## The practices, and what makes each one easy

| Practice | What does it for you | How you know it is working |
|---|---|---|
| Name every object you author `<Owner> - <Bundle> - ...` in the grammar of its class, and rename it in place, never by a delete and a create | `naming.py` tests one name against its class's grammar; `content.py` counts, per class, the names that hold it | every class holds its grammar, read by meaning |
| Bring what you built under the converge, then change it only through the file; never fix drift by recreating | `export.py`, then `converge.py --state`; `cycle.py` proves the behavior on two throwaway objects | a converge run reports every object unchanged |
| Read a metric key on real objects before a formula depends on it | `content.py` probes a kind's catalog keys (`OPS_PROBE_KIND`, `OPS_CONTROL_KEY`); the chapter shows the stats query for one key | the keys your formulas use return a value on the objects they run on |
| Run the audit weekly and act the day a reference stops resolving | `content.py --check` exits 2 on any dangling reference | the scheduled job passes, week after week |
| Set every alert you rely on explicitly in the policy, and report the rest as unset | `content.py` counts what the default policy sets against what exists | the alerts you page on are all explicitly set, and your report shows three states |
| Keep what a dashboard reads in code, and log every dashboard import | `content.py` probes the dashboard and view read paths; `dashboard-imports.csv` is the log's header | every dashboard on every instance has a line in the log |

## One grammar per class

Every name starts with your owner prefix and the separator, then the registered bundle the object ships in.
What follows depends on the class, because each class carries different facts on the object itself:

| Class | Grammar | Example |
|---|---|---|
| super metric | `<Owner> - <Bundle> - <Kind> - <Measure> (<unit>)` | `PCA - Availability - Ping Instance - Reachability SLI (%)` |
| symptom or alert definition | `<Owner> - <Bundle> - <Kind> - <Condition>` | `PCA - Availability - FQDN Check - Unreachable` |
| custom group | `<Owner> - <Bundle> - <Scope> (<member kinds>)` | `PCA - WTPC - dedicated tier (Hosts)` |
| policy | `<Owner> - <Bundle> - <Scope>` | `PCA - WTPC - dedicated tier` |
| view or report definition | `<Owner> - <Bundle> - <Subject>` | `PCA - Rightsizing - Oversized Candidates` |
| dashboard | `<Owner> - <Bundle> - <Question or audience>` | `PCA - Rightsizing - Readiness` |
| notification rule | `<Owner> - <Bundle> - <Route>` | |

The separator ` - ` appears in no field. Parentheses carry a unit or a group's member kinds. A per-scope copy of
a definition, view or dashboard ends in one `[<scope>]` qualifier, as in
`PCA - WTPC - Host - CPU Overcommit Position [dedicated tier]`; a scope value (a posture, a tier) appears only
there or as a group's or policy's own scope field, never inside a measure or a condition.

```bash
python3 naming.py --vocabulary naming.example.json "PCA - Example - VM - CPU Ready (%)" "super metric"
python3 test_naming.py                             # the checker's own cases
```

`naming.example.json` is the vocabulary the checker reads: your owner prefix, your registered bundles, your
kinds with the resource kind keys each one names, and your scope values. Copy it, edit it, and point
`OPS_NAMING` at your copy so the audit checks kinds and scope values as well as shape.

**Rename in place.** Change the name on the object, never by a delete and a create, which gives it a new id and
leaves whatever referred to it pointing at nothing. A super metric, a custom group, a symptom definition and an
alert definition each take a `PUT` of the whole object, read by id, with the new name, and keep their id. Read a
custom group with `includePolicy=true` and send its `policy` back: the `PUT` replaces the whole group, and a body
without it unbinds the policy. Rename a policy in the console, which keeps its id. A view or a dashboard has no
update call: re-import it under its new name (a view carries its id and updates in place; after a dashboard
import, delete the old copy if both remain).

## Bring what you already built under the converge

```bash
export OPS_OWNER=<your-owner-prefix>
python3 export.py > mine.json                      # read-only; the super metrics named '<owner> - ...'
python3 converge.py --state mine.json --dry-run    # expect every object "unchanged"
```

A dry run that reports every exported object unchanged is the proof that the converge has adopted what you built
by hand, by name, without touching it. From then on `mine.json` is the source: edit it, run the dry run to see
the change, then converge. `converge.py` creates and updates; it never deletes, and `teardown.py` is bound to the
demonstration declaration so it can never be pointed at your own content.

The list read returns `>` and `<` as `&gt;` and `&lt;` in both the formula and the description. `export.py`
writes the decoded text and `converge.py` compares decoded text; compared raw, every super metric with a
comparison operator would read as drifted and be rewritten on every run.

This companion converges super metrics. The reference estate runs the same converge across tags, groups,
policies, super metrics, views and alerts, in dependency order; these files are its smallest complete form.

## Prove the converge on your instance: `cycle.py`

```bash
python3 cycle.py
```

One command runs the whole cycle against the two demonstration super metrics in `desired-state.json`, each step
the command you would type yourself:

1. `converge.py --dry-run` reads only and shows what would change.
2. `converge.py` creates what is absent.
3. `converge.py` again reports every object unchanged: a converged estate is a no-op.
4. After one formula and another object's description are edited, `converge.py` repairs both in place, reads each
   back, and each object keeps its id.
5. After the other object is deleted outside the converge, `converge.py` creates it again, and it comes back
   with a new id: the failure a rebuild by teardown causes, shown on an object the script made.
6. `teardown.py` deletes only the declared names and reads back to confirm.
7. Read-only: `export.py`, then `converge.py --state mine.json --dry-run` on what you already built.

The formula edit is made in a temporary copy of this folder, so `desired-state.json` is never changed. The
script reads the super metric list itself between steps, so "id kept" and "new id" are checked against the
instance rather than taken from a script's message, and it reads once more after the teardown for residue. It
refuses to start if either demonstration name already exists, and if any step fails the teardown still runs.
It writes `converge-run.json` and exits 0 only when every behavior held.

The two demonstration super metrics compute active and consumed guest memory in GiB from stock metric keys. No
policy enables them, so they compute nothing and page nobody.

## Run the check on a schedule

```cron
# Mondays 06:00: audit the estate, and fail the job when any reference is dangling
0 6 * * 1  cd /path/to/ops-estate && python3 content.py --check
```

Give the job the environment above. On a healthy estate the check passes every week, which is what makes a
failure worth acting on. One way it fails is an object recreated rather than repaired, which comes back with a
new id and leaves whatever referred to it pointing at nothing; step 5 of `cycle.py` shows the new id.

## Log every dashboard import

Dashboards and views have no read path in the suite API (the audit's last probe shows which paths were tried),
so nothing on the instance can tell you which dashboard is where. Keep the log yourself, one line per import:

```csv
imported_utc,instance,dashboard,source_file,source_revision,imported_by
```

`dashboard-imports.csv` is that header. Keep the definitions the dashboard reads (super metrics, groups, views'
inputs) in files the converge owns, and treat the dashboard itself as a build artifact imported by hand.

## What the audit reports

1. **How much is there, and how much of it is yours.** Every content class the suite API serves, each walked
   to its declared total, never to one page. Your own content is usually a small share of the instance, and
   you cannot rename the rest, which is why a parseable name is the only way to find yours.
2. **Whether your names hold their grammar.** Per class, how many names hold the grammar of their class by
   meaning (`naming.py`: the field count for the class, the kind against your vocabulary, the qualifier's form,
   and no scope value outside a scope field or qualifier), with every failing name and its reasons. Beside it,
   how many have four or more fields, the number a separator count alone would publish. A class that diverges
   **consistently** is the standard being wrong about that class; a class that diverges in ones and twos is
   drift. A total cannot tell those apart.
3. **Whether every reference resolves.** Alert definition to symptom definition, custom group to policy,
   notification rule to alert definition.
4. **What the default policy decides.** The alert definitions present against the ones the default policy
   sets. Everything else is UNSET, a third origin and not a synonym for disabled. A custom policy may set
   alerts for the groups it governs; those are not in this count.
5. **What has no read surface.** Every candidate path for a dashboard or a view, with its answer.
6. **Which catalog keys actually return a value**, for the kind in `OPS_PROBE_KIND` (default `VirtualMachine`),
   checked against `OPS_CONTROL_KEY`, a key you know returns a value on that kind (default `cpu|readyPct`).

The record names the product build it was read from, and carries the summary the run printed, so a figure can
be compared across upgrades.

### Three ways the audit answered wrongly at first

- **A negated reference is still a reference.** A symptom id inside an alert definition may carry a leading
  `!`, which negates it. Resolve the id without the marker, or a healthy estate reports every negated
  reference as broken.
- **A filter can be an object, not a list.** `rules[].alertDefinitionIdFilters` is an object carrying a
  `values` array. Iterating the object yields its field names and reports those as dangling ids.
- **Ownership is the prefix AND the separator.** Testing for `PCA` also claims a vendor object called
  `PCAP Export Purge Failure`. The test is `PCA - `.

### Alert state

There is no JSON surface for it. The policy export is the read path, it must be requested with
`Accept: application/zip` (any other accept type answers a 500 that means "cannot determine", never anything
about the policy), and the archive carries the policy's whole ancestor chain. Alert state has **three
origins**, not two states: LOCAL, INHERITED and UNSET, and UNSET must be reported as null rather than as
enabled. `content.py` counts explicit entries; the full contract is the field guide the chapter cites.

### Present is not populated

The statkey describe for a resource kind is a **catalog**, not an inventory. `content.py` reads it, probes
every key it lists against objects known to collect, and reports how many returned a value and how many did
not; nothing in the describe distinguishes the two. A metric built on a key that returns nothing validates,
saves, activates, and renders an empty panel with nothing to diagnose.

The describe is not the whole vocabulary either. Configuration and state largely live on the properties API
(`GET /api/resources/{id}/properties`), which the statkey catalog never lists, and the record counts the
property names that appear in no describe at all. Ask the wrong surface and you get an empty result with
HTTP 200, which reads exactly like absence.

The prefix does not tell you which surface to ask. `config|hardware|num_Cpu` is a **metric** and
`config|hardware|numCpu` is a **property**: one underscore apart, same object type, same prefix, and each
silent on the other's surface. So the probe asks both and records which one answered. A key known to
populate is read beside every probe, because a query that answers zero for everything is a broken query and
looks exactly like a discovery.

## Scope, stated plainly

- `content.py`, `export.py` and `naming.py` change nothing; `naming.py` makes no network call at all. Their calls are GETs, plus POSTs that write nothing: the
  broker's token exchange and, in `content.py`, the stats query.
- `cycle.py`, `converge.py` and `teardown.py` write to your instance. `cycle.py` and `teardown.py` touch only
  the two demonstration super metrics declared in `desired-state.json`; `converge.py --state` creates and
  updates the super metrics in the file you give it, and deletes nothing.
- The absence claim about dashboards and views is scoped to the paths probed, and the record carries each
  path with its status so a later build can be rechecked rather than believed.
- **Only your own object names are published.** Every other object on the instance appears as a count: an
  estate's object names are its own business, and the audit does not need them.

## Reading the records

The two records in this folder are the reference estate's runs; each carries its capture time and build.

`content.json`: `census` is one row per class with the total, how many are yours, how many hold their grammar
by meaning (`conformingByMeaning`, with each failing name and its reasons) and how many have four or more fields
(`conformingToSchema`), and a histogram of how many fields your names actually carry. `totals` is the three headline numbers. `ownedNames`
is the full list of your objects, which is the inventory a parseable name buys you. `integrity` carries the
reference count per edge type with the dangling count, plus `negatedSymptomReferences` so the negation marker
is visible in the data. `definedVersusSet` is the alert gap under the default policy. `noReadSurface` is the
probe, path by path. `presenceVersusPopulation` is the catalog probe. `report` is the summary the run printed.

`converge-run.json`: `steps` is each command with its exit code and output, `drift` the formula edit,
`idPreservedAcrossDriftRepair` whether the repaired object kept its id, `recreate` whether the object deleted
outside the converge came back with a new one, `residueAfterTeardown` how many demonstration objects were left,
and `adoption` what the dry run reported for the super metrics already on the instance. All of those are read
from the instance by the script, not taken from the other scripts' messages. `expected-output.md` is the same
run as a transcript.
