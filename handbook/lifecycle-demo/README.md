# The hybrid self-service lifecycle, as it actually runs

This folder backs the demo walkthrough at
[privatecloudarchitect.com/demo/hybrid-app-lifecycle](https://privatecloudarchitect.com/demo/hybrid-app-lifecycle).

The published page is not a description of what the demo would do. It is a captured run: every step's
purpose, the file that implements it, the exact command or API call, and the results that came back,
lifted out of the transcript the demo prints while it runs.

## What `chronology.py` answers

> If I request a hybrid application (a database VM and a Kubernetes cluster in one namespace) through the
> platform's API, what exactly happens, in what order, and what does each step actually return?

It parses one or more captured run transcripts and emits `chronology.json`: the step skeleton
(`purpose`, `file`, `action`, `results`) plus the lifecycle stage banners, with every estate coordinate
replaced by a readable placeholder.

## Running it

```bash
# capture a run first; the demo prints this structure on stdout
./demo/01-create.sh <initials> --no-pause  | tee create.log
python3 lifecycle-story.py --tenant <initials> --execute --yes --no-pause | tee story.log

python3 chronology.py --transcript create.log --transcript story.log \
  --also-scrub <appliance fqdn>=automation-host
```

It reads your files and calls `pca lab context` for the coordinate list. It does not touch the estate.

## How the scrub works, and why the placeholders are words

Estate coordinates become `{{project}}`, `{{region}}`, `{{namespace}}` rather than `project-1`, because
the reader is meant to substitute their own and the **shape of the name is the lesson**. The application's
own name reads like a fictional example and is not one: it is the workload's name on the estate that ran,
so it publishes as `{{app}}`. The blueprint bundle's name is repository content rather than an estate
value, and stays as written.

The boundary permits an adjacent hyphen on purpose. An estate coordinate is usually a *component* of a
generated name rather than a standalone token, so `<app>-<env>-<project>` renders as
`{{app}}-dev-{{project}}` and the convention stays legible with the estate out of it.

**The script names no estate value of its own.** What it can learn it learns, from `pca lab context` and
from the run's own output: the namespace and deployment shapes, the application stem inside them, every
kubeconfig context the run mentioned (not only the one configured now, because a tool that falls back to
a stale context prints the name it tried), and any hostname that is not the platform's own vocabulary.
What that leaves is passed in with `--also-scrub value=label`, and a forgotten one is not silent: the
survivor checks fail the run and say what to pass.

Four things the script refuses to do:

- write a record in which an estate value survived, including the **stem** of a generated name (a suffix
  makes the full name unique, and matching only the full name lets the stem through);
- write a record in which a hostname survived that is not the platform's own vocabulary, which is the
  case the check above it cannot see: a coordinate nobody registered is not in the list being checked;
- write a record in which the platform's own vocabulary was eaten by the scrub, which is how a record
  stops teaching;
- write a record at all when no deploy context resolved, because that silently makes the scrub a no-op
  and produces a clean-looking file full of estate values.

## Reading `chronology.json`

| field | meaning |
|---|---|
| `runs[].source` | which transcript this came from |
| `runs[].steps[]` | `step`, `title`, `purpose`, `file`, `action`, `results[]` |
| `runs[].steps[].results[].mark` | the run's own marker: `✓` observed, `⚠` warned, `✗` failed, `ℹ` narration |
| `runs[].stages[]` | the lifecycle arc the story script narrates, with who owns each stage |
| `estateCoordinatesReplaced` | the coordinate families the scrub registered, so you can see what was hidden |

Quoted output has em dashes normalised to commas. The published pages forbid the character and
assert on it at build time; this is a presentational change to a quoted string, not a factual one.

## The scope this does not cover

One run, on one estate, on one day. The timings are that run's and are not a promise: VKS provisioning
took about four minutes on the captured run and the script budgets thirty. A result marked `✓` means the
step reported success at the time, which is not the same as the workload being healthy, and the page
distinguishes the two where it matters.
