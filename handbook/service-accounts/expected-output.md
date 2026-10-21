# Expected output

Transcripts from one VCF 9.1.0 instance with Real-Time Metrics deployed, 2026-09-16, and from the same estate on
VCF 9.1.1, host names and identifiers replaced: `doors.py` on every login path the reference catalog signs in by,
read on VCF 9.1.1 on 2026-10-21 (the first section); the 9.1.0 run, the only one that read the tenant OAuth grant;
and the broker and fleet-plane half of `doors.py` read on VCF 9.1.1 on 2026-10-15, which the last section replays from
the sets beside the scripts. Your rows will differ where your surfaces differ; the shape is what to expect.

## doors.py on VCF 9.1.1, every path the catalog signs in by

The run of 2026-10-21, on VCF Operations 9.1.1.0, VCF Automation 9.1.1.0100, NSX 9.1.1.0, vCenter 9.1.1.0 and SDDC
Manager 9.1.1.0, with every surface configured but the tenant OAuth grant: the reference catalog holds no tenant API
token for it, so its rows and the arrival rule's numbers are the 9.1.0 run's, in the next section. Every verdict is
the one the chapter states. The provider api-token path ran for the first time; its refresh token came back unchanged,
so no file was written. With one tenant path run, no arrival-rule line prints: that line compares one principal's
OAuth grant with its Basic session, and the provider is another principal, so its count stays on its own row. The
same organization user's Basic session read 136 effective rights on the 9.1.0 run and 144 here; what changed was
not read.

```text
doors.py: one harmless read per pair; tokens minted per run and never printed

broker bearer minted from the api-token

  VCF Operations                     broker bearer               200  accepted  MATCH
  NSX                                broker bearer               200  accepted  MATCH
  Real-Time Metrics                  broker bearer               401  refused   MATCH                      the fleet plane refuses the broker's bearer
  Real-Time Metrics                  service JWT (VCF_VODAP)     200  accepted  MATCH
  Fleet lifecycle, components        service JWT (VCF_FLEET_LCM)  200  accepted  MATCH
  Fleet lifecycle, components        the metrics service's JWT   401  refused   MATCH                      minted per service, so another service's is refused here
  Fleet lifecycle, health probe      the metrics service's JWT   200  accepted                             the health probe answers any service's JWT
  Real-Time Metrics                  the fleet service's JWT     200  accepted  MATCH                      accepted here, while Fleet lifecycle refuses another service's
  Log management                     service JWT (VCF_OPS_LI)    200  accepted  MATCH                      sent as X-JWT-Token

  VCF Automation, tenant OAuth grant   skipped: VCFA_HOST, VCFA_ORG, VCFA_REFRESH_TOKEN_FILE not all set

VCF Automation, the Basic session login
  VCF Automation, session login      Basic (user@org)            200  accepted  MATCH                      bearer returned in a response header
  VCF Automation, rights             session bearer              200  accepted  MATCH                      144 effective rights

VCF Automation, the provider api-token
  /oauth/provider/token: bearer minted; a refresh token came back with it and is the same value you sent (no rotation on this build)
  VCF Automation, provider rights    provider bearer             200  accepted  MATCH                      422 effective rights
  VCF Automation, control plane      provider bearer             401  refused   MATCH                      a tenant surface

vCenter, its own session
  vCenter, session mint              Basic                       201  accepted  MATCH                      a session id in the body, no Bearer prefix
  vCenter API                        session id                  200  accepted  MATCH

SDDC Manager, its own bearer
  SDDC Manager, token mint           username and password       200  accepted  MATCH
  SDDC Manager API                   its bearer                  200  accepted  MATCH

17 pairs read; 0 differ from the chapter; 0 without an answer

exit 0
```

## doors.py

The run of 2026-09-16 on VCF 9.1.0, the only one that read the tenant OAuth grant, and so the only one whose
arrival-rule line compares one principal's two tenant paths. Every surface configured; the provider api-token path
skipped because no provider refresh token was supplied.
The one DIFFERS row is a finding, not a fault: it corrected the Platform identity chapter the same day (Fleet
lifecycle refuses a JWT minted for another service, and the metrics service's metadata read does not). The notes
are kept as they were recorded; the next section says why they now read differently. Run today, a skipped path names
every variable it needs: the provider line reads `skipped: VCFA_HOST, VCFA_PROVIDER_REFRESH_TOKEN_FILE not both set`.

```text
doors.py: one harmless read per pair; tokens minted per run and never printed

broker bearer minted from OPS_API_TOKEN

  VCF Operations                     broker bearer               200  accepted  MATCH
  NSX                                broker bearer               200  accepted  MATCH
  Real-Time Metrics                  broker bearer               401  refused   MATCH                      the fleet plane refuses the broker's bearer
  Real-Time Metrics                  service JWT (VCF_VODAP)     200  accepted  MATCH
  Fleet lifecycle, components        service JWT (VCF_FLEET_LCM)  200  accepted  MATCH
  Fleet lifecycle, components        the metrics service's JWT   401  refused   MATCH                      audience is per service
  Fleet lifecycle, health probe      the metrics service's JWT   200  accepted                             the health probe does not check the audience
  Real-Time Metrics                  the fleet service's JWT     200  accepted  DIFFERS (chapter says refused) audience is per service
  Log management                     service JWT (VCF_OPS_LI)    200  accepted  MATCH                      sent as X-JWT-Token

VCF Automation, the tenant OAuth grant
  /oauth/tenant/<org>/token: bearer minted; a refresh token came back with it and is the same value you sent (no rotation on this build)
  VCF Automation, rights             tenant OAuth bearer         200  accepted  MATCH                      134 effective rights
  VCF Automation, deployment plane   tenant OAuth bearer         200  accepted  MATCH
  VCF Automation, control plane      tenant OAuth bearer         200  accepted  MATCH

VCF Automation, the Basic session login
  VCF Automation, session login      Basic (user@org)            200  accepted  MATCH                      bearer returned in a response header
  VCF Automation, rights             session bearer              200  accepted  MATCH                      136 effective rights

  VCF Automation, provider api-token    skipped: VCFA_PROVIDER_REFRESH_TOKEN_FILE not set

  the arrival rule, in numbers: OAuth grant: 134 · Basic session: 136

vCenter, its own session
  vCenter, session mint              Basic                       201  accepted  MATCH                      a session id in the body, no Bearer prefix
  vCenter API                        session id                  200  accepted  MATCH

SDDC Manager, its own bearer
  SDDC Manager, token mint           username and password       200  accepted  MATCH
  SDDC Manager API                   its bearer                  200  accepted  MATCH

18 pairs read; 1 differ from the chapter; 0 without an answer

exit 0
```

A run in which a surface you configured could not mint its own token prints a line for that surface as it happens,
and one more under the summary line, and exits 3 rather than 0. A vCenter session mint, an SDDC Manager token mint or a
VCF Automation session login that answers without its session or token is the same case: its own row prints what the
mint answered, and the `NOT READ` line says the doors behind it were not read. The recorded run above minted every
token, so these lines are the shape the code prints, held by its tests, not a transcript (here the log service's JWT
was refused, and the vCenter mint answered 401):

```text
  NOT READ: Log management, service JWT (VCF_OPS_LI): the service JWT could not be minted; its doors were not read
  NOT READ: vCenter: the session mint returned no session id (HTTP 401); its doors were not read
NOT READ: 2 configured surface(s) whose own token could not be minted: Log management, service JWT (VCF_OPS_LI); vCenter (exit 3)
```

## doors.py on VCF 9.1.1, the broker and the fleet plane

The same reads on 2026-10-15, VCF 9.1.1, with the broker, NSX and the three fleet-plane services configured and VCF
Automation, vCenter and SDDC Manager left unset (the catalog that ran it holds no tenant API token for the OAuth grant
path). Every verdict is the one the 9.1.0 run read. The notes changed: a service JWT from the fleet plane's exchange
carries no `aud` claim (`claims.py` prints `audience: None` for one, below), so what Fleet lifecycle refuses is a JWT
minted for another service, not another audience. What each service's JWT names is its `authorization_details`: the
fleet lifecycle's and the log service's each name their own service, and the metrics service's is empty.

```text
doors.py: one harmless read per pair; tokens minted per run and never printed

broker bearer minted from the api-token

  VCF Operations                     broker bearer               200  accepted  MATCH
  NSX                                broker bearer               200  accepted  MATCH
  Real-Time Metrics                  broker bearer               401  refused   MATCH                      the fleet plane refuses the broker's bearer
  Real-Time Metrics                  service JWT (VCF_VODAP)     200  accepted  MATCH
  Fleet lifecycle, components        service JWT (VCF_FLEET_LCM)  200  accepted  MATCH
  Fleet lifecycle, components        the metrics service's JWT   401  refused   MATCH                      minted per service, so another service's is refused here
  Fleet lifecycle, health probe      the metrics service's JWT   200  accepted                             the health probe answers any service's JWT
  Real-Time Metrics                  the fleet service's JWT     200  accepted  MATCH                      accepted here, while Fleet lifecycle refuses another service's
  Log management                     service JWT (VCF_OPS_LI)    200  accepted  MATCH                      sent as X-JWT-Token

9 pairs read; 0 differ from the chapter; 0 without an answer

exit 0
```

## claims.py

Three runs: the operator's own api-token (a person), an API client's stored api-token (dead: deleted or rotated
away, so on this 9.1.0 run of 2026-09-16 the broker answered 500; on 9.1.1 a deleted API client token was refused with
400), and a service JWT decoded through JWT_ENV (it names the person who minted the Operations session it was
exchanged from).

The runs were recorded on 2026-09-16, when a failed mint exited 2 and printed an unscoped 500 hint. Since 2026-10-15
claims.py exits 3 for a failed mint, the code every identity companion gives a read that failed, and its hint names
the code per run: run today, the second transcript ends `exit 3`. The printed lines are kept as they were recorded.

```text
----- claims.py with the operator's api-token
decoded: the bearer exchanged from OPS_API_TOKEN at the broker (2060 characters; value never printed)
header:   alg=RS256  typ=JWT  kid=present
issuer:   https://<broker-fqdn>/acs/t/CUSTOMER/
audience: https://<broker-fqdn>/auth/t/CUSTOMER/oauthtoken
sub:      <id>
prn:      <user>@CUSTOMER
azp:      vidb_api_token_internal_client
cid:      vidb_api_token_internal_client
principal: a PERSON (eml, prn is user@realm): this bearer carries that person's rights, and a pipeline holding it dies with their account
scp:      openid profile user email group
issued:   <utc timestamp>
expires:  <utc timestamp>  (lifetime 60 min 0 s: the minutes clock; the api-token behind it is on the months clock)
other claims present: acct, auth_time, authorization_details, ctx, domain, group_ids, group_names, idp, pid, prn_type, wid

exit 0
----- claims.py with the API client's api-token (recorded on VCF 9.1.0, 2026-09-16)
FATAL: the broker exchange failed: HTTPError: HTTP Error 500: Internal Server Error
       a deleted or rotated api-token answers HTTP 500 here, not 401: check the token still exists, then its expiry, before the service

exit 2
----- claims.py with JWT_ENV=SERVICE_JWT (a service JWT)
decoded: the JWT in $SERVICE_JWT (1132 characters; value never printed)
header:   alg=RS256  typ=JWT  kid=present
issuer:   vcf_ops-<id>
audience: None
sub:      <id>
prn:      <user>@<domain>
principal: a PERSON (eml, user_id, prn is user@realm): this bearer carries that person's rights, and a pipeline holding it dies with their account
issued:   <utc timestamp>
expires:  <utc timestamp>  (lifetime 35 min 0 s: the minutes clock; the api-token behind it is on the months clock)
other claims present: acct, auth_time, authorization_details, prn_type

exit 0
```

The three runs were also recorded before claims.py decided the principal by the broker's `prn_type`. Run today,
`prn_type` prints with the principal claims and the principal line names the claim that decided it: for a person's
api-token the broker states `USER` (read on the reference estate), and for an API client's `SERVICE`, whose `prn` also
has the form `<id>@CUSTOMER`, so the `@` in a `prn` no longer decides anything. A JWT whose claims carry neither
`prn_type` nor a person's claim is not read as a machine. These lines are the shape the code prints, held by its tests:

```text
principal: a CLIENT (prn_type SERVICE): a machine identity, the shape automation should hold

principal: not determined (no prn_type claim and no person's claim; a claim that is absent names no machine)
NOT DETERMINED: the claims do not say whether a person or a machine holds this bearer (exit 3)

principal: not determined (no prn_type claim, and preferred_username holds a name of the form service-account-<name>, the name VCF Automation gives a service account's user, so the claims do not tell that machine from a person)
NOT DETERMINED: the claims do not say whether a person or a machine holds this bearer (exit 3)
```

The last pair is a VCF Automation bearer (it carries no `prn_type`) whose user name is a service account's: VCF
Automation names that user `service-account-<name>`, as its session read on the reference estate, so the name alone
does not say a person holds it.

## catalog_check.py

The example catalog, read with a fixed date so the run is reproducible. One entry falls due inside the 30-day window,
which is a warning, so the exit is 1.

```text
$ python3 catalog_check.py credentials.example.json --today 2026-10-13
catalog_check.py: 3 credential(s) in credentials.example.json, read on 2026-10-13, warning window 30 days

  ok    gitops-reconciler        owner platform-team    due 2027-08-01
  warn  ci-inventory-read        owner ci-team          due 2026-10-18
        due 2026-10-18, inside the 30-day window
  ok    directory-bind           owner identity-team    due 2027-03-23

exit 1
```

With `--census` on a census record that did not read. The record is a synthetic one, made for the transcript in the
shape `census.py` writes when its credential is refused the fleet identity plane: every fleet call answered 403, its
API client list is empty, and it exited 3. The join refuses it before printing any entry, so its empty list is never
read as an estate with no API client.

```text
$ FINGERPRINT_KEY_FILE=~/.vcf/fingerprint.key python3 catalog_check.py credentials.example.json --census census-refused.json --today 2026-10-13
NOT READ: census-refused.json is not a read of the API clients: the census exited 3, not 0: a read failed, so its counts are not the estate's. Nothing is joined (exit 3)
```

Each check stands on its own, whatever exit the record states. A record written as exit 0 over a fleet call that
answered 200 without its list (the call `census.py` marks `shape`) is refused for that call, and a record whose read
passes every check but lists no API client is joined as zero. Both are synthetic records, and these lines are the
shape the code prints, held by its tests:

```text
$ FINGERPRINT_KEY_FILE=~/.vcf/fingerprint.key python3 catalog_check.py credentials.example.json --census census-shape-exit0.json --today 2026-10-13
NOT READ: census-shape-exit0.json is not a read of the API clients: 1 of its fleet identity call(s) answered without the list the read needs (no apiClients list in the answer), so an empty list there is an unread one. Nothing is joined (exit 3)

$ FINGERPRINT_KEY_FILE=~/.vcf/fingerprint.key python3 catalog_check.py credentials.example.json --census census-zero.json --today 2026-10-13
...
API clients in the census of 2026-10-13T07:41:40Z: 0, so none is joined to the catalog: the census read the API client and token lists of its 1 realm(s) to the totals they state, with no call refused or answered without its list, and those lists hold no API client

exit 1
```

The second run exits 1 for the example catalog's own warning, not for the census.

A record is a read only when it says its lists were read whole. `census.py` records on each page of a paged list the
total the answer stated and the distinct entries read (`listed`); the join refuses a record whose last page of a
realm's API client or token list does not carry them, or carries fewer read than stated. A record an earlier
`census.py` wrote carries none, so run `census.py` again; the reference estate's committed record (2026-10-15) carries
them and no fingerprints, so the join refuses it as a usage error until you run the census with your own key. A joined client is
judged on its tokens' state and end date too: `EXPIRED`, `REVOKED` or an end date past is a failure, and a state or end
date the record does not carry is not judged (exit 3). These lines are the shape the code prints, held by its tests:

```text
$ FINGERPRINT_KEY_FILE=~/.vcf/fingerprint.key python3 catalog_check.py credentials.example.json --census census-before-totals.json --today 2026-10-13
NOT READ: census-before-totals.json is not a read of the API clients: its API client list of realm {{id-6}} does not state that it was read whole (no `listed` total on its last page; an earlier census.py did not record it), so a short read would pass as the whole list: run census.py again. Nothing is joined (exit 3)

$ FINGERPRINT_KEY_FILE=~/.vcf/fingerprint.key python3 catalog_check.py credentials.example.json --census census-unread-token.json --today 2026-10-13
...
  unread {{name-7}}               catalog ci-inventory-read    roles vcf_viewer
        token {{name-9}}: its end date was not read, so neither its runway nor its rotation can be judged

NOT READ: a token's state or end date was not in the census record, so that client is not judged (exit 3)

exit 3
```

## A replayed run

The two commands under "Try it without an estate" in the README, run from this folder on the sets beside the scripts:
the X-126 estate, every name a placeholder, read from recorded answers with nothing sent. The first line of each is
written to standard error. Each exits 0, as the recorded run did, and the doors rows are the ones X-126 read.

```text
$ python3 claims.py --replay replay/claims
replay: 1 recorded answers from replay/claims; nothing is sent and no credential is read
decoded: the bearer exchanged from your api-token at the broker (1487 characters; value never printed)
header:   alg=none  typ=JWT  kid=absent
issuer:   https://broker.example.test/acs/t/CUSTOMER/
audience: https://broker.example.test/auth/t/CUSTOMER/oauthtoken
sub:      00000000-0000-4000-8000-000000000006
prn:      name-1@CUSTOMER
prn_type: USER
azp:      client-1
cid:      client-1
principal: a PERSON (prn_type USER, eml, user_id): this bearer carries that person's rights, and a pipeline holding it dies with their account
scp:      openid profile user email group
issued:   2026-10-15T21:12:04Z
expires:  2026-10-15T22:12:04Z  (lifetime 60 min 0 s: the minutes clock; the api-token behind it is on the months clock)
other claims present: acct, auth_time, authorization_details, ctx, domain, group_ids, group_names, idp, pid, wid

exit 0
```

```text
$ python3 doors.py --replay replay/doors
replay: 14 recorded answers from replay/doors; nothing is sent and no credential is read
doors.py: one harmless read per pair; tokens minted per run and never printed

broker bearer minted from the api-token

  VCF Operations                     broker bearer               200  accepted  MATCH
  NSX                                broker bearer               200  accepted  MATCH
  Real-Time Metrics                  broker bearer               401  refused   MATCH                      the fleet plane refuses the broker's bearer
  Real-Time Metrics                  service JWT (VCF_VODAP)     200  accepted  MATCH
  Fleet lifecycle, components        service JWT (VCF_FLEET_LCM)  200  accepted  MATCH
  Fleet lifecycle, components        the metrics service's JWT   401  refused   MATCH                      minted per service, so another service's is refused here
  Fleet lifecycle, health probe      the metrics service's JWT   200  accepted                             the health probe answers any service's JWT
  Real-Time Metrics                  the fleet service's JWT     200  accepted  MATCH                      accepted here, while Fleet lifecycle refuses another service's
  Log management                     service JWT (VCF_OPS_LI)    200  accepted  MATCH                      sent as X-JWT-Token

  VCF Automation, tenant OAuth grant   skipped: VCFA_HOST, VCFA_ORG, VCFA_REFRESH_TOKEN_FILE not all set

  VCF Automation, Basic session login   skipped: VCFA_HOST, VCFA_USER, VCFA_PASSWORD_FILE not all set

  VCF Automation, provider api-token    skipped: VCFA_HOST, VCFA_PROVIDER_REFRESH_TOKEN_FILE not both set

  vCenter                              skipped: VC_HOST, VC_USER, VC_PASSWORD_FILE not all set

  SDDC Manager                         skipped: SDDC_HOST, SDDC_USER, SDDC_PASSWORD_FILE not all set

9 pairs read; 0 differ from the chapter; 0 without an answer

exit 0
```
