# The platform map, read from your own estate

Companion to the chapter
([privatecloudarchitect.com/handbook/platform-map](https://privatecloudarchitect.com/handbook/platform-map)):
one read-only script that places your own VCF estate on the map the chapter draws, from the same two services the
chapter's figures came from. The chapter's inventory counts are rendered from the record in this folder.

| File | What it is |
|---|---|
| `inventory.py` | Read-only, stdlib Python. Reads every SDDC Manager you name (one per VCF instance): each domain's type and status, its clusters and hosts, and the vCenter and NSX manager it brings. Then reads the fleet: VCF Operations exchanges its session for the Fleet lifecycle service's key, and the service's component list gives each component's type, how it is hosted, its scope, size and nodes, matched to its instance through its vCenter. Ends with the placement checks the chapter teaches. Exit 0 every read answered and every check held, 1 a check differs, 2 a read failed. |
| `inventory.json` | The record from the reference estate, 2026-10-07, written with `--record`: counts and types only, with every host name, identifier and object name left out. |
| `expected-output.md` | The transcript of that run. |

## Run it

```bash
export SDDC_HOSTS=<sddc-manager-1-fqdn>,<sddc-manager-2-fqdn>   # one SDDC Manager per VCF instance
export SDDC_USER=<user@sso-domain>
read -rs SDDC_PASSWORD && export SDDC_PASSWORD                 # typed, never in the shell history
export OPS_HOST=<operations-fqdn> OPS_API_TOKEN=<api-token>    # for the fleet; omit both to skip it
export OPS_BROKER_HOST=<broker-fqdn>                           # omit if the broker shares the Operations FQDN
export TLS_VERIFY=false                                        # only on a self-signed lab CA

python3 inventory.py
python3 inventory.py --record inventory.json                   # also write the counts, with no names
```

## Scope, stated plainly

- Read-only: nothing is created or changed, and no token value is printed. The fleet read needs a VCF Operations
  api-token, because the Fleet lifecycle service takes a key exchanged through Operations rather than the
  Operations session itself.
- Run on the reference estate on 2026-10-07 (VCF 9.1: two instances, the second management-only), with every count
  matching the chapter's reads of 2026-09-16 and 2026-09-21.
- A component is placed on an instance through the vCenter it names; one the script cannot match is reported, not
  guessed.
- It does not read what runs inside a domain. Whether a tenant workload sits in the management domain is a vCenter
  read of that domain's machines, which this script does not make; the Supervisor's zones and the namespaces under
  it are read by the construct-model companion.

## Reading the output

- The domain lines answer plate 01: one management domain per instance, any workload domains beside it, and the
  vCenter and NSX manager each brings.
- The fleet table answers plate 02: `OVA` is an appliance with its own addresses, `VSP` a service on the VCF
  services runtime; `FLEET` and `INSTANCE` are its scope; the `VSP` rows' nodes are the runtime itself.
- The checks are the placements the chapter asks you to make; `DIFFERS` names the one that does not hold on yours.
