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

What to read in it:

- **No workflow broke R1 to R6.** The content was built to those rules, so this is the expected result for it, and
  a first run on content built another way is where the findings appear.
- **Sixteen R7 warnings:** scripts in the workflows hold non-ASCII characters (an emoji, box-drawing lines). That is
  the case the VCF Operations 9.1.1.0 release notes warn comes back from an export as a hex-encoded string.
- **Two R6 errors** are two files that hold JSON, saved from the API under a workflow's file names. The validator
  names them as JSON rather than reporting a broken workflow.
- **Twelve packages keep the platform's default creator** and four carry another; `--creator` turns the first kind
  into a warning when your convention is a creator of your own.
