# Expected output

What `custodian.py` printed on the reference estate at 2026-10-21T23:20:07Z: the primary instance's SDDC Manager on VCF 9.1.1, read-only. Every secret the inventory returned was destroyed on arrival; the output and `custodian.json` hold counts and dates only.

```
$ python3 custodian.py
custodian.py: the credential inventory and the certificate horizon, metadata only

  credentials: 49
     by resource type:   {'BACKUP': 1, 'ESXI': 18, 'NSXT_EDGE': 13, 'NSXT_MANAGER': 9, 'NSX_ALB': 1, 'PSC': 2, 'VCENTER': 5}
     by credential type: {'FTP': 1, 'SSH': 28, 'API': 12, 'AUDIT': 3, 'SSO': 5}
     by account type:    {'SYSTEM': 23, 'SERVICE': 15, 'USER': 11}
     carrying an automatic rotation policy: 6 of 49

  DISCLOSURE: 34 of 49 entries returned secret material in the LIST response
     disclosed for account types: {'SYSTEM': 23, 'USER': 11}
     withheld  for account types: {'SERVICE': 15}
     disclosed by resource type:  {'BACKUP': 1, 'ESXI': 9, 'NSXT_EDGE': 13, 'NSXT_MANAGER': 6, 'NSX_ALB': 1, 'PSC': 2, 'VCENTER': 2}
     This script destroyed those values on arrival and kept only the count. Anything else that
     reads this endpoint does not, so treat its output as secret material and never write it
     to a file, a log, a ticket or a terminal recording.

  MANAGEMENT   9 certificate(s); issuers {"the instance's own CA": 8, 'another chain': 1}
              days to expiry 211 to 576, 3 inside a year

  VI          10 certificate(s); issuers {"the instance's own CA": 10}
              days to expiry 291 to 1693, 3 inside a year

  across the estate: 19 certificate(s); status {'ACTIVE': 19}; auto renew {'DISABLED': 17, 'None': 2}
     nearest expiry 211 days; 6 inside a year; 0 inside 90 days
```
