# What request_catalog_item.py printed, one run of each kind

Example output: the five runs of the proof on VCF Automation 9.1.1, in a VM Apps organization, on 2026-11-13, in
order, with the script as it stands, one deployment from a throwaway catalog item, deleted at the end. The wait ran
with the default `CATALOG_WAIT_SECONDS`, 1200 s. Names are replaced: `<org>`, `<user>`, `<project>`, `<name>` (the
catalog item and the deployment shared it), the input values, and every id as `<id>`. Your run prints your own names,
and its timings are your platform's.

## Without --execute, signed in as a session: the checks and the request it would send (exit 0)

```
 1 session as <user>@<org>; signed in as <user>
   8.18: POST /csp/gateway/am/api/login?access_token {username, password} gave a refresh token (90 days, and
         'You cannot revoke the refresh token'), then POST /iaas/api/login {refreshToken} gave the bearer.
 2 VM Apps: /iaas/api/projects answered 200
   8.18: one kind of organization, so nothing to tell apart.
 3 project '<project>': <id>
   8.18: the same project.
 4 catalog item '<name>': <id> (com.vmw.blueprint, from its content source)
   8.18: the same catalog item, read the same way.
 7 no deployment named '<name>' in the project
   8.18: the same check, the guide's own step: GET /deployment/api/deployments?name=
 5 version 1 of 1 released
   8.18: the same list, GET /catalog/api/items/{id}/versions.
 6 inputs sent: app_name, flavor, image, ip_assignment, network_tag; defaults the platform fills: none
   8.18: the guide sends its inputs without reading the schema first.
 8 would send POST /catalog/api/items/<id>/request?apiVersion=2020-08-25
   {
     "deploymentName": "<name>",
     "projectId": "<id>",
     "version": "1",
     "inputs": {
       "app_name": "<name>",
       "image": "<image-mapping>",
       "flavor": "<flavor-mapping>",
       "network_tag": "<tag-key>:<tag-value>",
       "ip_assignment": "static"
     },
     "reason": "requested by request_catalog_item.py"
   }
   Add --execute to send it
   8.18: the same POST and body, without ?apiVersion=. Both guides print the answer as one object; the catalog
         API describes an array, and this script reads either.
10 DELETE /cloudapi/1.0.0/sessions/current: 204
   8.18: the guide gives no sign-out call; it says the access token 'times out' after 25 minutes of inactivity,
         and 'You can revoke an access token at any time.'
```

## --execute, signed in with an API token: the request sent once, and the wait (exit 0)

```
 1 API token, exchanged at /tm/oauth/tenant/<org>/token: a bearer for 3600 s; signed in as <user>
   8.18: POST /csp/gateway/am/api/login?access_token {username, password} gave a refresh token (90 days, and
         'You cannot revoke the refresh token'), then POST /iaas/api/login {refreshToken} gave the bearer.
 2 VM Apps: /iaas/api/projects answered 200
   8.18: one kind of organization, so nothing to tell apart.
 3 project '<project>': <id>
   8.18: the same project.
 4 catalog item '<name>': <id> (com.vmw.blueprint, from its content source)
   8.18: the same catalog item, read the same way.
 7 no deployment named '<name>' in the project
   8.18: the same check, the guide's own step: GET /deployment/api/deployments?name=
 5 version 1 of 1 released
   8.18: the same list, GET /catalog/api/items/{id}/versions.
 6 inputs sent: app_name, flavor, image, ip_assignment, network_tag; defaults the platform fills: none
   8.18: the guide sends its inputs without reading the schema first.
 8 POST /catalog/api/items/<id>/request?apiVersion=2020-08-25: 200, answered with a list, deployment <id>
   8.18: the same POST and body, without ?apiVersion=. Both guides print the answer as one object; the catalog
         API describes an array, and this script reads either.
 9 waiting on deployment <id>, at most 1200 s
   8.18: the same GET /deployment/api/deployments/{id}.
      after 0 s: deployment CREATE_INPROGRESS, request INITIALIZATION
      after 10 s: deployment CREATE_INPROGRESS, request INPROGRESS
      after 42 s: deployment CREATE_INPROGRESS, request CHECKING_APPROVAL
      after 52 s: deployment CREATE_INPROGRESS, request INPROGRESS
      after 322 s: deployment CREATE_SUCCESSFUL, request SUCCESSFUL
10 DELETE /cloudapi/1.0.0/sessions/current: 204
   8.18: the guide gives no sign-out call; it says the access token 'times out' after 25 minutes of inactivity,
         and 'You can revoke an access token at any time.'
```

## --execute again with the same name and no inputs file: the deployment found, nothing sent (exit 0)

```
 1 session as <user>@<org>; signed in as <user>
   8.18: POST /csp/gateway/am/api/login?access_token {username, password} gave a refresh token (90 days, and
         'You cannot revoke the refresh token'), then POST /iaas/api/login {refreshToken} gave the bearer.
 2 VM Apps: /iaas/api/projects answered 200
   8.18: one kind of organization, so nothing to tell apart.
 3 project '<project>': <id>
   8.18: the same project.
 4 catalog item '<name>': <id> (com.vmw.blueprint, from its content source)
   8.18: the same catalog item, read the same way.
 7 deployment '<name>' exists (<id>, CREATE_SUCCESSFUL): the request was sent before, and is not sent again
   8.18: the same check, the guide's own step: GET /deployment/api/deployments?name=
10 DELETE /cloudapi/1.0.0/sessions/current: 204
   8.18: the guide gives no sign-out call; it says the access token 'times out' after 25 minutes of inactivity,
         and 'You can revoke an access token at any time.'
```

## --delete without --execute: whose it is, and what it would remove (exit 0)

```
 1 API token, exchanged at /tm/oauth/tenant/<org>/token: a bearer for 3600 s; signed in as <user>
   8.18: POST /csp/gateway/am/api/login?access_token {username, password} gave a refresh token (90 days, and
         'You cannot revoke the refresh token'), then POST /iaas/api/login {refreshToken} gave the bearer.
 2 VM Apps: /iaas/api/projects answered 200
   8.18: one kind of organization, so nothing to tell apart.
 3 project '<project>': <id>
   8.18: the same project.
 4 catalog item '<name>': <id> (com.vmw.blueprint, from its content source)
   8.18: the same catalog item, read the same way.
 7 deployment named '<name>' in the project: one
   8.18: the same check, the guide's own step: GET /deployment/api/deployments?name=
   deployment <id> (CREATE_SUCCESSFUL): owned by <user>, created by <user>; signed in as <user>
   would delete it and every resource in it. Add --execute to delete it
10 DELETE /cloudapi/1.0.0/sessions/current: 204
   8.18: the guide gives no sign-out call; it says the access token 'times out' after 25 minutes of inactivity,
         and 'You can revoke an access token at any time.'
```

## --delete --execute: removed, and read until it was gone (exit 0)

```
 1 API token, exchanged at /tm/oauth/tenant/<org>/token: a bearer for 3600 s; signed in as <user>
   8.18: POST /csp/gateway/am/api/login?access_token {username, password} gave a refresh token (90 days, and
         'You cannot revoke the refresh token'), then POST /iaas/api/login {refreshToken} gave the bearer.
 2 VM Apps: /iaas/api/projects answered 200
   8.18: one kind of organization, so nothing to tell apart.
 3 project '<project>': <id>
   8.18: the same project.
 4 catalog item '<name>': <id> (com.vmw.blueprint, from its content source)
   8.18: the same catalog item, read the same way.
 7 deployment named '<name>' in the project: one
   8.18: the same check, the guide's own step: GET /deployment/api/deployments?name=
   deployment <id> (CREATE_SUCCESSFUL): owned by <user>, created by <user>; signed in as <user>
   DELETE /deployment/api/deployments/<id>: 200, request <id> PENDING
      gone after 53 s
10 DELETE /cloudapi/1.0.0/sessions/current: 204
   8.18: the guide gives no sign-out call; it says the access token 'times out' after 25 minutes of inactivity,
         and 'You can revoke an access token at any time.'
```
