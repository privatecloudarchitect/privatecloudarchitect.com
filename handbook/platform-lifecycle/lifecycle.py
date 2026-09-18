#!/usr/bin/env python3
"""lifecycle.py: read the lifecycle planes on an instance and answer the one question that matters before a window.

The registry will tell you an upgrade is available. The depot decides whether it actually is. This reads both,
joins them, and reports the gap:

  1. the RELEASES the instance knows about;
  2. the BUNDLE DEPOT, counted by download status, because a bundle the platform knows about and has not
     downloaded is content you do not have;
  3. the UPGRADABLE STATE for the management domain, which is the handle for the whole instance: asking for a
     workload domain by its own id is refused, and the message says the management domain was not found, which
     reads like a missing object rather than a wrong argument;
  4. the JOIN, which is the point of the script: for every upgradable, whether the bundle behind it has
     actually been staged, and how many gigabytes are still to fetch if it has not. An upgrade offered with
     nothing downloaded is the failure this chapter exists to prevent, and it is two reads away from visible;
  5. the DEPOT CONFIGURATION, read through whichever endpoint this build still serves. On 9.1 the old one is
     retired and answers 410 with the name of its replacement, which is worth following rather than guessing.

Read-only throughout. Nothing here stages, prechecks or upgrades anything.

Run:
  export SDDC_HOST=<sddc-manager-fqdn>
  export SDDC_TOKEN_FILE=/path/to/bearer      # mode 0600
  export TLS_VERIFY=false                     # only on a self-signed lab CA
  python3 lifecycle.py
"""
import collections
import json
import os
import re
import ssl
import time
import urllib.error
import urllib.request

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def ctx():
    verify = os.environ.get("TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")
    return ssl.create_default_context() if verify else ssl._create_unverified_context()


class Labels:
    RESERVED = {"MANAGEMENT", "VI", "PENDING", "SUCCESSFUL", "FAILED", "VMWARE_SOFTWARE", "SDDC_MANAGER",
                "VCF_DEPOT", "default", "none", "all"}

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


def read_instance(host, token, L, label):
    """Every lifecycle plane on one instance, plus the join between what is offered and what is staged."""

    def get(path):
        rq = urllib.request.Request(f"https://{host}{path}",
                                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(rq, context=ctx(), timeout=90) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, {}
        except (urllib.error.URLError, OSError):
            return None, {}

    print(f"\n=== {label} ===")
    st, dom = get("/v1/domains")
    domains = (dom.get("elements") or []) if isinstance(dom, dict) else []
    mgmt = [d for d in domains if str(d.get("type")).upper() == "MANAGEMENT"]
    workload = [d for d in domains if str(d.get("type")).upper() != "MANAGEMENT"]
    for d in domains:
        L.get("domain", d.get("name"))
    print(f"  domains: {len(domains)} ({len(mgmt)} management, {len(workload)} workload)")
    if not mgmt:
        raise SystemExit("no management domain visible; the upgradable read keys on it")

    st, rel = get("/v1/releases")
    releases = (rel.get("elements") or []) if isinstance(rel, dict) else []
    st, bun = get("/v1/bundles")
    bundles = (bun.get("elements") or []) if isinstance(bun, dict) else []
    by_status = collections.Counter(b.get("downloadStatus") for b in bundles)
    by_id = {b.get("id"): b for b in bundles}
    print(f"  releases known: {len(releases)}")
    print(f"  bundles: {len(bundles)} -> {dict(by_status)}")

    st, up = get(f"/v1/upgradables/domains/{mgmt[0].get('id')}")
    ups = (up.get("elements") or []) if isinstance(up, dict) else []
    print(f"  upgradables on the management domain: {len(ups)}")

    # the workload-domain refusal, quoted rather than described
    refusal = None
    if workload:
        st_w, r_w = get(f"/v1/upgradables/domains/{workload[0].get('id')}")
        refusal = {"status": st_w, "message": L.scrub((r_w.get("message") if isinstance(r_w, dict) else "") or "")}
        print(f"  the same read for a workload domain: HTTP {st_w} "
              f"({refusal['message'][:60]})")

    # ---- the join
    # Size is summed over DISTINCT bundles. Several upgradables can reference one bundle, and adding a size
    # per upgradable counts that bundle's gigabytes more than once. The first version of this script did
    # exactly that and overstated the download by the size of the shared bundle.
    joined, seen_bundles = [], {}
    for e in ups:
        bid = e.get("bundleId")
        b = by_id.get(bid) or {}
        if bid and not b:
            st_b, b = get(f"/v1/bundles/{bid}")
            b = b if isinstance(b, dict) else {}
        staged = str(b.get("downloadStatus")) == "SUCCESSFUL"
        size = float(b.get("sizeMB") or 0)
        if bid:
            seen_bundles[bid] = (staged, size)
        joined.append({"upgradableStatus": e.get("status"), "bundleType": b.get("type"),
                       "downloadStatus": b.get("downloadStatus"), "sizeMB": round(size, 1), "staged": staged})
    unstaged_mb = sum(sz for st_, sz in seen_bundles.values() if not st_)
    staged_n = sum(1 for st_, _ in seen_bundles.values() if st_)
    distinct = len({e.get("bundleId") for e in ups if e.get("bundleId")})
    print(f"\n  THE JOIN: {len(ups)} upgradable(s) reference {distinct} distinct bundle(s); "
          f"{staged_n} of those bundles are staged")
    if joined and staged_n == 0:
        print(f"     none of the content is downloaded. {round(unstaged_mb / 1024, 1)} GB still to fetch before "
              f"any of this is actually available, whatever the registry says.")
    elif joined and staged_n < distinct:
        print(f"     partially staged; {round(unstaged_mb / 1024, 1)} GB still to fetch.")
    elif joined:
        print("     every offered upgrade has its content staged.")
    else:
        print("     nothing is offered, which on a current estate is the read you want to be able to produce.")

    # ---- the depot, through whichever endpoint this build serves
    depot = None
    st_d, r_d = get("/v1/system/settings/depot")
    if st_d == 410 and isinstance(r_d, dict):
        successor = (r_d.get("remediationMessage") or "")
        print(f"\n  depot settings: HTTP 410, and the platform names its own replacement: {successor[:70]}")
        m = re.search(r"(v1/[A-Za-z0-9/_-]+)", successor)
        if m:
            st_s, r_s = get("/" + m.group(1))
            svcs = (r_s.get("services") or []) if isinstance(r_s, dict) else []
            depot = {"via": m.group(1), "services": [{"type": s.get("type"),
                                                      "nodes": len(s.get("nodes") or [])} for s in svcs]}
            print(f"     following it: {len(svcs)} service(s) configured -> "
                  f"{[s.get('type') for s in svcs]}")
    elif st_d == 200:
        depot = {"via": "v1/system/settings/depot", "services": []}
        print("\n  depot settings: still served at the original path on this build")
    else:
        print(f"\n  depot settings: HTTP {st_d}")

    return {"label": label,
               "domains": {"total": len(domains), "management": len(mgmt), "workload": len(workload)},
               "releases": len(releases), "bundles": {"total": len(bundles), "byStatus": dict(by_status)},
               "upgradables": len(ups), "distinctBundlesOffered": distinct,
               "offeredAndStaged": staged_n, "unstagedGB": round(unstaged_mb / 1024, 1),
               "join": joined, "workloadDomainRefusal": refusal, "depot": depot}


def main():
    """Read the instance you are asked about, and, when a second is named, the one you rehearse on."""
    out_dir = os.environ.get("OUT_DIR", ".")
    L = Labels()
    print("lifecycle.py: is the upgrade the registry is offering actually available?")
    primary = read_instance(os.environ["SDDC_HOST"],
                            open(os.environ["SDDC_TOKEN_FILE"], encoding="utf-8").read().strip(),
                            L, "the instance asked about")
    instances = [primary]
    # The chapter's discipline is a rehearsal instance held behind production. Comparing the two is the
    # read that shows whether the stagger still exists, so the script takes a second host when you have one.
    rh, rt = os.environ.get("SDDC_REHEARSAL_HOST"), os.environ.get("SDDC_REHEARSAL_TOKEN_FILE")
    if rh and rt and os.path.exists(rt):
        instances.append(read_instance(rh, open(rt, encoding="utf-8").read().strip(), L, "the rehearsal instance"))
    else:
        print("\n  rehearsal instance: not read; set SDDC_REHEARSAL_HOST and SDDC_REHEARSAL_TOKEN_FILE to compare")
    if len(instances) > 1:
        a, b = instances[0], instances[1]
        print(f"\n  the stagger: {a['upgradables']} upgradable(s) on the instance asked about, "
              f"{b['upgradables']} on the rehearsal instance; staged bundles "
              f"{a['bundles']['byStatus'].get('SUCCESSFUL', 0)} against "
              f"{b['bundles']['byStatus'].get('SUCCESSFUL', 0)}")
    payload = {"captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "instances": instances}
    token = ""
    host = ""
    text = L.scrub(UUID.sub("{{id}}", json.dumps(payload, indent=1, ensure_ascii=False)))
    for secret in (os.environ.get("SDDC_HOST", ""), os.environ.get("SDDC_REHEARSAL_HOST", "")):
        assert secret and secret not in text or not secret, "an estate value reached the record"
    bare = re.sub(r"\{\{[^}]*\}\}", "", text)
    for fam, m in L.maps.items():
        for nm in m:
            if nm and re.search(r"(?<![A-Za-z0-9-])" + re.escape(nm) + r"(?![A-Za-z0-9-])", bare):
                shp = re.sub(r"[A-Za-z]", "a", re.sub(r"[0-9]", "9", nm))
                raise SystemExit(f"FATAL: a {fam} name ({len(nm)} characters, shape {shp}) reached the record")
    os.makedirs(out_dir, exist_ok=True)
    open(os.path.join(out_dir, "lifecycle.json"), "w", encoding="utf-8").write(text + "\n")
    print(f"\nwrote lifecycle.json ({len(instances)} instance(s) read); "
          f"every instance name replaced by a placeholder")


if __name__ == "__main__":
    main()
