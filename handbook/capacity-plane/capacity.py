#!/usr/bin/env python3
"""capacity.py: the capacity plane of a VCF Automation organization, and whether its ledger balances.

Read-only. Capacity here is not a number on a project, it is a set of objects, so rather than describe them
this adds them up and checks the sum:

  1. the ZONES, each carrying a budget in spec and a consumption in status, for both limits and reservations;
  2. the NAMESPACES, each carrying a per-zone budget of its own;
  3. the LEDGER CHECK: does a zone's reported consumption equal the sum of the namespaces' limits, or of their
     reservations? Those are different numbers and only one of them is what a create is measured against;
  4. the CONTRACT CHECK: a namespace names a class, and the class's config carries a sizing template. This
     compares what the class promised, field by field, with what the namespace actually holds, and counts how
     often they agree. If the answer is rarely, the class name tells a reader very little;
  5. the STORAGE ledgers and the VM class catalog, which are the same shape one level out;
  6. the BINDINGS each project holds (region, class and VPC), counted beside the namespaces it hosts;
  7. with --probe-overrides --project <name>, the OVERRIDE CHECK: comparing what namespaces hold with what their
     class promised shows that they differ, but not why, because an override written at create and a class
     config edited afterwards leave identical evidence. This asks the platform directly, by creating namespaces
     in the project you name that depart from the config deliberately, a create into a zone with no limit budget
     left, and the same create sent as a dry run. It deletes every namespace it made, waits until they are
     gone, and reads the zones again to see whether the ledger came back to where it started.

Without --probe-overrides nothing here writes. Organization-specific names, a class config's own name among them,
are replaced by stable placeholders, and the script refuses to write a record in which one survived. Sizes, class
names, and field names are kept, because the arithmetic is the lesson.

Sign-in, one of:
  VCFA_REFRESH_TOKEN_FILE   a file holding a refresh token minted for the organization, mode 0600
  VCFA_USER and VCFA_PASSWORD_FILE   a session login as user@org (the password from a file of mode 0600, or
                            VCFA_PASSWORD, the value itself, which lands in the shell's history)
A file open to group or other is refused before it is read.

Run:
  export VCFA_HOST=<automation-fqdn> VCFA_ORG=<org>
  export VCFA_USER=<account> VCFA_PASSWORD_FILE=~/.vcf/vcfa-password    # or VCFA_REFRESH_TOKEN_FILE
  export TLS_VERIFY=false                                               # only on a self-signed lab CA
  python3 capacity.py
  python3 capacity.py --probe-overrides --project <name>   # also creates and deletes namespaces there, see step 7

Exit: 0 read (with the probe: every namespace it made is gone and the zones read as they did before it);
2 a call failed or the sign-in was refused; 3 the probe left a namespace behind, or the zones did not come back
to their starting figures; 5 an unknown argument, or --probe-overrides without --project naming a project this
sign-in can see.
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
TOPO = "topology.cci.vmware.com/v1alpha1"
INFRA1, INFRA2, INFRA3 = ("infrastructure.cci.vmware.com/v1alpha1", "infrastructure.cci.vmware.com/v1alpha2",
                          "infrastructure.cci.vmware.com/v1alpha3")
BUDGET = ("cpuLimit", "cpuReservation", "memoryLimit", "memoryReservation")


def ctx():
    verify = os.environ.get("TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")
    return ssl.create_default_context() if verify else ssl._create_unverified_context()


def qty(v):
    """The number out of a quantity string: 60000M reads 60000, 131072Mi reads 131072.

    The suffix is NOT noise and is never discarded silently: `unit()` reads it and every record this writes
    carries it, because this interface mixes unit families inside one object. CPU comes back in SI mega
    (60000M is 60 GHz) while memory and storage come back in binary mebi (131072Mi is 128 GiB). A reader who
    takes a bare 18830489 and divides by a million gets 18.8 of nothing at all; the same figure read as Mi is
    17.96 TiB. Carry the unit or do not carry the number.
    """
    m = re.match(r"^(\d+)", str(v if v is not None else 0))
    return int(m.group(1)) if m else 0


def unit(v, default=""):
    """The suffix out of a quantity string: 60000M reads M, 131072Mi reads Mi."""
    m = re.match(r"^\d+([A-Za-z]*)$", str(v if v is not None else "").strip())
    return (m.group(1) if m else "") or default


def tib(mib):
    """Mebibytes as tebibytes, to one decimal. 1 TiB is 1048576 MiB, not a million."""
    return round(mib / 1048576.0, 2)


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
    # The product's own vocabulary is never an estate name. A principal can be called exactly what a platform
    # object is called (this estate has a user named "admin" and a project role named "admin"), and registering
    # one teaches the scrubber to blank the other. A name in RESERVED identifies no estate and is left alone.
    RESERVED = {"admin", "view", "edit", "user", "users", "group", "groups", "owner", "auditor", "auditors",
                "administrator", "administrators", "default", "system", "none", "all"}

    def __init__(self):
        self.maps = {}

    def get(self, family, name):
        if str(name) in self.RESERVED:
            return name
        m = self.maps.setdefault(family, {})
        if name not in m:
            m[name] = f"{family}-{len(m) + 1}"
        return "{{%s}}" % m[name]

    def scrub(self, text):
        if not isinstance(text, str):
            return text
        known = [(real, label) for m in self.maps.values() for real, label in m.items()]
        # Longest first so a contained name cannot corrupt a longer one, and on a WORD BOUNDARY so a short
        # name is not replaced inside an unrelated word. A principal really can be called "admin", and a naive
        # replace turns the field name "administrators" into "{{user-3}}istrators". The leak check below uses
        # the same boundary, so what the scrub replaces and what the check looks for are one rule.
        text = one_pass(text, known)
        return UUID.sub("{{id}}", text)


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


class Cci:
    def __init__(self, host, org, refresh_token=None, user=None, password=None):
        """A tenant bearer, from the organization's refresh token or from a session login as user@org. A refused
        mint ends the run with the server's own answer: "invalid_grant" means the refresh token is dead, a 401 at
        the session means the login is."""
        self.host = host
        if refresh_token:
            self.kind = "refresh token"
            body = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": refresh_token}).encode()
            req = urllib.request.Request(
                f"https://{host}/oauth/tenant/{org}/token", data=body, method="POST",
                headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
        else:
            self.kind = "session login"
            basic = base64.b64encode(f"{user.split('@')[0]}@{org}:{password}".encode()).decode()
            req = urllib.request.Request(f"https://{host}/cloudapi/1.0.0/sessions", method="POST",
                                         headers={"Authorization": f"Basic {basic}", "Accept": "application/json;version=40.0"})
        try:
            with urllib.request.urlopen(req, context=ctx(), timeout=30) as r:
                self.bearer = (json.loads(r.read())["access_token"] if refresh_token
                               else r.headers.get("X-VMWARE-VCLOUD-ACCESS-TOKEN"))
        except urllib.error.HTTPError as e:
            print(f"FATAL: the {self.kind} answered HTTP {e.code}: {e.read().decode(errors='replace')[:200]}")
            sys.exit(2)
        except (urllib.error.URLError, OSError) as e:
            print(f"FATAL: the {self.kind} did not answer: {e}")
            sys.exit(2)
        if not self.bearer:
            print(f"FATAL: the {self.kind} answered without a bearer")
            sys.exit(2)

    def get(self, path):
        req = urllib.request.Request(f"https://{self.host}{CCI}{path}",
                                     headers={"Authorization": f"Bearer {self.bearer}", "Accept": "application/json"})
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
            return None, str(e)

    def items(self, group, resource):
        """Every item of a list, following the continue token a Kubernetes-style list hands back when it pages. A
        list that fails ends the run: a ledger summed over a list that did not arrive balances wrongly."""
        out, token = [], None
        while True:
            path = f"/apis/{group}/{resource}" + (f"?continue={urllib.parse.quote(token)}" if token else "")
            st, body = self.get(path)
            if st != 200 or not isinstance(body, dict):
                print(f"FATAL: GET {CCI}/apis/{group}/{resource} answered {st if st else 'nothing'}")
                sys.exit(2)
            out += body.get("items") or []
            token = (body.get("metadata") or {}).get("continue")
            if not token:
                return out

    def send(self, method, path, body=None):
        """Only --probe-overrides reaches this, and only to create a namespace it deletes again."""
        headers = {"Authorization": f"Bearer {self.bearer}", "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(f"https://{self.host}{CCI}{path}", method=method, headers=headers,
                                     data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(req, context=ctx(), timeout=120) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, raw.decode(errors="replace")[:300]
        except (urllib.error.URLError, OSError) as e:
            return None, str(e)


def zone_figures(c, L):
    """What every zone reports used right now, keyed by its placeholder: the four consumption figures."""
    out = {}
    for o in c.items(TOPO, "zones"):
        sp, stt = o.get("spec") or {}, o.get("status") or {}
        out[L.get("zone", sp.get("zoneName") or o["metadata"]["name"])] = {
            "cpu": qty(stt.get("cpuUsed")), "memory": qty(stt.get("memoryUsed")),
            "cpuReservation": qty(stt.get("cpuReservationUsed")), "memoryReservation": qty(stt.get("memoryReservationUsed"))}
    return out


def probe_overrides(c, L, proj, configs, zones, model_spec):
    """Ask the platform, at create, which way a class config can be departed from, and what a create into a zone
    with no budget left and a create sent as a dry run come back with.

    The chapter's central claim is that a class config is a default rather than a contract. Comparing what
    namespaces hold against what their class promised shows they differ, but it cannot tell you WHY: an
    override written at create and a class config edited afterwards leave identical evidence. This settles it
    by creating namespaces that depart from the config deliberately, reading what came back, and deleting them.

    It writes only into PROJ, the project named on the command line. Every namespace it creates it deletes.
    Deletion is asynchronous, so it waits for each to be gone, then reads the zones again and compares them
    with the figures it read before the first create. Returns the section of the record, or None when skipped.
    """
    cfg = configs.get("small") or next(iter(configs.values()), None)
    cls = next((k for k, v in configs.items() if v is cfg), None)
    free = [zn for zn, zv in zones.items()
            if cfg and zv["budget"]["cpuLimit"] - zv["used"]["cpu"] >= 2 * (cfg["cpuLimit"] or 1)]
    full = [zn for zn, zv in zones.items() if cfg and zv["budget"]["cpuLimit"] - zv["used"]["cpu"] < (cfg["cpuLimit"] or 1)]
    if not (cfg and free):
        print("\n  overrides: no zone has room for a probe namespace; skipped")
        return None
    zone, sto = free[0], (cfg["storage"] or [{}])[0]
    # Names the platform may quote back in a refusal: register them, so the scrub replaces them in the record.
    for family, key in (("region", "regionName"), ("vpc", "vpcName"), ("seg", "segName")):
        if model_spec.get(key):
            L.get(family, model_spec[key])
    base = {"name": zone, "cpuLimit": f"{cfg['cpuLimit']}M", "cpuReservation": f"{cfg['cpuReservation']}M",
            "memoryLimit": f"{cfg['memoryLimit']}Mi", "memoryReservation": f"{cfg['memoryReservation']}Mi"}
    sto_name = next((real for real, lab in L.maps.get("storageclass", {}).items()
                     if "{{%s}}" % lab == sto.get("class")), None)
    cases = [
        ("cpu limit above the class config", {"zones": [dict(base, cpuLimit=f"{cfg['cpuLimit'] * 2}M")]}, ""),
        ("cpu limit below the class config", {"zones": [dict(base, cpuLimit=f"{max(cfg['cpuLimit'] // 2, 1)}M")]}, ""),
        ("no override at all", {}, ""),
        ("the zone named, but no numbers with it", {"zones": [{"name": zone}]}, ""),
    ]
    if sto_name and sto.get("limit"):
        cases += [
            ("storage below the class config",
             {"zones": [dict(base)], "storageClasses": [{"name": sto_name, "limit": f"{sto['limit'] // 2}Mi"}]}, ""),
            ("storage above the class config",
             {"zones": [dict(base)], "storageClasses": [{"name": sto_name, "limit": f"{sto['limit'] * 2}Mi"}]}, ""),
        ]
    if full:
        cases.append(("the class config's figures, in a zone with no limit budget left",
                      {"zones": [dict(base, name=full[0])]}, ""))
    cases.append(("the class config's figures, sent as a dry run", {"zones": [dict(base)]}, "?dryRun=All"))
    before = zone_figures(c, L)
    print(f"\n  overrides: asking a create in {L.get('project', proj)} which way it may depart from class {cls}'s config")
    results, made = [], []
    path = f"/apis/{INFRA3}/namespaces/{proj}/supervisornamespaces"
    for label, ov, query in cases:
        body = {"apiVersion": INFRA3, "kind": "SupervisorNamespace",
                "metadata": {"generateName": "probe-ovr-", "namespace": proj},
                "spec": {"className": cls, "description": "override probe, deleted by the same run",
                         "regionName": model_spec.get("regionName"), "vpcName": model_spec.get("vpcName"),
                         "segName": model_spec.get("segName"), "classConfigOverrides": ov}}
        st, r = c.send("POST", path + query, body)
        if st in (200, 201) and isinstance(r, dict):
            name = (r.get("metadata") or {}).get("name")
            # A dry run that is honoured returns the object without making it; read it back to know which.
            exists = bool(name) and c.get(f"{path}/{name}")[0] == 200
            held = (r.get("spec", {}).get("classConfigOverrides", {}).get("zones") or [{}])[0]
            hsto = (r.get("spec", {}).get("classConfigOverrides", {}).get("storageClasses") or [{}])[0]
            results.append({"case": label, "status": st, "outcome": "accepted", "persisted": exists,
                            "held": {"cpuLimit": held.get("cpuLimit"), "memoryLimit": held.get("memoryLimit"),
                                     "storageLimit": hsto.get("limit")}})
            if name:   # deleted whatever the read-back said: a namespace the read missed is still one this run made
                made.append(name)
                c.send("DELETE", f"{path}/{name}")
            print(f"     {label:<62} HTTP {st}  accepted, holds cpu {held.get('cpuLimit')}, "
                  f"storage {hsto.get('limit') or 'the class config'}; "
                  f"{'deleted' if exists else 'read back as absent, delete sent anyway'}")
        else:
            msg = L.scrub(r.get("message") if isinstance(r, dict) else str(r)) or ""
            results.append({"case": label, "status": st, "outcome": "refused", "message": msg})
            print(f"     {label:<62} HTTP {st}  refused: {msg[:120].rstrip()}")
    # A delete answers 200 and sets deletionTimestamp at once, but the object stays in phase Created and its
    # budget stays spoken for until teardown finishes. Wait generously and re-issue, then time what it took.
    began, still = time.time(), list(made)
    for round_no in range(80):
        st, nss = c.get(path)
        still = [n["metadata"]["name"] for n in (((nss or {}).get("items") or []) if st == 200 else [])
                 if n["metadata"]["name"] in made]
        if not still:
            break
        if round_no and round_no % 8 == 0:
            for nm in still:
                c.send("DELETE", f"{path}/{nm}")
            print(f"     still tearing down after {round_no * 15}s ({len(still)} left); delete re-issued")
        time.sleep(15)
    teardown = round(time.time() - began)
    # The namespaces are gone; read the zones until they match the figures from before the first create, for two
    # minutes at most. A difference after that is reported as it stands: another write during the run reads the same.
    after = zone_figures(c, L)
    for _ in range(8):
        if after == before or still:
            break
        time.sleep(15)
        after = zone_figures(c, L)
    returned = after == before
    if still:
        print(f"     WARNING: {len(still)} probe namespace(s) are still deleting after 20 minutes. They hold zone and")
        print("     storage budget until they finish. Re-run a listing before trusting the ledger above.")
    else:
        print(f"     {sum(1 for r in results if r.get('persisted'))} probe namespace(s) created and deleted; "
              f"all gone {teardown}s after the last create")
    print(f"     the zones {'read as they did before the first create' if returned else 'differ from their figures before the first create'}")
    return {"probedUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "project": L.get("project", proj),
            "class": cls, "cases": results, "made": sum(1 for r in results if r.get("persisted")), "teardownSeconds": teardown,
            "residue": [L.get("namespace", n) for n in still], "zonesReturned": returned,
            "zonesBefore": before, "zonesAfter": after}


def refuse_unknown_args(known, takes_value=()):
    """Refuse any argument this script does not recognise, before a client opens: a stray flag such as --check
    must never reach a write. --help prints the usage above."""
    args = sys.argv[1:]
    if "-h" in args or "--help" in args:
        print(__doc__)
        sys.exit(0)
    unknown = [a for i, a in enumerate(args) if a not in known and not (i and args[i - 1] in takes_value)]
    if unknown:
        print(f"unknown argument(s) {unknown}: this script takes {', '.join(sorted(known))} (see --help)", file=sys.stderr)
        sys.exit(5)


def main():
    refuse_unknown_args({"--probe-overrides", "--project"}, takes_value=("--project",))
    args = sys.argv[1:]
    probe_project = args[args.index("--project") + 1] if "--project" in args[:-1] else None
    if "--probe-overrides" in args and not probe_project:
        print("--probe-overrides writes, so it takes --project <name>: the project its namespaces are made in",
              file=sys.stderr)
        sys.exit(5)
    host, org = os.environ["VCFA_HOST"], os.environ["VCFA_ORG"]
    try:
        refresh, password = secret("VCFA_REFRESH_TOKEN"), secret("VCFA_PASSWORD")
    except OSError as e:   # a secret file that is missing, unreadable or open to group or other
        print(f"FATAL: {e}")
        sys.exit(2)
    user = os.environ.get("VCFA_USER")
    if not refresh and not (user and password):
        print("FATAL: set VCFA_REFRESH_TOKEN_FILE, or VCFA_USER with VCFA_PASSWORD_FILE (see --help)")
        sys.exit(2)
    out_dir = os.environ.get("OUT_DIR", ".")
    c = Cci(host, org, refresh, None if refresh else user, None if refresh else password)
    L = Labels()
    print("capacity.py: the capacity plane, added up rather than described\n")

    # ---- 1. the zones: a budget in spec, a consumption in status, for two different things
    # Label every name other objects refer to, before reading the objects that refer to them.
    for o in c.items(INFRA1, "regionstorageclassquotas"):
        L.get("storageclass", (o.get("spec") or {}).get("storageClassName") or "")
    for o in c.items(INFRA2, "supervisornamespaceclassconfigs"):
        for sc in ((o.get("spec") or {}).get("storageClasses") or []):
            L.get("storageclass", sc.get("name") or "")
    zones = {}
    units = {}
    zone_objs = c.items(TOPO, "zones")
    for o in zone_objs:
        sp, stt = o.get("spec") or {}, o.get("status") or {}
        units.setdefault("cpu", unit(sp.get("cpuLimit"), "M"))
        units.setdefault("memory", unit(sp.get("memoryLimit"), "Mi"))
        zn = sp.get("zoneName") or o["metadata"]["name"]
        L.get("zone", zn)
        zones[zn] = {"name": L.scrub(zn),
                     "budget": {k: qty(sp.get(k)) for k in BUDGET},
                     "used": {"cpu": qty(stt.get("cpuUsed")), "memory": qty(stt.get("memoryUsed")),
                              "cpuReservation": qty(stt.get("cpuReservationUsed")),
                              "memoryReservation": qty(stt.get("memoryReservationUsed"))},
                     "objectNameIsAnIdentifier": bool(UUID.fullmatch(o["metadata"]["name"]))}
    units.setdefault("cpu", "M"); units.setdefault("memory", "Mi")
    units["note"] = ("cpu is SI mega (a 60000M limit is 60 GHz); memory and storage are binary mebi "
                     "(a 131072Mi limit is 128 GiB). Two unit families in one object, so a figure carried "
                     "without its suffix cannot be converted later.")
    print(f"  zones: {len(zones)}; units as returned: cpu in {units['cpu']}, memory in {units['memory']}")
    # A zone's object name is an identifier, not the readable name in its spec. Ask for one zone by that name and
    # record the answer beside the list's: on 9.1 a direct get answered 404 while the list returned the object.
    by_name = c.get(f"/apis/{TOPO}/zones/{zone_objs[0]['metadata']['name']}")[0] if zone_objs else None
    print(f"  a zone asked for by its own object name: HTTP {by_name}; the list returned it")

    # ---- 2. the namespaces, each with a budget of its own
    projects = c.items("project.cci.vmware.com/v1alpha2", "projects")
    claims, namespaces, model_spec, bindings = {}, [], None, []
    for p in projects:
        pname = p["metadata"]["name"]
        L.get("project", pname)
        nss = c.items(INFRA3, f"namespaces/{pname}/supervisornamespaces")
        held = {}
        for family, kind in (("regions", "topology.cci.vmware.com/v1alpha1/namespaces/%s/regionbindings"),
                             ("classes", "infrastructure.cci.vmware.com/v1alpha1/namespaces/%s/supervisornamespaceclassbindings"),
                             ("vpcs", "vpc.nsx.vmware.com/v1alpha1/namespaces/%s/vpcbindings")):
            st, body = c.get("/apis/" + kind % pname)
            held[family] = len((body or {}).get("items") or []) if st == 200 and isinstance(body, dict) else f"HTTP {st}"
        bindings.append({"project": L.get("project", pname), "namespaces": len(nss), "bindings": held})
        for ns in nss:
            sp = ns.get("spec") or {}
            L.get("namespace", ns["metadata"]["name"])
            ov = (sp.get("classConfigOverrides") or {})
            per_zone = ov.get("zones") or []
            # The probe copies region, VPC and service engine group from a namespace, its own project's first.
            if model_spec is None or (pname == probe_project and not model_spec.get("_own")):
                model_spec = dict(sp, _own=pname == probe_project)
            namespaces.append({"name": L.scrub(ns["metadata"]["name"]), "class": sp.get("className"),
                               "zones": [{"zone": L.scrub(z.get("name") or ""), **{k: qty(z.get(k)) for k in BUDGET}}
                                         for z in per_zone],
                               "storage": [{"class": L.scrub(s.get("name") or ""), "limit": qty(s.get("limit"))}
                                           for s in (ov.get("storageClasses") or [])]})
            for z in per_zone:
                cl = claims.setdefault(z.get("name"), {k: 0 for k in BUDGET} | {"namespaces": 0})
                for k in BUDGET:
                    cl[k] += qty(z.get(k))
                cl["namespaces"] += 1
    print(f"  projects: {len(projects)}; namespaces: {len(namespaces)}")
    for b in bindings:
        print(f"     {b['project']:<16} {b['namespaces']} namespace(s); bindings: "
              + ", ".join(f"{k} {v}" for k, v in b["bindings"].items()))

    # ---- 3. the ledger check: which number does the zone's consumption actually equal?
    ledger = []
    print("\n  the ledger, per zone (cpu first, then memory and what is left):")
    for zn, zv in sorted(zones.items()):
        cl = claims.get(zn) or {k: 0 for k in BUDGET} | {"namespaces": 0}
        mem_balances = cl["memoryLimit"] == zv["used"]["memory"]
        matches_limits = cl["cpuLimit"] == zv["used"]["cpu"]
        matches_res = cl["cpuReservation"] == zv["used"]["cpu"]
        verdict = ("the sum of the namespaces' limits" if matches_limits and not matches_res
                   else "the sum of the namespaces' reservations" if matches_res and not matches_limits
                   else "both are equal here, so this zone cannot tell them apart" if matches_limits and matches_res
                   else "neither, which is worth investigating")
        ledger.append({"zone": zv["name"], "namespaces": cl["namespaces"],
                       "sumOfLimits": cl["cpuLimit"], "sumOfReservations": cl["cpuReservation"],
                       "zoneReportsUsed": zv["used"]["cpu"], "matches": verdict,
                       "memorySumOfLimits": cl["memoryLimit"], "memoryReportsUsed": zv["used"]["memory"],
                       "memoryBalances": mem_balances,
                       "cpuFree": zv["budget"]["cpuLimit"] - zv["used"]["cpu"],
                       "memoryFree": zv["budget"]["memoryLimit"] - zv["used"]["memory"],
                       "reservationBudget": zv["budget"]["cpuReservation"],
                       "reservationDrawnDown": zv["used"]["cpuReservation"]})
        print(f"     {zv['name']:<16} {cl['namespaces']} namespace(s); zone reports {zv['used']['cpu']} used; "
              f"limits sum to {cl['cpuLimit']}, reservations to {cl['cpuReservation']}: {verdict}")
        print(f"     {'':<16} memory: limits sum to {cl['memoryLimit']}, zone reports {zv['used']['memory']} used; "
              f"left: cpu {zv['budget']['cpuLimit'] - zv['used']['cpu']}{units['cpu']}, memory "
              f"{zv['budget']['memoryLimit'] - zv['used']['memory']}{units['memory']}; reservation drawn "
              f"{zv['used']['cpuReservation']} of {zv['budget']['cpuReservation']}")

    # ---- 4. the contract check: what the class promised against what the namespace holds
    classes = [o["metadata"]["name"] for o in c.items(INFRA2, "supervisornamespaceclasses")]
    configs = {}
    for o in c.items(INFRA2, "supervisornamespaceclassconfigs"):
        sp = o.get("spec") or {}
        z = (sp.get("zones") or [{}])[0]
        # A config keyed to a class carries the class's name, which is kept. Any other config name is the
        # organization's own, and a record keyed on it must carry its placeholder (G-637).
        cname = o["metadata"]["name"]
        configs[cname if cname in classes else L.get("classconfig", cname)] = {
            "zoneList": [L.scrub(zz.get("name") or "") for zz in (sp.get("zones") or [])],
            **{k: qty(z.get(k)) for k in BUDGET},
            "storage": [{"class": L.scrub(s.get("name") or ""), "limit": qty(s.get("limit"))}
                        for s in (sp.get("storageClasses") or [])],
            "vmClasses": len(sp.get("vmClasses") or []),
        }
    tally = {f: {"same": 0, "above": 0, "below": 0} for f in BUDGET + ("storageLimit",)}
    widest, inherited = None, 0
    for ns in namespaces:
        cc = configs.get(ns["class"])
        if not cc or not ns["zones"]:
            continue
        got = ns["zones"][0]
        pairs = [(f, cc[f], got[f]) for f in BUDGET]
        # A namespace that omits its storage block takes the class config's limit (the probe's "no storage" cases
        # read it back), so an omitted block holds what the class promised rather than nothing.
        promised_sto = (cc["storage"] or [{"limit": 0}])[0]["limit"]
        inherited += not ns["storage"]
        pairs.append(("storageLimit", promised_sto, ns["storage"][0]["limit"] if ns["storage"] else promised_sto))
        for f, promised, held in pairs:
            tally[f]["same" if promised == held else "above" if held > promised else "below"] += 1
            if promised and held > promised and (widest is None or held / promised > widest["times"]):
                widest = {"class": ns["class"], "field": f, "promised": promised, "held": held,
                          "times": round(held / promised, 1)}
    agree = sum(v["same"] for v in tally.values())
    total = sum(sum(v.values()) for v in tally.values())
    print(f"\n  the contract: {len(classes)} class(es), {len(configs)} config(s)")
    print(f"     fields where the namespace holds exactly what its class promised: {agree} of {total} "
          f"({inherited} namespace(s) omit storage and take the class config's limit)")
    for f, v in tally.items():
        print(f"       {f:<20} same {v['same']:>2}   above the class {v['above']:>2}   below it {v['below']:>2}")
    if widest:
        print(f"     widest departure: class {widest['class']}, {widest['field']} promised {widest['promised']}, "
              f"namespace holds {widest['held']} ({widest['times']} times)")

    # ---- 5. the ledgers one level out
    storage = []
    for o in c.items(INFRA1, "regionstorageclassquotas"):
        sp, stt = o.get("spec") or {}, o.get("status") or {}
        L.get("storageclass", sp.get("storageClassName") or "")
        cap_raw, con_raw = sp.get("storageCapacity"), stt.get("storageConsumed")
        storage.append({"storageClass": L.scrub(sp.get("storageClassName") or ""),
                        "capacity": qty(cap_raw), "consumed": qty(con_raw),
                        "unit": unit(cap_raw, "Mi"),
                        "capacityTiB": tib(qty(cap_raw)), "consumedTiB": tib(qty(con_raw))})
    vmclasses = []
    for o in c.items(INFRA1, "regionvirtualmachineclasssummaries"):
        sp = o.get("spec") or {}
        vmclasses.append({"name": sp.get("vmClassName"), "cpuCount": sp.get("cpuCount"),
                          "memory": sp.get("memory"), "reservationRequired": bool(sp.get("reservationRequired"))})
    need_res = [v["name"] for v in vmclasses if v["reservationRequired"]]
    print(f"\n  storage ledgers: {len(storage)}; VM classes: {len(vmclasses)}, of which {len(need_res)} require a reservation")
    for s in storage:
        print(f"     {str(s['storageClass'])[:24]:<26} capacity {s['capacity']:>10}{s['unit']} ({s['capacityTiB']} TiB)"
              f"   consumed {s['consumed']:>9}{s['unit']} ({s['consumedTiB']} TiB)")

    # ---- 6. which way may a create depart from its class config? (only with --probe-overrides)
    overrides = None
    if "--probe-overrides" in args:
        if probe_project not in [p["metadata"]["name"] for p in projects]:
            print(f"--project {probe_project!r} is not a project this sign-in can see", file=sys.stderr)
            sys.exit(5)
        spec = {k: v for k, v in (model_spec or {}).items() if k != "_own"}
        overrides = probe_overrides(c, L, probe_project, configs, zones, spec)
    else:
        print("\n  overrides: not probed; pass --probe-overrides --project <name> to ask the platform at create "
              "(it creates namespaces there and deletes them again)")

    # ---- write, sanitized
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    payload = {"captured_utc": stamp, "signIn": c.kind,
               "units": units, "zoneGetByName": by_name,
               "zones": list(zones.values()), "namespaces": namespaces, "ledger": ledger,
               "classes": classes, "configs": {k: v for k, v in configs.items()},
               "contract": {"agree": agree, "total": total, "byField": tally, "widest": widest,
                            "storageInherited": inherited,
                            "exact": [ns["name"] for ns in namespaces if configs.get(ns["class"]) and ns["zones"]
                                      and all(configs[ns["class"]][f] == ns["zones"][0][f] for f in BUDGET)]},
               "overrides": overrides, "bindings": bindings,
               "storage": storage, "vmClasses": {"count": len(vmclasses), "requireReservation": len(need_res),
                                                 "sample": vmclasses[:4]}}

    # G-166, generically: an optional probe writes a section of a record, and it does not get to delete
    # one. A run without the probe flag leaves those keys None, and writing them would erase what a
    # flagged run captured. Carry forward any key this run has nothing to say about.
    _prior_path = os.path.join(out_dir, "capacity.json")
    if os.path.exists(_prior_path):
        try:
            _prior = json.load(open(_prior_path, encoding="utf-8")) or {}
        except ValueError:
            _prior = {}
        for _k, _v in list(payload.items()):
            if _v is None and _prior.get(_k) is not None:
                payload[_k] = _prior[_k]
                print(f"  carrying forward {_k!r} from an earlier run with the probe flag; "
                      f"this run did not re-probe it and has not erased it")

    text = UUID.sub("{{id}}", json.dumps(payload, indent=1, ensure_ascii=False))
    for value in (c.bearer, refresh, password, user, host, org):
        assert not value or value not in text, "an estate value reached the record"
    bare = re.sub(r"\{\{[^}]*\}\}", "", text)
    for fam, m in L.maps.items():
        for name in m:
            if name and re.search(r"(?<![A-Za-z0-9-])" + re.escape(name) + r"(?![A-Za-z0-9-])", bare):
                shape = re.sub(r"[A-Za-z]", "a", re.sub(r"[0-9]", "9", name))
                raise SystemExit(f"FATAL: a {fam} name ({len(name)} characters, shape {shape}) reached the record")
    os.makedirs(out_dir, exist_ok=True)
    open(os.path.join(out_dir, "capacity.json"), "w", encoding="utf-8").write(text + "\n")
    print(f"\nwrote capacity.json ({len(zones)} zones, {len(namespaces)} namespaces, {agree} of {total} contract "
          f"fields agreeing); every organization name replaced by a placeholder")
    if overrides and (overrides["residue"] or not overrides["zonesReturned"]):
        sys.exit(3)


if __name__ == "__main__":
    main()
