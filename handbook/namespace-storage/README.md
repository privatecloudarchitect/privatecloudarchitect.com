# Four storage ledgers, read in one run, printed side by side

Companion to the chapter
([privatecloudarchitect.com/handbook/namespace-storage](https://privatecloudarchitect.com/handbook/namespace-storage)):
one read-only script that asks every plane which will answer "how much storage is used" and puts the answers
next to each other. Stdlib Python only; no token, password or session id is printed or written.

**Provenance:** read on VCF Automation 9.1.1.0100 on 2026-10-19 with all four credentials
([`expected-output.md`](expected-output.md)). The 9.1 run of 2026-09-21 is kept in [`records/`](records/).

| File | What it is |
|---|---|
| `ledgers.py` | Reads what the volume claims actually request, what the region storage-class quota reports (and checks what that figure is really counting, by summing the namespaces' storage limits, a class config's where a namespace sets none, and comparing), the provider plane's consumption figure, and what the datastores of one vCenter hold. Each plane past the tenant's is optional and anything it cannot reach it **names** rather than omits. Prints each plane's percentage with both halves from that plane. With `--compare` it sets each ratio beside an earlier record's. Writes `out/ledgers.json`. |
| `ledgers.json` | That record from the reference estate. The chapter's plates render it. |
| `expected-output.md` | What the script printed on the reference estate, and the comparison with the 9.1 record. |
| `records/ledgers-vcf-9.1.json` | The 9.1 run of 2026-09-21, as that run wrote it. |

## Run it

```bash
export VCFA_HOST=<automation-fqdn> VCFA_ORG=<org> VCFA_USER=<account>
( umask 077; mkdir -p ~/.vcf && cat > ~/.vcf/vcfa-password )   # paste your password, then Ctrl-D
export VCFA_PASSWORD_FILE=~/.vcf/vcfa-password             # mode 0600; or VCFA_REFRESH_TOKEN_FILE
export TLS_VERIFY=false                                    # only on a self-signed lab CA

# optional, the provider ledger: a provider bearer in a file of mode 0600
export VCFA_PROVIDER_BEARER_FILE=~/.vcf/provider-bearer
# optional, the physical ledger: the vCenter behind the Supervisor
export VCENTER_HOST=<vcenter-fqdn> VCENTER_USER=<user> VCENTER_PASSWORD_FILE=~/.vcf/vcenter-password

python3 ledgers.py                                   # writes out/ledgers.json
python3 ledgers.py --compare last-week/ledgers.json  # also compares each ratio with an earlier record
```

Reaching all four planes needs **three different credentials**. With the tenant sign-in alone you still get
the first two and the check between them, which is the pair most often confused. A secret file open to group or
other is refused before it is read; `VCENTER_SESSION_FILE`, a vmware-api-session-id, works in place of the
vCenter user and password.

Exit codes: 0 written (with `--compare`, no ratio moved by more than a tenth); 1 with `--compare`, a ratio moved
by more than a tenth; 2 a call failed, a sign-in was refused, or a figure was not a quantity; 3 refused to replace
a record read from more ledgers; 5 an unknown argument.

## They disagree, and that is not a defect

The ledgers answer different questions: what was asked for, what was granted, what the provider allocated, and
what the disks hold. It becomes a defect the moment somebody makes a capacity decision from whichever one their
tooling happened to reach, which is the whole point of printing them together; the spread on the reference
estate is in [`expected-output.md`](expected-output.md).

Two disciplines the script enforces on itself:

- **A missing plane is named, never omitted.** A comparison missing a column still looks complete, and quietly
  becomes a different comparison.
- **Do not add the provider rows up.** Two of the per-class figures report the same capacity, one pool seen
  through two classes. On 9.1 their consumption matched to the byte as well; on 9.1.1 it differs, so the
  script tests the shared capacity rather than identical rows.

## Scope, stated plainly

- Read-only. Every call that touches the estate is a `GET`, apart from the sign-ins: the session login, and
  opening and closing the vCenter session.
- All four figures are **one run's reading**: a comparison of planes, not a trend. `--compare` is how a trend is
  read, one run against the last.
- **A run that reaches fewer ledgers than the record already in its output directory refuses to write, and names
  the credentials that would have completed it.** Carrying the missing ledgers forward from an earlier run would
  be worse than refusing: they would sit under a fresh timestamp and quietly make the one-run claim false, which
  is the claim that makes the spread a fact about the planes rather than about the clock. The default output
  directory is `out/`, so a first run never meets the reference record shipped in this folder.
- Quantities are read with their suffix: binary ones (`Ki`, `Mi`, `Gi`, `Ti`) as powers of two and decimal ones
  (`k`, `M`, `G`, `T`) as powers of ten. A figure that is not a quantity ends the run before anything is written.
- The provider list is read page by page. This build refuses the `sortAsc=id` the script asks for, so it falls
  back to one unsorted page, and it stops rather than read several unsorted pages that could overlap.
- The physical ledger counts every datastore that one vCenter holds, whether or not a storage class draws on it.
- Every organization and namespace name in the record is a placeholder.

## Reading the record

`figures` is the headline comparison (`tenantClaimed`, `tenantGranted`, `providerAllocation`, `physicalUsed`)
and `spread` is the ratio between the extremes. `quotas` is the per-class region ledger, `namespaceLimitsMiB`
the sum used to work out what the granted figure counts (`namespacesAtTheirClassConfigsLimit` of them set none),
and `quotaLedgerCounts` states the answer in words. `namespacesWithClaimsUnread` lists any namespace whose claims
could not be read. `provider` is the provider plane per class, with `providerClassesSharingACapacity` and
`providerConsumptionGapWithinACapacityMiB` flagging the rows that must not be added, and `providerSorted` saying
whether the pages were read sorted. `physical` is the datastore read, `perPlane` each plane's percentage, and
`ledgersRead` counts how many of the four this run reached, which is what the refusal above compares.
