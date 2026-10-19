# Cost coverage gate

Backs the cost and showback chapter
([privatecloudarchitect.com/handbook/cost-showback](https://privatecloudarchitect.com/handbook/cost-showback)).

A cost metric computes whether or not anyone set the prices, and it computes whether or not it has anything to say
about the object you are about to sum. So the first question about a cost figure is never "how much" but "over what".
`coverage.py` answers it read-only, from the outputs, and says which price inputs differ from the product's reference.

## Run it

```bash
export OPS_HOST=<your-ops-fqdn>
export OPS_BROKER_HOST=<your-broker-fqdn>    # omit if the broker shares the Ops FQDN
( umask 077; mkdir -p ~/.vcf && cat > ~/.vcf/ops-api-token )   # paste your api-token, then Ctrl-D
export OPS_API_TOKEN_FILE=~/.vcf/ops-api-token   # mode 0600; OPS_REALM defaults to CUSTOMER
export OPS_TLS_VERIFY=false                  # only on a self-signed lab CA

python3 coverage.py                          # writes coverage.json beside the script (OUT_DIR to move it)
```

The api-token is read from `OPS_API_TOKEN_FILE`, a file of mode 0600; a wider mode is refused. The value itself in
`OPS_API_TOKEN` still works, but it lands in the shell's history and the process list, so keep it for a throwaway
credential.

Stdlib Python 3 only; `opslib.py` holds the broker exchange. The script reads resource lists, stat keys, stat values,
properties, group membership and the cost-driver summary. It prices nothing and writes nothing to the instance. The
identity behind the api-token needs read access to those.

| exit | meaning |
|---|---|
| 0 | composition holds on both models |
| 1 | a total did not equal the sum of its published parts on a model: wiring, not pricing |
| 4 | a read was refused or came back short, so nothing was reported |

See [`expected-output.md`](expected-output.md) for a full run.

## What it reports

**1. The family, per object type.** Cost is not one metric and it is not one vocabulary. Four object types carry cost,
and they answer four different questions:

| object type | vocabulary | what it is |
|---|---|---|
| `VirtualMachine` | three bases (allocation, demand, effective) across cpu, memory and storage, daily and month-to-date, plus reclaimable costs and a projection | **the charge** |
| `HostSystem` | hardware, facilities, host labour, network, maintenance, OS licensing, additional, summing to a loaded total, with depreciation separate | **the basis** |
| `ClusterComputeResource` | `cpuBaseRate`, `memoryBaseRate`, total cost split allocated against unallocated | **the price** |
| `Datastore` | `storageRate`, `storageRateByAllocation`, and the same allocated/unallocated pair | **the price, for storage** |

None of them is another's roll-up: the machine total is not a share of the host total, and the cluster total is not the
sum of its machines. The rates sit on the infrastructure objects and the charges on the workload objects. The family is
read as the union of the keys every object of the type collects, because one object does not collect every key its
type carries.

**2. Coverage, by level.** The gate, and the reason it is per key rather than per estate: collection and the pricing
model are different mechanisms, so a priced instance can still have keys that report for part of it. The run groups the
keys by how many objects each reports for and checks each level against the densest key. A sparse key whose objects all
sit inside the densest key's drops the difference when summed, and nothing in its values marks it: same shape, same
units, plausible amounts. Some keys are sparse by design, such as a reclaimable cost, which exists only where something
is reclaimable; the basis keys are the ones to watch. The run also counts how many of the machines no key reaches are
templates, which carry no cost, so the denominator can be machines rather than everything the list returns.

**3. Composition, to the cent.** A total that does not equal the sum of its published parts is a total you cannot
explain, and a decomposable total is a negotiable one. Checked on both models:

```
consumption   effectiveDailyCpuCost + Memory + Storage + dailyAdditionalCost == effectiveDailyCost
ownership     hardware + facilities + hostLabor + network + maintenance
              + hostOsl + additional                                        == totalLoadedCost
```

An object missing a part is counted apart rather than summed as zero.

**4. Whether showback is a view or a build.** The tempting design is to roll priced signals up the custom-group tree
that already scopes policies and alerts. The run asks every custom group with members (the group types the `Container`
adapter holds) for its stat keys and counts the cost ones. The product's own world objects (vSphere World, VCF World
and the like) are counted apart: they can carry the estate-wide totals, which says nothing about whether the groups
you build carry cost. When the custom groups carry none, showback needs an explicit aggregation over members (a super
metric summing a chosen cost key), a modest build with an owner rather than a view over something that exists.

**5. The price inputs.** The public API serves one pricing fact, the currency (`GET /api/costconfig/currency`). The
internal API's cost-driver summary (`GET /suite-api/internal/costdrivers/summary`, which answers only with the header
`X-Ops-API-use-unsupported: true` and keeps no compatibility promise) carries each cost
driver's monthly cost in force beside the reference cost the product computes. A driver whose two differ was entered or
changed; one whose two match was left at the reference, or entered at it, which the summary cannot tell apart. The run
prints which drivers are which and when the cost engine last ran (`GET /suite-api/internal/costcalculation/status`),
the date to print beside any figure built on those inputs. It keeps no amount. If your instance refuses the internal
API, the run prints the refusal, and confirming the inputs stays a person's step.

## The record

`coverage.json` carries key names, counts and which drivers match their reference; it names no object and keeps no
amount. A cost key named after something on your estate (an additional cost's own name, after a colon) is recorded by
its family only. `coverage.json` in this folder is the reference estate's run of 2026-10-18 on VCF Operations 9.1.1.0
(build 25679751), the record the chapter renders.

## Scope

These keys price a VMware estate and the workloads on it. A VMware estate hosted in a public cloud presents the same
object types, so the four vocabularies, the coverage gate and the composition checks carry over unchanged. Setting any
of it beside a native public-cloud list price is a different exercise, with a different unit of accounting and evidence
an instance cannot be asked for, and it is out of this gate's scope.
