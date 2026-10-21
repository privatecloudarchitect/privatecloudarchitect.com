# What the platform says you are

Companion to the chapter
([privatecloudarchitect.com/handbook/access-control](https://privatecloudarchitect.com/handbook/access-control)):
a read-only script that asks the platform to state your derived authorization on each plane, instead of
inferring it from roles and rights, and a second that re-asks the chapter's write findings on your build, each on a
throwaway. Stdlib Python only; no token or password is printed or written.

| File | What it is |
|---|---|
| `whoami.py` | Runs a self review at the organization gateway and at a namespace's own endpoint, so you can see the two identities one bearer holds; lists the published project-role catalog; reads the ProjectRoleBinding authority beside the REST projection; asks one access review twice, once without a namespace and API group and once with both, against the matching real reads; and counts what a rules review reports in one namespace. Writes `derivation.json`, and refuses to write a record carrying any estate value or identifier. |
| `derivation.json` | That record from the reference estate, read on VCF Automation 9.1.1.0100.25757808 on 2026-10-13. The chapter's plates render it. |
| `reprobe.py` | The writes behind the chapter, each named by a flag and none without one: a directory group imported under the automation grant and under a session login, then removed (`--probe-import GROUP`); what a project administrator may do to projects, the update and delete sent as dry runs (`--probe-project-scope`); and a throwaway namespace where two members edit and delete each other's objects (`--probe-namespace`). Every object it makes it removes and looks for again. Writes `reprobe.json`. |
| `reprobe.json` | That record from the reference estate, the three probes run on VCF Automation 9.1.1.0100 on 2026-10-21 on the operator's go. |
| `expected-output.md` | The transcripts of both, with what to read in them. |

## Run it

```bash
export VCFA_HOST=<automation-fqdn> VCFA_ORG=<org>
export VCFA_REFRESH_TOKEN_FILE=/path/to/refresh-token   # mode 0600; the api-token minted in the console for that org
# or a bearer you already hold, such as a session login's:  export VCFA_BEARER_FILE=/path/to/bearer   (mode 0600)
export VC_HOST=<vcenter-fqdn>                           # optional: what the same bearer answers at vCenter
export TLS_VERIFY=false                                 # only on a self-signed lab CA
export OUT=derivation.json

python3 whoami.py
```

The re-probes write, so each runs only when you name it, and each checks its preconditions before the first write
(the group is in the directory and not yet imported; the test users hold the roles the order says):

```bash
export VCFA_USER=<org-admin> VCFA_PASSWORD_FILE=/path/to/password             # mode 0600: session login, reads, cleanup
export VCFA_TEST_USERS=<member>,<advanced>,<admin>                            # bound edit, edit_adv, admin in PROJECT
export VCFA_TEST_PASSWORD_FILE=/path/to/test-password                         # mode 0600
export PROJECT=<project> FOREIGN_PROJECT=<one-the-admin-is-not-in> TEMPLATE_NAMESPACE=<a-namespace-in-PROJECT>
export OUT=reprobe.json

python3 reprobe.py --probe-import "<a directory group with no members>"       # VCFA_REFRESH_TOKEN_FILE adds the grant leg
python3 reprobe.py --probe-project-scope
python3 reprobe.py --probe-namespace
```

| Exit | whoami.py | reprobe.py |
|---|---|---|
| 0 | recorded | recorded |
| 1 | the record would carry an estate value, so it was not written | the record would carry an estate value, so it was not written |
| 2 | | a precondition refused the run; nothing was written |
| 3 | a read failed, or no project was visible | a call failed |
| 5 | usage: it takes no options, a variable is unset, or a credential file is missing or open to group or other | usage: no probe named, an unknown option, a variable unset, or a credential file missing or open to group or other |

## Scope, stated plainly

- Read-only. Every call is a read or a self review; self reviews and access reviews are `create` verbs in the
  Kubernetes grammar but change nothing.
- It reports **your** derivation, not the model in general. To see how a tier differs, run it as a principal
  holding that tier; the chapter's tier matrix was built exactly that way with real test principals.
- A self review's answer carries the bearer you sent, in its `extra` field. The script compares that value with
  its own bearer by digest, records only whether they matched, and keeps no value; do the same in any tool of your
  own that calls the review.
- Group names in the record are the platform's own right names, which are product vocabulary. Your host,
  organization, project, namespace, user, and identifiers never enter it, and the script refuses to write a
  record in which one survived.
- An access review is a statement about RBAC wiring, not an enforcement verdict. It can answer yes where the
  admission layer then refuses, and it answers no when the question was malformed. Settle anything that matters
  with the real call against a disposable object.

## Reading the record

`organization_gateway` and `workload_plane` each carry the group count, the names of the answer's `extra` fields
and `extra_hands_back_the_bearer_sent` (the digest comparison above), and the groups split into `from_rights`
(named for a right you hold), `system`, and `plane_scoped` (shape only). `project_roles` is the published
catalog. `authority` counts the bindings by role and lists the subject kinds; `projection` reads every REST membership
array on the same project and records, for each, how many principals it holds and which role's bindings hold
exactly the same principals (`sameAsBindingsOfRole`), compared principal by principal in the script and never
written out. `access_reviews` is the same question asked `without_scope` and `with_scope`,
with the reason shape when allowed; `real_reads` is the status of the matching real call; `rules_review` counts
the resource rules the plane reports for you in one namespace.

## The third surface

Set `VC_HOST` and the script also presents **the bearer it already holds** to vCenter and records the answer.
It needs no vCenter credential, because the finding is the refusal.

On the estate this was verified against it answered `401` as a bearer token, `401` as a session id, and `401`
with no credential at all. Identical. The token that reads the organization gateway in the same run is not a
weak credential at vCenter; it is not a credential there. vCenter takes its own sign-in and decides by its own
grants, so no dial in this chapter sets them. Where the organization signs in through VCF single sign-on, the
person behind both can be the same directory user, and the two grants are still made and reviewed in different
places.

That is a boundary of the model rather than a gap in it, and it means the platform cannot close that door for
you. vCenter accounts are a separate grant needing a separate review, and they will not appear in any access
review this chapter describes.
