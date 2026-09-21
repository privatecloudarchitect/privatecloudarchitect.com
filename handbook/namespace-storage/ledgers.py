#!/usr/bin/env python3
"""ledgers.py: ask every plane that will answer "how much storage is used" and put the answers side by side.

This platform keeps several storage ledgers and they do not agree. That is not a defect; they answer different
questions. It becomes a defect the moment somebody makes a capacity decision from whichever one their tooling
happened to reach, so this reads as many as your credentials allow, on one day, and prints them together:

  1. TENANT CLAIMED: what the volume claims in every namespace actually ask for. The smallest honest number;
  2. TENANT GRANTED: the region storage-class quota's consumption figure. This is the number quotas and tenants
     are governed by, and the script checks what it is actually counting by summing the namespaces' storage
     limits and comparing. On the reference estate it is the limits, exactly, and not the claims;
  3. PROVIDER ALLOCATION: the provider plane's storageConsumedMiB. Needs a provider bearer;
  4. PHYSICAL: datastore capacity and free space from vCenter. Needs a vCenter session.

Each one is optional. With only a tenant bearer you still get the first two and the check between them, which
is the pair most often confused. Anything the script cannot reach it names rather than omits, because a
comparison missing a column silently becomes a different comparison.

Read-only throughout.

Run:
  export VCFA_HOST=<automation-fqdn> VCFA_ORG=<org>
  export VCFA_REFRESH_TOKEN_FILE=/path/to/refresh-token      # mode 0600, the tenant bearer
  export VCFA_PROVIDER_BEARER_FILE=/path/to/provider-bearer  # optional, for the provider ledger
  export VCENTER_HOST=<vcenter-fqdn>                         # optional, for the physical ledger
  export VCENTER_SESSION_FILE=/path/to/session-id            # optional, a vmware-api-session-id
  export TLS_VERIFY=false                                    # only on a self-signed lab CA
  python3 ledgers.py
"""
import http.client
import json
import os
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

http.client._MAXHEADERS = 1000
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
CCI = "/cci/kubernetes"
I1 = "infrastructure.cci.vmware.com/v1alpha1"
A3 = "infrastructure.cci.vmware.com/v1alpha3"
PROJ = "project.cci.vmware.com/v1alpha2"
MIB = 1024 * 1024


def ctx():
    verify = os.environ.get("TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")
    return ssl.create_default_context() if verify else ssl._create_unverified_context()


def mib(q):
    """A Kubernetes quantity in mebibytes. 20Gi is 20480, 900000Mi is 900000, a bare integer is bytes."""
    m = re.match(r"^\s*(\d+)\s*([KMGTP]i?)?\s*$", str(q or "0"))
    if not m:
        return 0
    n, u = int(m.group(1)), (m.group(2) or "")
    return {"": n // MIB, "Ki": n // 1024, "Mi": n, "Gi": n * 1024, "Ti": n * 1024 * 1024,
            "K": n // 1024, "M": n, "G": n * 1024, "T": n * 1024 * 1024}.get(u, n)


def tib(m):
    """Mebibytes as tebibytes. 1 TiB is 1048576 MiB, not a million."""
    return round(m / MIB, 2)


class Labels:
    RESERVED = {"admin", "view", "edit", "user", "users", "group", "default", "system", "none", "all"}

    def __init__(self):
        self.maps = {}

    def get(self, family, name):
        if not name or str(name) in self.RESERVED:
            return name
        m = self.maps.setdefault(family, {})
        if name not in m:
            m[name] = f"{family}-{len(m) + 1}"
        return "{{%s}}" % m[name]

    def scrub(self, text):
        if not isinstance(text, str):
            return text
        known = [(r, l) for m in self.maps.values() for r, l in m.items()]
        for real, label in sorted(known, key=lambda kv: -len(kv[0])):
            text = re.sub(r"(?<![A-Za-z0-9-])" + re.escape(real) + r"(?![A-Za-z0-9-])", "{{%s}}" % label, text)
        return UUID.sub("{{id}}", text)


def fetch(url, headers):
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, context=ctx(), timeout=90) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw.decode(errors="replace")[:200]
    except (urllib.error.URLError, OSError) as e:
        return None, str(e)[:160]


def main():
    host, org = os.environ["VCFA_HOST"], os.environ["VCFA_ORG"]
    refresh = open(os.environ["VCFA_REFRESH_TOKEN_FILE"], encoding="utf-8").read().strip()
    out_dir = os.environ.get("OUT_DIR", ".")
    L = Labels()
    body = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": refresh}).encode()
    req = urllib.request.Request(f"https://{host}/oauth/tenant/{org}/token", data=body, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded",
                                          "Accept": "application/json"})
    with urllib.request.urlopen(req, context=ctx(), timeout=30) as r:
        bearer = json.loads(r.read())["access_token"]
    H = {"Authorization": f"Bearer {bearer}", "Accept": "application/json"}
    gw = lambda p: fetch(f"https://{host}{CCI}{p}", H)
    print("ledgers.py: every plane that will answer how much storage is used\n")

    # ---- 2. tenant granted, and what it is actually counting
    st, q = gw(f"/apis/{I1}/regionstorageclassquotas")
    quotas = []
    for it in ((q.get("items") or []) if st == 200 else []):
        sp, stt = it.get("spec") or {}, it.get("status") or {}
        L.get("storageclass", sp.get("storageClassName"))
        quotas.append({"storageClass": L.scrub(sp.get("storageClassName") or ""),
                       "capacityMiB": mib(sp.get("storageCapacity")),
                       "consumedMiB": mib(stt.get("storageConsumed")),
                       "zones": len(sp.get("zones") or [])})
    granted = sum(x["consumedMiB"] for x in quotas)

    # ---- 1. tenant claimed, and the namespaces' own storage limits
    st, pl = gw(f"/apis/{PROJ}/projects")
    projects = [p["metadata"]["name"] for p in ((pl.get("items") or []) if st == 200 else [])]
    limits, claimed, claims_n, namespaces = 0, 0, 0, 0
    for p in projects:
        L.get("project", p)
        st, nss = gw(f"/apis/{A3}/namespaces/{p}/supervisornamespaces")
        for n in ((nss.get("items") or []) if st == 200 else []):
            namespaces += 1
            ns = n["metadata"]["name"]
            L.get("namespace", ns)
            for s_ in (((n.get("spec") or {}).get("classConfigOverrides") or {}).get("storageClasses") or []):
                limits += mib(s_.get("limit"))
            url = (n.get("status") or {}).get("namespaceEndpointURL")
            if not url:
                continue
            st2, pv = fetch(url.rstrip("/") + f"/api/v1/namespaces/{ns}/persistentvolumeclaims", H)
            for c in ((pv.get("items") or []) if st2 == 200 else []):
                claims_n += 1
                claimed += mib(((c.get("spec") or {}).get("resources") or {}).get("requests", {}).get("storage"))

    counting = ("the namespaces' storage limits" if granted == limits else
                "the volume claims" if granted == claimed else "neither, which is worth investigating")
    print(f"  TENANT CLAIMED   {claimed:>12,} MiB ({tib(claimed):>6} TiB)  from {claims_n} volume claim(s)")
    print(f"  TENANT GRANTED   {granted:>12,} MiB ({tib(granted):>6} TiB)  the quota ledger's own figure")
    print(f"     the namespaces' storage limits sum to {limits:,} MiB, so the quota ledger is counting {counting}")

    # ---- 3. provider allocation
    provider = None
    pb = None
    pf = os.environ.get("VCFA_PROVIDER_BEARER_FILE")
    if pf and os.path.exists(pf):
        pb = open(pf, encoding="utf-8").read().strip()
        st, sc = fetch(f"https://{host}/cloudapi/v1/storageClasses",
                       {"Authorization": f"Bearer {pb}", "Accept": "application/json;version=40.0"})
        vals = (sc.get("values") or []) if isinstance(sc, dict) else []
        if vals:
            provider = []
            for v in vals:
                L.get("storageclass", v.get("name"))
                cap, con = int(v.get("storageCapacityMiB") or 0), int(v.get("storageConsumedMiB") or 0)
                zs = v.get("zones")
                provider.append({"storageClass": L.scrub(v.get("name") or ""), "capacityMiB": cap,
                                 "consumedMiB": con, "ratio": round(con / cap, 3) if cap else None,
                                 "zones": len(zs) if isinstance(zs, list) else
                                          len((zs or {}).get("values") or []) if isinstance(zs, dict) else 0})
            # Do NOT sum these. On the reference estate two classes report byte-identical capacity AND
            # consumption, which means they are reporting the same underlying storage twice, so a total is
            # an invented number. Report the largest single class and say how many duplicated it.
            dupes = len(provider) - len({(x["capacityMiB"], x["consumedMiB"]) for x in provider})
            tot = max(x["consumedMiB"] for x in provider)
            print(f"  PROVIDER ALLOC   {tot:>12,} MiB ({tib(tot):>6} TiB)  largest of {len(provider)} class(es)"
                  + (f"; {dupes} report figures identical to another class, so these do not add up" if dupes else ""))
            for x in provider:
                print(f"     class capacity {x['capacityMiB']:>10,} consumed {x['consumedMiB']:>11,} "
                      f"ratio {x['ratio']} zones {x['zones']}")
        else:
            print(f"  PROVIDER ALLOC   not read (HTTP {st})")
    else:
        print("  PROVIDER ALLOC   not read: set VCFA_PROVIDER_BEARER_FILE to include it")

    # ---- 4. physical
    physical = None
    sid = None
    vh, vsf = os.environ.get("VCENTER_HOST"), os.environ.get("VCENTER_SESSION_FILE")
    if vh and vsf and os.path.exists(vsf):
        sid = open(vsf, encoding="utf-8").read().strip()
        st, ds = fetch(f"https://{vh}/api/vcenter/datastore", {"vmware-api-session-id": sid})
        items = ds if isinstance(ds, list) else []
        if items:
            cap = sum(int(d.get("capacity") or 0) for d in items)
            free = sum(int(d.get("free_space") or 0) for d in items)
            physical = {"datastores": len(items), "capacityMiB": cap // MIB, "usedMiB": (cap - free) // MIB,
                        "types": sorted({str(d.get("type")) for d in items})}
            print(f"  PHYSICAL         {physical['usedMiB']:>12,} MiB ({tib(physical['usedMiB']):>6} TiB) used "
                  f"of {tib(physical['capacityMiB'])} TiB across {len(items)} datastore(s)")
        else:
            print(f"  PHYSICAL         not read (HTTP {st})")
    else:
        print("  PHYSICAL         not read: set VCENTER_HOST and VCENTER_SESSION_FILE to include it")

    # A run that reached fewer ledgers than the record on disk does not get to overwrite it. This is the
    # G-166 problem, but the answer that fits G-166 elsewhere, carrying the missing block forward, is wrong
    # HERE: the whole argument of this record is that four ledgers were read on one estate in ONE RUN, which
    # is what makes their disagreement a fact about the planes rather than about the clock. A carried block
    # would sit under a fresh captured_utc and quietly make that claim false. So this one refuses, the way
    # recovery.py does, and says which credentials would have made the run complete.
    _reached = 2 + (1 if provider else 0) + (1 if physical else 0)
    _prior_path = os.path.join(out_dir, "ledgers.json")
    if os.path.exists(_prior_path):
        try:
            _prior = json.load(open(_prior_path, encoding="utf-8")) or {}
        except ValueError:
            _prior = {}
        _was = _prior.get("ledgersRead") or (2 + (1 if _prior.get("provider") else 0)
                                             + (1 if _prior.get("physical") else 0))
        if _was > _reached:
            _missing = [n for n, v in (("VCFA_PROVIDER_BEARER_FILE", provider),
                                       ("VCENTER_HOST + VCENTER_SESSION_FILE", physical)) if not v]
            raise SystemExit(
                f"\nREFUSING to write: this run reached {_reached} of the four ledgers and the record on "
                f"disk was written from {_was}. Every figure in that record was read in one run, which is "
                f"what makes the spread a fact about the planes and not about the clock; replacing it with "
                f"a narrower read would keep the claim and lose the evidence for it. Set "
                + " and ".join(_missing) + ", or leave the existing record alone. A thinner read is not a "
                "newer truth.")

    figures = {"tenantClaimed": claimed, "tenantGranted": granted}
    if provider:
        figures["providerAllocation"] = max(x["consumedMiB"] for x in provider)
    if physical:
        figures["physicalUsed"] = physical["usedMiB"]
    lo, hi = min(figures.values()), max(figures.values())
    print(f"\n  {len(figures)} answers to one question, spanning {round(hi / lo, 1) if lo else '?'} times: "
          + ", ".join(f"{k} {tib(v)} TiB" for k, v in figures.items()))

    payload = {"captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "quotas": quotas, "namespaces": namespaces, "claims": claims_n,
               "tenantClaimedMiB": claimed, "tenantGrantedMiB": granted, "namespaceLimitsMiB": limits,
               "quotaLedgerCounts": counting, "provider": provider, "physical": physical,
               "providerClassesReportingIdenticalFigures":
                   (len(provider) - len({(x["capacityMiB"], x["consumedMiB"]) for x in provider})) if provider else None,
               "figures": figures, "spread": round(hi / lo, 1) if lo else None,
               "ledgersRead": _reached,
               "unitNote": "every figure is mebibytes; 1 TiB is 1048576 MiB, not a million"}

    text = L.scrub(UUID.sub("{{id}}", json.dumps(payload, indent=1, ensure_ascii=False)))
    for secret in (bearer, refresh, host, org, pb, vh, sid):
        assert not secret or secret not in text, "an estate value reached the record"
    bare = re.sub(r"\{\{[^}]*\}\}", "", text)
    for fam, m in L.maps.items():
        for nm in m:
            if nm and re.search(r"(?<![A-Za-z0-9-])" + re.escape(nm) + r"(?![A-Za-z0-9-])", bare):
                shp = re.sub(r"[A-Za-z]", "a", re.sub(r"[0-9]", "9", nm))
                raise SystemExit(f"FATAL: a {fam} name ({len(nm)} characters, shape {shp}) reached the record")
    os.makedirs(out_dir, exist_ok=True)
    open(os.path.join(out_dir, "ledgers.json"), "w", encoding="utf-8").write(text + "\n")
    print(f"\nwrote ledgers.json ({len(figures)} ledger(s) reached); every organization name replaced by a placeholder")


if __name__ == "__main__":
    main()
