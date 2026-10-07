# Expected output

Runs against the reference estate on 2026-10-07 (VCF 9.1, one Supervisor on a VPC-networked NSX), with `--scrub`,
so every estate name is a placeholder. The Supervisor Service identifiers are the product's own and are kept.

## origins.py, the estate as it stands

```text
namespace origins, read 2026-10-07T18:56:08Z: 12 namespace(s) on 1 Supervisor(s)

  {{namespace-1}}   automation   Automation record, {{organization-1}}/{{project-1}}; VPC in the organization's project
  {{namespace-2}}   automation   Automation record, {{organization-1}}/{{project-1}}; VPC in the organization's project
  {{namespace-3}}   automation   Automation record, {{organization-1}}/{{project-1}}; VPC in the organization's project
  {{namespace-4}}   automation   Automation record, {{organization-1}}/{{project-1}}; VPC in the organization's project
  {{namespace-5}}   automation   Automation record, {{organization-1}}/{{project-1}}; VPC in the organization's project
  {{namespace-6}}   service      Supervisor Service auto-attach.vksm.broadcom.com
  {{namespace-7}}   service      Supervisor Service cci-ns.vmware.com
  {{namespace-8}}   service      Supervisor Service configuration.vsphere.vmware.com
  {{namespace-9}}   service      Supervisor Service consumption-operator.dsm.vsphere.vmware.com
  {{namespace-10}}  service      Supervisor Service metrics-aggregator.vmware.com
  {{namespace-11}}  service      Supervisor Service tkg.vsphere.vmware.com
  {{namespace-12}}  service      Supervisor Service velero.vsphere.vmware.com

  5 automation, 7 service, 0 supervisor, 0 orphan, 0 record-only

  0 check(s) failing
```

Five namespaces were created through VCF Automation: it holds their records, vCenter's system metadata names the
same organization and project, and each one's VPC sits in the organization's NSX project. Seven belong to the
Supervisor Services. None was created on the Supervisor itself.

## origins.py beside a throwaway created on the Supervisor

One namespace was created through vCenter's API at 19:24:33Z (`POST /api/vcenter/namespaces/instances/v2` with a
name, the Supervisor and one zone; no storage, classes, library or access entries) and reached `RUNNING` in 11
seconds. Before the create, the Supervisor read `RUNNING`, with no upgrade in flight, and its one condition was a
warning that a load-balancer CRD-operator system pod was not running.

```text
namespace origins, read 2026-10-07T19:25:37Z: 13 namespace(s) on 1 Supervisor(s)

  {{namespace-1}}   automation   Automation record, {{organization-1}}/{{project-1}}; VPC in the organization's project
  {{namespace-2}}   automation   Automation record, {{organization-1}}/{{project-1}}; VPC in the organization's project
  {{namespace-3}}   automation   Automation record, {{organization-1}}/{{project-1}}; VPC in the organization's project
  {{namespace-4}}   automation   Automation record, {{organization-1}}/{{project-1}}; VPC in the organization's project
  {{namespace-5}}   automation   Automation record, {{organization-1}}/{{project-1}}; VPC in the organization's project
  {{namespace-6}}   service      Supervisor Service auto-attach.vksm.broadcom.com
  {{namespace-7}}   service      Supervisor Service cci-ns.vmware.com
  {{namespace-8}}   service      Supervisor Service configuration.vsphere.vmware.com
  {{namespace-9}}   service      Supervisor Service consumption-operator.dsm.vsphere.vmware.com
  {{namespace-10}}  service      Supervisor Service metrics-aggregator.vmware.com
  {{namespace-11}}  service      Supervisor Service tkg.vsphere.vmware.com
  {{namespace-12}}  service      Supervisor Service velero.vsphere.vmware.com
  {{namespace-13}}  supervisor   no Automation record, no metadata; a VPC created for it in the Supervisor's default project

  5 automation, 7 service, 1 supervisor, 0 orphan, 0 record-only

  0 check(s) failing
```

The throwaway is `{{namespace-13}}`: VCF Automation holds no record of it, vCenter carries no system metadata and no
creator for it, its access list holds only the two reserved groups, and its VPC was created for it in the
Supervisor's default NSX project.

With an origin record that has no row for it, the check fails (exit 1):

```text
  5 automation, 7 service, 1 supervisor, 0 orphan, 0 record-only

  [FAIL] {{namespace-13}}: created on the Supervisor, and your origin record has no row for it
  1 check(s) failing
```

With a row saying it is provisional and naming who may make it permanent, the check holds (exit 0):

```text
  {{namespace-13}}  supervisor   no Automation record, no metadata; a VPC created for it in the Supervisor's default project; provisional: yes, decider {{decider-1}}

  0 check(s) failing
```

## What the create made, and what the delete left

The create made, in vCenter, the namespace, two folders and a resource pool; in NSX, a VPC in the Supervisor's
default project with a services subnet, an attachment to the default connectivity profile, its NAT sections and
default SNAT rule, an SNAT address allocation, an address pool, a default group and a security profile attachment,
plus an address block and a share under `/infra` and one container project. `origins.json` lists them by type.

The namespace was deleted at 19:35:42Z (`DELETE /api/vcenter/namespaces/instances/{namespace}`) and was gone 34
seconds later. Read back after that: vCenter's namespaces, folders and resource pools, every NSX policy object
under `/orgs/default` (295 before, 295 after), every NSX object carrying the name, and VCF Automation's namespace
records were identical to the read taken just before the create.
