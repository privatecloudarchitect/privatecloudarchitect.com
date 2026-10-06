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
export REALM_DOMAIN=<the broker realm's domain>    # VCF Operations, fleet IAM realms
export DIRECTORY_DOMAINS=<directory domain>[,<another>]
export TLS_VERIFY=false                            # only on a self-signed lab CA

python3 authz.py                                   # the census, read-only
```

The probes need a test user that is **not** an administrator, and a directory group it belongs to:

```bash
export TEST_USER=<user@directory-domain> TEST_PASSWORD_FILE=/path/to/password TEST_GROUP=<group>
export PROBE_VCENTER=<a vCenter where TEST_USER holds nothing, for --probe-tags>
export SUPERVISOR_VCENTER=<the vCenter of the Supervisor VM>

python3 authz.py --probe-grants --probe-tags --supervisor-vm <a Supervisor VM you own>
```

## What it answers

1. **Which grants apply to a broker session.** A broker session carries the directory's name for the user
   (`DOMAIN\user`). A grant on that name, or on a directory group the user is in, applies. A grant spelled with
   the broker realm's domain is accepted by vCenter, reported as effective by an administrator's privilege
   query, and applies to nobody. `--probe-grants` measures this on your vCenter with a one-privilege role on a
   throwaway folder: vCenter's own check, an actual subfolder create, and a REST read.
2. **How VCF roles reach vCenter.** As global permissions on local groups named `vcf_reserved_<role id>`. The
   census counts them and the other classes: local accounts, directory users and groups, realm-spelled grants,
   another identity provider's grants (VCF Automation's, on Supervisor namespaces).
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
- Membership of the reserved groups is not stored in the SSO domain: the SSO administration API lists no
  members even for groups whose VCF role is held. The census does not claim who holds a VCF role; VCF
  Operations' fleet IAM answers that.
- Every vCenter, user, group, domain and custom role name in the record is a placeholder.

## Reading the record

- `vcenters.<vc>.byClass`: permission counts by class and scope (`global` or `object`).
- `vcenters.<vc>.reservedGroupGrants`: grants on `vcf_reserved_*` groups, by the role held (product roles by
  name, custom roles as `a custom role`) and scope. Object-scoped ones are the Supervisor's namespace grants.
- `vcenters.<vc>.sessions`: sessions by class, and the local administrator's sessions by client agent.
- `roleDrift`: custom roles whose copies differ between vCenters, with what each copy holds beyond the shared
  set.
- `grantProbe`, `tagProbe`, `supervisorProbe`: each case, its outcome, and the residue read afterwards.
