# A tenant organization on its own identity provider

Companion to the chapter
([privatecloudarchitect.com/handbook/tenant-federation](https://privatecloudarchitect.com/handbook/tenant-federation)):
one script that federates a VCF Automation organization straight to Microsoft Entra ID, over OIDC or SAML, on a
classic or an All Apps organization, and takes it down again. Stdlib Python 3.9 or later; the `cryptography` package
only when Entra is reached with a certificate rather than a client secret. No secret or token is printed or written.

| File | What it is |
|---|---|
| `org_federation.py` | Plans by default: prints the request bodies the organization will be sent, the checklist the tenant's identity administrator works through on Entra ID (with the read-only app the provider asks for, and the name claim kept as the user principal name, which the leaver job looks each account up by), the checklist you work through in the organization, and the proof checklist, each with its owner, and changes nothing. `--execute` builds a throwaway organization, an Entra app and one entitlement group, and wires them; `--prove` reads both sides back and checks each setting the build depends on; `--teardown --execute` deletes what it built and checks that nothing is left. For a real tenant's organization, which `--execute` refuses, `--prove --org` proves it read-only and `--configure --org` writes the provider's side from what the tenant handed over; neither needs a state file. Writes `federation.json` (or `prove.json`, `configure.json`), and refuses to write a record carrying any estate value. |
| `federation.json` | That record from the reference estate. The chapter's plates render it. |
| `update_key_refresh.json`, `update_keys.json`, `update_secret.json`, `update_metadata.json` | The day-2 writer's records, one per kind of write, from a throwaway OIDC organization and a throwaway SAML one on the reference estate. federation-operations' plates render them. |
| `expected-output.md` | A run's transcript, with what to read in it, and a replayed run. |
| `replay/org_federation/` | A recorded answer set built from `federation.json` and the `update_*.json` records, every name a placeholder, for `--replay`: the script runs on it with no estate and sends nothing. |

## Try it without an estate

`--replay DIR` answers every request from a recorded set instead of the estate, so you can run the script before you
hold a provider credential or a tenant, or see what a mode prints before you point it at an organization. The set
beside this README, `replay/org_federation/`, is made from the committed records, with a placeholder for every name:
`org-01`, the All Apps organization over OIDC of the `update_*.json` records (its keys refreshed every 24 hours), and
`org-02`, the classic organization over SAML of `federation.json`, both federated to one Entra tenant.

```bash
python3 org_federation.py --replay replay/org_federation --prove --org org-02 --protocol saml --org-type classic   # proven read-only; exits 0
python3 org_federation.py --replay replay/org_federation --update --key-refresh   # ORG is org-01: the plan, 24 h to 1 h
python3 org_federation.py --replay replay/org_federation --update --keys --secret --execute   # a writer: its plan alone
python3 org_federation.py --replay replay/org_federation --configure --org org-01 --protocol oidc --group member=group-3 --execute
```

Nothing is sent and no credential is read: the set answers each request by its method, path and query, and names the
placeholder host, tenant and organization it was recorded on (`ORG` is `org-01`, `APP_CLIENT_ID` its app). A request
the set holds no answer for is a read that failed, so the run exits 3 and names the read, never a pass. Every write
this script sends is sent under `--execute`, so under `--replay` a run given `--execute` prints `replay: --execute runs
its plan alone under --replay; nothing is sent` and runs its plan: no mode writes, and no record says a write
happened. Each record goes to its `.replay.json` name (`prove.replay.json`, `update.replay.json`,
`configure.replay.json`, `federation.replay.json`) unless `OUT` names a file, so a replayed run never overwrites a
real record. The transcript is under "A replayed run" in `expected-output.md`.

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
export ENTRA_CERT_FILE=/path/to/cert.pem ENTRA_KEY_FILE=/path/to/key.pem   # the key mode 0600; or ENTRA_CLIENT_SECRET_FILE
export ORG=fed-trial-1                                                 # a name no organization, app or group uses
export ENTITLED_UPN=<test-user-1> UNENTITLED_UPN=<test-user-2>

python3 org_federation.py --protocol oidc --org-type all-apps --execute
python3 org_federation.py --protocol oidc --org-type all-apps --prove
# sign in at https://<automation-host>/tenant/<org> as each test user (the checklist the --prove run prints)
python3 org_federation.py --protocol oidc --org-type all-apps --teardown --execute
```

A provider bearer lasts an hour, so mint it just before each run, as the platform-identity chapter's plate 04, "Your provider bearer", shows ([privatecloudarchitect.com/handbook/platform-identity](https://privatecloudarchitect.com/handbook/platform-identity)). `VCFA_PROVIDER_REFRESH_TOKEN_FILE` takes a provider api-token instead and trades it for a bearer, and `ENTRA_CLIENT_SECRET_FILE` takes a client secret instead of a certificate. On the reference estate the runs used a provider System Administrator's bearer and a certificate; the api-token and the client secret paths were not exercised there. Whether a provider api-token's bearer may create organizations, write their settings or import their groups was not tried, and in the identity-lifecycle companion a provider api-token's bearer was refused the write that disables a local account (403), the write a provider bearer carried, so give every write here a provider bearer. With both files set, the script uses the bearer. Every secret's file (the bearer, the api-token, a client secret, the key) is read only at mode 0600: one open to group or other is refused unread, with the fix (`chmod 600` on the file), and the run exits 5 with nothing sent.

## Exit codes

| Exit | Means |
|---|---|
| 0 | done: the plan printed, or every step and check passed |
| 1 | a check failed, or a write was refused while building, configuring, updating or tearing down; the record names which |
| 2 | refused by what it read, with nothing sent: a name this script did not create, no state file to tear down, no such organization, an organization with no federation to `ENTRA_TENANT_ID` switched on (for `--update`, which says what the organization holds), a change its protocol does not take, a switch of protocol, OIDC user key or SAML user-name claim (judged on what the organization stores and the users it holds, enabled or not, and on a re-run of `--execute` over its own organization), a change of the app or the issuer under OIDC users keyed on a claim other than `oid` or `preferred_username`, a settings write to a switched-off federation without `--enable`, a group import into a federation that stays switched off, a group-only import to an organization that stores no settings for the tenant over that protocol, a client secret Entra refused, a role its type lacks, a named group held another way, SAML with no metadata yet (it prints what the tenant needs), SAML metadata naming none of the certificates the organization holds while it holds SAML users and the organization's app was not read, and, with the tenant's read-only app, a group to import that no group assigned to the app is named (or two are), metadata that does not name the certificate Entra signs the app with or names one the app does not hold, or no app (or two) carrying the organization's client id or identifier |
| 3 | a result not known: a credential refused before anything was read (the tenant's read-only app's among them), a read refused or a list not read to its end in any mode (`--prove` and `--prove --org` only read), Entra out of reach when asked about a new secret or a tenant's domain, a check with nothing to read yet (`--prove --org` over SAML before any SAML user has signed in: run it again after the first browser sign-in), a teardown that could not read whether an object it made is gone (an answer other than 200 or 404), a record the scrub refused to write on a run that would have exited 0, a request a `--replay` set holds no answer for, or an error the script did not expect (never 1). A record the scrub refuses never hides a 1, a 2 or a 3: the run's own code stands |
| 5 | not run as asked, and nothing sent: an unknown, missing or malformed argument (`--group` without `ROLE=NAME`, `--keys` without `--update`, `--enable` without `--configure`, `--groups-only` without `--group` or with `--enable` or `--user-key`), a missing environment variable or credential (`ENTRA_CLIENT_ID` without its credential among them), an `ENTRA_TENANT_ID` that is neither a tenant id nor a domain Entra names a tenant for, a file that cannot be read, a credential file that is empty, a secret's file open to group or other (refused unread, with the fix: `chmod 600`), metadata that is not the tenant's or names no signing certificate that reads, `SECRET_DAYS` of a year or more, a `--replay` directory that cannot be read or holds no replay set, a Python older than 3.9 |

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
need no state file; neither writes to Entra. `ENTRA_TENANT_ID` takes the tenant's id or one of its domain names,
resolved to the id through Entra's public OpenID configuration before anything is sent, as the watch and the leaver job
take it.

```bash
export VCFA_HOST=<automation-fqdn> ENTRA_TENANT_ID=<tenant-id or one of its domain names>
export VCFA_PROVIDER_BEARER_FILE=<file, mode 0600>    # a provider bearer: platform-identity's plate 04, "Your provider bearer"
export APP_CLIENT_ID=<the app's client id> APP_SECRET_FILE=<the secret the tenant handed over, mode 0600>   # OIDC
# export METADATA_FILE=<the app's federation metadata>                                                     # SAML
export ENTRA_CLIENT_ID=<the tenant's read-only app> ENTRA_CLIENT_SECRET_FILE=<its secret, mode 0600>   # the watch's app

python3 org_federation.py --configure --org <org> --protocol oidc --user-key oid --enable \
    --group member=<group> --group administrator=<group>            # the plan: each change, old -> new
python3 org_federation.py --configure --org <org> --protocol oidc --user-key oid --enable \
    --group member=<group> --group administrator=<group> --execute  # write, import, read every write back
python3 org_federation.py --prove --org <org> --group member=<group> --group administrator=<group>
ORGS=<org> python3 ../federation-operations/watch.py                 # the Entra side of each imported group
```

`--configure` writes the settings as a round trip, only when a field differs, and imports each `--group ROLE=NAME`
with the role the organization type defines, resolved by name from the organization's own role list. Its plan prints
each changing field as `old -> new`, the values a rollback writes back by hand (the secret is never shown). Without
`--user-key` it keeps the OIDC key the organization holds. It refuses (exit 2, nothing sent):

- a switch of protocol, OIDC user key or SAML user-name claim under the users it keys, judged on what the organization
  stores and the users it holds whether or not its federation is switched on. Over SAML a returning user is matched on
  its user name, taken from the claim the organization's mapping names: a console-built organization that maps
  another claim and holds SAML users is refused, since the write would refuse each user whose two values differ; with
  no SAML user yet, the claim is written and the plan shows the old one;
- a change of the app (its client id) or of the issuer under the OIDC users it holds, enabled or not, unless they are
  keyed on `oid` or `preferred_username`. Entra sends a person the same `oid` in every app of one tenant, and makes
  `sub` pairwise to each app, so under `sub` every returning user would get a new account and the old account would
  keep its direct roles; a key other than those two is refused the same way, since whether it moves with the app is
  not known. Under `oid` or `preferred_username` the plan says the users keep their accounts. An issuer the users'
  tenant cannot be read from is refused whatever the key, since `oid` and `sub` both change across tenants. A
  refusal names only flags the script takes: an organization keyed on `sub` is kept on it by running without
  `--user-key`;
- a settings write to a federation that is switched off, unless `--enable` is given, which the plan shows as
  `enabled: off -> on`; and a group import into a federation that stays switched off. VCF Automation refused a group
  import into a federation switched off (403, `GROUP_IMPORT`) where the same import was taken once it was switched on,
  so a run with a group to import and no `--enable` is refused there before anything is sent; with `--enable` the
  settings are written first and the groups imported after. `--groups-only` imports each `--group` into a federation
  switched on and never writes the settings, whatever they hold (the repair of a renamed group); it needs no
  `APP_CLIENT_ID`, secret or metadata, and refuses an organization that stores no settings for the tenant over that
  protocol. An organization that was never federated is switched off too, so its first configuration takes
  `--enable`;
- a new client secret Entra does not accept: before anything is written, the plan asks Entra's token endpoint for a
  token with it, and a refusal is named (a Secret ID pasted where the Value belongs is named as such);
- an organization signed in through VCF single sign-on, settings stored for a provider other than `ENTRA_TENANT_ID`, a
  role key the organization type lacks (a classic organization has no auditor), and a named group the organization
  already holds under the other protocol or with other roles;
- with the tenant's read-only app (`ENTRA_CLIENT_ID` with `ENTRA_CLIENT_SECRET_FILE`, or with `ENTRA_CERT_FILE` and
  `ENTRA_KEY_FILE`; the watch's app, which these reads need no more than), a group to import that no group assigned to
  the organization's app at Entra is named, or that two assigned groups are named. VCF Automation imports such a name
  all the same: it admits no one, and its role waits for whichever group is later given the name. The app is the one
  holding the organization's client id over OIDC, or its service-provider identifier over SAML, and no app or two is a
  refusal too. Every call there is a GET. Without the app, the plan says each group's assignment was not read, and the
  watch's `group_names` check is the one that reads it;
- over SAML, metadata judged by certificate thumbprint, never by count: with the tenant's read-only app, metadata that
  does not name the certificate Entra signs the organization's app with now, or names a certificate the app does not
  hold (the app read again for up to 90 seconds first while the metadata names the certificate it signs with, since
  Graph listed a certificate just added to the app later than Entra's metadata named it); without it, metadata naming
  none of the certificates the organization holds while it holds SAML users, enabled or not. Entra names the same identity-provider entity id, the tenant's issuer, in every app's metadata in one tenant,
  so another app's metadata reads as the tenant's; only the certificates tell two apps apart (read on two SAML apps of
  the lab's tenant, X-250). The plan prints the certificates kept, dropped and added by thumbprint.

A missing `APP_CLIENT_ID` over OIDC, or metadata that is not the tenant's, is a usage error (exit 5) and sends
nothing. Every list it reads (organizations, users, groups, roles) is read until its distinct items reach the total
the platform states; a list read short, or a page that adds no item not already read, is exit 3, never a short list,
and the read stops there. Every Graph list is read to its last next link: a page holding no item is read on, since
Microsoft's paging guidance says "A page of results might contain zero or more results"
([Paging Microsoft Graph data in your app](https://learn.microsoft.com/en-us/graph/paging)), and a 200 without its
`value` list, or a next link that is not a link or comes back, is exit 3. Over SAML without
`METADATA_FILE` it prints the organization's own service-provider identifier and reply URL for the tenant's
administrator, and stops. `--prove --org` reads the settings back against the plan for the protocol, type and user key
the organization holds, every imported group's roles against the organization's own role list, each named group's
role, and an enabled local user holding the top role, and prints the browser steps. Over SAML it also reads every
SAML user's stored email: an address passes, and the NameID stored as the email fails, the state in which a round trip
of the user's record was refused. The round trip itself is a write, which `--prove` never sends, so whether one succeeds
on your organization stays a step a person runs once on a test user. Before any SAML user has signed in there is no
stored email to read, so the check is not run and the run exits 3: run `--prove --org` again after the first browser
sign-in. `--prove --org` cannot see Entra: VCF Automation imported a group name that no group assigned to the app
carried, and the proof passed it; the watch's `group_names` check, through the tenant's read-only app, failed on it,
and `--configure` given that app now refuses such an import before it is sent.

On the reference estate (2026-10-15, X-192): a throwaway All Apps OIDC organization keyed on `oid`, built by
`--execute` and then configured as if someone else had built it. The plan named two changes, the key refresh (moved
to 24 hours for the run) and a client secret the tenant side added and handed over; `--execute` wrote both in one
round trip, imported a second group with Organization Administrator, and every check read back; a second run wrote
nothing; a switch to SAML and a switch to `preferred_username` were refused with nothing written; and `--prove --org`
passed every check. Run read-only on two standing organizations built earlier by other drivers, `--prove --org`
failed one OIDC organization on its key refresh (every 24 hours, not one) and one SAML organization on its local
administrator (none enabled holding Organization Administrator). The throwaway was removed with nothing left.
`--configure` over SAML and on a classic organization was not run live, and neither were `--enable`, the SAML
user-name claim refusal, the secret check, a group import into a switched-off federation, the assignment read before an
import, the metadata judged by thumbprint or a tenant given by domain: the companion's tests hold them, across each
protocol, user key and organization type. Whether VCF Automation takes a group import while the organization's federation is switched off was not run; with
only SAML on, it refused (403) an OIDC import of a name the organization held over SAML.

## Day 2: change an existing organization

`--update` works on an organization that already exists and is federated to your tenant, whoever built it. It reads
the organization's settings, changes only the fields you name, prints the plan with the fields it would change, and
with `--execute` writes the whole body back and reads every changed field back. When the organization already holds
what you asked for, it writes nothing, records "nothing to change", reads the settings back and exits 0. It never
writes to Entra: the tenant's administrator rotates secrets and certificates on Entra ID, and this writes what the
organization must hold. With `--secret` it first asks Entra's token endpoint for a token with the new secret, plan
included, and a secret Entra refuses is not written (exit 2, nothing sent); Entra out of reach is exit 3. With
`--metadata` it judges the file as `--configure` does: by certificate thumbprint, against the SAML users the organization
holds and, when `ENTRA_CLIENT_ID` names the tenant's read-only app, against the certificate Entra signs the
organization's app with now. That read is what lets the repair after a certificate was already rolled at Entra through:
metadata that drops every certificate the organization holds is refused under SAML users unless the app's active
certificate confirms it.

```bash
export VCFA_HOST=<automation-fqdn> ENTRA_TENANT_ID=<tenant-id>
export VCFA_PROVIDER_BEARER_FILE=<file, mode 0600>    # a provider bearer, as for --configure: platform-identity's plate 04, "Your provider bearer"
export ORG=<the organization>

python3 org_federation.py --update --key-refresh               # plan: automatic refresh on, strategy ADD, every hour
python3 org_federation.py --update --key-refresh --execute     # write it and read it back
python3 org_federation.py --update --keys --execute            # the keys the provider publishes now (after an emergency roll)
NEW_SECRET_FILE=<file, mode 0600> python3 org_federation.py --update --secret --execute      # the secret the tenant's administrator rotated
METADATA_FILE=<file> python3 org_federation.py --update --metadata --execute      # SAML: metadata naming both certificates
# --metadata with the tenant's read-only app: ENTRA_CLIENT_ID and ENTRA_CLIENT_SECRET_FILE, as for --configure
```

It refuses (exit 2) an organization with no federation to `ENTRA_TENANT_ID` switched on, and says what the
organization holds: a federation to the tenant switched off (then it names, for each protocol it holds, the
`--configure --org NAME --protocol <protocol> --enable` command that switches it back on; a group is imported only
into a federation switched on), settings for another provider, VCF single sign-on, or nothing stored. It refuses a change the organization's protocol does not take (`--metadata` on OIDC, the others on
SAML).
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
and metadata writes were round trips, not repairs. The keys run sent a write that changed nothing (`update_keys.json`
records `"changed": []`); the writer now sends none in that case and records "nothing to change", which the companion's
tests hold and no live run has shown yet. The writer was not run against an organization this script did not build, and
`--key-refresh` above one hour is for drills.

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
  name is refused, never adopted. `--teardown` without `--execute` reads the state file and lists what it records;
  with no state file it refuses (exit 2), as `--teardown --execute` does. `--configure --org` and `--prove --org` read no state file and delete nothing. Keep the state
  file beside the record and do not publish it.
- `--prove` checks configuration on both sides. It does not sign anyone in: a federated sign-in is a browser
  protocol, so the proof that matters (an entitled user holds its group's role, a user in no assigned group is
  refused at Entra with `AADSTS50105`, several sign-ins minutes apart) is yours to make in a browser.
- Teardown deletes the organization (disabled first, by a round trip of its full record), the Entra app and the
  group, by object id; deleting the app soft-deletes its service principal, so it purges all three from Entra's
  recycle bin, and reads each back until nothing is left or three minutes pass. A read that answers neither 200 nor
  404 says nothing of whether the object is gone, so the residue check reads `NOT KNOWN` and the run exits 3. A
  re-run of `--execute` over its own organization reads its stored settings and users first, and refuses a protocol
  or key switch under them: the same command with the key it holds keeps it, and another key is a new organization
  (set `ORG` to a name no organization uses, and remove this one with `--teardown --execute`).
- Entra and VCF Automation only. Other providers federate the same way on the VCF Automation side; the Entra side
  is this script's.
- The SAML email claim is set through Microsoft Graph's beta claims-policy endpoint
  (`servicePrincipals/{id}/claimsPolicy`), so that step can change as the beta does.

## Reading the record

Every record a `--replay` run writes (`federation.replay.json`, `update.replay.json`, `prove.replay.json`,
`configure.replay.json`) carries `"replay": true` at its top level, and a live run's record carries no such key: a
replayed record shows no read of an estate.
One record per organization: `protocol`, `org_type` and `user_key`, then `runs`, with one entry per mode you ran
(`execute`, `prove`, `teardown`), each holding when it ran and its `steps`. Each step has its HTTP status (or `done`
where a step made several calls), the seconds since that run began, and what it read back: for OIDC the stored safety
settings (`usePKCE`, `keyRefreshStrategy`, `keyRefreshFrequencyInHours`, `subjectAttributeName`) and the number of
signing keys held; for SAML the mapped attributes and the claims the app emits. `live_after_s` is how long Entra
refused the new client secret, `after_s` on the metadata step how long Entra took to name the new signing certificate
in the app's metadata, and `after_s` on each purge how long the recycle bin took to release the object. The `prove`
run lists each check as `pass` or `FAIL`; the `teardown` run ends on the residue check. A refusal is recorded
verbatim, with every estate value replaced by a placeholder.
