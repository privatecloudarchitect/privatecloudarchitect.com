# What this platform can and cannot put a clock on

Companion to the chapter
([privatecloudarchitect.com/handbook/temporary-elevation](https://privatecloudarchitect.com/handbook/temporary-elevation)):
one script that checks the claim the whole elevation design rests on, instead of repeating it. Stdlib Python
only; no token is printed or written.

| File | What it is |
|---|---|
| `elevation.py` | Asks your build what it can time-box: every policy type the plane declares with its schema scanned for any field that could hold a deadline, the complete field list of every object that grants access, and the deployment fields that **do** carry a time bound. With `--probe-elevation <binding name>` it also moves one binding you name up a role and puts it back, reading the object directly after every step. Writes `elevation.json`. |
| `elevation.json` | That record from the reference estate, 2026-09-18. The chapter's plates render it. |

## Run it

```bash
export VCFA_HOST=<automation-fqdn> VCFA_ORG=<org>
export VCFA_REFRESH_TOKEN_FILE=/path/to/refresh-token   # mode 0600
export TLS_VERIFY=false                                 # only on a self-signed lab CA

python3 elevation.py                                    # read-only
python3 elevation.py --probe-elevation cci:group:SomeTestGroup
```

## Why an enumeration rather than an assertion

"There is nowhere to put an expiry" is an absence claim, and an absence claim carries the same burden as a
positive one. So the script lists every field of every object that grants access and every policy type's
schema, and the emptiness of `anyExpiryField` is then something you can check rather than something you are
told. A lease **does** exist on this platform: it bounds a deployment's life, not a person's reach, and that
difference is the chapter.

## About `--probe-elevation`

This elevates a **real** binding for a few seconds and puts it back, because whether a role can be changed in
place and changed back is what decides if a guaranteed revert is possible at all. The script:

- **refuses to run without a binding named explicitly.** It will not choose a subject for you;
- captures the prior role before touching anything;
- restores it, and **verifies the restore with a direct read of the object**, not with a listing. A listing
  answered stale once during development and reported a revert that had not happened;
- reports whether the plane honoured a server-side dry run. It does not, and it does not refuse one either,
  which is the most expensive fact in this chapter.

Point it at a binding you created for the purpose. Without the flag nothing here writes.

## Scope, stated plainly

- Read-only by default; the probe flag is the only writer and it states what it sends.
- The findings are about **this build**. A recorded refusal is a claim about a version, not a safety interlock.
- Every organization, project and subject name in the record is a placeholder, and the script refuses to write
  a record in which one survived.

## Reading the record

`policyTypes` is one row per declared policy type with `timeBoundedFields` (what its schema could hold) and
what it governs. `access` is the enumeration: the field lists of a ProjectRoleBinding and a ProjectRole, the
published roles, the binding count, and `anyExpiryField`, which is the claim made checkable.
`deploymentLeaseFields` is the time bound that does exist, on the other kind of object. `elevation` is present
only when the probe ran, and carries each step with the read-back that followed it.
