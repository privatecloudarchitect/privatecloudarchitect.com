# Your organization is VM Apps? The same habits, in its dialect, and where it ends

This series is written for an **All Apps** organization: every stage declares its machine as an object in a Supervisor
namespace, and the same dialect carries you from one VM to Kubernetes. Some organizations are **VM Apps**: the Aria
Automation lineage of cloud accounts, cloud zones, image and flavor mappings, and `Cloud.vSphere.Machine`. An upgrade
from Aria Automation 8.18 lands in one. This branch teaches the series' first habits in that dialect, stage for stage,
so that nothing you learn here has to be unlearned when your organization adds All Apps. It is deliberately short: it
ends where VM Apps ends, and its last section is the way across.

## Which one is yours

Your provider administrator knows. An organization that came from an upgrade is VM Apps: Broadcom's documentation, as
[field note 04](https://privatecloudarchitect.com/notes/aria-automation-8-18-to-vcf-automation-9-1-1) quotes it, says
an upgraded Aria Automation 8.x deployment's organizations "are automatically mapped to VCF Automation for VM Apps
organizations". If you already call your organization's API with a bearer, one read tells you:

```bash
curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $TOKEN" https://<automation-fqdn>/iaas/api/projects
```

`200` is a VM Apps organization; an All Apps organization answers `403`. Both answers were read on VCF Automation
9.1.1 on 2026-11-12. On 9.1.0, G-259 found the whole `/iaas` plane answering `403` in an All Apps organization, for
every identity. If yours is All Apps, go back to the
[series](../README.md): everything there is for you.

## The ladder

Read each spine stage first. The V-template's header says only what differs; the idea is taught once, in the spine.

| V-stage | The spine stage it mirrors | What the stage adds | What is different in VM Apps |
|---|---|---|---|
| [V01 One machine](V01-single-vm/single-vm.blueprint.yaml) | [01 single VM](../templates/01-single-vm/) | a machine that boots and runs | `Cloud.vSphere.Machine`; an image mapping and a flavor mapping; placement by a network profile's tag |
| [V02 It configures itself](V02-vm-cloud-init/vm-cloud-init.blueprint.yaml) | [02 cloud-init](../templates/02-vm-cloud-init/) | a login, nginx and a page, at first boot | `cloudConfig` is a property of the machine; the setup is a per-boot script (below) |
| [V02x Salt](../../guest-configuration/vm-apps/README.md) | [02x guest configuration](../../guest-configuration/README.md) | a Salt master and minions that keep the guest configured | the same Salt practices; the master at its own address, no load balancer |
| [V03 A web pair](V03-web-pair/web-pair.blueprint.yaml) | [03 web pair](../templates/03-web-pair/) | two machines behind one front door | two declared machines and a `Cloud.NSX.LoadBalancer` whose instances are their ids; a `count: 2` depends on the project's naming (G-990) |

**How to deploy one.** As in the spine's catalog way: import the blueprint as a template in your project, release a
version, add it to your project's catalog, and request it from the form. Or submit it with an inputs payload through
the API, which is how the proof deployed each one: a blueprint created in the project, then a deployment request; the
catalog form was not run. Each input's description names the read that gives you its value: `GET /iaas/api/images` for the image
mappings, `GET /iaas/api/flavors` for the flavor mappings, and `GET /iaas/api/network-profiles` for each profile's
tags.

## The one thing VM Apps adds to cloud-init: the first boot can be cut short

On VM Apps, vSphere's guest customization can run beside cloud-init on the machine's first boot, apply the address,
and then reboot the machine. On the image the branch was proven with, it rebooted while cloud-init was still installing
packages. cloud-init never runs a once-per-instance module again once it has started it, so the package never arrived, and nothing in the deployment's
status said so: the deployment was `CREATE_SUCCESSFUL` and the page was not there (G-988).

So V02, V03 and the Salt blueprints do not put the work in `packages:` and `runcmd:` as the spine does. They write it
as a script in cloud-init's per-boot directory that exits at once once a marker exists, finishes an interrupted
install, bounds every download, and sets the marker last. It finishes on whichever boot reaches its end. That is the
spine's habit, idempotence, applied to the boot itself.

What V02 printed on the reference estate, 2026-11-12, inside the machine after its deployment (`last -x reboot | head -2;
cloud-init status; systemctl is-active nginx;` and the page's two lines):

```
reboot   system boot  6.8.0-55-generic Thu Nov 12 10:51   still running
reboot   system boot  6.8.0-55-generic Thu Nov 12 10:51 - 10:51  (00:00)
status: done
active
<h1>z2m-v02</h1>
<p>Configured by cloud-init on host <strong>z2m-v02</strong>, deployed through VCF Automation VM Apps.</p>
```

Two boots, the customization's reboot between them, and cloud-init `done` with nginx serving the page anyway.

## Where VM Apps ends: moving to All Apps

Stage 04 of the spine puts containers beside a VM, stage 05 runs microservices on a VKS cluster, and stage 06 drives
them from Git. Each needs a Supervisor namespace, which a VM Apps organization does not have. So the branch stops at
V03, and the next step is not a template but an organization.

| In VM Apps | In All Apps |
|---|---|
| `Cloud.vSphere.Machine` | a `VirtualMachine` in a namespace (`CCI.Supervisor.Resource`) |
| an image mapping | the image's display name, `kubectl get clustervirtualmachineimages,virtualmachineimages` |
| a flavor mapping | a VM class, `kubectl get virtualmachineclasses` |
| a network profile's tag | the namespace's own network |
| `cloudConfig` on the machine | a Secret the machine's `bootstrap.cloudInit` names |
| `Cloud.NSX.LoadBalancer` | a `VirtualMachineService` of type `LoadBalancer` |
| nothing | stages 04, 05 and 06 |

**How an organization moves.** Plan for an All Apps organization built beside the VM Apps one, with its content
authored again in the spine's dialect, which is why this branch keeps the spine's habits.
[Field note 04](https://privatecloudarchitect.com/notes/aria-automation-8-18-to-vcf-automation-9-1-1) gives the
frame: "All Apps is a different model, not a later version of the same one". It lists a conversion path from a VM Apps
to an All Apps organization, and any tool that moves VM Apps content into one, among what it looked for in Broadcom's
documentation and did not find. The [upgrade playbook](https://privatecloudarchitect.com/playbooks/vsphere-8-and-aria-automation-8-18-to-vcf-9-1)
builds the All Apps landing zone as its own stage, which the organization chooses when its design moves workloads
there.

When it does, start the spine at [stage 01](../templates/01-single-vm/): you already know every idea in it.
