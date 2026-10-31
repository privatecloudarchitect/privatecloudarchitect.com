# Is the upgrade the registry is offering actually available?

Companion to the chapter
([privatecloudarchitect.com/handbook/platform-lifecycle](https://privatecloudarchitect.com/handbook/platform-lifecycle)):
one read-only script that answers the question worth asking before a change window. Stdlib Python only; no token
is printed or written.

| File | What it is |
|---|---|
| `lifecycle.py` | Reads the releases the instance knows about, the bundle depot counted by download status, and the upgradable state, then **joins** the offered upgrades to the bundles behind them and reports how much is still to fetch, in the API's own unit (sizeMB). Name a second instance and it compares your rehearsal instance with the one it rehearses for. It also follows a retired endpoint to the replacement its own `410` names. Writes `lifecycle.json`, and refuses to write a record carrying an instance name. |
| `lifecycle.json` | That record from the reference estate, 2026-10-21, both instances. The chapter's plates render it; `records/lifecycle-2026-10-21.json` holds the same reading, so a new run's overwrite of this file leaves it in place. |

## Run it

```bash
export SDDC_HOST=<sddc-manager-fqdn>
export SDDC_TOKEN_FILE=/path/to/bearer      # mode 0600
export TLS_VERIFY=false                     # only on a self-signed lab CA

# optional, to compare the instance you rehearse on:
export SDDC_REHEARSAL_HOST=<other-sddc-manager-fqdn>
export SDDC_REHEARSAL_TOKEN_FILE=/path/to/other-bearer   # mode 0600

python3 lifecycle.py
```

| Exit | Meaning |
|---|---|
| 0 | nothing to act on: every offered upgrade has its content staged, or nothing is offered |
| 1 | an offered upgrade's content is not staged on the instance asked about: the weekly alert keys on this |
| 2 | an argument was given, a setting is missing, or a token file is open to group or other |
| 3 | a read failed, so the answer is unknown |
| 4 | the record refused to write because an estate name survived the scrub |

`expected-output.md` shows what it printed on the reference estate, and `records/lifecycle-2026-09-21.json` is the reading from a day an upgrade was on offer with nothing staged.

## The join is the point

The registry offers and the depot decides, and the two reads are rarely put side by side. An upgrade can read
as available with none of its content downloaded, which is discovered either on an ordinary Tuesday for the
price of two listings, or inside a change window for the price of the window. On the reference estate every
offered upgrade was backed by nothing at all.

Two traps the script handles so you do not have to:

- **Sum sizes over distinct bundle ids.** Several upgradables can reference one bundle, and adding a size per
  upgradable counts the shared one twice. The first version of this script overstated the download by exactly
  that bundle's size.
- **The upgradable read keys on the management domain.** A workload domain's own id is refused with a message
  saying the management domain was not found, which is true and reads like a missing object. Filter to the
  management domain before any loop.

## Scope, stated plainly

- Read-only. Nothing here stages, prechecks or upgrades anything.
- Prechecks and upgrade execution have **not** been exercised by this companion or the chapter it backs. Both
  are marked as vendor documented wherever they appear, and that gap is stated rather than left to be inferred.
- Every instance and domain name in the record is a placeholder, and the script refuses to write a record in
  which one survived.

## Reading the record

`instances` carries one entry per instance read. Inside each: `domains` split into management and workload,
`releases` known, `bundles` with `byStatus` (`PENDING` means known about and not downloaded), `upgradables`
offered, `distinctBundlesOffered` and `offeredAndStaged`, and `unstagedMB` as the outstanding download, summed
over distinct bundles in the API's own unit. A record written before 2026-10-07 carries `unstagedGB` instead:
the same sum divided by 1024 and labelled GB, which names a decimal unit for a binary division; read it as MB
divided by 1024. `join`
is one row per offer with the bundle behind it and whether it is staged. `workloadDomainRefusal` quotes the
refusal rather than describing it, and `depot` records which endpoint served the depot configuration on your
build and what it reported.
