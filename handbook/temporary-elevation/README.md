# What this platform can and cannot put a clock on

Companion to the chapter
([privatecloudarchitect.com/handbook/temporary-elevation](https://privatecloudarchitect.com/handbook/temporary-elevation)):
one script that checks the claim the whole elevation design rests on, instead of repeating it, and one that is
the design: the grant record, the broker's two gates and the scope reconciler. Stdlib Python only; no token or
password is printed or written, and every secret file open to group or other is refused unread.

| File | What it is |
|---|---|
| `elevation.py` | Asks your build what it can time-box: every policy type the plane declares, with every field its definition, target and scope schemas declare and the ones that could hold a time bound in the schema's own words; the published schema of the two kinds that grant access, checked against the objects; and the deployment fields that **do** carry a time bound. With `--probe-elevation <binding name>` it also moves one binding you name up a role and puts it back, reading the object directly after every step. Writes `elevation.json`. |
| `elevation.json` | That record from the reference estate on VCF Automation 9.1.1: the enumeration read 2026-10-22 at 09:50Z, and the probe block from the 09:49Z run with the flag, on a binding made for the test. The chapter's plates render it. |
| `broker.py` | The design as code you can read and run: `grant` (the approval writes the record; a scope grant records the baseline role at approval and refuses a non-member or an overlap), `check` (ownership first and absolute, then a live grant for a destructive action; prints a verdict, executes nothing), `reconcile` (the scope axis: plan by default, `--apply` writes in place and reads back, then writes a heartbeat), `heartbeat` (exits 1 when the reconciler has stopped or failed). |
| `expected-output.md` | What both scripts printed on the reference estate. |

## Run it

```bash
export VCFA_HOST=<automation-fqdn> VCFA_ORG=<org>
export VCFA_USER=<account> VCFA_PASSWORD_FILE=~/.secrets/vcfa   # mode 0600: a session login
# or, instead: export VCFA_REFRESH_TOKEN_FILE=~/.secrets/refresh  (mode 0600; a stored token can stop granting)
export TLS_VERIFY=false                                         # only on a self-signed lab CA

python3 elevation.py; echo "exit $?"                            # read-only
python3 elevation.py --probe-elevation 'cci:group:<test group>' --project <test project>
```

`elevation.py` exits 0 when the reads succeeded (and a probe put the binding back), 1 when a probe's revert did
**not** restore the role (put it back by hand), 2 on a missing setting or argument or a secret file open to group or
other, 3 when the sign-in or a read failed, and 4 when the record refused to write because an estate value survived.

## The broker

```bash
export VCFA_USER=<service identity> VCFA_PASSWORD_FILE=~/.secrets/broker   # the broker's own identity
export CALLER_USER=<member> CALLER_PASSWORD_FILE=~/.secrets/member         # check only: the person asking
export GRANTS_FILE=~/.elevation/grants.json HEARTBEAT_FILE=~/.elevation/heartbeat.json

python3 broker.py grant --principal <member> --action Deployment.Delete --hours 4 --approver <you> --reason "<why>"
python3 broker.py check --deployment <id> --action Deployment.Delete
python3 broker.py reconcile             # the scope axis's plan; --apply writes, and writes the heartbeat
python3 broker.py heartbeat --max-age-minutes 10
```

The two gates run in this order, and the order is the design. **Ownership** is absolute: the caller is resolved from
the caller's own sign-in, never from an argument, the owner is read by the broker's service identity, and a caller who
does not own the deployment is refused whatever grants they hold. **A live grant** is required only for an action on
the destructive allow-list (`Deployment.Delete`, `Deployment.PowerOff`; extend it in review). `check` prints the
verdict and executes nothing: your executor runs the action as the service identity after an ALLOW. The member never
holds the destructive right.

A scope grant records the role the member holds **at approval** as its baseline, so a second, overlapping grant cannot
record an already-raised role; the broker refuses the overlap. `reconcile --apply` raises a live grant's binding and
reverts an expired or revoked one with one server-side apply each, reads the object back, and leaves a failed write for
the next pass. Run it on a schedule, and alert on `heartbeat`: it is the one failure in this design that leaves
somebody elevated. The grants file is the broker's authority, so a grants file writable by group or other is refused.

`broker.py` exits 0 when a grant was written, a check allowed, nothing is due or the heartbeat is fresh; 1 when a grant
was refused, a check denied, a revert is due or a write failed, or the heartbeat is stale or failed; 2 on a missing
setting or argument or a refused file mode; and 3 when a sign-in or a read failed.

## Why an enumeration rather than an assertion

"There is nowhere to put an expiry" is an absence claim, and an absence claim carries the same burden as a
positive one. So the script lists every field each policy type's three schemas declare and every field the two
access kinds' published schema declares, and the emptiness of `anyExpiryField` is then something you can check
rather than something you are told. The schema is read rather than the objects alone because an object shows
only the fields that are set: an optional expiry left empty would appear on none of them.

Time bounds **do** exist on this platform, on two policy types: the lease bounds a deployment's life
(`leaseTermMax`, `leaseTotalTermMax`, `leaseGrace`, in days) and the approval policy bounds how long a request is
kept (`autoApprovalExpiry`). Neither bounds a person's reach, and that difference is the chapter.

An empty scan is not an absence. If a type's definition schema or an access kind's published schema cannot be
read, the script stops and writes no record, rather than reporting that it found nothing. The field-name pattern
only marks candidates; the record lists every field, so you can check the rest by reading it.

## About `--probe-elevation`

This elevates a **real** binding for a few seconds and puts it back, because whether a role can be changed in
place and changed back is what decides if a guaranteed revert is possible at all. The script:

- **refuses to run unless the binding and its project are both named explicitly.** It will not choose either;
- captures the prior role before touching anything;
- restores it, and **verifies the restore with a direct read of the object**, not with a listing. A listing
  answered stale once during development and reported a revert that had not happened;
- reports whether the plane honoured a server-side dry run. It does not, and it does not refuse one either,
  which is the most expensive fact in this chapter.

Point it at a binding you created for the purpose, and delete it afterwards. The binding has to name a principal
the identity provider knows: a create naming an unknown group is refused with HTTP 400, "There are principals that are
not present in the Identity provider". Without the flag nothing here writes.

## Scope, stated plainly

- `elevation.py` is read-only by default; its probe flag is its only writer and it states what it sends. `broker.py`
  writes only its local grants and heartbeat files, apart from `reconcile --apply`, which writes bindings.
- The findings are about **this build**. A recorded refusal is a claim about a version, not a safety interlock.
- Every organization, project and subject name in the record is a placeholder, and the script refuses to write
  a record in which one survived.

## Reading the record

`policyTypes` is one row per declared policy type: what it governs, every field its definition schema declares
(`says`), its target (`matches`) and scope (`appliesTo`) fields, and `timeBoundedFields`, each with the schema it
came from and the schema's own description. `access` is the enumeration: the fields the published schema declares
for a ProjectRoleBinding and a ProjectRole, `anyExpiryField` (the claim made checkable),
`objectMetadataTimeFields` (the Kubernetes metadata every kind carries, with the schema's words for each, which
mark them as set by the server), the fields observed on the objects, the published roles and the binding count.
`deploymentLeaseFields` is the time bound that does exist, on the other kind of object. `elevation` is present
only when the probe ran, and carries each step with the read-back that followed it.
