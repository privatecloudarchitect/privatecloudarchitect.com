#!/usr/bin/env python3
"""identifiers.py: every plane that holds an identifier for a workload, and which of them can see each other.

A workload on VCF 9.1 can be labelled in at least five places, and the word used for the label is the same
word in several of them:

  VSPHERE TAG        a (category, value) pair in vCenter's tagging service. What most people mean by "tag".
  CUSTOM ATTRIBUTE   an older per-object key/value on the same vCenter objects. A different store.
  K8S LABEL          a key/value on the Supervisor's VirtualMachine object. Selectable by Kubernetes.
  K8S ANNOTATION     a key/value on the same object that is NOT selectable, and is where controllers write.
  NSX TAG            a (scope, tag) pair in NSX's own inventory. Scope is the key, tag is the value.

Two consumers turn those identifiers into membership, and each can only see some of them:

  NSX GROUP          matches on NSX tags, via a Condition with member_type VirtualMachine and key Tag.
  OPS CUSTOM GROUP   matches on tags VCF Operations collected from vCenter, via resourceTagConditionRules.

The question this script answers is not "what tags exist". It is **which plane can see which**, because a
group is a query and a query the plane cannot answer returns zero without erroring. It reports:

  1. the PLANES it could reach at all, and with which credential, because reading five planes takes three;
  2. the INVENTORY each plane holds: how many identifiers are DEFINED, and how many objects carry one,
     which are different numbers and usually by a wide margin;
  3. the CONSUMERS: every group whose membership is defined by a tag, and whether it resolves to anything;
  4. with --probe-propagation, the END-TO-END question: attach a vSphere tag to machines you name, then ask
     NSX to group on that value, with a positive control so a zero means something.

Without --probe-propagation nothing here writes. The probe creates one vSphere tag category, one tag inside
it, and one NSX group; it attaches that tag to machines it did NOT create, which is metadata only, and it
detaches and deletes everything in a teardown that always runs and reads the estate back to prove it.

It will not choose the machines for you. Name them in IDENT_PROBE_VMS or the probe refuses to run: a script
that picks its own subjects on somebody's estate is not a probe, it is a surprise.

Run:
  export VC_HOST=<vcenter-fqdn> VC_USER=<user> VC_PASSWORD_FILE=/path/to/pw    # mode 0600
  export NSX_HOST=<nsx-fqdn>    NSX_USER=<user> NSX_PASSWORD_FILE=/path/to/pw  # optional
  export OPS_HOST=<ops-fqdn>    OPS_TOKEN_FILE=/path/to/token                  # optional
  export IDENT_PROBE_VMS="name-a,name-b"        # required for --probe-propagation
  export TLS_VERIFY=false                       # only on a self-signed lab CA
  python3 identifiers.py [--probe-propagation]
  python3 identifiers.py --where <machine-name>   # the thirty-second question, two calls
"""
import base64
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
PREFIX = "handbook-ident"


def ctx():
    c = ssl.create_default_context()
    if os.environ.get("TLS_VERIFY", "true").lower() in ("false", "0", "no"):
        c.check_hostname = False
        c.verify_mode = ssl.CERT_NONE
    return c


def secret(var):
    """Read a secret from a FILE named by an env var. Never from the env var itself."""
    p = os.environ.get(var)
    if not p or not os.path.exists(p):
        return None
    return open(p, encoding="utf-8").read().strip()


class Labels:
    """Estate names become placeholders. The product's own vocabulary never does.

    RESERVED is the platform's words, not ours: scrubbing them would make the record unreadable, and the
    whole point of the record is that a reader can see the product's actual vocabulary.
    """

    RESERVED = {"VirtualMachine", "Tag", "Condition", "EQUALS", "CONTAINS", "EQ", "STARTS_WITH", "EXISTS",
                "SegmentPort", "Segment", "TransportNode", "IPAddress", "VMWARE", "default", "GLOBAL",
                "MULTIPLE", "SINGLE", "HostSystem", "ClusterComputeResource", "Datastore", "Network"}

    def __init__(self):
        self.maps = {}

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
        known = [(real, label) for m in self.maps.values() for real, label in m.items()]
        for real, label in sorted(known, key=lambda kv: -len(kv[0])):
            text = re.sub(r"(?<![A-Za-z0-9-])" + re.escape(real) + r"(?![A-Za-z0-9-])", "{{%s}}" % label, text)
        return UUID.sub("{{id}}", text)


def call(url, headers=None, method="GET", payload=None, timeout=120):
    data = json.dumps(payload).encode() if payload is not None else None
    h = dict(headers or {})
    if data:
        h.setdefault("Content-Type", "application/json")
    h.setdefault("Accept", "application/json")
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, context=ctx(), timeout=timeout) as r:
            body = r.read()
            try:
                return r.status, json.loads(body or b"null")
            except ValueError:
                return r.status, body.decode("utf-8", "replace")[:400]
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw.decode("utf-8", "replace")[:400]
    except (urllib.error.URLError, OSError) as e:
        return None, {"transport": str(e)[:160]}


# ───────────────────────────────────────────────────────────── the planes


class VCenter:
    """vCenter's tagging service. Session auth: the token goes in vmware-api-session-id, not Authorization."""

    def __init__(self, host, user, password):
        self.host, self.ok = host, False
        basic = base64.b64encode(f"{user}:{password}".encode()).decode()
        st, tok = call(f"https://{host}/api/session", {"Authorization": f"Basic {basic}"}, "POST")
        self.h = {"vmware-api-session-id": tok} if st in (200, 201) and isinstance(tok, str) else {}
        self.ok = bool(self.h)

    def u(self, p):
        return f"https://{self.host}{p}"

    @classmethod
    def from_headers(cls, host, headers):
        """Build from an already-minted header. How the credential was obtained is not this class's business,
        which is what lets the same code run from an env-var password file or from a credential broker."""
        o = cls.__new__(cls)
        o.host, o.h = host, dict(headers)
        o.ok = True
        return o

    def categories(self):
        st, ids = call(self.u("/api/cis/tagging/category"), self.h)
        out = []
        for cid in (ids or []) if st == 200 else []:
            s, d = call(self.u(f"/api/cis/tagging/category/{cid}"), self.h)
            if s == 200:
                out.append({"id": cid, "name": d.get("name"), "cardinality": d.get("cardinality"),
                            "associableTypes": d.get("associable_types") or []})
        return out

    def tags(self):
        st, ids = call(self.u("/api/cis/tagging/tag"), self.h)
        out = {}
        for tid in (ids or []) if st == 200 else []:
            s, d = call(self.u(f"/api/cis/tagging/tag/{tid}"), self.h)
            if s == 200:
                out[tid] = {"name": d.get("name"), "categoryId": d.get("category_id")}
        return out

    def vms(self):
        st, v = call(self.u("/api/vcenter/vm"), self.h)
        return v if st == 200 else []

    def attached(self, morefs):
        """One batch call. Asking per-VM is the same answer and N times the load."""
        body = {"object_ids": [{"id": m, "type": "VirtualMachine"} for m in morefs]}
        st, r = call(self.u("/api/cis/tagging/tag-association?action=list-attached-tags-on-objects"),
                     self.h, "POST", body)
        return {x["object_id"]["id"]: x.get("tag_ids", []) for x in r} if st == 200 else {}

    def custom_attribute_surface(self):
        """A scoped probe, not an exhaustive one. Four documented-looking REST paths, and what they answer."""
        out = []
        for p in ("/api/vcenter/custom-attributes", "/api/vcenter/custom-attribute",
                  "/rest/vcenter/custom-attributes", "/api/vcenter/vm/custom-attributes"):
            st, _ = call(self.u(p), self.h)
            out.append({"path": p, "status": st})
        return out


class Nsx:
    def __init__(self, host, user, password):
        self.host = host
        self.h = {"Authorization": "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()}
        st, _ = call(self.u("/policy/api/v1/infra/domains/default/groups?page_size=1"), self.h)
        self.ok = st == 200

    def u(self, p):
        return f"https://{self.host}{p}"

    @classmethod
    def from_headers(cls, host, headers):
        """Build from an already-minted header. How the credential was obtained is not this class's business,
        which is what lets the same code run from an env-var password file or from a credential broker."""
        o = cls.__new__(cls)
        o.host, o.h = host, dict(headers)
        o.ok = True
        return o

    def groups(self):
        st, r = call(self.u("/policy/api/v1/infra/domains/default/groups?page_size=1000"), self.h)
        return (r or {}).get("results", []) if st == 200 else []

    def fabric_vms(self):
        st, r = call(self.u("/api/v1/fabric/virtual-machines?page_size=1000"), self.h)
        return (r or {}).get("results", []) if st == 200 else []

    def members(self, gid):
        st, r = call(self.u(f"/policy/api/v1/infra/domains/default/groups/{gid}/members/virtual-machines"), self.h)
        return (r or {}).get("results", []) if st == 200 else None


class Ops:
    def __init__(self, host, token):
        self.host = host
        self.h = {"Authorization": f"OpsToken {token}"}
        st, _ = call(self.u("/suite-api/api/resources/groups?pageSize=1"), self.h)
        self.ok = st == 200

    def u(self, p):
        return f"https://{self.host}{p}"

    @classmethod
    def from_headers(cls, host, headers):
        """Build from an already-minted header. How the credential was obtained is not this class's business,
        which is what lets the same code run from an env-var password file or from a credential broker."""
        o = cls.__new__(cls)
        o.host, o.h = host, dict(headers)
        o.ok = True
        return o

    def groups(self):
        st, r = call(self.u("/suite-api/api/resources/groups"), self.h)
        return (r or {}).get("groups", []) if st == 200 else []

    def members(self, gid):
        st, r = call(self.u(f"/suite-api/api/resources/groups/{gid}/members"), self.h)
        return len((r or {}).get("resourceList", [])) if st == 200 else None

    def tagmanagement_surface(self):
        """The centralized definition plane, and the header it refuses to answer without."""
        out = []
        for p in ("/internal/tagmanagement/categories", "/suite-api/internal/tagmanagement/categories"):
            for hdr, lbl in ((dict(self.h, **{"X-Ops-API-use-unsupported": "true"}), "with"),
                             (self.h, "without")):
                st, body = call(self.u(p), hdr)
                n = None
                if st == 200 and isinstance(body, dict):
                    n = (body.get("pageInfo") or {}).get("totalCount")
                out.append({"path": p, "unsupportedHeader": lbl, "status": st, "categories": n})
        return out


# ─────────────────────────────────────────────── the thirty-second question


def where_is_the_tag(vc, nsx, machine):
    """Which plane is this machine's tag actually on? Both lists, side by side, in one call each.

    This is the whole diagnosis for an empty NSX group. A group criterion of member type VirtualMachine
    and key Tag reads NSX's OWN inventory; a vSphere tag lives in vCenter's tagging service. They are
    different stores, so a tag can be plainly visible in the vSphere client and absent from the list the
    group is matching against. Printing both is faster than reasoning about either.
    """
    moref = next((v["vm"] for v in vc.vms() if v["name"] == machine), None)
    if not moref:
        return {"machine": machine, "found": False}
    tags, cats = vc.tags(), {c["id"]: c["name"] for c in vc.categories()}
    vsphere = sorted(f"{cats.get(tags[t]['categoryId'], '?')}={tags[t]['name']}"
                     for t in vc.attached([moref]).get(moref, []) if t in tags)
    seen = next((v for v in nsx.fabric_vms() if v.get("display_name") == machine), None)
    return {"machine": machine, "found": True, "inNsxInventory": seen is not None,
            "vSphereTags": vsphere,
            "nsxTags": sorted(f"{t.get('scope') or '(no scope)'}={t.get('tag')}"
                              for t in (seen.get("tags") or [])) if seen else None}


# ───────────────────────────────────────────────────────── what each plane holds


def vsphere_inventory(vc, L):
    """DEFINED versus CARRIED. They are different numbers and the gap is the finding."""
    cats = vc.categories()
    tags = vc.tags()
    catname = {c["id"]: c["name"] for c in cats}
    vms = vc.vms()
    att = vc.attached([v["vm"] for v in vms])
    carried = {m: ids for m, ids in att.items() if ids}
    byname = {v["vm"]: v["name"] for v in vms}
    # a tag NAME is not unique; only (category, name) is. Count both so the page can say so.
    pairs = {f"{catname.get(t['categoryId'], '?')}={t['name']}" for t in tags.values()}
    dupes = len(tags) - len({t["name"] for t in tags.values()})
    return {
        "categoriesDefined": len(cats),
        "tagsDefined": len(tags),
        "distinctCategoryValuePairs": len(pairs),
        "tagNamesReusedAcrossCategories": dupes,
        "vms": len(vms),
        "vmsCarryingAtLeastOneTag": len(carried),
        "categories": [{"name": c["name"], "cardinality": c["cardinality"],
                        "associableTypes": len(c["associableTypes"]) or "any"} for c in cats],
        # CATEGORY names only. A tag VALUE is estate data and can embed a machine name: on the estate
        # this was written against, a first-party controller writes data-service-name=<the machine>, and
        # the scrubber cannot catch it because the value holds a SHORTENED form of the registered name.
        # The teaching is which categories a controller wrote, not what it wrote in them.
        "carriers": [{"vm": L.get("machine", byname.get(m, m)),
                      "categories": sorted({catname.get(tags[t]["categoryId"], "?")
                                            for t in ids if t in tags})}
                     for m, ids in list(carried.items())[:12]],
        "customAttributeRestProbe": vc.custom_attribute_surface(),
    }


def nsx_inventory(nsx, L):
    gs = nsx.groups()
    kinds, condkeys, vmtag = {}, {}, []
    for g in gs:
        for e in (g.get("expression") or []):
            rt = e.get("resource_type")
            kinds[rt] = kinds.get(rt, 0) + 1
            if rt == "Condition":
                k = f"{e.get('member_type')}.{e.get('key')}"
                condkeys[k] = condkeys.get(k, 0) + 1
                if e.get("member_type") == "VirtualMachine" and e.get("key") == "Tag":
                    vmtag.append({"group": g.get("display_name"), "id": g.get("id"),
                                  "operator": e.get("operator"), "value": e.get("value")})
    vms = nsx.fabric_vms()
    scopes = {}
    for v in vms:
        for t in (v.get("tags") or []):
            s = t.get("scope") or "(empty scope)"
            scopes[s] = scopes.get(s, 0) + 1
    # resolve every VM-tag group, so a zero elsewhere has a control beside it
    for row in vmtag:
        m = nsx.members(row["id"])
        row["members"] = len(m) if isinstance(m, list) else None
        row["group"] = L.get("nsxgroup", row["group"]) if row["members"] in (None, 0) else row["group"]
        row.pop("id", None)
    return {
        "groups": len(gs),
        "expressionKinds": kinds,
        "conditionKeys": condkeys,
        "groupsMatchingVmTag": vmtag,
        "fabricVms": len(vms),
        "fabricVmsTagged": sum(1 for v in vms if v.get("tags")),
        "tagScopes": {(k if k.startswith("dis:") or k == "(empty scope)" else L.get("scope", k)): n
                      for k, n in scopes.items()},
        "discoveredTagsPresent": sum(1 for v in vms for t in (v.get("tags") or [])
                                     if str(t.get("scope", "")).startswith("dis:")),
    }


def ops_inventory(ops, L):
    gs = ops.groups()
    tag_defined, kinds = [], {}
    for g in gs:
        md = g.get("membershipDefinition") or {}
        conds = []
        for rr in (md.get("rules") or []):
            for key, val in rr.items():
                if isinstance(val, list) and val:
                    kinds[key] = kinds.get(key, 0) + len(val)
            for c in (rr.get("resourceTagConditionRules") or []):
                conds.append({"category": c.get("category"), "op": c.get("compareOperator"),
                              "value": c.get("stringValue")})
        if conds:
            tag_defined.append({"group": L.get("opsgroup", g.get("resourceKey", {}).get("name")),
                                "conditions": conds, "members": ops.members(g.get("id"))})
    return {
        "customGroups": len(gs),
        "populatedRuleKinds": kinds,
        "groupsDefinedByTag": len(tag_defined),
        "groupsDefinedByTagResolvingToZero": sum(1 for t in tag_defined if t["members"] == 0),
        "tagGroups": tag_defined,
        "tagManagementSurface": ops.tagmanagement_surface(),
    }


# ───────────────────────────────────────────────── the end-to-end propagation probe


def propagation_probe(vc, nsx, names, L):
    """Attach a vSphere tag to machines the operator NAMED, then ask NSX to group on that value.

    The positive control is whichever NSX group already matches an NSX-native tag and resolves. Without one,
    a zero from the probe is evidence of nothing: it could equally mean the members endpoint is wrong, or
    that membership evaluation is broken on this estate, or that the value is simply absent everywhere.
    """
    cat_name, tag_name = f"{PREFIX}-cat", f"{PREFIX}-value"
    gid = f"{PREFIX}-probe"
    state = {"category": None, "tag": None, "attached": [], "group": False}
    out = {"subjects": [], "positiveControl": None, "nsxInventoryAfterAttach": [],
           "groupMembersOverTime": [], "teardown": {}}

    control = None
    for row in nsx_inventory(nsx, L)["groupsMatchingVmTag"]:
        if row.get("members"):
            control = row
            break
    out["positiveControl"] = control
    if not control:
        raise SystemExit(
            "\nSTOPPING: no NSX group matching an NSX-native tag currently resolves to any member, so this "
            "estate offers no positive control. A zero from the probe would be unreadable. Create or find a "
            "working NSX-tag group first, or run without --probe-propagation.")

    try:
        st, cid = call(vc.u("/api/cis/tagging/category"), vc.h, "POST", {
            "name": cat_name, "description": "temporary; handbook identifier-planes probe",
            "cardinality": "MULTIPLE", "associable_types": []})
        out["createCategory"] = st
        state["category"] = cid if st in (200, 201) else None
        if state["category"]:
            st, tid = call(vc.u("/api/cis/tagging/tag"), vc.h, "POST", {
                "name": tag_name, "description": "temporary; handbook probe", "category_id": state["category"]})
            out["createTag"] = st
            state["tag"] = tid if st in (200, 201) else None
        if not state["tag"]:
            raise SystemExit(
                "\nSTOPPING: the vSphere tag was not created, so nothing after this would be a test. A zero "
                "from NSX against a value that exists nowhere is a tautology, not a finding.")

        vms = {v["name"]: v["vm"] for v in vc.vms()}
        for n in names:
            moref = vms.get(n)
            if not moref:
                out["subjects"].append({"vm": L.get("machine", n), "found": False})
                continue
            st, _ = call(vc.u(f"/api/cis/tagging/tag-association/{state['tag']}?action=attach"),
                         vc.h, "POST", {"object_id": {"id": moref, "type": "VirtualMachine"}})
            if st in (200, 204):
                state["attached"].append(moref)
            s2, ids = call(vc.u("/api/cis/tagging/tag-association?action=list-attached-tags"),
                           vc.h, "POST", {"object_id": {"id": moref, "type": "VirtualMachine"}})
            out["subjects"].append({"vm": L.get("machine", n), "found": True, "attach": st,
                                    "readBackFromVCenter": state["tag"] in (ids or [])})

        # does the vSphere tag show up in NSX's OWN inventory? this is the mechanism question
        byname = {v.get("display_name"): v for v in nsx.fabric_vms()}
        for n in names:
            v = byname.get(n)
            out["nsxInventoryAfterAttach"].append({
                "vm": L.get("machine", n),
                "inNsxInventory": bool(v),
                "nsxTags": [(t.get("scope"), t.get("tag")) for t in (v.get("tags") or [])] if v else None})

        st, _ = call(nsx.u(f"/policy/api/v1/infra/domains/default/groups/{gid}"), nsx.h, "PATCH", {
            "display_name": gid, "description": "temporary; handbook probe",
            "expression": [{"resource_type": "Condition", "member_type": "VirtualMachine",
                            "key": "Tag", "operator": "EQUALS", "value": tag_name}]})
        state["group"] = st is not None and st < 400
        out["createGroup"] = st
        elapsed = 0
        for wait in (10, 20, 30, 60):
            time.sleep(wait)
            elapsed += wait
            m = nsx.members(gid)
            out["groupMembersOverTime"].append({"afterSeconds": elapsed,
                                                "members": len(m) if isinstance(m, list) else None})
            if isinstance(m, list) and m:
                break
    finally:
        td = out["teardown"]
        if state["group"]:
            call(nsx.u(f"/policy/api/v1/infra/domains/default/groups/{gid}"), nsx.h, "DELETE")
            # An immediate 404 after a policy DELETE is NOT proof the object is gone. A group deleted this
            # way once answered 404 on the next call and was present again later, carrying its original
            # expression plus a scope_operator the platform had added. So read it back twice, with a gap,
            # and report the delayed answer as the one that counts.
            st_now, _ = call(nsx.u(f"/policy/api/v1/infra/domains/default/groups/{gid}"), nsx.h)
            time.sleep(30)
            st_later, _ = call(nsx.u(f"/policy/api/v1/infra/domains/default/groups/{gid}"), nsx.h)
            td["nsxGroupGoneImmediately"] = st_now == 404
            td["nsxGroupGoneAfter30s"] = st_later == 404
            td["nsxGroupGone"] = st_later == 404
        for moref in state["attached"]:
            call(vc.u(f"/api/cis/tagging/tag-association/{state['tag']}?action=detach"),
                 vc.h, "POST", {"object_id": {"id": moref, "type": "VirtualMachine"}})
        still = []
        for moref in state["attached"]:
            _s, ids = call(vc.u("/api/cis/tagging/tag-association?action=list-attached-tags"),
                           vc.h, "POST", {"object_id": {"id": moref, "type": "VirtualMachine"}})
            if state["tag"] in (ids or []):
                still.append(moref)
        td["stillAttachedAfterDetach"] = len(still)
        if state["tag"]:
            td["deleteTag"], _ = call(vc.u(f"/api/cis/tagging/tag/{state['tag']}"), vc.h, "DELETE")
        if state["category"]:
            td["deleteCategory"], _ = call(vc.u(f"/api/cis/tagging/category/{state['category']}"),
                                           vc.h, "DELETE")
        td["categoryResidue"] = any(c["name"] == cat_name for c in vc.categories())
        if td.get("categoryResidue") or still or (state["group"] and not td.get("nsxGroupGone")):
            raise SystemExit(
                f"\nSTOPPING: this run did not finish its own teardown. category-residue="
                f"{td.get('categoryResidue')} still-attached={len(still)} "
                f"nsx-group-gone={td.get('nsxGroupGone')}. Clear it before publishing "
                f"anything from this record; a probe that leaves marks on an estate is not read-only in "
                f"any sense the operator cares about.")
    return out


# ──────────────────────────────────────────────────────────────────── main


def main():
    probe = "--probe-propagation" in sys.argv
    where = next((a for i, a in enumerate(sys.argv) if i and sys.argv[i - 1] == "--where"), None)
    out_dir = os.path.dirname(os.path.abspath(__file__))
    L = Labels()

    vc = nsx = ops = None
    planes = []
    if os.environ.get("VC_HOST") and os.environ.get("VC_USER") and secret("VC_PASSWORD_FILE"):
        vc = VCenter(os.environ["VC_HOST"], os.environ["VC_USER"], secret("VC_PASSWORD_FILE"))
        planes.append({"plane": "vCenter tagging service", "credential": "vCenter session (Basic to /api/session)",
                       "reached": vc.ok})
    if os.environ.get("NSX_HOST") and os.environ.get("NSX_USER") and secret("NSX_PASSWORD_FILE"):
        nsx = Nsx(os.environ["NSX_HOST"], os.environ["NSX_USER"], secret("NSX_PASSWORD_FILE"))
        planes.append({"plane": "NSX inventory + groups", "credential": "NSX local credential (Basic)",
                       "reached": nsx.ok})
    if os.environ.get("OPS_HOST") and secret("OPS_TOKEN_FILE"):
        ops = Ops(os.environ["OPS_HOST"], secret("OPS_TOKEN_FILE"))
        planes.append({"plane": "VCF Operations groups + tag management", "credential": "Ops API token",
                       "reached": ops.ok})

    print("planes reachable:")
    for p in planes:
        print(f"  {p['plane']:42s} {'yes' if p['reached'] else 'NO':4s}  ({p['credential']})")
    if not any(p["reached"] for p in planes):
        raise SystemExit("no plane answered; set at least VC_HOST / VC_USER / VC_PASSWORD_FILE")

    if where:
        if not (vc and vc.ok and nsx and nsx.ok):
            raise SystemExit("--where needs BOTH vCenter and NSX reachable: it is a comparison between them.")
        answer = where_is_the_tag(vc, nsx, where)
        print(json.dumps(answer, indent=1))
        if answer.get("found") and answer["vSphereTags"] and not answer["nsxTags"]:
            print("\nThis machine carries vSphere tags and no NSX tag. An NSX group matching on VM Tag "
                  "reads the second list, so it will not match this machine whatever the first one says.")
        return

    payload = {"captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "planes": planes, "vsphere": None, "nsx": None, "ops": None, "propagation": None}

    if vc and vc.ok:
        payload["vsphere"] = vsphere_inventory(vc, L)
        v = payload["vsphere"]
        print(f"\nvSphere: {v['tagsDefined']} tag(s) defined in {v['categoriesDefined']} categories; "
              f"{v['vmsCarryingAtLeastOneTag']} of {v['vms']} VMs carry one")
    if nsx and nsx.ok:
        payload["nsx"] = nsx_inventory(nsx, L)
        n = payload["nsx"]
        print(f"NSX: {n['groups']} group(s); {len(n['groupsMatchingVmTag'])} match a VM tag; "
              f"{n['fabricVmsTagged']} of {n['fabricVms']} fabric VMs tagged; "
              f"{n['discoveredTagsPresent']} discovered (dis:*) tag(s)")
    if ops and ops.ok:
        payload["ops"] = ops_inventory(ops, L)
        o = payload["ops"]
        print(f"Ops: {o['customGroups']} custom group(s); {o['groupsDefinedByTag']} defined by tag, of which "
              f"{o['groupsDefinedByTagResolvingToZero']} resolve to zero members")

    if probe:
        names = [n.strip() for n in (os.environ.get("IDENT_PROBE_VMS") or "").split(",") if n.strip()]
        if not names:
            raise SystemExit(
                "\n--probe-propagation needs IDENT_PROBE_VMS set to the machines you are willing to have a "
                "temporary tag attached to and detached from. It will not choose them for you.")
        if not (vc and vc.ok and nsx and nsx.ok):
            raise SystemExit("\n--probe-propagation needs BOTH vCenter and NSX reachable; it is a question "
                             "about the relationship between them.")
        payload["propagation"] = propagation_probe(vc, nsx, names, L)
        pr = payload["propagation"]
        last = (pr["groupMembersOverTime"] or [{}])[-1]
        print(f"\npropagation: control group resolved {pr['positiveControl'].get('members')} member(s); "
              f"the probe group resolved {last.get('members')} after {last.get('afterSeconds')}s")

    # An optional section that did not run must not erase one that did (G-166, generically).
    prior_path = os.path.join(out_dir, "identifiers.json")
    if os.path.exists(prior_path):
        try:
            prior = json.load(open(prior_path, encoding="utf-8")) or {}
        except ValueError:
            prior = {}
        for k, v in list(payload.items()):
            if v is None and prior.get(k) is not None:
                payload[k] = prior[k]
                print(f"  carrying forward {k!r} from an earlier run; this run did not re-read it and has "
                      f"not erased it")

    text = L.scrub(UUID.sub("{{id}}", json.dumps(payload, indent=1, ensure_ascii=False)))
    for s in (os.environ.get("VC_HOST"), os.environ.get("NSX_HOST"), os.environ.get("OPS_HOST"),
              os.environ.get("VC_USER"), os.environ.get("NSX_USER"),
              secret("VC_PASSWORD_FILE"), secret("NSX_PASSWORD_FILE"), secret("OPS_TOKEN_FILE"),
              getattr(vc, "h", {}).get("vmware-api-session-id")):
        assert not s or s not in text, "an estate value or credential reached the record"
    bare = re.sub(r"\{\{[^}]*\}\}", "", text)
    for fam, m in L.maps.items():
        for nm in m:
            if not nm:
                continue
            if re.search(r"(?<![A-Za-z0-9-])" + re.escape(nm) + r"(?![A-Za-z0-9-])", bare):
                shape = re.sub(r"[A-Za-z]", "a", re.sub(r"[0-9]", "9", nm))
                raise SystemExit(f"FATAL: a {fam} name ({len(nm)} characters, shape {shape}) reached the record")
            # A generated suffix makes the full name unique; the STEM is what a controller embeds in a tag
            # value, and matching only the full name lets the stem through. Check every stem of 8 or more
            # characters, split on the separators a generated suffix is attached with.
            for stem in {nm.rsplit(sep, 1)[0] for sep in ("-", ".", "_") if sep in nm}:
                if len(stem) >= 8 and re.search(r"(?<![A-Za-z0-9])" + re.escape(stem) + r"(?![A-Za-z0-9])", bare):
                    raise SystemExit(
                        f"FATAL: the stem of a {fam} name ({len(stem)} characters) reached the record. A tag "
                        f"value or a description is embedding it; scrub that field or stop publishing it.")
    # the product's own vocabulary must SURVIVE the scrub, or the record teaches nothing
    for word in ("VirtualMachine", "Condition", "resourceTagConditionRules"):
        if word in json.dumps(payload) and word not in text:
            raise SystemExit(f"FATAL: the scrubber ate the product's own word {word!r}")

    open(prior_path, "w", encoding="utf-8").write(text + "\n")
    print(f"\nwrote identifiers.json; every estate name replaced by a placeholder"
          f"{', propagation probe included' if payload.get('propagation') else ''}")


if __name__ == "__main__":
    main()
