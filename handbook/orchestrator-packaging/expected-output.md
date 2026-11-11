# What validate_content.py printed

## The self-test, offline

`python3 validate_content.py --self-test`

```text
self-test OK: 6 fixture files reproduce the 18 expected findings exactly (11 errors), offline
```

## The reference estate's Orchestrator content, 2026-10-21

`python3 validate_content.py <content folder> --record findings.json`, over the folder that holds the reference
estate's workflows, packaged actions and action metadata. Only the summary lines are shown: each finding line names
a file of that estate. The record beside this file holds the same counts.

```text
scanned: {'action metadata': 10, 'action package': 12, 'unparsed document': 1, 'unparsed package': 1, 'workflow document': 3, 'workflow package': 4}
findings: R6 error 2, R7 warning 16, R9 note 16
creators: {'another': 4, "the platform's default": 12}
```

What to read in it, and in your own run:

- **R1 to R6 findings** (errors, and R4's warning) name a workflow that breaks a format rule, with its file and line.
  Content built to those rules shows none, so a first run on content built another way is where they appear.
- **R7 warnings** name scripts that hold non-ASCII characters (an emoji, box-drawing lines). That is the case the
  VCF Operations 9.1.1.0 release notes warn comes back from an export as a hex-encoded string.
- **An R6 error on a file that holds JSON**, such as a response saved from the API under a workflow's file name, is
  named as JSON rather than reported as a broken workflow.
- **R9 notes** count packages by creator; with `--creator NAME`, a package that carries another creator is a warning.
