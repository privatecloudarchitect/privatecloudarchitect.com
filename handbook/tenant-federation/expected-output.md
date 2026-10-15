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

The exit codes a script around it reads: 0 done, 1 a call or a check failed, 2 refused by what it read (a name it did
not create, a protocol or key switch, an organization it cannot find), 3 a result not known (a credential refused before
anything was read, a record the scrub refused, an error it did not expect), 5 not run as asked.
