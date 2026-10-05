# Flow collection: prove coverage from the flows themselves

The chapter ([privatecloudarchitect.com/handbook/flow-collection](https://privatecloudarchitect.com/handbook/flow-collection))
teaches flow collection on VCF 9.1 from the IPFIX record up: a flow is recorded at the port a packet leaves by, so
coverage is set switch by switch and port group by port group, by an owner who may not be the product you are looking
at. This folder is its checkpoint. One read-only script reports what Operations for Networks collects from, which
distributed switches carry its collector and how many of their port groups export, what NSX exports, and how many
flows arrived in the last hour.

Proven on VCF 9.1.1 (VCF Operations for Networks collector 9.1.1.0, NSX and vCenter at 9.1) on 2026-10-05, with the
exact files in this folder.

## What it reads

Every call is a read, plus the session token request each product requires, which changes nothing.

1. **Operations for Networks** (`/api/ni`): its node list (each node's type, version and health); every vCenter and NSX
   data source with its IPFIX state (`ipfix_response.ipfix_enabled_for` names the switch a vCenter source enabled;
   NSX sources say whether IPFIX is on) and the Antrea IPFIX state; the flows counted in the last hour
   (`POST /api/ni/search`, entity type `Flow`); and those flows counted by the host they were observed on
   (`POST /api/ni/entities/fetch` in batches of 100, each flow once for every host it touches).
2. **NSX** (`/policy/api/v1/infra/ipfix-*`), when `NSX_HOSTS` is set: the IPFIX collector and switch profiles.
3. **vSphere**, when `VC_HOSTS` is set and pyVmomi is installed: every distributed switch's own IPFIX settings
   (collector address and port, sampling rate, active and idle timeouts), how many of its port groups export,
   uplink groups counted apart, and its member hosts, each with the flows observed on it in the last hour. This is
   the level the chapter's Plate 02 calls the switch and its port groups, joined to the proof of its Plate 04.

## Run it

```
export NI_HOST=<operations for networks fqdn> NI_USER=<user> NI_PASSWORD=<password>   # NI_DOMAIN_TYPE=LDAP and NI_DOMAIN for a directory user
export NSX_HOSTS=<nsx manager fqdn>[,<another>] NSX_USER=<user> NSX_PASSWORD=<password>   # optional
export VC_HOSTS=<vcenter fqdn>[,<another>] VC_USER=<user> VC_PASSWORD=<password>         # optional, needs pyVmomi
python3 flow_paths.py --out ./records
```

Standard library only, except the switch read, which uses pyVmomi when it is installed and reports the read as
skipped when it is not; the rest of the run does not need it. The TLS helper is the metrics-collection harness's, which ships in this
repository at `../metrics-collection/harness/`; the script finds it there, so run it from this folder of a full
clone.

## Reading the result

- **Coverage passes** when every distributed switch that carries workloads has the collector set, its port groups
  export, and every one of its hosts shows flows in the hour; a host at zero is unobserved, not idle. A switch without the collector, or with
  silent port groups, is a blind spot for everything built on flows, including a dependency graph.
- **Who changes it.** A vCenter source that VCF added is changed from its account in VCF Operations, not through the
  Operations for Networks API, which refuses such a source; read the source in Operations for Networks first
  (Plate 03).
- **The record** (`flow-paths.record.json`): `operations_for_networks.nodes` and `.sources` (one per data source;
  `proxy_id` names the collector, `ipfix_enabled_for` the switch Operations for Networks enabled, `ipfix_enabled` for
  NSX), `.flows_last_hour`; `nsx` (each manager's IPFIX profile lists); `switches` (one row per distributed switch:
  collector address and port, sampling rate, timeouts, port groups and how many export, and `hosts` with each
  host's `flows_last_hour`); `operations_for_networks.flows_by_host`, `.flows_read` and `.flows_without_host`.

One scrubber serves a whole run, so a value keeps its placeholder across products: a switch Operations for Networks
names in `ipfix_enabled_for` is the same placeholder as that switch's row under `switches`. The script refuses to
write a record in which an estate value survived (`scrub.py`).

## What it does not cover

- The collector's on-disk buffer use: a root shell on the collector VM reads it, and the appliance refuses root over
  SSH by design, so it goes through vSphere Guest Operations.
- Antrea's own flow exporter settings inside each VKS cluster.

## Expected output

[`expected-output.md`](expected-output.md) holds a run against the reference estate.
