# The Well-Tuned Private Cloud: the starter posture records

The runnable companion to
[The Well-Tuned Private Cloud: posture over dashboards](https://privatecloudarchitect.com/handbook/wtpc),
specifically its starter catalog section. The three postures the sheet's catalog table publishes,
as machine-readable, instance-independent records.

**Provenance:** the exemplar (`prod-latency-critical-db`) is ratified and live-enforced on the
reference estate, its values being v1 operator-judgment defaults on a monthly envelope-review
cadence; `test-dev-traditional` is instantiated live beside it (values proposed); 
`prod-business-critical-vm` is proposed. Every number was transcribed from the framework's design
catalog and shipped records, never invented; each file's header states its own status.

## The record schema

Each posture is one YAML file carrying the whole realization chain the sheet teaches:

| Block | What it is |
|---|---|
| `posture / sla / tier / archetype` | the inputs that produce the posture |
| `membership` | the tag rule (AND of its conditions); the VM tier is the only tag-declarative anchor |
| `groups` | membership follows the workload: VMs match the rule, host and cluster groups derive from where those VMs run |
| `availability_floor` | the gate: verified pass or fail, never scored |
| `policy` | the enforcement copy: cloned from Default, capacity allocation set to the envelope targets, buffer per `round(100 * (1 - target/warn))` |
| `envelope` | target / warn / breach per metric, per pillar |

## Using them

1. Adopt the tag vocabulary (the example taxonomy here is `env` / `function` / `sla`) and tag one
   posture's workloads. Membership follows tagging on an interval, not instantly; wait, then check
   the group.
2. Create the groups, clone the policy from Default with the record's capacity values, and run
   **advisory only**: score against the envelope, gate nothing.
3. Tune. The proposed records are defaults; the sheet's monthly envelope review is where they
   earn ratification on your estate.

The [first-two-weeks path](https://privatecloudarchitect.com/handbook/wtpc#the-starter-catalog)
on the sheet sequences this end to end, and the sheet's enforcement ladder governs anything
beyond advisory.
