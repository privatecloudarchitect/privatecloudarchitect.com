# Expected output

The run on the reference estate, 2026-10-23, against the ConfigMax exports downloaded that day: both instances' SDDC
Manager, three vCenters, three NSX Managers and the VCF Automation provider plane read. Labels stand where the estate had
names; your counts and releases will differ. Exit code 0: no cap is at or over 70 percent.

```
$ python3 maximums.py --exports ~/configmax --fleet simple --nsx medium-singleton --vcfa medium
maximums.py: 11 export(s), sizes VCF Installer Simple Deployment, NSX Medium NSX Manager - Singleton, Edge Medium Edge Node, VCF Automation Medium Profile; planes read: sddc, vcenters, nsx, vcfa

  layer           cap                                                                  limit  release     read  used
  fleet           Number of Hosts in a VCF Fleet                                      50,000  9.1.0         11  0.02%
  fleet           Number of Hosts                                                        100  9.1.0         11  11.0%
  fleet           Number of VMs                                                        1,000  9.1.0         94  9.4%
  instance        ESXi Hosts                                                            5000  9.1.0          9  0.18%
  instance        vCenter Servers                                                         40  9.1.0          2  5.0%
  instance        VI Workload Domains                                                     39  9.1.0          1  2.56%
  workload domain ESXi Hosts                                                            2500  9.1.0          6  0.24%
  vCenter         Hosts per vCenter Server                                              2500  9.1.0          6  0.24%
  vCenter         Hosts per vCenter Server managed by vSphere Lifecycle Manager         1000  9.1.0          6  0.6%
  vCenter         Powered-on virtual machines per vCenter Server                       40000  9.1.0         45  0.11%
  vCenter         Registered virtual machines per vCenter Server                       45000  9.1.0         51  0.11%
  Supervisor      Maximum number of ESXi clusters enabled with vSphere with Kub           50  9.1.0          1  2.0%
  Supervisor      Maximum number of Namespace per vCenter                                500  9.1.0         14  2.8%
  Supervisor      Maximum number of vSphere Zones per Supervisor                          30  9.1.0          3  10.0%
  Supervisor      Maximum number of vSphere Zones per Supervisor namespace                 3  9.1.0
  Supervisor      Maximum number of hosts per WCP enabled cluster                         64  9.1.0
  Supervisor      Maximum number of worker nodes in a single vSphere Kubernetes          150  9.1.0
  Supervisor      Maximum number of vSphere Kubernetes clusters per Supervisor            93  9.1.0
  Supervisor      Maximum number of vSphere Kubernetes clusters that can be cre          190  9.1.0
  NSX             Projects                                                               500  9.1.0          6  1.2%
  NSX             System Wide VPCs                                                       120  9.1.0          7  5.83%
  NSX             Subnets                                                              1,024  9.1.0         24  2.34%
  NSX             Subnets per VPC                                               (not listed for this size)  9.1.0         11
  NSX             Transit Gateways                                              (not listed for this size)  9.1.0          6
  NSX             VPC per Transit Gateway                                                120  9.1.0
  VCF Automation  Organizations                                                         4000  9.1.1          7  0.17%
  VCF Automation  Projects across Organizations                                 10000 projects  9.1.1
  VCF Automation  Namespaces Across Organizations                               10000 namespaces  9.1.1          5  0.05%
  VCF Automation  Virtual Private Clouds                                               10000  9.1.1          5  0.05%
  VCF Automation  Region quota                                                          4000  9.1.1          4  0.1%
  VCF Automation  Regions per Organization                                      10 regions per Organization  9.1.1          1  10.0%
  VCF Automation  Users (max Users per Organization)                                    8000  9.1.1

  releases: ESX 9.1.0, HCX 9.1.0, NSX 9.1.0, Ops-for-Net 9.1.0, SDDC 9.1.0, SRM 9.1.1, VCF-Ops 9.1.0, VCFA 9.1.1, vCenter 9.1.0, vIDB 9.1.0, vSAN 9.1.1
wrote maximums.json; no host or object name is recorded
  not in your exports for these sizes: ['nsx-subnets-per-vpc', 'nsx-transit-gateways']
```

The two caps marked "not listed for this size" are absent from the 9.1.0 NSX export for a Medium singleton NSX Manager;
the counts beside them are printed so you can read them against the size you plan to move to.
