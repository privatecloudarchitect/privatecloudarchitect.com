# Every machine on the workload plane, sorted by how it arrived

Companion to the chapter
([privatecloudarchitect.com/handbook/vm-service](https://privatecloudarchitect.com/handbook/vm-service)):
one read-only script that does the join the platform will not do for you. Stdlib Python only; no token or
password is printed or written.

**Provenance:** read on VCF Automation 9.1.1.0100 on 2026-10-19 under a session login
([`expected-output.md`](expected-output.md)). The 9.1 run of 2026-09-21 is kept in [`records/`](records/).

| File | What it is |
|---|---|
| `vmservice.py` | Classifies every virtual machine into the path it arrived by, **reading objects rather than trusting naming conventions**: a controller owner means a cluster minted it, a deployment resource linking it (by namespace and name) means the catalog wrapped it, and neither means somebody wrote it straight to the namespace. Also reports the kinds the VM Service publishes with their verbs, the spec and status shape of a real machine and how many machines' two power fields disagree, what a blueprint may declare, and the class catalog of every namespace read the way that answers whether anything is reserved. With `--compare` it sets the arrival counts beside an earlier record's. Writes `vmservice.json`. |
| `vmservice.json` | That record from the reference estate. The chapter's plates render it. |
| `expected-output.md` | What the script printed on the reference estate, and the comparison with the 9.1 record. |
| `records/vmservice-vcf-9.1.json` | The 9.1 run of 2026-09-21, as that run wrote it. |

## Run it

```bash
export VCFA_HOST=<automation-fqdn> VCFA_ORG=<org> VCFA_USER=<account>
( umask 077; mkdir -p ~/.vcf && cat > ~/.vcf/vcfa-password )   # paste your password, then Ctrl-D
export VCFA_PASSWORD_FILE=~/.vcf/vcfa-password             # mode 0600; or VCFA_REFRESH_TOKEN_FILE
export TLS_VERIFY=false                                    # only on a self-signed lab CA

python3 vmservice.py                                       # writes vmservice.json
python3 vmservice.py --compare last-week/vmservice.json    # also compares the arrivals with an earlier record
```

The sign-in is a session login as `<account>@<org>`, or a refresh token minted for the organization in a file of
mode 0600. A secret file open to group or other is refused before it is read. `OUT_DIR` sets where the record is
written (the current directory by default).

Exit codes: 0 written (with `--compare`, the direct-arrival count did not rise); 1 with `--compare`, it rose;
2 a call failed or the sign-in was refused; 5 an unknown argument.

## The arrival path decides what governs a machine, and the machine does not record it

That is the finding worth carrying. A catalog-wrapped machine and a hand-made one are told apart only by
walking **outwards** to the deployment resource that links the first, by its namespace and name. Looking at the
machine itself answers nothing: the record reports how many of each carry a distinguishing marker, and the keys
they hold in common. The count that matters on most estates is the third one, machines written straight to the
namespace, because nothing announces it; `--compare` is how to watch it week to week.

One more trap the script handles: a best-effort VM class publishes a `policies.resources` block whose values
are **all zero**. The presence of that block is not evidence of a reservation, and reading it as one produces
the contradiction "every class has a reservation policy" beside a region that reports none required. The
region's own class summary carries the field that answers the question, and the script reads both.

## Scope, stated plainly

- Read-only. Every call that touches the estate is a `GET`, apart from the session login.
- The version is the one the VM Service group names as preferred; the script stops rather than guess when the
  group names none.
- Every list is read to its end: Kubernetes-style lists follow their continue token, and the deployment lists
  are read page by page, sorted. A deployment's resources answer HTTP 500 to `sort=id,asc` on 9.1.1, so they are
  sorted by name, which is unique within a deployment. A list that fails ends the run.
- The classification is structural: owner references and deployment resource links, never a name or a label
  convention. A link that names a machine no longer on the plane is counted separately rather than folded in.
- It reports **your** plane on the day you run it, which is what makes the third count actionable.
- Every organization, project, namespace and machine name in the record is a placeholder, and so is every label
  or annotation key outside a product's own domain (`vmware.com`, `k8s.io`, `kubernetes.io`).

## Reading the record

`vocabulary`, `verbs` and `apiVersions` are the kinds the VM Service publishes, which is a family rather than
one primitive. `primitive` is the spec and status shape of a real machine, including `namesImageTwoWays` and the
separate fields that govern power, and `powerDisagree` counts the machines whose two power fields differ.
`arrivals` is the join (`controllerOwned`, `catalogWrapped`, `rawOnTheWire`, `claimedButAbsent`, with
`linkResources` and `linksWithoutAKnownNamespace`) and `canTheMachineTell` is the follow-up question, with the
keys the two classes share. `machines` is one row per machine with its namespace, class, controller owner,
declared and observed power state, arrival path, and the label and annotation **keys** it carries. `classes`
carries `hasPolicyBlock` beside `allPolicyValuesZero` and the namespaces each was seen in; `requireReservation`
is the region's own answer and `reservationUnstated` counts summaries that do not state it.
