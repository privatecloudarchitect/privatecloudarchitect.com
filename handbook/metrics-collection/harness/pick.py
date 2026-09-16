"""Shared object lookups for the harness: a VM by name, or the busiest VM by latest CPU MHz."""

import sys

from opslib import ops

STAT = "cpu|usagemhz_average"


def list_vms(tok):
    st, body = ops("GET", "/api/resources", tok, params={
        "resourceKind": "VirtualMachine", "adapterKind": "VMWARE",
        "pageSize": 1000, "_no_links": "true"})
    if st != 200:
        sys.exit(f"FATAL: list VMs -> HTTP {st}: {body}")
    return [(r["identifier"], r["resourceKey"]["name"], r) for r in body.get("resourceList", [])]


def find_vm(tok, name):
    for rid, rname, rec in list_vms(tok):
        if rname == name:
            return rid, rname, rec
    sys.exit(f"FATAL: no VirtualMachine named {name!r} is visible to this token")


def busiest_vm(tok):
    """The VM with the highest latest cpu|usagemhz_average (one latest-stats call for all VMs)."""
    vms = list_vms(tok)
    if not vms:
        sys.exit("no VirtualMachine resources visible to this token")
    st, body = ops("POST", "/api/resources/stats/latest/query", tok,
                   body={"resourceId": [v[0] for v in vms], "statKey": [STAT]},
                   params={"_no_links": "true"})
    if st != 200:
        sys.exit(f"FATAL: latest stats -> HTTP {st}: {body}")
    latest = {}
    for v in (body or {}).get("values", []):
        for s in v.get("stat-list", {}).get("stat", []):
            data = s.get("data") or []
            if data:
                latest[v["resourceId"]] = data[-1]
    if not latest:
        sys.exit("no VM reported cpu|usagemhz_average yet; give the instance a collection cycle")
    rid = max(latest, key=latest.get)
    return next(v for v in vms if v[0] == rid)


def pick(tok, argv):
    """--vm <name> if given, else the busiest VM."""
    if "--vm" in argv:
        return find_vm(tok, argv[argv.index("--vm") + 1])
    return busiest_vm(tok)
