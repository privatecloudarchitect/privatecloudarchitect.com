# Drift: keep a committed copy of each workflow in step with what runs

Companion to the chapter
([privatecloudarchitect.com/handbook/orchestrator-drift](https://privatecloudarchitect.com/handbook/orchestrator-drift)):
one script that keeps a version-controlled copy of each Orchestrator workflow you own, tells you the day the
appliance stops running it, and puts it back. Python 3 standard library only.

| File | What it is |
|---|---|
| `reconcile.py` | Fetches a workflow's running definition into a normalized committed copy, diffs the copy against what runs (exit 1 on drift), and deploys the copy: a plan by default, `--apply` to send it. |
| `fixtures/` | A small workflow three ways (committed, the same with its keys reordered, and with one value edited) and an executions answer, for the offline self-test. |
| `records/` | The four runs on the reference estate on 2026-10-21, as counts with no name and no id: the drift found, the restore, the agreement after it, and an idempotent re-run that sent nothing. |
| `expected-output.md` | What the self-test and those runs printed. |

## Run it

```bash
export VRO_HOST=orchestrator.example.net
export VRO_TOKEN_FILE=~/.secrets/vro-token     # a bearer this appliance accepts, in a file of mode 0600
export TLS_VERIFY=false                         # only if the appliance carries a private CA you have not installed

python3 reconcile.py --self-test                          # offline: normalization, the diff, the in-flight count, the reference scan
python3 reconcile.py "My workflow" --fetch                # seed or refresh canonical/My_workflow.json from what runs
python3 reconcile.py "My workflow" --diff                 # exit 1 when the copy and the appliance differ
python3 reconcile.py "My workflow" --deploy               # the plan: references, executions not ended, the lines that would change
python3 reconcile.py "My workflow" --deploy --apply       # send it, then read it back
```

`WORKFLOW` is an id or an exact name. Commit the `canonical/` folder. In a pipeline, run `--diff` for every
workflow you own before shipping and on a schedule, and fail the job on a non-zero exit: a workflow can drift with
nothing shipped, so the schedule is the part that finds it.

| Exit | Meaning |
|---|---|
| 0 | in agreement, or the operation done (a deploy with nothing to send sends nothing) |
| 1 | drift found |
| 2 | usage error, or a token file open to group or other |
| 3 | a call failed, or a deploy did not read back as sent |
| 4 | a pre-flight check refused the deploy and nothing was sent: the copy calls an action or reads a configuration element the appliance lacks, or an execution has not ended and `--allow-inflight` was not given |

## What the deploy checks before it sends

1. **References.** Every action the copy's scripts call (`System.getModule("<module>").<name>`) must be in the
   appliance's action list, and every configuration element an attribute reads must answer with the key named.
   A nested workflow call is not checked.
2. **Executions.** Any execution of the workflow in a state other than completed, failed or canceled counts as not
   ended. With one, `--apply` refuses unless you pass `--allow-inflight`. The executions list answers its states in
   lower case; a check written for upper-case names never counts anything.
3. **The diff.** With nothing to change it reports agreement and sends nothing, so a re-run is safe.

After the `PUT /workflows/{id}/content` it reads the definition back and compares it with the copy. On VCF
Automation 9.1.1 the embedded Orchestrator's version history gained a commit for the write.

## Scope, stated plainly

- `--fetch` and `--diff` only read. `--deploy` without `--apply` only reads.
- The record (`--record`) holds the operation and its counts: versions, item and attribute counts, diff lines,
  reference and execution counts, the write's status. No name, id, script or value enters it.
- The copy is a definition, not its history: it says what runs, not why. Keep design notes beside it.
- The records' `2-restore.json` came from the build before the full count: it capped `changedLines` at the 60 lines
  it printed. Its 858, like `diffLines` in `1-before.json`, was counted afterwards with the same functions from the
  two definitions as read.
