# Is every host still what its cluster declares, and in what order do you leave the legacy?

Companion to the chapter
([privatecloudarchitect.com/handbook/host-lifecycle](https://privatecloudarchitect.com/handbook/host-lifecycle)):
one read-only script that reads both declarations a host in a vSphere Lifecycle Manager cluster is held to, the
cluster's image and its vSphere Configuration Profiles document, with the compliance vCenter stored for each, and a
pure function that orders the move off baselines, host profiles, Auto Deploy and UMDS from your own answers. Stdlib
Python only; no credential is printed or written.

| File | What it is |
|---|---|
| `hostlife.py` | Reads, for every cluster of every vCenter you name: whether it is managed with an image, the image's parts (base image, vendor add-on, firmware and drivers add-on, components, solutions) and its stored image compliance; whether Configuration Profiles is enabled, when (from its audit records), the document's sections and counts (never a value from it), and its stored compliance with, for every drifted item, its path and its non-identifying fields; and around them the depots and the newest base image they hold, any hardware support manager, any host profile, and the Auto Deploy and Image Builder services. Exits 1 when a cluster is still on baselines or a stored compliance is not compliant. Writes `out/hostlife.record.json`, scrubbed, and refuses to write a record in which a vCenter, cluster, host or depot server name, or an address, survived. `hostlife.py plan` prints the ordered moves for your answers. |
| `records/hostlife.record.json` | That record from the reference estate, 2026-10-25, three vCenters on VCF 9.1.1. The chapter's plates render it. |
| `expected-output.md` | What the script printed for that record, and what `plan` printed for the chapter's example answers. |

## Run it

```bash
export VC_HOST=<vcenter-fqdn>                 # several vCenters: separate them with commas
export VC_USER=<sso-user>  VC_PASSWORD_FILE=~/.secrets/vc   # mode 0600
export TLS_VERIFY=false                       # only on a self-signed lab CA

python3 hostlife.py; echo "exit $?"
python3 hostlife.py --json                    # the scrubbed record on stdout instead of the report
FINGERPRINT_KEY_FILE=~/.secrets/fp python3 hostlife.py --host-builds   # also what each host runs (key: mode 0600)
python3 hostlife.py --from-record records/hostlife.record.json   # the report again from a record; no call is made
```

`VC_SESSION_FILE` (a session id, mode 0600) works in place of the user and password file for a single vCenter. Every
credential file is refused, unread, if it is open to group or other. The record goes to `out/` (or `OUT_DIR`), so a
first run never meets the shipped one.

`--host-builds` (or `HOST_BUILDS=1`) adds what each host **runs**: its version and build, read live from the host's
own summary through the vSphere API's JSON form (SOAP where a build has none), never from a stored compliance result,
with its connection state and whether it is in maintenance mode. A host that is not connected reports the last build
vCenter knew, and the report marks it as last known. Each host is named by a keyed fingerprint of its hardware UUID,
made with a secret of your own in `FINGERPRINT_KEY_FILE` (mode 0600), so a dated series of records joins one host
across runs while no record names it. A UUID that is missing or all zeros, or that two hosts report, never joins; the
record counts them as `unidentified` and `collisions`, and a key two vCenters share never joins either. Without a key
file the builds are read and nothing joins. The flag also keeps the depot's base images, each with its release date
exactly as the read returned it, and the time of that read, from the read the script already makes; a read that fails
leaves `versions` null with its reason, never an empty list, so a failed read is never taken for an empty depot. An
image's release date is when the vendor released it, not when the depot took it in: no field records that, so a series
of records bounds it between two reads. And each image-managed cluster gains its last remediation as vSphere Lifecycle
Manager stores it: its status, start and end times (the end time the remediation's own, which runs past its last
host's), its failed, skipped and successful hosts as counts, the commit it applied, and its notifications counted by
type, never their text. The platform keeps only the last remediation, so a series of records sees a sample, and no
field says who started a remediation or whether a person intervened. An "are unavailable" answer is recorded as
`unavailable`, any other failure as `failed` with its reason. The flag changes no exit code: a read that fails is recorded with
`"read": false` and its reason, never as a pass. The build is the one the host reports in its summary; what a host
reports there after a Live Patch, applied without a reboot, has not been read on an estate yet, so the read makes no
claim for a host live-patched since its last reboot.

**Exit codes.** 0 every cluster read is managed with an image and the stored compliance with each declaration it has
is compliant; 1 a cluster is still on baselines, or a stored image or configuration compliance is not compliant (the
alert to schedule); 2 a setting is missing, an argument is wrong, or a secret file is open to group or other; 3 a
sign-in or a read failed; 4 the record refused to write, because an estate value survived the scrub.

## Plan the move

```bash
python3 hostlife.py plan --baselines --supervisor --upgrade --host-profiles
python3 hostlife.py plan --help               # every question, and --not-vcf, --disconnected, --hsm, --auto-deploy
python3 hostlife.py plan --baselines --sources   # each move with the documentation pages it rests on
```

`plan(answers)` is a pure function: it reads nothing but the answers, and returns the moves in order, each with how its
place is held (enforced where the platform refuses the next step without it, documented order where a page states the
order, advised where this companion recommends it, open where the pages read disagree) and whether it can be undone.
Each move names the chapter's plate that teaches it and, with `--sources`, the documentation pages it rests on, by
title and URL. The chapter's planner is a JavaScript twin of this function, held equal
to it in a browser on every combination of answers when the page is built.

## Both declarations

A cluster's image says what its hosts run; its configuration profile says how they are set; and vCenter stores a
compliance result for each. The script reads the stored results and never starts a check, so every compliance line
carries the time vCenter last checked. Two things it reports are easy to misread:

- **Compliant is not current.** Compliance is measured against the image the cluster declares. The depot can hold a
  newer base image than any cluster declares, and every cluster still reads compliant; the script prints a NOTE when
  it does.
- **Drift is not always somebody's mistake.** A setting declared in a configuration profile can be rewritten by
  another system on purpose. The script prints each drifted item's path and its non-identifying fields (a protocol and
  a port, say), so you can tell which system wrote it before anybody remediates; remediation writes the declared
  value back.

## Scope, stated plainly

- Read-only. Every REST call is a `GET`; the only other requests sign in and out: a vCenter session opened with
  `VC_USER` and closed when the script is done. Host profiles are read through the vSphere API's JSON form with the
  same session; where a build answers that form with a refusal, the script opens and closes a session of its own
  there, and where the build has no JSON form it falls back to SOAP, whose property read is a read carried in a
  `POST`, as every SOAP call is.
- No compliance check, precheck, stage, remediation, export, extract or service start is sent. The Auto Deploy rules
  are not read: the vCenter REST API's own catalog of services, read on the reference estate, lists none for them.
- The configuration document is reduced to its section names and counts in memory. A drifted item keeps only the
  fields whose names cannot identify anything; every other field is listed by name under `withheld`, never by value.
- Every vCenter, cluster, host and depot server name in the record is a placeholder, and the script refuses to write a
  record in which one survived. With `--host-builds`, a host appears only as its keyed fingerprint; its UUID never
  reaches the record.

## Reading the record

`summary` carries the counts the exit code and the chapter use. `vcenters` holds one entry per vCenter: its version,
`services` (Auto Deploy, Image Builder, vSphere Lifecycle Manager, Update Manager, each with its state and startup),
`hardware_support_managers`, `host_profiles` (`read`, `via`, `count`), `depot` (`umds`, the `online` depots by kind
and whether each is on, `base_images` and `newest_base_image`) and `clusters`. Inside a cluster: `image_managed`,
`image` (`base_image`, `vendor_add_on`, `firmware_add_on`, `components`, `solutions`, `alternative_images`),
`image_compliance` (`status`, `checked`), and `configuration`: `enabled`, then where it is on, `audit`,
`enabled_on`, `last_change`, `document` (the section names and counts) and `compliance` (`status`, `checked`, and per
host its `status` and its `drift`, each item's `change`, `path`, `fields` and `withheld`). `findings` lists what the
report prints at its foot; with `--host-builds`, each vCenter also carries `host_builds` (`read`, `via`, `read_at`,
`keyed`, `collisions`, `unidentified`, `unread`, and `hosts`, each with its `key`, `joinable`, `cluster`, `version`,
`build`, `connection_state` and `in_maintenance`), and its `depot` gains `versions` (each `version` with its
`release_date`), `read_at`, and `versions_why` when the read failed; each image-managed cluster gains
`last_remediation` (`state`, `read_at`, and when stored `status`, `start_time`, `end_time`, `end_time_from`, `failed`,
`skipped`, `successful`, `commit` and `notifications`); `exit` is the exit code; `calls` lists every request by method, path template and status.
