# orchestrator-dependencies

Companion to the chapter
([privatecloudarchitect.com/handbook/orchestrator-dependencies](https://privatecloudarchitect.com/handbook/orchestrator-dependencies)):
a deploy engine for Orchestrator content that creates it in the order its bindings force, writes the two identifiers
the target appliance issues into the content before uploading it, and reads both back afterwards. Stdlib Python only;
no token is printed or written.

| File | What it is |
|---|---|
| `deploy.py` | `validate` (offline), `plan` (GETs only), `deploy` (the six layers), `readback` (the two identifier bindings, read back from the appliance) and `teardown` (deletes exactly what the manifest names). |
| `example/` | A manifest and one of each object the six layers create: a configuration element, a Python environment, an action, and a workflow that reads the element through its `conf-id` and `conf-key`. Every name is prefixed `pca-deptest` (`pca_deptest` where a name cannot carry a dash), so a rehearsal touches nothing else. |
| `deploy.json` | The record of the rehearsal on the reference estate's standalone Orchestrator: both deploys, both readbacks, the counts after each, the teardown and the residue read, every identifier replaced. |
| `expected-output.md` | What the rehearsal printed. |

## Run it

```bash
export VRO_HOST=<orchestrator-fqdn>
export VRO_TOKEN_FILE=~/.secrets/vro-bearer    # mode 0600: a bearer this appliance accepts
export TLS_VERIFY=false                        # only on a self-signed lab CA

python3 deploy.py validate example/manifest.json     # offline
python3 deploy.py plan example/manifest.json         # GETs only
python3 deploy.py deploy example/manifest.json
python3 deploy.py readback example/manifest.json; echo "exit $?"
python3 deploy.py teardown example/manifest.json --confirm pca-deptest-package
```

Exit codes: 0 done, or nothing wrong found; 1 validation blockers, a failed layer, or a readback that found a binding
that does not resolve on this appliance; 2 a usage error, or a token file open to group or other; 3 a read or sign-in
failed; 4 a record refused to write because the appliance's host name survived.

## The six layers, and what each hands on

1. **The package**, created by a bare `PUT` (a JSON body is refused).
2. **The categories**, one each for configuration elements, actions and workflows, found or created by name.
3. **Configuration elements**, upserted by name in their category. Their ids go to layer 6.
4. **Environments**, upserted by name. The runtime must be one the appliance offers (`plan` checks it before anything
   is written). Their ids go to layer 5.
5. **Actions**, packaged here with the layer-4 environment id written into each one (`<environment>` in the action's
   content), under an id derived from the module and name, so a second deploy overwrites rather than duplicates.
6. **Workflows**, with every `conf-id` rewritten to the layer-3 element of the same `conf-name` (or the only element,
   when the manifest declares one). A binding the deploy cannot match is left as authored and never guessed at;
   `validate` refuses a manifest where that would happen.

After a deploy, run `readback`. It fetches each action and confirms the environment it reports is the one layer 4 made
on this appliance, and fetches each workflow's definition and confirms every `conf-id` names an element here. The
import accepts content that names objects from another appliance, so a deploy can succeed and be wrong; the readback
is how you tell.

## Package membership, and the teardown

`deploy` links each object to the package as it creates it, because an export carries what the package holds. On the
reference estate the configuration element, the environment and the workflow joined; the action link answered 404, so
an action deployed this way is not in the package. A workflow or configuration element in a package refused delete
with 409 while the package existed, so `teardown` deletes the package first (which leaves its contents in place), then
the newest layer first, and prints each refusal's reason.

## Scope, stated plainly

- `validate` and `plan` write nothing. `deploy` and `teardown` write, and `teardown` refuses to run unless
  `--confirm` names the manifest's package.
- The rehearsal ran on one standalone Orchestrator at one build, recorded in `deploy.json`. A pinned runtime is checked
  against what the appliance offers; whether your content runs on it is a test of its own.
- Every identifier in a record is replaced, and a record carrying the appliance's host name is refused.
