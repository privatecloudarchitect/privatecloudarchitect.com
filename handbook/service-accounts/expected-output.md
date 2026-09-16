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

## claims.py

Three runs: the operator's own api-token (a person), an API client's stored api-token (dead: the broker answers
500, the expiry trap in action), and a service JWT decoded through JWT_ENV (it names the person who minted the
Operations session it was exchanged from).

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
----- claims.py with the API client's api-token
FATAL: the broker exchange failed: HTTPError: HTTP Error 500: Internal Server Error
       an EXPIRED api-token answers HTTP 500 here, not 401: check its expiry before the service

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
