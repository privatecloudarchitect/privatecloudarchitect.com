# What a run prints, and what to read in it

The transcript of one run on the reference estate, 2026-10-12: an All Apps organization federated to Entra ID over
OIDC, users keyed on `preferred_username`. Only the record's path is changed; a run that succeeds prints no name
from your estate (a refusal quotes VCF Automation's or Entra's message, which can).

## Build

```
$ python3 org_federation.py --protocol oidc --org-type all-apps --user-key preferred_username --execute
  organization created: 202  {'classic': False}
  organization roles read: done  {'count': 5, 'expected_present': True}
  entitlement group created: 201
  Entra app registered: 201
  service principal created, assignment required: 201
  admin consent for openid profile email: 201
  client secret added, and accepted by Entra: done  {'days': 180, 'live_after_s': 11}
  entitlement group is the app's only assignment: done  {'others_removed': 0}
  entitled test user added as a direct member of the group: 204
  Entra discovery and signing keys read: done  {'keys': 6}
  OIDC settings written and read back: 200  {'stored': {'enabled': True, 'usePKCE': False, 'autoRefreshKey': True, 'keyRefreshStrategy': 'ADD', 'keyRefreshFrequencyInHours': 1, 'keyExpireDurationInHours': 24, 'enableIdTokenClaims': True, 'subjectAttributeName': 'preferred_username', 'signing_keys': 6}}
  group imported with its role: 201  {'role': 'Organization User', 'providerType': 'OAUTH'}

recorded 12 steps to federation.json; every estate value replaced by a placeholder
```

- `organization roles read` with `expected_present: True` is the check that this build names its roles the way the
  script expects. An All Apps organization holds five roles and imports the group as Organization User; a classic
  one holds eleven and imports it as Organization Member.
- `live_after_s` is how long Entra refused the new client secret before accepting it: 11 seconds on this run, none
  on another the same day. The script waits it out, so VCF Automation never receives a secret Entra still refuses.
- The `stored` block is what VCF Automation kept, read back after the write, not what was sent: PKCE off, keys
  refreshed every hour and added, and the claim users are keyed on.

## Check

```
$ python3 org_federation.py --protocol oidc --org-type all-apps --user-key preferred_username --prove
  check: organization exists and is enabled: pass
  check: assignment required on the app: pass
  check: the entitlement group is the only assignment: pass
  check: the entitled user is in the group: pass
  check: the unentitled user is not in the group: pass
  check: OIDC enabled: pass
  check: PKCE off: pass
  check: keys refresh every hour, added: pass
  check: users keyed on preferred_username: pass
  check: signing keys held: pass
  check: group imported with the member-level role: pass

Now prove it in a browser, at https://<automation-host>/tenant/<org>:
  - An entitled test user signs in through a browser and holds its group's role
  - A test user in no assigned group is refused at Entra with AADSTS50105
  - After any settings change, several sign-ins spread over minutes

recorded 11 steps to federation.json; every estate value replaced by a placeholder
```

A membership or assignment read can lag the write that made it by seconds, so each of those checks is read again for
up to 90 seconds before it counts as a FAIL. On this run the browser proof that followed admitted the entitled user
to the portal holding Organization User, twice, more than three minutes apart, and refused the other user at Entra with
`AADSTS50105`.

## A real SAML organization, proven read-only

`--prove --org` on a standing All Apps SAML organization of the reference estate, 2026-10-15 (UTC), built earlier by
another driver. It sends no write. Exit 1: two checks failed.

```
$ python3 org_federation.py --prove --org <org>
  read: done  {'protocol': 'saml', 'org_type': 'all-apps', 'user_key': None, 'imported_groups': 1, 'roles': 5, 'failed_fields': [], 'differing_fields': ['customUiButtonLabel'], 'saml_emails': {'saml_users': 2, 'enabled': 1, 'not_an_address': 1, 'disabled_not_judged': 1}}
  check: organization enabled: pass
  check: federated to ENTRA_TENANT_ID over OIDC or SAML: pass
  check: the metadata it holds names a signing certificate: pass
  check: every enabled SAML user's stored email is an address, not its NameID: FAIL
  check: every setting the sign-in depends on reads as planned: pass
  check: at least one group imported over SAML: pass
  check: imported group {{group}} holds roles of the organization's own list: pass
  check: an enabled local user holds Organization Administrator: FAIL

A round trip of a SAML user's record is a write, so --prove sends none. Where it was measured, a record whose stored email was the NameID was refused, and one whose stored email was the address answered 200; this run reads the stored email, and a round trip on this organization was not sent.
(then what to read on the Entra side and the browser steps, which the transcript leaves out here)
```

- **The stored email.** Of the two SAML users, the one enabled held its NameID as its email: the state a SAML app
  without an email claim leaves, and the one in which a round trip of the record was refused. The disabled one held
  an empty email, which the leaver close leaves when the platform refuses an email, and is not judged. On your
  organization, a FAIL here means the app sends no email claim (add it, and the next sign-in corrects the user); a
  pass still sends no round trip, so update one test user's record once yourself.
- **Before the first SAML sign-in** there is no enabled SAML user to read, so the check is not run and the tool exits
  3: run `--prove --org` again after the browser sign-ins.
- **The local administrator** fails on this organization as it did on the earlier read: it has none enabled holding
  Organization Administrator.

## A switched-off federation stays off, and keeps its key

`--configure --org` judges a switch on what the organization stores and the users it holds, enabled or not. On an
organization whose OIDC federation, keyed on `preferred_username`, was switched off, a run keyed on `oid` stops before
any write. The transcripts in this section are the companion's own output on the shapes its tests hold; no live run
has made them.

```
$ python3 org_federation.py --configure --org <org> --protocol oidc --user-key oid --execute
refused: the organization keys its users on preferred_username in the OIDC settings it holds, enabled or not: run --configure with --user-key preferred_username, or without --user-key, to keep it; a move to another key goes through a new organization
```

An organization with SAML switched off, its metadata or its SAML users still held, is refused a move to OIDC the same
way ("the organization holds SAML metadata and SAML users, enabled or not"). Exit 2, and nothing is sent.

A switched-off federation is also never switched back on by accident. Without `--enable`, a run writes no settings to
it, and imports no group into it: VCF Automation refused a group import into a federation switched off (403,
`GROUP_IMPORT`), where the same import was taken once the federation was switched on. A run with a group to import into
a federation that stays off is refused before anything is sent (exit 2), and names the way that works:

```
$ python3 org_federation.py --configure --org <org> --protocol oidc --groups-only --group member=<the new name> --execute
refused: the organization's OIDC federation is switched off, and VCF Automation refuses a group import into a federation switched off (it answered 403, GROUP_IMPORT), so the 1 group(s) to import were not sent. Switch it on and import in one run: --configure --org NAME --protocol oidc --enable with each --group ROLE=NAME (the plan shows enabled: off -> on), or switch it on first and run --groups-only after
```

Importing a renamed group's new name, the repair federation-operations teaches, takes `--groups-only` on a federation
switched on: it sends the imports alone and never a settings write, whatever the settings hold:

```
$ python3 org_federation.py --configure --org <org> --protocol oidc --groups-only --group member=<the new name> --execute
  the organization's app read at Entra, through the tenant's read-only app: read  {'groups_assigned': 2, 'groups_to_import': 1, 'groups_to_import_assigned': 1}
  plan: read  {'protocol': 'OIDC', 'org_type': 'all-apps', 'groups_only': True, 'settings_to_change': [], 'groups_to_import': ['Organization User'], 'groups_already_held': 0, 'entra_assignment': 'read'}
  --groups-only: no settings are written, and the federation stays switched on
  each group to import is assigned to the organization's app at Entra by that name, read through the tenant's read-only app
  group imported with its role: 201  {'role': 'Organization User', 'providerType': 'OAUTH'}
  check: group <the new name> imported over OAUTH holding Organization User: pass
```

With the tenant's read-only app set (`ENTRA_CLIENT_ID` and its credential, the watch's app), each group to import is
read against the groups assigned to the organization's app at Entra before anything is sent. A name no assigned group
carries, a typo or a group never assigned, is refused (exit 2): VCF Automation would import it all the same.

```
refused: no group assigned to the organization's app at Entra is named <the name given>: VCF Automation would import the name all the same, admitting no one, and its role would wait for whichever group is later given that name. Assign the group to the app at Entra, or correct the name. An assignment made moments ago can read late at Entra (seen live: refused, then read seconds later), so where the group was just assigned, run again before changing anything
```

Without the read-only app, the run says that the assignment was not read, in place of the line above the import:

```
  the tenant's read-only app was not given (ENTRA_CLIENT_ID with ENTRA_CLIENT_SECRET_FILE, or with ENTRA_CERT_FILE and ENTRA_KEY_FILE), so whether each group to import is assigned to the organization's app at Entra was not read: VCF Automation imports a name no assigned group carries. Confirm each with the tenant's administrator, and run the federation watch after
```

It needs no `APP_CLIENT_ID`, secret or metadata. An organization that stores no settings for the tenant over that
protocol is refused, since a group imported there would serve no federation. Without `--groups-only`, a run on a
federation switched on whose settings already read as planned also imports alone; on a federation switched off, a run
whose setting differs is refused until `--enable` is given, and the plan with `--enable` shows the switch:

```
$ python3 org_federation.py --configure --org <org> --protocol oidc --execute
  plan: read  {..., 'settings_to_change': ['maxClockSkew'], ...}
    maxClockSkew: 300 -> 60
refused: the organization's OIDC federation is switched off (enabled: off), and this run would write its settings (maxClockSkew): add --enable to write them and switch it on (enabled: off -> on). Without it, --configure writes no settings to a switched-off federation

$ python3 org_federation.py --configure --org <org> --protocol oidc --enable
  plan: read  {..., 'settings_to_change': ['enabled', 'maxClockSkew'], ...}
    enabled: off -> on
    maxClockSkew: 300 -> 60
```

Each line under the plan is a field the write changes, as `old -> new`: the values a rollback writes back by hand.

## A new app under the users an organization holds

The app's client id decides who a returning OIDC user is only when the users are keyed on a claim that moves with the
app. Entra makes `sub` pairwise to each app, so on an organization keyed on `sub` that holds OIDC users, enabled or
not, a new `APP_CLIENT_ID` is refused before anything is sent:

```
$ APP_CLIENT_ID=<the new app> python3 org_federation.py --configure --org <org> --protocol oidc --execute
refused: the organization holds OIDC users keyed on sub, enabled or not, and this run would change its clientId: Entra makes sub pairwise to each app, so every returning user would get a new account, and the old account would keep its direct roles. Set APP_CLIENT_ID to the client id the organization holds to keep its app, or move the tenant to the new app through a new organization
```

Asked for another key on such an organization, the refusal names only a flag the script takes:

```
refused: the organization keys its users on sub in the OIDC settings it holds, enabled or not: run --configure without --user-key, which keeps it; a move to another key goes through a new organization
```

Keyed on `oid` or `preferred_username`, which Entra sends the same for a person in every app of one tenant, the change
goes ahead, and the plan names what the users keep:

```
  plan: read  {'protocol': 'OIDC', 'org_type': 'all-apps', 'user_key': 'oid, the key it holds', 'settings_to_change': ['clientId', 'clientSecret'], 'groups_to_import': [], 'groups_already_held': 0}
    clientId: <the app it holds> -> <the new app>
    clientSecret: replaced by the secret in APP_SECRET_FILE (no value shown)
  the app changes (clientId): the 1 OIDC user(s) it holds keep their accounts, because oid does not change with the app within one tenant
```

These transcripts are the companion's own output on the shapes its tests hold; no live run has made them. The repo
records no organization keyed on `sub`.

## A SAML organization's user-name claim

Over SAML the organization matches a returning user on its user name, from the claim its mapping names. A console-built
organization that maps another claim and holds SAML users is refused, enabled or not:

```
$ METADATA_FILE=<the app's metadata> python3 org_federation.py --configure --org <org> --protocol saml --execute
refused: the organization matches its SAML users on the user-name claim http://schemas.xmlsoap.org/ws/2005/05/identity/claims/upn, enabled or not, and this run would write http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name: a returning user whose two values differ would be refused. --update --metadata changes the metadata alone; a move to another claim goes through a new organization
```

With no SAML user yet, the claim is written, and the plan keeps the old one on record:

```
  plan: read  {'protocol': 'SAML', 'org_type': 'all-apps', 'user_key': None, 'settings_to_change': ['samlAttributeMapping.userNameAttributeName'], ...}
    samlAttributeMapping.userNameAttributeName: http://schemas.xmlsoap.org/ws/2005/05/identity/claims/upn -> http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name
```

`--prove --org` judges such an organization's claim as held, as it judges an OIDC organization's key, so it does not
fail the organization on the claim its users are matched on.

## SAML metadata, judged by certificate

Entra names the same identity-provider entity id, the tenant's issuer, in the metadata of every app in one tenant, so
another app's metadata reads as the tenant's; the signing certificates tell two apps apart. `--update --metadata` and
`--configure --protocol saml` compare the file with the metadata the organization holds by certificate thumbprint, and
print the certificates kept, dropped and added for you to hold against Entra's portal. Metadata that names none of the
certificates the organization holds, while it holds SAML users, is refused unless the tenant's read-only app is given:

```
$ METADATA_FILE=<the metadata> python3 org_federation.py --update --metadata --execute
  plan: read  {'protocol': 'SAML', 'metadata': {'certificates_now': 1, 'certificates_new': 1, 'new_not_held': 1, 'held_not_new': 1, 'kept': 0, 'app_read': False}, 'saml_users': 1, 'would_change': ['samlMetadata']}
    certificates dropped: <thumbprint-1>
    certificates added: <thumbprint-2>
  refused: METADATA_FILE names none of the 1 signing certificate(s) the organization holds, and the organization holds 1 SAML user(s). It reads the same whether it is the organization's own app after a roll or another app in the same tenant (every app of a tenant names the same issuer; the certificate tells them apart), and a wrong one refuses every returning user. Give the tenant's read-only app (ENTRA_CLIENT_ID with ENTRA_CLIENT_SECRET_FILE, or with ENTRA_CERT_FILE and ENTRA_KEY_FILE) and run again: the run then reads the certificate Entra signs the organization's app with, and writes metadata that names it. Nothing was sent
```

With the read-only app, the run reads the certificate Entra signs the organization's app with now. Another app's
metadata is refused:

```
  refused: METADATA_FILE does not name the certificate Entra signs the organization's app with now: it is another app's metadata (every app of a tenant names the same issuer; the certificate tells them apart), or a certificate not yet made active, given alone. Load Entra's metadata for the organization's own app, which names its active certificate, and any next one. Nothing was sent
```

and the repair after a certificate was already made active at Entra, which drops every certificate the organization
holds, is written:

```
    certificates dropped: <thumbprint-1>
    certificates added: <thumbprint-2>
  METADATA_FILE names the certificate Entra signs the organization's app with now, and only the app's own, read through the tenant's read-only app
  SAML settings written: 200  {'changed': ['samlMetadata']}
  check: the organization holds the new metadata's certificates: pass
  check: SAML still enabled: pass
```

These transcripts are the companion's own output on the shapes its tests hold; no live run has made them.

## A secret Entra refuses is not written

A new client secret (`APP_SECRET_FILE`, or `NEW_SECRET_FILE` for `--update --secret`) is proven at Entra's token
endpoint before anything is written, in the plan too. A Secret ID pasted where the Value belongs:

```
refused: the secret in APP_SECRET_FILE was not written: Entra refused it (AADSTS7000215), and it is shaped like a Secret ID, a GUID, not the secret's Value: ask the tenant's administrator for the Value, which Entra shows once, when the secret is added. Nothing was sent to VCF Automation
```

Exit 2. A secret Entra refuses with the same code for another reason is asked again for up to two minutes, since Entra
refused a secret it had just added for some seconds; Entra out of reach is exit 3, and nothing is written either way.

## Day 2: nothing to change

`--update --execute` reads the organization first. When it already holds what was asked, nothing is written:

```
$ python3 org_federation.py --update --key-refresh --execute
  plan: read  {'protocol': 'OIDC', 'key_refresh': {'now': [True, 'ADD', 1], 'to': [True, 'ADD', 1]}, ..., 'would_change': []}
  nothing to change: nothing written  {'changed': []}
  check: keys refresh every 1 h, added: pass
  check: every settings field but the key refresh, the keys and the secret read back unchanged: pass
```

Exit 0. These lines are the shape the companion's tests hold; the live day-2 runs on the reference estate predate the
change, and the keys run there sent a write that changed nothing.

On a federation switched off, `--update` is refused, and names the commands that change one, each as the parser takes
it:

```
$ python3 org_federation.py --update --key-refresh --execute
refused: the organization has no federation to ENTRA_TENANT_ID switched on: it holds OIDC settings for ENTRA_TENANT_ID, switched off. --update changes a federation that is switched on. For the OIDC one, --configure --org NAME --protocol oidc --enable writes its settings and switches it on; a group is imported only into a federation switched on
```

## A re-run of --execute keeps its key

`--execute` run again over the organization it built, with another `--user-key`, is refused before anything is sent:

```
refused: the organization this script built keys its users on preferred_username in the OIDC settings it holds, enabled or not: run the same command with --user-key preferred_username to keep it. A build keyed on oid goes through a new organization: set ORG to a name no organization uses, and remove this one with --teardown --execute
```

## A proof that could not read: exit 3

`--prove` and `--prove --org` only read, so a read the platform or Entra refuses leaves the result unknown, never a
failed check:

```
$ python3 org_federation.py --prove --org <org>
  read refused: read users: HTTP 403: Forbidden

recorded 1 steps to prove.json; every estate value replaced by a placeholder

not proven: a read was refused (read users: HTTP 403: Forbidden); nothing is known of what it did not read (exit 3)
```

## Teardown

```
$ python3 org_federation.py --protocol oidc --org-type all-apps --user-key preferred_username --teardown --execute
  organization disabled and deleted: 202
  Entra app deleted by object id: 204
  Entra group deleted by object id: 204
  Entra app purged from the recycle bin: 204  {'after_s': 0}
  Entra service principal purged from the recycle bin: 204  {'after_s': 21}
  Entra group purged from the recycle bin: 204  {'after_s': 0}
  residue check: none  {'left': []}

recorded 7 steps to federation.json; every estate value replaced by a placeholder
```

Deleting the app also soft-deletes its service principal, so three objects go to Entra's recycle bin, not two. The
bin can refuse a purge for some seconds after the delete (21 seconds for the service principal here, 21 for an app on
another run); the script asks again until it is done. `residue check: none` means every object reads back as gone,
from the active directory and from the bin. A `LEFT` lists what remains; run the teardown again. A read that answers
neither 200 nor 404 (a 403, a 5xx) says nothing of whether the object is gone: the residue check reads `NOT KNOWN`,
names the object and the status under `not_read`, and the run exits 3.

## Not run as asked: exit 5, nothing sent

Every mode that talks to VCF Automation or Entra checks its arguments and its environment before the first call.
Run without them, it names what is missing and exits 5:

```
$ python3 org_federation.py --protocol oidc --org-type all-apps --execute
not run: --execute, --prove and --teardown need VCFA_HOST, ORG, ENTRA_TENANT_ID, ENTRA_CLIENT_ID and a provider credential (VCFA_PROVIDER_BEARER_FILE or VCFA_PROVIDER_REFRESH_TOKEN_FILE) (see the header); exit 5
```

The exit codes a script around it reads: 0 done, 1 a check failed or a write was refused while building, configuring,
updating or tearing down, 2 refused by what it read, with nothing sent (a name it did not create, a protocol, key or
SAML user-name claim switch judged on what the organization stores, enabled or not, a new app or issuer under OIDC
users keyed on a claim other than `oid` or `preferred_username`, a settings write to a switched-off federation without
`--enable`, a group-only import with no federation to serve, a secret Entra refused, an organization it cannot find,
SAML metadata dropping every held certificate under SAML users with the app unread, and with the tenant's read-only app
a group no assigned group is named, metadata not naming the app's active certificate, or no app or two), 3 a result not
known (a credential refused before anything was read, a read refused or a list not read to its end, Entra out of
reach, a teardown residue it could not read, a record the scrub refused on a run that would have exited 0, an error it
did not expect), 5 not run as asked (`ENTRA_CLIENT_ID` without its credential and a tenant domain Entra names no tenant
for among them). A record the scrub refuses never hides a 1, a 2 or a 3.
