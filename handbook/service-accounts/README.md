# Service accounts harness

Step three of the chapter
([privatecloudarchitect.com/handbook/service-accounts](https://privatecloudarchitect.com/handbook/service-accounts)):
prove a credential before a pipeline trusts it, and keep every credential your automation holds a managed object.
Three scripts, stdlib Python only, and no token value is ever printed. The Platform identity chapter's matrix of which token opens which door is built from exactly
these reads, so a row that differs on your estate is worth a report.

| Script | What it answers | Exit |
|---|---|---|
| `claims.py` | What does the bearer my api-token exchanges for say about its holder? Issuer, audience, the principal claims (a person shows up as user@realm with an email claim; a machine identity as a client id), scopes, and the lifetime read off the token itself. Any other JWT can be decoded through `JWT_ENV`. | 0 printed · 3 the mint failed · 5 a usage error |
| `catalog_check.py` | Is every credential your automation holds recorded with an owner, a scope, a backend and a rotation date, and which is overdue or falls due inside the warning window? Reads a catalog of metadata (start from `credentials.example.json`), refuses one that holds a secret value, and calls nothing. With `--census`, it also reads the record the identity-model companion's `census.py` writes and checks every API client in it for an owner, a role, both lifetimes and a rotation date, which neither file holds alone. | 0 every entry complete · 1 a warning · 2 a failure · 3 the census record is not a read (its exit is not 0, a fleet identity call failed, or it has no API client list) · 5 a usage error: an argument it does not take, a file it cannot read, the key unset, or a record without fingerprints or made under another key |
| `doors.py` | Which token does each surface accept? One harmless read per pair: the broker's bearer against VCF Operations, NSX, and the fleet plane's services; the per-service JWTs; VCF Automation's three login paths with the count of effective rights each carries (the arrival rule in numbers); vCenter's and SDDC Manager's own flows. Rows say MATCH or DIFFERS against the chapter's matrix. | 0 every pair answered · 3 a transport error or the broker mint failed · 5 a usage error |

Every script exits on one contract shared by the identity companions: 0 nothing for a person to act on, 3 a read
that failed or a result that is not known (an error a script did not expect is one, never 1 or 2), 5 a usage error
(a Python older than 3.10 among them); 1 and 2 keep the meanings in the table. A `DIFFERS` row from `doors.py` is
counted on its summary line and leaves the exit alone, because it is the chapter's to correct, not a fault on your
estate.

`--census` reads another tool's record, so it first checks that the census read: a record whose own exit is not 0,
that holds a failed call to the fleet identity plane, or that carries no API client list (a `--orgs-only` run reads no
fleet) is refused with exit 3 and `NOT READ`, before any entry is printed. A census refused its fleet reads still
writes a record, with an API client list that is empty, and without that check it would pass as an estate with no
client.

`opslib.py` holds the broker exchange (the api-token flow the Platform identity chapter teaches); `rtmlib.py`
holds the per-service JWT exchange the fleet plane's services require. Both are the same files the
metrics-collection harness ships.

## Run it

```bash
export OPS_HOST=<your-ops-fqdn>
export OPS_BROKER_HOST=<your-broker-fqdn>          # omit if the broker shares the Ops FQDN
export OPS_API_TOKEN_FILE=<a file holding your api-token, mode 0600>   # BROKER_TENANT defaults to CUSTOMER
export OPS_TLS_VERIFY=false                        # only on a self-signed lab CA

python3 claims.py                                  # what the bearer says it is

# each of these is optional; unset ones are skipped and reported as such
export NSX_HOST=<nsx-manager-fqdn>
export RTM_HOST=<vcf-instance-services-fqdn>       # fronts /data-query-service
export FLEET_HOST=<fleet-lifecycle-fqdn>           # fronts /fleet-lcm
export LOGS_HOST=<log-management-fqdn>:9543        # the API port on the build this was proven on
export VCFA_HOST=<automation-fqdn> VCFA_ORG=<org>
export VCFA_REFRESH_TOKEN_FILE=/path/to/refresh-token   # mode 0600; rewritten only if the answer carries a different value
export VCFA_USER=<user>@<org> VCFA_PASSWORD_FILE=<a file holding the password, mode 0600>  # the Basic session login; a dedicated account
export VCFA_PROVIDER_REFRESH_TOKEN_FILE=/path/to/provider-refresh-token   # a provider api-token minted in the console
export VC_HOST=<vcenter-fqdn> VC_USER=<user>@<domain> VC_PASSWORD_FILE=<a file holding the password, mode 0600>
export SDDC_HOST=<sddc-manager-fqdn> SDDC_USER=<user>@<domain> SDDC_PASSWORD_FILE=<a file holding the password, mode 0600>

python3 doors.py

# the catalog check needs no credential and no network
cp credentials.example.json credentials.json       # then one entry per credential your automation holds
python3 catalog_check.py credentials.json

# every API client the identity-model census read, joined to the catalog
export FINGERPRINT_KEY_FILE=<a secret of your own, mode 0600>   # the same file census.py ran with
python3 catalog_check.py credentials.json --census census.json
```

The census record names every API client by a placeholder, so the join is on keyed fingerprints: `census.py` run
with `FINGERPRINT_KEY_FILE` set gives each client the fingerprint of its client id and of its name, and the check
computes the same for each catalog entry's `api_client` (or its `name`, when that is the client's). Make the key once,
for example `python3 -c "import secrets; print(secrets.token_hex(32))" > key && chmod 600 key`, keep it off any shared
disk, and use the same file for every run you will join. A client no entry names fails, as does one whose entry has no
owner or no `next_due`, one holding no role, and a token missing a lifetime; a client with no token, and a token that
expires before its entry's `next_due`, are warnings.

Every password and token is read from `NAME_FILE`, a file of mode 0600, when it is set. The value itself in `NAME`
(`OPS_API_TOKEN`, `VC_PASSWORD` and the rest) still works, but it lands in the shell's history and the process list,
so keep it for a throwaway credential.

## Scope, stated plainly

- Everything was proven on one VCF Operations 9.1.0 instance with Real-Time Metrics deployed, on 2026-09-16:
  eighteen pairs read, seventeen matching the chapter and one correcting it.
- The provider api-token path runs only when you supply a provider refresh token minted in the console; the
  provider federation login (the `tm_ui` bearer) is a browser flow the harness does not reproduce.
- The Basic session login sends a password. Use a dedicated account, and read the count it prints beside the
  OAuth bearer's: the difference is the identity-management delta the chapter calls the arrival rule.
- Read-only against the platform. The one file the script writes is the refresh-token file, and only when the
  platform answers with a different value than it was sent; on the reference estate it never did.
- A deleted or rotated api-token is refused at the broker, and not with 401: with HTTP 500 on the 9.1.0 run of
  2026-09-16, and a deleted API client token with HTTP 400 on 9.1.1 (2026-10-13 and 2026-10-15). One past its expiry
  date is not tested. Both scripts say so when it happens, and exit 3.
- `catalog_check.py` reads metadata you keep and was run on the example catalog; it never reads a backend, so it
  cannot tell whether the value in the vault still works. That is what `claims.py` and `doors.py` are for. Its
  `--census` join was run once on the reference estate's census record, with a scratch catalog naming one client: that
  client joined, and the three no entry named failed (2026-10-15).

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
