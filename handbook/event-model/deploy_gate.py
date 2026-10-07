#!/usr/bin/env python3
"""deploy_gate.py: put gate.py on your Orchestrator as a workflow, bind it to deletes with a blocking
subscription, and read back both, or take them away again.

Dry run by default: without --apply it prints every call it would make and changes nothing.

  --apply           build the workflow from gate.py, import it, wait until the Automation host resolves it,
                    then create the blocking subscription and read it back
  --remove          delete the subscription, then the workflow, then the category if it is empty, and read
                    back that each is gone (with --apply; without it, the plan)
  --runs            the gate workflow's recent runs on the Orchestrator, newest first, with their log lines

Why each step is there. The workflow is imported, not typed into a console, so the script it runs is gate.py
byte for byte, which test_gate.py has already checked off the engine. The Automation host, not the
Orchestrator, is what dispatches an event, and it learns the Orchestrator's workflows by enumerating them on a
schedule, so a newly imported workflow is unknown to it until the next pass (about ten minutes apart on the
reference estate). A subscription bound before then is stored and silent; so the subscription is created only
once GET /vro/workflows/{id} on the Automation host answers 200 (events.py --workflow is the same check). The
subscription is refused without a scope, because an unscoped blocking subscription holds every delete in the
organization. And every write is read back, because the create calls report acceptance, not effect.

Exit codes: 0 done (or planned); 1 a read-back disagreed with what was sent; 2 the Automation host never
resolved the workflow, so nothing was bound.

Usage:
    export VCFA_HOST=automation.example.net        # the Automation host, which dispatches
    export VCFA_TOKEN=<a tenant bearer>
    export VRO_HOST=orchestrator.example.net       # the Orchestrator registered with it, which stores content
    export VRO_TOKEN=<a bearer it accepts>         # optional: defaults to VCFA_TOKEN

    python3 deploy_gate.py --registry https://cmdb.example.net/api/machines --resource-name Web01VM
    python3 deploy_gate.py --registry https://cmdb.example.net/api/machines --resource-name Web01VM --apply
    python3 deploy_gate.py --runs
    python3 deploy_gate.py --remove --apply
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import ssl
import sys
import time
import uuid
import zipfile
from urllib import error as _er, parse as _up, request as _rq

HERE = os.path.dirname(os.path.abspath(__file__))
GATE = os.path.join(HERE, "gate.py")
NS = uuid.UUID("6f1c3c2e-6a43-5b8e-9a51-2a7f3d0c9e11")    # names the workflow id, so a re-run updates in place
SUBSCRIBER = "service-account-project-serviceaccount"     # what a console-made subscription stores
TOPIC = "deployment.resource.request.pre"
# The engine logs a raise as a Python traceback and a workflow stack; --runs prints the gate's own lines and the
# reason it raised, once.
ENGINE_NOISE = ("Traceback", "File ", "^", "ret = ", "raise ", "outcome, attempts", "handler.", "Error in (",
                "Workflow execution stack", "***", "item: ")
VERIFY = os.environ.get("TLS_VERIFY", "true").lower() not in ("false", "0", "no")


def _ctx():
    ctx = ssl.create_default_context()
    if not VERIFY:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


class Api:
    def __init__(self, host_var, token_var, fallback_token_var=None):
        self.host = os.environ.get(host_var, "")
        self.token = os.environ.get(token_var) or (os.environ.get(fallback_token_var, "") if fallback_token_var else "")
        self.names = (host_var, token_var)

    def call(self, method, path, body=None, headers=None, raw=None):
        """Returns (status, parsed body or None). Never raises on an HTTP status: the status is the answer."""
        if not self.host or not self.token:
            sys.exit(f"set {self.names[0]} and {self.names[1]} first")
        h = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        data = raw
        if body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        h.update(headers or {})
        req = _rq.Request(f"https://{self.host}{path}", data=data, method=method, headers=h)
        try:
            with _rq.urlopen(req, context=_ctx(), timeout=120) as r:
                text = r.read().decode("utf-8", "replace")
                return r.status, (json.loads(text) if text.strip().startswith(("{", "[")) else None)
        except _er.HTTPError as e:
            text = e.read().decode("utf-8", "replace")
            try:
                return e.code, json.loads(text)
            except ValueError:
                return e.code, None


VCFA = Api("VCFA_HOST", "VCFA_TOKEN")
VRO = Api("VRO_HOST", "VRO_TOKEN", "VCFA_TOKEN")


# ---------------------------------------------------------------- the workflow, built from gate.py
def workflow_id(name: str) -> str:
    return str(uuid.uuid5(NS, name))


def subscription_id(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _cdata(text: str) -> str:
    if "]]>" in text:
        raise ValueError("the text carries ']]>', which would end the CDATA section early")
    return f"<![CDATA[{text}]]>"


def build_xml(name: str, registry: str, deadline: float, verify_tls: bool) -> str:
    """The workflow: one input, three attributes, one python:3.11 task whose script is gate.py unchanged."""
    script = open(GATE, encoding="utf-8").read()
    attrs = [("registryUrl", "string", registry), ("deadlineSeconds", "number", f"{float(deadline)}"),
             ("verifyTls", "boolean", "true" if verify_tls else "false")]
    attrib = "".join(f'  <attrib name="{n}" type="{t}" read-only="false">\n    <value encoded="n">{_cdata(v)}</value>\n  </attrib>\n'
                     for n, t, v in attrs)
    binds = "".join(f'      <bind name="{n}" type="{t}" export-name="{n}"/>\n'
                    for n, t in [("inputProperties", "Properties")] + [(n, t) for n, t, _v in attrs])
    return f"""<?xml version='1.0' encoding='UTF-8'?>
<workflow xmlns="http://vmware.com/vco/workflow" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://vmware.com/vco/workflow http://vmware.com/vco/workflow/Workflow-v4.xsd" root-name="item1" object-name="workflow:name=generic" id="{workflow_id(name)}" version="1.0.0" api-version="6.0.0" editor-version="2.0" restartMode="1" resumeFromFailedMode="0">
  <display-name>{_cdata(name)}</display-name>
  <description>{_cdata("Pre-delete gate built from the event-model companion's gate.py: acts only on DELETE_RESOURCE, unregisters the resource, fails closed, stays idempotent, bounds its own runtime.")}</description>
  <position y="50.0" x="100.0"/>
  <input>
    <param name="inputProperties" type="Properties">
      <description>{_cdata("The event payload the broker passes to every handler")}</description>
    </param>
  </input>
{attrib}  <workflow-item name="item0" type="end" end-mode="0">
    <in-binding/>
    <position y="50.0" x="300.0"/>
  </workflow-item>
  <workflow-item name="item1" out-name="item0" type="task">
    <runtime>{_cdata("python:3.11")}</runtime>
    <display-name>{_cdata("Unregister, then let the delete continue")}</display-name>
    <script encoded="false">{_cdata(script)}</script>
    <in-binding>
{binds}    </in-binding>
    <out-binding/>
    <position y="60.0" x="170.0"/>
  </workflow-item>
  <presentation/>
</workflow>
"""


def package(xml: str) -> bytes:
    """The .workflow file: a zip of a properties file and the content in UTF-16, as an export carries them."""
    info = ("#\n#" + time.strftime("%a %b %d %H:%M:%S GMT %Y", time.gmtime()) + "\nowner=\ncharset=UTF-16\n"
            "creator=privatecloudarchitect.com\nunicode=true\ntype=workflow\nversion=2.0\n")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("workflow-info", info.encode("latin-1"))
        z.writestr("workflow-content", xml.encode("utf-16"))
    return buf.getvalue()


def multipart(filename: str, data: bytes) -> tuple[bytes, str]:
    boundary = "----gate" + uuid.uuid4().hex
    head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
            "Content-Type: application/zip\r\n\r\n").encode()
    return head + data + f"\r\n--{boundary}--\r\n".encode(), f"multipart/form-data; boundary={boundary}"


# ---------------------------------------------------------------- reads
def find_category(name: str):
    st, b = VRO.call("GET", "/vco/api/categories?categoryType=WorkflowCategory")
    if st != 200:
        sys.exit(f"GET /vco/api/categories answered {st}")
    for link in (b or {}).get("link", []):
        a = {x["name"]: x.get("value") for x in link.get("attributes", [])}
        if a.get("name") == name and not a.get("parentCategoryId"):
            return a.get("id")
    return None


def task_script(wid: str):
    """The script and attribute values the Orchestrator stored, read back from the workflow's content."""
    st, b = VRO.call("GET", f"/vco/api/workflows/{wid}/content")
    if st != 200:
        return st, None, {}
    task = next((i for i in b.get("workflow-item", []) if i.get("runtime")), {})
    attrs = {a["name"]: next(iter((a.get("value") or {}).values()), {}).get("value") for a in b.get("attrib", [])}
    return st, (task.get("script") or {}).get("value"), {"runtime": task.get("runtime"), **attrs}


def gateway_resolves(wid: str) -> int:
    st, _b = VCFA.call("GET", f"/vro/workflows/{_up.quote(wid)}")
    return st


# ---------------------------------------------------------------- apply
def apply(a) -> int:
    name, wid, sid = a.name, workflow_id(a.name), subscription_id(a.name)
    criteria = a.criteria or (f'event.data["resourceName"] == "{a.resource_name}"' if a.resource_name else "")
    if not criteria:
        sys.exit("refusing: a blocking subscription with no criteria holds every delete in the organization. "
                 "Scope it with --resource-name or --criteria.")
    if not a.registry:
        sys.exit("--registry is required: the gate refuses every delete it cannot unregister, by design")
    xml = build_xml(name, a.registry, a.deadline, not a.insecure_registry)
    assert open(GATE, encoding="utf-8").read() in xml, "the workflow does not carry gate.py unchanged"
    pkg = package(xml)
    sub = {"id": sid, "name": name, "description": "Pre-delete gate (event-model companion)",
           "eventTopicId": TOPIC, "type": "RUNNABLE", "runnableType": "extensibility.vro", "runnableId": wid,
           "subscriberId": a.subscriber, "criteria": criteria, "blocking": True, "timeout": 0,
           "priority": a.priority, "disabled": False,
           "constraints": {"projectId": [a.project_id] if a.project_id else None}}
    print(f"workflow   {name}  id {wid}  ({len(pkg)} bytes, python:3.11, gate.py embedded unchanged)")
    print(f"           registryUrl {a.registry}  deadlineSeconds {a.deadline:g}  verifyTls {not a.insecure_registry}")
    print(f"category   {a.category} on {VRO.host or '$VRO_HOST'}")
    print(f"subscribe  {TOPIC}, blocking, timeout 0, criteria {criteria}"
          + (f", project {a.project_id}" if a.project_id else ""))
    if not a.apply:
        print("\ndry run: nothing sent. The calls, in order:\n"
              f"  GET  /vco/api/categories, then POST it if '{a.category}' is absent\n"
              f"  POST /vco/api/workflows?categoryId=<id>&overwrite=true      the .workflow file\n"
              f"  GET  /vco/api/workflows/{wid}/content    read back the script and attributes\n"
              f"  GET  /vro/workflows/{wid} on $VCFA_HOST, until 200: the dispatch plane resolves it\n"
              f"  POST /event-broker/api/subscriptions      id {sid}\n"
              f"  GET  /event-broker/api/subscriptions/{sid}      read back the binding\n"
              "Re-run with --apply.")
        return 0

    cat = find_category(a.category)
    if not cat:
        st, b = VRO.call("POST", "/vco/api/categories", {"name": a.category, "type": "WorkflowCategory"})
        cat = find_category(a.category)
        print(f"category   created ({st}), read back {'present' if cat else 'ABSENT'}")
        if not cat:
            return 1
    else:
        print("category   present, reused")

    body, ctype = multipart(f"{wid}.workflow", pkg)
    st, _b = VRO.call("POST", f"/vco/api/workflows?categoryId={_up.quote(cat)}&overwrite=true",
                      raw=body, headers={"Content-Type": ctype})
    rst, script, stored = task_script(wid)
    same = script == open(GATE, encoding="utf-8").read()
    print(f"import     {st}; read back {rst}: script {'is gate.py' if same else 'DIFFERS from gate.py'}, "
          f"runtime {stored.get('runtime')}, registryUrl {stored.get('registryUrl')}, "
          f"deadlineSeconds {stored.get('deadlineSeconds')}, verifyTls {stored.get('verifyTls')}")
    if rst != 200 or not same or stored.get("registryUrl") != a.registry:
        return 1

    t0, waited = time.monotonic(), 0
    while True:
        gst = gateway_resolves(wid)
        waited = time.monotonic() - t0
        if gst == 200:
            print(f"dispatch   the Automation host resolves the workflow (200) after {waited:.0f} s")
            break
        if waited >= a.wait:
            print(f"dispatch   the Automation host still answers {gst} after {waited:.0f} s: NOTHING BOUND. A "
                  "subscription to this id would be stored and never run. Check the Orchestrator integration "
                  "on the Automation host, then re-run.")
            return 2
        time.sleep(min(30, max(1, a.wait - waited)))

    st, _b = VCFA.call("POST", "/event-broker/api/subscriptions", sub)
    rst, got = VCFA.call("GET", f"/event-broker/api/subscriptions/{sid}")
    keys = ("eventTopicId", "type", "runnableType", "runnableId", "subscriberId", "criteria", "constraints", "blocking",
            "timeout", "disabled")
    diff = [k for k in keys if (got or {}).get(k) != sub[k]]
    print(f"subscribe  {st}; read back {rst}: " + ("every field as sent" if rst == 200 and not diff
                                                     else "DIFFERS on " + ", ".join(diff or ["the read"])))
    for k in keys:
        print(f"             {k:13s} {json.dumps((got or {}).get(k))}")
    return 0 if rst == 200 and not diff else 1


# ---------------------------------------------------------------- remove
def remove(a) -> int:
    wid, sid = workflow_id(a.name), subscription_id(a.name)
    if not a.apply:
        print(f"dry run: would DELETE /event-broker/api/subscriptions/{sid}, then /vco/api/workflows/{wid}, then the "
              f"category '{a.category}' if it holds nothing else, reading each back. Re-run with --apply.")
        return 0
    st, _ = VCFA.call("DELETE", f"/event-broker/api/subscriptions/{sid}")
    sst, _ = VCFA.call("GET", f"/event-broker/api/subscriptions/{sid}")
    print(f"subscription  delete {st}, read back {sst}")
    st, _ = VRO.call("DELETE", f"/vco/api/workflows/{wid}?force=true")
    wst, _ = VRO.call("GET", f"/vco/api/workflows/{wid}")
    print(f"workflow      delete {st}, read back {wst} on the Orchestrator")
    gst = gateway_resolves(wid)
    if gst == 200:
        print("dispatch      the Automation host still answers 200 for it: it forgets a deleted workflow at its next "
              "enumeration of the Orchestrator, as it learns a new one. Nothing is bound to it, so nothing runs.")
    cat, cst = find_category(a.category), None
    if cat:
        _s, b = VRO.call("GET", f"/vco/api/categories/{cat}")
        held = [r for r in (b or {}).get("relations", {}).get("link", []) if r.get("rel") == "down"]
        if held:
            print(f"category      kept: it still holds {len(held)} item(s)")
        else:
            st, _ = VRO.call("DELETE", f"/vco/api/categories/{cat}")
            cst = "absent" if not find_category(a.category) else "STILL PRESENT"
            print(f"category      delete {st}, read back {cst}")
    gone = sst == 404 and wst == 404 and cst != "STILL PRESENT"
    print("residue       none" if gone else "residue       FOUND: see the lines above")
    return 0 if gone else 1


# ---------------------------------------------------------------- runs
def runs(a) -> int:
    wid = workflow_id(a.name)
    st, b = VRO.call("GET", f"/vco/api/workflows/{wid}/executions?maxResult=500")   # the order is not newest first
    if st != 200:
        print(f"GET executions answered {st}")
        return 1
    rows = []
    for link in (b or {}).get("relations", {}).get("link", []):
        x = {i["name"]: i.get("value") for i in link.get("attributes", [])}
        if x.get("id"):
            rows.append(x)
    rows.sort(key=lambda x: str(x.get("startDate")), reverse=True)
    print(f"{len(rows)} run(s) of {a.name}" + (f", the newest {a.last}" if len(rows) > a.last else "") + "\n")
    for x in rows[:a.last]:
        eid = x["id"]
        _s, e = VRO.call("GET", f"/vco/api/workflows/{wid}/executions/{eid}")
        start, end = (e or {}).get("start-date"), (e or {}).get("end-date")
        secs = ""
        try:
            from datetime import datetime
            secs = f"{(datetime.fromisoformat(end.replace('Z', '+00:00')) - datetime.fromisoformat(start.replace('Z', '+00:00'))).total_seconds():.0f} s"
        except Exception:  # noqa: BLE001  a run still going has no end date
            pass
        print(f"  {str(start)[:19]}  {str((e or {}).get('state')):10s} {secs:>6s}  run {eid}")
        _s, logs = VRO.call("GET", f"/vco/api/workflows/{wid}/executions/{eid}/syslogs?maxResult=50")
        for entry in sorted((logs or {}).get("logs", []), key=lambda x: str((x.get("entry") or {}).get("time-stamp"))):
            msg = ((entry.get("entry") or {}).get("short-description") or "").strip()
            if msg and not msg.startswith(ENGINE_NOISE):
                print(f"        {msg[:160]}")
        if (e or {}).get("content-exception"):
            why = str(e["content-exception"]).split("Exception: ", 1)[-1].split(" (Workflow:", 1)[0]
            print(f"        raised: {why[:200]}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", default="Pre-delete gate", help="workflow and subscription name (default: %(default)s)")
    ap.add_argument("--category", default="Delete gates", help="Orchestrator workflow category (default: %(default)s)")
    ap.add_argument("--registry", help="base URL the gate sends DELETE <registry>/<resource id> to")
    ap.add_argument("--deadline", type=float, default=60, help="the gate's own ceiling in seconds (default: %(default)s)")
    ap.add_argument("--insecure-registry", action="store_true", help="do not verify the registry's certificate")
    ap.add_argument("--resource-name", help="scope: the template resource name the subscription holds deletes for")
    ap.add_argument("--criteria", help="scope: a full criteria expression, in place of --resource-name")
    ap.add_argument("--project-id", help="scope: also constrain the subscription to one project")
    ap.add_argument("--subscriber", default=SUBSCRIBER, help="subscriberId: the identity subscribing (default: %(default)s)")
    ap.add_argument("--priority", type=int, default=10)
    ap.add_argument("--wait", type=float, default=900, help="seconds to wait for the Automation host to resolve the workflow")
    ap.add_argument("--apply", action="store_true", help="send the calls (default: dry run)")
    ap.add_argument("--remove", action="store_true")
    ap.add_argument("--runs", action="store_true")
    ap.add_argument("--last", type=int, default=5, help="with --runs: how many (default: %(default)s)")
    a = ap.parse_args()
    if a.runs:
        sys.exit(runs(a))
    sys.exit(remove(a) if a.remove else apply(a))
