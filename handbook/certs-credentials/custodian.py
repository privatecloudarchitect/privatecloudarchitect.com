#!/usr/bin/env python3
"""custodian.py: the credential inventory and the certificate horizon, as counts and dates and nothing else.

Two single reads answer most of what anyone needs to know about an instance's secrets:

  1. the CREDENTIAL INVENTORY: how many credentials the custodian holds, by resource type, credential type and
     account type, and how many carry an automatic rotation policy. Rotation is opt-in per credential and the
     split is the number worth producing;
  2. the DISCLOSURE CHECK: whether the list response actually contains secret material. On the build this was
     written against it does, for some account types and not others, which is a thing to know before anyone
     pipes that call into a file, counted by account type AND by resource type;
  3. the CERTIFICATE HORIZON: every platform certificate per domain with the days remaining that the platform
     itself computes, the issuing chain, whether it renews itself, and how many expire inside a year.

SAFETY. This script is deliberately written so that a secret cannot reach its output. Every credential object
passes through ``strip_secrets`` the moment it arrives, which deletes the secret-bearing keys and replaces
each with a boolean saying whether something was there. Nothing downstream, including the printed summary and
the JSON record, can see a value because no value survives the read. If you extend this script, extend
``SECRET_KEYS`` first.

Read-only throughout. Nothing here rotates, renews or replaces anything.

Run:
  export SDDC_HOST=<sddc-manager-fqdn>
  export SDDC_TOKEN_FILE=/path/to/bearer      # mode 0600
  export TLS_VERIFY=false                     # only on a self-signed lab CA
  python3 custodian.py
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

# Anything that could carry secret material. A key listed here is destroyed on arrival and replaced by a
# boolean. Add to this list before adding any new read.
SECRET_KEYS = ("password", "privateKey", "secret", "token", "passphrase", "pemEncoded", "publicKey")


def strip_secrets(obj):
    """Destroy secret-bearing values on arrival, keeping only whether something was present.

    This runs before anything else touches the object. The point is that no later code, however careless,
    can print or serialise a secret, because by then the value does not exist in the process.
    """
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
    RESERVED = {"MANAGEMENT", "VI", "ACTIVE", "DISABLED", "SYSTEM", "SERVICE", "USER", "SSH", "API", "SSO",
                "AUDIT", "FTP", "ESXI", "VCENTER", "PSC", "BACKUP", "NSXT_EDGE", "NSXT_MANAGER", "NSX_ALB",
                "CA", "none", "all"}

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


def main():
    host = os.environ["SDDC_HOST"]
    token = open(os.environ["SDDC_TOKEN_FILE"], encoding="utf-8").read().strip()
    out_dir = os.environ.get("OUT_DIR", ".")
    L = Labels()

    def get(path):
        rq = urllib.request.Request(f"https://{host}{path}",
                                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(rq, context=ctx(), timeout=90) as r:
                # stripped on arrival, before anything else can see it
                return r.status, strip_secrets(json.loads(r.read() or b"null"))
        except urllib.error.HTTPError as e:
            return e.code, {}
        except (urllib.error.URLError, OSError):
            return None, {}

    print("custodian.py: the credential inventory and the certificate horizon, metadata only\n")

    # ---- 1 and 2: the inventory, and whether the read discloses anything
    st, cr = get("/v1/credentials")
    creds = (cr.get("elements") or []) if isinstance(cr, dict) else []
    by_resource = collections.Counter((c.get("resource") or {}).get("resourceType") for c in creds)
    by_cred = collections.Counter(c.get("credentialType") for c in creds)
    by_account = collections.Counter(c.get("accountType") for c in creds)
    auto = [c for c in creds if (c.get("autoRotatePolicy") or {})]
    discloses = [c for c in creds if c.get("password_present")]
    disclosed_by_account = collections.Counter(c.get("accountType") for c in discloses)
    withheld_by_account = collections.Counter(c.get("accountType") for c in creds if not c.get("password_present"))
    # Which RESOURCES disclose matters as much as which account types do. The custodian holds the credential
    # for the backup target, and the backup carries the custodian's own vault, so whether that one entry is in
    # the disclosed set closes a circle the chapter draws.
    disclosed_by_resource = collections.Counter((c.get("resource") or {}).get("resourceType") for c in discloses)
    print(f"  credentials: {len(creds)}")
    print(f"     by resource type:   {dict(by_resource)}")
    print(f"     by credential type: {dict(by_cred)}")
    print(f"     by account type:    {dict(by_account)}")
    print(f"     carrying an automatic rotation policy: {len(auto)} of {len(creds)}")
    print(f"\n  DISCLOSURE: {len(discloses)} of {len(creds)} entries returned secret material in the LIST response")
    if discloses:
        print(f"     disclosed for account types: {dict(disclosed_by_account)}")
        print(f"     withheld  for account types: {dict(withheld_by_account)}")
        print(f"     disclosed by resource type:  {dict(disclosed_by_resource)}")
        print(f"     This script destroyed those values on arrival and kept only the count. Anything else that")
        print(f"     reads this endpoint does not, so treat its output as secret material and never write it")
        print(f"     to a file, a log, a ticket or a terminal recording.")
    else:
        print("     the list response carried no secret material on this build")

    # ---- 3: the certificate horizon
    st, dom = get("/v1/domains")
    domains = (dom.get("elements") or []) if isinstance(dom, dict) else []
    horizon, per_domain = [], []
    for d in domains:
        L.get("domain", d.get("name"))
        st2, rc = get(f"/v1/domains/{d.get('id')}/resource-certificates")
        els = (rc.get("elements") or []) if isinstance(rc, dict) else []
        issuers = collections.Counter()
        days = []
        for c in els:
            raw = str(c.get("issuedBy") or "")
            m = re.search(r"CN=([^,]+)", raw)
            cn = (m.group(1) or "").strip() if m else raw.strip()
            issuers["the instance's own CA" if cn == "CA" else "another chain"] += 1
            n = c.get("numberOfDaysToExpire")
            if isinstance(n, int):
                days.append(n)
                horizon.append({"domain": L.scrub(str(d.get("name"))), "days": n,
                                "status": c.get("expirationStatus"), "autoRenew": c.get("autoRenew"),
                                "ownCA": cn == "CA"})
        days.sort()
        per_domain.append({"domain": L.scrub(str(d.get("name"))), "type": d.get("type"),
                           "certificates": len(els), "issuers": dict(issuers),
                           "nearestDays": days[0] if days else None, "furthestDays": days[-1] if days else None,
                           "within365": sum(1 for x in days if x <= 365)})
        print(f"\n  {str(d.get('type')):<11} {len(els):>2} certificate(s); issuers {dict(issuers)}")
        print(f"              days to expiry {days[0] if days else '?'} to {days[-1] if days else '?'}, "
              f"{sum(1 for x in days if x <= 365)} inside a year")
    all_days = sorted(h["days"] for h in horizon)
    statuses = collections.Counter(str(h["status"]) for h in horizon)
    renew = collections.Counter(str(h["autoRenew"]) for h in horizon)
    print(f"\n  across the estate: {len(horizon)} certificate(s); status {dict(statuses)}; "
          f"auto renew {dict(renew)}")
    print(f"     nearest expiry {all_days[0] if all_days else '?'} days; "
          f"{sum(1 for x in all_days if x <= 365)} inside a year; "
          f"{sum(1 for x in all_days if x <= 90)} inside 90 days")

    payload = {"captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "credentials": {"total": len(creds), "byResourceType": dict(by_resource),
                               "byCredentialType": dict(by_cred), "byAccountType": dict(by_account),
                               "autoRotating": len(auto),
                               "autoRotatingByResource": dict(collections.Counter(
                                   (c.get("resource") or {}).get("resourceType") for c in auto))},
               "disclosure": {"entriesReturningSecretMaterial": len(discloses),
                              "disclosedByAccountType": dict(disclosed_by_account),
                              "withheldByAccountType": dict(withheld_by_account),
                              "disclosedByResourceType": dict(disclosed_by_resource)},
               "certificates": {"total": len(horizon), "perDomain": per_domain,
                                "statuses": dict(statuses), "autoRenew": dict(renew),
                                "nearestDays": all_days[0] if all_days else None,
                                "furthestDays": all_days[-1] if all_days else None,
                                "within365": sum(1 for x in all_days if x <= 365),
                                "within90": sum(1 for x in all_days if x <= 90),
                                "daysSorted": all_days}}
    text = L.scrub(UUID.sub("{{id}}", json.dumps(payload, indent=1, ensure_ascii=False)))
    for key in SECRET_KEYS:
        assert f'"{key}"' not in text, f"a {key} field reached the record"
    assert token not in text and host not in text, "an estate value reached the record"
    bare = re.sub(r"\{\{[^}]*\}\}", "", text)
    for fam, m in L.maps.items():
        for nm in m:
            if nm and re.search(r"(?<![A-Za-z0-9-])" + re.escape(nm) + r"(?![A-Za-z0-9-])", bare):
                shp = re.sub(r"[A-Za-z]", "a", re.sub(r"[0-9]", "9", nm))
                raise SystemExit(f"FATAL: a {fam} name ({len(nm)} characters, shape {shp}) reached the record")
    os.makedirs(out_dir, exist_ok=True)
    open(os.path.join(out_dir, "custodian.json"), "w", encoding="utf-8").write(text + "\n")
    print(f"\nwrote custodian.json ({len(creds)} credentials, {len(horizon)} certificates); "
          f"counts and dates only, and no secret survived the read")


if __name__ == "__main__":
    main()
