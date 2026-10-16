#!/usr/bin/env python3
"""upgrade_risk.py: read an Orchestrator before you upgrade it, and list what the upgrade will break.

Read-only: every call is a GET. It reads every action environment, every action, every workflow
definition, the plug-ins, the plug-in hosts, scheduled tasks and policies, and checks them against
the release you are moving to. The target is either a file in targets/ (the runtimes and plug-ins a
release was measured to offer) or a live instance already on that release (--target-host).

What it checks, and why each check exists. Measured on the reference estate: an upgrade keeps the
runtime selector an environment, an action or a scriptable task stores; the object then reports
MISSING_RUNTIME and still runs, on the newest runtime of the same family the target offers. So a
selector does not stop your content; the code meeting a newer runtime is what breaks.

  R1  CHECK   a selector the target does not offer: the object will run on the target's runtime of
              that family, unproven. An action bound to such an environment reports nothing of its own,
              so it is listed under its environment. qualify.py runs it there before you trust it.
  R2  CHECK   a selector this instance already does not offer: it already runs on the newest.
  R3  BREAKS  a Python standard-library module the target's Python no longer ships.
  R4  BREAKS  the Command scripting object, removed from the JavaScript API.
  R5  BREAKS  a plug-in installed here that the target does not ship.
  R6  CHECK   environment dependencies to rebuild on the target selector, pinned and unpinned.
  R7  BREAKS  Python that calls context.getToken() as an attribute: the context is a dict.
      CHECK   any use of getToken, to run on the target on a fresh and on a refreshed token.
  R8  BREAKS  PowerShell that imports a module the target's PowerCLI runtime does not install;
      CHECK   one that pins a module version, because the version numbers change between releases.
  R9  CHECK   JavaScript that reaches Java classes, and constructs the source and target engines
              answer differently (needs --source-probe; the target's set is in its targets file).
  R10 CHECK   plug-in hosts to re-test: VM Apps hosts, PowerShell hosts, SSH hosts.
  R11 CHECK   scheduled tasks and policies.
  R12 CHECK   scripts that carry characters outside ASCII.

Usage:
    export VRO_HOST=orchestrator.example.net
    export VRO_TOKEN=<a bearer this appliance accepts>
    export TLS_VERIFY=false                                  # only on a self-signed lab CA
    python3 upgrade_risk.py --target targets/9.1.1.json
    python3 upgrade_risk.py --target targets/9.1.1.json --target-probe records/probe-9.1.1.json
    python3 upgrade_risk.py --target-host <fqdn-on-the-target-release>   # VRO_TARGET_TOKEN, else VRO_TOKEN
    python3 upgrade_risk.py --compare records/probe-9.1.0.0400.json records/probe-9.1.1.json
    python3 upgrade_risk.py --target targets/9.1.1.json --redact --record risk.json
    python3 upgrade_risk.py --target targets/9.1.1.json --files examples/at-risk/*      # no instance needed

Exit 0 nothing at risk; 1 at least one finding; 2 a read failed; 5 unknown option.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from urllib import error as _er
from urllib import request as _rq

BASE = "/vco/api"
CTX = ssl.create_default_context()
if os.environ.get("TLS_VERIFY", "true").lower() in ("0", "false", "no"):
    CTX.check_hostname = False
    CTX.verify_mode = ssl.CERT_NONE

# Python standard-library modules removed by release: 3.12 (PEP 632 and the asyncore family) and
# 3.13 (PEP 594, the "dead batteries"). A script that imports one fails at import on that Python.
PY_REMOVED = {
    (3, 12): ("distutils", "imp", "asynchat", "asyncore", "smtpd"),
    (3, 13): ("aifc", "audioop", "cgi", "cgitb", "chunk", "crypt", "imghdr", "mailcap", "msilib", "nis",
              "nntplib", "ossaudiodev", "pipes", "sndhdr", "spwd", "sunau", "telnetlib", "uu", "xdrlib",
              "lib2to3"),
}

# JavaScript constructs the probe measures, with a pattern that finds each in a script. A construct is
# reported only when the two probe records disagree about it.
JS_DETECT = {
    "e4x_xml_literal": r"\bnew\s+XML(?:List)?\s*\(",
    "for_each_in": r"\bfor\s+each\s*\(",
    "define_getter": r"__define[GS]etter__",
    "let_loop_closure": r"\bfor\s*\(\s*let\b",
    "proto_property": r"__proto__",
    "date_slash_format": r"new\s+Date\(\s*['\"]\d{4}/",
    "class_declaration": r"(?m)^\s*class\s+\w+",
    "spread_array": r"\[\s*\.\.\.\w",
    "async_await": r"\basync\s+function\b",
    "regex_named_groups": r"\(\?<\w+>",
    "regex_lookbehind": r"\(\?<[=!]",
}
PY_TOKEN_ATTR = re.compile(r"\bcontext\s*\.\s*getToken\s*\(")
JAVA_ACCESS = re.compile(r"\b(?:java|javax|Packages)\.[a-z]\w*|\bJavaImporter\b|\bimportPackage\s*\(|\bimportClass\s*\(")
COMMAND_OBJECT = re.compile(r"\bnew\s+Command\s*\(")
PS_PIN = re.compile(r"(?i)(?:-RequiredVersion|-MinimumVersion|-MaximumVersion|\b(?:Required|Module|Maximum)Version\s*=)")
PS_IMPORT = re.compile(r"(?im)^\s*(?:Import-Module\s+(?:-Name\s+)?|#Requires\s+-Modules?\s+|using\s+module\s+)['\"]?([A-Za-z][\w.\-]*)")
PY_IMPORT = re.compile(r"(?m)^\s*(?:import\s+([\w.]+(?:\s*,\s*[\w.]+)*)|from\s+([\w.]+)\s+import\b)")
SAFE_ENUM = re.compile(r"^[A-Za-z][A-Za-z0-9 _.\-]{0,40}$")


class Reader:
    def __init__(self, host: str, token: str):
        if not host or not token:
            print("set VRO_HOST and VRO_TOKEN first", file=sys.stderr)
            sys.exit(2)
        self.host, self.token = host, token

    def get(self, path: str, missing_ok: bool = False):
        req = _rq.Request(f"https://{self.host}{BASE}{path}", headers={
            "Authorization": f"Bearer {self.token}", "Accept": "application/json"})
        try:
            with _rq.urlopen(req, context=CTX, timeout=120) as r:
                return json.loads(r.read().decode() or "{}")
        except _er.HTTPError as e:
            if missing_ok and e.code == 404:
                return None
            raise SystemExit(_read_failed(f"GET {path} answered {e.code}"))
        except _er.URLError as e:
            raise SystemExit(_read_failed(f"GET {path} failed: {e.reason}"))

    def listing(self, path: str) -> list[dict]:
        j = self.get(path) or {}
        links = j.get("link") or (j.get("relations") or {}).get("link") or []
        return [{a["name"]: a.get("value") for a in li.get("attributes", [])} for li in links if li.get("attributes")]

    def many(self, paths: list[str]) -> list:
        with ThreadPoolExecutor(8) as ex:
            return list(ex.map(lambda p: self.get(p, missing_ok=True), paths))


def _read_failed(msg: str) -> int:
    print(f"read failed: {msg}", file=sys.stderr)
    return 2


def family(sel: str | None) -> str:
    return (sel or "").split(":", 1)[0].lower()


def version_tuple(sel: str) -> tuple[int, ...]:
    m = re.match(r"[a-z]+:(\d+(?:\.\d+)*)", sel or "")
    return tuple(int(x) for x in m.group(1).split(".")) if m else ()


def runs_on(sel: str, here: list[str], there: list[str]) -> str:
    a, b = successor(sel, here) or "?", successor(sel, there) or "?"
    return f"runs on {a}" if a == b else f"runs on {a} here and {b} there"


def successor(sel: str, offered: list[str]) -> str | None:
    """The newest selector of the same family the target offers."""
    cands = [s for s in offered if family(s) == family(sel)]
    return sorted(cands, key=lambda s: tuple(int(x) for x in re.findall(r"\d+", s)))[-1] if cands else None


def load_target(args) -> dict:
    if args.target:
        with open(args.target) as f:
            return json.load(f)
    tok = os.environ.get("VRO_TARGET_TOKEN") or os.environ.get("VRO_TOKEN", "")
    t = Reader(args.target_host, tok)
    rt = t.get("/server-configuration/polyglot-runtimes") or {}
    about = t.get("/about") or {}
    return {"release": "read live", "orchestrator": about.get("version"),
            "runtimes": list(rt.get("o11n-polyglot-runtime") or []),
            "plugins": sorted(p.get("moduleName") for p in (t.get("/plugins") or {}).get("plugins", [])),
            "deprecatedPlugins": {}}


def load_probe(path: str | None) -> dict:
    if not path:
        return {}
    with open(path) as f:
        return json.load(f)


class Names:
    """With --redact every object name becomes its kind and a number, so the transcript can be shared."""

    def __init__(self, redact: bool):
        self.redact, self.seen = redact, {}

    def __call__(self, kind: str, name: str) -> str:
        if not self.redact:
            return name
        key = (kind, name)
        if key not in self.seen:
            self.seen[key] = f"{kind}-{sum(1 for k in self.seen if k[0] == kind) + 1}"
        return self.seen[key]


def check_scripts(scripts: list[dict], target: dict, sprobe: dict, tprobe: dict, add) -> None:
    """The checks that read script text. They run the same on an instance read live and on files
    exported from one (--files), so content kept in source control can be checked before an upgrade."""
    there_rt = list(target.get("runtimes") or [])
    # R3: Python modules the target's Python removed.
    there_py = max((version_tuple(s) for s in there_rt if family(s) == "python"), default=())
    removed = {m: v for v, ms in PY_REMOVED.items() for m in ms if there_py and there_py >= v}
    for s in scripts:
        if s["lang"] != "python":
            continue
        mods = set()
        for m in PY_IMPORT.finditer(s["text"]):
            for part in (m.group(1) or m.group(2) or "").split(","):
                mods.add(part.strip().split(".")[0])
        hit = sorted(m for m in mods if m in removed)
        if hit:
            add("R3", "BREAKS", s["label"],
                "imports " + ", ".join(f"{m} (removed in Python {'.'.join(map(str, removed[m]))})" for m in hit)
                + f"; target Python {'.'.join(map(str, there_py))}")

    # R4: the Command object.
    for s in scripts:
        if s["lang"] == "javascript" and COMMAND_OBJECT.search(s["text"]):
            add("R4", "BREAKS", s["label"], "uses new Command(...); run the command over SSH or a polyglot action")

    # R7: context.getToken(). Measured on 9.1.0.0400 and 9.1.1: the Python context is a dict, so the
    # attribute form raises AttributeError and only context["getToken"]() reaches the function.
    for s in scripts:
        if s["lang"] != "python" or "getToken" not in s["text"]:
            continue
        if PY_TOKEN_ATTR.search(s["text"]):
            add("R7", "BREAKS", s["label"], "calls context.getToken(): the Python context is a dict, so this raises "
                "AttributeError; call context[\"getToken\"]()")
        add("R7", "CHECK", s["label"], "uses getToken: run it on the target on a fresh token and again after the token "
            "refreshes; probe.py makes the same call")

    # R8: PowerShell modules imported by name.
    tlist = ((tprobe.get("results") or {}).get("powercli") or {}).get("modules") or target.get("powercliModules") or []
    tmods = {m.split("==")[0].lower(): m.split("==", 1)[-1] for m in tlist}
    for s in scripts:
        if s["lang"] not in ("powershell", "powercli"):
            continue
        for mod in sorted({m.group(1) for m in PS_IMPORT.finditer(s["text"])}):
            if tmods and mod.lower() not in tmods:
                add("R8", "BREAKS", s["label"], f"imports {mod}, which the target's PowerCLI runtime does not install")
            elif not tmods:
                add("R8", "CHECK", s["label"], f"imports {mod}: confirm the target installs it (probe.py)")
        if PS_PIN.search(s["text"]):
            core = tmods.get("vmware.vimautomation.core")
            add("R8", "CHECK", s["label"], "pins a module version" + (
                f"; on the target VMware.VimAutomation.Core is {core}" if core else "") + ": compare the pin with the target's modules")

    # R9: Java access always; constructs only where the two engines were measured to disagree.
    sf = ((sprobe.get("results") or {}).get("js") or {}).get("features") or {}
    tf = ((tprobe.get("results") or {}).get("js") or {}).get("features") or target.get("jsFeatures") or {}
    differ = {k for k in JS_DETECT if k in sf and k in tf and sf[k] != tf[k]}
    for s in scripts:
        if s["lang"] != "javascript" or not s["text"]:
            continue
        if JAVA_ACCESS.search(s["text"]):
            add("R9", "CHECK", s["label"], "reaches Java classes: the engine and its class access change between releases; run it on the target")
        for k in sorted(differ):
            if re.search(JS_DETECT[k], s["text"]):
                add("R9", "BREAKS" if str(tf[k]).startswith("FAIL") else "CHECK", s["label"],
                    f"uses {k}: here {sf[k]!r}, on the target {tf[k]!r}")

    # R12: characters outside ASCII.
    for s in scripts:
        odd = {ch for ch in s["text"] if ord(ch) > 127}
        if odd:
            astral = any(ord(ch) > 0xFFFF for ch in odd)
            add("R12", "CHECK", s["label"],
                f"{len(odd)} distinct non-ASCII characters{', including emoji or other characters beyond the BMP' if astral else ''}: "
                "9.1.1.0 lists such characters as encoded on package export; remove them before content moves by package")


def scan(r: Reader, target: dict, sprobe: dict, tprobe: dict, names: Names) -> tuple[dict, list[dict]]:
    about = r.get("/about") or {}
    here_rt = list((r.get("/server-configuration/polyglot-runtimes") or {}).get("o11n-polyglot-runtime") or [])
    there_rt = list(target.get("runtimes") or [])
    plugins = sorted(p.get("moduleName") for p in (r.get("/plugins") or {}).get("plugins", []))

    envs_l = r.listing("/environments")
    envs = {e["id"]: d for e, d in zip(envs_l, r.many([f"/environments/{e['id']}" for e in envs_l])) if d}
    acts_l = r.listing("/actions")
    acts = [d for d in r.many([f"/actions/{a['id']}" for a in acts_l]) if d]
    wfs_l = r.listing("/workflows")
    wf_content = r.many([f"/workflows/{w['id']}/content" for w in wfs_l])

    # Every script with its language and the selector it resolves to. A scriptable task may name an
    # environment ("environment:<id>") instead of a runtime; it then carries that environment's runtime.
    scripts: list[dict] = []
    bound: dict[str, list[str]] = defaultdict(list)
    for a in acts:
        env = envs.get(a.get("actionEnvironmentId") or "")
        sel = a.get("runtime") or (env or {}).get("runtime")
        label = ("action", a.get("fqn") or f"{a.get('module')}/{a.get('name')}")
        if env:
            bound[env["id"]].append(label)
        scripts.append({"kind": "action", "label": label, "selector": sel, "via_env": env.get("id") if env else None,
                        "lang": family(sel) or "javascript", "text": a.get("script") or "",
                        "validation": a.get("validationMessage")})
    poly_tasks = 0
    for w, ct in zip(wfs_l, wf_content):
        if not ct:
            continue
        for it in ct.get("workflow-item") or []:
            if it.get("type") != "task":
                continue
            text = ((it.get("script") or {}).get("value")) or ""
            rt = it.get("runtime")
            env = None
            if rt and rt.startswith("environment:"):
                env = envs.get(rt.split(":", 1)[1])
                sel = (env or {}).get("runtime")
            else:
                sel = rt
            if it.get("script-module"):
                continue  # an action element: its script is the action's, read above
            if rt:
                poly_tasks += 1
            label = ("workflow", w.get("name") or w["id"], it.get("display-name") or it.get("name"))
            if env:
                bound[env["id"]].append(label)
            scripts.append({"kind": "scriptable task", "label": label, "selector": sel, "via_env": env.get("id") if env else None,
                            "lang": family(sel) or "javascript", "text": text, "validation": it.get("validation-message")})

    tasks = ((r.get("/tasks") or {}).get("relations") or {}).get("total", 0)
    policies = ((r.get("/policies") or {}).get("relations") or {}).get("total", 0)

    findings: list[dict] = []

    def show(label: tuple) -> str:
        """An object's printed name, numbered only when it is reported and --redact is on."""
        if label[0] == "workflow":
            return f"scriptable task {names('workflow', label[1])} / {label[2]}"
        return f"{label[0]} {names(label[0], label[1])}"

    def add(check: str, sev: str, obj, detail: str) -> None:
        findings.append({"check": check, "severity": sev, "object": show(obj) if isinstance(obj, tuple) else obj,
                         "detail": detail})

    # R1, R2: selectors. Environments first; the actions and tasks that inherit one are named under it.
    for eid, e in envs.items():
        sel = e.get("runtime")
        if sel in here_rt and sel in there_rt:
            continue
        label = ("environment", e.get("name") or eid)
        heirs = [show(h) for h in bound.get(eid, [])]
        tail = f"; {len(heirs)} bound: " + ", ".join(heirs[:6]) + (" ..." if len(heirs) > 6 else "") if heirs else ""
        if sel not in here_rt:
            add("R2", "CHECK", label, f"{sel} is not offered here (MISSING_RUNTIME); {runs_on(sel, here_rt, there_rt)}{tail}")
        elif sel not in there_rt:
            add("R1", "CHECK", label, f"{sel} -> runs on {successor(sel, there_rt) or 'no runtime of this family'}, "
                f"unproven: qualify it there{tail}")
    for s in scripts:
        if s["via_env"] or not s["selector"]:
            continue
        if s["selector"] not in here_rt:
            add("R2", "CHECK", s["label"], f"{s['selector']} is not offered here (MISSING_RUNTIME); "
                f"{runs_on(s['selector'], here_rt, there_rt)}")
        elif s["selector"] not in there_rt:
            add("R1", "CHECK", s["label"],
                f"{s['selector']} -> runs on {successor(s['selector'], there_rt) or 'no runtime of this family'}, "
                "unproven: qualify it there")

    check_scripts(scripts, target, sprobe, tprobe, add)

    # R5: plug-ins the target does not ship; deprecations noted.
    tplug = set(target.get("plugins") or [])
    for p in plugins:
        if tplug and p not in tplug:
            add("R5", "BREAKS", f"plug-in {p}", "installed here, not shipped by the target: content that calls it fails")
        elif p in (target.get("deprecatedPlugins") or {}):
            add("R5", "CHECK", f"plug-in {p}", (target["deprecatedPlugins"][p] or "deprecated on the target"))

    # R6: dependencies to rebuild when the environment's selector changes or does not resolve.
    for eid, e in envs.items():
        deps = e.get("dependencies") or {}
        sel = e.get("runtime")
        if deps and (sel not in there_rt or sel not in here_rt):
            pinned = sorted(f"{k}=={v}" for k, v in deps.items() if v)
            loose = sorted(k for k, v in deps.items() if not v)
            add("R6", "CHECK", ("environment", e.get("name") or eid),
                f"rebuild on {successor(sel, there_rt) or '?'} and read the install log; pinned: {', '.join(pinned) or 'none'}; "
                f"unpinned: {', '.join(loose) or 'none'}")

    # R10: plug-in hosts.
    for plug, kind, keep in (("VRA", "VM Apps host", ("connectionType", "sessionMode")),
                             ("PowerShell", "PowerShell host", ("type", "transportProtocol", "authentication")),
                             ("SSH", "SSH host", ())):
        for h in r.listing(f"/catalog/{plug}"):
            shown = {k: h.get(k) for k in keep if isinstance(h.get(k), str) and SAFE_ENUM.match(h.get(k) or "")}
            why = {"VRA": "read how it authenticates: vIDM user credentials end at the identity cut-over, and an API token "
                          "is the 9.1.1 alternative for shared and scheduled runs",
                   "PowerShell": "re-test a session on the target; a host that authenticates with Kerberos needs krb5.conf there",
                   "SSH": "re-test with FIPS-compatible algorithms on the remote host"}[plug]
            add("R10", "CHECK", f"{kind} {names(kind.replace(' ', '-').lower(), str(h.get('name') or h.get('displayName') or h.get('id')))}",
                (json.dumps(shown, sort_keys=True) + "; " if shown else "") + why)

    # R11: scheduled tasks and policies.
    if tasks or policies:
        add("R11", "CHECK", "scheduler", f"{tasks} scheduled tasks, {policies} policies: confirm each runs as its user after the upgrade")

    facts = {
        "orchestrator": about.get("version"), "target": target.get("release"),
        "targetOrchestrator": target.get("orchestrator"), "runtimesHere": here_rt, "runtimesThere": there_rt,
        "counts": {"workflows": len(wfs_l), "workflowsRead": sum(1 for c in wf_content if c),
                   "polyglotScriptableTasks": poly_tasks, "actions": len(acts),
                   "polyglotActions": sum(1 for s in scripts if s["kind"] == "action" and s["lang"] != "javascript"),
                   "environments": len(envs), "plugins": len(plugins), "scheduledTasks": tasks, "policies": policies},
    }
    return facts, findings


TITLES = {
    "R1": "a selector the target does not offer: kept, flagged, and run on the target's own runtime unproven",
    "R2": "a selector this instance already does not offer",
    "R3": "a Python module the target's Python removed",
    "R4": "the Command scripting object",
    "R5": "plug-ins the target does not ship, or deprecates",
    "R6": "environment dependencies to rebuild",
    "R7": "Python that calls getToken",
    "R8": "PowerShell modules by name and by version",
    "R9": "JavaScript that may answer differently on the target engine",
    "R10": "plug-in hosts to re-test",
    "R11": "scheduled tasks and policies",
    "R12": "scripts with characters outside ASCII",
}


def scan_files(paths: list[str], target: dict, sprobe: dict, tprobe: dict) -> list[dict]:
    """The script checks on exported files: .py as Python, .ps1 and .psm1 as PowerShell, .js as JavaScript."""
    langs = {".py": "python", ".ps1": "powershell", ".psm1": "powershell", ".js": "javascript"}
    scripts = []
    for p in paths:
        lang = langs.get(os.path.splitext(p)[1].lower())
        if not lang:
            print(f"skipped {p}: not .py, .ps1, .psm1 or .js")
            continue
        with open(p, encoding="utf-8", errors="replace") as f:
            scripts.append({"kind": "file", "label": f"file {p}", "selector": None, "via_env": None,
                            "lang": lang, "text": f.read()})
    findings: list[dict] = []
    check_scripts(scripts, target, sprobe, tprobe,
                  lambda check, sev, obj, detail: findings.append(
                      {"check": check, "severity": sev, "object": obj, "detail": detail}))
    print(f"files: {len(scripts)} read against {target.get('release')} (Python {target.get('python')}, "
          f"PowerShell {target.get('powershell')})")
    return findings


def report(facts: dict, findings: list[dict]) -> None:
    c = facts["counts"]
    print(f"orchestrator {facts['orchestrator']} -> target {facts['target']} (orchestrator {facts['targetOrchestrator']})")
    print(f"runtimes here:  {', '.join(facts['runtimesHere'])}")
    print(f"runtimes there: {', '.join(facts['runtimesThere'])}")
    gone = [s for s in facts["runtimesHere"] if s not in facts["runtimesThere"]]
    if gone:
        print("selectors that do not carry: " + ", ".join(f"{s} -> {successor(s, facts['runtimesThere']) or '?'}" for s in gone))
    print(f"read: {c['workflows']} workflows ({c['polyglotScriptableTasks']} polyglot scriptable tasks), {c['actions']} actions "
          f"({c['polyglotActions']} polyglot), {c['environments']} environments, {c['plugins']} plug-ins, "
          f"{c['scheduledTasks']} scheduled tasks, {c['policies']} policies")
    report_findings(findings)


def report_findings(findings: list[dict]) -> None:
    by = defaultdict(list)
    for f in findings:
        by[f["check"]].append(f)
    for check in sorted(by, key=lambda k: int(k[1:])):
        rows = by[check]
        print(f"\n{rows[0]['severity']:<6} {check} {TITLES[check]}: {len(rows)}")
        for f in rows:
            sev = "" if f["severity"] == rows[0]["severity"] else f"[{f['severity']}] "
            print(f"  {sev}{f['object']}\n      {f['detail']}")
    tally = Counter(f["severity"] for f in findings)
    print(f"\nsummary: {tally.get('BREAKS', 0)} BREAKS, {tally.get('CHECK', 0)} CHECK")


def compare(a_path: str, b_path: str) -> int:
    a, b = load_probe(a_path), load_probe(b_path)
    print(f"{a.get('orchestrator')}  ->  {b.get('orchestrator')}")
    print(f"runtimes: {', '.join(a.get('runtimes') or [])}  ->  {', '.join(b.get('runtimes') or [])}")
    ra, rb = a.get("results") or {}, b.get("results") or {}
    fa, fb = (ra.get("js") or {}).get("features") or {}, (rb.get("js") or {}).get("features") or {}
    print(f"javascript engine: {(ra.get('js') or {}).get('engine')!r}  ->  {(rb.get('js') or {}).get('engine')!r}")
    for k in sorted(set(fa) | set(fb)):
        if fa.get(k) != fb.get(k):
            print(f"  {k:<22} {fa.get(k)!s:<40} -> {fb.get(k)}")
    for key in ("py_current", "powercli"):
        va, vb = ra.get(key) or {}, rb.get(key) or {}
        field = "distributions" if key == "py_current" else "modules"
        la, lb = set(va.get(field) or []), set(vb.get(field) or [])
        ver = "python" if key == "py_current" else "powershell"
        print(f"{key}: {ver} {va.get(ver)} -> {vb.get(ver)}; {len(la)} -> {len(lb)} {field}")
        na = {x.split("==")[0]: x for x in la}
        nb = {x.split("==")[0]: x for x in lb}
        for n in sorted(set(na) - set(nb)):
            print(f"  gone     {na[n]}")
        for n in sorted(set(nb) - set(na)):
            print(f"  new      {nb[n]}")
        for n in sorted(set(na) & set(nb)):
            if na[n] != nb[n]:
                print(f"  changed  {na[n]} -> {nb[n].split('==', 1)[1]}")
    return 0


def main() -> int:
    class P(argparse.ArgumentParser):
        def error(self, message):
            self.print_usage(sys.stderr)
            print(f"upgrade_risk.py: {message}", file=sys.stderr)
            sys.exit(5)

    ap = P(description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--target", help="a targets/<release>.json file")
    g.add_argument("--target-host", help="an instance already on the target release, read live")
    g.add_argument("--compare", nargs=2, metavar=("BEFORE", "AFTER"), help="diff two probe.py records and exit")
    ap.add_argument("--source-probe", help="probe.py record from this instance")
    ap.add_argument("--target-probe", help="probe.py record from an instance on the target release")
    ap.add_argument("--files", nargs="+", metavar="FILE",
                    help="check exported .py, .ps1 and .js files against the target instead of reading an instance")
    ap.add_argument("--redact", action="store_true", help="print object kinds and numbers instead of names")
    ap.add_argument("--record", help="write the facts and per-check counts (no names) as JSON")
    a = ap.parse_args()
    if a.compare:
        return compare(*a.compare)

    target = load_target(a)
    if a.files:
        findings = scan_files(a.files, target, load_probe(a.source_probe), load_probe(a.target_probe))
        report_findings(findings)
        return 1 if findings else 0
    r = Reader(os.environ.get("VRO_HOST", ""), os.environ.get("VRO_TOKEN", ""))
    facts, findings = scan(r, target, load_probe(a.source_probe), load_probe(a.target_probe), Names(a.redact))
    report(facts, findings)
    if a.record:
        out = dict(facts, findings={k: dict(Counter(f["severity"] for f in findings if f["check"] == k))
                                    for k in sorted({f["check"] for f in findings}, key=lambda k: int(k[1:]))})
        with open(a.record, "w") as f:
            json.dump(out, f, indent=1, sort_keys=True)
            f.write("\n")
        print(f"record written: {a.record}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
