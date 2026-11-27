#!/usr/bin/env python3
"""lifecycle.py: read the lifecycle planes on an instance and answer the one question that matters before a window.

The registry will tell you an upgrade is available. The depot decides whether it actually is. This reads both,
joins them, and reports the gap:

  1. the RELEASES the instance knows about;
  2. the BUNDLE DEPOT, counted by download status, because a bundle the platform knows about and has not
     downloaded is content you do not have;
  3. the UPGRADABLE STATE for the management domain, which is the handle for the whole instance: asking for a
     workload domain by its own id is refused, and the message says the management domain was not found, which
     reads like a missing object rather than a wrong argument. The read answers for a target release, so the script
     reads each domain's target and the releases the registry names applicable to it (its future releases), and asks
     the upgradable read again for each applicable one by name: an empty answer is never read as a current estate;
  4. the JOIN, which is the point of the script: for every upgradable, whether the bundle behind it has
     actually been staged, and how much is still to fetch if it has not, in the API's own unit (sizeMB). An upgrade offered with
     nothing downloaded is the failure this chapter exists to prevent, and it is two reads away from visible;
  5. the DEPOT CONFIGURATION, read through whichever endpoint this build still serves. On 9.1 the old one is
     retired and answers 410 with the name of its replacement, which is worth following rather than guessing;
  6. the LATER PATCHES: for SDDC Manager, each vCenter and each NSX Manager, every patch bundle the depot lists on
     the component's running line above its running version, compared as a version within the line, never as a
     build, with its download status. A component's patch is a bundle, not a release, and no upgradable read above
     offers it; the bundle's download status says whether its content is staged here, not what any component runs.

Read-only throughout. Nothing here stages, prechecks or upgrades anything.

Run:
  export SDDC_HOST=<sddc-manager-fqdn>
  export SDDC_TOKEN_FILE=/path/to/bearer      # mode 0600
  export SDDC_REHEARSAL_HOST=<fqdn> SDDC_REHEARSAL_TOKEN_FILE=/path/to/bearer   # optional, mode 0600: the stagger
  export TLS_VERIFY=false                     # only on a self-signed lab CA
  python3 lifecycle.py
Exit: 0 nothing to act on: every offered upgrade has its content staged, or nothing is offered to the read without a
      target · 1 an offered upgrade's
      content is not staged on the instance asked about (the weekly alert keys on this; it keys on the upgradable read
      without a target, and an applicable release's offer or a later patch is reported, never alerted on) · 2 an argument was given, a
      setting is missing, or a token file is open to group or other · 3 a read failed, so the answer is unknown
      · 4 the record refused to write because an estate name survived the scrub
"""
import collections
import json
import os
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def ctx():
    verify = os.environ.get("TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")
    return ssl.create_default_context() if verify else ssl._create_unverified_context()


PLACEHOLDER = re.compile(r"(\{\{[^}]*\}\})")


def one_pass(text, known, edge="A-Za-z0-9-"):
    """Replace every (real, label) pair in one pass, the longest real name first, on a boundary of `edge` characters
    (none when empty), and never inside a placeholder already written. Replacing one name at a time lets a project
    named project-2 match inside the {{project-2}} just written for the project named project-1 (G-646). When a name
    is given twice, its first label wins."""
    label_of = {}
    for real, label in known:
        label_of.setdefault(real, label)
    if not label_of:
        return text
    names = "|".join(map(re.escape, sorted(label_of, key=len, reverse=True)))
    rx = re.compile(rf"(?<![{edge}])({names})(?![{edge}])" if edge else f"({names})")
    return "".join(part if i % 2 else rx.sub(lambda m: "{{%s}}" % label_of[m.group(1)], part)
                   for i, part in enumerate(PLACEHOLDER.split(text)))


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
        text = one_pass(text, known)
        return UUID.sub("{{id}}", text)


def line_version(v):
    """A version within its line, never a build: 9.1.1.0200.25901347 reads (9, 1, 1, 200), so 9.1.1.0200 is above
    9.1.1.0100 whatever their build numbers say. None when the text carries no four-part version."""
    m = re.match(r"(\d+)\.(\d+)\.(\d+)\.(\d+)", str(v or ""))
    return tuple(int(x) for x in m.groups()) if m else None


def later_patches(running, bundles):
    """For each component type and running version, the PATCH bundles on the same line above it, one row per version."""
    rows = {}
    for kind, versions in running.items():
        for rv in versions or []:
            r = line_version(rv)
            if not r:
                continue
            for b in bundles:
                for x in b.get("components") or []:
                    to = line_version(x.get("toVersion"))
                    if (str(x.get("type")) == kind and str(x.get("imageType")) == "PATCH" and to
                            and to[:3] == r[:3] and to > r):
                        rows[(kind, rv, x.get("toVersion"))] = {
                            "component": kind, "running": rv, "patch": x.get("toVersion"),
                            "releasedDate": str(x.get("releasedDate") or "")[:10], "downloadStatus": b.get("downloadStatus")}
    return [rows[k] for k in sorted(rows, key=lambda k: (k[0], line_version(k[1]), line_version(k[2])))]


class ReadFailed(Exception):
    """A read the answer depends on did not succeed; the run says so rather than reporting an empty plane."""


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
    st, sm = get("/v1/sddc-managers")
    versions = sorted({e.get("version") for e in ((sm.get("elements") or []) if isinstance(sm, dict) else [])
                       if e.get("version")})
    print(f"  SDDC Manager: {', '.join(versions) or 'version not read'}")
    st, dom = get("/v1/domains")
    if st != 200:
        raise ReadFailed(f"{label}: the domain list answered {st or 'nothing'}")
    domains = (dom.get("elements") or []) if isinstance(dom, dict) else []
    mgmt = [d for d in domains if str(d.get("type")).upper() == "MANAGEMENT"]
    workload = [d for d in domains if str(d.get("type")).upper() != "MANAGEMENT"]
    for d in domains:
        L.get("domain", d.get("name"))
    print(f"  domains: {len(domains)} ({len(mgmt)} management, {len(workload)} workload)")
    if not mgmt:
        raise ReadFailed(f"{label}: no management domain visible; the upgradable read keys on it")

    st, rel = get("/v1/releases")
    releases = (rel.get("elements") or []) if isinstance(rel, dict) else []
    st, bun = get("/v1/bundles")
    if st != 200:
        raise ReadFailed(f"{label}: the bundle list answered {st or 'nothing'}")
    bundles = (bun.get("elements") or []) if isinstance(bun, dict) else []
    by_status = collections.Counter(b.get("downloadStatus") for b in bundles)
    by_id = {b.get("id"): b for b in bundles}
    print(f"  releases known: {len(releases)}")
    print(f"  bundles: {len(bundles)} -> {dict(by_status)}")
    release_list = [{"version": e.get("version"), "releaseDate": str(e.get("releaseDate") or "")[:10]} for e in releases]
    running = {"SDDC_MANAGER": versions}
    for kind, path in (("VCENTER", "/v1/vcenters"), ("NSX_T_MANAGER", "/v1/nsxt-clusters")):
        st_c, r_c = get(path)
        els = (r_c.get("elements") or []) if st_c == 200 and isinstance(r_c, dict) else None
        running[kind] = sorted({e.get("version") for e in els if e.get("version")}, key=line_version) if els is not None else None

    # ---- the target each domain is held to, and the releases the registry names applicable to it
    targets, n_workload = [], 0
    for d in domains:
        st_t, rv = get(f"/v1/releases/domains/{d.get('id')}")
        st_f, fr = get(f"/v1/releases/domains/{d.get('id')}/future-releases")
        rv = rv if st_t == 200 and isinstance(rv, dict) else None
        fut = (fr.get("elements") or []) if st_f == 200 and isinstance(fr, dict) else None
        t_ = {"domain": L.get("domain", d.get("name")), "type": d.get("type"),
              "targetVersion": rv.get("targetVersion") if rv else None,
              "isCustomizedBom": rv.get("isCustomizedBom") if rv else None,
              "futureReleases": [{"version": e.get("version"), "applicabilityStatus": e.get("applicabilityStatus")}
                                 for e in fut] if fut is not None else None}
        targets.append(t_)
        if str(d.get("type")).upper() == "MANAGEMENT":
            kind = "management domain"
        else:
            n_workload += 1
            kind = f"workload domain {n_workload}"
        future = ", ".join(f"{e['version']} {e['applicabilityStatus']}" for e in t_["futureReleases"] or []) or "none"
        print(f"  {kind}: target {t_['targetVersion'] or 'not read'}, isCustomizedBom {t_['isCustomizedBom']}; "
              f"future releases: {future if fut is not None else 'not read'}")

    st, up = get(f"/v1/upgradables/domains/{mgmt[0].get('id')}")
    if st != 200:
        raise ReadFailed(f"{label}: the management domain's upgradable read answered {st or 'nothing'}")
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
    # per upgradable counts that bundle's size more than once. The first version of this script did
    # exactly that and overstated the download by the size of the shared bundle.
    def join(ups, title):
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
                           "components": [{"type": x.get("type"), "toVersion": x.get("toVersion")}
                                          for x in b.get("components") or []],
                           "downloadStatus": b.get("downloadStatus"), "sizeMB": round(size, 1), "staged": staged})
        unstaged_mb = sum(sz for st_, sz in seen_bundles.values() if not st_)
        staged_n = sum(1 for st_, _ in seen_bundles.values() if st_)
        distinct = len({e.get("bundleId") for e in ups if e.get("bundleId")})
        print(f"\n  {title}: {len(ups)} upgradable(s) reference {distinct} distinct bundle(s); "
              f"{staged_n} of those bundles are staged")
        if joined and staged_n == 0:
            # The API names the unit sizeMB and does not say whether a megabyte is 10^6 or 2^20 bytes, so the figure
            # is reported in that unit, never divided by 1024 and relabelled.
            print(f"     none of the content is downloaded. {unstaged_mb:,.0f} MB (the API's sizeMB) still to fetch before "
                  f"any of this is actually available, whatever the registry says.")
        elif joined and staged_n < distinct:
            print(f"     partially staged; {unstaged_mb:,.0f} MB (the API's sizeMB) still to fetch.")
        elif joined:
            print("     every offered upgrade has its content staged.")
        return joined, distinct, staged_n, unstaged_mb

    joined, distinct, staged_n, unstaged_mb = join(ups, "THE JOIN")
    if not joined:
        print("     nothing is offered to this read, which answers for a target release: a zero is not a current "
              "estate, so each release the registry names applicable is asked for by name below.")

    # ---- the same read, asked for each release the registry names applicable to the management domain
    targeted = []
    mt = next((t_ for t_ in targets if str(t_["type"]).upper() == "MANAGEMENT"), None)
    for fr in (mt or {}).get("futureReleases") or []:
        if fr.get("applicabilityStatus") != "APPLICABLE":
            continue
        v = str(fr.get("version"))
        st_v, up_v = get(f"/v1/upgradables/domains/{mgmt[0].get('id')}?targetVersion={urllib.parse.quote(v)}")
        if st_v != 200:
            print(f"\n  THE JOIN for target {v}: HTTP {st_v or 'nothing'}, so this offer was not read")
            targeted.append({"targetVersion": v, "status": st_v, "upgradables": None})
            continue
        ups_v = (up_v.get("elements") or []) if isinstance(up_v, dict) else []
        j_v, d_v, s_v, mb_v = join(ups_v, f"THE JOIN for target {v}")
        if not j_v:
            print("     nothing is offered for this target.")
        targeted.append({"targetVersion": v, "status": st_v, "upgradables": len(ups_v), "distinctBundlesOffered": d_v,
                         "offeredAndStaged": s_v, "unstagedMB": round(mb_v, 1), "join": j_v})
    if mt and not targeted:
        print("\n  no release the registry names applicable to the management domain, so no targeted read")

    # ---- the later patches: a component's patch is a bundle in the depot, not a release and not an offer
    patches = later_patches({k: v for k, v in running.items() if v}, bundles)
    print("\n  later patches in the depot, on each component's running line:")
    for kind in ("SDDC_MANAGER", "VCENTER", "NSX_T_MANAGER"):
        if running.get(kind) is None:
            print(f"     {kind}: running version not read")
            continue
        mine = [r for r in patches if r["component"] == kind]
        print(f"     {kind} at {', '.join(running[kind]) or 'no version read'}: "
              + ("; ".join(f"{r['patch']} (released {r['releasedDate']}, {r['downloadStatus']})" for r in mine)
                 or "none listed above it"))

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

    return {"label": label, "sddcManagerVersions": versions,
               "domains": {"total": len(domains), "management": len(mgmt), "workload": len(workload)},
               "releases": len(releases), "releaseList": release_list, "running": running,
               "domainTargets": targets, "bundles": {"total": len(bundles), "byStatus": dict(by_status)},
               "upgradables": len(ups), "distinctBundlesOffered": distinct,
               "offeredAndStaged": staged_n, "unstagedMB": round(unstaged_mb, 1),
               "join": joined, "targetedOffers": targeted, "laterPatches": patches,
               "workloadDomainRefusal": refusal, "depot": depot}


def read_secret(var):
    """The secret in the file VAR names. A file open to group or other is refused before it is read; the refusal
    names the variable and the fix, never the file's content."""
    with open(os.environ[var], encoding="utf-8") as f:
        mode = os.fstat(f.fileno()).st_mode & 0o777
        # Windows makes the mode from the read-only flag alone, so it has no group or other bits to judge.
        if mode & 0o077 and os.name != "nt":
            raise PermissionError(f"{var} names a file of mode {mode:04o}, open to group or other: "
                                  f'run chmod 600 "${var}" and try again (the file was not read)')
        return f.read().strip()


def main():
    """Read the instance you are asked about, and, when a second is named, the one you rehearse on."""
    out_dir = os.environ.get("OUT_DIR", ".")
    L = Labels()
    print("lifecycle.py: is the upgrade the registry is offering actually available?")
    primary = read_instance(os.environ["SDDC_HOST"],
                            read_secret("SDDC_TOKEN_FILE"),
                            L, "the instance asked about")
    instances = [primary]
    # The chapter's discipline is a rehearsal instance kept a cycle ahead of production. Comparing the two is the
    # read that shows whether the stagger still exists, so the script takes a second host when you have one.
    rh, rt = os.environ.get("SDDC_REHEARSAL_HOST"), os.environ.get("SDDC_REHEARSAL_TOKEN_FILE")
    if rh and rt:
        instances.append(read_instance(rh, read_secret("SDDC_REHEARSAL_TOKEN_FILE"), L, "the rehearsal instance"))
    else:
        print("\n  rehearsal instance: not read; set SDDC_REHEARSAL_HOST and SDDC_REHEARSAL_TOKEN_FILE to compare")
    if len(instances) > 1:
        a, b = instances[0], instances[1]
        print(f"\n  the stagger: SDDC Manager {', '.join(a['sddcManagerVersions']) or '?'} against "
              f"{', '.join(b['sddcManagerVersions']) or '?'}"
              + ("; the same build, so no stagger today" if a["sddcManagerVersions"] == b["sddcManagerVersions"] else ""))
        print(f"     {a['upgradables']} upgradable(s) on the instance asked about, "
              f"{b['upgradables']} on the rehearsal instance; staged bundles "
              f"{a['bundles']['byStatus'].get('SUCCESSFUL', 0)} against "
              f"{b['bundles']['byStatus'].get('SUCCESSFUL', 0)}")
    payload = {"captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "instances": instances}
    text = L.scrub(UUID.sub("{{id}}", json.dumps(payload, indent=1, ensure_ascii=False)))
    for secret in (os.environ.get("SDDC_HOST", ""), os.environ.get("SDDC_REHEARSAL_HOST", "")):
        if secret and secret in text:
            raise SystemExit("FATAL: a host name reached the record; nothing was written")
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
    unstaged = primary["upgradables"] and primary["offeredAndStaged"] < primary["distinctBundlesOffered"]
    return 1 if unstaged else 0


if __name__ == "__main__":
    import sys
    if sys.argv[1:]:
        print(f"lifecycle.py: takes no arguments (got {' '.join(sys.argv[1:])}); it is configured by the environment",
              file=sys.stderr)
        sys.exit(2)
    try:
        sys.exit(main())
    except KeyError as e:
        print(f"lifecycle.py: set {e.args[0]} (see the Run block at the top of this file)", file=sys.stderr)
        sys.exit(2)
    except PermissionError as e:
        print(f"lifecycle.py: {e}", file=sys.stderr)
        sys.exit(2)
    except ReadFailed as e:
        print(f"lifecycle.py: a read failed, so the answer is unknown: {e}", file=sys.stderr)
        sys.exit(3)
    except SystemExit as e:
        if isinstance(e.code, str):
            print(e.code, file=sys.stderr)
            sys.exit(4)
        raise
