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

Two read-only checks run on their own and write nothing:

  --actions <deployment-id>   reads that deployment's actions as you, every five seconds, until two reads in a row
                              agree, and prints the count it settled on: the read to trust after a policy change
  --authority <authority>     says whether an authority is written in a form the decision log holds (its prefix,
                              its case, the trailing at-sign a group carries), whether the platform's own check
                              accepts a policy naming it (validationOnly, which creates nothing), and whether any
                              decision holds a bucket for it yet

Sign-in, one of:
  VCFA_REFRESH_TOKEN_FILE   a file holding a refresh token minted for the organization, mode 0600
  VCFA_USER and VCFA_PASSWORD_FILE   a session login as user@org (the password from a file of mode 0600, or
                            VCFA_PASSWORD, the value itself, which lands in the shell's history)
A file open to group or other is refused before it is read.

Run:
  export VCFA_HOST=<automation-fqdn> VCFA_ORG=<org>
  export VCFA_USER=<account> VCFA_PASSWORD_FILE=~/.vcf/vcfa-password    # or VCFA_REFRESH_TOKEN_FILE
  export TLS_VERIFY=false                                               # only on a self-signed lab CA
  python3 governance.py                       # the model, the policies and the decision log
  python3 governance.py --rehearse            # also the platform's own dry run of one more policy
  python3 governance.py --actions <deployment-id>
  python3 governance.py --authority 'GROUP:Engineers@'

Exit: 0 read (for --actions: the count settled; for --authority: well formed and held by a decision)
      1 --actions: no two reads agreed within a minute; --authority: well formed, no decision holds it yet
      2 a call failed or the sign-in was refused
      3 --authority: written in a form the decision log never holds
      5 an unknown argument, or a flag without its value
"""
import base64
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
from collections import Counter

http.client._MAXHEADERS = 1000  # a large cloudapi page answers with more headers than the stdlib allows
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
ACTION_TYPE = "com.vmware.policy.deployment.action"


def ctx():
    verify = os.environ.get("TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")
    return ssl.create_default_context() if verify else ssl._create_unverified_context()


PLACEHOLDER = re.compile(r"(\{\{[^}]*\}\})")


def one_pass(text, known, edge="A-Za-z0-9-"):
    """Replace every (real, label) pair in one pass, the longest real name first, on a boundary of `edge` characters
    (none when empty), and never inside a placeholder already written. Replacing one name at a time lets a project
    named project-2 match inside the {{project-2}} just written for the project named project-1 (G-646). When a name
    is given twice, its first label wins."""
    label_of = {}
    for real, label in known:
        label_of.setdefault(real, label)
    if not label_of:
        return text
    names = "|".join(map(re.escape, sorted(label_of, key=len, reverse=True)))
    rx = re.compile(rf"(?<![{edge}])({names})(?![{edge}])" if edge else f"({names})")
    return "".join(part if i % 2 else rx.sub(lambda m: "{{%s}}" % label_of[m.group(1)], part)
                   for i, part in enumerate(PLACEHOLDER.split(text)))


class Labels:
    """Stable placeholders: the first group met is {{group-1}}, the second policy is {{policy-2}}."""

    # The product's own vocabulary is never an estate name. A principal can be called exactly what a platform
    # object is called (this estate has a user named "admin" and a project role named "admin"), and registering
    # one teaches the scrubber to blank the other. A name in RESERVED identifies no estate and is left alone.
    RESERVED = {"admin", "view", "edit", "user", "users", "group", "groups", "owner", "auditor", "auditors",
                "administrator", "administrators", "default", "system", "none", "all"}

    def __init__(self):
        self.maps = {}

    def get(self, family, name):
        if str(name) in self.RESERVED:
            return name
        m = self.maps.setdefault(family, {})
        if name not in m:
            m[name] = f"{family}-{len(m) + 1}"
        return "{{%s}}" % m[name]

    def scrub(self, text):
        """One pass, longest name first: a policy name can contain a group name."""
        if not isinstance(text, str):
            return text
        known = [(real, label) for m in self.maps.values() for real, label in m.items()]
        # Longest first so a contained name cannot corrupt a longer one, and on a WORD BOUNDARY so a short
        # name is not replaced inside an unrelated word. A principal really can be called "admin", and a naive
        # replace turns the field name "administrators" into "{{user-3}}istrators". The leak check below uses
        # the same boundary, so what the scrub replaces and what the check looks for are one rule.
        text = one_pass(text, known)
        return UUID.sub("{{id}}", text)


def secret(name):
    """A secret from NAME_FILE (a file, mode 0600, its value stripped) or else NAME itself; None when neither is set.
    The file keeps a tier-0 token out of the shell's history and the process list. A file open to group or other is
    refused before it is read; the refusal names the variable and the fix, never the file's content."""
    path = os.environ.get(f"{name}_FILE")
    if path:
        with open(path, encoding="utf-8") as f:
            mode = os.fstat(f.fileno()).st_mode & 0o777
            # Windows makes the mode from the read-only flag alone, so it has no group or other bits to judge.
            if mode & 0o077 and os.name != "nt":
                raise PermissionError(f"{name}_FILE names a file of mode {mode:04o}, open to group or other: "
                                      f'run chmod 600 "${name}_FILE" and try again (the file was not read)')
            return f.read().strip()
    return os.environ.get(name) or None


class Policy:
    def __init__(self, host, org, refresh_token=None, user=None, password=None):
        """A tenant bearer, from the organization's refresh token or from a session login as user@org. A refused
        mint ends the run with the server's own answer: "invalid_grant" means the refresh token is dead, a 401 at
        the session means the login is."""
        self.host = host
        if refresh_token:
            self.kind = "refresh token"
            body = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": refresh_token}).encode()
            req = urllib.request.Request(
                f"https://{host}/oauth/tenant/{org}/token", data=body, method="POST",
                headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
        else:
            self.kind = "session login"
            basic = base64.b64encode(f"{user.split('@')[0]}@{org}:{password}".encode()).decode()
            req = urllib.request.Request(f"https://{host}/cloudapi/1.0.0/sessions", method="POST",
                                         headers={"Authorization": f"Basic {basic}", "Accept": "application/json;version=40.0"})
        try:
            with urllib.request.urlopen(req, context=ctx(), timeout=30) as r:
                self.bearer = (json.loads(r.read())["access_token"] if refresh_token
                               else r.headers.get("X-VMWARE-VCLOUD-ACCESS-TOKEN"))
        except urllib.error.HTTPError as e:
            print(f"FATAL: the {self.kind} answered HTTP {e.code}: {e.read().decode(errors='replace')[:200]}")
            sys.exit(2)
        except (urllib.error.URLError, OSError) as e:
            print(f"FATAL: the {self.kind} did not answer: {e}")
            sys.exit(2)
        if not self.bearer:
            print(f"FATAL: the {self.kind} answered without a bearer")
            sys.exit(2)

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

    def page(self, path, size=200):
        """Every page of a list, in a stable order. The plane serves at most 200 entries a page whatever size is asked
        for (measured on 9.1.1: size=500 answered 200 of 270 decisions), so one read of a long list is partial; and
        a list read without a sort has no stable order across pages (one unsorted read of 270 decisions returned 16
        twice and missed 16), so every page is read sorted by id."""
        out, number = [], 0
        while True:
            st, body = self.get(f"{path}{'&' if '?' in path else '?'}size={size}&page={number}&sort=id,asc")
            if st != 200 or not isinstance(body, dict):
                return st, out
            out += body.get("content") or []
            number += 1
            if body.get("last", True) or number >= (body.get("totalPages") or 0):
                return st, out


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
def rehearse(c, org_id, project_id, L, decisions=()):
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
    # How many policies apply to each rehearsed target today, read from the decision log: the number the rehearsed
    # count is to be compared with (the length of the organization's whole policy list is a different number).
    today = {d.get("targetId"): len(d.get("policies") or []) for d in decisions}
    return {"targetsAffected": len({d.get("targetId") for d in rehearsed}),
            "policiesBefore": len(before), "policiesAfter": len(after),
            "wouldApplyPerTarget": sorted({len(d.get("policies") or []) for d in rehearsed}),
            "applyTodayPerTarget": sorted({today[d.get("targetId")] for d in rehearsed if d.get("targetId") in today}),
            "targetsWithoutADecisionToday": sum(1 for d in rehearsed if d.get("targetId") not in today),
            "sample": ([{"policiesThatWouldApply": len(rehearsed[0].get("policies") or []),
                         "wouldBecome": [{"authorities": [L.scrub(a) for a in (e.get("authorities") or [])],
                                          "actions": e.get("actions") or []}
                                         for e in ((rehearsed[0].get("effectivePolicyDefinition") or {}).get("allowedActions") or [])]}]
                       if rehearsed else [])}, None


def held_authorities(decisions):
    """Every authority the plane wrote into a decision's effective definition."""
    return [a for d in decisions for e in ((d.get("effectivePolicyDefinition") or {}).get("allowedActions") or [])
            for a in (e.get("authorities") or [])]


def authority_forms(held):
    """The forms the decision log writes authorities in, counted: prefixes, names in lower case, the trailing at-sign.
    The prefix itself is always written in capitals, so case is judged on the name after it."""
    def prefix(a):
        return a.split(":", 1)[0].upper() if ":" in a else "(none)"
    return {"total": len(held),
            "byPrefix": dict(sorted(Counter(prefix(a) for a in held).items())),
            "trailingAt": dict(sorted(Counter(prefix(a) for a in held if a.endswith("@")).items())),
            "lowercaseNames": sum(1 for a in held if a.split(":", 1)[-1] == a.split(":", 1)[-1].lower())}


def bucket_shapes(decisions):
    """The buckets the plane computed, by shape: an empty action list (an explicit deny) and a named action beside the
    star that already covers it (inert until the star narrows)."""
    buckets = [e for d in decisions for e in ((d.get("effectivePolicyDefinition") or {}).get("allowedActions") or [])]
    acts = [e.get("actions") or [] for e in buckets]
    return {"buckets": len(buckets), "emptyActions": sum(1 for a in acts if not a),
            "namedBesideStar": sum(1 for a in acts if "*" in a and len(a) > 1),
            "decisionsWithEmptyActions": sum(1 for d in decisions if any(not (e.get("actions") or []) for e in
                                             ((d.get("effectivePolicyDefinition") or {}).get("allowedActions") or [])))}


def rank_order(decisions):
    """Whether an organization-scoped policy is ranked ahead of every project-scoped one, counted over the log."""
    def scoped(p):
        return "project" if p.get("projectId") else "organization"
    with_policies = [d for d in decisions if d.get("policies")]
    both = [d for d in with_policies if {scoped(p) for p in d["policies"]} == {"organization", "project"}]
    org_first = [d for d in both
                 if max(p.get("rank", 0) for p in d["policies"] if scoped(p) == "organization")
                 < min(p.get("rank", 0) for p in d["policies"] if scoped(p) == "project")]
    project_only_first = [d for d in with_policies if all(scoped(p) == "project" for p in d["policies"])
                          and any(p.get("rank") == 1 for p in d["policies"])]
    return {"decisionsWithPolicies": len(with_policies), "bothScopes": len(both),
            "organizationRankedFirst": len(org_first),
            "projectHoldsRankOneWithNoOrganizationPolicy": len(project_only_first)}


def settle_actions(c, deployment, every=5, limit=60):
    """Read one deployment's actions as the signed-in principal until two reads in a row agree."""
    print("governance.py: the actions you hold on one deployment, read until two reads in a row agree\n")
    t0, last = time.time(), None
    while True:
        st, acts = c.get(f"/deployment/api/deployments/{urllib.parse.quote(deployment, safe='')}/actions")
        if st != 200 or not isinstance(acts, list):
            print(f"FATAL: the actions read answered HTTP {st}")
            return 2
        valid = sorted(a.get("name") or a.get("id") or "?" for a in acts if a.get("valid"))
        print(f"  {round(time.time() - t0):>3} s   {len(valid)} of {len(acts)} actions valid for you")
        if last is not None and len(valid) == last:
            print(f"\n  settled at {len(valid)} after {round(time.time() - t0)} s: this is the count to trust")
            print("  valid: " + (", ".join(valid) or "none"))
            return 0
        last = len(valid)
        if time.time() - t0 + every > limit:
            print(f"\n  no two reads agreed within {limit} s: the change is still propagating, read again")
            return 1
        time.sleep(every)


def validate_only(c, text, org_id, project_id):
    """The platform's own check of a body naming this authority, sent with validationOnly, which creates nothing:
    the policy list is read before and after, and the run stops hard if it changed."""
    st0, before = c.page("/policy/api/policies")
    probe = "zz-validation-that-is-never-created"
    body = {"name": probe, "typeId": ACTION_TYPE, "enforcementType": "HARD", "orgId": org_id, "projectId": project_id,
            "definition": {"allowedActions": [{"actions": ["Deployment.PowerOn"], "authorities": [text]}]}}
    st, answer, _ = c.send("POST", "/policy/api/policies?validationOnly=true", body)
    st1, after = c.page("/policy/api/policies")
    if st0 != 200 or st1 != 200 or len(after) != len(before) or any(p.get("name") == probe for p in after):
        raise SystemExit("FATAL: the policy list changed across a validation-only call, or could not be read; "
                         "check it by hand and do not trust this path")
    return st, answer


def check_authority(text, decisions, c=None, scope=None):
    """Is this authority written in a form the decision log holds, does the platform's own check accept it, and does a
    decision hold a bucket for it yet?"""
    held = held_authorities(decisions)
    forms = authority_forms(held)
    print("governance.py: one authority, checked against the forms the decision log holds\n")
    print(f"  the log holds {forms['total']} authorities in {len(decisions)} decisions; prefixes "
          + ", ".join(f"{k}: {v}" for k, v in forms["byPrefix"].items())
          + "; with a trailing at-sign " + (", ".join(f"{k}: {v}" for k, v in forms["trailingAt"].items()) or "none")
          + f"; names in lower case {forms['lowercaseNames']} of {forms['total']}")
    prefix, sep, name = text.partition(":")
    pfx, problems = prefix.upper(), []
    if not sep or pfx not in forms["byPrefix"]:
        problems.append(f"its prefix ({prefix + ':' if sep else 'none'}) is not one the log holds")
    else:
        total, at = forms["byPrefix"][pfx], forms["trailingAt"].get(pfx, 0)
        if at == total and not name.endswith("@"):
            problems.append(f"every {pfx}: authority the log holds ends in an at-sign, and this one does not")
        if at == 0 and name.endswith("@"):
            problems.append(f"no {pfx}: authority the log holds ends in an at-sign, and this one does")
    if c is not None and scope:
        st, answer = validate_only(c, text, *scope)
        if st == 200:
            print("  the platform's own check (validationOnly) accepted a policy naming it, and created nothing")
        elif st and 400 <= st < 500:
            print(f"  the platform's own check (validationOnly) refused it with HTTP {st}: "
                  + UUID.sub("{{id}}", str(answer))[:200])
        else:
            print(f"FATAL: the validation-only call answered HTTP {st}")
            return 2
    else:
        print("  the platform's own check was not asked: no project-scoped policy to borrow an organization and project from")
    if problems:
        for why in problems:
            print(f"  not a form the log holds: {why}")
        print("  a policy naming it would match nobody")
        return 3
    lower = forms["lowercaseNames"] == forms["total"]
    held_as = f"{pfx}:{name.lower()}" if lower else text
    present = any(a == held_as or (not lower and a.lower() == text.lower()) for a in held)
    if lower and held_as != text:
        print(f"  the log stores every name in lower case, so this one is held as {held_as}")
    if present:
        print("  a decision holds a bucket for it: it matches")
        return 0
    print("  well formed, and no decision holds a bucket for it yet: a grant not written yet, or a principal "
          "that matches nobody")
    return 1


def refuse_unknown_args(known, takes_value=()):
    """Refuse any argument this script does not recognise, before a client opens: a stray flag such as --check
    must never reach a write. --help prints the usage above."""
    args = sys.argv[1:]
    if "-h" in args or "--help" in args:
        print(__doc__)
        sys.exit(0)
    unknown = [a for i, a in enumerate(args) if a not in known and not (i and args[i - 1] in takes_value)]
    if unknown:
        print(f"unknown argument(s) {unknown}: this script takes {', '.join(sorted(known))} (see --help)", file=sys.stderr)
        sys.exit(5)


def main():
    refuse_unknown_args({"--rehearse", "--actions", "--authority"}, takes_value=("--actions", "--authority"))
    for flag in ("--actions", "--authority"):
        if flag in sys.argv and sys.argv.index(flag) + 1 >= len(sys.argv):
            print(f"{flag} takes a value (see --help)", file=sys.stderr)
            sys.exit(5)
    host, org = os.environ["VCFA_HOST"], os.environ["VCFA_ORG"]
    try:
        refresh, password = secret("VCFA_REFRESH_TOKEN"), secret("VCFA_PASSWORD")
    except OSError as e:   # a secret file that is missing, unreadable or open to group or other
        print(f"FATAL: {e}")
        sys.exit(2)
    user = os.environ.get("VCFA_USER")
    if not refresh and not (user and password):
        print("FATAL: set VCFA_REFRESH_TOKEN_FILE, or VCFA_USER with VCFA_PASSWORD_FILE (see --help)")
        sys.exit(2)
    out_dir = os.environ.get("OUT_DIR", ".")
    c = Policy(host, org, refresh, None if refresh else user, None if refresh else password)
    if "--actions" in sys.argv:
        sys.exit(settle_actions(c, sys.argv[sys.argv.index("--actions") + 1]))
    if "--authority" in sys.argv:
        st, decisions = c.page("/policy/api/policyDecisions")
        if st != 200:
            print(f"FATAL: the decision log answered HTTP {st}")
            sys.exit(2)
        st, pols = c.page("/policy/api/policies")
        scoped = next((p for p in pols if p.get("projectId")), None) if st == 200 else None
        scope = (scoped.get("orgId"), scoped.get("projectId")) if scoped else None
        sys.exit(check_authority(sys.argv[sys.argv.index("--authority") + 1], decisions, c, scope))
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
    print(f"\n  policies held: {len(held)}")
    print(f"     by type: {dict(Counter(h['type'].split('.')[-1] for h in held))}")
    print(f"     by scope: {dict(Counter(h['scope'] for h in held))}   by enforcement: {dict(Counter(h['enforcement'] for h in held))}")

    # ---- 4. the decision log: the composition rule, stated by the thing that performs it
    st, decisions = c.page("/policy/api/policyDecisions")
    if st != 200:
        print(f"FATAL: the decision log answered HTTP {st}")
        sys.exit(2)
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
    forms, order, shapes = authority_forms(held_authorities(decisions)), rank_order(decisions), bucket_shapes(decisions)
    print(f"     authorities written: {forms['total']}, by prefix {forms['byPrefix']}, with a trailing at-sign "
          f"{forms['trailingAt']}, names in lower case {forms['lowercaseNames']}")
    print(f"     decisions with both scopes: {order['bothScopes']}, the organization ranked first in "
          f"{order['organizationRankedFirst']}; a project policy at rank 1 with no organization policy: "
          f"{order['projectHoldsRankOneWithNoOrganizationPolicy']} of {order['decisionsWithPolicies']}")
    print(f"     buckets computed: {shapes['buckets']}; an empty action list {shapes['emptyActions']} "
          f"(in {shapes['decisionsWithEmptyActions']} decisions); a named action beside the star {shapes['namedBesideStar']}")

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
            rehearsal, why = rehearse(c, scoped.get("orgId"), scoped.get("projectId"), L, decisions)
            if rehearsal is None:
                print(f"     skipped: {why}")
            else:
                print(f"     it would touch {rehearsal['targetsAffected']} target(s); policies applying per target would be "
                      f"{rehearsal['wouldApplyPerTarget']}, where {rehearsal['applyTodayPerTarget']} apply today")
                print(f"     the policy list is {rehearsal['policiesBefore']} before and {rehearsal['policiesAfter']} after: nothing was created")
    elif pols:
        print("\n  rehearsal: not asked (pass --rehearse to run the platform's own dry run; see the README)")

    # A run without --rehearse must not blank a rehearsal a previous run captured. This is G-166 arriving
    # in a second script: an optional probe writes a section of a record, and it does not get to delete
    # one. Without this, a plain re-read erases the dry-run result and the chapter renders it empty.
    if rehearsal is None:
        prior = os.path.join(out_dir, "decisions.json")
        if os.path.exists(prior):
            try:
                kept = (json.load(open(prior, encoding="utf-8")) or {}).get("rehearsal")
            except ValueError:
                kept = None
            if kept:
                rehearsal = dict(kept)
                rehearsal.setdefault("capturedBy", "an earlier run with --rehearse")
                print("     carrying forward the rehearsal captured earlier; this run did not re-run it "
                      "and has not erased it")

    # ---- 5. write, sanitized
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    os.makedirs(out_dir, exist_ok=True)
    records = {
        "policy-model.json": {"captured_utc": stamp, "types": model, "actionSelectors": {"count": len(selectors), "tree": tree}},
        "decisions.json": {"captured_utc": stamp, "signIn": c.kind, "decisions": len(decisions), "decisionsHeld": total_decisions,
                           "authorityForms": forms, "rankOrder": order, "bucketShapes": shapes,
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
        for value in (c.bearer, refresh, password, user, host, org):
            assert not value or value not in text, f"an estate value reached {fname}"
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
