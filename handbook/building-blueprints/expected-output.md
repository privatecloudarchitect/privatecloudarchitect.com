# What `shapes.py` prints

Run against one VCF Automation 9.1.1.0100 organization on 2026-10-19, signed in with a session login, from this
folder of the companion repository with `--validate ../day1-provisioning/templates`, so the five template
blueprints of the crawl-walk-run series were sent to the platform's own validation. Your census will differ;
the shapes should not.

```
shapes.py: every blueprint on this estate, measured rather than described

  census: 14 blueprint(s) across 2 project(s) parsed (0 would not parse)
     size 840 to 48,100 bytes, a 57 times range
     49 resource declaration(s) of 2 distinct type(s); blueprints declaring each type: {'CCI.Supervisor.Namespace': 13, 'CCI.Supervisor.Resource': 13}
     declarable but never used here: ['CCI.VPC', 'CCI.VPC.Configuration', 'Util.PasswordEntry']
     input types: {'string': 73, 'integer': 2, 'boolean': 4}
     string inputs: 73; 28 carry a pattern or an enumeration (10 a pattern, 18 an enumeration), 57 a default, 45 neither a pattern nor an enumeration

  schema join: 10 catalog item(s), the same set under every project: True; 10 matched to a blueprint of their name in some project, 0 matched to none
     10 of the 10 have schema properties whose key set is identical to the blueprint's inputs
     keys the generator adds, counted over 74 propert(ies): {'encrypted': 64}
     inputs declaring no default, by type, and whether they became required:
        boolean   no default, NOT required: 2
        string    no default, required: 13

  validation: 5 template(s) under the directory, and 3 controls broken on purpose
     01-single-vm/single-vm.blueprint.yaml        valid
     02-vm-cloud-init/vm-cloud-init.blueprint.yaml valid
     03-web-pair/web-pair.blueprint.yaml          valid
     04-hybrid-3tier/hybrid-3tier.blueprint.yaml  valid
     05-microservices/microservices.blueprint.yaml valid
     an unknown resource type                     refused: Resource type CCI.NotAType not found
     a namespace missing its required fields      refused: Failed to match exactly one schema (matched 0 out of 2) One of: Existing namespaces requir
     content that is not YAML                     refused: Failed to parse blueprint: while parsing a flow sequence in 'reader', line 2, column 12: r
     blueprints and blueprint requests: 14 and 0 before, 14 and 0 after

wrote shapes.json (14 blueprints, 2 resource type(s) in use of 5 declarable); every organization name replaced by a placeholder
```

## What each block tells you

- **census**: every blueprint in every project, parsed as YAML: the size range, the resource declarations and
  the types they use, the declarable types never used, the input types, and for string inputs how many carry a
  pattern or an enumeration, a default, or neither.
- **schema join**: every catalog item set against the blueprint of its name in any project (the catalog lists
  the same items under every project path); how many share their blueprint's input keys exactly, what the
  generator adds to each property, and which inputs without a default became required.
- **validation**: each template under the directory and each of three blueprints broken on purpose, sent to
  `POST /blueprint/api/blueprint-validation`, which answers valid or refused with the reason and creates nothing;
  the blueprint and blueprint-request counts before and after prove it.
