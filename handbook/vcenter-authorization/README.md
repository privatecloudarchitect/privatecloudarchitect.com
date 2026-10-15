# vCenter authorization under VCF single sign-on, read the way a broker session reads it

Companion to the chapter
([privatecloudarchitect.com/handbook/vcenter-authorization](https://privatecloudarchitect.com/handbook/vcenter-authorization)):
one script that reads every permission on your vCenters and classifies it by how it behaves for someone
signed in through the VCF identity broker, and three opt-in probes that settle the questions a read cannot.
Standard library Python 3.10 or later, plus pyVmomi for the session read (needed once `REALM_DOMAIN` is set), `--remove`
and the probes.

| File | What it is |
|---|---|
| `authz.py` | The census (read-only), the realm-spelled grants named (`--where-realm`) and removed (`--remove`, plan first), and the probes (opt-in, and they write to vCenter: a throwaway folder, tag category and tag they create and remove, grants for the length of one case, a throwaway tag on a VM you own for `--supervisor-vm`, and six `authz-probe-*` roles kept by design). Writes `authz.json` with every estate name replaced, and refuses to write a record in which one survived. |
| `authz.json` | That record from the reference estate. The chapter's plates render it. |

## Run it

```bash
export VC_HOSTS=<vcenter-fqdn>[,<another>]
export VC_USER=<an administrator, user@domain>
export VC_PASSWORD_FILE=/path/to/password          # mode 0600
export REALM_DOMAIN=<the realm's name>            # once the estate has a realm (before one, run with --no-realm); never a directory domain, nor CUSTOMER
export DIRECTORY_DOMAINS=<directory domain>[,<another>]   # required
export LOCAL_DOMAIN=<your SSO domain>             # only if it is not vsphere.local; otherwise every local grant reads as another provider's
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
every grant sorts as local first and no realm-spelled grant could be found. `--remove` and `--where-realm` are refused
the same way. Expected output, with the names replaced:

```text
REALM_DOMAIN (<domain>) and DIRECTORY_DOMAINS (<domain>) name the same domain. REALM_DOMAIN is the realm's name as vCenter spells it in a grant (VCF Operations, fleet IAM realms); a directory domain is the one your directory spells its users and groups in, DOMAIN\user, which a broker session carries. Read as one, every working grant in that domain would be classed realm-spelled and named for removal. Set REALM_DOMAIN to the realm's name (exit 5)
```

### Every page of the lists

The permission and role lists are paged: an answer that carries a `marker` has more after it, and the census asks for
the next page with that marker until an answer carries none. A page refused, or a marker answered twice, is a list not
read (exit 3, `NOT READ` under that vCenter), and so is a permission list with no permission in it, because `VC_USER`,
an administrator, holds one.

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

## Exit codes

The first that applies, so a scheduler reads one state from one number:

| Exit | Means | Do |
|---|---|---|
| 2 | a removal (`--remove --execute`) that did not hold on read-back, a named grant still there or another grant moved; `--remove-probe-roles` refused (a probe role granted to someone other than its reserved group, which removing the role would remove too; nothing is sent) or not held (a probe role still listed after it); or a probe that left residue (its folder, its tag category, a grant it made on the Supervisor VM, or a grant of a probe role, one there before it began included, when it sends nothing) | read the vCenter's permissions before anything else |
| 1 | the census read realm-spelled grants (only with `REALM_DOMAIN` set, only when every vCenter's session list was read whole, and never while a live session is spelled in it; before a realm there is no such class) | name them with `--where-realm`, remove them with `--remove` |
| 3 | a read failed or a result is undetermined: a vCenter refused the session or a page of a list, a permission list held no permission, a session list not read whole (refused, holding only the reader's own sessions, or, with `REALM_DOMAIN` set, not read because pyVmomi is missing), the domains named no grant on a vCenter, or `REALM_DOMAIN` named none there beside an unplaced domain, or a live session is spelled in `REALM_DOMAIN` (`NOT PLACED`; with `--remove`, nothing is sent), a probe could not run or its residue was not read back, or an error the script did not expect | nothing is known about what was not read: fix the read (or the spelling, `DIRECTORY_DOMAINS` or `OTHER_DOMAINS`) and run again |
| 0 | nothing for a person to act on: every vCenter read and placed (with `REALM_DOMAIN` set, its session list read whole), no realm-spelled grant, every probe clean; with `--remove`, the plan printed or the removal held | nothing |
| 5 | a usage error, found before anything is read (a missing or wrong argument or variable, a password file it cannot read, a `REALM_DOMAIN` equal to a `DIRECTORY_DOMAINS`, `OTHER_DOMAINS` or `LOCAL_DOMAIN` entry, `--remove` without `OTHER_DOMAINS` stated, an id `--remove` cannot name as a realm-spelled grant, pyVmomi missing for a step that needs it, `--remove` among them, a Python older than 3.10) | fix the invocation |

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

## What it answers

1. **Which grants apply to a broker session.** A broker session carries the directory's name for the user
   (`DOMAIN\user`). A grant on that name, or on a directory group the user is in, applies. A grant spelled with
   the realm's name is accepted by vCenter, reported as effective by an administrator's privilege query, and,
   behind a broker backed by AD/LDAP, applies to nobody; behind a federated provider it was not measured. The realm's name is not the broker tenant (`CUSTOMER` by default) that an API client's
   session carries as `CUSTOMER\<client id>`; whether a grant spelled `CUSTOMER\<name>` applies to anyone was not
   tested. `--probe-grants` measures this on your vCenter with a one-privilege role on a
   throwaway folder: vCenter's own check, an actual subfolder create, and a REST read.
2. **How VCF roles reach vCenter.** As global permissions on local groups named `vcf_reserved_<role id>`. The
   census counts them and the other classes: local principals, directory users and groups, realm-spelled grants,
   another identity provider's grants (VCF Automation's, on Supervisor namespaces). Local principals split three
   ways, by who looks after them:
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
  reads the vCenter back for its folder, its tag category, any grant it made on the VM and every grant of a probe role,
  and never replaces a permission that already exists (vSphere keeps one per principal per object, so a principal
  that already holds one is skipped and recorded as skipped). A probe sends nothing while a probe role is already
  granted to someone other than its reserved group (exit 2): reconciling the role would change what they hold.
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
  grant of a role nobody else is given, which changes no one's access. `--remove-probe-roles` removes them and
  reports the groups left behind; removing those takes the vCenter's SSO administrator. A role removed takes every
  grant of it along, so it refuses, with nothing sent, while a probe role is granted to anyone but its reserved group,
  and it reads the role list back after (exit 2 for either). These two guards are the script's code and its tests; no
  run was made with them.
- The reserved groups list no members: vCenter's user directory returns none for them, even for a group
  whose VCF role is held. The census does not claim who holds a VCF role; VCF Operations' fleet IAM answers
  that.
- Every vCenter, user, group, domain and custom role name in the record is a placeholder.

## Reading the record

- `vcenters.<vc>.byClass`: permission counts by class and scope (`global` or `object`). A record written before the
  local split carries one `local` class; the shipped `authz.json` is one of those. A vCenter that was not read carries
  only `error`.
- `realmSpelling`: present when the run declared `--no-realm`, saying the realm-spelled class was not applicable.
- `vcenters.<vc>.domainsNamedNothing`, `vcenters.<vc>.realmNamedNothing`, `vcenters.<vc>.realmSignedIn`: present on a
  vCenter the run could not place (the domains given named no grant there, the realm named none beside an unplaced
  domain, or a live session there is spelled in the realm); the run exited 3.
- `exit`: the run's exit code (a record written before the exit table carries none).
- `vcenters.<vc>.reservedGroupGrants`: grants on `vcf_reserved_*` groups, by the role held (product roles by
  name, custom roles as `a custom role`) and scope. Object-scoped ones are the Supervisor's namespace grants.
- `vcenters.<vc>.sessions`: sessions by class, and the local administrator's sessions by client agent; `error` when the
  list was not read whole, or `not read: pyVmomi is not installed`.
- `probeRoleTeardown.<vc>`: with `--remove-probe-roles`, the roles removed, `rolesLeft` on the read-back, the reserved
  groups VCF left, or `refused` with nothing sent.
- `roleDrift`: custom roles whose copies differ between vCenters, with what each copy holds beyond the shared
  set.
- `grantProbe`, `tagProbe`, `supervisorProbe`: each case, its outcome, and the residue read afterwards (`true` or a
  count: left behind; `null`: not read back); `aborted` when the probe could not run, or sent nothing.
