# Expected output

A healthy `./run.sh` produces this shape (object ages and your region name will differ):

```
== 1. Create the group the rule will speak
networksecuritygroup.vpc.nsx.vmware.com/seg-proof-app serverside-applied
   OK: networksecuritygroup/seg-proof-app Realized

== 2. Land the section DISABLED (the reviewable document)
firewallpolicy.vpc.nsx.vmware.com/seg-proof-section serverside-applied
   OK: firewallpolicy/seg-proof-section Realized
   OK: rule is disabled, section is Realized: reviewed in place, altering nothing

== 3. The change under review is ONE field (diff of the two documents)
1,11c1,3
< # The firewall section, landed DISABLED. ...
---
> # The SAME section with the one field flipped. ...
27c19
<     disabled: true
---
>     disabled: false

== 4. Flip the enable (the change that alters traffic is one auditable field)
firewallpolicy.vpc.nsx.vmware.com/seg-proof-section serverside-applied
   OK: firewallpolicy/seg-proof-section Realized
   OK: rule is enabled and the section re-Realized

== 5. Read the section back the way an auditor would
NAME                REGION     RULE COUNT   STATUS     PRIORITY   AGE
seg-proof-section   <region>   1            Realized   900000     15s
   note: the LIST view trims rules[]; 'kubectl get firewallpolicy seg-proof-section -o yaml' shows the full rule grammar

== 6. Teardown (policy first, then the group it references)
firewallpolicy.vpc.nsx.vmware.com "seg-proof-section" deleted
networksecuritygroup.vpc.nsx.vmware.com "seg-proof-app" deleted
   OK: estate as it began

Round-trip complete: land disabled -> Realized -> one-field enable -> Realized -> teardown.
```

The diff in step 3 shows header-comment lines plus exactly one spec change: `disabled: true`
to `disabled: false`. That single field is the change that would alter traffic on a member-
carrying group; everything else was already reviewed in place.

If you re-run against objects left by `KEEP=1`, the applies still succeed: the gateway does not
persist field managers, and `--force-conflicts` (which the script always passes) is the standard
update idiom on this plane. See the README's gateway facts.
