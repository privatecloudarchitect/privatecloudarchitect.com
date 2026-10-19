# Expected output

A run on the reference estate on 2026-10-18 (VCF Operations 9.1.1.0, build 25679751). Your counts will differ; the
shape will not.

```
$ python3 coverage.py
coverage.py: what does this cost number actually cover?

  1. THE FAMILY: cost keys collected on any object of the type, against the first object's own list
     VirtualMachine            34 collected across  110 object(s);  34 described; the first object alone shows 28
     HostSystem                12 collected across   11 object(s);  12 described; the first object alone shows 12
     ClusterComputeResource    20 collected across    5 object(s);  20 described; the first object alone shows 20
     Datastore                  9 collected across   12 object(s);   9 described; the first object alone shows 7

  2. COVERAGE on VirtualMachine: 110 object(s), 34 cost key(s), by how many objects each reports for
        93/110    21 key(s), e.g. cost|additionalMTDCost, cost|allocation|allocationBasedCpuMTDCost
        58/110     1 key(s), e.g. cost|reclaimableCost   within the densest key's objects: summing drops 35
        53/110     6 key(s), e.g. cost|allocation|allocationBasedDailyCpuCost, cost|allocation|allocationBasedDailyMemoryCost   within the densest key's objects: summing drops 40
        33/110     1 key(s), e.g. cost|oversizedVMReclaimableCost   within the densest key's objects: summing drops 60
        13/110     1 key(s), e.g. cost|poweroffVMReclaimableCost   within the densest key's objects: summing drops 80
        10/110     1 key(s), e.g. cost|potentialCostIncrease   within the densest key's objects: summing drops 83
         2/110     1 key(s), e.g. cost|snapshotVMReclaimableCost   within the densest key's objects: summing drops 91
         1/110     2 key(s), e.g. cost|detailedAdditionalCost:<name>, cost|idleVMReclaimableCost   within the densest key's objects: summing drops 92
     17 machine(s) no key reaches; 17 of them are templates, which carry no cost, so count machines, not templates, in the denominator

  2. COVERAGE on HostSystem: 11 object(s), 12 cost key(s), by how many objects each reports for
        11/11     12 key(s), e.g. cost|accumulatedDepreciation, cost|additionalTotalCost

  2. COVERAGE on ClusterComputeResource: 5 object(s), 20 cost key(s), by how many objects each reports for
         5/5      18 key(s), e.g. cost|aggregatedDailyTotalCost, cost|aggregatedDeletedVmDailyTotalCost
         1/5       2 key(s), e.g. cost|allocatedCost, cost|unAllocatedCost   within the densest key's objects: summing drops 4

  2. COVERAGE on Datastore: 12 object(s), 9 cost key(s), by how many objects each reports for
        12/12      7 key(s), e.g. cost|allocation|allocationBasedAllocatedCost, cost|allocation|allocationBasedUnAllocatedCost
         4/12      2 key(s), e.g. cost|allocatedCost, cost|unAllocatedCost   within the densest key's objects: summing drops 8

  3. COMPOSITION: does each total equal the sum of its published parts?
     consumption   PASSES: 93/93 within a cent, largest difference 4.396e-07
     ownership     PASSES: 11/11 within a cent, largest difference 9.34005e-05

  4. SHOWBACK over the custom-group tree: 49 custom group(s), 32 with members (the group list declares no total; it was read in one page of 5000)
     0 of the 32 with members carry a cost key; 22 of them hold members of a priced type
     the custom groups do not carry cost: showback is a build, not a view. Aggregate over members deliberately (a super metric that sums the members' cost), and say so rather than pointing at an existing tree.
     the product's own world objects: 3 of 14 carry cost keys (VCFWorld, vSphere Private World, vSphere World), the estate-wide totals, not a showback by your groups

  5. PRICE INPUTS (currency USD): the public API serves the currency only; the internal
     cost-driver summary carries each driver's cost in force beside the product's reference
     3 of 10 driver(s) differ from the reference, so were entered or changed: storageCost, applicationCost, additionalCost
     7 match it, left at the reference or entered at it: hardwareTotalCost, hciHardwareCost, licenseTotalCost, maintenanceTotalCost, laborTotalCost, networkTotalCost, facilitiesTotalCost
     the cost engine last ran COMPLETED at 10/17/2026 21:13:49 (the instance's own clock and format), 0 of 3 datacenter(s) failed; print this beside every figure

wrote coverage.json; it carries key names and counts, and names no object
```

Exit code 0: composition holds on both models. Exit 1 means a total did not equal the sum of its parts on a model, which
is wiring rather than pricing. Exit 4 means a read was refused or came back short, and nothing was reported.

What each section is there to stop:

- **1, the family.** The keys a type carries are the union over its objects, not the first object's list: here the
  first machine listed showed 28 of the 34 machine cost keys and the first datastore 7 of 9.
- **2, coverage by level.** A key at a lower level whose objects all sit inside the densest key's drops the difference
  when summed, and nothing in its values marks it. Some keys are sparse by design (a reclaimable cost exists only where
  something is reclaimable, a named additional cost only where it applies); the basis keys are the ones to watch, here
  the allocation-based daily keys reporting for fewer machines than the effective daily cost.
- **3, composition.** Both models sum to their parts within a cent; a failure points at wiring.
- **4, showback.** The custom groups you build carry no cost key; the product's own world objects carry the estate-wide
  totals, which are not a showback by your groups.
- **5, price inputs.** Which cost drivers differ from the product's reference (entered or changed) and which match it
  (left at the reference, or entered at it), and when the cost engine last ran. No amount is printed or recorded.
