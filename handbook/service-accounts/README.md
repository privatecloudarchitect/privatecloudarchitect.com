# Service accounts harness

Step three of the chapter
([privatecloudarchitect.com/handbook/service-accounts](https://privatecloudarchitect.com/handbook/service-accounts)):
prove a credential before a pipeline trusts it. Two read-only scripts, stdlib Python only, and no token value
is ever printed. The Platform identity chapter's matrix of which token opens which door is built from exactly
these reads, so a row that differs on your estate is worth a report.

| Script | What it answers | Exit |
|---|---|---|
| `claims.py` | What does the bearer my api-token exchanges for say about its holder? Issuer, audience, the principal claims (a person shows up as user@realm with an email claim; a machine identity as a client id), scopes, and the lifetime read off the token itself. Any other JWT can be decoded through `JWT_ENV`. | 0 printed · 2 the mint failed |
| `doors.py` | Which token does each surface accept? One harmless read per pair: the broker's bearer against VCF Operations, NSX, and the fleet plane's services; the per-service JWTs; VCF Automation's three login paths with the count of effective rights each carries (the arrival rule in numbers); vCenter's and SDDC Manager's own flows. Rows say MATCH or DIFFERS against the chapter's matrix. | 0 every pair answered · 1 a transport error · 2 the broker mint failed |

`opslib.py` holds the broker exchange (the api-token flow the Platform identity chapter teaches); `rtmlib.py`
holds the per-service JWT exchange the fleet plane's services require. Both are the same files the
metrics-collection harness ships.

## Run it

```bash
export OPS_HOST=<your-ops-fqdn>
export OPS_BROKER_HOST=<your-broker-fqdn>          # omit if the broker shares the Ops FQDN
export OPS_API_TOKEN=<your-api-token>              # OPS_REALM defaults to CUSTOMER
export OPS_TLS_VERIFY=false                        # only on a self-signed lab CA

python3 claims.py                                  # what the bearer says it is

# each of these is optional; unset ones are skipped and reported as such
export NSX_HOST=<nsx-manager-fqdn>
export RTM_HOST=<vcf-instance-services-fqdn>       # fronts /data-query-service
export FLEET_HOST=<fleet-lifecycle-fqdn>           # fronts /fleet-lcm
export LOGS_HOST=<log-management-fqdn>:9543        # the API port on the build this was proven on
export VCFA_HOST=<automation-fqdn> VCFA_ORG=<org>
export VCFA_REFRESH_TOKEN_FILE=/path/to/refresh-token   # mode 0600; rewritten only if the answer carries a different value
export VCFA_USER=<user>@<org> VCFA_PASSWORD=<password>  # the Basic session login; use a dedicated account
export VCFA_PROVIDER_REFRESH_TOKEN_FILE=/path/to/provider-refresh-token   # a provider api-token minted in the console
export VC_HOST=<vcenter-fqdn> VC_USER=<user>@<domain> VC_PASSWORD=<password>
export SDDC_HOST=<sddc-manager-fqdn> SDDC_USER=<user>@<domain> SDDC_PASSWORD=<password>

python3 doors.py
```

## Scope, stated plainly

- Everything was proven on one VCF Operations 9.1.0 instance with Real-Time Metrics deployed, on 2026-09-16:
  eighteen pairs read, seventeen matching the chapter and one correcting it.
- The provider api-token path runs only when you supply a provider refresh token minted in the console; the
  provider federation login (the `tm_ui` bearer) is a browser flow the harness does not reproduce.
- The Basic session login sends a password. Use a dedicated account, and read the count it prints beside the
  OAuth bearer's: the difference is the identity-management delta the chapter calls the arrival rule.
- Read-only against the platform. The one file the script writes is the refresh-token file, and only when the
  platform answers with a different value than it was sent; on the reference estate it never did.
- An expired or revoked api-token answers HTTP 500 at the broker, not 401. Both scripts say so when it happens.

## Reading the output

- `claims.py` prints `principal: a PERSON` when the bearer names someone (a pipeline holding that token dies with
  their account) and `principal: a CLIENT` when it names a machine identity, the shape automation should hold.
- `doors.py` prints one row per pair. `accepted` is a status below 400, `refused` is 401 or 403. `MATCH` and
  `DIFFERS` compare the row with the chapter's matrix; `DIFFERS` is a finding to report, because the matrix is
  built from these reads and grows by them.
- The line `the arrival rule, in numbers` prints the effective-rights count per login path when more than one
  path ran.

## Expected output

See [`expected-output.md`](expected-output.md) for the transcript of each script.
