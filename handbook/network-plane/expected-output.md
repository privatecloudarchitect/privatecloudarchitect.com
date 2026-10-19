# What `network.py` prints

Run against one VCF Automation 9.1.1.0100 organization on 2026-10-19, signed in with a session login, with
`--publishable`, so every address below is the documentation range the records carry in place of the estate's
own. Without the flag your own ranges print on screen; the records are substituted either way. Your counts will
differ; the shapes should not.

```
network.py: the network plane, read from the platform through the Cloud Consumption Interface

  catalog: 55 networking kinds across 3 groups; 47 of them in the VPC group alone
     the chain                   9 kinds, 7 with anything on this estate
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
     {{netobj-11}}                              accessMode=Public      VLAN
     {{netobj-12}}                              accessMode=Public      VLAN
     {{netobj-13}}                              accessMode=Private     overlay

  the isolation dial: 5 strategies the platform ships, 5 profiles in this region
     none                                     0 rule(s) [no rules]
     vpc-external-connectivity                3 rule(s) [Drop/JumpToApplication]
     vpc-isolation                            2 rule(s) [Drop/JumpToApplication]
     vpc-isolation-with-essential-services    3 rule(s) [Drop/JumpToApplication]
     vpc-secure-connection                    3 rule(s) [Drop/JumpToApplication]
     ATTACHED: the VPC's profile carries none (the default profile)
     the region: 14 networking capabilities, 0 not enabled

  egress: 1 translation rule(s), 1 allocated address(es), 415 predefined services rules can name
     the interface documents 5 NAT actions, and declares create on rules: True, on address allocations: True
     SNAT 192.0.2.0/16 -> 198.18.0.0 (system owned: True)
     the gateway advertises private space: False; its own SNAT: False

  the walk, from each VPC's subnets outward:
     3 subnet(s) -> VPC {{netobj-4}} -> attachment {{netobj-14}} -> profile {{netobj-5}} -> transit gateway {{netobj-5}} -> attachment {{netobj-15}} -> gateway connection {{netobj-6}}

wrote network-model.json (55 kinds, 5 strategies) and chain.json (3 blocks, 3 subnets); every organization name replaced by a placeholder
```

## What each block tells you

- **catalog**: the networking kinds the build declares, the VPC group's held as families, and how many in each
  family have anything on the estate. A kind the grouping does not know is printed by name.
- **the chain**: the IP blocks with the visibility each carries, and the transit gateway's own space.
- **subnets**: each subnet's access mode and backing, and the access modes the subnet schema documents.
- **the isolation dial**: the strategies the platform ships, the strategy the attached profile carries (read
  from the profile's `eastWestFirewall.securityStrategies`), and the region's networking capabilities, any that
  are not enabled printed with the reason.
- **egress**: the translation rule and the address it maps onto, the NAT actions the schema documents, the verbs
  the interface declares on rules and address allocations (a declared verb is not a permission), and the gateway
  connection's two switches.
- **the walk**: per VPC, its subnets and each link outward to the gateway connection. A missing link prints in
  capitals, and it is the first place to look when something cannot connect.
