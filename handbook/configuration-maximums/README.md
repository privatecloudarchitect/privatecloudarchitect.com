# How close is your VCF 9.1 estate to the maximums that bind it first?

Companion to field note 18
([privatecloudarchitect.com/notes/configuration-maximums](https://privatecloudarchitect.com/notes/configuration-maximums)):
one read-only script that takes the CSV exports you download from Broadcom's Configuration Maximums tool, picks the caps
that bound a private cloud's construct ladder for the sizes you deployed, reads the estate's own counts, and prints how
much of each cap is used. Stdlib Python only; no token or password is printed or written.

**The tool is the authority.** Broadcom's VMware Configuration Maximums tool at configmax.broadcom.com publishes the
caps; this script only reads the exports you take from it, and the record here is a snapshot of the exports of
2026-10-23. Export again before you rely on a figure, for the release and the sizes you run.

| File | What it is |
|---|---|
| `maximums.py` | Reads the exports (one CSV per product), selects about thirty caps by the export's own row names and your sizes, and, for each plane whose settings you give it, reads SDDC Manager, vCenter, NSX and the VCF Automation provider plane with GETs only. Prints the caps with their release, the count read and the share used, and writes `maximums.json`. |
| `maximums.json` | That record from the reference estate. The field note renders it. |
| `expected-output.md` | The printed table from the same run. |

## Get the exports

Open the VMware Configuration Maximums tool at configmax.broadcom.com, choose each product and its release, and export
the table as CSV. Put every file in one folder. The script recognizes the product from the file name (SDDC, vCenter,
ESX, NSX, VCFA, vSAN and the others the tool offers) and reads the release and the download time from the file's own last
lines, so a file's name never decides its release. The tool may list an older release than the one you run for some
products: on 2026-10-23 it offered 9.1.0 for eight products and 9.1.1 for VCF Automation, vSAN and Site Recovery Manager.
Every cap this script prints carries the release it came from.

## Run it

```bash
python3 maximums.py --exports ~/configmax                    # the caps only, no estate read

export TLS_VERIFY=false                                       # only on a self-signed lab CA
export SDDC_HOSTS=<sddc-1>,<sddc-2>   SDDC_TOKEN_FILES=/path/to/bearer-1,/path/to/bearer-2   # one per instance, mode 0600
export VC_HOSTS=<vc-1>,<vc-2>         VC_USER=<account>    VC_PASSWORD_FILE=/path/to/password  # or one of each per host
export NSX_HOSTS=<nsx-1>,<nsx-2>      NSX_TOKEN_FILES=/path/to/bearer-1,/path/to/bearer-2     # one per manager
export VCFA_HOST=<automation-fqdn>    VCFA_PROVIDER_REFRESH_TOKEN_FILE=/path/to/provider-api-token

python3 maximums.py --exports ~/configmax --fleet simple --nsx medium-singleton --edge medium --vcfa medium --warn 70
```

Each plane is read only when its settings are present, so you can start with one. A secret file open to group or other
is refused unread.

## The sizes decide the caps

Most caps depend on what you deployed, and the export lists them by size. Tell the script your sizes in the export's terms:

| Flag | Values | What it selects |
|---|---|---|
| `--fleet` | `simple`, `medium-ha`, `large-ha` | the VCF Installer deployment model's hosts and VMs for the whole fleet |
| `--nsx` | `medium`, `large`, `extra-large`, each `-singleton` or `-clustered` | an NSX Manager's projects, VPCs, subnets and transit gateways |
| `--edge` | `medium`, `large`, `extra-large`, `bare-metal` | VPCs per transit gateway |
| `--vcfa` | `medium`, `large` | VCF Automation's organizations, namespaces, VPCs and quotas |

The 9.1 fleet sizing models page pairs them: the simple model runs one Medium NSX Manager and one Small VCF Automation node,
and the high-availability models run three of each at Medium or Large. The export lists VCF Automation caps for the Medium
and Large profiles only; for a Small node it lists none, so read against Medium knowing that is the smallest the export
names. Where the export does not list a cap for your size (on 2026-10-23, subnets per VPC and transit gateways for a
Medium singleton NSX Manager), the script prints "not listed for this size" and never borrows another size's figure.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Every cap read is under `--warn`. Caps the exports do not list for your sizes are printed, not failed |
| 1 | A cap is at or over `--warn` |
| 2 | A setting is missing, a secret file is open to group or other, or no export was found |
| 3 | A read failed; the plane is named |
| 4 | The record refused to write because a host or account name survived the labels |
| 5 | An unknown or incomplete argument |

## What each count is

- **Fleet hosts** add up every instance read; **fleet VMs** add up every VM each vCenter registers, the platform's own
  appliances included.
- **Per instance, per workload domain, per vCenter and per manager** counts are the largest found among those read, so a
  cap reads against your busiest instance, vCenter or NSX Manager.
- **Namespaces per vCenter** counts every namespace vCenter lists, the Supervisor's service namespaces included, which is
  the conservative reading; VCF Automation's namespace count is only the namespaces it manages.
- **VPCs, subnets and transit gateways** are counted per NSX Manager across all its projects, the default project included.
- Caps with nothing to count against from these reads (vSphere Kubernetes Service clusters and nodes, hosts per Supervisor
  cluster, users per organization, projects across organizations) are printed with no count.

## Scope, stated plainly

- **Read-only.** Every call is a GET, apart from a vCenter session opened and closed and the provider token exchanged.
- **The caps are Broadcom's, as exported.** The script quotes them; it does not interpret a cap's conditions. A row whose
  limit is text rather than a number (VCF Automation's per-project user rows, for instance) is printed as written and given
  no share.
- **Some caps move with another component's release.** The vSphere Kubernetes Service 3.7 release notes raise a cluster's
  worker nodes from 150 to 250, under conditions they list, and allow five control-plane nodes, while the 9.1.0 export says
  150 and 3. Read the release notes of the VKS version you run before relying on either.
- **One reading of each count.** A count is what the estate held when the script ran; it does not trend.
- **Every host name in the record is a label**, and the script refuses to write a record in which one survived.
