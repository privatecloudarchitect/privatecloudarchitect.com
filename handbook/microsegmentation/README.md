# Microsegmentation: posture audit + firewall-policy round-trip

Backs the microsegmentation sheet
([privatecloudarchitect.com/handbook/microsegmentation](https://privatecloudarchitect.com/handbook/microsegmentation)).

Two pieces, and **run them in this order**:

- **`posture.py`** reads what your org's posture actually is and, before that, whether this region
  can enforce one at all. Read-only.
- **`run.sh`** proves the three write disciplines by round-tripping a rule. It writes (safely, and
  it tears down), and it cannot succeed where the firewall capabilities are not entitled.

## posture.py: what is attached, and what can be enforced

```bash
export VCFA_HOST=<your-org-gateway-fqdn>
export VCFA_TOKEN=<a bearer for /cci/kubernetes>
export VCFA_TLS_VERIFY=false        # only on a self-signed lab CA
python3 posture.py                  # writes posture.json beside the script
```

Four reads, in the order that fails fastest:

1. **Entitlement.** `regionnetworkingcapabilities/<region>` carries a capability list: a type, a
   state, and where the state is false the platform's own reason and the licence it wants. **This
   is the pre-write read.** The chapter's `Realized` check verifies a write that was accepted; it
   cannot tell you a write was never going to be. On the reference estate four capabilities are
   unavailable and all four are firewall capabilities (distributed, VPC gateway, transit-gateway,
   and the security profile itself), while `NetworkSecurityGroup` is entitled: **the vocabulary a
   rule speaks works, and every surface that could enforce a rule does not.**

   Shape trap: the capability list sits at the **top level** of the object, beside `metadata`, not
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

4. **The floor**: the default section's rules with the disabled flag on each. Shape trap, and this
   one is about which call you make: the **collection view trims `rules[]`**, so a floor audited
   from the list reads as a section with no rules in it. `posture.py` reads every section by name.

Exit code 0 when the firewall capabilities are entitled, 1 when they are not.

## run.sh: the write disciplines

The sheet teaches three write disciplines for firewall-as-code; this harness proves all three on
your own estate in about a minute, **where the capabilities allow it**:

1. **Ship disabled, enable deliberately.** The section lands with its rule `disabled: true`,
   gets reviewed in place, and the enable is a one-field flip you can diff before applying.
2. **Realized is the only status that counts.** Every step verifies
   `status.conditions[type=Realized]` before proceeding.
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
first and you will know before you start. Re-run against the reference estate on 2026-09-20, that
is exactly what happened: the group created and Realized in under five seconds, the section create
returned `operation not supported in Region <region>: NSX licenses must have all of [DFW]`, and the
teardown left no residue.

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
./run.sh
```

`run.sh` substitutes `<your-region>` into working copies of the manifests; you can equally edit
the three files under `manifests/` directly and apply them by hand in order.

## Four gateway facts the docs will not tell you

All four surfaced by first-party writes on a live estate; the harness is built around them:

- **Server-side dry-run is NOT dry on this plane.** `kubectl apply --dry-run=server` against
  `vpc.nsx` kinds at the org gateway **persists the object** when it passes NSX validation (the
  response still says "server dry run"). Do not use dry-run as a preview here. The review gate
  this plane actually gives you is the one the sheet teaches: land the document with its rule
  `disabled: true`, read it back, then flip the field.
- **Field managers are not persisted**, so every apply over an existing `vpc.nsx` object reports
  a conflict with `before-first-apply` even when your manager applied it seconds ago.
  `--force-conflicts` is the standard update idiom on this plane, not an override of another
  owner. (Creates apply cleanly either way.)
- **Tenant rules accept `ipProtocol: IPV4` only.** The platform's own default rules carry
  `IPV4_IPV6`, but that value is rejected on a tenant create.
- **Tenant priority must be 0-999999.** The default section sits at max-int priority; that is a
  system special you cannot use.

One more read-path detail: the **list** view of `firewallpolicies` trims `rules[]` (you see
`RULE COUNT` but no rules). Fetch the single object (`-o yaml`) to see the full rule grammar.

## Expected output

See [`expected-output.md`](expected-output.md) for the transcript shape a healthy run produces.

## Where a rule about a pod belongs

The objects above segment virtual machines at the VPC boundary. A rule about a **pod** has three
documented homes, and the choice is architectural rather than tactical. None of the three was
exercised here (the firewall capabilities on the reference estate are not entitled), so what follows
is a reading of the published references, each of which is linked from the sheet:

| placement | what it is | what it costs |
|---|---|---|
| Firewall rules on the namespace's addresses | a rule per namespace, written against the addresses that namespace occupies | addresses again: it hard-codes today's allocation, which is the failure the sheet opens on |
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
firewall collections return HTTP 200 with no items at all. So a tenant-side audit is structurally
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

This estate runs 9.1, and the product has been renamed: what older corpuses call the NSX distributed
firewall is documented on the current line as **vDefend Firewall**. Two 9.1 changes matter to anyone
who hits the entitlement refusal above:

- **Licensing changed shape.** Subscription-based licence files replace the 25-character keys, and
  usage is submitted from License Hub on a 180-day cadence. An entitlement gap on 9.1 is therefore
  not always a purchase; it can be a licence that was never re-registered under the new model.
- **The firewall can be enabled per cluster.** 9.1 added per-cluster distributed firewall
  enablement, so a cluster can sit outside the firewall's scope for a reason unrelated to licensing.
  Read the capability list first, then work out which of the two you are looking at.
