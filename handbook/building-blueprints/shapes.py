#!/usr/bin/env python3
"""shapes.py: read every blueprint on an estate and measure what shape they actually are.

A chapter can assert that blueprints share one shape. This counts it. It parses every blueprint's content as
YAML rather than searching the text, because a grep for "type:" finds input types and embedded Kubernetes
fields and reports a vocabulary three times larger than the real one:

  1. the SHAPE CENSUS: every blueprint's size, input count, resource count and the set of resource types it
     declares. If one shape really does carry an estate from a single machine to a whole application, that
     shows up as a wide size range over a narrow type set;
  2. the TYPE USE: which of the declarable resource types are actually used, and which are never used at all;
  3. the INPUT VOCABULARY: the types a blueprint's inputs are declared with, counted;
  4. the SCHEMA JOIN: for every blueprint with a catalog item, whether the item's generated input schema has
     exactly the blueprint's input keys, what the generator adds to each property, and how the required list
     relates to which inputs declare a default.

Read-only throughout.

Run:
  export VCFA_HOST=<automation-fqdn> VCFA_ORG=<org>
  export VCFA_REFRESH_TOKEN_FILE=/path/to/refresh-token    # mode 0600
  export TLS_VERIFY=false                                  # only on a self-signed lab CA
  python3 shapes.py
"""
import collections
import http.client
import json
import os
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

try:
    import yaml
except ImportError:  # the only dependency, and only for parsing content the platform stores as YAML
    raise SystemExit("this script needs PyYAML: pip install pyyaml")

http.client._MAXHEADERS = 1000
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
CCI = "/cci/kubernetes"
BP = "blueprint.cci.vmware.com/v1alpha1"
CAT = "catalog.cci.vmware.com/v1alpha1"
PROJ = "project.cci.vmware.com/v1alpha2"


def ctx():
    verify = os.environ.get("TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")
    return ssl.create_default_context() if verify else ssl._create_unverified_context()


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
        if not isinstance(text, str):
            return text
        known = [(r, l) for m in self.maps.values() for r, l in m.items()]
        for real, label in sorted(known, key=lambda kv: -len(kv[0])):
            text = re.sub(r"(?<![A-Za-z0-9-])" + re.escape(real) + r"(?![A-Za-z0-9-])", "{{%s}}" % label, text)
        return UUID.sub("{{id}}", text)


def main():
    host, org = os.environ["VCFA_HOST"], os.environ["VCFA_ORG"]
    refresh = open(os.environ["VCFA_REFRESH_TOKEN_FILE"], encoding="utf-8").read().strip()
    out_dir = os.environ.get("OUT_DIR", ".")
    L = Labels()
    body = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": refresh}).encode()
    req = urllib.request.Request(f"https://{host}/oauth/tenant/{org}/token", data=body, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded",
                                          "Accept": "application/json"})
    with urllib.request.urlopen(req, context=ctx(), timeout=30) as r:
        bearer = json.loads(r.read())["access_token"]

    def gw(path):
        rq = urllib.request.Request(f"https://{host}{CCI}{path}",
                                    headers={"Authorization": f"Bearer {bearer}", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(rq, context=ctx(), timeout=90) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            return e.code, {}
        except (urllib.error.URLError, OSError):
            return None, {}

    print("shapes.py: every blueprint on this estate, measured rather than described\n")
    st, pl = gw(f"/apis/{PROJ}/projects")
    projects = [p["metadata"]["name"] for p in ((pl.get("items") or []) if st == 200 else [])]
    for p in projects:
        L.get("project", p)
    if not projects:
        raise SystemExit("no project is visible to this identity")

    st, rts = gw(f"/apis/{BP}/namespaces/{projects[0]}/blueprintresourcetypes")
    declarable = sorted(r["metadata"]["name"] for r in ((rts.get("items") or []) if st == 200 else []))
    L.reserve(*declarable)

    census, restypes, intypes, unparsed = [], collections.Counter(), collections.Counter(), 0
    decls = 0
    for p in projects:
        st, bs = gw(f"/apis/{BP}/namespaces/{p}/blueprints")
        for b in ((bs.get("items") or []) if st == 200 else []):
            content = (b.get("spec") or {}).get("content") or ""
            L.get("blueprint", b["metadata"]["name"])
            try:
                doc = yaml.safe_load(content) or {}
            except Exception:
                unparsed += 1
                continue
            res = doc.get("resources") or {}
            ins = doc.get("inputs") or {}
            # PARSE, do not grep: "type:" appears on inputs and inside embedded manifests too
            types = sorted({(v or {}).get("type") for v in res.values() if isinstance(v, dict)} - {None})
            restypes.update(types)
            decls += len(res)
            for v in ins.values():
                if isinstance(v, dict):
                    intypes[v.get("type")] += 1
            census.append({"project": L.scrub(p), "bytes": len(content), "inputs": len(ins),
                           "resources": len(res), "resourceTypes": types})
    sizes = sorted(x["bytes"] for x in census) or [0]
    print(f"  census: {len(census)} blueprint(s) parsed ({unparsed} would not parse)")
    print(f"     size {sizes[0]:,} to {sizes[-1]:,} bytes, a {round(sizes[-1] / sizes[0]) if sizes[0] else '?'} times range")
    print(f"     {decls} resource declaration(s) using {len(restypes)} distinct type(s): {dict(restypes)}")
    print(f"     declarable but never used here: {sorted(set(declarable) - set(restypes))}")
    print(f"     input types: {dict(intypes)}")

    # ---- the schema join
    joins, added, req_rule = [], collections.Counter(), collections.Counter()
    for p in projects:
        st, bs = gw(f"/apis/{BP}/namespaces/{p}/blueprints")
        st, ci = gw(f"/apis/{CAT}/namespaces/{p}/catalogitems")
        items = {i["metadata"]["name"]: i for i in ((ci.get("items") or []) if st == 200 else [])}
        for b in ((bs.get("items") or []) if st == 200 else []):
            nm = b["metadata"]["name"]
            it = items.get(nm)
            if not it:
                continue
            try:
                ins = (yaml.safe_load((b.get("spec") or {}).get("content") or "") or {}).get("inputs") or {}
            except Exception:
                continue
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
            joins.append({"blueprint": L.scrub(nm), "inputs": len(ins), "properties": len(props),
                          "identicalKeys": set(ins.keys()) == set(props.keys()),
                          "required": len(req)})
    same = sum(1 for j in joins if j["identicalKeys"])
    print(f"\n  schema join: {len(joins)} blueprint(s) have a catalog item; "
          f"{same} of them have schema properties whose key set is identical to the blueprint's inputs")
    print(f"     keys the generator adds to every property: {dict(added)}")
    print("     inputs declaring no default, by type, and whether they became required:")
    for (t, inreq), c in sorted(req_rule.items(), key=lambda x: str(x[0])):
        print(f"        {str(t):<9} no default, {'required' if inreq else 'NOT required'}: {c}")

    payload = {"captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "declarableTypes": declarable, "census": census, "unparsed": unparsed,
               "resourceDeclarations": decls, "resourceTypesUsed": dict(restypes),
               "typesNeverUsed": sorted(set(declarable) - set(restypes)),
               "inputTypes": dict(intypes), "sizeRange": [sizes[0], sizes[-1]],
               "schemaJoins": joins, "schemaMatches": same,
               "generatorAddsPerProperty": dict(added),
               "requiredByInputType": {f"{t}|{'required' if r else 'not-required'}": c
                                       for (t, r), c in req_rule.items()}}
    text = L.scrub(UUID.sub("{{id}}", json.dumps(payload, indent=1, ensure_ascii=False)))
    for secret in (bearer, refresh, host, org):
        assert secret not in text, "an estate value reached the record"
    for word in declarable:
        assert word in text, f"the scrub replaced {word!r}, which is the product's own vocabulary"
    bare = re.sub(r"\{\{[^}]*\}\}", "", text)
    for fam, m in L.maps.items():
        for nm in m:
            if nm and re.search(r"(?<![A-Za-z0-9-])" + re.escape(nm) + r"(?![A-Za-z0-9-])", bare):
                shp = re.sub(r"[A-Za-z]", "a", re.sub(r"[0-9]", "9", nm))
                raise SystemExit(f"FATAL: a {fam} name ({len(nm)} characters, shape {shp}) reached the record")
    os.makedirs(out_dir, exist_ok=True)
    open(os.path.join(out_dir, "shapes.json"), "w", encoding="utf-8").write(text + "\n")
    print(f"\nwrote shapes.json ({len(census)} blueprints, {len(restypes)} resource type(s) in use of "
          f"{len(declarable)} declarable); every organization name replaced by a placeholder")


if __name__ == "__main__":
    main()
