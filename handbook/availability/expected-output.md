# Expected output: promise.py

A run against the reference estate on 2026-10-22 (VCF Operations 9.1.1), the run that wrote `promise.json` beside
this file. Checks are grouped by anonymized address block and no address, check or machine is named. Counts are this
estate's; the shape is what any 9.1 instance returns.

```
$ python3 promise.py
promise.py: is the availability arm still computing, and what does it say?

  CONTENT: 5 of 5 reachability metrics found among your 100 owned super metrics
     checks       present
     reachable    present
     unreachable  present
     sli          present
     delivery     present

  COMPUTING: 4 of the 4 roll-up metrics carry a current value on the adapter instance (the per-check delivery metric computes on each check, not here)
     sli          100.0        9.8 minutes old
     reachable    7.0          9.8 minutes old
     checks       7.0          9.8 minutes old
     unreachable  0.0          9.8 minutes old

  DENOMINATOR: 7 direct children ({'ip_type': 6, 'fqdn_type': 1}) against 8 raw check objects; 1 fold under a name check
  SHAPE: packet loss distribution {0.0: 7}
     a name check reachable 1, unreachable 0
     block A      reachable 1, unreachable 0
     block B      reachable 5, unreachable 0

  GUEST AGAINST THE FLOOR: 139 machine records, 41 of them for machines that no longer exist (9 of those still read a KPI of zero)
     29 of the 98 machines that exist read a guest KPI of zero:
     29 are powered off: down, or off on purpose
     0 are powered on with a current uptime: running, the guest layer blind (VMware Tools silent)
     0 are powered on without a current uptime reading: unknown
     8 of the powered-off machines still carry their last uptime above zero, which is why a latest uptime is not a running machine
     the latest uptime alone, deleted records included, would have said 16 running, 0 stopped and 22 unmeasured

wrote promise.json; checks are grouped by anonymised block and no address is named
```

## Reading it

- `minutes old` is the age of each roll-up's newest reading. Readings that all stopped at the same age, and that age
  is hours, mean the collector stopped, not the fleet.
- `direct children` is the denominator the SLI formula uses: independent endpoints. The gap to `raw check objects` is
  the addresses that fold under a name check.
- `block` lines group the checks by where they point. Every unreachable check in one block, with every other block
  answering, is one cause to find.
- `machine records` counts every virtual machine resource the instance holds. A record whose adapter reports
  NOT_EXISTING belongs to a machine that was deleted; it keeps its last values, a guest KPI of zero among them, so it
  is counted apart and never as a machine.
- A guest KPI of zero is split by the hypervisor's power state and the age of the uptime reading. A powered-off
  machine keeps its last uptime, which is why the last line shows what the uptime alone would have said.
