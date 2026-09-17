# What `network.py` prints

One VCF 9.1 organization, 2026-09-17. Your counts will differ; the shapes should not.

The addresses below are documentation ranges. The script discovers every distinct network as it reads, assigns
each one a range reserved for documentation at the same prefix length, and names none of them in its own source.
It prints your real ranges on screen and substitutes only in the records it writes, so what you see when you run
it will be yours.

```
network.py: the network plane, read from the platform through the Cloud Consumption Interface

  catalog: 54 networking kinds across 3 groups; 46 of them in the VPC group alone
     the chain                   8 kinds, 7 with anything on this estate
     addressing                  6 kinds, 3 with anything on this estate
     security                    8 kinds, 6 with anything on this estate
     routing and translation     4 kinds, 2 with anything on this estate
     site to site                6 kinds, 3 with anything on this estate
     limits and capability       4 kinds, 4 with anything on this estate
     services                    3 kinds, 2 with anything on this estate
     bound under a project       3 kinds, 0 with anything on this estate
     the write surface           4 kinds, 0 with anything on this estate

  the chain: 3 IP block(s), 1 VPC(s), 1 connectivity profile(s), 1 transit gateway(s), 1 gateway connection(s)
     block  ['198.18.0.0/16']      visibility=External  systemOwned=False
     block  ['192.0.2.0/16']      visibility=Private   systemOwned=True
     block  ['198.51.100.0/16']      visibility=Private   systemOwned=False
     transit gateway carries its own space: ['198.19.0.0/21']

  subnets: 3; the platform documents 3 access modes: Public, PrivateTGW, Private

  the isolation dial: 5 strategies the platform ships, 5 profiles in this region
     none                                     0 rule(s) [no rules]
     vpc-external-connectivity                3 rule(s) [Drop/JumpToApplication]
     vpc-isolation                            2 rule(s) [Drop/JumpToApplication]
     vpc-isolation-with-essential-services    3 rule(s) [Drop/JumpToApplication]
     vpc-secure-connection                    3 rule(s) [Drop/JumpToApplication]
     ATTACHED: the VPC runs the none strategy

  egress: 1 translation rule(s), 1 allocated address(es), 415 predefined services rules can name
     SNAT 192.0.2.0/16 -> 198.18.0.0 (system owned: True)
     the gateway advertises private space: False; its own SNAT: False
```

## Reading it

**The catalog.** Forty-six kinds in one group is more than anyone holds in their head, and the second number
in each family row is why that is fine: most of the declared surface has nothing on it. The two rows worth
pausing on are `bound under a project`, which is the only place a tenant creates anything, and
`the write surface`, which exists because the group declares read and write as separate kinds.

**The chain.** Three blocks, and the `visibility` on each is what the connectivity profile turns into a
purpose. One is External, one is the VPC's own Private space and is system owned, and one is the Private block
the transit gateway draws from. The transit gateway's own space is separate again, which is why a capture
between two of your own workloads can show a range you do not recognize.

**The subnets.** The access mode on a subnet decides two things at once: how far it can be reached, and which
of those blocks its addresses come from. Auditing what the outside can reach is therefore one read filtered on
`accessMode == "Public"`, not a routing exercise.

**The dial.** Five strategies, ordered here alphabetically rather than by strictness. From most open to most
closed they run: `none`, `vpc-secure-connection`, `vpc-external-connectivity`,
`vpc-isolation-with-essential-services`, `vpc-isolation`. Each carries rule templates whose group names are
substituted when the strategy is attached, and every one but `none` ends in a drop, so its other rules are the
whole of what is permitted.

**Egress.** The whole VPC translates to a single external address by a rule the system created, and the
gateway connection advertises the external block while leaving private space unannounced. Per-workload source
attribution outside the VPC does not exist, whatever a downstream log appears to show.

## What this does not tell you

- Whether a VPC per tenant or an NSX project per organization is the right shape. That is a design decision the
  chapter's last plate covers, and no read answers it.
- What is reachable inside the VPC. Every position on the dial lets workloads inside a VPC talk to each other;
  segmentation within the boundary is a different control and a different chapter.
- The pod and service ranges your Kubernetes clusters use. Those are declared per cluster and are not drawn from
  any block above, so nothing in this plane holds a register of them and two clusters may pick the same range.
