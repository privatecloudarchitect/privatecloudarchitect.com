# Audit three alerting rules against your own estate

Companion to the chapter
([privatecloudarchitect.com/handbook/alerting-doctrine](https://privatecloudarchitect.com/handbook/alerting-doctrine)):
one read-only script that checks the chapter's doctrine on a running VCF Operations instance instead of
restating it. Stdlib Python only; no token is printed or written.

| File | What it is |
|---|---|
| `alerts.py` | Reads the complete field list of every alert definition, reviews the default policy's enablement list for the definitions you own, measures what that policy actually governs, reads every symptom condition's type and operator and value and key, counts the wait and cancel cycles yours beside the vendor's, and checks the outbound rules for the absence of filters. Writes `alerts.json`. |
| `alerts.json` | That record from the reference estate, 2026-09-19. The chapter's plates render it. |
| `opslib.py` | The broker exchange and request helper, shared with the ops-estate harness. |

## Run it

```bash
export OPS_HOST=<operations-fqdn>
export OPS_BROKER_HOST=<identity-broker-fqdn>   # omit if the broker shares the Ops FQDN
export OPS_REALM=CUSTOMER                       # the broker realm, usually this
export OPS_API_TOKEN=<api-token>                # minted in the operations console
export OPS_OWNER="PCA"                          # the owner prefix your content carries
export OPS_KIND=VirtualMachine                  # the kind to measure blast radius against
export OPS_TLS_VERIFY=false                     # only on a self-signed lab CA

python3 alerts.py
```

## What it checks, and why each check is shaped that way

**Where scope can live.** The script enumerates every field present on every alert definition. If none of
them names an object, a group or a policy, then scope cannot live on the definition and must live in policy
enablement. That is an enumeration rather than an impression, which matters because the whole doctrine rests
on it.

**The any-any review, in two halves.** Which of your definitions the default policy enables, *and* how many
objects that policy actually governs. Neither is the blast radius on its own: a short enablement list on a
policy that governs the whole estate is worse than a long one on a policy that governs nothing. The second
half needs the effective-policy query, which lives on the unsupported `/internal` surface and takes **exactly
one** acknowledgment header (missing is 403, doubled is 400). When it refuses, the script reports the reach as
not determined rather than guessing.

**Where the threshold lives.** Every symptom condition's type, operator, value and metric key. A doctrine of
dumb conditions over intelligent metrics shows up as a tiny value vocabulary against keys that are mostly
super metrics. Arithmetic hiding in conditions shows up as dozens of distinct values.

**The debounce census.** Wait and cancel cycles, yours beside the whole instance's. This is the check where an
estate usually discovers it has been describing a platform default as a decision: if your distribution is a
single value on every definition, nobody chose it.

**What routing can see.** The complete field list of a notification rule, and the filter counts of each one.
An enabled rule with no definition filter, no resource filter, no kind filter and no criticality is an any-any
on the way out, and the check for that is four lengths and an `or`.

## Two shapes that make this lie

- `rules[].alertDefinitionIdFilters` is an **object** carrying a `values` array, not an array. Iterating the
  object yields its field names.
- Ownership is the prefix **and** the separator: `"PCA - "`, not `"PCA"`, or a vendor object whose name merely
  starts with the same letters is counted as yours.

## Alert state and the export

The policy export is the only read path for alert enablement. It must be requested with
`Accept: application/zip` (any other accept type answers a 500 that means "cannot determine", never anything
about the policy), and the archive carries the policy's whole ancestor chain. Alert state has three origins,
not two states: LOCAL, INHERITED and UNSET, and UNSET is null rather than enabled. This script reads explicit
entries only; the full contract is the field guide the chapter cites.

## Scope, stated plainly

- Read-only. Every call is a `GET` except the effective-policy query, which is a `POST` that reads.
- Nothing here enables, disables or edits an alert, a policy or a rule.
- Outbound delivery to another system is not exercised, on this estate or any other.
- **Only your own object names are published.** Every other object appears as a count.

## Reading the record

`definitions` carries the totals, the universal field list and the severity and kind breakdowns.
`defaultPolicyReview` is the any-any review: explicit entries, how many are enabled, how many are yours, and
the names of any of yours that are enabled there. `blastRadius` is what that policy actually governs.
`thresholds` carries the condition-type census for the instance and for you, with your value and operator
vocabulary and how many conditions read a super metric. `debounce` carries the cycle distributions, the states
per definition, the impact badges and how many definitions have no description. `routing` carries the rule
field list, whether a policy field exists, and the filter counts per rule.
