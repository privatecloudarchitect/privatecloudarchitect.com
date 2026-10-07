# The VCF Automation API, as recorded

Companion to the chapter
([privatecloudarchitect.com/handbook/vcfa-api](https://privatecloudarchitect.com/handbook/vcfa-api)): the two token
flows performed read-only on a real estate and recorded as they went over the wire, with every value that belongs
to that estate replaced by a placeholder. The chapter's plates are rendered from the record in this folder, and the
page re-renders them with the host, organization, and user you type, so what you read is the exchange as it would
look on your estate, not a sample someone typed from memory.

| File | What it is |
|---|---|
| `capture.py` | Performs the chapter's calls against your own VCF Automation and writes the record: flow A (the stored refresh token traded for a bearer, then one read on each API surface), flow B (the Basic session login whose bearer arrives in a response header), the count of effective rights under each bearer, and the rights present under one and absent under the other, by name. Read-only; stdlib Python; no token value is printed or written, and the script refuses to write a record in which any secret, host, or organization survived. |
| `calls.json` | The record from the reference estate, 2026-09-21: eight exchanges with their request lines, headers, bodies, status codes, elapsed times, and each bearer's own expiry claim. |
| `runway.py` | How long your refresh tokens have left, and whether the one you store still works: one refresh grant with the stored token (a 400 is read for its error body and never retried), then the token list read to its declared total, each token's expiry against `WARN_DAYS` (14) and `ALERT_DAYS` (7). Read-only; stdlib Python; no token value is printed. Exit 0 ok, 1 within the warning window, 2 within the alert window or the grant refused, 3 nothing could be read. |
| `expected-output.md` | The transcripts: `capture.py` on 2026-09-21 and `runway.py` on 2026-10-07. |

## Run it

```bash
export VCFA_HOST=<automation-fqdn> VCFA_ORG=<org>
export VCFA_REFRESH_TOKEN_FILE=/path/to/refresh-token      # mode 0600; the api-token minted in the console for that org
export VCFA_USER=<user>@<org> VCFA_PASSWORD=<password>    # flow B; a dedicated account, never an administrator's daily one
export VCFA_DOMAIN=<your-dns-domain>                       # optional; replaced by a placeholder in the record
export VCFA_PROVIDER_REFRESH_TOKEN_FILE=/path/to/provider-refresh-token   # optional; the provider path
export TLS_VERIFY=false                                    # only on a self-signed lab CA
export OUT=calls.json

python3 capture.py
python3 runway.py                                          # the same environment; VCFA_BEARER works too
```

Run `runway.py` on a schedule and let its exit code raise the alarm, for example weekly:

```bash
python3 runway.py || notify-the-owner "refresh token: act now"
```

## Scope, stated plainly

- Recorded on one VCF Automation 9.1 organization on 2026-09-21. Your status codes and shapes should match;
  your counts, elapsed times, and the rights delta may differ with your roles.
- Read-only: nothing is created or changed. The record replaces the host, the organization, the user, the
  DNS domain, every token, and every identifier, and the script refuses to write it if any of them survived.
- The provider path runs only with a provider refresh token minted in the console; the provider federation
  login (the `tm_ui` bearer) is a browser flow the script does not reproduce.
- Both bearers' expiry claims read 3,600 seconds on the reference estate, and the OAuth answer's `expires_in`
  agreed. A refresh token came back with the OAuth bearer and was the value sent; store what comes back either way.
- `runway.py` lists the tokens the bearer's user can see, which under a service account's own bearer are its own.
  The listed expiry is what a schedule warns on; the grant is the authority on whether a stored token still
  works, because a revoked token is refused before its listed date. On 2026-10-07 the reference estate's stored
  token, past its rotation date, answered `invalid_grant`, and the check exited 2.

## Reading the record

Each entry carries `request` (method, path, headers, body), `response` (status, elapsed milliseconds, the
headers worth reading, the body), a `note`, and where a bearer was minted, `bearer_claims` with the token's own
lifetime. Placeholders: `{{host}}`, `{{org}}`, `{{user}}`, `{{domain}}`, `{{bearer · N chars}}`,
`{{refresh-token · N chars}}`, `{{id-N}}` (one per distinct identifier). The `R` entry is not a call: it is the
set difference of the two rights lists, the arrival rule stated by name.
