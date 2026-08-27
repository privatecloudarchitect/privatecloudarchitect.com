#!/usr/bin/env python3
"""ad_fixtures.py: create (or tear down) throwaway Active Directory test fixtures.

The onboarding flow in ``e2e_tenant_setup.py`` IMPORTS an existing directory group;
it does not create one. When you need a disposable group + users to exercise that
flow end to end, this helper provisions them directly in Active Directory over LDAPS,
then removes them again with ``--teardown``.

This is deliberately SEPARATE from the onboarding reference: it needs the ``ldap3``
package (``pip install ldap3``) and a domain administrator, and its details are
Active-Directory-specific, whereas the onboarding flow is portable and standard
library only. Treat this as a test convenience, not part of the reference.

Configuration is by environment variable so no secret is ever on the command line:

  AD_HOST            the domain controller FQDN, e.g. ad.example.com          (required)
  AD_ADMIN           the bind identity, e.g. Administrator@example.com         (required)
  AD_ADMIN_SECRET    path to a JSON file with a {"password": "..."} key for AD_ADMIN
                     (required; source it from your secret store, never inline)
  AD_USER_SECRET     path to a JSON file with the {"password": "..."} to set on the
                     created users (defaults to AD_ADMIN_SECRET)
  AD_BASE_DN         base DN, e.g. DC=example,DC=com (optional; auto-discovered)
  AD_USERS_CONTAINER RDN of the container to create objects in (default: CN=Users)

Example (create), passwords sourced from a secret file, never typed:
  export AD_HOST=ad.example.com AD_ADMIN=Administrator@example.com
  export AD_ADMIN_SECRET=/path/to/ad-admin.json
  python3 ad_fixtures.py --group "Example AD Group" --users ExampleUser1,ExampleUser2

Teardown (removes exactly what it created):
  python3 ad_fixtures.py --group "Example AD Group" --users ExampleUser1,ExampleUser2 --teardown
"""
import argparse
import json
import os
import ssl
import sys

try:
    from ldap3 import ALL, MODIFY_REPLACE, Connection, Server, Tls
except ImportError:
    sys.exit("ad_fixtures.py needs the 'ldap3' package: pip install ldap3")

# Global security group; normal, enabled user account.
_GROUP_TYPE = -2147483646  # 0x80000002
_UAC_NORMAL_ENABLED = 512


def _require(var):
    val = os.environ.get(var)
    if not val:
        sys.exit(f"set the {var} environment variable (see the header of ad_fixtures.py)")
    return val


def _password(secret_path):
    return json.load(open(secret_path))["password"]


def _connect():
    host = _require("AD_HOST")
    admin = _require("AD_ADMIN")
    admin_pw = _password(_require("AD_ADMIN_SECRET"))
    tls = Tls(validate=ssl.CERT_NONE)  # lab self-signed CA
    server = Server(host, port=636, use_ssl=True, get_info=ALL, tls=tls)
    conn = Connection(server, user=admin, password=admin_pw, auto_bind=True)
    base = os.environ.get("AD_BASE_DN") or server.info.other.get("defaultNamingContext", [""])[0]
    if not base:
        sys.exit("could not determine the base DN; set AD_BASE_DN")
    return conn, base


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--group", required=True, help="the group's name (cn / sAMAccountName)")
    ap.add_argument("--users", required=True, help="comma-separated usernames to create")
    ap.add_argument("--teardown", action="store_true", help="delete the users and group instead")
    args = ap.parse_args()

    users = [u.strip() for u in args.users.split(",") if u.strip()]
    conn, base = _connect()
    container = os.environ.get("AD_USERS_CONTAINER", "CN=Users")
    domain = ".".join(p.split("=")[1] for p in base.split(","))  # DC=example,DC=com -> example.com
    group_dn = f"CN={args.group},{container},{base}"
    user_dns = {u: f"CN={u},{container},{base}" for u in users}
    print(f"# AD {os.environ['AD_HOST']} base {base}")

    if args.teardown:
        for u, dn in user_dns.items():
            ok = conn.delete(dn)
            print(f"[teardown] delete user {u}: {'ok' if ok else conn.result['description']}")
        ok = conn.delete(group_dn)
        print(f"[teardown] delete group {args.group!r}: {'ok' if ok else conn.result['description']}")
        conn.unbind()
        return 0

    # 1. group
    ok = conn.add(group_dn, ["top", "group"],
                  {"sAMAccountName": args.group, "groupType": _GROUP_TYPE})
    print(f"[1] create group {args.group!r}: {'ok' if ok else conn.result['description']}")

    # 2. users: create, set the password over LDAPS, enable, then add to the group.
    user_pw = _password(os.environ.get("AD_USER_SECRET") or _require("AD_ADMIN_SECRET"))
    for u, dn in user_dns.items():
        added = conn.add(dn, ["top", "person", "organizationalPerson", "user"],
                         {"sAMAccountName": u, "userPrincipalName": f"{u}@{domain}"})
        if not added and conn.result["description"] != "entryAlreadyExists":
            print(f"[2] create user {u}: FAILED {conn.result['description']}")
            continue
        conn.extend.microsoft.modify_password(dn, user_pw)
        conn.modify(dn, {"userAccountControl": [(MODIFY_REPLACE, [_UAC_NORMAL_ENABLED])]})
        conn.extend.microsoft.add_members_to_groups([dn], group_dn)
        print(f"[2] user {u}: created, password set, enabled, added to {args.group!r}")

    # 3. verify membership
    conn.search(group_dn, "(objectClass=group)", attributes=["member"])
    members = conn.entries[0].member.values if conn.entries else []
    print(f"[3] group {args.group!r} now has {len(members)} member(s)")
    conn.unbind()
    return 0


if __name__ == "__main__":
    sys.exit(main())
