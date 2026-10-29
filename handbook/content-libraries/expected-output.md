# What libraries.py prints

Read on a VCF 9.1.1 estate (VCF Automation 9.1.1.0100, vCenter 9.1.1) on 2026-10-28 and 2026-10-29, every estate name replaced by a
placeholder, as the record carries them.

## Every namespace, every pin and every lock, with the provider side from vCenter

`python3 libraries.py --vcenter --pins <the demo blueprints> --lock <the demo blueprints>`, read on 2026-10-29, after the
demo blueprints moved to display-name pins held by image locks. Each namespace names the same three general-purpose
images, all delivered by the one library attached Supervisor-wide; the second library on the Supervisor's list carries
only Kubernetes release images; and every namespace's own vCenter setting is empty. That line is why the namespace
setting is the wrong place to look: it reads empty while every image resolves. Every pin resolves by display name at
cluster scope, and every lock holds: the name resolves to one image, and that image's fingerprint equals the one
recorded when the blueprint was qualified. Exit 0. The same read on 2026-10-28, with the pins then still ids, is kept
as `records/libraries-2026-10-28.json`.

```
libraries.py, read 2026-10-29T14:42:27Z
VCF Automation: 1 library this organization can use
  {{library-1}}          provider     auto-attach true  READY      subscribed
{{namespace-1}}: 3 general-purpose image(s) (3 via supervisor), 99 Kubernetes release image(s)
  attached supervisor     {{library-2}}          0 image(s), 99 Kubernetes release image(s)
  attached supervisor     {{library-1}}          3 image(s)
{{namespace-2}}: 3 general-purpose image(s) (3 via supervisor), 99 Kubernetes release image(s)
  attached supervisor     {{library-2}}          0 image(s), 99 Kubernetes release image(s)
  attached supervisor     {{library-1}}          3 image(s)
{{namespace-3}}: 3 general-purpose image(s) (3 via supervisor), 99 Kubernetes release image(s)
  attached supervisor     {{library-2}}          0 image(s), 99 Kubernetes release image(s)
  attached supervisor     {{library-1}}          3 image(s)
{{namespace-4}}: 3 general-purpose image(s) (3 via supervisor), 99 Kubernetes release image(s)
  attached supervisor     {{library-2}}          0 image(s), 99 Kubernetes release image(s)
  attached supervisor     {{library-1}}          3 image(s)
pin {{image-1}}                {{file-10}}:18  resolves by display name at cluster scope, in 4 of 4 namespace(s)
pin {{image-1}}                {{file-4}}:109  resolves by display name at cluster scope, in 4 of 4 namespace(s)
pin {{image-1}}                {{file-5}}:100  resolves by display name at cluster scope, in 4 of 4 namespace(s)
pin {{image-1}}                {{file-6}}:23  resolves by display name at cluster scope, in 4 of 4 namespace(s)
pin {{image-1}}                {{file-7}}:123  resolves by display name at cluster scope, in 4 of 4 namespace(s)
pin {{image-1}}                {{file-8}}:23  resolves by display name at cluster scope, in 4 of 4 namespace(s)
pin {{image-1}}                {{file-9}}:23  resolves by display name at cluster scope, in 4 of 4 namespace(s)
lock {{image-1}}               {{file-1}}  HELD: held in 4 of 4 namespace(s) (qualified 2026-10-29)
lock {{image-1}}               {{file-2}}  HELD: held in 4 of 4 namespace(s) (qualified 2026-10-29)
lock {{image-1}}               {{file-3}}  HELD: held in 4 of 4 namespace(s) (qualified 2026-10-29)
vCenter, the Supervisor's library list: {{library-2}} (Kubernetes releases); {{library-1}} (VM images, PREFER_ITEM_SOURCE_ID)
vCenter, each namespace's own setting: {{namespace-1}} 0, {{namespace-2}} 0, {{namespace-3}} 0, {{namespace-4}} 0
findings: none
record: libraries.json
```

A lock reads RE-QUALIFY when the fingerprint the namespace serves differs from the lock's: since the copies VCF
Automation makes carry no checksum, the fingerprint covers the item's file names and sizes, so it catches a changed
name or size, not a same-size change. NOT CHECKED means the fingerprint could not be read, which is not a pass.

## A pin left over from before a library rebuild

`python3 libraries.py --pins <a folder holding a blueprint saved before the rebuild> --namespace <one namespace>`. The
blueprint pins an image id from the library as it was; the rebuilt library serves the same image under a new id, so the
pin resolves in no namespace. Exit 1.

```
libraries.py, read 2026-10-28T23:07:49Z
VCF Automation: 1 library this organization can use
  {{library-1}}          provider     auto-attach true  READY      subscribed
{{namespace-1}}: 3 general-purpose image(s) (3 via supervisor), 99 Kubernetes release image(s)
  attached supervisor     {{library-2}}          0 image(s), 99 Kubernetes release image(s)
  attached supervisor     {{library-1}}          3 image(s)
pin {{image-id-4}}             {{file-1}}:96  RESOLVES NOWHERE, in 0 of 1 namespace(s)
pin {{image-id-4}}             {{file-1}}:99  RESOLVES NOWHERE, in 0 of 1 namespace(s)
findings: {{namespace-1}}: pin {{image-id-4}} ({{file-1}}:96) resolves nowhere; {{namespace-1}}: pin {{image-id-4}} ({{file-1}}:99) resolves nowhere
record: libraries.json
```
