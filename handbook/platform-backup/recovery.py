#!/usr/bin/env python3
"""recovery.py: what actually protects the management plane, read from every plane that will answer.

A backup configuration says what is supposed to happen. It is not evidence that anything happened, and on the
estate this was written against the two disagree in a way no status field reports. So this reads the
configuration AND the run history on each plane, and puts them side by side:

  1. the SCHEDULES, as each plane encodes them. Three planes here use three different encodings and not one of
     them contains the word "daily": a frequency named WEEKLY whose day list holds all seven days, an empty
     day list that means every day, and a WeeklyBackupSchedule whose day list holds five;
  2. the RUN HISTORY, which is the only thing that settles cadence. Every run is counted, the calendar days it
     covers are counted, and the days it does NOT cover are reported as gaps with their dates. A gap leaves no
     failed record behind, because nothing ran: the runs that did happen all succeeded, and a monitor watching
     for failures sees perfect health straight through the hole;
  3. what the COPY CONTAINS, where the plane publishes a parts catalog. A schedule lists what is selected. It
     does not say which defaults were deselected, and that subtraction is the interesting half;
  4. the TARGET each plane writes to, compared, because a recovery plan has as many single points as the
     targets have in common;
  5. the RESTORE EVIDENCE: whether a restore has ever run here. Each plane answers differently, and one of
     them answers with an HTTP 500 whose message reads like a broken endpoint.

SAFETY. Backup configurations carry credentials for the target. Every response passes through ``strip_secrets``
inside the function that performs the request, which deletes the secret-bearing keys on arrival and keeps only
a boolean saying whether something was there. Nothing downstream can leak a value because no value survives the
read. If you extend this script, extend ``SECRET_KEYS`` first.

Read-only throughout. Nothing here takes, deletes or restores a backup.

Run:
  export SDDC_HOST=<sddc-manager-fqdn>  SDDC_TOKEN_FILE=/path/to/bearer          # mode 0600
  export VC_HOST=<vcenter-fqdn>         VC_SESSION_FILE=/path/to/session-id      # optional
  export NSX_HOST=<nsx-manager-fqdn>    NSX_BASIC_FILE=/path/to/user:password    # optional, mode 0600
  export TLS_VERIFY=false                                                        # only on a self-signed lab CA
  python3 recovery.py
"""
import base64
import collections
import datetime as dt
import json
import os
import re
import ssl
import time
import urllib.error
import urllib.request

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
FINGERPRINT = re.compile(r"\b(?:SHA256|SHA1|MD5):[A-Za-z0-9+/=:]{10,}")

# Anything that could carry secret material. A key listed here is destroyed on arrival and replaced by a
# boolean. Add to this list before adding any new read.
SECRET_KEYS = ("password", "passphrase", "encryptionPassphrase", "privateKey", "secret", "token",
               "sshKey", "backupPassphrase")


def strip_secrets(obj):
    """Destroy secret-bearing values on arrival, keeping only whether something was present."""
    if isinstance(obj, list):
        return [strip_secrets(x) for x in obj]
    if not isinstance(obj, dict):
        return obj
    out = {}
    for k, val in obj.items():
        if k in SECRET_KEYS:
            out[k + "_present"] = bool(val)
        else:
            out[k] = strip_secrets(val)
    return out


def ctx():
    verify = os.environ.get("TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")
    return ssl.create_default_context() if verify else ssl._create_unverified_context()


class Labels:
    """Estate values become stable placeholders. The product's own vocabulary is never replaced."""

    RESERVED = {"SDDC_MANAGER", "SFTP", "sftp", "SUCCESS", "SUCCESSFUL", "Successful", "FAILED", "INITIAL",
                "common", "seat", "supervisors", "WEEKLY", "DAILY", "HOURLY", "PASSWORD", "none", "all",
                "WeeklyBackupSchedule", "default"}

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
        text = FINGERPRINT.sub("{{fingerprint}}", text)
        text = IPV4.sub("{{address}}", text)
        return UUID.sub("{{id}}", text)


def coverage(days):
    """Turn a set of calendar days into a window, the days it covers, and the gaps it does not.

    This is the whole argument of the chapter in six lines. A run history is a list of successes; the days
    BETWEEN them are what nobody reports, because an absence leaves no record to fail.
    """
    if not days:
        return None
    lo, hi = min(days), max(days)
    span = (hi - lo).days + 1
    missing = [lo + dt.timedelta(days=i) for i in range(span) if (lo + dt.timedelta(days=i)) not in days]
    gaps, cur = [], []
    for d in missing:
        if cur and (d - cur[-1]).days == 1:
            cur.append(d)
        else:
            if cur:
                gaps.append(cur)
            cur = [d]
    if cur:
        gaps.append(cur)
    gaps.sort(key=len, reverse=True)
    return {"firstDay": str(lo), "lastDay": str(hi), "windowDays": span, "daysCovered": len(days),
            "daysUncovered": len(missing), "gaps": len(gaps),
            "longestGapDays": len(gaps[0]) if gaps else 0,
            "longestGap": [str(gaps[0][0]), str(gaps[0][-1])] if gaps else None,
            "gapsBySize": [{"days": len(g), "from": str(g[0]), "to": str(g[-1])} for g in gaps[:6]]}


def split_location(url, L):
    """sftp://host/dir -> the same three fields the other planes publish separately.

    Without this the cross-plane target comparison compares description shapes, which always differ, and would
    report three distinct targets where there is one.
    """
    m = re.match(r"([a-z]+)://([^/]+)(/.*)?$", url or "")
    if not m:
        return {"protocol": None, "server": None, "directory": None}
    return {"protocol": m.group(1).upper(),
            "server": L.get("target", m.group(2)),
            "directory": L.get("path", m.group(3) or "")}


def reader(host, headers):
    """One GET helper per plane, with the secret strip applied before anything else can see the body."""

    def get(path):
        rq = urllib.request.Request(f"https://{host}{path}", headers=dict(headers, Accept="application/json"))
        try:
            with urllib.request.urlopen(rq, context=ctx(), timeout=180) as r:
                return r.status, strip_secrets(json.loads(r.read() or b"null"))
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, strip_secrets(json.loads(raw))
            except ValueError:
                return e.code, raw.decode(errors="replace")[:200]
        except (urllib.error.URLError, OSError) as e:
            return None, str(e)[:120]

    return get


def read_sddc(L):
    host, tf = os.environ.get("SDDC_HOST"), os.environ.get("SDDC_TOKEN_FILE")
    if not (host and tf and os.path.exists(tf)):
        return {"plane": "the lifecycle manager", "reached": False,
                "why": "set SDDC_HOST and SDDC_TOKEN_FILE to include this plane"}
    get = reader(host, {"Authorization": "Bearer " + open(tf, encoding="utf-8").read().strip()})
    st, cfg = get("/v1/system/backup-configuration")
    locs = (cfg.get("backupLocations") or []) if isinstance(cfg, dict) else []
    scheds = (cfg.get("backupSchedules") or []) if isinstance(cfg, dict) else []
    s0 = scheds[0] if scheds else {}
    st, t = get("/v1/tasks?limit=2000")
    tasks = (t.get("elements") or []) if isinstance(t, dict) else []
    runs = sorted([e for e in tasks if e.get("type") == "SDDCMANAGER_BACKUP"],
                  key=lambda e: e.get("creationTimestamp") or "")
    stamps = [dt.datetime.fromisoformat(e["creationTimestamp"].replace("Z", "+00:00")) for e in runs
              if e.get("creationTimestamp")]
    statuses = collections.Counter(e.get("status") for e in runs)
    sub, seconds = [], None
    if runs:
        st, one = get(f"/v1/tasks/{runs[-1]['id']}")
        steps = (one.get("subTasks") or []) if isinstance(one, dict) else []
        sub = [s.get("name") for s in steps]
        # How long a run takes is a number the chapter states, so it comes from here rather than from prose.
        if steps and steps[0].get("creationTimestamp") and steps[-1].get("completionTimestamp"):
            a = dt.datetime.fromisoformat(steps[0]["creationTimestamp"].replace("Z", "+00:00"))
            b = dt.datetime.fromisoformat(steps[-1]["completionTimestamp"].replace("Z", "+00:00"))
            seconds = round((b - a).total_seconds())
    return {"plane": "the lifecycle manager", "reached": True,
            "configured": bool(cfg.get("isConfigured")) if isinstance(cfg, dict) else None,
            "schedule": {"field": "frequency", "says": s0.get("frequency"),
                         "daysListed": len(s0.get("daysOfWeek") or []),
                         "days": list(s0.get("daysOfWeek") or []),
                         "atHour": s0.get("hourOfDay"), "atMinute": s0.get("minuteOfHour"),
                         "onStateChange": s0.get("takeBackupOnStateChange"),
                         "enabled": s0.get("takeScheduledBackups"),
                         "retention": s0.get("retentionPolicy")},
            "target": {"protocol": (locs[0] or {}).get("protocol") if locs else None,
                       "port": (locs[0] or {}).get("port") if locs else None,
                       "server": L.get("target", (locs[0] or {}).get("server")) if locs else None,
                       "directory": L.get("path", (locs[0] or {}).get("directoryPath")) if locs else None,
                       "username": L.get("account", (locs[0] or {}).get("username")) if locs else None,
                       "fingerprintPinned": bool((locs[0] or {}).get("sshFingerprint")) if locs else None},
            "runs": {"total": len(runs), "byStatus": dict(statuses),
                     "carryingAnError": sum(1 for e in runs if e.get("errors")),
                     "hourOfDay": dict(collections.Counter(x.hour for x in stamps))},
            "coverage": coverage({x.date() for x in stamps}),
            "whatARunDoes": sub, "aRunTakesSeconds": seconds,
            "tasksRead": len(tasks)}


def read_vcenter(L):
    host, sf = os.environ.get("VC_HOST"), os.environ.get("VC_SESSION_FILE")
    if not (host and sf and os.path.exists(sf)):
        return {"plane": "the management vCenter", "reached": False,
                "why": "set VC_HOST and VC_SESSION_FILE to include this plane"}
    get = reader(host, {"vmware-api-session-id": open(sf, encoding="utf-8").read().strip()})
    st, scheds = get("/api/appliance/recovery/backup/schedules")
    name, s0 = (list(scheds.items())[0] if isinstance(scheds, dict) and scheds else (None, {}))
    rec = (s0 or {}).get("recurrence_info") or {}
    st, parts = get("/api/appliance/recovery/backup/parts")
    catalog = [{"id": p.get("id"), "optional": p.get("optional"),
                "selectedByDefault": p.get("selected_by_default"),
                "what": (p.get("description") or {}).get("default_message")}
               for p in (parts if isinstance(parts, list) else [])]
    selected = list((s0 or {}).get("parts") or [])
    st, jobs = get("/api/appliance/recovery/backup/job")
    jobs = jobs if isinstance(jobs, list) else []
    days = set()
    for j in jobs:
        m = re.match(r"(\d{4})(\d{2})(\d{2})-", str(j))
        if m:
            days.add(dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
    last = {}
    if jobs:
        st, one = get(f"/api/appliance/recovery/backup/job/{jobs[0]}")
        last = {"state": one.get("state"), "progress": one.get("progress"),
                "messages": len(one.get("messages") or [])} if isinstance(one, dict) else {}
    st_r, restore = get("/api/appliance/recovery/restore/job")
    return {"plane": "the management vCenter", "reached": True,
            "schedule": {"field": "recurrence_info.days", "daysListed": len(rec.get("days") or []),
                         # This plane has no field that names a cadence at all, which is a fact about the
                         # object rather than a gap in the read, so the record carries null and the chapter
                         # renders it as "not stated" beside the two planes that do name one and are wrong.
                         "says": None,
                         "emptyDayListMeans": "every day",
                         "atHour": rec.get("hour"), "atMinute": rec.get("minute"),
                         "enabled": (s0 or {}).get("enable"),
                         "retention": (s0 or {}).get("retention_info")},
            "target": dict(split_location(str((s0 or {}).get("location") or ""), L),
                           username=L.get("account", (s0 or {}).get("location_user"))),
            "parts": {"catalog": catalog, "selected": selected,
                      "deselectedDefaults": [p["id"] for p in catalog
                                             if p["selectedByDefault"] and p["id"] not in selected]},
            "runs": {"total": len(jobs), "mostRecent": last},
            "coverage": coverage(days),
            "restoreEvidence": {"status": st_r,
                                "message": L.scrub(json.dumps(restore))[:200] if restore else ""}}


def read_nsx(L):
    host, bf = os.environ.get("NSX_HOST"), os.environ.get("NSX_BASIC_FILE")
    if not (host and bf and os.path.exists(bf)):
        return {"plane": "the network manager", "reached": False,
                "why": "set NSX_HOST and NSX_BASIC_FILE to include this plane"}
    cred = open(bf, encoding="utf-8").read().strip()
    get = reader(host, {"Authorization": "Basic " + base64.b64encode(cred.encode()).decode()})
    st, cfg = get("/api/v1/cluster/backups/config")
    sch = (cfg.get("backup_schedule") or {}) if isinstance(cfg, dict) else {}
    srv = (cfg.get("remote_file_server") or {}) if isinstance(cfg, dict) else {}
    proto = srv.get("protocol") or {}
    st, hist = get("/api/v1/cluster/backups/history")
    cl = (hist.get("cluster_backup_statuses") or []) if isinstance(hist, dict) else []
    inv = (hist.get("inventory_backup_statuses") or []) if isinstance(hist, dict) else []
    st_r, restore = get("/api/v1/cluster/restore/status")
    return {"plane": "the network manager", "reached": True,
            "schedule": {"field": "resource_type", "says": sch.get("resource_type"),
                         "daysListed": len(sch.get("days_of_week") or []),
                         "days": sorted(sch.get("days_of_week") or []),
                         "dayNumbering": "the plane publishes integers; a run observed on a Friday carries 5, "
                                         "which fixes 6 and 0-or-7 as the two absent days under either "
                                         "convention this platform could be using",
                         "atHour": sch.get("hour_of_day"), "atMinute": sch.get("minute_of_day"),
                         "enabled": cfg.get("backup_enabled") if isinstance(cfg, dict) else None,
                         "inventorySummaryIntervalMinutes": cfg.get("inventory_summary_interval")
                         if isinstance(cfg, dict) else None},
            "target": {"protocol": proto.get("protocol_name"), "port": srv.get("port"),
                       "server": L.get("target", srv.get("server")),
                       "directory": L.get("path", srv.get("directory_path")),
                       "username": L.get("account", (proto.get("authentication_scheme") or {}).get("username")),
                       "authScheme": (proto.get("authentication_scheme") or {}).get("scheme_name"),
                       "fingerprintPinned": bool(proto.get("ssh_fingerprint"))},
            "runs": {"overall": hist.get("overall_backup_status") if isinstance(hist, dict) else None,
                     "clusterBackupsReported": len(cl),
                     "inventoryBackupsReported": len(inv),
                     "mostRecentClusterBackupUtc":
                         dt.datetime.fromtimestamp(cl[0]["start_time"] / 1000, dt.timezone.utc)
                         .strftime("%Y-%m-%dT%H:%M:%SZ") if cl and cl[0].get("start_time") else None,
                     "historyDepth": "only the most recent is reported"},
            "coverage": None,
            "restoreEvidence": {"status": st_r,
                                "state": ((restore or {}).get("status") or {}).get("value"),
                                "description": ((restore or {}).get("status") or {}).get("description")}}


def main():
    out_dir = os.environ.get("OUT_DIR", ".")
    L = Labels()
    print("recovery.py: what protects the management plane, and whether it actually ran\n")
    planes = [read_sddc(L), read_vcenter(L), read_nsx(L)]

    for p in planes:
        if not p.get("reached"):
            print(f"  {p['plane']:<26} NOT READ ({p['why']})")
            continue
        s = p["schedule"]
        print(f"  {p['plane']:<26} {s['field']} says {str(s['says'])!r}, {s['daysListed']} day(s) listed, "
              f"at {s['atHour']:02d}:{s.get('atMinute') or 0:02d}")
        cov = p.get("coverage")
        if cov:
            print(f"  {'':<26} {p['runs']['total']} run(s); {cov['daysCovered']} of {cov['windowDays']} days "
                  f"covered, {cov['daysUncovered']} NOT, in {cov['gaps']} gap(s); "
                  f"longest {cov['longestGapDays']} days ({cov['longestGap'][0]} .. {cov['longestGap'][1]})")
        else:
            print(f"  {'':<26} {p['runs']}")
        if p.get("parts"):
            print(f"  {'':<26} copy contains {p['parts']['selected']}; "
                  f"deselected defaults: {p['parts']['deselectedDefaults'] or 'none'}")

    reached = [p for p in planes if p.get("reached")]
    targets = {json.dumps([(p.get("target") or {}).get(k) for k in ("server", "directory", "username")])
               for p in reached}
    print(f"\n  TARGETS: {len(reached)} plane(s) read, {len(targets)} distinct target description(s)")
    if len(targets) == 1 and len(reached) > 1:
        print("     every plane read writes to the same place, so the recovery plan has one target and "
              "as many dependants as there are planes")

    print("\n  HAS A RESTORE EVER RUN HERE?")
    for p in reached:
        ev = p.get("restoreEvidence")
        if ev:
            print(f"     {p['plane']:<26} HTTP {ev.get('status')}  "
                  f"{ev.get('state') or ''} {str(ev.get('description') or ev.get('message') or '')[:90]}")
        else:
            print(f"     {p['plane']:<26} no task of that type among {p.get('tasksRead')} read")

    # A run that reached fewer planes than a previous one must not overwrite the richer record. This is
    # the sibling of G-166: there the loss came from an optional probe, here from partial credentials,
    # and neither is a reason to publish less than was known. The record says how many planes it read,
    # so the comparison is one integer.
    _prior_path = os.path.join(out_dir, "recovery.json")
    _prior = {}
    if os.path.exists(_prior_path):
        try:
            _prior = json.load(open(_prior_path, encoding="utf-8")) or {}
        except ValueError:
            _prior = {}

    payload = {"captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "planes": planes,
               "distinctTargets": len(targets),
               "planesRead": len(reached)}

    if _prior and _prior.get("planesRead", 0) > payload["planesRead"]:
        raise SystemExit(
            f"REFUSING to write: this run reached {payload['planesRead']} plane(s) and the record on disk "
            f"was written from {_prior['planesRead']}. Supply the missing credentials, or move the old "
            f"record aside deliberately. A thinner read is not a newer truth.")

    text = L.scrub(json.dumps(payload, indent=1, ensure_ascii=False))
    for key in SECRET_KEYS:
        assert f'"{key}"' not in text, f"a {key} field reached the record"
    for var in ("SDDC_HOST", "VC_HOST", "NSX_HOST"):
        v = os.environ.get(var)
        assert not v or v not in text, f"{var} reached the record"
    assert not IPV4.search(text), "an address reached the record"
    bare = re.sub(r"\{\{[^}]*\}\}", "", text)
    for fam, m in L.maps.items():
        for nm in m:
            if nm and re.search(r"(?<![A-Za-z0-9-])" + re.escape(nm) + r"(?![A-Za-z0-9-])", bare):
                shp = re.sub(r"[A-Za-z]", "a", re.sub(r"[0-9]", "9", nm))
                raise SystemExit(f"FATAL: a {fam} value ({len(nm)} characters, shape {shp}) reached the record")
    os.makedirs(out_dir, exist_ok=True)
    open(os.path.join(out_dir, "recovery.json"), "w", encoding="utf-8").write(text + "\n")
    print(f"\nwrote recovery.json ({len(reached)} of {len(planes)} plane(s) read); "
          f"every address, path and account name replaced by a placeholder")


if __name__ == "__main__":
    main()
