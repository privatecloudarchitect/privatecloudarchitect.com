# Runway harness

Backs the capacity-forecasting sheet
([privatecloudarchitect.com/handbook/capacity-forecasting](https://privatecloudarchitect.com/handbook/capacity-forecasting)).
The sheet's three rules, runnable against your own VCF Operations instance:

1. **The primitive**: time remaining in days, commitment-adjusted, per resource axis, per
   cluster, read as the `OnlineCapacityAnalytics|<axis>|alloc|timeRemainingWithCommit` statkeys
   through the stats API.
2. **The roll-up**: pessimistic by construction. A cluster's runway is its first axis to run
   out; the estate's runway is its first cluster; the number always prints with its cluster and
   axis attached, and the exit code encodes the verdict (0 healthy, 1 warning, 2 critical).
3. **The ruler**: optionally, the script refuses to project at all until a config-parity gate
   passes (`--parity expectations.json`), because a projection measured against a drifted
   allocation policy looks precise and reads wrong.

## Run it

```bash
export OPS_HOST=<your-ops-fqdn>
export OPS_BROKER_HOST=<your-broker-fqdn>    # omit if the broker shares the Ops FQDN
export OPS_API_TOKEN=<your-api-token>        # OPS_REALM defaults to CUSTOMER
export OPS_INSECURE=1                        # only on a self-signed lab CA

python3 runway.py
python3 runway.py --parity parity.example.json    # after editing the example
```

Stdlib Python only; `opslib.py` holds the broker exchange (the same api-token flow the
handbook's Part 0 identity chapter teaches). The script reads; it writes nothing.

## The parity gate, honestly scoped

The gate is deliberately minimal: you declare, per ruler policy, strings that must appear in
that policy's allocation-model read (`GET /api/policies/{id}/settings?type=CAPACITY_ALLOCATION_MODEL`
for cluster resources), typically the encoded allocation ratios. Present means the ruler still says what you declared; absent means drift,
and the projection is refused (`--parity-warn` downgrades refusal to a warning). The reference
estate runs a richer parity pass comparing full policy records; this gate is its portable core.

## Reading the output

A fleet can average years of headroom while one cluster sits at sixty days on one axis; that
cluster and axis ARE the estate's runway. If every cell shows `-`, capacity analytics has not
finished computing for those clusters yet; give a fresh instance a collection cycle.

## Expected output

See [`expected-output.md`](expected-output.md) for the transcript shape.
