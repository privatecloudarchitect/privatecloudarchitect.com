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
it. Importing a renamed group's new name, the repair federation-operations teaches, sends the import alone:

```
$ python3 org_federation.py --configure --org <org> --protocol oidc --group member=<the new name> --execute
  plan: read  {'protocol': 'OIDC', 'org_type': 'all-apps', 'user_key': 'oid, the key it holds', 'settings_to_change': [], 'groups_to_import': ['Organization User'], 'groups_already_held': 0}
  ...
  settings left as stored: nothing to change, and the federation stays switched off: nothing written
  group imported with its role: 201  {'role': 'Organization User', 'providerType': 'OAUTH'}
```

When a setting differs, the run is refused until `--enable` is given, and the plan then shows the switch:

```
$ python3 org_federation.py --configure --org <org> --protocol oidc --execute
  plan: read  {..., 'settings_to_change': ['maxClockSkew'], ...}
    maxClockSkew: 300 -> 60
refused: the organization's OIDC federation is switched off (enabled: off), and this run would write its settings (maxClockSkew): add --enable to write them and switch it on (enabled: off -> on). Without --enable, --configure writes no settings to a switched-off federation, so an import alone leaves it off

$ python3 org_federation.py --configure --org <org> --protocol oidc --enable
  plan: read  {..., 'settings_to_change': ['enabled', 'maxClockSkew'], ...}
    enabled: off -> on
    maxClockSkew: 300 -> 60
```

Each line under the plan is a field the write changes, as `old -> new`: the values a rollback writes back by hand.

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
from the active directory and from the bin. A `LEFT` lists what remains; run the teardown again.

## Not run as asked: exit 5, nothing sent

Every mode that talks to VCF Automation or Entra checks its arguments and its environment before the first call.
Run without them, it names what is missing and exits 5:

```
$ python3 org_federation.py --protocol oidc --org-type all-apps --execute
not run: --execute, --prove and --teardown need VCFA_HOST, ORG, ENTRA_TENANT_ID, ENTRA_CLIENT_ID and a provider credential (VCFA_PROVIDER_BEARER_FILE or VCFA_PROVIDER_REFRESH_TOKEN_FILE) (see the header); exit 5
```

The exit codes a script around it reads: 0 done, 1 a check failed or a write was refused while building, configuring,
updating or tearing down, 2 refused by what it read, with nothing sent (a name it did not create, a protocol, key or
SAML user-name claim switch judged on what the organization stores, enabled or not, a settings write to a switched-off
federation without `--enable`, a secret Entra refused, an organization it cannot find), 3 a result not known (a
credential refused before anything was read, a read refused or a list not read to its end, Entra out of reach, a record
the scrub refused, an error it did not expect), 5 not run as asked.
