# Three doors to one machine

Companion to the chapter
([privatecloudarchitect.com/handbook/deployment-paths](https://privatecloudarchitect.com/handbook/deployment-paths)).
There are two ways to put a virtual machine on a VCF Supervisor, and three doors, because one of the two has two
request surfaces:

| door | what it is |
|---|---|
| **direct** | a `VirtualMachine` object POSTed to the namespace's own Kubernetes endpoint. `kubectl apply -f <file>.vm.yaml` is that call with a config file and a clearer error message. |
| **API** | a VCF Automation blueprint wraps that same object in a `CCI.Supervisor.Resource`, a version is released, and a pipeline asks for a deployment. |
| **catalog** | the identical released version, requested from a form by a person instead of by a pipeline. Same mechanism as API. |

`doors.py` answers the question that actually decides between them, which is not which is faster. It is **what is
different afterwards**. Stdlib Python; no token or password is printed or written.

**Provenance:** run on VCF Automation 9.1.1.0100 and vCenter 9.1.1.0.25712839 on 2026-10-19 under a session login,
both probes included ([`expected-output.md`](expected-output.md)). The 9.1 run of 2026-09-21 is kept in
[`records/`](records/).

| File | What it is |
|---|---|
| `doors.py` | Reads what each door needs and which namespaces can open it, both image lists, what a deployment record claims, and one tenant bearer offered to every door. With `--probe-doors` it builds the same machine through two doors and compares them; with `--probe-vcenter` it makes one machine straight in vCenter. Writes `doors.json`, and refuses to write a record carrying an estate value. |
| `doors.json` | That record from the reference estate, from the run with both probes. The chapter's plates render it. |
| `expected-output.md` | What the script printed on the reference estate: read-only, the dry run, and the probes. |
| `records/doors-vcf-9.1.json` | The 9.1 run of 2026-09-21, as that run wrote it. |

## Run it

```bash
export VCFA_HOST=<automation-fqdn> VCFA_ORG=<org> VCFA_USER=<account>
( umask 077; mkdir -p ~/.vcf && cat > ~/.vcf/vcfa-password )   # paste your password, then Ctrl-D
export VCFA_PASSWORD_FILE=~/.vcf/vcfa-password             # mode 0600; or VCFA_REFRESH_TOKEN_FILE
export DOORS_PROJECT=<project>                             # optional; else the first project that hosts a namespace
export VC_HOST=<vcenter-fqdn>                              # optional: adds vCenter to the credential row
export TLS_VERIFY=false                                    # only on a self-signed lab CA

python3 doors.py                                           # read-only
```

The sign-in is a session login as `<account>@<org>`, or a refresh token minted for the organization in a file of
mode 0600. A secret file open to group or other is refused before it is read.

That much is read-only. To build the comparison rather than read about it, see the plan first, then run it:

```bash
export DOORS_NAMESPACE=<a-namespace-you-may-build-in>
export DOORS_STORAGE_CLASS=<storage-class>                 # optional; inferred from a running VM otherwise
python3 doors.py --probe-doors --dry-run                   # what it would create, and whether a name is taken
python3 doors.py --probe-doors                             # build, compare, delete, read back

export VCENTER_USER=<sso-account> VCENTER_PASSWORD_FILE=~/.vcf/vcenter-password   # or VC_SESSION_FILE
python3 doors.py --probe-vcenter --dry-run
python3 doors.py --probe-vcenter
```

Exit codes: 0 written; 2 a call failed, a sign-in was refused, or a probe's precondition was not met (nothing was
created); 3 a probe left something behind; 5 an unknown argument. `--help` prints the usage.

## What `--probe-doors` does, and does not do

It builds **the same manifest twice**: once POSTed straight at the namespace endpoint, once wrapped in a blueprint,
released as a version and requested from the project catalog. It reads both machines back field by field, times
both teardowns, deletes everything it created, and reads back the machines, the deployment, the blueprint, the
version and both catalogs to report whether anything of its own remains.

Every object it touches is one it made. Both machines, the blueprint and its version carry a `handbook-doors-`
prefix. Its teardown deletes by name, so before it creates anything it checks that none of those names is taken
and stops if one is. It also checks two prerequisites first and refuses with the reason rather than letting an
admission webhook say it later: a general-purpose VM image the namespace can name (bound to it, or cluster-scoped from
a library attached to the whole Supervisor), and storage quota with room for a 20 GiB boot disk.

The teardown waits up to ten minutes for each path, and records each machine's disk promotion state
(`VirtualMachineDiskPromotionSynced`) when its delete is issued. On 9.1.1 the machine whose promotion had not synced
was the slow one to go, whichever door built it, so the door does not decide which teardown is slower.

## The finding

The two machines are indistinguishable. The same annotation set, the same spec fields, no owner reference on
either, and no label or annotation anywhere on either one naming a deployment, a catalog or a blueprint. Nothing on
the object records which door built it. The 9.1 run found the same.

Everything that differs is **outside** the machine: a deployment record holding a single link of the shape
`cci:<project>:<namespace>:vmoperator.vmware.com/v1alpha5:VirtualMachine:<name>`. That link is what makes 17 Day-2
actions exist on the reference estate, 5 on the deployment and 12 on the machine, along with a recorded owner, a
lease, and the blueprint, version, catalog item and inputs the machine came from. An identical machine with no
record has none of them, because a Day-2 action is a property of the record rather than of the virtual machine.

## Two prerequisites that bite, and are worth reading before you pick a namespace

**An image counts at either scope, and the long list is mostly the wrong images.** A VM image is either bound to
your namespace (`virtualmachineimages`) or cluster-scoped (`clustervirtualmachineimages`), where a library attached
to the whole Supervisor lands its images in every namespace. `doors.py` compares the two lists by id and by display
name, counts how many cluster-scoped images are Kubernetes node images by the release their name carries, and counts
the rest as general-purpose (`imageScope` in the record); a namespace can build when it can name a general-purpose
image at either scope. On the reference estate on 2026-10-19 the general-purpose images were bound to three of five
namespaces and none was cluster-scoped, so the same manifest built in three and was refused in two; on 2026-10-28,
after the provider library was attached to the Supervisor, none was bound, every namespace named them at cluster
scope, and every namespace could build.

**Storage quota is per namespace,** and a namespace short of room for the boot disk refuses the create.

## The fourth door, which does not reach the same machine

`--probe-vcenter` creates a virtual machine **straight in vCenter**, in one cluster's root pool on a datastore that
cluster's machines already use, outside the folders the Supervisor owns. It asks every Supervisor namespace for it
by name, asks every deployment whether it claims it, weighs it against the tenant storage quota, and deletes it. If
vCenter refuses the create, the record keeps the error type and message.

On the reference estate: created, declared by none of the namespaces, claimed by no deployment, and it did not move
the tenant storage quota while holding a disk on a datastore its cluster shares. The machine is not a worse machine;
it is a different kind of object: not a `VirtualMachine`, so no namespace scopes it, no quota counts it, no
reconciler maintains it and no record can claim it.

## What each door asks you to be

Every run holds a single tenant bearer and presents it to each door in turn. The table is measured, not documented:
on the reference estate the Automation API, the catalog and the namespace endpoint answered it with 200, and vCenter
with 401, naming what it takes instead. Three of the four doors are one identity question, which is why choosing the
catalog over `kubectl` changes what claims the machine and not who you have to be.

A 200 means the door answered this **identity**. What it then permits is the project role tier, which the
access-control chapter covers.

## The action count is the surface, not the menu

The count above is how many actions **exist**. Each carries a `valid` flag that tracks the machine's state, and the
usable set changes with power: the day2-pathways companion measures which are valid while the machine runs and
which while it is stopped.

## Scope, stated plainly

- Read-only without a probe flag. With one, every write is to an object this run created and deletes.
- The teardown timings are one observation per run and they move with the machines' own state; quote the
  direction and the state beside it, never a ratio between the doors.
- The probe compares the **direct** and **catalog** doors. The API door uses the same mechanism as the catalog, so
  it is not separately built; that is a claim about the mechanism, from reading both request surfaces, and not a
  third measurement.
- Day-2 actions are read from whichever claimed machine the estate already has. The list is the platform's, but
  the count is what this estate publishes.
- Every organization, project, namespace, machine, cluster and datastore name in the record is a placeholder. The
  scrubber replaces every name in one pass and never reaches inside a placeholder it has written, and the
  script refuses to write a record in which a name survived.

## Reading the record

`needs` is the prerequisite ledger, split into `direct` and `automation`, with what each door requires and how many
of each the estate has. `namespaces` is one row per namespace with the images bound to it (`imagesBound`), the
general-purpose cluster images it can name (`imagesCluster`), the classes it publishes,
its quota and whether it could build a VM today. `imageScope` compares the two image lists. `claimBuys` holds the
shape of the claim (`linkShape`), the `deploymentActions` and `resourceActions` the claim makes possible, and the
`recordFields` the deployment carries. `credentials` is the bearer offered to each door. `probe` is present when
`--probe-doors` ran: `direct` and `catalog` carry each door's statuses and timings, `identical` the field-by-field
comparison, `teardown` the timings with each machine's disk promotion state at its delete, `residue` what this run
left behind (every list empty) and `clean`. `fourthDoor` is present when `--probe-vcenter` ran.
