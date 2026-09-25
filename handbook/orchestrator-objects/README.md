# orchestrator-objects

The read-only probe behind Part IX of the handbook, *Orchestrator content engineering*. It reads
your Automation Orchestrator's object tree and prints the three binding mechanisms that hold it
together.

It **creates nothing, imports nothing, and changes nothing.** Every call it makes is a GET.

## What it answers

| Command | Answers |
|---|---|
| `--inventory` | how many of each object kind you have, how many packages carry a name somebody chose, and how your categories are typed across the five namespaces |
| `--runtimes` | every action environment: its runtime, its dependency pins, whether the appliance can resolve it, and whether its bundle has been built |
| `--bindings <workflow-id>` | for one workflow: which attributes read a configuration element, which actions it calls, and how many items are inline script |
| `--sweep [limit]` | reads **every** workflow definition and counts how the estate is actually built. This is the number that says how much of Part IX applies to you |
| `--record` | the counts, as the JSON the chapters render. Includes the sweep unless you pass `--no-sweep` |

## Running it

```bash
export VRO_HOST=orchestrator.example.net
export VRO_TOKEN=<a bearer this appliance accepts>

python objects.py --inventory
python objects.py --runtimes
python objects.py --bindings 00000000-0000-0000-0000-000000000000
python objects.py --sweep
```

No dependencies beyond the Python standard library. TLS verification is disabled because lab
appliances commonly carry a private CA; if yours carries a public one, remove the two `CTX` lines.

`--sweep` makes one request per workflow, so on an appliance with several hundred it takes minutes
rather than seconds. `--record` includes it by default; pass `--no-sweep` for the fast answer.

## Why it exists

Orchestrator is a tree of six object kinds connected by three different binding mechanisms that use
three different keys, and nothing in the console shows you which mechanism is in play:

- an **action** points at its **runtime** by identifier, written inside the packaged file;
- a **workflow** points at a **configuration element** by identifier plus the key name inside it;
- a **workflow** points at an **action** by name path, with no identifier at all.

The first two are appliance-specific, so content that works in one place imports cleanly somewhere
else and fails at run time. The third is portable. `--bindings` prints all three for a workflow you
name, which is the fastest way to see the asymmetry on your own content.

## Reading the record

`--record` emits counts and product vocabulary only, by construction. No host name, object name,
identifier or credential from your estate appears in it, which is why it is the thing the published
chapters render.

| Key | Means |
|---|---|
| `objects` | one count per object kind |
| `packageNaming` | `humanNamed` against `generatedName`: how much of the package namespace is yours to navigate |
| `categoryTypes` | the five typed namespaces and how many categories sit in each |
| `actionCategoryAgreement` | the count of action categories read two ways. They should be equal; a difference means a category holds no actions, or an action has no category |
| `runtimes` | how many environments cannot be resolved, how many leave dependencies unpinned, and how many pin everything |
| `sweep` | `inlineOnly` against `withActionCall` is the headline: a workflow that calls no action needs no runtime and no packaging, so chapters 2 and 3 are not yours yet |

The interactive commands are different. `--bindings` deliberately prints your own attribute names,
configuration keys and action paths to your own terminal, because that is what makes the binding
legible. None of it is ever written to the record.

## What it does not cover

- It does not read workflow **run history**, permissions, or schedules.
- It does not open packaged files. Everything here is read from the running appliance, so a
  `.action` or `.workflow` on disk is out of scope; the packaging chapter shows how to open those
  with `unzip` and `iconv`.
- `--bindings` reads the configuration binding and the action binding, which are both visible in a
  workflow's definition. The runtime binding lives inside a packaged action rather than in the
  workflow, so it is not on that output.
- It tests nothing. A binding that resolves today is not a binding that points at the right object;
  that check is a read-back against the identifiers your own appliance issued.
