# Expected output

What `deploy.py` printed against the standalone Orchestrator 9.1.0.0400.25545107 on 2026-10-22, deploying
`example/manifest.json` (every object prefixed `pca-deptest`, or `pca_deptest` where a name cannot carry a dash): a
deploy, a readback, a second deploy, a second readback, the teardown, and a plan afterwards that finds nothing left.
The bearer was the organization's tenant token, which this appliance accepts. The record of the same run is
`deploy.json`, with every identifier replaced.

```
$ python3 deploy.py deploy example/manifest.json --record deploy-run1.json
─── DEPLOY: manifest.json ───
  ✓ Layer 1 (package): created package 'pca-deptest-package'
  ✓ Layer 2 (categories): ensured 3 categories
      • created pca-deptest-configs
      • created pca-deptest-actions
      • created pca-deptest-workflows
  ✓ Layer 3 (configuration elements): upserted 1
      • pca-deptest-config created
  ✓ Layer 4 (environments): upserted 1
      • pca_deptest_env created on python:3.11
  ✓ Layer 5 (actions): imported 1
      • pca-deptest-actions/pca_deptest_hello imported, environment pca_deptest_env written into it
  ✓ Layer 6 (workflows): imported 1
      • pca-deptest-workflow imported, 1 configuration binding(s) rebound
  package membership (not a layer; an export carries what is linked): configuration: HTTP 204, environment: HTTP 204, action: HTTP 404, workflow: HTTP 204
✓ Overall: deployed; now run readback
exit 0

$ python3 deploy.py readback example/manifest.json --record readback-run1.json
─── READBACK: manifest.json ───
  OK   action   pca_deptest_hello: reports ['actionEnvironmentName']; wants pca_deptest_env
  OK   workflow pca-deptest-workflow: conf-id names element 'pca-deptest-config' here, key greeting
exit 0

$ python3 deploy.py deploy example/manifest.json --record deploy-run2.json
─── DEPLOY: manifest.json ───
  ✓ Layer 1 (package): package 'pca-deptest-package' exists
  ✓ Layer 2 (categories): ensured 3 categories
      • pca-deptest-configs exists
      • pca-deptest-actions exists
      • pca-deptest-workflows exists
  ✓ Layer 3 (configuration elements): upserted 1
      • pca-deptest-config updated in place
  ✓ Layer 4 (environments): upserted 1
      • pca_deptest_env updated in place on python:3.11
  ✓ Layer 5 (actions): imported 1
      • pca-deptest-actions/pca_deptest_hello imported over the existing action, environment pca_deptest_env written into it
  ✓ Layer 6 (workflows): imported 1
      • pca-deptest-workflow imported, 1 configuration binding(s) rebound
  package membership (not a layer; an export carries what is linked): configuration: HTTP 204, environment: HTTP 204, action: HTTP 404, workflow: HTTP 204
✓ Overall: deployed; now run readback
exit 0

$ python3 deploy.py readback example/manifest.json --record readback-run2.json
─── READBACK: manifest.json ───
  OK   action   pca_deptest_hello: reports ['actionEnvironmentName']; wants pca_deptest_env
  OK   workflow pca-deptest-workflow: conf-id names element 'pca-deptest-config' here, key greeting
exit 0

$ python3 deploy.py teardown example/manifest.json --confirm pca-deptest-package
─── TEARDOWN: manifest.json ───
  deleted   package pca-deptest-package: HTTP 204
  deleted   workflow pca-deptest-workflow: HTTP 200
  deleted   action pca-deptest-actions/pca_deptest_hello: HTTP 200
  deleted   environment pca_deptest_env: HTTP 204
  deleted   configuration pca-deptest-config: HTTP 204
  deleted   category pca-deptest-workflows: HTTP 204
  deleted   category pca-deptest-actions: HTTP 204
  deleted   category pca-deptest-configs: HTTP 204
exit 0

$ python3 deploy.py plan example/manifest.json
─── PLAN: manifest.json ───
  → Layer 1 (package): would create package 'pca-deptest-package'
  → Layer 2 (categories): would ensure 3 categories
      • would create pca-deptest-configs
      • would create pca-deptest-actions
      • would create pca-deptest-workflows
  → Layer 3 (configuration elements): would upsert 1
      • would create pca-deptest-config
  → Layer 4 (environments): would upsert 1
      • would create pca_deptest_env on python:3.11 (offered here)
  → Layer 5 (actions): would import 1
      • would import pca-deptest-actions/pca_deptest_hello (new), environment pca_deptest_env
  → Layer 6 (workflows): would import 1
      • would import pca-deptest-workflow (id from its XML), rebinding its conf-id bindings to pca-deptest-config
→ Overall: plan complete, nothing written
exit 0
```

The second deploy left one action, one workflow and one environment of each name: layers 3 and 4 updated in place,
and layers 5 and 6 imported under the ids the objects already had. Package links: the configuration element, the
environment and the workflow joined the package; the action link answered 404, so an action created this way is not in
the package, and an export of it would not carry the action. The teardown deletes the package first: a run that
deleted it last saw the linked workflow and configuration element refused with 409 until the package was gone.
