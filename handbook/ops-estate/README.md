# Operations content as code: converge it, then audit it

Backs the operations-content chapter
([privatecloudarchitect.com/handbook/ops-estate](https://privatecloudarchitect.com/handbook/ops-estate)).
The chapter's doctrine is that operations content is code: objects addressed by stable, parseable names,
asserted by one level-triggered converge, with teardown a separate and scoped tool. Two harnesses here, both
stdlib Python, both running against your own VCF Operations instance.

| Harness | What it does |
|---|---|
| `converge.py`, `teardown.py` | **Asserts desired state.** Adopt-or-create by name, level-triggered, id-preserving, with a scoped teardown. Writes to your estate, on two deliberately boring demonstration objects. |
| `content.py` | **Audits the estate.** Read-only. Counts every content class, tests your names against your own schema, resolves every reference between objects, reports what the governing policy actually decides, and probes for the read surfaces that do not exist. |
| `opslib.py` | Shared plumbing: the broker exchange and the request helper both harnesses use. |
| `desired-state.json`, `expected-output.md`, `content.json` | The converge declaration, its transcript, and the audit record the chapter's plates render. |

## Prereqs, shared by both

An api-token minted in your operations console, and the broker exchange the handbook's Part 0 identity chapter
teaches. On 9.1 the older username and password token-acquire flow is rejected for federated users.

```bash
export OPS_HOST=<your-ops-fqdn>
export OPS_BROKER_HOST=<your-broker-fqdn>    # omit if the broker shares the Ops FQDN
export OPS_API_TOKEN=<your-api-token>        # OPS_REALM defaults to CUSTOMER
export OPS_TLS_VERIFY=false                  # only on a self-signed lab CA
```

## The converge harness

```bash
python3 converge.py --dry-run   # reads only; shows what would change
python3 converge.py             # run 1: created 2
python3 converge.py             # run 2: unchanged 2 (the level-trigger proof)
# edit one formula in desired-state.json, then:
python3 converge.py             # updated 1, unchanged 1, id preserved
python3 teardown.py             # deleted 2, read-back verified
```

What it proves:

1. **Adopt-or-create by name.** A declared name that is absent is created; a name that is live is adopted
   with an id-preserving update. Instance ids are read from the estate, never stored in the declaration.
2. **Level-triggered convergence.** The second run reports every object unchanged.
3. **Teardown is scoped and separate.** It deletes only the declared names and verifies each with a
   read-back; it cannot touch anything else on your estate.

It creates two super metrics named under the `Converge Demo - Ops Estate - ...` schema, computing active and
consumed guest memory in GiB from stock metric keys. They are enabled in no policy, so they compute nothing
and page nobody; they exist to be converged and deleted.

This demonstrates the pattern on one object class. The reference estate runs the same doctrine across tags,
groups, policies, super metrics, views and alerts, generator-sequenced in dependency order; this harness is
its minimal faithful core, small enough to read in one sitting. See
[`expected-output.md`](expected-output.md) for the transcript shape.

## The audit harness

```bash
export OPS_OWNER="PCA"      # the owner prefix your content carries
python3 content.py
```

Four questions, one read-only pass:

1. **How much is there, and how much of it is yours?** Every class walked to its declared total, never to one
   page. On the reference estate: 5,172 objects of which 158 were ours. That ratio is the entire argument for
   a parseable name, because you cannot rename the other 5,014.
2. **Does your content hold the standard you publish?** Per class, how many names carry the four fields, and
   how many fields the rest actually use. A class that diverges **consistently** is the standard being wrong
   about that class; a class that diverges in ones and twos is drift. A total cannot tell those apart.
3. **Does every reference resolve?** Alert definition to symptom definition, custom group to policy,
   notification rule to alert definition. This is the check that catches an id re-minted by a rebuild, which
   is the failure the chapter opens with.
4. **What does the governing policy actually decide?** The alert definitions present against the ones the
   policy sets. Everything else is UNSET, a third origin and not a synonym for disabled.

### Three ways the audit answers wrongly, each of which it did first

- **A negated reference is still a reference.** A symptom id inside an alert definition may carry a leading
  `!`, which negates it. Resolve the id without the marker, or a healthy estate reports every negated
  reference as broken. There were 34 of them here.
- **A filter can be an object, not a list.** `rules[].alertDefinitionIdFilters` is an object carrying a
  `values` array. Iterating the object yields its field names and reports those as dangling ids.
- **Ownership is the prefix AND the separator.** Testing for `PCA` also claims a vendor object called
  `PCAP Export Purge Failure`. The test is `PCA - `.

### Alert state

There is no JSON surface for it. The policy export is the read path, it must be requested with
`Accept: application/zip` (any other accept type answers a 500 that means "cannot determine", never anything
about the policy), and the archive carries the policy's whole ancestor chain. Alert state has **three
origins**, not two states: LOCAL, INHERITED and UNSET, and UNSET must be reported as null rather than as
enabled. `content.py` counts explicit entries; the full contract is the field guide the chapter cites.

### Scope, stated plainly

- `content.py` is read-only. Every call is a `GET`. It creates, converges and deletes nothing.
- The absence claim about dashboards and views is scoped to the paths it probes, and the record carries each
  path with its status so a later build can be rechecked rather than believed.
- **Only your own object names are published.** Every other object on the instance appears as a count: an
  estate's object names are its own business, and the audit does not need them.

### Reading the record

`census` is one row per class with the total, how many are yours, how many conform, and a histogram of how
many fields your names actually carry. `totals` is the three headline numbers. `ownedNames` is the full list
of your objects, which is the inventory a parseable name buys you. `integrity` carries the reference count per
edge type with the dangling count, plus `negatedSymptomReferences` so the trap is visible in the data.
`definedVersusSet` is the alert gap. `noReadSurface` is the probe, path by path.
