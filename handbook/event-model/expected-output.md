# What the gate printed on the reference estate

One run of the gate's documented path on 2026-10-07, VCF Automation 9.1 (one All Apps organization) with its
registered standalone Orchestrator. Every object was a throwaway named `pca-gate-probe-<stamp>`: the workflow, its
category, the subscription, and four deployments of one ConfigMap each in an existing namespace, under one
template resource name the subscription's criteria named and nothing else in the organization carries. Host
names, project and object identifiers are replaced by placeholders; nothing else is edited.

The registry was a stand-in on both runs: first an address in a range reserved for documentation, which no host
answers, so the gate's request times out; then a path on a web server that answers 404, which is
what a registry holding no record of the machine answers.

## 1. Apply: import, wait for the dispatch plane, subscribe, read back

```
$ python3 deploy_gate.py --name pca-gate-probe-10071824 --category pca-gate-probe-10071824 \
    --registry https://192.0.2.1/registry --deadline 20 --insecure-registry \
    --resource-name PcaGateProbe10071824 --project-id <project id> --wait 1200 --apply
workflow   pca-gate-probe-10071824  id <workflow id>  (4297 bytes, python:3.11, gate.py embedded unchanged)
           registryUrl https://192.0.2.1/registry  deadlineSeconds 20  verifyTls False
category   pca-gate-probe-10071824 on orchestrator.example.net
subscribe  deployment.resource.request.pre, blocking, timeout 0, criteria event.data["resourceName"] == "PcaGateProbe10071824", project <project id>
category   created (201), read back present
import     202; read back 200: script is gate.py, runtime python:3.11, registryUrl https://192.0.2.1/registry, deadlineSeconds 20.0, verifyTls False
dispatch   the Automation host resolves the workflow (200) after 458 s
subscribe  201; read back 200: every field as sent
             eventTopicId  "deployment.resource.request.pre"
             type          "RUNNABLE"
             runnableType  "extensibility.vro"
             runnableId    "<workflow id>"
             subscriberId  "service-account-project-serviceaccount"
             criteria      "event.data[\"resourceName\"] == \"PcaGateProbe10071824\""
             blocking      true
             timeout       0
             disabled      false
exit 0
```

The 458 seconds are the wait for the Automation host's next enumeration of the Orchestrator. Read beside it, the
integration's last enumeration moved from 18:22:21Z (before the import) to 18:32:32Z, and the workflow resolved
on that pass; the next passes ran at 18:42:32Z and 18:52:34Z. Re-running `--apply` for the same name re-imported
the workflow (202) and resolved in 1 second, because the id was already known.

This first subscription sent the project as a single string, and it never ran: a create half a minute later
fired both resource-scoped request events in the broker's log and started no workflow. With no project
constraint it ran on the next create, and with the project sent as a list it ran on the one after; set back to a
string, it again ran on none, a minute after the change. While it was a string, the audit said so:

```
$ python3 events.py --subscriptions
1 subscription

  CANNOT DISPATCH pca-gate-probe-10071824                  deployment.resource.request.pre    blocking
        - its project constraint is a string, not a list of project ids, so it matches no event and never fires

  1 of 1 cannot dispatch, 0 cannot hold the operation they block; the platform reports none of them as an error
exit 2
```

`deploy_gate.py` now sends `--project-id` as a list and compares the constraint in its read-back. With the list:

```
$ python3 events.py --subscriptions
1 subscription

  ok              pca-gate-probe-10071824                  deployment.resource.request.pre    blocking

  0 of 1 cannot dispatch, 0 cannot hold the operation they block
exit 0
```

## 2. A create, a refused delete, and the same delete passing

Two creates under the dispatching subscription each ran the gate once, on `CREATE_RESOURCE`, and the deployment
completed with the registry unreachable: the gate did not call it. One delete with the registry unreachable ran
the gate for 23 seconds against its 20-second deadline and refused; the request failed and both of the
deployment's resources stayed in place:

```
request FAILED (+65 s)
    details: Failed to process ebs event: SubscriberID: service-account-project-serviceaccount, RunnableID: <workflow id>
    and SubscriptionID: pca-gate-probe-10071824 failed with the following error: Workflow run [<run id>] completed
    with error [Wrapped ch.dunes.scripting.server.polyglot.PolyglotRunnerException: the de-registration did not
    finish inside 20 s (2 attempt(s), last: URLError: timed out); refusing the delete (Workflow:pca-gate-probe-10071824
    / Unregister, then let the delete continue (item1)#1)]
deployment DELETE_FAILED; resources [Namespace OK, PcaGateProbe10071824 OK]
```

Then `--apply` again with `--registry` pointed at the path that answers 404, and the identical delete went
through in 33 seconds; so did the other three deployments. The runs, newest first:

```
$ python3 deploy_gate.py --name pca-gate-probe-10071824 --runs --last 10
7 run(s) of pca-gate-probe-10071824

  2026-10-07T18:44:39  completed     3 s  run <run id>
        DELETE_RESOURCE on PcaGateProbe10071824: unregister <resource id> before it is removed
        already absent (HTTP 404), counted as done after 1 attempt(s) in 0.0 s; the delete may continue
  2026-10-07T18:44:04  completed     3 s  run <run id>
        DELETE_RESOURCE on PcaGateProbe10071824: unregister <resource id> before it is removed
        already absent (HTTP 404), counted as done after 1 attempt(s) in 0.0 s; the delete may continue
  2026-10-07T18:43:34  completed     3 s  run <run id>
        DELETE_RESOURCE on PcaGateProbe10071824: unregister <resource id> before it is removed
        already absent (HTTP 404), counted as done after 1 attempt(s) in 0.0 s; the delete may continue
  2026-10-07T18:42:54  completed     3 s  run <run id>
        DELETE_RESOURCE on PcaGateProbe10071824: unregister <resource id A> before it is removed
        already absent (HTTP 404), counted as done after 1 attempt(s) in 0.0 s; the delete may continue
  2026-10-07T18:40:34  failed       23 s  run <run id>
        DELETE_RESOURCE on PcaGateProbe10071824: unregister <resource id A> before it is removed
        raised: the de-registration did not finish inside 20 s (2 attempt(s), last: URLError: timed out); refusing the delete
  2026-10-07T18:37:09  completed     3 s  run <run id>
        CREATE_RESOURCE on PcaGateProbe10071824: not a delete, nothing to do
  2026-10-07T18:35:20  completed    25 s  run <run id>
        CREATE_RESOURCE on PcaGateProbe10071824: not a delete, nothing to do
exit 0
```

`<resource id A>` is the same resource on both lines: the refused delete and the one that passed. The first run
took 25 seconds and the rest 3, probably the first start of the Python runtime; that was not measured.

## 3. Remove, and the residue

```
$ python3 deploy_gate.py --name pca-gate-probe-10071824 --category pca-gate-probe-10071824 --remove --apply
subscription  delete 204, read back 404
workflow      delete 200, read back 404 on the Orchestrator
category      delete 204, read back absent
residue       none
exit 0
```

The Automation host went on answering 200 for the deleted workflow until its next enumeration seven minutes
later, then 404; `--remove` now prints that line when it happens. Read afterwards: no subscription in the
organization, no deployment named `pca-gate-probe-*`, no ConfigMap of that name in the namespace, and the
workflow and category absent on the Orchestrator.
