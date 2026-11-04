# The adopter's companion

The Architect's NOC companion (DEC-01): the reader's own console over the strategy layer (charter section 6; `40-BREADTH.md` step 9). It reads an estate
through the records its companions wrote and the drift-read adapters, and the estate's portfolio; holds no credential
and opens no connection; runs the gates that judge a portfolio without publishing; and emits, scrubbed, the role-by-role
adoption view against the bar, the drift and exceptions, the ranked board, and a brief per department that stays
private. The layer's generator does the computing (core, models, policy, migrate, drift, gates, scrublist); this package
adds the command line, the sources built from passed paths, the static clause split, the role grade fold, its own layout
and views, and the refusals. It imports no renderer and reads no site file.

## Run

```bash
python -m companion.adopt --root ROOT --run RUN --portfolio PATH --records DIR --scrub-list PATH --vocabulary PATH \
                         [--register PATH] [--policy PATH] [--import PATH] [--day YYYY-MM-DD]
```

| Input | What it is |
|---|---|
| `--root` | the layer's folder the code and files are read from: `docs/design/enterprise-strategy-layer` in this repository, `handbook/strategy/` in the companion repository's mirror; never derived from where this file sits |
| `--run` | the run folder, the one place the run writes: `views/` (index, adoption, drift, board), `gates.json`, `private/` (the department briefs, the raw drift lines, the import's values, `provenance.json` with the paths as given); the run writes `private/` into the folder's own `.gitignore` |
| `--portfolio` | the estate's portfolio (schema 5, or the schema before it; an older one is told so and refused, exit 3) |
| `--records` | a folder holding `pins.yaml` and the record copies it names, flat, each found by its basename (`fixtures/adopter/records/` is the form); a companion the estate did not run gives its declarations not covered, never a failed check |
| `--scrub-list` | the estate identifiers never to reach a view: a `.py` holding `KILL_LIST` and `KILLLIST_ALLOW` (read as data with `ast`, never run) or a `.yaml` holding `kill` (a regular expression) and `allow` (values spared). Addresses are caught only through this list: list your ranges |
| `--vocabulary` | the site vocabulary a strategy release wrote (`generator/vocabulary.py`: the jobs, competencies, phases, pages and ladder rungs the gates hold a register to), so no site file is read |
| `--import` | a stand-in export of a system of record: `{"supplies": {field: [address prefixes]}, "values": {...}}`; its values land in `RUN/private/imported.json`, never in the portfolio; a portfolio node under a supplied path, or a supplied field `ownership.imports` does not name, is refused (GATE-14, 14.9) |
| `--day` | the day the date clauses (13.1, 13.2) judge at; the run's UTC date otherwise, recorded in every view's provenance |
| `--register`, `--policy` | the register and the policy to judge against: the root's own files in this repository, or, where the root holds none, the pinned copies under `companion/pinned/` (the companion repository's mirror ships them there, beside `pins.json`); pass a path to judge against another |

## Exit

The identity companions' contract (0 nothing to act on, 3 a read that failed or a result not known, 5 a usage error),
with 1 and 2 as this script's own:

- 0: every clause the companion covers passed and nothing was refused.
- 1: a covered clause refused; the views still render, the findings in `gates.json`.
- 2: a refusal before any view renders: two departments for one role in one scope; an illustrative value in an
  adopter's portfolio; an override of an entry not overridable, one-way or without its decision; a node under a path the
  run's import supplies, or an import supplying a field the portfolio does not import. The portfolio was read and
  judged, which is why this is 2 and not 5.
- 3: an input the run could not read, the files not loading through their models, or a portfolio two or more schemas
  behind, nothing known from it; or a covered clause its gate could not judge, `not_judged` in `gates.json` with the
  reason (the views render, the result is not known).
- 5: a usage error, refused before anything is read.

## What a run judges, and what it reports not covered

The clause split is static (`split.py`): every clause of the charter's section 8 has one judge. The companion judges the
clauses that read the portfolio, the register as mirrored and the policy; every other clause is reported in `gates.json`
by id with its reason, as not covered, on every run: a clause that judges a served view or the reference portfolio's
approvals (which an adopter's run has none of), and a clause that judges the register against the site, the code against
git, or the layer's own scheduled reads, which only the repository's run judges. The run passes the covered set to the
gates (`Sources.clauses`), and a gate skips the reads of a clause it does not judge, so a repository file the mirror
does not hold never leaves a gate's other clauses unjudged. Not covered is never passed, and a covered clause whose
gate could not judge, whose gate did not run, or (13.1, 13.2) whose date run did not happen, is reported `not_judged`
with the reason, never passed; a clause of a gate the split does not name is refused when the split loads, never
covered by default.

## The reference run, and an adopter's

A portfolio is the reference one only when its sha256 is a digest `pinned/pins.json` records (the working file's at the
pin, or the projected copy's); every other portfolio is an adopter's, whatever its `estate` says, and an illustrative
value in it is refused. The pinned copies under `pinned/` (the register, the policy, the served projection of the
reference portfolio) are written by `generator/pin_companion.py --write` in a strategy release and are what step 12
mirrors to the companion repository, never the live files.

An estate's own initiative (`local_initiatives`) is defined and judged (GATE-4, GATE-11, with the trigger event that
spawned it) but is not ranked: the board ranks the register's initiatives the estate plans, and a plan for an estate's
own initiative is a later change to the core.

## The synthetic adopter

`fixtures/adopter/` is a worked example an adopter can start from: a portfolio of measured and input values only, each
input naming its supplier; one estate-local initiative its own trigger event spawned; a role assigned to two departments
in two scopes; two exceptions, one expired and one renewed twice; two small records in the shapes the host-lifecycle and
platform-backup adapters read, with their own `pins.yaml`; and `export.json`, a stand-in export that supplies the
investment and effort the portfolio also types, so a run with `--import` is refused (the test of 14.9).
