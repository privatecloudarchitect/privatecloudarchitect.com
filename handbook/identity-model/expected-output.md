# What a run looks like

The reference estate, 2026-10-12 (UTC): two VCF 9.1.1 instances, both management vCenters and one workload vCenter,
VCF Operations and VCF Automation. Run with `--redact`, so the names are placeholders; the record path is shortened
to its file name. Exit 0: every call answered.

The given hosts take the first placeholders, in the order the script reads them: `{{host-1}}` is `OPS_HOST`,
`{{host-2}}` is `OPS_BROKER_HOST`, `{{host-3}}` is `VCFA_HOST`, and `{{host-4}}` to `{{host-6}}` are `VC_HOSTS`. A
value keeps its placeholder everywhere it appears.

```
$ python3 census.py --redact
Brokers, from the identity plane: 3 (2 embedded, 1 instance)
  {{host-4}}  embedded  holds no realm
  {{host-5}}  embedded  holds no realm
  {{host-2}}  instance  holds realm {{host-2}}
Realm {{host-2}} on the instance broker {{host-2}}: covers 2 VCF instance(s) ({{name-2}}, {{name-3}}), 10 component(s); issues: none
Provider {{name-5}}: type ADLDAP, protocol LDAP_BIND, provisioning LDAP
  directory ad ({{domain-1}}): LDAP port 389 to {{host-7}}; sync COMPLETED, 14 users, 6 groups
Emergency client: none
API clients: 4
  {{name-8}}: roles sddc_admin, vcf_administrator, {{role-1}}; no token
  {{name-10}}: roles vcf_administrator; token {{name-16}} ACTIVE: API token 259200 min (180 d), access token 60 min
  {{name-12}}: roles vcf_viewer; token {{name-17}} ACTIVE: API token 259200 min (180 d), access token 60 min
  {{name-14}}: roles vcf_administrator; no token
User API token of {{name-1}}: token {{name-15}} ACTIVE: API token 259200 min (180 d), access token 60 min
Fleet settings: access token 60 min, API token 259200 min (180 d), retention 43200 min (30 d), all-users group off
Organizations: 10
  {{org-1}}  all-apps: ldap-system
  {{org-2}}  classic: ldap-system
  {{org-3}}  all-apps: oidc (issuer: entra)
  {{org-4}}  all-apps: saml
  {{org-5}}  classic: oidc (issuer: entra)
  {{org-6}}  classic: saml
  {{org-7}}  all-apps: ldap-system
  {{org-8}}  all-apps, provider consumption: oidc-broker, ldap-system (issuer: broker)
  System  all-apps: vcf-sso, ldap-system (issuer: broker)
  {{org-9}}  classic: oidc, ldap-system (issuer: other)
vCenter {{host-4}} signs in through {{host-2}} (instance)
vCenter {{host-5}} signs in through {{host-2}} (instance)
vCenter {{host-6}} signs in through {{host-2}} (instance); Supervisor {{name-22}}: {{host-3}}

57 call(s), 0 failed; census.json written with every estate value replaced
```

The egress option, run once a few minutes earlier against Entra ID's federation metadata for the lab tenant, adds
one notice before the run and one line after the vCenters:

```
$ python3 census.py --redact --egress-metadata-url https://login.microsoftonline.com/<tenant-id>/FederationMetadata/2007-06/FederationMetadata.xml
--egress-metadata-url: each broker will be asked to fetch the URL; this sends a request per broker
...
Egress (each broker fetched the metadata URL): {{host-4}} 200, {{host-5}} 200, {{host-2}} 200; identity plane unchanged
```

## What to read in it

- **Three brokers, one realm.** The identity plane lists two embedded brokers and one instance broker. The
  embedded brokers' hosts are `{{host-4}}` and `{{host-5}}`, the two management vCenters: an embedded broker lives
  inside a management vCenter whether or not it is used, and neither holds a realm. The identity plane lists no
  broker on the workload vCenter `{{host-6}}`. The fleet inventory has no row for an embedded broker, so a count taken there misses
  them.
- **The realm covers whole instances.** The one realm sits on the instance broker and covers both VCF instances
  and ten components. It carries the broker's own host as its name, which is why it reads `{{host-2}}`.
- **The provider is Active Directory over plain LDAP.** One identity provider of type `ADLDAP`, bound with
  `LDAP_BIND`, users arriving by `LDAP` sync. Its one directory binds to its domain controller over `LDAP` on port
  389, not `LDAPS`. That is the line to raise with the directory's owner.
- **No emergency client.** The realm holds no emergency access client: the break-glass client VCF documents for
  when standard sign-in fails, holding the highest role with the largest scope.
- **Machine identities and their lifetimes.** Four API clients; two hold an active token, each living 180 days and
  traded for a bearer that lives an hour. One person also holds an API token of the same lifetimes. The fleet
  settings hold the same two values.
- **Each organization chooses its own way in.** Three sign in only through VCF Automation's system LDAP
  (`ldap-system`); two federate over OIDC to Entra ID and two over SAML; one federates over OIDC to another
  provider (`issuer: other`) and also takes the system LDAP. The provider's `System` organization signs in
  through VCF single sign-on (`vcf-sso`), and the provider consumption organization holds an OIDC configuration
  that points at the broker without VCF Automation's flag (`oidc-broker`).
- **Every vCenter signs in through the instance broker,** including the two that carry an embedded broker of
  their own. The workload vCenter's Supervisor has one identity provider, and its issuer is `{{host-3}}`: VCF
  Automation.
- **The egress check reached Entra ID from all three brokers,** and the brokers, realms and providers read after
  it were the same as before it.
