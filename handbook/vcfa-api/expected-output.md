# Expected output

Two runs against one VCF Automation 9.1 organization, read-only, with the placeholders the record carries.

## capture.py, 2026-09-21

The run that wrote [`calls.json`](calls.json), re-capturing the original of 2026-09-17 with every status, rights
count and token lifetime identical. The provider path was skipped because no provider refresh token was supplied.

```text
capture.py: the two flows, recorded read-only; values parameterized on the way into the record

  A1  POST /oauth/tenant/{{org}}/token                      200    606 ms
   (the refresh token that came back is the value that was sent)
   the answer says expires_in 3600 s; the bearer's own exp claim says 3600 s
  A2  GET  /cloudapi/1.0.0/sessions/current                 200    363 ms
  A3  GET  /cloudapi/1.0.0/sessions/current/rights?pageSize=1 200    363 ms
  A4  GET  /iaas/api/about                                  200    370 ms
  A5  GET  /cci/kubernetes/api                              200    517 ms
  B1  POST /cloudapi/1.0.0/sessions                         200    598 ms
   the session bearer's own exp claim says 3600 s
  B2  GET  /cloudapi/1.0.0/sessions/current/rights?pageSize=1 200    362 ms

  R   rights: OAuth 134, session 136; under the session only: ['Group / User: Manage', 'Role: Create, Edit, Delete, or Copy']; under OAuth only: []
  P   skipped: VCFA_PROVIDER_REFRESH_TOKEN_FILE not set (a provider api-token minted in the console)

recorded 8 exchanges to calls.json; every host, organization, user, token, and id replaced by a placeholder
```

The record is every request and response as it went over the wire, with the host, the organization, the user,
every token, and every identifier replaced by a placeholder. The chapter's plates render that file, and re-render
it with the values you type on the page.

## runway.py, 2026-10-07

One grant attempt with the organization's stored refresh token, then the token list under a session bearer
(`VCFA_BEARER`, because the grant was refused). Token names are replaced by `<token-N>`; nothing else was changed.

```text
runway.py: refresh-token runway on one organization, warn at 14 days, alert at 7

  grant   the stored refresh token: REFUSED (HTTP 400, invalid_grant: Invalid refresh token): revoked, expired, or minted for another organization; re-mint it (the console, or the session-login mint)
  bearer  from VCFA_BEARER

  token                              type       expires (UTC)            days  verdict
  <token-1>                          REFRESH    2026-11-03T05:45:31      26.6  ok
  <token-2>                          REFRESH    2027-01-04T20:38:57      89.2  ok

2 token(s) listed; exit 2
```

The stored token was past its rotation date, so the grant's `invalid_grant` is the line that matters: it exits 2,
which is the alarm. The two listed tokens are the same user's other refresh tokens, each with weeks to run; going by
their dates neither is the stored one, which was due for rotation on 2026-09-27. A list that looks healthy does not say the token you actually use still works; the
grant does.
