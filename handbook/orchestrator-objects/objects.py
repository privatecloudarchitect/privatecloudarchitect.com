#!/usr/bin/env python3
"""objects.py: read your own Orchestrator's object tree, and the bindings that hold it together.

Read-only. It creates nothing, imports nothing, and changes nothing. Four answers:

  --inventory   how many of each object kind you have, and how your categories are typed
  --runtimes    every action environment, its runtime, its dependency pins, and whether it resolves
  --bindings    for one workflow: the configuration elements and the actions it actually references
  --record      the counts, written as JSON in the shape the handbook chapter renders

Why this exists: Orchestrator is a tree of seven object kinds held together by three different
binding mechanisms that use three different keys, and nothing in the console shows you the
mechanism. An action points at its runtime by UUID; a workflow points at a configuration element
by UUID plus key name; a workflow points at an action by name path. Two of those three break when
content moves between appliances, and the third does not. Read your own tree before you author
into it.

Usage:
    export VRO_HOST=orchestrator.example.net
    export VRO_TOKEN=<a bearer this appliance accepts>
    python objects.py --inventory
    python objects.py --bindings <workflow-uuid>
"""
from __future__ import annotations
import argparse, json, os, re, ssl, sys
from collections import Counter
from urllib import request as _rq

HOST = os.environ.get("VRO_HOST", "")
TOKEN = os.environ.get("VRO_TOKEN", "")
BASE = "/vco/api"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE          # lab appliances commonly carry a private CA

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
    if not HOST or not TOKEN:
        sys.exit("set VRO_HOST and VRO_TOKEN first")
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
            # Present only when the appliance cannot resolve the runtime this environment names.
            # The environment still exists, still lists, and still gets referenced by actions.
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
    to_action = sorted({it.get("script-module") for it in items if it.get("script-module")})
    scripted = sum(1 for it in items if it.get("script") and not it.get("script-module"))
    return {
        "attributes": {"total": len(atts), "boundToConfigurationElement": len(to_config), "plain": plain},
        "configurationBindings": to_config,
        "actionBindings": to_action,
        "items": {"total": len(items), "callingAnAction": len(to_action), "inlineScript": scripted},
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
             "withConfigBinding": 0, "withActionCall": 0, "inlineOnly": 0, "empty": 0,
             "items": 0, "itemsCallingAction": 0, "itemsInlineScript": 0,
             "attributes": 0, "attributesBoundToConfig": 0}
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
        calls = sum(1 for it in items if it.get("script-module"))
        inline = sum(1 for it in items if it.get("script") and not it.get("script-module"))
        stats["attributes"] += len(atts)
        stats["attributesBoundToConfig"] += bound
        stats["items"] += len(items)
        stats["itemsCallingAction"] += calls
        stats["itemsInlineScript"] += inline
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
    print(f"  {s['withActionCall']:5d}  call at least one action")
    print(f"  {s['inlineOnly']:5d}  are inline script only (no action, no runtime, no packaging)")
    print(f"  {s['empty']:5d}  have neither")
    print(f"  {s['withConfigBinding']:5d}  bind at least one attribute to a configuration element")
    print(f"\n  items: {s['items']} total, {s['itemsCallingAction']} call an action, "
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
        flag = "  <- UNRESOLVED: " + str(r["validationMessage"]) if r["validationMessage"] else ""
        print(f"  runtime={r['runtime']}{flag}")
        print(f"      dependencies {r['dependencies']}  pinned {len(r['pinned'])}  unpinned {len(r['unpinned'])}"
              f"   bundle {'built' if r['bundleBuilt'] else 'not built'}")
        print(f"      memoryLimit={r['memoryLimit']}  timeout={r['timeout']}")
        if r["unpinned"]:
            print(f"      unpinned: {', '.join(r['unpinned'])}"
                  "   <- builds against whatever the index serves that day")
    broken = [r for r in rs if r["validationMessage"]]
    if broken:
        print(f"\n{len(broken)} environment(s) name a runtime this appliance cannot resolve. They still")
        print("list, and an action can still reference one. The failure surfaces when the action runs.")


def show_bindings(workflow_id: str) -> None:
    b = bindings(workflow_id)
    at, it = b["attributes"], b["items"]
    print(f"Workflow: {at['total']} attributes, {it['total']} items\n")
    print(f"  Configuration element bindings: {at['boundToConfigurationElement']} of {at['total']} attributes")
    print("    key = config-id (a UUID) + config-key (a name inside that element)")
    for c in b["configurationBindings"]:
        print(f"      {c['attribute']}  ({c['type']})  <- {c['configKey']}")
    print(f"\n  Action bindings: {it['callingAnAction']} distinct actions across {it['total']} items")
    print("    key = <category>/<name>, a name path. No UUID.")
    for m in b["actionBindings"]:
        print(f"      {m}")
    print(f"\n  Inline scripted items (no action, JavaScript in the workflow): {it['inlineScript']}")
    print("\n  Two of these bindings carry a UUID and one carries a name. That is the whole reason")
    print("  content has to be deployed in dependency order rather than in any order you like.")


def show_record(with_sweep: bool = True) -> None:
    """The record the chapter renders. Counts and product vocabulary only, by construction.

    The sweep is included by default because the chapter's opening claim is the split between
    workflows that call actions and workflows that are inline script only, and that claim has to
    be measured over every workflow rather than sampled. It costs one request per workflow.
    """
    inv = inventory()
    rs = runtimes()
    sw = sweep() if with_sweep else {}
    print(json.dumps({
        "objects": inv["objects"],
        "packageNaming": inv["packageNaming"],
        "categoryTypes": inv["categoryTypes"],
        "actionCategoryAgreement": inv["actionCategoryAgreement"],
        "runtimes": {
            "total": len(rs),
            "runtimes": sorted({r["runtime"] for r in rs if r["runtime"]}),
            "unresolved": sum(1 for r in rs if r["validationMessage"]),
            "withUnpinnedDependencies": sum(1 for r in rs if r["unpinned"]),
            "fullyPinned": sum(1 for r in rs if r["pinned"] and not r["unpinned"]),
            "noDependencies": sum(1 for r in rs if not r["pinned"] and not r["unpinned"]),
        },
        "sweep": sw,
    }, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inventory", action="store_true")
    ap.add_argument("--runtimes", action="store_true")
    ap.add_argument("--bindings", metavar="WORKFLOW_ID")
    ap.add_argument("--sweep", nargs="?", type=int, const=0, metavar="LIMIT",
                    help="read every workflow definition and count how the estate is built")
    ap.add_argument("--record", action="store_true")
    ap.add_argument("--no-sweep", action="store_true",
                    help="with --record: skip the per-workflow sweep (faster, fewer answers)")
    a = ap.parse_args()
    if a.inventory: show_inventory()
    elif a.runtimes: show_runtimes()
    elif a.bindings: show_bindings(a.bindings)
    elif a.sweep is not None: show_sweep(a.sweep)
    elif a.record: show_record(not a.no_sweep)
    else: ap.print_help()
