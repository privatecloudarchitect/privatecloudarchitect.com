#!/usr/bin/env python3
"""request_catalog_item.py: request a catalog item by API in a VCF Automation 9.1.1 VM Apps organization, and read,
beside each step, what an Aria Automation 8.18 script did at the same step.

A script that requested catalog items from Aria Automation 8.18 keeps its request: POST /catalog/api/items/{id}/request,
with the same body. What it cannot keep is its sign-in. 8.18 sent a username and password to the Identity Service
for a refresh token, then traded that token at /iaas/api/login for a bearer. Broadcom's 9.1 VM Apps programming guide
says the Identity Service API is no longer used to obtain a refresh token programmatically, and on 9.1.1 this handbook
measured both 8.18 calls refused: the login answered 404, and /iaas/api/login refused a 9.1 API token with
invalid_grant. This script signs in the 9.1.1 way, makes the request the way the 9.1 guide makes it, and prints the
8.18 form of each step, so a migration can be read off its output.

   1 sign in        the organization's API token, exchanged for a one-hour bearer; or a session as user@org
   2 organization   a VM Apps organization answers /iaas/api/projects; an All Apps one refuses it with 403
   3 project        found by name
   4 catalog item   found by name among the items shared to the project
   7 name           a deployment of this name already in the project means the request was sent: never twice
   5 version        the one you name, or the newest released; none for an item that is not versioned
   6 inputs         held to that version's own input schema: none required left out, none it does not declare
   8 request        POST /catalog/api/items/{id}/request?apiVersion=2020-08-25        (with --execute only)
   9 wait           the deployment's status and its request's, until one of them ends  (with --execute only)
  10 sign out       the bearer's session closed, however the bearer was made

Step 7 runs before 5 and 6: once the name exists, the request was sent, and the run reports or waits on it without
needing the inputs again. Without --execute nothing is written: it signs in, checks, prints the request it would send
(an input the schema marks encrypted, or whose name says it is a secret, is shown as hidden, never its value), and
signs out. With --execute it sends the
request once. Run it again with the same name and it finds the deployment and waits on it or reports it, sending
nothing; a CATALOG_VERSION or input given that differs from what that deployment was made with stops it (exit 4).
After a request with no clear answer (none, a 5xx, or a 2xx without a deployment id) it lists by name for a minute
before saying anything; it never says nothing was made.

--delete removes the named deployment: only one this catalog item made, only one owned by the signed-in user (unless
--any-owner), and only with --execute. Without --execute it prints the owner and creator and what it would remove.

Sign-in to VCF Automation, one of:
  VCFA_API_TOKEN_FILE   the organization's API token, in a file of mode 0600. Make one in the VCF Automation UI, in the
                        organization: the tenant's name ▸ My Account (under User Settings) ▸ API Tokens ▸ New. Broadcom's
                        guide asks for the Assembler Administrator or Service Broker Administrator role. It lasts 90
                        days unless your administrator changed the lifetime. VCFA_API_TOKEN, the value itself, also
                        works and lands in the shell's history.
  VCFA_USER and VCFA_PASSWORD_FILE   a session as user@org, the password from a file of mode 0600 (or VCFA_PASSWORD).
A credential or inputs file that is missing, unreadable or open to group or other is refused before anything is sent.

The request:
  VCFA_HOST             the VCF Automation FQDN; a redirect from it is refused, never followed, so the credential
                        goes to this host only
  VCFA_ORG              the organization's Name in Provider Management (Organizations ▸ yours ▸ Overview), not its
                        display name
  CATALOG_PROJECT       the project's name
  CATALOG_ITEM          the catalog item's name
  DEPLOYMENT_NAME       the deployment's name; the key that keeps the request from being sent twice
  CATALOG_VERSION       optional: a released version; the newest when unset
  CATALOG_INPUTS_FILE   optional: a JSON object of the item's inputs, in a file of mode 0600 (an input may be a
                        password); the platform fills each default you leave out
  CATALOG_WAIT_SECONDS  optional: how long --execute waits for the deployment to end, and --delete --execute for it
                        to go (default 1200)
  TLS_VERIFY=false      only on a self-signed lab CA

Run:
  python3 request_catalog_item.py                     # read-only: sign in, check, print the request, sign out
  python3 request_catalog_item.py --execute           # send it once and wait for the deployment
  python3 request_catalog_item.py --delete            # what deleting DEPLOYMENT_NAME would remove, and whose it is
  python3 request_catalog_item.py --delete --execute  # remove it, if this catalog item made it and it is yours
  python3 request_catalog_item.py --delete --execute --any-owner   # remove it whoever owns it

Exit: 0 the plan printed, or the deployment exists and was created (an UPDATE_ status included), or it was deleted;
2 a call failed, a sign-in was refused, the request was refused, a redirect was refused, or a check before the request
failed; 3 the deployment exists and is not created: it failed, a policy rejected or holds it, it is being removed or
was removed while waiting, the bearer ended during the wait, or the wait ended first (run again: it finds the
deployment and waits, sending nothing), or a delete did not finish; 4 the name belongs to more than one deployment,
to one from another catalog item, to one made with another version or other inputs, or (for --delete) to one owned
by someone else; 5 an unknown argument, a missing variable, or a credential or inputs file refused; 6 the request had
no clear answer and no deployment of that name was visible after a minute (it may still be in flight: wait before
running again).
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

API_VERSION = "2020-08-25"  # the catalog and deployment API version Broadcom's 9.1 VM Apps guide names
CLOUDAPI = "application/json;version=40.0"  # the session sign-in and sign-out take a versioned Accept
CREATED = {"CREATE_SUCCESSFUL", "UPDATE_SUCCESSFUL", "UPDATE_INPROGRESS", "UPDATE_FAILED"}
REQUEST_STOPPED = {"FAILED", "ABORTED", "APPROVAL_REJECTED"}
REQUEST_HELD = {"APPROVAL_PENDING", "USER_INTERACTION_PENDING"}
REASON = "requested by request_catalog_item.py"
HIDDEN = "<encrypted input, not shown>"
FLAGS = ("--execute", "--delete", "--any-owner")
LIST_AFTER_SILENCE = 60  # seconds a request with no clear answer is followed by a list by name
# An input whose name says it is a secret is hidden whatever its schema says: the mask must not rest on one flag alone.
SECRET_NAME = re.compile(r"passw(or)?d|pwd|secret|token|private[ _-]?key", re.IGNORECASE)

# What the 8.18 script did at each step (Broadcom's Aria Automation 8.18 API Programming Guide: "Get Your Access Token
# for the VMware Aria Automation API" and "Request Deployment").
WAS_818 = {
    1: "8.18: POST /csp/gateway/am/api/login?access_token {username, password} gave a refresh token (90 days, and\n"
       "      'You cannot revoke the refresh token'), then POST /iaas/api/login {refreshToken} gave the bearer.",
    2: "8.18: one kind of organization, so nothing to tell apart.",
    3: "8.18: the same project.",
    4: "8.18: the same catalog item, read the same way.",
    5: "8.18: the same list, GET /catalog/api/items/{id}/versions.",
    6: "8.18: the guide sends its inputs without reading the schema first.",
    7: "8.18: the same check, the guide's own step: GET /deployment/api/deployments?name=",
    8: "8.18: the same POST and body, without ?apiVersion=. Both guides print the answer as one object; the catalog\n"
       "      API describes an array, and this script reads either.",
    9: "8.18: the same GET /deployment/api/deployments/{id}.",
    10: "8.18: the guide gives no sign-out call; it says the access token 'times out' after 25 minutes of inactivity,\n"
        "      and 'You can revoke an access token at any time.'",
}


class Stop(Exception):
    """End the run with an exit code and a sentence; the sign-out still runs."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse every redirect. urllib's default handler re-sends the request headers, Authorization among them, to the
    new address, whatever its host or scheme; returning None makes the 3xx the answer instead."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def ctx():
    verify = os.environ.get("TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")
    return ssl.create_default_context() if verify else ssl._create_unverified_context()


def private_file(name, path):
    """The text of a file the run was given, refused (exit 5, before anything is sent) when it is missing, unreadable,
    empty or open to group or other; the refusal names the variable and the fix, never the file's content."""
    try:
        with open(path, encoding="utf-8") as f:
            mode = os.fstat(f.fileno()).st_mode & 0o777
            # Windows makes the mode from the read-only flag alone, so it has no group or other bits to judge.
            if mode & 0o077 and os.name != "nt":
                raise Stop(5, f"{name} names a file of mode {mode:04o}, open to group or other: "
                              f'run chmod 600 "${name}" and try again (the file was not read)')
            value = f.read()
    except OSError as ex:
        raise Stop(5, f"{name} could not be read: {ex.strerror or ex}") from None
    if not value.strip():
        raise Stop(5, f"{name} names an empty file")
    return value


def secret(name):
    """A secret from NAME_FILE (mode 0600, its value stripped) or else NAME itself; None when neither is set."""
    path = os.environ.get(f"{name}_FILE")
    if path:
        return private_file(f"{name}_FILE", path).strip()
    return os.environ.get(name) or None


def need(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise Stop(5, f"{name} is not set; see the variables at the top of this script")
    return value


def detail(body):
    """The platform's own words for a refusal, in one line."""
    if isinstance(body, dict):
        for k in ("error_description", "message", "detail", "error"):
            if body.get(k):
                return " ".join(str(body[k]).split())[:300]
    if isinstance(body, list) and body and isinstance(body[0], dict):
        return detail(body[0])
    return ""


class Vcfa:
    """One VCF Automation host, the bearer this run holds for it, and who the bearer is."""

    def __init__(self, host):
        self.host = host
        self.bearer = None
        self.how = None
        self.user = None
        self._opener = None

    def _send(self, req, timeout):
        """The network seam: (status, body bytes, headers), or (None, b"", {}) when nothing usable answered."""
        if self._opener is None:
            self._opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx()), _NoRedirect())
        try:
            with self._opener.open(req, timeout=timeout) as r:
                return r.status, r.read(), dict(r.headers)
        except urllib.error.HTTPError as ex:
            return ex.code, ex.read(), dict(ex.headers or {})
        except (urllib.error.URLError, http.client.HTTPException, OSError):
            return None, b"", {}

    def call(self, method, path, params=None, body=None, form=None, accept="application/json", auth=True, basic=None,
             timeout=60):
        url = f"https://{self.host}{path}"
        if params:
            url += ("&" if "?" in path else "?") + urllib.parse.urlencode(params)
        headers = {"Accept": accept}
        data = None
        if body is not None:
            data, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
        elif form is not None:
            data, headers["Content-Type"] = urllib.parse.urlencode(form).encode(), "application/x-www-form-urlencoded"
        if basic:
            headers["Authorization"] = f"Basic {basic}"
        elif auth and self.bearer:
            headers["Authorization"] = f"Bearer {self.bearer}"
        status, raw, resp_headers = self._send(urllib.request.Request(url, data=data, method=method, headers=headers),
                                               timeout)
        resp_headers = {k.lower(): v for k, v in resp_headers.items()}
        if status is not None and 300 <= status < 400:
            where = urllib.parse.urlsplit(resp_headers.get("location", "")).netloc or "an address it did not name"
            raise Stop(2, f"{method} {path} answered {status}, a redirect to {where}. It was not followed and the "
                          "credential was not sent on; set VCFA_HOST to the host that answers")
        try:
            parsed = json.loads(raw) if raw else None
        except ValueError:
            parsed = None
        return status, parsed, resp_headers


def say(step, text, was=True):
    label = f"{step:>2} " if step else "   "
    lines = str(text).split("\n")
    print(f"{label}{lines[0]}")
    for line in lines[1:]:
        print(f"   {line}")
    if was and step in WAS_818:
        for line in WAS_818[step].split("\n"):
            print(f"   {line}")


# --------------------------------------------------------------------------- 1 and 10: in and out

def sign_in(v, org, token=None, user=None, password=None):
    """A bearer from the organization's API token (Broadcom's documented way for a VM Apps organization) or from a
    session as user@org, and the name it signs in as. A refusal ends the run with the reason and what to do."""
    if token:
        path = f"/tm/oauth/tenant/{urllib.parse.quote(org, safe='')}/token"
        st, body, _ = v.call("POST", path, form={"grant_type": "refresh_token", "refresh_token": token}, auth=False)
        if st == 200 and isinstance(body, dict) and body.get("access_token"):
            v.bearer, v.how = body["access_token"], "API token"
            said = f"API token, exchanged at /tm/oauth/tenant/{org}/token: a bearer for {body.get('expires_in', '?')} s"
        elif st == 400 and isinstance(body, dict) and body.get("error") == "invalid_grant":
            raise Stop(2, "the API token was refused (invalid_grant): it was revoked, it is past its lifetime (90 days "
                          "unless your administrator changed it), or it was made in another organization. Make a new "
                          "one in this organization: the tenant's name ▸ My Account ▸ API Tokens ▸ New")
        else:
            raise Stop(2, f"the token exchange answered {st or 'nothing'}: {detail(body)}")
    else:
        basic = base64.b64encode(f"{user.split('@')[0]}@{org}:{password}".encode()).decode()
        st, body, headers = v.call("POST", "/cloudapi/1.0.0/sessions", accept=CLOUDAPI, basic=basic)
        if st == 200 and headers.get("x-vmware-vcloud-access-token"):
            v.bearer, v.how = headers["x-vmware-vcloud-access-token"], "session"
            said = f"session as {user.split('@')[0]}@{org}"
        elif st == 401:
            raise Stop(2, f"the session sign-in was refused (401) for {user.split('@')[0]}@{org}: check the account, "
                          "its password, and that VCFA_ORG is the organization's Name in Provider Management")
        else:
            raise Stop(2, f"the session sign-in answered {st or 'nothing'}: {detail(body)}")
    st, cur, _ = v.call("GET", "/cloudapi/1.0.0/sessions/current", accept=CLOUDAPI)
    v.user = ((cur or {}).get("user") or {}).get("name") if st == 200 and isinstance(cur, dict) else None
    return said + (f"; signed in as {v.user}" if v.user else "")


def sign_out(v):
    """Close the bearer's session. Both kinds of bearer are sessions; the call takes a versioned Accept. Returns the
    line to print, or None when there was no bearer."""
    if not v.bearer:
        return None
    st, _, _ = v.call("DELETE", "/cloudapi/1.0.0/sessions/current", accept=CLOUDAPI)
    v.bearer = None
    if st is not None and 200 <= st < 300:
        return f"DELETE /cloudapi/1.0.0/sessions/current: {st}"
    return (f"DELETE /cloudapi/1.0.0/sessions/current answered {st or 'nothing'}: the session may stay open until its "
            "bearer expires, an hour after it was made")


# --------------------------------------------------------------------------- 2 to 7: the checks

def organization_type(v):
    st, body, _ = v.call("GET", "/iaas/api/projects", params={"$top": "1"})
    if st == 200:
        return "VM Apps: /iaas/api/projects answered 200"
    if st == 403:
        raise Stop(2, "this organization refused /iaas/api/projects with 403: it is All Apps, where a template is "
                      "requested through a project's catalog in the same way but placed in a namespace. This script "
                      "is the VM Apps branch's; the series' catalog way is in ../README.md")
    raise Stop(2, f"GET /iaas/api/projects answered {st or 'nothing'}: {detail(body)}")


def find_project(v, name):
    found, skip = [], 0
    while True:
        st, body, _ = v.call("GET", "/iaas/api/projects", params={"$top": "200", "$skip": str(skip)})
        if st != 200 or not isinstance(body, dict):
            raise Stop(2, f"GET /iaas/api/projects answered {st or 'nothing'}: {detail(body)}")
        rows = body.get("content") or []
        found += [p for p in rows if p.get("name") == name]
        skip += len(rows)
        if not rows or skip >= int(body.get("totalElements") or 0):
            break
    if len(found) != 1:
        raise Stop(2, f"{len(found)} projects are named {name!r}; CATALOG_PROJECT must name exactly one you can see")
    return found[0]["id"]


def pages(v, path, params):
    """Every row of a paged catalog or deployment list; a list that fails ends the run."""
    out, number = [], 0
    while True:
        st, body, _ = v.call("GET", path, params={**params, "size": "200", "page": str(number)})
        if st != 200 or not isinstance(body, dict):
            raise Stop(2, f"GET {path} answered {st or 'nothing'}: {detail(body)}")
        out += body.get("content") or []
        number += 1
        if body.get("last", True) or number >= int(body.get("totalPages") or 0):
            return out


def find_item(v, project_id, name):
    rows = [i for i in pages(v, "/catalog/api/items", {"projects": project_id, "search": name}) if i.get("name") == name]
    if len(rows) != 1:
        raise Stop(2, f"{len(rows)} catalog items shared to the project are named {name!r}; CATALOG_ITEM must name one")
    item = rows[0]
    if item.get("isRequestable") is False:
        raise Stop(2, f"the catalog item {name!r} is not requestable")
    return item


def pick_version(versions, wanted=None):
    """The version named, which must be released to the item, or the newest by its creation time."""
    if not versions:
        raise Stop(2, "the catalog item has no released version")
    if wanted:
        for ver in versions:
            if ver.get("id") == wanted:
                return ver
        raise Stop(2, f"version {wanted!r} is not among the released ones: " + ", ".join(v_.get("id", "?") for v_ in versions))
    return max(versions, key=lambda ver: ver.get("createdAt") or "")


def version_schema(v, item_id, version):
    st, body, _ = v.call("GET", f"/catalog/api/items/{item_id}/versions/{urllib.parse.quote(version, safe='')}")
    if st != 200 or not isinstance(body, dict):
        raise Stop(2, f"GET the schema of version {version!r} answered {st or 'nothing'}")
    return body.get("schema") or {}


def encrypted_names(schema, names=()):
    """The inputs never to print: those the schema marks encrypted (9.1.1's catalog marked every secret input read for
    this branch so), and any, in the schema or given, whose name says it is a secret."""
    props = (schema or {}).get("properties") or {}
    flagged = {k for k, p in props.items() if isinstance(p, dict) and p.get("encrypted")}
    return flagged | {k for k in set(props) | set(names) if SECRET_NAME.search(k)}


def shown(inputs, schema):
    """The inputs as they may be printed: every value the schema marks encrypted replaced."""
    hidden = encrypted_names(schema, inputs)
    return {k: (HIDDEN if k in hidden else val) for k, val in inputs.items()}


def check_inputs(schema, inputs):
    """(missing, unknown): required inputs left out that have no default, and inputs the version does not declare."""
    props = (schema or {}).get("properties") or {}
    required = (schema or {}).get("required") or []
    missing = sorted(k for k in required if k not in inputs and "default" not in (props.get(k) or {}))
    unknown = sorted(k for k in inputs if props and k not in props)
    return missing, unknown


def existing(v, project_id, name):
    """Deployments of exactly this name in exactly this project, read whole. The project is checked here as well as
    filtered by the server, so a list that ignored the filter cannot hand back another project's deployment."""
    rows = pages(v, "/deployment/api/deployments", {"projects": project_id, "name": name, "apiVersion": API_VERSION})
    return [d for d in rows if d.get("name") == name and d.get("projectId") == project_id]


def one(found, name):
    if len(found) > 1:
        raise Stop(4, f"{len(found)} deployments in the project are named {name!r}; this script acts on one name that "
                      "names one deployment")
    return found[0] if found else None


def same_owner(owned_by, me):
    """Whether the signed-in user owns it. Exact, ignoring case: on 9.1.1 a session's user name and a deployment's
    ownedBy were written alike for the same person, while another sign-in style wrote the full user principal name, so
    a looser match could take one person for another."""
    return bool(owned_by and me and owned_by.strip().lower() == me.strip().lower())


def deployment_ids(answer):
    """The deployment ids a request answered with. The catalog API describes an array; both guides print an object."""
    rows = answer if isinstance(answer, list) else [answer] if isinstance(answer, dict) else []
    return [r["deploymentId"] for r in rows if isinstance(r, dict) and r.get("deploymentId")]


# --------------------------------------------------------------------------- 8 and 9: the request and the wait

def read_deployment(v, dep_id):
    st, body, _ = v.call("GET", f"/deployment/api/deployments/{dep_id}",
                         params={"expand": "lastRequest", "apiVersion": API_VERSION})
    if st == 401:
        raise Stop(3, "the bearer ended during the wait (it lasts one hour). The deployment exists: run again and it "
                      "waits on it, sending nothing")
    if st != 200 or not isinstance(body, dict):
        return st, None, None
    return st, body.get("status"), (body.get("lastRequest") or {}).get("status")


def state(dep, req):
    """What a deployment's status and its last request's status say, for this script's purpose."""
    dep = dep or ""
    if dep in CREATED:
        return "created"
    if dep.startswith("DELETE_"):
        return "removing"
    if dep == "CREATE_FAILED" or req in REQUEST_STOPPED:
        return "failed"
    if req in REQUEST_HELD:
        return "held"
    return "running"


def report(dep_id, dep, req):
    """The exit code for a deployment found in a given state, with what to do about it."""
    kind = state(dep, req)
    if kind == "created":
        if dep == "UPDATE_FAILED":
            print("   it was created; a later update of it failed (UPDATE_FAILED), which this script does not act on")
        return 0
    if kind == "removing":
        print(f"   deployment {dep_id} is {dep}: it is being removed or is gone. Run again once it is gone to request it anew")
    elif kind == "failed":
        print("   the deployment did not succeed; its request's details are in the UI, under the deployment's History tab")
    elif kind == "held":
        print(f"   the request is held ({req}): a policy wants a person. Nothing more is sent; run again later to read "
              "where it stands")
    return 3


def wait(v, dep_id, limit):
    """Print each change of the deployment's status or its request's until it is created, fails, is held, goes, or the
    limit passes. Returns the exit code."""
    started = time.monotonic()
    seen, read_once, last = None, False, None
    while True:
        last, dep, req = read_deployment(v, dep_id)
        if last == 404 and read_once:
            print(f"   deployment {dep_id} answered 404 after it had been read: it was deleted while waiting")
            return 3
        if last == 200:
            read_once = True
            if (dep, req) != seen:
                say(None, f"   after {int(time.monotonic() - started)} s: deployment {dep}, request {req}", was=False)
                seen = (dep, req)
            if state(dep, req) != "running":
                return report(dep_id, dep, req)
        if time.monotonic() - started >= limit:
            if last == 200:
                print(f"   still {dep} after {limit} s. The deployment exists, so a second run waits on it and sends "
                      "nothing")
            else:
                print(f"   deployment {dep_id} could not be read for {limit} s (last answer {last or 'none'}). The "
                      "request was accepted with that id; run again later: the script lists before it sends")
            return 3
        time.sleep(10)


def request(v, item, project_id, version, inputs, name, limit):
    path = f"/catalog/api/items/{item['id']}/request"
    body = {"deploymentName": name, "projectId": project_id, "version": version, "inputs": inputs, "reason": REASON}
    if version is None:
        del body["version"]
    st, answer, _ = v.call("POST", path, params={"apiVersion": API_VERSION}, body=body, timeout=120)
    if st is not None and 400 <= st < 500:
        raise Stop(2, f"the request was refused ({st}): {detail(answer)}")
    ids = deployment_ids(answer) if st is not None and 200 <= st < 300 else []
    if ids:
        shape = "a list" if isinstance(answer, list) else "an object"
        say(8, f"POST {path}?apiVersion={API_VERSION}: {st}, answered with {shape}, deployment {ids[0]}")
    else:
        # No answer, a 5xx, or a 2xx without an id: the platform may still have taken the request. Only the list by
        # name can say, and it may lag the request, so it is read for a while; nothing is ever sent again from here.
        started, found = time.monotonic(), None
        while True:
            found = one(existing(v, project_id, name), name)
            if found or time.monotonic() - started >= LIST_AFTER_SILENCE:
                break
            time.sleep(10)
        if not found:
            raise Stop(6, f"the request answered {st or 'nothing'}, and no deployment named {name!r} was visible after "
                          f"{LIST_AFTER_SILENCE} s. It may still be in flight: wait a few minutes before running again. "
                          "The script lists before it sends, so a deployment that has appeared by then is not "
                          "requested twice")
        ids = [found["id"]]
        say(8, f"the request answered {st or 'nothing'}; the list by name found deployment {ids[0]}")
    say(9, f"waiting on deployment {ids[0]}, at most {limit} s")
    return wait(v, ids[0], limit)


def delete(v, dep, execute, any_owner, limit):
    owned_by, created_by = dep.get("ownedBy"), dep.get("createdBy")
    say(None, f"deployment {dep['id']} ({dep.get('status')}): owned by {owned_by}, created by {created_by}; "
              f"signed in as {v.user or 'a user this script could not read'}", was=False)
    mine = same_owner(owned_by, v.user)
    if not mine and not any_owner:
        if not execute:
            say(None, "would refuse to delete it: it is not owned by the signed-in user. --any-owner deletes it anyway",
                was=False)
            return 0
        raise Stop(4, f"deployment {dep['id']} is owned by {owned_by}, not by {v.user}; add --any-owner to delete it "
                      "anyway")
    if (dep.get("status") or "").startswith("DELETE_INPROGRESS"):
        say(None, "it is already being removed; nothing more is sent", was=False)
        if not execute:
            return 0
        return gone(v, dep["id"], None, limit)
    if not execute:
        say(None, "would delete it and every resource in it. Add --execute to delete it", was=False)
        return 0
    st, body, _ = v.call("DELETE", f"/deployment/api/deployments/{dep['id']}", params={"apiVersion": API_VERSION})
    if st != 200:
        raise Stop(2, f"the delete answered {st or 'nothing'}: {detail(body)}")
    req_id = (body or {}).get("id")
    say(None, f"DELETE /deployment/api/deployments/{dep['id']}: 200, request {req_id} {(body or {}).get('status')}",
        was=False)
    return gone(v, dep["id"], req_id, limit)


def gone(v, dep_id, req_id, limit):
    """Wait for a deployment to answer 404, watching the delete's own request when its id is known."""
    started = time.monotonic()
    while True:
        time.sleep(10)
        st, status, _ = read_deployment(v, dep_id)
        if st == 404:
            say(None, f"   gone after {int(time.monotonic() - started)} s", was=False)
            return 0
        req_status = None
        if req_id:
            rst, rbody, _ = v.call("GET", f"/deployment/api/requests/{req_id}", params={"apiVersion": API_VERSION})
            req_status = (rbody or {}).get("status") if rst == 200 else None
        if status == "DELETE_FAILED" or req_status in REQUEST_STOPPED:
            print(f"   the delete did not finish: deployment {status}, delete request {req_status}")
            return 3
        if time.monotonic() - started >= limit:
            print(f"   still there after {limit} s: deployment {status}, delete request {req_status}")
            return 3


# --------------------------------------------------------------------------- the run

def run(args):
    execute, remove, any_owner = "--execute" in args, "--delete" in args, "--any-owner" in args
    host, org = need("VCFA_HOST"), need("VCFA_ORG")
    project, item_name, name = need("CATALOG_PROJECT"), need("CATALOG_ITEM"), need("DEPLOYMENT_NAME")
    token = secret("VCFA_API_TOKEN")
    user = os.environ.get("VCFA_USER", "").strip()
    password = secret("VCFA_PASSWORD") if not token else None
    if not token and not (user and password):
        raise Stop(5, "no sign-in: set VCFA_API_TOKEN_FILE, or VCFA_USER with VCFA_PASSWORD_FILE")
    inputs, inputs_given = {}, False
    if os.environ.get("CATALOG_INPUTS_FILE") and not remove:
        try:
            inputs = json.loads(private_file("CATALOG_INPUTS_FILE", os.environ["CATALOG_INPUTS_FILE"]))
        except ValueError as ex:
            raise Stop(5, f"CATALOG_INPUTS_FILE could not be read as JSON: {ex}") from None
        if not isinstance(inputs, dict):
            raise Stop(5, "CATALOG_INPUTS_FILE must hold one JSON object, the inputs by name")
        inputs_given = True
    try:
        limit = int(os.environ.get("CATALOG_WAIT_SECONDS") or 1200)
    except ValueError:
        raise Stop(5, "CATALOG_WAIT_SECONDS must be a whole number of seconds") from None
    wanted_version = os.environ.get("CATALOG_VERSION", "").strip() or None

    v = Vcfa(host)
    try:
        say(1, sign_in(v, org, token=token, user=user, password=password))
        say(2, organization_type(v))
        project_id = find_project(v, project)
        say(3, f"project {project!r}: {project_id}")
        item = find_item(v, project_id, item_name)
        say(4, f"catalog item {item_name!r}: {item['id']} ({(item.get('type') or {}).get('id', '?')}, from "
               f"{item.get('sourceName') or 'its content source'})")
        dep = one(existing(v, project_id, name), name)
        if remove:
            say(7, f"deployment named {name!r} in the project: {'one' if dep else 'none'}")
            if not dep:
                print("   nothing to delete")
                return 0
            if dep.get("catalogItemId") != item["id"]:
                raise Stop(4, f"deployment {name!r} was not made from {item_name!r}; this script deletes only what "
                              "this catalog item made")
            return delete(v, dep, execute, any_owner, limit)
        if dep:
            if dep.get("catalogItemId") != item["id"]:
                raise Stop(4, f"the name {name!r} belongs to a deployment from another catalog item; choose another")
            made_with = dep.get("catalogItemVersion")
            if wanted_version and made_with and wanted_version != made_with:
                raise Stop(4, f"deployment {name!r} was made with version {made_with}, not {wanted_version}; choose "
                              "another name for another version")
            if inputs_given:
                hidden = encrypted_names(version_schema(v, item["id"], made_with) if made_with else {}, inputs)
                st, full, _ = v.call("GET", f"/deployment/api/deployments/{dep['id']}", params={"apiVersion": API_VERSION})
                if st != 200 or not isinstance(full, dict):
                    raise Stop(2, f"GET the deployment {dep['id']} to compare its inputs answered {st or 'nothing'}")
                had = full.get("inputs") or {}
                differ = sorted(k for k, val in inputs.items()
                                if k not in hidden and k in had and had[k] != val and str(had[k]) != str(val))
                if differ:
                    raise Stop(4, f"deployment {name!r} was made with other values for: {', '.join(differ)}; choose "
                                  "another name for another request")
            say(7, f"deployment {name!r} exists ({dep['id']}, {dep.get('status')}): the request was sent before, and is "
                   "not sent again")
            if state(dep.get("status"), None) == "running" and execute:
                say(9, f"waiting on deployment {dep['id']}, at most {limit} s")
                return wait(v, dep["id"], limit)
            if state(dep.get("status"), None) == "running":
                print("   it is still being created; --execute waits on it")
                return 3
            return report(dep["id"], dep.get("status"), None)
        say(7, f"no deployment named {name!r} in the project")
        versions = pages(v, f"/catalog/api/items/{item['id']}/versions", {})
        versioned = [x for x in versions if x.get("id")]
        if versioned or not versions:
            ver = pick_version(versioned, wanted_version)
            version_id = ver["id"]
            say(5, f"version {version_id} of {len(versioned)} released")
            schema = version_schema(v, item["id"], version_id)
        else:
            # Its version entries carry no id (on 9.1.1, an Orchestrator workflow item's read so): the item is not
            # versioned, its inputs are on the item, and the request names no version.
            if wanted_version:
                raise Stop(2, f"the catalog item {item_name!r} has no versions; unset CATALOG_VERSION")
            version_id = None
            st, whole, _ = v.call("GET", f"/catalog/api/items/{item['id']}")
            if st != 200 or not isinstance(whole, dict):
                raise Stop(2, f"GET the catalog item's schema answered {st or 'nothing'}")
            schema = whole.get("schema") or {}
            say(5, "the item has no versions, so the request names none; its inputs are the item's own")
        missing, unknown = check_inputs(schema, inputs)
        if missing or unknown:
            raise Stop(2, "the inputs do not fit this version: "
                       + "; ".join(([f"required and unset: {', '.join(missing)}"] if missing else [])
                                   + ([f"not declared: {', '.join(unknown)}"] if unknown else [])))
        defaults = sorted(k for k, p in ((schema.get("properties") or {}).items()) if k not in inputs and "default" in (p or {}))
        hidden = sorted(encrypted_names(schema, inputs) & set(inputs))
        say(6, f"inputs sent: {', '.join(sorted(inputs)) or 'none'}; defaults the platform fills: "
               f"{', '.join(defaults) or 'none'}" + (f"; encrypted, never printed: {', '.join(hidden)}" if hidden else ""))
        if not execute:
            plan = {"deploymentName": name, "projectId": project_id, "version": version_id,
                    "inputs": shown(inputs, schema), "reason": REASON}
            if version_id is None:
                del plan["version"]
            say(8, f"would send POST /catalog/api/items/{item['id']}/request?apiVersion={API_VERSION}\n"
                   + json.dumps(plan, indent=2) + "\nAdd --execute to send it")
            return 0
        return request(v, item, project_id, version_id, inputs, name, limit)
    finally:
        line = sign_out(v)
        if line:
            say(10, line)


def main(argv):
    if any(a in ("-h", "--help") for a in argv):
        print(__doc__)
        return 0
    unknown = [a for a in argv if a not in FLAGS]
    if unknown:
        print(f"USAGE: unknown argument {unknown[0]!r}; the flags are " + ", ".join(FLAGS))
        return 5
    try:
        return run(argv)
    except Stop as stop:
        print(("USAGE: " if stop.code == 5 else "STOPPED: ") + str(stop))
        return stop.code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
