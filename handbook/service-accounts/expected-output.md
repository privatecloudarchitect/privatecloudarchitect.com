# Expected output

Transcripts from one VCF 9.1.0 instance with Real-Time Metrics deployed, 2026-09-16, host names and identifiers
replaced. Your rows will differ where your surfaces differ; the shape is what to expect.

## doors.py

Every surface configured; the provider api-token path skipped because no provider refresh token was supplied.
The one DIFFERS row is a finding, not a fault: it corrected the Platform identity chapter the same day (the
audience check on the fleet plane is per service, and the metrics service's metadata read does not make it).

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
$ FINGERPRINT_KEY_FILE=key python3 catalog_check.py credentials.example.json --census census-refused.json --today 2026-10-13
NOT READ: census-refused.json is not a read of the API clients: the census exited 3, not 0: a read failed, so its counts are not the estate's. Nothing is joined (exit 3)
```

Each check stands on its own, whatever exit the record states. A record written as exit 0 over a fleet call that
answered 200 without its list (the call `census.py` marks `shape`) is refused for that call, and a record whose read
passes every check but lists no API client is joined as zero. Both are synthetic records, and these lines are the
shape the code prints, held by its tests:

```text
$ FINGERPRINT_KEY_FILE=key python3 catalog_check.py credentials.example.json --census census-shape-exit0.json --today 2026-10-13
NOT READ: census-shape-exit0.json is not a read of the API clients: 1 of its fleet identity call(s) answered without the list the read needs (no apiClients list in the answer), so an empty list there is an unread one. Nothing is joined (exit 3)

$ FINGERPRINT_KEY_FILE=key python3 catalog_check.py credentials.example.json --census census-zero.json --today 2026-10-13
...
API clients in the census of 2026-10-13T07:41:40Z: 0, so none is joined to the catalog: the census queried the API client and token lists of its 1 realm(s), with no call refused or answered without its list, and those lists hold no API client

exit 1
```

The second run exits 1 for the example catalog's own warning, not for the census.
