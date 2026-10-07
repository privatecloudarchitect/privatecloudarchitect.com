#!/usr/bin/env python3
"""origins.py: list every namespace on your Supervisors with the plane that created it.

A namespace's origin decides what its workloads can still be given. One VCF Automation created carries tenancy
(project roles, the organization's VPC, quota); one created on the Supervisor never will, because a Supervisor
attached to an NSX Manager refuses to import it. No single field on the namespace names its origin, so this joins
three reads:

  vCenter      every namespace on each Supervisor (GET /api/vcenter/namespaces/instances/v2, then each one's
               detail): the organization, project and region it was made for (system_metadata, which only VCF
               Automation writes) and the VPC it sits in, with whether that VPC was created for it;
  Supervisor   the namespace each installed Supervisor Service runs in (its service_namespace);
  Automation   the namespaces VCF Automation holds a record for (GET /cloudapi/v1/namespaceSummaries), each with
               its Supervisor, organization and project.

and gives each namespace one origin:

  automation   Automation holds its record: created through VCF Automation, under tenancy. A check confirms that
               vCenter's system_metadata names the same organization and project
  service      a Supervisor Service runs in it: the platform's own
  supervisor   neither: created on the Supervisor itself, through vCenter or its API
  orphan       vCenter names an organization and project, but Automation holds no record of it
  record-only  Automation holds a record whose namespace is not on the Supervisor

With --record FILE it also checks the origin record you keep, a CSV with the columns namespace, provisional
(yes or no) and decider: every namespace created on the Supervisor has a row, and every provisional one names who
may decide that it has become permanent.

Read-only throughout: nothing is created, changed or deleted, and no token value is printed.

Exit code: 0 when every namespace has an origin and every check holds, 1 when a check fails (an orphan, a
record-only namespace, metadata that disagrees with Automation's record, a Supervisor-created namespace with no
row, a provisional row with no decider), 2 when a read failed.

Run:
  export VCENTER_HOSTS=<vcenter-fqdn>[,<vcenter-fqdn>...]      # the vCenter in front of each Supervisor
  export VCENTER_USER=<user>   VCENTER_PASSWORD_FILE=/path/to/password      # mode 0600
  #   or, instead of user and password, an existing session: VCENTER_SESSION_FILE=/path/to/session-id
  export VCFA_HOST=<automation-fqdn>   VCFA_PROVIDER_TOKEN_FILE=/path/to/bearer   # a provider administrator
  export TLS_VERIFY=false                                       # only on a self-signed lab CA
  python3 origins.py                              # one line per namespace, with its origin and evidence
  python3 origins.py --record origin-record.csv   # also check the record you keep
  python3 origins.py --json                       # the whole join as JSON
  python3 origins.py --scrub                      # every estate name replaced, for a transcript you share
"""
import argparse
import base64
import csv
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
ORIGINS = ("automation", "service", "supervisor", "orphan", "record-only")


class ReadFailed(Exception):
    pass


def ctx():
    verify = os.environ.get("TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")
    return ssl.create_default_context() if verify else ssl._create_unverified_context()


def secret(var):
    return open(os.environ[var], encoding="utf-8").read().strip()


class Client:
    def __init__(self, base, headers):
        self.base, self.headers = base, headers

    def call(self, method, path, headers=None):
        rq = urllib.request.Request(self.base + path, method=method, headers={**self.headers, **(headers or {})})
        try:
            with urllib.request.urlopen(rq, context=ctx(), timeout=90) as r:
                raw = r.read()
                return r.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            return e.code, None
        except urllib.error.URLError as e:
            raise ReadFailed(f"{self.base} unreachable ({e.reason})")

    def get(self, path, what):
        st, body = self.call("GET", path)
        if st != 200:
            raise ReadFailed(f"{what} refused ({st})")
        return body

    def pages(self, path, what):
        """Every value of a paged Automation list."""
        out, page = [], 1
        while True:
            body = self.get(f"{path}?page={page}&pageSize=100", what)
            out += body.get("values") or []
            if page >= (body.get("pageCount") or 1):
                return out
            page += 1


def vcenter_session(host):
    base = f"https://{host}"
    if os.environ.get("VCENTER_SESSION_FILE"):
        return Client(base, {"vmware-api-session-id": secret("VCENTER_SESSION_FILE"), "Accept": "application/json"}), False
    basic = base64.b64encode(f"{os.environ['VCENTER_USER']}:{secret('VCENTER_PASSWORD_FILE')}".encode()).decode()
    st, sid = Client(base, {"Authorization": f"Basic {basic}"}).call("POST", "/api/session")
    if st not in (200, 201) or not isinstance(sid, str):
        raise ReadFailed(f"vCenter {host} refused the session ({st})")
    return Client(base, {"vmware-api-session-id": sid, "Accept": "application/json"}), True


def tail(urn):
    """The UUID inside an Automation URN, or the value itself."""
    m = UUID.search(urn or "")
    return m.group(0) if m else urn


def read_vcenter(host):
    """Every namespace on every Supervisor this vCenter fronts, with the services' namespaces."""
    c, mine = vcenter_session(host)
    try:
        sups = c.get("/api/vcenter/namespace-management/supervisors/summaries", f"{host} Supervisor list")["items"]
        names = {s["supervisor"]: s["info"]["name"] for s in sups}
        services = {}
        for sid in names:
            body = c.get(f"/api/vcenter/namespace-management/supervisors/{sid}/supervisor-services",
                         f"{host} Supervisor Services")
            for s in body.get("supervisor_services", body) if isinstance(body, dict) else body:
                d = c.get(f"/api/vcenter/namespace-management/supervisors/{sid}/supervisor-services/{s['supervisor_service']}",
                          f"{host} Supervisor Service {s['supervisor_service']}")
                if d.get("service_namespace"):
                    services[(sid, d["service_namespace"])] = s["supervisor_service"]
        rows = []
        for n in c.get("/api/vcenter/namespaces/instances/v2", f"{host} namespace list"):
            d = c.get(f"/api/vcenter/namespaces/instances/v2/{n['namespace']}", f"{host} namespace detail")
            vpc = ((d.get("network_spec") or {}).get("vpc_network") or {})
            path = vpc.get("vpc") or ""
            m = re.match(r"^/orgs/[^/]+/projects/([^/]+)/vpcs/([^/]+)$", path)
            rows.append({"vcenter": host, "supervisorId": n["supervisor"], "supervisor": names.get(n["supervisor"]),
                         "namespace": n["namespace"], "configStatus": n.get("config_status"),
                         "metadata": d.get("system_metadata") or None,
                         "service": services.get((n["supervisor"], n["namespace"])),
                         "vpcProject": m.group(1) if m else None, "vpc": m.group(2) if m else None,
                         "vpcCreatedForIt": vpc.get("auto_created"),
                         "accessList": sorted(f"{a.get('role')}:{a.get('subject_type')}:{a.get('subject')}@{a.get('domain') or ''}"
                                              for a in d.get("access_list") or [])})
        return rows, names
    finally:
        if mine:
            c.call("DELETE", "/api/session")


def read_automation(host):
    c = Client(f"https://{host}/cloudapi", {"Authorization": f"Bearer {secret('VCFA_PROVIDER_TOKEN_FILE')}",
                                            "Accept": "application/json;version=9.0.0"})
    out = []
    for s in c.pages("/v1/namespaceSummaries", "Automation namespace records (a provider administrator's bearer is required)"):
        ref = s.get("vcReference") or {}
        out.append({"namespace": s.get("name"), "supervisorId": ref.get("supervisorUuid"), "status": s.get("status"),
                    "organization": (s.get("organization") or {}).get("name"),
                    "organizationId": tail((s.get("organization") or {}).get("id")),
                    "project": (s.get("projectAssignment") or {}).get("name"),
                    "projectId": tail((s.get("projectAssignment") or {}).get("id"))})
    return out


def read_record(path):
    rows = {}
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            name = (r.get("namespace") or "").strip()
            if name and not name.startswith("#"):
                rows[name] = {"provisional": (r.get("provisional") or "").strip().lower(),
                              "decider": (r.get("decider") or "").strip()}
    return rows


def classify(vc_rows, supervisors, records, kept):
    by_key = {(r["supervisorId"], r["namespace"]): r for r in records}
    out, checks = [], []
    for n in vc_rows:
        rec = by_key.pop((n["supervisorId"], n["namespace"]), None)
        md = n["metadata"] or {}
        if rec:
            origin = "automation"
            agrees = md.get("organization_id") == rec["organizationId"] and md.get("project_id") == rec["projectId"]
            if not agrees:
                checks.append(("FAIL", f"{n['namespace']}: Automation's record names {rec['organization']}/{rec['project']}, "
                                       f"vCenter's metadata {'is absent' if not md else 'names another organization or project'}"))
        elif n["service"]:
            origin = "service"
        elif md.get("organization_id"):
            origin = "orphan"
            checks.append(("FAIL", f"{n['namespace']}: vCenter names an organization and project, Automation holds no record"))
        else:
            origin = "supervisor"
        row = {**n, "origin": origin,
               "organization": rec["organization"] if rec else None, "project": rec["project"] if rec else None,
               "vpcInOrganizationProject": bool(rec) and n["vpcProject"] == rec["organizationId"]}
        if origin == "supervisor" and kept is not None:
            k = kept.get(n["namespace"])
            row["kept"] = k
            if k is None:
                checks.append(("FAIL", f"{n['namespace']}: created on the Supervisor, and your origin record has no row for it"))
            elif k["provisional"] not in ("yes", "no"):
                checks.append(("FAIL", f"{n['namespace']}: the record does not say whether it is provisional (yes or no)"))
            elif k["provisional"] == "yes" and not k["decider"]:
                checks.append(("FAIL", f"{n['namespace']}: provisional, and the record names nobody who may make it permanent"))
        out.append(row)
    for (sid, name), rec in by_key.items():
        if sid in supervisors:
            out.append({"vcenter": None, "supervisorId": sid, "supervisor": supervisors[sid], "namespace": name,
                        "origin": "record-only", "organization": rec["organization"], "project": rec["project"],
                        "service": None, "metadata": None, "vpcProject": None, "vpc": None, "vpcCreatedForIt": None,
                        "accessList": [], "configStatus": rec["status"]})
            checks.append(("FAIL", f"{name}: Automation holds a record ({rec['status']}) and the Supervisor has no such namespace"))
    unread = sorted({r["supervisorId"] for r in by_key.values() if r["supervisorId"] not in supervisors})
    return out, checks, unread


class Scrub:
    """Stable placeholders for estate names. Origins, service identifiers and the product's own words stay."""
    KEEP = set(ORIGINS) | {"default", "RUNNING", "READY", "CONFIGURING", "REMOVING", "ERROR", "NOT_READY", "yes", "no"}

    def __init__(self):
        self.maps = {}

    def __call__(self, family, name):
        if name is None or name in self.KEEP:
            return name
        m = self.maps.setdefault(family, {})
        if name not in m:
            m[name] = f"{family}-{len(m) + 1}"
        return "{{%s}}" % m[name]

    def apply(self, rows):
        out = []
        for r in rows:
            r = dict(r)
            for key, fam in (("vcenter", "vcenter"), ("supervisor", "supervisor"), ("namespace", "namespace"),
                             ("organization", "organization"), ("project", "project"), ("vpc", "vpc")):
                r[key] = self(fam, r.get(key))
            if r.get("vpcProject") not in (None, "default"):
                r["vpcProject"] = "{{organization's NSX project}}"
            r["supervisorId"] = "{{id}}"
            r["metadata"] = {k: "{{id}}" for k in (r.get("metadata") or {})} or None
            r["accessList"] = [self.principal(a) for a in r.get("accessList") or []]
            if r.get("kept"):
                r["kept"] = {**r["kept"], "decider": self("decider", r["kept"]["decider"]) if r["kept"]["decider"] else ""}
            out.append(r)
        return out

    def principal(self, a):
        role, kind, rest = a.split(":", 2)
        subject, _, domain = rest.rpartition("@")
        if domain == "vsphere.local" and subject.startswith("vcf_reserved_"):
            return a
        if re.match(r"^(edit|view)-[0-9a-f]{20,}", subject):
            return f"{role}:{kind}:{subject.split('-')[0]}-{{{{project-role group}}}}@{{{{domain}}}}"
        return f"{role}:{kind}:{{{{principal}}}}@{{{{domain}}}}"

    def text(self, s):
        s = UUID.sub("{{id}}", s)
        pairs = [(real, label) for fam in self.maps.values() for real, label in fam.items()]
        for real, label in sorted(pairs, key=lambda kv: len(kv[0]), reverse=True):
            s = s.replace(real, "{{%s}}" % label)
        return s

    def leaked(self, s):
        return [real for fam in self.maps.values() for real in fam if real and real in s]


def evidence(r):
    if r["origin"] == "automation":
        vpc = "VPC in the organization's project" if r.get("vpcInOrganizationProject") else "VPC outside the organization's project"
        return f"Automation record, {r['organization']}/{r['project']}; {vpc}"
    if r["origin"] == "service":
        return f"Supervisor Service {r['service']}"
    if r["origin"] == "supervisor":
        made = "a VPC created for it" if r.get("vpcCreatedForIt") else "an existing VPC"
        where = "the Supervisor's default project" if r.get("vpcProject") == "default" else "a project"
        kept = r.get("kept")
        rec = "" if kept is None and "kept" not in r else (
            "; no row in your record" if kept is None else
            f"; provisional: {kept['provisional'] or '?'}{', decider ' + kept['decider'] if kept.get('decider') else ''}")
        return f"no Automation record, no metadata; {made} in {where}{rec}"
    if r["origin"] == "orphan":
        return "vCenter names an organization and project; Automation holds no record"
    return f"Automation record ({r['configStatus']}), no namespace on the Supervisor"


def main():
    ap = argparse.ArgumentParser(description="List every Supervisor namespace with the plane that created it.")
    ap.add_argument("--record", metavar="CSV", help="check the origin record you keep (namespace,provisional,decider)")
    ap.add_argument("--json", action="store_true", help="print the whole join as JSON")
    ap.add_argument("--scrub", action="store_true", help="replace every estate name with a stable placeholder")
    a = ap.parse_args()
    captured = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        vc_rows, supervisors = [], {}
        for host in [h.strip() for h in os.environ["VCENTER_HOSTS"].split(",") if h.strip()]:
            rows, names = read_vcenter(host)
            vc_rows += rows
            supervisors.update(names)
        records = read_automation(os.environ["VCFA_HOST"])
        kept = read_record(a.record) if a.record else None
    except KeyError as e:
        print(f"read failed: the environment variable {e} is not set", file=sys.stderr)
        return 2
    except (ReadFailed, OSError) as e:
        print(f"read failed: {e}", file=sys.stderr)
        return 2
    rows, checks, unread = classify(vc_rows, supervisors, records, kept)
    order = {o: i for i, o in enumerate(ORIGINS)}
    rows.sort(key=lambda r: (r["supervisor"] or "", order[r["origin"]], r["namespace"]))
    counts = {o: sum(1 for r in rows if r["origin"] == o) for o in ORIGINS}
    sc = Scrub() if a.scrub else None
    shown = sc.apply(rows) if sc else rows
    msgs = [(s, sc.text(m) if sc else m) for s, m in checks]
    if a.json:
        out = json.dumps({"captured": captured, "supervisors": len(supervisors), "origins": counts,
                          "automationRecordsOnUnreadSupervisors": len(unread), "checks": [
                              {"status": s, "detail": m} for s, m in msgs], "namespaces": shown}, indent=2)
    else:
        lines = [f"namespace origins, read {captured}: {len(rows)} namespace(s) on {len(supervisors)} Supervisor(s)", ""]
        w = max([len(r["namespace"] or "") for r in shown] + [9])
        for r in shown:
            lines.append(f"  {r['namespace']:<{w}}  {r['origin']:<11}  {evidence(r)}")
        lines += ["", "  " + ", ".join(f"{counts[o]} {o}" for o in ORIGINS)]
        if unread:
            lines.append(f"  {len(unread)} Supervisor(s) hold Automation records but were not read (add their vCenter)")
        lines.append("")
        for s, m in msgs:
            lines.append(f"  [{s}] {m}")
        lines.append(f"  {sum(1 for s, _ in msgs if s == 'FAIL')} check(s) failing")
        out = "\n".join(lines)
    if sc:
        out = sc.text(out)
        if sc.leaked(out):
            print("refusing to print: an estate name survived scrubbing", file=sys.stderr)
            return 2
    print(out)
    return 1 if any(s == "FAIL" for s, _ in checks) else 0


if __name__ == "__main__":
    sys.exit(main())
