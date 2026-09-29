# Metadata projection

Does the metadata a workload declares reach the plane its consumers read, and does it stay there?

On a VCF 9.1 All Apps organization a cloud template has no tag field. It declares Kubernetes
labels, and every consumer that governs on metadata reads tags: VCF Operations resolves custom
group membership, policy scope and view filters from `summary|tag` and `summary|tagJson`, and
carries no Kubernetes label on a machine object at all. So the label is the declaration, the tag is
a projection of it, and something has to perform that projection repeatedly.

`content.py` measures whether yours does. It is read-only and writes nothing to any plane.

## Before the numbers: why there are several stores at all

The honest first impression of this subject is that the platform has sprawled. Labels do not become
tags. Tags are the wrong shape for a configuration database. A firewall group cannot read either of
them. It looks like an accident somebody should clean up.

It is not an accident, and the cleanup is not coming. **Metadata does not live anywhere.** It is
said once, in the artifact that declares the workload, and rendered into every store a consumer can
read, the way a document is not "in" its PDF. Each consumer here is a different product with its own
membership engine, and a shared lookup between them has never existed:

| consumer | the only store it reads | why it cannot read another |
|---|---|---|
| VCF Operations groups, policies, views, dashboards | vSphere tag | the only metadata properties a group rule can filter on are the two tag ones; no property carries a Kubernetes label |
| a CMDB, through the ServiceNow management pack | vCenter custom attribute | a column maps one Operations property to one CMDB column, and the type enum has no tag type. From the tag plane a column receives every tag at once as an unqueryable string |
| the distributed firewall | NSX tag | a group criterion matches `scope` and `tag` on the fabric machine, and nothing else |
| Kubernetes-native policy and Antrea | the label itself | pod-level intent has its own homes and its own precedence ladder |
| the template | label, or `tags:` on a classic organization | the organization type decides which construct exists, not the author |

So an estate that standardizes on one store has standardized on one consumer and given up the rest.
**The thing to standardize on is the taxonomy**: the concepts, their vocabulary, their cardinality,
and which axes you actually govern on. Every store is then a rendering of that one vocabulary, and
an existing tag standard becomes the binding for one plane rather than something to discard.

Two things follow that are worth saying to anyone who suspects their tagging practice was wasted:

- **Tagging is not legacy.** It is the rendering the vSphere-native half of governance reads, which
  is most of it. What is legacy is applying tags *by hand* as the authoring act, because the workload
  lifecycle erases that work silently and every tool reports success while it happens.
- **The complexity is bounded, and the bound is the point.** A new consumer adds an actuator, never a
  template edit. A new axis is one taxonomy change, one definition, one line of source configuration,
  and every template already declaring it starts projecting. New vocabulary touches the binding alone.

This record measures whether that rendering is true on your estate right now.

## What it answers

| question | plane | what it reports |
|---|---|---|
| what can a template even declare | Automation | templates carrying a resource-tag, a label, a class-name and a flavor construct, counted separately |
| what does each machine declare | Automation | the labels on each provisioned machine's manifest, and the instance UUID to find it by |
| what does the machine carry | vCenter | the tags on those same machines, joined on that UUID |
| can the consumer see any of it | Operations | how many properties on a machine object carry a tag, and how many carry a Kubernetes label |
| is the metadata still alive | Operations | objects still collecting against objects retained after deletion, each split by whether it carries metadata |
| how many machines are there really | vCenter | every machine your Supervisor namespaces hold, split by whether it can declare for itself or can only inherit from its cluster |
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
export VC_USER=<username@domain>            # tag read, plus namespace read for the population
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
- **`population`** the machines your namespaces actually hold.
  `machinesDeclaringForThemselves` sit in their namespace's own folder; `clusterNodes` sit one
  level below, in a folder named for their cluster, and were created by that cluster's controller.
  `nodesThatCanInherit` have a cluster the deployment records describe; `nodesWithNothingToInherit`
  do not, and are reported rather than guessed at. Read `declaredByAutomation` against
  `machinesDeclaringForThemselves + clusterNodes` before reading any coverage ratio: that is the
  difference between the machines something declared and the machines you are running.
- **`corpus`** your own published examples, checked at rest. A template nobody has deployed appears
  in no estate reading, and it is the one somebody copies.

## What it does not cover

- **It does not read NSX.** NSX dynamic security groups read NSX tags, which are a third plane. A
  projection does have to fan out there, because an NSX group criterion cannot read a vSphere tag;
  measuring that plane needs an NSX credential this record does not ask for.
- **It does not read the Supervisor directly.** Declarations come from the deployment record, which
  is reachable with the same tenant credential as everything else; the per-namespace proxy needs a
  namespace-scoped credential on a one-hour clock. A machine created in a namespace by hand, outside
  any deployment, is therefore not counted.
- **It sees only machines inside a Supervisor namespace.** The population is read from the
  namespace folder tree, so an ordinary vSphere VM elsewhere in the estate is outside this
  question, by design: nothing declares metadata for it on this path.
- **It does not read the cluster objects' labels.** It reports which clusters a deployment record
  describes, which is what decides whether a node has anything to inherit; whether the inherited
  values then landed is the projection question, and the loop answers it per machine.
- **It does not judge whether a declared value is correct**, only whether it arrived. A machine
  labelled with the wrong application is projected faithfully.
- **It writes nothing.** Converging the estate is a separate tool, and it is deliberately not in
  this folder: a script that reports and a script that changes things should not be the same script.

## Four ways this answers wrongly

Each of these was a defect in this script before it was a warning here.

1. **Joining declaration to machine by name.** Two live machines can share one name in different
   namespaces. The join then reads one machine's tags and attributes them to the other. The instance
   UUID is on both sides, so there is no reason to accept an ambiguous key.
2. **Counting a retained object as coverage.** On the estate this was written from, every tagged
   object in one reading was a deleted machine.
3. **Reading `${input.environment}` as a literal.** It is a placeholder resolved at deploy time. The
   thing to check is the input's declared enum, because that is the complete set of values a
   deployer can choose.
4. **Counting only the machines a deployment record names.** A cluster's nodes are the majority of
   a real estate and no deployment record describes one. A ratio taken over the named machines
   alone is a true number about a fraction of the estate, reported as though it were about the
   estate.
