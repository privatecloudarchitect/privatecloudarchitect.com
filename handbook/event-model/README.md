# event-model

The companion to the handbook chapter on the All Apps event model: what a deployment lifecycle
actually fires, how to make a workflow run on it, and how to fire on a machine and only a machine.

## What is here

| file | what it is |
|---|---|
| `events.py` | a read-only probe for **your** organization: the topic catalogue, the lifecycle events the broker recorded, every subscription checked for the ways it can be silent, and whether the dispatch plane resolves a workflow id |
| `events.json` | the record captured on the reference estate, which the chapter renders |

`events.py` creates no subscription, deploys nothing, and changes nothing.

## Run it

```bash
export VCFA_HOST=automation.example.net
export VCFA_TOKEN=<a tenant bearer>

python events.py --topics            # what your organization publishes, and what is blockable
python events.py --recent            # lifecycle events, grouped by the request that caused them
python events.py --subscriptions     # every subscription, each checked for the quiet failures below
python events.py --workflow <id>     # does the Automation host resolve this workflow, before you bind it
```

`--subscriptions` and `--workflow` exit 2 when they find a subscription or a workflow an event cannot reach,
and 0 otherwise, so a scheduler can run them and raise the alarm on the exit code.

## The one thing to check first

The topic catalogue **differs by organization type**. The `compute.*` family an operator knows from
Aria Automation or a VM Apps organization does not exist in an All Apps organization, and a
subscription to a topic that does not exist **does not fail, it never fires**. `--topics` tells you
which list you are working against before you write anything.

## The quiet failures `--subscriptions` checks

Each of these is stored without an error and dispatches nothing, which is why a read-back is the only way to
find them:

| what is wrong | how it was found on the reference estate |
|---|---|
| the topic is not published in this organization | a throwaway subscription on `compute.removal.pre`, absent from the All Apps catalog, answered 201 and was stored as given, then deleted |
| no runnable is bound (`type`, `runnableType` or `runnableId` empty) | a create with `runnableType` and `runnableId` but no `type` answered 201 and kept neither field |
| the subscriber names the workflow (`extensibility.vro:<id>`) rather than the identity subscribing | answered 201, stored, and dispatched nothing |
| the workflow id does not resolve through the Automation host | a workflow that answered on the Orchestrator and not through the Automation host was stored and never ran |

It also flags a subscription marked blocking on a topic that cannot hold an operation: that one runs, and it
gates nothing. `--workflow` is the last row's check on its own, to run before you bind: take the id from
`GET /vro/workflows` on the Automation host, because that host, not the Orchestrator, is what dispatches.

## What the record holds

`events.json` comes from two runs of one create and one delete of a three-machine template: a first run
with eight subscriptions on the eight deployment lifecycle topics, whose events were read from the broker's
event log (the per-phase counts and the action topics' zero come from it), and a second run with two
console-made subscriptions, whose payloads were read out of the Orchestrator run logs. Its `method` string
describes the second run only. It carries the topic catalog, the per-phase event counts, the field names
a payload carries, the three fields that differ between a machine and a bootstrap secret, the kinds a
resource lookup returns, the four subscription binding forms with what each one does, and the blocking gate's
runs. The `reread` block is a read-only pass on a later date: the topic catalog compared with the record, the
subscription audit, the workflow check on the stock payload logger and on an id that does not exist, and one
throwaway subscription on a topic the organization does not publish, created disabled, read back, audited and
deleted, with the residue read afterwards. No host name, identifier or credential is in it.

No gate workflow ships here. The workflow's contract (one `inputProperties` input, act only on
`DELETE_RESOURCE`, confirm the kind, fail closed, stay idempotent, bound your own runtime) is on the chapter
page, and the handbook's Orchestrator content engineering series builds one.
