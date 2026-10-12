# The platform map, read from your own estate

Companion to the chapter
([privatecloudarchitect.com/handbook/platform-map](https://privatecloudarchitect.com/handbook/platform-map)):
one read-only script that places your own VCF estate on the map the chapter draws, with the release each component
runs, from the same services the chapter's figures came from. The chapter's counts and versions are rendered from the
record in this folder.

| File | What it is |
|---|---|
| `inventory.py` | Read-only, stdlib Python. Reads every SDDC Manager you name (one per VCF instance): its version, each domain's type and status, its clusters and hosts with their ESX version, and the vCenter and NSX manager it brings with theirs. Signs in to each of those vCenters as the same user and reads its Supervisors and their version, its vSphere zones and the clusters each holds, the Supervisor services installed, and how many namespaces are the platform's own. Reads the fleet: VCF Operations exchanges its session for the Fleet lifecycle service's key, and the service's component list gives each component's type, version, hosting, scope, size and nodes, matched to its instance through its vCenter; then where VCF Operations collects. Optionally reads standalone Orchestrator appliances. Ends with a release summary, an optional bill-of-materials comparison, and the placement checks the chapter teaches. Exit 0 every read answered and every check held, 1 a check differs, 2 a read failed. |
| `bom-9.1.1.json` | The VCF 9.1.1 bill of materials, transcribed from Broadcom's release notes on 2026-10-12, keyed by the names `inventory.py` prints. For another release, copy it and fill it from that release's bill of materials. |
| `inventory.json` | The record from the reference estate, 2026-10-12, written with `--record`: versions, counts and types only, with every host name, identifier and object name left out. |
| `expected-output.md` | The transcript of that run. |

## Run it

```bash
export SDDC_HOSTS=<sddc-manager-1-fqdn>,<sddc-manager-2-fqdn>   # one SDDC Manager per VCF instance
export SDDC_USER=<user@sso-domain>                             # also signs in to each vCenter they list
read -rs SDDC_PASSWORD && export SDDC_PASSWORD                 # typed, never in the shell history
export OPS_HOST=<operations-fqdn> OPS_API_TOKEN=<api-token>    # for the fleet; omit both to skip it
export OPS_BROKER_HOST=<broker-fqdn>                           # omit if the broker shares the Operations FQDN
export VCFO_HOSTS=<orchestrator-fqdn>                          # standalone Orchestrators only; omit if you have none
export TLS_VERIFY=false                                        # only on a self-signed lab CA

python3 inventory.py --bom bom-9.1.1.json
python3 inventory.py --bom bom-9.1.1.json --record inventory.json   # also write the record, with no names
python3 inventory.py --no-vcenter                                   # skip the vCenter reads
```

## Scope, stated plainly

- Read-only: nothing is created or changed, and no token or password value is printed. The one call that is not a
  GET besides the sign-ins is the `DELETE /api/session` that ends the script's own vCenter session.
- The fleet read needs a VCF Operations api-token, because the Fleet lifecycle service takes a key exchanged through
  Operations rather than the Operations session itself. An identity broker on its own appliance has its own FQDN,
  which is what `OPS_BROKER_HOST` is for.
- The release check covers every component the two inventories carry, the Supervisors the vCenters report, and any
  standalone Orchestrator you name. A component in neither inventory and not named is not checked; on the reference
  estate the standalone Orchestrator is exactly that kind of component, and it was the one behind the release.
- A Supervisor's version string carries vCenter's build, so it is compared with the bill of materials by release
  only. Supervisor services (the Kubernetes service, Harbor and the rest) version on their own lines and are listed,
  not checked.
- A component is placed on an instance through the vCenter it names; one the script cannot match is reported, not
  guessed.
- It does not read what runs inside a domain beyond the Supervisor's own rungs. Whether a tenant workload sits in the
  management domain is a vCenter read of that domain's machines, which this script does not make; the namespaces a
  tenant sees are read by the construct-model companion.
- Run on the reference estate on 2026-10-12, VCF 9.1.1: two instances, the second management-only.

## Reading the output

- The instance blocks answer plate 01: one management domain per instance, any workload domains beside it, the
  vCenter and NSX manager each brings and the version each runs, and a Supervisor only where tenants are served.
  `namespaces 14, 8 of them the platform's own (svc-)` is the Supervisor running its services in namespaces of their
  own, which is why a namespace list or a load balancer's address range shows names no tenant created.
- The fleet table answers plate 02: `OVA` is an appliance with its own addresses, `VSP` a service on the VCF services
  runtime; `FLEET` and `INSTANCE` are its scope; the `VSP` rows' nodes are the runtime itself. In the `OPS` row,
  `MASTER` is the analytics node and `ONE_WAY_REMOTE_COLLECTOR` a cloud proxy: three nodes there is one analytics node
  with two proxies, not a three-node cluster.
- `where VCF Operations collects` says which collector runs the adapters. The vCenter, NSX and vSAN adapters belong on
  the cloud proxies; the analytics node's own collector runs the rest you have configured there.
- `releases` lists every release the versions read belong to; more than one is the line to read first. With `--bom`,
  each component is at its bill-of-materials build, on a later patch of the same release, or behind it.
- The checks are the placements the chapter asks you to make; `DIFFERS` names the one that does not hold on yours.
