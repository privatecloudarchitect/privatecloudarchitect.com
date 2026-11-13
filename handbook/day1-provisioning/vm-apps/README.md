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
tags. To request a released template from the catalog by API instead of the form, the next section has the script.

## Requesting it from the catalog by API, and what changed since Aria Automation 8.18

A released version reaches a project's catalog in two steps, and only the first is automatic. The project's template
content source lists it: on 9.1.1 the source's items named a version as soon as it was released, and a second source
for the same project answered `400`, "A source with provided configuration already exists". Then the source, or the
item, has to be entitled to the project, which Broadcom's guide calls creating entitlement and which on 9.1.1 was a
content sharing policy: the item appeared in the project's catalog within seconds of one. A project whose sharing policy
shares another source does not see its own released templates. Both are your administrator's to set up;
`GET /catalog/api/items?projects=<project-id>` is what your project sees.

Once the item is there, a script can request it the way the form does.
[`request_catalog_item.py`](request_catalog_item.py) does it the way Broadcom's 9.1 VM Apps programming guide does, and
prints beside each step what an Aria Automation 8.18 script did there. Without `--execute` it only signs in, checks and
prints the request it would send, with an input shown as hidden when its schema marks it `encrypted`, or when its name
says it is a secret (password, passwd, pwd, secret, token, private key). On 9.1.1 the catalog marked every secret input
this branch read as `encrypted`, in the template items' version schemas and in an Orchestrator workflow item's own
schema; the name rule is there so the mask never rests on one flag. Keep the inputs file at mode 0600: an input can be
a password, and the script refuses a file open to group or other. An item that is not versioned, as a workflow item
read, is requested with no version and its own inputs (that request was not run live; the proof requested a template).
[`request_catalog_item.expected.md`](request_catalog_item.expected.md) is what each kind of run printed on 9.1.1.

The request itself did not change. The sign-in did:

| Step | Aria Automation 8.18 | VCF Automation 9.1.1, VM Apps organization |
|---|---|---|
| A refresh token | `POST /csp/gateway/am/api/login?access_token` with a username and password; the token is "valid for 90 days" and "You cannot revoke the refresh token" | made by a person in the UI: the tenant's name ▸ My Account (under User Settings) ▸ API Tokens ▸ New. "As of VCF 9.0, the Identity Service API is no longer used to obtain a refresh token programmatically." 90 days by default; revoking one on 9.1.1 answered `204`, and the next exchange was refused |
| The bearer | `POST /iaas/api/login` with `{"refreshToken": ...}`; "The access token is valid for eight hours" | `POST /tm/oauth/tenant/<org>/token`, form `grant_type=refresh_token`; one hour (the same exchange at `/oauth/tenant/<org>/token`, without `/tm`, also answered on 9.1.1). Or a session as `user@org` |
| Item, versions, the name not yet used | `GET /catalog/api/items/{id}/versions`, `GET /deployment/api/deployments?name=` | the same calls; the guide adds `?apiVersion=` |
| The request | `POST /catalog/api/items/{id}/request` with `deploymentName`, `projectId`, `version`, `inputs` | the same call and body, with `?apiVersion=2020-08-25`; the answer is a list of `{deploymentId, deploymentName}` |
| Sign out | the guide gives no sign-out call; it says the access token "times out" after 25 minutes of inactivity, and "You can revoke an access token at any time." | `DELETE /cloudapi/1.0.0/sessions/current` with `Accept: application/json;version=40.0`, for either kind of bearer |

So a script that worked against 8.18 changes three things, all at the edges: where its refresh token comes from, where
it trades that token for a bearer, and how it reads the request's answer. Keeping either 8.18 sign-in call does not
work on 9.1.1: on a VM Apps organization this branch measured the Identity Service login answering `404`, and
`/iaas/api/login` refusing a 9.1 API token with `invalid_grant`. Both guides print the request's answer as one object;
the catalog API describes an array, and 9.1.1 answered with one, so a script that reads `.deploymentId` off the
answer stops there. The script reads either.

Sending a request twice makes two deployments, so the script treats the deployment's name, in the project, as the
request's key. When a deployment of that name exists, made from this catalog item, it reports it or waits on it and
sends nothing, with or without the inputs; a version or an input given that differs from what it was made with stops it
with exit 4, and so does a name that two deployments share or that a deployment from another item holds. After a
request with no clear answer (none, a `5xx`, or a `2xx` without a deployment id) it lists by name for a minute and never
sends again; when nothing is visible by then it exits 6 and says the request may still be in flight. `--delete
--execute` removes only one deployment, made by this item and owned by the signed-in user (`--any-owner` for another
owner's), and without `--execute` it prints the owner and creator first. A redirect from `VCFA_HOST` is refused rather
than followed, so the credential reaches that host only.

How it was proven, on VCF Automation 9.1.1 in a VM Apps organization on 2026-11-13: V01 released as a throwaway
catalog item and shared to one project, then the script run five ways, with both sign-ins. The request answered with a
list and the deployment was created, passing through `CHECKING_APPROVAL`; a second `--execute` with the same name and
no inputs found it and sent nothing; `--delete --execute` removed it. Every session the script opened was signed out
with `204`. The template, the sharing and the deployment were deleted afterwards and nothing was left in VCF
Automation or vCenter. The script's 48 offline tests hold each refusal above.

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
