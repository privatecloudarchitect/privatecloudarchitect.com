# Walk the capacity ladder: is every layer's gate true, and what is left behind?

Companion to field note 07
([privatecloudarchitect.com/notes/capacity-in-and-out](https://privatecloudarchitect.com/notes/capacity-in-and-out)):
one read-only script that walks the layers a platform team owns, from workload domain to tenancy, prints each
layer's gate, and reports the residue that blocks the next join or the next leave. Stdlib Python only; no token
or password is printed or written.

| File | What it is |
|---|---|
| `ladder.py` | Reads workload domains on SDDC Manager, every Supervisor on the vCenters you name (zones with their type and drain state, service against tenant namespaces, and who holds the Supervisor's single external identity provider slot), the Automation provider plane (registered SDDC Managers, vCenters, NSX Managers, regions, zones, provider gateways, IP blocks), every organization with what it still holds, and the unmanaged VM list Automation offers for each vCenter. Prints the ladder with a PASS or FAIL per gate. Writes `ladder.json`, and refuses to write a record carrying an estate name. |
| `ladder.json` | That record from the reference estate, 2026-09-29. The field note renders it. |
| `expected-output.md` | The printed ladder from the same run. |

## Run it

```bash
export SDDC_HOST=<sddc-manager-fqdn>
export SDDC_TOKEN_FILE=/path/to/bearer                  # mode 0600
export VCENTER_HOSTS=<vcenter-fqdn>,<vcenter-fqdn>      # every vCenter whose Supervisors you want read
export VCENTER_USER=<user>
export VCENTER_PASSWORD_FILE=/path/to/password          # mode 0600; the script opens a session and closes it
# or, instead of user and password, an existing session for one vCenter (left open, it is yours):
# export VCENTER_SESSION_FILE=/path/to/session-id
export VCFA_HOST=<automation-fqdn>
export VCFA_PROVIDER_TOKEN_FILE=/path/to/bearer         # a provider administrator's bearer, mode 0600
export TLS_VERIFY=false                                 # only on a self-signed lab CA

python3 ladder.py        # exit 0: every gate true, no residue; exit 2: something to fix; exit 1: an error
```

The provider plane (regions, quotas across organizations, the unmanaged VM lists) is only readable by a provider
administrator, which is why this takes a provider bearer rather than a tenant one.

## What each gate means

| Layer | Gate | Why it matters |
|---|---|---|
| L1 workload domains | every domain `ACTIVE` | nothing joins on top of a domain mid-operation |
| L3 Supervisors | `RUNNING` and `READY` | the region and every namespace sit on it |
| L3 Supervisors | no zone left half-drained | a zone marked for removal refuses new and restarting workloads and deletes itself only once empty; tenant namespaces still on it are the drain in progress |
| L3 Supervisors | identity slot held by Automation or empty | a Supervisor takes one external identity provider and refuses a second; on the reference estate Automation holds that slot. At which step of region onboarding it registers was not observed |
| L4 provider plane | every region `READY` | a region is one NSX Manager and its Supervisors; the vendor documentation says its name and NSX Manager cannot be edited |
| L5 tenancy | no disabled organization still holding capacity or networking | disabling an organization releases nothing: its quota keeps the Supervisor pinned in the region, and its networking and VPC stay realized |

The unmanaged VM lists are reported rather than gated: the count per vCenter, how many of the records are the
platform's own machines by name (Supervisor control plane, load balancer engines, NSX Edges), and the fields each
record carries. Those fields hold no marker that separates a workload from a platform machine, so build an import
candidate list from vCenter facts, never from this list.

## Scope, stated plainly

- Read-only. Nothing here imports, drains, unbinds, disables or deletes anything.
- It reads one SDDC Manager per run. Run it once per VCF instance.
- The platform's own machines are recognized **by name** in the unmanaged lists, and only for the three kinds
  named above. Pods of Supervisor services and Kubernetes nodes also appear in those lists and are not counted as
  platform machines here, because nothing in the record identifies them.
- Every estate name in the record is a placeholder, and the script refuses to write a record in which one
  survived. Statuses, types and layer names are the product's own words and are kept.

## Reading the record

`layers` holds one entry per layer read. `L1 workload domains` lists each domain's type, status, cluster count,
NSX Manager and whether it shares the management domain's SSO domain. `L3 Supervisors` carries each Supervisor's
zones (type, status, `markedForRemoval`, tenant and service namespaces), its identity providers and how many of
them are this Automation. `L4 provider plane` counts the registered estate and lists each region with its one NSX
Manager; a region whose `nsx` placeholder matches a domain's is that domain's region. `L5 tenancy` lists each
organization, whether it is enabled, and what it `holds` (quotas, regional networking, VPCs, namespaces), with
`residue` naming the disabled ones that still hold something. Every layer carries its `gates`.
