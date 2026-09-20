# Cost coverage gate

Backs the cost and showback sheet
([privatecloudarchitect.com/handbook/cost-showback](https://privatecloudarchitect.com/handbook/cost-showback)).

A cost metric computes whether or not anyone set the prices, and it computes whether or not it has
anything to say about the object you are about to sum. So the first question about a cost figure is
never "how much" but "over what". `coverage.py` answers it read-only, from the outputs, because on
this build the price inputs are not on the suite API surface (ten candidate paths probed; one serves
the currency).

## Run it

```bash
export OPS_HOST=<your-ops-fqdn>
export OPS_BROKER_HOST=<your-broker-fqdn>    # omit if the broker shares the Ops FQDN
export OPS_API_TOKEN=<your-api-token>        # OPS_REALM defaults to CUSTOMER
export OPS_TLS_VERIFY=false                  # only on a self-signed lab CA

python3 coverage.py                          # writes coverage.json beside the script
```

Stdlib Python only; `opslib.py` holds the broker exchange. The script reads resource lists, stat
keys, stat values and group membership. It prices nothing and writes nothing to the instance.

## What it reports

**1. The family, per object type.** Cost is not one metric and it is not one vocabulary. Four object
types carry cost, and they answer four different questions:

| object type | keys | vocabulary | what it is |
|---|---|---|---|
| `VirtualMachine` | 28 | three bases (allocation, demand, effective) across cpu, memory and storage, daily and month-to-date, plus reclaimable and a projection | **the charge** |
| `HostSystem` | 12 | hardware, facilities, host labour, network, maintenance, OS licensing, additional, summing to a loaded total, with depreciation separate | **the basis** |
| `ClusterComputeResource` | 19 | `cpuBaseRate`, `memoryBaseRate`, total cost split allocated against unallocated | **the price** |
| `Datastore` | 7 | `storageRate`, `storageRateByAllocation`, and the same allocated/unallocated pair | **the price, for storage** |

None of them is another's roll-up: the machine total is not a share of the host total, and the
cluster total is not the sum of its machines. The useful division is that **the rates sit on the
infrastructure objects and the charges sit on the workload objects**, which is price-times-signal
already implemented, and which means a cost figure can be attacked at either factor. Quoting one
object type's answer when somebody asked another's is a category error both sides will accept.

**2. Coverage, per key.** The gate, and the reason it is per key rather than per estate: a fully
priced instance can still have cost keys that report for a fifth of it, because collection and the
pricing model are different mechanisms. On the estate this was written against, the best-covered
machine cost key reported for 91 of 103 and the worst for 20, with the sparse set a strict subset of
the dense one. Summing the sparse key produces a confident total missing most of the estate, and
nothing in the response distinguishes them: same shape, same units, same plausible values.

Sweep rather than sample, and then re-read what the sample already infected. Sampling two of a
cluster's nineteen cost keys was enough to reach the wrong conclusion that clusters carry no cost
data; seventeen other keys report for every cluster. The first correction fixed the table and left
the generalisation standing elsewhere, which is the more expensive half of that mistake.

**3. Composition, to the decimal.** A total that does not equal the sum of its published parts is a
total you cannot explain to anyone, and a decomposable total is a negotiable one: the component that
surprises somebody is the one to discuss. Checked on both models:

```
consumption   effectiveDailyCpuCost + Memory + Storage + dailyAdditionalCost == effectiveDailyCost
ownership     hardware + facilities + hostLabor + network + maintenance
              + hostOsl + additional                                        == totalLoadedCost
```

Both pass to float precision on the reference estate. A failure here is wiring rather than pricing:
a metric built on the wrong signal still produces plausible money, it just stops summing.

**4. Whether showback is a view or a build.** The tempting design is to roll priced signals up the
custom-group tree that already scopes policies and alerts. Whether that works is a property of your
instance and it is one read. On the reference estate a group **with members** carries 50 stat keys
and **zero** cost keys, while all 66 cost keys sit on the four inventory object types beneath it. So
the group tree is the right scope and not a carrier: showback needs an explicit aggregation over
members (a super metric summing a chosen cost key), which is a modest build with an owner rather
than a view over something that already exists.

Test against a group that has members. An empty group cannot distinguish a missing metric from a
missing membership.

## Two decisions the gate surfaces but does not make

- **Powered-off machines report no cost.** On the reference estate every machine that no cost key
  reached was powered off. That is a showback boundary decision, not a gap: a machine that is off
  still holds storage and a licence.
- **Reference inputs compute as convincingly as entered ones.** The ownership model is fully
  populated, every component present, the total decomposing exactly, whether or not anybody entered
  a real price. Since the inputs are not readable from this API, confirming they were entered is a
  human step, and the date they were entered belongs beside every figure derived from them.

## The record

`coverage.json` carries key names and counts only; it names no object and publishes no amount.
Amounts on any estate are its own, and on a lab they are the platform's reference inputs rather than
a purchase record.

## Scope

These keys price a VMware estate and the workloads on it, which is the question this gate answers
well. A VMware estate hosted in a public cloud presents the same object types, so the four
vocabularies, the coverage gate and the composition checks carry over unchanged.

Setting any of it beside a native public-cloud list price is a different exercise: a different unit
of accounting, and evidence that is a dated vendor price for a matched workload shape rather than
anything an instance can be asked. That belongs with whoever owns the commercial argument, with its
references attached, and it is out of this gate's scope rather than queued behind it.
