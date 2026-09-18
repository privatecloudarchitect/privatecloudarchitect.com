# The Kubernetes estate, read from both surfaces it answers on

Companion to the chapter
([privatecloudarchitect.com/handbook/vks-operations](https://privatecloudarchitect.com/handbook/vks-operations)):
one read-only script that reads the fleet projection and the declared cluster, and reports where they differ.
Stdlib Python only; no token is printed or written.

| File | What it is |
|---|---|
| `vks.py` | Reads every estate-management kind at the organization gateway with the verbs it **declares** and the verbs you are actually **allowed**, which are different answers; each cluster's capacity and per-component control-plane health from the fleet projection, the triage read that needs no kubeconfig; the declared Cluster API object at each Supervisor namespace endpoint with its class, version, replicas and variables; and every node machine walked back through its controller owner to the declaration that produced it. Writes `vks.json`. |
| `vks.json` | That record from the reference estate, 2026-09-18. The chapter's plates render it. |

## Run it

```bash
export VCFA_HOST=<automation-fqdn> VCFA_ORG=<org>
export VCFA_REFRESH_TOKEN_FILE=/path/to/refresh-token   # mode 0600
export TLS_VERIFY=false                                 # only on a self-signed lab CA

python3 vks.py
```

## Two surfaces, and they are not the same surface

The organization gateway carries a fleet projection: one object per cluster, health and capacity, readable
without entering any cluster. The Supervisor namespace endpoint carries the declared cluster itself, a Cluster
API object whose topology is what day-2 actually edits. Asking the right question at the wrong one produces two
confusions this script makes visible:

- **A declared verb is not a permitted verb.** The fleet kinds declare a full write set and permit only reads.
  The record prints both columns, and the count of kinds where they disagree.
- **A refusal can mean "wrong place", not "not allowed".** The same list is refused at cluster scope and served
  under a namespace. The first reading of that refusal is the wrong one, so the script records the message.

## Scope, stated plainly

- Read-only throughout. There is no probe flag and no write of any kind: this plane runs live workload clusters,
  and every question worth asking about it is answerable by reading.
- The allowed-verb column describes **your** identity. Run it as a principal holding a different tier to see a
  different answer; the gap between the two columns is the finding either way.
- Every organization, project, namespace and cluster name in the record is a placeholder, and the script
  refuses to write a record in which one survived. The platform names the calling user inside some refusal
  messages, so the caller is registered as a placeholder too.

## Reading the record

`fleetKinds` is one row per kind with `declared`, `allowed`, `declaresWrite` and `permitsWrite`, and
`misleadingDeclarations` counts the rows where those disagree. `fleetClusters` is the triage read: phase,
state, cpu and memory allocatable against requested, and per-component control-plane health.
`declaredClusters` is what each namespace endpoint holds: class, Kubernetes version, control-plane replicas,
worker pools and topology variables. `ownership` is the chain made structural, with the machine and virtual
machine counts and which controller kinds own them. `scope` carries the refusal and its message. `selfRules`
is how many resource rules each surface reports for you.
