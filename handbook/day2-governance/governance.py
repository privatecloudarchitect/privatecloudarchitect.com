#!/usr/bin/env python3
"""governance.py: the policy model of a VCF Automation 9.1 organization, read from the platform itself.

Read-only. It asks the policy plane to describe itself rather than describing it from documentation:

  1. the policy TYPES the build declares, and for each one the three schemas it publishes (what a policy of
     that type says, what it matches, and where it applies) plus the capability flags and per-scope limits
     the type carries;
  2. the ACTION SELECTORS a Day-2 action policy may name, kept as the tree they form, since a selector
     ending in a star is the parent of every selector under it;
  3. the POLICIES the organization holds right now, counted by type, scope and enforcement;
  4. the DECISION LOG: for each decision the plane recorded, which policies applied, the rank it gave each
     one, and the effective definition it computed from them. This is the composition rule stated by the
     thing that performs it, which is why this script exists.

Nothing here writes. Every organization-specific value (names of policies, groups, projects, deployments,
and every identifier) is replaced by a stable placeholder, and the script refuses to write a record in which
one survived. Action selectors, schema keys and enum values are the product's own vocabulary and are kept.

Run:
  export VCFA_HOST=<automation-fqdn> VCFA_ORG=<org>
  export VCFA_REFRESH_TOKEN_FILE=/path/to/refresh-token    # mode 0600
  export TLS_VERIFY=false                                  # only on a self-signed lab CA
  python3 governance.py
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

http.client._MAXHEADERS = 1000  # a large cloudapi page answers with more headers than the stdlib allows
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
ACTION_TYPE = "com.vmware.policy.deployment.action"


def ctx():
    verify = os.environ.get("TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")
    return ssl.create_default_context() if verify else ssl._create_unverified_context()


class Labels:
    """Stable placeholders: the first group met is {{group-1}}, the second policy is {{policy-2}}."""

    def __init__(self):
        self.maps = {}

    def get(self, family, name):
        m = self.maps.setdefault(family, {})
        if name not in m:
            m[name] = f"{family}-{len(m) + 1}"
        return "{{%s}}" % m[name]

    def scrub(self, text):
        """One pass, longest name first: a policy name can contain a group name."""
        if not isinstance(text, str):
            return text
        known = [(real, label) for m in self.maps.values() for real, label in m.items()]
        for real, label in sorted(known, key=lambda kv: -len(kv[0])):
            text = text.replace(real, "{{%s}}" % label)
        return UUID.sub("{{id}}", text)


class Policy:
    def __init__(self, host, org, refresh_token):
        self.host = host
        body = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": refresh_token}).encode()
        req = urllib.request.Request(
            f"https://{host}/oauth/tenant/{org}/token", data=body, method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
        with urllib.request.urlopen(req, context=ctx(), timeout=30) as r:
            self.bearer = json.loads(r.read())["access_token"]

    def get(self, path):
        req = urllib.request.Request(f"https://{self.host}{path}",
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

    def send(self, method, path, body):
        """Only ever used for the platform's own dry run, which creates nothing; see rehearse()."""
        req = urllib.request.Request(f"https://{self.host}{path}", data=json.dumps(body).encode(), method=method,
                                     headers={"Authorization": f"Bearer {self.bearer}", "Accept": "application/json",
                                              "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, context=ctx(), timeout=90) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if raw else None), dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode(errors="replace")[:200], dict(e.headers)
        except (urllib.error.URLError, OSError) as e:
            return None, str(e), {}

    def page(self, path, size=500):
        st, body = self.get(f"{path}{'&' if '?' in path else '?'}size={size}")
        if st == 200 and isinstance(body, dict):
            return st, body.get("content", [])
        return st, []


def action_tree(selectors):
    """The selectors as the tree they are: a star is the parent of everything beneath it."""
    names = sorted(s for s in selectors if s != "*")
    tree = {"*": {"label": "every action of every kind", "children": {}}}
    for branch in [s for s in names if s.endswith(".*")]:
        stem = branch[:-2]
        leaves = sorted(s for s in names if s.startswith(stem + ".") and not s.endswith(".*"))
        kinds = {}
        for leaf in leaves:
            rest = leaf[len(stem) + 1:]
            kind = rest.split(".")[0] if "." in rest else "(direct)"
            # a leaf like CCI.Supervisor.Resource.VirtualMachine.Add.Disk has kind VirtualMachine, verb Add.Disk
            kinds.setdefault(kind, []).append(rest[len(kind) + 1:] if rest.startswith(kind + ".") else rest)
        tree["*"]["children"][branch] = {"leaves": len(leaves), "kinds": {k: sorted(v) for k, v in sorted(kinds.items())}}
    return tree



# ---- the rehearsal: the platform's own no-write dry run of a policy that does not exist yet
#
# The create call takes a dryRun query parameter. The plane answers 202, writes nothing, and returns a Location
# naming the decisions it WOULD have produced, one per target the policy would touch. That is the only way to see
# the regime flip and the union before they are real. This function sends that call with a grant naming a group
# that exists nowhere, reads the rehearsal back, and then re-reads the policy list to prove nothing was created.
def rehearse(c, org_id, project_id, L):
    """Ask what one more policy would do. Returns (summary, None) or (None, why)."""
    st, before = c.page("/policy/api/policies")
    if st != 200:
        return None, f"the policy list answered HTTP {st}"
    probe_name = "zz-rehearsal-that-is-never-created"
    body = {"name": probe_name, "typeId": ACTION_TYPE, "enforcementType": "HARD",
            "orgId": org_id, "projectId": project_id,
            "definition": {"allowedActions": [{"actions": ["Deployment.PowerOn"],
                                               "authorities": ["GROUP:zz-rehearsal-group@"]}]}}
    st2, _, headers = c.send("POST", "/policy/api/policies?dryRun=true", body)
    if st2 != 202:
        return None, f"the plane answered HTTP {st2} to a dry run rather than 202"
    loc = headers.get("location") or headers.get("Location")
    if not loc:
        return None, "the dry run returned no location to read the rehearsal from"
    rehearsed = []
    for _ in range(8):
        time.sleep(5)
        st3, page = c.get(loc + "&size=200")
        if st3 == 200 and isinstance(page, dict) and (page.get("content") or []):
            rehearsed = page["content"]
            break
    st4, after = c.page("/policy/api/policies")
    created = [p for p in after if p.get("name") == probe_name]
    if created:
        raise SystemExit("FATAL: the dry run created a policy; delete it by hand and do not trust this path")
    return {"targetsAffected": len({d.get("targetId") for d in rehearsed}),
            "policiesBefore": len(before), "policiesAfter": len(after),
            "wouldApplyPerTarget": sorted({len(d.get("policies") or []) for d in rehearsed}),
            "sample": ([{"policiesThatWouldApply": len(rehearsed[0].get("policies") or []),
                         "wouldBecome": [{"authorities": [L.scrub(a) for a in (e.get("authorities") or [])],
                                          "actions": e.get("actions") or []}
                                         for e in ((rehearsed[0].get("effectivePolicyDefinition") or {}).get("allowedActions") or [])]}]
                       if rehearsed else [])}, None


def main():
    host, org = os.environ["VCFA_HOST"], os.environ["VCFA_ORG"]
    refresh = open(os.environ["VCFA_REFRESH_TOKEN_FILE"], encoding="utf-8").read().strip()
    out_dir = os.environ.get("OUT_DIR", ".")
    c = Policy(host, org, refresh)
    L = Labels()
    print("governance.py: the policy model, read from the platform through the policy plane, read-only\n")

    # ---- 1. the types, and the three schemas each publishes
    st, types = c.page("/policy/api/policyTypes")
    if st != 200:
        print(f"FATAL: the policy plane answered HTTP {st}")
        sys.exit(1)
    model = []
    for t in types:
        st2, full = c.get(f"/policy/api/policyTypes/{t['id']}")
        full = full if st2 == 200 and isinstance(full, dict) else t
        st3, scope = c.get(f"/policy/api/policyTypes/{t['id']}/scopeSchema")

        def keys(schema):
            return sorted((schema or {}).get("properties", {}).keys())

        model.append({
            "id": t["id"],
            "displayName": t.get("displayName") or t.get("name"),
            "config": full.get("config") or {},
            "says": keys(full.get("definitionSchema")),
            "matches": keys(full.get("targetSchema")),
            "applies": keys(scope if st3 == 200 else None),
            "required": sorted((full.get("definitionSchema") or {}).get("required") or []),
            "enums": {k: v.get("enum") for k, v in ((full.get("definitionSchema") or {}).get("properties") or {}).items() if isinstance(v, dict) and v.get("enum")},
        })
    print(f"  types: {len(model)} declared")
    for m in model:
        cfg = m["config"]
        lim = "unlimited" if cfg.get("maxNumberOfPoliciesPerOrg", -1) < 0 else f"{cfg['maxNumberOfPoliciesPerOrg']} per org, {cfg.get('maxNumberOfPoliciesPerProject')} per project"
        print(f"     {m['id']:<38} enforcement={'yes' if cfg.get('enableEnforcementType') else 'no ':<3} dryRun={'yes' if cfg.get('enableDryRun') else 'no '}  validation={'yes' if cfg.get('enablePolicyValidation') else 'no '}  {lim}")

    # ---- 2. the action selectors, as a tree
    st, sel = c.get(f"/policy/api/policyTypes/{ACTION_TYPE}/data/action-selectors?size=500")
    selectors = [s["id"] for s in (sel.get("content") or [])] if st == 200 and isinstance(sel, dict) else []
    tree = action_tree(selectors)
    branches = tree["*"]["children"]
    print(f"\n  action selectors: {len(selectors)}, one root, {len(branches)} branches")
    for b, v in branches.items():
        print(f"     {b:<34} {v['leaves']:>2} leaves in {len(v['kinds'])} kind(s): " + ", ".join(f"{k} ({len(x)})" for k, x in v["kinds"].items()))

    # ---- 3. the policies the organization holds
    st, pols = c.page("/policy/api/policies")
    held = []
    for p in pols:
        L.get("policy", p.get("name", ""))
        held.append({"type": p.get("typeId"), "scope": "project" if p.get("projectId") else "organization",
                     "enforcement": p.get("enforcementType")})
    from collections import Counter
    print(f"\n  policies held: {len(held)}")
    print(f"     by type: {dict(Counter(h['type'].split('.')[-1] for h in held))}")
    print(f"     by scope: {dict(Counter(h['scope'] for h in held))}   by enforcement: {dict(Counter(h['enforcement'] for h in held))}")

    # ---- 4. the decision log: the composition rule, stated by the thing that performs it
    st, decisions = c.page("/policy/api/policyDecisions")
    st_all, all_page = c.get("/policy/api/policyDecisions?size=1")
    total_decisions = (all_page or {}).get("totalElements") if isinstance(all_page, dict) else None
    for d in decisions:
        for p in (d.get("policies") or []):
            L.get("policy", p.get("name", ""))
        for a in ((d.get("effectivePolicyDefinition") or {}).get("allowedActions") or []):
            for auth in (a.get("authorities") or []):
                if ":" in auth:
                    L.get("authority", auth.split(":", 1)[1])
    ranks = Counter(p.get("rank") for d in decisions for p in (d.get("policies") or []))
    applied = Counter(len(d.get("policies") or []) for d in decisions)
    print(f"\n  decisions read: {len(decisions)} of {total_decisions} held, over {len({d.get('targetId') for d in decisions})} target(s)")
    print(f"     policies applied per decision: {dict(sorted(applied.items()))}")
    print(f"     ranks the plane assigned:      {dict(sorted(ranks.items()))}")

    def shape(d):
        """One decision, structurally: what applied, at what rank, and what it computed."""
        eff = d.get("effectivePolicyDefinition") or {}
        return {
            "policiesApplied": [
                {"rank": p.get("rank"), "status": p.get("status"), "enforcement": p.get("enforcementType"),
                 "scope": "project" if p.get("projectId") else "organization", "name": L.scrub(p.get("name", ""))}
                for p in sorted(d.get("policies") or [], key=lambda x: x.get("rank", 0))],
            "effective": [
                {"authorities": [L.scrub(a) for a in (e.get("authorities") or [])], "actions": e.get("actions") or []}
                for e in (eff.get("allowedActions") or [])],
            "description": L.scrub(d.get("description") or ""),
        }

    by_count = {}
    for d in decisions:
        by_count.setdefault(len(d.get("policies") or []), d)
    worked = {str(n): shape(d) for n, d in sorted(by_count.items())}
    print("\n  one decision of each shape the log holds:")
    for n, w in worked.items():
        auth = sum(len(e["actions"]) for e in w["effective"])
        print(f"     {n} policy/policies applied -> {len(w['effective'])} authority bucket(s), {auth} action entr(ies)")

    # ---- 4b. optional: rehearse one more policy, which the plane will do without creating it
    rehearsal = None
    if "--rehearse" in sys.argv:
        scoped = next((p for p in pols if p.get("projectId")), None)
        if not scoped:
            print("\n  rehearsal: skipped (no project-scoped policy to borrow an organization and project from)")
        else:
            print("\n  rehearsal: asking what one more policy would do, without creating it")
            rehearsal, why = rehearse(c, scoped.get("orgId"), scoped.get("projectId"), L)
            if rehearsal is None:
                print(f"     skipped: {why}")
            else:
                print(f"     it would touch {rehearsal['targetsAffected']} target(s); policies applying per target would be {rehearsal['wouldApplyPerTarget']}")
                print(f"     the policy list is {rehearsal['policiesBefore']} before and {rehearsal['policiesAfter']} after: nothing was created")
    elif pols:
        print("\n  rehearsal: not asked (pass --rehearse to run the platform's own dry run; see the README)")

    # ---- 5. write, sanitized
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    os.makedirs(out_dir, exist_ok=True)
    records = {
        "policy-model.json": {"captured_utc": stamp, "types": model, "actionSelectors": {"count": len(selectors), "tree": tree}},
        "decisions.json": {"captured_utc": stamp, "decisions": len(decisions), "decisionsHeld": total_decisions,
                           "targets": len({d.get("targetId") for d in decisions}),
                           "policiesAppliedPerDecision": {str(k): v for k, v in sorted(applied.items())},
                           "ranksAssigned": {str(k): v for k, v in sorted(ranks.items())},
                           "held": {"total": len(held), "byType": dict(Counter(h["type"] for h in held)),
                                    "byScope": dict(Counter(h["scope"] for h in held)),
                                    "byEnforcement": dict(Counter(h["enforcement"] for h in held))},
                           "worked": worked, "rehearsal": rehearsal},
    }
    for fname, payload in records.items():
        text = UUID.sub("{{id}}", json.dumps(payload, indent=1, ensure_ascii=False))
        for secret in (c.bearer, refresh, host, org):
            assert secret not in text, f"an estate value reached {fname}"
        bare = re.sub(r"\{\{[^}]*\}\}", "", text)
        for fam, m in L.maps.items():
            for name in m:
                if not name:
                    continue
                if re.search(r"(?<![A-Za-z0-9-])" + re.escape(name) + r"(?![A-Za-z0-9-])", bare):
                    shape_of = re.sub(r"[A-Za-z]", "a", re.sub(r"[0-9]", "9", name))
                    raise SystemExit(f"FATAL: a {fam} name ({len(name)} characters, shape {shape_of}) reached {fname}; not writing it")
        open(os.path.join(out_dir, fname), "w", encoding="utf-8").write(text + "\n")
    print(f"\nwrote policy-model.json ({len(model)} types, {len(selectors)} selectors) and decisions.json "
          f"({len(decisions)} decisions, {len(worked)} worked shapes); every organization value replaced by a placeholder")


if __name__ == "__main__":
    main()
