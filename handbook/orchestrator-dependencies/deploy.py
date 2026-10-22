#!/usr/bin/env python3
"""deploy.py: deploy Orchestrator content in the order its bindings force, and read back what the deploy wrote.

Two of Orchestrator's three bindings carry an identifier the appliance issues: an action points at its runtime
environment by id, and a workflow points at a configuration element by id plus a key name. Content authored on one
appliance therefore names objects that do not exist on the next, and the import accepts it anyway. So a deploy runs
in six layers, each one creating what the next needs and handing its identifiers on:

  1  the package          a name
  2  the categories       one each for configuration elements, actions and workflows
  3  configuration elements, upserted by name in their category; their ids go to layer 6
  4  action environments, upserted by name; the runtime must be one this appliance offers; ids go to layer 5
  5  actions, packaged here with the layer-4 environment id written into each one, imported into their module
  6  workflows, with every conf-id rewritten to the layer-3 element of the same conf-name, imported into their category

Then the check no import performs: readback fetches each action and confirms the environment it reports is the one
layer 4 made here, and fetches each workflow's definition and confirms every conf-id names an element on this
appliance. A deploy can succeed and be wrong; the readback is how you tell.

Commands (a manifest is a JSON file; paths inside it are relative to it; see example/manifest.json):
  validate MANIFEST              offline: the schema, every file present, every reference declared
  plan MANIFEST                  GETs only: what each layer would create, update or import, and the runtime check
  deploy MANIFEST [--record F]   the six layers; F gets a JSON record of the run with every id replaced
  readback MANIFEST [--record F] the two identifier bindings, read back from this appliance
  teardown MANIFEST --confirm PACKAGE   deletes exactly the objects the manifest names, newest layer first
Env:   VRO_HOST; VRO_TOKEN_FILE, a bearer this appliance accepts, in a file of mode 0600 (VRO_TOKEN, the value
       itself, is read when no file is named); TLS_VERIFY=false for an appliance whose private CA you have not installed
Exit:  0 done, or nothing wrong found · 1 validation blockers, a layer failed, or a readback found a binding that does not
       resolve here · 2 a usage error, or a token file open to group or other · 3 a read or sign-in failed · 4 the
       record refused to write because the appliance's host name survived
"""
import io
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from pathlib import Path

BASE = "/vco/api"
UUID_RX = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
CATEGORY_KINDS = (("configurations", "ConfigurationElementCategory"), ("actions", "ScriptModuleCategory"),
                  ("workflows", "WorkflowCategory"))
TOP = {"schema_version", "metadata", "package", "categories", "configurations", "environments", "actions", "workflows"}
VRO_TYPES = {"string": "string", "number": "number", "boolean": "boolean", "properties": "Properties",
             "secure_string": "SecureString", "date": "Date", "any": "Any"}


class ReadFailed(Exception):
    """A request the result depends on could not be made, or the appliance refused the sign-in."""


class LayerFailed(Exception):
    """A layer could not do its job; the chain stops here, and later layers are not run."""


# ---------------------------------------------------------------- transport
def read_secret(var):
    """The secret in the file VAR names. A file open to group or other is refused before it is read; the refusal
    names the variable and the fix, never the file's content."""
    with open(os.environ[var], encoding="utf-8") as f:
        mode = os.fstat(f.fileno()).st_mode & 0o777
        # Windows makes the mode from the read-only flag alone, so it has no group or other bits to judge.
        if mode & 0o077 and os.name != "nt":
            raise PermissionError(f"{var} names a file of mode {mode:04o}, open to group or other: "
                                  f'run chmod 600 "${var}" and try again (the file was not read)')
        return f.read().strip()


class Vro:
    def __init__(self):
        self.host = os.environ["VRO_HOST"]
        self.token = read_secret("VRO_TOKEN_FILE") if os.environ.get("VRO_TOKEN_FILE") else os.environ["VRO_TOKEN"]
        verify = os.environ.get("TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")
        self.ctx = ssl.create_default_context() if verify else ssl._create_unverified_context()

    def call(self, method, path, body=None, ctype="application/json"):
        """(status, parsed JSON or None, the raw bytes). Transport failure raises ReadFailed; an HTTP error returns."""
        data = body if isinstance(body, bytes) or body is None else json.dumps(body).encode()
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = ctype
        rq = urllib.request.Request(f"https://{self.host}{BASE}{path}", data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(rq, context=self.ctx, timeout=120) as r:
                raw = r.read()
                return r.status, _json(raw), raw
        except urllib.error.HTTPError as e:
            raw = e.read()
            if e.code == 401:
                raise ReadFailed("the appliance refused the bearer (HTTP 401)") from None
            return e.code, _json(raw), raw
        except (urllib.error.URLError, OSError) as e:
            raise ReadFailed(f"{method} {path.split('?')[0]}: {e}") from None

    def get(self, path):
        st, body, _ = self.call("GET", path)
        return st, body

    def upload(self, path, filename, payload, fields=None):
        """A multipart/form-data POST with one file part named 'file' and optional form fields."""
        boundary = f"----pca{uuid.uuid4().hex}"
        out = io.BytesIO()
        for k, v in (fields or {}).items():
            out.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
        out.write(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                  f"Content-Type: application/zip\r\n\r\n".encode())
        out.write(payload)
        out.write(f"\r\n--{boundary}--\r\n".encode())
        return self.call("POST", path, out.getvalue(), f"multipart/form-data; boundary={boundary}")


def _json(raw):
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return None


def links(body):
    """The flat rows of an Orchestrator list answer: {"link": [{"attributes": [{"name", "value"}], "href"}]}."""
    rows = []
    for entry in (body or {}).get("link") or []:
        row = {a.get("name"): a.get("value") for a in entry.get("attributes") or []}
        row["href"] = entry.get("href")
        rows.append(row)
    return rows


# ---------------------------------------------------------------- the manifest
def load(path):
    path = Path(path)
    m = json.loads(path.read_text(encoding="utf-8"))
    m["_dir"] = path.parent
    return m


def validate(m):
    """Blockers (and warnings) as (severity, field, message). Offline: reads the manifest's own files only."""
    out, d = [], m["_dir"]
    for k in sorted(set(m) - TOP - {"_dir"}):
        out.append(("BLOCKER", k, f"unknown key {k!r}"))
    for k in ("metadata", "package", "categories"):
        if not isinstance(m.get(k), dict):
            out.append(("BLOCKER", k, f"{k} is required"))
    if not (m.get("package") or {}).get("name"):
        out.append(("BLOCKER", "package.name", "package.name is required"))
    for kind, _ in CATEGORY_KINDS:
        if not (m.get("categories") or {}).get(kind):
            out.append(("BLOCKER", f"categories.{kind}", f"categories.{kind} is required"))
    envs = [e.get("name") for e in m.get("environments") or []]
    for i, e in enumerate(m.get("environments") or []):
        if not e.get("name") or not re.fullmatch(r"[A-Za-z0-9_$]+", e["name"]):
            out.append(("BLOCKER", f"environments[{i}].name", "an environment name allows letters, digits, _ and $ only"))
        if not e.get("runtime"):
            out.append(("BLOCKER", f"environments[{i}].runtime", "a runtime selector is required, e.g. python:3.11"))
        for p in e.get("packages") or []:
            if re.search(r"[<>~!,]", p):
                out.append(("BLOCKER", f"environments[{i}].packages", f"{p!r}: pin with == or leave unpinned"))
    if len(envs) != len(set(envs)):
        out.append(("BLOCKER", "environments", "environment names must be unique"))
    for i, c in enumerate(m.get("configurations") or []):
        if not c.get("name") or not (d / c.get("file", "")).is_file():
            out.append(("BLOCKER", f"configurations[{i}].file", f"configuration file not found: {c.get('file')}"))
    for i, a in enumerate(m.get("actions") or []):
        src = d / a.get("source", "")
        if not (src / "metadata.json").is_file():
            out.append(("BLOCKER", f"actions[{i}].source", f"action source missing metadata.json: {a.get('source')}"))
        elif not re.fullmatch(r"[A-Za-z0-9_]+", json.loads((src / "metadata.json").read_text())["name"]):
            out.append(("BLOCKER", f"actions[{i}].source", "an action name allows letters, digits and _ only"))
        if not _script(src):
            out.append(("BLOCKER", f"actions[{i}].source", f"action source missing a script: {a.get('source')}"))
        if a.get("environment_ref") not in envs:
            out.append(("BLOCKER", f"actions[{i}].environment_ref",
                        f"environment_ref {a.get('environment_ref')!r} does not match any declared environment"))
    names = {c.get("name") for c in m.get("configurations") or []}
    for i, w in enumerate(m.get("workflows") or []):
        xml = _workflow_xml(d / w.get("source", ""))
        if not xml:
            out.append(("BLOCKER", f"workflows[{i}].source", f"workflow source missing an XML file: {w.get('source')}"))
            continue
        text = xml.read_text(encoding="utf-8")
        for tag in re.findall(r"<attrib\b[^>]*conf-id=\"[^\"]*\"[^>]*>", text):
            cname = re.search(r'conf-name="([^"]+)"', tag)
            if cname and cname.group(1) not in names:
                out.append(("BLOCKER", f"workflows[{i}].source",
                            f"a binding names configuration element {cname.group(1)!r}, which the manifest does not declare"))
            elif not cname and len(names) != 1:
                out.append(("BLOCKER", f"workflows[{i}].source",
                            "a binding carries no conf-name and the manifest does not declare exactly one element, so the "
                            "deploy could not tell which element to bind it to"))
    if not any(m.get(k) for k in ("configurations", "environments", "actions", "workflows")):
        out.append(("WARNING", "<root>", "the manifest declares no content"))
    return out


def _script(src):
    return next((p for ext in ("*.py", "*.ps1", "*.js") for p in sorted(Path(src).glob(ext))), None)


def _workflow_xml(src):
    return next(iter(sorted(Path(src).glob("*.xml"))), None)


# ---------------------------------------------------------------- packaging (pure)
def java_now():
    return time.strftime("%a %b %d %H:%M:%S GMT %Y", time.gmtime())


def action_id(module, name):
    """A stable id per action, so a second import of the same action overwrites rather than duplicates."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"pca:vro-action:{module}/{name}"))


def package_action(src, env_id, aid):
    """The .action file: action-info (latin-1) and action-content, whose first child names the environment by id.
    The content is UTF-16 with a byte-order mark, as the appliance's own export writes it."""
    meta = json.loads((Path(src) / "metadata.json").read_text(encoding="utf-8"))
    script = _script(src).read_text(encoding="utf-8")
    params = "".join(f'  <param n="{p["name"]}" t="{VRO_TYPES.get(str(p.get("type", "string")).lower(), "string")}">'
                     f'{_esc(p.get("description", ""))}</param>\n' for p in meta.get("inputs") or [])
    content = ("<?xml version='1.0' encoding='UTF-8'?>\n"
               f'<dunes-script-module name="{meta["name"]}" result-type="Properties" api-version="6.0.0" id="{aid}" '
               f'version="{meta.get("version", "1.0.0")}">\n'
               f"  <environment>{env_id}</environment>\n{params}"
               f'  <script encoded="false"><![CDATA[{script}]]></script>\n</dunes-script-module>\n')
    info = (f"#\n#{java_now()}\nowner=\ncharset=UTF-16\ncreator=www.dunes.ch\nunicode=true\ntype=action\nversion=2.0\n")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("action-info", info.encode("latin-1"))
        z.writestr("action-content", content.encode("utf-16"))
    return meta, buf.getvalue()


def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def rebind(text, config_id_by_name):
    """Rewrite each binding's conf-id to this appliance's element of the same conf-name; with no conf-name, to the
    sole declared element. A binding that cannot be matched is left as authored, never guessed at.
    Returns (text, the number of bindings that changed)."""
    sole = next(iter(config_id_by_name.values())) if len(config_id_by_name) == 1 else None
    count = 0

    def sub(mt):
        nonlocal count
        tag = mt.group(0)
        name = re.search(r'conf-name="([^"]+)"', tag)
        new = config_id_by_name.get(name.group(1)) if name else sole
        if not new:
            return tag
        out = re.sub(r'conf-id="[^"]*"', f'conf-id="{new}"', tag)
        count += out != tag
        return out

    return re.sub(r"<attrib\b[^>]*conf-id=\"[^\"]*\"[^>]*/?>", sub, text), count


def package_workflow(text):
    info = (f"#\n#{java_now()}\nowner=\ncharset=UTF-16\ncreator=pca-companion\nunicode=true\ntype=workflow\nversion=2.0\n")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("workflow-info", info.encode("latin-1"))
        z.writestr("workflow-content", text.encode("utf-16"))
    return buf.getvalue()


def workflow_id(text):
    m = re.search(r"<workflow\b[^>]*\bid=\"([^\"]+)\"", text)
    return m.group(1) if m else None


# ---------------------------------------------------------------- what exists on the appliance
def find_category(v, kind, name):
    st, body = v.get(f"/categories?categoryType={kind}")
    if st != 200:
        raise ReadFailed(f"the {kind} list answered HTTP {st}")
    return next((r.get("id") for r in links(body) if r.get("name") == name), None)


def find_configuration(v, category_id, name):
    if not category_id or category_id.startswith("<"):
        return None
    st, body = v.get(f"/configurations?categoryId={category_id}")
    if st != 200:
        raise ReadFailed(f"the configuration list answered HTTP {st}")
    return next((r.get("id") for r in links(body) if r.get("name") == name), None)


def find_environment(v, name):
    st, body = v.get("/environments")
    if st != 200:
        raise ReadFailed(f"the environment list answered HTTP {st}")
    return next((r.get("id") for r in links(body) if r.get("name") == name), None)


def find_action(v, module, name):
    st, body = v.get("/actions")
    if st != 200:
        raise ReadFailed(f"the action list answered HTTP {st}")
    fqn = f"{module}/{name}"
    return next((r.get("id") for r in links(body) if r.get("fqn") == fqn), None)


def offered_runtimes(v):
    st, body = v.get("/server-configuration/polyglot-runtimes")
    if st != 200:
        raise ReadFailed(f"the runtime list answered HTTP {st}")
    return list((body or {}).get("o11n-polyglot-runtime") or [])


# ---------------------------------------------------------------- the six layers
def run_layers(v, m, dry):
    """Run the six layers in order (dry: GETs only). Returns the per-layer outcomes; raises LayerFailed to stop."""
    d, pkg, cats = m["_dir"], m["package"]["name"], m["categories"]
    out = []

    def layer(n, name, summary, items=(), status="ok"):
        out.append({"layer": n, "name": name, "status": status, "summary": summary, "items": list(items)})
        mark = {"ok": "✓", "plan": "→", "skipped": "·", "failed": "✗"}[status]
        print(f"  {mark} Layer {n} ({name}): {summary}")
        for it in items:
            print(f"      • {it}")

    links_made = []

    def link(kind, oid):
        """Put an object into the package. A refusal is recorded, not fatal: package membership decides what an
        export carries, not whether the deploy works."""
        if dry:
            return
        st, _, _ = v.call("POST", f"/packages/{urllib.parse.quote(pkg, safe='')}/{kind}/{oid}")
        links_made.append(f"{kind}: HTTP {st}")

    # 1. the package
    st, _ = v.get(f"/packages/{urllib.parse.quote(pkg, safe='')}")
    if st not in (200, 404):
        raise ReadFailed(f"the package read answered HTTP {st}")
    if st == 200:
        layer(1, "package", f"package '{pkg}' exists", status="plan" if dry else "ok")
    elif dry:
        layer(1, "package", f"would create package '{pkg}'", status="plan")
    else:
        stc, _, _ = v.call("PUT", f"/packages/{urllib.parse.quote(pkg, safe='')}")  # bare PUT: a JSON body gets 400
        if stc not in (200, 201) or v.get(f"/packages/{urllib.parse.quote(pkg, safe='')}")[0] != 200:
            raise LayerFailed(f"layer 1: the package create answered HTTP {stc} and the package is not readable")
        layer(1, "package", f"created package '{pkg}'")

    # 2. the categories
    cat_ids, items = {}, []
    for kind, typ in CATEGORY_KINDS:
        cid = find_category(v, typ, cats[kind])
        if cid:
            items.append(f"{cats[kind]} exists")
        elif dry:
            cid = f"<planned:{cats[kind]}>"
            items.append(f"would create {cats[kind]}")
        else:
            stc, body, _ = v.call("POST", "/categories", {"name": cats[kind], "type": typ})
            cid = (body or {}).get("id") or find_category(v, typ, cats[kind])
            if not cid:
                raise LayerFailed(f"layer 2: the {typ} create answered HTTP {stc} and the category is not listed")
            items.append(f"created {cats[kind]}")
        cat_ids[kind] = cid
    layer(2, "categories", ("would ensure" if dry else "ensured") + " 3 categories", items, "plan" if dry else "ok")

    # 3. configuration elements
    config_ids, items = {}, []
    for c in m.get("configurations") or []:
        spec = json.loads((d / c["file"]).read_text(encoding="utf-8"))
        attrs = spec.get("attributes") if isinstance(spec, dict) else spec
        payload = {"name": c["name"], "category-id": cat_ids["configurations"], "description": c.get("description", ""),
                   "version": "1.0.0", "attributes": attrs or []}
        cid = find_configuration(v, cat_ids["configurations"], c["name"])
        if dry:
            config_ids[c["name"]] = cid or f"<planned:{c['name']}>"
            items.append(f"{'would update' if cid else 'would create'} {c['name']}")
            continue
        if cid:
            stc, _, _ = v.call("PUT", f"/configurations/{cid}", dict(payload, id=cid))
            what = "updated in place"
        else:
            stc, body, _ = v.call("POST", "/configurations", payload)
            cid = (body or {}).get("id") or find_configuration(v, cat_ids["configurations"], c["name"])
            what = "created"
        if stc not in (200, 201, 204) or not cid:
            raise LayerFailed(f"layer 3: {c['name']} answered HTTP {stc}")
        config_ids[c["name"]] = cid
        items.append(f"{c['name']} {what}")
        link("configuration", cid)
    layer(3, "configuration elements", f"{'would upsert' if dry else 'upserted'} {len(config_ids)}", items,
          "plan" if dry else "ok")

    # 4. environments
    offered = offered_runtimes(v)
    env_ids, items = {}, []
    for e in m.get("environments") or []:
        if e["runtime"] not in offered:
            raise LayerFailed(f"layer 4: {e['name']} pins {e['runtime']}, which this appliance does not offer "
                              f"(offered: {', '.join(offered)}); nothing was written in this layer")
        deps = {p.split("==")[0]: (p.split("==")[1] if "==" in p else "") for p in e.get("packages") or []}
        eid = find_environment(v, e["name"])
        if dry:
            env_ids[e["name"]] = eid or f"<planned:{e['name']}>"
            items.append(f"{'would update' if eid else 'would create'} {e['name']} on {e['runtime']} (offered here)")
            continue
        body = {"name": e["name"], "runtime": e["runtime"], "version": e.get("version", "1.0.0"),
                "description": e.get("description", ""), "dependencies": deps}
        if eid:
            st0, cur = v.get(f"/environments/{eid}")
            cur = {k: val for k, val in (cur or {}).items() if k not in ("status", "validationMessage")}
            stc, _, _ = v.call("PUT", f"/environments/{eid}", dict(cur, **body, id=eid))
            what = "updated in place"
        else:
            stc, created, _ = v.call("POST", "/environments", body)
            eid = (created or {}).get("id") or find_environment(v, e["name"])
            what = "created"
        if stc not in (200, 201, 202, 204) or not eid:
            raise LayerFailed(f"layer 4: {e['name']} answered HTTP {stc}")
        env_ids[e["name"]] = eid
        items.append(f"{e['name']} {what} on {e['runtime']}")
        link("environment", eid)
    layer(4, "environments", f"{'would upsert' if dry else 'upserted'} {len(env_ids)}", items, "plan" if dry else "ok")

    # 5. actions, each carrying its layer-4 environment id
    if m.get("actions") and not env_ids:
        raise LayerFailed("layer 5 cannot run without environment ids from layer 4")
    items, module = [], cats["actions"]
    for a in m.get("actions") or []:
        meta = json.loads((d / a["source"] / "metadata.json").read_text(encoding="utf-8"))
        existing = find_action(v, module, meta["name"])
        aid = existing or action_id(module, meta["name"])
        env_id = env_ids.get(a["environment_ref"])
        if dry:
            items.append(f"would import {module}/{meta['name']} "
                         f"({'overwriting the action of the same id' if existing else 'new'}), environment "
                         f"{a['environment_ref']}")
            continue
        _, payload = package_action(d / a["source"], env_id, aid)
        stc, body, _ = v.upload("/actions", f"{meta['name']}.action", payload, {"categoryName": module})
        got = (body or {}).get("id") or find_action(v, module, meta["name"])
        if stc not in (200, 201, 202) or not got:
            raise LayerFailed(f"layer 5: {module}/{meta['name']} answered HTTP {stc} and is not listed")
        items.append(f"{module}/{meta['name']} imported{' over the existing action' if existing else ''}, "
                     f"environment {a['environment_ref']} written into it")
        link("action", got)
    layer(5, "actions", f"{'would import' if dry else 'imported'} {len(m.get('actions') or [])}", items,
          "plan" if dry else "ok")

    # 6. workflows, every conf-id rewritten to this appliance's element
    items = []
    for w in m.get("workflows") or []:
        text = _workflow_xml(d / w["source"]).read_text(encoding="utf-8")
        planned = [n for n, i in config_ids.items() if str(i).startswith("<planned")]
        if dry:
            items.append(f"would import {Path(w['source']).name} (id from its XML), rebinding its conf-id bindings to "
                         f"{', '.join(config_ids) or 'nothing declared'}")
            continue
        if planned:
            raise LayerFailed(f"layer 6: bindings would point at planned identifiers for {planned}")
        text2, n = rebind(text, config_ids)
        wid = workflow_id(text2)
        stc, _, _ = v.upload(f"/workflows?categoryId={cat_ids['workflows']}", f"{Path(w['source']).name}.workflow",
                             package_workflow(text2))
        if stc not in (200, 201, 202):
            raise LayerFailed(f"layer 6: {Path(w['source']).name} answered HTTP {stc}")
        items.append(f"{Path(w['source']).name} imported, {n} configuration binding(s) rebound")
        if wid:
            link("workflow", wid)
    layer(6, "workflows", f"{'would import' if dry else 'imported'} {len(m.get('workflows') or [])}", items,
          "plan" if dry else "ok")
    if links_made:
        print(f"  package membership (not a layer; an export carries what is linked): {', '.join(links_made)}")
    return out, links_made


# ---------------------------------------------------------------- readback
def readback(v, m):
    """The two identifier bindings, read back: each action's environment, and each workflow's conf-ids."""
    cats, d, results = m["categories"], m["_dir"], []
    envs = {e["name"]: find_environment(v, e["name"]) for e in m.get("environments") or []}
    for a in m.get("actions") or []:
        meta = json.loads((d / a["source"] / "metadata.json").read_text(encoding="utf-8"))
        aid = find_action(v, cats["actions"], meta["name"])
        if not aid:
            results.append({"kind": "action", "name": meta["name"], "ok": False, "says": "not on this appliance"})
            continue
        st, body = v.get(f"/actions/{aid}")
        reported = {k: (body or {}).get(k) for k in ("environment", "environmentName", "actionEnvironmentName",
                                                     "runtimeEnvironment") if (body or {}).get(k)}
        want_id, want_name = envs.get(a["environment_ref"]), a["environment_ref"]
        ok = any(val in (want_id, want_name) or (isinstance(val, dict) and want_id in json.dumps(val))
                 for val in reported.values())
        results.append({"kind": "action", "name": meta["name"], "ok": ok,
                        "says": f"reports {sorted(reported) or 'no environment field'}; wants {want_name}"})
    for w in m.get("workflows") or []:
        text = _workflow_xml(d / w["source"]).read_text(encoding="utf-8")
        wid = workflow_id(text)
        st, body = v.get(f"/workflows/{wid}/content")
        if st != 200:
            results.append({"kind": "workflow", "name": Path(w["source"]).name, "ok": False,
                            "says": f"its definition answered HTTP {st}"})
            continue
        refs = [((a2.get("value") or {}).get("attribute-reference") or {}) for a2 in (body or {}).get("attrib") or []]
        refs = [r for r in refs if r.get("config-id")]
        for r in refs:
            st2, conf = v.get(f"/configurations/{r['config-id']}")
            ok = st2 == 200
            results.append({"kind": "workflow", "name": Path(w["source"]).name, "ok": ok,
                            "says": (f"conf-id names element '{(conf or {}).get('name')}' here, key "
                                     f"{r.get('config-key')}") if ok else
                                    f"conf-id names no element on this appliance (HTTP {st2})"})
        if not refs:
            results.append({"kind": "workflow", "name": Path(w["source"]).name, "ok": True,
                            "says": "binds no configuration element"})
    for r in results:
        print(f"  {'OK  ' if r['ok'] else 'FAIL'} {r['kind']:<8} {r['name']}: {r['says']}")
    return results


# ---------------------------------------------------------------- teardown
def teardown(v, m):
    """Delete exactly the objects the manifest names: the package first, then the newest layer first. A workflow or a
    configuration element linked into a package was refused with 409 while the package existed, and deleted once it
    was gone; deleting the package leaves its contents in place. Returns (deleted, refused)."""
    cats, d, pkg = m["categories"], m["_dir"], m["package"]["name"]
    done, refused = [], []

    def delete(label, path):
        st, body, raw = v.call("DELETE", path)
        why = ""
        if st not in (200, 202, 204):
            why = ((body or {}).get("details") or (body or {}).get("message") or "") if isinstance(body, dict) else ""
            why = f" ({str(why)[:160]})" if why else ""
        (done if st in (200, 202, 204) else refused).append(f"{label}: HTTP {st}{why}")

    if v.get(f"/packages/{urllib.parse.quote(pkg, safe='')}")[0] == 200:
        delete(f"package {pkg}", f"/packages/{urllib.parse.quote(pkg, safe='')}")

    for w in m.get("workflows") or []:
        wid = workflow_id(_workflow_xml(d / w["source"]).read_text(encoding="utf-8"))
        if v.get(f"/workflows/{wid}")[0] == 200:
            delete(f"workflow {Path(w['source']).name}", f"/workflows/{wid}")
    for a in m.get("actions") or []:
        name = json.loads((d / a["source"] / "metadata.json").read_text(encoding="utf-8"))["name"]
        aid = find_action(v, cats["actions"], name)
        if aid:
            delete(f"action {cats['actions']}/{name}", f"/actions/{aid}")
    for e in m.get("environments") or []:
        eid = find_environment(v, e["name"])
        if eid:
            delete(f"environment {e['name']}", f"/environments/{eid}")
    ccat = find_category(v, "ConfigurationElementCategory", cats["configurations"])
    for c in m.get("configurations") or []:
        cid = find_configuration(v, ccat, c["name"])
        if cid:
            delete(f"configuration {c['name']}", f"/configurations/{cid}")
    for kind, typ in reversed(CATEGORY_KINDS):
        cid = find_category(v, typ, cats[kind])
        if cid:
            delete(f"category {cats[kind]}", f"/categories/{cid}")
    for line in done:
        print(f"  deleted   {line}")
    for line in refused:
        print(f"  REFUSED   {line}")
    return done, refused


# ---------------------------------------------------------------- the record and the command line
def write_record(path, payload):
    text = UUID_RX.sub("{{id}}", json.dumps(payload, indent=1, ensure_ascii=False))
    text = re.sub(r"\b[0-9a-f]{32}\b", "{{id}}", text)  # category and element ids the appliance issues as 32 hex digits
    host = os.environ.get("VRO_HOST")
    if host and host in text:
        raise SystemExit("FATAL: the appliance's host name reached the record")
    Path(path).write_text(text + "\n", encoding="utf-8")


def appliance(v):
    st, a = v.get("/about")
    return {"version": (a or {}).get("version"), "apiVersion": (a or {}).get("api-version")} if st == 200 else {}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    cmds = {"validate", "plan", "deploy", "readback", "teardown"}
    if not argv or argv[0] in ("-h", "--help") or argv[0] not in cmds or len(argv) < 2:
        print(__doc__)
        return 0 if argv and argv[0] in ("-h", "--help") else 2
    cmd, manifest, rest = argv[0], argv[1], argv[2:]
    opts = {}
    allowed = {"deploy": {"--record"}, "readback": {"--record"}, "teardown": {"--confirm"}}.get(cmd, set())
    for i in range(0, len(rest), 2):
        if rest[i] not in allowed or i + 1 >= len(rest):
            raise KeyError(f"{cmd} does not take {rest[i]!r} (it takes {', '.join(sorted(allowed)) or 'nothing'}, each with a value)")
        opts[rest[i]] = rest[i + 1]
    m = load(manifest)
    issues = validate(m)
    for sev, field, msg in issues:
        print(f"  [{sev}] {field}: {msg}")
    blockers = [i for i in issues if i[0] == "BLOCKER"]
    if cmd == "validate" or blockers:
        print(f"{'✗' if blockers else '✓'} manifest {'FAILED' if blockers else 'OK'} ({len(blockers)} blocker(s))")
        return 1 if blockers else 0
    v = Vro()
    if cmd == "teardown":
        if opts.get("--confirm") != m["package"]["name"]:
            raise KeyError("teardown deletes what the manifest names: pass --confirm with the manifest's package name")
        print(f"─── TEARDOWN: {Path(manifest).name} ───")
        _, refused = teardown(v, m)
        return 1 if refused else 0
    if cmd == "readback":
        print(f"─── READBACK: {Path(manifest).name} ───")
        res = readback(v, m)
        if opts.get("--record"):
            write_record(opts["--record"], {"capturedUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                            "appliance": appliance(v), "readback": res})
        return 0 if all(r["ok"] for r in res) else 1
    dry = cmd == "plan"
    print(f"─── {'PLAN' if dry else 'DEPLOY'}: {Path(manifest).name} ───")
    try:
        layers, linked = run_layers(v, m, dry)
    except LayerFailed as e:
        print(f"  ✗ {e}")
        print("✗ Overall: FAILED; later layers were not run")
        return 1
    print("→ Overall: plan complete, nothing written" if dry else "✓ Overall: deployed; now run readback")
    if opts.get("--record"):
        write_record(opts["--record"], {"capturedUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                        "appliance": appliance(v), "layers": layers, "packageLinks": linked})
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyError, PermissionError, json.JSONDecodeError) as e:
        print(f"deploy.py: {e}", file=sys.stderr)
        sys.exit(2)
    except (ReadFailed, urllib.error.URLError, OSError) as e:
        print(f"READ FAILED: {e}", file=sys.stderr)
        sys.exit(3)
    except SystemExit as e:
        if isinstance(e.code, str):
            print(e.code, file=sys.stderr)
            sys.exit(4 if e.code.startswith("FATAL") else 2)
        raise
