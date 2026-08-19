# Configuring availability monitoring, layer by layer

The import artifacts in this directory render the dashboard; this guide makes the readings true.
It follows the sensor chain from the pipeline up, the same order as the dashboard's setup panel,
and every step, payload, and failure signature here was proven on a live VCF Operations 9.1
estate before publication, including onboarding a second vCenter's Service Discovery and standing
up a live application's agent and PostgreSQL service monitor end to end through the API. Where the
guide says "proven," it means executed, failed where noted, and verified fixed. The cardinality
map in the next section is the first thing to read if you are planning a multi-vCenter rollout.

## 0 · The pipeline: collectors before content

Every adapter instance is pinned to a collector on a cloud proxy. A down proxy freezes every
layer at once, and the signature is distinctive: a fleet of readings that all stopped at the
same age. That is one dead collector, not many failures.

- Verify: every collector reports UP, and each adapter's last-collected time advances.
- Discipline: a latest value without its timestamp is not evidence that anything is computing.
  When verifying any metric, read the timestamp and treat a point older than about two
  collection cycles as not collecting.

**Know the cardinality before you start.** At scale the first question is how many times you do
each thing. This is the map:

| Step | Cardinality | What repeats |
|---|---|---|
| Cloud proxy / collector | per site or failure domain | one proxy per network vantage you must collect from |
| Ping instance | per collector vantage | one instance per proxy whose network path you want to test; endpoints are an identifier list on the instance |
| Object ping | per guest VM, opt-in | reachability bound to the inventory object (isPingEnabled), on the object's own collector |
| VMware Tools | per VM | install and keep current on every guest |
| Service Discovery (agentless) | per vCenter | one adapter instance per vCenter, each with its own VMCA root trusted |
| VC-CP mapping | per vCenter, one-time | map each vCenter to its proxy before any agent installs behind it |
| Agent (layer 4) | per VM you instrument | install by promise, not by fleet |
| Agent service plugin (layer 5) | per service per VM | activate the plugin with the service's own connection |
| Super metrics + enablement | per Operations instance | create once; enable in every governing policy |

## 1 · Ping monitoring (layer 1)

The Ping adapter ships with the platform; an out-of-the-box install has no instance and no
checks. Create one instance and declare your endpoints on it.

**The rules that are easy to miss, all proven live:**

- The instance's internal unique name must be a **plain slug** (letters, digits, underscores).
  Spaces or punctuation break the adapter's own configuration write: the instance heartbeats
  green while minting zero checks, and the only truthful signal is the instance's
  **Adapter Status message** ("Adapter configuration failed"). Read that message after every
  create or edit; heartbeat and last-collected are liveness, not health.
- The display name is separate from the unique name and can carry your naming standard.
- Take values from the product's documented ranges (packet count 20 to 100, per-packet interval
  2000 ms or more, DNS re-resolution interval in minutes with 15 the minimum, packet size 56 to
  65536). Out-of-range values do not fail the create; they fail the adapter's config validation
  afterward, with the same quiet symptom as above.
- Enable **generated FQDN children** so each name check also pings every address the name
  resolves to. A child is deduplicated against an explicitly declared address check, so
  endpoint counts mean independent endpoints.
- Endpoints live in one comma-separated identifier (`address_list`) on the instance. Scaling to
  new applications is an identifier update, not a new instance: add addresses, update the
  instance, and the checks mint on the next configuration cycle. Keep the list sorted if you
  manage it declaratively, so ordering never looks like drift.

**Reachability is the question, not a precondition.** Declaring an application segment's
addresses is how you learn whether the collector routes to it; a 100 percent loss row is a
finding about the path, and a different finding than a degraded one.

**Monitor the front door, not the private backend.** This one is proven and it is the trap most
worth naming. A modern application on a supervisor namespace, a VKS guest cluster, or an NSX VPC
runs on a private CIDR (172.16.0.0/12-style space) that is inbound-isolated from the management
network by design: the workload reaches out by source NAT and is reached in only through a load
balancer. A ping from the collector to the workload's private pod or VM IP therefore reads a
stable 100 percent loss, which is correct and useless, and it will page you on a healthy app.
The right target is the application's external LoadBalancer VIP, the address users actually reach.
On a live three-tier app this was unmistakable: the private data-tier VM IP read 100 percent from
the collector while the NSX Advanced Load Balancer VIP for the web tier answered a ping at 0
percent and served HTTP 200. Find the VIP in Operations under the NSX Advanced Load Balancer
adapter's VirtualService objects (the `Summary|VSVIP` property), or from the LoadBalancer
service's external IP inside the guest cluster, and declare that. Reserve the private IP for a
check that runs from a vantage that actually shares the workload's network, if you have one.

**A ping result is relative to the collector's vantage.** The check proves reachability from the
collector that runs it, not from where your users sit. On a multi-site estate, a service can read
100 percent reachable from the datacenter collector and be unreachable for a branch, so plan a
ping instance per vantage that matters and read each as "reachable from here," never as a global
truth. One instance can carry many endpoints (they are a single identifier list), but keep a
practical ceiling in mind and split when the batch interval and packet count times the endpoint
count start crowding the collection window; a few hundred endpoints per instance is comfortable,
thousands is not.

### 1b · Object-level ping: reachability bound to inventory

There is a second, complementary ping mechanism. The Ping adapter above reaches arbitrary and
external endpoints and mints standalone objects; **object-level ping runs on a virtual machine or
host's own collector and writes the reading onto the object itself.** Enabling it on a VM gives
that VM `ping|peak_packet_loss` and `ping|peak_latency` of its own (verified: the peak loss reads
100 on an unreachable object, not blank, so failures surface; latency is null when unreachable),
which lets reachability sit on the same row as the guest availability KPI. A VM green on the KPI
but red on loss is alive with its path down from the monitoring vantage, a real and different
finding than a dead guest.

The toggle is a resource identifier, `isPingEnabled`, which is not part of the object's
uniqueness, so flipping it updates the existing object. Enable it with
`PUT /api/resources`: read the object (`GET /api/resources?resourceKind=VirtualMachine&name=...`),
set the `isPingEnabled` identifier's value to `"true"` in the returned `resourceKey`, and PUT the
object back with every other identifier preserved. Disable by setting it back to `""`. For bulk,
loop a scoped GET and PUT; **scope it, do not sweep the fleet.** Enable object ping on the
workloads that carry a reachability commitment, by the same by-promise rule as the agent plane. A
VM with object ping off simply carries no ping metric, which is a coverage statement, not a health
one.

The vantage rule from above still holds and is the one caution worth internalizing: object ping
runs from the object's collector, exactly like a ping instance runs from its collector group. A
workload reachable only through a different vantage (an NSX overlay reachable only via a workload
cloud proxy, say) reads 100 percent here while the guest is up. Object ping does not add a new
vantage; it binds the reading to the object. This was verified live: the same target read
identically from the Ping adapter and from object ping on the same collector, and the two mechanisms
agree whenever they share a vantage.

Bind object ping to guests, not hosts. Object ping targets every address the object carries, and the
portable `ping|peak_packet_loss` is the worst of them. A multi-homed ESXi host has many vmknics, and
a non-routable link-local one (a `169.254.x` address on a vSAN or auto-config interface) never
answers, so the peak reads a permanent 100 percent even while every routable interface answers at 0
percent. The host's true reachability is its instanced `ping:<mgmt-ip>|packet_loss`, which a
fleet-wide view cannot key on, and host availability is already the platform floor's job (connection
state, uptime). So the clean coupled target is a single-homed guest.

## 2 · VMware Tools (the layer-3 sensor)

Tools carries three duties at once: its heartbeat carries the guest availability reading, HA's
VM Monitoring restarts a hung guest on heartbeat loss, and current Tools (12.3.0 or later) feeds
Service Discovery. Install it everywhere; keep it current with the same cadence as guest
patching. The dashboard's layer-3 table is the verification loop: a red Tools state is a guest
the platform can neither measure nor protect, and the honest reading of such a guest is unknown,
not up.

At scale, do not hand-install onto the existing fleet: bake current Tools into the golden images
and templates so new guests arrive instrumented, and drive the existing estate from your
configuration-management or guest-patching pipeline. The dashboard's yellow "Supported Old" rows
are the remediation queue, already sorted; work it on the patch cadence rather than in a
one-time sweep.

## 3 · Service Discovery (layer 5, native), per vCenter

Service Discovery is enabled **per vCenter adapter**. If your discovered services all look like
platform internals, check which vCenter the discovery instance actually points at: that was
exactly the state we found, and the application workloads lived behind a second vCenter with no
discovery instance at all.

**Console path:** the vCenter integration's Service Discovery tab (or the Service Discovery
configuration tile). The console flow handles certificate acceptance for you.

**API path (proven end to end):** create an `APPLICATIONDISCOVERY` adapter instance via
`POST /api/adapters`. Three things the API demands that the console hides:

1. **The credential is embedded, and it already exists.** The create body requires a
   `credential` object; `{"id": "<credential-uuid>"}` suffices. Each vCenter adapter owns a
   system-managed service-account credential (readable through the adapter's
   `credentialInstanceId`, not listed by the credentials API); reuse that id. Note the same
   credential kind cannot ride an adapter *update*: on later PUTs, omit the credential field.
2. **The identifier set mirrors a working instance.** The load-bearing identifiers:
   `APPLICATIONDISCOVERY=enable`, `NAMESPACEDB_BASED_DISCOVERY_ENABLED=enabled`,
   `USESUDO=disable`, `VCURL=<vcenter-fqdn>`, and `VMEntityVCID=<the vCenter's instance uuid>`
   (read both values from the target vCenter's own adapter instance identifiers), plus empty
   scope and whitelist identifiers.
3. **Trust the signing CA, not endpoint certificates.** Adapter TLS trust is chain-based
   against the global certificate store (`GET`/`POST /api/certificate`; the POST is multipart
   with a `certificateFile` PEM). The test-connection call returns only the endpoint's leaf
   certificate, and trusting it is not enough: on our estate, the instance kept reporting
   "Certificate validation failed" after the vCenter leaf and every ESX host leaf were trusted,
   and cleared on the first poll after the vCenter's **VMCA root CAs** were added. Fetch them
   from the vCenter's own bundle at `https://<vcenter-fqdn>/certs/download.zip` (trust the
   `CN=CA, DC=vsphere, DC=local` roots, including the `O=localhost` pre-rename identity if the
   bundle carries one), then stop and start the instance.

**After creation:** the instance's Adapter Status message is the health gate, exactly as with
the Ping adapter. Discovery alone refreshes daily; **activating monitoring per service** (the
Manage Services page) moves that service to five-minute collection, starts its performance
metrics, and arms the shipped service-unavailability alert. A discovered-but-unmonitored
service shows blank metric cells by design: that is coverage information. Activate by promise,
starting with the services your commitments name.

**Both discovery modes are agentless.** Service Discovery and the Application Discovery layer on
top of it (rule-based multi-tier applications composed from discovered services) both run through
VMware Tools plus vCenter privileges, not an installed agent. This is not just the documented
design; it is verified: on the reference estate, Service Discovery found PostgreSQL, Active
Directory, and Tomcat on management VMs that carry no agent object at all. The product-managed
agent (the Telegraf-based OS and Application Monitoring pack in §4) is a separate sensor, so a
service type like PostgreSQL can be monitored two ways, agentlessly here or by the agent there.

**The Linux limit, and why layer 5 has a second sensor.** Credential-less discovery reads a
Linux guest's inventory through Tools but does not see the services running inside it without
guest credentials: the instance will show the VMs and zero services. Provide guest credentials to
discover Linux services, or use the agent's service plugins (§4) for those workloads. This is not
a defect to route around; it is why the service layer is two sensors, agentless breadth where
credentials permit and the agent for depth and for credential-constrained Linux.

**Repeat per vCenter.** Service Discovery is per-vCenter, so onboarding a second or third vCenter
is the same procedure with four things that change each time:

| Per-vCenter input | Where it comes from |
|---|---|
| `VCURL` | the target vCenter's FQDN |
| `VMEntityVCID` | the target vCenter adapter instance's own identifier |
| credential id | the target vCenter adapter's `credentialInstanceId` |
| VMCA root CA | fetched and trusted separately, from that vCenter's `/certs/download.zip` |

Everything else (the identifier template, the health-gate discipline, the activate-by-promise
rule) is identical across vCenters.

## 4 · Agents (layer 4) and agent-monitored services (the second layer-5 sensor)

The OS and Application Monitoring agent is the second, independent sensor. It delivers two
things: the operating system's own availability figure on a 0-to-1 scale (layer 4), and, through
per-service plugins, a per-service availability object (the agent half of layer 5). On a
credential-constrained Linux service the agent is not optional depth; it is the sensor of
record, because credential-less Service Discovery cannot see inside the Linux guest (see §3).
Install onto the guests whose promise justifies it, the data tier first.

This layer has more preconditions than any other, and each was a live blocker before it was a
step. In order:

**4a. Map the target vCenter to the cloud proxy first (per vCenter, one-time).** Agent bootstrap
resolves target VM to its vCenter to that vCenter's mapped cloud proxy to that proxy's
AppOsAdapter. If the vCenter is not mapped, the install fails 400 "No AppOsAdapter exists on the
Cloud Proxy in the VC-CP mapping." Add the mapping with
`POST /api/applications/vccpmappings`, body
`{"vCenterMappings":[{"collectorUUID":"<proxy collector uuid>","vCenterIds":["<vc-instance-uuid>"]}]}`.
It is **additive per vCenter**: include a vCenter that is already mapped and the whole call 400s
"already exists," so query the current mappings
(`POST /api/applications/vccpmappings/query`) and post only the new vCenter id. The
`vc-instance-uuid` is the vCenter adapter's `VMEntityVCID`; the `collectorUUID` is the proxy's
own uuid from the existing mapping, not the small integer collector id.

**4b. Have a working guest credential, and do not trust the deployment record for it.** Bootstrap
performs a guest-operations login on the VM. If your VMs were provisioned by an automation
platform, a deploy-time guest password stored there is likely returned **encrypted**: a long
opaque blob that fails guest auth. Recover the real value from the deployment tooling's own
defaults (the create script's variable default), and verify it authoritatively before use with a
vCenter guest-operations process-create; a 201 with a real process id means the credential is
good, a 401 means it is not. Treat guest credentials as the highest-exposure surface in this
practice: scope them to the install, do not cache them in shell history or logs, and rotate on
the guest's own schedule.

**4c. Install.** Console install, or `POST /api/applications/agents` with
`{"resourceCredentials":[{"resourceId":"<vm resource id>","username":"...","password":"...","addRuntimeUser":true}]}`.
Poll the returned `taskStatuses[0].taskID` at `/api/applications/agents/{id}/status` to FINISHED.

**4d. Expect a warmup, do not read it as failure.** For roughly two collection cycles after the
task finishes, the agent object is grey and offers only its base network plugins
(icmp, tcp, udp, http, customscript, processavailability). The application plugins (postgresql
and its siblings) appear, and the agent registers with the cloud proxy for service management,
only after it fully checks in. Before then, activating a service plugin fails 400 "not connected
to any ARC or Cloud Proxy." This transient is expected; a re-install here is churn, not a fix.

**4e. Activate the service plugin (the agent half of layer 5).** Once the plugin is offered, add
it with `POST /api/applications/agents/{id}/services`, where `{id}` is the **VM's VMWARE resource
id, not the OS object id** (the OS object id returns "not a virtual machine or Endpoint"). The
plugin needs the service's own connection: PostgreSQL, for instance, takes mandatory
`PORT`, `USERNAME`, `PASSWORD` (and optional `HOSTNAME`, defaulting to the loopback on the VM).
Source those from the same deployment tooling that set them, not from the encrypted record. On
success the agent mints a per-service availability object (`System Attributes|availability` on
the 0-to-1 scale) that is a child of the guest OS object, so it renders through the same vSphere
World traversal the layer-4 OS views use; the dashboard's agent-service view binds it.

## 5 · The computed layer: super metrics and policy enablement

Only the fleet reachability row and the per-check delivery column are computed content; import
them from this directory or build them from `supermetrics/editor-formulas.yaml`. Two enablement
rules that cost us real debugging time, both proven:

- **A super metric computes only under the policy that governs the object.** Enablement is per
  policy, and the effective policy is winner-takes-all for an object; enabling in a policy that
  does not govern the target leaves the metric silently blank.
- **The enablement call is a declarative replace.** One assignment call carries a metric's
  complete set of policies and object types; issuing per-policy calls in a loop leaves the
  metric enabled only in the last policy called. Converge each metric's full enablement in one
  call, every time.

Scope alerting to a dedicated group and policy, never to everything: an alert without a scoped
group pages on objects you never meant.

**On automation.** The reference estate drives every step above from committed generators and
reconcilers (a declarative checks file for the ping endpoints, generators for the super metrics
and views). Those are the estate's own tooling, not shipped here; this directory ships the
outputs (the import packages) plus `editor-formulas.yaml` for building the metrics by hand. At
scale, treat each step's API calls above as the contract and wrap them in whatever
configuration-management you already run; nothing here needs a bespoke controller, only the
calls in the right order with the right cardinality.

## 6 · Verifying without waiting for the console

Two verification tools worth knowing, both used to prove this directory's artifacts:

- **Execute a view exactly as a widget would:**
  `GET /suite-api/internal/views/{viewId}/data/export?resourceId=<providerId>` renders any
  imported view against any provider object. It sits under the internal API surface (send the
  `X-Ops-API-use-unsupported: true` acknowledgment header and treat it as a diagnostic, not an
  integration).
- **Prove an import package without changing anything:** a no-force
  `POST /api/content/operations/import` (multipart `contentFile`) reports recognized content as
  `skipped` with `failed: 0`. That is the id-preserving proof this directory's packages carry.

## 7 · Failure signatures, condensed

| You see | It means | The move |
|---|---|---|
| Instance heartbeats green, zero resources minted | The adapter's own config write failed | Read the Adapter Status message; check the unique-name slug rule and value ranges |
| "Certificate validation failed" persists after trusting the endpoint certificate | Trust is chain-based | Add the signing VMCA root CA(s) from the vCenter's certs bundle, then restart the instance |
| A whole fleet of readings frozen at one age | One dead collector, not many failures | Check collector state and adapter last-collected before touching content |
| A perfect reading renders yellow | Ascending band bounds are exclusive at the top | Set the yellow bound below the perfect value |
| A workload's private IP reads a stable 100% loss from the collector | It is a VPC / supervisor / VKS private address, inbound-isolated by design | Monitor the app's external LoadBalancer VIP (the front door) instead; the private IP is the wrong target |
| A Linux VM discovered with zero services | Credential-less discovery cannot see inside a Linux guest | Provide guest credentials to Service Discovery, or monitor the service with the agent plugin (§4) |
| Agent install fails "No AppOsAdapter ... in the VC-CP mapping" | The target vCenter is not mapped to a proxy | Query mappings, then post the new vCenter id once (additive; re-posting a mapped vCenter 400s) |
| Guest auth fails at agent install with a credential from the automation platform | The stored deploy-time password is encrypted, not the plaintext | Recover the value from the deploy tooling's defaults; verify with a vCenter guest-operations login (201 = good) |
| A freshly installed agent is grey and offers only base plugins | Expected warmup, about two collection cycles | Wait for check-in; the app plugins and cloud-proxy connection appear on their own, do not re-install |
| Agent service activation 422 "not a virtual machine or Endpoint" | The call was keyed on the OS object id | Key agent-service calls on the VM's VMWARE resource id, not the OS object id |
| Blank metric cells on a discovered service | Discovered is not monitored | Activate monitoring for that service; daily discovery becomes five-minute collection |
| Blank SLI and fleet-row cells | The super metrics are absent or not enabled in the governing policy | Import the package, then converge enablement in one declarative call |
| A guest availability reading you doubt | The sensor, not the guest | Read the Tools state and uptime witness columns beside the number |
