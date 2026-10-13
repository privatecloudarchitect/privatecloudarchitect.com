# Will each federated organization keep signing in

Companion to the chapter
([privatecloudarchitect.com/handbook/federation-operations](https://privatecloudarchitect.com/handbook/federation-operations)):
one read-only script that reads both sides of every VCF Automation organization federated to Entra ID and says
which of them has drifted out of step, now or at the provider's next roll, with an exit code a scheduler can act
on. Stdlib Python; the `cryptography` package only if Graph is reached with a certificate. No token, secret or
password is printed or written.

| File | What it is |
|---|---|
| `watch.py` | Reads each organization's OIDC or SAML settings, imported groups and local administrators from VCF Automation, the keys the provider publishes, and (optionally) the app behind the organization from Microsoft Graph, then runs nine checks: key refresh, keys held, PKCE, the client secret's end date, the SAML certificate's end date, whether the organization's metadata holds every signing certificate, imported group names against the groups assigned to the app, the app's own gate, and a local user holding the organization's top role (Organization Administrator in an All Apps organization, Organization Owner in a classic one) for the day the provider refuses. `--why` is the sign-in router: what a user saw in, where it was refused and what to read first out. Writes `watch.json`, and refuses to write a record carrying any estate value. |
| `watch.json` | That record from the reference estate, 2026-10-12, four throwaway organizations (classic and All Apps, OIDC and SAML). |
| `expected-output.md` | The transcript of that run, with what to read in it. |

## Run it

```bash
export VCFA_HOST=<automation-fqdn>
export VCFA_PROVIDER_BEARER_FILE=/path/to/provider-bearer             # mode 0600; or VCFA_PROVIDER_REFRESH_TOKEN_FILE
export TLS_VERIFY=false                                             # only on a self-signed lab CA
# optional: the Graph checks, through the tenant's read-only app (Microsoft Graph application permission Application.Read.All)
export ENTRA_TENANT_ID=<tenant-id> ENTRA_CLIENT_ID=<app-id>
export ENTRA_CERT_FILE=/path/to/cert.pem ENTRA_KEY_FILE=/path/to/key.pem   # or ENTRA_CLIENT_SECRET_FILE
export ORGS=<org>,<org>                                             # optional; default every federated organization
export WARN_DAYS=30 OUT=watch.json

python3 watch.py            # read, print, record
python3 watch.py --redact   # the same, printed with placeholders, for a transcript you will share
python3 watch.py --why "Your Single Sign-On attempt failed" --protocol oidc
```

Schedule it and read the exit code:

| Exit | Means |
|---|---|
| 0 | every check is ok (a check it could not run is reported as unknown, and does not raise the code) |
| 1 | a warning: an end date inside `WARN_DAYS`, a refresh interval over one hour, a signing certificate the organization does not yet hold, no local user holding the organization's top role |
| 2 | a failure that stops sign-in now or at the provider's next roll: a published key not held, refreshes not succeeding, an expired secret or certificate, the active certificate missing from the organization's metadata, a renamed group, PKCE on, a disabled app |
| 3 | a read failed and nothing failed |

## Scope, stated plainly

- Read-only. Every call is a GET; nothing on VCF Automation or Entra changes.
- The secret dies where it arrives. VCF Automation returns an organization's OIDC client secret in clear to the
  provider; the script deletes it inside the function that read it, keeping its first three characters only long
  enough to match the `hint` Graph returns for each of the app's secrets, so `secret_end` judges the secret the
  organization actually holds.
- Organizations signed in through VCF single sign-on, and the provider's own consumption organization, are skipped
  by default: their sign-in settings are the platform's (name one in `ORGS` to read it anyway). An
  organization federated to another OIDC provider gets the organization-side checks (key refresh, keys held,
  local administrator); the Graph checks run only where the issuer is Entra ID.
- The key-refresh signal is the age of the last *successful* refresh against the interval. On a 24-hour interval
  the attempt timestamp moves every hour and the success timestamp once a day, so a difference between them is
  not a failure. On the cycle read (one organization), the refresh ran at the first hourly run a full interval after
  the last success, and a run 0.4 s short of the interval did not refresh, so a healthy success can be up to an hour
  older than the interval; the check fails only past that and a quarter hour. `keys_held` checks the outcome directly against the provider's published keys.
- What it cannot see: whether a provider that is unreachable (rather than refusing) would be survived; the claim
  form synchronized Active Directory groups need (not tested); a user's MFA state; Entra's sign-in log, which is
  where `--why` sends you first.
- Whose read each check is. `key_refresh`, `keys_held`, `pkce` and `break_glass` read the organization and the
  provider's public keys endpoint: the provider runs them alone. `secret_end`, `saml_cert_end`, `saml_cert_held`,
  `app_gate` and `group_names` read the tenant's Entra app in Microsoft Graph, so they run through a read-only app
  the tenant registers and consents in its own directory; without one, the tenant runs them and reports them.
- The Graph application permission those checks need is `Application.Read.All`, measured on 2026-10-13 by narrowing:
  a throwaway app on the lab tenant ran this script read-only under six sets of `Application.Read.All`,
  `User.Read.All` and `GroupMember.Read.All`. With `Application.Read.All` alone every Graph check ran; in every set
  without it, none did. In one run holding `Application.Read.All` and `GroupMember.Read.All` the Graph checks were
  skipped with an HTTP error; that run was not repeated and is not explained. The app was deleted and purged.
- Measured on VCF Automation 9.1 against Entra ID, with a provider bearer, and with a Graph certificate (the
  reference run) and a Graph client secret (the permission measurement); the provider api-token path was not
  exercised.

## Reading the record

`organizations` holds one entry per organization, named `{{org-1}}` and onward, with its `protocol` and
`org_type` and a `checks` list. Each check has a `state` (`ok`, `warn`, `fail`, `unknown`), a `detail` sentence
and a `measure` with its numbers: `interval_h` and `success_age_h` for key refresh, `held`, `published` and
`missing` for keys, `days_left` and `matched` (whether the organization's own secret was identified) for the
secret, `days_left` for the SAML certificate, `stored` and `others_not_held` for metadata, `imported`, `assigned`
and `unmatched` for group names, `local_admins` and `role` (the top role judged, read from the organization's own role list) for break-glass. `read_errors` names any plane that could not be
read. `exit` is the code the run returned.
