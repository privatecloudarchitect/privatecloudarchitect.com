# Expected output

## inventory.py, 2026-10-12

One run against the reference estate on VCF 9.1.1, read-only, with `--bom bom-9.1.1.json --record inventory.json` and
one standalone Orchestrator named in `VCFO_HOSTS`. The two SDDC Manager names are replaced by placeholders; the script
prints nothing else that names the estate.

```text
inventory.py: your estate on the platform map, read-only

instance 1  SDDC Manager 9.1.1.0.25713928  ({{sddc-manager-1}})
  domain  MANAGEMENT  ACTIVE   clusters 1 (hosts per cluster: 3)  hosts 3 on ESX 9.1.1.0.25714478
          vCenter 1 (9.1.1.0.25712839)  NSX 1 (9.1.1.0.25691509)
          Supervisor: none
  domain  VI          ACTIVE   clusters 3 (hosts per cluster: 2, 2, 2)  hosts 6 on ESX 9.1.1.0.25714478
          vCenter 1 (9.1.1.0.25712839)  NSX 1 (9.1.1.0.25691509)
          Supervisor READY, v1.34.9+vmware.1-vsc9.1.1.0-25712839; 3 vSphere zone(s), clusters per zone: 1, 1, 1
          Supervisor services 8: VKS cluster management 0.2.1-0100-25757808, Local Consumption Interface 9.1.2-embedded+fe6ddfd1, Configuration Service 9.1.1-25670523, Data Services Manager Consumption Operator 9.1.0+vmware.0.25261877, Harbor 2.15.2+vmware.1-vks.1, Metrics Aggregator 0.1.0, Kubernetes Service 3.7.1+v1.36, Velero vSphere Operator 1.9.0-embedded+25647146
          namespaces 14, 8 of them the platform's own (svc-)
instance 2  SDDC Manager 9.1.1.0.25713928  ({{sddc-manager-2}})
  domain  MANAGEMENT  ACTIVE   clusters 1 (hosts per cluster: 2)  hosts 2 on ESX 9.1.1.0.25714478
          vCenter 1 (9.1.1.0.25712839)  NSX 1 (9.1.1.0.25691509)
          Supervisor: none

fleet  (the Fleet lifecycle service's component list)
  component            version               hosted as scope     size         nodes                                instance
  OPS                  9.1.1.0.25679751      OVA       FLEET     medium       1 MASTER, 2 ONE_WAY_REMOTE_COLLECTOR 1
  OPS_LOGS             9.1.1.0.25679624      VSP       FLEET     small        -                                    1
  OPS_NETWORKS         9.1.1.0.25682214      OVA       FLEET     extra_large  1 PLATFORM                           1
  SALT_RAAS            9.1.1.0.25679895      VSP       FLEET     medium       -                                    1
  VCFA                 9.1.1.0100.25757808   VSP       FLEET     small        -                                    1
  VCF_FLEET_DEPOT      9.1.1.0.25713941      VSP       FLEET     medium       -                                    1
  VCF_FLEET_LCM        9.1.1.0100.25761871   VSP       FLEET     small        -                                    1
  OPS_DATA_PLATFORM    9.1.1.0.25679622      VSP       INSTANCE  medium       -                                    1
  SALT                 9.1.1.0.25679895      VSP       INSTANCE  medium       -                                    1
  TELEMETRY_ACCEPTOR   9.1.1.0.25671600      VSP       INSTANCE  medium       -                                    1
  VCFMS_METRICS_STORE  9.1.1.0.25714471      VSP       INSTANCE  medium       -                                    1
  VCF_SDDC_LCM         9.1.1.0100.25761870   VSP       INSTANCE  small        -                                    1
  VIDB                 9.1.1.0.25679886      VSP       INSTANCE  medium       -                                    1
  VSP                  9.1.1.0.25714471      VSP       INSTANCE  medium       3 control-plane, 4 worker            1
  VCF_SDDC_LCM         9.1.1.0100.25761870   VSP       INSTANCE  small        -                                    2
  VSP                  9.1.1.0.25714471      VSP       INSTANCE  small        1 control-plane, 2 worker            2
  16 components: 14 on instance 1, 2 on instance 2; 7 at fleet scope, 9 at instance scope; 2 appliances from an OVA, 14 on the services runtime
  where VCF Operations collects: 48 adapter instances on its remote collectors (2 UNIFIED_CLOUD_PROXY), 10 on the analytics node's own collector; vCenter, NSX and vSAN adapters: 9 remote, 0 on the analytics node

standalone  (named in VCFO_HOSTS; neither SDDC Manager nor the fleet list carries these)
  VCF Operations orchestrator 1: 9.1.0.0400.25545107

releases  (every version on the VCF release line read above)
  9.1.0: 1 component reading(s): VCF Operations orchestrator 9.1.0.0400.25545107
  9.1.1: 28 component reading(s)

bill of materials 9.1.1  (bom-9.1.1.json, read 2026-10-12)
  at its build   15 (23 readings): ESX 9.1.1.0.25714478; Identity broker 9.1.1.0.25679886; Log management 9.1.1.0.25679624; NSX 9.1.1.0.25691509; Real-time metrics 9.1.1.0.25679622; Real-time metrics store 9.1.1.0.25714471; SDDC Manager 9.1.1.0.25713928; Salt RaaS 9.1.1.0.25679895; Salt master 9.1.1.0.25679895; Software depot 9.1.1.0.25713941; Telemetry 9.1.1.0.25671600; VCF Operations 9.1.1.0.25679751; VCF Operations for networks 9.1.1.0.25682214; VCF services runtime 9.1.1.0.25714471; vCenter 9.1.1.0.25712839
  on its release 1: Supervisor v1.34.9+vmware.1-vsc9.1.1.0-25712839
  a later patch  3 (4 readings): Fleet lifecycle 9.1.1.0100.25761871; SDDC lifecycle 9.1.1.0100.25761870; VCF Automation 9.1.1.0100.25757808
  behind         1: VCF Operations orchestrator 9.1.0.0400.25545107 (the bill lists 9.1.1.0.25679883)

checks
  ok      instance 1 has one management domain
  ok      instance 1 has 1 workload domain(s)
  ok      instance 1, MANAGEMENT domain: its own vCenter (1) and an NSX manager (1)
  ok      instance 1, MANAGEMENT domain: no Supervisor (0)
  ok      instance 1, VI domain: its own vCenter (1) and an NSX manager (1)
  ok      instance 2 has one management domain
  ok      instance 2 has 0 workload domain(s): management only
  ok      instance 2, MANAGEMENT domain: its own vCenter (1) and an NSX manager (1)
  ok      instance 2, MANAGEMENT domain: no Supervisor (0)
  ok      every fleet component matched to an instance
  ok      one services runtime per instance (2 for 2)
  DIFFERS one release across every component read: 2 releases (9.1.0, 9.1.1)
  DIFFERS no component behind the bill of materials: 1 (VCF Operations orchestrator)

wrote inventory.json: versions, counts and types only, no host name, identifier or object name

exit 1
```

What to read in it. The primary instance carries one management and one workload domain, the second is
management-only, and every domain brings its own vCenter and NSX manager; only the workload domain's vCenter runs a
Supervisor, over three vSphere zones of one cluster each, with eight Supervisor services, each in a namespace of its
own (plate 01). The fleet's sixteen components split into appliances from an OVA and services on the runtime, at
fleet and at instance scope; VCF Operations is one analytics node with two cloud proxies, and the vCenter, NSX and
vSAN adapters all run on the proxies (plate 02). The release check is the reason this run exits 1: every component
the two inventories carry is on 9.1.1, three of them on its 0100 patch, and the one component neither inventory
carries, a standalone Orchestrator, is still on 9.1.0 (plate 02).
