# Metadata projection

Does the metadata a workload declares reach the plane its consumers read, and does it stay there?

On a VCF 9.1 All Apps organization a cloud template has no tag field. It declares Kubernetes
labels, and every consumer that governs on metadata reads tags: VCF Operations resolves custom
group membership, policy scope and view filters from `summary|tag` and `summary|tagJson`, and
carries no Kubernetes label on a machine object at all. So the label is the declaration, the tag is
a projection of it, and something has to perform that projection repeatedly.

`content.py` measures whether yours does. It is read-only and writes nothing to any plane.

## What it answers

| question | plane | what it reports |
|---|---|---|
| what can a template even declare | Automation | templates carrying a resource-tag, a label, a class-name and a flavor construct, counted separately |
| what does each machine declare | Automation | the labels on each provisioned machine's manifest, and the instance UUID to find it by |
| what does the machine carry | vCenter | the tags on those same machines, joined on that UUID |
| can the consumer see any of it | Operations | how many properties on a machine object carry a tag, and how many carry a Kubernetes label |
| is the metadata still alive | Operations | objects still collecting against objects retained after deletion, each split by whether it carries metadata |
| do your own examples comply | this repository | example manifests declaring every concept the engine reads |

## Run it

Each plane is credentialed separately, and the script records which ones it reached. Give it
whatever you have; a missing plane produces `not credentialed` in the record rather than an error.

```bash
export VCFA_HOST=<automation-fqdn>
export VCFA_ORG=<organization>
export VCFA_USER=<username>                 # the bare account, not the UPN
export VCFA_PASSWORD_FILE=/path/to/pw       # mode 0600
export VC_HOST=<vcenter-fqdn>
export VC_USER=<username@domain>
export VC_PASSWORD_FILE=/path/to/pw
export OPS_HOST=<operations-fqdn>
export OPS_TOKEN_FILE=/path/to/bearer
export TLS_VERIFY=false                     # only on a self-signed lab CA
python3 content.py
```

It writes `content.json` beside itself. Every estate value is replaced with a stable placeholder
before the file is written, longest name first, and the script refuses to write a record in which
one survived.

## Reading the record

- **`reached`** which planes answered. Read this first: every count below is scoped to the planes
  that responded, and a missing plane is not a zero.
- **`grammar`** templates by the construct they carry. `declaringTags` at zero with
  `declaringLabels` high is the All Apps shape, and it is a statement about the manifest rather than
  about adoption.
- **`workloads`** `declaredByAutomation` is how many machines a deployment describes;
  `joinedToAMachine` is how many were found in vCenter by UUID. A gap between them is machines the
  deployment still describes that no longer exist.
- **`workloads.declaringButUnprojected`** the number that matters most: machines that declare
  metadata and carry none. That is the projection's backlog.
- **`operations.collectingWithMetadata` against `retainedWithMetadata`** the decay reading. Higher
  density among retained objects means metadata was applied once and the machines were replaced
  since. Retained objects keep their last properties, so counting them as covered flatters an estate
  that is losing ground.
- **`operations.propertiesCarryingAKubernetesLabel`** an empty list means there is no property for a
  group rule to filter a label on, which is what makes the projection necessary rather than
  traditional.
- **`corpus`** your own published examples, checked at rest. A template nobody has deployed appears
  in no estate reading, and it is the one somebody copies.

## What it does not cover

- **It does not read NSX.** NSX dynamic security groups read NSX tags, which are a third plane.
  Whether a projection should fan out to NSX as well is an open question here, not an answered one.
- **It does not read the Supervisor directly.** Declarations come from the deployment record, which
  is reachable with the same tenant credential as everything else; the per-namespace proxy needs a
  namespace-scoped credential on a one-hour clock. A machine created in a namespace by hand, outside
  any deployment, is therefore not counted.
- **It does not judge whether a declared value is correct**, only whether it arrived. A machine
  labelled with the wrong application is projected faithfully.
- **It writes nothing.** Converging the estate is a separate tool, and it is deliberately not in
  this folder: a script that reports and a script that changes things should not be the same script.

## Three ways this answers wrongly

Each of these was a defect in this script before it was a warning here.

1. **Joining declaration to machine by name.** Two live machines can share one name in different
   namespaces. The join then reads one machine's tags and attributes them to the other. The instance
   UUID is on both sides, so there is no reason to accept an ambiguous key.
2. **Counting a retained object as coverage.** On the estate this was written from, every tagged
   object in one reading was a deleted machine.
3. **Reading `${input.environment}` as a literal.** It is a placeholder resolved at deploy time. The
   thing to check is the input's declared enum, because that is the complete set of values a
   deployer can choose.
