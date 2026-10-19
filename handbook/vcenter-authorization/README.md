# vCenter authorization under VCF single sign-on, read the way a broker session reads it

Companion to the chapter
([privatecloudarchitect.com/handbook/vcenter-authorization](https://privatecloudarchitect.com/handbook/vcenter-authorization)):
one script that reads every permission on your vCenters and classifies it by how it behaves for someone
signed in through the VCF identity broker, and three opt-in probes that settle the questions a read cannot.
Standard library Python 3.10 or later, plus pyVmomi for the session read (needed once `REALM_DOMAIN` is set), `--remove`
and the probes.

| File | What it is |
|---|---|
| `authz.py` | The census (read-only), the realm-spelled grants named (`--where-realm`) and removed (`--remove`, plan first), every grant saved to a file of your own and two saves compared (`--save-permissions`, `--compare-permissions`), and the probes (opt-in, and they write to vCenter: a throwaway folder, tag category and tag they create and remove, grants for the length of one case, a throwaway tag on a VM you own for `--supervisor-vm`, and six `authz-probe-*` roles kept by design, each recorded the moment it is made in a ledger of your own, `authz-probe-roles.state.json`). Writes `authz.json` with every estate name replaced, and refuses to write a record in which one survived. |
| `authz.json` | That record from the reference estate, read 2026-10-19 on three vCenter 9.1.1 instances with all three probes. The chapter's plates render it. |
| `replay/authz/` | A recorded answer set made from the reference estate's record of 2026-10-06 (the `authz.json` this folder shipped before the 9.1.1 refresh), every name a placeholder, for `--replay`: the census runs on it with no estate and sends nothing. |

## Try it without an estate

`--replay DIR` answers every request from a recorded set instead of your vCenters, so you can run the census before
you have an estate to read, or see what it prints for a shape your estate has not shown you. The set beside this
README, `replay/authz/`, is the reference estate's record of 2026-10-06 made into the vSphere Automation API's answers
for three vCenters, with a placeholder for every name:

```bash
python3 authz.py --replay replay/authz                 # the census of three vCenters; writes authz.replay.json
python3 authz.py --replay replay/authz --where-realm   # the same, and each realm-spelled grant by id (none here)
```

Nothing is sent and no credential is read: the set answers each request by its method, path, query and host, and
names the placeholder hosts and domains it was recorded with. A request the set holds no answer for is a read that
failed, so the run exits 3 and names the call, never a pass. The session list is read through pyVmomi, which a set does
not answer, so a replayed run reads none; with the set's `REALM_DOMAIN` it exits 3, as a run without pyVmomi does,
because whether anyone signs in with the realm's domain is not known. A writing mode runs its plan alone: `--remove`
with `--execute` sends nothing and stops where its plan reads who is signed in (exit 3), and the probes and
`--remove-probe-roles`, which write as they go and have no plan, are refused (exit 5), as is `--adopt-probe-role`,
which reads the role list through pyVmomi. `--save-permissions` writes its
file from the set's answers. The record goes to `authz.replay.json`, in `OUT_DIR` or the directory you run in, so a
replayed run never overwrites `authz.json`. The record and a list `--save-permissions` writes under `--replay` carry
`"replay": true` at the top, so neither passes for a read of an estate: `--compare-permissions` refuses such a file
(exit 3), and a live run's record and list carry no such key.

### A replayed run

The first command, run in this folder: the reference estate's three vCenters, read from recorded answers with nothing
sent. The first line is written to standard error. The counts by class and the four custom roles whose copies differ
are that record's; it counted local grants as one class, so the set splits them into the Administrators group's
one global grant and VCF-managed accounts. It exits 3 because no session list was read.

```text
$ python3 authz.py --replay replay/authz
replay: 8 recorded answers from replay/authz; nothing is sent and no credential is read
authz.py: vCenter authorization under VCF single sign-on, read the way a broker session reads it

  {{vcenter-1}}: 70 permissions (64 global); {'directory, global': 1, 'directory, object': 1, 'local, Administrators, global': 1, 'local, VCF-managed, global': 46, 'local, VCF-managed, object': 5, 'reserved group, global': 16}
     sessions not read: a replayed run reads no session list (it is read through pyVmomi)
     NOT PLACED: the session list was not read whole, so whether people sign in with REALM_DOMAIN's domain is not known here, and a grant spelled in it is no finding until it is (exit 3)
  {{vcenter-2}}: 144 permissions (102 global); {'directory, global': 1, 'directory, object': 1, 'local, Administrators, global': 1, 'local, VCF-managed, global': 80, 'local, VCF-managed, object': 41, 'reserved group, global': 20}
     sessions not read: a replayed run reads no session list (it is read through pyVmomi)
     NOT PLACED: the session list was not read whole, so whether people sign in with REALM_DOMAIN's domain is not known here, and a grant spelled in it is no finding until it is (exit 3)
  {{vcenter-3}}: 249 permissions (75 global); {'another provider, object': 8, 'directory, global': 2, 'directory, object': 3, 'local, Administrators, global': 1, 'local, VCF-managed, global': 54, 'local, VCF-managed, object': 140, 'reserved group, global': 18, 'reserved group, object': 23}
     read as another provider's (printed here only, never recorded): DOMAIN-2.EXAMPLE.TEST 8
     sessions not read: a replayed run reads no session list (it is read through pyVmomi)
     NOT PLACED: the session list was not read whole, so whether people sign in with REALM_DOMAIN's domain is not known here, and a grant spelled in it is no finding until it is (exit 3)

  custom roles whose copies differ between vCenters: 4

wrote authz.replay.json: counts, classes and outcomes, with every estate name replaced
exit 3
```

## Run it

```bash
export VC_HOSTS=<vcenter-fqdn>[,<another>]
export VC_USER=<an administrator, user@domain>
export VC_PASSWORD_FILE=/path/to/password          # mode 0600
export REALM_DOMAIN=<the realm's name>            # once the estate has a realm (before one, run with --no-realm); never a directory domain, nor CUSTOMER
export DIRECTORY_DOMAINS=<directory domain>[,<another>]   # required
export LOCAL_DOMAIN=<your SSO domain>             # only if it is not vsphere.local; otherwise every local grant reads as another provider's
export BROKER_TENANT=<the broker tenant>          # only if it is not CUSTOMER: the domain an API client's session carries
export OTHER_DOMAINS=<another provider's domain>[,<another>]   # domains you know are another provider's; optional for the census, stated (empty allowed) for --remove
export TLS_VERIFY=false                            # only on a self-signed lab CA

python3 authz.py                                   # the census, read-only
python3 authz.py --where-realm                     # the census, and each realm-spelled grant by id, on your terminal only
```

The census refuses to start without `DIRECTORY_DOMAINS`: unset, every directory grant reads as another provider's, so
the census would count no directory grant on an estate full of them. On a vCenter where `DIRECTORY_DOMAINS` (and
`REALM_DOMAIN`, when set) name no grant while another provider's grants are there, it prints `NOT PLACED` under that
vCenter, records `domainsNamedNothing` and exits 3; check the spelling against the vCenter's own before reading the
census. Every run also prints, on the terminal only and never in the record, the domains it read as another provider's
with their grant counts, which is where a misspelled domain shows.

With `REALM_DOMAIN` set, the census also reads who is signed in on each vCenter (pyVmomi), because a broker session
carries the directory's name: a live session spelled in `REALM_DOMAIN` shows a domain people sign in with, and a grant
spelled in it may apply to them. So a session list not read whole is a read that failed (exit 3, `NOT PLACED`), and the
realm-spelled grants are no finding until it is read: a list refused, one that does not hold the session that read it,
one that holds only the reader's own sessions (an identity that may not read the others lists only its own: run the
census as an administrator of the vCenter), or none read because pyVmomi is missing. Before a realm (`--no-realm`) the
session read is optional.

A misspelled `REALM_DOMAIN` is caught the same way. It moves every realm-spelled grant into another provider's class,
where nothing flags it, while the directory domains still name their own grants. So with `REALM_DOMAIN` set, a vCenter
on which the realm names no grant while grants of an unplaced domain are there (one in none of `DIRECTORY_DOMAINS`,
`LOCAL_DOMAIN`, `REALM_DOMAIN` and `OTHER_DOMAINS`) prints `NOT PLACED` with those domains, on the terminal only,
records `realmNamedNothing`, and exits 3. Check `REALM_DOMAIN` against the realm's name, and name in `OTHER_DOMAINS`
each domain you know is another identity provider's. On the reference estate, with the realm spelled right and no
realm-spelled grant left, the workload vCenter that runs a Supervisor needed one such domain named before the run
exited 0 (X-207).

### The realm is not the directory domain

`REALM_DOMAIN` is the realm's name as vCenter spells it in a grant (VCF Operations, fleet IAM realms). A directory
domain is the one your directory spells its users and groups in, `DOMAIN\user`, which a broker session carries. The
census tests the realm's name first, so a `REALM_DOMAIN` typed as a directory domain, or as a domain in `OTHER_DOMAINS`,
would class every working grant in that domain realm-spelled: exit 1 would say to remove them, and `--remove` would
accept their ids. So a `REALM_DOMAIN` equal to any `DIRECTORY_DOMAINS` or `OTHER_DOMAINS` entry, compared without regard
to case, surrounding spaces or a trailing dot (`corp.example.` and `CORP.EXAMPLE` are one domain), is refused before
anything is read (exit 5), and so is one equal to `LOCAL_DOMAIN`, where
every grant sorts as local first and no realm-spelled grant could be found, or to the broker tenant (below). `--remove`
and `--where-realm` are refused the same way. Expected output, with the names replaced:

```text
REALM_DOMAIN (<domain>) and DIRECTORY_DOMAINS (<domain>) name the same domain. REALM_DOMAIN is the realm's name as vCenter spells it in a grant (VCF Operations, fleet IAM realms); a directory domain is the one your directory spells its users and groups in, DOMAIN\user, which a broker session carries. Read as one, every working grant in that domain would be classed realm-spelled and named for removal. Set REALM_DOMAIN to the realm's name (exit 5)
```

### An API client's grant is kept

A grant whose domain is the broker tenant, `BROKER_TENANT` (`CUSTOMER` when unset, as on the reference estate), is
classed `API client (broker tenant)`, whatever the name after it. An API client signed in through the SAML exchange
carries the broker tenant and its clientId, and the spelling cannot tell a clientId from a person's name. Such a grant
is an integration's own access: review it with the integration's owner, never remove it as clutter. The census counts
it by scope, prints the count and that advice on your terminal, and places its domain, so the broker tenant is never
read as another provider's and never itself stops a run at `NOT PLACED`. `--remove` refuses its id, as it refuses every grant
that is not realm-spelled, and names the class. On your terminal, as the script's tests show it:

```text
     API client (broker tenant): 2 grant(s) in CUSTOMER, the broker tenant: an integration's own access: review it with the integration's owner, never remove it as clutter
```

Two guards keep the class apart, each a usage error found before anything is read (exit 5). A `REALM_DOMAIN` equal to
the broker tenant is refused, because the census tests the realm first and would class every API client's grant
realm-spelled and offer it for removal. A `BROKER_TENANT` equal to a `DIRECTORY_DOMAINS` or `LOCAL_DOMAIN` entry is
refused, because the census tests those first and every API client's grant would read as a person's or a local one.
`OTHER_DOMAINS` may name the broker tenant: it places a domain and classes nothing. A `BROKER_TENANT` that is not your
estate's leaves the API clients' grants in another provider's class, where their domain shows on the terminal.

What this changes for a run: a vCenter where the broker tenant was the only domain none of the domains given placed
could stop at `NOT PLACED` (exit 3) until the tenant was named in `OTHER_DOMAINS`; it is now placed. A `REALM_DOMAIN`
equal to the broker tenant, and a `BROKER_TENANT` equal to a directory or the local domain, ran before and are now
refused (exit 5). No exit code changed its meaning.

### Every page of the lists

The permission and role lists are paged: an answer that carries a `marker` has more after it, and the census asks for
the next page with that marker until an answer carries none. vCenter states no total for them, so the read holds them to
what it can check. A page refused, an item without its id, an id answered on an earlier page (the list moved while it was
read), a page that says more follow and adds nothing, or a marker answered twice, is a list not read (exit 3, `NOT READ`
under that vCenter), and so is a permission list with no permission in it, because `VC_USER`, an administrator, holds
one.

### Before the realm exists

Run the census before the broker takes the realm, while the boundary is being decided, so every grant is inventoried
first. Declare that with `--no-realm`: there is no realm to spell a grant with, so the census reports the realm-spelled
class as not applicable (`realmSpelling` in the record) and flags nothing for it. Set `DIRECTORY_DOMAINS` to the
directory domains the vCenter's own identity sources spell. Once a realm exists, set `REALM_DOMAIN`. A run with neither
is refused (exit 5): left to infer "no realm" from a variable not set, a run on an estate with a realm read its
realm-spelled grant as another provider's and exited 0 (X-197).

### Name the realm-spelled grants, then remove them

```bash
python3 authz.py --where-realm                     # each realm-spelled grant: permission id, principal, object, role, scope
export VC_HOSTS=<the one vCenter that holds them>
export OTHER_DOMAINS=<every other provider's domain, or nothing>   # stated: --remove trusts DIRECTORY_DOMAINS to name every directory
python3 authz.py --remove <id>[,<id>...]           # the plan: each grant and the DELETE it would send; nothing is sent
python3 authz.py --remove <id>[,<id>...] --execute # one DELETE per id, then the list read back
```

`--where-realm` prints each id on your terminal and never writes it to the record. `--remove` acts on one vCenter at a
time and only on realm-spelled grants: it refuses, before anything is sent, an id that vCenter does not hold and an id
that is not a realm-spelled grant (remove any other grant where it was made). With `--execute` it holds when every named
grant is gone and no other grant moved on the read-back; a second run with the same ids is refused, because the ids are
gone, so it is safe to repeat. It writes no record.

`--remove` trusts the domains you declare. A directory you left out of `DIRECTORY_DOMAINS` and typed as `REALM_DOMAIN`
reads as the realm, so its working grants would read realm-spelled. Two guards stand before anything is sent: a
`REALM_DOMAIN` equal to a domain you named is refused (exit 5), and `--remove` reads who is signed in on that vCenter
first. A broker session carries the directory's name, so a live session spelled in `REALM_DOMAIN` shows that domain is
one people sign in with, and a grant in it may apply to them: the removal is refused, plan and `--execute` alike, with
nothing sent (exit 3), as it is when the session list cannot be read whole: refused, without the session that read it,
or holding only the reader's own sessions, the list an identity that may not read the others gets. A directory nobody
from is signed in to at
that moment passes both, so `--remove` runs only with `OTHER_DOMAINS` stated, empty when there is none, as your
declaration that `DIRECTORY_DOMAINS` names every directory. Expected output, with the names replaced:

```text
authz.py --remove on <vcenter>: 1 realm-spelled grant(s), printed here only; no live session is spelled in REALM_DOMAIN
  permission <permission-id>: <realm>\<account> (USER) on Folder <folder-moid>, role NoAccess, object, not propagating
    DELETE /api/vcenter/authorization/permissions/<permission-id>
  DELETE <permission-id>: HTTP 204
read back: 1 of 1 named grant(s) gone; other grants moved: 0
held: every named grant is gone and no other grant moved
exit 0
```

## Save every grant, and compare two saves

The census counts grants by class and names none. To see which grants a change moved, save the whole list before the
change and again after, on your own disk, and compare the two grant by grant:

```bash
export VC_HOSTS=<every vCenter the change touches>
python3 authz.py --save-permissions ~/.vcf/grants-before.json      # a new file, mode 0600, outside the clone
# ... the change ...
python3 authz.py --save-permissions ~/.vcf/grants-after.json
python3 authz.py --compare-permissions ~/.vcf/grants-before.json ~/.vcf/grants-after.json
```

`--save-permissions FILE` reads each vCenter's permission list whole, with the census's pager and its rules, and the
role catalog for the roles' names, and writes every grant: the vCenter, the entity (its type and id), the principal as
vCenter spells it in the grant (`DOMAIN\name`, user or group), the role's id and name, whether it propagates, and the
permission's id. It needs `VC_HOSTS`, `VC_USER` and `VC_PASSWORD_FILE`, and no domain variable. The file names every
principal on your estate, so it is never scrubbed and never published: it is written only as a new file (an existing one
is refused, so a list saved before a change is never written over), at mode 0600, and never inside the clone (exit 5 for
each; `~/.vcf` is where the other companions keep their files). A list not read whole on any vCenter writes nothing
(exit 3), because a saved list that missed a vCenter's grants would compare as removals. The file carries its own header,
per-vCenter counts, totals and a digest of its grants.

`--compare-permissions BEFORE AFTER` reads no vCenter. It matches grants by the grant key: the vCenter, the entity, the
principal (its name, and whether it is a user or a group) and the role. On the terminal only, it prints each grant added,
removed or changed (a grant that started or stopped propagating); a grant given another role on the same entity shows as
one removed and one added. vCenter's list can carry one grant more than once, under different permission ids and
identical otherwise (one key on one vCenter of the reference estate held two): the save reports such a key, and the compare counts
the grants under such a key, so one of the two gone is one removal. It exits 1 on any difference and 0 on none. It exits 3, comparing nothing, when either file is
unreadable, partial, edited after it was written, written by a replayed run, or not written by `--save-permissions`. A vCenter read in one file only
is named `NOT COMPARED`, and the files are not shown equal: exit 3, unless a vCenter both read differs (1). A host typed
in another case, or with a trailing dot, is the same vCenter. BEFORE saved after AFTER is a usage error (exit 5), since
every addition would read as a removal. Output, with the names replaced and the counts written as `<n>`:

```text
authz.py --compare-permissions: grant by grant, on every vCenter both files read (printed here only)
  BEFORE: saved <time>, 2 vCenter(s), <n> grants
  AFTER: saved <time>, 2 vCenter(s), <n> grants
  <vcenter-1>: 0 added, 0 removed, 0 changed, of <n> and <n> grants
  <vcenter-2>: 1 added, 1 removed, 0 changed, of <n> and <n> grants
    + Folder <folder-moid>: <directory>\<group> (GROUP), role ReadOnly (-2), propagating
    - Folder <folder-moid>: <realm>\<group> (GROUP), role ReadOnly (-2), propagating
2 grant(s) differ
exit 1
```

What a compare cannot see: vCenter keeps a grant by the principal's name, so a name your directory gave to someone new
reads as the same grant. Who holds a name is the directory's to answer.

## Exit codes

The first that applies, so a scheduler reads one state from one number:

| Exit | Means | Do |
|---|---|---|
| 2 | a removal (`--remove --execute`) that did not hold on read-back, a named grant still there or another grant moved; `--remove-probe-roles` refused (one of the ledger's roles granted to someone other than its own reserved group, which removing the role would remove too; nothing is sent), not held (a role it removed still listed after it), or leaving a role kept (one of the six names, which the ledger does not name with that role id on that vCenter); or a probe that left residue (its folder, its tag category, a grant it made on the Supervisor VM, or a grant of one of the ledger's roles, one there before it began included, when it sends nothing) | read the vCenter's permissions before anything else; for a kept role, decide whose it is (below) |
| 1 | the census read realm-spelled grants (only with `REALM_DOMAIN` set, only when every vCenter's session list was read whole, and never while a live session is spelled in it; before a realm there is no such class); with `--compare-permissions`, a grant added, removed or changed on a vCenter both files read | name them with `--where-realm`, remove them with `--remove`; for a compare, read each line and confirm the change was meant |
| 3 | a read failed or a result is undetermined: a vCenter refused the session or a page of a list, a list not read whole (a permission list with no permission, an item without its id, an id answered twice, a page that adds nothing), a session list not read whole (refused, holding only the reader's own sessions, or, with `REALM_DOMAIN` set, not read because pyVmomi is missing or the run is replayed), a request a `--replay` set holds no answer for, the domains named no grant on a vCenter, or `REALM_DOMAIN` named none there beside an unplaced domain, or a live session is spelled in `REALM_DOMAIN` (`NOT PLACED`; with `--remove`, nothing is sent), a probe could not run (a role it needs carrying its name and not the ledger's among them: nothing sent), stopped on an error, or its residue was not read back, a vCenter `--remove-probe-roles` could not finish or read back, the ledger unreadable, not one this script wrote, or not written, a vCenter whose instance UUID was not read, or an error the script did not expect; with `--save-permissions`, a list not read whole (nothing written); with `--compare-permissions`, a file unreadable, partial, written by a replayed run (`"replay": true`) or not written by `--save-permissions` (nothing compared), or a vCenter read in one file only | nothing is known about what was not read: fix the read (or the spelling, `DIRECTORY_DOMAINS` or `OTHER_DOMAINS`) and run again |
| 0 | nothing for a person to act on: every vCenter read and placed (with `REALM_DOMAIN` set, its session list read whole), no realm-spelled grant, every probe clean; with `--remove`, the plan printed or the removal held; with `--save-permissions`, the file written; with `--compare-permissions`, no difference and every vCenter in both files | nothing |
| 5 | a usage error, found before anything is sent (a missing or wrong argument or variable, an abbreviated flag, since flags are taken whole and `--exec` is not `--execute`, a password file it cannot read, a `REALM_DOMAIN` equal to the broker tenant or to a `DIRECTORY_DOMAINS`, `OTHER_DOMAINS` or `LOCAL_DOMAIN` entry, a `BROKER_TENANT` equal to a `DIRECTORY_DOMAINS` or `LOCAL_DOMAIN` entry, `--remove` without `OTHER_DOMAINS` stated, an id `--remove` cannot name as a realm-spelled grant (an API client's among them), pyVmomi missing for a step that needs it, `--remove` among them, a `--supervisor-vm` that names no VM or several, looked up before the census and every probe, a `--save-permissions` FILE that exists, has no directory or lies inside the clone, a `--compare-permissions` BEFORE saved after AFTER, a `--replay` directory that cannot be read or holds no replay set, a probe or `--remove-probe-roles` under `--replay`, since each writes as it goes and has no plan to run alone, an `--adopt-probe-role` under `--replay`, naming a role other than the six or one name twice, with `VC_HOSTS` naming more than one vCenter, or naming a role the vCenter does not list under that name with that id and exactly the name's privileges, a Python older than 3.10) | fix the invocation |

A record refused because an estate value or a password survived the scrub is not written, and it never hides the run's
result: the run's own code stands when it is 1, 2 or 3, and a run that found nothing to act on exits 3, because nothing
shows what it read (the probes and `--remove-probe-roles` may already have written to vCenter).

The probes need a test user that is **not** an administrator, and a directory group it belongs to:

```bash
export TEST_USER=<user@directory-domain> TEST_PASSWORD_FILE=/path/to/password TEST_GROUP=<group>
export PROBE_VCENTER=<a vCenter where TEST_USER holds nothing, for --probe-tags>
export SUPERVISOR_VCENTER=<the vCenter of the Supervisor VM>

python3 authz.py --probe-grants --probe-tags --supervisor-vm <a Supervisor VM you own>
```

`TEST_LOCAL_GROUP`, optional, names a local SSO group you have made to hold `TEST_GROUP` as a member: `--probe-grants`
then adds one case, the role granted to that local group, and measures whether a directory group nested in a local
group carries its grant.

`--supervisor-vm` is looked up on `SUPERVISOR_VCENTER` before the census and every probe: a name that names no VM, or
several, is a usage error (exit 5) with nothing read or sent, and a lookup that cannot be made is exit 3, nothing sent.
Each grant a probe makes comes off in a `finally` the moment its case ends, the global ones by their permission ids
(deleting the folder does not take them). A probe that meets an error it did not expect stops there: its removals still
run, its residue is read back into the record (`stopped`), any probe after it is not run, and the run exits 2 for residue
or 3. A grant it could not take off the Supervisor VM is named on your terminal only, with the command's other residue.

### The probes' roles, and the ledger

The probes keep six roles named `authz-probe-<what it holds>` (below, under Scope, for why). A role carrying one of
those names is this companion's only when its ledger names it. The ledger is `authz-probe-roles.state.json` beside
`authz.py`, whatever `OUT_DIR` says, so every run reads the one ledger (`PROBE_LEDGER` names another file), mode 0600
and yours: git ignores `*.state.json`, and it is never published. It holds each probe role a run created, by vCenter, whole name and role id,
written the moment the role is made, so a run that stops after a create still leaves it named. It names a vCenter by a
digest of its instance UUID, never the UUID or the host's name, so an entry is read only on the vCenter that made it.

- A probe reuses, and reconciles to its declared privileges, a role only when the ledger names it on that vCenter with
  the id the vCenter lists under that name. Where a role the probe needs carries its name and the ledger does not name
  it so (a role of yours under that name, a role deleted and made again under it, or one a run made before the ledger
  existed), the probe sends nothing, names the role and its id, and the run exits 3.
- `--remove-probe-roles` removes only the ledger's roles, by whole name and role id, reads the role list back, and the
  ledger forgets each one read back gone (and each it named that is no longer listed under its id). A role carrying one
  of the six names that the ledger does not name with that id is left alone and printed as `KEPT` (exit 2).
- `--adopt-probe-role NAME=ID` records in the ledger a role a run made before the ledger existed: the record of such a
  run names its roles without an id (the reference estate's run of 2026-10-06 is one), so nothing can tell them from a
  role made again under the name. Run it with `VC_HOSTS` naming that one vCenter. Before the census and every probe, the
  vCenter must list a role under that name with that id and exactly the privileges the name declares, or the run stops
  with nothing written (exit 5). It writes the ledger only, never vCenter; the probes and `--remove-probe-roles` in the
  same run then read the role as the ledger's. Name only a role you know a run of this companion made.

To retire roles a run made before the ledger, take the ids the `KEPT` lines print, then adopt and remove them in one run:

```bash
python3 authz.py --remove-probe-roles     # prints each role carrying a probe name the ledger does not name, and its id
python3 authz.py --adopt-probe-role authz-probe-none=<role id> --adopt-probe-role authz-probe-folder-create=<role id> --remove-probe-roles
```

Expected output of the first command on one vCenter holding two such roles (the ids are placeholders; the ledger's path
is printed in full on your terminal):

```text
  probe roles the ledger names (<this folder>/authz-probe-roles.state.json), one vCenter at a time:
     {{vcenter-1}}: 0 probe role(s) removed, none listed after; 0 reserved group(s) VCF left behind, removed by the vCenter's SSO administrator
       KEPT: authz-probe-folder-create (role id 1002): the ledger names no authz-probe-folder-create on this vCenter, so it is an operator's role or one a run made before the ledger existed
       KEPT: authz-probe-none (role id 1001): the ledger names no authz-probe-none on this vCenter, so it is an operator's role or one a run made before the ledger existed
       a kept role is left alone (exit 2): if a run of this companion made it before the ledger existed, add --adopt-probe-role authz-probe-folder-create=1002 --adopt-probe-role authz-probe-none=1001 to a run whose VC_HOSTS names that vCenter alone; a role of your own under a probe name is yours to rename
```

Removing a role leaves its reserved group behind (below); removing that takes the vCenter's SSO administrator.

## What it answers

1. **Which grants apply to a broker session.** A broker session carries the directory's name for the user
   (`DOMAIN\user`). A grant on that name, or on a directory group the user is in, applies. A grant spelled with
   the realm's name is accepted by vCenter, reported as effective by an administrator's privilege query, and,
   behind a broker backed by AD/LDAP, applies to nobody; behind a federated provider it was not measured. The realm's
   name is not the broker tenant (`BROKER_TENANT`, `CUSTOMER` by default) that an API client's session carries as
   `CUSTOMER\<its clientId>`. A grant spelled `CUSTOMER\<clientId>` applied to that client's session, and one spelled
   `CUSTOMER\<user>` did not reach a directory user signing in through the broker (one management vCenter, one run
   each). `--probe-grants` measures the directory and realm spellings on your vCenter with a one-privilege role on a
   throwaway folder: vCenter's own check, an actual subfolder create, and a REST read.
2. **How VCF roles reach vCenter.** As global permissions on local groups named `vcf_reserved_<role id>`. The
   census counts them and the other classes: local principals, directory users and groups, realm-spelled grants,
   API clients' grants (`API client (broker tenant)`, an integration's own access, kept), another identity provider's
   grants (VCF Automation's, on Supervisor namespaces). Local principals split three ways, by who looks after them:
   - `local, VCF-managed`: VCF's integration accounts (`svc-`), the Supervisor's (`wcp-`) and the solution users,
     named with a UUID at the end. Leave them to VCF, and read them as the evidence of what each integration holds.
     The census sorts by name, so an account you named `svc-` yourself lands here: check the names.
   - `local, Administrators`: the local administrator and the Administrators group. Read the group's members: from
     vCenter 9.1.1 the VCF Administrator role maps to it, and on the reference estate a directory administrators
     group is nested in it on every vCenter.
     Keep the administrator vaulted, as the way back in.
   - `local, other`: every other local group or user, the ones an administrator made and the groups vCenter or
     another product ships under their own names, which the census cannot tell apart by name. Read each, members
     included: a directory group nested in a local group carries that group's grant (measured once, on one vCenter,
     with a local group made for the test). Review the ones you made as you would a directory grant.
3. **Where tag rights come from.** `AttachTag` counts only from a global permission that propagates;
   `ObjectAttachable` must be in effect on the object. A grant on the object, Administrator included, never
   lets anyone tag. `--probe-tags` measures each combination on a throwaway folder.
4. **What an administrator holds on a Supervisor VM.** `--supervisor-vm` reads each identity's effective roles
   and tag privileges on the VM, attaches a throwaway tag as each, and records whether vCenter lets the
   administrator grant itself a tag role there. Choose a VM you own.
5. **Who signs in.** Sessions by principal class, and the local administrator's sessions by client agent.

## Scope, stated plainly

- The census is read-only. `--remove --execute` deletes only the realm-spelled grants you name by id, on one vCenter,
  and reads the list back. The probes need a test user that is not an administrator. `--probe-grants` and
  `--probe-tags` create a folder (and a tag category and tag) and grant roles on them for the length of one case;
  `--supervisor-vm` attaches a throwaway tag to the VM you name and tries grants on it as the administrator, removing
  any it is given. Each removes every grant and object it made except the six probe roles, kept on purpose (below),
  reads the vCenter back for its folder, its tag category, any grant it made on the VM and every grant of the ledger's
  roles, and never replaces a permission that already exists (vSphere keeps one per principal per object, so a
  principal that already holds one is skipped and recorded as skipped). A probe sends nothing while one of the ledger's
  roles is already granted to someone other than its reserved group (exit 2): reconciling the role would change what
  they hold.
- `--remove` was run once, on one 9.1.1 vCenter, on a grant the run made on a folder it made and removed. The pre-realm
  path, which now runs with `--no-realm`, was run (in X-197, as `REALM_DOMAIN` left unset, before a run had to declare
  it) on an estate that has a realm, not on one without. An estate with no realm yet was not run.
- A misspelled `REALM_DOMAIN` was run once (X-207), on one management vCenter holding one realm-spelled grant the run
  made on a folder it made and removed: `NOT PLACED` and exit 3, where the version before this check read the same grant
  as another provider's and exited 0. Spelled right, across the reference estate's three vCenters, the workload vCenter
  that runs a Supervisor held 12 grants of one domain no domain given placed, and the run exited 3 until that domain was
  named in `OTHER_DOMAINS`, then 0. Which product those grants belong to was not read in that run.
- The refusal of a realm typed as a directory, another provider's or the local domain is the script's code and its
  tests; no run was made with one. So are `--remove`'s session guard, the census's `realmSignedIn`, and the refusal of
  a session list that holds only the reader's own sessions: no run was made with a live session spelled in the realm
  or with a filtered list, and the record's session read holds none.
- The `API client (broker tenant)` class, `BROKER_TENANT` and its two guards are the script's code and its tests; no
  census was run on an estate holding such a grant. The two grants behind the class were measured by X-221's own
  driver, with `authz.py`'s probe role on a throwaway folder: one API client and one directory user, one management
  vCenter, one run each; that the name after `CUSTOMER\` is the client's clientId was read for two clients.
- Paging: each vCenter's own API metadata (vSphere API 9.0.0.0 onward) defines both lists as paged. A call that sets no
  iteration returns "only the first permissions that fit in a size defined by the service" (the role list reads the
  same), and a page size the client sets may be lowered by a service policy. On 2026-10-15, on the reference estate's
  three 9.1.1 vCenter instances, one call with no iteration returned every permission (270 on the largest) and every
  role, with no marker; walked one item per page, both lists returned the same sets. So the census's paged path has run
  only in its tests.
- **The probes' roles are kept, on purpose.** On a vCenter joined to VCF single sign-on, VCF creates a local
  group `vcf_reserved_<role id>` for every role created there, and deleting the role leaves the group behind.
  So the probes use six roles named `authz-probe-<what it holds>`, created the first time they are needed and
  reconciled on every run, instead of creating and deleting roles each time. Their reserved groups hold a
  grant of a role nobody else is given, which changes no one's access. A role is the companion's only when its ledger
  names it, by vCenter, whole name and role id (above). `--remove-probe-roles` removes the ledger's roles and reports
  the groups left behind; removing those takes the vCenter's SSO administrator. A role removed takes every grant of it
  along, so it refuses, with nothing sent, while one of the ledger's roles is granted to anyone but its own reserved
  group, and it reads the role list back after (exit 2 for either). A role's own reserved group is
  `vcf_reserved_<its role id>` in the local domain, matched whole: a role you named `authz-probe-<anything else>` is
  never reconciled, counted or removed, and a grant to another role's reserved group, or to a directory group of that
  name, counts as someone's access. It works one vCenter at a time and prints each one's result as it is done, so a run
  that stops shows which were done; a vCenter it could not finish is recorded with the roles it removed before the
  error (exit 3). These guards and `--remove-probe-roles` are the script's code and its tests; no run was made with
  them. A read-only read of the reference estate (X-311, 2026-10-17) found the six roles the 2026-10-06 run made still
  there, five on one management vCenter and one on the workload vCenter, each holding the privileges its name declares
  and granted to no one but its own reserved group, and each vCenter's instance UUID read as a UUID. On 2026-10-19 the
  six read the same again, and `--adopt-probe-role` recorded them in the reference estate's ledger, one vCenter per run
  (five, then one), each run's own check of name, id and privileges passing first (X-339); the probes run next reused
  all six, creating and reconciling none, and left each granted to no one but its own reserved group (X-340).
- The census sorts a local group named `vcf_reserved_` and a role id, matched whole, as a reserved group: a group you
  named with that prefix and anything else is read as `local, other`.
- A probe that stopped on an error, the `--supervisor-vm` lookup before the census, and `--remove-probe-roles` across
  vCenters that fail part way are the script's code and its tests; no run stopped so.
- `--save-permissions` and `--compare-permissions` were run once, read-only, on the reference estate's three 9.1.1
  vCenter instances (X-220, 2026-10-15): two saves wrote every grant at mode 0600 and compared equal, and two copies
  altered after they were written were refused. Every list came in one page there, so the paging past one page, the
  refusal of a list not read whole and the compare across two vCenter sets are the script's tests (recorded answers).
- The reserved groups list no members: vCenter's user directory returns none for them, even for a group
  whose VCF role is held. The census does not claim who holds a VCF role; VCF Operations' fleet IAM answers
  that.
- Every vCenter, user, group, domain and custom role name in the record is a placeholder.

## Reading the record

- `vcenters.<vc>.byClass`: permission counts by class and scope (`global` or `object`). A record written before the
  local split carries one `local` class (the reference estate's of 2026-10-06 did); the shipped `authz.json` carries the
  three. A record carries the `API client (broker tenant)` class only when a grant in the broker tenant was read, and
  the shipped one read none. A vCenter that was not read carries only `error`.
- `realmSpelling`: present when the run declared `--no-realm`, saying the realm-spelled class was not applicable.
- `replay`: `true` in a replayed run's `authz.replay.json`; a record of a read of an estate carries no such key.
- `vcenters.<vc>.domainsNamedNothing`, `vcenters.<vc>.realmNamedNothing`, `vcenters.<vc>.realmSignedIn`: present on a
  vCenter the run could not place (the domains given named no grant there, the realm named none beside an unplaced
  domain, or a live session there is spelled in the realm); the run exited 3.
- `exit`: the run's exit code (a record written before the exit table carries none).
- `vcenters.<vc>.reservedGroupGrants`: grants on `vcf_reserved_*` groups, by the role held (product roles by
  name, custom roles as `a custom role`) and scope. Object-scoped ones are the Supervisor's namespace grants.
- `vcenters.<vc>.sessions`: sessions by class, and the local administrator's sessions by client agent; `error` when the
  list was not read whole, `not read: pyVmomi is not installed`, or, in a replayed run's `authz.replay.json`, `not read: a
  replayed run reads no session list (it is read through pyVmomi)`.
- `probeRoleTeardown.<vc>`: with `--remove-probe-roles`, the ledger's roles removed (`removedRoles`), `rolesLeft`, how
  many of them are still listed on the read-back (`null`: not read back), the reserved groups VCF left, `kept` (each
  role carrying a probe name that the ledger does not name with that id, and why) with `next`, the step for one a run
  made before the ledger, `alreadyGone` (the ledger's roles no longer listed under their ids, forgotten), `ledger` when
  the ledger was not written after the removal, `refused` with nothing sent, or `error` with what was removed before it.
- `probeRoleAdoption.<vc>`: with `--adopt-probe-role`, each role recorded in the ledger (`adopted <name> (role id
  <id>)`), or already there.
- `roleDrift`: custom roles whose copies differ between vCenters, with what each copy holds beyond the shared
  set.
- `grantProbe`, `tagProbe`, `supervisorProbe`: each case, its outcome, and the residue read afterwards (`true` or a
  count: left behind; `null`: not read back); `probeRoles`, each role the probe created or reconciled with its role id
  (a record written before the ledger carries no id); `aborted` when the probe could not run, or sent nothing; `stopped`
  when it met an error it did not expect, with only the error's kind (its message is on the terminal).
