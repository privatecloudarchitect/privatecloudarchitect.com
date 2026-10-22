#!/usr/bin/env python3
"""traffic.py: does a firewall rule written through VCF Automation actually stop traffic between two machines?

posture.py answers whether a region can enforce; this script answers whether it does. It builds the smallest
honest test and takes it down again:

  1. A THROWAWAY NAMESPACE in the project you name, its spec copied from a namespace you name (class, region, VPC,
     service-engine group and limits), so it sits in the same VPC and under the same posture as your workloads.
  2. TWO SMALL VMs: a server answering HTTP on TCP 8080, and a client that tries the server every second or two and
     writes curl's exit code into its own guestinfo. The client's readiness probe matches that key against "^0$",
     so the VM service reports, on the client's own status, whether the client can reach the server right now. No
     shell, no guest operations and no address reachable from outside are needed to read the result.
  3. ONE GROUP PER VM, each naming exactly that VM, and ONE FIREWALL POLICY dropping client to server on TCP 8080,
     applied to those two groups only. It lands with its rule disabled; then the one field changes to enabled; then
     back. The script records how long each change took to reach the traffic.
  4. TEARDOWN, always, in reverse, then a residue read.

Three findings shaped it (the chapter's gotchas): a namespace deleted while the platform's own post-create update
runs can be left stranded, so the delete waits for the namespace to be two minutes old and is re-sent once if no
delete task removes it; a namespace made through the API gets VM classes but may get no VM images, because the
organization's library is not attached to it and a tenant cannot attach it; and guest operations on a VM service VM
are refused even to vCenter's administrator, which is why the result travels through guestinfo.

What it writes on the platform: one namespace, two VMs, two groups and one policy, every one named seg-proof, all
deleted before it exits. With --attach-library, also the library the --like namespace carries, added to the
throwaway namespace alone through vCenter's namespace setting; the library itself is not touched.

Run:
  export VCFA_HOST=... VCFA_ORG=... VCFA_USER=... VCFA_PASSWORD_FILE=/path/to/password   # mode 0600
  export VCFA_TLS_VERIFY=false                    # only on a self-signed lab CA
  # only with --attach-library, the workload domain's vCenter:
  export VC_HOST=... VC_USER=... VC_PASSWORD_FILE=/path/to/password                     # mode 0600
  python3 traffic.py --project <project> --like <project>/<namespace> [--attach-library] [--image <vmi>] [--class <c>]
Every printed line and the record (traffic.json, beside this script or in OUT_DIR) carry labels in place of the
project, namespace, user, organization and host names, and no address or object id. POSTURE_DIR, optional, names the
folder holding posture.py when it is not beside this script.

The timings are upper bounds: the client tries every one to three seconds, the probe reads every two, and the script
reads the condition every two, so a reported second count includes the measurement's own lag.

Exit: 0 the rule stopped the traffic when enabled and released it when disabled · 1 it did not: the record says
      which step · 2 a setting is missing or a secret file is open to group or other · 3 a read or a write failed,
      including no image in the namespace without --attach-library · 4 the record refused to write because an
      estate value survived
"""

from __future__ import annotations

import base64
import importlib.util
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("posture", os.path.join(os.environ.get("POSTURE_DIR") or HERE, "posture.py"))
P = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(P)

A3 = "infrastructure.cci.vmware.com/v1alpha3"
VPC = "vpc.nsx.vmware.com/v1alpha1"
VMOP = "vmoperator.vmware.com/v1alpha5"
LIB = "imageregistry.vmware.com/v1alpha2"
SERVER, CLIENT, POLICY = "seg-proof-server", "seg-proof-client", "seg-proof-drop"
PORT = 8080
KEY = "segproof.curl"  # the VM service prefixes guestinfo. itself
SMALL = ("best-effort-xsmall", "best-effort-small", "best-small", "best-effort-medium")


class Failed(Exception):
    """A step the verdict depends on could not be done; exit 3 with the step named."""


def args():
    a, out = sys.argv[1:], {"attach": False}
    allowed = {"--project": "project", "--like": "like", "--image": "image", "--class": "cls"}
    while a:
        k = a.pop(0)
        if k == "--attach-library":
            out["attach"] = True
        elif k in allowed and a:
            out[allowed[k]] = a.pop(0)
        else:
            raise KeyError(f"unknown or incomplete argument {k!r}: use --project, --like, --attach-library, --image, --class")
    if "project" not in out or "/" not in out.get("like", ""):
        raise KeyError("--project <project> and --like <project>/<namespace> are required")
    return out


def call(method, url, body=None, ctype="application/json", accept="application/json"):
    data = json.dumps(body).encode() if body is not None else None
    h = {"Authorization": f"Bearer {P.bearer()}", "Accept": accept}
    if data is not None:
        h["Content-Type"] = ctype
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, context=P._ctx(), timeout=120) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"message": raw.decode(errors="replace")[:300]}


class VCenter:
    """vCenter's REST API under VC_USER: the library attach on the throwaway namespace, and the residue read."""

    def __init__(self):
        self.host = os.environ["VC_HOST"]
        password = P.secret("VC_PASSWORD")
        if not password:
            raise KeyError("VC_PASSWORD_FILE")
        basic = base64.b64encode(f"{os.environ['VC_USER']}:{password}".encode()).decode()
        req = urllib.request.Request(f"https://{self.host}/api/session", method="POST", headers={"Authorization": f"Basic {basic}"})
        with urllib.request.urlopen(req, context=P._ctx(), timeout=60) as r:
            self.sid = json.loads(r.read())

    def req(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        h = {"vmware-api-session-id": self.sid, "Accept": "application/json"}
        if data is not None:
            h["Content-Type"] = "application/json"
        req = urllib.request.Request(f"https://{self.host}{path}", data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, context=P._ctx(), timeout=120) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, None

    def close(self):
        self.req("DELETE", "/api/session")


class Run:
    def __init__(self, opt):
        self.opt = opt
        self.gw = f"https://{os.environ['VCFA_HOST']}/cci/kubernetes"
        self.like_project, self.like_ns = opt["like"].split("/", 1)
        self.ns = self.ep = self.born = None
        self.created = {"ns": False, "vms": [], "groups": [], "policy": False}
        self.vc = None
        self.rec = {"capturedUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "steps": []}

    def pairs(self):
        """Every estate value this run knows, longest first, with the label that replaces it."""
        p = [(self.ns, "<throwaway namespace>"), (self.like_ns, "<like namespace>"), (self.opt["project"], "<project>"),
             (self.like_project, "<like project>"), (os.environ.get("VCFA_USER"), "<user>"), (os.environ.get("VCFA_ORG"), "<org>"),
             (os.environ.get("VCFA_HOST"), "<host>"), (os.environ.get("VC_HOST"), "<vcenter>")]
        return sorted((x for x in p if x[0]), key=lambda x: -len(x[0]))

    def redact(self, text):
        for value, label in self.pairs():
            text = text.replace(value, label)
        return re.sub(r"vm-\d+", "<vm>", P.UUID.sub("<uuid>", text))

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
    def realized(obj):
        return any(c.get("type") == "Realized" and c.get("status") == "True"
                   for c in ((obj or {}).get("status") or {}).get("conditions") or [])

    def nsurl(self, project, name=""):
        return f"{self.gw}/apis/{A3}/namespaces/{project}/supervisornamespaces" + (f"/{name}" if name else "")

    def vmurl(self, name=""):
        return f"{self.ep}/apis/{VMOP}/namespaces/{self.ns}/virtualmachines" + (f"/{name}" if name else "")

    # ------------------------------------------------------------ the namespace
    def namespace(self):
        st, like = call("GET", self.nsurl(self.like_project, self.like_ns))
        if st != 200:
            raise Failed(f"reading the --like namespace answered {st}")
        spec = {k: v for k, v in like["spec"].items() if k in ("className", "regionName", "vpcName", "segName", "classConfigOverrides")}
        spec["description"] = "throwaway: microsegmentation traffic test, deleted by the script that made it"
        self.region = spec["regionName"]
        # The platform names it: a name cannot be given, only a prefix, and the project must be repeated in metadata.
        st, o = call("POST", self.nsurl(self.opt["project"]), {"apiVersion": A3, "kind": "SupervisorNamespace",
                     "metadata": {"generateName": "seg-proof-", "namespace": self.opt["project"]}, "spec": spec})
        self.log("namespace create", status=st, refused=(o or {}).get("message", "")[:200] if st >= 300 else None)
        if st >= 300:
            raise Failed("namespace create refused")
        self.ns, self.born, self.created["ns"] = o["metadata"]["name"], time.time(), True

        def endpoint():
            s, n = call("GET", self.nsurl(self.opt["project"], self.ns))
            return ((n or {}).get("status") or {}).get("namespaceEndpointURL") if s == 200 else None
        url, secs = self.wait("the namespace endpoint", endpoint, 600, 10)
        self.ep = url.rstrip("/")
        s, n = call("GET", self.nsurl(self.opt["project"], self.ns))
        self.storage = next((c["name"] for c in ((n or {}).get("status") or {}).get("storageClasses") or []), None) \
            or next((c["name"] for c in (spec.get("classConfigOverrides") or {}).get("storageClasses") or []), None)
        self.log("namespace ready", seconds=secs)

    def offers(self):
        def a_class():
            s, cl = call("GET", f"{self.ep}/apis/{VMOP}/namespaces/{self.ns}/virtualmachineclasses")
            names = [c["metadata"]["name"] for c in (cl or {}).get("items", [])] if s == 200 else []
            if self.opt.get("cls"):
                return self.opt["cls"] if self.opt["cls"] in names else None
            return next((c for c in SMALL if c in names), None)
        self.cls, secs = self.wait("a small VM class in the namespace", a_class, 900, 10)
        self.log("namespace offers a VM class", secondsAfterReady=secs, chosenClass=self.cls)

        def an_image():
            s, im = call("GET", f"{self.ep}/apis/{VMOP}/namespaces/{self.ns}/virtualmachineimages")
            ready = [i["metadata"]["name"] for i in (im or {}).get("items", []) if s == 200
                     and ((i.get("status") or {}).get("osInfo") or {}).get("type", "").startswith("ubuntu")
                     and any(c.get("type") == "Ready" and c.get("status") == "True" for c in (i.get("status") or {}).get("conditions") or [])]
            if self.opt.get("image"):
                return self.opt["image"] if self.opt["image"] in ready else None
            return sorted(ready)[0] if ready else None
        try:
            self.image, secs = self.wait("an Ubuntu image", an_image, 60, 10)
            self.log("namespace offers an Ubuntu image", attachedBy="already attached")
            return
        except Failed:
            pass
        if not self.opt["attach"]:
            raise Failed("no Ubuntu image in the namespace: its library is not attached (G-663); rerun with --attach-library, or ask the provider")
        self.attach()
        self.image, secs = self.wait("an Ubuntu image after the attach", an_image, 900, 10)
        self.log("namespace offers an Ubuntu image", secondsAfterAttach=secs)

    def attach(self):
        s, like = call("GET", self.nsurl(self.like_project, self.like_ns))
        lep = like["status"]["namespaceEndpointURL"].rstrip("/")
        s, libs = call("GET", f"{lep}/apis/{LIB}/namespaces/{self.like_ns}/contentlibraries")
        lib = ((libs or {}).get("items") or [None])[0]
        if not lib:
            raise Failed("the --like namespace carries no library to attach")
        body = {"apiVersion": LIB, "kind": "ContentLibrary", "metadata": {"name": lib["metadata"]["name"], "namespace": self.ns},
                "spec": {k: lib["spec"][k] for k in ("id", "libraryType", "resourceNamingStrategy") if k in lib["spec"]}}
        st, o = call("POST", f"{self.ep}/apis/{LIB}/namespaces/{self.ns}/contentlibraries", body)
        self.log("library attach, the tenant way: a ContentLibrary in the namespace", status=st,
                 refused=(o or {}).get("message", "")[:200] if st >= 300 else None)
        if st < 300:
            return
        self.vc = self.vc or VCenter()
        st, d = self.vc.req("GET", f"/api/vcenter/namespaces/instances/{self.ns}")
        vss = dict((d or {}).get("vm_service_spec") or {})
        vss["content_libraries"] = sorted(set(vss.get("content_libraries") or []) | {lib["spec"]["id"]})
        st, o = self.vc.req("PATCH", f"/api/vcenter/namespaces/instances/{self.ns}", {"vm_service_spec": vss})
        self.log("library attach, vCenter's namespace setting", status=st)
        if st >= 300:
            raise Failed("library attach refused both ways")

    # ------------------------------------------------------------ the two VMs
    def vm(self, name, runcmd, probe=None):
        spec = {"className": self.cls, "imageName": self.image, "storageClass": self.storage, "powerState": "PoweredOn",
                "bootstrap": {"cloudInit": {"cloudConfig": {"runcmd": runcmd}}}}
        if probe:
            spec["readinessProbe"] = probe
        st, o = call("POST", self.vmurl(), {"apiVersion": VMOP, "kind": "VirtualMachine",
                     "metadata": {"name": name, "namespace": self.ns, "labels": {"pca-test": "seg-proof"}}, "spec": spec})
        self.log(f"vm create ({name.rsplit('-', 1)[-1]})", status=st, refused=(o or {}).get("message", "")[:200] if st >= 300 else None)
        if st >= 300:
            raise Failed("vm create refused")
        self.created["vms"].append(name)

        def up():
            s, v = call("GET", self.vmurl(name))
            stt = (v or {}).get("status") or {}
            ip = (stt.get("network") or {}).get("primaryIP4")
            if s == 200 and stt.get("powerState") == "PoweredOn" and ip and stt.get("instanceUUID"):
                return {"ip": ip, "uuid": stt["instanceUUID"]}
        got, secs = self.wait(f"{name} powered on with an address", up, 900, 10)
        self.log(f"vm up ({name.rsplit('-', 1)[-1]})", seconds=secs)
        return got

    def ready(self):
        """The client's probe condition: True while its last try reached the server. (status, transition time)."""
        s, v = call("GET", self.vmurl(CLIENT))
        c = next((c for c in ((v or {}).get("status") or {}).get("conditions") or [] if c.get("type") == "Ready"), None)
        return (c.get("status"), c.get("lastTransitionTime"), c.get("reason")) if c else (None, None, None)

    def until(self, want, timeout, every=2):
        """Seconds until the client's Ready condition reads WANT, with the samples seen; None when it never did."""
        t0, seen = time.time(), []
        while time.time() - t0 < timeout:
            status, _, reason = self.ready()
            if not seen or seen[-1] != (status, reason):
                seen.append((status, reason))
            if status == want:
                return round(time.time() - t0), seen
            time.sleep(every)
        return None, seen

    def holds(self, want, seconds, every=2):
        """Whether the condition reads WANT throughout SECONDS; the samples that did not."""
        t0, off = time.time(), []
        while time.time() - t0 < seconds:
            status, _, reason = self.ready()
            if status != want:
                off.append({"after": round(time.time() - t0), "status": status, "reason": reason})
            time.sleep(every)
        return not off, off

    # ------------------------------------------------------------ groups and the policy
    def groups(self, uuids):
        for g, uuid in ((CLIENT, uuids[CLIENT]), (SERVER, uuids[SERVER])):
            st, o = call("POST", f"{self.gw}/apis/{VPC}/networksecuritygroups",
                         {"apiVersion": VPC, "kind": "NetworkSecurityGroup", "metadata": {"name": g},
                          "spec": {"regionName": self.region, "vms": [{"instanceUUID": uuid}]}})
            self.log(f"group create ({g.rsplit('-', 1)[-1]})", status=st, refused=(o or {}).get("message", "")[:200] if st >= 300 else None)
            if st >= 300:
                raise Failed("group create refused")
            self.created["groups"].append(g)
            _, secs = self.wait(f"group {g} Realized", lambda g=g: self.realized(call("GET", f"{self.gw}/apis/{VPC}/networksecuritygroups/{g}")[1]), 180)
            self.log(f"group Realized ({g.rsplit('-', 1)[-1]})", seconds=secs)

    def policy_body(self, disabled):
        applied = {"groupNames": [CLIENT, SERVER]}
        return {"apiVersion": VPC, "kind": "FirewallPolicy", "metadata": {"name": POLICY},
                "spec": {"regionName": self.region, "category": "Application", "priority": 900000, "stateful": True, "appliedTo": applied,
                         "rules": [{"name": f"{POLICY}-{PORT}", "action": "Drop", "direction": "InOut", "disabled": disabled, "ipProtocol": "IPV4",
                                    "from": [{"groupName": CLIENT}], "to": [{"groupName": SERVER}],
                                    "services": [{"l4PortSet": {"l4Protocol": "TCP", "destinationPorts": [str(PORT)]}}],
                                    "appliedTo": applied}]}}

    def apply(self, disabled):
        """Server-side apply: the same body creates the policy and changes the one field."""
        st, o = call("PATCH", f"{self.gw}/apis/{VPC}/firewallpolicies/{POLICY}?fieldManager=seg-proof&force=true",
                     self.policy_body(disabled), "application/apply-patch+yaml")
        if st >= 300:
            raise Failed(f"policy apply answered {st}: {(o or {}).get('message', '')[:160]}")
        self.created["policy"] = True
        t0 = time.time()

        def landed():
            s, p = call("GET", f"{self.gw}/apis/{VPC}/firewallpolicies/{POLICY}")
            rule = (((p or {}).get("spec") or {}).get("rules") or [{}])[0]
            return rule.get("disabled") == disabled and self.realized(p)
        self.wait("the policy Realized", landed, 180, 2)
        return st, round(time.time() - t0)

    # ------------------------------------------------------------ the test
    def test(self):
        self.namespace()
        self.offers()
        server = self.vm(SERVER, [["bash", "-c", f"systemd-run --unit=segproof-http python3 -m http.server {PORT} --directory /tmp"]])
        loop = (f"while true; do curl -s -o /dev/null -m 2 http://{server['ip']}:{PORT}/; c=$?; "
                f"vmware-rpctool \"info-set guestinfo.{KEY} $c\" >/dev/null 2>&1; sleep 1; done")
        client = self.vm(CLIENT, [["systemd-run", "--unit=segproof-try", "bash", "-c", loop]],
                         probe={"guestInfo": [{"key": KEY, "value": "^0$"}], "periodSeconds": 2})
        secs, seen = self.until("True", 600, 5)
        self.log("baseline: the client reaches the server", secondsUntilReady=secs, samples=seen[:6])
        if secs is None:
            s, v = call("GET", self.vmurl(CLIENT))
            self.log("client conditions", conditions=[(c.get("type"), c.get("status"), c.get("reason")) for c in ((v or {}).get("status") or {}).get("conditions") or []])
            raise Failed("the client's Ready condition never read True before any rule existed")
        self.groups({CLIENT: client["uuid"], SERVER: server["uuid"]})

        st, rsecs = self.apply(True)
        ok, off = self.holds("True", 30)
        self.log("policy landed with its rule disabled", applyStatus=st, realizedAfterSeconds=rsecs, trafficHeldFor30Seconds=ok, interruptions=off[:6])
        verdict = {"landedDisabledLeftTrafficAlone": ok}

        t0 = time.time()
        st, rsecs = self.apply(False)
        secs, seen = self.until("False", 180)
        to_block = round(time.time() - t0) if secs is not None else None
        blocked_for, off = (self.holds("False", 30) if secs is not None else (False, []))
        self.log("rule enabled", applyStatus=st, realizedAfterSeconds=rsecs, secondsFromApplyToBlocked=to_block,
                 blockedThroughout30Seconds=blocked_for, samples=seen[:6], gotThrough=off[:6])
        verdict["enabledBlocked"] = secs is not None and blocked_for

        t0 = time.time()
        st, rsecs = self.apply(True)
        secs, seen = self.until("True", 180)
        self.log("rule disabled again", applyStatus=st, realizedAfterSeconds=rsecs, secondsFromApplyToReached=round(time.time() - t0) if secs is not None else None, samples=seen[:6])
        verdict["disabledReleased"] = secs is not None
        self.rec["verdict"] = verdict
        return all(verdict.values())

    # ------------------------------------------------------------ teardown and residue
    def teardown(self):
        if self.created["policy"]:
            st, _ = call("DELETE", f"{self.gw}/apis/{VPC}/firewallpolicies/{POLICY}")
            self.log("teardown policy", status=st)
        for g in self.created["groups"]:
            st, _ = call("DELETE", f"{self.gw}/apis/{VPC}/networksecuritygroups/{g}")
            self.log(f"teardown group ({g.rsplit('-', 1)[-1]})", status=st)
        if not self.created["ns"]:
            return
        for name in self.created["vms"]:
            st, _ = call("DELETE", self.vmurl(name))
            self.log(f"teardown vm ({name.rsplit('-', 1)[-1]})", status=st)
        if self.created["vms"]:
            try:
                self.wait("the VMs gone", lambda: all(call("GET", self.vmurl(n))[0] == 404 for n in self.created["vms"]), 600, 10)
            except Failed as e:
                self.log("vms not gone yet", note=str(e))
        age = time.time() - self.born
        if age < 120:  # a delete during the platform's post-create update was left stranded once (G-662)
            self.log("teardown waits for the namespace to be two minutes old", seconds=round(120 - age))
            time.sleep(120 - age)
        url = self.nsurl(self.opt["project"], self.ns)
        st, _ = call("DELETE", url)
        self.log("teardown namespace", status=st)
        try:
            _, secs = self.wait("the namespace gone", lambda: call("GET", url)[0] == 404, 180, 15)
            self.log("namespace gone", seconds=secs)
        except Failed:
            st, _ = call("DELETE", url)
            self.log("namespace still present after 180 s: delete sent again", status=st)
            try:
                _, secs = self.wait("the namespace gone", lambda: call("GET", url)[0] == 404, 720, 15)
                self.log("namespace gone after the second delete", seconds=secs)
            except Failed as e:
                self.log("namespace not gone yet: delete it by hand", note=str(e))
        st, q = call("GET", f"https://{os.environ['VCFA_HOST']}/api/query?type=task&format=records&sortDesc=startDate&pageSize=50",
                     accept="application/*+json;version=40.0")
        self.log("namespace task timeline", tasks=[{"op": (t.get("operationFull") or "").split(" ")[0], "start": (t.get("startDate") or "")[11:19],
                                                   "end": (t.get("endDate") or "")[11:19], "status": t.get("status")}
                                                  for t in reversed((q or {}).get("record") or []) if f" {self.ns}(" in (t.get("operationFull") or "")])

    def residue(self):
        st, nss = call("GET", self.nsurl(self.opt["project"]))
        st2, gs = call("GET", f"{self.gw}/apis/{VPC}/networksecuritygroups")
        st3, ps = call("GET", f"{self.gw}/apis/{VPC}/firewallpolicies")
        r = {"segProofNamespaces": sum(1 for n in (nss or {}).get("items") or [] if n["metadata"]["name"].startswith("seg-proof-")),
             "segProofGroups": sum(1 for g in (gs or {}).get("items") or [] if g["metadata"]["name"].startswith("seg-proof")),
             "segProofPolicies": sum(1 for p in (ps or {}).get("items") or [] if p["metadata"]["name"].startswith("seg-proof"))}
        if os.environ.get("VC_HOST"):
            try:
                self.vc = self.vc or VCenter()
                s, lst = self.vc.req("GET", "/api/vcenter/namespaces/instances")
                r["vcenterSegProofNamespaces"] = sum(1 for x in lst or [] if x["namespace"].startswith("seg-proof-"))
            except Exception as e:
                r["vcenterSegProofNamespaces"] = f"unread: {type(e).__name__}"
        self.log("residue", **r)
        self.rec["residue"] = r
        return not any(v for v in r.values() if isinstance(v, int))


def scrub(rec, run):
    """Names become labels, as on every printed line. A record in which an estate value survives outside a label is
    refused (exit 4): the check strips the labels first, so a value that happens to spell a label's word is still caught."""
    text = run.redact(json.dumps(rec, ensure_ascii=False))  # raw, so an escaped name cannot slip past the check
    bare = text
    for _, label in run.pairs():
        bare = bare.replace(label, "")
    left = [label for value, label in run.pairs() if value in bare]
    if left:
        print(f"FATAL: the record still carries {left}; nothing written", file=sys.stderr)
        return None
    return json.loads(text)


def main():
    try:
        opt = args()
        P.bearer()
    except (KeyError, PermissionError) as e:
        print(f"setting: {e}", file=sys.stderr)
        return 2
    except (urllib.error.URLError, OSError) as e:
        print(f"sign-in failed: {type(e).__name__}", file=sys.stderr)
        return 3
    run, code = Run(opt), 3
    try:
        code = 0 if run.test() else 1
    except Failed as e:
        run.log("stopped", reason=str(e))
        code = 3
    except (urllib.error.URLError, OSError) as e:
        run.log("stopped", reason=f"{type(e).__name__}")
        code = 3
    finally:
        try:
            run.teardown()
            clean = run.residue()
            if not clean:
                code = code or 3
        finally:
            if run.vc:
                run.vc.close()
            out_dir = os.environ.get("OUT_DIR", HERE)
            out = os.path.join(out_dir, "traffic.json")
            rec = scrub(run.rec, run)
            if rec is None:
                code = 4
            else:
                with open(out, "w", encoding="utf-8") as f:
                    json.dump(rec, f, indent=1)
                    f.write("\n")
                where = "traffic.json" if os.path.abspath(out_dir) == HERE else out
                print(f"wrote {where}; no project, namespace, user, organization or host name is recorded; exit {code}")
    return code


if __name__ == "__main__":
    sys.exit(main())
