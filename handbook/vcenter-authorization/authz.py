#!/usr/bin/env python3
"""authz.py: who may do what in vCenter under VCF single sign-on, read the way a broker session reads it.

On the vCenters read, already joined to the VCF identity broker, two authorization planes applied side by side: the
vCenter's own permissions, and the VCF roles assigned in VCF Operations, which arrive in vCenter as global
permissions on local groups named ``vcf_reserved_<role id>`` (the join itself was not tested, so take this census
before a join and prove a sample with sign-ins after it). A broker session carries the directory's name
for the user (``DOMAIN\\user``), so a permission spelled with the realm's name applied to nobody behind a broker
backed by AD/LDAP (behind a federated provider it was not measured), even though vCenter accepts it and an
administrator's privilege query reports it as effective.

Read-only by default:

  1. GRANTS: every permission on each vCenter, global and per-object, from the vSphere Automation API's list
     action, every page of it, classified by how it behaves for a broker session: reserved group (a VCF role
     arriving); local, split three ways (VCF-managed: svc- and wcp- accounts and solution users, left to VCF;
     Administrators: the local administrator and its group; other: what an operator made, and groups vCenter or
     another product ships under their own names, each read with its members); directory user, directory group,
     realm spelling (inert behind an AD/LDAP provider, not measured behind a federated one), an API client's (the
     broker tenant's spelling: an integration's own access, never removed here), or another provider's;
  2. ROLES: the role catalog, and the custom roles whose copies differ between vCenters;
  3. SESSIONS (pyVmomi): who is signed in now, by principal class and client agent, from a list read whole (one
     that does not hold the reading session, or holds nothing but the reader's own sessions, is not). Addresses,
     session keys and login times are never read into the record. With REALM_DOMAIN set the session read is part of
     the judgment, so a run without pyVmomi exits 3; before a realm (--no-realm) it is optional.

Opt-in probes. Each creates its own throwaway objects (a folder, a tag category and tag), removes each grant it
makes in a ``finally`` the moment its case ends, removes its objects, and reads the vCenter back for residue: the
folder, the category, any grant it made on the Supervisor VM, and every grant of a probe role; a residue read that
does not answer is not a clean run (exit 3). A probe that meets an error it did not expect stops there: its removals
still run, its residue is still read back and recorded (``stopped``), any probe after it is not run, and the run
exits 2 for residue or 3. None replaces an existing permission: vSphere keeps one permission per principal per
object, so a principal that already holds one where a case would add one is skipped and recorded as skipped. A probe
sends nothing while a probe role is already granted to someone other than its own reserved group (exit 2). All need
pyVmomi.

The probes' roles are not throwaway. On a vCenter joined to VCF single sign-on, VCF creates a local group
``vcf_reserved_<role id>`` for every role created there, and deleting the role leaves the group behind, so a
probe that created and deleted its roles on every run would leave one empty group per role per run. The
probes use six roles named ``authz-probe-<what it holds>``, created the first time they are needed, reconciled
to their declared privileges on every run, and granted only on the probe's own objects for the length of a
case. A probe role is one of those six names, matched whole, and its own reserved group is
``vcf_reserved_<that role's id>`` in the local domain, matched whole: a role an operator named with the same prefix,
another role's reserved group, and a directory group of that name are never taken for them. ``--remove-probe-roles``
removes the six and reports the reserved groups VCF leaves; removing those takes the vCenter's SSO administrator. A
role removed takes every grant of it along, so it refuses, with nothing sent, while a probe role is granted to anyone
but its own reserved group, and reads the role list back after (exit 2 for either). It works one vCenter at a time and
prints each one's result as it is done, so a run that stops shows which were done; a vCenter it could not finish is
recorded with what it removed before the error (exit 3).

  --probe-grants   on PROBE_VCENTER: a one-privilege role (Folder.Create) on a throwaway folder, granted in turn
                   to TEST_USER and to TEST_GROUP, each in the directory and the realm spelling, measured from
                   fresh sessions of TEST_USER (vCenter's own check, an actual subfolder create, a REST read). With
                   TEST_LOCAL_GROUP set, one more case grants the role to that local SSO group, which you have
                   made to hold TEST_GROUP as a member: does a directory group nested in a local group carry it?
  --probe-tags     on PROBE_VCENTER, where TEST_USER should hold nothing: where the two tag privileges must come
                   from. AttachTag counts only from a global permission that propagates; ObjectAttachable must
                   be in effect on the object. Each case attaches a throwaway tag as TEST_USER and detaches it.
  --supervisor-vm NAME
                   on SUPERVISOR_VCENTER: the effective roles and tag privileges of VC_USER and TEST_USER on one
                   Supervisor-managed VM, an attach of a throwaway tag as each, and VC_USER's attempts to grant
                   itself a tag role and Admin on the VM, each grant it is given removed as its attempt ends. Choose
                   a VM you own. The name is looked up before the census and every probe: one that names no VM, or
                   several, is a usage error (exit 5) with nothing read or sent.

A saved permission list, and a compare. Each is a run of its own, and neither writes the record.
  --save-permissions FILE
                   every grant on every vCenter in VC_HOSTS (vCenter, entity, principal as vCenter spells it, user or
                   group, role id and name, whether it propagates, permission id), each list read whole by the pager
                   below, written to FILE: a new file of mode 0600, outside the clone, never scrubbed and never
                   published. A list not read whole on any vCenter writes nothing (exit 3). The file carries its own
                   header, totals and digest, so the compare can tell it from any other.
  --compare-permissions BEFORE AFTER
                   two such files, compared by the grant key (vCenter, entity, principal with user or group, role):
                   each grant added, removed or changed (whether it propagates), printed on the terminal only. vCenter's
                   list can carry one grant under two permission ids; such a key is compared by count. Exit 1
                   on any difference, 0 on none, 3 on a file unreadable, partial or not written by --save-permissions,
                   and 3 when a vCenter was read in one file only (it was not compared). Reads no vCenter.

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

--remove trusts the domains you declare. A directory left out of DIRECTORY_DOMAINS and typed as REALM_DOMAIN reads as
the realm, so its working grants would read realm-spelled. Two guards stand before anything is sent. A realm equal to a
domain you named is refused (exit 5, below). And --remove reads who is signed in on that vCenter first (pyVmomi): a
broker session carries the directory's name, so a live session spelled in REALM_DOMAIN shows that domain is one people
sign in with, and a grant in it may apply to them. The removal is then refused, plan and --execute alike, with nothing
sent (exit 3), as it is when the session list cannot be read whole: one that does not hold the session that read it,
or one that holds nothing but the reader's own sessions (an identity that may not read the others lists only its own).
A directory nobody from is signed in to at that moment passes both, so --remove runs only with OTHER_DOMAINS stated,
empty when there is none (export OTHER_DOMAINS=), as your declaration that DIRECTORY_DOMAINS names every directory.

Before a realm exists. Run the census before the broker takes the realm, so the grants are inventoried while the
boundary is decided: declare it with --no-realm, and the realm-spelled class is reported as not applicable and nothing
is flagged for it. A run with neither REALM_DOMAIN nor --no-realm is refused (exit 5): left to infer "no realm" from
a variable not set, a run on an estate that has a realm read its realm-spelled grant as another provider's and exited
0 (X-197). Every run prints, on the terminal only, the domains it read as another provider's with their grant counts,
so a misspelled REALM_DOMAIN or directory domain shows there.

A misspelled realm, caught. A misspelled REALM_DOMAIN moves every realm-spelled grant into another provider's class,
where nothing flags it, while the directory domains still name their grants. So with REALM_DOMAIN set, a vCenter on
which the realm names no grant while grants of an unplaced domain are there (a domain in none of DIRECTORY_DOMAINS,
LOCAL_DOMAIN, REALM_DOMAIN, BROKER_TENANT and OTHER_DOMAINS) is a failed read: the run prints NOT PLACED with those
domains, on the terminal only, records realmNamedNothing, and exits 3. Name in OTHER_DOMAINS the domains you know are
another identity provider's, and the vCenter is placed (on the reference estate, the workload vCenter that runs a
Supervisor held one).

An API client's grant, kept. An API client signed in through the SAML exchange carries the broker tenant and its
clientId, CUSTOMER\\<clientId> on the reference estate, and a grant to that name applied to the client's session, while
a grant to CUSTOMER\\<user> did not reach a directory user signing in through the broker (X-221; one management
vCenter, one run each). So a grant whose domain is BROKER_TENANT (CUSTOMER when unset) is classed API client (broker
tenant), whatever its name, since the spelling cannot tell a clientId from a person's name: an integration's own
access, to review with the integration's owner and never remove as clutter. The census counts it, prints the count
and that advice on the terminal, and places its domain, so it is neither another provider's nor a reason for NOT
PLACED; --remove refuses its id as it refuses every grant that is not realm-spelled. A BROKER_TENANT that is not the
estate's leaves the API clients' grants in another provider's class, where their domain shows on the terminal.

The realm is not the directory domain, refused. The census tests the realm's name before the directory domains, the
broker tenant and another provider's, so a REALM_DOMAIN that names a DIRECTORY_DOMAINS or OTHER_DOMAINS entry, or the
broker tenant, would class every working grant in that domain realm-spelled, an API client's own among them: exit 1
would say to remove them, and --remove would accept their ids. So a REALM_DOMAIN equal to any of those, compared
without regard to case, surrounding spaces or a trailing dot (corp.example. and CORP.EXAMPLE are one domain), is a
usage error (exit 5) found before anything is read, and so is one equal to LOCAL_DOMAIN, where every grant sorts as
local first and no grant could ever read realm-spelled. The broker tenant is held the same way: the census tests the
local and the directory domains before it, so a BROKER_TENANT equal to a DIRECTORY_DOMAINS or LOCAL_DOMAIN entry would
read every API client's grant as a person's or a local one, and is a usage error (exit 5). OTHER_DOMAINS may name it:
that places a domain and classes nothing, and the broker tenant's rule comes first.

Paged lists. The permission and role lists are paged: an answer that carries a marker has more after it, and the next
page is asked for with that marker until an answer carries none. vCenter states no total for them, so the read holds
them to what it can check: a page refused, an item without its id, an id answered on an earlier page (the list moved
while it was read), a page that says more follow and adds nothing, or a marker answered twice, is a list not read
(exit 3). A permission list with no permission in it is too: VC_USER, an administrator, holds one.

Environment:
  VC_HOSTS            comma-separated vCenter FQDNs (one, with --remove)
  VC_USER             an administrator of those vCenters, user@domain
  VC_PASSWORD_FILE    a file holding that password (mode 0600); VC_PASSWORD is read if it is not set
  REALM_DOMAIN        the realm's name as vCenter spells it in a grant (VCF Operations, fleet IAM realms); never the
                      broker tenant an API client's session carries (BROKER_TENANT) or a directory domain: one equal to
                      BROKER_TENANT or to a DIRECTORY_DOMAINS, OTHER_DOMAINS or LOCAL_DOMAIN entry is refused (exit 5).
                      Required once the estate has a realm, and by --where-realm, --remove and the probes; before a
                      realm, run with --no-realm
  DIRECTORY_DOMAINS   required: comma-separated directory domains under the broker's identity provider (or, before
                      the realm, the vCenter's own directory identity sources). Unset, every directory grant reads as
                      another provider's and the census would count none, so the script refuses to start without it
  LOCAL_DOMAIN        the vCenter's own SSO domain (default VSPHERE.LOCAL); set it where yours is named otherwise,
                      or every local grant reads as another provider's
  BROKER_TENANT       the broker tenant, the realm's path segment at the broker and the domain an API client's session
                      carries before its clientId (default CUSTOMER, as on the reference estate); its grants are
                      classed API client (broker tenant). One equal to a DIRECTORY_DOMAINS or LOCAL_DOMAIN entry is
                      refused (exit 5). Set it where yours is named otherwise, or the API clients' grants read as
                      another provider's
  OTHER_DOMAINS       comma-separated domains you know are another identity provider's. Their grants stay in another
                      provider's class and count as placed, so neither NOT PLACED check stops on them. Optional for
                      the census; --remove needs it stated, empty when there is none
  TLS_VERIFY          false only on a self-signed lab CA
  TEST_USER, TEST_PASSWORD_FILE, TEST_GROUP, PROBE_VCENTER   for the probes (TEST_USER must not be an administrator)
  TEST_LOCAL_GROUP    optional: a local SSO group holding TEST_GROUP, for the nested case of --probe-grants
  SUPERVISOR_VCENTER  the vCenter for --supervisor-vm (default PROBE_VCENTER)
  OUT_DIR             where authz.json is written (default: this folder)

Run:  python3 authz.py [--where-realm] [--probe-grants] [--probe-tags] [--supervisor-vm NAME]
      python3 authz.py --remove ID[,ID...] [--execute]
      python3 authz.py --save-permissions FILE
      python3 authz.py --compare-permissions BEFORE AFTER
      Python 3.10 or later.
Exit, the first that applies, so a scheduler reads one state from one number:
      2 a removal (--remove --execute) that did not hold on read-back: a named grant still there, or another grant
        moved; --remove-probe-roles refused (a probe role granted to someone other than its reserved group: removing
        the role would remove that grant with it, so nothing is sent) or not held (a probe role still listed after it);
        or a probe that left residue (its folder, its tag category, a grant it made on the Supervisor VM, or a grant of
        a probe role, one there before the probe began included, when the probe sends nothing)
      1 the census read realm-spelled grants: remove them (--where-realm names them, --remove removes them). Only
        with REALM_DOMAIN set, only when the session list of every vCenter read was read whole, and never while a live
        session is spelled in it (each of those is 3); before a realm there is no such class. With
        --compare-permissions: a grant added, removed or changed on a vCenter both files read
      3 a read failed or a result is undetermined: a vCenter refused the session or a page of the permission or role
        list, a permission list with no permission in it, a session list not read whole (refused, holding nothing but
        the reader's own sessions, or, with REALM_DOMAIN set, not read because pyVmomi is missing), a vCenter on which
        DIRECTORY_DOMAINS (and REALM_DOMAIN, when set) name no grant while another provider's grants are there, a
        vCenter on which REALM_DOMAIN names no grant while grants of a domain in none of the domains given are there (a
        misspelled realm hides its grants there), a live session spelled in REALM_DOMAIN (a domain people sign in with,
        so a grant spelled in it may apply to them; with --remove, nothing is sent), a probe that could not run its
        cases, stopped on an error, or whose residue was not read back, a vCenter --remove-probe-roles could not finish
        or read back, or an error the script did not expect. With --save-permissions: a list not read whole on any
        vCenter (nothing written). With --compare-permissions: a file unreadable, partial or not written by
        --save-permissions (nothing compared), or a vCenter read in one file only (not compared, so the files are not
        shown equal). Nothing is known about what was not read
      0 nothing for a person to act on: every vCenter read and placed (with REALM_DOMAIN set, its session list read
        whole), no realm-spelled grant, every probe clean (with --remove: the plan printed, or every named grant removed
        and nothing else moved; with --save-permissions: the file written; with --compare-permissions: no grant added,
        removed or changed, and every vCenter in both files)
      5 a usage error, before anything is sent: an argument or environment variable missing or wrong (an abbreviated flag
        among them: flags are taken whole, so --exec is not --execute), a REALM_DOMAIN
        that names BROKER_TENANT or a DIRECTORY_DOMAINS, OTHER_DOMAINS or LOCAL_DOMAIN entry, a BROKER_TENANT that
        names a DIRECTORY_DOMAINS or LOCAL_DOMAIN entry, --remove without OTHER_DOMAINS stated, an id --remove cannot
        name as a realm-spelled grant on that vCenter (an API client's among them), pyVmomi missing for a step that needs it
        (--remove among them), a --supervisor-vm that names no VM or several (looked up before the census and every
        probe), a --save-permissions FILE that exists, has no directory or lies inside the clone, a
        --compare-permissions BEFORE saved after AFTER, a Python older than 3.10
      A record refused because an estate value or a password survived the scrub is not written, and never hides the
      run's result: the run's code stands when it is 1, 2 or 3, and a run that found nothing to act on exits 3 (its
      record was not written; the probes and --remove-probe-roles may already have written to vCenter).
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
# A reserved group's whole name: vcf_reserved_ and the id of the role it holds, an integer (-1 for Admin, -2 for
# ReadOnly, a large number for a custom role). Matched whole, never by its prefix: a local group an operator named
# vcf_reserved_<anything else> is theirs, not a VCF role arriving, and is read like any other local group.
RESERVED_NAME = r"^vcf_reserved_-?[0-9]+$"
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

# The broker tenant: the domain an API client's vCenter session carries before its clientId (CUSTOMER on the reference
# estate), the realm's path segment at the broker. BROKER_TENANT names it, CUSTOMER when unset or empty, as the other
# identity companions read it. A grant spelled in it is an API client's (X-221: a grant to CUSTOMER\<clientId> applied
# to that client's session, and one to CUSTOMER\<user> did not reach a directory user), so it is an integration's own
# access: the census names its class and the advice below, and --remove, which removes only realm-spelled grants,
# never removes one.
BROKER_DEFAULT = "CUSTOMER"
BROKER_CLASS = "API client (broker tenant)"
BROKER_ADVICE = "an integration's own access: review it with the integration's owner, never remove it as clutter"

# The classification, as data, in the order classify() applies it: the first rule whose domain and name both match
# names the class. ``domain`` is the domain the principal's must equal, compared as norm() reads a domain: "local" is
# LOCAL_DOMAIN (VSPHERE.LOCAL by default), "realm" is REALM_DOMAIN (never matched while it is unset), "directory" is any
# of DIRECTORY_DOMAINS, "broker" is BROKER_TENANT (CUSTOMER by default), "any" is every domain. ``name`` is a pattern the
# principal's name must match, without regard to case, or None for any name. The chapter's grant translator runs this
# same table in the reader's browser, exported by rule_table(), so the page cannot class a grant otherwise than the
# census does.
CLASS_RULES = (
    ("local", RESERVED_NAME, "reserved group"),
    ("local", VCF_MANAGED.pattern, LOCAL_CLASSES[0]),
    ("local", "^(?:" + "|".join(sorted(re.escape(p) for p in PRODUCT_LOCAL)) + ")$", LOCAL_CLASSES[1]),
    ("local", None, LOCAL_CLASSES[2]),
    ("realm", None, "realm spelling"),
    ("directory", None, "directory"),
    ("broker", None, BROKER_CLASS),
    ("any", None, "another provider"),
)
# The domains REALM_DOMAIN may never equal, in the order realm_overlap() tests them. classify() tests the local domain
# first and the realm before a directory, the broker tenant or another provider's domain, so a realm typed as one of
# these would either class every working grant in it realm-spelled (an API client's among them, which --remove would
# then accept) or never class one so. Exported with the rules for the same reason.
REALM_MUST_DIFFER = ("DIRECTORY_DOMAINS", "OTHER_DOMAINS", "LOCAL_DOMAIN", "BROKER_TENANT")
# The domains BROKER_TENANT may never equal, in the order broker_overlap() tests them. classify() tests the local and the
# directory domains before the broker tenant, so a broker tenant typed as one of them would never class an API client's
# grant as one: it would read as a person's grant or a local one. OTHER_DOMAINS may name it: it places a domain and
# classes nothing, and the broker tenant's rule comes before another provider's.
BROKER_MUST_DIFFER = ("DIRECTORY_DOMAINS", "LOCAL_DOMAIN")

# The exit codes, one state each (the docstring's table).
EXIT_OK, EXIT_REALM, EXIT_NOT_HELD, EXIT_UNREAD, EXIT_USAGE = 0, 1, 2, 3, 5
EXIT_DIFFER = EXIT_REALM  # --compare-permissions: a grant added, removed or changed
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


def pages(what, ask, ident):
    """Every item of a paged vSphere Automation list, each once. ``ask(marker)`` sends one request and returns its status
    and body; ``ident(item)`` is the item's id. An answer whose ``marker`` is set has more items after it, and the next
    page is asked for with that marker; an answer with no marker has returned the last of them. vCenter states no total
    for these lists, so the read is held to what it can check: a page refused, an answer without its items list, an
    item without its id, an id read on an earlier page (the list moved while it was read), a page that says more follow
    and adds no item, or a marker that is not a string or was answered before, is a list not read (ReadError, exit 3)."""
    out, marker, seen, ids = [], None, set(), set()
    while True:
        st, body = ask(marker)
        n = len(seen) + 1
        page = f" on page {n}" if seen else ""
        if st != 200 or not isinstance(body, dict) or not isinstance(body.get("items"), list):
            raise ReadError(f"the {what} list answered {st}{page}")
        for item in body["items"]:
            try:
                i = ident(item)
            except (KeyError, TypeError):
                i = None
            if i is None or str(i) == "":
                raise ReadError(f"the {what} list answered an item without its id on page {n}")
            if str(i) in ids:
                raise ReadError(f"the {what} list answered an id it had answered before, on page {n}: the list moved "
                                "while it was read; read it again")
            ids.add(str(i))
            out.append(item)
        marker = body.get("marker")
        if marker is None or marker == "":
            return out
        if not isinstance(marker, str) or marker in seen:
            raise ReadError(f"the {what} list answered a marker it had answered before, or one that is not a string, "
                            f"on page {n}")
        if not body["items"]:
            raise ReadError(f"the {what} list answered a page that adds nothing and says more follow, on page {n}")
        seen.add(marker)


def permissions(rest, page_size=None):
    """Every permission, global and per-object, every page. A GET on the collection answers 404 on vCenter 9.1; the
    list is the action=list POST, and global ones carry object type GlobalAcl. The page size and the marker go in the
    body's ``iterate``. A list with no permission in it read nothing: VC_USER, an administrator, holds one."""
    size = PAGE_SIZE if page_size is None else page_size

    def ask(marker):
        it = {k: v for k, v in (("page_size", size), ("marker", marker)) if v}
        return rest.call("POST", "/api/vcenter/authorization/permissions?action=list", {"iterate": it} if it else {})

    items = pages("permission", ask, lambda p: p["permission"])
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

    return {str(i["role"]): i["info"] for i in pages("role", ask, lambda r: r["role"])}


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

def norm(domain):
    """A domain as every comparison here reads it: trimmed, without regard to case, and with a trailing dot dropped, so
    ``corp.example.`` and ``CORP.EXAMPLE`` name one domain (a spelling that differs only so would otherwise pass the
    realm guard and class a directory's working grants realm-spelled)."""
    return str(domain or "").strip().rstrip(".").strip().lower()


def local_domain():
    return norm(os.environ.get("LOCAL_DOMAIN") or "VSPHERE.LOCAL").upper()


def broker_tenant():
    """BROKER_TENANT as the census reads it, CUSTOMER when unset or empty: the domain an API client's session carries."""
    return norm(os.environ.get("BROKER_TENANT") or BROKER_DEFAULT).upper()


def classify(domain, name, realm, directories, local=None, rules=CLASS_RULES, broker=None):
    """One principal's class, by how it behaves for a broker session and who looks after it: the first of ``rules``
    (CLASS_RULES, in order) whose domain and name both match. A local principal is reserved (a VCF role arriving),
    VCF-managed (leave it), Administrators (the administrator and its group: read the members), or other (read it,
    members included). A principal in the broker tenant's domain is an API client's, whatever its name: the spelling
    cannot tell a clientId from a person's name, and a grant to CUSTOMER\\<user> did not reach a directory user (X-221).
    ``rules`` is a parameter so the chapter's builder can run the table its page carries through this same function and
    hold the two equal; ``local`` and ``broker`` empty read LOCAL_DOMAIN and BROKER_TENANT."""
    d = norm(domain)
    domains = {"local": {norm(local or local_domain())}, "realm": {norm(realm)} - {""},
               "directory": {norm(x) for x in directories} - {""}, "broker": {norm(broker or broker_tenant())}}
    for where, pattern, cls in rules:
        if where != "any" and d not in domains[where]:
            continue
        if pattern is None or re.search(pattern, str(name or ""), re.IGNORECASE):
            return cls
    raise ValueError("the classification table has no rule for every domain")


def rule_table():
    """The classification and the realm guard as data, for the chapter's grant translator: classify()'s rules in order,
    how a domain is compared, the default local domain, and the domains REALM_DOMAIN may never equal. Patterns are
    written so a browser's regular expressions read them the same way (no Python-only syntax). The broker tenant's
    default and the domains it may never equal travel with them."""
    return {"rules": [{"domain": w, "name": p, "class": c} for w, p, c in CLASS_RULES],
            "nameFlags": "i", "domainCompare": "trimmed, trailing dots dropped, without regard to case",
            "localDefault": "VSPHERE.LOCAL", "realmMustDiffer": list(REALM_MUST_DIFFER),
            "brokerDefault": BROKER_DEFAULT, "brokerMustDiffer": list(BROKER_MUST_DIFFER)}


def names_nothing(by_class):
    """Whether neither the realm's name nor a directory domain names a grant on a vCenter whose list holds another
    provider's grants: a misspelled domain hides its grants there, as VCF Automation's own grants sit there anyway. An
    API client's grant neither raises this nor answers it: the broker tenant naming a grant says nothing of whether
    DIRECTORY_DOMAINS and REALM_DOMAIN are spelled right, and a misspelled one still sends its grants to another
    provider's class, where this finds them."""
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
    """OTHER_DOMAINS, as norm() reads them: the domains the reader knows are another identity provider's."""
    return {norm(x) for x in os.environ.get("OTHER_DOMAINS", "").split(",") if norm(x)}


REALM_IS = "REALM_DOMAIN is the realm's name as vCenter spells it in a grant (VCF Operations, fleet IAM realms)"


BROKER_IS = ("BROKER_TENANT is the broker tenant, the domain an API client's session carries before its clientId "
             "(CUSTOMER when unset)")


def realm_overlap(realm, directories, others=(), local="", broker=""):
    """Why REALM_DOMAIN cannot be read, when it names a domain the run was given as something else; else None.
    classify() tests the realm before a directory domain, the broker tenant or another provider's, so a realm typed as
    one of them would class every working grant in it realm-spelled, an API client's own grant among them: exit 1 would
    say to remove them and --remove would accept their ids. The local domain is tested first, so a realm typed as it
    could never class a grant realm-spelled. Compared as norm() reads a domain: trimmed, without regard to case, a
    trailing dot dropped; ``local`` empty is VSPHERE.LOCAL and ``broker`` empty is CUSTOMER, the defaults."""
    r = (realm or "").strip()
    if not norm(r):
        return None
    lo, b = (local or "").strip(), (broker or "").strip()
    given = {"DIRECTORY_DOMAINS": list(directories), "OTHER_DOMAINS": list(others), "LOCAL_DOMAIN": [lo or "VSPHERE.LOCAL"],
             "BROKER_TENANT": [b or BROKER_DEFAULT]}
    for var in REALM_MUST_DIFFER:
        for entry in given[var]:
            if norm(entry) != norm(r):
                continue
            if var == "LOCAL_DOMAIN":
                return (f"REALM_DOMAIN ({r}) and LOCAL_DOMAIN ({lo or 'VSPHERE.LOCAL, the default'}) name the same domain. "
                        f"{REALM_IS}; LOCAL_DOMAIN is the vCenter's own SSO domain. Read as one, every grant in that domain "
                        "sorts as local and no realm-spelled grant could be found. Set REALM_DOMAIN to the realm's name")
            if var == "BROKER_TENANT":
                return (f"REALM_DOMAIN ({r}) and BROKER_TENANT ({b or BROKER_DEFAULT + ', the default'}) name the same "
                        f"domain. {REALM_IS}; {BROKER_IS}, and a grant spelled in it is that client's own access. Read as "
                        "one, every API client's grant would be classed realm-spelled and named for removal. Set "
                        "REALM_DOMAIN to the realm's name, and BROKER_TENANT to the broker tenant's")
            what = ("a directory domain is the one your directory spells its users and groups in, DOMAIN\\user, which a "
                    "broker session carries" if var == "DIRECTORY_DOMAINS"
                    else "OTHER_DOMAINS names the domains you know are another identity provider's")
            return (f"REALM_DOMAIN ({r}) and {var} ({entry.strip()}) name the same domain. {REALM_IS}; {what}. Read as "
                    "one, every working grant in that domain would be classed realm-spelled and named for removal. Set "
                    "REALM_DOMAIN to the realm's name")
    return None


def broker_overlap(broker, directories, local=""):
    """Why BROKER_TENANT cannot be read, when it names a domain the run was given as a directory or the local domain;
    else None. classify() tests those before the broker tenant, so an API client's grant would read as a directory
    grant, a person's, or as a local one, and never as an integration's own access. Compared as norm() reads a domain;
    ``broker`` empty is CUSTOMER and ``local`` empty is VSPHERE.LOCAL, the defaults."""
    b, lo = (broker or "").strip(), (local or "").strip()
    shown = b or BROKER_DEFAULT + ", the default"
    given = {"DIRECTORY_DOMAINS": list(directories), "LOCAL_DOMAIN": [lo or "VSPHERE.LOCAL"]}
    for var in BROKER_MUST_DIFFER:
        for entry in given[var]:
            if norm(entry) != norm(b or BROKER_DEFAULT):
                continue
            if var == "LOCAL_DOMAIN":
                return (f"BROKER_TENANT ({shown}) and LOCAL_DOMAIN ({lo or 'VSPHERE.LOCAL, the default'}) name the same "
                        f"domain. {BROKER_IS}; LOCAL_DOMAIN is the vCenter's own SSO domain. Read as one, every grant in "
                        "that domain sorts as local and no API client's grant could be told. Set BROKER_TENANT to the "
                        "broker tenant's name")
            return (f"BROKER_TENANT ({shown}) and DIRECTORY_DOMAINS ({entry.strip()}) name the same domain. {BROKER_IS}; "
                    "a directory domain is the one your directory spells its users and groups in, DOMAIN\\user, which a "
                    "broker session carries. Read as one, every API client's grant would be classed a directory grant, "
                    "a person's. Take the broker tenant out of DIRECTORY_DOMAINS, or set BROKER_TENANT to the broker "
                    "tenant's name")
    return None


def unplaced(others, declared):
    """Of the domains read as another provider's (domain to grant count), the ones OTHER_DOMAINS does not name."""
    return {d: n for d, n in others.items() if norm(d) not in declared}


def realm_names_nothing(by_class, realm, undeclared):
    """Whether REALM_DOMAIN is set, names no grant on a vCenter, and grants of an unplaced domain are there: a
    misspelled realm's grants would sit among them, unflagged, while the directory domains still name theirs. A
    correct realm on a vCenter with no realm-spelled grant and no unplaced domain is never this (G-410's other half)."""
    kinds = {k.rsplit(", ", 1)[0] for k in by_class}
    return bool(realm) and "realm spelling" not in kinds and bool(undeclared)


def other_domains(perms, realm, directories):
    """The domains whose grants read as another provider's, with their counts: printed on the terminal only, so a
    misspelled REALM_DOMAIN or directory domain shows among them. A domain is an estate value; the record never
    carries this. The broker tenant is not among them: its grants are API clients', placed by BROKER_TENANT, so a
    vCenter whose only other domain is the broker tenant is placed. A BROKER_TENANT that does not match the estate's
    sends the API clients' grants here, where their domain shows."""
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
    the class it exists to clean up, so an API client's grant (the broker tenant's spelling) is never removed here. A
    realm that names a directory, another provider's, the local domain or the broker tenant is refused first: read as
    the realm, that domain's working grants would pass as realm-spelled."""
    problem = realm_overlap(realm, directories, sorted(other_domains_declared()), os.environ.get("LOCAL_DOMAIN", ""),
                            os.environ.get("BROKER_TENANT", ""))
    if problem:
        return None, problem
    by_id = {str(p.get("permission")): p for p in perms}
    unknown = [i for i in ids if i not in by_id]
    if unknown:
        return None, f"no grant on this vCenter has the id {', '.join(unknown)}; read the ids with --where-realm"
    realm_ids = {str(p.get("permission")) for p in realm_grants(perms, realm, directories)}
    other = [i for i in ids if i not in realm_ids]
    if other:
        clients = [i for i in other if classify(by_id[i]["info"]["principal"]["domain"],
                                                by_id[i]["info"]["principal"]["name"], realm, directories) == BROKER_CLASS]
        return None, (f"{', '.join(other)} {'is' if len(other) == 1 else 'are'} not a realm-spelled grant; this script "
                      "removes only those, and any other grant is removed where it was made"
                      + (f". {', '.join(clients)} {'is' if len(clients) == 1 else 'are'} an {BROKER_CLASS} grant, "
                         f"{BROKER_ADVICE}" if clients else ""))
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


def session_list(si):
    """Every live session on one vCenter. vCenter states no count for the list, so it is checked for the member it must
    hold: the session that read it. A refusal, or a list without that session, is a read that failed (ReadError, exit
    3). So is a list that holds nothing but the reader's own sessions: an identity that may not read the others lists
    only its own (a directory account with no administrator role did, on the reference estate), and that list says
    nothing of anyone else. Read whole by an administrator, each reference vCenter listed hundreds of sessions besides
    the reader's, so a list of the reader's alone is read as filtered, never as an estate where no one else is signed
    in."""
    try:
        sm = si.content.sessionManager
        own, listed = sm.currentSession, list(sm.sessionList or [])
    except Exception as e:  # a refusal of either read: nothing is known of who is signed in
        raise ReadError(f"the session list was not read: {type(e).__name__}") from None
    if own is None or own.key not in {s.key for s in listed}:
        raise ReadError("the session list does not hold the session that read it, so it is not the whole list")
    me = str(getattr(own, "userName", "") or "").strip().lower()
    if all(s.key == own.key or (me and str(getattr(s, "userName", "") or "").strip().lower() == me) for s in listed):
        raise ReadError("the session list held only the reader's own session(s): an identity that may not read the others "
                        "lists only its own, so it is not the whole list; run as an administrator of the vCenter")
    return listed


def realm_sessions(names, realm):
    """The live sessions spelled in REALM_DOMAIN. A broker session carries the directory's name for the user
    (DOMAIN\\user), so a session spelled in REALM_DOMAIN shows that domain is one people sign in with: a directory left
    out of DIRECTORY_DOMAINS and typed as the realm, or a realm whose grants can apply. Either way a grant spelled in
    it may apply to them."""
    r = norm(realm)
    return [n for n in names if r and norm(str(n).rpartition("\\")[0]) == r]


def session_names(host, user, password):
    """Who is signed in on one vCenter now, as vCenter spells each session's name (DOMAIN\\name), read whole: what
    --remove checks before it acts. A session that cannot be opened, or a list not read whole, is ReadError (exit 3)."""
    try:
        si = soap(host, user, password)
    except Exception as e:
        raise ReadError(f"the session list was not read: {type(e).__name__}") from None
    try:
        return [str(s.userName) for s in session_list(si)]
    finally:
        unsoap(si)


def sessions(si, realm, directories):
    by_class = collections.Counter()
    admin_agents = collections.Counter()
    for s in session_list(si):
        domain, _, name = str(s.userName).rpartition("\\")
        cls = classify(domain, name, realm, directories)
        by_class[cls] += 1
        if norm(domain) == norm(local_domain()) and name == "Administrator":
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
# The six roles the probes keep, by their whole names. A role is a probe role only when its name is one of these: a
# role an operator named authz-probe-<anything else> is theirs, and nothing here counts, reconciles or removes it.
PROBE_ROLE_NAMES = frozenset(PROBE_ROLE_PREFIX + k for k in PROBE_ROLES)


def probe_role_ids(am):
    """The probe roles on this vCenter, by role id: the roles whose whole name is one of PROBE_ROLE_NAMES."""
    return {r.roleId: r.name for r in am.roleList if r.name in PROBE_ROLE_NAMES}


def own_reserved_group(principal, role_id):
    """Whether a grant's principal is the reserved group VCF made for that very role, vcf_reserved_<role id> in the
    local domain, matched whole: another role's reserved group, a group named with the prefix, or a directory group
    of the same name holds the role as anyone else would."""
    domain, _, name = str(principal).rpartition("\\")
    return norm(domain) == norm(local_domain()) and name.lower() == f"{RESERVED_PREFIX}{role_id}".lower()


def _read(fn):
    """A residue read: its answer, or None when the read itself failed (a residue not read back is never a clean run)."""
    try:
        return fn()
    except Exception:  # noqa: BLE001  any failure of a read-back leaves it unread, which exit_code reads as exit 3
        return None


def stopped(e):
    """Why a step stopped, as its record keeps it: the error's kind only, since a message can carry a host or a
    principal the scrub would then refuse. The message itself goes to the terminal, once, here."""
    print(f"     stopped on {type(e).__name__}: {str(e)[:240]} (on this terminal only)", file=sys.stderr)
    return f"{type(e).__name__}, an error the step did not expect"


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
    ids = probe_role_ids(am)
    return sum(1 for p in am.RetrieveAllPermissions() if p.roleId in ids and not own_reserved_group(p.principal, p.roleId))


def held_before(n):
    """Why a probe sends nothing: a probe role is already granted to someone other than its reserved group. Reconciling
    the role would change what that principal holds, and the residue read after the run would count the grant as the
    probe's own. The record keeps the count as residue, so the run exits 2."""
    return (f"{n} grant(s) of an {PROBE_ROLE_PREFIX}* role to someone other than its reserved group were there before "
            "the probe began: reconciling the role would change what they hold, so nothing was sent; remove those grants "
            "where they were made, then run again")


def remove_probe_roles(si):
    """Remove the six probe roles (PROBE_ROLE_NAMES, by whole name) once nothing but their own reserved groups holds
    them, and read the role list back. RemoveAuthorizationRole with failIfUsed false removes a role with every grant of
    it, so a grant of a probe role to anyone else is refused first, with nothing sent: that grant is someone's access,
    removed where it was made. A probe role still listed after the removal is a removal that did not hold (exit 2). A
    removal that stops on an error records the roles it removed before it and reads the role list back (exit 3)."""
    am = si.content.authorizationManager
    try:
        held = probe_role_grants(am)
        roles = sorted(probe_role_ids(am).items(), key=lambda kv: kv[1])
    except Exception as e:  # noqa: BLE001  the grants not read: nothing may be sent
        return {"removed": 0, "error": f"the probe roles' grants were not read ({stopped(e)}); nothing was sent"}
    if held:
        return {"removed": 0, "refused": f"{held} grant(s) of a probe role to someone other than its reserved group: "
                                         "removing the role would remove those grants with it, so nothing was sent"}
    done = []
    for rid, name in roles:
        try:
            am.RemoveAuthorizationRole(rid, False)
        except Exception as e:  # noqa: BLE001  record what was done before the error, and read the list back
            return {"removed": len(done), "removedRoles": done, "error": f"the removal stopped at {name} ({stopped(e)})",
                    "rolesLeft": _read(lambda: len(probe_role_ids(am)))}
        done.append(name)
    return {"removed": len(done), "removedRoles": done, "rolesLeft": _read(lambda: len(probe_role_ids(am))),
            "reservedGroupsLeft": _read(lambda: reserved_groups_left(si, [rid for rid, _ in roles]))}


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


def throwaway_folder(si, name):
    """The probe's own folder, made under the first datacenter's VM folder."""
    from pyVmomi import vim
    dc = next(e for e in si.content.rootFolder.childEntity if isinstance(e, vim.Datacenter))
    return dc.vmFolder.CreateFolder(name)


def folder_left(si, name):
    """Whether a folder by the probe's own name is still there: the residue read after its delete."""
    from pyVmomi import vim
    view = si.content.viewManager.CreateContainerView(si.content.rootFolder, [vim.Folder], True)
    try:
        return any(f.name == name for f in view.view)
    finally:
        view.Destroy()


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
    """A one-privilege probe role granted on a throwaway folder to each case's principal in turn, measured from fresh
    sessions of the subject. Each grant is removed in a ``finally`` the moment its case ends, whatever the measurement
    did; an error the probe did not expect stops it, recorded as ``stopped``, and its folder is still deleted and the
    vCenter read back for residue (exit 2 for residue, else 3)."""
    from pyVmomi import vim
    name = "authz-run-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    si = soap(host, *admin)
    am = si.content.authorizationManager
    made = {}
    rec = {"privilege": "Folder.Create", "cases": []}
    try:
        held = probe_role_grants(am)
        if held:   # the residue read below counts them, so the run exits 2 with nothing sent
            rec["aborted"] = held_before(held)
            return rec
        made["folder"] = throwaway_folder(si, name)
        ids, rec["probeRoles"] = ensure_probe_roles(am, ["folder-create"])
        made["role"] = ids["folder-create"]
        folder = made["folder"]
        rec["baseline"] = measure_folder(host, subject, folder._moId, name, si)
        for label, principal, group in cases:
            row = {"case": label}
            rec["cases"].append(row)
            if any(str(p.principal).lower() == principal.lower() for p in am.RetrieveEntityPermissions(folder, False)):
                row["skipped"] = "the principal already holds a permission here"
                continue
            am.SetEntityPermissions(folder, [vim.AuthorizationManager.Permission(
                principal=principal, group=group, roleId=made["role"], propagate=True)])
            try:
                time.sleep(3)
                row.update(measure_folder(host, subject, folder._moId, name, si))
            finally:
                am.RemoveEntityPermission(folder, principal, group)
        rec["after"] = measure_folder(host, subject, folder._moId, name, si)
    except Exception as e:  # noqa: BLE001  recorded, and the residue read below still runs
        rec["stopped"] = stopped(e)
    finally:
        with contextlib.suppress(Exception):
            if "folder" in made:
                wait(made["folder"].Destroy_Task())
        # read by the run's own folder name even when no create answered: a create that timed out may have landed
        rec["residue"] = {"folder": _read(lambda: folder_left(si, name)),
                          "grantsOfProbeRoles": _read(lambda: probe_role_grants(am))}
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
        """The objects the tag is attached to. A refused list is a read that failed (ReadError, exit 3), never an empty
        one: read as empty, an attach that landed would be measured as refused and never detached."""
        st, body = self.rest.call("POST", self.path() + "?action=list-attached-objects")
        if st != 200 or not isinstance(body, list):
            raise ReadError(f"the probe tag's attached-object list answered {st}")
        return [o.get("id") for o in body if isinstance(o, dict)]

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
        """Delete the tag and its category, then read the category list back: True when the category is still there,
        False when it is gone, None when the list could not be read (a residue not read is no clean run: exit 3)."""
        self.rest.call("DELETE", "/api/cis/tagging/tag/" + urllib.parse.quote(self.tag, safe=""))
        self.rest.call("DELETE", "/api/cis/tagging/category/" + urllib.parse.quote(self.cat, safe=""))
        st, cats = self.rest.call("GET", "/api/cis/tagging/category")
        if st != 200 or not isinstance(cats, list):
            return None
        return self.cat in cats


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
    """Where the two tag privileges must come from, as an identity holding nothing else on this vCenter. Each case's
    grants are removed in a ``finally`` the moment the case ends, the global ones by their permission ids (deleting the
    folder would not take them); an error the probe did not expect stops it, recorded as ``stopped``, and the tag, the
    folder and every grant of a probe role are still read back for residue."""
    from pyVmomi import vim
    name = "authz-run-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    si = soap(host, *admin)
    am = si.content.authorizationManager
    rest = Rest(host, *admin)
    made = {"roles": {}}
    rec = {"cases": []}
    lab = None
    try:
        held = probe_role_grants(am)
        if held:   # the residue read below counts them, so the run exits 2 with nothing sent
            rec["aborted"] = held_before(held)
            return rec
        keys = {"none": "none", "tag": "attach-tag", "object": "tag-on-object", "both": "tag-both"}
        ids, rec["probeRoles"] = ensure_probe_roles(am, list(keys.values()))
        made["roles"] = {k: ids[v] for k, v in keys.items()}
        made["roles"]["Admin"] = -1
        made["folder"] = throwaway_folder(si, name)
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
            rec["cases"].append(row)
            live_obj, live_global = [], []
            try:
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
            finally:   # every grant this case made, removed whatever the case did; a removal that fails shows as residue
                for principal in live_obj:
                    with contextlib.suppress(Exception):
                        am.RemoveEntityPermission(made["folder"], principal, False)
                for pid in live_global:
                    with contextlib.suppress(Exception):
                        ungrant_global(rest, pid)
    except Exception as e:  # noqa: BLE001  recorded, and the residue read below still runs
        rec["stopped"] = stopped(e)
    finally:
        rec["residue"] = {}
        if lab is not None:
            rec["residue"]["category"] = _read(lab.close)
        if "folder" in made:
            with contextlib.suppress(Exception):
                wait(made["folder"].Destroy_Task())
        rec["residue"]["folder"] = _read(lambda: folder_left(si, name))
        rec["residue"]["grantsOfProbeRoles"] = _read(lambda: probe_role_grants(am))
        with contextlib.suppress(Exception):
            rest.close()
        unsoap(si)
    return rec


def read_identity(host, cred, vm, names, lab, obj, L):
    """One identity on the Supervisor VM, from a session of its own: its effective roles, vCenter's privilege check for
    the two tag privileges and ModifyPermissions, and an attach of the probe's tag, read back and detached."""
    from pyVmomi import vim
    s = soap(host, *cred)
    try:
        v = vim.VirtualMachine(vm._moId, s._stub)
        got = s.content.authorizationManager.HasPrivilegeOnEntity(
            v, s.content.sessionManager.currentSession.key, [ATTACH, ON_OBJECT, MODIFY])
        eff = [names.get(x, str(x)) for x in (v.effectiveRole or [])]
        return {"effectiveRoles": [x if x in PRODUCT_ROLES else L.get("role", x) for x in eff],
                "check": {"AttachTag": bool(got[0]), "ObjectAttachable": bool(got[1]), "ModifyPermissions": bool(got[2])},
                **lab.try_attach(host, cred, obj)}
    finally:
        unsoap(s)


def vms_named(si, vm_name):
    """The VMs on one vCenter whose name is exactly ``vm_name``."""
    from pyVmomi import vim
    view = si.content.viewManager.CreateContainerView(si.content.rootFolder, [vim.VirtualMachine], True)
    try:
        return [v for v in view.view if v.name == vm_name]
    finally:
        view.Destroy()


def supervisor_vm_check(host, user, password, vm_name):
    """--supervisor-vm, checked before the census and every probe: a name that names no VM, or several, on that vCenter
    is a usage error (exit 5) found before anything is written; a lookup that cannot be made is a read that failed
    (exit 3), nothing sent either way. Before this check the grant and tag probes had already written when it failed."""
    try:
        si = soap(host, user, password)
    except Exception as e:
        raise ReadError(f"--supervisor-vm could not be looked up on its vCenter: {type(e).__name__}; nothing was sent") from None
    try:
        try:
            n = len(vms_named(si, vm_name))
        except Exception as e:
            raise ReadError(f"--supervisor-vm could not be looked up on its vCenter: {type(e).__name__}; nothing was sent") from None
    finally:
        unsoap(si)
    if n != 1:
        raise UsageError(f"--supervisor-vm names {n} VMs on its vCenter, not one: name one VM you own; nothing was read "
                         "or sent")


def probe_supervisor(host, operator, tag_identity, vm_name, d_op, r_op, L):
    """One Supervisor-managed VM: effective roles, an attach as each identity, and the operator's grant attempts. A
    grant the operator is given on the VM is removed in a ``finally`` the moment its attempt ends; an error the probe did
    not expect stops it, recorded as ``stopped``, and every grant it made on the VM is removed again and read back."""
    from pyVmomi import vim
    si = soap(host, *operator)
    am = si.content.authorizationManager
    rest = Rest(host, *operator)
    name = "authz-run-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    made = {}
    rec = {"identities": {}, "grantAttempts": []}
    lab, vm, granted = None, None, []
    try:
        held = probe_role_grants(am)
        if held:   # the residue read below counts them, so the run exits 2 with nothing sent
            rec["aborted"] = held_before(held)
            return rec
        found = vms_named(si, vm_name)
        if len(found) != 1:   # checked before the run began; a VM renamed or added since is a probe that cannot run
            rec["aborted"] = f"--supervisor-vm names {len(found)} VMs on that vCenter now, not one; nothing was sent"
            return rec
        vm = found[0]
        rec["managedBy"] = vm.config.managedBy.extensionKey if vm.config.managedBy else None
        obj = {"id": vm._moId, "type": "VirtualMachine"}
        lab = TagLab(rest, name, ["VirtualMachine"])
        names = {x.roleId: x.name for x in am.roleList}
        for key, cred in (("operator", operator), ("tag identity", tag_identity)):
            rec["identities"][key] = read_identity(host, cred, vm, names, lab, obj, L)
        ids, rec["probeRoles"] = ensure_probe_roles(am, ["tag-on-object-modify"])
        made["role"] = ids["tag-on-object-modify"]
        for label, principal, role in (("ObjectAttachable to itself, directory spelling", d_op, made["role"]),
                                       ("Admin to itself, directory spelling", d_op, -1),
                                       ("ObjectAttachable to itself, realm spelling", r_op, made["role"])):
            row = {"attempt": label}
            rec["grantAttempts"].append(row)
            if any(str(p.principal).lower() == principal.lower() for p in am.RetrieveEntityPermissions(vm, False)):
                row["result"] = "skipped: the principal already holds a permission on the VM"
                continue
            try:
                am.SetEntityPermissions(vm, [vim.AuthorizationManager.Permission(
                    principal=principal, group=False, roleId=role, propagate=False)])
            except vim.fault.NoPermission as e:
                row["result"] = "refused"
                row["missingPrivilege"] = str(getattr(e, "privilegeId", "") or "")
                continue
            granted.append(principal)
            row["result"] = "accepted"
            try:
                row.update(lab.try_attach(host, operator, obj))
            finally:   # the grant (Admin among them) comes off the VM whatever the attach did
                am.RemoveEntityPermission(vm, principal, False)
    except Exception as e:  # noqa: BLE001  recorded, and the removal and residue read below still run
        rec["stopped"] = stopped(e)
    finally:
        rec["residue"] = {}
        if lab is not None:
            rec["residue"]["category"] = _read(lab.close)
        if granted:   # a principal granted here held nothing on the VM before (a holder is skipped), so any it holds now is left
            mine = {p.lower() for p in granted}

            def left_on_vm():
                return [p for p in am.RetrieveEntityPermissions(vm, False) if str(p.principal).lower() in mine]

            for p in _read(left_on_vm) or []:   # a removal that did not run, or did not hold: one more, then the read
                with contextlib.suppress(Exception):
                    am.RemoveEntityPermission(vm, p.principal, bool(getattr(p, "group", False)))
            left = _read(left_on_vm)
            rec["residue"]["grantsOnVm"] = None if left is None else len(left)
            if left:
                rec["leftOnVm"] = sorted({str(p.principal) for p in left})   # for the terminal; popped before the record
        rec["residue"]["grantsOfProbeRoles"] = _read(lambda: probe_role_grants(am))
        with contextlib.suppress(Exception):
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
    ap = _Parser(description=__doc__.split("\n")[0], allow_abbrev=False)  # "--exec" must never reach --execute
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
    ap.add_argument("--save-permissions", metavar="FILE",
                    help="a run of its own: every grant on every vCenter in VC_HOSTS, each list read whole, written to "
                         "FILE (a new file, mode 0600, outside the clone), with every principal named; never publish it")
    ap.add_argument("--compare-permissions", nargs=2, metavar=("BEFORE", "AFTER"),
                    help="a run of its own: two files --save-permissions wrote, compared grant by grant; reads no vCenter")
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
    except ReadError as e:  # a read a step needed did not answer, outside the probes (they record their own); no record
        print(f"NOT READ: {e}; the run stopped there and wrote no record; what it read or did before it is on the lines "
              "above (exit 3)", file=sys.stderr)
        return EXIT_UNREAD
    except Exception as e:  # the last guard: whatever was not expected is not known, so exit 3
        print(f"the run stopped on an error it did not expect: {type(e).__name__}: {str(e)[:160]}; nothing is known "
              "about what it had not read (exit 3)", file=sys.stderr)
        return EXIT_UNREAD


def _alone(a, flag):
    """--save-permissions and --compare-permissions are runs of their own: any other flag beside one is a usage error."""
    others = [f for f, on in (("--probe-grants", a.probe_grants), ("--probe-tags", a.probe_tags),
                              ("--supervisor-vm", a.supervisor_vm), ("--remove-probe-roles", a.remove_probe_roles),
                              ("--no-realm", a.no_realm), ("--where-realm", a.where_realm), ("--remove", a.remove),
                              ("--execute", a.execute), ("--save-permissions", a.save_permissions),
                              ("--compare-permissions", a.compare_permissions)) if on and f != flag]
    if others:
        raise UsageError(f"{flag} is a run of its own: it takes no {', '.join(others)}")


def _settings(a):
    """The environment the run reads, checked before anything is read: a usage error raises UsageError."""
    hosts = _hosts()
    user, password = os.environ.get("VC_USER", "").strip(), secret("VC_PASSWORD")
    realm = os.environ.get("REALM_DOMAIN", "").strip().rstrip(".").strip()
    given = [x.strip() for x in os.environ.get("DIRECTORY_DOMAINS", "").split(",") if norm(x)]
    directories = [norm(x) for x in given]
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
    overlap = (realm_overlap(realm, given, others, os.environ.get("LOCAL_DOMAIN", ""), os.environ.get("BROKER_TENANT", ""))
               or broker_overlap(os.environ.get("BROKER_TENANT", ""), given, os.environ.get("LOCAL_DOMAIN", "")))
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
    if removing and "OTHER_DOMAINS" not in os.environ:
        raise UsageError("--remove trusts the domains you declare: a directory left out of DIRECTORY_DOMAINS and typed "
                         "as REALM_DOMAIN reads as the realm, and its working grants would pass for removal. Name every "
                         "directory in DIRECTORY_DOMAINS, and state OTHER_DOMAINS, every other provider's domain, empty "
                         "when there is none (export OTHER_DOMAINS=)")
    if removing and not have_pyvmomi():
        raise UsageError("--remove reads who is signed in on the vCenter before it acts, which needs pyVmomi")
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
    if a.compare_permissions:
        _alone(a, "--compare-permissions")
        return compare_permissions(*a.compare_permissions)
    if a.save_permissions:
        _alone(a, "--save-permissions")
        return save_permissions(a.save_permissions)
    hosts, user, password, realm, directories = _settings(a)
    if a.remove:
        return _remove(hosts[0], user, password, realm, directories, _ids(a.remove), a.execute)
    if a.supervisor_vm:   # before the census and every probe: a name that is not one VM is found before anything is written
        supervisor_vm_check(os.environ.get("SUPERVISOR_VCENTER") or os.environ.get("PROBE_VCENTER") or hosts[0],
                            user, password, a.supervisor_vm)
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
                except ReadError as e:
                    row["sessions"] = {"error": str(e)}
                finally:
                    unsoap(si)
        else:
            row["sessions"] = "not read: pyVmomi is not installed"
        signed_in = (row["sessions"].get("byClass") or {}).get("realm spelling", 0) \
            if realm and isinstance(row["sessions"], dict) else 0
        if signed_in:
            row["realmSignedIn"] = True
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
        if row.get("realmSignedIn"):
            print(f"     NOT PLACED: {signed_in} live session(s) here are spelled in REALM_DOMAIN. A broker session "
                  "carries the directory's name, so REALM_DOMAIN names a domain people sign in with, and a grant "
                  "spelled in it may apply to them: check REALM_DOMAIN against the realm's name, and name every "
                  "directory in DIRECTORY_DOMAINS (exit 3)")
        clients = sum(n for k, n in row["byClass"].items() if k.rsplit(", ", 1)[0] == BROKER_CLASS)
        if clients:
            print(f"     {BROKER_CLASS}: {clients} grant(s) in {broker_tenant()}, the broker tenant: {BROKER_ADVICE}")
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
        else:
            print(f"     sessions {row['sessions']}")
        if realm and sessions_unread(row):
            print("     NOT PLACED: the session list was not read whole, so whether people sign in with REALM_DOMAIN's "
                  "domain is not known here, and a grant spelled in it is no finding until it is (exit 3)")
    record["roleDrift"] = drift(catalogs, L)
    if a.remove_probe_roles:
        record["probeRoleTeardown"] = {}
        print("\n  probe roles, one vCenter at a time:")
        for h in hosts:   # each vCenter's result printed as it is done, so a run that stops shows which were
            try:
                si = soap(h, user, password)
            except Exception as e:  # noqa: BLE001  that vCenter not reached: nothing sent there; the others still run
                t = {"removed": 0, "error": f"the session was refused ({type(e).__name__}); nothing was sent"}
            else:
                try:
                    t = remove_probe_roles(si)
                finally:
                    unsoap(si)
            record["probeRoleTeardown"][vc_label[h]] = t
            print(f"     {vc_label[h]}: {teardown_line(t)}", flush=True)
    print(f"\n  custom roles whose copies differ between vCenters: {len(record['roleDrift'])}")

    probe_host = os.environ.get("PROBE_VCENTER", hosts[0])
    test_user = os.environ.get("TEST_USER", "")
    subject = (test_user, secret("TEST_PASSWORD"))
    local, _, dom = test_user.partition("@")
    d_user, r_user = f"{dom.upper()}\\{local}", f"{realm.upper()}\\{local}"
    left_on_vm = []
    probes = []
    if a.probe_grants:
        group = os.environ["TEST_GROUP"]
        cases = [("group, directory spelling", f"{dom.upper()}\\{group}", True),
                 ("user, directory spelling", d_user, False),
                 ("user, realm spelling", r_user, False),
                 ("group, realm spelling", f"{realm.upper()}\\{group}", True)]
        nested = os.environ.get("TEST_LOCAL_GROUP", "").strip()
        if nested:
            cases.append(("group, nested in a local SSO group", f"{local_domain()}\\{nested}", True))
        probes.append(("grantProbe", probe_host, lambda: probe_grants(probe_host, (user, password), subject, cases)))
    if a.probe_tags:
        probes.append(("tagProbe", probe_host, lambda: probe_tags(probe_host, (user, password), subject, d_user, r_user)))
    if a.supervisor_vm:
        op_local, _, op_dom = user.partition("@")
        sup_host = os.environ.get("SUPERVISOR_VCENTER", probe_host)
        probes.append(("supervisorProbe", sup_host, lambda: probe_supervisor(
            sup_host, (user, password), subject, a.supervisor_vm, f"{op_dom.upper()}\\{op_local}",
            f"{realm.upper()}\\{op_local}", L)))
    halted = None
    for key, where, run in probes:
        label = vc_label.get(where, L.get("vcenter", where))
        if halted:   # a probe that stopped on an error leaves the ones after it unrun: nothing more is written
            record[key] = {"vcenter": label, "aborted": f"not run: {halted} stopped on an error before it; nothing was sent"}
            continue
        try:
            rec = run()
        except Exception as e:  # noqa: BLE001  the probe's own sign-in failed before it wrote anything
            rec = {"aborted": f"the probe did not start: {type(e).__name__}; nothing was sent"}
        left_on_vm += rec.pop("leftOnVm", [])
        record[key] = {"vcenter": label, **rec}
        if rec.get("stopped"):
            halted = key
    for key, rec in ((k, record[k]) for k in ("grantProbe", "tagProbe", "supervisorProbe") if k in record):
        print(f"\n  {key}: " + probe_line(key, rec))
        if rec.get("aborted"):
            print(f"     NOT RUN: {rec['aborted']}")
        if rec.get("stopped"):
            print(f"     STOPPED: {rec['stopped']}. Its removals ran as the probe stopped, and its residue was read back "
                  "(next line); any probe after it was not run")
        if rec.get("stopped") or probe_residue(rec) or probe_unread(rec):
            print(f"     residue {rec.get('residue')} (True or a count: left behind; None: not read back). Read the vCenter "
                  f"for folders named authz-run-*, tag categories of that name, and grants of the {len(PROBE_ROLE_NAMES)} "
                  "authz-probe-* roles" + (", and remove these grants the probe made on the VM (printed here only, never "
                                           "recorded): " + ", ".join(left_on_vm) if key == "supervisorProbe" and left_on_vm
                                           else ""))

    record["exit"] = code = exit_code(record, realm)
    text = json.dumps(record, indent=1, ensure_ascii=False)
    estate = set(hosts) | {user, local, dom, realm, test_user, os.environ.get("TEST_GROUP", ""), a.supervisor_vm,
                           os.environ.get("TEST_LOCAL_GROUP", ""),
                           user.partition("@")[0]} | set(directories) | declared | set(L.words())
    estate |= {h.split(".")[0] for h in hosts}
    for value in sorted({v for v in estate if v and v not in PRODUCT_ROLES | PRODUCT_LOCAL}, key=len, reverse=True):
        if re.search(r"(?<![A-Za-z0-9-])" + re.escape(value) + r"(?![A-Za-z0-9-])", text, re.IGNORECASE):
            shape = re.sub(r"[A-Za-z]", "a", re.sub(r"[0-9]", "9", value))
            return refused_record(f"an estate value ({len(value)} characters, shape {shape}) reached the record", code)
    if any(s and s in text for s in (password, subject[1])):
        return refused_record("a password reached the record", code)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "authz.json"), "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print("\nwrote authz.json: counts, classes and outcomes, with every estate name replaced")
    if unread:
        print(f"NOT READ: {len(unread)} vCenter(s); nothing is known about their grants")
    print(f"exit {code}")
    return code


def refused_record(why, code):
    """A record the scrub refused: nothing is written, and the run's own code stands (G-456), because the census read,
    and the probes or --remove-probe-roles may already have written. A run that found nothing to act on exits 3: its
    record was not written, so nothing shows what it read. Never 5, which would say nothing was read or sent."""
    code = code if code != EXIT_OK else EXIT_UNREAD
    print(f"refusing to write authz.json: {why}; nothing is written; exit {code}: "
          + ("the run's own code stands" if code != EXIT_UNREAD else "the record that shows what the run read was not "
             "written"), file=sys.stderr)
    return code


def teardown_line(t):
    """One vCenter's --remove-probe-roles result, as the terminal shows it the moment that vCenter is done."""
    if t.get("refused"):
        return f"NOT HELD: refused, {t['refused']} (exit 2)"
    done = f"{t.get('removed', 0)} probe role(s) removed" + (f" ({', '.join(t['removedRoles'])})" if t.get("removedRoles") else "")
    if t.get("error"):
        left = t.get("rolesLeft")
        return (f"NOT READ: {t['error']}; {done} before it; "
                + ("the role list was not read back" if left is None else f"{left} probe role(s) listed after it") + " (exit 3)")
    if t.get("rolesLeft") is None:
        return f"{done}; NOT READ: the role list was not read back (exit 3)"
    if t["rolesLeft"]:
        return f"NOT HELD: {done}, and {t['rolesLeft']} probe role(s) still listed after the removal (exit 2)"
    groups = t.get("reservedGroupsLeft")
    return (f"{done}, none listed after; "
            + ("the reserved groups VCF left were not read" if groups is None
               else f"{groups} reserved group(s) VCF left behind, removed by the vCenter's SSO administrator"))


def probe_line(key, rec):
    """A probe's cases, as the terminal shows them."""
    if key == "grantProbe":
        return str([(c["case"], c.get("check"), c.get("enforced")) for c in rec.get("cases", [])])
    if key == "tagProbe":
        return str([(c["case"], c.get("attached")) for c in rec.get("cases", [])])
    return (json.dumps(rec.get("identities", {})) + "; grant attempts "
            + str([(g["attempt"], g.get("result")) for g in rec.get("grantAttempts", [])]))


def probe_residue(rec):
    """Whether a probe left something behind: its folder, its tag category, a grant it made on the Supervisor VM, or a
    grant of a probe role (one there before the probe began is counted too: the probe then sent nothing)."""
    res = (rec or {}).get("residue") or {}
    return any(res.get(k) for k in ("folder", "category", "grantsOnVm", "grantsOfProbeRoles"))


def probe_unread(rec):
    """Whether a probe's residue read did not read: a value None is a residue not read back, never a clean run."""
    return any(v is None for v in ((rec or {}).get("residue") or {}).values())


def teardown_unread(t):
    """Whether one vCenter's --remove-probe-roles did not finish or was not read back: an error, or no role list read
    after the removal (a refusal sent nothing and is exit 2, never this)."""
    return not t.get("refused") and (bool(t.get("error")) or t.get("rolesLeft") is None)


def sessions_unread(row):
    """Whether a vCenter whose grants were read had its session list read whole: a list refused, one holding only the
    reader's own sessions, or none read (pyVmomi not installed, or no session read recorded) is not."""
    s = row.get("sessions")
    return "error" not in row and (not isinstance(s, dict) or "error" in s)


def exit_code(record, realm):
    """The first that applies: 2 a probe left residue, or --remove-probe-roles was refused or did not hold; 1
    realm-spelled grants read (only with a realm, only when every vCenter read had its session list read whole, and
    none while a live session is spelled in it); 3 a vCenter not read, a session list not read whole (with a realm,
    pyVmomi missing among them: whether people sign in with the realm's domain is then not known), a vCenter whose
    domains named no grant or whose realm named none beside an unplaced domain, a live session spelled in the realm (a
    grant spelled in it may then apply to someone, so the realm-spelled grants are no finding), a probe that could not
    run, or a residue not read back; else 0."""
    probes = [record.get(k) for k in ("grantProbe", "tagProbe", "supervisorProbe") if record.get(k) is not None]
    teardown = list((record.get("probeRoleTeardown") or {}).values())
    if any(probe_residue(p) for p in probes) or any(t.get("refused") or t.get("rolesLeft") for t in teardown):
        return EXIT_NOT_HELD
    rows = list((record.get("vcenters") or {}).values())
    signed_in = any(r.get("realmSignedIn") for r in rows)
    sessions_short = any(sessions_unread(r) for r in rows)
    if realm and not signed_in and not sessions_short and any(
            n for r in rows for k, n in (r.get("byClass") or {}).items() if k.startswith("realm spelling")):
        return EXIT_REALM
    unread = (not rows or signed_in or any("error" in r for r in rows)
              or any(r.get("domainsNamedNothing") or r.get("realmNamedNothing") for r in rows)
              or any(isinstance(r.get("sessions"), dict) and "error" in r["sessions"] for r in rows)
              or (bool(realm) and sessions_short)
              or any(p.get("aborted") or p.get("stopped") or probe_unread(p) for p in probes)
              or any(teardown_unread(t) for t in teardown))
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
        try:
            names = session_names(host, user, password)
        except ReadError as e:
            print(f"{host}: NOT READ: {e}; --remove acts only once it has read who is signed in, so nothing was sent "
                  "(exit 3)", file=sys.stderr)
            return EXIT_UNREAD
        signed = realm_sessions(names, realm)
        if signed:
            users = {n.rpartition("\\")[2].strip().lower() for n in signed}
            used = [p for p in plan if str(p["info"]["principal"].get("type", "")).upper() == "USER"
                    and str(p["info"]["principal"].get("name", "")).strip().lower() in users]
            print(f"refused, nothing sent: {len(signed)} live session(s) on {host} are spelled in REALM_DOMAIN "
                  f"({realm})" + (f", and {len(used)} of the grants named here are made to a user signed in now"
                                  if used else "")
                  + ". A broker session carries the directory's name, so this domain is one people sign in with, and "
                    "a grant spelled in it may apply to them. Check REALM_DOMAIN against the realm's name, and name every "
                    "directory in DIRECTORY_DOMAINS (exit 3)", file=sys.stderr)
            return EXIT_UNREAD
        print(f"authz.py --remove on {host}: {len(plan)} realm-spelled grant(s), printed here only; no live session "
              "is spelled in REALM_DOMAIN")
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


# ---------------------------------------------------------------- a saved permission list, and its compare

SAVE_KIND = "authz.py --save-permissions"
SAVE_FORMAT = 1
GRANT_FIELDS = {"vcenter": str, "entity": dict, "principal": str, "principalType": str, "role": str, "propagate": bool}


def host_key(host):
    """A vCenter as the compare matches it across two files: trimmed, a trailing dot dropped, without regard to case."""
    return norm(host)


def principal_key(principal):
    """A principal as the compare matches it: its domain as norm() reads one, and its name without regard to case."""
    domain, _, name = str(principal).rpartition("\\")
    return f"{norm(domain)}\\{name.strip().lower()}"


def by_key(grants):
    """Grants grouped by the grant key. vSphere's list can carry one grant more than once under different permission ids,
    identical in every other field (one key on one vCenter of the reference estate held two), so a key may hold several."""
    out = collections.defaultdict(list)
    for g in grants:
        out[compare_key(g)].append(g)
    return out


def shared_keys(grants):
    """How many grant keys hold more than one grant."""
    return sum(1 for v in by_key(grants).values() if len(v) > 1)


def compare_key(g):
    """The grant key: the vCenter, the entity (its type and id), the principal (its name and whether it is a user or a
    group, since vSphere keeps a user's and a group's grant of one name apart) and the role id. What else a grant carries,
    whether it propagates, is what a compare reports as changed."""
    return (host_key(g["vcenter"]), str(g["entity"].get("type")), str(g["entity"].get("id")), principal_key(g["principal"]),
            str(g["principalType"]).upper(), str(g["role"]))


def saved_grant(host, p, cat):
    """One grant as --save-permissions writes it: the vCenter, the entity, the principal as vCenter spells it in the
    grant (DOMAIN\\name, as a broker session must match it), user or group, the role's id and name, whether it
    propagates, and the permission's id. A grant without one of those fields is a list not read (ReadError)."""
    try:
        info, who, obj = p["info"], p["info"]["principal"], p["info"]["object"]
        g = {"vcenter": host, "entity": {"type": str(obj["type"]), "id": str(obj["id"])},
             "principal": f"{who['domain']}\\{who['name']}", "principalType": str(who["type"]).upper(),
             "role": str(info["role"]), "roleName": (cat.get(str(info["role"])) or {}).get("name"),
             "propagate": bool(info.get("propagating")), "permission": str(p["permission"])}
    except (KeyError, TypeError):
        raise ReadError("a permission in the list lacks its principal, object, role or id") from None
    return g


def digest(grants):
    """A digest of the grants as written, so the compare can tell a file edited after --save-permissions wrote it."""
    import hashlib
    return hashlib.sha256(json.dumps(grants, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def inside_a_clone(path):
    """Whether ``path`` lies inside the git work tree that holds this script: a saved list names every principal on the
    estate, and a file inside a clone is one commit away from being published."""
    here = os.path.dirname(os.path.abspath(__file__))
    while True:
        if os.path.exists(os.path.join(here, ".git")):
            root = os.path.realpath(here)
            target = os.path.realpath(os.path.dirname(os.path.abspath(path)))
            return target == root or target.startswith(root + os.sep)
        parent = os.path.dirname(here)
        if parent == here:
            return False
        here = parent


def save_permissions(path):
    """--save-permissions FILE: every grant on every vCenter VC_HOSTS names, each permission list read whole by the
    pager the census uses (and the role catalog, for the roles' names), written to FILE, a new file of mode 0600. The
    file names every principal as vCenter spells it: it is never scrubbed, and it is never published. A list not read
    whole on any vCenter writes nothing (exit 3). It carries its own header and totals, so --compare-permissions can
    tell a file this command wrote, whole, from any other."""
    hosts = _hosts()
    user, password = os.environ.get("VC_USER", "").strip(), secret("VC_PASSWORD")
    if not hosts or not user or not password:
        raise UsageError("--save-permissions needs VC_HOSTS, VC_USER and VC_PASSWORD_FILE (or VC_PASSWORD)")
    if os.path.lexists(path):
        raise UsageError(f"--save-permissions writes a new file, and {path} exists: name another, so a list saved before a "
                         "change is never written over")
    if not os.path.isdir(os.path.dirname(os.path.abspath(path))):
        raise UsageError(f"--save-permissions: the directory for {path} does not exist")
    if inside_a_clone(path):
        raise UsageError("--save-permissions writes every principal's name: write FILE outside the clone (for example under "
                         "~/.vcf), where no commit can carry it")
    print(f"authz.py --save-permissions: every grant on {len(hosts)} vCenter(s), each list read whole, for {path}")
    grants, header, unread = [], {}, []
    for h in hosts:
        rest = Rest(h, user, password)
        if rest.token is None:
            unread.append(h)
            print(f"  {h}: NOT READ: the vSphere Automation API refused the session")
            continue
        try:
            perms, cat = permissions(rest), roles(rest)
            mine = [saved_grant(h, p, cat) for p in perms]
        except ReadError as e:
            unread.append(h)
            print(f"  {h}: NOT READ: {e}")
            continue
        finally:
            rest.close()
        grants += mine
        shared = shared_keys(mine)
        header[h] = {"grants": len(mine), "global": sum(1 for g in mine if g["entity"]["type"] == "GlobalAcl"),
                     "roles": len(cat), "sharedKeys": shared}
        print(f"  {h}: {len(mine)} grants ({header[h]['global']} global), {len(cat)} roles, every page read"
              + (f"; {shared} grant key(s) listed under more than one permission id, compared by count" if shared else ""))
    if unread:
        print(f"NOT READ: {len(unread)} vCenter(s); nothing was written, because a saved list that misses a vCenter's "
              "grants would compare as removals (exit 3)", file=sys.stderr)
        return EXIT_UNREAD
    doc = {"kind": SAVE_KIND, "format": SAVE_FORMAT,
           "note": "every grant, each principal named as vCenter spells it: keep this file on your own disk, never publish it",
           "saved_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "vcenters": header,
           "totals": {"vcenters": len(header), "grants": len(grants)}, "grantsSha256": digest(grants), "grants": grants}
    write_new(path, json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {path}, mode 0600: {len(grants)} grants on {len(header)} vCenter(s), every principal named; it is never "
          "scrubbed, so keep it on your own disk\nexit 0")
    return EXIT_OK


def write_new(path, text):
    """Write a new file of mode 0600 whole, or nothing: a temporary file beside it, created 0600, then linked to the
    name, which fails rather than replace a file that appeared meanwhile."""
    d = os.path.dirname(os.path.abspath(path))
    tmp = os.path.join(d, f".{os.path.basename(path)}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.link(tmp, path)
        except FileExistsError:
            raise UsageError(f"{path} appeared while the lists were read; nothing was written over it") from None
    finally:
        with contextlib.suppress(OSError):
            os.unlink(tmp)


def load_saved(path):
    """A file --save-permissions wrote, whole, or the reason it is not one (ReadError, exit 3): unreadable, not JSON,
    another kind or format, a grant without its fields, totals or per-vCenter counts that disagree with its grants, a
    digest that does not match (edited after it was written)."""
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, UnicodeDecodeError, ValueError) as e:
        raise ReadError(f"{path} was not read: {type(e).__name__}") from None
    if not isinstance(doc, dict) or doc.get("kind") != SAVE_KIND or doc.get("format") != SAVE_FORMAT:
        raise ReadError(f"{path} is not a file --save-permissions wrote (its kind or format is not {SAVE_KIND!r}, "
                        f"format {SAVE_FORMAT})")
    grants, header, totals = doc.get("grants"), doc.get("vcenters"), doc.get("totals")
    if not isinstance(grants, list) or not isinstance(header, dict) or not isinstance(totals, dict):
        raise ReadError(f"{path} is partial: its grants, vCenters or totals are missing")
    for g in grants:
        if not isinstance(g, dict) or any(not isinstance(g.get(k), t) for k, t in GRANT_FIELDS.items()):
            raise ReadError(f"{path} is partial: a grant lacks one of {', '.join(GRANT_FIELDS)}")
    counts = collections.Counter(g["vcenter"] for g in grants)
    if (totals.get("grants") != len(grants) or totals.get("vcenters") != len(header) or set(counts) - set(header)
            or any(not isinstance(v, dict) or v.get("grants") != counts.get(h, 0) for h, v in header.items())):
        raise ReadError(f"{path} is partial: its totals do not match the grants it holds")
    if doc.get("grantsSha256") != digest(grants):
        raise ReadError(f"{path} was changed after --save-permissions wrote it (its digest does not match its grants)")
    return doc


def grant_text(g):
    """One saved grant as the compare prints it, on the terminal only."""
    role = f"{g.get('roleName')} ({g['role']})" if g.get("roleName") else g["role"]
    return (f"{g['entity']['type']} {g['entity']['id']}: {g['principal']} ({g['principalType']}), role {role}, "
            f"{'propagating' if g['propagate'] else 'not propagating'}")


def compare_vcenter(before, after):
    """One vCenter's two grant lists, compared by the grant key: (added, removed, changed, count before, count after).
    A key held by one grant on each side is changed when it started or stopped propagating. A key held by several grants
    on either side (one grant listed under two ids) is compared by count, for each propagation, and each grant added or
    removed there is marked as one of several under its key."""
    b, f = by_key(before), by_key(after)
    added, removed, changed = [], [], []
    for k in sorted(set(b) | set(f)):
        gb, gf = b.get(k, []), f.get(k, [])
        if len(gb) == len(gf) == 1:
            if gb[0]["propagate"] != gf[0]["propagate"]:
                changed.append((gb[0], gf[0]))
            continue
        note = f" (one of {max(len(gb), len(gf))} grants listed under this key)" if max(len(gb), len(gf)) > 1 else ""
        cb, cf = collections.Counter(g["propagate"] for g in gb), collections.Counter(g["propagate"] for g in gf)
        for prop, n in sorted((cf - cb).items()):
            added += [(next(g for g in gf if g["propagate"] == prop), note)] * n
        for prop, n in sorted((cb - cf).items()):
            removed += [(next(g for g in gb if g["propagate"] == prop), note)] * n
    return added, removed, changed, len(before), len(after)


def compare_permissions(before_path, after_path):
    """--compare-permissions BEFORE AFTER: two files --save-permissions wrote, compared by the grant key on every vCenter
    both read. Exit, the first that applies: 3 a file unreadable, partial or not written by --save-permissions (nothing
    compared); 5 BEFORE saved after AFTER; 1 a grant added, removed or changed on a vCenter both read; 3 a vCenter read
    in one file only (it could not be compared, so the files are not shown equal), or none in common; 0 none."""
    print("authz.py --compare-permissions: grant by grant, on every vCenter both files read (printed here only)")
    try:
        before, after = load_saved(before_path), load_saved(after_path)
    except ReadError as e:
        print(f"NOT READ: {e}; nothing was compared (exit 3)", file=sys.stderr)
        return EXIT_UNREAD
    for label, doc in (("BEFORE", before), ("AFTER", after)):
        print(f"  {label}: saved {doc.get('saved_utc')}, {doc['totals']['vcenters']} vCenter(s), {doc['totals']['grants']} "
              "grants")
    if str(before.get("saved_utc")) > str(after.get("saved_utc")):
        print("BEFORE was saved after AFTER: name the earlier file first, or every addition reads as a removal (exit 5)",
              file=sys.stderr)
        return EXIT_USAGE
    hb = {host_key(h): h for h in before["vcenters"]}
    ha = {host_key(h): h for h in after["vcenters"]}
    common = sorted(set(hb) & set(ha))
    differ = 0
    for hk in common:
        added, removed, changed, nb, nf = compare_vcenter([g for g in before["grants"] if host_key(g["vcenter"]) == hk],
                                                          [g for g in after["grants"] if host_key(g["vcenter"]) == hk])
        differ += len(added) + len(removed) + len(changed)
        print(f"  {ha[hk]}: {len(added)} added, {len(removed)} removed, {len(changed)} changed, of {nb} and {nf} grants")
        for g, note in added:
            print(f"    + {grant_text(g)}{note}")
        for g, note in removed:
            print(f"    - {grant_text(g)}{note}")
        for old, new in changed:
            print(f"    ~ {grant_text(new)} (was {'propagating' if old['propagate'] else 'not propagating'})")
    only = [f"{hb[k]} (BEFORE only)" for k in sorted(set(hb) - set(ha))] + \
           [f"{ha[k]} (AFTER only)" for k in sorted(set(ha) - set(hb))]
    if only:
        print("  NOT COMPARED, read in one file only: " + ", ".join(only))
    if differ:
        print(f"{differ} grant(s) differ" + (", and some vCenters were not compared" if only else "") + "\nexit 1")
        return EXIT_DIFFER
    if only or not common:
        print("no difference on the vCenters both files read, but " + ("none is in both" if not common else
              "not every vCenter was compared") + ": the files are not shown equal (exit 3)")
        return EXIT_UNREAD
    print(f"no grant added, removed or changed on {len(common)} vCenter(s)\nexit 0")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
