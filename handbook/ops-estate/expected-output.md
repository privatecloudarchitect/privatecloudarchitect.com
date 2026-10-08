# Expected output

The full cycle as `cycle.py` ran it on the reference estate (VCF Operations 9.1.1.0, 2026-10-08). Rendered by cycle.py from
`converge-run.json`, the record the same run wrote; your object ids will differ.

```
$ python3 converge.py --dry-run
  would create  Converge Demo - Ops Estate - VM - Active Memory (GiB)
  would create  Converge Demo - Ops Estate - VM - Consumed Memory (GiB)

dry-run: 2 created, 0 updated, 0 unchanged
```

```
$ python3 converge.py
  created       Converge Demo - Ops Estate - VM - Active Memory (GiB)
  created       Converge Demo - Ops Estate - VM - Consumed Memory (GiB)

converge: 2 created, 0 updated, 0 unchanged
run it again: a converged estate reports every object unchanged.
```

```
$ python3 converge.py
  unchanged     Converge Demo - Ops Estate - VM - Active Memory (GiB)
  unchanged     Converge Demo - Ops Estate - VM - Consumed Memory (GiB)

converge: 0 created, 0 updated, 2 unchanged
```

Then one formula and one description are edited in a temporary copy of `desired-state.json`:

```diff
- (${this, metric=mem|active_average} / 1048576)
+ (${this, metric=mem|active_average} / 1024 / 1024)
```

```diff
- Converge-demo metric: consumed guest memory in GiB. Safe to delete; owned by the ops-estate companion harness.
+ Converge-demo metric: consumed guest memory in GiB. Safe to delete; owned by the ops-estate companion harness. Edited in the file to show a description repair.
```

```
$ python3 converge.py
  updated       Converge Demo - Ops Estate - VM - Active Memory (GiB)  (id preserved: 6b671c74...)
  updated       Converge Demo - Ops Estate - VM - Consumed Memory (GiB)  (id preserved: 08a64bdb...)

converge: 0 created, 2 updated, 0 unchanged
run it again: a converged estate reports every object unchanged.
```

Then `Converge Demo - Ops Estate - VM - Consumed Memory (GiB)` is deleted directly, outside the converge, the way a rebuild by teardown would, and the converge runs again:

```
$ python3 converge.py
  unchanged     Converge Demo - Ops Estate - VM - Active Memory (GiB)
  created       Converge Demo - Ops Estate - VM - Consumed Memory (GiB)

converge: 1 created, 0 updated, 1 unchanged
run it again: a converged estate reports every object unchanged.
```

```
$ python3 teardown.py
  deleted       Converge Demo - Ops Estate - VM - Active Memory (GiB)
  deleted       Converge Demo - Ops Estate - VM - Consumed Memory (GiB)
  read-back:    all declared names gone

teardown: 2 deleted, 0 already absent
```

Then, read-only, the super metrics already on the instance under the owner prefix are exported and
dry-run against the converge. Only the summary line is kept in the record:

```
$ python3 export.py > mine.json
export.py: 100 super metric(s) named under the owner prefix
$ python3 converge.py --state mine.json --dry-run
dry-run: 0 created, 0 updated, 100 unchanged
```

What the script checked with its own reads, rather than taking from the scripts' messages:

- both repaired objects kept the ids the first run created (`idPreservedAcrossDriftRepair: true`), the formula and the description alike;
- the object deleted outside the converge came back with a different id (`recreate.idChanged: true`), which is
  what leaves anything that referred to it pointing at nothing;
- after the teardown, 0 demonstration objects were left;
- every exported super metric was reported unchanged (100 of 100): the converge adopted what was built by hand.
