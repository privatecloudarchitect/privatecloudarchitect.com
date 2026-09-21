#!/usr/bin/env python3
"""whoami.py - what the platform says you are, on each plane, and where it says that came from.

Authorization here is not one system, and the hardest part to hold is the derivation: an organization right
becomes a group, a project role mints a second bundle of groups, and Kubernetes-style RBAC then evaluates the
union. This script asks the platform to state that derivation rather than inferring it, read-only:

  1. SelfSubjectReview at the organization gateway   the groups the gateway derived for your bearer
  2. SelfSubjectReview at a namespace's own endpoint  the groups the workload plane derived for the same bearer
  3. the ProjectRole catalog                          the four tiers, as the platform publishes them
  4. ProjectRoleBinding in a project                  the authority: which role each subject kind holds
  5. the project-service arrays                       the projection beside it, for contrast
  6. an access review, asked twice                    once without a namespace or API group, once with both,
                                                      beside a real read, so the difference is visible
  7. SelfSubjectRulesReview at the namespace          everything the plane says you may do there

It writes `derivation.json`: group names (which are product right names, not yours), counts, shapes, and
verdicts. No estate name, endpoint, user, project, or namespace reaches the record, and the script refuses to
write one that does. Stdlib only; no token is printed or written.

Env:  VCFA_HOST, VCFA_ORG, VCFA_REFRESH_TOKEN_FILE; TLS_VERIFY=false on a self-signed lab CA; OUT (derivation.json)
Exit: 0 recorded · 1 a call failed
"""

import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

CCI = "/cci/kubernetes"
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
HEX32 = re.compile(r"\b[0-9a-f]{32}\b")


def ctx():
    verify = os.environ.get("TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")
    return ssl.create_default_context() if verify else ssl._create_unverified_context()


class Api:
    def __init__(self, host, org, refresh):
        self.host = host
        body = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": refresh}).encode()
        req = urllib.request.Request(f"https://{host}/oauth/tenant/{org}/token", data=body, method="POST",
                                     headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
        with urllib.request.urlopen(req, context=ctx(), timeout=30) as r:
            self.bearer = json.loads(r.read())["access_token"]

    def call(self, method, url, body=None):
        h = {"Authorization": f"Bearer {self.bearer}", "Accept": "application/json"}
        if body is not None:
            h["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, context=ctx(), timeout=60) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, raw.decode(errors="replace")[:200]

    def groups_at(self, base):
        st, r = self.call("POST", base + "/apis/authentication.k8s.io/v1/selfsubjectreviews",
                          {"apiVersion": "authentication.k8s.io/v1", "kind": "SelfSubjectReview"})
        if st >= 400:
            return st, [], []
        ui = (r.get("status") or {}).get("userInfo") or {}
        return st, sorted(ui.get("groups") or []), sorted((ui.get("extra") or {}).keys())


def classify(groups):
    """Product-vocabulary groups keep their names; anything estate-shaped is reduced to its shape."""
    rights, system, other = [], [], []
    for g in groups:
        if g.startswith("vcf:"):
            rights.append(g)
        elif g.startswith("system:"):
            system.append(g)
        else:
            shape = re.sub(r"@[A-Za-z0-9.-]+$", "@<realm>", g)          # the realm first: it is hex-shaped too
            shape = UUID.sub("<project-uid>", HEX32.sub("<project-uid>", shape))
            shape = re.sub(r"(?<=-)[a-z0-9-]+(?=@)", "<project>", shape)
            other.append(shape)
    return {"from_rights": rights, "system": system, "plane_scoped": other}


def main():
    host, org = os.environ["VCFA_HOST"], os.environ["VCFA_ORG"]
    refresh = open(os.environ["VCFA_REFRESH_TOKEN_FILE"], encoding="utf-8").read().strip()
    api = Api(host, org, refresh); G = f"https://{host}{CCI}"
    rec = {"captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    print("whoami.py: the derivation, asked of the platform rather than inferred\n")

    # 1. the organization gateway
    st, groups, extra = api.groups_at(G)
    org_cls = classify(groups)
    rec["organization_gateway"] = {"status": st, "groups": len(groups), "extra_claims": extra, **org_cls}
    print(f"  organization gateway: {len(groups)} groups derived "
          f"({len(org_cls['from_rights'])} from rights, {len(org_cls['system'])} system); userInfo extra: {', '.join(extra)}")

    # 2. the project role catalog
    st, roles = api.call("GET", f"{G}/apis/authorization.cci.vmware.com/v1alpha1/projectroles")
    rec["project_roles"] = [{"name": i["metadata"]["name"], "description": (i.get("spec") or {}).get("description")}
                            for i in (roles.get("items") or [])] if st == 200 else f"HTTP {st}"
    print(f"  project roles published: {[r['name'] for r in rec['project_roles']] if st == 200 else st}")

    # 3. the authority and the projection
    st, projects = api.call("GET", f"{G}/apis/project.cci.vmware.com/v1alpha2/projects")
    proj = (projects.get("items") or [{}])[0].get("metadata", {}).get("name") if st == 200 else None
    if not proj:
        print("FATAL: no project is visible to this bearer"); sys.exit(1)
    st, rb = api.call("GET", f"{G}/apis/authorization.cci.vmware.com/v1alpha1/namespaces/{proj}/projectrolebindings")
    bindings = rb.get("items") or []
    rec["authority"] = {"kind": "ProjectRoleBinding", "status": st, "bindings": len(bindings),
                        "by_role": {r: sum(1 for b in bindings if (b.get("roleRef") or {}).get("name") == r)
                                    for r in sorted({(b.get("roleRef") or {}).get("name") for b in bindings if b.get("roleRef")})},
                        "subject_kinds": sorted({s.get("kind") for b in bindings for s in (b.get("subjects") or [])}),
                        "name_shape": "cci:<subject-kind>:<subject>"}
    print(f"  authority: {len(bindings)} ProjectRoleBindings, by role {rec['authority']['by_role']}, subject kinds {rec['authority']['subject_kinds']}")
    st, pr = api.call("GET", f"https://{host}/project-service/api/projects")
    first = ((pr.get("content") or pr.get("items") or [{}])[0]) if st == 200 else {}
    arrays = {k: len(first.get(k) or []) for k in ("administrators", "members", "viewers", "supervisors") if k in first}
    rec["projection"] = {"surface": "project-service REST arrays", "status": st, "arrays_present": sorted(arrays),
                         "note": "accepts a write, returns 200, persists nothing; it mirrors the project's admin group"}
    print(f"  projection: project-service arrays present {sorted(arrays)}")

    # 4. the workload plane, same bearer
    st, nss = api.call("GET", f"{G}/apis/infrastructure.cci.vmware.com/v1alpha3/namespaces/{proj}/supervisornamespaces")
    items = [n for n in (nss.get("items") or []) if (n.get("status") or {}).get("namespaceEndpointURL")]
    if not items:
        rec["workload_plane"] = {"status": "no namespace with a published endpoint"}
        print("  workload plane: no namespace has a published endpoint yet")
    else:
        n0 = items[0]; ep = n0["status"]["namespaceEndpointURL"].rstrip("/"); sup = n0["metadata"]["name"]
        st, wgroups, wextra = api.groups_at(ep)
        w_cls = classify(wgroups)
        rec["workload_plane"] = {"status": st, "groups": len(wgroups), "endpoint_shape": "/proxy/k8s/namespaces/urn:vcloud:namespace:<uuid>", **w_cls}
        print(f"  workload plane:       {len(wgroups)} groups derived for the same bearer "
              f"({len(w_cls['from_rights'])} from rights, {len(w_cls['plane_scoped'])} plane-scoped)")
        for g in w_cls["plane_scoped"]:
            print(f"      {g}")
        # 5. the same question asked twice, beside the real read
        probes = []
        for verb, group, res in (("list", "vmoperator.vmware.com", "virtualmachines"), ("create", "vmoperator.vmware.com", "virtualmachines"),
                                 ("delete", "vmoperator.vmware.com", "virtualmachines"), ("create", "", "secrets"), ("create", "", "namespaces")):
            bare = {"spec": {"resourceAttributes": {"verb": verb, "resource": res}}}
            full = {"spec": {"resourceAttributes": {"namespace": sup, "verb": verb, "group": group, "resource": res}}}
            out = {"verb": verb, "apiGroup": group or "core", "resource": res}
            for label, spec in (("without_scope", bare), ("with_scope", full)):
                st2, r2 = api.call("POST", ep + "/apis/authorization.k8s.io/v1/selfsubjectaccessreviews",
                                   {"apiVersion": "authorization.k8s.io/v1", "kind": "SelfSubjectAccessReview", **spec})
                s = (r2.get("status") or {}) if st2 < 400 else {}
                out[label] = s.get("allowed")
                if label == "with_scope" and s.get("reason"):
                    out["reason_shape"] = re.sub(r'"[^"]*"', '"<binding>"', str(s["reason"]))
            probes.append(out)
        rec["access_reviews"] = probes
        print("\n  the same question, asked two ways (an access review is about RBAC wiring, not enforcement):")
        print(f"      {'verb':<7}{'apiGroup':<24}{'resource':<16}{'no scope':<10}{'with scope'}")
        for p in probes:
            print(f"      {p['verb']:<7}{p['apiGroup']:<24}{p['resource']:<16}{str(p['without_scope']):<10}{p['with_scope']}")
        reads = {}
        for label, path in (("virtualmachines", f"/apis/vmoperator.vmware.com/v1alpha5/namespaces/{sup}/virtualmachines"),
                            ("secrets", f"/api/v1/namespaces/{sup}/secrets")):
            st2, _ = api.call("GET", ep + path); reads[label] = st2
        rec["real_reads"] = reads
        print(f"  real reads for comparison: {reads}")
        st, rules = api.call("POST", ep + "/apis/authorization.k8s.io/v1/selfsubjectrulesreviews",
                             {"apiVersion": "authorization.k8s.io/v1", "kind": "SelfSubjectRulesReview", "spec": {"namespace": sup}})
        n_rules = len((rules.get("status") or {}).get("resourceRules") or []) if st < 400 else None
        rec["rules_review"] = {"status": st, "resource_rules": n_rules}
        print(f"  SelfSubjectRulesReview: {n_rules} resource rules in that one namespace")

    # 5b. the third surface, which is not a tier of the first two
    #
    # The four dials govern the deployment plane and the project role tier governs the workload plane. There
    # is a third plane underneath both, and no dial reaches it, because it does not authenticate the same
    # principals: vCenter answers to vSphere SSO, and the bearer this whole script holds is not one of those.
    # Proving that needs NO vCenter credential, which is the point: the probe presents the credential it
    # already has and records the refusal.
    vc = os.environ.get("VC_HOST")
    if vc:
        answers = {}
        for label, hdrs in (("as a bearer token", {"Authorization": f"Bearer {api.bearer}"}),
                            ("as a vCenter session id", {"vmware-api-session-id": api.bearer}),
                            ("with no credential", {})):
            try:
                req = urllib.request.Request(f"https://{vc}/api/vcenter/vm", headers=hdrs)
                with urllib.request.urlopen(req, context=ctx(), timeout=45) as r:
                    answers[label] = r.status
            except urllib.error.HTTPError as e:
                answers[label] = e.code
            except Exception:
                answers[label] = None
        rec["third_surface"] = {
            "plane": "vCenter",
            "governedBy": "vSphere SSO principals and permissions on inventory objects",
            "reachedByAnyProjectRole": False,
            "tenantBearerAnswers": answers,
            "note": "the same bearer reads its own plane in this run; these codes are the platform declining "
                    "a credential from a different identity domain, not a role that is too narrow"}
        codes = ", ".join(f"{k}: {v}" for k, v in answers.items())
        print(f"  third surface (vCenter): the bearer that works above answers {codes} here")
    else:
        rec["third_surface"] = {"plane": "vCenter", "probed": False,
                                "note": "set VC_HOST to record what this identity answers there"}
        print("  third surface (vCenter): not probed (set VC_HOST)")

    # 6. write, refusing anything estate-shaped
    text = json.dumps(rec, indent=1, ensure_ascii=False)
    for secret in (api.bearer, refresh, host, org, proj):
        if secret and secret in text:
            raise SystemExit(f"FATAL: an estate value ({len(secret)} characters) reached the record; not writing it")
    if UUID.search(text) or HEX32.search(text):
        raise SystemExit("FATAL: an identifier reached the record; not writing it")
    out = os.environ.get("OUT", "derivation.json")
    open(out, "w", encoding="utf-8").write(text + "\n")
    print(f"\nwrote {out}: the derivation as the platform states it, group names are product rights, nothing estate-shaped")


if __name__ == "__main__":
    main()
