#!/usr/bin/env python3
"""vcfa.py: a minimal, teaching VCF Automation 9.1 API client.

This one file is the API fundamentals for the whole solution. Read it top to
bottom once and you will understand how every other script authenticates and
talks to the platform. It is standard-library only (no pip installs), so it runs
anywhere Python 3.9+ runs.

The two things a newcomer to the VCFA API must internalize are both here:

  1. THE TOKEN COMES BACK IN A RESPONSE HEADER, NOT THE BODY.
     You log in with HTTP Basic auth to POST /cloudapi/1.0.0/sessions, and the
     bearer token you use for everything after is the value of the
     X-VMWARE-VCLOUD-ACCESS-TOKEN response header. The body is metadata.

  2. THERE ARE TWO API SURFACES, AND THEY SPEAK DIFFERENTLY.
     - cloudapi (VCD lineage): /cloudapi/1.0.0/...  needs a versioned Accept
       header (application/json;version=9.1.0). This is where roles, rights,
       users, groups, and sessions live.
     - CCI (the Cloud Consumption Interface): /cci/kubernetes/apis/...  is a
       Kubernetes-style API. Projects, ProjectRoleBindings, and Supervisor
       Namespaces are Kubernetes objects here. Plain application/json.

Configuration is by environment variable so nothing secret is ever hard-coded:

  VCFA_HOST       the appliance FQDN, e.g. vcfa.example.com   (required)
  VCFA_ORG        the tenant organization name                 (required)
  VCFA_USER       the account to act as                        (required)
  VCFA_PASSWORD   that account's password                      (required; source
                  it from a secret store, never inline in a shell history)
  VCFA_INSECURE   set to 1 to skip TLS verification for a self-signed lab CA

Nothing here is specific to any one estate. Fill the four required variables and
it talks to your appliance.
"""
from __future__ import annotations

import base64
import http.client
import json
import os
import ssl
import urllib.error
import urllib.request

# The /cloudapi/1.0.0/rights endpoints emit one Link header per relation, far
# past http.client's default 100-header cap. Lift it so a rights read does not
# raise "got more than 100 headers". Harmless for every other call.
http.client._MAXHEADERS = 10000

CLOUDAPI_ACCEPT = "application/json;version=9.1.0"


class VcfaError(RuntimeError):
    """Raised when the platform returns a non-2xx we did not expect."""


class Vcfa:
    """A thin session against one VCF Automation organization.

    Construct it, and it logs in immediately and holds the bearer token. Every
    method below is a small wrapper over one HTTP call, so you can see exactly
    what wire request each platform operation is.
    """

    def __init__(self, host=None, org=None, user=None, password=None, insecure=None):
        self.host = host or _require("VCFA_HOST")
        self.org = org or _require("VCFA_ORG")
        user = user or _require("VCFA_USER")
        password = password or _require("VCFA_PASSWORD")
        self._insecure = insecure if insecure is not None else os.environ.get("VCFA_INSECURE") == "1"
        self.token = self._session_login(user, password)

    # -- transport -------------------------------------------------------------
    def _ctx(self):
        ctx = ssl.create_default_context()
        if self._insecure:
            # A lab appliance usually presents a self-signed certificate. In
            # production, trust the real CA instead of turning verification off.
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        return ctx

    def _request(self, method, path, *, accept="application/json", body=None, basic=None,
                 content_type="application/json", tenant_context=None):
        headers = {"Accept": accept}
        if basic:
            headers["Authorization"] = "Basic " + basic
        elif getattr(self, "token", None):
            headers["Authorization"] = "Bearer " + self.token
        if tenant_context:
            headers["X-VMWARE-VCLOUD-TENANT-CONTEXT"] = tenant_context
        data = None
        if body is not None:
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            headers["Content-Type"] = content_type
        req = urllib.request.Request(f"https://{self.host}{path}", data=data, method=method,
                                     headers=headers)
        try:
            with urllib.request.urlopen(req, context=self._ctx(), timeout=90) as resp:
                # Lowercase the header keys: HTTP headers are case-insensitive, and
                # the token header can come back in a different case than we ask for.
                return resp.status, resp.read().decode(), {k.lower(): v for k, v in resp.headers.items()}
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode(), {k.lower(): v for k, v in e.headers.items()}

    # -- authentication --------------------------------------------------------
    def _session_login(self, user, password):
        """Basic-auth session login. Returns the bearer token from the header.

        Why session login and not an OAuth API token? Both work for reads and
        for the calls in this solution. But identity-management rights (importing
        AD groups and users) are present ONLY on an interactive session login and
        are stripped from OAuth grants. Using the session login throughout means
        the same token can also onboard identities when you need it to.
        """
        basic = base64.b64encode(f"{user}@{self.org}:{password}".encode()).decode()
        status, raw, headers = self._request("POST", "/cloudapi/1.0.0/sessions",
                                             accept=CLOUDAPI_ACCEPT, basic=basic)
        if status != 200:
            raise VcfaError(f"session login failed: HTTP {status}: {raw[:200]}")
        # The token is the header value, not the body. This is the single most
        # common newcomer stumble against this API. (Header keys are lowercased
        # in _request because HTTP headers are case-insensitive.)
        token = headers.get("x-vmware-vcloud-access-token")
        if not token:
            raise VcfaError("session login returned no X-VMWARE-VCLOUD-ACCESS-TOKEN header")
        return token

    def whoami(self):
        """Return the current session's username and roles (a good first read)."""
        status, raw, _ = self._request("GET", "/cloudapi/1.0.0/sessions/current",
                                        accept=CLOUDAPI_ACCEPT)
        if status != 200:
            raise VcfaError(f"sessions/current: HTTP {status}")
        body = json.loads(raw)
        return {"user": body.get("user", {}).get("name"),
                "org": body.get("org", {}).get("name"),
                "roles": body.get("roles", [])}

    # -- cloudapi (roles, rights, users, groups) -------------------------------
    def cloudapi_list(self, resource):
        """Page a cloudapi list endpoint fully. pageSize caps at 128, so paginate."""
        out, page = [], 1
        while True:
            sep = "&" if "?" in resource else "?"
            status, raw, _ = self._request(
                "GET", f"/cloudapi/1.0.0/{resource}{sep}page={page}&pageSize=128",
                accept=CLOUDAPI_ACCEPT)
            if status != 200:
                raise VcfaError(f"list {resource}: HTTP {status}: {raw[:160]}")
            body = json.loads(raw)
            out.extend(body.get("values", []))
            if len(out) >= body.get("resultTotal", len(out)) or not body.get("values"):
                return out
            page += 1

    def create_role(self, name, description, rights_names):
        """Create a custom organization role and set its rights.

        Rights have an implied-closure graph: the platform rejects a set that is
        missing an implied right and NAMES the one it wants, so we iterate until
        the set is closed. This is how the namespace-catalogs role is built.
        """
        existing = {r["name"]: r["id"] for r in self.cloudapi_list("roles")}
        if name in existing:
            role_id = existing[name]
        else:
            status, raw, _ = self._request(
                "POST", "/cloudapi/1.0.0/roles", accept=CLOUDAPI_ACCEPT,
                body={"name": name, "description": description,
                      "bundleKey": "com.vmware.vcloud.undefined.key", "readOnly": False})
            if status not in (200, 201):
                raise VcfaError(f"create role: HTTP {status}: {raw[:200]}")
            role_id = json.loads(raw)["id"]
        catalog = {r["name"]: r for r in self.cloudapi_list("rights")}
        want = list(rights_names)
        import re
        for _ in range(8):
            missing = [n for n in want if n not in catalog]
            if missing:
                raise VcfaError(f"rights not in this org's catalog: {missing}")
            refs = [{"name": n, "id": catalog[n]["id"]} for n in want]
            status, raw, _ = self._request(
                "PUT", f"/cloudapi/1.0.0/roles/{role_id}/rights",
                accept=CLOUDAPI_ACCEPT, body={"values": refs})
            if status in (200, 201, 204):
                return role_id
            m = re.search(r"implied rights are missing: (.+?)\"", raw)
            if status == 400 and m:
                want += [x.strip() for x in m.group(1).split(",") if x.strip() not in want]
                continue
            raise VcfaError(f"set role rights: HTTP {status}: {raw[:200]}")
        raise VcfaError("role rights did not converge after 8 closure passes")

    # -- CCI (projects, bindings, namespaces) ----------------------------------
    def cci(self, method, path, body=None, content_type="application/json"):
        """One call against the CCI Kubernetes-style API under /cci/kubernetes."""
        return self._request(method, f"/cci/kubernetes{path}", body=body,
                             content_type=content_type)

    def create_project(self, name, description=""):
        status, raw, _ = self.cci(
            "POST", "/apis/project.cci.vmware.com/v1alpha2/projects",
            body={"apiVersion": "project.cci.vmware.com/v1alpha2", "kind": "Project",
                  "metadata": {"name": name}, "spec": {"description": description}})
        if status not in (200, 201):
            raise VcfaError(f"create project {name}: HTTP {status}: {raw[:200]}")
        return json.loads(raw)

    def bind_role(self, project, subject_kind, subject_name, project_role):
        """Create a ProjectRoleBinding: grant a user or group a project role.

        This is THE authority for project RBAC. The REST membership arrays you
        may find elsewhere are a read-only projection that accepts a write,
        returns 200, and persists nothing. Bind here.
        Users bind by bare name; groups bind by "Name@" (note the trailing @).
        """
        subject = {"kind": subject_kind,
                   "name": f"{subject_name}@" if subject_kind == "Group" else subject_name}
        bname = f"cci:{subject_kind.lower()}:{subject_name}"
        status, raw, _ = self.cci(
            "POST",
            f"/apis/authorization.cci.vmware.com/v1alpha1/namespaces/{project}/projectrolebindings",
            body={"apiVersion": "authorization.cci.vmware.com/v1alpha1", "kind": "ProjectRoleBinding",
                  "metadata": {"name": bname, "namespace": project},
                  "roleRef": {"apiGroup": "authorization.cci.vmware.com", "kind": "ProjectRole",
                              "name": project_role},
                  "subjects": [subject]})
        if status not in (200, 201):
            raise VcfaError(f"bind {bname} -> {project_role} in {project}: HTTP {status}: {raw[:200]}")
        return json.loads(raw)

    def create_namespace(self, project, generate_name, region, vpc=None, seg=None, zone=None,
                         class_name="large", cpu_limit="2000M", memory_limit="4000Mi"):
        """Create the project's first Supervisor Namespace, fully by API.

        Only two spec fields are REQUIRED by the SupervisorNamespace CRD
        (v1alpha3): className and regionName. Everything else is optional and
        depends on how your supervisor is networked - so this builds the spec
        incrementally and includes an optional field only when you pass it:
          * generateName, NOT a fixed metadata.name. The platform derives the
            name and appends a suffix; a fixed name is rejected. (Always.)
          * segName, the load-balancer service engine group, is required at
            RUNTIME only when the region load-balances through NSX Advanced Load
            Balancer (Avi) - the backend then rejects the create with "SEG is
            required". A supervisor without NSX ALB service engine groups omits
            it. Read it (and vpcName, and a zone) from a namespace that works:
            GET .../namespaces/<project>/supervisornamespaces/<name>, copy spec.
          * vpcName and classConfigOverrides.zones are likewise optional; omit
            zones to inherit the namespace class's default limits.
        Returns the created object; poll status.phase until it reads "Created".
        """
        stem = generate_name if generate_name.endswith("-") else generate_name + "-"
        spec = {"className": class_name, "regionName": region}
        if vpc:
            spec["vpcName"] = vpc
        if seg:
            spec["segName"] = seg
        if zone:
            spec["classConfigOverrides"] = {"zones": [{
                "name": zone, "cpuLimit": cpu_limit, "cpuReservation": "0M",
                "memoryLimit": memory_limit, "memoryReservation": "0Mi",
                "vmClassReservations": []}]}
        status, raw, _ = self.cci(
            "POST",
            f"/apis/infrastructure.cci.vmware.com/v1alpha3/namespaces/{project}/supervisornamespaces",
            body={"apiVersion": "infrastructure.cci.vmware.com/v1alpha3", "kind": "SupervisorNamespace",
                  "metadata": {"generateName": stem, "namespace": project},
                  "spec": spec})
        if status not in (200, 201):
            raise VcfaError(f"create namespace in {project}: HTTP {status}: {raw[:300]}")
        return json.loads(raw)

    def get_namespace(self, project, name):
        status, raw, _ = self.cci(
            "GET",
            f"/apis/infrastructure.cci.vmware.com/v1alpha3/namespaces/{project}/supervisornamespaces/{name}")
        return (json.loads(raw) if status == 200 else None)

    def list_projects(self):
        status, raw, _ = self.cci("GET", "/apis/project.cci.vmware.com/v1alpha2/projects")
        if status != 200:
            raise VcfaError(f"list projects: HTTP {status}")
        return [i["metadata"]["name"] for i in json.loads(raw).get("items", [])]


def _require(var):
    val = os.environ.get(var)
    if not val:
        raise SystemExit(f"set the {var} environment variable (see the header of vcfa.py)")
    return val


if __name__ == "__main__":
    # Smoke test: log in and print who you are. This is your first API call.
    v = Vcfa()
    who = v.whoami()
    print(f"logged in to {v.host} as {who['user']} in org {who['org']}; roles: {who['roles']}")
    print(f"projects you can see: {v.list_projects()}")
