#!/usr/bin/env python3
"""probe.py: measure what each runtime on your Orchestrator actually provides, on throwaway objects.

Run it on the instance you upgrade from and again on the instance you upgrade to, then compare the
two records with `upgrade_risk.py --compare`. An upgrade does not rewrite the runtime an environment
or an action names, so the questions that decide whether your content survives are measured here
rather than read from a page:

  - which runtime selectors the instance offers (read-only; printed in plan mode too)
  - the Python version and every installed distribution, under the newest Python selector
  - the PowerShell version and every module Get-Module -ListAvailable lists, under the newest
    PowerCLI selector
  - which modern and legacy JavaScript constructs the scripting engine accepts, one line each,
    with the value each returns, because a construct can parse on both engines and answer
    differently
  - what an action does when its environment names a selector the instance does not offer, for
    Python and for PowerCLI: whether that environment can be created, what it reports, and which
    runtime a run of the action lands on

Plan by default: it reads the runtime list and prints every object it would create; it creates
nothing. With --execute it creates, under one throwaway name, up to four action environments,
five actions in a new action module, and one workflow in a new workflow folder; runs the workflow
once; prints the report; deletes every object it created; and reads each one back to prove it is
gone. Of what existed before, it reads only the about endpoint, the runtime list, and the names of
categories and environments (to refuse a name that already exists).

Usage:
    export VRO_HOST=orchestrator.example.net
    export VRO_TOKEN=<a bearer this appliance accepts>
    export TLS_VERIFY=false                      # only on a self-signed lab CA
    python3 probe.py                             # plan
    python3 probe.py --execute                   # create, run, report, delete, residue check
    python3 probe.py --execute --record probe-9.1.1.json

Exit 0 every step answered and nothing was left behind; 1 an object it created is still there
(its id is printed); 2 a call failed; 5 unknown option.
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
from datetime import datetime, timezone
from urllib import error as _er
from urllib import request as _rq
from xml.sax.saxutils import escape

HOST = os.environ.get("VRO_HOST", "")
TOKEN = os.environ.get("VRO_TOKEN", "")
BASE = "/vco/api"
CTX = ssl.create_default_context()
if os.environ.get("TLS_VERIFY", "true").lower() in ("0", "false", "no"):
    CTX.check_hostname = False
    CTX.verify_mode = ssl.CERT_NONE

# A selector the upgrade leaves behind. The first of these the instance does NOT offer is used for
# the stale-environment test: on 9.1.1 that is python:3.11 (what 9.1.0 offered), on 9.1.0 it is
# python:3.10 (the selector older content carries).
STALE_CANDIDATES = ("python:3.11", "python:3.10")
# The same test for PowerCLI: on 9.1.1 the selector 9.1.0 offered, on 9.1.0 the PowerCLI 13 one.
STALE_PS_CANDIDATES = ("powercli:9.0.0-powershell-7.4", "powercli:13-powershell-7.4")

PY_PROBE = r'''import json
import platform
import sys


def handler(context, inputs):
    out = {"python": sys.version.split()[0], "implementation": platform.python_implementation()}
    try:
        from importlib import metadata as md
        out["distributions"] = sorted(f"{d.metadata['Name']}=={d.version}" for d in md.distributions())
    except Exception as e:  # noqa: BLE001
        out["distributions_error"] = f"{type(e).__name__}: {e}"
    # In Python the context arrives as a dict, so getToken is a key holding a callable, not an
    # attribute. Only the key names and whether a token came back are recorded, never a value.
    out["contextType"] = type(context).__name__
    out["contextKeys"] = sorted(context) if isinstance(context, dict) else sorted(k for k in dir(context) if not k.startswith("_"))
    try:
        fn = context["getToken"] if isinstance(context, dict) else context.getToken
        tok = fn()
        out["getToken"] = {"ok": bool(tok), "type": type(tok).__name__}
    except Exception as e:  # noqa: BLE001
        out["getToken"] = {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}
    return json.dumps(out)
'''

PS_PROBE = r'''function Handler($context, $inputs) {
    $mods = Get-Module -ListAvailable | Sort-Object Name, Version -Unique | ForEach-Object { "$($_.Name)==$($_.Version)" }
    # Import the names older scripts use. A name that is not installed fails here exactly as it
    # would in your action; VMware.VimAutomation.Core is the module most PowerCLI scripts load.
    $imports = [ordered]@{}
    foreach ($name in @("VMware.PowerCLI", "PowerNSX", "PowervRA", "VMware.VimAutomation.Core")) {
        $t0 = Get-Date
        try {
            Import-Module $name -ErrorAction Stop | Out-Null
            $imports[$name] = "ok in {0:N1}s" -f ((Get-Date) - $t0).TotalSeconds
        } catch {
            $imports[$name] = "FAIL: " + $_.Exception.Message.Substring(0, [Math]::Min(140, $_.Exception.Message.Length))
        }
    }
    $out = @{
        powershell = $PSVersionTable.PSVersion.ToString()
        edition    = $PSVersionTable.PSEdition
        modules    = @($mods)
        imports    = $imports
    }
    return ($out | ConvertTo-Json -Depth 3 -Compress)
}
'''

# Each construct is compiled inside eval(), so one the engine rejects cannot mask the others. The
# value matters as much as ok or FAIL: let_loop_closure answers 0 under block scoping and 2 without.
JS_PROBE = r'''var probes = {
    "let_const": "let a = 1; const b = 2; a + b",
    "let_loop_closure": "var fs = []; for (let i = 0; i < 2; i++) { fs.push(function () { return i; }); } fs[0]()",
    "arrow_function": "var f = (x) => x * 2; f(21)",
    "template_literal": "var n = 'vro'; `hello ${n}`",
    "class_declaration": "class A { constructor(v) { this.v = v; } get d() { return this.v * 2; } } new A(2).d",
    "class_extends": "class B { static s() { return 1; } } class C extends B {} C.s()",
    "destructuring": "var {p, q} = {p: 1, q: 2}; var [r, s] = [3, 4]; p + q + r + s",
    "spread_array": "var x = [1, 2]; [...x, 3].length",
    "spread_object": "var o = {a: 1}; ({...o, b: 2}).b",
    "default_params": "function g(a, b = 5) { return a + b; } g(1)",
    "rest_params": "function h(...xs) { return xs.length; } h(1, 2, 3)",
    "for_of": "var t = 0; for (var v of [1, 2, 3]) { t += v; } t",
    "map_set": "new Map([[1, 'a']]).get(1) + new Set([1, 1, 2]).size",
    "symbol": "typeof Symbol('x')",
    "generator": "function* gen() { yield 1; yield 2; } var it = gen(); it.next().value + it.next().value",
    "promise": "typeof Promise",
    "async_await": "async function af() { return 1; } typeof af",
    "optional_chaining": "var u = {}; u.a?.b === undefined",
    "nullish_coalescing": "null ?? 'd'",
    "exponent_operator": "2 ** 10",
    "array_includes": "[1, 2, 3].includes(2)",
    "object_entries": "Object.entries({k: 1}).length",
    "string_padstart": "'5'.padStart(3, '0')",
    "array_flat": "[[1], [2]].flat().length",
    "object_fromentries": "Object.fromEntries([['k', 1]]).k",
    "string_replaceall": "'a-b-c'.replaceAll('-', '+')",
    "array_at": "[1, 2, 3].at(-1)",
    "logical_assignment": "var la = null; la ??= 7; la",
    "numeric_separator": "1_000",
    "bigint": "typeof 10n",
    "regex_named_groups": "'2026-09'.match(/(?<y>\\d{4})-(?<m>\\d{2})/).groups.y",
    "regex_lookbehind": "'a1'.match(/(?<=a)\\d/)[0]",
    "computed_property": "var k = 'z'; ({[k]: 1}).z",
    "shorthand_method": "({m() { return 1; }}).m()",
    "json_roundtrip": "JSON.parse(JSON.stringify({a: [1, 2]})).a.length",
    "e4x_xml_literal": "new XML('<a><b>1</b></a>').b.toString()",
    "for_each_in": "var fe = 0; for each (var w in [1, 2]) { fe += w; } fe",
    "define_getter": "var dg = {}; dg.__defineGetter__('x', function () { return 1; }); dg.x",
    "proto_property": "({}).__proto__ === Object.prototype",
    "date_slash_format": "new Date('2026/10/16').getFullYear()",
    "java_system_property": "String(java.lang.System.getProperty('java.version'))"
};
var results = {};
for (var name in probes) {
    try {
        results[name] = "ok: " + String(eval(probes[name]));
    } catch (e) {
        results[name] = "FAIL: " + String(e).substring(0, 160);
    }
}
var engine = "unavailable";
try {
    engine = String(java.lang.Package.getPackage("org.mozilla.javascript").getImplementationVersion());
} catch (e2) {
    engine = "unavailable: " + String(e2).substring(0, 120);
}
return JSON.stringify({engine: engine, features: results});
'''

# Error-bound attribute names, one per probe, so a probe that throws still lets the next one run.
PROBES = ("js", "py_current", "py_stale", "powercli", "ps_stale")


def _fail(code: int, msg: str):
    print(msg, file=sys.stderr)
    sys.exit(code)


def call(method: str, path: str, body: bytes | None = None, ctype: str | None = None,
         ok: tuple[int, ...] = (200, 201, 202, 204)) -> tuple[int, dict | str, dict]:
    if not HOST or not TOKEN:
        _fail(2, "set VRO_HOST and VRO_TOKEN first")
    headers = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"}
    if ctype:
        headers["Content-Type"] = ctype
    req = _rq.Request(f"https://{HOST}{BASE}{path}", data=body, method=method, headers=headers)
    for attempt in range(6):
        try:
            with _rq.urlopen(req, context=CTX, timeout=120) as r:
                raw = r.read().decode("utf-8", "replace")
                status, hdrs = r.status, dict(r.headers)
            break
        except _er.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            status, hdrs = e.code, dict(e.headers)
            break
        except (_er.URLError, ConnectionError, TimeoutError) as e:
            # A refused or dropped connection is retried with a growing pause; a run that loses the
            # appliance for good still reaches cleanup, and cleanup retries the same way.
            if attempt == 5:
                return 0, f"connection failed: {getattr(e, 'reason', e)}", {}
            time.sleep(5 * (attempt + 1))
    try:
        parsed: dict | str = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        # An error page: keep its words, drop its styles and scripts, so the reason is readable.
        text = re.sub(r"(?is)<(style|script)[^>]*>.*?</\1>", " ", raw)
        parsed = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()[:400]
    if status not in ok:
        return status, parsed, hdrs
    return status, parsed, hdrs


def listing(path: str) -> list[dict]:
    status, j, _ = call("GET", path)
    if status != 200 or not isinstance(j, dict):
        _fail(2, f"GET {path} answered {status}")
    return [{a["name"]: a.get("value") for a in li.get("attributes", [])} for li in j.get("link", [])]


def multipart(fields: dict[str, str], filename: str, data: bytes) -> tuple[bytes, str]:
    boundary = "pcaprobe" + uuid.uuid4().hex
    out = io.BytesIO()
    for k, v in fields.items():
        out.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    out.write(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
              f"Content-Type: application/zip\r\n\r\n".encode())
    out.write(data)
    out.write(f"\r\n--{boundary}--\r\n".encode())
    return out.getvalue(), f"multipart/form-data; boundary={boundary}"


def _info(kind: str) -> bytes:
    stamp = datetime.now(timezone.utc).strftime("%a %b %d %H:%M:%S GMT %Y")
    return (f"#\n#{stamp}\nowner=\ncharset=UTF-16\ncreator=www.dunes.ch\nunicode=true\n"
            f"type={kind}\nversion=2.0\n").encode("latin-1")


def action_zip(name: str, action_id: str, script: str, env_id: str | None) -> bytes:
    """The .action archive: a properties file and a UTF-16 XML body. An action bound to an
    environment names it by identifier; a JavaScript action names none."""
    env = f"  <environment>{env_id}</environment>\n" if env_id else ""
    xml = ("<?xml version='1.0' encoding='UTF-8'?>\n"
           f'<dunes-script-module name="{name}" result-type="string" api-version="6.0.0" '
           f'id="{action_id}" version="0.0.1" allowed-operations="vef">\n'
           f"  <description>Throwaway upgrade probe; deleted by the run that created it.</description>\n"
           f"{env}  <script encoded=\"false\">{escape(script)}</script>\n</dunes-script-module>\n")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("action-info", _info("action"))
        z.writestr("action-content", xml.encode("utf-16"))
    return buf.getvalue()


def workflow_zip(wf_id: str, name: str, module: str) -> bytes:
    """One workflow: four action elements, each with an error handler that records the error and
    moves on, then a script that gathers every result into the output `report`."""
    attribs = "".join(
        f'  <attrib name="{p}" type="string" read-only="false"><value encoded="n"><![CDATA[]]></value></attrib>\n'
        f'  <attrib name="{p}_error" type="string" read-only="false"><value encoded="n"><![CDATA[]]></value></attrib>\n'
        for p in PROBES)
    items, y = [], 50
    for i, p in enumerate(PROBES):
        nxt = f"item{i + 1}"
        items.append(
            f'  <workflow-item name="item{i}" out-name="{nxt}" catch-name="{nxt}" throw-bind-name="{p}_error" '
            f'type="task" script-module="{module}/probe_{p}">\n'
            f"    <display-name><![CDATA[probe_{p}]]></display-name>\n"
            f'    <script encoded="false"><![CDATA[//Auto generated script, cannot be modified !\n'
            f"actionResult = System.getModule(\"{module}\").probe_{p}() ;]]></script>\n"
            f'    <in-binding/>\n    <out-binding><bind name="actionResult" type="string" export-name="{p}"/></out-binding>\n'
            f'    <position y="{y}.0" x="{180 + 120 * i}.0"/>\n  </workflow-item>\n')
    binds = "".join(f'      <bind name="{p}" type="string" export-name="{p}"/>\n'
                    f'      <bind name="{p}_error" type="string" export-name="{p}_error"/>\n' for p in PROBES)
    gather = "var r = {};\n" + "".join(
        f'r["{p}"] = {p} || null;\nr["{p}_error"] = {p}_error || null;\n' for p in PROBES) + "report = JSON.stringify(r);\n"
    n = len(PROBES)
    items.append(
        f'  <workflow-item name="item{n}" out-name="item{n + 1}" type="task">\n'
        f"    <display-name><![CDATA[gather]]></display-name>\n"
        f'    <script encoded="false"><![CDATA[{gather}]]></script>\n'
        f"    <in-binding>\n{binds}    </in-binding>\n"
        f'    <out-binding><bind name="report" type="string" export-name="report"/></out-binding>\n'
        f'    <position y="{y}.0" x="{180 + 120 * n}.0"/>\n  </workflow-item>\n'
        f'  <workflow-item name="item{n + 1}" type="end" end-mode="0">\n'
        f'    <position y="{y}.0" x="{180 + 120 * (n + 1)}.0"/>\n  </workflow-item>\n')
    xml = ('<?xml version="1.0" encoding="utf-8"?>\n'
           '<workflow xmlns="http://vmware.com/vco/workflow" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
           'xsi:schemaLocation="http://vmware.com/vco/workflow http://vmware.com/vco/workflow/Workflow-v4.xsd" '
           f'root-name="item0" object-name="workflow:name=generic" id="{wf_id}" version="0.0.1" '
           'api-version="6.0.0" restartMode="1" resumeFromFailedMode="0">\n'
           f"  <display-name><![CDATA[{name}]]></display-name>\n"
           '  <position y="50.0" x="100.0"/>\n  <input/>\n'
           '  <output><param name="report" type="string"/></output>\n'
           f"{attribs}{''.join(items)}</workflow>\n")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("workflow-info", _info("workflow"))
        z.writestr("workflow-content", xml.encode("utf-16"))
    return buf.getvalue()


def newest(names: list[str], family: str) -> str | None:
    cands = [n for n in names if n.lower().startswith(family + ":")]
    return sorted(cands, key=lambda n: tuple(int(x) for x in re.findall(r"\d+", n)))[-1] if cands else None


def read_runtimes() -> tuple[list[str], dict]:
    status, j, _ = call("GET", "/server-configuration/polyglot-runtimes")
    if status != 200 or not isinstance(j, dict):
        _fail(2, f"GET /server-configuration/polyglot-runtimes answered {status}")
    return list(j.get("o11n-polyglot-runtime") or []), j.get("o11n-polyglot-default-runtime-memory-limit") or {}


def wait_env(env_id: str, limit: int = 600) -> dict:
    """An environment installs its dependencies after it is created and reports `status` while it
    does; an action run before that ends is not a measurement of the runtime. With no dependencies
    the status is UP_TO_DATE at once and no bundle hash is ever written."""
    t0 = time.time()
    while True:
        _, d, _ = call("GET", f"/environments/{env_id}")
        d = d if isinstance(d, dict) else {}
        status = str(d.get("status") or "")
        if status and status not in ("IN_PROGRESS", "PENDING", "INSTALLING", "BUILDING"):
            return d
        if time.time() - t0 > limit:
            return d
        time.sleep(5)


class Run:
    """Every object this run creates, in creation order, so cleanup can walk it backwards."""

    def __init__(self) -> None:
        self.created: list[tuple[str, str, str]] = []   # (kind, id, path)

    def add(self, kind: str, oid: str, path: str) -> None:
        self.created.append((kind, oid, path))

    def cleanup(self) -> list[str]:
        left = []
        for kind, oid, path in reversed(self.created):
            status, body, _ = call("DELETE", path, ok=(200, 202, 204, 404))
            if status not in (200, 202, 204, 404):
                status, body, _ = call("DELETE", path + ("&" if "?" in path else "?") + "force=true",
                                       ok=(200, 202, 204, 404))
            gone, _, _ = call("GET", path.split("?")[0], ok=(404,))
            print(f"  delete {kind:<22} {status}  read back {gone}")
            if gone != 404:
                left.append(f"{kind} {oid}")
        return left


def main() -> int:
    class P(argparse.ArgumentParser):
        def error(self, message):  # unknown option: exit 5, the companions' contract
            self.print_usage(sys.stderr)
            print(f"probe.py: {message}", file=sys.stderr)
            sys.exit(5)

    ap = P(description=__doc__.split("\n")[0])
    ap.add_argument("--execute", action="store_true", help="create, run, report, delete (default: plan only)")
    ap.add_argument("--record", help="write the measured result as JSON to this file")
    ap.add_argument("--timeout", type=int, default=900, help="seconds to wait for the run (default 900)")
    a = ap.parse_args()

    _, about, _ = call("GET", "/about")
    version = about.get("version") if isinstance(about, dict) else None
    names, mem = read_runtimes()
    py_cur, ps_cur = newest(names, "python"), newest(names, "powercli")
    stale = next((s for s in STALE_CANDIDATES if s not in names), None)
    ps_stale = next((s for s in STALE_PS_CANDIDATES if s not in names), None)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    prefix = f"pcaprobe_{stamp}"
    module = f"com.pcaprobe.p{stamp}"

    print(f"orchestrator {version}")
    print(f"runtimes offered: {', '.join(names) or '(none)'}")
    print(f"default memory limits: {json.dumps(mem, sort_keys=True)}")
    plan = [("environment", f"{prefix}_py_current", py_cur), ("environment", f"{prefix}_py_stale", stale),
            ("environment", f"{prefix}_powercli", ps_cur), ("environment", f"{prefix}_ps_stale", ps_stale),
            ("action module", module, None),
            ("action", f"{module}/probe_js", "javascript"), ("action", f"{module}/probe_py_current", py_cur),
            ("action", f"{module}/probe_py_stale", stale), ("action", f"{module}/probe_powercli", ps_cur),
            ("action", f"{module}/probe_ps_stale", ps_stale),
            ("workflow folder", prefix, None), ("workflow", f"{prefix} upgrade probe", None)]
    print("\nwould create, in this order:" if not a.execute else "\ncreating, in this order:")
    for kind, name, rt in plan:
        if rt is None and kind in ("environment",):
            print(f"  {kind:<16} {name}  (skipped: no selector to test)")
            continue
        print(f"  {kind:<16} {name}" + (f"  [{rt}]" if rt else ""))
    if not a.execute:
        print("\nplan only: nothing created. Add --execute to create, run, report and delete.")
        return 0

    taken = {e.get("name") for e in listing("/environments")} | {c.get("name") for c in listing("/categories")}
    if prefix in taken or module in taken or any(str(n).startswith(prefix) for n in taken):
        _fail(2, f"refusing: an object named {prefix}* already exists")

    run = Run()
    record: dict = {"orchestrator": version, "runtimes": names, "defaultMemory": mem,
                    "measuredAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "selectors": {"py_current": py_cur, "py_stale": stale, "powercli": ps_cur, "ps_stale": ps_stale}}
    rc = 0
    try:
        envs: dict[str, str | None] = {}
        for key, rt in (("py_current", py_cur), ("py_stale", stale), ("powercli", ps_cur), ("ps_stale", ps_stale)):
            if not rt:
                envs[key] = None
                continue
            body = json.dumps({"name": f"{prefix}_{key}", "runtime": rt, "version": "1.0.0",
                               "description": "Throwaway upgrade probe", "runtimeMemoryLimit": 0,
                               "runtimeTimeout": 180, "dependencies": {}}).encode()
            status, j, _ = call("POST", "/environments", body, "application/json")
            if status not in (200, 201, 202) or not isinstance(j, dict) or not j.get("id"):
                record.setdefault("environmentCreate", {})[key] = {"status": status, "answer": str(j)[:300]}
                print(f"  environment {key:<12} [{rt}] create answered {status}: {str(j)[:160]}")
                envs[key] = None
                continue
            run.add(f"environment {key}", j["id"], f"/environments/{j['id']}")
            d = wait_env(j["id"])
            record.setdefault("environments", {})[key] = {
                "runtime": d.get("runtime"), "validationMessage": d.get("validationMessage"),
                "status": d.get("status")}
            envs[key] = j["id"]
            print(f"  environment {key:<12} [{rt}] created; status {d.get('status')}, "
                  f"validationMessage {d.get('validationMessage')!r}")

        status, j, _ = call("POST", "/categories", json.dumps({"name": module, "type": "ScriptModuleCategory"}).encode(),
                            "application/json")
        if status not in (200, 201) or not isinstance(j, dict) or not j.get("id"):
            raise RuntimeError(f"action module create answered {status}: {str(j)[:200]}")
        run.add("action module", j["id"], f"/categories/{j['id']}")

        scripts = {"js": (JS_PROBE, None), "py_current": (PY_PROBE, envs.get("py_current")),
                   "py_stale": (PY_PROBE, envs.get("py_stale")), "powercli": (PS_PROBE, envs.get("powercli")),
                   "ps_stale": (PS_PROBE, envs.get("ps_stale"))}
        for key, (script, env_id) in scripts.items():
            if key != "js" and env_id is None:
                print(f"  action probe_{key:<12} skipped: its environment was not created")
                continue
            zbytes = action_zip(f"probe_{key}", str(uuid.uuid4()), script, env_id)
            body, ctype = multipart({"categoryName": module}, f"probe_{key}.action", zbytes)
            status, j, _ = call("POST", "/actions", body, ctype)
            if status not in (200, 201, 202, 204):
                raise RuntimeError(f"action probe_{key} import answered {status}: {str(j)[:200]}")
            found = [x for x in listing("/actions") if x.get("fqn") == f"{module}/probe_{key}"]
            if not found:
                raise RuntimeError(f"action probe_{key} not visible after import")
            run.add(f"action probe_{key}", found[0]["id"], f"/actions/{found[0]['id']}")
            _, ad, _ = call("GET", f"/actions/{found[0]['id']}")
            ad = ad if isinstance(ad, dict) else {}
            record.setdefault("actions", {})[key] = {"runtime": ad.get("runtime"),
                                                     "environment": ad.get("actionEnvironmentName"),
                                                     "validationMessage": ad.get("validationMessage")}
            print(f"  action probe_{key:<12} imported; validationMessage {ad.get('validationMessage')!r}")

        status, j, _ = call("POST", "/categories", json.dumps({"name": prefix, "type": "WorkflowCategory"}).encode(),
                            "application/json")
        if status not in (200, 201) or not isinstance(j, dict) or not j.get("id"):
            raise RuntimeError(f"workflow folder create answered {status}: {str(j)[:200]}")
        run.add("workflow folder", j["id"], f"/categories/{j['id']}")
        wf_id = str(uuid.uuid4())
        body, ctype = multipart({}, "probe.workflow", workflow_zip(wf_id, f"{prefix} upgrade probe", module))
        status, jw, _ = call("POST", f"/workflows?categoryId={j['id']}", body, ctype)
        if status not in (200, 201, 202):
            raise RuntimeError(f"workflow import answered {status}: {str(jw)[:200]}")
        run.add("workflow", wf_id, f"/workflows/{wf_id}")

        status, _, hdrs = call("POST", f"/workflows/{wf_id}/executions", json.dumps({"parameters": []}).encode(),
                               "application/json")
        loc = hdrs.get("Location") or hdrs.get("location") or ""
        exec_id = loc.rstrip("/").rsplit("/", 1)[-1]
        if status not in (200, 201, 202) or not exec_id:
            raise RuntimeError(f"workflow run answered {status}")
        print(f"  workflow run started; waiting up to {a.timeout}s")
        t0, state = time.time(), "running"
        while state not in ("completed", "failed", "canceled") and time.time() - t0 < a.timeout:
            time.sleep(5)
            _, s, _ = call("GET", f"/workflows/{wf_id}/executions/{exec_id}/state")
            state = s.get("value", state) if isinstance(s, dict) else state
        _, ex, _ = call("GET", f"/workflows/{wf_id}/executions/{exec_id}")
        ex = ex if isinstance(ex, dict) else {}
        report = None
        for p in ex.get("output-parameters") or []:
            if p.get("name") == "report":
                report = ((p.get("value") or {}).get("string") or {}).get("value")
        record["run"] = {"state": state, "seconds": round(time.time() - t0),
                         "exception": ex.get("content-exception")}
        parsed = json.loads(report) if report else {}
        for p in PROBES:
            val = parsed.get(p)
            try:
                record.setdefault("results", {})[p] = json.loads(val) if val else None
            except json.JSONDecodeError:
                record.setdefault("results", {})[p] = val
            record.setdefault("errors", {})[p] = parsed.get(f"{p}_error")
        print(f"  workflow run {state} in {record['run']['seconds']}s")
    except RuntimeError as e:
        print(f"  stopped: {e}")
        rc = 2
    finally:
        print("\ncleanup:")
        left = run.cleanup()
        residue = [e.get("name") for e in listing("/environments") if str(e.get("name")).startswith(prefix)]
        residue += [c.get("name") for c in listing("/categories") if str(c.get("name")) in (prefix, module)]
        record["residue"] = left + residue
        print(f"  residue: {record['residue'] or 'none'}")
        if record["residue"]:
            rc = 1

    show(record)
    if a.record:
        with open(a.record, "w") as f:
            json.dump(record, f, indent=1, sort_keys=True)
            f.write("\n")
        print(f"\nrecord written: {a.record}")
    return rc


def show(r: dict) -> None:
    res, err = r.get("results") or {}, r.get("errors") or {}
    print("\nresults:")
    js = res.get("js") or {}
    if js:
        feats = js.get("features") or {}
        ok = sum(1 for v in feats.values() if str(v).startswith("ok"))
        print(f"  javascript engine {js.get('engine')}; {ok} of {len(feats)} constructs accepted")
        for k, v in feats.items():
            print(f"    {k:<22} {v}")
    elif err.get("js"):
        print(f"  javascript probe failed: {err['js']}")
    for key in ("py_current", "py_stale"):
        sel = (r.get("selectors") or {}).get(key)
        v = res.get(key)
        if isinstance(v, dict):
            print(f"  {key:<11} [{sel}] ran on python {v.get('python')}, {len(v.get('distributions') or [])} distributions, "
                  f"getToken {json.dumps(v.get('getToken'))}")
            print(f"    context ({v.get('contextType')}) keys: {', '.join(v.get('contextKeys') or [])}")
        elif sel:
            print(f"  {key:<11} [{sel}] did not run: {err.get(key) or (r.get('environmentCreate') or {}).get(key)}")
    for key in ("powercli", "ps_stale"):
        show_ps(key, r, res, err)


def show_ps(key: str, r: dict, res: dict, err: dict) -> None:
    v = res.get(key)
    if isinstance(v, dict):
        mods = v.get("modules") or []
        print(f"  {key:<11} [{(r.get('selectors') or {}).get(key)}] ran on powershell {v.get('powershell')}, "
              f"{len(mods)} modules")
        for m in mods:
            if re.match(r"(VMware\.PowerCLI|VCF\.PowerCLI|PowerNSX|PowervRA|VMware\.Sdk\.Vcf\.|VMware\.VimAutomation\.Core)", m):
                print(f"    {m}")
        for name, outcome in (v.get("imports") or {}).items():
            print(f"    Import-Module {name:<26} {outcome}")
    elif (r.get("selectors") or {}).get(key):
        print(f"  {key:<11} did not run: {err.get(key) or (r.get('environmentCreate') or {}).get(key)}")


if __name__ == "__main__":
    sys.exit(main())
