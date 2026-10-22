#!/usr/bin/env python3
"""fences.py: do the two deletion fences that are policies, approval on destroy and a lease, hold on your build?

governance.py reads the policy model and never writes. This script writes, on objects it creates and deletes, to
answer what the model cannot: what the platform does with a destroy request once an approval policy covers it, and
what a lease policy writes onto a new deployment. In the project you name:

  1. A THROWAWAY BLUEPRINT that provisions nothing (one generated password, no machine, no namespace).
  2. TWO HARD POLICIES, each scoped by its criteria to that blueprint alone, so no other deployment meets them:
     a lease (the shortest term the schema allows, one day, with no grace) and an approval on Deployment.Delete
     naming you as the one approver.
  3. A DEPLOYMENT of the blueprint, and the lease it was given, read from the deployment.
  4. A DESTROY REQUEST, which should wait for approval; you REJECT it as the approver, and the deployment should
     still be there. Then a second destroy request, which you APPROVE, and the deployment should be gone.
  5. TEARDOWN, always: the approval policy first (so nothing it covers is left waiting), the deployment if it is
     still there, the lease, the blueprint, then a residue read.

Everything it creates is named probe-fences. A policy change takes a while to reach new requests, so it waits for
that before deploying; the record says how long.

Run:
  export VCFA_HOST=<automation-fqdn> VCFA_ORG=<org>
  export VCFA_USER=<account> VCFA_PASSWORD_FILE=~/.vcf/vcfa-password    # mode 0600: a session login
  export TLS_VERIFY=false                                               # only on a self-signed lab CA
  python3 fences.py --project <a project nobody depends on>
The account must hold the organization administrator role: it writes policies, and it approves its own request.

The record, fences.json (beside this script, or in OUT_DIR), and every printed line carry labels in place of the
project, user, organization and host, and no object id.

Exit: 0 both fences held: the lease was set from the policy, the destroy waited, the rejection kept the deployment and
      the approval removed it · 1 a fence did not hold, and the record says which step · 2 a setting is missing or a
      secret file is open to group or other · 3 a read or write failed · 4 the record refused to write because an
      estate value survived · 5 an unknown argument, or --project missing
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import secrets
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("governance", os.path.join(HERE, "governance.py"))
G = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(G)

PREFIX = "probe-fences"
LEASE = "com.vmware.policy.deployment.lease"
APPROVAL = "com.vmware.policy.approval"
CONTENT = ("formatVersion: 1\ninputs: {}\nresources:\n  Secret:\n    type: Util.PasswordEntry\n"
           "    properties:\n      length: 12\n")
TERMINAL = {"SUCCESSFUL", "FAILED", "CANCELLED", "ABORTED", "REJECTED", "APPROVAL_REJECTED", "COMPLETED"}
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


class Failed(Exception):
    """A step the verdict depends on could not be done; exit 3 with the step named."""


def args():
    a, out = sys.argv[1:], {}
    while a:
        k = a.pop(0)
        if k == "--project" and a:
            out["project"] = a.pop(0)
        else:
            print(f"unknown or incomplete argument {k!r}: the one argument is --project <project>", file=sys.stderr)
            sys.exit(5)
    if "project" not in out:
        print("fences.py writes policies and a deployment: name the project it may write in with --project <project>",
              file=sys.stderr)
        sys.exit(5)
    return out


class Run:
    def __init__(self, opt):
        self.opt = opt
        self.rec = {"capturedUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "steps": []}
        self.created = {"blueprint": None, "lease": None, "approval": None, "deployment": None}
        self.c = self.me = self.project_id = self.org_id = None
        self.pending = []  # destroy requests left waiting for approval, rejected by teardown

    # ---------------------------------------------------------------- plumbing
    def call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        h = {"Authorization": f"Bearer {self.c.bearer}", "Accept": "application/json"}
        if data is not None:
            h["Content-Type"] = "application/json"
        req = urllib.request.Request(f"https://{os.environ['VCFA_HOST']}{path}", data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, context=G.ctx(), timeout=90) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, {"message": raw.decode(errors="replace")[:300]}
        except (urllib.error.URLError, OSError) as e:
            return None, {"message": type(e).__name__}

    def pairs(self):
        p = [(self.opt["project"], "<project>"), (self.me, "<user>"), (os.environ.get("VCFA_USER"), "<user>"),
             (os.environ.get("VCFA_ORG"), "<org>"), (os.environ.get("VCFA_HOST"), "<host>")]
        return sorted((x for x in p if x[0]), key=lambda x: -len(x[0]))

    def redact(self, text):
        for value, label in self.pairs():
            text = text.replace(value, label)
        return UUID.sub("<id>", text)

    def log(self, step, **kw):
        t = time.strftime("%H:%M:%SZ", time.gmtime())
        self.rec["steps"].append({"at": t, "step": step, **kw})
        print(self.redact(f"[{t}] {step} {json.dumps(kw) if kw else ''}"), flush=True)

    @staticmethod
    def wait(what, fn, timeout, every=5):
        t0 = time.time()
        while time.time() - t0 < timeout:
            v = fn()
            if v:
                return v, round(time.time() - t0)
            time.sleep(every)
        raise Failed(f"timed out after {timeout} s waiting for {what}")

    @staticmethod
    def hours_until(start, end):
        if not (start and end):
            return None
        span = datetime.fromisoformat(end.replace("Z", "+00:00")) - datetime.fromisoformat(start.replace("Z", "+00:00"))
        return round(span.total_seconds() / 3600, 1)

    @staticmethod
    def message(body):
        return (body or {}).get("message", "")[:200] if isinstance(body, dict) else str(body)[:200]

    # ---------------------------------------------------------------- setup
    def sign_in(self):
        self.c = G.Policy(os.environ["VCFA_HOST"], os.environ["VCFA_ORG"], None, os.environ["VCFA_USER"],
                          G.secret("VCFA_PASSWORD"))
        st, me = self.call("GET", "/csp/gateway/am/api/loggedin/user")
        if st != 200:
            raise Failed(f"reading who you are answered {st}")
        self.me = me["username"]
        st, pr = self.call("GET", "/project-service/api/projects?size=200")
        proj = next((p for p in (pr or {}).get("content") or [] if p.get("name") == self.opt["project"]), None)
        if not proj:
            raise Failed("--project names no project this identity can see")
        self.project_id, self.org_id = proj["id"], proj.get("orgId")

    def blueprint(self):
        name = f"{PREFIX}-{secrets.token_hex(3)}"
        st, b = self.call("POST", "/blueprint/api/blueprints",
                          {"name": name, "projectId": self.project_id, "content": CONTENT,
                           "description": "throwaway: deletion-fence probe, deleted by the script that made it"})
        self.log("blueprint create", status=st, refused=self.message(b) if (st or 0) >= 300 else None)
        if (st or 0) >= 300:
            raise Failed("blueprint create refused")
        self.created["blueprint"] = b["id"]

    def policy(self, key, typ, definition):
        body = {"name": f"{PREFIX}-{key}", "typeId": typ, "enforcementType": "HARD", "orgId": self.org_id,
                "projectId": self.project_id, "definition": definition,
                "description": "throwaway: deletion-fence probe, scoped to one throwaway blueprint",
                "criteria": {"matchExpression": [{"key": "blueprintId", "operator": "eq",
                                                  "value": self.created["blueprint"]}]}}
        st, p = self.call("POST", "/policy/api/policies", body)
        self.log(f"{key} policy create", status=st, refused=self.message(p) if (st or 0) >= 300 else None)
        if (st or 0) >= 300:
            raise Failed(f"{key} policy create refused")
        self.created[key] = p["id"]

    # ---------------------------------------------------------------- the test
    def deploy(self):
        name = f"{PREFIX}-{secrets.token_hex(3)}"
        st, r = self.call("POST", "/blueprint/api/blueprint-requests",
                          {"blueprintId": self.created["blueprint"], "projectId": self.project_id,
                           "deploymentName": name, "inputs": {}, "reason": "deletion-fence probe"})
        self.log("deploy request", status=st, refused=self.message(r) if (st or 0) >= 300 else None)
        if (st or 0) >= 300 or not (r or {}).get("deploymentId"):
            raise Failed("deploy request refused")
        dep = r["deploymentId"]
        self.created["deployment"] = dep

        def done():
            s, d = self.call("GET", f"/deployment/api/deployments/{dep}")
            status = (d or {}).get("status") if s == 200 else None
            if status in ("CREATE_SUCCESSFUL", "CREATE_FAILED"):
                return d
        d, secs = self.wait("the deployment created", done, 600, 10)
        created, expires = d.get("createdAt"), d.get("leaseExpireAt")
        days = None
        if created and expires:
            span = datetime.fromisoformat(expires.replace("Z", "+00:00")) - datetime.fromisoformat(created.replace("Z", "+00:00"))
            days = round(span.total_seconds() / 86400, 2)
        self.log("deployment created", seconds=secs, status=d.get("status"), leaseSet=bool(expires), leaseDays=days)
        if d.get("status") != "CREATE_SUCCESSFUL":
            raise Failed("the deployment did not create")
        return days

    def destroy_request(self):
        dep = self.created["deployment"]
        st, r = self.call("POST", f"/deployment/api/deployments/{dep}/requests",
                          {"actionId": "Deployment.Delete", "reason": "deletion-fence probe", "inputs": {}})
        if (st or 0) >= 300 or not (r or {}).get("id"):
            raise Failed(f"destroy request answered {st}: {self.message(r)}")
        rid = r["id"]

        def settled():
            s, q = self.call("GET", f"/deployment/api/deployments/{dep}/requests?size=50")
            req = next((x for x in (q or {}).get("content") or [] if x.get("id") == rid), None)
            status = (req or {}).get("status")
            if status and (status == "APPROVAL_PENDING" or status in TERMINAL or status.endswith("FAILED")):
                return status
        status, secs = self.wait("the destroy request to wait or finish", settled, 300, 5)
        if status == "APPROVAL_PENDING":
            self.pending.append(rid)
        return rid, status, secs

    def approval_item(self, rid):
        """The approval the platform raised for this request, by the item's own requestId. The list is read without a
        sort: sorted by id, as other lists here are read, it answers HTTP 500 on 9.1.1, and a read that fails is a
        failure, never a reason to wait longer (G-786)."""
        def found():
            s, page = self.call("GET", "/approval/api/approvals?size=200")
            if s != 200:
                raise Failed(f"the approvals list answered {s}: {self.message(page)}")
            return next((a for a in (page or {}).get("content") or [] if a.get("requestId") == rid), None)
        return self.wait("the approval item for the request", found, 120, 5)[0]

    def item_state(self, item_id):
        s, a = self.call("GET", f"/approval/api/approvals/{item_id}")
        return ({k: a.get(k) for k in ("status", "decision", "currentLevel", "totalLevels", "autoApproval", "expired")}
                if s == 200 and isinstance(a, dict) else {"read": s})

    def act(self, item, action):
        st, r = self.call("POST", "/approval/api/approvals/action",
                          {"itemId": item["id"], "action": action, "comment": "deletion-fence probe"})
        return st, self.message(r) if (st or 0) >= 300 else ""

    def request_status(self, rid, want, timeout=600):
        dep = self.created["deployment"]

        def at():
            s, q = self.call("GET", f"/deployment/api/deployments/{dep}/requests?size=50")
            req = next((x for x in (q or {}).get("content") or [] if x.get("id") == rid), None)
            status = (req or {}).get("status")
            return status if status and (status in want or status in TERMINAL) else None
        return self.wait(f"the request to reach {sorted(want)}", at, timeout, 5)

    def test(self):
        self.sign_in()
        self.blueprint()
        self.policy("lease", LEASE, {"leaseTermMax": 1, "leaseTotalTermMax": 2, "leaseGrace": 0})
        self.policy("approval", APPROVAL, {"level": 1, "actions": ["Deployment.Delete"], "approvers": [f"USER:{self.me}"],
                                           "approvalMode": "ANY_OF", "approverType": "USER", "autoApprovalExpiry": 1,
                                           "autoApprovalDecision": "REJECT"})
        settle = 60  # a policy change takes a while to reach new requests (day2-governance's own measure is seconds)
        self.log("waiting for the policies to reach new requests", seconds=settle)
        time.sleep(settle)
        days = self.deploy()
        verdict = {"leaseSetFromThePolicy": days is not None and 0.9 <= days <= 1.1}

        rid, status, secs = self.destroy_request()
        self.log("first destroy request", status=status, secondsToSettle=secs)
        verdict["destroyWaitedForApproval"] = status == "APPROVAL_PENDING"
        if status != "APPROVAL_PENDING":
            self.rec["verdict"] = verdict
            return False
        item = self.approval_item(rid)
        self.log("approval raised", fields=sorted(item), status=item.get("status"), currentLevel=item.get("currentLevel"),
                 totalLevels=item.get("totalLevels"), expiresAfterHours=self.hours_until(item.get("createdAt"), item.get("expiryAt")))
        st, refused = self.act(item, "REJECT")
        final, secs = self.request_status(rid, {"REJECTED", "APPROVAL_REJECTED"})
        if final in TERMINAL:
            self.pending.remove(rid)
        s, d = self.call("GET", f"/deployment/api/deployments/{self.created['deployment']}")
        kept = s == 200
        self.log("rejected as the approver", actionStatus=st, refused=refused or None, requestStatus=final,
                 secondsToSettle=secs, deploymentStillThere=kept, item=self.item_state(item["id"]))
        verdict["rejectionKeptTheDeployment"] = kept and final in ("REJECTED", "APPROVAL_REJECTED")

        rid2, status2, secs = self.destroy_request()
        self.log("second destroy request", status=status2, secondsToSettle=secs)
        if status2 != "APPROVAL_PENDING":
            verdict["approvalRemovedTheDeployment"] = False
            self.rec["verdict"] = verdict
            return False
        item2 = self.approval_item(rid2)
        st, refused = self.act(item2, "APPROVE")
        if (st or 0) < 300:
            self.pending.remove(rid2)
        t0 = time.time()
        try:
            self.wait("the deployment gone", lambda: self.call("GET", f"/deployment/api/deployments/{self.created['deployment']}")[0] == 404, 900, 10)
            gone = True
        except Failed:
            gone = False
        self.log("approved as the approver", actionStatus=st, refused=refused or None, deploymentGone=gone,
                 secondsToGone=round(time.time() - t0) if gone else None, item=self.item_state(item2["id"]))
        if gone:
            self.created["deployment"] = None
        verdict["approvalRemovedTheDeployment"] = gone
        self.rec["verdict"] = verdict
        return all(verdict.values())

    # ---------------------------------------------------------------- teardown and residue
    def teardown(self):
        for rid in list(self.pending):
            try:
                st, refused = self.act(self.approval_item(rid), "REJECT")
                self.log("teardown rejects a destroy request still waiting", status=st, refused=refused or None)
            except Failed as e:
                self.log("a destroy request still waiting was not found to reject", note=str(e))
        if self.created["approval"]:
            st, _ = self.call("DELETE", f"/policy/api/policies/{self.created['approval']}")
            self.log("teardown approval policy", status=st)
        if self.created["deployment"]:
            time.sleep(30)  # the approval policy's removal reaching new requests
            dep = self.created["deployment"]
            st, r = self.call("POST", f"/deployment/api/deployments/{dep}/requests",
                              {"actionId": "Deployment.Delete", "reason": "deletion-fence probe teardown", "inputs": {}})
            self.log("teardown deployment", status=st)
            try:
                self.wait("the deployment gone", lambda: self.call("GET", f"/deployment/api/deployments/{dep}")[0] == 404, 900, 10)
            except Failed as e:
                self.log("deployment not gone yet: delete it by hand", note=str(e))
        if self.created["lease"]:
            st, _ = self.call("DELETE", f"/policy/api/policies/{self.created['lease']}")
            self.log("teardown lease policy", status=st)
        if self.created["blueprint"]:
            st, _ = self.call("DELETE", f"/blueprint/api/blueprints/{self.created['blueprint']}")
            self.log("teardown blueprint", status=st)

    def residue(self):
        st1, pols = self.c.page("/policy/api/policies")
        st2, deps = self.call("GET", f"/deployment/api/deployments?projects={self.project_id}&size=200")
        st3, bps = self.call("GET", f"/blueprint/api/blueprints?projects={self.project_id}&size=200")
        r = {"probePolicies": sum(1 for p in pols if str(p.get("name", "")).startswith(PREFIX)),
             "probeDeployments": sum(1 for d in (deps or {}).get("content") or [] if str(d.get("name", "")).startswith(PREFIX)),
             "probeBlueprints": sum(1 for b in (bps or {}).get("content") or [] if str(b.get("name", "")).startswith(PREFIX))}
        self.log("residue", **r)
        self.rec["residue"] = r
        return not any(r.values())


def scrub(rec, run):
    """Labels in place of every estate value; a record in which one survives outside a label is refused (exit 4)."""
    text = run.redact(json.dumps(rec, ensure_ascii=False))
    bare = text
    for _, label in run.pairs():
        bare = bare.replace(label, "")
    left = [label for value, label in run.pairs() if value in bare]
    if left:
        print(f"FATAL: the record still carries {left}; nothing written", file=sys.stderr)
        return None
    return json.loads(text)


def main():
    opt = args()
    run, code = Run(opt), 3
    try:
        if not os.environ.get("VCFA_HOST") or not os.environ.get("VCFA_ORG") or not os.environ.get("VCFA_USER"):
            raise KeyError("VCFA_HOST, VCFA_ORG and VCFA_USER, with VCFA_PASSWORD_FILE")
        if not G.secret("VCFA_PASSWORD"):
            raise KeyError("VCFA_PASSWORD_FILE")
    except (KeyError, PermissionError) as e:
        print(f"setting: {e}", file=sys.stderr)
        return 2
    try:
        code = 0 if run.test() else 1
    except Failed as e:
        run.log("stopped", reason=str(e))
        code = 3
    finally:
        try:
            if run.c:
                run.teardown()
                if not run.residue():
                    code = code or 3
        finally:
            out_dir = os.environ.get("OUT_DIR", HERE)
            rec = scrub(run.rec, run)
            if rec is None:
                code = 4
            else:
                with open(os.path.join(out_dir, "fences.json"), "w", encoding="utf-8") as f:
                    json.dump(rec, f, indent=1)
                    f.write("\n")
                where = "fences.json" if os.path.abspath(out_dir) == HERE else os.path.join(out_dir, "fences.json")
                print(f"wrote {where}; no project, user, organization or host name is recorded; exit {code}")
    return code


if __name__ == "__main__":
    sys.exit(main())
