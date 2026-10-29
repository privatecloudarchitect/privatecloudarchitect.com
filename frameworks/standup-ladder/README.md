# Standup Dependency Ladder starter estate

The adoptable framework behind the Standup Dependency Ladder field note
([privatecloudarchitect.com/notes/standup-dependency-ladder](https://privatecloudarchitect.com/notes/standup-dependency-ladder)).
Where the note teaches the model, this directory gives you the gate: a dependency-ordered
preflight you run against your own target namespace before you deploy, so the prerequisites that
get taken for granted fail fast with a clear remediation instead of stalling silently while your
orchestrator reports success.

Proven by running the gate against live namespaces on a VCF estate, in both directions: on 2026-09-08 a
namespace that could see no OS image FAILed the image rung before submit and a prepared namespace passed;
on 2026-10-28, on VCF 9.1.1, R1 was rebuilt to read the images the namespace can actually name, and a pin
the estate still carries PASSed at cluster scope while a pin left over from a rebuilt library FAILed.
Universal by construction; it carries no environment identifiers.

## The one discipline

The control plane reporting created is not the data plane being ready. Verify each prerequisite at
the layer that owns it, and verify readiness at the workload, never at the orchestrator in between.

## The ladder, as a checklist

Read bottom to top for standup, top to bottom for teardown. Each rung is a prerequisite the rung
above assumes.

| Rung | Prerequisite | The assumption that breaks it | The check |
|---|---|---|---|
| R0 | one authenticated read succeeds | a burst of calls is free | one probe before any fan-out; a burst locks the account |
| R1 | the pinned image resolves in THIS namespace | a correct image ID is enough, forever | the image is among the namespace's own images or the Supervisor's cluster images, under the id you pin (a rebuilt library gives every image a new id) |
| R2 | the namespace construct set is complete | region and network are enough | the spec includes storage, zones, and the load-balancer group; generated name |
| R3 | the quota covers the real footprint | the default quota fits | quota covers the un-right-sized boot disk times the replica count |
| R4 | the load balancer is serving VIPs | submitting builds the cluster | the region's LB provider is placing VIPs and node machines appear |
| R5 | the guest control plane and nodes come up | the CR being created means the cluster exists | node machines appear within minutes of submit |
| R6 | the in-guest app reaches its dependencies | the parent DNS bridges | cross-boundary targets are discovered at runtime |
| top | the workload is ready | the orchestrator says created | the front door serves and nodes report Ready |

Two rules cut across every rung: give every retryable, deterministically named object a unique name so a
still-deleting prior run cannot collide, and remember that teardown mirrors standup and inherits its
finalizers, so a delete the control plane reports as done can hang on a data-protection service the standup never surfaced.

## Running the gate

`preflight.py` is stdlib-only and parameterized entirely by environment, so it runs on your estate
with no repo dependency. It performs the live, namespace-scoped reads (R0, R1, R3) and reports each
rung PASS, WARN, FAIL, SKIP or UNKNOWN with the remediation, exiting non-zero if a rung blocks.

```
export PREFLIGHT_VC_HOST=your-supervisor-vcenter.example.com
export PREFLIGHT_NAMESPACE=your-target-namespace
export PREFLIGHT_SESSION_ID=$(curl -sk -u 'you@example.com' -X POST "https://$PREFLIGHT_VC_HOST/api/session")
# R1 lists the images through the namespace's own endpoint (status.namespaceEndpointURL of the namespace):
export PREFLIGHT_NS_ENDPOINT=https://your-automation-host/cci/kubernetes/...   # the namespace endpoint URL
( umask 077; cat > ~/.vcf/vcfa-bearer )        # paste a VCF Automation bearer, then Ctrl-D
export PREFLIGHT_BEARER_FILE=~/.vcf/vcfa-bearer   # mode 0600; the gate refuses a file open to group or other
python3 preflight.py --image vmi-0000000000000 --vm-count 2   # the image the bundle pins, and its VM count
```

R1 reads cluster scope (`clustervirtualmachineimages`, where a library attached to the whole Supervisor
lands) and namespace scope (`virtualmachineimages`). It does not judge from the namespace's vCenter library
setting: that list is empty for a Supervisor-wide library and keeps the id of a deleted one. Without the
endpoint and bearer, R1 reports UNKNOWN, meaning it did not look, which is neither a pass nor a fail.

The check logic is pure and unit-testable; the live wrapper is the only part that touches your
estate, and it only reads. Wire it into your own deploy path as the step between vending the
namespace and submitting the deployment.
