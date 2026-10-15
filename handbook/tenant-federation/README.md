# A tenant organization on its own identity provider

Companion to the chapter
([privatecloudarchitect.com/handbook/tenant-federation](https://privatecloudarchitect.com/handbook/tenant-federation)):
one script that federates a VCF Automation organization straight to Microsoft Entra ID, over OIDC or SAML, on a
classic or an All Apps organization, and takes it down again. Stdlib Python 3.9 or later; the `cryptography` package
only when Entra is reached with a certificate rather than a client secret. No secret or token is printed or written.

| File | What it is |
|---|---|
| `org_federation.py` | Plans by default: prints every body each side will be sent, the checklist the tenant's identity administrator works through on Entra ID (with the read-only app the provider asks for, and the name claim kept as the user principal name, which the leaver job looks each account up by), the checklist you work through in the organization, and the proof checklist, each with its owner, and changes nothing. `--execute` builds a throwaway organization, an Entra app and one entitlement group, and wires them; `--prove` reads both sides back and checks each setting the build depends on; `--teardown --execute` deletes what it built and checks that nothing is left. For a real tenant's organization, which `--execute` refuses, `--prove --org` proves it read-only and `--configure --org` writes the provider's side from what the tenant handed over; neither needs a state file. Writes `federation.json` (or `prove.json`, `configure.json`), and refuses to write a record carrying any estate value. |
| `federation.json` | That record from the reference estate. The chapter's plates render it. |
| `update_key_refresh.json`, `update_keys.json`, `update_secret.json`, `update_metadata.json` | The day-2 writer's records, one per kind of write, from a throwaway OIDC organization and a throwaway SAML one on the reference estate. federation-operations' plates render them. |
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

A provider bearer lasts an hour, so mint it just before each run, as the platform-identity chapter's plate 04, "Your provider bearer", shows ([privatecloudarchitect.com/handbook/platform-identity](https://privatecloudarchitect.com/handbook/platform-identity)). `VCFA_PROVIDER_REFRESH_TOKEN_FILE` takes a provider api-token instead and trades it for a bearer, and `ENTRA_CLIENT_SECRET_FILE` takes a client secret instead of a certificate. On the reference estate the runs used a provider System Administrator's bearer and a certificate; the api-token and the client secret paths were not exercised there. Whether a provider api-token's bearer may create organizations, write their settings or import their groups was not tried, and in the identity-lifecycle companion a provider api-token's bearer was refused an account write (403) that a provider bearer carried, so give every write here a provider bearer.

## Exit codes

| Exit | Means |
|---|---|
| 0 | done: the plan printed, or every step and check passed |
| 1 | a call or a check failed; the record names which |
| 2 | refused by what it read: a name this script did not create, no state file to tear down, no such organization, an organization not federated to `ENTRA_TENANT_ID`, a change its protocol does not take, a protocol or user-key switch, a role its type lacks, a named group held another way, or SAML with no metadata yet (it prints what the tenant needs) |
| 3 | a result not known: a credential refused before anything was read, a check with nothing to read yet (`--prove --org` over SAML before any SAML user has signed in: run it again after the first browser sign-in), a record the scrub refused to write, or an error the script did not expect (never 1) |
| 5 | not run as asked, and nothing sent: an unknown, missing or malformed argument (`--group` without `ROLE=NAME`, `--keys` without `--update`), a missing environment variable or credential, a file that cannot be read, metadata that is not the tenant's or names no signing certificate, `SECRET_DAYS` of a year or more, a Python older than 3.9 |

The Entra app the script runs as creates and deletes app registrations, service principals, their role
assignments and permission grants, and groups, and sets a service principal's claims policy. On the reference
estate it ran as an app holding, among other Microsoft Graph application permissions, `Application.ReadWrite.All`,
`AppRoleAssignment.ReadWrite.All`, `DelegatedPermissionGrant.ReadWrite.All`, `Group.ReadWrite.All`,
`User.ReadWrite.All` and `Policy.ReadWrite.ApplicationConfiguration`; a smaller set was not tried. Those are
tenant-wide powers: run it in a tenant made for trials, or as an app you remove afterwards.

## A real organization: configure it, then prove it

`--execute` builds only throwaways: it refuses any organization, app or group it did not create. A real tenant's
organization is built in two halves. The tenant's administrator builds the Entra app from the workshop's first list
and hands over its client id and secret (OIDC) or its federation metadata (SAML). You create the organization first,
choosing its type, which decides the role names its groups are imported with: `POST /cloudapi/1.0.0/orgs`, with
`isClassicTenant` true for a classic organization, the call `--execute` sends for its throwaways (this script has no
mode that creates an organization it does not also tear down). Then write its side with `--configure --org`, and
prove it with `--prove --org`. Both take the organization by name and
need no state file; neither writes to Entra.

```bash
export VCFA_HOST=<automation-fqdn> ENTRA_TENANT_ID=<tenant-id>
export VCFA_PROVIDER_BEARER_FILE=<file>    # a provider bearer: platform-identity's plate 04, "Your provider bearer"
export APP_CLIENT_ID=<the app's client id> APP_SECRET_FILE=<the secret the tenant handed over, mode 0600>   # OIDC
# export METADATA_FILE=<the app's federation metadata>                                                     # SAML

python3 org_federation.py --configure --org <org> --protocol oidc --user-key oid \
    --group member=<group> --group administrator=<group>            # the plan: what changes, what is imported
python3 org_federation.py --configure --org <org> --protocol oidc --user-key oid \
    --group member=<group> --group administrator=<group> --execute  # write, import, read every write back
python3 org_federation.py --prove --org <org> --group member=<group> --group administrator=<group>
python3 ../federation-operations/watch.py                            # with ORGS=<org>: the Entra side of each group
```

`--configure` writes the settings as a round trip, only when a field differs, and imports each `--group ROLE=NAME`
with the role the organization type defines, resolved by name from the organization's own role list. It refuses
(exit 2) a protocol or user-key switch on an organization already federated, an organization signed in through VCF
single sign-on (OIDC), a role key the organization type lacks (a classic organization has no auditor), and a named
group the organization already holds under the other protocol or with other roles; a missing `APP_CLIENT_ID` over
OIDC, or metadata that is not the tenant's, is a usage error (exit 5) and sends nothing. Over SAML without
`METADATA_FILE` it prints the organization's own service-provider identifier and reply URL for the tenant's
administrator, and stops. `--prove --org` reads the settings back against the plan for the protocol, type and user key
the organization holds, every imported group's roles against the organization's own role list, each named group's
role, and an enabled local user holding the top role, and prints the browser steps. Over SAML it also reads every
SAML user's stored email: an address passes, and the NameID stored as the email fails, the state in which a round trip
of the user's record was refused. The round trip itself is a write, which `--prove` never sends, so whether one succeeds
on your organization stays a step a person runs once on a test user. Before any SAML user has signed in there is no
stored email to read, so the check is not run and the run exits 3: run `--prove --org` again after the first browser
sign-in. Neither mode can see Entra:
VCF Automation imported a group name that no group assigned to the app carried, and only the watch's `group_names`
check, through the tenant's read-only app, failed on it.

On the reference estate (2026-10-15, X-192): a throwaway All Apps OIDC organization keyed on `oid`, built by
`--execute` and then configured as if someone else had built it. The plan named two changes, the key refresh (moved
to 24 hours for the run) and a client secret the tenant side added and handed over; `--execute` wrote both in one
round trip, imported a second group with Organization Administrator, and every check read back; a second run wrote
nothing; a switch to SAML and a switch to `preferred_username` were refused with nothing written; and `--prove --org`
passed every check. Run read-only on two standing organizations built earlier by other drivers, `--prove --org`
failed one OIDC organization on its key refresh (every 24 hours, not one) and one SAML organization on its local
administrator (none enabled holding Organization Administrator). The throwaway was removed with nothing left.
`--configure` over SAML and on a classic organization was not run live.

## Day 2: change an existing organization

`--update` works on an organization that already exists and is federated to your tenant, whoever built it. It reads
the organization's settings, changes only the fields you name, prints the plan, and with `--execute` writes the whole
body back and reads every changed field back. It never touches Entra: the tenant's administrator rotates secrets and
certificates on Entra ID, and this writes what the organization must hold.

```bash
export VCFA_HOST=<automation-fqdn> ENTRA_TENANT_ID=<tenant-id>
export VCFA_PROVIDER_BEARER_FILE=<file>    # a provider bearer, as for --configure: platform-identity's plate 04, "Your provider bearer"
export ORG=<the organization>

python3 org_federation.py --update --key-refresh               # plan: automatic refresh on, strategy ADD, every hour
python3 org_federation.py --update --key-refresh --execute     # write it and read it back
python3 org_federation.py --update --keys --execute            # the keys the provider publishes now (after an emergency roll)
NEW_SECRET_FILE=<file> python3 org_federation.py --update --secret --execute      # the secret the tenant's administrator rotated
METADATA_FILE=<file> python3 org_federation.py --update --metadata --execute      # SAML: metadata naming both certificates
```

It refuses (exit 2) an organization not federated to `ENTRA_TENANT_ID` (an organization signed in through VCF single
sign-on included) and a change the organization's protocol does not take (`--metadata` on OIDC, the others on SAML).
A `--secret` or `--metadata` without its file, and metadata that is not this tenant's or names no signing
certificate, are usage errors (exit 5): nothing is sent.
A settings write carries the client secret, because VCF Automation refuses an OIDC settings write without it: the one
the organization holds, read and sent back in memory, or the new one; neither is printed or written.

On the reference estate (2026-10-13, a throwaway All Apps organization over OIDC and one over
SAML, built and removed by the run): the key refresh was written to 24 hours and back to one hour, the keys the
provider publishes were written (all six already held), a secret rotated at Entra was written and read back, and the
SAML metadata Entra publishes for the app was written, with the same signing certificate. Every changed field read back
as written. On OIDC the check compares every settings field except the key-refresh fields, the keys and the secret; on
SAML it checks only that the organization holds the metadata's certificates and that SAML stayed enabled, so the keys
and metadata writes were round trips, not repairs. The writer was not run against an organization this script did not
build, and `--key-refresh` above one hour is for drills.

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
   in. The entity id and assertion consumer come from the organization's service-provider metadata, which a new
   organization served only after its first seconds (HTTP 500 until then), so the script reads it until it answers;
   on a real tenant that makes the provider's fetch the first step of the hand-off, sent to the tenant's
   administrator before the app is built.
4. **The group as the app's only assignment**, and the entitled test user as a direct member.
5. **The organization's settings by round trip**: read, change the named fields, write back, read again. OIDC:
   Entra's discovery document and signing keys, PKCE off, keys refreshed every hour and added rather than replaced,
   users keyed on the claim you chose (`--user-key`). SAML: Entra's app metadata, once it names the signing
   certificate, and the attribute mapping.
6. **The group imported** with its role.

## Scope, stated plainly

- `--execute` and `--teardown` create and delete only what they record in the state file
  (`org_federation.<ORG>.state.json`, object ids, no secrets): an existing organization, app or group of the same
  name is refused, never adopted. `--configure --org` and `--prove --org` read no state file and delete nothing. Keep the state
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
