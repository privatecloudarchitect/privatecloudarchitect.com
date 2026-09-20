# Runway harness

Backs the capacity-forecasting sheet
([privatecloudarchitect.com/handbook/capacity-forecasting](https://privatecloudarchitect.com/handbook/capacity-forecasting)).
The sheet's three rules, runnable against your own VCF Operations instance:

1. **The primitive**, and it is a family rather than a key. Time remaining is
   `OnlineCapacityAnalytics|<axis>|<model>|timeRemaining[WithCommit]`: three axes (`cpu`, `mem`,
   `diskspace`) by two capacity models (`alloc` against configured capacity and the policy's
   overcommit ratios, `demand` against observed use) by two flavours (plain, and
   commitment-adjusted, which honours resident reservations), plus the platform's own per-cluster
   roll-up in both flavours. Fourteen keys, one stats query. The model in the key name is the
   question you asked, and a chart titled "runway" with no model named cannot be acted on.
2. **The roll-up**: pessimistic by construction. A cluster's runway is its first axis to run
   out; the estate's runway is its first cluster; the number always prints with its cluster and
   axis attached, and the exit code encodes the verdict (0 healthy, 1 warning, 2 critical).
   Severity comes from the governing policy's own `TIME_REMAINING` block rather than from
   constants in the script.
3. **The ruler**: optionally, the script refuses to project at all until a parity gate passes
   (`--parity expectations.json`), because a projection measured against a drifted allocation
   policy looks precise and reads wrong.

## Run it

```bash
export OPS_HOST=<your-ops-fqdn>
export OPS_BROKER_HOST=<your-broker-fqdn>    # omit if the broker shares the Ops FQDN
export OPS_API_TOKEN=<your-api-token>        # OPS_REALM defaults to CUSTOMER
export OPS_TLS_VERIFY=false                  # only on a self-signed lab CA

python3 runway.py
python3 runway.py --parity parity.example.json    # after editing the example
```

Stdlib Python only; `opslib.py` holds the broker exchange (the same api-token flow the
handbook's Part 0 identity chapter teaches). The script reads; it writes nothing.

## The parity gate, and why it compares values

You declare, per ruler policy, the allocation ratios it should carry:

```json
{ "<your allocation policy name>": { "cpu": 1.5, "memory": 1.0, "diskspace": 2.0 } }
```

The gate reads `GET /api/policies/{id}/settings?type=CAPACITY_ALLOCATION_MODEL` for cluster
resources, **parses** the allocation block, and compares numbers. Any difference refuses the
projection (`--parity-warn` downgrades refusal to a warning).

An earlier version of this gate searched the serialized settings for declared substrings, and
both failure directions were reproduced against a live policy before it was replaced. Against
numeric settings a substring test is prefix matching: `"cpu": 1` matches a ruler that has drifted
to `15.0`, so drift passes the gate that exists to catch it; and `"cpu":1.5` without the space
the JSON serializer emits refuses a ruler reading exactly 1.5, so the operator loses the forecast
and the message points at a policy that is correct. Compare parsed values, not renderings.

### The ruler is three blocks, and `type` is required

The settings endpoint answers HTTP 400 without a `type`, and each value returns a different block:

| `type` | what it governs |
|---|---|
| `CAPACITY_ALLOCATION_MODEL` | the overcommit ratios the projection measures against |
| `CAPACITY_BUFFER` | headroom held back, per axis, per model |
| `TIME_REMAINING` | the critical and warning day counts |

Every response carries an `inherited` flag. `false` means this policy sets the value; `true`
means you are reading the default policy showing through, and confirming an inherited value tells
you about the default rather than about the posture you meant to check. The gate prints a note
when the block it verified is inherited.

## Reading the output

A fleet can average years of headroom while one cluster sits at sixty days on one axis; that
cluster and axis ARE the estate's runway. If every cell shows `-`, capacity analytics has not
finished computing for those clusters yet; give a fresh instance a collection cycle.

Three things the run prints that stop a misreading:

- **`cap` is not a value.** The platform caps time remaining at 366 days. Clusters reading the cap
  are past the horizon the metric measures and are indistinguishable from each other, so the read
  screens rather than ranks; the run prints how many clusters are pinned there. Ranking capped
  clusters needs a capacity-remaining percentage, not a time projection.
- **a tie has no binding axis.** When every axis reads the cap, `min()` returns whichever key came
  first, which is dictionary order presented as a finding. The run reports no binding axis instead.
- **a flat commitment pair gets a census.** Plain and commitment-adjusted reading the same number
  has two opposite explanations: nothing is reserved, or the commitment-adjusted key is not
  collecting. When no pair differs, the run counts the machines carrying a CPU or memory
  reservation and prints it, so the flatness is explained rather than presented.

## Writing a record

`--record runway.json` writes the run as JSON for a report or a chart. Clusters are numbered by
their place in the sorted list; no cluster name is written to the record.

## Expected output

See [`expected-output.md`](expected-output.md) for the transcript shape.
