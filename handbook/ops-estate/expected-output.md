# Expected output

The full cycle on a healthy instance:

```
$ python3 converge.py --dry-run
  would create  Converge Demo - Ops Estate - Super Metric - Active Memory GiB
  would create  Converge Demo - Ops Estate - Super Metric - Consumed Memory GiB

dry-run: 2 created, 0 updated, 0 unchanged

$ python3 converge.py
  created       Converge Demo - Ops Estate - Super Metric - Active Memory GiB
  created       Converge Demo - Ops Estate - Super Metric - Consumed Memory GiB

converge: 2 created, 0 updated, 0 unchanged
run it again: a converged estate reports every object unchanged.

$ python3 converge.py
  unchanged     Converge Demo - Ops Estate - Super Metric - Active Memory GiB
  unchanged     Converge Demo - Ops Estate - Super Metric - Consumed Memory GiB

converge: 0 created, 0 updated, 2 unchanged
```

Edit one formula in `desired-state.json` (drift), then:

```
$ python3 converge.py
  updated       Converge Demo - Ops Estate - Super Metric - Active Memory GiB  (id preserved: 1a2b3c4d...)
  unchanged     Converge Demo - Ops Estate - Super Metric - Consumed Memory GiB

converge: 0 created, 1 updated, 1 unchanged
```

The id in the updated line matches the id the create minted: adoption is id-preserving, which
is what keeps every reference to the object alive across repairs.

```
$ python3 teardown.py
  deleted       Converge Demo - Ops Estate - Super Metric - Active Memory GiB
  deleted       Converge Demo - Ops Estate - Super Metric - Consumed Memory GiB
  read-back:    all declared names gone

teardown: 2 deleted, 0 already absent
```
