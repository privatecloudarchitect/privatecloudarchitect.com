# Can every namespace see the VM images it needs, and will your pins and locks hold?

`libraries.py` answers that for a VCF Automation organization, namespace by namespace, by reading the layer each answer
lives on. It is read-only.

Proven on VCF Automation 9.1.1.0100 and vCenter 9.1.1 on 2026-10-28 and 2026-10-29, on an estate where the provider
content library had just been rebuilt: every namespace saw the rebuilt library's images through the Supervisor, every
namespace's own vCenter setting was empty, a blueprint pinned by id before the rebuild resolved nowhere, and once the
demo blueprints pinned by display name, every pin resolved and every image lock held.

## Run it

```
export VCFA_HOST=<automation-fqdn> VCFA_ORG=<org>
( umask 077; mkdir -p ~/.vcf && cat > ~/.vcf/vcfa-password )   # type the password, then Ctrl-D
export VCFA_USER=<account> VCFA_PASSWORD_FILE=~/.vcf/vcfa-password   # mode 0600; or VCFA_REFRESH_TOKEN_FILE
export TLS_VERIFY=false                                              # only on a self-signed lab CA
python3 libraries.py                         # every namespace the account can list
python3 libraries.py --pins ./blueprints     # and every image pin under ./blueprints
python3 libraries.py --lock ./blueprints     # and every image-lock.json under ./blueprints
python3 libraries.py --namespace <name>      # one namespace
```

With `--vcenter` it also reads the provider side (the Supervisor's library list and each namespace's own library
setting) from the vCenter that runs the Supervisor; set `VC_HOST`, `VC_USER` and `VC_PASSWORD_FILE` (mode 0600). A
secret file open to group or other is refused before it is read.

`expected-output.md` shows both runs: an estate where every pin resolves and every lock holds, and a pin left over from
a library rebuild.

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
resolves when exactly one image carries that name. An image id is computed from its library item, so rebuilding a
library gives every image a new id, and an id pinned before the rebuild resolves nowhere; updating an item's content
in place keeps its id while the bits change. So neither handle freezes the bits, and the practice is to pin by display
name and hold the pin with a lock.

A lock is an `image-lock.json` beside the blueprint, written from one qualification deploy: the pin, the image's
fingerprint, the guest's own OS reading and the date. `--lock` checks that the pin resolves to one image and that the
image's fingerprint equals the lock's, and prints HELD, RE-QUALIFY, AMBIGUOUS, UNRESOLVED or NOT CHECKED. The
fingerprint is SHA-256 over the library item's sorted `name:bytes` file pairs; sizes are read as Kubernetes quantities
(`3952256k` is 3,952,256,000 bytes). A lock this script reads:

```
{
  "lockVersion": 1,
  "images": [
    {
      "pin": "<display name>",
      "name": "versioned",
      "fingerprint": {"kind": "manifest-sha256", "value": "sha256:<64 hex>", "files": 3},
      "guest": {"prettyName": "<the guest's own OS name>", "kernel": "<kernel>"},
      "qualified": {"on": "<YYYY-MM-DD>", "by": "<who, or the record>", "observedId": "vmi-<id seen>"}
    }
  ]
}
```

## Scope, stated plainly

- It reads one organization, as that organization's account. A namespace whose endpoint does not answer is reported as
  not read (exit 3), which is not a finding.
- `--pins` reads `vmi-...` ids anywhere in a YAML or JSON file outside a comment, display names from an `imageName` key,
  and the default of a blueprint input whose key names an image (`vm_image`, `db_vm_image`). It skips `image-lock.json`,
  whose observed id is a record, not a pin.
- A display name two images carry was refused at admission on VCF 9.1.1, in the one case tried (a namespace image beside
  a cluster image); the script reports such a pin as ambiguous rather than guessing.
- The fingerprint covers file names and sizes, because the library copies VCF Automation makes carry no checksum: it
  catches a changed name or size, not a same-size change. A lock re-reads neither the image's bits nor the guest.
- It checks the namespaces when it runs; a request made in between, through the catalog UI for instance, is not
  guarded by it. Run it on a schedule to find a change after the fact.

## Reading the record

`libraries.json` (or `OUT_DIR/libraries.json`) carries placeholders for every organization, project, namespace, library,
image, file and host name and every image id, the same placeholder each time a name appears; the script refuses to
write a record in which one survived outside a placeholder.

- `orgLibraries`: what VCF Automation lists for the organization: `kind` (`PROVIDER` or `TENANT`), `autoAttach`
  (always `true` for provider and project libraries), `projectScoped`, `status`, `subscribed`, `regions`.
- `namespaces[]`: per namespace, `images` (the general-purpose images it can name, each with its `scope`, `library`
  and the attachment it came `via`), `kubernetesImages` (the count of release images, kept apart), `attachments` (each
  library the namespace holds, its `via`, `type`, `naming` strategy, `ready`, and how many images it delivered), `pins`
  with `--pins`, and `locks` with `--lock` (each lock's file, pin, verdict and qualified date; fingerprints are not
  written).
- `vcenter` with `--vcenter`: the Supervisor's library list (each entry's library, whether it serves Kubernetes
  releases, its naming strategy, and whether vCenter still holds it) and, per namespace, how many entries its own
  setting holds and how many name no library.
- `findings`: a namespace with no general-purpose image, an attachment that is not ready, a pin that resolves nowhere
  or is ambiguous, a lock to re-qualify or that does not resolve, a Supervisor entry naming a library vCenter does not
  hold.
