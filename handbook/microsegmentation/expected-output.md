# Expected output

What the two scripts printed on the reference estate on 2026-10-22: VCF 9.1.1, one organization, the region's
name replaced by a placeholder.

## `posture.py`, read-only, 2026-10-22T06:14:27Z

```
$ python3 posture.py
posture.py: what is attached, and what can this org actually enforce?

  1. ENTITLEMENT: 14 capability(ies) on this region, 14 enabled, 0 not

  2. THE STRATEGY LADDER: 5 strategy(ies), each with its own description
     none
       "'None' security strategy implies the attached VPC would not have any security strategy attached to it. This strategy will be marked as the 'Default' security strategy by the system by default"
     vpc-external-connectivity
       "Allow only Outgoing Communications, deny all incoming connections. VPC to VPC communication is blocked"
       rule templates: Allow-Essential-Services, Allow-OUT, Deny-All
     vpc-isolation
       "Deny any communication between VPCs within the project. All workloads within the VPC to be allowed to communicate"
       rule templates: Allow-within-VPC, Deny-All
     vpc-isolation-with-essential-services
       "Deny all communication to VPCs except for essential services like ICMP, DNS, NTP and DHCP. All workloads within the VPC to be allowed to communicate"
       rule templates: Allow-Essential-Services, Allow-within-VPC, Deny-All
     vpc-secure-connection
       "Allow all outgoing communications, deny incoming connections. Allow VPC to VPC within project"
       rule templates: Allow-Essential-Services, Allow_within_Project, Deny-All

  3. POSTURE: 1 VPC(s), 5 profile(s), 1 attachment(s)
     a VPC is attached to a profile carrying strategies ['none'], north-south firewall off
       the attachment carries NO status conditions, so there is nothing to verify it against: 'Realized' is not available on this kind
     4 profile(s) defined and attached to nothing
     0 of 5 profile(s) have the north-south firewall enabled

  4. THE FLOOR: 1 firewall section(s)
     1 of them came back from the LIST with no rules at all; the rules are on the single-object read, so every section is read by name
     a section at priority 2147483646, Realized=True, 5 of 5 rule(s) disabled
       default-ndp-rule-allow           Allow  disabled=True ipProtocol=IPV4_IPV6
       default-dhcp-rule-allow          Allow  disabled=True ipProtocol=IPV4_IPV6
       default-dhcpv6-rule-allow        Allow  disabled=True ipProtocol=IPV4_IPV6
       default-rule-allow               Allow  disabled=True ipProtocol=IPV4_IPV6
       default-rule-drop                Drop   disabled=True ipProtocol=IPV4_IPV6
       every rule in this section is disabled, so the floor enforces nothing whatever the actions say

  VERDICT: the posture chain reads, and its firewall capabilities are entitled on this org.

wrote posture.json; no VPC, profile, group or region name is recorded
```

It exited 0: the region's firewall capabilities are entitled. On 2026-09-20 the same read found four firewall
capabilities disabled for want of a license and exited 1; that record is `records/posture-2026-09-20.json`.

## `./run.sh round-trip`, on throwaway objects, 05:48Z

```
$ VCFA_REGION=<your-region> VCFA_CONTEXT=<org-gateway-context> ./run.sh round-trip
== 1. Create the group the rule will speak
networksecuritygroup.vpc.nsx.vmware.com/seg-proof-app serverside-applied
   OK: networksecuritygroup/seg-proof-app Realized

== 2. Land the section DISABLED (the reviewable document)
firewallpolicy.vpc.nsx.vmware.com/seg-proof-section serverside-applied
   OK: firewallpolicy/seg-proof-section Realized
   OK: rule is disabled, section is Realized: reviewed in place, altering nothing

== 3. The change under review is ONE field (diff of the two documents)
1,10c1,3
< # The firewall section, landed DISABLED. This is the reviewable document: one
< # rule allowing HTTPS between members of the proof group, scoped (appliedTo) to
< # that same group. Ship it, review it in place, then the enable is one field.
< #
< # Two admission facts a first write teaches (surfaced by live writes, never by
< # the docs; two more gateway behaviors are in the README):
< #   - Tenant-created rules accept ipProtocol IPV4 only; the platform's own
< #     default rules carry IPV4_IPV6, but that value is rejected on create.
< #   - Tenant priority must be 0-999999; the default section's max-int priority
< #     is a system special you cannot use.
---
> # The SAME section with the one field flipped. Diff this file against
> # 20-policy-disabled.yaml before applying: the change that alters traffic is a
> # single auditable field on a rule that was already reviewed in place.
27c20
<     disabled: true
---
>     disabled: false

== 4. Flip the enable (the change that alters traffic is one auditable field)
firewallpolicy.vpc.nsx.vmware.com/seg-proof-section serverside-applied
   OK: firewallpolicy/seg-proof-section Realized
   OK: rule is enabled and the section re-Realized

== 5. Read the section back the way an auditor would
NAME                REGION      RULE COUNT   STATUS     PRIORITY   AGE
seg-proof-section   <your-region>   1            Realized   900000     5s
   note: the LIST view trims rules[]; 'kubectl get firewallpolicy seg-proof-section -o yaml' shows the full rule grammar

== 6. Teardown (policy first, then the group it references)
firewallpolicy.vpc.nsx.vmware.com "seg-proof-section" deleted
networksecuritygroup.vpc.nsx.vmware.com "seg-proof-app" deleted
   OK: estate as it began

Round-trip complete: land disabled -> Realized -> one-field enable -> Realized -> teardown.
```

Both objects were deleted and a read afterwards found neither. The group had no members, so no traffic changed at
any step; enforcement on traffic is not what this run tests.
