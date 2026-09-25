# event-model

The companion to the handbook chapter on the All Apps event model: what a deployment lifecycle
actually fires, how to make a workflow run on it, and how to fire on a machine and only a machine.

## What is here

| file | what it is |
|---|---|
| `events.py` | a read-only probe for **your** organization: the topic catalogue, and the lifecycle events the broker recorded |
| `events.json` | the record captured on the reference estate, which the chapter renders |

`events.py` creates no subscription, deploys nothing, and changes nothing.

## Run it

```bash
export VCFA_HOST=automation.example.net
export VCFA_TOKEN=<a tenant bearer>

python events.py --topics     # what your organization publishes, and what is blockable
python events.py --recent     # lifecycle events, grouped by the request that caused them
```

## The one thing to check first

The topic catalogue **differs by organization type**. The `compute.*` family an operator knows from
Aria Automation or a VM Apps organization does not exist in an All Apps organization, and a
subscription to a topic that does not exist **does not fail, it never fires**. `--topics` tells you
which list you are working against before you write anything.

## What the record holds

`events.json` is one create and one delete of a three-machine template, with every payload read out of
the Orchestrator run logs. It carries the topic catalogue, the per-phase event counts, the field names
a payload carries, the three fields that differ between a machine and a bootstrap secret, the kinds a
resource lookup returns, and the four subscription binding forms with what each one does. No host
name, identifier or credential is in it.
