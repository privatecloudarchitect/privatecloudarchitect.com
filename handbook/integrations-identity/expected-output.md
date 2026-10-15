# What a run looks like

The reference estate, 2026-10-13 and 2026-10-15 (UTC): three vCenters on 9.1.1 joined to VCF single sign-on, whose
broker's identity provider is Active Directory over LDAP. Every run on the estate used `--redact`, so the names are
placeholders, and each record path is shown as the record's file name in this folder. The API clients in them were
throwaways, made by `api_client.py` for these runs and removed at the end: sections 1, 1a and 5 are one run of
2026-10-15 at 06:36, section 3 a run of 2026-10-13 at 07:45, section 4 a read two minutes after it, section 2 an
earlier client at 04:51, and section 3b a run of 2026-10-15 at 11:25. The plans and the refusal in sections 1 and 1a send nothing, and were run with a stand-in
host.

**The exit codes were renumbered on 2026-10-15** to the one contract every identity companion keeps: 0 nothing to act
on, 3 a read failed or is undetermined, 5 a usage error; the other codes are each script's own (the README's tables).
Each transcript below keeps the `exit` its run printed. Where today's code differs, the line above the transcript says
both: the session censuses of 2026-10-13 printed 1 for a failed read (3 now) and 3 for a directory account off the
vSphere Client (1 now), and a refusal before anything is sent for a bad argument was 2 (5 now).

## 1. `api_client.py`: the plan, then the client made

With no `--execute` it prints every call and body and sends nothing. Exit 0.

```
$ python3 api_client.py --client-id backup-01 --role vcf_viewer --api-token-ttl 43200 --access-token-ttl 60
Create plan for API client backup-01 on operations.example.net:
  in the fleet's only realm (refused, exit 5, if it holds more than one: name it with --realm)
  POST   /api/fleet-management/iam/ssorealms/{realm}/api-clients
         {"clientDescription": "an integration's own identity", "clientId": "backup-01", "clientName": "backup-01"}
  PUT    /api/fleet-management/iam/ssorealms/{realm}/principals/{client uuid}/roles
         {"vcfRoleAssignments": [{"roleName": "vcf_viewer", "roleScope": {"resources": [], "scopeType": "SSO_REALM"}}]}
  POST   /api/fleet-management/iam/ssorealms/{realm}/api-tokens
         {"accessTokenTtl": 60, "apiClientId": "backup-01", "apiTokenTtl": 43200, "tokenName": "backup-01-token", "tokenType": "API_CLIENT"}
  then: the token to <--token-file> (mode 0600, never printed), traded at the broker once, and the client and its token read back

plan only: nothing was sent (--execute sends it)
```

A lifetime outside the broker's bounds is refused before anything is sent: a usage error, exit 5 (2 before
2026-10-15).

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
  POST   /ssorealms/{realm}/api-tokens/query: HTTP 200
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
- **A state file records what the script made.** The create wrote `api_client.<client id>.state.json` (mode 0600: the
  client's id and uuid and the ids of the tokens it issued). Every later write reads it and refuses a client it does not
  record; keep it beside the record and do not publish it.

## 1a. `api_client.py --rotate`, then `--retire-old`: a new token beside the old, then the old one refused

A rotation is two runs, and the integration moves between them. The plans first, then both runs on the same throwaway
client, with other lifetimes for the new token so the read-back shows which token is which. Exit 0 each.

```
$ python3 api_client.py --client-id backup-01 --rotate --api-token-ttl 2880 --access-token-ttl 60
Rotation plan for API client backup-01 on operations.example.net:
  in the fleet's only realm (refused, exit 5, if it holds more than one: name it with --realm)
  POST   /api/fleet-management/iam/ssorealms/{realm}/api-clients/query and api-tokens/query, ?page=N&pageSize=50 to the stated total: the client and the tokens it holds
  POST   /api/fleet-management/iam/ssorealms/{realm}/api-tokens
         {"accessTokenTtl": 60, "apiClientId": "backup-01", "apiTokenTtl": 2880, "tokenName": "backup-01-token-<UTC stamp>", "tokenType": "API_CLIENT"}
  POST   /acs/t/{broker tenant}/token at the broker  (the new token, once; with --old-token-file the old one too)
  POST   /api/fleet-management/iam/ssorealms/{realm}/api-tokens/query, every page; read back: the new token active beside the old
  then: the new token to <--token-file> (mode 0600, never printed); nothing is deleted: point the integration at the new token, run one job, then --retire-old

plan only: nothing was sent (--execute sends it)
```

```
$ python3 api_client.py --client-id <id> --rotate --api-token-ttl 2880 --access-token-ttl 60 \
    --token-file <new path> --old-token-file <path> --execute --redact
rotate: API client {{client-1}}
  GET    /ssorealms: HTTP 200
  POST   /ssorealms/{realm}/api-clients/query: HTTP 200
  POST   /ssorealms/{realm}/api-tokens/query: HTTP 200
  POST   /ssorealms/{realm}/api-tokens: HTTP 201
  POST   /ssorealms/{realm}/api-tokens/query: HTTP 200
  POST   /ssorealms/{realm}/api-clients/query: HTTP 200
  POST   /ssorealms/{realm}/api-tokens/query: HTTP 200
  the new token traded at the broker: HTTP 200, a SERVICE bearer living 60.0 min
  signed in as: a person's token
  in the overlap: 1 token(s) held before, 2 active with the new one
  the old token at the broker, in the overlap, the old ones kept: HTTP 200, traded
  read back: client present True, roles vcf_viewer at SSO_REALM scope; tokens ACTIVE API 1440 min, access 60 min; ACTIVE API 2880 min, access 60 min
  next: point the integration at the new token, run one job, then --retire-old
exit 0

api_client_overlap.json written with every estate value replaced
```

```
$ python3 api_client.py --client-id backup-01 --retire-old --old-token-file <path>
Retirement plan for API client backup-01 on operations.example.net:
  in the fleet's only realm (refused, exit 5, if it holds more than one: name it with --realm)
  POST   /api/fleet-management/iam/ssorealms/{realm}/api-clients/query and api-tokens/query, ?page=N&pageSize=50 to the stated total: the client and the tokens it holds
  POST   /acs/t/{broker tenant}/token at the broker  (with --old-token-file: the old token, before the delete)
  DELETE /api/fleet-management/iam/ssorealms/{realm}/api-tokens/{token id}  (each token older than the newest)
  POST   /acs/t/{broker tenant}/token at the broker  (with --old-token-file: the old token again, expected refused)
  POST   /api/fleet-management/iam/ssorealms/{realm}/api-tokens/query, every page; read back: one token left
  only for a client the state file records, and never on the client's own token; refused while it holds one token, or when its newest is not the one this script issued last

plan only: nothing was sent (--execute sends it)
```

```
$ python3 api_client.py --client-id <id> --retire-old --old-token-file <path> --execute --redact
retire-old: API client {{client-1}}
  GET    /ssorealms: HTTP 200
  POST   /ssorealms/{realm}/api-clients/query: HTTP 200
  POST   /ssorealms/{realm}/api-tokens/query: HTTP 200
  DELETE /ssorealms/{realm}/api-tokens/{token id}: HTTP 204
  POST   /ssorealms/{realm}/api-clients/query: HTTP 200
  POST   /ssorealms/{realm}/api-tokens/query: HTTP 200
  signed in as: a person's token
  held before: 2 token(s); deleted 1, every one older than the newest
  the old token at the broker, before the delete: HTTP 200, traded
  the old token at the broker, after the delete: HTTP 400, refused
  read back: client present True, roles vcf_viewer at SSO_REALM scope; tokens ACTIVE API 2880 min, access 60 min
exit 0

api_client_retire.json written with every estate value replaced
```

- **A rotation deletes nothing.** Once the new token was issued and proved, the client held two active tokens, and the
  old one still traded at the broker (HTTP 200): that overlap is the window in which the integration switches to the new
  file and runs one job on it.
- **The retirement removes what is older than the newest.** `--retire-old` deleted the one older token; the broker
  traded it before the delete and answered it with HTTP 400 after, and one token was left, with the new lifetimes. The
  old token's file can then be removed.
- **What it refuses, before any delete.** On the same client, `--retire-old` with no state file recording the client
  exited 2 with `refused: this script did not make this client`, and a second `--retire-old`, with one token left, exited
  2 with `refused: the client holds one token`. Run on a client's own token, every write after the create refuses too
  (`--rotate` included, since 2026-10-15, held by the companion's tests): a second throwaway client, holding VCF
  Administrator, was refused its teardown that way, with no call that deletes.
- **Regenerating a token in place gives no overlap.** The fleet API also regenerates a token's value
  (`POST /ssorealms/{realm}/api-tokens/{token id}/regenerate`). In a run of 2026-10-13, called outside the script, the answer
  was a token under a new id with a new end date and a new value; the value from before answered HTTP 400 at the broker
  three seconds later, and the new one HTTP 200. An integration reading the old value fails from that moment, so rotate with
  `--rotate` and its overlap, not by regenerating.

## 1b. `api_client.py --scope instance`: the role at one VCF instance

The same estate, 2026-10-13, throwaway clients each made and removed. The fleet refused `vcf_viewer` at an instance's scope on a first
attempt, and the record keeps its reason:

```text
  PUT    /ssorealms/{realm}/principals/{client uuid}/roles: HTTP 400 (Invalid role scope for the given role:vcf_viewer)
```

`sddc_viewer` bundles only an instance's components (vCenter ReadOnly, NSX auditor), and the fleet took it:

```text
create: API client {{client-1}}
  GET    /ssorealms: HTTP 200
  POST   /ssorealms/{realm}/api-clients/query: HTTP 200
  GET    /ssorealms/{realm}: HTTP 200
  POST   /ssorealms/{realm}/api-clients: HTTP 201
  PUT    /ssorealms/{realm}/principals/{client uuid}/roles: HTTP 200
  POST   /ssorealms/{realm}/api-tokens: HTTP 201
  POST   /ssorealms/{realm}/api-clients/query: HTTP 200
  POST   /ssorealms/{realm}/api-tokens/query: HTTP 200
  the token traded at the broker: HTTP 200, a SERVICE bearer living 30.0 min
  read back: client present True, roles sddc_viewer at VCF_INSTANCE scope ({{instance-1}}); tokens ACTIVE API 1440 min, access 30 min
exit 0

api_client_instance.json written with every estate value replaced
```

- **The binding reads back at the instance.** One role, `VCF_INSTANCE`, one instance named.
- **It reaches that instance's vCenters and no other.** Taken through each vCenter's exchange, the client opened a REST
  session that saw 56 and 36 VMs on the instance's 2 vCenters, and
  signed in over SOAP on each. On the vCenter outside the instance a REST session still opened but saw
  0 VMs, and the SOAP sign-in was refused ("Permission to perform this operation was denied."). So a
  REST session that opens is not a reach: read what it sees.
- Torn down after, with no client or token left.

## 1c. Your own token, and every list read to its end

`api_client.py` runs on your own VCF Operations API token, never an integration's: the token of an API client of your own
holding VCF Administrator, made in the console (**Manage ▸ Fleet Management ▸ Identity & Access ▸ VCF SSO Overview**, the
broker that holds your realm, **API Access ▸ API Clients ▸ Create**, then against that client **⋮ ▸ Generate API
Token**), in a file of mode 0600 outside this clone, named in `OPS_API_TOKEN_FILE`. The reference estate, 2026-10-15:

- **The fleet's token call names a client.** Asked for a person's own token, `tokenType` `USER` with no `apiClientId`,
  by that person, it answered HTTP 400 with `apiClientId` "must not be blank", and made nothing.
- **An administrator client's token carries the writes.** A client made for the run, holding `vcf_administrator`, its
  token set to 1,440 and 30 minutes, traded for a bearer that lived 30 minutes. On that token the script made another
  throwaway client and removed it, below; then the administrator client was removed on the token that made it. No
  client and no token was left.
- **Every list is read whole.** The calls name their page. The fleet's default page is 50, and asked for 500 it
  answered with 50; a page of one at a time read the same clients and tokens as one page. A list counts as read only
  when its items, counted once each by id, reach the total the answer states; otherwise the run exits 3 and writes
  nothing on it.

The create and the teardown on the administrator client's token, `--redact`, as the script printed them:

```
create: API client {{client-1}}
  GET    /ssorealms: HTTP 200
  POST   /ssorealms/{realm}/api-clients/query?page=0&pageSize=50: HTTP 200
  POST   /ssorealms/{realm}/api-clients: HTTP 201
  PUT    /ssorealms/{realm}/principals/{client uuid}/roles: HTTP 200
  POST   /ssorealms/{realm}/api-tokens: HTTP 201
  POST   /ssorealms/{realm}/api-tokens/query?page=0&pageSize=50: HTTP 200
  POST   /ssorealms/{realm}/api-clients/query?page=0&pageSize=50: HTTP 200
  POST   /ssorealms/{realm}/api-tokens/query?page=0&pageSize=50: HTTP 200
  the token traded at the broker: HTTP 200, a SERVICE bearer living 30.0 min
  read back: client present True, roles vcf_viewer at SSO_REALM scope; tokens ACTIVE API 1440 min, access 30 min
exit 0
```

```
teardown: API client {{client-1}}
  GET    /ssorealms: HTTP 200
  POST   /ssorealms/{realm}/api-tokens/query?page=0&pageSize=50: HTTP 200
  POST   /ssorealms/{realm}/api-clients/query?page=0&pageSize=50: HTTP 200
  DELETE /ssorealms/{realm}/api-tokens/{token id}: HTTP 204
  DELETE /ssorealms/{realm}/api-clients/{client id}: HTTP 204
  POST   /ssorealms/{realm}/api-clients/query?page=0&pageSize=50: HTTP 200
  POST   /ssorealms/{realm}/api-tokens/query?page=0&pageSize=50: HTTP 200
  signed in as: another API client
  residue: client present False, tokens left 0
exit 0
```

- **Signed in as another API client.** The run was on the administrator client's token, not the client it removed, so
  the teardown went ahead. Run on the removed client's own token, it is refused before any delete (section 5).
- **The transcripts above it predate the paging,** and show each query's path without its page. They also predate the
  realm line: a run on a fleet of more than one realm names, on its first line, the realm `--realm` chose.

## 2. `vcenter_exchange.py --sessions` as a client, holding `vcf_viewer`

An earlier throwaway client (X-142, 04:51), `VC_USER` unset, so the census read the session lists as the client's own
session. It printed exit 1, the failed read's code then; the same read exits 3 now.

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
  sessions each; a list of one means this identity may not see the others. The census prints that the read was narrowed and exits 3, a
  read that failed, rather than reporting an estate with nobody signed in.

## 3. That client rebound to `vcf_administrator`

Section 1a's client, its role changed to `vcf_administrator` at realm scope, as X-142 found the census needs. It
printed exit 3, then the code for a directory account off the vSphere Client; the same read exits 1 now. This is the
run in `exchange.json`.

```
$ python3 vcenter_exchange.py --sessions --redact
Census read as the API client's own session
vCenter {{host-1}}
  the bearer as presented: HTTP 401
  exchange: HTTP 200, urn:ietf:params:oauth:token-type:saml2, Bearer, lives 299 s
  REST session (SIGN): HTTP 201, user CUSTOMER\{{client-1}}, VM list HTTP 200
  SOAP session (LoginByToken): user CUSTOMER\{{client-1}}
  sessions (319, this census's own left out): directory 1, local administrator 15, local, VCF integration account 256, local, other 47
    local administrator by agent: VMware vim-java 5, XML-WS Runtime git-revision#50dbfd3 2, vapi-endpoint 8
    directory {{domain-1}}\{{name-1}}: vapi-endpoint 1  SIGNS IN FROM A CLIENT THAT IS NOT INTERACTIVE
vCenter {{host-2}}
  the bearer as presented: HTTP 401
  exchange: HTTP 200, urn:ietf:params:oauth:token-type:saml2, Bearer, lives 299 s
  REST session (SIGN): HTTP 201, user CUSTOMER\{{client-1}}, VM list HTTP 200
  SOAP session (LoginByToken): user CUSTOMER\{{client-1}}
  sessions (358, this census's own left out): directory 2, local administrator 8, local, VCF integration account 274, local, other 74
    local administrator by agent: VMware vim-java 1, XML-WS Runtime git-revision#50dbfd3 3, vAPI 4
    directory {{domain-1}}\{{name-1}}: vapi-endpoint 1  SIGNS IN FROM A CLIENT THAT IS NOT INTERACTIVE
    directory {{domain-1}}\{{name-2}}: vSphereUI 1
vCenter {{host-3}}
  the bearer as presented: HTTP 401
  exchange: HTTP 200, urn:ietf:params:oauth:token-type:saml2, Bearer, lives 299 s
  REST session (SIGN): HTTP 201, user CUSTOMER\{{client-1}}, VM list HTTP 200
  SOAP session (LoginByToken): user CUSTOMER\{{client-1}}
  sessions (280, this census's own left out): directory 3, local, VCF integration account 154, local, other 123
    directory {{domain-1}}\{{name-1}}: vapi-endpoint 3  SIGNS IN FROM A CLIENT THAT IS NOT INTERACTIVE
The client took both sessions on 3 of 3 vCenter(s)
Directory accounts signing in from a client that is not interactive: 1
WATCH: the local administrator holds 23 session(s) from clients that are not interactive: an account in automated use is not a break-glass account

exchange.json written with every estate value replaced; exit 3
```

- **The bearer as presented is refused, and that is expected.** Every vCenter answered the broker's bearer with HTTP 401.
  vCenter takes the client only after its own exchange; NSX takes the same bearer as it is.
- **The exchange answers a SAML token that lives minutes.** `urn:ietf:params:oauth:token-type:saml2`, of the Bearer type,
  about 299 seconds. Make the exchange just before the session, not ahead of time.
- **Both sessions are the client itself.** The REST session (the assertion in a `SIGN` header) and the SOAP session
  (`LoginByToken`) both read `CUSTOMER\{{client-1}}`: the broker tenant and the client's id. That is how a machine identity
  shows in a session census. The broker tenant is not the realm's name, the spelling a vCenter grant is accepted in and,
  behind an AD/LDAP provider, applies to nobody.
- **The role decided what the census could see.** Holding `vcf_viewer` the client saw only itself; holding
  `vcf_administrator` it read every list. A role between the two was not tried.
- **Most sessions are VCF's own.** VCF's integration accounts (local, named `svc-`) and other local accounts (solution
  users, Supervisor accounts) held nearly all of them. Leave those; VCF runs them.
- **The local administrator is in automated use on the two management vCenters.** Its sessions came from `VMware vim-java`,
  `XML-WS Runtime`, `vAPI` and `vapi-endpoint` agents: programs, not a person at a console. The census prints a `WATCH`
  line for it and, with nothing worse, exits 4. An account in automated use is not a break-glass account; find the client
  behind each before you vault it.
- **One directory account signs in from `vapi-endpoint` on all three vCenters, and is flagged.** It is the directory
  account the reference tooling itself signs in to vCenter with, so it is an integration on a directory password: the
  very thing this chapter moves to an identity of its own. The census exits 1 until it moves; a pair its owner confirms
  as a person's own is acknowledged with `--ack` (section 3b).
- **One directory account was at the vSphere Client, `vSphereUI`, and is not flagged.** That agent is the only one the
  census treats as a person's. Sessions show what is signed in at that moment; a nightly or weekly job is absent between
  runs, so read at intervals shorter than the shortest session a job holds, across your longest job cycle, and compare
  the records (section 3b) before you conclude no integration signs in on a directory password.

## 3a. `--sessions` without `DIRECTORY_DOMAINS`: refused before any read

Unset, no directory session would be judged, and the run would pass a census that saw nothing it was asked to see.
So it refuses to start: a usage error, exit 5 (2 before 2026-10-15), nothing read or written (run with a stand-in
host).

```
$ python3 vcenter_exchange.py --sessions --redact
--sessions needs DIRECTORY_DOMAINS, the directory domains as vCenter spells them: without them no directory session would be judged, so a census of nothing would pass
```

- **Every session placed, or a failed read.** A session in a domain that none of `DIRECTORY_DOMAINS`, `OTHER_DOMAINS`,
  `LOCAL_DOMAIN` and the broker tenant names is not placed: a misspelled directory domain, or a second directory
  nobody listed. The census prints `NOT PLACED: <n> session(s) in a domain neither DIRECTORY_DOMAINS nor OTHER_DOMAINS
  names` under that vCenter, `FAILED READ: sessions not placed on <n> vCenter(s)` at the end, and the domains on the
  terminal only (counted, under `--redact`), and exits 3; `--compare` does not count that vCenter as read. Name each
  domain in `DIRECTORY_DOMAINS`, or in `OTHER_DOMAINS` if it is another identity provider's. That path is held by the
  companion's tests; no run on the reference estate met it, because every session read there was placed.

## 3b. `--ack`, then `--compare` held to a coverage

A run of 2026-10-15 at 11:25 (X-206b) on all three vCenters, as the directory account of section 4. Before the reads it
opened one SOAP session of its own on each vCenter as that account, with the client agent `PowerCLI`: a stand-in for a
person on PowerCLI, the case `--ack` exists for. It read three times, the second time with that pair acknowledged until
the next day, compared the three records twice, and closed its stand-in sessions; read back, none was left.

```
$ OUT=b.json python3 vcenter_exchange.py --sessions --redact --ack acks.json
Census read as VC_USER, an account with a password
vCenter {{host-1}}
  sessions (317, this census's own left out): directory 1, local administrator 15, local, VCF integration account 254, local, other 47
    local administrator by agent: VMware vim-java 5, XML-WS Runtime git-revision#50dbfd3 2, vapi-endpoint 8
    directory {{domain-1}}\{{name-2}} [fingerprint d1598c27948a7c1e]: PowerCLI 1 (acknowledged until 2026-10-16)
vCenter {{host-2}}
  sessions (445, this census's own left out): directory 1, local administrator 5, local, VCF integration account 365, local, other 74
    local administrator by agent: VMware vim-java 1, XML-WS Runtime git-revision#50dbfd3 3, vAPI 1
    directory {{domain-1}}\{{name-2}} [fingerprint d1598c27948a7c1e]: PowerCLI 1 (acknowledged until 2026-10-16)
vCenter {{host-3}}
  sessions (298, this census's own left out): directory 1, local, VCF integration account 152, local, other 145
    directory {{domain-1}}\{{name-2}} [fingerprint d1598c27948a7c1e]: PowerCLI 1 (acknowledged until 2026-10-16)
Directory accounts signing in from a client that is not interactive: 0 not acknowledged
Acknowledged: 1 account(s) on a pair a person decided on; 1 acknowledgement(s), 0 matching no pair read
WATCH: the local administrator holds 20 session(s) from clients that are not interactive: an account in automated use is not a break-glass account

b.json written with every estate value replaced; exit 4
```

- **The acknowledged pair is listed, and nothing else is silenced.** Each `PowerCLI` session reads
  `(acknowledged until 2026-10-16)`, the directory count reads `0 not acknowledged`, and the run exits 4 for the local
  administrator, the finding left. Read without `--ack`, a minute before and a minute after, the same pair was flagged
  and the run exited 1.

```
$ python3 vcenter_exchange.py --compare a.json b.json c.json
Compared 3 session records on 1 day(s): 2026-10-15
Coverage: reads in 1 of 24 hours of day (UTC: 11); a span of 0.02 h (0.00 days) from the first read to the last; the largest gap between two reads 1 min
Asked: reads in 24 hours of day, a span of 7 days, no gap limit
COVERAGE SHORT: reads in 1 of the 24 hours of day asked; a span of 0.00 day(s) where 7 were asked. A job that runs between two reads is absent from both, so what these records do not show is not known; that is exit 3, unless a finding comes first
vCenter {{host-2}} [fingerprint 11a82a3adbfef99e], read in 3 of 3 record(s)
  in every record: directory {{domain-1}}\{{name-2}} [fingerprint d1598c27948a7c1e] from PowerCLI; local administrator from VMware vim-java; local administrator from XML-WS Runtime git-revision#50dbfd3; local administrator from vAPI
  came and went: none
  from a client that is not interactive: directory {{domain-1}}\{{name-2}} [fingerprint d1598c27948a7c1e] from PowerCLI, seen in 3 record(s): NOT ACKNOWLEDGED
  from a client that is not interactive: local administrator from VMware vim-java, seen in 3 record(s): a break-glass account in automated use
  from a client that is not interactive: local administrator from XML-WS Runtime git-revision#50dbfd3, seen in 3 record(s): a break-glass account in automated use
  from a client that is not interactive: local administrator from vAPI, seen in 3 record(s): a break-glass account in automated use
vCenter {{host-1}} [fingerprint 492009a5c0b9a01e], read in 3 of 3 record(s)
  in every record: directory {{domain-1}}\{{name-2}} [fingerprint d1598c27948a7c1e] from PowerCLI; local administrator from VMware vim-java; local administrator from XML-WS Runtime git-revision#50dbfd3; local administrator from vapi-endpoint
  came and went: none
  from a client that is not interactive: directory {{domain-1}}\{{name-2}} [fingerprint d1598c27948a7c1e] from PowerCLI, seen in 3 record(s): NOT ACKNOWLEDGED
  from a client that is not interactive: local administrator from VMware vim-java, seen in 3 record(s): a break-glass account in automated use
  from a client that is not interactive: local administrator from XML-WS Runtime git-revision#50dbfd3, seen in 3 record(s): a break-glass account in automated use
  from a client that is not interactive: local administrator from vapi-endpoint, seen in 3 record(s): a break-glass account in automated use
vCenter {{host-3}} [fingerprint 8ae6dbd6036b19fa], read in 3 of 3 record(s)
  in every record: directory {{domain-1}}\{{name-2}} [fingerprint d1598c27948a7c1e] from PowerCLI
  came and went: none
  from a client that is not interactive: directory {{domain-1}}\{{name-2}} [fingerprint d1598c27948a7c1e] from PowerCLI, seen in 3 record(s): NOT ACKNOWLEDGED

exit 1
```

- **Three reads minutes apart cover one hour of day and a span of a minute.** Against the defaults (every hour of day,
  seven days) the coverage is short, so nothing these records leave out is known. The exit is 1, because a directory
  pair off the vSphere Client that no acknowledgement covers comes first; without it, the shortfall alone exits 3.
  `--compare` judges the pair itself, so an acknowledgement given to one census run is not carried into the comparison.

```
$ python3 vcenter_exchange.py --compare a.json b.json c.json --cover-hours 1 --span-days 0 --ack acks.json
Compared 3 session records on 1 day(s): 2026-10-15
Coverage: reads in 1 of 24 hours of day (UTC: 11); a span of 0.02 h (0.00 days) from the first read to the last; the largest gap between two reads 1 min
Asked: reads in 1 hours of day, a span of 0 days, no gap limit
vCenter {{host-2}} [fingerprint 11a82a3adbfef99e], read in 3 of 3 record(s)
  in every record: directory {{domain-1}}\{{name-2}} [fingerprint d1598c27948a7c1e] from PowerCLI; local administrator from VMware vim-java; local administrator from XML-WS Runtime git-revision#50dbfd3; local administrator from vAPI
  came and went: none
  from a client that is not interactive: directory {{domain-1}}\{{name-2}} [fingerprint d1598c27948a7c1e] from PowerCLI, seen in 3 record(s): acknowledged until 2026-10-16
  from a client that is not interactive: local administrator from VMware vim-java, seen in 3 record(s): a break-glass account in automated use
  from a client that is not interactive: local administrator from XML-WS Runtime git-revision#50dbfd3, seen in 3 record(s): a break-glass account in automated use
  from a client that is not interactive: local administrator from vAPI, seen in 3 record(s): a break-glass account in automated use
vCenter {{host-1}} [fingerprint 492009a5c0b9a01e], read in 3 of 3 record(s)
  in every record: directory {{domain-1}}\{{name-2}} [fingerprint d1598c27948a7c1e] from PowerCLI; local administrator from VMware vim-java; local administrator from XML-WS Runtime git-revision#50dbfd3; local administrator from vapi-endpoint
  came and went: none
  from a client that is not interactive: directory {{domain-1}}\{{name-2}} [fingerprint d1598c27948a7c1e] from PowerCLI, seen in 3 record(s): acknowledged until 2026-10-16
  from a client that is not interactive: local administrator from VMware vim-java, seen in 3 record(s): a break-glass account in automated use
  from a client that is not interactive: local administrator from XML-WS Runtime git-revision#50dbfd3, seen in 3 record(s): a break-glass account in automated use
  from a client that is not interactive: local administrator from vapi-endpoint, seen in 3 record(s): a break-glass account in automated use
vCenter {{host-3}} [fingerprint 8ae6dbd6036b19fa], read in 3 of 3 record(s)
  in every record: directory {{domain-1}}\{{name-2}} [fingerprint d1598c27948a7c1e] from PowerCLI
  came and went: none
  from a client that is not interactive: directory {{domain-1}}\{{name-2}} [fingerprint d1598c27948a7c1e] from PowerCLI, seen in 3 record(s): acknowledged until 2026-10-16

exit 4
```

- **With a coverage the reads meet and the pair acknowledged, what is left is the local administrator,** in automated
  use on the two management vCenters: exit 4. On a real gate the coverage asked is your own: a gap below the
  shortest session a job holds and a span over your longest cycle.

## 4. The census with no API client

`VC_USER` set to a directory account and no API client credential: the census alone, as that account. It printed exit
3, then the code for a directory account off the vSphere Client; the same read exits 1 now. The counts
differ from run 3 by a few sessions, read minutes apart. The account it reads as is the one run 3 flagged: its own
session is left out, its other sessions are not.

```
$ python3 vcenter_exchange.py --sessions --redact
Census read as VC_USER, an account with a password
vCenter {{host-1}}
  sessions (320, this census's own left out): directory 1, local administrator 15, local, VCF integration account 257, local, other 47
    local administrator by agent: VMware vim-java 5, XML-WS Runtime git-revision#50dbfd3 2, vapi-endpoint 8
    directory {{domain-1}}\{{name-2}}: vapi-endpoint 1  SIGNS IN FROM A CLIENT THAT IS NOT INTERACTIVE
vCenter {{host-2}}
  sessions (359, this census's own left out): directory 2, local administrator 8, local, VCF integration account 275, local, other 74
    local administrator by agent: VMware vim-java 1, XML-WS Runtime git-revision#50dbfd3 3, vAPI 4
    directory {{domain-1}}\{{name-2}}: vapi-endpoint 1  SIGNS IN FROM A CLIENT THAT IS NOT INTERACTIVE
    directory {{domain-1}}\{{name-3}}: vSphereUI 1
vCenter {{host-3}}
  sessions (280, this census's own left out): directory 3, local, VCF integration account 154, local, other 123
    directory {{domain-1}}\{{name-2}}: vapi-endpoint 3  SIGNS IN FROM A CLIENT THAT IS NOT INTERACTIVE
Directory accounts signing in from a client that is not interactive: 1
WATCH: the local administrator holds 23 session(s) from clients that are not interactive: an account in automated use is not a break-glass account

exchange.json written with every estate value replaced; exit 3
```

## 5. `api_client.py --teardown --execute`

The throwaway removed, on the operator's own token. Exit 0.

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
  signed in as: a person's token
  residue: client present False, tokens left 0
exit 0

api_client_teardown.json written with every estate value replaced
```

- **The residue read is the result.** After the deletes, both lists were read again: no client, no token. A teardown of a
  client that is not there removes nothing and exits 0, so it is safe to run again, in the fleet's only realm or the
  realm the state file records; on a fleet of more than one realm with no state file recording the client's realm, it
  prints `NOT READ` and exits 3, because the client may be in a realm the run did not read.
- **Signed in as a person.** The run's own bearer is read for who it is; signed in as the client it would remove, the
  teardown refuses, because nothing would outlive the removal to read the residue.

## 6. `service_account.py`: the plan, then one VCF Automation service account made

The same shape as `api_client.py`, in VCF Automation: a throwaway account in a throwaway All Apps organization,
2026-10-13, VCF Automation 9.1.1, run with a provider bearer (the third run, 07:04Z). The plan is today's; the run and
the teardown in section 7 predate the paged reads, so each list line there shows its path without
`&page=N&pageSize=128`, which the script now sends page after page until the items reach the stated `resultTotal`.

```text
Create plan for service account {{client-1}} in organization {{org-1}} on {{host-1}}:
  GET    /cloudapi/1.0.0/orgs?filter=name=={org}&page=N&pageSize=128  (every page, to the stated total)
  GET    /cloudapi/1.0.0/serviceAccounts?filter=name=={name}&page=N&pageSize=128  (in the organization, every page: refused if present)
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
