# Expected output

What `lifecycle.py` printed on the reference estate at 2026-11-27T05:55:33Z: two instances' SDDC Managers, read-only, one as the instance asked about and the other as the rehearsal instance. It exited 0: the upgradable read without a target offered nothing on the instance asked about.

```
$ python3 lifecycle.py
lifecycle.py: is the upgrade the registry is offering actually available?

=== the instance asked about ===
  SDDC Manager: 9.1.1.0200.25801071
  domains: 2 (1 management, 1 workload)
  releases known: 21
  bundles: 414 -> {'PENDING': 398, 'SUCCESSFUL': 15, 'FAILED': 1}
  management domain: target 9.1.1.0, isCustomizedBom True; future releases: 9.1.2.0 APPLICABLE
  workload domain 1: target 9.1.1.0, isCustomizedBom True; future releases: 9.1.2.0 APPLICABLE
  upgradables on the management domain: 0
  the same read for a workload domain: HTTP 400 (Management Domain with ID {{id}} not found.)

  THE JOIN: 0 upgradable(s) reference 0 distinct bundle(s); 0 of those bundles are staged
     nothing is offered to this read, which answers for a target release: a zero is not a current estate, so each release the registry names applicable is asked for by name below.

  THE JOIN for target 9.1.2.0: 1 upgradable(s) reference 1 distinct bundle(s); 0 of those bundles are staged
     none of the content is downloaded. 2,544 MB (the API's sizeMB) still to fetch before any of this is actually available, whatever the registry says.

  later patches in the depot, on each component's running line:
     SDDC_MANAGER at 9.1.1.0200.25801071: none listed above it
     VCENTER at 9.1.1.0100.25784172: 9.1.1.0200.25901347 (released 2026-11-19, PENDING)
     NSX_T_MANAGER at 9.1.1.0100.25762940: none listed above it

  depot settings: HTTP 410, and the platform names its own replacement: Please refer to GET v1/services-config instead.
     following it: 1 service(s) configured -> ['VCF_DEPOT']

=== the rehearsal instance ===
  SDDC Manager: 9.1.1.0200.25801071
  domains: 1 (1 management, 0 workload)
  releases known: 21
  bundles: 412 -> {'PENDING': 412}
  management domain: target 9.1.1.0, isCustomizedBom True; future releases: 9.1.2.0 APPLICABLE
  upgradables on the management domain: 0

  THE JOIN: 0 upgradable(s) reference 0 distinct bundle(s); 0 of those bundles are staged
     nothing is offered to this read, which answers for a target release: a zero is not a current estate, so each release the registry names applicable is asked for by name below.

  THE JOIN for target 9.1.2.0: 1 upgradable(s) reference 1 distinct bundle(s); 0 of those bundles are staged
     none of the content is downloaded. 2,544 MB (the API's sizeMB) still to fetch before any of this is actually available, whatever the registry says.

  later patches in the depot, on each component's running line:
     SDDC_MANAGER at 9.1.1.0200.25801071: none listed above it
     VCENTER at 9.1.1.0100.25784172: 9.1.1.0200.25901347 (released 2026-11-19, PENDING)
     NSX_T_MANAGER at 9.1.1.0100.25762940: none listed above it

  depot settings: HTTP 410, and the platform names its own replacement: Please refer to GET v1/services-config instead.
     following it: 1 service(s) configured -> ['VCF_DEPOT']

  the stagger: SDDC Manager 9.1.1.0200.25801071 against 9.1.1.0200.25801071; the same build, so no stagger today
     0 upgradable(s) on the instance asked about, 0 on the rehearsal instance; staged bundles 15 against 0

wrote lifecycle.json (2 instance(s) read); every instance name replaced by a placeholder
```

`records/lifecycle-2026-10-21.json` is the reading before this one, at the 9.1.1.0 build. `records/lifecycle-2026-09-21.json` is the reading from 2026-09-21, while the 9.1.1 upgrade was on offer: four upgradables on the instance asked about, three distinct bundles behind them, none staged. Run against that state, this build would have exited 1.
