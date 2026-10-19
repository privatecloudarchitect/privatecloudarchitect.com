# What `day1.py` prints

Run against one VCF Automation 9.1.1.0100 organization on 2026-10-19, signed in with a session login, without
`--probe-release`. Your counts will differ; the shapes should not.

```
day1.py: the Day-1 plane, read through both of its faces

  vocabulary: 13 Day-1 kind(s) across 3 group(s); 5 accept a write, 8 are read-only
     blueprint  blueprints               write  create,delete,get,list,patch,update
     blueprint  blueprintresourcetypes   read   get,list
     blueprint  blueprintexportrequests  write  create,delete,get,list,patch,update
     blueprint  blueprintimportrequests  write  create,delete,get,list,patch,update
     blueprint  blueprintversions        write  create,delete,get,list,patch,update
     catalog    instanceresources        read   get,list
     catalog    instanceuserevents       read   get,list
     catalog    instances                write  create,delete,get,list,patch,update
     catalog    instanceactions          read   get,list
     catalog    catalogitemversions      read   get,list
     catalog    catalogitems             read   get,list
     catalog    instancerequests         read   get,list
     image      images                   read   get,list

  the same deployments, both faces: classic returns 4, CCI returns 4
     fields on the classic object only: 14 -> ['blueprintId', 'blueprintVersion', 'catalogItemId', 'catalogItemVersion', 'createdAt', 'createdBy', 'iconId', 'id', 'lastUpdatedAt', 'lastUpdatedBy', 'orgId', 'ownedBy', 'ownerType', 'projectId']
     of those, the ones naming a person: ['createdBy', 'lastUpdatedBy', 'ownedBy', 'ownerType']
     classic deployments with no owner: 0 of 4
     fields on the CCI object only:     ['annotations', 'creationTimestamp', 'finalizers', 'labels', 'managedFields', 'namespace', 'ownerReferences', 'sourceRef', 'uid']

  the content tree: 14 blueprint(s), 31 version(s)
     catalog items are identical in every project read: True ([10, 10]), yet 0 of 10 are marked global and 10 carry a project list
     a catalog item's spec carries a schema of 5 typed input(s); it carries the blueprint content: False

  the ingredients: 5 deployable resource type(s) -> ['CCI.Supervisor.Namespace', 'CCI.Supervisor.Resource', 'CCI.VPC', 'CCI.VPC.Configuration', 'Util.PasswordEntry']
     images: 3; the object name equals the display name: False; spec ['contentLibraryName', 'displayName', 'type']

  release semantics: not probed; pass --probe-release to ask each face what a delete does (it creates a throwaway blueprint and deletes it again)
  carrying forward 'release' from an earlier run with the probe flag; this run did not re-probe it and has not erased it

wrote day1.json (13 kinds, 14 fields on the classic deployment alone); every organization name replaced by a placeholder
```

## What each block tells you

**The vocabulary is the design.** Of the Day-1 kinds the Cloud Consumption face declares, a tenant writes
blueprints, their versions, import and export requests, and instances. Everything describing what may be
requested, and every record of what was requested, is read-only. The interface lists this itself, so ask it
before you automate anything.

**The same deployments are two different records.** The classic object carries the fields that say who owns a
deployment, who created and last changed it, when, and what it was built from; the Cloud Consumption object
carries none of them. Read ownership from the classic face. The script also counts classic deployments with no
owner, which is the sign that your inventory can attribute everything.

**The content tree and the catalog.** Blueprints and versions per project, and the catalog items each project
path returns. The catalog kind is addressed under a project, yet the same set can come back under every
project path while the classic face reports none of the items as global and every one carrying a project list:
a listing is not an entitlement answer.

**The ingredients.** The deployable resource types and the images, whose object name is an opaque id and whose
readable name is a separate field. Pin by the id.

## `--lookup`: key on the id, refuse a name that is not yours

Read-only. Every blueprint of that exact name in every project the identity can see, with id, project and
creator. Exit 0: one match, in your project (`--project`), or the only one when no project is named; key on
the id it prints. Exit 1: no blueprint of that name. Exit 3: the name also matches outside your project, or
more than once; update only by the id of the one you own. Run on 2026-10-19 with a name no project holds:

```
day1.py: blueprints named 'probe-day1-release' in every project this identity can see: 0
  none: a create under that name collides with nothing
```

## `--probe-release`: what each face does with a delete

This writes, on a throwaway blueprint the same run creates and deletes, and reports any residue. Run on VCF
Automation 9.1.1.0100 on 2026-10-19:

```
  release semantics, on a throwaway blueprint this run creates and deletes
     naming a version freely                 HTTP 422  BlueprintVersion.blueprint.cci.vmware.com "wrong-name" is invalid: [metadata.name: metadata.name must equal 's
     release version 1.0.0                   HTTP 200  catalog items 10 -> 11
     CCI     DELETE the version              HTTP 200  version still present: True, publishToCatalog now False, catalog items 10
     classic DELETE the same version         HTTP 405  Method 'DELETE' is not supported.
     classic unrelease, the named action     HTTP 200  accepted, which is what the CCI delete did
     CCI     DELETE the blueprint object     HTTP 200  (this is the one that cascades)
     cleanup: probe residue on the estate    none
```

The Cloud Consumption delete of a released version answered 200, left the version in place with
`publishToCatalog` false, and withdrew its catalog item: an unrelease under a delete's name. The classic face
refused the same delete and performed unrelease when asked by that name. Deleting the blueprint object is the
operation that cascades. The probe on VCF Automation 9.1 on 2026-09-18 answered every case with the same status;
it is kept in [`records/day1-release-vcf-9.1.json`](records/day1-release-vcf-9.1.json). A run without the flag
keeps the latest probe in `day1.json` and prints that it did.

## Requesting a deployment from the catalog

The request itself is `POST /catalog/api/items/{id}/request` with `deploymentName`, `projectId`, `version` and
`inputs`; the companion for the three doors (`handbook/three-doors/doors.py`) sends it and reads the deployment it
produced.
