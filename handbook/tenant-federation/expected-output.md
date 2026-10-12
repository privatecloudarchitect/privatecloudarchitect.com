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
