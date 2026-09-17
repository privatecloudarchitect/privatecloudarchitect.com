# The construct model, read from your own estate

Companion to the chapter
([privatecloudarchitect.com/handbook/construct-model](https://privatecloudarchitect.com/handbook/construct-model)):
the containment spine and the taxonomy the chapter draws, read through the Cloud Consumption Interface with an
organization's OAuth bearer, written as two records with every estate name replaced by a placeholder. The chapter's
plates are rendered from the records in this folder; run the script and you have the same two records for yours.

| File | What it is |
|---|---|
| `naming-standard.json` | The object naming standard: for each of nineteen constructs, the grammar its name must follow, a name that satisfies it, and the anchored pattern that enforces it. Published from the same machine-readable module the estate's own linter runs, with a neutral region token, and every example re-checked against the pattern it illustrates. `inventory.py` reads this file to audit your names; the chapter's plates render it. |
| `inventory.py` | Read-only. Discovers every VMware API group the interface declares and records each kind with its scope (published at the top level, or under a project), its verbs, and how many of each top-level kind the organization can see; then walks the tree: projects, the binding kinds each carries (regions, classes, VPCs, subnets, service engine groups, infra policies), role bindings and their roles, images and catalog items, namespaces with the fields each bound at create (region, zone, class, VPC, storage classes, VM classes, overrides) and their phase, and behind each namespace's endpoint the virtual machines and VKS clusters. Then it audits every name it met against `naming-standard.json` and writes the counts. Refuses to write a record in which any estate name survived, and the naming record may carry only values that came from the standard itself. Stdlib Python; no token printed or written. |
| `taxonomy.json` | The interface as declared on the reference estate, 2026-09-16: 13 VMware API groups, one line per kind. |
| `estate.json` | The tree as it stood: one organization, two projects, three namespaces, and what each bound. |
| `naming.json` | The conformance audit of that estate: per construct, how many names conform, the grammar they should follow, and a verdict of keep, refine, or rename. Counts only, never a name. |
| `bindings.json` | What the interface answered when the script asked whether a namespace's class, region, VPC, and parent project can be changed after create. Five attempts, each with the question, what was sent, and the server's own sentence. Written only when you pass `--probe-bindings`. |
| `expected-output.md` | The transcript of that run. |

## Run it

```bash
export VCFA_HOST=<automation-fqdn> VCFA_ORG=<org>
export VCFA_REFRESH_TOKEN_FILE=/path/to/refresh-token      # mode 0600; the api-token minted in the console for that org
export TLS_VERIFY=false                                    # only on a self-signed lab CA
export OUT_DIR=.

python3 inventory.py                       # read-only
python3 inventory.py --probe-bindings      # also ask whether a namespace's bindings can be changed
```

### About `--probe-bindings`

The chapter claims a namespace binds four planes at create and refuses to rebind them. That claim should be the
platform's answer, not ours, so the flag asks it and records the reply. It sends five requests the server is
built to refuse, and every one carries a value that cannot be applied anyway: a class, a region and a VPC named
`zz-probe-value-that-exists-nowhere`, and a parent project sent in the body while the URL still addresses the
real parent, which is the shape a Kubernetes API server rejects as a mismatch rather than a move. The script
reads the namespace before and after and **refuses to write the record if one byte of its spec moved**.

Two things to know before you run it on an estate you care about:

- **Patching a field the server accepts is not a no-op.** Any accepted patch, even one setting a field to the
  value it already holds, dispatches a tenant-manager edit task on that namespace; the next request then answers
  `409 ... edit in progress` instead of the question you asked. The script sends only values that cannot be
  applied, and waits out a 409 rather than reporting it as an answer.
- **There is no dry run.** The interface rejects `dryRun=All`, so aiming at values the server cannot apply is
  the safe substitute, not a preference.

It asks about the first namespace it finds, and needs a second project to exist for the last question.

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
- The refusal record covers this interface only. A second surface, the Tenant Manager's own namespace update,
  takes a body carrying the project assignment; a tenant identity is refused there for want of a right before
  the change is evaluated, so whether a provider identity could reassign a namespace that way is untested here.
  What is documented is a cross-project copy rather than a move: a namespace can be captured as a blueprint and
  redeployed under another project, and the original stays where it is.
- Recorded on one 9.1 organization on 2026-09-16, and the bindings asked on 2026-09-17; your counts will differ,
  the shapes should not.
- The naming audit is a format check, not a judgement of meaning: a name can satisfy its pattern and still say
  nothing about what the object isolates. Read the verdict as a work list and assign the last word yourself.
- Tune the standard to your estate before you audit against it. The vocabularies are the parts that travel least
  well: your environments, your region grammar, and your size names are yours, and the file is small on purpose.

## Reading the records

`taxonomy.json` is a list of `{group, version, kind, resource, namespaced, verbs, count}`; `namespaced` true means
the kind lives under a project. `estate.json` is `{organization, published, projects}`: `published` carries the
regions, zones (with limits and usage), namespace classes, VPCs, subnet and quota counts; each project carries its
`bindings` counts, `roleBindings` (count, roles, fields), `images`, `catalogItems`, and `namespaces`, each with
`phase`, `bound` (region, zone, class, vpc, storage classes, VM classes, overrides), `specFields`, and `workloads`.
`naming.json` is `{construct: {objects, conform, convention, example, pattern, verdict}}`: `objects` is how many
of that construct the audit met, `conform` how many matched the pattern, and the verdict is `keep` when all of
them did, `rename` when none did, and `refine` in between.
