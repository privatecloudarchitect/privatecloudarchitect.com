# Configuring availability monitoring, layer by layer

The import artifacts in this directory render the dashboard; this guide makes the readings true.
It follows the sensor chain from the pipeline up, the same order as the dashboard's setup panel,
and every step, payload, and failure signature here was proven on a live VCF Operations 9.1
estate before publication, including onboarding a second vCenter's Service Discovery entirely
through the API. Where the guide says "proven," it means executed, failed where noted, and
verified fixed.

## 0 · The pipeline: collectors before content

Every adapter instance is pinned to a collector on a cloud proxy. A down proxy freezes every
layer at once, and the signature is distinctive: a fleet of readings that all stopped at the
same age. That is one dead collector, not many failures.

- Verify: every collector reports UP, and each adapter's last-collected time advances.
- Discipline: a latest value without its timestamp is not evidence that anything is computing.
  When verifying any metric, read the timestamp and treat a point older than about two
  collection cycles as not collecting.

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

## 2 · VMware Tools (the layer-3 sensor)

Tools carries three duties at once: its heartbeat carries the guest availability reading, HA's
VM Monitoring restarts a hung guest on heartbeat loss, and current Tools (12.3.0 or later)
powers credential-less Service Discovery. Install it everywhere; keep it current with the same
cadence as guest patching. The dashboard's layer-3 table is the verification loop: a red Tools
state is a guest the platform can neither measure nor protect, and the honest reading of such a
guest is unknown, not up.

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

## 4 · Agents (layer 4), by promise

The OS and Application Monitoring agent is the second, independent sensor: the operating
system's own availability figure on a 0-to-1 scale, process pathology, and in-guest service
monitors. It requires the cloud proxy from step 0 and guest credentials at install time
(console install, or `POST /api/applications/agents` with the agent lifecycle endpoints
alongside it). Install onto the guests whose promise justifies the install, the data tier
first; a workload absent from the layer-4 tables is relying on the thinner layers, and the
dashboard says so rather than hiding it.

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
| Blank metric cells on a discovered service | Discovered is not monitored | Activate monitoring for that service; daily discovery becomes five-minute collection |
| Blank SLI and fleet-row cells | The super metrics are absent or not enabled in the governing policy | Import the package, then converge enablement in one declarative call |
| A guest availability reading you doubt | The sensor, not the guest | Read the Tools state and uptime witness columns beside the number |
