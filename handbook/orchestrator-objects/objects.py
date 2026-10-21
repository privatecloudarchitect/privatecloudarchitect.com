#!/usr/bin/env python3
"""objects.py: read your own Orchestrator's object tree, and the bindings that hold it together.

Read-only. It creates nothing, imports nothing, and changes nothing. Every call is a GET.

  --inventory        how many of each object kind you have, and how your categories are typed
  --runtimes         every action environment, its runtime, its dependency pins, and whether it resolves
  --bindings ID      for one workflow: the configuration elements and the actions it actually references
  --package NAME     what one package carries, bucket by bucket (an empty package exports nothing)
  --sweep [LIMIT]    every workflow definition read, and how the estate is built
  --record FILE      the counts, written as JSON in the shape the handbook chapter renders

Why this exists: Orchestrator is a tree of seven object kinds held together by three different
binding mechanisms that use three different keys, and nothing in the console shows you the
mechanism. An action points at its runtime by UUID; a workflow points at a configuration element
by UUID plus key name; a workflow points at an action by name path. Two of those three break when
content moves between appliances, and the third does not. Read your own tree before you author
into it.

A workflow calls an action in one of two ways: an action element (an item that names the action), or
a script item that calls System.getModule("<module>").<name>(...). Both are counted as calling an
action; only a script with neither is inline.

Env:   VRO_HOST; VRO_TOKEN_FILE, a bearer this appliance accepts in a file of mode 0600 (VRO_TOKEN, the value
       itself, is still read when no file is named); TLS_VERIFY=false for an appliance whose private CA you
       have not installed
Usage: python3 objects.py --inventory | --runtimes | --bindings WORKFLOW_ID | --package NAME | --sweep [LIMIT]
       python3 objects.py --record objects.json [--no-sweep] [--with-package NAME]
Exit:  0 answered · 2 usage error, or a token file open to group or other · 3 a read failed
"""
from __future__ import annotations
import argparse, json, os, re, ssl, sys, time
from collections import Counter
from urllib import error as _er, parse as _ps, request as _rq

BASE = "/vco/api"
CTX = ssl.create_default_context()
if os.environ.get("TLS_VERIFY", "true").strip().lower() in ("0", "false", "no", "off"):
    CTX.check_hostname, CTX.verify_mode = False, ssl.CERT_NONE     # a private CA you have not installed
CALL = re.compile(r'System\.getModule\("([^"]+)"\)\.([A-Za-z_][A-Za-z0-9_]*)')


def secret(name):
    """A secret from NAME_FILE (a file, mode 0600, its value stripped) or else NAME itself; None when neither is set.
    A file open to group or other is refused before it is read; the refusal names the variable and the fix."""
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


HOST, TOKEN = "", ""

UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

# The five category types Orchestrator keeps in separate namespaces. A name is only unique
# within its type, so "Configuration" as a WorkflowCategory and as a ConfigurationElementCategory
# are two different folders that happen to share a label.
CATEGORY_TYPES = ("WorkflowCategory", "ScriptModuleCategory", "ResourceElementCategory",
                  "ConfigurationElementCategory", "PolicyTemplateCategory")

# The eight typed buckets a package carries. A package is a manifest of references, not a folder
# that contains objects: deleting the package does not delete what it lists.
PACKAGE_BUCKETS = ("actions", "workflows", "configurations", "environments",
                   "resources", "policy-templates", "environment-repositories", "workflowTokens")


def get(path: str):
    req = _rq.Request(f"https://{HOST}{BASE}{path}", headers={
        "Authorization": f"Bearer {TOKEN}", "Accept": "application/json"})
    with _rq.urlopen(req, context=CTX, timeout=120) as r:
        return json.loads(r.read().decode())


def listing(path: str) -> list[dict]:
    """Flatten a vRO list response.

    The 9.1 shape is {"link": [{"attributes": [{"name": .., "value": ..}], "href": ..}], "total": N}.
    An attribute whose value is null omits the "value" key entirely rather than carrying a null,
    so .get() is load-bearing here: attr["value"] raises on every empty description.
    """
    j = get(path)
    return [{a["name"]: a.get("value") for a in li.get("attributes", [])}
            for li in j.get("link", [])]


def action_calls(item: dict) -> tuple[set, set]:
    """(by element, by script): the actions one workflow item calls, as <module>/<name>. An action element also
    carries a generated script that makes the same call, so a script call is counted only on an item that is not
    an element, and the two forms never overlap."""
    if item.get("script-module"):
        return {item["script-module"]}, set()
    text = (item.get("script") or {}).get("value") if isinstance(item.get("script"), dict) else item.get("script")
    return set(), {f"{m}/{n}" for m, n in CALL.findall(text or "")}


def inventory() -> dict:
    """Counts only. No name, host, or identifier from your estate leaves this function."""
    pkgs = listing("/packages")
    acts = listing("/actions")
    wfs = listing("/workflows")
    cats = listing("/categories")
    cfgs = listing("/configurations")
    envs = listing("/environments")

    # A package's name is free text. Content that arrived with a plugin commonly carries a
    # generated one, so counting which packages a human named is the honest measure of how much
    # of the namespace is yours to navigate.
    named = [p for p in pkgs if p.get("name") and not UUID.match(p["name"])]

    # An action is addressed as "<category>/<name>", and that prefix is its ScriptModuleCategory.
    # The two counts below are read from different endpoints and should agree; when they do not,
    # the tree has a category holding no actions, which is worth knowing before you add one.
    act_prefixes = {(a.get("fqn") or "/").rsplit("/", 1)[0] for a in acts if a.get("fqn")}
    cat_types = Counter(c.get("type") for c in cats)

    return {
        "objects": {"packages": len(pkgs), "actions": len(acts), "workflows": len(wfs),
                    "categories": len(cats), "configurationElements": len(cfgs),
                    "actionEnvironments": len(envs)},
        "packageNaming": {"total": len(pkgs), "humanNamed": len(named),
                          "generatedName": len(pkgs) - len(named)},
        "categoryTypes": {t: cat_types.get(t, 0) for t in CATEGORY_TYPES},
        "categoryTypesOther": {k: v for k, v in cat_types.items() if k not in CATEGORY_TYPES},
        "actionCategoryAgreement": {"scriptModuleCategories": cat_types.get("ScriptModuleCategory", 0),
                                    "distinctActionPrefixes": len(act_prefixes),
                                    "agree": cat_types.get("ScriptModuleCategory", 0) == len(act_prefixes)},
    }


def runtimes() -> list[dict]:
    """Every action environment with its runtime, pins, and whether the appliance can resolve it."""
    out = []
    for e in listing("/environments"):
        d = get(f"/environments/{e['id']}")
        deps = d.get("dependencies") or {}
        out.append({
            "runtime": d.get("runtime"),
            "dependencies": len(deps),
            # An empty version string is an accepted, unpinned dependency: the environment builds
            # against whatever the index serves that day. It is not an error and it is not a pin.
            "unpinned": sorted(k for k, v in deps.items() if not v),
            "pinned": sorted(k for k, v in deps.items() if v),
            "memoryLimit": d.get("runtimeMemoryLimit"),
            "timeout": d.get("runtimeTimeout"),
            # Present when the appliance does not offer the runtime this environment names, typically a
            # selector an upgrade left in place (MISSING_RUNTIME). On 9.1.1 such an environment still ran
            # its action, on the newest runtime of the same family: the flag is not a failure.
            "validationMessage": d.get("validationMessage"),
            "bundleBuilt": bool(d.get("bundleHash")),
        })
    return out


def bindings(workflow_id: str) -> dict:
    """The three binding mechanisms, read off one workflow's live definition.

    Note the asymmetry this prints. Two of the three carry a UUID, which is why moving content
    between appliances rebinds them; the third carries a name path, which survives the move.
    """
    c = get(f"/workflows/{workflow_id}/content")
    atts = c.get("attrib") or []
    to_config, plain = [], 0
    for a in atts:
        ref = ((a.get("value") or {}).get("attribute-reference") or {}) if isinstance(a.get("value"), dict) else {}
        if ref.get("config-id"):
            to_config.append({"attribute": a.get("name"), "type": a.get("type"),
                              "configKey": ref.get("config-key")})
        else:
            plain += 1
    items = c.get("workflow-item") or []
    by_element, by_script, calling, inline = set(), set(), 0, 0
    for it in items:
        e, sc = action_calls(it)
        by_element |= e
        by_script |= sc
        calling += bool(e or sc)
        inline += bool(it.get("script") and not (e or sc))
    return {
        "attributes": {"total": len(atts), "boundToConfigurationElement": len(to_config), "plain": plain},
        "configurationBindings": to_config,
        "actionBindings": sorted(by_element | by_script),
        "actionsByElement": sorted(by_element),
        "actionsByScript": sorted(by_script),
        "items": {"total": len(items), "callingAnAction": calling, "inlineScript": inline},
    }


def sweep(limit: int = 0) -> dict:
    """Read every workflow's definition and count how the estate is actually built.

    This is the expensive call: one request per workflow. It answers a question no single
    workflow can, and the answer decides how much of this series applies to you. A workflow
    whose items are all inline script needs no action, no runtime and no packaging; a workflow
    that calls actions needs all three, in order.
    """
    wfs = listing("/workflows")
    if limit:
        wfs = wfs[:limit]
    stats = {"workflowsRead": 0, "unreadable": 0,
             "withConfigBinding": 0, "withActionCall": 0, "withActionElement": 0, "withScriptedActionCall": 0,
             "inlineOnly": 0, "empty": 0,
             "items": 0, "itemsCallingAction": 0, "itemsActionElement": 0, "itemsScriptedActionCall": 0,
             "itemsInlineScript": 0, "attributes": 0, "attributesBoundToConfig": 0}
    for w in wfs:
        try:
            c = get(f"/workflows/{w['id']}/content")
        except Exception:
            stats["unreadable"] += 1
            continue
        stats["workflowsRead"] += 1
        atts = c.get("attrib") or []
        bound = sum(1 for a in atts
                    if isinstance(a.get("value"), dict)
                    and ((a["value"].get("attribute-reference") or {}).get("config-id")))
        items = c.get("workflow-item") or []
        found = [action_calls(it) for it in items]
        by_element = sum(1 for e, _ in found if e)
        by_script = sum(1 for _, sc in found if sc)
        calls = sum(1 for e, sc in found if e or sc)
        inline = sum(1 for it, (e, sc) in zip(items, found) if it.get("script") and not (e or sc))
        stats["attributes"] += len(atts)
        stats["attributesBoundToConfig"] += bound
        stats["items"] += len(items)
        stats["itemsCallingAction"] += calls
        stats["itemsActionElement"] += by_element
        stats["itemsScriptedActionCall"] += by_script
        stats["itemsInlineScript"] += inline
        stats["withActionElement"] += bool(by_element)
        stats["withScriptedActionCall"] += bool(by_script)
        if bound:
            stats["withConfigBinding"] += 1
        if calls:
            stats["withActionCall"] += 1
        elif inline:
            stats["inlineOnly"] += 1
        else:
            stats["empty"] += 1
    return stats


def show_sweep(limit: int) -> None:
    s = sweep(limit)
    n = s["workflowsRead"]
    print(f"Read {n} workflow definitions ({s['unreadable']} unreadable)\n")
    print(f"  {s['withActionCall']:5d}  call at least one action ({s['withActionElement']} by an action element, "
          f"{s['withScriptedActionCall']} from a script)")
    print(f"  {s['inlineOnly']:5d}  are inline script only (no action, no runtime, no packaging)")
    print(f"  {s['empty']:5d}  have neither")
    print(f"  {s['withConfigBinding']:5d}  bind at least one attribute to a configuration element")
    print(f"\n  items: {s['items']} total, {s['itemsCallingAction']} call an action "
          f"({s['itemsActionElement']} elements, {s['itemsScriptedActionCall']} scripts), "
          f"{s['itemsInlineScript']} are inline script")
    print(f"  attributes: {s['attributes']} total, {s['attributesBoundToConfig']} bound to a configuration element")
    if n:
        print(f"\n  The split decides how much of this applies to you: a workflow that never calls")
        print(f"  an action needs no runtime and no packaging at all.")


# ─────────────────────────────────────────────────────────────────── display

def show_inventory() -> None:
    inv = inventory()
    o = inv["objects"]
    print("Object kinds on this appliance\n")
    for k in ("packages", "categories", "workflows", "actions", "configurationElements", "actionEnvironments"):
        print(f"  {o[k]:6d}  {k}")

    n = inv["packageNaming"]
    print(f"\nPackage namespace: {n['humanNamed']} of {n['total']} carry a name somebody chose; "
          f"{n['generatedName']} carry a generated one.")
    print("  Your own package name is the only thing that makes your content findable in that list.")

    print("\nCategories are typed, and a name is unique only within its type:")
    for t, c in inv["categoryTypes"].items():
        print(f"  {c:6d}  {t}")
    for t, c in inv["categoryTypesOther"].items():
        print(f"  {c:6d}  {t}   (not in this chapter's list; report it)")

    a = inv["actionCategoryAgreement"]
    verdict = "agree" if a["agree"] else "DISAGREE: a category holds no actions, or an action has no category"
    print(f"\nAction categories: {a['scriptModuleCategories']} ScriptModuleCategory records vs "
          f"{a['distinctActionPrefixes']} distinct action name prefixes -> {verdict}")


def show_runtimes() -> None:
    rs = runtimes()
    print(f"{len(rs)} action environments\n")
    for r in rs:
        flag = "  <- NOT OFFERED: " + str(r["validationMessage"]) if r["validationMessage"] else ""
        print(f"  runtime={r['runtime']}{flag}")
        print(f"      dependencies {r['dependencies']}  pinned {len(r['pinned'])}  unpinned {len(r['unpinned'])}"
              f"   bundle {'built' if r['bundleBuilt'] else 'not built'}")
        print(f"      memoryLimit={r['memoryLimit']}  timeout={r['timeout']}")
        if r["unpinned"]:
            print(f"      unpinned: {', '.join(r['unpinned'])}"
                  "   <- builds against whatever the index serves that day")
    flagged = [r for r in rs if r["validationMessage"]]
    if flagged:
        print(f"\n{len(flagged)} environment(s) name a runtime this appliance does not offer. On VCF Automation 9.1.1")
        print("such an environment ran its action on the newest runtime of the same family, so the flag is not")
        print("a failure. What can fail is the code meeting that newer runtime: prove it there before relying on it.")


def show_bindings(workflow_id: str) -> None:
    b = bindings(workflow_id)
    at, it = b["attributes"], b["items"]
    print(f"Workflow: {at['total']} attributes, {it['total']} items\n")
    print(f"  Configuration element bindings: {at['boundToConfigurationElement']} of {at['total']} attributes")
    print("    key = config-id (a UUID) + config-key (a name inside that element)")
    for c in b["configurationBindings"]:
        print(f"      {c['attribute']}  ({c['type']})  <- {c['configKey']}")
    print(f"\n  Action bindings: {len(b['actionBindings'])} distinct actions, called by {it['callingAnAction']} "
          f"of {it['total']} items")
    print("    key = <module>/<name>, a name path. No UUID.")
    for m in b["actionBindings"]:
        how = "element" if m in b["actionsByElement"] else "script"
        print(f"      {m}   ({how})")
    print(f"\n  Inline scripted items (JavaScript that calls no action): {it['inlineScript']}")
    print("\n  Two of these bindings carry a UUID and one carries a name. That is the whole reason")
    print("  content has to be deployed in dependency order rather than in any order you like.")


def package(name: str) -> dict:
    """What one package carries, bucket by bucket. A package is a manifest of references: the objects exist
    whether or not a package lists them, and an export carries only what is listed."""
    req = _rq.Request(f"https://{HOST}{BASE}/packages/{_ps.quote(name, safe='')}", headers={
        "Authorization": f"Bearer {TOKEN}", "Accept": "application/json"})
    with _rq.urlopen(req, context=CTX, timeout=120) as r:
        j = json.loads(r.read().decode())
    return {b: len(j.get(b) or []) for b in PACKAGE_BUCKETS}


def show_package(name: str) -> None:
    buckets = package(name)
    total = sum(buckets.values())
    print(f"Package: {total} references\n")
    for b, n in buckets.items():
        print(f"  {n:5d}  {b}")
    if not total:
        print("\n  EMPTY: an export of this package carries nothing. Add each object's category to it.")


def show_record(path: str, with_sweep: bool = True, with_package: str | None = None) -> None:
    """The record the chapter renders. Counts and product vocabulary only, by construction.

    The sweep is included by default because the chapter's opening claim is the split between
    workflows that call actions and workflows that are inline script only, and that claim has to
    be measured over every workflow rather than sampled. It costs one request per workflow.
    """
    inv = inventory()
    rs = runtimes()
    sw = sweep() if with_sweep else {}
    rec = {
        "captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "objects": inv["objects"],
        "packageNaming": inv["packageNaming"],
        "categoryTypes": inv["categoryTypes"],
        "actionCategoryAgreement": inv["actionCategoryAgreement"],
        "runtimes": {
            "total": len(rs),
            "runtimes": sorted({r["runtime"] for r in rs if r["runtime"]}),
            "notOffered": sum(1 for r in rs if r["validationMessage"]),
            "withUnpinnedDependencies": sum(1 for r in rs if r["unpinned"]),
            "fullyPinned": sum(1 for r in rs if r["pinned"] and not r["unpinned"]),
            "noDependencies": sum(1 for r in rs if not r["pinned"] and not r["unpinned"]),
        },
        "sweep": sw,
    }
    if with_package:
        rec["package"] = package(with_package)    # bucket counts only; the name stays out of the record
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(rec, indent=1) + "\n")
    print(f"wrote {path}: counts and product vocabulary only, no name, host or identifier from the appliance")


def main(a) -> int:
    global HOST, TOKEN
    HOST, TOKEN = os.environ.get("VRO_HOST", ""), secret("VRO_TOKEN")
    if not HOST or not TOKEN:
        print("objects.py: set VRO_HOST and VRO_TOKEN_FILE (or VRO_TOKEN)", file=sys.stderr)
        return 2
    if a.inventory: show_inventory()
    elif a.runtimes: show_runtimes()
    elif a.bindings: show_bindings(a.bindings)
    elif a.package: show_package(a.package)
    elif a.sweep is not None: show_sweep(a.sweep)
    else: show_record(a.record, not a.no_sweep, a.with_package)
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    one = ap.add_mutually_exclusive_group(required=True)
    one.add_argument("--inventory", action="store_true")
    one.add_argument("--runtimes", action="store_true")
    one.add_argument("--bindings", metavar="WORKFLOW_ID")
    one.add_argument("--package", metavar="NAME")
    one.add_argument("--sweep", nargs="?", type=int, const=0, metavar="LIMIT",
                     help="read every workflow definition and count how the estate is built")
    one.add_argument("--record", metavar="FILE")
    ap.add_argument("--no-sweep", action="store_true",
                    help="with --record: skip the per-workflow sweep (faster, fewer answers)")
    ap.add_argument("--with-package", metavar="NAME",
                    help="with --record: add one package's bucket counts (not its name) to the record")
    args = ap.parse_args()
    if (args.no_sweep or args.with_package) and not args.record:
        ap.error("--no-sweep and --with-package go with --record")
    try:
        sys.exit(main(args))
    except PermissionError as e:
        print(f"objects.py: {e}", file=sys.stderr)
        sys.exit(2)
    except (_er.URLError, OSError, ValueError) as e:
        print(f"objects.py: a read failed: {getattr(e, 'code', '') or e}", file=sys.stderr)
        sys.exit(3)
