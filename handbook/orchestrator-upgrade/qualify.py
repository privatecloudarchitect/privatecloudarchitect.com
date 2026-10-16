#!/usr/bin/env python3
"""qualify.py: run your own actions on the runtime you are moving to, on throwaway copies, before you trust it.

An upgrade does not ask. Content keeps the runtime selector it stores and runs on the newest runtime of
that family the instance offers (measured; see the README). upgrade_risk.py says what might break; this
runs the code. For each polyglot action you name it:

  - reads the action from the source instance: its script, its inputs, and its environment's packages,
  - builds a throwaway environment on the target instance's newest runtime of that family with the same
    packages, and reports whether the install settles (a pinned package with no build for the new
    runtime fails here),
  - copies the action there, compiles it on that runtime and resolves every import it makes (loads),
  - runs the cases you give it and checks each result holds what you expect (behaves),
  - deletes everything it made and reads each object back.

Source and target can be one instance (a lab already at the target release, or production after its
upgrade) or two (read from the instance you will upgrade, run on a lab at the target release). Run it
before the production upgrade: after it, the content is already running on the new runtime.

Plan by default: reads the actions and the target's runtimes, prints what it would create, creates nothing.

Usage:
    export VRO_HOST=<source-fqdn> VRO_TOKEN=<bearer>                    # where the actions live
    export VRO_TARGET_HOST=<target-fqdn> VRO_TARGET_TOKEN=<bearer>      # default: the source
    export TLS_VERIFY=false                                             # only on a self-signed lab CA
    python3 qualify.py --module com.example.dns                          # plan, every polyglot action in a module
    python3 qualify.py --actions com.example.dns/addRecord --cases cases.json --execute --record q.json

cases.json maps an action to its cases; each names inputs by the action's own input names:
    {"com.example.dns/parseName": [{"name": "fqdn splits", "inputs": {"fqdn": "a.b.c"}, "expect": {"host": "a"}}]}
Give a case only to an action whose inputs touch nothing outside the Orchestrator; the rest are load-checked.

Exit 0 every action loaded and every case passed; 1 something did not, or a throwaway survived; 2 a call
failed; 5 unknown option.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import time
import uuid
import zipfile
from datetime import datetime, timezone
from xml.sax.saxutils import escape

import probe as P  # the throwaway mechanics: call, listing, multipart, Run (cleanup with read-back)

LOADERS = {
    "python": ("python", r'''import ast
import importlib
import json
import sys


class _Imports(ast.NodeVisitor):
    """Imports outside any try block; one inside try is optional and is not required."""

    def __init__(self):
        self.required, self.depth = set(), 0

    def visit_Try(self, node):
        self.depth += 1
        self.generic_visit(node)
        self.depth -= 1

    visit_TryStar = visit_Try

    def visit_Import(self, node):
        if not self.depth:
            self.required.update(a.name.split(".")[0] for a in node.names)

    def visit_ImportFrom(self, node):
        if not self.depth and node.level == 0 and node.module:
            self.required.add(node.module.split(".")[0])


def handler(context, inputs):
    src, name = inputs.get("source") or "", inputs.get("name") or "action"
    out = {"runtime": "Python " + sys.version.split()[0]}
    try:
        tree = ast.parse(src)
        compile(tree, name, "exec")
    except SyntaxError as e:
        out.update(compiles=False, error=f"{e.msg} (line {e.lineno})")
        return json.dumps(out)
    finder = _Imports()
    finder.visit(tree)
    missing = []
    for module in sorted(finder.required):
        try:
            importlib.import_module(module)
        except Exception as e:  # noqa: BLE001
            missing.append(f"{module}: {type(e).__name__}: {str(e)[:160]}")
    out.update(compiles=True, imports=sorted(finder.required), missing=missing)
    return json.dumps(out)
'''),
    "powershell": ("powershell", r'''function Handler($context, $inputs) {
    $tokens = $null; $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseInput([string]$inputs.source, [ref]$tokens, [ref]$errors)
    $out = [ordered]@{ runtime = "PowerShell " + $PSVersionTable.PSVersion.ToString(); compiles = (@($errors).Count -eq 0) }
    if (@($errors).Count -gt 0) { $out.error = (@($errors)[0]).Message }
    $mods = @()
    if ($ast.ScriptRequirements) { $mods += @($ast.ScriptRequirements.RequiredModules | ForEach-Object { $_.Name }) }
    foreach ($c in $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.CommandAst] }, $true)) {
        if ($c.GetCommandName() -ne 'Import-Module') { continue }
        $arg = @($c.CommandElements | Select-Object -Skip 1 | Where-Object { $_ -is [System.Management.Automation.Language.StringConstantExpressionAst] }) | Select-Object -First 1
        if ($arg) { $mods += $arg.Value }
    }
    $mods = @($mods | Sort-Object -Unique)
    $out.imports = $mods
    $out.missing = @($mods | Where-Object { -not (Get-Module -ListAvailable -Name $_) })
    return ($out | ConvertTo-Json -Compress -Depth 3)
}
'''),
}
LOADERS["powercli"] = ("powercli", LOADERS["powershell"][1])

JS_HELPERS = r'''
function toJson(v) {
    if (v === null || v === undefined) return "null";
    if (typeof v === "string") return JSON.stringify(v);
    if (typeof v === "number" || typeof v === "boolean") return String(v);
    if (v instanceof Array) { var a = []; for (var i = 0; i < v.length; i++) a.push(toJson(v[i])); return "[" + a.join(",") + "]"; }
    if (typeof v.keys !== "undefined" && typeof v.get === "function") {
        var keys = v.keys, parts = [];
        for (var j = 0; j < keys.length; j++) parts.push(JSON.stringify(String(keys[j])) + ":" + toJson(v.get(keys[j])));
        return "{" + parts.join(",") + "}";
    }
    try { var s = JSON.stringify(v); if (s !== undefined && s !== "{}") return s; } catch (e) {}
    return JSON.stringify(String(v));
}
function props(o) {
    if (o === null || typeof o !== "object") return o;
    if (o instanceof Array) { var a = []; for (var i = 0; i < o.length; i++) a.push(props(o[i])); return a; }
    var p = new Properties();
    for (var k in o) p.put(k, props(o[k]));
    return p;
}
var out = {};
'''


class Endpoint:
    """One instance. probe.py's helpers read module-level HOST and TOKEN, so each call switches to this one."""

    def __init__(self, host: str, token: str) -> None:
        self.host, self.token = host, token

    def use(self) -> "Endpoint":
        P.HOST, P.TOKEN = self.host, self.token
        return self

    def call(self, *args, **kwargs):
        self.use()
        return P.call(*args, **kwargs)

    def listing(self, path: str) -> list[dict]:
        self.use()
        return P.listing(path)


def family(selector: str | None) -> str:
    return (selector or "").split(":", 1)[0].lower()


def newest(offered: list[str], fam: str) -> str | None:
    cands = [s for s in offered if family(s) == fam]
    return max(cands, key=lambda s: tuple(int(n) for n in re.findall(r"\d+", s))) if cands else None


def contains(actual, expect) -> bool:
    if isinstance(expect, dict):
        return isinstance(actual, dict) and all(k in actual and contains(actual[k], v) for k, v in expect.items())
    return actual == expect


def action_zip(name: str, script: str, env_id: str, params: list[tuple[str, str]], result_type: str) -> bytes:
    """A copy of an action: its script and declared inputs, bound to the throwaway environment, a fresh id."""
    param_xml = "".join(f'  <param n="{escape(n)}" t="{escape(t)}"><![CDATA[]]></param>\n' for n, t in params)
    xml = ("<?xml version='1.0' encoding='UTF-8'?>\n"
           f'<dunes-script-module name="{name}" result-type="{escape(result_type or "Any")}" api-version="6.0.0" '
           f'id="{uuid.uuid4()}" version="0.0.1" allowed-operations="vef">\n'
           "  <description>Throwaway qualification copy; deleted by the run that created it.</description>\n"
           f"  <environment>{env_id}</environment>\n{param_xml}"
           f'  <script encoded="false">{escape(script)}</script>\n</dunes-script-module>\n')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("action-info", P._info("action"))
        z.writestr("action-content", xml.encode("utf-16"))
    return buf.getvalue()


def workflow_zip(wf_id: str, name: str, script: str) -> bytes:
    body = script.replace("]]>", "]]]]><![CDATA[>")
    xml = ('<?xml version="1.0" encoding="utf-8"?>\n'
           '<workflow xmlns="http://vmware.com/vco/workflow" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
           'xsi:schemaLocation="http://vmware.com/vco/workflow http://vmware.com/vco/workflow/Workflow-v4.xsd" '
           f'root-name="item0" object-name="workflow:name=generic" id="{wf_id}" version="0.0.1" api-version="6.0.0" '
           'restartMode="1" resumeFromFailedMode="0">\n'
           f"  <display-name><![CDATA[{name}]]></display-name>\n  <position y=\"50.0\" x=\"100.0\"/>\n  <input/>\n"
           '  <output><param name="report" type="string"/></output>\n'
           '  <workflow-item name="item0" out-name="item1" type="task">\n'
           "    <display-name><![CDATA[qualify]]></display-name>\n"
           f'    <script encoded="false"><![CDATA[{body}]]></script>\n    <in-binding/>\n'
           '    <out-binding><bind name="report" type="string" export-name="report"/></out-binding>\n'
           '    <position y="60.0" x="200.0"/>\n  </workflow-item>\n'
           '  <workflow-item name="item1" type="end" end-mode="0"><position y="60.0" x="360.0"/></workflow-item>\n'
           "</workflow>\n")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("workflow-info", P._info("workflow"))
        z.writestr("workflow-content", xml.encode("utf-16"))
    return buf.getvalue()


def read_actions(src: Endpoint, fqns: list[str], module: str | None) -> list[dict]:
    """Every named polyglot action, with what a copy needs. A JavaScript action has no runtime and is skipped."""
    rows = src.listing("/actions")
    wanted = [r for r in rows if r.get("fqn") in fqns or (module and str(r.get("fqn", "")).startswith(module + "/"))]
    missing = sorted(set(fqns) - {r.get("fqn") for r in wanted})
    if missing:
        P._fail(2, f"not found on the source: {', '.join(missing)}")
    out = []
    for r in wanted:
        status, a, _ = src.call("GET", f"/actions/{r['id']}")
        if status != 200 or not isinstance(a, dict):
            P._fail(2, f"GET /actions/{r['id']} answered {status}")
        env = None
        if a.get("actionEnvironmentId"):
            _, env, _ = src.call("GET", f"/environments/{a['actionEnvironmentId']}")
            env = env if isinstance(env, dict) else None
        selector = a.get("runtime") or (env or {}).get("runtime")
        if not selector:
            continue
        out.append({
            "fqn": a.get("fqn") or f"{a.get('module')}/{a.get('name')}", "name": a.get("name"),
            "script": a.get("script") or "", "selector": selector, "family": family(selector),
            "environment": (env or {}).get("name"), "dependencies": dict((env or {}).get("dependencies") or {}),
            "memory": int((env or {}).get("runtimeMemoryLimit") or a.get("runtimeMemoryLimit") or 0),
            "params": [(p.get("name"), p.get("type")) for p in a.get("input-parameters") or []],
            "result": a.get("output-type") or "Any",
        })
    return out


def main() -> int:
    class Parser(argparse.ArgumentParser):
        def error(self, message):
            self.print_usage(sys.stderr)
            print(f"qualify.py: {message}", file=sys.stderr)
            sys.exit(5)

    ap = Parser(description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--actions", nargs="+", metavar="MODULE/NAME", help="actions to qualify, by full name")
    g.add_argument("--module", help="qualify every polyglot action in this module")
    ap.add_argument("--cases", help="JSON file of smoke cases by action full name")
    ap.add_argument("--execute", action="store_true", help="create, run, report, delete (default: plan only)")
    ap.add_argument("--record", help="write the result as JSON (action names, statuses, findings)")
    ap.add_argument("--timeout", type=int, default=900, help="seconds for each install and for the run (default 900)")
    a = ap.parse_args()

    src = Endpoint(os.environ.get("VRO_HOST", ""), os.environ.get("VRO_TOKEN", ""))
    dst = Endpoint(os.environ.get("VRO_TARGET_HOST") or src.host, os.environ.get("VRO_TARGET_TOKEN") or src.token)
    cases_by_fqn = json.load(open(a.cases)) if a.cases else {}
    actions = read_actions(src, a.actions or [], a.module)
    if not actions:
        P._fail(2, "no polyglot action matched")
    _, about, _ = dst.call("GET", "/about")
    status, rt, _ = dst.call("GET", "/server-configuration/polyglot-runtimes")
    offered = list((rt or {}).get("o11n-polyglot-runtime") or []) if isinstance(rt, dict) else []
    print(f"target orchestrator {(about or {}).get('version') if isinstance(about, dict) else '?'}; runtimes {', '.join(offered)}")

    # One throwaway environment per distinct source environment (family and packages), on the target's newest.
    groups: dict[tuple, list[dict]] = {}
    for act in actions:
        act["target"] = newest(offered, act["family"])
        key = (act["family"], act["environment"] or f"inline:{act['selector']}", json.dumps(act["dependencies"], sort_keys=True))
        groups.setdefault(key, []).append(act)
    for (fam, envname, deps), acts in groups.items():
        target = acts[0]["target"]
        print(f"  {envname} [{acts[0]['selector']} here -> {target or 'no ' + fam + ' runtime'} there], "
              f"{len(json.loads(deps))} package(s): " + ", ".join(
                  f"{x['fqn']}{' (+' + str(len(cases_by_fqn.get(x['fqn'], []))) + ' cases)' if x['fqn'] in cases_by_fqn else ''}"
                  for x in acts))
    if not a.execute:
        print("\nplan only: nothing created. Add --execute to copy, build, load, run and delete.")
        return 0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    prefix, module = f"pcaqual_{stamp}", f"com.pcaqual.q{stamp}"
    run = P.Run()
    result: dict = {"target": (about or {}).get("version") if isinstance(about, dict) else None,
                    "measuredAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "environments": [], "actions": {}}
    rc = 0
    dst.use()
    try:
        status, cat, _ = dst.call("POST", "/categories", json.dumps({"name": module, "type": "ScriptModuleCategory"}).encode(), "application/json")
        if status not in (200, 201) or not isinstance(cat, dict):
            raise RuntimeError(f"module create answered {status}")
        run.add("action module", cat["id"], f"/categories/{cat['id']}")
        calls = []
        expects: dict[str, object] = {}
        for i, ((fam, envname, deps), acts) in enumerate(groups.items()):
            target = acts[0]["target"]
            if not target:
                for x in acts:
                    result["actions"][x["fqn"]] = {"loads": "skipped", "detail": f"no {fam} runtime on the target"}
                continue
            body = {"name": f"{prefix}_{i}", "runtime": target, "version": "1.0.0", "description": "Throwaway qualification",
                    "runtimeMemoryLimit": max(a_["memory"] for a_ in acts), "runtimeTimeout": 180, "dependencies": json.loads(deps)}
            status, env, _ = dst.call("POST", "/environments", json.dumps(body).encode(), "application/json")
            if status not in (200, 201) or not isinstance(env, dict):
                raise RuntimeError(f"environment create answered {status}: {str(env)[:200]}")
            run.add(f"environment {i}", env["id"], f"/environments/{env['id']}")
            t0, last, settled = time.time(), None, None
            while time.time() - t0 <= a.timeout:
                _, d, _ = dst.call("GET", f"/environments/{env['id']}")
                st = str((d or {}).get("status") if isinstance(d, dict) else "")
                if st != last:
                    print(f"  environment for {envname}: {st} after {round(time.time() - t0)}s")
                    last = st
                # STALE_BUNDLE is where an install settles when a package does not install on the runtime
                # (measured: pykerberos on python:3.14 reached it in 11 s and held it); it ends the wait.
                if st == "UP_TO_DATE" or any(w in st for w in ("FAIL", "ERROR", "STALE")):
                    settled = st
                    break
                time.sleep(10)
            built = settled == "UP_TO_DATE"
            result["environments"].append({"source": envname, "target": target, "packages": json.loads(deps),
                                           "install": settled or f"still {last} after {a.timeout}s"})
            if not built:
                for x in acts:
                    result["actions"][x["fqn"]] = {"loads": "skipped", "detail": f"environment install {settled or 'did not settle'}"}
                rc = 1
                continue
            loader_fam, loader_src = LOADERS.get(fam, (None, None))
            loader = f"pcaqual_loader_{i}"
            if loader_src:
                z = action_zip(loader, loader_src, env["id"], [("source", "string"), ("name", "string")], "string")
                bdy, ctype = P.multipart({"categoryName": module}, f"{loader}.action", z)
                dst.call("POST", "/actions", bdy, ctype)
            for x in acts:
                z = action_zip(x["name"], x["script"], env["id"], x["params"], x["result"])
                bdy, ctype = P.multipart({"categoryName": module}, f"{x['name']}.action", z)
                status, _, _ = dst.call("POST", "/actions", bdy, ctype)
                if status not in (200, 201, 202, 204):
                    raise RuntimeError(f"copy of {x['fqn']} answered {status}")
                if loader_src:
                    calls.append(f'try {{ out["loads:{x["fqn"]}"] = String(System.getModule("{module}").{loader}('
                                 f'{json.dumps(x["script"])}, {json.dumps(x["name"])})); }} '
                                 f'catch (e) {{ out["loads:{x["fqn"]}"] = "ERROR: " + e; }}')
                order = [n for n, _ in x["params"]]
                for n, case in enumerate(cases_by_fqn.get(x["fqn"], [])):
                    args = ", ".join(f"props({json.dumps((case.get('inputs') or {}).get(k))})" for k in order)
                    calls.append(f'try {{ out["case:{x["fqn"]}:{n}"] = toJson(System.getModule("{module}").{x["name"]}({args})); }} '
                                 f'catch (e) {{ out["case:{x["fqn"]}:{n}"] = "ERROR: " + e; }}')
                    expects[f"case:{x['fqn']}:{n}"] = case.get("expect") or {}
        for row in dst.listing("/actions"):
            if str(row.get("fqn", "")).startswith(module + "/"):
                run.add(f"action {row.get('name')}", row["id"], f"/actions/{row['id']}")
        if calls:
            status, folder, _ = dst.call("POST", "/categories", json.dumps({"name": prefix, "type": "WorkflowCategory"}).encode(), "application/json")
            run.add("workflow folder", folder["id"], f"/categories/{folder['id']}")
            wf_id = str(uuid.uuid4())
            bdy, ctype = P.multipart({}, "qualify.workflow", workflow_zip(wf_id, f"{prefix} qualification",
                                                                          JS_HELPERS + "\n".join(calls) + "\nreport = JSON.stringify(out);"))
            status, _, _ = dst.call("POST", f"/workflows?categoryId={folder['id']}", bdy, ctype)
            if status not in (200, 201, 202):
                raise RuntimeError(f"workflow import answered {status}")
            run.add("workflow", wf_id, f"/workflows/{wf_id}")
            status, _, hdrs = dst.call("POST", f"/workflows/{wf_id}/executions", json.dumps({"parameters": []}).encode(), "application/json")
            exec_id = (hdrs.get("Location") or hdrs.get("location") or "").rstrip("/").rsplit("/", 1)[-1]
            t0, state = time.time(), "RUNNING"
            while state not in ("completed", "failed", "canceled") and time.time() - t0 < a.timeout:
                _, s, _ = dst.call("GET", f"/workflows/{wf_id}/executions/{exec_id}/state")
                state = s.get("value", state) if isinstance(s, dict) else state
                if state not in ("completed", "failed", "canceled"):
                    time.sleep(5)
            _, ex, _ = dst.call("GET", f"/workflows/{wf_id}/executions/{exec_id}")
            report = {}
            for p in (ex or {}).get("output-parameters") or [] if isinstance(ex, dict) else []:
                if p.get("name") == "report":
                    report = json.loads(((p.get("value") or {}).get("string") or {}).get("value") or "{}")
            for x in actions:
                if x["fqn"] in result["actions"]:
                    continue
                entry: dict = {"selector": x["selector"], "target": x["target"]}
                raw = report.get(f"loads:{x['fqn']}")
                try:
                    got = json.loads(raw) if raw else None
                except ValueError:
                    got = None
                if got is None and not LOADERS.get(x["family"]):
                    entry.update(loads="skipped", detail=f"no loader for {x['family']}; cases are the proof")
                elif got is None:
                    entry.update(loads="fail", detail=raw or "no result")
                else:
                    problems = ([f"does not compile: {got.get('error')}"] if not got.get("compiles") else []) + list(got.get("missing") or [])
                    entry.update(loads="fail" if problems else "pass", ran_on=got.get("runtime"), findings=problems)
                fails = []
                for key, expect in expects.items():
                    if key.startswith(f"case:{x['fqn']}:"):
                        try:
                            actual = json.loads(report.get(key) or "null")
                        except ValueError:
                            actual = report.get(key)
                        if not contains(actual, expect):
                            fails.append(f"{key.rsplit(':', 1)[-1]}: expected {json.dumps(expect)}, got {json.dumps(actual)[:240]}")
                ncases = len(cases_by_fqn.get(x["fqn"], []))
                entry["behaves"] = ("fail" if fails else "pass") if ncases else "no cases"
                entry["case_failures"] = fails
                result["actions"][x["fqn"]] = entry
                if entry["loads"] == "fail" or fails:
                    rc = 1
    except RuntimeError as e:
        print(f"  stopped: {e}")
        rc = 2
    finally:
        print("\ncleanup:")
        dst.use()
        left = run.cleanup()
        dst.use()
        residue = [e.get("name") for e in dst.listing("/environments") if str(e.get("name")).startswith(prefix)]
        residue += [c.get("name") for c in dst.listing("/categories") if str(c.get("name")) in (prefix, module)]
        result["residue"] = left + residue
        print(f"  residue: {result['residue'] or 'none'}")
        if result["residue"]:
            rc = 1

    print("\nresults:")
    for env in result["environments"]:
        print(f"  environment from {env['source']} on {env['target']}: install {env['install']}")
    for fqn, e in result["actions"].items():
        print(f"  {fqn}: loads {e.get('loads')}" + (f" on {e['ran_on']}" if e.get("ran_on") else "")
              + f"; behaves {e.get('behaves', '-')}" + (f"  ({e['detail']})" if e.get("detail") else ""))
        for f in (e.get("findings") or []) + (e.get("case_failures") or []):
            print(f"      {f}")
    if a.record:
        with open(a.record, "w") as f:
            json.dump(result, f, indent=1, sort_keys=True)
            f.write("\n")
        print(f"\nrecord written: {a.record}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
