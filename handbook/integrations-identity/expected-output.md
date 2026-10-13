# What a run looks like

The reference estate, 2026-10-13 (UTC): three vCenters on 9.1.1 joined to VCF single sign-on, whose broker's identity
provider is Active Directory over LDAP. The API client holds the fleet role `vcf_viewer`; the session lists were read as a
directory administrator. Run with `--sessions --redact`, so the names are placeholders; the record path is shortened to
its file name. Exit 0: the client took both sessions everywhere, and no directory account signs in from a vSphere SDK.

```
$ python3 vcenter_exchange.py --sessions --redact
vCenter {{host-1}}
  the bearer as presented: HTTP 401
  exchange: HTTP 200, urn:ietf:params:oauth:token-type:saml2, Bearer, lives 299 s
  REST session (SIGN): HTTP 201, user CUSTOMER\{{client-1}}, VM list HTTP 200
  SOAP session (LoginByToken): user CUSTOMER\{{client-1}}
  sessions (312, this census's own left out): local administrator 15, local, VCF integration account 249, local, other 48
    local administrator by agent: VMware vim-java 5, XML-WS Runtime git-revision#50dbfd3 2, vapi-endpoint 8
vCenter {{host-2}}
  the bearer as presented: HTTP 401
  exchange: HTTP 200, urn:ietf:params:oauth:token-type:saml2, Bearer, lives 299 s
  REST session (SIGN): HTTP 201, user CUSTOMER\{{client-1}}, VM list HTTP 200
  SOAP session (LoginByToken): user CUSTOMER\{{client-1}}
  sessions (351, this census's own left out): local administrator 8, local, VCF integration account 270, local, other 73
    local administrator by agent: VMware vim-java 1, XML-WS Runtime git-revision#50dbfd3 3, vAPI 4
vCenter {{host-3}}
  the bearer as presented: HTTP 401
  exchange: HTTP 200, urn:ietf:params:oauth:token-type:saml2, Bearer, lives 299 s
  REST session (SIGN): HTTP 201, user CUSTOMER\{{client-1}}, VM list HTTP 200
  SOAP session (LoginByToken): user CUSTOMER\{{client-1}}
  sessions (263, this census's own left out): local, VCF integration account 151, local, other 112
The client took both sessions on 3 of 3 vCenter(s)
Directory accounts signing in from a vSphere SDK: 0

exchange.json written with every estate value replaced; exit 0
```

## What to read in it

- **The bearer as presented is refused, and that is expected.** Every vCenter answered the broker's bearer with HTTP 401.
  vCenter takes the client only after its own exchange; NSX takes the same bearer as it is.
- **The exchange answers a SAML token that lives minutes.** `urn:ietf:params:oauth:token-type:saml2`, of the Bearer type,
  299 seconds on every vCenter. Make the exchange just before the session, not ahead of time.
- **Both sessions are the client itself.** The REST session (the assertion in a `SIGN` header) and the SOAP session
  (`LoginByToken`) both read `CUSTOMER\{{client-1}}`: the realm's domain and the client's id. That is how a machine identity
  shows in a session census.
- **The census leaves itself out.** It reads each session list as `VC_USER` and drops its own session by its key, so a
  directory account seen here is someone else's.
- **Most sessions are VCF's own.** On the reference estate VCF's integration accounts (local, named `svc-`) and other local
  accounts (solution users, Supervisor accounts) held nearly all of them. Leave those; VCF runs them.
- **The local administrator is in automated use on the two management vCenters.** Its sessions came from `VMware vim-java`,
  `XML-WS Runtime` and `vAPI` or `vapi-endpoint` agents: programs, not a person at a console. An account in automated use
  is not a break-glass account; find the client behind each before you vault it.
- **No directory account signed in at the read.** Sessions show what is signed in at that moment; a nightly or weekly job is
  absent between runs. Read on several days before you conclude there is none.
