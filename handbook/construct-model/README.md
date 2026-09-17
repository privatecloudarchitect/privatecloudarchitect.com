# The construct model, read from your own estate

Companion to the chapter
([privatecloudarchitect.com/handbook/construct-model](https://privatecloudarchitect.com/handbook/construct-model)):
the containment spine and the taxonomy the chapter draws, read through the Cloud Consumption Interface with an
organization's OAuth bearer, written as two records with every estate name replaced by a placeholder. The chapter's
plates are rendered from the records in this folder; run the script and you have the same two records for yours.

| File | What it is |
|---|---|
| `inventory.py` | Read-only. Discovers every VMware API group the interface declares and records each kind with its scope (published at the top level, or under a project), its verbs, and how many of each top-level kind the organization can see; then walks the tree: projects, the binding kinds each carries (regions, classes, VPCs, subnets, service engine groups, infra policies), role bindings and their roles, images and catalog items, namespaces with the fields each bound at create (region, zone, class, VPC, storage classes, VM classes, overrides) and their phase, and behind each namespace's endpoint the virtual machines and VKS clusters. Refuses to write a record in which any estate name survived. Stdlib Python; no token printed or written. |
| `taxonomy.json` | The interface as declared on the reference estate, 2026-09-16: 13 VMware API groups, one line per kind. |
| `estate.json` | The tree as it stood: one organization, two projects, three namespaces, and what each bound. |
| `expected-output.md` | The transcript of that run. |

## Run it

```bash
export VCFA_HOST=<automation-fqdn> VCFA_ORG=<org>
export VCFA_REFRESH_TOKEN_FILE=/path/to/refresh-token      # mode 0600; the api-token minted in the console for that org
export TLS_VERIFY=false                                    # only on a self-signed lab CA
export OUT_DIR=.

python3 inventory.py
```

## Scope, stated plainly

- Read-only, under one organization's bearer: the records hold what that organization can see, which is the
  tenant's view of the model; a provider sees more kinds and every organization.
- The verbs recorded are what the interface declares for a kind, not what your role allows: a create the
  interface declares still answers 403 without the right.
- Placeholders are assigned in the order objects were met ({{project-1}}, {{namespace-2}}, {{region-1}},
  {{zone-3}}, {{class-1}}, {{vpc-1}}); the same object keeps the same placeholder within one run, and a real name
  that happens to look like a placeholder is not a leak.
- Workloads are counted behind each namespace's own endpoint (the VM service and the cluster API); a namespace
  that has not reached phase Created has no endpoint yet and reports none.
- Recorded on one 9.1 organization on 2026-09-16; your counts will differ, the shapes should not.

## Reading the records

`taxonomy.json` is a list of `{group, version, kind, resource, namespaced, verbs, count}`; `namespaced` true means
the kind lives under a project. `estate.json` is `{organization, published, projects}`: `published` carries the
regions, zones (with limits and usage), namespace classes, VPCs, subnet and quota counts; each project carries its
`bindings` counts, `roleBindings` (count, roles, fields), `images`, `catalogItems`, and `namespaces`, each with
`phase`, `bound` (region, zone, class, vpc, storage classes, VM classes, overrides), `specFields`, and `workloads`.
