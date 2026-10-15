# What a run looks like

The reference estate, 2026-10-12 (UTC), four throwaway organizations: an All Apps and a classic organization over
OIDC, and one of each over SAML, all federated to one Entra ID tenant. Run with `--redact`, so the names are
placeholders. Exit 1: warnings, nothing broken now.

```
$ ORGS=<the four organizations> python3 watch.py --redact
{{org-1}}  (oidc, all-apps)
  WARN    key_refresh     refresh every 24 h: an emergency roll at the provider stops sign-in for up to that long; set 1 h
  OK      keys_held       all 6 published keys are held
  OK      pkce            PKCE is off
  WARN    secret_end      the secret the organization holds ends in 26.0 days: rotate with overlap
  OK      app_gate        the app is enabled and requires assignment
  OK      group_names     every imported group (1) is assigned to the app by that name
  OK      break_glass     1 enabled local user(s) holding Organization Administrator

{{org-2}}  (saml, all-apps)
  OK      saml_cert_end   the active signing certificate ends in 361.0 days
  OK      saml_cert_held  the organization's metadata holds every signing certificate on the app
  OK      app_gate        the app is enabled and requires assignment
  OK      group_names     every imported group (1) is assigned to the app by that name
  WARN    break_glass     no enabled local user holds Organization Administrator: when the provider refuses the organization, nobody can sign in to it

{{org-3}}  (oidc, classic)
  WARN    key_refresh     refresh every 24 h: an emergency roll at the provider stops sign-in for up to that long; set 1 h
  OK      keys_held       all 6 published keys are held
  OK      pkce            PKCE is off
  WARN    secret_end      the secret the organization holds ends in 23.2 days: rotate with overlap; 1 other listed secret(s) already expired
  OK      app_gate        the app is enabled and requires assignment
  OK      group_names     every imported group (1) is assigned to the app by that name
  WARN    break_glass     no enabled local user holds Organization Owner: when the provider refuses the organization, nobody can sign in to it

{{org-4}}  (saml, classic)
  OK      saml_cert_end   the active signing certificate ends in 358.2 days
  WARN    saml_cert_held  1 other signing certificate(s) on the app are not in the organization's metadata: making one active stops sign-in until metadata carrying it is loaded
  OK      app_gate        the app is enabled and requires assignment
  OK      group_names     every imported group (1) is assigned to the app by that name
  WARN    break_glass     no enabled local user holds Organization Owner: when the provider refuses the organization, nobody can sign in to it

4 organization(s); exit 1; record written with every estate value replaced
```

## What to read in it

- **`key_refresh` warns on both OIDC organizations.** They refresh Entra's keys every 24 hours, the interval they
  were built with. Every key Entra publishes is held today (`keys_held`), so sign-in works; but when Entra rolls a
  key in an emergency, sign-in stops until the next refresh, which on this setting can be a day away. The chapter's
  practice is one hour with strategy ADD. The run was taken minutes after an hourly refresh attempt that left one
  organization's last success a full day old; that is on schedule (the refresh waits until a full interval has
  passed, and the next hourly run did refresh it), so the check warns on the interval and does not fail on the age.
- **`secret_end` names the secret the organization holds,** matched by Graph's hint, not the one that ends last.
  `{{org-3}}` lists two secrets: one ends in 23 days and is the one it uses; the other expired six days before the
  run and is unused, so it is reported, not judged.
- **`saml_cert_held` warns on `{{org-4}}`.** Its Entra app carries a second signing certificate that the
  organization's metadata does not hold. Nothing fails while the first stays active; made active, the second
  stops every sign-in until metadata carrying it is loaded. The warning is the step the rollover needs first.
- **`break_glass` warns on three of the four, judged by each organization's own top role.** An All Apps
  organization's is Organization Administrator, a classic one's Organization Owner, read from the organization's
  role list. Only `{{org-1}}` keeps a local user holding it, so on the other three a refusal at Entra (a disabled
  app, a blocked service principal) leaves nobody able to sign in.
- **Nothing failed.** On your estate a `fail` is the line to act on today: a published key not held, refreshes not
  succeeding, an expired secret or certificate, a renamed group, PKCE on, or a disabled app.

## Without the tenant's read-only app

The same watch run on the provider's credential alone, with no `ENTRA_*` variable set: the reference estate,
2026-10-15 (UTC), two standing All Apps organizations federated to the lab's Entra tenant, one over OIDC and one over
SAML. Exit 3: the rollover checks were not run, which is never a pass.

```
$ ORGS=<the two organizations> python3 watch.py --redact
{{org-1}}  (oidc, all-apps)
  WARN    key_refresh     refresh every 24 h: an emergency roll at the provider stops sign-in for up to that long; set 1 h
  OK      keys_held       all 6 published keys are held
  OK      pkce            PKCE is off
  UNKNOWN secret_end      rollover checks not run: the tenant's read-only app is owed (no Graph credential given)
  UNKNOWN app_gate        rollover checks not run: the tenant's read-only app is owed (no Graph credential given)
  UNKNOWN group_names     rollover checks not run: the tenant's read-only app is owed (no Graph credential given)
  OK      break_glass     1 enabled local user(s) holding Organization Administrator

{{org-2}}  (saml, all-apps)
  UNKNOWN saml_cert_end   rollover checks not run: the tenant's read-only app is owed (no Graph credential given)
  UNKNOWN saml_cert_held  rollover checks not run: the tenant's read-only app is owed (no Graph credential given)
  UNKNOWN app_gate        rollover checks not run: the tenant's read-only app is owed (no Graph credential given)
  UNKNOWN group_names     rollover checks not run: the tenant's read-only app is owed (no Graph credential given)
  WARN    break_glass     no enabled local user holds Organization Administrator: when the provider refuses the organization, nobody can sign in to it

rollover checks not run on 2 organization(s): the tenant's read-only app is owed
  read: the organization's side (key_refresh, keys_held, pkce, break_glass)
  not read: app_gate, group_names, saml_cert_end, saml_cert_held, secret_end (whether the app requires assignment, the names of the groups assigned to the app, the signing certificate's end date, the app's active signing certificate, the client secret's end date)
  a check not run is never a pass: exit 3 until they run

2 organization(s); exit 3; record written with every estate value replaced
```

- **It reads the organization's side and says what it did not read.** `key_refresh`, `keys_held`, `pkce` and
  `break_glass` need only the provider's credential. The rollover checks, the client secret's and the SAML
  certificate's end dates, whether the organization holds the active certificate, the app's gate and the group names,
  live in the tenant's directory, so each reads `UNKNOWN` with the reason and what is owed.
- **The exit is 3, never 0.** Run again on the same two organizations with the tenant's read-only app, the watch read
  every rollover check and exited 1: the OIDC organization's held secret ended in 23.4 days, which the run above had
  no way to see. A scheduler that alerts on any non-zero exit keeps alerting until the app is held.

## Declared provider-only, and one schedule per tenant

The same two organizations, 2026-10-15 (UTC), read-only. A tenant that withholds the read-only app gets a run declared
`--provider-only`, here with a report of its rollover dates 45 days old against the default 30-day limit. Exit 1: the
two warnings the organization's side shows, and the stale report; the rollover checks are owed by the tenant and do
not hold the exit at 3.

```
$ ENTRA_TENANT_ID=<the tenant's domain> ORGS=<the two organizations> python3 watch.py --redact --provider-only --tenant-attested 2026-08-31
{{org-1}}  (oidc, all-apps)
  WARN    key_refresh     refresh every 24 h: an emergency roll at the provider stops sign-in for up to that long; set 1 h
  OK      keys_held       all 6 published keys are held
  OK      pkce            PKCE is off
  UNKNOWN secret_end      rollover checks not run: owed by the tenant: its administrator runs them and reports the dates (a declared provider-only run)
  UNKNOWN app_gate        rollover checks not run: owed by the tenant: its administrator runs them and reports the dates (a declared provider-only run)
  UNKNOWN group_names     rollover checks not run: owed by the tenant: its administrator runs them and reports the dates (a declared provider-only run)
  WARN    tenant_report   the tenant's last report of its rollover dates is 45 days old, past the 30-day limit: ask the tenant's administrator for a new one
  OK      break_glass     1 enabled local user(s) holding Organization Administrator

{{org-2}}  (saml, all-apps)
  UNKNOWN saml_cert_end   rollover checks not run: owed by the tenant: its administrator runs them and reports the dates (a declared provider-only run)
  UNKNOWN saml_cert_held  rollover checks not run: owed by the tenant: its administrator runs them and reports the dates (a declared provider-only run)
  UNKNOWN app_gate        rollover checks not run: owed by the tenant: its administrator runs them and reports the dates (a declared provider-only run)
  UNKNOWN group_names     rollover checks not run: owed by the tenant: its administrator runs them and reports the dates (a declared provider-only run)
  WARN    tenant_report   the tenant's last report of its rollover dates is 45 days old, past the 30-day limit: ask the tenant's administrator for a new one
  WARN    break_glass     no enabled local user holds Organization Administrator: when the provider refuses the organization, nobody can sign in to it

rollover checks not run on 2 organization(s): owed by the tenant: its administrator runs them and reports the dates
  read: the organization's side (key_refresh, keys_held, pkce, break_glass)
  not read: app_gate, group_names, saml_cert_end, saml_cert_held, secret_end (whether the app requires assignment, the names of the groups assigned to the app, the signing certificate's end date, the app's active signing certificate, the client secret's end date)
  a declared provider-only run: its exit is the organization's side, and the age of the tenant's last report

2 organization(s); exit 1; record written with every estate value replaced
```

Run with a tenant that no organization names (an id made up for the run), the watch names both organizations another
tenant's and leaves them to that tenant's schedule, then exits 3 because its own tenant named nothing:

```
$ ENTRA_TENANT_ID=<a tenant no organization names> ORGS=<the two organizations> python3 watch.py --redact --provider-only
{{org-1}}  (oidc, all-apps)
  TENANT  another tenant's: its own schedule reads it (tenant {{tenant-2}})

{{org-2}}  (saml, all-apps)
  TENANT  another tenant's: its own schedule reads it (tenant {{tenant-2}})

another tenant's: its own schedule reads it: 2 organization(s) federated to another tenant, left out of this run's exit

READ    no organization in the run is federated to the run's tenant (ENTRA_TENANT_ID): a wrong tenant would read every organization as another tenant's

2 organization(s); exit 3; record written with every estate value replaced
```

Run with a tenant list that leaves their tenant out, both are uncovered:

```
$ ORGS=<the two organizations> python3 watch.py --redact --provider-only --expect-tenants <a tenant no organization names>
{{org-1}}  (oidc, all-apps)
  TENANT  uncovered: no schedule reads it (tenant {{tenant-1}})

{{org-2}}  (saml, all-apps)
  TENANT  uncovered: no schedule reads it (tenant {{tenant-1}})

uncovered: no schedule reads it: 2 organization(s) federated to a tenant outside --expect-tenants; exit 3 until a schedule reads it

2 organization(s); exit 3; record written with every estate value replaced
```

- **One schedule per tenant.** On your estate, each tenant's schedule names its own tenant and passes the whole list.
  An organization on another tenant then reads `another tenant's` and leaves the exit alone; an organization on a
  tenant nobody listed reads `uncovered` and exits 3 until a schedule covers it. The lab has one Entra tenant, so an
  organization on a second real tenant was not run; the other tenant above is an id made up for the run.
- **A declared run still fails on what it reads.** `--provider-only` moves the rollover checks to the tenant, not the
  organization's side: a published key not held or refreshes not succeeding still exit 2.
- **A domain that names no tenant is refused before anything is read**, with exit 5: `Entra names no tenant for the
  domain <domain> (HTTP 400)`.
