# Can every namespace see the VM images it needs, and will your pins still resolve?

`libraries.py` answers that for a VCF Automation organization, namespace by namespace, by reading the layer each answer
lives on. It is read-only.

Proven on VCF Automation 9.1.1.0100 and vCenter 9.1.1 on 2026-10-28, on an estate where the provider content library
had just been rebuilt: every namespace saw the rebuilt library's images through the Supervisor, every namespace's own
vCenter setting was empty, and a blueprint pinned before the rebuild resolved nowhere.

## Run it

```
export VCFA_HOST=<automation-fqdn> VCFA_ORG=<org>
( umask 077; mkdir -p ~/.vcf && cat > ~/.vcf/vcfa-password )   # type the password, then Ctrl-D
export VCFA_USER=<account> VCFA_PASSWORD_FILE=~/.vcf/vcfa-password   # mode 0600; or VCFA_REFRESH_TOKEN_FILE
export TLS_VERIFY=false                                              # only on a self-signed lab CA
python3 libraries.py                         # every namespace the account can list
python3 libraries.py --pins ./blueprints     # and every image pin under ./blueprints
python3 libraries.py --namespace <name>      # one namespace
```

With `--vcenter` it also reads the provider side (the Supervisor's library list and each namespace's own library
setting) from the vCenter that runs the Supervisor; set `VC_HOST`, `VC_USER` and `VC_PASSWORD_FILE` (mode 0600). A
secret file open to group or other is refused before it is read.

`expected-output.md` shows both runs: an estate where everything resolves, and a pin left over from a library rebuild.

## What it teaches

An image reaches a namespace by one of three attachments, and each lives on a different layer:

| Attachment | What the namespace holds | Where the images appear | What makes it |
|---|---|---|---|
| Supervisor-wide | a `ClusterContentLibrary` | `clustervirtualmachineimages`, in every namespace | a provider library in VCF Automation |
| Per namespace | a `ContentLibrary` (type `ContentLibrary`) and an entry in its vCenter setting | `virtualmachineimages` | an organization library with auto-attach on, or a hand-made attach |
| Project folder | a `ContentLibrary` (type `Inventory`) | `virtualmachineimages` | a project-scoped library |

The script attributes every image to the library that delivered it (the image names a library item, the item names
its library) and keeps the Kubernetes release images apart, since a long cluster list of those says nothing about
whether a VM image is there.

A pin is checked the way admission reads it: an id (`vmi-...`) resolves when an image carries that id; a display name
resolves when exactly one image carries that name. An image id belongs to the library item, so rebuilding a library
gives every image a new id, and an id pinned before the rebuild resolves nowhere. Updating an item's content in place
keeps its id while the bits change.

## Scope, stated plainly

- It reads one organization, as that organization's account. A namespace whose endpoint does not answer is reported as
  not read (exit 3), which is not a finding.
- `--pins` reads `vmi-...` ids anywhere in a YAML or JSON file, and display names only from an `imageName` key at the
  start of a line. A blueprint input whose default is a display name is not read.
- Whether a display name carried by two images resolves at admission was not tested; the script reports such a pin as
  ambiguous rather than guessing.
- It does not read the library's items from vCenter, only what the namespaces can name, and it does not compare image
  content, so an in-place update that changed the bits under an id is not visible here.

## Reading the record

`libraries.json` (or `OUT_DIR/libraries.json`) carries placeholders for every organization, project, namespace, library,
image, file and host name and every image id, the same placeholder each time a name appears; the script refuses to
write a record in which one survived.

- `orgLibraries`: what VCF Automation lists for the organization: `kind` (`PROVIDER` or `TENANT`), `autoAttach`
  (always `true` for provider and project libraries), `projectScoped`, `status`, `subscribed`, `regions`.
- `namespaces[]`: per namespace, `images` (the general-purpose images it can name, each with its `scope`, `library`
  and the attachment it came `via`), `kubernetesImages` (the count of release images, kept apart), `attachments` (each
  library the namespace holds, its `via`, `type`, `naming` strategy, `ready`, and how many images it delivered), and
  `pins` with `--pins`.
- `vcenter` with `--vcenter`: the Supervisor's library list (each entry's library, whether it serves Kubernetes
  releases, its naming strategy, and whether vCenter still holds it) and, per namespace, how many entries its own
  setting holds and how many name no library.
- `findings`: a namespace with no general-purpose image, an attachment that is not ready, a pin that resolves nowhere
  or is ambiguous, a Supervisor entry naming a library vCenter does not hold.
</content>
</invoke>
