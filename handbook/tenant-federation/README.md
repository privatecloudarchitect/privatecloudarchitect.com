# A tenant organization on its own identity provider

Companion to the chapter
([privatecloudarchitect.com/handbook/tenant-federation](https://privatecloudarchitect.com/handbook/tenant-federation)):
one script that federates a VCF Automation organization straight to Microsoft Entra ID, over OIDC or SAML, on a
classic or an All Apps organization, and takes it down again. Stdlib Python; the `cryptography` package only when
Entra is reached with a certificate rather than a client secret. No secret or token is printed or written.

| File | What it is |
|---|---|
| `org_federation.py` | Plans by default: prints every body each side will be sent, the Entra checklist and the proof checklist, and changes nothing. `--execute` builds a throwaway organization, an Entra app and one entitlement group, and wires them; `--prove` reads both sides back and checks each setting the build depends on; `--teardown --execute` deletes what it built and checks that nothing is left. Writes `federation.json`, and refuses to write a record carrying any estate value. |
| `federation.json` | That record from the reference estate. The chapter's plates render it. |
| `expected-output.md` | A run's transcript, with what to read in it. |

## Run it

Read the plan first. It needs no credentials:

```bash
python3 org_federation.py --protocol oidc --org-type all-apps --user-key oid
python3 org_federation.py --protocol saml --org-type classic
```

Then build, prove and tear down a throwaway:

```bash
export VCFA_HOST=<automation-fqdn>
export VCFA_PROVIDER_BEARER_FILE=/path/to/provider-bearer             # mode 0600, a provider System Administrator's bearer
export TLS_VERIFY=false                                                # only on a self-signed lab CA
export ENTRA_TENANT_ID=<tenant-id> ENTRA_CLIENT_ID=<automation-app-client-id>
export ENTRA_CERT_FILE=/path/to/cert.pem ENTRA_KEY_FILE=/path/to/key.pem   # or ENTRA_CLIENT_SECRET_FILE
export ORG=fed-trial-1                                                 # a name no organization, app or group uses
export ENTITLED_UPN=<test-user-1> UNENTITLED_UPN=<test-user-2>

python3 org_federation.py --protocol oidc --org-type all-apps --execute
python3 org_federation.py --protocol oidc --org-type all-apps --prove
# sign in at https://<automation-host>/tenant/<org> as each test user (the checklist the --prove run prints)
python3 org_federation.py --protocol oidc --org-type all-apps --teardown --execute
```

A provider bearer lasts an hour, so mint it just before each run. `VCFA_PROVIDER_REFRESH_TOKEN_FILE` takes a provider api-token instead and trades it for a bearer, and `ENTRA_CLIENT_SECRET_FILE` takes a client secret instead of a certificate. On the reference estate the runs used a provider bearer and a certificate; the api-token and the client secret paths were not exercised there, and whether a provider api-token's bearer may create organizations and write their settings was not tested.

The Entra app the script runs as creates and deletes app registrations, service principals, their role
assignments and permission grants, and groups, and sets a service principal's claims policy. On the reference
estate it ran as an app holding, among other Microsoft Graph application permissions, `Application.ReadWrite.All`,
`AppRoleAssignment.ReadWrite.All`, `DelegatedPermissionGrant.ReadWrite.All`, `Group.ReadWrite.All`,
`User.ReadWrite.All` and `Policy.ReadWrite.ApplicationConfiguration`; a smaller set was not tried. Those are
tenant-wide powers: run it in a tenant made for trials, or as an app you remove afterwards.

## What it does, in order

1. **The organization**, classic or All Apps, then its roles read back: the import uses the member-level role the
   organization type holds (Organization Member on a classic organization, Organization User on an All Apps one),
   and the run stops if this build names its roles differently.
2. **One entitlement group** at Entra, a cloud-only security group.
3. **The Entra app.** OIDC: an app registration with the organization's redirect URI, a groups claim limited to
   groups assigned to the app and carrying display names, assignment required, admin consent for
   `openid profile email`, and a client secret that ends in under a year (`SECRET_DAYS`, default 180), held until
   Entra accepts it. SAML: an enterprise app from the Custom template with the organization's own entity id and
   assertion consumer, the same groups claim, a signing certificate, and an email claim set before anyone signs
   in.
4. **The group as the app's only assignment**, and the entitled test user as a direct member.
5. **The organization's settings by round trip**: read, change the named fields, write back, read again. OIDC:
   Entra's discovery document and signing keys, PKCE off, keys refreshed every hour and added rather than replaced,
   users keyed on the claim you chose (`--user-key`). SAML: Entra's app metadata, once it names the signing
   certificate, and the attribute mapping.
6. **The group imported** with its role.

## Scope, stated plainly

- It creates and deletes only what it records in its state file (`org_federation.<ORG>.state.json`, object ids,
  no secrets): an existing organization, app or group of the same name is refused, never adopted. Keep the state
  file beside the record and do not publish it.
- `--prove` checks configuration on both sides. It does not sign anyone in: a federated sign-in is a browser
  protocol, so the proof that matters (an entitled user holds its group's role, a user in no assigned group is
  refused at Entra with `AADSTS50105`, several sign-ins minutes apart) is yours to make in a browser.
- Teardown deletes the organization (disabled first, by a round trip of its full record), the Entra app and the
  group, by object id; deleting the app soft-deletes its service principal, so it purges all three from Entra's
  recycle bin, and reads each back until nothing is left or three minutes pass.
- Entra and VCF Automation only. Other providers federate the same way on the VCF Automation side; the Entra side
  is this script's.
- The SAML email claim is set through Microsoft Graph's beta claims-policy endpoint
  (`servicePrincipals/{id}/claimsPolicy`), so that step can change as the beta does.

## Reading the record

One record per organization: `protocol`, `org_type` and `user_key`, then `runs`, with one entry per mode you ran
(`execute`, `prove`, `teardown`), each holding when it ran and its `steps`. Each step has its HTTP status (or `done`
where a step made several calls), the seconds since that run began, and what it read back: for OIDC the stored safety
settings (`usePKCE`, `keyRefreshStrategy`, `keyRefreshFrequencyInHours`, `subjectAttributeName`) and the number of
signing keys held; for SAML the mapped attributes and the claims the app emits. `live_after_s` is how long Entra
refused the new client secret, `after_s` on the metadata step how long Entra took to name the new signing certificate
in the app's metadata, and `after_s` on each purge how long the recycle bin took to release the object. The `prove`
run lists each check as `pass` or `FAIL`; the `teardown` run ends on the residue check. A refusal is recorded
verbatim, with every estate value replaced by a placeholder.
