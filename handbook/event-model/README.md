# event-model

The companion to the handbook chapter on the All Apps event model: what a deployment lifecycle
actually fires, how to make a workflow run on it, and how to fire on a machine and only a machine.

## What is here

| file | what it is |
|---|---|
| `events.py` | a read-only probe for **your** organization: the topic catalogue, the lifecycle events the broker recorded, every subscription checked for the ways it can be silent, and whether the dispatch plane resolves a workflow id |
| `gate.py` | a pre-delete gate, as the one Python scriptable task of an Orchestrator workflow: it acts only on `DELETE_RESOURCE`, unregisters the resource from a registry you name, refuses the delete when it cannot, counts a record already gone as done, and stops at its own deadline |
| `test_gate.py` | eleven offline cases for `gate.py`, one per way a gate can be wrong, with a fake clock so the deadline cases run instantly |
| `deploy_gate.py` | builds the workflow from `gate.py`, imports it, waits until the Automation host resolves it, binds a scoped blocking subscription and reads both back; `--runs` reads the gate's runs, `--remove` takes it all away; dry run unless `--apply` |
| `events.json` | the record captured on the reference estate, which the chapter renders |
| `expected-output.md` | what the gate's commands printed on the reference estate |

`events.py` creates no subscription, deploys nothing, and changes nothing. `deploy_gate.py` changes the estate only
with `--apply`.

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
| the project constraint is one string, not a list of project ids | a blocking subscription with `"projectId": "<id>"` read back as given and ran on none of two creates; the same subscription with `["<id>"]` ran on the next one |
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
deleted, with the residue read afterwards. The `deleteGate` block is the gate's proof on the same day: `gate.py`
imported by `deploy_gate.py`, the wait for the dispatch plane and the enumeration passes beside it, the three
project-constraint forms and which of them ran, a create the gate let through, a delete it refused and the same
delete passing, and the removal and residue reads (`expected-output.md` is its transcript). No host name,
identifier or credential is in it.

## The gate

`gate.py` is the workflow the chapter's plate 04 describes, small enough to read in one sitting. A blocking
subscription on `deployment.resource.request.pre` runs it once per resource, before the resource is removed:

| rule | where it lives in `gate.py` |
|---|---|
| act only on deletes | `plan()`: the same topic carries every create, so anything but `DELETE_RESOURCE` returns at once |
| fail closed | every path that cannot finish the de-registration raises `GateRefused`, and a raise refuses the delete with every resource left in place |
| stay idempotent | a registry that no longer holds the record answers 404 or 410, which counts as done, so a redelivered event succeeds |
| bound your own runtime | `unregister()` stops at `deadlineSeconds` and raises; the subscription's timeout of 0 makes the platform wait as long as the workflow runs |

The registry call is the one part to replace: `unregister()` sends `DELETE <registryUrl>/<resource id>`. Keep its
contract (return when the record is gone, raise `GateRefused` otherwise) and the rules hold. It does not look up
the resource's kind; scope the subscription to the template's machine resources by name (plate 03).

```bash
python3 test_gate.py                                    # the four rules, offline

export VRO_HOST=orchestrator.example.net                # the Orchestrator registered with your Automation host
python3 deploy_gate.py --registry https://cmdb.example.net/api/machines --resource-name Web01VM   # the plan
python3 deploy_gate.py --registry https://cmdb.example.net/api/machines --resource-name Web01VM --apply
python3 events.py --subscriptions                       # the new subscription reads back ok
```

`--apply` refuses a subscription with no scope, because an unscoped blocking subscription holds every delete in
the organization. Add `--project-id` to constrain it to one project as well; it is sent as a list, the shape that
dispatches. The workflow id is derived from `--name`, so running `--apply` again updates the same workflow and
subscription in place.

**Expect to wait up to ten minutes the first time.** The Automation host learns the Orchestrator's workflows by
enumerating them on a schedule, and on the reference estate the passes ran ten minutes apart. A newly imported
workflow answers 404 there until the next pass, and a subscription bound to it in that window is stored and never
runs. `--apply` waits for the 200 before it subscribes (`--wait`, default 900 seconds). A deleted workflow goes the
other way: the Automation host answers 200 for it until the next pass.

Then prove it once, as plate 05 asks: deploy something small from the template the subscription names, delete
it, and read the run.

```bash
python3 deploy_gate.py --runs          # each run, its state and duration, the gate's own lines, why it raised
python3 deploy_gate.py --remove        # the plan; add --apply to delete the subscription, workflow and category
```

`expected-output.md` is that proof on the reference estate: a create the gate let through, a delete it refused
because the registry could not be reached, and the same delete passing once the registry had no record.
