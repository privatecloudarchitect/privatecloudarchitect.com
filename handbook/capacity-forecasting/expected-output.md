# Expected output

A run on the reference estate on 2026-10-18 (VCF Operations 9.1.1.0, build 25679751), with its cluster names and its
two posture policies' names replaced by placeholders. Your names and figures will differ.

```
$ python3 runway.py --record runway.json
ESTATE CAPACITY RUNWAY - 5 cluster(s), alloc/demand model(s), plain and commitment-adjusted

  THE RULER - each cluster's governing policy, read through the effective-policy query
  policy 1  <posture policy A>  governs 1 cluster(s)
    allocation ratios  cpu 1.5, memory 1, diskspace 2  (set here)
    buffers            0  (inherited)
    thresholds         critical 90d, warning 120d  (inherited)
  policy 2  <posture policy B>  governs 2 cluster(s)
    allocation ratios  cpu 8, memory 2.5, diskspace 4  (set here)
    buffers            0  (inherited)
    thresholds         critical 90d, warning 120d  (inherited)
  policy 3  Default Policy  governs 2 cluster(s)
    allocation ratios  cpu 4, memory 1, diskspace 2  (set here)
    buffers            0  (set here)
    thresholds         critical 90d, warning 120d  (inherited)

  cluster                pol   allo.cpu   allo.mem  allo.disk   dema.cpu   dema.mem  dema.disk  allo runway  dema runway  platform
  --------------------------------------------------------------------------------------------------------------------------------
  cluster-01               1         0d        98d        cap        cap        cap        cap           0d          cap        0d  CRITICAL
  cluster-02               2        cap        cap        cap        cap        cap        cap          cap          cap       cap
  cluster-03               2        cap        cap        cap        cap        cap        cap          cap          cap       cap
  cluster-04               3        cap        cap        cap         0d        cap        cap          cap           0d        0d  CRITICAL
  cluster-05               3        cap        cap        cap        cap        cap        cap          cap          cap       cap
  --------------------------------------------------------------------------------------------------------------------------------

  ALLOC RUNWAY: 0d - bound by cluster-01 on alloc.cpu

  DEMAND RUNWAY: 0d - bound by cluster-04 on demand.cpu
  First axis, first cluster, per model: how long each question's answer lasts before the tightest cluster
  runs out. The platform column is its own roll-up, the minimum across both models.

  3 of 5 cluster(s) read the 366-day cap on every axis. A capped metric at its
  cap has no gradient: those clusters are indistinguishable here, and the read screens rather than ranks.

  plain vs commitment-adjusted: 0 of 30 pair(s) differ.
  0 of 110 machine(s) carry a CPU or memory reservation, so the
  commitment-adjusted flavour has nothing to honour here. The pair is flat because of the estate,
  not because the distinction does not exist.

  wrote runway.json; clusters and policies are numbered and none is named
```

Exit code 2 (critical). Each cluster is graded by the `TIME_REMAINING` block of the policy that governs it, read
through the effective-policy query, so two clusters under different policies can be graded by different day counts.
`(inherited)` means the value comes from the policy's parent rather than from the policy itself; `(set here)` means the
policy sets it.

What each part of the output is there to stop:

- **the ruler first.** Every cluster is projected against its governing policy's allocation ratios, and on this
  estate three policies govern five clusters with three different rulers. A projection read without its ruler is a
  number with no unit.
- **one runway line per model.** The allocation and demand runways answer different questions, and here they are bound
  by different clusters. The `platform` column is the platform's own roll-up key, the minimum across both models: it
  agrees with the lower of the two per-model figures and never says which model it came from.
- **every cluster tied at the minimum is named.** When two clusters share the lowest figure, the line names both; a
  minimum over equal values would otherwise return whichever came first and present that as a finding.
- **the count at the cap.** Three identical rows reading `cap` are not three clusters with equal headroom, they are
  three clusters past the horizon this metric measures. The metric screens; it cannot rank.
- **the reservation census under a flat commitment pair.** A pair that reads the same has two opposite explanations:
  nothing is reserved, or the commitment-adjusted key is not collecting.

## With the parity gate

Declare the ratios you expect a policy to carry, in a copy of `parity.example.json`:

```
$ python3 runway.py --parity expectations.json
parity gate: 1 policy(ies) match their declared ratios exactly

ESTATE CAPACITY RUNWAY - 5 cluster(s), ...
```

And when the ruler and the declaration differ (here the declaration says `"cpu": 1` for a policy holding 1.5):

```
$ python3 runway.py --parity expectations.json
PARITY GATE REFUSED:
  - <posture policy A>: cpu declared 1, ruler reads 1.5
a drifted ruler looks precise and reads wrong; fix the policy or the expectation before trusting any projection.
```

Exit code 3: no projection is printed at all, which is the point. The gate compares parsed ratios, so `1` does not
satisfy `1.5` and the spacing of the serialized settings plays no part.

## When a read cannot be trusted

Exit code 4 means a read the run needs was refused or came back short: the cluster or machine list read fewer
resources than it declared, declared no total, or the stats query was refused. Nothing is projected, because a runway
over part of an estate names the wrong first cluster. If the effective-policy query alone is refused, the run prints the refusal,
prints no ruler, and grades every cluster against the script's fallback day counts (critical under 30, warning under
90), naming them as such.

## Writing a record

`--record runway.json` writes the run as JSON for a report or a chart. Clusters are numbered by their place in the
sorted list and policies by the order they were first met; no cluster or policy name is written to it, and the run
refuses to write a record that would carry one.
