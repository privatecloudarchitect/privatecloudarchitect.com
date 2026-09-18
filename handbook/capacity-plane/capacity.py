#!/usr/bin/env python3
"""capacity.py: the capacity plane of a VCF Automation 9.1 organization, and whether its ledger balances.

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
  6. with --probe-overrides, the OVERRIDE CHECK: comparing what namespaces hold with what their class promised
     shows that they differ, but not why, because an override written at create and a class config edited
     afterwards leave identical evidence. This asks the platform directly, by creating namespaces that depart
     from the config deliberately and deleting them again.

Without --probe-overrides nothing here writes. Organization-specific names are replaced by stable placeholders and the script refuses to
write a record in which one survived. Sizes, class names, and field names are the product's own vocabulary and
are kept, because the arithmetic is the lesson.

Run:
  export VCFA_HOST=<automation-fqdn> VCFA_ORG=<org>
  export VCFA_REFRESH_TOKEN_FILE=/path/to/refresh-token    # mode 0600
  export TLS_VERIFY=false                                  # only on a self-signed lab CA
  python3 capacity.py
  python3 capacity.py --probe-overrides   # also creates and deletes namespaces, see step 6
"""
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


class Labels:
    def __init__(self):
        self.maps = {}

    def get(self, family, name):
        m = self.maps.setdefault(family, {})
        if name not in m:
            m[name] = f"{family}-{len(m) + 1}"
        return "{{%s}}" % m[name]

    def scrub(self, text):
        if not isinstance(text, str):
            return text
        known = [(real, label) for m in self.maps.values() for real, label in m.items()]
        for real, label in sorted(known, key=lambda kv: -len(kv[0])):
            text = text.replace(real, "{{%s}}" % label)
        return UUID.sub("{{id}}", text)


class Cci:
    def __init__(self, host, org, refresh_token):
        self.host = host
        body = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": refresh_token}).encode()
        req = urllib.request.Request(
            f"https://{host}/oauth/tenant/{org}/token", data=body, method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
        with urllib.request.urlopen(req, context=ctx(), timeout=30) as r:
            self.bearer = json.loads(r.read())["access_token"]

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
        st, body = self.get(f"/apis/{group}/{resource}")
        return (body.get("items") or []) if st == 200 and isinstance(body, dict) else []

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


def probe_overrides(c, L, projects, configs, zones, claims, model_spec):
    """Ask the platform, at create, which way a class config can be departed from.

    The chapter's central claim is that a class config is a default rather than a contract. Comparing what
    namespaces hold against what their class promised shows they differ, but it cannot tell you WHY: an
    override written at create and a class config edited afterwards leave identical evidence. This settles it
    by creating namespaces that depart from the config deliberately, reading what came back, and deleting them.

    Every namespace it creates it deletes. Deletion is asynchronous, so it waits for the budget to come back
    before it returns; a probe that exits early leaves the ledger reading high for several minutes.
    """
    if not projects:
        return None
    proj = projects[0]["metadata"]["name"]
    cfg = configs.get("small") or next(iter(configs.values()), None)
    cls = next((k for k, v in configs.items() if v is cfg), None)
    free = [zn for zn, zv in zones.items()
            if zv["budget"]["cpuLimit"] - zv["used"]["cpu"] >= 2 * (cfg["cpuLimit"] or 1)]
    if not (cfg and free):
        print("\n  overrides: no zone has room for a probe namespace; skipped")
        return None
    zone, sto = free[0], (cfg["storage"] or [{}])[0]
    base = {"name": zone, "cpuLimit": f"{cfg['cpuLimit']}M", "cpuReservation": f"{cfg['cpuReservation']}M",
            "memoryLimit": f"{cfg['memoryLimit']}Mi", "memoryReservation": f"{cfg['memoryReservation']}Mi"}
    sto_name = next((real for real, lab in L.maps.get("storageclass", {}).items()
                     if "{{%s}}" % lab == sto.get("class")), None)
    cases = [
        ("cpu limit above the class config", {"zones": [dict(base, cpuLimit=f"{cfg['cpuLimit'] * 2}M")]}),
        ("cpu limit below the class config", {"zones": [dict(base, cpuLimit=f"{max(cfg['cpuLimit'] // 2, 1)}M")]}),
        ("no override at all", {}),
        ("the zone named, but no numbers with it", {"zones": [{"name": zone}]}),
    ]
    if sto_name and sto.get("limit"):
        cases += [
            ("storage below the class config",
             {"zones": [dict(base)], "storageClasses": [{"name": sto_name, "limit": f"{sto['limit'] // 2}Mi"}]}),
            ("storage above the class config",
             {"zones": [dict(base)], "storageClasses": [{"name": sto_name, "limit": f"{sto['limit'] * 2}Mi"}]}),
        ]
    print(f"\n  overrides: asking a create which way it may depart from class {cls}'s config")
    results, made = [], []
    for label, ov in cases:
        body = {"apiVersion": INFRA3, "kind": "SupervisorNamespace",
                "metadata": {"generateName": "probe-ovr-", "namespace": proj},
                "spec": {"className": cls, "description": "override probe, deleted by the same run",
                         "regionName": model_spec.get("regionName"), "vpcName": model_spec.get("vpcName"),
                         "segName": model_spec.get("segName"), "classConfigOverrides": ov}}
        st, r = c.send("POST", f"/apis/{INFRA3}/namespaces/{proj}/supervisornamespaces", body)
        if st in (200, 201):
            held = (r.get("spec", {}).get("classConfigOverrides", {}).get("zones") or [{}])[0]
            hsto = (r.get("spec", {}).get("classConfigOverrides", {}).get("storageClasses") or [{}])[0]
            results.append({"case": label, "status": st, "outcome": "accepted",
                            "held": {"cpuLimit": held.get("cpuLimit"), "memoryLimit": held.get("memoryLimit"),
                                     "storageLimit": hsto.get("limit")}})
            made.append(r["metadata"]["name"])
            c.send("DELETE", f"/apis/{INFRA3}/namespaces/{proj}/supervisornamespaces/{r['metadata']['name']}")
            print(f"     {label:<44} HTTP {st}  accepted, holds cpu {held.get('cpuLimit')}, "
                  f"storage {hsto.get('limit') or 'the class config'}; deleted")
        else:
            msg = L.scrub(r.get("message") if isinstance(r, dict) else str(r)) or ""
            results.append({"case": label, "status": st, "outcome": "refused", "message": msg})
            print(f"     {label:<44} HTTP {st}  refused: {msg[:120]}")
    # A delete answers 200 and sets deletionTimestamp at once, but the object stays in phase Created and its
    # budget stays spoken for until teardown finishes. Observed between well under a minute and past ten, so
    # wait generously and re-issue, rather than leaving someone's ledger reading high with no explanation.
    for round_no in range(80):
        st, nss = c.get(f"/apis/{INFRA3}/namespaces/{proj}/supervisornamespaces")
        still = [n["metadata"]["name"] for n in ((nss.get("items") or []) if st == 200 else [])
                 if n["metadata"]["name"] in made]
        if not still:
            print(f"     {len(made)} probe namespace(s) created and deleted; the ledger is back where it started")
            return results
        if round_no and round_no % 8 == 0:
            for nm in still:
                c.send("DELETE", f"/apis/{INFRA3}/namespaces/{proj}/supervisornamespaces/{nm}")
            print(f"     still tearing down after {round_no * 15}s ({len(still)} left); delete re-issued")
        time.sleep(15)
    print(f"     WARNING: {len(still)} probe namespace(s) are still deleting after 20 minutes. They hold zone and")
    print("     storage budget until they finish. Re-run a listing before trusting the ledger above.")
    return results


def main():
    host, org = os.environ["VCFA_HOST"], os.environ["VCFA_ORG"]
    refresh = open(os.environ["VCFA_REFRESH_TOKEN_FILE"], encoding="utf-8").read().strip()
    out_dir = os.environ.get("OUT_DIR", ".")
    c = Cci(host, org, refresh)
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
    for o in c.items(TOPO, "zones"):
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

    # ---- 2. the namespaces, each with a budget of its own
    st, projects = c.get(f"/apis/project.cci.vmware.com/v1alpha2/projects")
    projects = (projects.get("items") or []) if st == 200 else []
    claims, namespaces, model_spec = {}, [], None
    for p in projects:
        pname = p["metadata"]["name"]
        L.get("project", pname)
        st, nss = c.get(f"/apis/{INFRA3}/namespaces/{pname}/supervisornamespaces")
        for ns in ((nss.get("items") or []) if st == 200 else []):
            sp = ns.get("spec") or {}
            L.get("namespace", ns["metadata"]["name"])
            ov = (sp.get("classConfigOverrides") or {})
            per_zone = ov.get("zones") or []
            model_spec = model_spec or sp
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

    # ---- 3. the ledger check: which number does the zone's consumption actually equal?
    ledger = []
    for zn, zv in sorted(zones.items()):
        cl = claims.get(zn) or {k: 0 for k in BUDGET} | {"namespaces": 0}
        matches_limits = cl["cpuLimit"] == zv["used"]["cpu"]
        matches_res = cl["cpuReservation"] == zv["used"]["cpu"]
        verdict = ("the sum of the namespaces' limits" if matches_limits and not matches_res
                   else "the sum of the namespaces' reservations" if matches_res and not matches_limits
                   else "both are equal here, so this zone cannot tell them apart" if matches_limits and matches_res
                   else "neither, which is worth investigating")
        ledger.append({"zone": zv["name"], "namespaces": cl["namespaces"],
                       "sumOfLimits": cl["cpuLimit"], "sumOfReservations": cl["cpuReservation"],
                       "zoneReportsUsed": zv["used"]["cpu"], "matches": verdict,
                       "cpuFree": zv["budget"]["cpuLimit"] - zv["used"]["cpu"],
                       "memoryFree": zv["budget"]["memoryLimit"] - zv["used"]["memory"],
                       "reservationBudget": zv["budget"]["cpuReservation"],
                       "reservationDrawnDown": zv["used"]["cpuReservation"]})
        print(f"     {zv['name']:<16} {cl['namespaces']} namespace(s); zone reports {zv['used']['cpu']} used; "
              f"limits sum to {cl['cpuLimit']}, reservations to {cl['cpuReservation']}: {verdict}")

    # ---- 4. the contract check: what the class promised against what the namespace holds
    configs = {}
    for o in c.items(INFRA2, "supervisornamespaceclassconfigs"):
        sp = o.get("spec") or {}
        z = (sp.get("zones") or [{}])[0]
        configs[o["metadata"]["name"]] = {
            "zoneList": [zz.get("name") for zz in (sp.get("zones") or [])],
            **{k: qty(z.get(k)) for k in BUDGET},
            "storage": [{"class": L.scrub(s.get("name") or ""), "limit": qty(s.get("limit"))}
                        for s in (sp.get("storageClasses") or [])],
            "vmClasses": len(sp.get("vmClasses") or []),
        }
    classes = [o["metadata"]["name"] for o in c.items(INFRA2, "supervisornamespaceclasses")]
    tally = {f: {"same": 0, "above": 0, "below": 0} for f in BUDGET + ("storageLimit",)}
    widest = None
    for ns in namespaces:
        cc = configs.get(ns["class"])
        if not cc or not ns["zones"]:
            continue
        got = ns["zones"][0]
        pairs = [(f, cc[f], got[f]) for f in BUDGET]
        pairs.append(("storageLimit", (cc["storage"] or [{"limit": 0}])[0]["limit"],
                      (ns["storage"] or [{"limit": 0}])[0]["limit"]))
        for f, promised, held in pairs:
            tally[f]["same" if promised == held else "above" if held > promised else "below"] += 1
            if promised and held > promised and (widest is None or held / promised > widest["times"]):
                widest = {"class": ns["class"], "field": f, "promised": promised, "held": held,
                          "times": round(held / promised, 1)}
    agree = sum(v["same"] for v in tally.values())
    total = sum(sum(v.values()) for v in tally.values())
    print(f"\n  the contract: {len(classes)} class(es), {len(configs)} config(s)")
    print(f"     fields where the namespace holds exactly what its class promised: {agree} of {total}")
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
    if "--probe-overrides" in sys.argv:
        overrides = probe_overrides(c, L, projects, configs, zones, claims, model_spec or {})
    else:
        print("\n  overrides: not probed; pass --probe-overrides to ask the platform at create "
              "(it creates namespaces and deletes them again)")
    print("  note: this interface offers no dry run on a create; see the chapter's plate on admission")

    # ---- write, sanitized
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    payload = {"captured_utc": stamp,
               "units": units,
               "zones": list(zones.values()), "namespaces": namespaces, "ledger": ledger,
               "classes": classes, "configs": {k: v for k, v in configs.items()},
               "contract": {"agree": agree, "total": total, "byField": tally, "widest": widest},
               "overrides": overrides,
               "storage": storage, "vmClasses": {"count": len(vmclasses), "requireReservation": len(need_res),
                                                 "sample": vmclasses[:4]}}
    text = UUID.sub("{{id}}", json.dumps(payload, indent=1, ensure_ascii=False))
    for secret in (c.bearer, refresh, host, org):
        assert secret not in text, "an estate value reached the record"
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


if __name__ == "__main__":
    main()
