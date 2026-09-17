# Expected output

One run of `capture.py` against a VCF Automation 9.1 organization on 2026-09-16, with the placeholders the record
carries. The provider path was skipped because no provider refresh token was supplied.

```text
capture.py: the two flows, recorded read-only; values parameterized on the way into the record

  A1  POST /oauth/tenant/{{org}}/token                      200    629 ms
   (the refresh token that came back is the value that was sent)
   the answer says expires_in 3600 s; the bearer's own exp claim says 3600 s
  A2  GET  /cloudapi/1.0.0/sessions/current                 200    417 ms
  A3  GET  /cloudapi/1.0.0/sessions/current/rights?pageSize=1 200    365 ms
  A4  GET  /iaas/api/about                                  200    362 ms
  A5  GET  /cci/kubernetes/api                              200    517 ms
  B1  POST /cloudapi/1.0.0/sessions                         200    570 ms
   the session bearer's own exp claim says 3600 s
  B2  GET  /cloudapi/1.0.0/sessions/current/rights?pageSize=1 200    366 ms

  R   rights: OAuth 134, session 136; under the session only: ['Group / User: Manage', 'Role: Create, Edit, Delete, or Copy']; under OAuth only: []
  P   skipped: VCFA_PROVIDER_REFRESH_TOKEN_FILE not set (a provider api-token minted in the console)

recorded 8 exchanges to calls.json every host, organization, user,
```

The record it wrote is [`calls.json`](calls.json): every request and response as it went over the wire, with the
host, the organization, the user, every token, and every identifier replaced by a placeholder. The chapter's plates
render that file, and re-render it with the values you type on the page.
