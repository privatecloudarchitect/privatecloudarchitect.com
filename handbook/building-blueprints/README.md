# Validate the template series, and measure the blueprints on an estate

Companion to the chapter
([privatecloudarchitect.com/handbook/building-blueprints](https://privatecloudarchitect.com/handbook/building-blueprints)),
which teaches authoring an application blueprint crawl to run with the template series in
[`../day1-provisioning/templates`](../day1-provisioning/templates). One script does two things: it sends each
template blueprint to the platform's own validation, which creates nothing, and it measures every blueprint your
estate already holds. Stdlib Python plus PyYAML; no token or password is printed or written.

**Provenance:** run on VCF Automation 9.1.1.0100 on 2026-10-19 under a session login
([`expected-output.md`](expected-output.md)). The 9.1 census of 2026-09-21 is kept in [`records/`](records/).

| File | What it is |
|---|---|
| `shapes.py` | Parses every blueprint's content **as YAML** and reports the census (size, input count, resource count and the resource types each one really declares), which declarable types are never used, the types the inputs are declared with and, for every string input, whether it carries a pattern, an enumeration or a default; then joins each catalog item to the blueprint of its name in any project and compares the generated schema with the blueprint's inputs. With `--validate <dir>` it also sends every `*.blueprint.yaml` under the directory to the platform's blueprint validation, beside three blueprints broken on purpose. Writes `shapes.json`, and refuses to write a record carrying an estate value. |
| `shapes.json` | That record from the reference estate. The chapter's plates render it. |
| `expected-output.md` | What the script printed on the reference estate, with `--validate ../day1-provisioning/templates`. |
| `records/shapes-vcf-9.1.json` | The 9.1 census of 2026-09-21, as that run wrote it (its project placeholders carry the collision described below). |

## Run it

```bash
export VCFA_HOST=<automation-fqdn> VCFA_ORG=<org> VCFA_USER=<account>
( umask 077; mkdir -p ~/.vcf && cat > ~/.vcf/vcfa-password )   # paste your password, then Ctrl-D
export VCFA_PASSWORD_FILE=~/.vcf/vcfa-password             # mode 0600; or VCFA_REFRESH_TOKEN_FILE
export TLS_VERIFY=false                                    # only on a self-signed lab CA

python3 shapes.py                                          # the census alone
python3 shapes.py --validate ../day1-provisioning/templates
```

The sign-in is a session login as `<account>@<org>`, or a refresh token minted for the organization in a file of
mode 0600. A secret file open to group or other is refused before it is read.

Exit codes: 0 written (with `--validate`, every template valid and every control refused); 1 with `--validate`, a
template was refused or a control was not; 2 a call failed or the sign-in was refused; 3 with `--validate`, the
blueprint or blueprint-request count moved, which a validation must never do; 5 an unknown argument.

## Validation that creates nothing

`POST /blueprint/api/blueprint-validation` takes a blueprint's content and a project id and answers `valid` with
any messages. The script reads the blueprint and blueprint-request counts before and after, and stops with exit 3
if either moved. A "valid" is only worth having from a validator that can refuse, so three blueprints broken on
purpose go with every run: an unknown resource type, a namespace missing its required fields, and content that is
not YAML. Valid is not deployed: a blueprint that validates can still fail at request time on something only the
estate knows, such as an image that is not there.

The project id comes from `GET /project-service/api/projects`, which refuses a `sort=` parameter on 9.1.1 (it
names OData `$orderby`), so the script reads it unsorted and stops if the list ever spans pages.

## Parse, do not search

A text search for `type:` across blueprint content finds input declarations and fields inside embedded
Kubernetes manifests as well as resource types, and reports a vocabulary several times larger than the real one.
Parsing each document and reading `resources[].type` gives the real answer.

## Scope, stated plainly

- Read-only, apart from the session login and the validation calls, which create nothing and are proved to.
- Every list is read to its end, following the continue token, and a list that fails ends the run.
- The catalog lists the same items under every project path, while a blueprint lives in one project, so each item
  is joined to the blueprint of its name in any project.
- Every organization, project and blueprint name in the record is a placeholder. The scrubber never reaches inside
  a placeholder it has already written: an estate can name a project exactly what a placeholder says, and the 9.1
  record shows what happens otherwise, two projects collapsed into one.

## Reading the record

`census` is one row per blueprint (`project`, `bytes`, `inputs`, `resources`, `resourceTypes`), with
`resourceDeclarations`, `resourceTypesUsed`, `typesNeverUsed` and `sizeRange`. `inputTypes` counts inputs by type
and `stringInputs` splits the strings by `pattern`, `enumeration`, `default`, `constrained` and `unconstrained`.
`schemaJoins` is one row per catalog item joined to its blueprint, with `schemaMatches`, `schemaProperties`,
`generatorAddsPerProperty` and `requiredByInputType`; `sameItemsUnderEveryProject` and `itemsWithoutABlueprint`
describe the join itself. `validation` is present with `--validate`: each template and control with whether it was
valid and the platform's messages, and `countsUnchanged`.
