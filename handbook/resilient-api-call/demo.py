#!/usr/bin/env python3
"""demo.py - the three guarantees, exercised against your own VCF Operations (and, optionally, VCF Automation).

  1. one read through the typed boundary
  2. the token guarantee: the cached bearer is deliberately corrupted, the next call answers 401, the client re-mints
     exactly once and the call succeeds; the mint count goes up by one
  3. a whole collection read with the envelope's declared total honored
  4. (with VCFA_* set) the answer that lies: a rights read at pageSize=512 returns a capped page while declaring the
     true total; then the same collection read correctly
  5. the boundary refusing a drifted shape, with the message that names the field
  6. an idempotent ensure() in dry-run mode: find by name, and the request it would have sent
  7. the effect, read back: confirm() re-reads an object by its stable key; on one that exists it passes, and on the
     group step 6 did not send it refuses, which is what a write answered as a success that applied nothing looks like
  8. (with --write) the write itself: step 6's request sent once through ensure() and confirmed by a re-read, a
     second ensure() that finds it and sends nothing, an expectation the stored group does not meet refused, then
     the group deleted and confirm_gone() reading back that it is gone

Steps 1 to 7 write nothing to the platform. Step 8 runs only with --write: it refuses to start if a group by the
throwaway name already exists, creates exactly one, and deletes the one it created, even when a step in between
fails. Nothing prints a token value or an identifier. The one file touched is the cache file the client writes
atomically at owner-only permissions (CACHE_FILE, optional) and, if the platform answers a refresh-token grant with a
different refresh token, VCFA_REFRESH_TOKEN_FILE.

Env:  OPS_HOST, OPS_API_TOKEN (OPS_BROKER_HOST, OPS_REALM optional); TLS_VERIFY=false on a self-signed lab CA
      VCFA_HOST, VCFA_ORG, VCFA_REFRESH_TOKEN_FILE (optional, step 4); CACHE_FILE (optional)
Run:  python3 demo.py            steps 1 to 7, read-only
      python3 demo.py --write    adds step 8: one throwaway custom group, created, confirmed and deleted
Exit: 0 every step ran · 1 a step failed
"""

import json
import os
import sys
import tempfile
import urllib.parse
import urllib.request

from resilient import ApiError, Client, EffectError, ShapeError, confirm, confirm_gone, ensure, paginate, require, tls_context, unwrap

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
    name = "PCA - Example - resilient call throwaway (VMs)"   # D-038: <owner> - <bundle> - <scope> (<member kinds>)
    # a custom group's resourceKindKey is its group type (Environment is the one the spec's examples use), never the
    # words "Custom Group"; the kinds it gathers go in a membership rule. The platform refuses a group with neither a
    # rule nor a member, so this one carries a rule that matches no machine: it touches nothing it did not create
    sentinel = "pca-resilient-call-demo-matches-nothing"
    rule = {"resourceKindKey": {"resourceKind": "VirtualMachine", "adapterKind": "VMWARE"},
            "resourceNameConditionRules": [{"name": sentinel, "compareOperator": "EQ"}],
            "statConditionRules": [], "propertyConditionRules": [], "relationshipConditionRules": [], "resourceTagConditionRules": []}
    body = {"resourceKey": {"name": name, "adapterKindKey": "Container", "resourceKindKey": "Environment"},
            "autoResolveMembership": True,
            "membershipDefinition": {"includedResources": [], "excludedResources": [], "rules": [rule]}}
    seen = {"groups": 0}
    def find():
        groups = unwrap(ops.get("/api/resources/groups"), "groups")
        seen["groups"] = len(groups)
        return next((g for g in groups if require(g, {"resourceKey": dict}, "group")["resourceKey"].get("name") == name), None)
    def desired(g):
        key, members = g["resourceKey"], g.get("membershipDefinition") or {}
        rules = members.get("rules") or []
        names = [c.get("name") for r in rules for c in r.get("resourceNameConditionRules") or []]
        return (key.get("name") == name and key.get("adapterKindKey") == "Container" and key.get("resourceKindKey") == "Environment"
                and g.get("autoResolveMembership") is True and not members.get("includedResources") and names == [sentinel])
    def create():
        return ("POST", "/api/resources/groups", body)
    verdict, payload = ensure(find, create, dry_run=True)
    if verdict == "create":
        print(f"   not found; would send {payload[0]} {payload[1]} with a {len(json.dumps(payload[2]))}-byte body; a second run finds it and sends nothing")
    else:
        print(f"   {verdict}: the group is already there; a re-run changes nothing")
    # 7. the effect, read back
    step(7, "the effect, read back by the stable key")
    rid = first["identifier"]
    def reread():
        try:
            return ops.get(f"/api/resources/{rid}")
        except ApiError as e:
            if e.status == 404:
                return None
            raise
    confirm(reread, lambda r: require(r, {"identifier": str}, "resource")["identifier"] == rid, "the first resource")
    print("   an object that exists: a re-read by its identifier finds it, in the state expected")
    if verdict == "create":
        try:
            confirm(find, what="the demo group")
            failed += 1; print("   (no error: unexpected)")
        except EffectError as e:
            print(f"   the group step 6 did not send: {e}")
            print("   a write answered as a success that applied nothing reads exactly like this, and this is where it is caught")
    # 8. the write itself (opt-in)
    if "--write" in sys.argv[1:]:
        failed += write_proof(ops, name, find, desired, create, seen)
    else:
        print("\n8. skipped: the write proof runs only with --write (one throwaway group, created, confirmed and deleted)")
    print(f"\ndone: mints {ops.mints}; {'every step ran' if not failed else str(failed) + ' step(s) failed'}")
    sys.exit(1 if failed else 0)


def write_proof(ops, name, find, desired, create, seen):
    """Step 8: one throwaway group through ensure() and back out again; returns the number of checks that failed."""
    step(8, "the write itself: sent once, confirmed, run twice, and deleted")
    sent, made = [], {}
    def send(method, path, body):
        sent.append(method); ops.request(method, path, body=body)
    def by_id():
        try:
            return ops.get(f"/api/resources/groups/{made['id']}")
        except ApiError as e:
            if e.status == 404:
                return None
            raise
    if find() is not None:
        print(f"   a group named {name!r} is already there and this run did not create it: nothing was written")
        return 1
    before = seen["groups"]
    failed = 0
    try:
        verdict, group = ensure(find, lambda: (*create(), send), matches=desired, dry_run=False)
        made["id"] = group["id"]   # the identifier the re-read found, not the one the write answered with
        print(f"   {verdict}: one POST sent; a re-read by name found it in the state sent (Environment type, one rule that matches no machine, auto-resolve on); the list went from {before} groups to {seen['groups']}")
        confirm(by_id, desired, "the throwaway group")
        print("   a second re-read, by the identifier the first one found, agrees")
        again, _ = ensure(find, lambda: (*create(), send), matches=desired, dry_run=False)
        print(f"   a second ensure(): {again}; writes sent across both runs: {len(sent)}")
        if again != "unchanged" or len(sent) != 1:
            failed += 1; print("   (a second run sent a write: unexpected)")
        try:
            confirm(by_id, lambda g: g.get("autoResolveMembership") is False, "the throwaway group")
            failed += 1; print("   (no error: unexpected)")
        except EffectError as e:
            print(f"   an expectation the stored group does not meet (auto-resolve off): {e}")
    except EffectError as e:
        failed += 1; print(f"   refused: {e}")
    finally:
        if not made.get("id") and sent:
            made["id"] = (find() or {}).get("id")   # a write that was sent and not confirmed is still ours to remove
        if made.get("id"):
            ops.request("DELETE", f"/api/resources/groups/{made['id']}")
            try:
                confirm_gone(by_id, "the throwaway group")
                confirm_gone(find, "the throwaway group")
                print(f"   deleted; a re-read by its identifier answers 404, and the list, back to {seen['groups']} groups, has none by its name")
            except EffectError as e:
                failed += 1; print(f"   refused: {e}")
            if seen["groups"] != before:
                failed += 1; print(f"   (the list holds {seen['groups']} groups, not the {before} it held before the write: unexpected)")
    return failed


if __name__ == "__main__":
    try:
        main()
    except ApiError as e:
        print(f"FATAL: {e}"); sys.exit(1)
