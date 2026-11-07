# Expected output

A run on the reference estate on 2026-11-07 (VCF Operations 9.1.1.0, build 25679751). Your counts will differ; the
shape will not.

```
$ python3 coverage.py
coverage.py: what does this cost number actually cover?

  1. THE FAMILY: cost keys collected on any object of the type, against the first object's own list
     VirtualMachine            34 collected across  129 object(s);  34 described; the first object alone shows 21
     HostSystem                12 collected across   12 object(s);  12 described; the first object alone shows 12
     ClusterComputeResource    20 collected across    5 object(s);  20 described; the first object alone shows 20
     Datastore                  9 collected across   13 object(s);   9 described; the first object alone shows 7

  2. COVERAGE on VirtualMachine: 129 object(s), 34 cost key(s), by how many objects each reports for
       103/129    21 key(s), e.g. cost|additionalMTDCost, cost|allocation|allocationBasedCpuMTDCost
        92/129     6 key(s), e.g. cost|allocation|allocationBasedDailyCpuCost, cost|allocation|allocationBasedDailyMemoryCost   within the densest key's objects: summing drops 11
        56/129     1 key(s), e.g. cost|reclaimableCost   within the densest key's objects: summing drops 47
        32/129     1 key(s), e.g. cost|oversizedVMReclaimableCost   within the densest key's objects: summing drops 71
        12/129     1 key(s), e.g. cost|poweroffVMReclaimableCost   within the densest key's objects: summing drops 91
         8/129     1 key(s), e.g. cost|potentialCostIncrease   within the densest key's objects: summing drops 95
         3/129     1 key(s), e.g. cost|snapshotVMReclaimableCost   within the densest key's objects: summing drops 100
         1/129     2 key(s), e.g. cost|detailedAdditionalCost:<name>, cost|idleVMReclaimableCost   within the densest key's objects: summing drops 102
     26 machine(s) no key reaches; 18 of them are templates, which carry no cost, so count machines, not templates, in the denominator

  2. COVERAGE on HostSystem: 12 object(s), 12 cost key(s), by how many objects each reports for
        12/12     12 key(s), e.g. cost|accumulatedDepreciation, cost|additionalTotalCost

  2. COVERAGE on ClusterComputeResource: 5 object(s), 20 cost key(s), by how many objects each reports for
         5/5      18 key(s), e.g. cost|aggregatedDailyTotalCost, cost|aggregatedDeletedVmDailyTotalCost
         0/5       2 key(s), e.g. cost|allocatedCost, cost|unAllocatedCost   within the densest key's objects: summing drops 5

  2. COVERAGE on Datastore: 13 object(s), 9 cost key(s), by how many objects each reports for
        13/13      7 key(s), e.g. cost|allocation|allocationBasedAllocatedCost, cost|allocation|allocationBasedUnAllocatedCost
         0/13      2 key(s), e.g. cost|allocatedCost, cost|unAllocatedCost   within the densest key's objects: summing drops 13

  3. COMPOSITION: does each total equal the sum of its published parts?
     consumption   PASSES: 103/103 within a cent, largest difference 5.96e-07
     ownership     PASSES: 12/12 within a cent, largest difference 9.08375e-05

  4. SHOWBACK over the custom-group tree: 44 custom group(s), 31 with members (the list declares no total and takes no paging, per the 9.1.1 specification; one call)
     0 of the 31 with members carry a cost key; 21 of them hold members of a priced type
     the custom groups do not carry cost: showback is a build, not a view. Aggregate over members deliberately (a super metric that sums the members' cost), and say so rather than pointing at an existing tree.
     the product's own world objects: 3 of 14 carry cost keys (VCFWorld, vSphere Private World, vSphere World), the estate-wide totals, not a showback by your groups

  5. PRICE INPUTS (currency USD): the public API serves the currency only; the internal
     cost-driver summary carries each driver's cost in force beside the product's reference
     2 of 10 driver(s) differ from the reference, so were entered or changed: applicationCost, additionalCost
     8 match it, left at the reference or entered at it: hardwareTotalCost, hciHardwareCost, storageCost, licenseTotalCost, maintenanceTotalCost, laborTotalCost, networkTotalCost, facilitiesTotalCost
     the cost engine last ran COMPLETED at 11/06/2026 21:13:55 (the instance's own clock and format, no zone given), 0 of 3 datacenter(s) failed; print this beside every figure

wrote coverage.json; it carries key names and counts, and names no object
```

Exit code 0: composition holds on both models. Exit 1 means a total did not equal the sum of its parts on a model, which
is wiring rather than pricing. Exit 4 means a read was refused or came back short, and nothing was reported.

What each section is there to stop:

- **1, the family.** The keys a type carries are the union over its objects, not the first object's list: here the
  first machine listed showed 21 of the 34 machine cost keys and the first datastore 7 of 9.
- **2, coverage by level.** A key at a lower level whose objects all sit inside the densest key's drops the difference
  when summed, and nothing in its values marks it. Some keys are sparse by design (a reclaimable cost exists only where
  something is reclaimable, a named additional cost only where it applies); the basis keys are the ones to watch, here
  the allocation-based daily keys reporting for fewer machines than the effective daily cost.
- **3, composition.** Both models sum to their parts within a cent; a failure points at wiring.
- **4, showback.** Whether the custom groups you build carry a cost key; on the reference estate none did. The product's
  own world objects carry the estate-wide totals, which are not a showback by your groups.
- **5, price inputs.** Which cost drivers differ from the product's reference (entered or changed) and which match it
  (left at the reference, or entered at it), and when the cost engine last ran. No amount is printed or recorded.
