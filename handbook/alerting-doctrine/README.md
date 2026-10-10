# Audit your alerting, and keep one failure to one alert

Companion to the chapter
([privatecloudarchitect.com/handbook/alerting-doctrine](https://privatecloudarchitect.com/handbook/alerting-doctrine)):
three scripts that check the chapter's six practices on a running VCF Operations instance instead of restating them.
Stdlib Python only; no token is printed or written.

| File | What it is |
|---|---|
| `alerts.py` | Read-only. Reads the complete field list of every alert definition, reviews the default policy's enablement list for the definitions you own, measures what that policy governs and what it reaches through the policies that inherit from it, reads every symptom condition and its wait and cancel, counts the dials yours beside the vendor's, checks the outbound rules against every filter the API defines, and checks whether anything keeps a child's alert quiet while its parent fails. Writes `alerts.json`. |
| `storm.py` | Read-only. Reads the instance's alert history around every host failure it still holds: what the host, its NSX transport node, its cluster and the VMs raised, and whether any VM alert said a VM was down. Writes `storm.json`. |
| `parent_aware.py` | Builds a parent-aware VM alert and a host roll-up from throwaway objects, watches what the platform raises, and removes everything. A dry run unless given `--execute`. Writes `parent-aware.json`. |
| `alerts.json`, `storm.json`, `parent-aware.json` | The three records from the reference estate. The chapter's plates render them. |
| `opslib.py` | The broker exchange and request helper, shared with the ops-estate harness. |

## Run it

```bash
export OPS_HOST=<operations-fqdn>
export OPS_BROKER_HOST=<identity-broker-fqdn>   # omit if the broker shares the Ops FQDN
export OPS_REALM=CUSTOMER                       # the broker realm, usually this
export OPS_API_TOKEN=<api-token>                # minted in the operations console
export OPS_OWNER="PCA"                          # the owner prefix your content carries
export OPS_KIND=VirtualMachine                  # the kind to measure blast radius against
export OPS_CHILD_KINDS=VirtualMachine,HostSystem  # the kinds that fail with a parent, for check 6
export OPS_TLS_VERIFY=false                     # only on a self-signed lab CA

python3 alerts.py                    # the audit, read-only
python3 storm.py                     # what your instance raised when a host failed, read-only
python3 parent_aware.py              # dry run: the subjects it would use and every body it would send
python3 parent_aware.py --execute    # throwaways only, watched up to 25 minutes, then removed
```

## What `alerts.py` checks, and why each check is shaped that way

**1. Where scope can live.** The script enumerates every field present on every alert definition. If none of them
names an object, a group or a policy, then scope cannot live on the definition and must live in policy enablement.
That is an enumeration rather than an impression, which matters because the whole doctrine rests on it.

**2. The any-any review, in two halves.** Which of your definitions the default policy enables, *and* how many
objects it reaches. Neither is the blast radius on its own: a short enablement list on a policy that reaches the
whole estate is worse than a long one on a policy that reaches nothing. The reach is larger than what the default
policy governs. A policy takes every alert setting it does not make itself from its parent, so an alert switched on
in the default policy is on in every policy cloned from it that leaves the alert alone. The script therefore counts
two things: the objects the default policy governs, and the objects governed by a policy whose `parentPolicy` chain
reaches it. The first needs the effective-policy query, which lives on the unsupported `/internal` surface and takes
**exactly one** acknowledgment header (missing is 403, doubled is 400). The second exports each governing policy in
turn, one at a time, because the export carries the policy's ancestors and a single export of every policy can
outlast the read timeout. When either refuses, the script reports what it could not determine rather than guessing.
It also reports how many of your definitions have an explicit entry there: one with none is unset, and the product
decides.

**3. Where the threshold lives.** Every symptom condition's type, operator, value and metric key. A doctrine of plain
conditions over computed metrics shows up as a tiny value vocabulary against keys that are mostly super metrics.
Arithmetic hiding in conditions shows up as dozens of distinct values. A log condition compares no value and is
counted on its own.

**4. The debounce census.** Wait and cancel cycles on every alert definition and on every symptom, yours beside the
whole instance's. A definition at wait 1 and cancel 1 holds nothing; a symptom that waits holds its condition before
the alert sees it. If your distribution is a single value everywhere, nobody set those dials for any alert in
particular. One is the minimum the API accepts, not a default it applies.

**5. What routing can see.** The complete field list of a notification rule, and how many of the 13 filters the
9.1.1 API's notification-rule schema defines each rule sets: definition, object (two fields), kind (two fields),
criticality, alert type and subtype, impact, alert status, control state, action status and collector (two fields).
An enabled rule with none of them set is an any-any on the way out.

**6. One failure, one alert.** Whether any definition on the instance keeps a child's alert quiet while its parent
fails (a symptom set on the PARENT or ANCESTOR whose reference is negated with `!`), how many roll children up into
the parent instead (CHILD or DESCENDANT with COUNT or PERCENT), how many of your definitions on a child kind are
parent-aware, and how many enabled rules select every alert on a child kind with no definition or object filter. A
notification rule has no field that groups or deduplicates alerts, so each alert such a rule selects reaches its
plug-in on its own.

## What `storm.py` reads

Every alert of the two shipped host-availability definitions ("Host has lost connection to vCenter Server" and
"vSphere High Availability (HA) has detected a possible host failure") the instance still holds, grouped into events
(alerts that start within five minutes of an event's first alert). Around each event, from 15 minutes before to 90
minutes after, every alert that started, by object kind and definition; the alerts on the VMs under the event's hosts
now, and on their clusters; and whether any VM alert's name could say the VM is down. Then the VirtualMachine
definitions whose names could say that, and how often each has raised; and every alert by control state.

A window counts every alert that started in it, on any object, so it bounds what the event raised from above: an
alert in the window was not necessarily caused by the event. The alerts on the VMs under the event's hosts are the
closer reading, with one limit: a VM that moved since is counted under its host now.

## What `parent_aware.py` builds

| Object | What it is | Expected |
|---|---|---|
| `S_vm` | VirtualMachine symptom: `summary|runtime|powerState` EQ `Powered On` | true on every running VM |
| `S_host` | HostSystem symptom: `summary|hostuuid` EQ host A's uuid | true on host A only; it stands in for a failure |
| control | VM alert: `S_vm` | raised on the VM on host A and the VM on host B |
| aware | VM alert: `S_vm` AND a PARENT HostSystem set on `!S_host` | raised on the VM on host B only |
| rollup | host alert: a CHILD VirtualMachine set on `S_vm`, COUNT GT 0 | raised once on each host, not once per VM |

A throwaway custom group holds one running VM on each of two hosts, and the two hosts, under a throwaway policy that
inherits the default policy. All four must already be governed by the default policy, so for them nothing changes but
the three test alerts. INFORMATION severity throughout. The script refuses to start while an enabled notification
rule could send a test alert (one with no definition filter whose kind and object filters do not exclude the test
objects), samples each alert every minute until the pattern has held for two collection cycles or 25 minutes have
passed, deletes every object in a `finally` block and reads each one back absent. Set `OPS_HOST_A` and `OPS_HOST_B`
to choose the hosts; otherwise it takes the first two that qualify.

Two shapes the API insists on: a related set names the related kind (`adapterKindKey` and `resourceKindKey`), and a
CHILD COUNT set without them and without `populationOperator` answers 400.

## Two shapes that make an audit lie

- `rules[].alertDefinitionIdFilters` is an **object** carrying a `values` array, not an array. Iterating the
  object yields its field names.
- Ownership is the prefix **and** the separator: `"PCA - "`, not `"PCA"`, or a vendor object whose name merely
  starts with the same letters is counted as yours.

## Alert state and the export

The policy export is the only read path for alert enablement. It must be requested with
`Accept: application/zip` (any other accept type answers a 500 that means "cannot determine", never anything
about the policy), and the archive carries the policy's whole ancestor chain. Alert state has three origins,
not two states: LOCAL, INHERITED and UNSET, and UNSET is null rather than enabled. `alerts.py` reads explicit
entries and walks each policy's ancestor chain to the first one that sets an alert; the full contract is the
field guide the chapter cites.

## Scope, stated plainly

- `alerts.py` and `storm.py` are read-only. Every call is a `GET` except the effective-policy query and the alert
  query, which are `POST`s that read.
- `parent_aware.py --execute` creates a custom group, a policy, two symptoms and three alerts, all named
  `zz-throwaway parent-aware <UTC> - ...`, and deletes them. Nothing else on the instance is changed.
- Outbound delivery to another system is not exercised, on this estate or any other.
- **Only your own object names are published.** Hosts, clusters and VMs appear as counts and labels; definitions
  appear under the product's names.

## Reading the records

`alerts.json`: `definitions` carries the totals, the universal field list and the severity and kind breakdowns.
`defaultPolicyReview` is the any-any review: explicit entries, how many are enabled, how many are yours, and the
names of any of yours enabled there. `blastRadius` is what that policy reaches. `thresholds` carries the
condition-type census, your value and operator vocabulary, how many conditions read a super metric and how many
compare no value. `debounce` carries the cycle distributions for definitions and symptoms, the states per
definition, the impact badges and how many definitions have no description. `routing` carries the rule field list,
the filter fields read, whether a policy field exists, and per rule the size of each filter. `correlation` carries
check 6. `report` is the text the script printed.

`storm.json`: `events`, each with its hosts and clusters (counts), the window by kind and definition, the VM alerts
that could say down, and the alerts on the VMs under its hosts now and on its clusters; `vmVocabulary`;
`byControlState`; `report`.

`parent-aware.json`: `observations`, one per sample, naming which labelled object each alert was raised on;
`verdict`; `bodies`, as sent; `residue`, which is empty when everything was removed; and `held`.
