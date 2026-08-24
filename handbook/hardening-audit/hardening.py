#!/usr/bin/env python3
"""hardening.py - the hardening loop as one runnable read-schedule.

Runs the six posture reads the hardening sheet assembles and writes a dated
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
  Consumption plane (firewall floor, access, audit trail):
    VCFA_HOST, VCFA_ORG, VCFA_USER, VCFA_PASSWORD

  Set OPS_TLS_VERIFY=false to skip TLS verification on every plane (self-signed lab CA).

Usage:  python3 hardening.py [--out DIR]
Exit:   0 clean · 1 findings present · (skips never fail the run)
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
CLOUDAPI_ACCEPT = "application/json;version=40.0"


def _ctx():
    # TLS verification is on by default; set OPS_TLS_VERIFY=false (or 0/no/off) for a
    # self-signed CA. The legacy OPS_INSECURE=1 is still honored.
    tv = os.environ.get("OPS_TLS_VERIFY")
    if tv is not None:
        verify = tv.strip().lower() not in ("0", "false", "no", "off")
    else:
        verify = os.environ.get("OPS_INSECURE") != "1"
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


# ── the six reads (each returns (record, findings)) ─────────────────────────

def read_certificates(tok):
    domains = sddc("/v1/domains", tok).get("elements", [])
    now = datetime.datetime.now(datetime.timezone.utc)
    horizon = now + datetime.timedelta(days=EXPIRY_HORIZON_DAYS)
    per_domain, findings = [], []
    for d in domains:
        certs = sddc(f"/v1/domains/{d['id']}/resource-certificates", tok).get("elements", [])
        issuers, expiring, expired = set(), 0, 0
        for c in certs:
            issuers.add(c.get("issuedBy") or c.get("issuer") or "?")
            not_after = c.get("expirationStatus"), c.get("notAfter")
            status = (c.get("expirationStatus") or "").upper()
            if status and status != "ACTIVE":
                expired += 1
            raw_date = c.get("notAfter")
            if raw_date:
                try:
                    dt = datetime.datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                    if dt < horizon:
                        expiring += 1
                except ValueError:
                    pass
        per_domain.append({"domain": d.get("name"), "certificates": len(certs),
                           "issuers": sorted(issuers), "expiringWithinHorizon": expiring,
                           "notActive": expired})
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
    encryption_set = any("ncrypt" in k for k in json.dumps(b).split('"'))
    schedules = [{"resourceType": s.get("resourceType"), "frequency": s.get("frequency"),
                  "retention": s.get("retentionPolicy")}
                 for s in b.get("backupSchedules", [])]
    locations = [{"server": loc.get("server"), "protocol": loc.get("protocol"),
                  "port": loc.get("port"), "directoryPath": loc.get("directoryPath")}
                 for loc in b.get("backupLocations", [])]
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
    host = os.environ["OPS_HOST"]
    st, raw, _ = http("GET", f"https://{host}/suite-api/api/policies/export?id={default['id']}",
                      headers={"Authorization": f"Bearer {ops_bearer()}", "Accept": "*/*"})
    xml = zipfile.ZipFile(io.BytesIO(raw)).read("exportedPolicies.xml").decode()
    alerts = re.findall(r'<Alert\s[^>]*enabled="(true|false)"', xml)
    enabled = alerts.count("true")
    findings = []
    if enabled:
        findings.append(f"alert scope: {enabled} of {len(alerts)} alert definitions are ENABLED "
                        f"in the default policy ({default.get('name')}); each is a page on every "
                        "object no other policy claims")
    return {"defaultPolicy": default.get("name"), "alertDefinitions": len(alerts),
            "enabledInDefault": enabled}, findings


def read_firewall_floor(tok):
    fw = vcfa("/cci/kubernetes/apis/vpc.nsx.vmware.com/v1alpha1/firewallpolicies", tok)
    sections = []
    findings = []
    for item in fw.get("items", []):
        name = item["metadata"]["name"]
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
    return {"sections": sections, "profileAttachments": attachments}, findings


def read_access(tok):
    pr = vcfa("/cci/kubernetes/apis/project.cci.vmware.com/v1alpha2/projects", tok)
    per_project = []
    for p in pr.get("items", []):
        name = p["metadata"]["name"]
        rb = vcfa(f"/cci/kubernetes/apis/authorization.cci.vmware.com/v1alpha1/"
                  f"namespaces/{name}/projectrolebindings", tok)
        bindings = [{"subject": b["metadata"]["name"],
                     "role": (b.get("spec", {}) or {}).get("roleRef",
                             (b.get("spec", {}) or {}).get("role", "?"))}
                    for b in rb.get("items", [])]
        per_project.append({"project": name, "bindings": bindings})
    return {"projects": per_project}, []


def read_audit_trail(tok):
    d = vcfa("/cloudapi/1.0.0/auditTrail?pageSize=1", tok, accept=CLOUDAPI_ACCEPT)
    return {"events": d.get("resultTotal")}, []


# ── the schedule ─────────────────────────────────────────────────────────────

def main():
    out_base = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else "."
    stamp = datetime.date.today().isoformat()
    outdir = os.path.join(out_base, f"posture-{stamp}")
    os.makedirs(outdir, exist_ok=True)

    planes = {
        "sddc": all(os.environ.get(k) for k in ("SDDC_HOST", "SDDC_USERNAME", "SDDC_PASSWORD")),
        "ops": all(os.environ.get(k) for k in ("OPS_HOST", "OPS_API_TOKEN")),
        "vcfa": all(os.environ.get(k) for k in ("VCFA_HOST", "VCFA_ORG", "VCFA_USER", "VCFA_PASSWORD")),
    }
    records, all_findings, skips = {}, [], []

    def run(name, plane, fn, *args):
        if not planes[plane]:
            skips.append((name, f"{plane} environment not set"))
            print(f"  SKIP {name:16} ({plane} environment not set)")
            return
        try:
            record, findings = fn(*args)
            records[name] = record
            all_findings.extend(findings)
            print(f"  read {name:16} " + (f"{len(findings)} finding(s)" if findings else "clean"))
        except Exception as e:
            skips.append((name, f"{type(e).__name__}: {e}"))
            print(f"  SKIP {name:16} ({type(e).__name__}: {str(e)[:80]})")

    print(f"HARDENING LOOP - {stamp}\n")
    stok = sddc_token() if planes["sddc"] else None
    run("certificates", "sddc", read_certificates, stok)
    run("credentials", "sddc", read_credentials, stok)
    run("backup", "sddc", read_backup, stok)
    run("alert-scope", "ops", read_alert_scope)
    vtok = vcfa_session() if planes["vcfa"] else None
    run("firewall-floor", "vcfa", read_firewall_floor, vtok)
    run("access", "vcfa", read_access, vtok)
    run("audit-trail", "vcfa", read_audit_trail, vtok)

    with open(os.path.join(outdir, "reads.json"), "w") as f:
        json.dump(records, f, indent=2, sort_keys=True)

    lines = [f"# Posture - {stamp}", "",
             "Produced by the hardening loop: distilled reads only, no secret material.", "",
             "## Findings" if all_findings else "## Findings", ""]
    lines += [f"- {f}" for f in all_findings] or ["- none"]
    if skips:
        lines += ["", "## Skipped reads", ""]
        lines += [f"- {n}: {r}" for n, r in skips]
    lines += ["", "## Control families covered", "",
              "| read | control family |", "|---|---|",
              "| certificates | PKI and certificate lifecycle |",
              "| credentials | credential management and rotation |",
              "| backup | platform backup and recovery readiness |",
              "| alert-scope | monitoring scope governance |",
              "| firewall-floor | network policy baseline |",
              "| access | access review |",
              "| audit-trail | audit logging |", ""]
    with open(os.path.join(outdir, "report.md"), "w") as f:
        f.write("\n".join(lines))

    print(f"\nposture folder: {outdir}  ({len(records)} reads, "
          f"{len(all_findings)} finding(s), {len(skips)} skip(s))")
    for fnd in all_findings:
        print(f"  ! {fnd}")
    return 1 if all_findings else 0


if __name__ == "__main__":
    sys.exit(main())
