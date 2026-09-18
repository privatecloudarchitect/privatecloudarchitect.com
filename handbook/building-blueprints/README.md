# The shape of every blueprint on an estate, measured

Companion to the chapter
([privatecloudarchitect.com/handbook/building-blueprints](https://privatecloudarchitect.com/handbook/building-blueprints)):
one read-only script that counts what blueprints actually are on your estate instead of asserting it from a
handful of examples. Stdlib Python plus PyYAML; no token is printed or written.

| File | What it is |
|---|---|
| `shapes.py` | Parses every blueprint's content **as YAML**, then reports four things: the shape census (size, input count, resource count and the resource types each one really declares), which declarable types are never used, the types the inputs are declared with, and a join of each blueprint's inputs against the schema its catalog item publishes. Writes `shapes.json`, and refuses to write a record carrying an estate value. |
| `shapes.json` | That record from the reference estate, 2026-09-18. The chapter's plates render it. |

## Run it

```bash
export VCFA_HOST=<automation-fqdn> VCFA_ORG=<org>
export VCFA_REFRESH_TOKEN_FILE=/path/to/refresh-token   # mode 0600
export TLS_VERIFY=false                                 # only on a self-signed lab CA

python3 shapes.py
```

## Parse, do not search

This is the reason the script exists in this form. A text search for `type:` across blueprint content finds
input declarations and fields inside embedded Kubernetes manifests as well as resource types, and reports a
vocabulary roughly three times larger than the real one. The first version of this script did exactly that.
Parsing each document and reading `resources[].type` gives the real answer, which on the reference estate is
**two resource types across 14 blueprints**, not six.

## Scope, stated plainly

- Read-only. Every call is a `GET`.
- It measures **your** estate. The shape it finds is a fact about what has been built there, not a statement
  about what the platform permits; the never-used list is the second half of that pair.
- The schema join reads what the catalog generator publishes today. A generator change moves those numbers,
  which is a reason to re-run it rather than to quote it.
- Every organization and project name in the record is a placeholder.

## Reading the record

`census` is one row per blueprint (size in bytes, input count, resource count, the resource types declared) and
`sizeRange` is the widest and narrowest of them, which is where "one shape carries an estate from a single
machine to a whole application" becomes visible or does not. `resourceTypesUsed` counts the types that appear
and `typesNeverUsed` names the declarable ones that never do. `inputTypes` is the input vocabulary.
`schemaJoins` is one row per blueprint with a catalog item: how many inputs it declares, how many properties
the generated schema carries, whether the key sets are identical, and what ends up required.
`generatorAddsPerProperty` names what the generator adds to every property, and `requiredByInputType` is the
rule the required list actually follows.
