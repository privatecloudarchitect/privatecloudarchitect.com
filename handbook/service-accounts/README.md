# Service accounts harness

Step three of the chapter
([privatecloudarchitect.com/handbook/service-accounts](https://privatecloudarchitect.com/handbook/service-accounts)):
prove a credential before a pipeline trusts it, and keep every credential your automation holds a managed object.
Three scripts, stdlib Python only, and no token value is ever printed. The Platform identity chapter's matrix of which token opens which door is built from exactly
these reads, so a row that differs on your estate is worth a report.

| File | What it answers | Exit |
|---|---|---|
| `claims.py` | What does the bearer my api-token exchanges for say about its holder? Issuer, audience, the principal (the broker's `prn_type`: `USER` a person, `SERVICE` a machine identity; without it, a person's claim such as an email or a user name names a person, unless it holds `service-account-<name>`, the name VCF Automation gives a service account's user), scopes, and the lifetime read off the token itself. Any other JWT can be decoded through `JWT_ENV`. | 0 printed, the principal a PERSON or a CLIENT · 3 the mint failed, the broker answered a bearer that is not a JWT, or the principal is not determined (no `prn_type` and no person's claim, no `prn_type` and a person's claim holding `service-account-<name>`, or a `prn_type` other than `USER` or `SERVICE`), or a request a `--replay` set holds no answer for · 5 a usage error: an argument it does not take, the credential unset or its file unreadable, a `JWT_ENV` value that is not a JWT, a `--replay` directory that cannot be read or holds no replay set, `--replay` with `JWT_ENV` set |
| `catalog_check.py` | Is every credential your automation holds recorded with an owner, a scope, a backend and a rotation date, and which is overdue or falls due inside the warning window? Reads a catalog of metadata (start from `credentials.example.json`), refuses one that holds a secret value, and calls nothing. With `--census`, it also reads the record the identity-model companion's `census.py` writes and checks every API client in it for an owner, a role, both lifetimes and a rotation date, which neither file holds alone. | The worst state, in this order: 2 a failure (with `--census`, a client holding a token `EXPIRED`, `REVOKED` or past its end date among them) · 3 the census record is not a read (a replayed run wrote it, `"replay": true`; its exit is not 0; a fleet identity call failed or answered without its list; it lists no realm, did not query every realm's API client and token lists, or does not state them read to their total; or a line the join reads is missing), or a joined client holds a token whose state or end date the record does not carry · 1 a warning · 0 every entry complete · 5 a usage error: an argument it does not take, a file it cannot read, a catalog that is not one (no object with a `credentials` list), the key unset, or a record without fingerprints or made under another key |
| `doors.py` | Which token does each surface accept? One harmless read per pair: the broker's bearer against VCF Operations, NSX, and the fleet plane's services; the per-service JWTs; VCF Automation's three login paths with the count of effective rights each carries (the arrival rule in numbers); vCenter's and SDDC Manager's own flows. Rows say MATCH or DIFFERS against the chapter's matrix. | 0 every door of every surface you configured answered · 3 a transport error, the broker mint failed, a surface you configured whose own token could not be minted (`NOT READ`), or a request a `--replay` set holds no answer for · 5 a usage error: an argument it does not take, `OPS_HOST` or the api-token unset, a credential file it cannot read, a `--replay` directory that cannot be read or holds no replay set |
| `replay/claims/`, `replay/doors/` | Recorded answer sets made from the X-126 record (VCF 9.1.1, 2026-10-15), every name a placeholder, for `--replay`: `claims.py` and `doors.py` run on them with no estate and send nothing. | none: a set is read by the scripts, never run |

Every script exits on one contract shared by the identity companions: 0 nothing for a person to act on, 3 a read
that failed or a result that is not known (an error a script did not expect is one, never 1 or 2), 5 a usage error
(a Python older than 3.10 among them); 1 and 2 keep the meanings in the table. A `DIFFERS` row from `doors.py` is
counted on its summary line and leaves the exit alone, because it is the chapter's to correct, not a fault on your
estate. A surface you configured whose own token could not be minted (a service JWT; a VCF Automation refresh-token
grant or session login that returned no bearer; a vCenter session mint with no session id; an SDDC Manager token mint
with no token) is the opposite case: the doors behind it were not read, so `doors.py` prints `NOT READ` for it and
exits 3, never 0. A refused mint that is a row of its own still prints that row. `claims.py` and `doors.py` take one
option, `--replay DIR` (below); `--help` prints the variables and the exit codes, and any other argument is a usage
error (exit 5) before anything is read.

`--census` reads another tool's record, so it first checks that the census read, each check on its own whatever the
record's exit says. It refuses, with exit 3 and `NOT READ` before any entry is printed, a record:

- that a replayed run wrote: `census.py --replay` marks its record `"replay": true`, because its answers came from a
  recorded set, not from your estate;
- whose own exit is not 0;
- that holds a call to the fleet identity plane that failed, or that answered without the list the read needs
  (`census.py` marks that call `shape`, as it does a 200 whose list key is missing);
- that carries no API client list or no realm list (a `--orgs-only` run reads no fleet), lists no realm, or did not
  query the API client and the API token lists of every realm it lists;
- whose last page of a realm's API client or API token list does not state that the list was read whole: `census.py`
  records on each page the total the answer stated and the distinct entries read (`listed`), and the two must be equal.
  A record an earlier `census.py` wrote carries no such numbers and is refused: run `census.py` again;
- whose API client lines are not the clients its reads listed;
- whose API client lines lack the roles or tokens list the check judges, or, in a fingerprinted record, the
  fingerprint the join is made on.

A census refused its fleet reads still writes a record, with an API client list that is empty, and without these
checks it would pass as an estate with no client. An empty list from a read that passes them is the estate's: the
run prints that 0 API clients were joined and which reads stand behind the empty list.

`opslib.py` holds the broker exchange (the api-token flow the Platform identity chapter teaches); `rtmlib.py`
holds the per-service JWT exchange the fleet plane's services require. Every request in either goes through the replay
block in `opslib.py`, so under `--replay` each one is answered from the set and none is sent.

## Try it without an estate

`--replay DIR` answers every request `claims.py` and `doors.py` send from a recorded set instead of the estate, so you
can see what each prints before you have an estate to read. The sets beside this README, `replay/claims/` and
`replay/doors/`, are the X-126 record (VCF 9.1.1, 2026-10-15: the broker, NSX and the three fleet-plane services) made
into answers, with a placeholder for every name. `catalog_check.py` reads files only, so it needs no set:

```bash
python3 claims.py --replay replay/claims      # what the broker's bearer says about its holder
python3 doors.py --replay replay/doors        # the broker's and the fleet plane's doors, as X-126 read them
python3 catalog_check.py credentials.example.json --today 2026-10-13   # the example catalog, on a fixed date
```

Nothing is sent and no credential or token file is read: the set answers each request by its method, path and query,
and names the placeholder hosts it was recorded on. A request the set holds no answer for is a read that failed, so
the run exits 3 and names the call, never a pass. Under `--replay` every credential reads as present, so a surface
runs when its hosts and user names are set: the doors set names the broker, NSX and the three fleet-plane services,
and `doors.py` skips VCF Automation, vCenter and SDDC Manager, as X-126 did. Neither script writes a record, and the
one file `doors.py` can rewrite, a VCF Automation refresh-token file, is never read or written under `--replay`. The
transcripts are under "A replayed run" in `expected-output.md`.

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
export FINGERPRINT_KEY_FILE=~/.vcf/fingerprint.key   # a secret of your own, mode 0600 (below); the same file census.py ran with
python3 catalog_check.py credentials.json --census census.json
```

The census record names every API client by a placeholder, so the join is on keyed fingerprints: `census.py` run
with `FINGERPRINT_KEY_FILE` set gives each client the fingerprint of its client id and of its name, and the check
computes the same for each catalog entry's `api_client` (or its `name`, when that is the client's). Make the key once,
under your home and outside this clone, created at mode 0600 rather than changed to it after it is written:
`( umask 077; mkdir -p ~/.vcf && python3 -c "import secrets; print(secrets.token_hex(32))" > ~/.vcf/fingerprint.key )`.
Keep it off any shared disk, and use the same file for every run you will join. A client no entry names fails, as does one whose entry has no
owner or no `next_due`, one holding no role, a token missing a lifetime, and a token `EXPIRED`, `REVOKED` or past its
end date; a client with no token, a token that expires before its entry's `next_due`, and an entry that two clients
join (a name two clients share, in two realms or across a re-creation: name each by its client id) are warnings. A token whose
state (anything but `ACTIVE`, `EXPIRED` or `REVOKED`) or end date the record does not carry is not judged: its client
prints `unread`, and the run exits 3 unless a failure (exit 2) comes first, so a warning never hides it.

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
- The replay sets were made from X-126's record, which keeps each door's status and each token's claim names and
  lifetime, never a value: every value in them is a placeholder, and a token in them is made unsigned at answer time.
- `catalog_check.py` reads metadata you keep and was run on the example catalog; it never reads a backend, so it
  cannot tell whether the value in the vault still works. That is what `claims.py` and `doors.py` are for. Its
  `--census` join was run once on the reference estate's census record, with a scratch catalog naming one client: that
  client joined, and the three no entry named failed (2026-10-15). That record predates the list totals the join now
  requires, so the same record is refused today until `census.py` is run again. Its refusals of a census that did not
  read, its token states and its zero-client line were run on synthetic records and on records `census.py`'s own code
  wrote from a fake fleet, a page of one entry at a time past fifty included, and are held by its tests.

## Reading the output

- `claims.py` prints `principal: a PERSON` when the bearer names someone (a pipeline holding that token dies with
  their account) and `principal: a CLIENT` when it names a machine identity, the shape automation should hold; each
  with the claims that decided it. The broker's bearer states `prn_type` (`USER` for a person's api-token and
  `SERVICE` for an API client's, read on the reference estate). A JWT whose claims decide neither prints
  `principal: not determined` and exits 3: the absence of a person's claim is not a machine.
- `doors.py` prints one row per pair. `accepted` is a status below 400, `refused` is 401 or 403. `MATCH` and
  `DIFFERS` compare the row with the chapter's matrix; `DIFFERS` is a finding to report, because the matrix is
  built from these reads and grows by them.
- The line `the arrival rule, in numbers` prints the effective-rights count per login path when more than one
  path ran.

## Expected output

See [`expected-output.md`](expected-output.md) for the transcript of each script.
