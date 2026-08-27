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

    def current_org_id(self):
        """Return the bare org UUID of the authenticated session.

        This is the value the tenant-context header wants (the directory group is
        resolved against THIS org). The session's org.id is a URN
        (urn:vcloud:org:<uuid>); the header wants just the <uuid>.
        """
        status, raw, _ = self._request("GET", "/cloudapi/1.0.0/sessions/current",
                                        accept=CLOUDAPI_ACCEPT)
        if status != 200:
            raise VcfaError(f"sessions/current: HTTP {status}")
        org_urn = json.loads(raw).get("org", {}).get("id", "")
        return org_urn.split(":")[-1]  # urn:vcloud:org:<uuid> -> <uuid>

    def find_org_role(self, name):
        """Return the org role dict matching ``name`` (e.g. 'Organization User'), or None."""
        for role in self.cloudapi_list("roles"):
            if role["name"] == name:
                return role
        return None

    def import_ad_group(self, group_name, role_name="Organization User", provider_type="LDAP"):
        """Import a directory group into this organization and assign it an org role.

        ``provider_type`` selects the org's identity source and must be one of
        ``LDAP``, ``SAML``, or ``OAUTH``:
          * LDAP (this lab's Active Directory) - the group is resolved against the
            directory by name.
          * SAML (e.g. Azure AD) - the group is matched against the SAML assertion's
            group claim, and its members are provisioned JUST-IN-TIME on first login
            rather than pre-imported. So for SAML you import the GROUP here and skip
            the per-user import; membership carries users in when they authenticate.
          * OAUTH - an OIDC provider, JIT like SAML.
        The name to pass is the group as the provider presents it: a directory name
        for LDAP, or the group name/id the SAML claim carries (verify which your IdP
        emits - Azure AD can send the display name or the group's object id).

        ``role_name`` is the ORGANIZATION role the group gets - the org-wide "door",
        separate from the project role. Keep it at ``Organization User`` (or a narrow
        custom variant such as the catalogs role) for an isolated tenant: it grants no
        cross-project reach. ``Organization Administrator`` and ``Organization Auditor``
        are org-WIDE and break own-only; ``Defer to Identity Provider`` takes the role
        from the IdP assertion (OIDC/SAML). The real power is the per-project role.

        REQUIRES a session-login token (what this client uses): the group-import
        right is present only on an interactive session login and is stripped from
        OAuth/api-token grants, so those 403. The org comes from the tenant-context
        header; the group resolves by name server-side. Idempotent-ish: re-importing
        an existing group name returns an HTTP error rather than duplicating.
        """
        # OIDC is the friendly name for the OAUTH providerType enum value.
        provider_type = "OAUTH" if str(provider_type).upper() == "OIDC" else provider_type
        if provider_type not in ("LDAP", "SAML", "OAUTH"):
            raise VcfaError(f"provider_type must be LDAP, OIDC (OAUTH), or SAML; got {provider_type!r}")
        role = self.find_org_role(role_name)
        if role is None:
            raise VcfaError(f"org role {role_name!r} not found in this org's roles")
        body = {"name": group_name, "providerType": provider_type,
                "roleEntityRefs": [{"id": role["id"], "name": role["name"]}], "description": ""}
        status, raw, _ = self._request(
            "POST", "/cloudapi/1.0.0/groups",
            accept="application/json;version=10.0.0.0-alpha", body=body,
            tenant_context=self.current_org_id())
        if status not in (200, 201):
            raise VcfaError(f"import AD group {group_name!r}: HTTP {status}: {raw[:200]}")
        return json.loads(raw)

    def import_ad_user(self, user_name, role_name="Organization User", provider_type="LDAP"):
        """Import a single directory user into this organization, with an org role.

        ``provider_type`` is one of ``LOCAL``, ``LDAP``, ``SAML``, or ``OAUTH``. For
        SAML/OAUTH the user is normally provisioned JUST-IN-TIME on first login
        (mapped from the assertion's claims), so pre-importing an individual user is
        usually unnecessary - bind the group and let membership carry them in. This
        method is mainly for LDAP, where a user must already be an org principal
        before you can reference them directly in a project binding (a per-user
        project). Same identity plane as import_ad_group (session-login token,
        tenant-context header) but at /cloudapi/1.0.0/users.
        """
        provider_type = "OAUTH" if str(provider_type).upper() == "OIDC" else provider_type
        if provider_type not in ("LOCAL", "LDAP", "SAML", "OAUTH"):
            raise VcfaError(f"provider_type must be LOCAL, LDAP, OIDC (OAUTH), or SAML; got {provider_type!r}")
        role = self.find_org_role(role_name)
        if role is None:
            raise VcfaError(f"org role {role_name!r} not found in this org's roles")
        # A VcdUser keys the login name as `username` (a group uses `name`).
        body = {"username": user_name, "providerType": provider_type,
                "roleEntityRefs": [{"id": role["id"], "name": role["name"]}]}
        status, raw, _ = self._request(
            "POST", "/cloudapi/1.0.0/users",
            accept="application/json;version=10.0.0.0-alpha", body=body,
            tenant_context=self.current_org_id())
        if status not in (200, 201):
            raise VcfaError(f"import AD user {user_name!r}: HTTP {status}: {raw[:200]}")
        return json.loads(raw)

    def sync_ldap(self):
        """Trigger an LDAP directory sync so this organization picks up newly
        created directory users and groups now, rather than at the next scheduled
        sync. Returns True on success.

        Scope note: this refreshes THIS layer's directory view - enough for a new
        principal to log in and be seen in the org - but the Kubernetes workload
        plane authorizes against a SEPARATE identity provider (the fleet identity
        manager), whose sync is not this call. So immediately after creating a
        brand-new directory user, they may be visible here yet not yet bindable to
        a project or able to operate on the workload plane until that other
        provider syncs (often a short, scheduled interval). Provision users ahead
        of the moment you need to bind them, or expect a brief wait.
        """
        status, raw, _ = self._request("POST", "/cloudapi/1.0.0/ldap/sync",
                                        accept=CLOUDAPI_ACCEPT)
        if status not in (200, 202, 204):
            raise VcfaError(f"ldap sync: HTTP {status}: {raw[:160]}")
        return True

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
        """Create a ProjectRoleBinding: grant a user or group a PROJECT ROLE.

        This is THE authority for project RBAC (the REST membership arrays you may
        find elsewhere are a read-only projection that accepts a write, returns 200,
        and persists nothing - bind here). Users bind by bare name; groups bind by
        "Name@" (the trailing @, which this method adds).

        ``project_role`` is one of four handles - console name -> handle, confirmed
        live against /apis/authorization.cci.vmware.com/v1alpha1/projectroles, each
        the built-in Kubernetes ClusterRole of that name:
          * view     = Project Auditor         read-only across the project; sees
                                               everything, changes nothing.
          * edit     = Project User            the isolation floor: own-only on the
                                               deployment plane, and NO reach onto the
                                               Kubernetes workload plane (a 403) - so
                                               not enough for the services portal.
          * edit_adv = Project Advanced User   the services-portal floor: project-WIDE
                                               read+write across the namespaces (note
                                               the underscore, edit_adv not edit-adv).
                                               Project-wide + no per-user ownership on
                                               the workload plane is why own-only
                                               services needs a project per user.
          * admin    = Project Administrator   edit_adv PLUS manages the project's
                                               namespaces (create/delete) and RBAC -
                                               the tier that lets a user self-serve
                                               their own namespaces.
        """
        valid = ("view", "edit", "edit_adv", "admin")
        if project_role not in valid:
            raise VcfaError(
                f"project_role must be one of {valid}: view=Project Auditor, "
                f"edit=Project User, edit_adv=Project Advanced User, admin=Project "
                f"Administrator. Got {project_role!r}.")
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
