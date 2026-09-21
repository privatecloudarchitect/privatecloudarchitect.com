# Day-2 on three planes

Creating a machine is the small half. A machine is created once and changed many times, so the pathway you
take for Day-2 matters more than the one you took on day one.

Three planes will accept the same change, and they do not behave alike:

| plane | what happens |
|---|---|
| **vCenter** | the call is accepted and returns success. On a machine the Supervisor declares, the reconciler undoes it. Measured at about **12 seconds** to revert, with nothing on the vCenter side recording that it was reverted. |
| **Supervisor** | a `PATCH` of `spec.powerState`. The change sticks, nothing waits for it, and the deployment record that claims the machine is never told. |
| **VCF Automation** | writes that **same Supervisor field**, then blocks until the machine actually converges before reporting success. |

The two that stick are the same mechanism. Automation is not a parallel control path: it writes the field a
`kubectl patch` writes, which is why those two never fight and why vCenter does.

## Run it

```bash
export VCFA_HOST=<automation-fqdn> VCFA_ORG=<org>
export VCFA_REFRESH_TOKEN_FILE=/path/to/refresh-token    # mode 0600
export PATHWAYS_PROJECT=<project>                        # optional; first visible project otherwise
export TLS_VERIFY=false                                  # only on a self-signed lab CA
python3 pathways.py
```

That is read-only, and it is the part worth scheduling. To make the comparison rather than read about it:

```bash
export PATHWAYS_NAMESPACE=<a-namespace-you-may-build-in>
export PATHWAYS_STORAGE_CLASS=<storage-class>            # optional; inferred from a running VM otherwise
python3 pathways.py --probe-pathways
```

## The drift audit, which is why this script exists

For every machine claimed by a deployment it compares three views:

- **declared**: the manifest the record holds
- **last observed**: a cached copy of the object, which the record refreshes
- **live**: the object on the Supervisor right now

The first pair is the useful one, because **both halves are inside the deployment record**. Anybody who can
read Automation can prove drift without touching the workload plane at all.

**The finding it exists to catch:** after a change made on the Supervisor, the record declared `PoweredOff`
for a machine that was `PoweredOn`, and `syncStatus` read `SUCCESS` the whole time. That field answers
whether the record applied its manifest, not whether the machine still matches it. It does catch deletion,
reporting `MISSING`. So the boundary is **existence against conformance**, and only one side of it is
instrumented.

Two rules the audit follows, both learned the hard way:

- **Resolve the machine through its resource link, never its name.** Names are reused. A retired record can
  name a machine that now belongs to somebody else, and the first version of this audit compared a dead
  record against a live stranger and reported it healthy.
- **Compare only fields somebody set on purpose.** A manifest legitimately omits fields the platform then
  defaults, so comparing every key reports defaulting as drift.

## Tombstones, and the order that makes one

The script also counts deployments that report `DELETE_SUCCESSFUL` **and still hold a resource**. These
cannot be retired through any API here.

The sequence that makes one, established by running all three orders:

| when you delete the deployment | outcome |
|---|---|
| the machine still exists | the record retires, in tens of seconds |
| the machine is gone, the record has not noticed yet | still retires, more slowly |
| the machine is gone and the record **has** noticed (`syncStatus: MISSING`) | reports `DELETE_SUCCESSFUL` and stays |

Every one of those deletes reports `SUCCESSFUL` with all its tasks completed, because removing the resources
it manages is exactly what it did. The difference is whether there was anything left to remove.

A retired record keeps listing its missing resource and keeps publishing its full action set; the platform
reports the `Delete` action as `valid: true`, and asking for one answers `400 Action is not supported based
on the current state`.

**A deliberate omission.** The probe always tears down while the machine still exists. It will not perform
the third order, because a teaching script must not litter the estate it teaches on. If you want to see a
tombstone, the audit above will show you any your estate already has.

## What a delete takes, and what it leaves

`--probe-pathways` also gives one machine two disks and deletes it once, reading the namespace storage quota
before and after each step.

| the disk | `ownerReferences` | when the machine is deleted | quota |
|---|---|---|---|
| the boot disk the platform made | names the machine | deleted with it | released, matching its size |
| a volume you made and attached | none | **survives, still Bound** | held until you delete it yourself |

**The documentation says the opposite, for a newer API line than VCF 9.1 serves.** The VM Operator
documentation states that when a VM is deleted, PVCs *still attached* (listed in `spec.volumes`) "are
automatically deleted along with it", while a previously detached one has its owner reference removed "so it
survives instead of being cascade-deleted". It also documents a `vmoperator.vmware.com/keep-owner-ref`
annotation to opt out, which only makes sense if the owner reference is normally present.

On this estate it was never present: the attached volume carried no owner reference even while attached, and
survived. Those documentation examples use `v1alpha6`; this Supervisor serves up to `v1alpha5` and answers
404 for `v1alpha6`, so the likeliest reading is a behaviour that changed between the two. That is a reading,
not a finding.

**And the door you delete through decides it.** The same unowned volume was removed when the **deployment**
was deleted instead of the machine. Kubernetes garbage collection had no handle on it, because it had no
owner reference; the record did, because it was tracking it as a resource. That is the strongest practical
argument here for deleting through the thing that claims a machine.

**So test it rather than trusting either answer.** Assume the documented rule on a build that does not
implement it and orphans accumulate quietly; assume this estate's result on a build that does and a volume
you meant to keep is cascade-deleted. Attach a throwaway volume to a throwaway machine, delete the machine,
and look. The two answers differ by whether your data still exists.

The list worth having is one read: every volume in the namespace with **no owner reference**. That is
everything no machine deletion will ever clean up.

One caution about boot disks. They come in two shapes here, `Classic` and `Managed`, and only the second is a
PersistentVolumeClaim you can see in the namespace listing. A machine built by a direct create got a
`Classic` disk that never appeared as a PVC at all; a catalog-built machine's was `Managed` and did. Both
went with their machine, so the rule above holds either way, but a volume audit that reads only PVCs will not
see every disk an estate is paying for.

## Day-2 actions are a state machine, not a list

`--probe-pathways` reads each action's `valid` flag with the machine running and again with it stopped. They
are not the same set:

| | valid |
|---|---|
| machine **running** | Add.Disk, both consoles, Remove.Disk, snapshots, PowerOff, Suspend |
| machine **stopped** | **Resize**, snapshots, PowerOn |

Resize is refused while the machine runs and becomes available when it stops; disks and consoles are the
reverse. So an action total is the size of the surface, never a count of what you can do right now, and a
runbook that assumes otherwise has an ordering bug in it.

Two practical notes from driving these:

- The request path is **per resource**: `POST /deployment/api/deployments/{id}/resources/{resourceId}/requests`
  with `{actionId, inputs, reason}`. Posting a resource action to the deployment-level `/requests` answers 404.
- Each action carries its own schema with patterns and enums. `Add.Disk` declares `diskSize` as
  `^[0-9]+Gi$`, so `"1"` is refused with 400 and `"1Gi"` succeeds. Read the schema rather than guessing.

**A Day-2 action that reports FAILED may still have changed things.** On one run `Add.Disk` ended
SUCCESSFUL, on the next with identical inputs it ended FAILED, and in both it created the requested volume
*and* converted the boot disk from a `Classic` disk into a PVC. Read the estate after a failed action rather
than assuming it rolled back.

## Scope, stated plainly

- Read-only without `--probe-pathways`. With it, every write is to an object this run created and deletes.
- The probe exercises the **VCFA** and **Supervisor** pathways. It does not touch vCenter: that result needs
  a vCenter credential this script deliberately does not ask for, and it is a fact about where authority
  lives rather than a Day-2 option.
- Timings vary a great deal between runs. The spec write was steady at about twenty seconds; convergence
  ranged from 22 to 323 seconds on the same machine shape, because it is a guest shutting down. In every run
  the request reported success at the moment the machine converged. Treat the ordering as the finding.
- The tombstone result is scoped to the APIs this handbook uses. The product UI and any provider-side or
  support tooling were not tested; the provider identity returns 500 against the tenant deployment API and is
  not a route.
- Every organization, project, namespace, deployment and machine name in the record is a placeholder, and the
  script refuses to write a record in which one survived.

## Reading the record

`audit` is one row per claimed machine with its `syncStatus`, whether all three views `agrees`, whether its
`objectGone`, and the field lists `declaredVsObserved` and `declaredVsLive`. `auditTotals` summarises them,
including `driftProvableFromTheRecordAlone`, which is the count you can reproduce with one credential.
`tombstones` lists deployments reporting `DELETE_SUCCESSFUL` that still hold a resource. `watchedFields`
states which spec fields are compared. `probe` is present when `--probe-pathways` ran, and is carried
forward by later read-only runs rather than erased: `vcfa` and `supervisor` each carry their timings and the
record's state afterwards, and `teardown` records that the record retired.
