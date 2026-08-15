# Expected output

A healthy run (your cluster names and figures will differ):

```
$ python3 runway.py
ESTATE CAPACITY RUNWAY - 3 cluster(s), allocation model, commitment-adjusted

  cluster                      mem     cpu    disk   runway
  ---------------------------------------------------------
  cluster-01                 > 1yr   > 1yr   > 1yr    > 1yr
  cluster-02                  212d   > 1yr   > 1yr     212d
  cluster-03                 > 1yr    64d   > 1yr      64d  warning
  ---------------------------------------------------------

  ESTATE RUNWAY: 64d  (warning) - bound by cluster-03 on cpu.
  First axis, first cluster: the estate can place projected demand this long before its
  tightest cluster runs out, honoring resident commitments.
```

Exit code 1 (warning) here; 2 if any cluster reads under thirty days; 0 when everything clears
ninety. With the parity gate:

```
$ python3 runway.py --parity expectations.json
parity gate: 1 policy(ies) match their declared expectations

ESTATE CAPACITY RUNWAY - 3 cluster(s), ...
```

And when the ruler has drifted:

```
$ python3 runway.py --parity expectations.json
PARITY GATE REFUSED:
  - <policy>: expected setting not present: <needle>
a drifted ruler looks precise and reads wrong; fix the policy or the expectation before
trusting any projection.
```

Exit code 3: no projection is printed at all, which is the point.
