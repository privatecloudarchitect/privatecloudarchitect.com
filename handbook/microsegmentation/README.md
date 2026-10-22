# Microsegmentation: posture audit, firewall-policy round-trip, traffic test

Backs the microsegmentation sheet
([privatecloudarchitect.com/handbook/microsegmentation](https://privatecloudarchitect.com/handbook/microsegmentation)).

Three pieces, and **run them in this order**:

- **`posture.py`** reads what your org's posture actually is and, before that, whether this region
  is entitled to enforce one at all. Read-only.
- **`run.sh`** proves the three write disciplines by round-tripping a rule. It writes (safely, and
  it tears down), and it cannot succeed where the firewall capabilities are not entitled. It does not test
  enforcement on traffic: its group has no members.
- **`traffic.py`** tests enforcement: two throwaway VMs in a throwaway namespace, a drop rule between them
  landed disabled, enabled by its one field, then disabled again, with the client's reach to the server read
  at each step. It writes more than `run.sh` and tears all of it down.

## posture.py: what is attached, and what the region is entitled to enforce

```bash
export VCFA_HOST=<your-org-gateway-fqdn> VCFA_ORG=<organization>
export VCFA_USER=<account> VCFA_PASSWORD_FILE=~/.secrets/vcfa   # mode 0600: a session login
# or instead: export VCFA_TOKEN_FILE=~/.secrets/vcfa-bearer      # mode 0600, a bearer for /cci/kubernetes
export VCFA_TLS_VERIFY=false        # only on a self-signed lab CA
python3 posture.py                  # writes posture.json beside the script
```

A secret file open to group or other is refused before it is read. A stored API token exchanged for a bearer
can stop granting, so the session login is the default.

Four reads, in the order that fails fastest:

1. **Entitlement.** `regionnetworkingcapabilities/<region>` carries a capability list: a type, a
   state, and where the state is false the platform's own reason and the licence it wants. **This
   is the pre-write read.** The chapter's `Realized` check verifies a write that was accepted; it
   cannot tell you a write was never going to be. On the reference estate on 2026-09-20 (VCF 9.1.0)
   four capabilities were unavailable and all four were firewall capabilities (distributed, VPC
   gateway, transit-gateway, and the security profile itself), while `NetworkSecurityGroup` was
   entitled: **the vocabulary a rule speaks worked, and every surface that could enforce a rule
   reported itself unentitled.** That read is kept as `records/posture-2026-09-20.json`. On
   2026-10-22 (VCF 9.1.1) the same region read every capability enabled, firewall included, while
   every object in the chain read the same as before; what changed it was not established. Read the
   list at every design and on every audit, not once.

   Shape detail: the capability list sits at the **top level** of the object, beside `metadata`, not
   under `spec` or `status` where a reader of this API looks first. Read the wrong key and the
   object looks like a region reporting nothing.

2. **The strategy ladder**, each with its description quoted verbatim. There is more than one
   isolation strategy and the difference between them is one clause: pure isolation denies the
   services a workload needs to function, and the essential-services rung carves out ICMP, DNS,
   NTP and DHCP. Paraphrasing a security description inside quotation marks publishes a different
   specification than the one the reviewer approves.

3. **Posture per VPC**: which profile each VPC is attached to, which strategies it carries, and
   whether its north-south dial is on. An unattached profile is a posture nobody is running. Note
   that `SecurityProfileAttachment` carries **no status conditions** on this build, so there is no
   `Realized` to verify an attachment against.

4. **The floor**: the default section's rules with the disabled flag on each. A second shape
   detail, and this one is about which call you make: the **collection view trims `rules[]`**, so a floor audited
   from the list reads as a section with no rules in it. `posture.py` reads every section by name.

`posture.py`'s exit codes: 0 the firewall capabilities are entitled; 1 a firewall capability is off, with the platform's own
reason; 2 a setting is missing or a secret file is open to group or other; 3 the sign-in or a read failed; 4 the
record refused to write because an estate value survived. Exit 1 is the one to page on from a schedule.

## run.sh: the write disciplines

The sheet teaches three write disciplines for firewall-as-code; this harness proves all three on
your own estate in about a minute, **where the capabilities allow it**:

1. **Ship disabled, enable deliberately.** The section lands with its rule `disabled: true`,
   gets reviewed in place, and the enable is a one-field flip you can diff before applying.
2. **Verify Realized before the next step.** Every step reads
   `status.conditions[type=Realized]` before proceeding. Realized verifies a write that was accepted; it
   says nothing about entitlement, which `posture.py` reads first, or about traffic.
3. **Rules speak groups.** The rule's from/to/appliedTo are a named group the harness creates
   and removes; no addresses anywhere.

## What it creates (and removes)

| Object | Kind | Why it is safe |
|---|---|---|
| `seg-proof-app` | `NetworkSecurityGroup` | carries no members, so it matches nothing |
| `seg-proof-section` | `FirewallPolicy` | one HTTPS allow rule, shipped disabled, `appliedTo` scoped to the empty group, priority 900000 (beneath everything you run) |

No traffic on your estate changes at any step. Teardown deletes both objects; run with `KEEP=1`
to keep them for inspection instead.

**If `Firewall.DistributedFirewall` is not entitled on your region, step 2 fails** with an HTTP 500
naming the licence, and the group from step 1 is the only thing that was created. Run `posture.py`
first and you will know before you start. Run against the reference estate on 2026-09-20, that is
exactly what happened: the group created and Realized in under five seconds, the section create
returned `operation not supported in Region <region>: NSX licenses must have all of [DFW]`, and the
teardown left no residue. On 2026-10-22, on VCF 9.1.1 with the region entitled, the round trip ran
end to end: both objects Realized at every step and a read afterwards found neither
([`expected-output.md`](expected-output.md)). Realized is the platform accepting the configuration;
with no members in the group, no packet met the rule. `traffic.py`, next, is the test with packets in it.

## traffic.py: does the rule stop traffic?

```bash
export VCFA_HOST=gw.example VCFA_ORG=<organization>
export VCFA_USER=<account> VCFA_PASSWORD_FILE=~/.secrets/vcfa    # mode 0600: a session login
# only with --attach-library, the workload domain's vCenter:
export VC_HOST=vc.example VC_USER=<account> VC_PASSWORD_FILE=~/.secrets/vc   # mode 0600
python3 traffic.py --project <a project to put the test in> --like <project>/<a namespace to copy>; echo "exit $?"
```

It copies the `--like` namespace's spec (class, region, VPC, service-engine group and limits) into a new namespace in
`--project`, so the test sits in the same VPC and under the same posture as the workloads it stands for. Then:

1. **Two small VMs.** A server answering HTTP on TCP 8080; a client that tries the server every second or two and
   writes curl's exit code into its own guestinfo. The client's readiness probe matches that key against `^0$`, so
   the client's `Ready` condition reads True while it reaches the server and False while it cannot.
2. **One group per VM**, each naming exactly that VM by instance UUID, and **one firewall policy**: drop, client to
   server, TCP 8080, IPV4, applied to those two groups only, in the Application category at priority 900000.
3. **The sequence.** The policy lands with its rule disabled and the traffic is watched for 30 seconds; the one field
   goes to enabled and the script times how long until the client loses the server, then watches 30 seconds more;
   the field goes back and it times how long until the client reaches it again.
4. **Teardown**, always, policy first, then groups, VMs and the namespace, then a residue read; with `VC_HOST` set,
   vCenter's list of namespaces is read too.

| Object | Kind | Why it is safe |
|---|---|---|
| `seg-proof-<suffix>` | `SupervisorNamespace` | new, in the project you name; the platform picks the suffix |
| `seg-proof-server`, `seg-proof-client` | `VirtualMachine` | the smallest class offered, in that namespace only |
| `seg-proof-server`, `seg-proof-client` | `NetworkSecurityGroup` | each names one of those two VMs and nothing else |
| `seg-proof-drop` | `FirewallPolicy` | one rule, scoped to the two groups, so no other traffic meets it |

Three things the reference estate taught it, each found by a run that failed first:

- **A namespace made through the API gets VM classes but may get no VM images.** The organization's library was
  not attached to the new namespace, and the tenant cannot attach it: creating the `ContentLibrary` object in the
  namespace is refused with 403. With `--attach-library` the script adds the library the `--like` namespace carries
  to the throwaway namespace alone, through vCenter's namespace setting; without it, it stops and names the missing attachment.
- **Guest operations on a VM service VM are refused**, even to vCenter's SSO administrator, so nothing here runs a
  command in a guest. The result travels out through guestinfo and the readiness probe instead.
- **A namespace deleted in its first moments can be left stranded**: deleted while the platform's own post-create
  update ran, it kept a deletion timestamp with no delete task, and vCenter kept running it, until a second delete.
  The script waits until the namespace is two minutes old, sends the delete again once if it is still there three
  minutes on, and records the namespace's task timeline.

Exit: 0 the rule stopped the traffic when enabled and released it when disabled; 1 it did not, and the record says
which step; 2 a setting is missing or a secret file is open to group or other; 3 a read or write failed, including no
image without `--attach-library`; 4 the record refused to write because an estate value survived. The record,
`traffic.json`, and every printed line carry labels in place of the project, namespace, user, organization and host
names, and no address or object id. The timings are upper bounds: the client tries every one to three seconds, the
probe reads every two and the script every two.

On the reference estate on 2026-10-22, on VCF 9.1.1, three runs gave the same verdict: the landed-disabled rule left
the traffic alone for 30 seconds, the enabled rule stopped it within 11, 9 and 10 seconds of the apply and held for
the next 30, and the disabled rule released it within 8, 4 and 11. Each run left no residue in VCF Automation or in
vCenter. The last run's output is in [`expected-output.md`](expected-output.md); the records are `traffic.json` and
the two under `records/`.

## Prereqs

A kubectl context named `vcfa-cci` at the org gateway with an org-admin **session** token
(same recipe as the isolation-design harness):

```bash
kubectl config set-cluster vcfa-cci --server=https://<vcfa-fqdn>/cci/kubernetes
kubectl config set-credentials vcfa-cci-user --token=<access-token>
kubectl config set-context vcfa-cci --cluster=vcfa-cci --user=vcfa-cci-user
```

The access token comes from the session login (`POST /cloudapi/1.0.0/sessions`); on an estate
with a self-signed CA add `--insecure-skip-tls-verify=true` to `set-cluster`. Then:

```bash
export VCFA_REGION=<your-region>     # kubectl --context vcfa-cci get regions
./run.sh round-trip
```

The verb is required: run without one (or with `--help`), the script prints its usage and changes nothing.
`./run.sh teardown` removes the two objects if a `KEEP=1` run left them in place.

`run.sh` substitutes `<your-region>` into working copies of the manifests; you can equally edit
the three files under `manifests/` directly and apply them by hand in order.

## Four gateway facts found by writing

All four surfaced by first-party writes on a live 9.1 estate on 2026-08-14, and the harness is built around
them. On 2026-09-20 the firewall create was refused for entitlement before most of them could be reached
again, and the 2026-10-22 round trip does not ask any of them again, so each carries the date it was last
confirmed:

- **Server-side dry-run is NOT dry on this plane.** `kubectl apply --dry-run=server` against
  `vpc.nsx` kinds at the org gateway **persists the object** when it passes NSX validation (the
  response still says "server dry run"; 2026-08-14, not testable on 2026-09-20). Do not use dry-run as a
  preview here. The review gate
  this plane actually gives you is the one the sheet teaches: land the document with its rule
  `disabled: true`, read it back, then flip the field.
- **Field managers are not persisted**, so every apply over an existing `vpc.nsx` object reports
  a conflict with `before-first-apply` even when your manager applied it seconds ago.
  `--force-conflicts` is the standard update idiom on this plane, not an override of another
  owner. (Creates apply cleanly either way.) 2026-08-14; `run.sh` always passes the flag, so its runs
  do not show the conflict.
- **Tenant rules accept `ipProtocol: IPV4` only.** The platform's own default rules carry
  `IPV4_IPV6`, but that value is rejected on a tenant create. Re-confirmed 2026-09-20: validation runs
  before the entitlement check, so the rejection still arrives first.
- **Tenant priority must be 0-999999.** The default section sits at max-int priority; that is a
  system special you cannot use. 2026-08-14; on 2026-09-20 the attempt met the entitlement refusal first,
  and on 2026-10-22 the harness's priority, 900000, was accepted, which says nothing of the bound.

One more read-path detail: the **list** view of `firewallpolicies` trims `rules[]` (you see
`RULE COUNT` but no rules). Fetch the single object (`-o yaml`) to see the full rule grammar.

## Expected output

See [`expected-output.md`](expected-output.md) for the three transcripts from the reference estate on 2026-10-22:
`posture.py` read-only, `./run.sh round-trip` on throwaway objects, and `traffic.py` on throwaway objects.

## Where a rule about a pod belongs

The objects above segment virtual machines at the VPC boundary. A rule about a **pod** has three
documented homes, and the choice is architectural rather than tactical. None of the three was
exercised here, so what follows is a reading of the published references: the VCF 9.0 administration
guide's procedure for converting Kubernetes network policies to distributed firewall policies, the
vDefend design library's page on securing VKS (linked from the sheet), and a practitioner's write-up
of Antrea's tiers:

| placement | what it is | what it costs |
|---|---|---|
| Firewall rules on the namespace's addresses | a rule per namespace, written against the addresses that namespace occupies | addresses again: it hard-codes today's allocation, which is why the sheet's rules speak groups |
| Convert Kubernetes NetworkPolicy to DFW | an import API takes policy UUIDs and produces vDefend DFW policies plus Antrea groups | documented as one-way, and the originals are deleted from the cluster on import |
| Antrea-native, with tiers | cluster and namespace policies evaluated on their own tier ladder inside the cluster | a second enforcement engine with a second precedence model |

Three things worth carrying from those references into any design:

- **The conversion is lossy in named ways.** Named ports, SCTP, and selector expressions past a
  documented complexity limit do not carry across, and the import runs either all-or-nothing or
  skip-and-continue depending on the error mode you pass.
- **A Kubernetes NetworkPolicy cannot express a default deny** the way a firewall section can.
  Closing an estate on the Antrea side takes a cluster-scoped policy on the baseline tier.
- **Allow DNS egress before the baseline deny lands.** It is the classic casualty: apply the deny
  first and every pod in the namespace loses name resolution at once.

## Precedence: which category your rules land in

**The invisibility is measurable; the ordering is not, from here.** On a 9.1 estate a tenant token
lists exactly one firewall policy, the VPC default section, and the transit-gateway and VPC-gateway
firewall collections return HTTP 200 with no items at all; read again on 9.1.1 on 2026-10-22 with the
region entitled, the same. So a tenant-side audit is structurally
partial: correct about the level it covers, silent about everything above it, with nothing in the
response marking the gap.

The **ordering** is doc-tier and it is a ladder of policy **categories**, not of spaces: rules evaluate
**Infrastructure** (highest, the provider's, in the infra space), then **Environment** (the project
administrator's, covering inter-VPC and north-south on the transit gateway), then **Application**
(lowest, the VPC administrator's). The one policy a tenant can see here reads `category: Application`,
which is exactly where the role model puts it, and the guidance states that rules in the two higher
categories are not visible to a VPC administrator.

The categories are bridged on purpose: a **Jump to Application** action lets a permissive rule above
hand evaluation down, which is why every permissive rule template in the shipped security strategies
carries `"action": "JumpToApplication"` and how a tenant gets to layer restrictions underneath a
provider's allow.

## Version currency

This estate runs 9.1.1, and the product has been renamed: what older corpuses call the NSX distributed
firewall is documented on the current line as **vDefend Firewall**. Two 9.1 changes matter to anyone
who hits the entitlement refusal above:

- **Licensing changed shape.** Subscription-based licence files replace the 25-character keys, and
  usage is submitted from License Hub on a 180-day cadence. An entitlement gap on 9.1 is therefore
  not always a purchase; it can be a licence that was never re-registered under the new model.
- **The firewall can be enabled per cluster.** 9.1 added per-cluster distributed firewall
  enablement, so a cluster can sit outside the firewall's scope for a reason unrelated to licensing.
  Read the capability list first, then work out which of the two you are looking at.
