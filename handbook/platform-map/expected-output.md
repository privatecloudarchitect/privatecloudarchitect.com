# Expected output

## inventory.py, 2026-10-28

One run against the reference estate on VCF 9.1.1, read-only, with `--bom bom-9.1.1.json --record inventory.json` and
one standalone Orchestrator named in `VCFO_HOSTS`, finished at 06:52:20 UTC. The two SDDC Manager names are replaced by placeholders; the script
prints nothing else that names the estate.

```text
inventory.py: your estate on the platform map, read-only

instance 1  SDDC Manager 9.1.1.0.25713928  ({{sddc-manager-1}})
  domain  MANAGEMENT  ACTIVE   clusters 1 (hosts per cluster: 3)  hosts 3 on ESX 9.1.1.0.25714478
          vCenter 1 (9.1.1.0.25712839)  NSX 1 (9.1.1.0.25691509)
          appliances  51 VMs; by their OVF product (version not kept: it is the deployed one): 1 Avi Cloud Controller; 1 Protection and recovery appliance; 1 VCF License Server Appliance; 1 VCF Operations for Networks Collector; 1 VCF Operations for Networks Platform; 1 VCF Operations orchestrator Appliance; 1 VMware Cloud Foundation Operations Appliance; 1 VMware Cloud Foundation Operations Cloud Proxy; 1 VMware VCF SDDC Manager Appliance; 3 VMware vCenter Server Appliance; 1 license-hub; 2 nsx-edge; 2 nsx-unified-appliance; 34 with no product or another vendor's
          Supervisor: none
  domain  VI          ACTIVE   clusters 3 (hosts per cluster: 2, 2, 2)  hosts 6 on ESX 9.1.1.0.25714478
          vCenter 1 (9.1.1.0.25712839)  NSX 1 (9.1.1.0.25691509)
          appliances  33 VMs; by their OVF product (version not kept: it is the deployed one): 5 Avi Service Engine; 1 VMware Data Services Manager Appliance; 2 nsx-edge; 3 vSphere Supervisor; 22 with no product or another vendor's
          Supervisor READY, v1.34.9+vmware.1-vsc9.1.1.0-25712839; 3 vSphere zone(s), clusters per zone: 1, 1, 1
          Supervisor services 9: VKS cluster management 0.2.1-0200-25801570, Local Consumption Interface 9.1.2-embedded+fe6ddfd1, Configuration Service 9.1.1-25670523, Data Services Consumption Operator 9.1.1+vmware.0.25623779, Data Services Provider Operator 9.1.1+vmware.0.25641961, Harbor 2.15.2+vmware.1-vks.1, Metrics Aggregator 0.1.0, Kubernetes Service 3.7.1+v1.36, Velero vSphere Operator 1.9.0-embedded+25647146
          namespaces 14, 9 of them the platform's own (svc-)
instance 2  SDDC Manager 9.1.1.0.25713928  ({{sddc-manager-2}})
  domain  MANAGEMENT  ACTIVE   clusters 1 (hosts per cluster: 2)  hosts 2 on ESX 9.1.1.0.25714478
          vCenter 1 (9.1.1.0.25712839)  NSX 1 (9.1.1.0.25691509)
          appliances  10 VMs; by their OVF product (version not kept: it is the deployed one): 1 VMware Cloud Foundation Operations Cloud Proxy; 1 VMware VCF SDDC Manager Appliance; 2 nsx-edge; 1 nsx-unified-appliance; 5 with no product or another vendor's
          Supervisor: none

fleet  (the Fleet lifecycle service's component list)
  component            version               hosted as scope     size         nodes                                instance  runtime
  OPS                  9.1.1.0100.25795063   OVA       FLEET     medium       1 MASTER, 2 ONE_WAY_REMOTE_COLLECTOR 1         -
  OPS_LOGS             9.1.1.0100.25795095   VSP       FLEET     small        -                                    1         #2 MANAGEMENT
  OPS_NETWORKS         9.1.1.0100.25774578   OVA       FLEET     extra_large  1 PLATFORM                           1         -
  SALT_RAAS            9.1.1.0100.25795075   VSP       FLEET     medium       -                                    1         #2 MANAGEMENT
  VCFA                 9.1.1.0200.25801570   VSP       FLEET     small        -                                    1         #3 CONSUMPTION, not listed
  VCF_FLEET_DEPOT      9.1.1.0200.25801072   VSP       FLEET     medium       -                                    1         #2 MANAGEMENT
  VCF_FLEET_LCM        9.1.1.0200.25801070   VSP       FLEET     small        -                                    1         #2 MANAGEMENT
  OPS_DATA_PLATFORM    9.1.1.0100.25794546   VSP       INSTANCE  medium       -                                    1         #2 MANAGEMENT
  SALT                 9.1.1.0100.25795075   VSP       INSTANCE  medium       -                                    1         #2 MANAGEMENT
  TELEMETRY_ACCEPTOR   9.1.1.0100.25741214   VSP       INSTANCE  medium       -                                    1         #2 MANAGEMENT
  VCFMS_METRICS_STORE  9.1.1.0100.25801571   VSP       INSTANCE  medium       -                                    1         #2 MANAGEMENT
  VCF_SDDC_LCM         9.1.1.0200.25801981   VSP       INSTANCE  small        -                                    1         #2 MANAGEMENT
  VIDB                 9.1.1.0100.25796677   VSP       INSTANCE  medium       -                                    1         #2 MANAGEMENT
  VSP                  9.1.1.0100.25801571   VSP       INSTANCE  medium       3 control-plane, 4 worker            1         is #2 MANAGEMENT
  VCF_SDDC_LCM         9.1.1.0200.25801981   VSP       INSTANCE  small        -                                    2         #1 MANAGEMENT
  VSP                  9.1.1.0100.25801571   VSP       INSTANCE  small        1 control-plane, 2 worker            2         is #1 MANAGEMENT
  16 components: 14 on instance 1, 2 on instance 2; 7 at fleet scope, 9 at instance scope; 2 appliances from an OVA, 14 on the services runtime
  services runtime #3 (CONSUMPTION) carries VCF Automation; the list carries no component for that runtime itself
  where VCF Operations collects: 48 adapter instances on its remote collectors (2 UNIFIED_CLOUD_PROXY), 10 on the analytics node's own collector; vCenter, NSX and vSAN adapters: 9 remote, 0 on the analytics node

standalone  (named in VCFO_HOSTS; neither SDDC Manager nor the fleet list carries these)
  VCF Operations orchestrator 1: 9.1.0.0400.25545107

releases  (every version on the VCF release line read above)
  9.1.0: 1 component reading(s): VCF Operations orchestrator 9.1.0.0400.25545107
  9.1.1: 28 component reading(s)

bill of materials 9.1.1  (bom-9.1.1.json, read 2026-10-28): 56 rows, 20 read here, 11 seen deployed (an appliance or a Supervisor service), 25 not read here
  at its build   4 (11 readings): ESX 9.1.1.0.25714478; NSX 9.1.1.0.25691509; SDDC Manager 9.1.1.0.25713928; vCenter 9.1.1.0.25712839
  on its release 1: Supervisor v1.34.9+vmware.1-vsc9.1.1.0-25712839
  a later patch  14 (16 readings): Fleet lifecycle 9.1.1.0200.25801070; Identity broker 9.1.1.0100.25796677; Log management 9.1.1.0100.25795095; Real-time metrics 9.1.1.0100.25794546; Real-time metrics store 9.1.1.0100.25801571; SDDC lifecycle 9.1.1.0200.25801981; Salt RaaS 9.1.1.0100.25795075; Salt master 9.1.1.0100.25795075; Software depot 9.1.1.0200.25801072; Telemetry 9.1.1.0100.25741214; VCF Automation 9.1.1.0200.25801570; VCF Operations 9.1.1.0100.25795063; VCF Operations for networks 9.1.1.0100.25774578; VCF services runtime 9.1.1.0100.25801571
  behind         1: VCF Operations orchestrator 9.1.0.0400.25545107 (the bill lists 9.1.1.0.25679883)
  seen, version unread 11: Cloud proxy; License server; VMware vSphere Kubernetes Service; Harbor (Supervisor service); VKSM Auto-attach; VMware vSphere Supervisor LCI; Configuration Service (VCF service); Data Services (VCF service); Metrics Aggregator (VCF service); VMware Data Services Manager; Protection and Recovery
  not read here  25: vSAN ESA Witness; vSAN File Services *; vSAN OSA Witness; VCF Operations HCX; VKS Add-ons (former VKS Standard Packages); vSphere Kubernetes releases; VCF download tool; VMware Remote Console; VMware Tools; VCF Consumption CLI; VCF Consumption CLI Plugins & Database; Deep Learning VM; Private AI Services; CA Cluster issuer (Supervisor service); Contour (Supervisor service); External DNS (Supervisor service); ArgoCD (Supervisor service); Supervisor Management Proxy; Migration service engine (VCF service); Migration Service (VCF service); ArgoCD (VCF service); Encryption Management (VCF service); Protection and Recovery (VCF service); Harbor (VCF service); Secret Store (VCF service)

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
```

What to read in it. The primary instance carries one management and one workload domain, the second is
management-only, and every domain has its own vCenter and NSX manager, the workload domain's running in the management
domain; only the workload domain's vCenter runs a Supervisor, over three vSphere zones of one cluster each, with nine
Supervisor services, each in a namespace of its own, and each vCenter's appliances are counted by the product their
OVF names (plate 01). The fleet's sixteen components split into appliances from an OVA and services on the management
services runtime, at fleet and at instance scope, with VCF Automation on a runtime of its own, typed CONSUMPTION, that
the list carries no component for; VCF Operations is one analytics node with two cloud proxies, and the vCenter, NSX
and vSAN adapters all run on the proxies (plate 02). The release check is the reason this run exits 1: every component
the two inventories carry is on 9.1.1, fourteen of them on a later patch (0100, 0200), and the one component
neither inventory carries, a standalone Orchestrator, is still on 9.1.0. Of the bill's 56 rows, twenty were read
with their version, eleven seen deployed and twenty-five not read here: a row no read finds is reported, not dropped (plate 02).
