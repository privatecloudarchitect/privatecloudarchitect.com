# Four storage ledgers, read on one day, printed side by side

Companion to the chapter
([privatecloudarchitect.com/handbook/namespace-storage](https://privatecloudarchitect.com/handbook/namespace-storage)):
one read-only script that asks every plane which will answer "how much storage is used" and puts the answers
next to each other. Stdlib Python only; no token or session id is printed or written.

| File | What it is |
|---|---|
| `ledgers.py` | Reads what the volume claims actually request, what the region storage-class quota reports (and checks what that figure is really counting, by summing the namespaces' storage limits and comparing), the provider plane's consumption figure, and what the datastores hold. Each plane is optional and anything it cannot reach it **names** rather than omits. Writes `ledgers.json`. |
| `ledgers.json` | That record from the reference estate, 2026-09-18. The chapter's plates render it. |

## Run it

```bash
export VCFA_HOST=<automation-fqdn> VCFA_ORG=<org>
export VCFA_REFRESH_TOKEN_FILE=/path/to/refresh-token       # mode 0600, the tenant bearer
export VCFA_PROVIDER_BEARER_FILE=/path/to/provider-bearer   # optional, the provider ledger
export VCENTER_HOST=<vcenter-fqdn>                          # optional, the physical ledger
export VCENTER_SESSION_FILE=/path/to/session-id             # optional, a vmware-api-session-id
export TLS_VERIFY=false                                     # only on a self-signed lab CA

python3 ledgers.py
```

Reaching all four planes needs **three different credentials**. With only a tenant bearer you still get the
first two and the check between them, which is the pair most often confused.

## They disagree, and that is not a defect

The ledgers answer different questions: what was asked for, what was granted, what the provider allocated, and
what the disks hold. It becomes a defect the moment somebody makes a capacity decision from whichever one their
tooling happened to reach. The spread between the smallest and largest figure on the reference estate is
**74 times**, which is the whole point of printing them together.

Two disciplines the script enforces on itself:

- **A missing plane is named, never omitted.** A comparison missing a column still looks complete, and quietly
  becomes a different comparison.
- **Do not add the provider rows up.** Two of the per-class figures are byte-identical views of the same pool;
  summing them produced a total more than twice the real one in the first version of this script.

## Scope, stated plainly

- Read-only. Every call is a `GET`.
- All four figures are **one day's reading**. They are a comparison of planes, not a trend.
- **A run that reaches fewer ledgers than the record on disk refuses to write, and names the credentials
  that would have completed it.** Reaching all four needs three different credentials, so a run with fewer
  is the normal accident rather than an exotic one. Carrying the missing ledgers forward from an earlier run
  would be worse than refusing: they would sit under a fresh timestamp and quietly make the one-day claim
  above false, which is the claim that makes the spread a fact about the planes rather than about the clock.
- Units are mebibytes throughout, carried in the field names and stated in `unitNote`.
- Every organization and namespace name in the record is a placeholder.

## Reading the record

`figures` is the headline comparison (`tenantClaimed`, `tenantGranted`, `providerAllocation`, `physicalUsed`)
and `spread` is the ratio between the extremes. `quotas` is the per-class region ledger, `namespaceLimitsMiB`
the sum used to work out what the granted figure counts, and `quotaLedgerCounts` states the answer in words.
`provider` is the provider plane per class with `providerClassesReportingIdenticalFigures` flagging the rows
that must not be added. `physical` is the datastore read, and `ledgersRead` counts how many of the four
this run reached, which is what the refusal above compares. A plane you could not reach appears as a named
absence rather than a missing key.
