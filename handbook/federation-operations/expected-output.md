# What a run looks like

The reference estate, 2026-10-16 (UTC), four throwaway organizations: an All Apps and a classic organization over
OIDC, and one of each over SAML, all federated to one Entra ID tenant and read through the tenant's read-only app. Run
with `--redact`, so the names are placeholders. Exit 1: warnings, nothing broken now. Each transcript on this page is a run of the date it gives; the
lines this version prints differently (the `read:` line of a run without the tenant's app, the closing count of
organizations judged, the line for a run that judged none, the `key_refresh` warning's bound, and an organization left
out because its federation is off) are shown as it prints them now.

```
$ ORGS=<the four organizations> python3 watch.py --redact --expect-tenants <the tenant>
{{org-1}}  (oidc, all-apps)
  WARN    key_refresh     refresh every 24 h: an emergency roll at the provider stops sign-in for up to the interval plus an hour (25 h); set 1 h
  OK      keys_held       all 5 published keys are held
  OK      pkce            PKCE is off
  WARN    secret_end      the secret the organization holds ends in 21.8 days: rotate with overlap
  OK      app_gate        the app is enabled and requires assignment
  OK      group_names     every imported group (1) is assigned to the app by that name
  OK      break_glass     1 enabled local user(s) holding Organization Administrator

{{org-2}}  (saml, all-apps)
  OK      saml_cert_end   the active signing certificate ends in 356.8 days
  OK      saml_cert_held  the organization's metadata holds every signing certificate on the app
  OK      app_gate        the app is enabled and requires assignment
  OK      group_names     every imported group (1) is assigned to the app by that name
  WARN    break_glass     no enabled local user holds Organization Administrator: when the provider refuses the organization, nobody can sign in to it

{{org-3}}  (oidc, classic)
  WARN    key_refresh     refresh every 24 h: an emergency roll at the provider stops sign-in for up to the interval plus an hour (25 h); set 1 h
  OK      keys_held       all 5 published keys are held
  OK      pkce            PKCE is off
  WARN    secret_end      the secret the organization holds ends in 19.0 days: rotate with overlap; 1 other listed secret(s) already expired
  OK      app_gate        the app is enabled and requires assignment
  OK      group_names     every imported group (1) is assigned to the app by that name
  WARN    break_glass     no enabled local user holds Organization Owner: when the provider refuses the organization, nobody can sign in to it

{{org-4}}  (saml, classic)
  OK      saml_cert_end   the active signing certificate ends in 354.1 days
  WARN    saml_cert_held  1 other signing certificate(s) on the app are not in the organization's metadata: making one active stops sign-in until metadata carrying it is loaded
  OK      app_gate        the app is enabled and requires assignment
  OK      group_names     every imported group (1) is assigned to the app by that name
  WARN    break_glass     no enabled local user holds Organization Owner: when the provider refuses the organization, nobody can sign in to it

4 organization(s), 4 judged; exit 1; record written with every estate value replaced
```

## What to read in it

- **`key_refresh` warns on both OIDC organizations.** They refresh Entra's keys every 24 hours, the interval they
  were built with. Every key Entra publishes is held today (`keys_held`: the five Entra publishes, among the six key ids
  each organization stores), so sign-in works; but when Entra rolls a key in an emergency, sign-in stops until the
  next successful refresh, at most the interval plus an hour after the last one: a day and an hour on this setting.
  The chapter's practice is one hour with strategy ADD. The last successful refreshes were 0.7 and 19.7 hours old,
  inside the interval plus an hour, so the check warns on the interval and does not fail on the age.
- **`secret_end` names the secret the organization holds,** matched by Graph's hint, not the one that ends last.
  `{{org-3}}` lists two secrets: one ends in 19 days and is the one it uses; the other has already expired and is
  unused, so it is reported, not judged. A secret the hint matches whose end date does not read is never
  dropped: it reads `UNKNOWN secret_end ... has an end date that does not read`, exit 3, unless another matched
  secret has already ended (the companion's tests hold this; no run on the reference estate showed it).
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
  WARN    key_refresh     refresh every 24 h: an emergency roll at the provider stops sign-in for up to the interval plus an hour (25 h); set 1 h
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
  read: the organization's side, key_refresh, keys_held, pkce, break_glass (OIDC); break_glass (SAML)
  not read: app_gate, group_names, saml_cert_end, saml_cert_held, secret_end (whether the app requires assignment, the names of the groups assigned to the app, the signing certificate's end date, the app's active signing certificate, the client secret's end date)
  a check not run is never a pass: exit 3 until they run

2 organization(s), 2 judged; exit 3; record written with every estate value replaced
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
  WARN    key_refresh     refresh every 24 h: an emergency roll at the provider stops sign-in for up to the interval plus an hour (25 h); set 1 h
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
  read: the organization's side, key_refresh, keys_held, pkce, break_glass (OIDC); break_glass (SAML)
  not read: app_gate, group_names, saml_cert_end, saml_cert_held, secret_end (whether the app requires assignment, the names of the groups assigned to the app, the signing certificate's end date, the app's active signing certificate, the client secret's end date)
  a declared provider-only run: its exit is the organization's side, and the age of the tenant's last report

2 organization(s), 2 judged; exit 1; record written with every estate value replaced
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

READ    the run judged no organization (<n> listed; 2 another tenant's): check VCFA_HOST, the credential and ORGS; a run that judges nothing is never a pass

2 organization(s), 0 judged; exit 3; record written with every estate value replaced
```

Run with a tenant list that leaves their tenant out, both are uncovered:

```
$ ORGS=<the two organizations> python3 watch.py --redact --provider-only --expect-tenants <a tenant no organization names>
{{org-1}}  (oidc, all-apps)
  TENANT  uncovered: no schedule reads it (tenant {{tenant-1}})

{{org-2}}  (saml, all-apps)
  TENANT  uncovered: no schedule reads it (tenant {{tenant-1}})

uncovered: no schedule reads it: 2 organization(s) federated to a tenant outside --expect-tenants; exit 3 until a schedule reads it

READ    the run judged no organization (<n> listed; 2 uncovered): check VCFA_HOST, the credential and ORGS; a run that judges nothing is never a pass

2 organization(s), 0 judged; exit 3; record written with every estate value replaced
```

- **One schedule per tenant.** On your estate, each tenant's schedule names its own tenant and passes the whole list.
  An organization on another tenant then reads `another tenant's` and leaves the exit alone; an organization on a
  tenant nobody listed reads `uncovered` and exits 3 until a schedule covers it. The lab has one Entra tenant, so an
  organization on a second real tenant was not run; the other tenant above is an id made up for the run.
- **A declared run still fails on what it reads.** `--provider-only` moves the rollover checks to the tenant, not the
  organization's side: a published key not held or refreshes not succeeding still exit 2.
- **A domain that names no tenant is refused before anything is read**, with exit 5: `Entra names no tenant for the
  domain <domain> (HTTP 400)`.

## On a provider API token, the credential a schedule holds

The same two organizations, 2026-10-15 (UTC), read with the tenant's read-only app on a provider API token minted for
the run (`VCFA_PROVIDER_REFRESH_TOKEN_FILE`, with `VCFA_PROVIDER_TOKEN_NAME` naming it), then revoked. Exit 1, on the
same three warnings the same run gave on a provider bearer:

```
$ VCFA_PROVIDER_REFRESH_TOKEN_FILE=<the token, mode 0600> VCFA_PROVIDER_TOKEN_NAME=<its name> ORGS=<the two organizations> python3 watch.py --redact

the watch's own credential
  OK      own_token       the watch's own provider API token ends in 90.0 days

{{org-1}}  (oidc, all-apps)
  WARN    key_refresh     refresh every 24 h: an emergency roll at the provider stops sign-in for up to the interval plus an hour (25 h); set 1 h
  OK      keys_held       all 6 published keys are held
  OK      pkce            PKCE is off
  WARN    secret_end      the secret the organization holds ends in 23.2 days: rotate with overlap
  OK      app_gate        the app is enabled and requires assignment
  OK      group_names     every imported group (1) is assigned to the app by that name
  OK      break_glass     1 enabled local user(s) holding Organization Administrator

{{org-2}}  (saml, all-apps)
  OK      saml_cert_end   the active signing certificate ends in 358.2 days
  OK      saml_cert_held  the organization's metadata holds every signing certificate on the app
  OK      app_gate        the app is enabled and requires assignment
  OK      group_names     every imported group (1) is assigned to the app by that name
  WARN    break_glass     no enabled local user holds Organization Administrator: when the provider refuses the organization, nobody can sign in to it

2 organization(s), 2 judged; exit 1; record written with every estate value replaced
```

- **The token carried every read.** No read was refused, and each check read the same state as on the provider
  bearer in the run that followed. The token was minted the way platform-identity's chapter shows (`/oauth/provider/register`,
  then the jwt-bearer exchange) and revoked after the run; its refresh then answered 400 `invalid_grant`. The client
  registration the mint made stays: the API reference read offers no call to delete it.
- **`own_token` is the token's end date, read from the provider's token list (90 days after it was minted on the reference run).** Inside `WARN_DAYS` (30 by default) it warns,
  exit 1: mint the next token under a new name, set `VCFA_PROVIDER_TOKEN_NAME` to that name and swap the 0600 file, run
  the watch once on it, revoke the old one. Run again without `VCFA_PROVIDER_TOKEN_NAME`, the watch read the same end
  date. Set the name all the same: during a rotation the user holds two refresh tokens, and without the name the end
  date is undetermined (exit 3).

## A run that judges nothing

The shape the companion's tests hold, not a run on the reference estate: `VCFA_HOST` names an estate whose
organizations have no federation switched on, or the tenant's only organization had its federation switched off.

```
$ python3 watch.py --redact

{{off-1}}  (off, all-apps)
  OFF     neither OIDC nor SAML is on (federation switched off, or signed in through VCF single sign-on): left out and not judged; name it in ORGS to read it

{{off-2}}  (off, all-apps)
  OFF     neither OIDC nor SAML is on (federation switched off, or signed in through VCF single sign-on): left out and not judged; name it in ORGS to read it

READ    the run judged no organization (2 listed; 2 with neither OIDC nor SAML on (federation switched off, or signed in through VCF single sign-on), left out): check VCFA_HOST, the credential and ORGS; a run that judges nothing is never a pass

0 organization(s), 0 judged; exit 3; record written with every estate value replaced
```

An organization left out this way is printed as `OFF` in every run, beside the organizations that were judged, so a
federation switched off during an incident is never silent: without `--redact` it carries its name.

## A replayed run

`python3 watch.py --replay replay/watch` on the set beside the script: the reference run above, every name a
placeholder, read from recorded answers with nothing sent and every date judged as of the record's time. The first line
is written to standard error. Each check reads the state and measure `watch.json` records, and the run exits 1, as the
recorded run did. Two lines the record does not hold come from what the set adds: the watch's own provider API token
(a replayed run holds a token, not a bearer, so its end date is read), and the provider's System organization, which
signs in through VCF single sign-on and is left out.

```
$ python3 watch.py --replay replay/watch
replay: 45 recorded answers from replay/watch; nothing is sent and no credential is read

the watch's own credential
  OK      own_token       the watch's own provider API token ends in 90.0 days

org-01  (oidc, all-apps)
  WARN    key_refresh     refresh every 24 h: an emergency roll at the provider stops sign-in for up to the interval plus an hour (25 h); set 1 h
  OK      keys_held       all 5 published keys are held
  OK      pkce            PKCE is off
  WARN    secret_end      the secret the organization holds ends in 21.8 days: rotate with overlap
  OK      app_gate        the app is enabled and requires assignment
  OK      group_names     every imported group (1) is assigned to the app by that name
  OK      break_glass     1 enabled local user(s) holding Organization Administrator

org-02  (saml, all-apps)
  OK      saml_cert_end   the active signing certificate ends in 356.8 days
  OK      saml_cert_held  the organization's metadata holds every signing certificate on the app
  OK      app_gate        the app is enabled and requires assignment
  OK      group_names     every imported group (1) is assigned to the app by that name
  WARN    break_glass     no enabled local user holds Organization Administrator: when the provider refuses the organization, nobody can sign in to it

org-03  (oidc, classic)
  WARN    key_refresh     refresh every 24 h: an emergency roll at the provider stops sign-in for up to the interval plus an hour (25 h); set 1 h
  OK      keys_held       all 5 published keys are held
  OK      pkce            PKCE is off
  WARN    secret_end      the secret the organization holds ends in 19.0 days: rotate with overlap; 1 other listed secret(s) already expired
  OK      app_gate        the app is enabled and requires assignment
  OK      group_names     every imported group (1) is assigned to the app by that name
  WARN    break_glass     no enabled local user holds Organization Owner: when the provider refuses the organization, nobody can sign in to it

org-04  (saml, classic)
  OK      saml_cert_end   the active signing certificate ends in 354.1 days
  WARN    saml_cert_held  1 other signing certificate(s) on the app are not in the organization's metadata: making one active stops sign-in until metadata carrying it is loaded
  OK      app_gate        the app is enabled and requires assignment
  OK      group_names     every imported group (1) is assigned to the app by that name
  WARN    break_glass     no enabled local user holds Organization Owner: when the provider refuses the organization, nobody can sign in to it

System  (off, all-apps)
  OFF     neither OIDC nor SAML is on (federation switched off, or signed in through VCF single sign-on): left out and not judged; name it in ORGS to read it

4 organization(s), 4 judged; exit 1; record written with every estate value replaced
```

The record is `watch.replay.json`, marked `"replay": true`. A request the set holds no answer for prints
`replay: the set holds no answer for` with the request on standard error, and the read it belonged to reads as failed
(exit 3).

## The provider's inventory

`inventory.py` on the reference estate, 2026-10-16 (UTC), read-only, on a provider bearer. The file declared the lab's
one Entra tenant, the four organizations federated to it with their ids, placeholder owners, consent `consented`, and
the tenant's two schedules pointed at the records then committed in the companions: this folder's `watch.json` of
2026-10-12 and the identity-lifecycle companion's `leavers.json`. Exit 1: the watch's record is four days old. Run
again that evening against the `watch.json` a new watch run had just written, the inventory read `OK watch` and `OK
consent`, and `DRIFT leavers` on the leaver record, by then 25.5 hours old; exit 1.

```
$ INVENTORY_FILE=<the provider's file> python3 inventory.py --redact

{{tenant-1}}  (consent: consented; owners: tenant {{estate}}, provider {{estate}}; 4 organization(s) declared)
  OK      owners        the tenant's owner and the provider's owner are named
  NOTE    consent       not compared: no watch record that passed its check
  DRIFT   watch         the last record is 95.4 h old, past its 24 h interval plus 1 h of slack: the schedule missed its run (the record also fails its check: the record lacks mode, judged, run_errors)
  OK      leavers       the last record is 20.3 h old, inside its 24 h interval plus 1 h of slack; its run read, and exited 4 (its own schedule acts on that)
  OK      organization  {{org-3}}: OIDC, federated to this tenant, declared
  OK      organization  {{org-4}}: SAML, federated to this tenant, declared
  OK      organization  {{org-5}}: OIDC, federated to this tenant, declared
  OK      organization  {{org-6}}: SAML, federated to this tenant, declared

outside every row
  NOTE    organization  {{org-1}}: neither OIDC nor SAML is on, and its stored settings name no Entra tenant: not federated, and not declared
  NOTE    organization  {{org-2}}: neither OIDC nor SAML is on, and its stored settings name no Entra tenant: not federated, and not declared
  NOTE    organization  {{org-7}}: neither OIDC nor SAML is on, and its stored settings name no Entra tenant: not federated, and not declared
  NOTE    organization  {{org-8}}: the provider's own consumption organization, left out as the watch leaves it out
  NOTE    organization  {{org-9}}: signs in through VCF single sign-on: the platform's sign-in, outside this inventory
  NOTE    organization  {{org-10}}: OIDC is on toward a provider other than Entra ID: outside this inventory, which reads Entra tenants

10 organization(s) listed, 9 judged; 1 drift, 0 unread; exit 1; record written with every estate value replaced
```

- **The schedules are judged by their records.** The `watch.json` then committed, written on 2026-10-12, lacks `mode`,
  `judged` and `run_errors`, which the watch records now. It is past its interval plus its slack, so the schedule
  missed its run (drift), and it also fails the record check, so the inventory does not read the tenant's consent from
  it. The
  committed `leavers.json`, written 20 hours before, is a report whose every call read; its exit 4 (a flag) belongs to
  the leaver schedule and stays out of the inventory's exit.
- **Every organization is placed.** The four federated to the tenant match the file by id. The other six are notes: no
  row is owed for an organization with no federation on, one on VCF single sign-on, one on another provider, or the
  provider's own.
- **It sent nothing.** The run made 19 requests, every one a GET: the organization list, then each organization's OIDC
  and SAML settings.

### When the estate and the file have drifted

The shapes the companion's tests hold, not a run on the reference estate: a fake estate of two tenants, seven
organizations and three schedule records.

```
$ INVENTORY_FILE=<the provider's file> python3 inventory.py --redact

{{tenant-1}}  (consent: consented; owners: tenant {{estate}}, provider {{estate}}; 4 organization(s) declared)
  OK      owners        the tenant's owner and the provider's owner are named
  OK      consent       the watch's last run read with the tenant's app, as the file states
  OK      watch         the last record is 3.0 h old, inside its 24 h interval plus 1 h of slack; its run read, and exited 1 (its own schedule acts on that)
  DRIFT   leavers       the last record is 50.0 h old, past its 24 h interval plus 1 h of slack: the schedule missed its run
  DRIFT   row           {{org-6}}: the name is held by an organization of another id than declared: the declared organization is gone and a new one took its name; vet the new one before you declare its id
  OK      organization  {{org-1}}: OIDC, federated to this tenant, declared
  OK      organization  {{org-2}}: SAML, federated to this tenant, declared
  DRIFT   organization  {{org-3}}: switched off: neither OIDC nor SAML is on, and the file declares it on; its stored settings name the tenant {{tenant-1}}
  DRIFT   organization  {{org-6}}: OIDC, federated to this tenant, and missing from its row's organization list

{{tenant-2}}  (consent: withheld; owners: tenant (blank), provider {{estate}}; 1 organization(s) declared)
  DRIFT   owners        the tenant's owner is blank: name a role or a mailbox
  DRIFT   consent       the file states the tenant withholds the read-only app, and the watch's last run read with it: set consent to consented, or take the app's credential out of the watch's schedule
  OK      watch         the last record is 5.0 h old, inside its 24 h interval plus 1 h of slack; its run read, and exited 1 (its own schedule acts on that)
  NOTE    leavers       no leaver report: it needs the read-only app, which the tenant withholds; a leaver is closed from the tenant's dated leaver notice
  OK      organization  {{org-4}}: OIDC, federated to this tenant, declared

outside every row
  DRIFT   organization  {{org-5}}: OIDC, federated to the tenant {{tenant-3}}, which has no row in the file
  NOTE    organization  {{org-7}}: the provider's own consumption organization, left out as the watch leaves it out

7 organization(s) listed, 6 judged; 7 drift, 0 unread; exit 1; record written with every estate value replaced
```

- **Drift both ways.** `{{org-5}}` federates to a tenant the file has no row for; a row or a declared organization that
  names no organization reads `no organization names this tenant` or `no organization by the declared name`.
- **A reused name is caught by the declared id.** `{{org-6}}` holds the name the file declared under another id: the
  declared organization is gone, and the new one is not in the row. Declared by name alone, the new holder would have
  read as the old one.
- **Switched off is never missing.** `{{org-3}}` has neither protocol on and still stores the tenant; the file declares
  it on, so it is drift, and it reads `switched off`. Declared `"federation": "off"`, it reads `OK`.
- **Consent is read from the watch's record.** The second tenant is declared `withheld`, and its watch ran with the
  tenant's app. A watch run without the app and not declared reads `run it as watch.py --provider-only`.
- **A record from a run that did not read is never a pass.** Had the watch's record exited 3, or named a read error,
  the line would read `UNREAD watch ... is from a run that did not read` and the run would exit 3; had an
  organization's settings read been refused, the line would read `UNREAD organization ... its settings were not read
  (VCF Automation: HTTPError 403)`.

### A replayed run

`python3 inventory.py --replay replay/inventory` from this folder: the reference run above, every name a placeholder,
read from recorded answers with nothing sent, against the inventory the set names (`replay/inventory/files/inventory.json`,
its two schedules pointed at copies beside it of the two records the recorded run read, `files/watch.json` and
`files/leavers.json`). Each record's age is judged as of the recorded run's time, so every line and the exit are the
recorded run's. The first line is
written to standard error. The record is `inventory.replay.json`, marked `"replay": true`.

```
$ python3 inventory.py --replay replay/inventory
replay: 20 recorded answers from replay/inventory; nothing is sent and no credential is read

00000000-0000-4000-8000-0000000000e1  (consent: consented; owners: tenant the tenant's identity administrators, provider the provider's platform owners; 4 organization(s) declared)
  OK      owners        the tenant's owner and the provider's owner are named
  NOTE    consent       not compared: no watch record that passed its check
  DRIFT   watch         the last record is 95.4 h old, past its 24 h interval plus 1 h of slack: the schedule missed its run (the record also fails its check: the record lacks mode, judged, run_errors)
  OK      leavers       the last record is 20.3 h old, inside its 24 h interval plus 1 h of slack; its run read, and exited 4 (its own schedule acts on that)
  OK      organization  org-03: OIDC, federated to this tenant, declared
  OK      organization  org-04: SAML, federated to this tenant, declared
  OK      organization  org-05: OIDC, federated to this tenant, declared
  OK      organization  org-06: SAML, federated to this tenant, declared

outside every row
  NOTE    organization  org-01: neither OIDC nor SAML is on, and its stored settings name no Entra tenant: not federated, and not declared
  NOTE    organization  org-02: neither OIDC nor SAML is on, and its stored settings name no Entra tenant: not federated, and not declared
  NOTE    organization  org-07: neither OIDC nor SAML is on, and its stored settings name no Entra tenant: not federated, and not declared
  NOTE    organization  org-08: the provider's own consumption organization, left out as the watch leaves it out
  NOTE    organization  org-09: signs in through VCF single sign-on: the platform's sign-in, outside this inventory
  NOTE    organization  org-10: OIDC is on toward a provider other than Entra ID: outside this inventory, which reads Entra tenants

10 organization(s) listed, 9 judged; 1 drift, 0 unread; exit 1; record written with every estate value replaced
```

A watch record a replayed watch wrote, named as a schedule's record, reads `UNREAD watch ... is from a run that did not
read: it is a replayed record, answered from a recorded set, not a run of the schedule`, whether or not the inventory
itself runs under `--replay`.
