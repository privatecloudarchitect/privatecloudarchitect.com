#!/usr/bin/env python3
"""identity_keys.py - the identifiers one VM carries, and the composite key that joins systems.

Reads the VM's resource identifiers from VCF Operations (VMEntityVCID, VMEntityObjectID,
VMEntityInstanceUUID, VMEntityName), resolves the vCenter adapter behind it (VCURL), and prints
the global object key the sheet recommends: (vcenter_instance_uuid, moid). The managed object
ID alone repeats in every vCenter; the pair is what the platform itself marks as unique.

Usage:  python3 identity_keys.py --vm <name>
Env:    see opslib.py (OPS_HOST, OPS_API_TOKEN, ...)
Exit:   0 both halves present · 1 a half is missing · 2 a read failed
"""

import sys

from opslib import bearer, ops
from pick import find_vm


def main():
    argv = sys.argv[1:]
    if "--vm" not in argv:
        sys.exit("usage: identity_keys.py --vm <name>")
    tok = bearer()
    rid, name, rec = find_vm(tok, argv[argv.index("--vm") + 1])
    ids = {}
    unique = set()
    for i in rec.get("resourceKey", {}).get("resourceIdentifiers", []):
        n = i["identifierType"]["name"]
        ids[n] = i.get("value")
        if i["identifierType"].get("isPartOfUniqueness"):
            unique.add(n)
    print(f"IDENTITY KEYS - {name}\n")
    print(f"  {'Operations identifier':26}{'value':42}part of uniqueness")
    print("  " + "-" * 82)
    for n in ("VMEntityVCID", "VMEntityObjectID", "VMEntityInstanceUUID", "VMEntityName"):
        print(f"  {n:26}{str(ids.get(n, '-')):42}{'yes' if n in unique else 'no'}")
    print(f"  {'Operations resource id':26}{rid:42}(internal to this instance)")

    st, body = ops("GET", "/api/adapters", tok, params={"adapterKindKey": "VMWARE", "_no_links": "true"})
    vcurl = "-"
    if st == 200:
        for a in body.get("adapterInstancesInfoDto", []):
            aids = {i["identifierType"]["name"]: i.get("value")
                    for i in a.get("resourceKey", {}).get("resourceIdentifiers", [])}
            if aids.get("VMEntityVCID") == ids.get("VMEntityVCID"):
                vcurl = aids.get("VCURL", "-")
    print(f"  {'vCenter adapter VCURL':26}{vcurl:42}(a name, resolves to the UUID above)")

    vc, mo = ids.get("VMEntityVCID"), ids.get("VMEntityObjectID")
    print(f"\n  composite key: (vcenter_instance_uuid, moid) = ({vc}, {mo})")
    print("  Real-Time Metrics carries the moid as a label and the vCenter half only as the query's"
          "\n  sourceId; the CMDB stores the same pair as vcenter_uuid and object_id (or morid).")
    if vc and mo:
        print("  both halves present: key every row on this pair, and carry the instance UUID as an attribute.")
        return 0
    print("  a half is missing on this record; check the adapter's identifiers before joining.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
