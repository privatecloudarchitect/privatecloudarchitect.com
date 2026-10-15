#!/usr/bin/env python3
"""authz.py: who may do what in vCenter under VCF single sign-on, read the way a broker session reads it.

Once vCenter signs people in through the VCF identity broker, two authorization planes apply at once: the
vCenter's own permissions, and the VCF roles assigned in VCF Operations, which arrive in vCenter as global
permissions on local groups named ``vcf_reserved_<role id>``. A broker session carries the directory's name
for the user (``DOMAIN\\user``), so a permission spelled with the realm's name applied to nobody behind a broker
backed by AD/LDAP (behind a federated provider it was not measured), even though vCenter accepts it and an
administrator's privilege query reports it as effective.

Read-only by default:

  1. GRANTS: every permission on each vCenter, global and per-object, from the vSphere Automation API's list
     action, every page of it, classified by how it behaves for a broker session: reserved group (a VCF role
     arriving); local, split three ways (VCF-managed: svc- and wcp- accounts and solution users, left to VCF;
     Administrators: the local administrator and its group; other: what an operator made, and groups vCenter or
     another product ships under their own names, each read with its members); directory user, directory group,
     realm spelling (inert behind an AD/LDAP provider, not measured behind a federated one), or another provider's;
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
                   fresh sessions of TEST_USER (vCenter's own check, an actual subfolder create, a REST read). With
                   TEST_LOCAL_GROUP set, one more case grants the role to that local SSO group, which you have
                   made to hold TEST_GROUP as a member: does a directory group nested in a local group carry it?
  --probe-tags     on PROBE_VCENTER, where TEST_USER should hold nothing: where the two tag privileges must come
                   from. AttachTag counts only from a global permission that propagates; ObjectAttachable must
                   be in effect on the object. Each case attaches a throwaway tag as TEST_USER and detaches it.
  --supervisor-vm NAME
                   on PROBE_VCENTER: the effective roles and tag privileges of VC_USER and TEST_USER on one
                   Supervisor-managed VM, an attach of a throwaway tag as each, and VC_USER's attempts to grant
                   itself a tag role on the VM (every role it grants itself carries ModifyPermissions, so an
                   accepted grant stays removable). Choose a VM you own.

The realm-spelled grants, named and removed. The census counts them and never names them in the record.
  --where-realm    with the census: each realm-spelled grant's permission id, principal, object, role and scope,
                   printed on your terminal only and never written to the record, so you can name the ones to remove
  --remove ID[,ID...] [--execute]
                   on the one vCenter VC_HOSTS names: the realm-spelled grants with those permission ids. Without
                   --execute it prints each grant and the DELETE it would send, and sends nothing. With --execute it
                   sends one DELETE per id, then reads the permission list again: the run holds when every named id
                   is gone and no other grant moved. It refuses, before anything is sent, an id that is not on that
                   vCenter and an id that is not a realm-spelled grant: any other grant is removed where it was made.
                   It writes no record; what it removed is on the terminal.

Before a realm exists. Run the census before the broker takes the realm, so the grants are inventoried while the
boundary is decided: declare it with --no-realm, and the realm-spelled class is reported as not applicable and nothing
is flagged for it. A run with neither REALM_DOMAIN nor --no-realm is refused (exit 5): left to infer "no realm" from
a variable not set, a run on an estate that has a realm read its realm-spelled grant as another provider's and exited
0 (X-197). Every run prints, on the terminal only, the domains it read as another provider's with their grant counts,
so a misspelled REALM_DOMAIN or directory domain shows there.

A misspelled realm, caught. A misspelled REALM_DOMAIN moves every realm-spelled grant into another provider's class,
where nothing flags it, while the directory domains still name their grants. So with REALM_DOMAIN set, a vCenter on
which the realm names no grant while grants of an unplaced domain are there (a domain in none of DIRECTORY_DOMAINS,
LOCAL_DOMAIN, REALM_DOMAIN and OTHER_DOMAINS) is a failed read: the run prints NOT PLACED with those domains, on the
terminal only, records realmNamedNothing, and exits 3. Name in OTHER_DOMAINS the domains you know are another identity
provider's, and the vCenter is placed (on the reference estate, the workload vCenter that runs a Supervisor held one).

The realm is not the directory domain, refused. The census tests the realm's name before the directory domains and
another provider's, so a REALM_DOMAIN that names a DIRECTORY_DOMAINS or OTHER_DOMAINS entry would class every working
grant in that domain realm-spelled: exit 1 would say to remove them, and --remove would accept their ids. So a
REALM_DOMAIN equal to any of those entries, compared case-insensitively after trimming, is a usage error (exit 5) found
before anything is read, and so is one equal to LOCAL_DOMAIN, where every grant sorts as local first and no grant could
ever read realm-spelled.

Paged lists. The permission and role lists are paged: an answer that carries a marker has more after it, and the next
page is asked for with that marker until an answer carries none. A page refused, or a marker answered twice, is a list
not read (exit 3). A permission list with no permission in it is too: VC_USER, an administrator, holds one.

Environment:
  VC_HOSTS            comma-separated vCenter FQDNs (one, with --remove)
  VC_USER             an administrator of those vCenters, user@domain
  VC_PASSWORD_FILE    a file holding that password (mode 0600); VC_PASSWORD is read if it is not set
  REALM_DOMAIN        the realm's name as vCenter spells it in a grant (VCF Operations, fleet IAM realms); not the
                      broker tenant an API client's session carries (CUSTOMER by default), and never a directory
                      domain: one equal to a DIRECTORY_DOMAINS, OTHER_DOMAINS or LOCAL_DOMAIN entry is refused (exit 5).
                      Required once the estate has a realm, and by --where-realm, --remove and the probes; before a
                      realm, run with --no-realm
  DIRECTORY_DOMAINS   required: comma-separated directory domains under the broker's identity provider (or, before
                      the realm, the vCenter's own directory identity sources). Unset, every directory grant reads as
                      another provider's and the census would count none, so the script refuses to start without it
  LOCAL_DOMAIN        the vCenter's own SSO domain (default VSPHERE.LOCAL); set it where yours is named otherwise,
                      or every local grant reads as another provider's
  OTHER_DOMAINS       optional: comma-separated domains you know are another identity provider's. Their grants stay
                      in another provider's class and count as placed, so neither NOT PLACED check stops on them
  TLS_VERIFY          false only on a self-signed lab CA
  TEST_USER, TEST_PASSWORD_FILE, TEST_GROUP, PROBE_VCENTER   for the probes (TEST_USER must not be an administrator)
  TEST_LOCAL_GROUP    optional: a local SSO group holding TEST_GROUP, for the nested case of --probe-grants
  SUPERVISOR_VCENTER  the vCenter for --supervisor-vm (default PROBE_VCENTER)
  OUT_DIR             where authz.json is written (default: this folder)

Run:  python3 authz.py [--where-realm] [--probe-grants] [--probe-tags] [--supervisor-vm NAME]
      python3 authz.py --remove ID[,ID...] [--execute]
      Python 3.10 or later.
Exit, the first that applies, so a scheduler reads one state from one number:
      2 a removal (--remove --execute) that did not hold on read-back: a named grant still there, or another grant
        moved; or a probe that left residue (its folder, its tag category, or a grant of a probe role)
      1 the census read realm-spelled grants: remove them (--where-realm names them, --remove removes them). Only
        with REALM_DOMAIN set; before a realm there is no such class
      3 a read failed or a result is undetermined: a vCenter refused the session or a page of the permission or role
        list, a permission list with no permission in it, the session list could not be read, a vCenter on which
        DIRECTORY_DOMAINS (and REALM_DOMAIN, when set) name no grant while another provider's grants are there, a vCenter on which REALM_DOMAIN names no grant while grants
        of a domain in none of the domains given are there (a misspelled realm hides its grants there), a probe that
        could not run its cases, or an error the script did not expect. Nothing is known about what was not read
      0 nothing for a person to act on: every vCenter read and placed, no realm-spelled grant, every probe clean
        (with --remove: the plan printed, or every named grant removed and nothing else moved)
      5 a usage error, before anything is read: an argument or environment variable missing or wrong, a REALM_DOMAIN
        that names a DIRECTORY_DOMAINS, OTHER_DOMAINS or LOCAL_DOMAIN entry, an id --remove cannot name as a
        realm-spelled grant on that vCenter, pyVmomi missing for a step that needs it, a Python older than 3.10; or the
        record refused because an estate value survived the scrub (nothing is written)
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
# The local principals VCF keeps for itself: its integration accounts (svc-), the Supervisor's (wcp-) and the solution
# users, named with a UUID at the end (nsxt_<uuid> among them). The census sorts by name, so an account an operator
# named svc- lands here too. vCenter's own administrator and Administrators group are a class of their own. Every other
# local principal, a group or user an operator made or a group vCenter or another product ships under its own name, is
# read rather than left: a directory group nested in a local group may carry that group's grants.
VCF_MANAGED = re.compile(r"^(svc-|wcp-)|[-_][0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)
LOCAL_CLASSES = ("local, VCF-managed", "local, Administrators", "local, other")

# The platform's own vocabulary: system roles, the roles the Supervisor grants, the local groups vCenter ships.
# A word in this set identifies no estate, so it is never replaced, and the leak check never fires on it.
PRODUCT_ROLES = {
    "Admin", "ReadOnly", "View", "Anonymous", "NoAccess", "NoCryptoAdmin", "TrustedAdmin", "NoTrustedAdmin",
    "VM-Service-VM-Management", "NamespacesEdit", "NamespacesView", "NamespacesOwner",
    "SupervisorAdministrator", "vSpherePodAdministrator", "VMOperatorController", "ObservabilityOperator",
}
PRODUCT_LOCAL = {"Administrator", "Administrators"}

# The exit codes, one state each (the docstring's table).
EXIT_OK, EXIT_REALM, EXIT_NOT_HELD, EXIT_UNREAD, EXIT_USAGE = 0, 1, 2, 3, 5
NO_REALM = "not applicable: --no-realm, an estate with no realm yet"


class ReadError(Exception):
    """A read or a step the run needed did not answer: the result is undetermined (exit 3)."""


class UsageError(Exception):
    """An argument or environment variable the run cannot work with, found before anything is changed (exit 5)."""


class _Parser(argparse.ArgumentParser):
    """argparse with its usage errors on exit 5, the code for a usage error, not argparse's own 2."""

    def error(self, message):
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        raise SystemExit(EXIT_USAGE)


# ---------------------------------------------------------------- plumbing

def ctx():
    verify = os.environ.get("TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")
    return ssl.create_default_context() if verify else ssl._create_unverified_context()


def secret(name):
    """NAME_FILE's content, or NAME itself. A file named but unreadable is a usage error (exit 5), never a read that
    failed: nothing has been sent when it is read."""
    path = os.environ.get(name + "_FILE")
    if path:
        try:
            with open(path, encoding="utf-8") as f:
                return f.read().strip()
        except (OSError, UnicodeDecodeError) as e:
            raise UsageError(f"{name}_FILE could not be read: {type(e).__name__}") from None
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
                status = r.status
        except urllib.error.HTTPError as e:
            return e.code, None
        except (urllib.error.URLError, OSError):
            return None, None
        try:
            return status, (json.loads(raw) if raw else None)
        except ValueError:  # an answer that is not JSON carries nothing the read needs: the caller reads it as unread
            return status, None

    def close(self):
        if self.token:
            self.call("DELETE", "/api/session")
            self.token = None


# The page size the lists are asked for. None sends no iteration, and vCenter returns "only the first ... that fit in a
# size defined by the service" (the API's own metadata); a size set here may be lowered by a service policy. Either way
# every page is read; 1 proves it.
PAGE_SIZE = None


def pages(what, ask):
    """Every item of a paged vSphere Automation list. ``ask(marker)`` sends one request and returns its status and
    body. An answer whose ``marker`` is set has more items after it, and the next page is asked for with that marker;
    an answer with no marker has returned the last of them. A page refused, an answer without its items list, or a
    marker that is not a string or was answered before, is a list not read (ReadError, exit 3)."""
    out, marker, seen = [], None, set()
    while True:
        st, body = ask(marker)
        page = f" on page {len(seen) + 1}" if seen else ""
        if st != 200 or not isinstance(body, dict) or not isinstance(body.get("items"), list):
            raise ReadError(f"the {what} list answered {st}{page}")
        out += body["items"]
        marker = body.get("marker")
        if marker is None or marker == "":
            return out
        if not isinstance(marker, str) or marker in seen:
            raise ReadError(f"the {what} list answered a marker it had answered before, or one that is not a string, "
                            f"on page {len(seen) + 1}")
        seen.add(marker)


def permissions(rest, page_size=None):
    """Every permission, global and per-object, every page. A GET on the collection answers 404 on vCenter 9.1; the
    list is the action=list POST, and global ones carry object type GlobalAcl. The page size and the marker go in the
    body's ``iterate``. A list with no permission in it read nothing: VC_USER, an administrator, holds one."""
    size = PAGE_SIZE if page_size is None else page_size

    def ask(marker):
        it = {k: v for k, v in (("page_size", size), ("marker", marker)) if v}
        return rest.call("POST", "/api/vcenter/authorization/permissions?action=list", {"iterate": it} if it else {})

    items = pages("permission", ask)
    if not items:
        raise ReadError("the permission list answered with no permission in it, though the administrator that read it "
                        "holds one")
    return items


def roles(rest, page_size=None):
    """The role catalog, every page: the page size and the marker go in the query."""
    size = PAGE_SIZE if page_size is None else page_size

    def ask(marker):
        query = urllib.parse.urlencode([(k, v) for k, v in (("page_size", size), ("marker", marker)) if v])
        return rest.call("GET", "/api/vcenter/authorization/roles" + (f"?{query}" if query else ""))

    return {str(i["role"]): i["info"] for i in pages("role", ask)}


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

def local_domain():
    return (os.environ.get("LOCAL_DOMAIN") or "VSPHERE.LOCAL").strip().upper()


def classify(domain, name, realm, directories, local=None):
    """One principal's class, by how it behaves for a broker session and who looks after it. A local principal is
    reserved (a VCF role arriving), VCF-managed (leave it), Administrators (the administrator and its group: read the
    members), or other (read it, members included)."""
    d = domain.upper()
    if d == (local or local_domain()).upper():
        if name.startswith(RESERVED_PREFIX):
            return "reserved group"
        if VCF_MANAGED.search(name):
            return LOCAL_CLASSES[0]
        return LOCAL_CLASSES[1] if name.lower() in {p.lower() for p in PRODUCT_LOCAL} else LOCAL_CLASSES[2]
    if realm and d == realm.upper():
        return "realm spelling"
    if d.lower() in directories:
        return "directory"
    return "another provider"


def names_nothing(by_class):
    """Whether neither the realm's name nor a directory domain names a grant on a vCenter whose list holds another
    provider's grants: a misspelled domain hides its grants there, as VCF Automation's own grants sit there anyway."""
    kinds = {k.rsplit(", ", 1)[0] for k in by_class}
    return "another provider" in kinds and not kinds & {"directory", "realm spelling"}


def census(rest, realm, directories, perms=None, cat=None):
    """Every grant counted by class and scope, with the role catalog. The lists are read here unless the caller
    has read them already; no principal is named."""
    perms = permissions(rest) if perms is None else perms
    cat = roles(rest) if cat is None else cat
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


def other_domains_declared():
    """OTHER_DOMAINS, lower-cased: the domains the reader knows are another identity provider's."""
    return {x.strip().lower() for x in os.environ.get("OTHER_DOMAINS", "").split(",") if x.strip()}


REALM_IS = "REALM_DOMAIN is the realm's name as vCenter spells it in a grant (VCF Operations, fleet IAM realms)"


def realm_overlap(realm, directories, others=(), local=""):
    """Why REALM_DOMAIN cannot be read, when it names a domain the run was given as something else; else None.
    classify() tests the realm before a directory domain or another provider's, so a realm typed as one of them would
    class every working grant in it realm-spelled: exit 1 would say to remove them and --remove would accept their
    ids. The local domain is tested first, so a realm typed as it could never class a grant realm-spelled. Compared
    case-insensitively after trimming; ``local`` empty is VSPHERE.LOCAL, the default."""
    r = (realm or "").strip()
    if not r:
        return None
    for var, entry in [("DIRECTORY_DOMAINS", d) for d in directories] + [("OTHER_DOMAINS", d) for d in others]:
        if entry.strip().lower() == r.lower():
            what = ("a directory domain is the one your directory spells its users and groups in, DOMAIN\\user, which a "
                    "broker session carries" if var == "DIRECTORY_DOMAINS"
                    else "OTHER_DOMAINS names the domains you know are another identity provider's")
            return (f"REALM_DOMAIN ({r}) and {var} ({entry.strip()}) name the same domain. {REALM_IS}; {what}. Read as "
                    "one, every working grant in that domain would be classed realm-spelled and named for removal. Set "
                    "REALM_DOMAIN to the realm's name")
    lo = (local or "").strip()
    if r.lower() == (lo or "VSPHERE.LOCAL").lower():
        return (f"REALM_DOMAIN ({r}) and LOCAL_DOMAIN ({lo or 'VSPHERE.LOCAL, the default'}) name the same domain. "
                f"{REALM_IS}; LOCAL_DOMAIN is the vCenter's own SSO domain. Read as one, every grant in that domain sorts "
                "as local and no realm-spelled grant could be found. Set REALM_DOMAIN to the realm's name")
    return None


def unplaced(others, declared):
    """Of the domains read as another provider's (domain to grant count), the ones OTHER_DOMAINS does not name."""
    return {d: n for d, n in others.items() if d.lower() not in declared}


def realm_names_nothing(by_class, realm, undeclared):
    """Whether REALM_DOMAIN is set, names no grant on a vCenter, and grants of an unplaced domain are there: a
    misspelled realm's grants would sit among them, unflagged, while the directory domains still name theirs. A
    correct realm on a vCenter with no realm-spelled grant and no unplaced domain is never this (G-410's other half)."""
    kinds = {k.rsplit(", ", 1)[0] for k in by_class}
    return bool(realm) and "realm spelling" not in kinds and bool(undeclared)


def other_domains(perms, realm, directories):
    """The domains whose grants read as another provider's, with their counts: printed on the terminal only, so a
    misspelled REALM_DOMAIN or directory domain shows among them. A domain is an estate value; the record never
    carries this."""
    out = collections.Counter()
    for p in perms:
        who = p["info"]["principal"]
        if classify(who["domain"], who["name"], realm, directories) == "another provider":
            out[who["domain"]] += 1
    return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0].lower())))


def realm_grants(perms, realm, directories):
    """The realm-spelled grants, each with its permission id: the ones --where-realm names and --remove may remove.
    Empty without a realm."""
    if not realm:
        return []
    return [p for p in perms
            if classify(p["info"]["principal"]["domain"], p["info"]["principal"]["name"], realm, directories)
            == "realm spelling"]


def grant_line(p, cat):
    """One grant as the terminal shows it: its id, principal, object, role and scope. Never recorded."""
    info, who = p["info"], p["info"]["principal"]
    role = cat.get(str(info["role"]), {}).get("name") or str(info["role"])
    scope = "global" if info["object"]["type"] == "GlobalAcl" else "object"
    return (f"permission {p['permission']}: {who['domain']}\\{who['name']} ({who.get('type', '?')}) on "
            f"{info['object']['type']} {info['object']['id']}, role {role}, {scope}, "
            f"{'propagating' if info.get('propagating') else 'not propagating'}")


def grant_key(p):
    """What makes a grant the same grant on a second read: its id and every field it carries."""
    info, who = p["info"], p["info"]["principal"]
    return (str(p.get("permission")), str(who.get("domain", "")).upper(), str(who.get("name", "")).lower(),
            str(who.get("type", "")), info["object"]["type"], str(info["object"]["id"]), str(info["role"]),
            bool(info.get("propagating")))


def removal_plan(perms, ids, realm, directories):
    """The grants --remove would delete, by id, or the reason it refuses (a usage error: nothing is sent). An id
    that is not on the vCenter, and an id that is not a realm-spelled grant, are refused: this script removes only
    the class it exists to clean up. A realm that names a directory, another provider's or the local domain is refused
    first: read as the realm, that domain's working grants would pass as realm-spelled."""
    problem = realm_overlap(realm, directories, sorted(other_domains_declared()), os.environ.get("LOCAL_DOMAIN", ""))
    if problem:
        return None, problem
    by_id = {str(p.get("permission")): p for p in perms}
    unknown = [i for i in ids if i not in by_id]
    if unknown:
        return None, f"no grant on this vCenter has the id {', '.join(unknown)}; read the ids with --where-realm"
    realm_ids = {str(p.get("permission")) for p in realm_grants(perms, realm, directories)}
    other = [i for i in ids if i not in realm_ids]
    if other:
        return None, (f"{', '.join(other)} {'is' if len(other) == 1 else 'are'} not a realm-spelled grant; this script "
                      "removes only those, and any other grant is removed where it was made")
    return [by_id[i] for i in ids], None


def remove_grants(rest, ids, before):
    """Send one DELETE per id, read the list back, and say whether the removal held: every named id gone, and every
    other grant as it was."""
    others_before = {str(p.get("permission")): grant_key(p) for p in before if str(p.get("permission")) not in ids}
    sent = []
    for i in ids:
        st, _ = rest.call("DELETE", "/api/vcenter/authorization/permissions/" + urllib.parse.quote(i, safe=""))
        sent.append({"id": i, "status": st})
    after = permissions(rest)
    left = sorted({str(p.get("permission")) for p in after} & set(ids))
    others_after = {str(p.get("permission")): grant_key(p) for p in after if str(p.get("permission")) not in ids}
    moved = sum(1 for k in set(others_before) | set(others_after) if others_before.get(k) != others_after.get(k))
    return {"sent": sent, "still_there": left, "other_grants_moved": moved, "held": not left and moved == 0}


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
        if domain.upper() == local_domain() and name == "Administrator":
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
            domain=local_domain(), searchStr=f"{RESERVED_PREFIX}{rid}", belongsToGroup=None, belongsToUser=None,
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
        if st not in (200, 201):
            raise ReadError(f"the probe's tag category create answered {st}")
        st, self.tag = rest.call("POST", "/api/cis/tagging/tag",
                                 {"name": name, "description": "throwaway", "category_id": self.cat})
        if st not in (200, 201):
            rest.call("DELETE", "/api/cis/tagging/category/" + urllib.parse.quote(self.cat, safe=""))
            raise ReadError(f"the probe's tag create answered {st}; its category was deleted")

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
        # prove the delete path for a global permission before any case, on the realm spelling (inert behind AD/LDAP)
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
            raise UsageError(f"--supervisor-vm names {len(found)} VMs on that vCenter, not one")
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


def _hosts():
    return [h.strip() for h in os.environ.get("VC_HOSTS", "").split(",") if h.strip()]


def _ids(values):
    """The permission ids --remove names, from one or more comma-separated values, in order and once each."""
    out = []
    for v in values or []:
        for i in v.split(","):
            if i.strip() and i.strip() not in out:
                out.append(i.strip())
    return out


def _parser():
    ap = _Parser(description=__doc__.split("\n")[0])
    ap.add_argument("--probe-grants", action="store_true")
    ap.add_argument("--probe-tags", action="store_true")
    ap.add_argument("--supervisor-vm", default="")
    ap.add_argument("--remove-probe-roles", action="store_true",
                    help="remove the authz-probe-* roles from every vCenter in VC_HOSTS and report the groups left")
    ap.add_argument("--no-realm", action="store_true",
                    help="declare an estate with no realm yet; without it, REALM_DOMAIN is required")
    ap.add_argument("--where-realm", action="store_true",
                    help="with the census: print each realm-spelled grant's id, principal, object, role and scope on "
                         "the terminal only, never in the record")
    ap.add_argument("--remove", action="append", metavar="ID[,ID...]",
                    help="the realm-spelled grants to remove, by permission id, on the one vCenter VC_HOSTS names; "
                         "plan only without --execute")
    ap.add_argument("--execute", action="store_true", help="with --remove: send the DELETEs and read the list back")
    return ap


def main(argv=None):
    """The run, with two guards around it: a Python older than 3.10 is refused (exit 5) before anything is read, and
    an error the script did not expect exits 3, the code for a read that failed, never 1, the code for a finding."""
    if sys.version_info < (3, 10):  # noqa: UP036  the script is run by readers on their own Python
        print("authz.py needs Python 3.10 or later", file=sys.stderr)
        return EXIT_USAGE
    try:
        return _run(argv)
    except SystemExit as e:  # argparse: --help exits 0, a usage error exits 5 through _Parser.error
        return e.code if isinstance(e.code, int) else EXIT_USAGE
    except UsageError as e:
        print(f"{e} (exit 5)", file=sys.stderr)
        return EXIT_USAGE
    except Exception as e:  # the last guard: whatever was not expected is not known, so exit 3
        print(f"the run stopped on an error it did not expect: {type(e).__name__}: {str(e)[:160]}; nothing is known "
              "about what it had not read (exit 3)", file=sys.stderr)
        return EXIT_UNREAD


def _settings(a):
    """The environment the run reads, checked before anything is read: a usage error raises UsageError."""
    hosts = _hosts()
    user, password = os.environ.get("VC_USER", "").strip(), secret("VC_PASSWORD")
    realm = os.environ.get("REALM_DOMAIN", "").strip()
    given = [x.strip() for x in os.environ.get("DIRECTORY_DOMAINS", "").split(",") if x.strip()]
    directories = [x.lower() for x in given]
    if not hosts or not user or not password:
        raise UsageError("VC_HOSTS, VC_USER and VC_PASSWORD_FILE (or VC_PASSWORD) are required")
    if not directories:
        raise UsageError("DIRECTORY_DOMAINS is required: without it every directory grant reads as another provider's, "
                         "and the census would count none of them")
    if realm and a.no_realm:
        raise UsageError("REALM_DOMAIN and --no-realm contradict each other: set the one that is true of the estate")
    if not realm and not a.no_realm:
        raise UsageError("REALM_DOMAIN is required, or --no-realm to declare an estate with no realm yet: left to infer "
                         "it from a variable not set, a realm-spelled grant reads as another provider's (X-197)")
    others = [x.strip() for x in os.environ.get("OTHER_DOMAINS", "").split(",") if x.strip()]
    overlap = realm_overlap(realm, given, others, os.environ.get("LOCAL_DOMAIN", ""))
    if overlap:
        raise UsageError(overlap)
    removing = bool(a.remove)
    if a.execute and not removing:
        raise UsageError("--execute goes with --remove; the census and the probes take no --execute")
    if removing and (a.where_realm or a.probe_grants or a.probe_tags or a.supervisor_vm or a.remove_probe_roles):
        raise UsageError("--remove is a run of its own: it takes only --execute")
    if removing and len(hosts) != 1:
        raise UsageError("--remove acts on one vCenter: set VC_HOSTS to the one whose grant ids you name")
    if removing and not _ids(a.remove):
        raise UsageError("--remove takes one or more permission ids")
    if (removing or a.where_realm) and not realm:
        raise UsageError("--where-realm and --remove name realm-spelled grants, so they need REALM_DOMAIN, the "
                         "realm's name as vCenter spells it")
    probing = a.probe_grants or a.probe_tags or a.supervisor_vm
    test_user = os.environ.get("TEST_USER", "")
    if (probing or a.remove_probe_roles) and not have_pyvmomi():
        raise UsageError("the probes and --remove-probe-roles need pyVmomi")
    if probing:
        local, _, dom = test_user.partition("@")
        if not (local and dom and realm and secret("TEST_PASSWORD")):
            raise UsageError("the probes need TEST_USER (user@domain), TEST_PASSWORD_FILE and REALM_DOMAIN")
        if a.probe_grants and not os.environ.get("TEST_GROUP", "").strip():
            raise UsageError("--probe-grants needs TEST_GROUP, a directory group TEST_USER is in")
    return hosts, user, password, realm, directories


def _run(argv=None):
    a = _parser().parse_args(argv)
    hosts, user, password, realm, directories = _settings(a)
    if a.remove:
        return _remove(hosts[0], user, password, realm, directories, _ids(a.remove), a.execute)
    out_dir = os.environ.get("OUT_DIR", os.path.dirname(os.path.abspath(__file__)))
    L = Labels()
    vc_label = {h: L.get("vcenter", h) for h in hosts}

    print("authz.py: vCenter authorization under VCF single sign-on, read the way a broker session reads it\n")
    if not realm:
        print("  --no-realm: an estate with no realm yet, so the realm-spelled class is not applicable.\n")
    record = {"captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "vcenters": {}}
    if not realm:
        record["realmSpelling"] = NO_REALM
    catalogs = {}
    pyv = have_pyvmomi()
    unread = []
    declared = other_domains_declared()
    for h in hosts:
        label = vc_label[h]
        rest = Rest(h, user, password)
        if rest.token is None:
            record["vcenters"][label] = {"error": "the vSphere Automation API refused the session"}
            unread.append(label)
            print(f"  {label}: NOT READ: the vSphere Automation API refused the session")
            continue
        try:
            perms, cat = permissions(rest), roles(rest)
            row, cat = census(rest, realm, directories, perms, cat)
        except ReadError as e:
            record["vcenters"][label] = {"error": str(e)}
            unread.append(label)
            print(f"  {label}: NOT READ: {e}")
            continue
        finally:
            rest.close()
        catalogs[label] = cat
        if pyv:
            try:
                si = soap(h, user, password)
            except Exception as e:  # the session read is part of the census: a refusal is a read that failed
                row["sessions"] = {"error": f"the session list was not read: {type(e).__name__}"}
                si = None
            if si is not None:
                try:
                    row["version"] = f"{si.content.about.version} build {si.content.about.build}"
                    row["sessions"] = sessions(si, realm, directories)
                finally:
                    unsoap(si)
        else:
            row["sessions"] = "not read: pyVmomi is not installed"
        others = other_domains(perms, realm, directories)
        undeclared = unplaced(others, declared)
        if names_nothing(row["byClass"]) and undeclared:
            row["domainsNamedNothing"] = True
        elif realm_names_nothing(row["byClass"], realm, undeclared):
            row["realmNamedNothing"] = True
        record["vcenters"][label] = row
        print(f"  {label}: {row['permissions']} permissions ({row['global']} global); {row['byClass']}")
        if row.get("domainsNamedNothing"):
            print("     NOT PLACED: " + ("REALM_DOMAIN and DIRECTORY_DOMAINS name" if realm else "DIRECTORY_DOMAINS names")
                  + " no grant here while grants of another provider are there; check the spelling against the "
                    "vCenter's own before reading the census (exit 3)")
        if row.get("realmNamedNothing"):
            print("     NOT PLACED: REALM_DOMAIN names no grant here while grants of a domain none of the domains given "
                  "places are there (printed here only, never recorded): "
                  + ", ".join(f"{d} {n}" for d, n in undeclared.items())
                  + ". A misspelled realm hides its grants among them: check REALM_DOMAIN against the realm's name, and "
                    "name each domain you know is another provider's in OTHER_DOMAINS (exit 3)")
        if others:
            print("     read as another provider's (printed here only, never recorded): "
                  + ", ".join(f"{d} {n}" for d, n in others.items()))
        if not realm:
            print(f"     realm spelling: {NO_REALM}")
        if a.where_realm:
            found = realm_grants(perms, realm, directories)
            print(f"     realm-spelled grants (printed here only, never recorded): {len(found) or 'none'}")
            for p in found:
                print(f"       {grant_line(p, cat)}")
        if isinstance(row["sessions"], dict) and "error" in row["sessions"]:
            print(f"     sessions NOT READ: {row['sessions']['error']}")
        elif isinstance(row["sessions"], dict):
            print(f"     sessions by class {row['sessions']['byClass']}; local administrator by agent "
                  f"{row['sessions']['localAdministratorByAgent']}")
    record["roleDrift"] = drift(catalogs, L)
    if a.remove_probe_roles:
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
    d_user, r_user = f"{dom.upper()}\\{local}", f"{realm.upper()}\\{local}"
    if a.probe_grants:
        group = os.environ["TEST_GROUP"]
        cases = [("group, directory spelling", f"{dom.upper()}\\{group}", True),
                 ("user, directory spelling", d_user, False),
                 ("user, realm spelling", r_user, False),
                 ("group, realm spelling", f"{realm.upper()}\\{group}", True)]
        nested = os.environ.get("TEST_LOCAL_GROUP", "").strip()
        if nested:
            cases.append(("group, nested in a local SSO group", f"{local_domain()}\\{nested}", True))
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

    record["exit"] = code = exit_code(record, realm)
    text = json.dumps(record, indent=1, ensure_ascii=False)
    estate = set(hosts) | {user, local, dom, realm, test_user, os.environ.get("TEST_GROUP", ""), a.supervisor_vm,
                           os.environ.get("TEST_LOCAL_GROUP", ""),
                           user.partition("@")[0]} | set(directories) | declared | set(L.words())
    estate |= {h.split(".")[0] for h in hosts}
    for value in sorted({v for v in estate if v and v not in PRODUCT_ROLES | PRODUCT_LOCAL}, key=len, reverse=True):
        if re.search(r"(?<![A-Za-z0-9-])" + re.escape(value) + r"(?![A-Za-z0-9-])", text, re.IGNORECASE):
            shape = re.sub(r"[A-Za-z]", "a", re.sub(r"[0-9]", "9", value))
            print(f"refusing to write authz.json: an estate value ({len(value)} characters, shape {shape}) reached the "
                  "record; nothing is written (exit 5)", file=sys.stderr)
            return EXIT_USAGE
    if any(s and s in text for s in (password, subject[1])):
        print("refusing to write authz.json: a password reached the record; nothing is written (exit 5)", file=sys.stderr)
        return EXIT_USAGE
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "authz.json"), "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print("\nwrote authz.json: counts, classes and outcomes, with every estate name replaced")
    if unread:
        print(f"NOT READ: {len(unread)} vCenter(s); nothing is known about their grants")
    print(f"exit {code}")
    return code


def probe_residue(rec):
    """Whether a probe left something behind: its folder, its tag category, or a grant of a probe role."""
    res = (rec or {}).get("residue") or {}
    return bool(res.get("folder") or res.get("category") or res.get("grantsOfProbeRoles"))


def exit_code(record, realm):
    """The first that applies: 2 a probe left residue, 1 realm-spelled grants read (only with a realm), 3 a vCenter
    or its session list not read, a vCenter whose domains named no grant or whose realm named none beside an unplaced
    domain, or a probe that could not run; else 0."""
    probes = [record.get(k) for k in ("grantProbe", "tagProbe", "supervisorProbe") if record.get(k) is not None]
    if any(probe_residue(p) for p in probes):
        return EXIT_NOT_HELD
    rows = list((record.get("vcenters") or {}).values())
    if realm and any(n for r in rows for k, n in (r.get("byClass") or {}).items() if k.startswith("realm spelling")):
        return EXIT_REALM
    unread = (not rows or any("error" in r for r in rows)
              or any(r.get("domainsNamedNothing") or r.get("realmNamedNothing") for r in rows)
              or any(isinstance(r.get("sessions"), dict) and "error" in r["sessions"] for r in rows)
              or any(p.get("aborted") for p in probes))
    return EXIT_UNREAD if unread else EXIT_OK


def _remove(host, user, password, realm, directories, ids, execute):
    """--remove: plan, or with --execute send, one DELETE per named realm-spelled grant on one vCenter, then read the
    list back. Writes no record; every line is on the terminal."""
    rest = Rest(host, user, password)
    if rest.token is None:
        print(f"{host}: NOT READ: the vSphere Automation API refused the session (exit 3)", file=sys.stderr)
        return EXIT_UNREAD
    try:
        try:
            before, cat = permissions(rest), roles(rest)
        except ReadError as e:
            print(f"{host}: NOT READ: {e} (exit 3)", file=sys.stderr)
            return EXIT_UNREAD
        plan, problem = removal_plan(before, ids, realm, directories)
        if problem:
            print(f"refused, nothing sent: {problem} (exit 5)", file=sys.stderr)
            return EXIT_USAGE
        print(f"authz.py --remove on {host}: {len(plan)} realm-spelled grant(s), printed here only")
        for p in plan:
            print(f"  {grant_line(p, cat)}")
            print(f"    DELETE /api/vcenter/authorization/permissions/{p['permission']}")
        if not execute:
            print("\nplan only: nothing was sent (--execute sends it)\nexit 0")
            return EXIT_OK
        try:
            result = remove_grants(rest, ids, before)
        except ReadError as e:
            print(f"the DELETEs were sent and the list could not be read back: {e}; nothing is known of what they did "
                  "(exit 3)", file=sys.stderr)
            return EXIT_UNREAD
    finally:
        rest.close()
    for s in result["sent"]:
        print(f"  DELETE {s['id']}: HTTP {s['status']}")
    print(f"read back: {len(ids) - len(result['still_there'])} of {len(ids)} named grant(s) gone"
          + (f"; still there: {', '.join(result['still_there'])}" if result["still_there"] else "")
          + f"; other grants moved: {result['other_grants_moved']}")
    code = EXIT_OK if result["held"] else EXIT_NOT_HELD
    print(("held: every named grant is gone and no other grant moved" if result["held"]
           else "NOT HELD: read the list again before anything else") + f"\nexit {code}")
    return code


if __name__ == "__main__":
    sys.exit(main())
