#!/usr/bin/env python3
"""authz.py: who may do what in vCenter under VCF single sign-on, read the way a broker session reads it.

Once vCenter signs people in through the VCF identity broker, two authorization planes apply at once: the
vCenter's own permissions, and the VCF roles assigned in VCF Operations, which arrive in vCenter as global
permissions on local groups named ``vcf_reserved_<role id>``. A broker session carries the directory's name
for the user (``DOMAIN\\user``), so a permission spelled with the broker realm's domain applies to nobody, even
though vCenter accepts it and an administrator's privilege query reports it as effective.

Read-only by default:

  1. GRANTS: every permission on each vCenter, global and per-object, from the vSphere Automation API's list
     action, classified by how it behaves for a broker session: reserved group (a VCF role arriving), local,
     directory user, directory group, realm spelling (inert), or another provider's;
  2. ROLES: the role catalog, and the custom roles whose copies differ between vCenters;
  3. SESSIONS (pyVmomi, optional): who is signed in now, by principal class and client agent. Addresses,
     session keys and login times are never read into the record.

Opt-in probes. Each creates its own throwaway objects (a folder, a tag category and tag), removes them in a
``finally``, and reads the vCenter back for residue. None replaces an existing permission: vSphere keeps one
permission per principal per object, so a principal that already holds one where a case would add one is
skipped and recorded as skipped. All need pyVmomi.

The probes' roles are not throwaway. On a vCenter joined to VCF single sign-on, VCF creates a local group
``vcf_reserved_<role id>`` for every role created there, and deleting the role leaves the group behind, so a
probe that created and deleted its roles on every run would leave one empty group per role per run. The
probes use six roles named ``authz-probe-<what it holds>``, created the first time they are needed, reconciled
to their declared privileges on every run, and granted only on the probe's own objects for the length of a
case. ``--remove-probe-roles`` removes them and reports the reserved groups VCF leaves; removing those takes
the vCenter's SSO administrator.

  --probe-grants   on PROBE_VCENTER: a one-privilege role (Folder.Create) on a throwaway folder, granted in turn
                   to TEST_USER and to TEST_GROUP, each in the directory and the realm spelling, measured from
                   fresh sessions of TEST_USER (vCenter's own check, an actual subfolder create, a REST read).
  --probe-tags     on PROBE_VCENTER, where TEST_USER should hold nothing: where the two tag privileges must come
                   from. AttachTag counts only from a global permission that propagates; ObjectAttachable must
                   be in effect on the object. Each case attaches a throwaway tag as TEST_USER and detaches it.
  --supervisor-vm NAME
                   on PROBE_VCENTER: the effective roles and tag privileges of VC_USER and TEST_USER on one
                   Supervisor-managed VM, an attach of a throwaway tag as each, and VC_USER's attempts to grant
                   itself a tag role on the VM (every role it grants itself carries ModifyPermissions, so an
                   accepted grant stays removable). Choose a VM you own.

Environment:
  VC_HOSTS            comma-separated vCenter FQDNs
  VC_USER             an administrator of those vCenters, user@domain
  VC_PASSWORD_FILE    a file holding that password (mode 0600); VC_PASSWORD is read if it is not set
  REALM_DOMAIN        the broker realm's domain as vCenter spells it (VCF Operations, fleet IAM realms)
  DIRECTORY_DOMAINS   comma-separated directory domains under the broker's identity provider
  TLS_VERIFY          false only on a self-signed lab CA
  TEST_USER, TEST_PASSWORD_FILE, TEST_GROUP, PROBE_VCENTER   for the probes (TEST_USER must not be an administrator)
  SUPERVISOR_VCENTER  the vCenter for --supervisor-vm (default PROBE_VCENTER)
  OUT_DIR             where authz.json is written (default: this folder)

Run:  python3 authz.py [--probe-grants] [--probe-tags] [--supervisor-vm NAME]
"""
import argparse
import base64
import collections
import contextlib
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ATTACH = "InventoryService.Tagging.AttachTag"
ON_OBJECT = "InventoryService.Tagging.ObjectAttachable"
MODIFY = "Authorization.ModifyPermissions"
RESERVED_PREFIX = "vcf_reserved_"

# The platform's own vocabulary: system roles, the roles the Supervisor grants, the local groups vCenter ships.
# A word in this set identifies no estate, so it is never replaced, and the leak check never fires on it.
PRODUCT_ROLES = {
    "Admin", "ReadOnly", "View", "Anonymous", "NoAccess", "NoCryptoAdmin", "TrustedAdmin", "NoTrustedAdmin",
    "VM-Service-VM-Management", "NamespacesEdit", "NamespacesView", "NamespacesOwner",
    "SupervisorAdministrator", "vSpherePodAdministrator", "VMOperatorController", "ObservabilityOperator",
}
PRODUCT_LOCAL = {"Administrator", "Administrators"}


# ---------------------------------------------------------------- plumbing

def ctx():
    verify = os.environ.get("TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")
    return ssl.create_default_context() if verify else ssl._create_unverified_context()


def secret(name):
    path = os.environ.get(name + "_FILE")
    if path:
        return open(path, encoding="utf-8").read().strip()
    return os.environ.get(name, "")


class Rest:
    """The vSphere Automation API under one session, closed on exit."""

    def __init__(self, host, user, password):
        self.host = host
        basic = base64.b64encode(f"{user}:{password}".encode()).decode()
        st, body = self.call("POST", "/api/session", headers={"Authorization": f"Basic {basic}"})
        self.token = body if st in (200, 201) and isinstance(body, str) else None

    def call(self, method, path, body=None, headers=None):
        h = {"Accept": "application/json", **(headers or {})}
        if getattr(self, "token", None):
            h["vmware-api-session-id"] = self.token
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        rq = urllib.request.Request(f"https://{self.host}{path}", data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(rq, context=ctx(), timeout=60) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as e:
            return e.code, None
        except (urllib.error.URLError, OSError):
            return None, None

    def close(self):
        if self.token:
            self.call("DELETE", "/api/session")
            self.token = None


def permissions(rest):
    """Every permission, global and per-object. A GET on the collection answers 404 on vCenter 9.1; the
    list is the action=list POST with an empty filter, and global ones carry object type GlobalAcl."""
    st, body = rest.call("POST", "/api/vcenter/authorization/permissions?action=list", {})
    if st != 200:
        raise SystemExit(f"permission list answered {st}")
    return body["items"]


def roles(rest):
    st, body = rest.call("GET", "/api/vcenter/authorization/roles")
    if st != 200:
        raise SystemExit(f"role list answered {st}")
    return {str(i["role"]): i["info"] for i in body["items"]}


def soap(host, user, password):
    from pyVim.connect import SmartConnect
    c = ssl.create_default_context()
    if os.environ.get("TLS_VERIFY", "true").strip().lower() in ("0", "false", "no", "off"):
        c.check_hostname, c.verify_mode = False, ssl.CERT_NONE
    return SmartConnect(host=host, user=user, pwd=password, sslContext=c)


def unsoap(si):
    from pyVim.connect import Disconnect
    with contextlib.suppress(Exception):
        Disconnect(si)


def have_pyvmomi():
    try:
        import pyVmomi  # noqa: F401
        return True
    except ImportError:
        return False


# ---------------------------------------------------------------- the census

def classify(domain, name, realm, directories):
    d = domain.upper()
    if d == "VSPHERE.LOCAL":
        return "reserved group" if name.startswith(RESERVED_PREFIX) else "local"
    if realm and d == realm.upper():
        return "realm spelling"
    if d.lower() in directories:
        return "directory"
    return "another provider"


def census(rest, realm, directories):
    perms, cat = permissions(rest), roles(rest)
    by = collections.Counter()
    directory_kinds = collections.Counter()
    reserved_named = collections.Counter()
    for p in perms:
        info, who = p["info"], p["info"]["principal"]
        scope = "global" if info["object"]["type"] == "GlobalAcl" else "object"
        cls = classify(who["domain"], who["name"], realm, directories)
        by[f"{cls}, {scope}"] += 1
        if cls == "directory":
            directory_kinds[f"{who['type'].lower()}, {scope}"] += 1
        if cls == "reserved group":
            role = cat.get(str(info["role"]), {}).get("name", "?")
            reserved_named[f"{role if role in PRODUCT_ROLES else 'a custom role'}, {scope}"] += 1
    return {
        "permissions": len(perms),
        "global": sum(1 for p in perms if p["info"]["object"]["type"] == "GlobalAcl"),
        "byClass": dict(sorted(by.items())),
        "directoryGrants": dict(sorted(directory_kinds.items())),
        "reservedGroupGrants": dict(sorted(reserved_named.items())),
        "roles": len(cat),
        "customRoles": sum(1 for r in cat.values() if not r.get("system")),
    }, cat


def drift(catalogs, L):
    """Custom roles sharing a name across vCenters but not a privilege set: what each copy adds."""
    by_name = collections.defaultdict(dict)
    for vc, cat in catalogs.items():
        for info in cat.values():
            if not info.get("system"):
                by_name[info["name"]][vc] = set(info.get("privileges") or [])
    out = []
    for name, copies in sorted(by_name.items()):
        if len(copies) > 1 and len({frozenset(v) for v in copies.values()}) > 1:
            common = set.intersection(*copies.values())
            out.append({"role": name if name in PRODUCT_ROLES else L.get("role", name),
                        "copies": {vc: sorted(p - common) for vc, p in sorted(copies.items())}})
    return out


def sessions(si, realm, directories):
    by_class = collections.Counter()
    admin_agents = collections.Counter()
    for s in si.content.sessionManager.sessionList or []:
        domain, _, name = str(s.userName).rpartition("\\")
        cls = classify(domain, name, realm, directories)
        by_class[cls] += 1
        if domain.upper() == "VSPHERE.LOCAL" and name == "Administrator":
            admin_agents[str(getattr(s, "userAgent", "") or "").split("/")[0][:40] or "(none)"] += 1
    return {"byClass": dict(sorted(by_class.items())), "localAdministratorByAgent": dict(sorted(admin_agents.items()))}


# ---------------------------------------------------------------- the probes

PROBE_ROLE_PREFIX = "authz-probe-"
PROBE_ROLES = {
    "folder-create": ["Folder.Create"],
    "none": [],
    "attach-tag": [ATTACH],
    "tag-on-object": [ON_OBJECT],
    "tag-both": [ATTACH, ON_OBJECT],
    "tag-on-object-modify": [ON_OBJECT, MODIFY],
}
SYSTEM_PRIVILEGES = {"System.Anonymous", "System.Read", "System.View"}


def ensure_probe_roles(am, keys):
    """The id of each probe role, created if missing and reconciled if its privileges drifted."""
    by_name = {r.name: r for r in am.roleList}
    ids, actions = {}, []
    for key in keys:
        want, role = set(PROBE_ROLES[key]), by_name.get(PROBE_ROLE_PREFIX + key)
        if role is None:
            ids[key] = am.AddAuthorizationRole(name=PROBE_ROLE_PREFIX + key, privIds=sorted(want))
            actions.append("created " + PROBE_ROLE_PREFIX + key)
            continue
        ids[key] = role.roleId
        if set(role.privilege or []) - SYSTEM_PRIVILEGES != want:
            am.UpdateAuthorizationRole(roleId=role.roleId, newName=PROBE_ROLE_PREFIX + key, privIds=sorted(want))
            actions.append("reconciled " + PROBE_ROLE_PREFIX + key)
    return ids, actions


def probe_role_grants(am):
    """Grants of a probe role to anyone but its own reserved group. A clean run leaves none."""
    ids = {r.roleId for r in am.roleList if r.name.startswith(PROBE_ROLE_PREFIX)}
    return sum(1 for p in am.RetrieveAllPermissions()
               if p.roleId in ids and not str(p.principal).split("\\")[-1].startswith(RESERVED_PREFIX))


def remove_probe_roles(si):
    am = si.content.authorizationManager
    roles = [(r.roleId, r.name) for r in am.roleList if r.name.startswith(PROBE_ROLE_PREFIX)]
    for rid, _ in roles:
        am.RemoveAuthorizationRole(rid, False)
    return {"removed": len(roles), "reservedGroupsLeft": reserved_groups_left(si, [rid for rid, _ in roles])}


def reserved_groups_left(si, role_ids):
    """On a vCenter joined to VCF single sign-on, VCF creates a local group vcf_reserved_<role id> for a role
    created there, and deleting the role leaves the group behind, empty. Count the ones this run left, so the
    residue report is complete; removing them takes the vCenter's SSO administrator."""
    found = 0
    for rid in role_ids:
        if rid is None:
            continue
        res = si.content.userDirectory.RetrieveUserGroups(
            domain="VSPHERE.LOCAL", searchStr=f"{RESERVED_PREFIX}{rid}", belongsToGroup=None, belongsToUser=None,
            exactMatch=False, findUsers=False, findGroups=True)
        found += sum(1 for g in res if g.principal == f"{RESERVED_PREFIX}{rid}")
    return found


def wait(task, seconds=30):
    for _ in range(seconds):
        if task.info.state in ("success", "error"):
            return
        time.sleep(1)


def measure_folder(host, subject, folder_moid, folder_name, admin_si):
    """vCenter's own check, an actual subfolder create, and a REST read, each from a fresh session. The
    subject may hold Folder.Create and not Folder.Delete, so the administrator removes the subfolder."""
    from pyVmomi import vim
    out = {}
    try:
        si = soap(host, *subject)
    except Exception as e:
        out["signIn"] = type(e).__name__
        si = None
    if si is not None:
        try:
            f = vim.Folder(folder_moid, si._stub)
            got = si.content.authorizationManager.HasPrivilegeOnEntity(
                f, si.content.sessionManager.currentSession.key, ["Folder.Create"])
            out["check"] = bool(got[0])
            try:
                child = f.CreateFolder(folder_name + "-child")
                out["enforced"] = True
                wait(vim.Folder(child._moId, admin_si._stub).Destroy_Task())
            except vim.fault.NoPermission:
                out["enforced"] = False
        finally:
            unsoap(si)
    r = Rest(host, *subject)
    try:
        st, body = r.call("GET", "/api/vcenter/folder?names=" + urllib.parse.quote(folder_name))
        out["restSeesFolder"] = bool(st == 200 and any(x.get("folder") == folder_moid for x in body or []))
    finally:
        r.close()
    return out


def probe_grants(host, admin, subject, cases):
    from pyVmomi import vim
    name = "authz-run-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    si = soap(host, *admin)
    am = si.content.authorizationManager
    made = {}
    rec = {"privilege": "Folder.Create", "cases": []}
    try:
        dc = next(e for e in si.content.rootFolder.childEntity if isinstance(e, vim.Datacenter))
        made["folder"] = dc.vmFolder.CreateFolder(name)
        ids, rec["probeRoles"] = ensure_probe_roles(am, ["folder-create"])
        made["role"] = ids["folder-create"]
        folder = made["folder"]
        rec["baseline"] = measure_folder(host, subject, folder._moId, name, si)
        for label, principal, group in cases:
            row = {"case": label}
            if any(str(p.principal).lower() == principal.lower() for p in am.RetrieveEntityPermissions(folder, False)):
                row["skipped"] = "the principal already holds a permission here"
            else:
                am.SetEntityPermissions(folder, [vim.AuthorizationManager.Permission(
                    principal=principal, group=group, roleId=made["role"], propagate=True)])
                time.sleep(3)
                row.update(measure_folder(host, subject, folder._moId, name, si))
                am.RemoveEntityPermission(folder, principal, group)
            rec["cases"].append(row)
        rec["after"] = measure_folder(host, subject, folder._moId, name, si)
    finally:
        with contextlib.suppress(Exception):
            if "folder" in made:
                wait(made["folder"].Destroy_Task())
        view = si.content.viewManager.CreateContainerView(si.content.rootFolder, [vim.Folder], True)
        rec["residue"] = {"folder": any(f.name == name for f in view.view),
                          "grantsOfProbeRoles": probe_role_grants(am)}
        view.Destroy()
        unsoap(si)
    return rec


class TagLab:
    """A throwaway category and tag, attached and detached as a subject, deleted on close."""

    def __init__(self, rest, name, types):
        self.rest, self.name = rest, name
        st, self.cat = rest.call("POST", "/api/cis/tagging/category", {
            "name": name, "description": "authz.py probe (throwaway)", "cardinality": "SINGLE",
            "associable_types": types})
        assert st in (200, 201), f"category create answered {st}"
        st, self.tag = rest.call("POST", "/api/cis/tagging/tag",
                                 {"name": name, "description": "throwaway", "category_id": self.cat})
        assert st in (200, 201), f"tag create answered {st}"

    def path(self):
        return "/api/cis/tagging/tag-association/" + urllib.parse.quote(self.tag, safe="")

    def attached(self):
        st, body = self.rest.call("POST", self.path() + "?action=list-attached-objects")
        return [o.get("id") for o in body or []]

    def try_attach(self, host, subject, obj):
        r = Rest(host, *subject)
        try:
            st, _ = r.call("POST", self.path() + "?action=attach", {"object_id": obj})
            landed = obj["id"] in self.attached()
            out = {"attachStatus": st, "attached": landed}
            if landed:
                r.call("POST", self.path() + "?action=detach", {"object_id": obj})
                if obj["id"] in self.attached():
                    self.rest.call("POST", self.path() + "?action=detach", {"object_id": obj})
                out["detached"] = obj["id"] not in self.attached()
            return out
        finally:
            r.close()

    def close(self):
        self.rest.call("DELETE", "/api/cis/tagging/tag/" + urllib.parse.quote(self.tag, safe=""))
        self.rest.call("DELETE", "/api/cis/tagging/category/" + urllib.parse.quote(self.cat, safe=""))
        st, cats = self.rest.call("GET", "/api/cis/tagging/category")
        return self.cat in (cats or [])


def grant_global(rest, principal, group, role_id, propagate):
    domain, name = principal.split("\\", 1)
    for p in permissions(rest):
        who = p["info"]["principal"]
        if (p["info"]["object"]["type"] == "GlobalAcl" and who["domain"].upper() == domain.upper()
                and who["name"].lower() == name.lower()):
            return None, "skipped: the principal already holds a global permission"
    st, _ = rest.call("POST", "/api/vcenter/authorization/permissions", {
        "object": {"id": "GlobalAcl", "type": "GlobalAcl"},
        "principal": {"domain": domain, "name": name, "type": "GROUP" if group else "USER"},
        "role": str(role_id), "propagating": propagate})
    for p in permissions(rest):
        who = p["info"]["principal"]
        if (p["info"]["object"]["type"] == "GlobalAcl" and who["domain"].upper() == domain.upper()
                and who["name"].lower() == name.lower() and p["info"]["role"] == str(role_id)):
            return p["permission"], f"created {st}"
    return None, f"create answered {st}, not found in the list"


def ungrant_global(rest, permission):
    st, _ = rest.call("DELETE", "/api/vcenter/authorization/permissions/" + urllib.parse.quote(permission, safe=""))
    return st


def probe_tags(host, admin, subject, d, r):
    """Where the two tag privileges must come from, as an identity holding nothing else on this vCenter."""
    from pyVmomi import vim
    name = "authz-run-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    si = soap(host, *admin)
    am = si.content.authorizationManager
    rest = Rest(host, *admin)
    made = {"roles": {}}
    rec = {"cases": []}
    lab = None
    try:
        keys = {"none": "none", "tag": "attach-tag", "object": "tag-on-object", "both": "tag-both"}
        ids, rec["probeRoles"] = ensure_probe_roles(am, list(keys.values()))
        made["roles"] = {k: ids[v] for k, v in keys.items()}
        made["roles"]["Admin"] = -1
        dc = next(e for e in si.content.rootFolder.childEntity if isinstance(e, vim.Datacenter))
        made["folder"] = dc.vmFolder.CreateFolder(name)
        obj = {"id": made["folder"]._moId, "type": "Folder"}
        lab = TagLab(rest, name, ["Folder"])
        # prove the delete path for a global permission before any case, on the realm spelling (inert)
        pid, note = grant_global(rest, r, False, made["roles"]["none"], False)
        rec["globalDeletePath"] = {"created": pid is not None, "deleteStatus": ungrant_global(rest, pid) if pid else None,
                                   "gone": all(p["permission"] != pid for p in permissions(rest))}
        if not rec["globalDeletePath"]["gone"] or pid is None:
            rec["aborted"] = "the global-permission delete path did not prove out"
            return rec
        cases = [
            ("no grant", []),
            ("both privileges on the folder only", [("object", d, "both", True)]),
            ("ObjectAttachable on the folder, AttachTag global, not propagating", [("object", d, "object", True), ("global", d, "tag", False)]),
            ("ObjectAttachable on the folder, AttachTag global, propagating", [("object", d, "object", True), ("global", d, "tag", True)]),
            ("ObjectAttachable on the folder, AttachTag global in the realm spelling", [("object", d, "object", True), ("global", r, "tag", True)]),
            ("both global and propagating", [("global", d, "both", True)]),
            ("both global and propagating, a no-privilege role on the folder", [("global", d, "both", True), ("object", d, "none", True)]),
            ("both global and propagating, Admin on the folder", [("global", d, "both", True), ("object", d, "Admin", True)]),
            ("no grant, after the last removal", []),
        ]
        for label, grants in cases:
            row = {"case": label, "grants": []}
            live_obj, live_global = [], []
            for where, principal, role, propagate in grants:
                if where == "global":
                    pid, note = grant_global(rest, principal, False, made["roles"][role], propagate)
                    row["grants"].append(note)
                    if pid:
                        live_global.append(pid)
                else:
                    if any(str(p.principal).lower() == principal.lower() for p in am.RetrieveEntityPermissions(made["folder"], False)):
                        row["grants"].append("skipped: the principal already holds a permission here")
                        continue
                    am.SetEntityPermissions(made["folder"], [vim.AuthorizationManager.Permission(
                        principal=principal, group=False, roleId=made["roles"][role], propagate=propagate)])
                    live_obj.append(principal)
                    row["grants"].append("created")
            time.sleep(4)
            row.update(lab.try_attach(host, subject, obj))
            for principal in live_obj:
                am.RemoveEntityPermission(made["folder"], principal, False)
            for pid in live_global:
                ungrant_global(rest, pid)
            rec["cases"].append(row)
    finally:
        rec["residue"] = {}
        if lab is not None:
            rec["residue"]["category"] = lab.close()
        if "folder" in made:
            with contextlib.suppress(Exception):
                wait(made["folder"].Destroy_Task())
        rec["residue"]["grantsOfProbeRoles"] = probe_role_grants(am)
        rest.close()
        unsoap(si)
    return rec


def probe_supervisor(host, operator, tag_identity, vm_name, d_op, r_op, L):
    """One Supervisor-managed VM: effective roles, an attach as each identity, and the operator's grant attempts."""
    from pyVmomi import vim
    si = soap(host, *operator)
    am = si.content.authorizationManager
    rest = Rest(host, *operator)
    name = "authz-run-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    made = {}
    rec = {"identities": {}, "grantAttempts": []}
    lab = None
    try:
        view = si.content.viewManager.CreateContainerView(si.content.rootFolder, [vim.VirtualMachine], True)
        found = [v for v in view.view if v.name == vm_name]
        view.Destroy()
        if len(found) != 1:
            raise SystemExit(f"{len(found)} VMs carry that name")
        vm = found[0]
        rec["managedBy"] = vm.config.managedBy.extensionKey if vm.config.managedBy else None
        obj = {"id": vm._moId, "type": "VirtualMachine"}
        lab = TagLab(rest, name, ["VirtualMachine"])
        names = {x.roleId: x.name for x in am.roleList}
        for key, cred in (("operator", operator), ("tag identity", tag_identity)):
            s = soap(host, *cred)
            try:
                v = vim.VirtualMachine(vm._moId, s._stub)
                got = s.content.authorizationManager.HasPrivilegeOnEntity(
                    v, s.content.sessionManager.currentSession.key, [ATTACH, ON_OBJECT, MODIFY])
                eff = [names.get(x, str(x)) for x in (v.effectiveRole or [])]
                rec["identities"][key] = {
                    "effectiveRoles": [x if x in PRODUCT_ROLES else L.get("role", x) for x in eff],
                    "check": {"AttachTag": bool(got[0]), "ObjectAttachable": bool(got[1]), "ModifyPermissions": bool(got[2])},
                    **lab.try_attach(host, cred, obj)}
            finally:
                unsoap(s)
        ids, rec["probeRoles"] = ensure_probe_roles(am, ["tag-on-object-modify"])
        made["role"] = ids["tag-on-object-modify"]
        for label, principal, role in (("ObjectAttachable to itself, directory spelling", d_op, made["role"]),
                                       ("Admin to itself, directory spelling", d_op, -1),
                                       ("ObjectAttachable to itself, realm spelling", r_op, made["role"])):
            row = {"attempt": label}
            if any(str(p.principal).lower() == principal.lower() for p in am.RetrieveEntityPermissions(vm, False)):
                row["result"] = "skipped: the principal already holds a permission on the VM"
            else:
                try:
                    am.SetEntityPermissions(vm, [vim.AuthorizationManager.Permission(
                        principal=principal, group=False, roleId=role, propagate=False)])
                    row["result"] = "accepted"
                    row.update(lab.try_attach(host, operator, obj))
                    am.RemoveEntityPermission(vm, principal, False)
                except vim.fault.NoPermission as e:
                    row["result"] = "refused"
                    row["missingPrivilege"] = str(getattr(e, "privilegeId", "") or "")
            rec["grantAttempts"].append(row)
    finally:
        rec["residue"] = {}
        if lab is not None:
            rec["residue"]["category"] = lab.close()
        rec["residue"]["grantsOfProbeRoles"] = probe_role_grants(am)
        rest.close()
        unsoap(si)
    return rec


# ---------------------------------------------------------------- scrubbing

class Labels:
    def __init__(self):
        self.maps = {}

    def get(self, family, real):
        if not real or real in PRODUCT_ROLES or real in PRODUCT_LOCAL:
            return real
        m = self.maps.setdefault(family, {})
        if real not in m:
            m[real] = f"{family}-{len(m) + 1}"
        return "{{%s}}" % m[real]

    def words(self):
        return [r for m in self.maps.values() for r in m]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--probe-grants", action="store_true")
    ap.add_argument("--probe-tags", action="store_true")
    ap.add_argument("--supervisor-vm", default="")
    ap.add_argument("--remove-probe-roles", action="store_true",
                    help="remove the authz-probe-* roles from every vCenter in VC_HOSTS and report the groups left")
    a = ap.parse_args()

    hosts = [h.strip() for h in os.environ["VC_HOSTS"].split(",") if h.strip()]
    user, password = os.environ["VC_USER"], secret("VC_PASSWORD")
    realm = os.environ.get("REALM_DOMAIN", "").strip()
    directories = [x.strip().lower() for x in os.environ.get("DIRECTORY_DOMAINS", "").split(",") if x.strip()]
    out_dir = os.environ.get("OUT_DIR", os.path.dirname(os.path.abspath(__file__)))
    L = Labels()
    vc_label = {h: L.get("vcenter", h) for h in hosts}

    print("authz.py: vCenter authorization under VCF single sign-on, read the way a broker session reads it\n")
    record = {"captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "vcenters": {}}
    catalogs = {}
    pyv = have_pyvmomi()
    for h in hosts:
        rest = Rest(h, user, password)
        if rest.token is None:
            raise SystemExit("the vSphere Automation API refused the session")
        try:
            row, cat = census(rest, realm, directories)
        finally:
            rest.close()
        catalogs[vc_label[h]] = cat
        if pyv:
            si = soap(h, user, password)
            try:
                row["version"] = f"{si.content.about.version} build {si.content.about.build}"
                row["sessions"] = sessions(si, realm, directories)
            finally:
                unsoap(si)
        else:
            row["sessions"] = "not read: pyVmomi is not installed"
        record["vcenters"][vc_label[h]] = row
        print(f"  {vc_label[h]}: {row['permissions']} permissions ({row['global']} global); {row['byClass']}")
        if isinstance(row["sessions"], dict):
            print(f"     sessions by class {row['sessions']['byClass']}; local administrator by agent "
                  f"{row['sessions']['localAdministratorByAgent']}")
    record["roleDrift"] = drift(catalogs, L)
    if a.remove_probe_roles:
        if not pyv:
            raise SystemExit("removing the probe roles needs pyVmomi")
        record["probeRoleTeardown"] = {}
        for h in hosts:
            si = soap(h, user, password)
            try:
                record["probeRoleTeardown"][vc_label[h]] = remove_probe_roles(si)
            finally:
                unsoap(si)
        print(f"\n  probe roles removed: {record['probeRoleTeardown']}")
    print(f"\n  custom roles whose copies differ between vCenters: {len(record['roleDrift'])}")

    probe_host = os.environ.get("PROBE_VCENTER", hosts[0])
    test_user = os.environ.get("TEST_USER", "")
    subject = (test_user, secret("TEST_PASSWORD"))
    local, _, dom = test_user.partition("@")
    if a.probe_grants or a.probe_tags or a.supervisor_vm:
        if not pyv:
            raise SystemExit("the probes need pyVmomi")
        if not (test_user and realm and dom):
            raise SystemExit("the probes need TEST_USER (user@domain), TEST_PASSWORD_FILE and REALM_DOMAIN")
    d_user, r_user = f"{dom.upper()}\\{local}", f"{realm.upper()}\\{local}"
    if a.probe_grants:
        group = os.environ["TEST_GROUP"]
        cases = [("group, directory spelling", f"{dom.upper()}\\{group}", True),
                 ("user, directory spelling", d_user, False),
                 ("user, realm spelling", r_user, False),
                 ("group, realm spelling", f"{realm.upper()}\\{group}", True)]
        record["grantProbe"] = {"vcenter": vc_label.get(probe_host, L.get("vcenter", probe_host)),
                                **probe_grants(probe_host, (user, password), subject, cases)}
        print(f"\n  grant probe: {[(c['case'], c.get('check'), c.get('enforced')) for c in record['grantProbe']['cases']]}")
    if a.probe_tags:
        record["tagProbe"] = {"vcenter": vc_label.get(probe_host, L.get("vcenter", probe_host)),
                              **probe_tags(probe_host, (user, password), subject, d_user, r_user)}
        print(f"\n  tag probe: {[(c['case'], c.get('attached')) for c in record['tagProbe']['cases']]}")
    if a.supervisor_vm:
        op_local, _, op_dom = user.partition("@")
        sup_host = os.environ.get("SUPERVISOR_VCENTER", probe_host)
        record["supervisorProbe"] = {
            "vcenter": vc_label.get(sup_host, L.get("vcenter", sup_host)),
            **probe_supervisor(sup_host, (user, password), subject, a.supervisor_vm,
                               f"{op_dom.upper()}\\{op_local}", f"{realm.upper()}\\{op_local}", L)}
        print(f"\n  supervisor probe: {json.dumps(record['supervisorProbe']['identities'])}")
        print(f"     grant attempts: {[(g['attempt'], g['result']) for g in record['supervisorProbe']['grantAttempts']]}")

    text = json.dumps(record, indent=1, ensure_ascii=False)
    estate = set(hosts) | {user, local, dom, realm, test_user, os.environ.get("TEST_GROUP", ""), a.supervisor_vm,
                           user.partition("@")[0]} | set(directories) | set(L.words())
    estate |= {h.split(".")[0] for h in hosts}
    for value in sorted({v for v in estate if v and v not in PRODUCT_ROLES | PRODUCT_LOCAL}, key=len, reverse=True):
        if re.search(r"(?<![A-Za-z0-9-])" + re.escape(value) + r"(?![A-Za-z0-9-])", text, re.IGNORECASE):
            shape = re.sub(r"[A-Za-z]", "a", re.sub(r"[0-9]", "9", value))
            raise SystemExit(f"FATAL: an estate value ({len(value)} characters, shape {shape}) reached the record")
    for s in (password, subject[1]):
        assert not s or s not in text, "a password reached the record"
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "authz.json"), "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print("\nwrote authz.json: counts, classes and outcomes, with every estate name replaced")


if __name__ == "__main__":
    sys.exit(main())
