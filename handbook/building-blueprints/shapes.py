#!/usr/bin/env python3
"""shapes.py: measure the blueprints an estate holds, and ask the platform whether a template is valid.

A chapter on authoring blueprints can assert what good ones look like. This counts what an estate's ones are,
and checks the templates it teaches against the platform that would run them. It parses every blueprint's
content as YAML rather than searching the text, because a grep for "type:" finds input types and embedded
Kubernetes fields and reports a vocabulary three times larger than the real one:

  1. the SHAPE CENSUS: every blueprint's size, input count, resource count and the set of resource types it
     declares, in every project;
  2. the TYPE USE: which of the declarable resource types are used, and which never are;
  3. the INPUTS: the types inputs are declared with, and for every string input whether it carries a pattern,
     an enumeration (enum or oneOf) or a default, because an unconstrained string is where a request form
     accepts what a deployment then refuses;
  4. the SCHEMA JOIN: every catalog item set against the blueprint of its name, looked for in every project
     (the catalog lists the same items under every project path, while a blueprint lives in one), with what the
     generator adds to each property and how the required list follows which inputs declare a default;
  5. with --validate <dir>, the VALIDATION: every *.blueprint.yaml under the directory sent to the platform's own
     blueprint validation, which answers valid or not with the reasons and creates nothing, beside three
     blueprints that are broken on purpose, so a "valid" is known to come from a validator that can refuse. The
     blueprint and blueprint-request counts are read before and after, and the run stops if either moved.

Sign-in, one of:
  VCFA_REFRESH_TOKEN_FILE   a refresh token minted for the organization, in a file of mode 0600
  VCFA_USER and VCFA_PASSWORD_FILE   a session login as user@org (the password from a file of mode 0600, or
                            VCFA_PASSWORD, the value itself, which lands in the shell's history)
A secret file open to group or other is refused before it is read.

Run:
  export VCFA_HOST=<automation-fqdn> VCFA_ORG=<org>
  export VCFA_USER=<account> VCFA_PASSWORD_FILE=~/.vcf/vcfa-password    # or VCFA_REFRESH_TOKEN_FILE
  export TLS_VERIFY=false                                               # only on a self-signed lab CA
  python3 shapes.py                                          # writes shapes.json
  python3 shapes.py --validate ../day1-provisioning/templates

Exit: 0 written (with --validate, every template valid and every control refused); 1 with --validate, a template
was refused or a control was not; 2 a call failed or the sign-in was refused; 3 with --validate, the blueprint or
request count moved, which a validation must never do; 5 an unknown argument.
"""
import base64
import collections
import glob
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

try:
    import yaml
except ImportError:  # the only dependency, and only for parsing content the platform stores as YAML
    raise SystemExit("this script needs PyYAML: pip install pyyaml") from None

http.client._MAXHEADERS = 1000
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
CCI = "/cci/kubernetes"
BP = "blueprint.cci.vmware.com/v1alpha1"
CAT = "catalog.cci.vmware.com/v1alpha1"
PROJ = "project.cci.vmware.com/v1alpha2"
PLACEHOLDER = re.compile(r"(\{\{[^}]*\}\})")
# Three blueprints broken on purpose. A validator that answers "valid" to all of them is not checking anything.
CONTROLS = {
    "an unknown resource type": "formatVersion: 1\ninputs: {}\nresources:\n  Thing:\n    type: CCI.NotAType\n    properties: {}\n",
    "a namespace missing its required fields": "formatVersion: 1\ninputs: {}\nresources:\n  Namespace:\n    type: CCI.Supervisor.Namespace\n    properties:\n      name: ${input.nowhere}\n",
    "content that is not YAML": "formatVersion: 1\nresources: [unclosed\n",
}


def ctx():
    verify = os.environ.get("TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")
    return ssl.create_default_context() if verify else ssl._create_unverified_context()


def secret(name):
    """A secret from NAME_FILE (a file, mode 0600, its value stripped) or else NAME itself; None when neither is set.
    The file keeps a tier-0 token out of the shell's history and the process list. A file open to group or other is
    refused before it is read; the refusal names the variable and the fix, never the file's content."""
    path = os.environ.get(f"{name}_FILE")
    if path:
        with open(path, encoding="utf-8") as f:
            mode = os.fstat(f.fileno()).st_mode & 0o777
            # Windows makes the mode from the read-only flag alone, so it has no group or other bits to judge.
            if mode & 0o077 and os.name != "nt":
                raise PermissionError(f"{name}_FILE names a file of mode {mode:04o}, open to group or other: "
                                      f'run chmod 600 "${name}_FILE" and try again (the file was not read)')
            return f.read().strip()
    return os.environ.get(name) or None


def fail(msg):
    print(f"FATAL: {msg}")
    sys.exit(2)


class Labels:
    """Estate names become placeholders. The product's own vocabulary never does."""

    RESERVED = {"admin", "view", "edit", "user", "default", "system", "none", "all",
                "string", "integer", "boolean", "number", "object", "array"}

    def __init__(self):
        self.maps = {}

    def reserve(self, *names):
        for n in names:
            if n:
                self.RESERVED = self.RESERVED | {str(n)}

    def get(self, family, name):
        if not name or str(name) in self.RESERVED:
            return name
        m = self.maps.setdefault(family, {})
        if name not in m:
            m[name] = f"{family}-{len(m) + 1}"
        return "{{%s}}" % m[name]

    def scrub(self, text):
        """Replace every registered name, never inside a placeholder already written. An estate can name a project
        exactly what a placeholder says (this one has a project called project-1), and a scrub that reaches into
        "{{project-1}}" turns one project's placeholder into another's."""
        if not isinstance(text, str):
            return text
        # One pass with every name in a single pattern, longest first, so a placeholder written in this pass is
        # never scanned again: replacing one name at a time lets a project named project-2 match inside the
        # "{{project-2}}" just written for the project named project-1.
        label = {real: lab for m in self.maps.values() for real, lab in m.items()}
        names = sorted(label, key=len, reverse=True)
        rx = re.compile(r"(?<![A-Za-z0-9-])(" + "|".join(map(re.escape, names)) + r")(?![A-Za-z0-9-])") if names else None
        parts = PLACEHOLDER.split(text)
        for i in range(0, len(parts), 2):   # the even parts are outside any placeholder
            if rx:
                parts[i] = rx.sub(lambda mt: "{{%s}}" % label[mt.group(1)], parts[i])
            parts[i] = UUID.sub("{{id}}", parts[i])
        return "".join(parts)


def refuse_unknown_args(known, takes_value=()):
    """Refuse any argument this script does not recognise, before a client opens. --help prints the usage above."""
    args = sys.argv[1:]
    if "-h" in args or "--help" in args:
        print(__doc__)
        sys.exit(0)
    unknown = [a for i, a in enumerate(args) if a not in known and not (i and args[i - 1] in takes_value)]
    if unknown or (args and args[-1] in takes_value):
        print(f"unknown or incomplete argument(s) {unknown or args[-1:]}: this script takes {', '.join(sorted(known))} "
              "(see --help)", file=sys.stderr)
        sys.exit(5)


class Vcfa:
    def __init__(self, host, org, refresh_token=None, user=None, password=None):
        """A tenant bearer, from the organization's refresh token or from a session login as user@org. A refused
        mint ends the run with the server's own answer."""
        self.host = host
        if refresh_token:
            self.kind = "refresh token"
            body = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": refresh_token}).encode()
            req = urllib.request.Request(f"https://{host}/oauth/tenant/{org}/token", data=body, method="POST",
                                         headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
        else:
            self.kind = "session login"
            basic = base64.b64encode(f"{user.split('@')[0]}@{org}:{password}".encode()).decode()
            req = urllib.request.Request(f"https://{host}/cloudapi/1.0.0/sessions", method="POST",
                                         headers={"Authorization": f"Basic {basic}", "Accept": "application/json;version=40.0"})
        try:
            with urllib.request.urlopen(req, context=ctx(), timeout=30) as r:
                self.bearer = json.loads(r.read())["access_token"] if refresh_token else r.headers.get("X-VMWARE-VCLOUD-ACCESS-TOKEN")
        except urllib.error.HTTPError as e:
            fail(f"the {self.kind} answered HTTP {e.code}: {e.read().decode(errors='replace')[:200]}")
        except (urllib.error.URLError, OSError) as e:
            fail(f"the {self.kind} did not answer: {e}")
        if not self.bearer:
            fail(f"the {self.kind} answered without a bearer")

    def call(self, method, path, body=None):
        headers = {"Authorization": f"Bearer {self.bearer}", "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(f"https://{self.host}{path}", method=method, headers=headers,
                                     data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(req, context=ctx(), timeout=90) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, raw.decode(errors="replace")[:200]
        except (urllib.error.URLError, OSError) as e:
            return None, str(e)

    def items(self, path):
        """Every item of a Kubernetes-style list at the gateway, following its continue token; a failure ends the run."""
        out, token = [], None
        while True:
            st, body = self.call("GET", f"{CCI}{path}" + (f"?continue={urllib.parse.quote(token)}" if token else ""))
            if st != 200 or not isinstance(body, dict):
                fail(f"GET {CCI}{path} answered {st if st else 'nothing'}")
            out += body.get("items") or []
            token = (body.get("metadata") or {}).get("continue")
            if not token:
                return out

    def total(self, path):
        st, body = self.call("GET", path)
        if st != 200 or not isinstance(body, dict):
            fail(f"GET {path} answered {st if st else 'nothing'}")
        return body.get("totalElements")


def validate(c, L, directory, project_name):
    """Every template under DIRECTORY through the platform's validation, beside the three controls."""
    # The classic project list refuses a sort= parameter (it names OData $orderby); unsorted, it is one page here.
    st, projs = c.call("GET", "/project-service/api/projects?size=200&page=0")
    if st != 200 or not isinstance(projs, dict):
        fail(f"the classic project list answered {st}")
    if (projs.get("totalPages") or 1) > 1:
        fail("the classic project list spans pages and refuses a sort, so a paged read could overlap")
    pid = next((p["id"] for p in projs.get("content") or [] if p.get("name") == project_name), None)
    if not pid:
        fail("the project is not on the classic project list")
    files = sorted(glob.glob(os.path.join(directory, "**", "*.blueprint.yaml"), recursive=True))
    if not files:
        fail(f"no *.blueprint.yaml under {directory}")
    counts = lambda: (c.total("/blueprint/api/blueprints?size=1"), c.total("/blueprint/api/blueprint-requests?size=1"))
    before = counts()
    out = []

    def one(label, content, kind):
        st, v = c.call("POST", "/blueprint/api/blueprint-validation", {"content": content, "projectId": pid})
        if st != 200 or not isinstance(v, dict):
            fail(f"the validation of {label} answered {st}")
        msgs = [" ".join(L.scrub(str(m.get("message") or "")).split())[:240] for m in (v.get("validationMessages") or [])]
        out.append({"subject": label, "kind": kind, "valid": bool(v.get("valid")), "messages": msgs})
        print(f"     {label:<44} {'valid' if v.get('valid') else 'refused'}" + (f": {msgs[0][:90]}" if msgs else ""))

    print(f"\n  validation: {len(files)} template(s) under the directory, and {len(CONTROLS)} controls broken on purpose")
    for f in files:
        one(os.path.relpath(f, directory), open(f, encoding="utf-8").read(), "template")
    for label, content in CONTROLS.items():
        one(label, content, "control")
    after = counts()
    unchanged = before == after
    print(f"     blueprints and blueprint requests: {before[0]} and {before[1]} before, {after[0]} and {after[1]} after"
          + ("" if unchanged else ": THEY MOVED"))
    return {"project": L.get("project", project_name), "results": out, "countsUnchanged": unchanged,
            "templatesValid": sum(1 for r in out if r["kind"] == "template" and r["valid"]),
            "templates": len(files), "controlsRefused": sum(1 for r in out if r["kind"] == "control" and not r["valid"]),
            "controls": len(CONTROLS)}


def main():
    refuse_unknown_args({"--validate"}, takes_value=("--validate",))
    args = sys.argv[1:]
    vdir = args[args.index("--validate") + 1] if "--validate" in args else None
    host, org = os.environ["VCFA_HOST"], os.environ["VCFA_ORG"]
    try:
        refresh, password = secret("VCFA_REFRESH_TOKEN"), secret("VCFA_PASSWORD")
    except OSError as e:   # a secret file that is missing, unreadable or open to group or other
        fail(e)
    user = os.environ.get("VCFA_USER")
    if not refresh and not (user and password):
        fail("set VCFA_REFRESH_TOKEN_FILE, or VCFA_USER with VCFA_PASSWORD_FILE (see --help)")
    out_dir = os.environ.get("OUT_DIR", ".")
    c = Vcfa(host, org, refresh, None if refresh else user, None if refresh else password)
    L = Labels()
    print("shapes.py: every blueprint on this estate, measured rather than described\n")

    projects = [p["metadata"]["name"] for p in c.items(f"/apis/{PROJ}/projects")]
    for p in projects:
        L.get("project", p)
    if not projects:
        fail("no project is visible to this identity")
    declarable = sorted({r["metadata"]["name"] for p in projects for r in c.items(f"/apis/{BP}/namespaces/{p}/blueprintresourcetypes")})
    L.reserve(*declarable)

    census, restypes, intypes, unparsed, decls = [], collections.Counter(), collections.Counter(), 0, 0
    strings = {"total": 0, "pattern": 0, "enumeration": 0, "default": 0, "constrained": 0, "unconstrained": 0}
    blueprints = {}
    for p in projects:
        for b in c.items(f"/apis/{BP}/namespaces/{p}/blueprints"):
            content = (b.get("spec") or {}).get("content") or ""
            name = b["metadata"]["name"]
            L.get("blueprint", name)
            try:
                doc = yaml.safe_load(content) or {}
            except Exception:
                unparsed += 1
                continue
            blueprints[name] = doc
            res = doc.get("resources") or {}
            ins = doc.get("inputs") or {}
            # PARSE, do not grep: "type:" appears on inputs and inside embedded manifests too
            types = sorted({(v or {}).get("type") for v in res.values() if isinstance(v, dict)} - {None})
            restypes.update(types)
            decls += len(res)
            for v in ins.values():
                if not isinstance(v, dict):
                    continue
                intypes[v.get("type")] += 1
                if v.get("type") == "string":
                    strings["total"] += 1
                    has_pattern, has_enum = "pattern" in v, ("enum" in v or "oneOf" in v)
                    strings["pattern"] += has_pattern
                    strings["enumeration"] += has_enum
                    strings["default"] += "default" in v
                    strings["constrained" if (has_pattern or has_enum) else "unconstrained"] += 1
            census.append({"project": L.get("project", p), "bytes": len(content), "inputs": len(ins),
                           "resources": len(res), "resourceTypes": types})
    sizes = sorted(x["bytes"] for x in census) or [0]
    print(f"  census: {len(census)} blueprint(s) across {len(projects)} project(s) parsed ({unparsed} would not parse)")
    print(f"     size {sizes[0]:,} to {sizes[-1]:,} bytes, a {round(sizes[-1] / sizes[0]) if sizes[0] else '?'} times range")
    print(f"     {decls} resource declaration(s) using {len(restypes)} distinct type(s): {dict(restypes)}")
    print(f"     declarable but never used here: {sorted(set(declarable) - set(restypes))}")
    print(f"     input types: {dict(intypes)}")
    print(f"     string inputs: {strings['total']}; {strings['constrained']} carry a pattern or an enumeration "
          f"({strings['pattern']} a pattern, {strings['enumeration']} an enumeration), {strings['default']} a default, "
          f"{strings['unconstrained']} neither a pattern nor an enumeration")

    # ---- the schema join, across every project: the catalog lists the same items under each project path
    item_sets = {p: {i["metadata"]["name"]: i for i in c.items(f"/apis/{CAT}/namespaces/{p}/catalogitems")} for p in projects}
    same_everywhere = len({frozenset(s) for s in item_sets.values()}) == 1
    items = {}
    for s in item_sets.values():
        items.update(s)
    joins, added, req_rule = [], collections.Counter(), collections.Counter()
    unmatched = 0
    for nm, it in sorted(items.items()):
        doc = blueprints.get(nm)
        if doc is None:
            unmatched += 1
            continue
        ins = doc.get("inputs") or {}
        sch = ((it.get("spec") or {}).get("schema") or {})
        props = sch.get("properties") or {}
        req = set(sch.get("required") or [])
        for k, v in ins.items():
            if not isinstance(v, dict):
                continue
            for key in (set(props.get(k, {})) - set(v)):
                added[key] += 1
            if "default" not in v:
                req_rule[(v.get("type"), k in req)] += 1
        joins.append({"blueprint": L.get("blueprint", nm), "inputs": len(ins), "properties": len(props),
                      "identicalKeys": set(ins.keys()) == set(props.keys()), "required": len(req)})
    same = sum(1 for j in joins if j["identicalKeys"])
    props_total = sum(j["properties"] for j in joins)
    print(f"\n  schema join: {len(items)} catalog item(s), the same set under every project: {same_everywhere}; "
          f"{len(joins)} matched to a blueprint of their name in some project, {unmatched} matched to none")
    print(f"     {same} of the {len(joins)} have schema properties whose key set is identical to the blueprint's inputs")
    print(f"     keys the generator adds, counted over {props_total} propert(ies): {dict(added)}")
    print("     inputs declaring no default, by type, and whether they became required:")
    for (t, inreq), n in sorted(req_rule.items(), key=lambda x: str(x[0])):
        print(f"        {str(t):<9} no default, {'required' if inreq else 'NOT required'}: {n}")

    validation = validate(c, L, vdir, projects[0]) if vdir else None

    payload = {"captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "signIn": c.kind,
               "declarableTypes": declarable, "census": census, "unparsed": unparsed,
               "resourceDeclarations": decls, "resourceTypesUsed": dict(restypes),
               "typesNeverUsed": sorted(set(declarable) - set(restypes)),
               "inputTypes": dict(intypes), "stringInputs": strings, "sizeRange": [sizes[0], sizes[-1]],
               "catalogItems": len(items), "sameItemsUnderEveryProject": same_everywhere, "itemsWithoutABlueprint": unmatched,
               "schemaJoins": joins, "schemaMatches": same, "schemaProperties": props_total,
               "generatorAddsPerProperty": dict(added),
               "requiredByInputType": {f"{t}|{'required' if r else 'not-required'}": n for (t, r), n in req_rule.items()},
               "validation": validation}
    L.get("org", org)
    text = L.scrub(json.dumps(payload, indent=1, ensure_ascii=False))
    for value in (c.bearer, refresh, password, user, host):
        assert not value or value not in text, "an estate value reached the record"
    for word in declarable:
        assert word in text, f"the scrub replaced {word!r}, which is the product's own vocabulary"
    assert "{{{{" not in text, "a placeholder was scrubbed twice"
    bare = PLACEHOLDER.sub("", text)
    for fam, m in L.maps.items():
        for nm in m:
            if nm and re.search(r"(?<![A-Za-z0-9-])" + re.escape(nm) + r"(?![A-Za-z0-9-])", bare):
                shp = re.sub(r"[A-Za-z]", "a", re.sub(r"[0-9]", "9", nm))
                fail(f"a {fam} name ({len(nm)} characters, shape {shp}) reached the record; nothing was written")
    os.makedirs(out_dir, exist_ok=True)
    open(os.path.join(out_dir, "shapes.json"), "w", encoding="utf-8").write(text + "\n")
    print(f"\nwrote shapes.json ({len(census)} blueprints, {len(restypes)} resource type(s) in use of "
          f"{len(declarable)} declarable); every organization name replaced by a placeholder")
    if validation:
        if not validation["countsUnchanged"]:
            sys.exit(3)
        if validation["templatesValid"] < validation["templates"] or validation["controlsRefused"] < validation["controls"]:
            sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
