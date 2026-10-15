# vCenter authorization under VCF single sign-on, read the way a broker session reads it

Companion to the chapter
([privatecloudarchitect.com/handbook/vcenter-authorization](https://privatecloudarchitect.com/handbook/vcenter-authorization)):
one script that reads every permission on your vCenters and classifies it by how it behaves for someone
signed in through the VCF identity broker, and three opt-in probes that settle the questions a read cannot.
Standard library Python 3.10 or later, plus pyVmomi for the session read and the probes.

| File | What it is |
|---|---|
| `authz.py` | The census (read-only), the realm-spelled grants named (`--where-realm`) and removed (`--remove`, plan first), and the probes (opt-in, on objects they create and remove). Writes `authz.json` with every estate name replaced, and refuses to write a record in which one survived. |
| `authz.json` | That record from the reference estate. The chapter's plates render it. |

## Run it

```bash
export VC_HOSTS=<vcenter-fqdn>[,<another>]
export VC_USER=<an administrator, user@domain>
export VC_PASSWORD_FILE=/path/to/password          # mode 0600
export REALM_DOMAIN=<the realm's name>            # once the estate has a realm (before one, run with --no-realm); not CUSTOMER
export DIRECTORY_DOMAINS=<directory domain>[,<another>]   # required
export LOCAL_DOMAIN=<your SSO domain>             # only if it is not vsphere.local; otherwise every local grant reads as another provider's
export OTHER_DOMAINS=<another provider's domain>[,<another>]   # optional: domains you know are another provider's
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

A misspelled `REALM_DOMAIN` is caught the same way. It moves every realm-spelled grant into another provider's class,
where nothing flags it, while the directory domains still name their own grants. So with `REALM_DOMAIN` set, a vCenter
on which the realm names no grant while grants of an unplaced domain are there (one in none of `DIRECTORY_DOMAINS`,
`LOCAL_DOMAIN`, `REALM_DOMAIN` and `OTHER_DOMAINS`) prints `NOT PLACED` with those domains, on the terminal only,
records `realmNamedNothing`, and exits 3. Check `REALM_DOMAIN` against the realm's name, and name in `OTHER_DOMAINS`
each domain you know is another identity provider's. On the reference estate, with the realm spelled right and no
realm-spelled grant left, the workload vCenter that runs a Supervisor needed one such domain named before the run
exited 0 (X-207).

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
python3 authz.py --remove <id>[,<id>...]           # the plan: each grant and the DELETE it would send; nothing is sent
python3 authz.py --remove <id>[,<id>...] --execute # one DELETE per id, then the list read back
```

`--where-realm` prints each id on your terminal and never writes it to the record. `--remove` acts on one vCenter at a
time and only on realm-spelled grants: it refuses, before anything is sent, an id that vCenter does not hold and an id
that is not a realm-spelled grant (remove any other grant where it was made). With `--execute` it holds when every named
grant is gone and no other grant moved on the read-back; a second run with the same ids is refused, because the ids are
gone, so it is safe to repeat. It writes no record. Expected output, with the names replaced:

```text
authz.py --remove on <vcenter>: 1 realm-spelled grant(s), printed here only
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
| 2 | a removal (`--remove --execute`) that did not hold on read-back, a named grant still there or another grant moved; or a probe that left residue | read the vCenter's permissions before anything else |
| 1 | the census read realm-spelled grants (only with `REALM_DOMAIN` set; before a realm there is no such class) | name them with `--where-realm`, remove them with `--remove` |
| 3 | a read failed or a result is undetermined: a vCenter refused the session or a list, the session list was not read, the domains named no grant on a vCenter, or `REALM_DOMAIN` named none there beside an unplaced domain (`NOT PLACED`), a probe could not run, or an error the script did not expect | nothing is known about what was not read: fix the read (or the spelling, or `OTHER_DOMAINS`) and run again |
| 0 | nothing for a person to act on: every vCenter read and placed, no realm-spelled grant, every probe clean; with `--remove`, the plan printed or the removal held | nothing |
| 5 | a usage error, found before anything is read (a missing or wrong argument or variable, a password file it cannot read, an id `--remove` cannot name as a realm-spelled grant, pyVmomi missing for a step that needs it, a Python older than 3.10), or the record refused because an estate value survived the scrub (nothing is written) | fix the invocation |

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
  and reads the list back. The probes create a folder, a tag category and a tag, grant roles on those objects
  for the length of one case, and remove everything they created; they never replace a permission that
  already exists (vSphere keeps one per principal per object, so a principal that already holds one is
  skipped and recorded as skipped).
- `--remove` was run once, on one 9.1.1 vCenter, on a grant the run made on a folder it made and removed. The pre-realm
  path, which now runs with `--no-realm`, was run (in X-197, as `REALM_DOMAIN` left unset, before a run had to declare
  it) on an estate that has a realm, not on one without. An estate with no realm yet was not run.
- A misspelled `REALM_DOMAIN` was run once (X-207), on one management vCenter holding one realm-spelled grant the run
  made on a folder it made and removed: `NOT PLACED` and exit 3, where the version before this check read the same grant
  as another provider's and exited 0. Spelled right, across the reference estate's three vCenters, the workload vCenter
  that runs a Supervisor held 12 grants of one domain no domain given placed, and the run exited 3 until that domain was
  named in `OTHER_DOMAINS`, then 0. Which product those grants belong to was not read in that run.
- **The probes' roles are kept, on purpose.** On a vCenter joined to VCF single sign-on, VCF creates a local
  group `vcf_reserved_<role id>` for every role created there, and deleting the role leaves the group behind.
  So the probes use six roles named `authz-probe-<what it holds>`, created the first time they are needed and
  reconciled on every run, instead of creating and deleting roles each time. Their reserved groups hold a
  grant of a role nobody else is given, which changes no one's access. `--remove-probe-roles` removes them and
  reports the groups left behind; removing those takes the vCenter's SSO administrator.
- The reserved groups list no members: vCenter's user directory returns none for them, even for a group
  whose VCF role is held. The census does not claim who holds a VCF role; VCF Operations' fleet IAM answers
  that.
- Every vCenter, user, group, domain and custom role name in the record is a placeholder.

## Reading the record

- `vcenters.<vc>.byClass`: permission counts by class and scope (`global` or `object`). A record written before the
  local split carries one `local` class; the shipped `authz.json` is one of those. A vCenter that was not read carries
  only `error`.
- `realmSpelling`: present when the run declared `--no-realm`, saying the realm-spelled class was not applicable.
- `vcenters.<vc>.domainsNamedNothing`, `vcenters.<vc>.realmNamedNothing`: present on a vCenter the run could not place
  (the domains given named no grant there, or the realm named none beside an unplaced domain); the run exited 3.
- `exit`: the run's exit code (a record written before the exit table carries none).
- `vcenters.<vc>.reservedGroupGrants`: grants on `vcf_reserved_*` groups, by the role held (product roles by
  name, custom roles as `a custom role`) and scope. Object-scoped ones are the Supervisor's namespace grants.
- `vcenters.<vc>.sessions`: sessions by class, and the local administrator's sessions by client agent.
- `roleDrift`: custom roles whose copies differ between vCenters, with what each copy holds beyond the shared
  set.
- `grantProbe`, `tagProbe`, `supervisorProbe`: each case, its outcome, and the residue read afterwards.
