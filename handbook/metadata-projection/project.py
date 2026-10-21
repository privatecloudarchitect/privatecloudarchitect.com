#!/usr/bin/env python3
"""project.py: project the labels your workloads declare onto the vSphere tags your consumers read, and gate on it.

content.py measures whether the projection holds. This performs it. On an All Apps organization a template
declares Kubernetes labels and every consumer that governs on metadata reads tags, so something has to render one
into the other, and has to keep doing it: a redeploy, a scale-out or a node roll makes a new machine with no tags.
Run this on a schedule. A run that writes nothing is the normal outcome.

It reads three things and decides one:

  1. what each machine DECLARES: the labels on its manifest in the deployment record (Automation), joined to the
     machine by instance UUID, never by name. A cluster's node machines inherit the cluster's labels, found through
     vCenter's folder tree (the namespace folder holds the cluster's folder, which holds its nodes);
  2. what your MAPPING says each label means: a JSON file naming, per concept, the label it is read from, the tag
     category it renders to, the category's cardinality, and the values it accepts (projection.example.json);
  3. what each machine CARRIES: its tags in those categories only (vCenter).

Each (machine, concept) a machine declares lands in one of four outcomes, kept apart because each has its own owner:

  covered     the tag is present and correct                 nobody; this is the goal
  drifted     the tag is absent, or another value is there   the projection; --apply
  unmapped    the label holds a value the mapping refuses    the mapping file; no run can fix it
  undefined   the category or the tag does not exist         whoever defines categories; usually the mapping asked
                                                             for a concept nobody activated

The verdict is GREEN (every declared assignment covered), RED (anything drifted, unmapped or undefined), or
INDETERMINATE: a plane could not be read, or no live machine declares anything, so the run has no subject and has
neither passed nor failed. A ratio over nothing is not a pass.

--apply attaches the tags a drifted assignment lacks, then reads every written machine back. A SINGLE-cardinality
category holding another value is held, not changed, unless --allow-change, which detaches the old value first.

Env:   VCFA_HOST, VCFA_ORG, VCFA_USER (the bare account), VCFA_PASSWORD_FILE (mode 0600);
       VC_HOST, VC_USER, VC_PASSWORD_FILE (mode 0600; tag read, namespace read, and tag attach for --apply);
       TLS_VERIFY=false only on a self-signed lab CA
Usage: python3 project.py --mapping projection.json [--apply [--allow-change]] [--no-cluster-nodes] [--record FILE]
       python3 project.py --self-test           the decision, on the shipped fixtures, offline
Exit:  0 GREEN · 1 RED · 2 usage error, or a password file open to group or other · 3 INDETERMINATE
       · 4 an --apply that did not read back as written
"""

from __future__ import annotations

import base64
import json
import os
import sys
import time
from pathlib import Path

from content import POD_FOLDER, _folders, _req, _secret, _vms_in, vc_session

HERE = Path(__file__).resolve().parent
OUTCOMES = ("covered", "drifted", "unmapped", "undefined")


# ─── the mapping ────────────────────────────────────────────────────────────────────────────────


def load_mapping(path):
    """{concept: {label, category, cardinality, closed, values}}, checked. A closed concept accepts only the values
    it lists; an open one renders an unlisted label value as a tag of the same name."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    out = {}
    for name, c in (raw.get("concepts") or {}).items():
        if not c.get("label") or not c.get("category"):
            raise ValueError(f"concept {name!r} needs a label and a category")
        card = c.get("cardinality", "single")
        if card not in ("single", "multiple"):
            raise ValueError(f"concept {name!r}: cardinality is single or multiple, not {card!r}")
        out[name] = {"label": c["label"], "category": c["category"], "cardinality": card,
                     "closed": bool(c.get("closed", True)), "values": dict(c.get("values") or {})}
    if not out:
        raise ValueError("the mapping declares no concept")
    return out


# ─── the decision, pure ─────────────────────────────────────────────────────────────────────────


def decide(machines, mapping, catalog, attached, allow_change=False):
    """The outcome of every (machine, concept) a machine declares, and the writes that would fix the drift.

    machines   [{uuid, name, labels, inheritedFrom}]: labels already resolved, a node carrying its cluster's
    catalog    {category: {tag name: tag id}} for the mapped categories that exist on the vCenter
    attached   {uuid: {category: [tag names]}}
    Returns (rows, actions): rows are {uuid, name, concept, outcome, want, have}; actions are
    {uuid, name, category, attach (tag id), detach ([tag ids]), want, have}, one per drifted row that may be written.
    """
    rows, actions = [], []
    for m in machines:
        for concept, c in mapping.items():
            label = (m.get("labels") or {}).get(c["label"])
            if label is None:
                continue                                   # this machine does not declare this concept
            want = c["values"].get(label, None if c["closed"] else label)
            have = list((attached.get(m["uuid"]) or {}).get(c["category"], []))
            row = {"uuid": m["uuid"], "name": m["name"], "concept": concept, "want": want, "have": have}
            tags = catalog.get(c["category"])
            if want is None:
                row["outcome"] = "unmapped"
            elif tags is None or want not in tags:
                row["outcome"] = "undefined"
            elif want in have:
                row["outcome"] = "covered"
            else:
                row["outcome"] = "drifted"
                others = [t for t in have if t != want]
                # MULTIPLE: membership is the question, so another value conflicts with nothing. SINGLE: another
                # value is a competing current value, held unless a change was allowed.
                if c["cardinality"] == "multiple" or not others:
                    actions.append({"uuid": m["uuid"], "name": m["name"], "category": c["category"],
                                    "attach": tags[want], "detach": [], "want": want, "have": have})
                elif allow_change:
                    actions.append({"uuid": m["uuid"], "name": m["name"], "category": c["category"],
                                    "attach": tags[want], "detach": [tags[t] for t in others if t in tags],
                                    "want": want, "have": have})
                else:
                    row["held"] = True
            rows.append(row)
    return rows, actions


def verdict(rows, reached):
    if any(v != "read" for v in reached.values()) or not rows:
        return "INDETERMINATE"
    return "GREEN" if all(r["outcome"] == "covered" for r in rows) else "RED"


# ─── reading the planes ─────────────────────────────────────────────────────────────────────────


def declarations(reached):
    """([{uuid, name, namespace, labels}], {(namespace, cluster): labels}) from the deployment records."""
    host, org = os.environ.get("VCFA_HOST"), os.environ.get("VCFA_ORG")
    user, pw = os.environ.get("VCFA_USER"), _secret("VCFA_PASSWORD_FILE")
    if not all((host, org, user, pw)):
        reached["automation"] = "not credentialed"
        return [], {}
    cred = base64.b64encode(f"{user}@{org}:{pw}".encode()).decode()
    st, _, hdrs = _req("POST", f"https://{host}/cloudapi/1.0.0/sessions",
                       {"Authorization": f"Basic {cred}", "Accept": "application/json;version=9.1.0"})
    tok = hdrs.get("x-vmware-vcloud-access-token")
    if st != 200 or not tok:
        reached["automation"] = f"session login HTTP {st}"
        return [], {}
    h = {"Authorization": f"Bearer {tok}", "Accept": "application/json"}
    st, raw, _ = _req("GET", f"https://{host}/deployment/api/deployments?size=200", h)
    if st != 200:
        reached["automation"] = f"deployment list HTTP {st}"
        return [], {}
    machines, clusters = [], {}
    for dep in json.loads(raw).get("content", []):
        st2, raw2, _ = _req("GET", f"https://{host}/deployment/api/deployments/{dep['id']}/resources", h)
        if st2 != 200:
            reached["automation"] = f"a deployment's resources HTTP {st2}"
            return [], {}
        for res in json.loads(raw2).get("content", []):
            obj = (res.get("properties") or {}).get("object") or {}
            meta, spec = obj.get("metadata") or {}, obj.get("spec") or {}
            if obj.get("kind") == "Cluster" and meta.get("namespace") and meta.get("name"):
                clusters[(meta["namespace"], meta["name"])] = meta.get("labels") or {}
            elif obj.get("kind") == "VirtualMachine" and spec.get("instanceUUID"):
                machines.append({"uuid": spec["instanceUUID"], "name": meta.get("name", ""),
                                 "namespace": meta.get("namespace", ""), "labels": meta.get("labels") or {}})
    reached["automation"] = "read"
    return machines, clusters


def catalog_for(host, h, categories, reached):
    """{category name: {tag name: tag id}} for the wanted categories that exist; a missing one is simply absent."""
    st, raw, _ = _req("GET", f"https://{host}/api/cis/tagging/category", h)
    if st != 200:
        reached["vcenter"] = f"tagging plane HTTP {st}"
        return {}
    by_name = {}
    for cid in json.loads(raw):
        s, r, _ = _req("GET", f"https://{host}/api/cis/tagging/category/{cid}", h)
        if s == 200 and json.loads(r).get("name") in categories:
            by_name[json.loads(r)["name"]] = cid
    out = {}
    for name, cid in by_name.items():
        s, r, _ = _req("POST", f"https://{host}/api/cis/tagging/tag?action=list-tags-for-category",
                       {**h, "Content-Type": "application/json"}, json.dumps({"category_id": cid}).encode())
        out[name] = {}
        for tid in json.loads(r) if s == 200 else []:
            s2, r2, _ = _req("GET", f"https://{host}/api/cis/tagging/tag/{tid}", h)
            if s2 == 200:
                out[name][json.loads(r2)["name"]] = tid
    reached["vcenter"] = "read"
    return out


def vm_uuid(host, h, moref):
    st, raw, _ = _req("GET", f"https://{host}/api/vcenter/vm/{moref}", h)
    return (json.loads(raw).get("identity") or {}).get("instance_uuid") if st == 200 else None


def attached_tags(host, h, moref, names_by_id):
    """{category: [tag names]} the machine carries in the wanted categories, or None when the read failed."""
    st, raw, _ = _req("POST", f"https://{host}/api/cis/tagging/tag-association?action=list-attached-tags",
                      {**h, "Content-Type": "application/json"},
                      json.dumps({"object_id": {"id": moref, "type": "VirtualMachine"}}).encode())
    if st != 200:
        return None
    out = {}
    for tid in json.loads(raw):
        if tid in names_by_id:
            cat, name = names_by_id[tid]
            out.setdefault(cat, []).append(name)
    return out


def machines_on_vcenter(host, h, declared, clusters, with_nodes, reached):
    """The machines to judge, each with its moref: every declared machine found by UUID, and, from the namespace
    folder tree, every node of a declared cluster carrying that cluster's labels. Plus the population counts."""
    want = {m["uuid"]: m for m in declared}
    st, raw, _ = _req("GET", f"https://{host}/api/vcenter/namespaces/instances", h)
    if st != 200:
        reached["vcenter-namespaces"] = f"HTTP {st}"
        return [], {}
    ns_names = {n["namespace"] for n in json.loads(raw) if n.get("namespace")}
    out, pop = [], {"declaredMachines": len(declared), "declaredFoundOnVcenter": 0, "clusterNodes": 0,
                    "nodesInheriting": 0, "nodesWithNothingToInherit": 0}
    for f in _folders(host, h):
        if f["name"] not in ns_names:
            continue
        for vm in _vms_in(host, h, f["folder"]):
            u = vm_uuid(host, h, vm["vm"])
            if u in want:
                out.append({**want[u], "moref": vm["vm"], "inheritedFrom": ""})
                pop["declaredFoundOnVcenter"] += 1
        if not with_nodes:
            continue
        for kid in _folders(host, h, parent_folders=f["folder"]):
            if kid["name"] == POD_FOLDER:
                continue
            nodes = _vms_in(host, h, kid["folder"])
            pop["clusterNodes"] += len(nodes)
            labels = clusters.get((f["name"], kid["name"]))
            if labels is None:
                pop["nodesWithNothingToInherit"] += len(nodes)
                continue
            for vm in nodes:
                u = vm_uuid(host, h, vm["vm"])
                if u:
                    out.append({"uuid": u, "name": vm["name"], "namespace": f["name"], "labels": labels,
                                "moref": vm["vm"], "inheritedFrom": kid["name"]})
                    pop["nodesInheriting"] += 1
    reached["vcenter-namespaces"] = "read"
    return out, pop


# ─── writing ────────────────────────────────────────────────────────────────────────────────────


def association(host, h, tag_id, moref, action):
    st, _, _ = _req("POST", f"https://{host}/api/cis/tagging/tag-association/{tag_id}?action={action}",
                    {**h, "Content-Type": "application/json"},
                    json.dumps({"object_id": {"id": moref, "type": "VirtualMachine"}}).encode())
    return st


# ─── the run ────────────────────────────────────────────────────────────────────────────────────


def counts(rows, actions, pop, reached, verdict_, written=None, mismatches=None):
    """The record: counts only. No machine, namespace, label, category or tag name enters it."""
    rec = {"captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "reached": reached,
           "verdict": verdict_, "population": pop,
           "machinesDeclaring": len({r["uuid"] for r in rows}),
           "assignments": len(rows), "outcomes": {o: sum(1 for r in rows if r["outcome"] == o) for o in OUTCOMES},
           "held": sum(1 for r in rows if r.get("held")), "writesPlanned": len(actions)}
    if written is not None:
        rec["written"], rec["didNotReadBack"] = written, mismatches
    return rec


def run(mapping_path, apply_, allow_change, with_nodes, record):
    mapping = load_mapping(mapping_path)
    reached = {}
    declared, clusters = declarations(reached)
    host, h = vc_session(reached)
    machines, pop, catalog, attached = [], {}, {}, {}
    if host and reached.get("automation") == "read":
        catalog = catalog_for(host, h, {c["category"] for c in mapping.values()}, reached)
        names_by_id = {tid: (cat, name) for cat, tags in catalog.items() for name, tid in tags.items()}
        machines, pop = machines_on_vcenter(host, h, declared, clusters, with_nodes, reached)
        for m in machines:
            got = attached_tags(host, h, m["moref"], names_by_id)
            if got is None:
                reached["vcenter"] = "a machine's tags could not be read"
                break
            attached[m["uuid"]] = got
    rows, actions = decide(machines, mapping, catalog, attached, allow_change)
    v = verdict(rows, reached)

    print("Planes: " + ", ".join(f"{k} {val}" for k, val in reached.items()))
    if pop:
        print(f"Machines judged: {len(machines)} ({pop.get('declaredFoundOnVcenter', 0)} declaring for themselves, "
              f"{pop.get('nodesInheriting', 0)} cluster nodes inheriting; {pop.get('nodesWithNothingToInherit', 0)} "
              f"nodes whose cluster declares nothing)")
        declaring = len({r["uuid"] for r in rows})
        print(f"  {declaring} of {len(machines)} declare at least one mapped concept (declaration coverage; the outcomes "
              f"below are projection coverage)")
        missing = pop.get("declaredMachines", 0) - pop.get("declaredFoundOnVcenter", 0)
        if missing:
            print(f"  {missing} declared machine(s) not found on this vCenter: a deployment record outliving its machine, "
                  f"or a machine on another vCenter; not judged")
    for o in OUTCOMES:
        print(f"  {sum(1 for r in rows if r['outcome'] == o):5d}  {o}")
    for r in rows:
        if r["outcome"] != "covered":
            note = "  (held: another value is set; --allow-change to replace it)" if r.get("held") else ""
            print(f"    {r['outcome']:<9} {r['name']}  {r['concept']}: want {r['want']!r}, has {r['have']}{note}")
    print(f"VERDICT: {v}; {len(actions)} write(s) {'to send' if apply_ else 'planned'}")

    written, mismatches = None, None
    rc = {"GREEN": 0, "RED": 1, "INDETERMINATE": 3}[v]
    if apply_ and actions and v != "INDETERMINATE":
        written, mismatches = 0, 0
        for a in actions:
            m = next(x for x in machines if x["uuid"] == a["uuid"])
            for old in a["detach"]:
                association(host, h, old, m["moref"], "detach")
            if association(host, h, a["attach"], m["moref"], "attach") in (200, 204):
                written += 1
            names_by_id = {tid: (cat, name) for cat, tags in catalog.items() for name, tid in tags.items()}
            back = attached_tags(host, h, m["moref"], names_by_id) or {}
            if a["want"] not in back.get(a["category"], []):
                mismatches += 1
                print(f"    DID NOT LAND: {a['name']}  {a['category']} = {a['want']}")
        print(f"APPLIED: {written} of {len(actions)} attached; {mismatches} did not read back")
        rc = 4 if mismatches else rc
    if record:
        rec = counts(rows, actions, pop, reached, v, written, mismatches)
        Path(record).write_text(json.dumps(rec, indent=1) + "\n", encoding="utf-8")
        print(f"wrote {record}: counts only, no machine, label, category or tag name")
    return rc


def self_test():
    fx = HERE / "fixtures" / "projection"
    def load(name):
        return json.loads((fx / name).read_text(encoding="utf-8"))

    mapping = load_mapping(fx / "mapping.json")
    machines, catalog, attached, want = load("machines.json"), load("catalog.json"), load("attached.json"), load("expected.json")
    rows, actions = decide(machines, mapping, catalog, attached)
    got = {"outcomes": {o: sum(1 for r in rows if r["outcome"] == o) for o in OUTCOMES},
           "held": sum(1 for r in rows if r.get("held")), "writes": len(actions)}
    _, changed = decide(machines, mapping, catalog, attached, allow_change=True)
    got["writesWithChange"] = len(changed)
    got["verdictEmpty"] = verdict([], {"automation": "read", "vcenter": "read"})
    if got == want:
        print(f"self-test OK: {got['outcomes']} with {got['held']} held and {got['writes']} write(s), "
              f"{got['writesWithChange']} with --allow-change, and an empty run reads {got['verdictEmpty']}, offline")
        return 0
    print(f"self-test FAILED: got {got}, expected {want}")
    return 1


def main(argv):
    if argv == ["--self-test"]:
        return self_test()
    args = {"mapping": None, "apply": False, "allow_change": False, "nodes": True, "record": None}
    it = iter(argv)
    for a in it:
        if a in ("--mapping", "--record"):
            val = next(it, None)
            if not val:
                print(f"project.py: {a} needs a value", file=sys.stderr)
                return 2
            args[a[2:]] = val
        elif a == "--apply":
            args["apply"] = True
        elif a == "--allow-change":
            args["allow_change"] = True
        elif a == "--no-cluster-nodes":
            args["nodes"] = False
        else:
            print(f"project.py: unknown argument {a}", file=sys.stderr)
            return 2
    if not args["mapping"] or (args["allow_change"] and not args["apply"]):
        print(__doc__.split("Usage:")[1].split("Exit:")[0].strip(), file=sys.stderr)
        return 2
    try:
        return run(args["mapping"], args["apply"], args["allow_change"], args["nodes"], args["record"])
    except (PermissionError, FileNotFoundError, ValueError, json.JSONDecodeError) as e:
        print(f"project.py: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
