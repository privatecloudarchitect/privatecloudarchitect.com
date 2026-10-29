# What libraries.py prints

Read on a VCF 9.1.1 estate (VCF Automation 9.1.1.0100, vCenter 9.1.1) on 2026-10-28, every estate name replaced by a
placeholder, as the record carries them.

## Every namespace, with the provider side from vCenter

`python3 libraries.py --vcenter --pins <the demo blueprints>`, after the provider library was attached to the Supervisor and the blueprints re-pinned. Each namespace names the
same three general-purpose images, all delivered by the one library attached Supervisor-wide; the second library on the
Supervisor's list carries only Kubernetes release images; and every namespace's own vCenter setting is empty. That line
is why the namespace setting is the wrong place to look: it reads empty while every image resolves. Every pin resolves by
id at cluster scope. Exit 0.

```
libraries.py, read 2026-10-28T23:28:04Z
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
pin {{image-id-1}}             {{file-10}}:18  resolves by id at cluster scope, in 4 of 4 namespace(s)
pin {{image-id-1}}             {{file-1}}:72  resolves by id at cluster scope, in 4 of 4 namespace(s)
pin {{image-id-1}}             {{file-2}}:46  resolves by id at cluster scope, in 4 of 4 namespace(s)
pin {{image-id-1}}             {{file-2}}:105  resolves by id at cluster scope, in 4 of 4 namespace(s)
pin {{image-id-1}}             {{file-2}}:107  resolves by id at cluster scope, in 4 of 4 namespace(s)
pin {{image-id-1}}             {{file-3}}:55  resolves by id at cluster scope, in 4 of 4 namespace(s)
pin {{image-id-1}}             {{file-4}}:35  resolves by id at cluster scope, in 4 of 4 namespace(s)
pin {{image-id-1}}             {{file-4}}:96  resolves by id at cluster scope, in 4 of 4 namespace(s)
pin {{image-id-1}}             {{file-4}}:99  resolves by id at cluster scope, in 4 of 4 namespace(s)
pin {{image-id-1}}             {{file-5}}:23  resolves by id at cluster scope, in 4 of 4 namespace(s)
pin {{image-id-1}}             {{file-6}}:59  resolves by id at cluster scope, in 4 of 4 namespace(s)
pin {{image-id-1}}             {{file-7}}:56  resolves by id at cluster scope, in 4 of 4 namespace(s)
pin {{image-id-1}}             {{file-7}}:119  resolves by id at cluster scope, in 4 of 4 namespace(s)
pin {{image-id-1}}             {{file-7}}:123  resolves by id at cluster scope, in 4 of 4 namespace(s)
pin {{image-id-1}}             {{file-8}}:23  resolves by id at cluster scope, in 4 of 4 namespace(s)
pin {{image-id-1}}             {{file-9}}:23  resolves by id at cluster scope, in 4 of 4 namespace(s)
vCenter, the Supervisor's library list: {{library-2}} (Kubernetes releases); {{library-1}} (VM images, PREFER_ITEM_SOURCE_ID)
vCenter, each namespace's own setting: {{namespace-1}} 0, {{namespace-2}} 0, {{namespace-3}} 0, {{namespace-4}} 0
findings: none
record: libraries.json
```

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
