# Every machine on the workload plane, sorted by how it arrived

Companion to the chapter
([privatecloudarchitect.com/handbook/vm-service](https://privatecloudarchitect.com/handbook/vm-service)):
one read-only script that does the join the platform will not do for you. Stdlib Python only; no token is
printed or written.

| File | What it is |
|---|---|
| `vmservice.py` | Classifies every virtual machine into the path it arrived by, **reading objects rather than trusting naming conventions**: a controller owner means a cluster minted it, a deployment claiming it by resource link means the catalog wrapped it, and neither means somebody wrote it straight to the namespace. Also reports the kinds the VM Service publishes, the spec and status shape of a real machine, what a blueprint may declare, and the class catalog read the way that answers whether anything is reserved. Writes `vmservice.json`. |
| `vmservice.json` | That record from the reference estate, 2026-09-18. The chapter's plates render it. |

## Run it

```bash
export VCFA_HOST=<automation-fqdn> VCFA_ORG=<org>
export VCFA_REFRESH_TOKEN_FILE=/path/to/refresh-token   # mode 0600
export TLS_VERIFY=false                                 # only on a self-signed lab CA

python3 vmservice.py
```

## The arrival path decides what governs a machine, and the machine does not record it

That is the finding worth carrying. A catalog-wrapped machine and a hand-made one are told apart only by
walking **outwards** to the deployment that claims the first by resource link. Looking at the machine itself
answers nothing: the record reports how many of each carry a distinguishing marker, and the keys they hold in
common. The count that matters on most estates is the third one, machines written straight to the namespace,
because nothing announces it.

One more trap the script handles: a best-effort VM class publishes a `policies.resources` block whose values
are **all zero**. The presence of that block is not evidence of a reservation, and reading it as one produces
the contradiction "every class has a reservation policy" beside a region that reports none required. The
region's own class summary carries the field that answers the question, and the script reads both.

## Scope, stated plainly

- Read-only. Every call is a `GET`.
- The classification is structural: owner references and deployment resource links, never a name or a label
  convention. A machine whose claiming deployment has been removed is counted separately rather than folded in.
- It reports **your** plane on the day you run it, which is what makes the third count actionable.
- Every organization, project and namespace name in the record is a placeholder, and machine names are not
  carried at all.

## Reading the record

`vocabulary` and `apiVersions` are the kinds the VM Service publishes, which is a family rather than one
primitive. `primitive` is the spec and status shape of a real machine, including `namesImageTwoWays` and the
separate fields that govern power. `arrivals` is the join (`controllerOwned`, `catalogWrapped`,
`rawOnTheWire`, `claimedButAbsent`) and `canTheMachineTell` is the follow-up question, with the keys the two
classes share. `machines` is one row per machine with its class, controller owner, declared and observed power
state, and the label and annotation **keys** it carries. `classes` carries `hasPolicyBlock` beside
`allPolicyValuesZero`, and `requireReservation` is the region's own answer.
