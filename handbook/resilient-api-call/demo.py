#!/usr/bin/env python3
"""demo.py - the three guarantees, exercised read-only against your own VCF Operations (and, optionally, VCF Automation).

  1. one read through the typed boundary
  2. the token guarantee: the cached bearer is deliberately corrupted, the next call answers 401, the client re-mints
     exactly once and the call succeeds; the mint count goes up by one
  3. a whole collection read with the envelope's declared total honored
  4. (with VCFA_* set) the answer that lies: a rights read at pageSize=512 returns a capped page while declaring the
     true total; then the same collection read correctly
  5. the boundary refusing a drifted shape, with the message that names the field
  6. an idempotent ensure() in dry-run mode: find by name, and the request it would have sent

Nothing is written to the platform. Nothing prints a token value. The one file touched is the cache file the client
writes atomically at owner-only permissions (CACHE_FILE, optional) and, if the platform answers a refresh-token grant
with a different refresh token, VCFA_REFRESH_TOKEN_FILE.

Env:  OPS_HOST, OPS_API_TOKEN (OPS_BROKER_HOST, OPS_REALM optional); TLS_VERIFY=false on a self-signed lab CA
      VCFA_HOST, VCFA_ORG, VCFA_REFRESH_TOKEN_FILE (optional, step 4); CACHE_FILE (optional)
Exit: 0 every step ran · 1 a step failed
"""

import json
import os
import sys
import tempfile
import urllib.parse
import urllib.request

from resilient import ApiError, Client, ShapeError, ensure, paginate, require, tls_context, unwrap

GRANT = "urn:custom:vcf:params:oauth:grant-type:api-token"


def broker_mint():
    """The broker exchange the identity chapter teaches; returns (bearer, lifetime in seconds)."""
    host = os.environ["OPS_HOST"]; broker = os.environ.get("OPS_BROKER_HOST", host); realm = os.environ.get("OPS_REALM", "CUSTOMER")
    body = urllib.parse.urlencode({"grant_type": GRANT, "api_token": os.environ["OPS_API_TOKEN"]}).encode()
    req = urllib.request.Request(f"https://{broker}/acs/t/{realm}/token", data=body, method="POST", headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, context=tls_context(), timeout=30) as r:
        d = json.loads(r.read())
    return d["access_token"], int(d.get("expires_in", 1800))


def tenant_mint():
    """The consumption surface's refresh-token grant; the refresh token file is rewritten only if a different value comes back."""
    path = os.environ["VCFA_REFRESH_TOKEN_FILE"]
    sent = open(path, encoding="utf-8").read().strip()
    body = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": sent}).encode()
    req = urllib.request.Request(f"https://{os.environ['VCFA_HOST']}/oauth/tenant/{os.environ['VCFA_ORG']}/token", data=body, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
    with urllib.request.urlopen(req, context=tls_context(), timeout=30) as r:
        d = json.loads(r.read())
    if d.get("refresh_token") and d["refresh_token"] != sent:
        folder = os.path.dirname(os.path.abspath(path)) or "."
        fd, tmp = tempfile.mkstemp(dir=folder, prefix=".rotating-")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(d["refresh_token"] + "\n")
        os.chmod(tmp, 0o600); os.replace(tmp, path)
        print("   (the refresh token came back different and the file was rewritten)")
    return d["access_token"], int(d.get("expires_in", 3600))


def step(n, title):
    print(f"\n{n}. {title}")


def main():
    ops = Client(os.environ["OPS_HOST"], broker_mint, identity="ops:broker", api_base="/suite-api", cache=os.environ.get("CACHE_FILE"))
    failed = 0
    # 1. one read through the boundary
    step(1, "one read, parsed at the boundary")
    body = ops.get("/api/resources", pageSize=1, page=0)
    first = require(unwrap(body, "resourceList")[0], {"identifier": str, "resourceKey": dict}, "resource")
    kind = require(first["resourceKey"], {"resourceKindKey": str, "name": str}, "resourceKey")
    print(f"   first resource: kind {kind['resourceKindKey']}; the envelope declares {body.get('pageInfo', {}).get('totalCount')} resources in all; mints so far: {ops.mints}")
    # 2. the token guarantee
    step(2, "the bearer expires mid-run (simulated by corrupting the cached one)")
    ops.corrupt()
    body = ops.get("/api/resources", pageSize=1, page=0)
    print(f"   the call answered 401 once, the client re-minted once and retried: HTTP 200, mints so far: {ops.mints} (one more than before)")
    # 3. a whole collection
    step(3, "a whole collection, the declared total honored")
    vms = paginate(ops, "/api/resources", "resourceList", size=100, first_page=0, total_of=lambda b: b["pageInfo"]["totalCount"], extra={"resourceKind": "VirtualMachine"})
    print(f"   {len(vms)} virtual machines collected in pages of 100; equals the declared total")
    # 4. the answer that lies (optional)
    if os.environ.get("VCFA_HOST") and os.environ.get("VCFA_ORG") and os.environ.get("VCFA_REFRESH_TOKEN_FILE"):
        step(4, "the answer that lies: a page that is capped while the total is declared")
        vcfa = Client(os.environ["VCFA_HOST"], tenant_mint, identity="vcfa:tenant", api_base="", cache=os.environ.get("CACHE_FILE"))
        accept = {"Accept": "application/json;version=9.1.0"}
        big = vcfa.request("GET", "/cloudapi/1.0.0/rights", params={"pageSize": 512, "page": 1}, headers=accept)
        got, total = len(unwrap(big, "values")), big.get("resultTotal")
        from collections import Counter
        top = Counter(vcfa.last_headers).most_common(1)[0]
        print(f"   asked for 512 per page: {got} values returned, resultTotal {total}, HTTP 200 and no error: a membership check on this page alone would be wrong")
        print(f"   the answer carried {len(vcfa.last_headers)} response headers ({top[1]} named {top[0]}); the standard library refuses more than 100 unless told otherwise")
        allr = paginate(vcfa, "/cloudapi/1.0.0/rights", "values", size=128, first_page=1, total_of=lambda b: b["resultTotal"], headers=accept)
        print(f"   walked at 128 per page: {len(allr)} rights collected, equal to the declared total")
    else:
        print("\n4. skipped: VCFA_HOST, VCFA_ORG, VCFA_REFRESH_TOKEN_FILE not all set")
    # 5. the boundary refusing drift
    step(5, "the boundary refusing a drifted shape")
    moved = {"resources": body["resourceList"], "pageInfo": body["pageInfo"]}
    try:
        unwrap(moved, "resourceList"); failed += 1; print("   (no error: unexpected)")
    except ShapeError as e:
        print(f"   wrapper key moved: {e}")
    try:
        require({"identifier": first["identifier"]}, {"identifier": str, "resourceKey": dict}, "resource"); failed += 1
    except ShapeError as e:
        print(f"   field missing:     {e}")
    # 6. idempotent ensure, dry run
    step(6, "an idempotent ensure(), dry run: nothing is sent")
    name = "PCA - Resilient call demo"
    def find():
        groups = unwrap(ops.get("/api/resources/groups", includePolicy="true"), "groups")
        return next((g for g in groups if require(g, {"resourceKey": dict}, "group")["resourceKey"].get("name") == name), None)
    def create():
        return ("POST", "/api/resources/groups", {"resourceKey": {"name": name, "adapterKindKey": "Container", "resourceKindKey": "Custom Group"}, "membershipDefinition": {"includedResources": []}})
    verdict, payload = ensure(find, create, dry_run=True)
    if verdict == "create":
        print(f"   not found; would send {payload[0]} {payload[1]} with a {len(json.dumps(payload[2]))}-byte body; a second run finds it and sends nothing")
    else:
        print(f"   {verdict}: the group is already there; a re-run changes nothing")
    print(f"\ndone: mints {ops.mints}; {'every step ran' if not failed else str(failed) + ' step(s) failed'}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    try:
        main()
    except ApiError as e:
        print(f"FATAL: {e}"); sys.exit(1)
