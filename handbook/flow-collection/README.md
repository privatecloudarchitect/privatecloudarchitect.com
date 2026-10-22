# Flow collection: prove export at the collector and attribution in the store

The chapter ([privatecloudarchitect.com/handbook/flow-collection](https://privatecloudarchitect.com/handbook/flow-collection))
teaches flow collection on VCF 9.1 from the IPFIX record up: a flow is recorded at the port a packet leaves by, so
coverage is set switch by switch and port group by port group, by an owner who may not be the product you are looking
at, and it is proven twice: at the collector, for which hosts export, and in the store, for which workloads the flows
name. This folder is its checkpoint, two read-only scripts.

- `flow_paths.py` reads what Operations for Networks collects from and whether VCF manages each source, which
  distributed switches carry its collector and how many of their port groups export, which kind of IPFIX NSX exports
  (the distributed firewall's or the switch's), how many flows arrived in the last hour, and which hosts those flows
  name.
- `exporters.py` reads the collector's own exporter list: which hosts send it records, under which observation
  domain, and which hosts send nothing.

Proven on VCF 9.1.1 (Operations for Networks 9.1.1.0, NSX and vCenter 9.1.1) on 2026-10-22, with the exact files in
this folder.

## What they read

Every call is a read, plus the session token request each product requires, which changes nothing.

1. **Operations for Networks** (`flow_paths.py`, `/api/ni`): its node list (each node's type, version and health);
   every vCenter and NSX data source with its IPFIX state (`ipfix_response.ipfix_enabled_for` lists the switches a
   vCenter source enabled, and `ipfix_enabling_failed` any it could not; NSX sources say whether IPFIX is on), its
   `vcfManaged` flag (true means VCF Operations owns a change to it) and the Antrea IPFIX state; the flows counted in
   the last hour (`POST /api/ni/search`, entity type `Flow`); and those flows counted by the host each endpoint runs
   on (`POST /api/ni/entities/fetch` in batches of 100, each flow once for every host it names). A flow's
   `source_host` and `destination_host` are where its endpoints run; no flow field names the host that exported it.
2. **NSX** (`flow_paths.py`, `/policy/api/v1/infra/ipfix-*`), when `NSX_HOSTS` is set: the collector and IPFIX
   profiles of both kinds, and which kind is in use. Operations for Networks enables the distributed firewall's IPFIX
   where a security licence is installed and the firewall is on, and the switch's otherwise, and it creates these
   profiles itself; they are not to be changed by hand.
3. **vSphere** (`flow_paths.py`), when `VC_HOSTS` is set and pyVmomi is installed: every distributed switch's own
   IPFIX settings (collector address and port, sampling rate, active and idle timeouts), how many of its port groups
   export, uplink groups counted apart, and its member hosts, each with the hour's flows that name an endpoint on it.
4. **The collector itself** (`exporters.py`), through vSphere Guest Operations, because the appliance refuses root
   over SSH: one fixed command in the guest, `nfdump -E` over the newest minute files its IPFIX receiver wrote, the
   output copied back and the one temporary file it wrote under the guest's `/tmp` removed. From each vCenter named
   it reads every host's VMkernel addresses, to name the exporters and the hosts that sent nothing.

## Credentials

Each password or bearer is read from a file named by a `*_FILE` variable. The file must be mode 0600: one open to
group or other is refused before it is read, and the refusal names the variable, never the content. The bare
variable (`NI_PASSWORD`, and so on) is read only when no file is named. A VCF 9.1 single sign-on user signs in to NSX
with a bearer, not with Basic; give `NSX_BEARER_FILE` for such a user, or `NSX_USER` and `NSX_PASSWORD_FILE` for a
local NSX user.

## Run them

```
umask 077    # files you create from here on are mode 0600
export NI_HOST=<operations for networks fqdn> NI_USER=<user> NI_PASSWORD_FILE=./ni.pw   # NI_DOMAIN_TYPE=LDAP and NI_DOMAIN for a directory user
export NSX_HOSTS=<nsx manager fqdn>[,<another>] NSX_BEARER_FILE=./nsx.bearer        # or NSX_USER and NSX_PASSWORD_FILE
export VC_HOSTS=<vcenter fqdn>[,<another>] VC_USER=<user> VC_PASSWORD_FILE=./vc.pw   # every vCenter whose hosts export
python3 flow_paths.py --out ./records
export COLLECTOR_VM=<the collector VM's name> GUEST_USER=root GUEST_PASSWORD_FILE=./guest.pw
python3 exporters.py --minutes 60 --out ./records    # --redact prints placeholders instead of your names
```

`flow_paths.py` is standard library only, except the switch read, which uses pyVmomi when it is installed and reports
the read as skipped when it is not. `exporters.py` needs pyVmomi. Both take the TLS helper and the secret reader from
the metrics-collection harness, which ships in this repository at `../metrics-collection/harness/`; run them from
this folder of a full clone.

## Reading the result

- **Export, at the collector** (`exporters.py`). A host listed under domain 0 sends its distributed switch's IPFIX;
  under any other number it sends an NSX profile's, whose kind `flow_paths.py` reports. "Registered, nothing in the
  window" means the collector holds the host's templates for that domain and received no record from it in the
  window. A host under "hosts that sent nothing" exports nothing in the window, whatever the switch settings say.
  Sequence failures are counted per exporter; on the reference estate every switch exporter shows them and the NSX
  profile's exporters none, and why was not read.
- **Attribution, in the store** (`flow_paths.py`, the tally). A host at zero in the tally has no named workloads: it
  exports nothing, or Operations for Networks cannot name its VMs (a host missing from its inventory, or addresses it
  binds to several VMs). The exporter list tells the two apart. A switch without the collector, or with silent port
  groups, is a blind spot for everything built on flows, including a dependency graph.
- **Who changes it.** A source whose `vcfManaged` reads true is changed from its account in VCF Operations, not
  through the Operations for Networks API, which refuses such a source (the chapter's Plate 03). Read the exporter
  list and the source's state after any change, and again later: an update of a source can leave its switch with no
  collector.
- **Testing with traffic.** A TCP conversation becomes a flow only once its handshake completes; a probe nobody
  answers is rejected and never appears. Test with a connection that completes, and give it several minutes: the
  reference estate's completed test conversations took four to eight minutes to become searchable.
- **The records.** `flow-paths.record.json`: `operations_for_networks.nodes` and `.sources` (one per data source;
  `proxy_id` names the collector, `vcfManaged` the owner of a change, `ipfix_enabled_for` the switches Operations for
  Networks enabled, `ipfix_enabling_failed` those it could not, `ipfix_enabled` for NSX), `.flows_last_hour`; `nsx`
  (each manager's profile lists and `in_use`: `distributed firewall`, `switch` or `none`); `switches` (one row per
  distributed switch: collector address and port, sampling rate, timeouts, port groups and how many export, and
  `hosts` with each host's `flows_last_hour`); `operations_for_networks.flows_by_host`, `.flows_read` and
  `.flows_without_host`. `exporters.record.json`: `window` (the minute files read), `exporters` (one row per address
  and observation domain: `host`, `domain`, `records`, `packets`, `sequence_failures`, `files_with_packets`),
  `hosts_sending_nothing` and `exporting_addresses_no_vcenter_named`.

One scrubber serves a whole run, so a value keeps its placeholder across products within one script's record. Each
script refuses to write a record in which an estate value survived (`scrub.py`).

## What they do not cover

- The collector's on-disk buffer use.
- Antrea's own flow exporter settings inside each VKS cluster.
- The distributed firewall's per-cluster state, which decides whether a host has firewall IPFIX to send.

## Expected output

[`expected-output.md`](expected-output.md) holds a run of each against the reference estate.
