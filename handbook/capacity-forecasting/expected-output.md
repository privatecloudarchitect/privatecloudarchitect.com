# Expected output

A run against a small estate (your cluster names and figures will differ):

```
$ python3 runway.py
ESTATE CAPACITY RUNWAY - 5 cluster(s), alloc/demand model(s), plain and commitment-adjusted
severity from the policy's own TIME_REMAINING block (inherited): critical under 90d, warning under 120d

  cluster                  allo.cpu   allo.mem  allo.disk   dema.cpu   dema.mem  dema.disk   runway
  ---------------------------------------------------------------------------------------------------
  cluster-01                     0d        cap        cap        cap        cap        cap       0d  CRITICAL
  cluster-02                    cap        cap        cap        cap        cap        cap      cap
  cluster-03                    cap        cap        cap        cap        cap        cap      cap
  cluster-04                    cap        cap        cap        cap        cap        cap      cap
  cluster-05                    cap        cap        cap        cap        cap        cap      cap
  ---------------------------------------------------------------------------------------------------

  ESTATE RUNWAY: 0d  (CRITICAL) - bound by cluster-01 on alloc.cpu.
  First axis, first cluster: the estate can place projected demand this long before
  its tightest cluster runs out.

  4 of 5 cluster(s) read the 366-day cap on every axis. A capped
  metric at its cap has no gradient: those clusters are indistinguishable here, and the
  read screens rather than ranks.

  plain vs commitment-adjusted: 0 of 30 pair(s) differ.
  0 of 103 machine(s) carry a CPU or memory reservation, so the
  commitment-adjusted flavour has nothing to honour here. The pair is flat because of
  the estate, not because the distinction does not exist.
```

Exit code 2 (critical) here. Severity comes from the governing policy's own `TIME_REMAINING`
block, not from constants in the script: a harness that verifies a ruler and then grades against
its own numbers has not used the thing it verified. `(inherited)` means those day counts come from
the default policy rather than from the posture.

Three lines in that output are there to stop a misreading:

- **the count at the cap.** Four identical rows reading `cap` are not four clusters with equal
  headroom, they are four clusters past the horizon this metric measures. The metric screens; it
  cannot rank.
- **the binding axis, when there is one.** A cluster whose axes are all tied at the cap has no
  binding axis, and the table reports none rather than letting `min()` return whichever key came first.
- **the reservation census under a flat commitment pair.** A pair that reads the same has two
  opposite explanations: nothing is reserved, or the commitment-adjusted key is not collecting.

## With the parity gate

```
$ python3 runway.py --parity expectations.json
parity gate: 1 policy(ies) match their declared ratios exactly

ESTATE CAPACITY RUNWAY - 5 cluster(s), ...
```

And when the ruler has drifted from the declaration:

```
$ python3 runway.py --parity expectations.json
PARITY GATE REFUSED:
  - <policy>: cpu declared 1, ruler reads 1.5
a drifted ruler looks precise and reads wrong; fix the policy or the expectation before
trusting any projection.
```

Exit code 3: no projection is printed at all, which is the point.

The gate compares **parsed ratios**, not substrings. An earlier version searched the serialized
settings for declared strings, and both failure directions were reproduced against a live policy
before it was replaced: `"cpu": 1` matched a ruler reading `15.0` (a drifted ruler passing the
gate), and `"cpu":1.5` written without the space the serializer emits refused a ruler reading
exactly 1.5 (a correct ruler losing its forecast). Against numeric settings a substring test is
prefix matching, which is not what a parity check means.

## Writing a record

`--record runway.json` writes the run as JSON for a report or a chart. Clusters are numbered by
their place in the sorted list and no cluster name is written to it.
