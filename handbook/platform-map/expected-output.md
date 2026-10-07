# Expected output

## inventory.py, 2026-10-07

One run against the reference estate, read-only, with `--record`. The two SDDC Manager names are replaced by
placeholders; the script prints nothing else that names the estate.

```text
inventory.py: your estate on the platform map, read-only

instance 1  (SDDC Manager {{sddc-manager-1}})
  domain  MANAGEMENT  ACTIVE   clusters 1 (hosts per cluster: 3)  hosts 3  vCenter 1  NSX 1
  domain  VI          ACTIVE   clusters 3 (hosts per cluster: 2, 2, 2)  hosts 6  vCenter 1  NSX 1
instance 2  (SDDC Manager {{sddc-manager-2}})
  domain  MANAGEMENT  ACTIVE   clusters 1 (hosts per cluster: 2)  hosts 2  vCenter 1  NSX 1

fleet  (the Fleet lifecycle service's component list)
  component              hosted as  scope     size         nodes                                instance
  OPS                    OVA        FLEET     medium       1 MASTER, 2 ONE_WAY_REMOTE_COLLECTOR 1
  OPS_LOGS               VSP        FLEET     small        -                                    1
  OPS_NETWORKS           OVA        FLEET     extra_large  1 PLATFORM                           1
  SALT_RAAS              VSP        FLEET     medium       -                                    1
  VCFA                   VSP        FLEET     small        -                                    1
  VCF_FLEET_DEPOT        VSP        FLEET     medium       -                                    1
  VCF_FLEET_LCM          VSP        FLEET     small        -                                    1
  OPS_DATA_PLATFORM      VSP        INSTANCE  medium       -                                    1
  SALT                   VSP        INSTANCE  medium       -                                    1
  TELEMETRY_ACCEPTOR     VSP        INSTANCE  medium       -                                    1
  VCFMS_METRICS_STORE    VSP        INSTANCE  medium       -                                    1
  VCF_SDDC_LCM           VSP        INSTANCE  small        -                                    1
  VIDB                   VSP        INSTANCE  medium       -                                    1
  VSP                    VSP        INSTANCE  medium       3 control-plane, 4 worker            1
  VCF_SDDC_LCM           VSP        INSTANCE  small        -                                    2
  VSP                    VSP        INSTANCE  small        1 control-plane, 2 worker            2
  16 components: 14 on instance 1, 2 on instance 2; 7 at fleet scope, 9 at instance scope; 2 appliances from an OVA, 14 on the services runtime

checks
  ok      instance 1 has one management domain
  ok      instance 1 has 1 workload domain(s)
  ok      instance 1, MANAGEMENT domain: its own vCenter (1) and an NSX manager (1)
  ok      instance 1, VI domain: its own vCenter (1) and an NSX manager (1)
  ok      instance 2 has one management domain
  ok      instance 2 has 0 workload domain(s): management only
  ok      instance 2, MANAGEMENT domain: its own vCenter (1) and an NSX manager (1)
  ok      every fleet component matched to an instance
  ok      one services runtime per instance (2 for 2)

wrote inventory.json: counts and types only, no host name, identifier or object name

exit 0
```

What to read in it: the primary instance carries one management and one workload domain, the second is
management-only, and every domain brings its own vCenter and NSX manager (plate 01). The fleet's sixteen
components split into appliances from an OVA and services on the runtime, at fleet and at instance scope, with the
runtime itself listed as one component per instance (plate 02).
