# Expected output

What `lifecycle.py` printed on the reference estate at 2026-10-21T23:44:53Z: both instances' SDDC Managers, read-only, the primary as the instance asked about and the secondary as the rehearsal instance. It exited 0: nothing is offered, so nothing offered is unstaged.

```
$ python3 lifecycle.py
lifecycle.py: is the upgrade the registry is offering actually available?

=== the instance asked about ===
  SDDC Manager: 9.1.1.0.25713928
  domains: 2 (1 management, 1 workload)
  releases known: 19
  bundles: 368 -> {'PENDING': 338, 'SUCCESSFUL': 29, 'FAILED': 1}
  upgradables on the management domain: 0
  the same read for a workload domain: HTTP 400 (Management Domain with ID {{id}} not found.)

  THE JOIN: 0 upgradable(s) reference 0 distinct bundle(s); 0 of those bundles are staged
     nothing is offered, which on a current estate is the read you want to be able to produce.

  depot settings: HTTP 410, and the platform names its own replacement: Please refer to GET v1/services-config instead.
     following it: 1 service(s) configured -> ['VCF_DEPOT']

=== the rehearsal instance ===
  SDDC Manager: 9.1.1.0.25713928
  domains: 1 (1 management, 0 workload)
  releases known: 19
  bundles: 366 -> {'PENDING': 339, 'SUCCESSFUL': 27}
  upgradables on the management domain: 0

  THE JOIN: 0 upgradable(s) reference 0 distinct bundle(s); 0 of those bundles are staged
     nothing is offered, which on a current estate is the read you want to be able to produce.

  depot settings: HTTP 410, and the platform names its own replacement: Please refer to GET v1/services-config instead.
     following it: 1 service(s) configured -> ['VCF_DEPOT']

  the stagger: SDDC Manager 9.1.1.0.25713928 against 9.1.1.0.25713928; the same build, so no stagger today
     0 upgradable(s) on the instance asked about, 0 on the rehearsal instance; staged bundles 29 against 27
```

`records/lifecycle-2026-09-21.json` is the reading from 2026-09-21, while the 9.1.1 upgrade was on offer: four upgradables on the instance asked about, three distinct bundles behind them, none staged. Run against that state, this build would have exited 1.
