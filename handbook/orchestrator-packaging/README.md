# Packaging: check workflows and actions on your machine

Companion to the chapter
([privatecloudarchitect.com/handbook/orchestrator-packaging](https://privatecloudarchitect.com/handbook/orchestrator-packaging)):
one script that holds Orchestrator workflows and actions to the format rules before any import, so a format error
costs a line number instead of a round trip to the appliance. Python 3 standard library only; no network, no
credentials, nothing uploaded.

| File | What it is |
|---|---|
| `validate_content.py` | Walks the files and folders you name and checks every workflow (`.workflow` package or its XML), action (`.action` package or its XML) and `metadata.json` it finds. Prints each finding as `file:line: rule level: message`, a summary by rule, and with `--record` a counts-only record. |
| `metadata.example.json` | The shape of an action's interface, written before its code: a name, typed and described inputs, and the fields the result carries. `validate_content.py` checks any `metadata.json` against it (R12). |
| `fixtures/` | Workflows, actions and a metadata file that each break chosen rules, with `expected.json`, the findings they must produce. The packaged fixtures are kept as text members and zipped when the self-test runs. |
| `records/findings.json` | The validator run over the reference estate's Orchestrator content on 2026-10-21: counts by kind and rule, no file name and no content. |
| `expected-output.md` | What the self-test and that run printed. |

## Run it

```bash
python3 validate_content.py --self-test                     # the fixtures against expected.json, offline
python3 validate_content.py path/to/content/                # every workflow, action and metadata.json under it
python3 validate_content.py path/to/content/ --creator com.example.platform --record findings.json
```

In a pipeline, run it over the folder that holds your content on every commit and fail the build on a non-zero
exit. A clean file prints nothing but the summary.

| Exit | Meaning |
|---|---|
| 0 | no error; warnings and notes may be printed |
| 1 | at least one error |
| 2 | a path is missing, or the command was used wrongly |

## The rules

| Rule | Level | Applies to | What it checks |
|---|---|---|---|
| R1 | error | workflows | display names, descriptions, scripts and values are wrapped in character data, not written as text |
| R2 | error | workflows | a decision names an onward and an alternative onward item, has a script and an output binding element (a script with no `return` is a warning) |
| R3 | error | workflows | every canvas position is decimal on both coordinates |
| R4 | warning | workflows | each input binding names a variable the workflow declares; a workflow-scoped variable is invisible to the check, so it warns |
| R5 | error | workflows | a SecureString attribute carries no value element |
| R6 | error | both | the document parses (and a file holding JSON, such as an API response saved as content, is named as such) |
| R7 | warning | both | script text is ASCII: the VCF Operations 9.1.1.0 release notes warn that a script carrying Unicode characters comes back as a hex-encoded string after package export and import |
| R8 | error | packages | the info member's declared charset matches the content member: UTF-16 when it opens with a byte-order mark, else UTF-8 |
| R9 | note | packages | the creator in the info member; with `--creator NAME`, a different creator is a warning |
| R10 | error | actions | the action name starts with a letter and holds only letters, digits and underscores |
| R11 | warning | actions | every parameter carries a description, and the module declares a result type |
| R12 | error | `metadata.json` | a name that passes R10, and every input and output named, typed and described |

R1 to R6 are the workflow rules this platform's content was built to, generalized from the validator written
alongside the operator's deploy script. They are this tool's rules: which of them the appliance refuses today was
not re-tested, so read a clean run as "meets these rules", not as "the import will succeed".

## Scope, stated plainly

- Offline and read-only: it opens files, never writes them, and never contacts an appliance.
- The record holds counts by kind and rule only; no file name, path, script or value enters it.
- A run is a check of format, not of behavior. Whether the actions a workflow names exist on your appliance, and
  whether a configuration identifier resolves there, is the deploy's read-back, in the chapter on dependencies.
