# vCenter authorization under VCF single sign-on, read the way a broker session reads it

Companion to the chapter
([privatecloudarchitect.com/handbook/vcenter-authorization](https://privatecloudarchitect.com/handbook/vcenter-authorization)):
one script that reads every permission on your vCenters and classifies it by how it behaves for someone
signed in through the VCF identity broker, and three opt-in probes that settle the questions a read cannot.
Standard library Python, plus pyVmomi for the session read and the probes.

| File | What it is |
|---|---|
| `authz.py` | The census (read-only) and the probes (opt-in, on objects they create and remove). Writes `authz.json` with every estate name replaced, and refuses to write a record in which one survived. |
| `authz.json` | That record from the reference estate. The chapter's plates render it. |

## Run it

```bash
export VC_HOSTS=<vcenter-fqdn>[,<another>]
export VC_USER=<an administrator, user@domain>
export VC_PASSWORD_FILE=/path/to/password          # mode 0600
export REALM_DOMAIN=<the realm's name>            # required; VCF Operations, fleet IAM realms; not CUSTOMER
export DIRECTORY_DOMAINS=<directory domain>[,<another>]   # required
export LOCAL_DOMAIN=<your SSO domain>             # only if it is not vsphere.local; otherwise every local grant reads as another provider's
export TLS_VERIFY=false                            # only on a self-signed lab CA

python3 authz.py                                   # the census, read-only
```

The census refuses to start without `REALM_DOMAIN` or `DIRECTORY_DOMAINS`: either one unset reads its grants as
another provider's, so the census would count no realm-spelled or no directory grant on an estate full of them. On a
vCenter where neither names a grant while another provider's grants are there, it prints `NOT PLACED` under that vCenter
and records `domainsNamedNothing`; check the spelling against the vCenter's own before reading the census.

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

- The census is read-only. The probes create a folder, a tag category and a tag, grant roles on those objects
  for the length of one case, and remove everything they created; they never replace a permission that
  already exists (vSphere keeps one per principal per object, so a principal that already holds one is
  skipped and recorded as skipped).
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
  local split carries one `local` class; the shipped `authz.json` is one of those.
- `vcenters.<vc>.reservedGroupGrants`: grants on `vcf_reserved_*` groups, by the role held (product roles by
  name, custom roles as `a custom role`) and scope. Object-scoped ones are the Supervisor's namespace grants.
- `vcenters.<vc>.sessions`: sessions by class, and the local administrator's sessions by client agent.
- `roleDrift`: custom roles whose copies differ between vCenters, with what each copy holds beyond the shared
  set.
- `grantProbe`, `tagProbe`, `supervisorProbe`: each case, its outcome, and the residue read afterwards.
