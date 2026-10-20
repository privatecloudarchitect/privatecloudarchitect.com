#!/usr/bin/env python3
"""ledgers.py: ask every plane that will answer "how much storage is used" and put the answers side by side.

This platform keeps several storage ledgers and they do not agree. That is not a defect; they answer different
questions. It becomes a defect the moment somebody makes a capacity decision from whichever one their tooling
happened to reach, so this reads as many as your credentials allow, on one day, and prints them together:

  1. TENANT CLAIMED: what the volume claims in every namespace actually ask for. The smallest honest number;
  2. TENANT GRANTED: the region storage-class quota's consumption figure. This is the number quotas and tenants
     are governed by, and the script checks what it is actually counting by summing the namespaces' storage
     limits and comparing. A namespace that sets no storage limit takes its class config's, so that is the
     figure it is summed at;
  3. PROVIDER ALLOCATION: the provider plane's storageConsumedMiB, every page of it. Needs a provider bearer;
  4. PHYSICAL: capacity and free space of every datastore one vCenter holds. Needs a vCenter sign-in.

Each one is optional but the first two. With only the tenant sign-in you still get those two and the check
between them, which is the pair most often confused. Anything the script cannot reach it names rather than
omits, because a comparison missing a column silently becomes a different comparison. Each plane's percentage
is printed with both halves taken from that plane.

With --compare <earlier ledgers.json> it also sets each ledger's ratio to the quota figure beside the same ratio
in the earlier record, which is the weekly check: the spread itself is expected, a ratio that moves is news.

Read-only throughout.

Sign-in:
  the tenant (required), one of
    VCFA_REFRESH_TOKEN_FILE   a refresh token minted for the organization, in a file of mode 0600
    VCFA_USER and VCFA_PASSWORD_FILE   a session login as user@org (the password from a file of mode 0600, or
                              VCFA_PASSWORD, the value itself, which lands in the shell's history)
  the provider (optional): VCFA_PROVIDER_BEARER_FILE, a provider bearer in a file of mode 0600
  vCenter (optional): VCENTER_HOST, with VCENTER_USER and VCENTER_PASSWORD_FILE, or VCENTER_SESSION_FILE holding a
    vmware-api-session-id
A secret file open to group or other is refused before it is read.

Run:
  export VCFA_HOST=<automation-fqdn> VCFA_ORG=<org>
  export VCFA_USER=<account> VCFA_PASSWORD_FILE=~/.vcf/vcfa-password       # or VCFA_REFRESH_TOKEN_FILE
  export VCFA_PROVIDER_BEARER_FILE=~/.vcf/provider-bearer                  # optional, the provider ledger
  export VCENTER_HOST=<vcenter-fqdn> VCENTER_USER=<user> VCENTER_PASSWORD_FILE=~/.vcf/vcenter-password
                                                                           # optional, the physical ledger
  export TLS_VERIFY=false                                                  # only on a self-signed lab CA
  python3 ledgers.py                                # writes out/ledgers.json
  python3 ledgers.py --compare out/ledgers.json     # also compares each ratio with an earlier record

Exit: 0 written (with --compare, no ratio moved by more than a tenth); 1 with --compare, a ratio moved by more
than a tenth; 2 a call failed, a sign-in was refused, or a figure was not a quantity; 3 refused to replace a
record read from more ledgers; 5 an unknown argument.
"""
import base64
import http.client
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

http.client._MAXHEADERS = 1000
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
CCI = "/cci/kubernetes"
I1 = "infrastructure.cci.vmware.com/v1alpha1"
I2 = "infrastructure.cci.vmware.com/v1alpha2"
A3 = "infrastructure.cci.vmware.com/v1alpha3"
PROJ = "project.cci.vmware.com/v1alpha2"
MIB = 1024 * 1024
TOLERANCE = 0.1   # --compare: a ratio that moves by more than a tenth of itself is reported
# A Kubernetes quantity's suffix: binary ones are powers of two, decimal ones (lowercase k among them) powers of ten.
BYTES = {"": 1, "k": 10**3, "M": 10**6, "G": 10**9, "T": 10**12, "P": 10**15, "E": 10**18,
         "Ki": 2**10, "Mi": 2**20, "Gi": 2**30, "Ti": 2**40, "Pi": 2**50, "Ei": 2**60}
QUANTITY = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(Ki|Mi|Gi|Ti|Pi|Ei|k|M|G|T|P|E)?\s*$")
UNPARSED = []


def ctx():
    verify = os.environ.get("TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")
    return ssl.create_default_context() if verify else ssl._create_unverified_context()


def mib(q):
    """A Kubernetes quantity in mebibytes: 20Gi is 20480, 20G is 19073, 900000Mi is 900000, a bare number is bytes.
    An absent figure is zero; a figure that is not a quantity is recorded and counted as nothing, and the run
    ends on it before writing, because a ledger summed past an unreadable figure balances wrongly."""
    if q is None or q == "":
        return 0
    m = QUANTITY.match(str(q))
    if not m:
        UNPARSED.append(str(q)[:40])
        return 0
    return round(float(m.group(1)) * BYTES[m.group(2) or ""] / MIB)


def tib(m):
    """Mebibytes as tebibytes. 1 TiB is 1048576 MiB, not a million."""
    return round(m / MIB, 2)


def pct(part, whole):
    return f"{100 * part / whole:.1f}%" if whole else "?"


def secret(name):
    """A secret from NAME_FILE (a file, mode 0600, its value stripped) or else NAME itself; None when neither is set.
    The file keeps a tier-0 token out of the shell's history and the process list. A file open to group or other is
    refused before it is read; the refusal names the variable and the fix, never the file's content."""
    path = os.environ.get(f"{name}_FILE")
    if path:
        with open(path, encoding="utf-8") as f:
            mode = os.fstat(f.fileno()).st_mode & 0o777
            # Windows makes the mode from the read-only flag alone, so it has no group or other bits to judge.
            if mode & 0o077 and os.name != "nt":
                raise PermissionError(f"{name}_FILE names a file of mode {mode:04o}, open to group or other: "
                                      f'run chmod 600 "${name}_FILE" and try again (the file was not read)')
            return f.read().strip()
    return os.environ.get(name) or None


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
        known = [(r, lab) for m in self.maps.values() for r, lab in m.items()]
        text = one_pass(text, known)
        return UUID.sub("{{id}}", text)


def fetch(url, headers, method="GET"):
    req = urllib.request.Request(url, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, context=ctx(), timeout=90) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None), r.headers
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw), e.headers
        except ValueError:
            return e.code, raw.decode(errors="replace")[:200], e.headers
    except (urllib.error.URLError, OSError) as e:
        return None, str(e)[:160], {}


def fail(msg):
    print(f"FATAL: {msg}")
    sys.exit(2)


def tenant_bearer(host, org, refresh, user, password):
    """A tenant bearer, from the organization's refresh token or from a session login as user@org. A refused mint
    ends the run with the server's own answer: "invalid_grant" means the refresh token is dead, a 401 at the
    session means the login is."""
    if refresh:
        kind = "refresh token"
        body = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": refresh}).encode()
        req = urllib.request.Request(f"https://{host}/oauth/tenant/{org}/token", data=body, method="POST",
                                     headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
    else:
        kind = "session login"
        basic = base64.b64encode(f"{user.split('@')[0]}@{org}:{password}".encode()).decode()
        req = urllib.request.Request(f"https://{host}/cloudapi/1.0.0/sessions", method="POST",
                                     headers={"Authorization": f"Basic {basic}", "Accept": "application/json;version=40.0"})
    try:
        with urllib.request.urlopen(req, context=ctx(), timeout=30) as r:
            bearer = json.loads(r.read())["access_token"] if refresh else r.headers.get("X-VMWARE-VCLOUD-ACCESS-TOKEN")
    except urllib.error.HTTPError as e:
        fail(f"the {kind} answered HTTP {e.code}: {e.read().decode(errors='replace')[:200]}")
    except (urllib.error.URLError, OSError) as e:
        fail(f"the {kind} did not answer: {e}")
    if not bearer:
        fail(f"the {kind} answered without a bearer")
    return bearer, kind


def refuse_unknown_args(known, takes_value=()):
    """Refuse any argument this script does not recognise, before a client opens. --help prints the usage above."""
    args = sys.argv[1:]
    if "-h" in args or "--help" in args:
        print(__doc__)
        sys.exit(0)
    unknown = [a for i, a in enumerate(args) if a not in known and not (i and args[i - 1] in takes_value)]
    if unknown or (args and args[-1] in takes_value):
        print(f"unknown or incomplete argument(s) {unknown or args[-1:]}: this script takes {', '.join(sorted(known))} "
              "(see --help)", file=sys.stderr)
        sys.exit(5)


def compare(earlier_path, figures):
    """Each ledger's ratio to the quota figure, now and in an earlier record. Returns True when one moved by more
    than TOLERANCE of itself."""
    try:
        earlier = json.load(open(earlier_path, encoding="utf-8"))
    except (OSError, ValueError) as e:
        fail(f"--compare could not read {earlier_path}: {e}")
    then = earlier.get("figures") or {}
    base_now, base_then = figures.get("tenantGranted"), then.get("tenantGranted")
    print(f"\n  compared with the record of {earlier.get('captured_utc', '?')}, each ledger as a multiple of the quota figure:")
    moved = False
    for k in figures:
        if k == "tenantGranted" or k not in then or not (base_now and base_then):
            continue
        r_now, r_then = figures[k] / base_now, then[k] / base_then
        change = (r_now - r_then) / r_then if r_then else None
        flag = change is None or abs(change) > TOLERANCE
        moved = moved or flag
        print(f"     {k:<20} {r_then:>8.2f} then, {r_now:>8.2f} now"
              + (f"  ({change:+.0%})" if change is not None else "") + ("  MOVED" if flag else ""))
    return moved


def main():
    refuse_unknown_args({"--compare"}, takes_value=("--compare",))
    args = sys.argv[1:]
    earlier = args[args.index("--compare") + 1] if "--compare" in args else None
    host, org = os.environ["VCFA_HOST"], os.environ["VCFA_ORG"]
    try:
        refresh, password = secret("VCFA_REFRESH_TOKEN"), secret("VCFA_PASSWORD")
        pb = secret("VCFA_PROVIDER_BEARER")
        vpass, sid_given = secret("VCENTER_PASSWORD"), secret("VCENTER_SESSION")
    except OSError as e:   # a secret file that is missing, unreadable or open to group or other
        fail(e)
    user, vh, vuser = os.environ.get("VCFA_USER"), os.environ.get("VCENTER_HOST"), os.environ.get("VCENTER_USER")
    if not refresh and not (user and password):
        fail("set VCFA_REFRESH_TOKEN_FILE, or VCFA_USER with VCFA_PASSWORD_FILE (see --help)")
    out_dir = os.environ.get("OUT_DIR", "out")
    L = Labels()
    bearer, sign_in = tenant_bearer(host, org, refresh, user, password)
    H = {"Authorization": f"Bearer {bearer}", "Accept": "application/json"}

    def items(path):
        """Every item of a tenant list, following the continue token; a list that fails ends the run."""
        out, token = [], None
        while True:
            st, body, _ = fetch(f"https://{host}{CCI}{path}" + (f"?continue={urllib.parse.quote(token)}" if token else ""), H)
            if st != 200 or not isinstance(body, dict):
                fail(f"GET {CCI}{path} answered {st if st else 'nothing'}")
            out += body.get("items") or []
            token = (body.get("metadata") or {}).get("continue")
            if not token:
                return out

    print("ledgers.py: every plane that will answer how much storage is used\n")

    # ---- 2. tenant granted, and what it is actually counting
    quotas = []
    for it in items(f"/apis/{I1}/regionstorageclassquotas"):
        sp, stt = it.get("spec") or {}, it.get("status") or {}
        L.get("storageclass", sp.get("storageClassName"))
        quotas.append({"storageClass": L.scrub(sp.get("storageClassName") or ""),
                       "capacityMiB": mib(sp.get("storageCapacity")),
                       "consumedMiB": mib(stt.get("storageConsumed")),
                       "zones": len(sp.get("zones") or [])})
    granted = sum(x["consumedMiB"] for x in quotas)

    # ---- 1. tenant claimed, and the namespaces' own storage limits, a class config's where the namespace sets none
    class_limit = {}
    for o in items(f"/apis/{I2}/supervisornamespaceclassconfigs"):
        class_limit[o["metadata"]["name"]] = sum(mib(s.get("limit")) for s in ((o.get("spec") or {}).get("storageClasses") or []))
    limits, claimed, claims_n, namespaces, inherited, unread = 0, 0, 0, 0, 0, []
    for p in [p["metadata"]["name"] for p in items(f"/apis/{PROJ}/projects")]:
        L.get("project", p)
        for n in items(f"/apis/{A3}/namespaces/{p}/supervisornamespaces"):
            namespaces += 1
            ns, sp = n["metadata"]["name"], n.get("spec") or {}
            L.get("namespace", ns)
            own = ((sp.get("classConfigOverrides") or {}).get("storageClasses")) or []
            if own:
                limits += sum(mib(s_.get("limit")) for s_ in own)
            else:
                inherited += 1
                limits += class_limit.get(sp.get("className"), 0)
            url = (n.get("status") or {}).get("namespaceEndpointURL")
            if not url:
                unread.append("no endpoint")
                continue
            st2, pv, _ = fetch(url.rstrip("/") + f"/api/v1/namespaces/{ns}/persistentvolumeclaims", H)
            if st2 != 200 or not isinstance(pv, dict):
                unread.append(f"HTTP {st2}")
                continue
            for c in pv.get("items") or []:
                claims_n += 1
                claimed += mib(((c.get("spec") or {}).get("resources") or {}).get("requests", {}).get("storage"))

    counting = ("the namespaces' storage limits" if granted == limits else
                "the volume claims" if granted == claimed else "neither, which is worth investigating")
    print(f"  TENANT CLAIMED   {claimed:>12,} MiB ({tib(claimed):>6} TiB)  from {claims_n} volume claim(s) in "
          f"{namespaces - len(unread)} of {namespaces} namespace(s)"
          + (f"; {len(unread)} not read ({', '.join(sorted(set(unread)))})" if unread else ""))
    print(f"  TENANT GRANTED   {granted:>12,} MiB ({tib(granted):>6} TiB)  the quota ledger's own figure")
    print(f"     the namespaces' storage limits sum to {limits:,} MiB ({inherited} of {namespaces} at their class "
          f"config's), so the quota ledger is counting {counting}")

    # ---- 3. provider allocation, every page, sorted so the pages do not overlap
    provider, sorted_by = None, None
    if pb:
        ph = {"Authorization": f"Bearer {pb}", "Accept": "application/json;version=40.0"}
        vals, page, pages = [], 1, 1
        while page <= pages:
            q = f"page={page}&pageSize=128" + ("&sortAsc=id" if sorted_by != "none" else "")
            st, sc, _ = fetch(f"https://{host}/cloudapi/v1/storageClasses?{q}", ph)
            if st == 400 and page == 1 and sorted_by is None:
                sorted_by = "none"   # this build refuses the sort; one unsorted page is still a complete read
                continue
            if st != 200 or not isinstance(sc, dict):
                fail(f"the provider storage classes answered {st if st else 'nothing'}")
            sorted_by = sorted_by or "id"
            vals += sc.get("values") or []
            pages = int(sc.get("pageCount") or 1)
            if sorted_by == "none" and pages > 1:
                fail("the provider storage classes span pages and refuse a sort, so a paged read could overlap")
            page += 1
        provider = []
        for v in vals:
            L.get("storageclass", v.get("name"))
            cap, con = int(v.get("storageCapacityMiB") or 0), int(v.get("storageConsumedMiB") or 0)
            zs = v.get("zones")
            provider.append({"storageClass": L.scrub(v.get("name") or ""), "capacityMiB": cap,
                             "consumedMiB": con, "ratio": round(con / cap, 3) if cap else None,
                             "zones": len(zs) if isinstance(zs, list) else
                                      len((zs or {}).get("values") or []) if isinstance(zs, dict) else 0})
        # Do NOT sum these. Classes reporting the same capacity read as one pool seen through two classes, and
        # their consumption need not match to the byte (an object in one class only moves it), so test the
        # capacity, not the whole row. Report the largest single class and how many share another's capacity.
        same_cap = len(provider) - len({x["capacityMiB"] for x in provider})
        groups = [[x["consumedMiB"] for x in provider if x["capacityMiB"] == c] for c in {x["capacityMiB"] for x in provider}]
        gap = max((max(g) - min(g) for g in groups if len(g) > 1), default=None)
        tot = max((x["consumedMiB"] for x in provider), default=0)
        print(f"  PROVIDER ALLOC   {tot:>12,} MiB ({tib(tot):>6} TiB)  largest of {len(provider)} class(es)"
              + (f"; {same_cap} report the capacity of another class, consumption within {gap:,} MiB of it, "
                 "so these do not add up" if same_cap else ""))
        for x in provider:
            print(f"     class capacity {x['capacityMiB']:>10,} consumed {x['consumedMiB']:>11,} "
                  f"ratio {x['ratio']} zones {x['zones']}")
    else:
        print("  PROVIDER ALLOC   not read: set VCFA_PROVIDER_BEARER_FILE to include it")

    # ---- 4. physical: every datastore one vCenter holds
    physical, sid, owned = None, None, False
    if vh and (sid_given or (vuser and vpass)):
        base = f"https://{vh}"
        if sid_given:
            sid = sid_given
        else:
            basic = base64.b64encode(f"{vuser}:{vpass}".encode()).decode()
            st, got, _ = fetch(base + "/api/session", {"Authorization": f"Basic {basic}"}, method="POST")
            if st not in (200, 201) or not isinstance(got, str):
                fail(f"vCenter refused the session (HTTP {st})")
            sid, owned = got, True
        st, ds, _ = fetch(base + "/api/vcenter/datastore", {"vmware-api-session-id": sid, "Accept": "application/json"})
        if owned:
            fetch(base + "/api/session", {"vmware-api-session-id": sid}, method="DELETE")
        if st != 200 or not isinstance(ds, list):
            fail(f"vCenter's datastore list answered {st if st else 'nothing'}")
        cap = sum(int(d.get("capacity") or 0) for d in ds)
        free = sum(int(d.get("free_space") or 0) for d in ds)
        physical = {"datastores": len(ds), "capacityMiB": cap // MIB, "usedMiB": (cap - free) // MIB,
                    "types": sorted({str(d.get("type")) for d in ds})}
        print(f"  PHYSICAL         {physical['usedMiB']:>12,} MiB ({tib(physical['usedMiB']):>6} TiB) used "
              f"of {tib(physical['capacityMiB'])} TiB across {len(ds)} datastore(s), types {', '.join(physical['types'])}")
    else:
        print("  PHYSICAL         not read: set VCENTER_HOST with VCENTER_USER and VCENTER_PASSWORD_FILE to include it")

    if UNPARSED:
        fail(f"{len(UNPARSED)} figure(s) were not quantities, for example {UNPARSED[0]!r}; nothing was written")

    # ---- each plane's percentage, both halves from that plane
    per_plane = []
    if quotas:
        q = max(quotas, key=lambda x: x["consumedMiB"])
        per_plane.append({"plane": "tenant", "storageClass": q["storageClass"], "usedMiB": q["consumedMiB"], "capacityMiB": q["capacityMiB"]})
    if provider:
        x = max(provider, key=lambda x: x["consumedMiB"])
        per_plane.append({"plane": "provider", "storageClass": x["storageClass"], "usedMiB": x["consumedMiB"], "capacityMiB": x["capacityMiB"]})
    if physical:
        per_plane.append({"plane": "physical", "storageClass": None, "usedMiB": physical["usedMiB"], "capacityMiB": physical["capacityMiB"]})
    print("\n  each plane's percentage, both halves from that plane:")
    for r in per_plane:
        print(f"     {r['plane']:<9} {r['storageClass'] or 'every datastore':<20} {r['usedMiB']:>12,} of "
              f"{r['capacityMiB']:>12,} MiB  {pct(r['usedMiB'], r['capacityMiB'])}")

    # A run that reached fewer ledgers than the record on disk does not get to overwrite it. Carrying the missing
    # block forward (G-166's answer elsewhere) is wrong HERE: the whole argument of this record is that the
    # ledgers were read on one estate in ONE RUN, which is what makes their disagreement a fact about the planes
    # rather than about the clock. So this one refuses, and says which credentials would have made it complete.
    reached = 2 + (1 if provider else 0) + (1 if physical else 0)
    prior_path = os.path.join(out_dir, "ledgers.json")
    if os.path.exists(prior_path):
        try:
            prior = json.load(open(prior_path, encoding="utf-8")) or {}
        except ValueError:
            prior = {}
        was = prior.get("ledgersRead") or (2 + (1 if prior.get("provider") else 0) + (1 if prior.get("physical") else 0))
        if was > reached:
            missing = [n for n, v in (("VCFA_PROVIDER_BEARER_FILE", provider),
                                      ("VCENTER_HOST with VCENTER_USER and VCENTER_PASSWORD_FILE", physical)) if not v]
            print(f"\nREFUSING to write: this run reached {reached} of the four ledgers and the record at {prior_path} "
                  f"was written from {was}. Every figure in that record was read in one run, which is what makes the "
                  f"spread a fact about the planes and not about the clock; replacing it with a narrower read would "
                  f"keep the claim and lose the evidence for it. Set " + " and ".join(missing) + ", or set OUT_DIR "
                  "elsewhere. A thinner read is not a newer truth.")
            sys.exit(3)

    figures = {"tenantClaimed": claimed, "tenantGranted": granted}
    if provider:
        figures["providerAllocation"] = max(x["consumedMiB"] for x in provider)
    if physical:
        figures["physicalUsed"] = physical["usedMiB"]
    lo, hi = min(figures.values()), max(figures.values())
    print(f"\n  {len(figures)} answers to one question, spanning {round(hi / lo, 1) if lo else '?'} times: "
          + ", ".join(f"{k} {tib(v)} TiB" for k, v in figures.items()))
    moved = compare(earlier, figures) if earlier else False

    payload = {"captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "signIn": sign_in,
               "quotas": quotas, "namespaces": namespaces, "claims": claims_n, "namespacesWithClaimsUnread": unread,
               "tenantClaimedMiB": claimed, "tenantGrantedMiB": granted, "namespaceLimitsMiB": limits,
               "namespacesAtTheirClassConfigsLimit": inherited, "quotaLedgerCounts": counting,
               "provider": provider, "providerSorted": sorted_by, "physical": physical,
               "providerClassesReportingIdenticalFigures":
                   (len(provider) - len({(x["capacityMiB"], x["consumedMiB"]) for x in provider})) if provider else None,
               "providerClassesSharingACapacity": same_cap if provider else None,
               "providerConsumptionGapWithinACapacityMiB": gap if provider else None,
               "perPlane": per_plane, "figures": figures, "spread": round(hi / lo, 1) if lo else None,
               "ledgersRead": reached,
               "unitNote": "every figure is mebibytes; 1 TiB is 1048576 MiB, not a million"}

    text = L.scrub(UUID.sub("{{id}}", json.dumps(payload, indent=1, ensure_ascii=False)))
    for value in (bearer, refresh, password, user, host, org, pb, vh, sid, vuser, vpass):
        assert not value or value not in text, "an estate value reached the record"
    bare = re.sub(r"\{\{[^}]*\}\}", "", text)
    for fam, m in L.maps.items():
        for nm in m:
            if nm and re.search(r"(?<![A-Za-z0-9-])" + re.escape(nm) + r"(?![A-Za-z0-9-])", bare):
                shp = re.sub(r"[A-Za-z]", "a", re.sub(r"[0-9]", "9", nm))
                fail(f"a {fam} name ({len(nm)} characters, shape {shp}) reached the record; nothing was written")
    os.makedirs(out_dir, exist_ok=True)
    open(prior_path, "w", encoding="utf-8").write(text + "\n")
    print(f"\nwrote {prior_path} ({len(figures)} ledger(s) reached); every organization name replaced by a placeholder")
    sys.exit(1 if moved else 0)


if __name__ == "__main__":
    main()
