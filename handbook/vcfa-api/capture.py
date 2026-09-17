#!/usr/bin/env python3
"""capture.py - the VCF Automation API's two token flows, recorded on your own estate.

Performs the chapter's calls read-only and records each request and response as it went over the wire, with
every value that belongs to your estate replaced by a placeholder ({{host}}, {{org}}, {{user}}, {{domain}},
{{bearer}}, {{refresh-token}}, {{id}}), so the record can be published and the chapter's plates can re-render
it with anyone's values. Stdlib only. No token value is printed or written; a token appears in the record only
as a placeholder with its length.

  A1  POST /oauth/tenant/{{org}}/token          flow A: the stored refresh token traded for a bearer
  A2  GET  /cloudapi/1.0.0/sessions/current     who the bearer is, as the platform sees it
  A3  GET  /cloudapi/1.0.0/sessions/current/rights  the count of effective rights (one page, the total declared)
  A4  GET  /iaas/api/about                      the deployment plane answering the same bearer
  A5  GET  /cci/kubernetes/api                  the control plane answering the same bearer
  B1  POST /cloudapi/1.0.0/sessions             flow B: the Basic session login; the bearer in a response header
  B2  GET  /cloudapi/1.0.0/sessions/current/rights  the count under the session bearer
  R   the rights present under B and absent under A, by name: the arrival rule's delta
  P1  POST /oauth/provider/token                the provider path, only when VCFA_PROVIDER_REFRESH_TOKEN_FILE is set

Env:  VCFA_HOST, VCFA_ORG, VCFA_REFRESH_TOKEN_FILE (flow A); VCFA_USER (user@org), VCFA_PASSWORD (flow B);
      VCFA_PROVIDER_REFRESH_TOKEN_FILE (optional); TLS_VERIFY=false on a self-signed lab CA; OUT (default calls.json)
Exit: 0 recorded · 1 a call failed
"""

import base64
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ACCEPT = "application/json;version=9.1.0"
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
KEEP_HEADERS = ("content-type", "x-vmware-vcloud-access-token", "x-vmware-vcloud-request-id", "link", "cache-control", "x-frame-options", "strict-transport-security")
RECORD = []


def ctx():
    verify = os.environ.get("TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")
    return ssl.create_default_context() if verify else ssl._create_unverified_context()


class Sanitizer:
    def __init__(self, host, org, user, domain, secrets):
        self.host, self.org, self.user, self.domain = host, org, user, domain
        self.secrets = [s for s in secrets if s]
        self.ids = {}

    def text(self, s):
        for sec in self.secrets:
            s = s.replace(sec, "{{secret}}")
        s = s.replace(self.host, "{{host}}")
        if self.domain:
            s = s.replace(self.domain, "{{domain}}")
        s = re.sub(r"\b" + re.escape(self.user) + r"\b", "{{user}}", s)
        s = re.sub(r"\b" + re.escape(self.org) + r"\b", "{{org}}", s)
        s = UUID.sub(lambda m: self.ids.setdefault(m.group(0), "{{id-%d}}" % (len(self.ids) + 1)), s)
        return s

    def value(self, v, key=""):
        k = key.lower()
        if isinstance(v, str):
            if k == "authorization":
                scheme = v.split(" ", 1)[0]
                return f"{scheme} {{{{bearer}}}}" if scheme == "Bearer" else f"{scheme} {{{{base64 of user@org:password}}}}"
            if k in ("access_token", "refresh_token", "id_token") or (k == "x-vmware-vcloud-access-token"):
                return "{{%s · %d chars}}" % ({"access_token": "bearer", "refresh_token": "refresh-token", "id_token": "id-token"}.get(k, "bearer"), len(v))
            return self.text(v)
        if isinstance(v, dict):
            return {kk: self.value(vv, kk) for kk, vv in v.items()}
        if isinstance(v, list):
            out = [self.value(x, key) for x in v[:8]]
            if len(v) > 8:
                out.append("... %d more" % (len(v) - 8))
            return out
        return v


def call(san, cid, title, method, path, headers, body=None, form=None, note=""):
    url = f"https://{san.host}{path}"
    data = urllib.parse.urlencode(form).encode() if form is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, context=ctx(), timeout=60) as r:
            status, raw, hdrs = r.status, r.read(), r.getheaders()
    except urllib.error.HTTPError as e:
        status, raw, hdrs = e.code, e.read(), list(e.headers.items())
    ms = int((time.monotonic() - t0) * 1000)
    try:
        parsed = json.loads(raw) if raw else None
    except ValueError:
        parsed = raw.decode(errors="replace")[:400]
    shown_headers = {k: san.value(v, k) for k, v in headers.items()}
    if form is not None:
        shown_body = "&".join(f"{k}={'{{refresh-token}}' if k == 'refresh_token' else san.text(str(v))}" for k, v in form.items())
    else:
        shown_body = san.value(body) if body is not None else None
    resp_headers = {k: san.value(v, k) for k, v in hdrs if k.lower() in KEEP_HEADERS}
    RECORD.append({"id": cid, "title": title, "request": {"method": method, "path": san.text(path), "headers": shown_headers, "body": shown_body},
                   "response": {"status": status, "elapsed_ms": ms, "headers": resp_headers, "body": san.value(parsed)}, "note": note})
    print(f"  {cid:<3} {method:<4} {san.text(path):<48} {status}  {ms:>5} ms")
    return status, parsed, dict((k.lower(), v) for k, v in hdrs)


def jwt_claims(token):
    """The token's own claims, decoded without verification: only the lifetime and the issuer shape are recorded."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        pad = lambda p: p + "=" * (-len(p) % 4)
        claims = json.loads(base64.urlsafe_b64decode(pad(parts[1])))
        iat, exp = claims.get("iat"), claims.get("exp")
        return {"lifetime_s": (int(exp) - int(iat)) if iat and exp else None, "has_exp": exp is not None, "claims_present": sorted(claims)[:16]}
    except Exception:  # noqa: BLE001
        return None


def rights_all(san, host, bearer):
    names, page = [], 1
    while True:
        req = urllib.request.Request(f"https://{host}/cloudapi/1.0.0/sessions/current/rights?page={page}&pageSize=128", headers={"Authorization": f"Bearer {bearer}", "Accept": ACCEPT})
        with urllib.request.urlopen(req, context=ctx(), timeout=60) as r:
            d = json.loads(r.read())
        names += [v.get("name") for v in d.get("values", [])]
        if page >= int(d.get("pageCount", 1)):
            return names, d.get("resultTotal")
        page += 1


def main():
    host, org = os.environ["VCFA_HOST"], os.environ["VCFA_ORG"]
    user_at_org = os.environ.get("VCFA_USER", ""); user = user_at_org.split("@")[0] if user_at_org else "{{user}}"
    domain = os.environ.get("VCFA_DOMAIN", "")
    refresh = open(os.environ["VCFA_REFRESH_TOKEN_FILE"], encoding="utf-8").read().strip()
    password = os.environ.get("VCFA_PASSWORD", "")
    san = Sanitizer(host, org, user, domain, [refresh, password])
    failed = 0
    print("capture.py: the two flows, recorded read-only; values parameterized on the way into the record\n")
    # ---- flow A
    st, body, _ = call(san, "A1", "Flow A: the stored refresh token traded for a bearer", "POST", f"/oauth/tenant/{org}/token",
                       {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}, form={"grant_type": "refresh_token", "refresh_token": refresh},
                       note="the bearer lives expires_in seconds; a refresh token comes back beside it: store the value that comes back")
    if st != 200:
        print("FATAL: the tenant grant failed"); sys.exit(1)
    bearer_a = body["access_token"]; san.secrets.append(bearer_a)
    if body.get("refresh_token") and body["refresh_token"] != refresh:
        san.secrets.append(body["refresh_token"]); print("   (a different refresh token came back; store it: the old value is dead)")
    else:
        print("   (the refresh token that came back is the value that was sent)")
    RECORD[-1]["bearer_claims"] = jwt_claims(bearer_a)
    if RECORD[-1]["bearer_claims"]:
        print(f"   the answer says expires_in {body.get('expires_in')} s; the bearer's own exp claim says {RECORD[-1]['bearer_claims']['lifetime_s']} s")
    ah = {"Authorization": "Bearer " + bearer_a, "Accept": ACCEPT}
    call(san, "A2", "Who the bearer is, as the platform sees it", "GET", "/cloudapi/1.0.0/sessions/current", ah, note="the session behind the bearer: the user, the organization, the roles")
    st, rb, _ = call(san, "A3", "The count of effective rights under the OAuth bearer", "GET", "/cloudapi/1.0.0/sessions/current/rights?pageSize=1", ah, note="one page of one, and resultTotal declares the count; the page size is capped at 128 on this collection")
    total_a = (rb or {}).get("resultTotal")
    call(san, "A4", "The deployment plane, same bearer", "GET", "/iaas/api/about", {"Authorization": "Bearer " + bearer_a, "Accept": "application/json"}, note="the IaaS surface VM Apps organizations lean on")
    call(san, "A5", "The control plane, same bearer", "GET", "/cci/kubernetes/api", {"Authorization": "Bearer " + bearer_a, "Accept": "application/json"}, note="the Cloud Consumption Interface, a Kubernetes-style API; All Apps organizations live here")
    # ---- flow B
    total_b, bearer_b = None, None
    if user_at_org and password:
        cred = base64.b64encode(f"{user_at_org}:{password}".encode()).decode(); san.secrets.append(cred)
        st, sb, hdrs = call(san, "B1", "Flow B: the Basic session login; the bearer is a response header", "POST", "/cloudapi/1.0.0/sessions",
                            {"Authorization": "Basic " + cred, "Accept": ACCEPT}, note="the bearer is not in the body: read X-VMWARE-VCLOUD-ACCESS-TOKEN, case-insensitively")
        bearer_b = hdrs.get("x-vmware-vcloud-access-token")
        if bearer_b:
            san.secrets.append(bearer_b)
            RECORD[-1]["bearer_claims"] = jwt_claims(bearer_b)
            if RECORD[-1]["bearer_claims"]:
                print(f"   the session bearer's own exp claim says {RECORD[-1]['bearer_claims']['lifetime_s']} s")
            bh = {"Authorization": "Bearer " + bearer_b, "Accept": ACCEPT}
            st, rb, _ = call(san, "B2", "The count of effective rights under the session bearer", "GET", "/cloudapi/1.0.0/sessions/current/rights?pageSize=1", bh, note="the same user, the same organization, the same role")
            total_b = (rb or {}).get("resultTotal")
        else:
            failed += 1; print("   no access-token header on the session answer")
    else:
        print("  B   skipped: VCFA_USER and VCFA_PASSWORD not set")
    # ---- the delta
    if bearer_b:
        a_names, _ = rights_all(san, host, bearer_a); b_names, _ = rights_all(san, host, bearer_b)
        delta = sorted(set(b_names) - set(a_names)); back = sorted(set(a_names) - set(b_names))
        RECORD.append({"id": "R", "title": "The arrival rule's delta, by name", "request": None, "response": None,
                       "delta": {"oauth_rights": total_a, "session_rights": total_b, "present_under_session_only": delta, "present_under_oauth_only": back},
                       "note": "the rights the session login carries and the OAuth grant is stripped of; no role edit adds them to the OAuth path"})
        print(f"\n  R   rights: OAuth {total_a}, session {total_b}; under the session only: {delta}; under OAuth only: {back}")
    # ---- provider path (optional)
    if os.environ.get("VCFA_PROVIDER_REFRESH_TOKEN_FILE"):
        prov = open(os.environ["VCFA_PROVIDER_REFRESH_TOKEN_FILE"], encoding="utf-8").read().strip(); san.secrets.append(prov)
        st, pb, _ = call(san, "P1", "The provider path: the same grant at the provider endpoint", "POST", "/oauth/provider/token",
                         {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}, form={"grant_type": "refresh_token", "refresh_token": prov})
        if st == 200:
            san.secrets.append(pb["access_token"])
            call(san, "P2", "The count of effective rights under the provider bearer", "GET", "/cloudapi/1.0.0/sessions/current/rights?pageSize=1", {"Authorization": "Bearer " + pb["access_token"], "Accept": ACCEPT})
    else:
        print("  P   skipped: VCFA_PROVIDER_REFRESH_TOKEN_FILE not set (a provider api-token minted in the console)")
    out = os.environ.get("OUT", "calls.json")
    text = json.dumps({"captured": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "calls": RECORD}, indent=2, ensure_ascii=False)
    for sec in san.secrets:
        assert sec not in text, "a secret reached the record"
    assert host not in text and org not in text
    with open(out, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(f"\nrecorded {len(RECORD)} exchanges to {out}; every host, organization, user, token, and id replaced by a placeholder")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
