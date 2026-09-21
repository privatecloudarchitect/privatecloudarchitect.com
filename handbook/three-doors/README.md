# Three doors to one machine

There are two ways to put a virtual machine on a VCF 9.1 Supervisor, and three doors, because one of the two
has two request surfaces:

| door | what it is |
|---|---|
| **direct** | a `VirtualMachine` object POSTed to the namespace's own Kubernetes endpoint. `kubectl apply -f <file>.vm.yaml` is that call with a config file and a better error message. |
| **API** | a VCF Automation blueprint wraps that same object in a `CCI.Supervisor.Resource`, a version is released, and a pipeline asks for a deployment. |
| **catalog** | the identical released version, requested from a form by a person instead of by a pipeline. Same mechanism as API. |

`doors.py` answers the question that actually decides between them, which is not which is faster. It is
**what is different afterwards**.

## Run it

```bash
export VCFA_HOST=<automation-fqdn> VCFA_ORG=<org>
export VCFA_REFRESH_TOKEN_FILE=/path/to/refresh-token   # mode 0600
export DOORS_PROJECT=<project>                          # optional; first visible project otherwise
export TLS_VERIFY=false                                 # only on a self-signed lab CA
python3 doors.py
```

That much is read-only: it inventories what each door needs, checks each namespace against those needs, and
reads an existing deployment's Day-2 action catalogue. To build the comparison rather than read about it:

```bash
export DOORS_NAMESPACE=<a-namespace-you-may-build-in>
export DOORS_STORAGE_CLASS=<storage-class>              # optional; inferred from a running VM otherwise
python3 doors.py --probe-doors
```

## What `--probe-doors` does, and does not do

It builds **the same manifest twice**: once POSTed straight at the namespace endpoint, once wrapped in a
blueprint, released as a version and requested from the project catalog. It reads both machines back field by
field, times both teardowns, deletes everything it created, and reads the namespace and the catalog back to
report whether anything of its own remains.

Every object it touches is one it made. Both machines carry a `handbook-doors-` prefix, the blueprint and its
version do too, and nothing pre-existing is read for anything but comparison. It checks two prerequisites
**before** creating anything and refuses with the reason rather than letting an admission webhook say it
later: a VM image bound to the namespace, and storage quota with room for a 20 GiB boot disk.

## The finding

The two machines are indistinguishable. The same annotation set, the same labels once you ignore the name,
the same spec fields, no owner reference on either, and no label or annotation anywhere on either one naming
a deployment, a catalog or a blueprint. Nothing on the object records which door built it.

Everything that differs is **outside** the machine: a deployment record holding a single link of the shape
`cci:<project>:<namespace>:vmoperator.vmware.com/v1alpha5:VirtualMachine:<name>`. That link is what makes 17
Day-2 actions exist, 5 on the deployment and 12 on the machine, along with a recorded owner, a lease, and the
blueprint, version, catalog item and inputs the machine came from. An identical machine with no record has
none of them, because a Day-2 action is a property of the record rather than of the virtual machine.

## Two prerequisites that bite, and are worth reading before you pick a namespace

**Images are scoped, and the longer list is usually the wrong one.** A VM image is either bound to your
namespace (`virtualmachineimages`) or shared cluster-wide (`clustervirtualmachineimages`), and the two lists
can have nothing in common. On the estate this was verified against they overlapped in zero entries: three
general-purpose images bound to a namespace, 138 cluster-scoped. The cluster-scoped list is where a VKS estate
keeps its **Kubernetes node images**, so a search there for Ubuntu returned 103 results and not one of them
was a general-purpose Ubuntu. The same manifest therefore works in one namespace and is refused in the next
with *no VM image exists ... in namespace or cluster scope*.

**Storage quota is per namespace,** and the refusal arrives from an admission webhook at the create call. One
namespace here had 15 GiB left against a 293 GiB limit, which is not enough for a 20 GiB boot disk.

## The fourth door, which does not reach the same machine

`--probe-vcenter` (with `VC_HOST` and `VC_SESSION_FILE`) creates a virtual machine **straight in vCenter**,
asks every Supervisor namespace for it by name, asks every deployment on the estate whether it claims it,
weighs it against the tenant storage quota, and deletes it.

On the estate this was verified against: created (HTTP 201), declared by **none** of the namespaces, claimed
by **no** deployment, and it moved the tenant storage quota by **0 bytes** while holding a real disk on a
datastore that also backs those namespaces.

That is the honest form of "I will just use vCenter". It works. The machine is not a worse machine, it is a
different kind of object: not a `VirtualMachine`, so no namespace scopes it, no quota counts it, no
reconciler maintains it and no record can claim it. What it costs is not governance, it is accounting.

One boundary the platform does defend: vCenter refuses a hand-made machine in the folder the Supervisor owns,
answering HTTP 403. The probe places its machine elsewhere for that reason.

## Scope, stated plainly

- Read-only without `--probe-doors`. With it, every write is to an object this run created and deletes.
- The teardown timings are one observation per run and they vary enormously. Across three runs the
  deployment teardown took about 32, 70 and 367 seconds, and the direct delete about 20, 10 and 30. The
  deployment path was slower every time, so treat the direction as the finding and refuse to quote a ratio:
  any ratio here is an artefact of which run you picked.
- The probe compares the **direct** and **catalog** doors. The API door uses the same mechanism as the
  catalog, so it is not separately built; that is a claim about the mechanism, from reading both request
  surfaces, and not a third measurement.
- Day-2 actions are read from whichever claimed machine the estate already has. The list is the platform's,
  not this estate's invention, but the count is what this estate publishes.
- Every organization, project, namespace and machine name in the record is a placeholder, and the script
  refuses to write a record in which one survived.

## Reading the record

`needs` is the prerequisite ledger, split into `direct` and `automation`, with what each door requires and how
many of each the estate has. `namespaces` is one row per namespace with the images bound to it, the classes it
publishes, its quota and whether it could build a VM today. `claimBuys` holds the shape of the claim
(`linkShape`), the `deploymentActions` and `resourceActions` the claim makes possible, and the
`recordFields` the deployment carries. `probe` is present only when `--probe-doors` ran: `direct` and
`catalog` carry each door's statuses and timings, `identical` is the field-by-field comparison,
`teardown` the timings, and `residue` what this run left behind, which should be two empty lists.
