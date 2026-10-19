# The capacity plane, added up and checked

Companion to the chapter
([privatecloudarchitect.com/handbook/capacity-plane](https://privatecloudarchitect.com/handbook/capacity-plane)):
one script that treats capacity as a set of objects rather than a number, adds the ledger up, and checks whether
it balances. Stdlib Python only; no token is printed or written.

**Provenance:** read on VCF Automation 9.1.1.0100 on 2026-10-19 under a session login, and the override probe
run the same day, with the operator's approval, into a project that held no namespace
([`expected-output.md`](expected-output.md)). The 9.1 probe of 2026-09-18 is kept in [`records/`](records/).

| File | What it is |
|---|---|
| `capacity.py` | Reads the zones (a budget in spec, a consumption in status, for both limits and reservations), every project with the bindings it holds, and every namespace (each with a per-zone budget of its own), then runs two checks: does a zone's reported consumption equal the sum of the namespaces' **limits** or of their **reservations**, for cpu and for memory, and does a namespace hold what the class it names promised, field by field. Also reads the storage ledgers and the VM class catalog. With `--probe-overrides --project <name>` it creates namespaces in that project that depart from a class config deliberately and deletes them again. Writes `capacity.json`. |
| `capacity.json` | That record from the reference estate. The chapter's plates render it. |
| `expected-output.md` | What the script printed on the reference estate, the read-only run and the probe. |
| `records/capacity-overrides-vcf-9.1.json` | The probe's section of the record from the 9.1 run of 2026-09-18, as that run wrote it. |

## Run it

```bash
export VCFA_HOST=<automation-fqdn> VCFA_ORG=<org> VCFA_USER=<account>
( umask 077; mkdir -p ~/.vcf && cat > ~/.vcf/vcfa-password )   # paste your password, then Ctrl-D
export VCFA_PASSWORD_FILE=~/.vcf/vcfa-password             # mode 0600; or VCFA_REFRESH_TOKEN_FILE
export TLS_VERIFY=false                                    # only on a self-signed lab CA

python3 capacity.py                                        # read-only
python3 capacity.py --probe-overrides --project <name>     # also creates and deletes namespaces there, see below
```

The sign-in is a session login as `<account>@<org>`, or a refresh token minted for the organization in a file of
mode 0600. A secret file open to group or other is refused before it is read. A zone is an organization-wide
object, so run it as someone who can see every project: the script sums the namespaces of every project the
sign-in can see.

Exit codes: 0 read (with the probe, every namespace it made is gone and the zones read as they did before it);
2 a call failed or the sign-in was refused; 3 the probe left a namespace behind, or the zones did not come back
to their starting figures; 5 an unknown argument, or `--probe-overrides` without `--project` naming a project the
sign-in can see.

## Two numbers that are not the same number

A zone reports one consumption figure, and there are two plausible things it could be counting. Summing the
namespaces' limits and the namespaces' reservations gives different totals, and only one of them is what a
create is measured against. The script computes both and prints which one the zone agrees with, so the answer
comes from your estate rather than from a page. The zone's reservation column is checked the same way, against
the reservations the namespaces hold.

## About `--probe-overrides`

Comparing what namespaces hold against what their class promised shows that they differ. It does not show
**why**, because an override written at create and a class config edited afterwards leave identical evidence
behind. Nothing in a read can separate them. So this flag asks the platform directly. In the project you name,
and nowhere else, it sends creates from the `small` class config (or the first config) that each depart in one
direction: cpu above and below the config, no override at all, a zone named with no figures, storage below and
above the config, the config's own figures in a zone with no limit budget left, and the same create sent with
`dryRun=All`. It records what the platform did with each, deletes every namespace a create made, waits until each
is gone (re-sending the delete every two minutes, for twenty at most), and reads the zones again to compare them
with the figures it read before the first create. Name a project nobody depends on: the namespaces it makes hold
zone budget until their teardown finishes. Without the flag nothing here writes.

**Running it again without the flag does not erase what the flag captured.** A run that did not probe has
nothing to say about that section of the record, which is different from having found it empty. So when the
record on disk holds a block this run did not produce, the block is carried forward and the script prints
that it carried it. The alternative, writing the section as empty, would have published a narrower record as
though it were a newer one.

## Scope, stated plainly

- Read-only by default. The probe flag is the only writer, it writes only into the project it is told, and it
  states what it sends.
- **Units are carried, not dropped.** This platform returns cpu in SI mega and memory and storage in binary
  mebi, side by side in one object. The record keeps the suffix; a bare integer here is a number nobody can
  convert later, including whoever dropped it.
- Class names, size names and field names are kept, because the arithmetic is the lesson. A class config named
  for no class carries the organization's own name, so it is a placeholder like every other organization name,
  and the script refuses to write a record in which one survived.

## Reading the record

`units` states the two families before any figure appears, and `zoneGetByName` is what a get of one zone by its
own object name answered. `zones` and `namespaces` carry the budgets as read; `bindings` lists each project with
the namespaces it hosts and the region, class and VPC bindings it holds. `ledger` is the check, one row per zone
with `sumOfLimits`, `sumOfReservations`, `zoneReportsUsed` and whether they match, the same for memory
(`memorySumOfLimits`, `memoryReportsUsed`, `memoryBalances`), and what is left (`cpuFree`, `memoryFree`) and drawn
(`reservationDrawnDown` of `reservationBudget`). `configs` is what each class promises and `contract` is how often
a namespace holds it (`agree` of `total`, `byField`, `widest` for the largest single divergence, `exact` for the
namespaces that hold their class's four figures, and `storageInherited` for those that omit storage and take the
config's limit). `storage` is the per-class ledger with a TiB conversion beside the raw figure; **do not add those
rows up**, two of them are byte-identical views of one pool. `vmClasses` carries the catalog count and how many
require a reservation. `overrides` is present when the probe ran, or when an earlier run's probe wrote it and this
run carried it forward: `probedUtc`, the `project` it wrote into, each case with its status and outcome, how many
namespaces it `made`, `teardownSeconds`, any `residue`, and `zonesBefore`, `zonesAfter` and `zonesReturned`.
