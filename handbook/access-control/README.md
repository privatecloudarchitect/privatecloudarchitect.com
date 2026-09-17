# What the platform says you are

Companion to the chapter
([privatecloudarchitect.com/handbook/access-control](https://privatecloudarchitect.com/handbook/access-control)):
one read-only script that asks the platform to state your derived authorization on each plane, instead of
inferring it from roles and rights. Stdlib Python only; no token is printed or written.

| File | What it is |
|---|---|
| `whoami.py` | Runs a self review at the organization gateway and at a namespace's own endpoint, so you can see the two identities one bearer holds; lists the published project-role catalog; reads the ProjectRoleBinding authority beside the REST projection; asks one access review twice, once without a namespace and API group and once with both, against the matching real reads; and counts what a rules review reports in one namespace. Writes `derivation.json`, and refuses to write a record carrying any estate value or identifier. |
| `derivation.json` | That record from the reference estate, 2026-09-17. The chapter's plates render it. |
| `expected-output.md` | The transcript of that run, with what to read in it. |

## Run it

```bash
export VCFA_HOST=<automation-fqdn> VCFA_ORG=<org>
export VCFA_REFRESH_TOKEN_FILE=/path/to/refresh-token   # mode 0600; the api-token minted in the console for that org
export TLS_VERIFY=false                                 # only on a self-signed lab CA
export OUT=derivation.json

python3 whoami.py
```

## Scope, stated plainly

- Read-only. Every call is a read or a self review; self reviews and access reviews are `create` verbs in the
  Kubernetes grammar but change nothing.
- It reports **your** derivation, not the model in general. To see how a tier differs, run it as a principal
  holding that tier; the chapter's tier matrix was built exactly that way with real test principals.
- Group names in the record are the platform's own right names, which are product vocabulary. Your host,
  organization, project, namespace, user, and identifiers never enter it, and the script refuses to write a
  record in which one survived.
- An access review is a statement about RBAC wiring, not an enforcement verdict. It can answer yes where the
  admission layer then refuses, and it answers no when the question was malformed. Settle anything that matters
  with the real call against a disposable object.

## Reading the record

`organization_gateway` and `workload_plane` each carry the group count and the groups split into `from_rights`
(named for a right you hold), `system`, and `plane_scoped` (shape only). `project_roles` is the published
catalog. `authority` counts the bindings by role and lists the subject kinds; `projection` names which REST
membership arrays exist beside it. `access_reviews` is the same question asked `without_scope` and `with_scope`,
with the reason shape when allowed; `real_reads` is the status of the matching real call; `rules_review` counts
the resource rules the plane reports for you in one namespace.
