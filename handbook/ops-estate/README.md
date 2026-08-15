# Converge harness

Backs the operations-content sheet
([privatecloudarchitect.com/handbook/ops-estate](https://privatecloudarchitect.com/handbook/ops-estate)).
The sheet's doctrine is that operations content is code: objects addressed by stable, parseable
names, asserted by one level-triggered converge, with teardown a separate and scoped tool. This
harness runs that doctrine against your own VCF Operations instance in about a minute, using two
deliberately boring super metrics as the demonstration objects.

## What it proves

1. **Adopt-or-create by name.** A declared name that is absent is created; a name that is live
   is adopted with an id-preserving update. Instance ids are read from the estate, never stored
   in the declaration.
2. **Level-triggered convergence.** The second run reports every object unchanged. Edit a
   formula in `desired-state.json` and run again: exactly one object repairs, id preserved.
3. **Teardown is scoped and separate.** `teardown.py` deletes only the declared names and
   verifies each with a read-back; it cannot touch anything else on your estate.

## What it creates (and removes)

Two super metrics named under the `Converge Demo - Ops Estate - ...` schema, computing active
and consumed guest memory in GiB from stock metric keys. They are enabled in no policy, so they
compute nothing and page nobody; they exist to be converged and deleted.

## Prereqs

An api-token minted in your operations console, and the broker exchange the handbook's Part 0
identity chapter teaches. Set the environment and run:

```bash
export OPS_HOST=<your-ops-fqdn>
export OPS_BROKER_HOST=<your-broker-fqdn>    # omit if the broker shares the Ops FQDN
export OPS_API_TOKEN=<your-api-token>        # OPS_REALM defaults to CUSTOMER
export OPS_INSECURE=1                        # only on a self-signed lab CA

python3 converge.py --dry-run   # reads only; shows what would change
python3 converge.py             # run 1: created 2
python3 converge.py             # run 2: unchanged 2 (the level-trigger proof)
# edit one formula in desired-state.json, then:
python3 converge.py             # updated 1, unchanged 1, id preserved
python3 teardown.py             # deleted 2, read-back verified
```

Everything is stdlib Python; `opslib.py` holds the broker exchange and the request plumbing.

## The estate-scale version

This harness demonstrates the pattern on one object class. The reference estate runs the same
doctrine across tags, groups, policies, super metrics, views, and alerts, generator-sequenced in
dependency order; the sheet describes that shape, and this harness is its minimal faithful core:
the same list-adopt-create-verify cycle, small enough to read in one sitting.

## Expected output

See [`expected-output.md`](expected-output.md) for the transcript shape of the full cycle.
