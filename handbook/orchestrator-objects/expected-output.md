# Expected output

What `objects.py` printed on the reference estate on 2026-10-21: the Orchestrator embedded in VCF Automation
9.1.1, one appliance, read-only. `--bindings` is left out because it prints the estate's own attribute names,
configuration keys and action paths, which is its job on your terminal and not something to publish.

## `--inventory`

```
$ python3 objects.py --inventory
Object kinds on this appliance

     750  packages
     420  categories
     744  workflows
     724  actions
      17  configurationElements
       4  actionEnvironments

Package namespace: 35 of 750 carry a name somebody chose; 715 carry a generated one.
  Your own package name is the only thing that makes your content findable in that list.

Categories are typed, and a name is unique only within its type:
     246  WorkflowCategory
     110  ScriptModuleCategory
      52  ResourceElementCategory
       9  ConfigurationElementCategory
       3  PolicyTemplateCategory

Action categories: 110 ScriptModuleCategory records vs 110 distinct action name prefixes -> agree
```

## `--runtimes`

```
$ python3 objects.py --runtimes
4 action environments

  runtime=python:3.11  <- NOT OFFERED: MISSING_RUNTIME
      dependencies 2  pinned 0  unpinned 2   bundle built
      memoryLimit=0  timeout=180
      unpinned: requests, urllib3   <- builds against whatever the index serves that day
  runtime=python:3.14
      dependencies 4  pinned 3  unpinned 1   bundle built
      memoryLimit=256000000  timeout=180
      unpinned: requests-credssp   <- builds against whatever the index serves that day
  runtime=powercli:13-powershell-7.4  <- NOT OFFERED: MISSING_RUNTIME
      dependencies 0  pinned 0  unpinned 0   bundle not built
      memoryLimit=1024000000  timeout=180
  runtime=python:3.11  <- NOT OFFERED: MISSING_RUNTIME
      dependencies 3  pinned 3  unpinned 0   bundle built
      memoryLimit=128000000  timeout=180

3 environment(s) name a runtime this appliance does not offer. On VCF Automation 9.1.1
such an environment ran its action on the newest runtime of the same family, so the flag is not
a failure. What can fail is the code meeting that newer runtime: prove it there before relying on it.
```

## `--package` on one solution package

```
$ python3 objects.py --package <your package>
Package: 21 references

     13  actions
      5  workflows
      2  configurations
      1  environments
      0  resources
      0  policy-templates
      0  environment-repositories
      0  workflowTokens
```

## `--sweep`

```
$ python3 objects.py --sweep
Read 744 workflow definitions (0 unreadable)

    361  call at least one action (319 by an action element, 110 from a script)
    368  are inline script only (no action, no runtime, no packaging)
     15  have neither
     52  bind at least one attribute to a configuration element

  items: 3824 total, 759 call an action (640 elements, 119 scripts), 1530 are inline script
  attributes: 2217 total, 163 bound to a configuration element

  The split decides how much of this applies to you: a workflow that never calls
  an action needs no runtime and no packaging at all.
```

The sweep's counts are the record's (`objects.json`, `sweep`), printed through the probe's own summary; the
record run read every workflow once.
