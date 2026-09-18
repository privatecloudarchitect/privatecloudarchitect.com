# The credential inventory and the certificate horizon, as counts and dates

Companion to the chapter
([privatecloudarchitect.com/handbook/certs-credentials](https://privatecloudarchitect.com/handbook/certs-credentials)):
one read-only script that reports rotation coverage, disclosure exposure and the certificate horizon of a VCF
instance from metadata alone. Stdlib Python only. **No secret can reach its output, by construction.**

| File | What it is |
|---|---|
| `custodian.py` | Reads the credential inventory and the per-domain certificate plane, and computes counts and dates. Every response passes through `strip_secrets` inside the function that performs the request, which deletes each secret-bearing key on arrival and replaces it with a boolean saying whether something was there. Writes `custodian.json`, and refuses to write a record carrying an estate name or a secret-bearing key. |
| `custodian.json` | That record from the reference estate, 2026-09-18. The chapter's plates render it. |

## Run it

```bash
export SDDC_HOST=<sddc-manager-fqdn>
export SDDC_TOKEN_FILE=/path/to/bearer    # mode 0600
export TLS_VERIFY=false                   # only on a self-signed lab CA

python3 custodian.py
```

## The one thing to know before you run anything against this endpoint

`GET /v1/credentials` is an inventory endpoint **and a bulk secret export at the same time**. On the build this
was written against, the list response carries a non-empty cleartext `password` for two account types out of
three, with no header, flag or field marking the response as sensitive, and no separate reveal call to opt into.

That makes the ordinary reflexes for handling an inventory each a disclosure:

```
do NOT  > file          do NOT  | tee          do NOT  paste into a ticket
do NOT  log the body    do NOT  capture it in a terminal recording
```

This script is written the other way round, and the placement is the whole point. Filtering at print time
protects one code path and leaves the value in the object for every later log line and future edit; deleting the
field inside the reader means no later code can leak what no longer exists in the process:

```python
SECRET_KEYS = ("password", "privateKey", "secret", "token", "passphrase", "pemEncoded", "publicKey")
```

If you extend the script, extend that list first. Writing the list is also what surfaced the disclosure: you
cannot enumerate what counts as a secret on a plane without looking, and looking showed one of those keys coming
back populated.

## Scope, stated plainly

- Read-only. Every call is a `GET`. Nothing here rotates, renews or replaces anything.
- It reports counts, booleans and dates. No credential value is printed, logged or stored at any point, and the
  record is checked to contain no secret-bearing key name at all before it is written.
- The disclosure figures are a count of entries whose secret field was non-empty. Which entries, and which
  account types, is useful; a sample would not be, and there is none.
- Rotation execution and certificate signing-request flows are **not** exercised. The handbook reads both planes
  and has rotated nothing.
- Instance and domain names in the record are placeholders, and the script refuses to write a record in which
  one survived.

## Reading the record

`credentials` carries the total with breakdowns by resource type, credential type and account type, plus
`autoRotating` and which resources those sit on. `disclosure` carries how many entries returned secret material,
cross-tabbed `disclosedByAccountType` and `disclosedByResourceType` against `withheldByAccountType`; the
`BACKUP` row is worth finding, because the custodian holds the credential for the backup target and the backup
carries the custodian's own state. `certificates` carries the per-domain read (count, nearest and furthest days
to expiry, how many fall inside a year, and the issuing chains) alongside the estate totals, the status and
auto-renew tallies, and `daysSorted`, which is the horizon itself and the thing to turn into calendar entries.
