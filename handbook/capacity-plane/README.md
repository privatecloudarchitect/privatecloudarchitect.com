# The capacity plane, added up and checked

Companion to the chapter
([privatecloudarchitect.com/handbook/capacity-plane](https://privatecloudarchitect.com/handbook/capacity-plane)):
one script that treats capacity as a set of objects rather than a number, adds the ledger up, and checks whether
it balances. Stdlib Python only; no token is printed or written.

| File | What it is |
|---|---|
| `capacity.py` | Reads the zones (a budget in spec, a consumption in status, for both limits and reservations), the namespaces (each with a per-zone budget of its own), then runs two checks: does a zone's reported consumption equal the sum of the namespaces' **limits** or of their **reservations**, and does a namespace hold what the class it names promised, field by field. Also reads the storage ledgers and the VM class catalog. With `--probe-overrides` it creates namespaces that depart from a class config deliberately and deletes them again. Writes `capacity.json`. |
| `capacity.json` | That record from the reference estate, 2026-09-18. The chapter's plates render it. |

## Run it

```bash
export VCFA_HOST=<automation-fqdn> VCFA_ORG=<org>
export VCFA_REFRESH_TOKEN_FILE=/path/to/refresh-token   # mode 0600
export TLS_VERIFY=false                                 # only on a self-signed lab CA

python3 capacity.py                    # read-only
python3 capacity.py --probe-overrides  # also creates and deletes namespaces, see below
```

## Two numbers that are not the same number

A zone reports one consumption figure, and there are two plausible things it could be counting. Summing the
namespaces' limits and the namespaces' reservations gives different totals, and only one of them is what a
create is measured against. The script computes both and prints which one the zone agrees with, so the answer
comes from your estate rather than from a page.

## About `--probe-overrides`

Comparing what namespaces hold against what their class promised shows that they differ. It does not show
**why**, because an override written at create and a class config edited afterwards leave identical evidence
behind. Nothing in a read can separate them. So this flag asks the platform directly: it creates namespaces
that depart from a config in a chosen direction, records what the platform did with each departure, and deletes
them. Every object it creates is one it made itself, and it verifies removal afterwards. Without the flag
nothing here writes.

**Running it again without the flag does not erase what the flag captured.** A run that did not probe has
nothing to say about that section of the record, which is different from having found it empty. So when the
record on disk holds a block this run did not produce, the block is carried forward and the script prints
that it carried it. The alternative, writing the section as empty, would have published a narrower record as
though it were a newer one.

## Scope, stated plainly

- Read-only by default. The probe flag is the only writer and it states what it sends.
- **Units are carried, not dropped.** This platform returns cpu in SI mega and memory and storage in binary
  mebi, side by side in one object. The record keeps the suffix; a bare integer here is a number nobody can
  convert later, including whoever dropped it.
- Class names, size names and field names are the product's own vocabulary and are kept, because the arithmetic
  is the lesson. Organization-specific names are placeholders, and the script refuses to write a record in
  which one survived.

## Reading the record

`units` states the two families before any figure appears. `zones` and `namespaces` carry the budgets as read;
`ledger` is the check, one row per zone with `sumOfLimits`, `sumOfReservations`, `zoneReportsUsed` and whether
they match. `configs` is what each class promises and `contract` is how often a namespace holds it (`agree` of
`total`, `byField`, and `widest` for the largest single divergence). `storage` is the per-class ledger with a
TiB conversion beside the raw figure; **do not add those rows up**, two of them are byte-identical views of one
pool. `vmClasses` carries the catalog count and how many require a reservation. `overrides` is present when the probe
ran, or when an earlier run's probe wrote it and this run carried it forward.
