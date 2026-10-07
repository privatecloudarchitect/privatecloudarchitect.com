#!/usr/bin/env python3
"""hardening.py - the hardening loop as one runnable read-schedule.

Runs the seven posture reads the hardening chapter assembles and writes a dated
posture folder: the evidence an audit actually consumes, produced on demand.
Every read is read-only, and every stored record is a distillation; secret
fields are stripped before anything touches disk.

The loop spans three token planes, and each is optional: set the environment
for the planes you have, and the reads you cannot run are recorded as skips
with their reason, which is itself part of the posture record.

  SDDC Manager plane (certificates, credentials, backup):
    SDDC_HOST, SDDC_USERNAME, SDDC_PASSWORD
  Operations plane (alert scope):
    OPS_HOST, OPS_API_TOKEN  (OPS_BROKER_HOST, OPS_REALM as in opslib.py)
    The token's role must be allowed to export a policy: a fleet API client
    holding only a viewer role lists the policies and is refused the export
    (HTTP 403), and the read is then recorded as a skip.
  Consumption plane (firewall floor, access, audit trail):
    VCFA_HOST, VCFA_ORG, VCFA_USER, VCFA_PASSWORD
    VCFA_USER is the bare account name; the login principal is
    <VCFA_USER>@<VCFA_ORG>, so a user@domain name here is refused.

  AUDIT_MIN_DAYS (optional): how far back the audit trail must answer. When set,
  a trail whose oldest readable event is younger than this is a finding.

  Set OPS_TLS_VERIFY=false to skip TLS verification on every plane (self-signed lab CA).

Usage:  python3 hardening.py [--out DIR] [--record FILE]
        --record FILE also writes the run as counts, dates and product words only,
        with every host, object and principal name left out; it refuses to write
        a record in which a name it read survived (the record the chapter renders).
Exit:   0 every read made, none found anything · 1 every read made, findings present
        2 a read was skipped: the folder is incomplete, and its report names why
"""

import datetime
import io
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from opslib import bearer as ops_bearer, ops

EXPIRY_HORIZON_DAYS = 90
# The consumption surface serves its API in two numbering schemes and marks the older one (40.x) deprecated;
# name a current version of the 9.x line.
CLOUDAPI_ACCEPT = "application/json;version=9.1.0"

# Each read, the token plane that owns it, and the control family it answers. report.md prints this table, so
# the mapping is written once, beside the schedule, and every dated folder carries it.
CONTROL_FAMILIES = {
    "certificates": ("lifecycle", "PKI and certificate lifecycle"),
    "credentials": ("lifecycle", "credential management and rotation"),
    "backup": ("lifecycle", "platform backup and recovery readiness"),
    "alert-scope": ("operations", "monitoring scope governance"),
    "firewall-floor": ("tenancy", "network policy baseline"),
    "access": ("tenancy", "access review"),
    "audit-trail": ("tenancy", "audit logging and retention"),
}

# Every name a read meets (hosts, domains, policies, sections, projects, principals). --record refuses to write
# a record that still carries one.
SEEN = set()


def _ctx():
    # TLS verification is on by default; set OPS_TLS_VERIFY=false (or 0/no/off) for a self-signed CA.
    verify = os.environ.get("OPS_TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")
    return ssl.create_default_context() if verify else ssl._create_unverified_context()


def http(method, url, body=None, headers=None, form=False, timeout=60):
    h = dict(headers or {})
    data = None
    if body is not None:
        data = (urllib.parse.urlencode(body).encode() if form else json.dumps(body).encode())
        h["Content-Type"] = ("application/x-www-form-urlencoded" if form else "application/json")
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    with urllib.request.urlopen(req, context=_ctx(), timeout=timeout) as r:
        return r.status, r.read(), dict(r.headers)


# ── plane sessions ───────────────────────────────────────────────────────────

def sddc_token():
    host = os.environ["SDDC_HOST"]
    st, raw, _ = http("POST", f"https://{host}/v1/tokens",
                      body={"username": os.environ["SDDC_USERNAME"],
                            "password": os.environ["SDDC_PASSWORD"]},
                      headers={"Accept": "application/json"})
    return json.loads(raw)["accessToken"]


def sddc(path, tok):
    host = os.environ["SDDC_HOST"]
    st, raw, _ = http("GET", f"https://{host}{path}",
                      headers={"Authorization": f"Bearer {tok}",
                               "Accept": "application/json"})
    return json.loads(raw)


def vcfa_session():
    host, org = os.environ["VCFA_HOST"], os.environ["VCFA_ORG"]
    user, pw = os.environ["VCFA_USER"], os.environ["VCFA_PASSWORD"]
    import base64
    basic = base64.b64encode(f"{user}@{org}:{pw}".encode()).decode()
    st, raw, hdrs = http("POST", f"https://{host}/cloudapi/1.0.0/sessions",
                         headers={"Authorization": f"Basic {basic}",
                                  "Accept": CLOUDAPI_ACCEPT})
    tok = hdrs.get("X-VMWARE-VCLOUD-ACCESS-TOKEN") or hdrs.get("x-vmware-vcloud-access-token")
    if not tok:
        raise RuntimeError("session login returned no access-token header")
    return tok


def vcfa(path, tok, accept="application/json"):
    host = os.environ["VCFA_HOST"]
    st, raw, _ = http("GET", f"https://{host}{path}",
                      headers={"Authorization": f"Bearer {tok}", "Accept": accept})
    return json.loads(raw)


def _keys(obj):
    """Every key name in a response, at any depth: a structural read, never a text match over the values."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _keys(v)


# ── the seven reads (each returns (record, findings)) ───────────────────────

def read_certificates(tok):
    domains = sddc("/v1/domains", tok).get("elements", [])
    now = datetime.datetime.now(datetime.timezone.utc)
    horizon = now + datetime.timedelta(days=EXPIRY_HORIZON_DAYS)
    per_domain, findings = [], []
    for d in domains:
        SEEN.add(d.get("name") or "")
        certs = sddc(f"/v1/domains/{d['id']}/resource-certificates", tok).get("elements", [])
        issuers, expiring, expired, nearest = set(), 0, 0, None
        for c in certs:
            issuers.add(c.get("issuedBy") or c.get("issuer") or "?")
            status = (c.get("expirationStatus") or "").upper()
            if status and status != "ACTIVE":
                expired += 1
            raw_date = c.get("notAfter")
            if raw_date:
                try:
                    dt = datetime.datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                    days = (dt - now).days
                    nearest = days if nearest is None else min(nearest, days)
                    if dt < horizon:
                        expiring += 1
                except ValueError:
                    pass
        SEEN.update(issuers)
        per_domain.append({"domain": d.get("name"), "certificates": len(certs),
                           "issuers": sorted(issuers), "expiringWithinHorizon": expiring,
                           "notActive": expired, "nearestExpiryDays": nearest})
        if expired:
            findings.append(f"certificates: {expired} not ACTIVE in domain {d.get('name')}")
        if expiring:
            findings.append(f"certificates: {expiring} expire within {EXPIRY_HORIZON_DAYS}d "
                            f"in domain {d.get('name')}")
    return {"horizonDays": EXPIRY_HORIZON_DAYS, "domains": per_domain}, findings


def read_credentials(tok):
    els = sddc("/v1/credentials?pageSize=500", tok).get("elements", [])
    by_type, auto = {}, 0
    for e in els:
        # distillation only: the raw response carries secret material; none of it
        # is read into the record. Counts and rotation posture are the evidence.
        rtype = (e.get("resource") or {}).get("resourceType") or e.get("credentialType") or "?"
        by_type[rtype] = by_type.get(rtype, 0) + 1
        if e.get("autoRotatePolicy"):
            auto += 1
    findings = []
    if els and auto < len(els):
        findings.append(f"credentials: rotation is opt-in and only {auto} of {len(els)} "
                        "carry an auto-rotate policy; make the split deliberate")
    return {"total": len(els), "byResourceType": by_type, "autoRotate": auto}, findings


def read_backup(tok):
    b = sddc("/v1/system/backup-configuration", tok)
    # The configuration carries an encryption key only when a passphrase is set, so the read is a key
    # name anywhere in the structure. Values are never matched: a path such as /encrypted-backups is not
    # an encryption setting.
    encryption_set = any("encrypt" in k.lower() for k in _keys(b))
    schedules = [{"resourceType": s.get("resourceType"), "frequency": s.get("frequency"),
                  "retention": s.get("retentionPolicy")}
                 for s in b.get("backupSchedules", [])]
    locations = [{"server": loc.get("server"), "protocol": loc.get("protocol"),
                  "port": loc.get("port"), "directoryPath": loc.get("directoryPath")}
                 for loc in b.get("backupLocations", [])]
    for loc in locations:
        SEEN.update(str(loc.get(k) or "") for k in ("server", "directoryPath"))
    findings = []
    if not b.get("isConfigured"):
        findings.append("backup: not configured at all")
    if b.get("isConfigured") and not encryption_set:
        findings.append("backup: encryption passphrase UNSET; backups carry the credential "
                        "vault and leave the platform unencrypted")
    return {"isConfigured": b.get("isConfigured"), "encryption": "SET" if encryption_set else "UNSET",
            "schedules": schedules, "locations": locations}, findings


def read_alert_scope():
    tok = ops_bearer()
    st, body = ops("GET", "/api/policies", tok, params={"pageSize": 500, "_no_links": "true"})
    if st != 200:
        raise RuntimeError(f"policies list -> HTTP {st}")
    default = next((p for p in body.get("policySummaries", []) if p.get("defaultPolicy")), None)
    if default is None:
        raise RuntimeError("no policy carries the defaultPolicy flag")
    SEEN.add(default.get("name") or "")
    host = os.environ["OPS_HOST"]
    try:
        st, raw, _ = http("GET", f"https://{host}/suite-api/api/policies/export?id={default['id']}",
                          headers={"Authorization": f"Bearer {tok}", "Accept": "*/*"})
    except urllib.error.HTTPError as e:
        # the platform's own words, so a skip names the missing right rather than a status code
        try:
            said = json.loads(e.read()).get("message", "")
        except Exception:
            said = ""
        raise RuntimeError(f"policy export -> HTTP {e.code}" + (f": {said}" if said else "")) from None
    xml = zipfile.ZipFile(io.BytesIO(raw)).read("exportedPolicies.xml").decode()
    alerts = re.findall(r'<Alert\s[^>]*enabled="(true|false)"', xml)
    enabled = alerts.count("true")
    findings = []
    if enabled:
        findings.append(f"alert scope: {enabled} of {len(alerts)} alert definitions are ENABLED "
                        "in the default policy; each is a page on every object no other policy claims")
    return {"defaultPolicy": default.get("name"), "alertDefinitions": len(alerts),
            "enabledInDefault": enabled}, findings


def read_firewall_floor(tok):
    fw = vcfa("/cci/kubernetes/apis/vpc.nsx.vmware.com/v1alpha1/firewallpolicies", tok)
    sections = []
    findings = []
    for item in fw.get("items", []):
        name = item["metadata"]["name"]
        SEEN.add(name)
        # the LIST view trims rules[]; the single get carries the grammar
        full = vcfa(f"/cci/kubernetes/apis/vpc.nsx.vmware.com/v1alpha1/firewallpolicies/{name}", tok)
        rules = full.get("spec", {}).get("rules", []) or []
        enabled = [r for r in rules if not r.get("disabled")]
        sections.append({"section": name, "isDefault": full.get("spec", {}).get("isDefault"),
                         "rules": len(rules), "enabled": len(enabled)})
        if full.get("spec", {}).get("isDefault") and enabled:
            findings.append(f"firewall floor: default section {name} has {len(enabled)} "
                            "ENABLED rule(s); the floor of every posture above it")
    att = vcfa("/cci/kubernetes/apis/vpc.nsx.vmware.com/v1alpha1/securityprofileattachments", tok)
    attachments = [{"attachment": a["metadata"]["name"],
                    "vpc": a.get("spec", {}).get("vpcName"),
                    "profile": a.get("spec", {}).get("securityProfileName")}
                   for a in att.get("items", [])]
    for a in attachments:
        SEEN.update(str(v or "") for v in a.values())
    return {"sections": sections, "profileAttachments": attachments}, findings


def read_access(tok):
    pr = vcfa("/cci/kubernetes/apis/project.cci.vmware.com/v1alpha2/projects", tok)
    per_project = []
    for p in pr.get("items", []):
        name = p["metadata"]["name"]
        SEEN.add(name)
        rb = vcfa(f"/cci/kubernetes/apis/authorization.cci.vmware.com/v1alpha1/"
                  f"namespaces/{name}/projectrolebindings", tok)
        bindings = []
        # A project role binding has the Kubernetes RoleBinding shape: roleRef and subjects sit at the top
        # level, beside metadata, and the object carries no spec.
        for b in rb.get("items", []):
            subjects = [{"kind": s.get("kind"), "name": s.get("name")} for s in (b.get("subjects") or [])]
            SEEN.add(b["metadata"]["name"])
            SEEN.update(s["name"] or "" for s in subjects)
            bindings.append({"binding": b["metadata"]["name"],
                             "role": (b.get("roleRef") or {}).get("name"),
                             "subjects": subjects})
        per_project.append({"project": name, "bindings": bindings})
    return {"projects": per_project}, []


def read_audit_trail(tok):
    def page(order):
        return vcfa(f"/cloudapi/1.0.0/auditTrail?pageSize=1&{order}=timestamp", tok, accept=CLOUDAPI_ACCEPT)
    first, last = page("sortAsc"), page("sortDesc")
    oldest = ((first.get("values") or [{}])[0]).get("timestamp")
    newest = ((last.get("values") or [{}])[0]).get("timestamp")
    record = {"events": first.get("resultTotal"), "oldest": oldest, "newest": newest, "windowDays": None,
              "minDays": None, "olderOnRequest": None}
    if oldest:
        # Asked explicitly for anything before the oldest event: zero means the window is the trail's own, not a
        # default view of a longer one.
        flt = urllib.parse.quote(f"timestamp=lt={oldest}", safe="")
        older = vcfa(f"/cloudapi/1.0.0/auditTrail?pageSize=1&filter={flt}", tok, accept=CLOUDAPI_ACCEPT)
        record["olderOnRequest"] = older.get("resultTotal")
    findings = []
    if oldest:
        t0 = datetime.datetime.fromisoformat(oldest.replace("Z", "+00:00"))
        record["windowDays"] = (datetime.datetime.now(datetime.timezone.utc) - t0).days
    want = os.environ.get("AUDIT_MIN_DAYS", "").strip()
    if want:
        record["minDays"] = int(want)
        if record["windowDays"] is None or record["windowDays"] < int(want):
            findings.append(f"audit trail: the oldest event this session can read is {record['windowDays']} "
                            f"day(s) old, short of the {int(want)} decided; an incident older than that "
                            "cannot be answered from this trail")
    return record, findings


def read_builds(stok):
    """The product build each plane answered with, so a posture folder says what it was read against.

    Never a finding and never a skip: a plane that cannot say is recorded as unknown."""
    builds = {}
    if stok:
        try:
            builds["SDDC Manager"] = (sddc("/v1/sddc-managers", stok).get("elements") or [{}])[0].get("version")
        except Exception:
            builds["SDDC Manager"] = None
    if os.environ.get("OPS_HOST") and os.environ.get("OPS_API_TOKEN"):
        try:
            st, v = ops("GET", "/api/versions/current", ops_bearer())
            name = v.get("releaseName") if st == 200 and isinstance(v, dict) else None
            builds["VCF Operations"] = re.sub(r"^\D+", "", name) if name else None
        except Exception:
            builds["VCF Operations"] = None
    if os.environ.get("VCFA_HOST"):
        try:
            # unauthenticated: the API versions the consumption surface serves. The list mixes two numbering
            # schemes, and the older one is marked deprecated, so the line is the highest version that is
            # neither deprecated nor a pre-release (which carries a suffix).
            st, raw, _ = http("GET", f"https://{os.environ['VCFA_HOST']}/api/versions",
                              headers={"Accept": "application/*+xml"})
            served = [v for dep, v in re.findall(r'<VersionInfo[^>]*deprecated="(true|false)"[^>]*>.*?'
                                                 r"<Version>([^<]+)</Version>", raw.decode(), re.S)
                      if dep == "false" and re.fullmatch(r"\d+(?:\.\d+)+", v)]
            builds["VCF Automation API"] = max(served, key=lambda v: tuple(int(x) for x in v.split("."))) if served else None
        except Exception:
            builds["VCF Automation API"] = None
    return builds


# ── the record the chapter renders ───────────────────────────────────────────

# Words the platform itself publishes. They identify no estate, so the leak check never treats one as a name,
# even when a principal or object happens to carry it (a user called admin beside the project role admin).
RESERVED = {"admin", "edit", "edit_adv", "view", "Default Policy", "default", "User", "Group"}


def distil(records, findings, skips, planes, transcript, stamp, builds):
    """The run as counts, dates and product words: no host, object or principal name."""
    rd = {}
    for name, (plane, family) in CONTROL_FAMILIES.items():
        base = {"plane": plane, "controlFamily": family,
                "status": "read" if name in records else "skip",
                "findings": sum(1 for f in findings if f.split(":", 1)[0].replace(" ", "-") == name)}
        r = records.get(name)
        if r is None:
            rd[name] = base
            continue
        if name == "certificates":
            base.update(domains=len(r["domains"]), certificates=sum(d["certificates"] for d in r["domains"]),
                        issuers=len({i for d in r["domains"] for i in d["issuers"]}),
                        expiringWithinHorizon=sum(d["expiringWithinHorizon"] for d in r["domains"]),
                        notActive=sum(d["notActive"] for d in r["domains"]), horizonDays=r["horizonDays"],
                        nearestExpiryDays=min((d["nearestExpiryDays"] for d in r["domains"]
                                               if d["nearestExpiryDays"] is not None), default=None))
        elif name == "credentials":
            base.update(total=r["total"], autoRotate=r["autoRotate"], byResourceType=r["byResourceType"])
        elif name == "backup":
            base.update(isConfigured=r["isConfigured"], encryption=r["encryption"], locations=len(r["locations"]),
                        schedules=[{"resourceType": s["resourceType"], "frequency": s["frequency"]}
                                   for s in r["schedules"]])
        elif name == "alert-scope":
            base.update(alertDefinitions=r["alertDefinitions"], enabledInDefault=r["enabledInDefault"])
        elif name == "firewall-floor":
            dflt = [s for s in r["sections"] if s["isDefault"]]
            base.update(sections=len(r["sections"]), defaultSections=len(dflt),
                        defaultRules=sum(s["rules"] for s in dflt), defaultEnabled=sum(s["enabled"] for s in dflt),
                        profileAttachments=len(r["profileAttachments"]))
        elif name == "access":
            roles, kinds, n = {}, {}, 0
            for p in r["projects"]:
                for b in p["bindings"]:
                    n += 1
                    roles[b["role"] or "?"] = roles.get(b["role"] or "?", 0) + 1
                    for s in b["subjects"]:
                        kinds[s["kind"] or "?"] = kinds.get(s["kind"] or "?", 0) + 1
            base.update(projects=len(r["projects"]), bindings=n, byRole=roles, bySubjectKind=kinds)
        elif name == "audit-trail":
            base.update(events=r["events"], oldest=r["oldest"], newest=r["newest"],
                        windowDays=r["windowDays"], minDays=r["minDays"], olderOnRequest=r["olderOnRequest"])
        rd[name] = base
    return {"captured": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "date": stamp, "tool": "hardening.py", "builds": builds, "planes": planes, "reads": rd,
            "findings": findings, "skips": [{"read": n, "reason": r} for n, r in skips],
            "transcript": transcript, "exit": exit_code(findings, skips)}


def write_record(path, rec):
    for k in ("SDDC_HOST", "SDDC_USERNAME", "OPS_HOST", "OPS_BROKER_HOST", "VCFA_HOST", "VCFA_ORG", "VCFA_USER"):
        SEEN.add(os.environ.get(k, ""))
    text = json.dumps(rec, indent=1, sort_keys=True)
    names = {n for n in SEEN if n and len(n) > 3 and n not in RESERVED}
    # One boundary rule: a name counts only where it stands as a whole token, so a short name inside a longer
    # product word is not a leak, and a host inside a sentence still is.
    leaked = sorted(n for n in names if re.search(r"(?<![\w.-])" + re.escape(n) + r"(?![\w-])", text))
    if leaked:
        raise SystemExit(f"--record: {len(leaked)} name(s) read from the estate reached the record; nothing was written")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text + "\n")


# ── the schedule ─────────────────────────────────────────────────────────────

def exit_code(findings, skips):
    """2 when a read was skipped, whatever else happened: a folder missing a read is incomplete evidence, and a
    scheduler that watched only for findings would file it as clean. 1 when every read was made and some found
    something, 0 when every read was made and none did."""
    return 2 if skips else (1 if findings else 0)


def main():
    out_base = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else "."
    record_path = sys.argv[sys.argv.index("--record") + 1] if "--record" in sys.argv else None
    stamp = datetime.date.today().isoformat()
    outdir = os.path.join(out_base, f"posture-{stamp}")
    os.makedirs(outdir, exist_ok=True)
    transcript = []

    def say(line="", shown=None):
        print(line)
        transcript.append(line if shown is None else shown)

    planes = {
        "sddc": all(os.environ.get(k) for k in ("SDDC_HOST", "SDDC_USERNAME", "SDDC_PASSWORD")),
        "ops": all(os.environ.get(k) for k in ("OPS_HOST", "OPS_API_TOKEN")),
        "vcfa": all(os.environ.get(k) for k in ("VCFA_HOST", "VCFA_ORG", "VCFA_USER", "VCFA_PASSWORD")),
    }
    records, all_findings, skips = {}, [], []

    def run(name, plane, fn, *args):
        if not planes[plane]:
            skips.append((name, f"{plane} environment not set"))
            say(f"  SKIP {name:16} ({plane} environment not set)")
            return
        try:
            record, findings = fn(*args)
            records[name] = record
            all_findings.extend(findings)
            say(f"  read {name:16} " + (f"{len(findings)} finding(s)" if findings else "clean"))
        except Exception as e:
            skips.append((name, f"{type(e).__name__}: {e}"))
            say(f"  SKIP {name:16} ({type(e).__name__}: {str(e)[:120]})")

    say(f"HARDENING LOOP - {stamp}")
    say()
    stok = sddc_token() if planes["sddc"] else None
    run("certificates", "sddc", read_certificates, stok)
    run("credentials", "sddc", read_credentials, stok)
    run("backup", "sddc", read_backup, stok)
    run("alert-scope", "ops", read_alert_scope)
    vtok = vcfa_session() if planes["vcfa"] else None
    run("firewall-floor", "vcfa", read_firewall_floor, vtok)
    run("access", "vcfa", read_access, vtok)
    run("audit-trail", "vcfa", read_audit_trail, vtok)
    builds = read_builds(stok)
    read_against = ", ".join(f"{k} {v or 'unknown'}" for k, v in builds.items()) or "no plane set"
    say(f"  read against        {read_against}")

    with open(os.path.join(outdir, "reads.json"), "w") as f:
        json.dump(records, f, indent=2, sort_keys=True)

    lines = [f"# Posture - {stamp}", "",
             "Produced by the hardening loop: distilled reads only, no secret material.", "",
             f"Read against: {read_against}.", "",
             "## Findings", ""]
    lines += [f"- {f}" for f in all_findings] or ["- none"]
    if skips:
        lines += ["", "## Skipped reads", ""]
        lines += [f"- {n}: {r}" for n, r in skips]
    lines += ["", "## Control families covered", "",
              "| read | owner (token plane) | control family |", "|---|---|---|"]
    lines += [f"| {n} | {p} | {fam} |" for n, (p, fam) in CONTROL_FAMILIES.items()] + [""]
    with open(os.path.join(outdir, "report.md"), "w") as f:
        f.write("\n".join(lines))

    say()
    summary = f"({len(records)} reads, {len(all_findings)} finding(s), {len(skips)} skip(s))"
    say(f"posture folder: {outdir}  {summary}", shown=f"posture folder: ./posture-{stamp}  {summary}")
    for fnd in all_findings:
        say(f"  ! {fnd}")
    if record_path:
        write_record(record_path, distil(records, all_findings, skips,
                                         {k: ("set" if v else "not set") for k, v in planes.items()},
                                         transcript, stamp, builds))
        print(f"\nwrote {record_path}: counts, dates and product words only, no host, object or principal name")
    return exit_code(all_findings, skips)


if __name__ == "__main__":
    sys.exit(main())
