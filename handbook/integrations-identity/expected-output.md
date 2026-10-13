# What a run looks like

The reference estate, 2026-10-13 (UTC): three vCenters on 9.1.1 joined to VCF single sign-on, whose broker's identity
provider is Active Directory over LDAP. Every run on the estate used `--redact`, so the names are placeholders, and each
record path is shown as the script's default file name. The API client in them was a throwaway, made by
`api_client.py` for these runs and removed at the end. The plan and the refusal in section 1 send nothing, and were run
with a stand-in host.

## 1. `api_client.py`: the plan, then the client made

With no `--execute` it prints every call and body and sends nothing. Exit 0.

```
$ python3 api_client.py --client-id backup-01 --role vcf_viewer --api-token-ttl 43200 --access-token-ttl 60
Create plan for API client backup-01 on operations.example.net:
  POST   /api/fleet-management/iam/ssorealms/{realm}/api-clients
         {"clientDescription": "an integration's own identity", "clientId": "backup-01", "clientName": "backup-01"}
  PUT    /api/fleet-management/iam/ssorealms/{realm}/principals/{client uuid}/roles
         {"vcfRoleAssignments": [{"roleName": "vcf_viewer", "roleScope": {"resources": [], "scopeType": "SSO_REALM"}}]}
  POST   /api/fleet-management/iam/ssorealms/{realm}/api-tokens
         {"accessTokenTtl": 60, "apiClientId": "backup-01", "apiTokenTtl": 43200, "tokenName": "backup-01-token", "tokenType": "API_CLIENT"}
  then: the token to <--token-file> (mode 0600, never printed), traded at the broker once, and the client and its token read back

plan only: nothing was sent (--execute sends it)
```

A lifetime outside the broker's bounds is refused before anything is sent. Exit 2.

```
$ python3 api_client.py --client-id backup-01 --role vcf_viewer --api-token-ttl 100 --access-token-ttl 60
--api-token-ttl 100 is outside the broker's bounds of 1440 to 259200 minutes
```

The create on the reference estate, with the shortest API token lifetime the broker takes. Exit 0.

```
$ python3 api_client.py --client-id <id> --role vcf_viewer --api-token-ttl 1440 --access-token-ttl 60 \
    --description <a throwaway> --token-file <path> --execute --redact
create: API client {{client-1}}
  GET    /ssorealms: HTTP 200
  POST   /ssorealms/{realm}/api-clients/query: HTTP 200
  POST   /ssorealms/{realm}/api-clients: HTTP 201
  PUT    /ssorealms/{realm}/principals/{client uuid}/roles: HTTP 200
  POST   /ssorealms/{realm}/api-tokens: HTTP 201
  POST   /ssorealms/{realm}/api-clients/query: HTTP 200
  POST   /ssorealms/{realm}/api-tokens/query: HTTP 200
  the token traded at the broker: HTTP 200, a SERVICE bearer living 60.0 min
  read back: client present True, roles vcf_viewer at SSO_REALM scope; tokens ACTIVE API 1440 min, access 60 min
exit 0

api_client.json written with every estate value replaced
```

- **The query comes before the create.** A client with the id you gave is refused, never adopted.
- **The token proves itself once.** The broker traded it for a bearer whose principal type is `SERVICE` and which lived
  60 minutes, the access lifetime asked for. The token is in the file you named, mode 0600; it is in neither the
  transcript nor the record.
- **The read-back is the result.** The client, its one role at realm scope, and an active token with both lifetimes as
  asked. Exit 0 means all of it held.

## 2. `vcenter_exchange.py --sessions` as that client, holding `vcf_viewer`

`VC_USER` unset, so the census read the session lists as the client's own session. Exit 1.

```
$ python3 vcenter_exchange.py --sessions --redact
Census read as the API client's own session
vCenter {{host-1}}
  the bearer as presented: HTTP 401
  exchange: HTTP 200, urn:ietf:params:oauth:token-type:saml2, Bearer, lives 298 s
  REST session (SIGN): HTTP 201, user CUSTOMER\{{client-1}}, VM list HTTP 200
  SOAP session (LoginByToken): user CUSTOMER\{{client-1}}
  sessions not read: the session list held only this census's own session: this identity cannot read the others
vCenter {{host-2}}
  the bearer as presented: HTTP 401
  exchange: HTTP 200, urn:ietf:params:oauth:token-type:saml2, Bearer, lives 299 s
  REST session (SIGN): HTTP 201, user CUSTOMER\{{client-1}}, VM list HTTP 200
  SOAP session (LoginByToken): user CUSTOMER\{{client-1}}
  sessions not read: the session list held only this census's own session: this identity cannot read the others
vCenter {{host-3}}
  the bearer as presented: HTTP 401
  exchange: HTTP 200, urn:ietf:params:oauth:token-type:saml2, Bearer, lives 299 s
  REST session (SIGN): HTTP 201, user CUSTOMER\{{client-1}}, VM list HTTP 200
  SOAP session (LoginByToken): user CUSTOMER\{{client-1}}
  sessions not read: the session list held only this census's own session: this identity cannot read the others
The client took both sessions on 3 of 3 vCenter(s)

exchange.json written with every estate value replaced; exit 1
```

- **A list that holds only the census's own session is a failed read.** Minutes later the same lists held 275 to 354
  sessions each; a list of one means this identity may not see the others. The census prints that the read was narrowed and exits 1, rather than
  reporting an estate with nobody signed in.

## 3. The same client rebound to `vcf_administrator`

The same throwaway client, its role changed to `vcf_administrator` at realm scope, read again. Exit 0. This is the run
in `exchange.json`.

```
$ python3 vcenter_exchange.py --sessions --redact
Census read as the API client's own session
vCenter {{host-1}}
  the bearer as presented: HTTP 401
  exchange: HTTP 200, urn:ietf:params:oauth:token-type:saml2, Bearer, lives 299 s
  REST session (SIGN): HTTP 201, user CUSTOMER\{{client-1}}, VM list HTTP 200
  SOAP session (LoginByToken): user CUSTOMER\{{client-1}}
  sessions (319, this census's own left out): local administrator 17, local, VCF integration account 256, local, other 46
    local administrator by agent: VMware vim-java 5, XML-WS Runtime git-revision#50dbfd3 2, vAPI 2, vapi-endpoint 8
vCenter {{host-2}}
  the bearer as presented: HTTP 401
  exchange: HTTP 200, urn:ietf:params:oauth:token-type:saml2, Bearer, lives 299 s
  REST session (SIGN): HTTP 201, user CUSTOMER\{{client-1}}, VM list HTTP 200
  SOAP session (LoginByToken): user CUSTOMER\{{client-1}}
  sessions (354, this census's own left out): directory 1, local administrator 8, local, VCF integration account 272, local, other 73
    local administrator by agent: VMware vim-java 1, XML-WS Runtime git-revision#50dbfd3 3, vAPI 4
    directory {{domain-1}}\{{name-1}}: vSphereUI 1
vCenter {{host-3}}
  the bearer as presented: HTTP 401
  exchange: HTTP 200, urn:ietf:params:oauth:token-type:saml2, Bearer, lives 299 s
  REST session (SIGN): HTTP 201, user CUSTOMER\{{client-1}}, VM list HTTP 200
  SOAP session (LoginByToken): user CUSTOMER\{{client-1}}
  sessions (275, this census's own left out): local, VCF integration account 150, local, other 125
The client took both sessions on 3 of 3 vCenter(s)
Directory accounts signing in from a vSphere SDK: 0

exchange.json written with every estate value replaced; exit 0
```

- **The bearer as presented is refused, and that is expected.** Every vCenter answered the broker's bearer with HTTP 401.
  vCenter takes the client only after its own exchange; NSX takes the same bearer as it is.
- **The exchange answers a SAML token that lives minutes.** `urn:ietf:params:oauth:token-type:saml2`, of the Bearer type,
  about 299 seconds. Make the exchange just before the session, not ahead of time.
- **Both sessions are the client itself.** The REST session (the assertion in a `SIGN` header) and the SOAP session
  (`LoginByToken`) both read `CUSTOMER\{{client-1}}`: the realm's domain and the client's id. That is how a machine identity
  shows in a session census.
- **The role decided what the census could see.** Holding `vcf_viewer` the client saw only itself; holding
  `vcf_administrator` it read every list. A role between the two was not tried.
- **Most sessions are VCF's own.** VCF's integration accounts (local, named `svc-`) and other local accounts (solution
  users, Supervisor accounts) held nearly all of them. Leave those; VCF runs them.
- **The local administrator is in automated use on the two management vCenters.** Its sessions came from `VMware vim-java`,
  `XML-WS Runtime`, `vAPI` and `vapi-endpoint` agents: programs, not a person at a console. An account in automated use is
  not a break-glass account; find the client behind each before you vault it.
- **One directory account was signed in, from `vSphereUI`, not from a vSphere SDK.** Sessions show what is signed in at
  that moment; a nightly or weekly job is absent between runs. Read on several days before you conclude no integration
  signs in on a directory password.

## 4. The census with no API client

`VC_USER` set to a directory account and no API client credential: the census alone, as that account. Exit 0. The counts
differ from run 3 by a few sessions, read minutes apart.

```
$ python3 vcenter_exchange.py --sessions --redact
Census read as VC_USER, an account with a password
vCenter {{host-1}}
  sessions (317, this census's own left out): local administrator 17, local, VCF integration account 254, local, other 46
    local administrator by agent: VMware vim-java 5, XML-WS Runtime git-revision#50dbfd3 2, vAPI 2, vapi-endpoint 8
vCenter {{host-2}}
  sessions (353, this census's own left out): directory 1, local administrator 8, local, VCF integration account 271, local, other 73
    local administrator by agent: VMware vim-java 1, XML-WS Runtime git-revision#50dbfd3 3, vAPI 4
    directory {{domain-1}}\{{name-3}}: vSphereUI 1
vCenter {{host-3}}
  sessions (276, this census's own left out): local, VCF integration account 151, local, other 125
Directory accounts signing in from a vSphere SDK: 0

exchange.json written with every estate value replaced; exit 0
```

## 5. `api_client.py --teardown --execute`

The throwaway removed. Exit 0.

```
$ python3 api_client.py --client-id <id> --teardown --execute --redact
teardown: API client {{client-1}}
  GET    /ssorealms: HTTP 200
  POST   /ssorealms/{realm}/api-tokens/query: HTTP 200
  POST   /ssorealms/{realm}/api-clients/query: HTTP 200
  DELETE /ssorealms/{realm}/api-tokens/{token id}: HTTP 204
  DELETE /ssorealms/{realm}/api-clients/{client id}: HTTP 204
  POST   /ssorealms/{realm}/api-clients/query: HTTP 200
  POST   /ssorealms/{realm}/api-tokens/query: HTTP 200
  residue: client present False, tokens left 0
exit 0

api_client_teardown.json written with every estate value replaced
```

- **The residue read is the result.** After the deletes, both lists were read again: no client, no token. A teardown of a
  client that is not there removes nothing and exits 0, so it is safe to run again.

## 6. `service_account.py`: the plan, then one VCF Automation service account made

The same shape as `api_client.py`, in VCF Automation: a throwaway account in a throwaway All Apps organization,
2026-10-13, VCF Automation 9.1.1, run with a provider bearer (the third run, 07:04Z).

```text
Create plan for service account {{client-1}} in organization {{org-1}} on {{host-1}}:
  GET    /cloudapi/1.0.0/orgs?filter=name=={org}
  GET    /cloudapi/1.0.0/serviceAccounts?filter=name=={name}  (in the organization: refused if present)
  POST   /oauth/tenant/{org}/register
         {"client_name": "{{client-1}}", "scope": "urn:vcloud:role:Organization%20User", "software_id": "<a new UUID>", "software_version": "1.0"}
  POST   /oauth/tenant/{org}/device_authorization
         {"client_id": "<from the register>"}
  POST   /cloudapi/1.0.0/deviceLookup/grant  (in the organization)
         {"userCode": "<from the device authorization>"}
  POST   /oauth/tenant/{org}/token  (polled until the grant lands)
         {"client_id": "<from the register>", "device_code": "<from the device authorization>", "grant_type": "urn:ietf:params:oauth:grant-type:device_code"}
  then: the refresh token to <--token-file> (mode 0600, never printed), the bearer's session read for its principal and roles, one refresh with the stored token, and the account read back

plan only: nothing was sent (--execute sends it)
```

```text
create: service account {{client-1}} in organization {{org-1}}
  GET    /cloudapi/1.0.0/orgs?filter=name=={org}: HTTP 200
  GET    /cloudapi/1.0.0/serviceAccounts?filter=name=={name}: HTTP 200
  POST   /oauth/tenant/{org}/register: HTTP 200
  GET    /cloudapi/1.0.0/serviceAccounts?filter=name=={name}: HTTP 200
  POST   /oauth/tenant/{org}/device_authorization: HTTP 200
  POST   /cloudapi/1.0.0/deviceLookup/grant: HTTP 204
  POST   /oauth/tenant/{org}/token  (device-code grant): HTTP 200
  GET    /cloudapi/1.0.0/sessions/current  (as the account): HTTP 200
  POST   /oauth/tenant/{org}/token  (refresh grant, with client_id): HTTP 200
  GET    /cloudapi/1.0.0/serviceAccounts?filter=name=={name}: HTTP 200
  device-code grant: HTTP 200, refresh token issued, bearer for 3600 s
  the bearer's session: HTTP 200, principal service-account-{{client-1}}, roles Organization User
  refresh with the stored token (with client_id): HTTP 200, bearer issued, a new refresh token, written over the stored one
  read back: present True, status ACTIVE, roles Organization User, rotation required on every refresh True
exit 0

service_account.json written with every estate value replaced
```

- **The bearer's session is the proof.** It names `service-account-` and the account's name, and holds exactly the role
  the scope named; the account read back `ACTIVE`.
- **Each refresh replaced the refresh token.** The account reads back with rotation required on every refresh, and the
  one refresh returned a new refresh token, which the script wrote over the stored one. Keep the file the script
  writes; it is the token the next run presents.

## 7. `service_account.py --teardown --token-file ... --execute`

```text
teardown: service account {{client-1}} in organization {{org-1}}
  GET    /cloudapi/1.0.0/orgs?filter=name=={org}: HTTP 200
  GET    /cloudapi/1.0.0/serviceAccounts?filter=name=={name}: HTTP 200
  POST   /cloudapi/1.0.0/serviceAccounts/{id}/revoke: HTTP 204
  POST   /oauth/tenant/{org}/token  (refresh grant, with client_id): HTTP 400
  POST   /oauth/tenant/{org}/token  (refresh grant, without client_id): HTTP 400
  DELETE /cloudapi/1.0.0/serviceAccounts/{id}: HTTP 202
  GET    /cloudapi/1.0.0/serviceAccounts?filter=name=={name}: HTTP 200
  GET    /cloudapi/1.0.0/serviceAccounts?filter=name=={name}: HTTP 200
  POST   /oauth/tenant/{org}/token  (refresh grant, with client_id): HTTP 400
  POST   /oauth/tenant/{org}/token  (refresh grant, without client_id): HTTP 400
  residue: account present False
  refresh with the revoked token, after revoke (with client_id): HTTP 400, bearer refused (invalid_request)
  refresh with the revoked token, after revoke (without client_id): HTTP 400, bearer refused (invalid_grant)
  refresh with the revoked token, after delete (with client_id): HTTP 400, bearer refused (invalid_request)
  refresh with the revoked token, after delete (without client_id): HTTP 400, bearer refused (invalid_grant)
exit 0

service_account_teardown.json written with every estate value replaced
```

- **The revoke alone refuses the account's refresh.** Right after the revoke, before the delete, the stored token's
  refresh answered HTTP 400 with the client id (`invalid_request`) and without it (`invalid_grant`); after the delete it
  answered the same, and the list held no account. Whether the revoke voids the client or the token is not separated,
  and a replaced token was not tried after the revoke.
