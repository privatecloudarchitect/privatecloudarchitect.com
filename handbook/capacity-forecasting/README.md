# Runway harness

Backs the capacity-forecasting chapter
([privatecloudarchitect.com/handbook/capacity-forecasting](https://privatecloudarchitect.com/handbook/capacity-forecasting)).
One read-only command reports how long each capacity model's answer lasts before the tightest cluster runs out, with
the cluster, the axis and the ruler attached:

1. **The family, not a key.** Time remaining is `OnlineCapacityAnalytics|<axis>|<model>|timeRemaining[WithCommit]`:
   three axes (`cpu`, `mem`, `diskspace`) by two capacity models (`alloc` against configured capacity and the policy's
   overcommit ratios, `demand` against observed use) by two flavours (plain, and commitment-adjusted, which honours
   resident reservations), plus the platform's own per-cluster roll-up in both flavours. Fourteen keys, one stats
   query.
2. **The ruler each cluster is measured against.** The run asks the effective-policy query which policy governs each
   cluster and prints that policy's three capacity blocks (allocation ratios, buffers, time-remaining thresholds), each
   marked set here or inherited. Each cluster is graded by its own policy's thresholds.
3. **The roll-up, per model.** A cluster's runway is its first axis to run out; the estate's runway is its first
   cluster. The run prints one line for the allocation model and one for the demand model, naming every cluster tied at
   the minimum, and the exit code encodes the worst verdict (0 healthy, 1 warning, 2 critical).
4. **The parity gate**, optional (`--parity expectations.json`): it refuses to project at all until the policies you
   name carry the allocation ratios you declare, compared as parsed numbers.

## Run it

```bash
export OPS_HOST=<your-ops-fqdn>
export OPS_BROKER_HOST=<your-broker-fqdn>    # omit if the broker shares the Ops FQDN
( umask 077; mkdir -p ~/.vcf && cat > ~/.vcf/ops-api-token )   # paste your api-token, then Ctrl-D
export OPS_API_TOKEN_FILE=~/.vcf/ops-api-token   # mode 0600; OPS_REALM defaults to CUSTOMER
export OPS_TLS_VERIFY=false                  # only on a self-signed lab CA

python3 runway.py
python3 runway.py --model alloc              # one model only
python3 runway.py --record runway.json       # also write the run as JSON
cp parity.example.json expectations.json     # then put your policy names and ratios in the copy
python3 runway.py --parity expectations.json
```

The api-token is read from `OPS_API_TOKEN_FILE`, a file of mode 0600; a wider mode is refused. The value itself in
`OPS_API_TOKEN` still works, but it lands in the shell's history and the process list, so keep it for a throwaway
credential.

Stdlib Python 3 only; `opslib.py` holds the broker exchange (the api-token flow the handbook's platform-identity
chapter teaches). The script reads; it writes nothing on the instance. The identity behind the api-token needs read
access to the clusters, the virtual machines and the policies.

The governing policy is read through `POST /suite-api/internal/policies/effective/query`, an internal endpoint that
answers only with the header `X-Ops-API-use-unsupported: true`. If your instance refuses it, the run prints that refusal, prints no
ruler, and grades against the script's fallback day counts (critical under 30, warning under 90), naming them as such.

## Exit codes

| code | meaning |
|---|---|
| 0 | every cluster's runway is at or above its policy's warning threshold |
| 1 | at least one cluster under its policy's warning threshold |
| 2 | at least one cluster under its policy's critical threshold |
| 3 | the parity gate refused: a declared ratio differs from the ruler, so nothing is projected |
| 4 | a read the run needs was refused or came back short, so nothing is projected |

## The ruler is three blocks, and `type` is required

The settings endpoint, `GET /api/policies/{id}/settings`, answers HTTP 400 without a `type`, and each value returns a
different block (with `resourceKind=ClusterComputeResource&adapterKind=VMWARE&includeInherited=true`):

| `type` | what it governs |
|---|---|
| `CAPACITY_ALLOCATION_MODEL` | the overcommit ratios the projection measures against |
| `CAPACITY_BUFFER` | headroom held back, per axis, per model |
| `TIME_REMAINING` | the critical and warning day counts |

Every block carries an `inherited` flag. `false` means this policy sets the value; `true` means the value comes from
the policy's parent, and a check that confirms it is confirming the parent, not the posture you meant to check.

## The parity gate compares values

You declare, per policy, the allocation ratios it should carry:

```json
{ "<your allocation policy name>": { "cpu": 1.5, "memory": 1.0, "diskspace": 2.0 } }
```

The gate reads each named policy's `CAPACITY_ALLOCATION_MODEL` block, parses it, and compares numbers. Any
difference refuses the projection (`--parity-warn` downgrades the refusal to a warning). A test that searched the
serialized settings for the declared text would be prefix matching: `"cpu": 1` would match a ruler that had drifted
to `15.0`, and `"cpu":1.5` written without the space the serializer emits would refuse a ruler reading exactly 1.5.

## Reading the output

See [`expected-output.md`](expected-output.md) for a full run. Four things in it stop a misreading:

- **`cap` is not a value.** The platform caps time remaining at 366 days. Clusters reading the cap are past the
  horizon the metric measures and are indistinguishable from each other, so the read screens rather than ranks; the
  run prints how many clusters are pinned there. Ranking capped clusters needs a capacity-remaining percentage, not a
  time projection.
- **one line per model.** The allocation and demand runways can be bound by different clusters. The `platform` column
  is the platform's own roll-up, the minimum across both models, so it agrees with the lower line and never names the
  model.
- **a tie names everyone.** When several axes of a cluster, or several clusters, share the minimum, the run names all
  of them rather than letting `min()` return whichever came first.
- **a flat commitment pair gets a census.** Plain and commitment-adjusted reading the same number has two opposite
  explanations: nothing is reserved, or the commitment-adjusted key is not collecting. When no pair differs, the run
  counts the machines carrying a CPU or memory reservation and prints it.

If every cell shows `-`, capacity analytics has not finished computing for those clusters; give a fresh instance a
collection cycle.

## Writing a record

`--record runway.json` writes the run as JSON for a report or a chart. Clusters are numbered by their place in the
sorted list and policies by the order they were first met; no cluster or policy name is written, and the run refuses
to write a record that would carry one. `runway.json` in this folder is the reference estate's run of 2026-10-18 on
VCF Operations 9.1.1.0 (build 25679751), the record the chapter renders.
