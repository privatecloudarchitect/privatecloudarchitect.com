#!/usr/bin/env python3
"""content.py: does the metadata a workload declares reach the plane its consumers read?

A workload on an All Apps organization declares itself in Kubernetes labels, because the template
has no field for a tag. Every consumer that governs on metadata reads tags. This asks whether the
first reaches the second, on your estate, and writes a record the chapter renders.

Five questions, each on a plane that can be credentialed separately, so the script runs with
whatever you have and records which planes it could reach:

  1. the GRAMMAR SPLIT (Automation): per organization, how many templates declare resource `tags:`
     and how many declare Kubernetes `labels:`. A classic organization stamps the machine from the
     template; a non-classic one has no tag construct at all, and the difference is the whole
     reason the rest of this record exists;
  2. the DECLARATION (Automation): what each provisioned machine's manifest actually declares, and
     the instance UUID to find it by. Not the name: two machines in different namespaces may share
     one, and a name join then reads one machine's tags and writes the other's metadata onto it;
  3. the PROJECTION (vCenter): what tags those same machines carry, joined on that UUID. The
     categories your taxonomy owns only, because the tagging API is a per-tag GET and resolving an
     estate's whole catalog to answer about four categories is thousands of wasted calls;
  4. the CONSUMER SURFACE (Operations): which properties an Operations VM object exposes, and
     whether any of them carries a Kubernetes label. This is the question that decides whether the
     projection is necessary or merely traditional;
  5. the DECAY SPLIT (Operations): objects still collecting against objects retained after
     deletion, each with whether it carries metadata. Operations keeps deleted resources and they
     keep their last properties, so a coverage number that does not separate the two reports an
     estate healthier than it is.

Three ways this answers wrongly, each of which it did first:

  * joining declaration to machine by NAME. Two live machines here share one name in different
    namespaces, and the join silently picks one;
  * counting a retained Operations object as evidence of coverage. The tagged objects on the
    reference estate were every one of them deleted machines;
  * reading a template's `${input.environment}` as a literal value. It is a placeholder whose value
    is chosen at deploy time, so the thing to check is the input's declared enum, not the string.

Read-only throughout. Nothing here creates, attaches or deletes a tag.

Every estate value is replaced with a stable placeholder before the record is written, and the
script refuses to write a record in which one survived.

Run:
  export VCFA_HOST=<automation-fqdn>          # question 1 and 2
  export VCFA_ORG=<organization>
  export VCFA_USER=<username>                 # the bare account, not the UPN
  export VCFA_PASSWORD_FILE=/path/to/pw       # mode 0600
  export VC_HOST=<vcenter-fqdn>               # question 3
  export VC_USER=<username@domain>
  export VC_PASSWORD_FILE=/path/to/pw
  export OPS_HOST=<operations-fqdn>           # question 4 and 5
  export OPS_TOKEN_FILE=/path/to/bearer          # the exchanged bearer, not the api token
  export TLS_VERIFY=false                     # only on a self-signed lab CA
  python3 content.py
"""

from __future__ import annotations

import base64
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "content.json"

CLOUDAPI = "application/json;version=9.1.0"
# The concepts this record is about. A category outside the set is somebody else's and is counted,
# never named, so the record carries no third-party vocabulary.
OWNED_PREFIXES = ("identity.", "lifecycle.", "policy.", "topology.", "capacity.", "admin.")
ENGINE_LABELS = {
    "function": "app.kubernetes.io/component",
    "app": "app.kubernetes.io/part-of",
    "env": "environment",
}


def _ctx():
    if os.environ.get("TLS_VERIFY", "true").lower() in ("false", "0", "no"):
        c = ssl.create_default_context()
        c.check_hostname = False
        c.verify_mode = ssl.CERT_NONE
        return c
    return ssl.create_default_context()


def _req(method, url, headers=None, body=None):
    r = urllib.request.Request(url, method=method, data=body)
    for k, v in (headers or {}).items():
        r.add_header(k, v)
    try:
        with urllib.request.urlopen(r, context=_ctx(), timeout=90) as resp:
            return (
                resp.status,
                resp.read().decode(),
                {k.lower(): v for k, v in resp.headers.items()},
            )
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), {k.lower(): v for k, v in e.headers.items()}
    except Exception as e:  # unreachable plane: recorded, never fatal
        return 0, f"{type(e).__name__}: {e}", {}


def _secret(var):
    p = os.environ.get(var)
    return Path(p).read_text(encoding="utf-8").strip() if p and Path(p).exists() else None


# ─── plane 1 and 2: Automation ──────────────────────────────────────────────────────────────────


def automation(reached):
    host, org = os.environ.get("VCFA_HOST"), os.environ.get("VCFA_ORG")
    user, pw = os.environ.get("VCFA_USER"), _secret("VCFA_PASSWORD_FILE")
    if not all((host, org, user, pw)):
        reached["automation"] = "not credentialed"
        return None, [], []

    cred = base64.b64encode(f"{user}@{org}:{pw}".encode()).decode()
    st, _, hdrs = _req(
        "POST",
        f"https://{host}/cloudapi/1.0.0/sessions",
        {"Authorization": f"Basic {cred}", "Accept": CLOUDAPI},
    )
    tok = hdrs.get("x-vmware-vcloud-access-token")
    if st != 200 or not tok:
        reached["automation"] = f"session login HTTP {st}"
        return None, [], []
    reached["automation"] = "read"
    h = {"Authorization": f"Bearer {tok}", "Accept": "application/json"}

    # (1) the grammar split: what construct do this org's templates use?
    st, raw, _ = _req("GET", f"https://{host}/blueprint/api/blueprints", h)
    grammar = {
        "templates": 0,
        "declaringTags": 0,
        "declaringLabels": 0,
        "declaringClassName": 0,
        "declaringFlavorOrImage": 0,
    }
    if st == 200:
        rows = json.loads(raw).get("content", [])
        grammar["templates"] = len(rows)
        for b in rows:
            st2, raw2, _ = _req("GET", f"https://{host}/blueprint/api/blueprints/{b['id']}", h)
            if st2 != 200:
                continue
            body = json.loads(raw2).get("content") or ""
            grammar["declaringTags"] += 1 if re.search(r"^\s+tags:\s*$", body, re.M) else 0
            grammar["declaringLabels"] += 1 if re.search(r"^\s+labels:\s*$", body, re.M) else 0
            grammar["declaringClassName"] += 1 if re.search(r"^\s+className:", body, re.M) else 0
            grammar["declaringFlavorOrImage"] += (
                1 if re.search(r"^\s+(flavor|image):", body, re.M) else 0
            )

    # (2) what each provisioned machine declares, and the UUID to find it by
    declared, orgs_seen = [], []
    st, raw, _ = _req("GET", f"https://{host}/deployment/api/deployments", h)
    if st == 200:
        for dep in json.loads(raw).get("content", []):
            st2, raw2, _ = _req(
                "GET", f"https://{host}/deployment/api/deployments/{dep['id']}/resources", h
            )
            if st2 != 200:
                continue
            for res in json.loads(raw2).get("content", []):
                obj = (res.get("properties") or {}).get("object") or {}
                if obj.get("kind") != "VirtualMachine":
                    continue
                meta, spec = obj.get("metadata") or {}, obj.get("spec") or {}
                if not spec.get("instanceUUID"):
                    continue
                declared.append(
                    {
                        "uuid": spec["instanceUUID"],
                        "name": meta.get("name", ""),
                        "namespace": meta.get("namespace", ""),
                        "labels": meta.get("labels") or {},
                        "apiVersion": obj.get("apiVersion", ""),
                    }
                )
                orgs_seen.append(meta.get("namespace", ""))
    return grammar, declared, orgs_seen


# ─── plane 3: vCenter ───────────────────────────────────────────────────────────────────────────


def vcenter(reached, wanted_names):
    host, user, pw = (
        os.environ.get("VC_HOST"),
        os.environ.get("VC_USER"),
        _secret("VC_PASSWORD_FILE"),
    )
    if not all((host, user, pw)):
        reached["vcenter"] = "not credentialed"
        return {}, {}
    cred = base64.b64encode(f"{user}:{pw}".encode()).decode()
    st, raw, _ = _req("POST", f"https://{host}/api/session", {"Authorization": f"Basic {cred}"})
    if st not in (200, 201):
        reached["vcenter"] = f"session HTTP {st}"
        return {}, {}
    sid = json.loads(raw)
    h = {"vmware-api-session-id": sid, "Accept": "application/json"}

    st, raw, _ = _req("GET", f"https://{host}/api/cis/tagging/category", h)
    if st != 200:
        reached["vcenter"] = f"tagging plane HTTP {st} (the identity can list VMs but not tags)"
        return {}, {}
    reached["vcenter"] = "read"

    cats, tags = {}, {}
    for cid in json.loads(raw):
        s, r, _ = _req("GET", f"https://{host}/api/cis/tagging/category/{cid}", h)
        if s == 200:
            cats[cid] = json.loads(r)["name"]
    s, r, _ = _req("GET", f"https://{host}/api/cis/tagging/tag", h)
    for tid in json.loads(r) if s == 200 else []:
        s2, r2, _ = _req("GET", f"https://{host}/api/cis/tagging/tag/{tid}", h)
        if s2 == 200:
            t = json.loads(r2)
            tags[tid] = (cats.get(t["category_id"], "?"), t["name"])

    by_uuid, held = {}, {}
    s, r, _ = _req("GET", f"https://{host}/api/vcenter/vm", h)
    for vm in json.loads(r) if s == 200 else []:
        if wanted_names and vm["name"] not in wanted_names:
            continue  # name narrows the candidates; the UUID still decides the join
        s2, r2, _ = _req("GET", f"https://{host}/api/vcenter/vm/{vm['vm']}", h)
        if s2 != 200:
            continue
        uuid = (json.loads(r2).get("identity") or {}).get("instance_uuid")
        if not uuid:
            continue
        by_uuid[uuid] = vm["name"]
        s3, r3, _ = _req(
            "POST",
            f"https://{host}/api/cis/tagging/tag-association?action=list-attached-tags",
            {**h, "Content-Type": "application/json"},
            json.dumps({"object_id": {"id": vm["vm"], "type": "VirtualMachine"}}).encode(),
        )
        carried = {}
        for tid in json.loads(r3) if s3 == 200 else []:
            cv = tags.get(tid)
            if cv:
                carried[cv[0]] = cv[1]
        held[uuid] = carried
    return by_uuid, held


# ─── planes 4 and 5: Operations ─────────────────────────────────────────────────────────────────


def operations(reached, wanted_names, namespaces):
    host, token = os.environ.get("OPS_HOST"), _secret("OPS_TOKEN_FILE")
    if not (host and token):
        reached["operations"] = "not credentialed"
        return None
    h = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    st, raw, _ = _req(
        "GET",
        f"https://{host}/suite-api/api/resources?resourceKind=VirtualMachine&pageSize=1000",
        h,
    )
    if st != 200:
        reached["operations"] = f"resources HTTP {st}"
        return None
    reached["operations"] = "read"

    collecting_bare = collecting_tagged = retained_bare = retained_tagged = 0
    property_names, label_bearing = set(), set()
    for res in json.loads(raw).get("resourceList", []):
        name = (res.get("resourceKey") or {}).get("name") or ""
        # The decay question is about every machine this platform provisioned, not only the ones
        # a deployment still describes: the retained objects are precisely the ones no deployment
        # mentions any more, and scoping to today's declarations hides them.
        folder = (res.get("resourceKey") or {}).get("resourceIdentifiers") or []
        related = name in wanted_names or any(
            ns and ns.split("-")[0] and name.startswith(ns.split("-")[0]) for ns in namespaces
        )
        if not related:
            continue
        del folder
        states = res.get("resourceStatusStates") or [{}]
        collecting = states[0].get("resourceState") == "STARTED"
        s, r, _ = _req(
            "GET", f"https://{host}/suite-api/api/resources/{res['identifier']}/properties", h
        )
        props = json.loads(r).get("property", []) if s == 200 else []
        names = {p.get("name", "") for p in props}
        property_names |= names
        tagged = any(
            p.get("name") in ("summary|tag", "summary|tagJson")
            and p.get("value") not in (None, "", "none", "[, , ]")
            for p in props
        )
        # does ANY property carry a Kubernetes label key? this is question 4
        label_bearing |= {n for n in names if "kubernetes.io" in n or n.lower().endswith("|labels")}
        if collecting:
            collecting_tagged += 1 if tagged else 0
            collecting_bare += 0 if tagged else 1
        else:
            retained_tagged += 1 if tagged else 0
            retained_bare += 0 if tagged else 1
    return {
        "collectingWithMetadata": collecting_tagged,
        "collectingWithout": collecting_bare,
        "retainedWithMetadata": retained_tagged,
        "retainedWithout": retained_bare,
        "propertyNamesOnAVmObject": len(property_names),
        "propertiesCarryingATag": sorted(n for n in property_names if n.startswith("summary|tag")),
        "propertiesCarryingAKubernetesLabel": sorted(label_bearing),
    }


# ─── the corpus at rest (this repository, not an estate) ────────────────────────────────────────


def _vm_label_blocks(text: str) -> list[set[str]]:
    """The label keys belonging to each ``kind: VirtualMachine`` in a file.

    Walks by indentation from the kind line: the machine's `metadata:` sits at the same indent, and
    its `labels:` block ends at the first line indented no further than `labels:` itself. Counting
    any `labels:` in the file instead would credit a Secret's labels to the machine beside it.
    """
    lines, out = text.splitlines(), []
    for i, ln in enumerate(lines):
        if ln.strip() != "kind: VirtualMachine":
            continue
        indent = len(ln) - len(ln.lstrip())
        keys: set[str] = set()
        # scan the sibling block in both directions: metadata may precede or follow kind
        for j in range(max(0, i - 40), min(len(lines), i + 60)):
            cur = lines[j]
            if not cur.strip() or len(cur) - len(cur.lstrip()) < indent:
                if j > i and keys:
                    break
                continue
            if cur.strip() == "labels:":
                li = len(cur) - len(cur.lstrip())
                for k in range(j + 1, len(lines)):
                    nxt = lines[k]
                    if not nxt.strip():
                        continue
                    if len(nxt) - len(nxt.lstrip()) <= li:
                        break
                    keys.add(nxt.strip().split(":")[0])
        out.append(keys)
    return out


def corpus():
    """How many published example manifests declare what the engine reads.

    Read from the checkout rather than an estate, so it carries a repo provenance. A template
    nobody has deployed cannot appear in any estate reading, and it is the one a reader copies.
    """
    roots = [HERE.parent / "day1-provisioning"]
    total = complete = 0
    for root in roots:
        if not root.exists():
            continue
        for p in sorted(root.rglob("*")):
            if p.suffix not in (".yaml", ".yml", ".md") or not p.is_file():
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
            if "vmoperator.vmware.com" not in text:
                continue
            # Each VirtualMachine's OWN labels, found by indentation rather than by splitting on
            # the document separator. A template may nest several machines under one document
            # (a blueprint puts each under resources.<id>.properties.manifest), and a Secret or a
            # Service in the same file has labels of its own that are not the subject.
            for man_labels in _vm_label_blocks(text):
                total += 1
                complete += 1 if all(lbl in man_labels for lbl in ENGINE_LABELS.values()) else 0
    return {"manifests": total, "declaringEveryConcept": complete}


# ─── scrub ──────────────────────────────────────────────────────────────────────────────────────


def scrub(record, secrets):
    """Replace every estate value with a stable placeholder, longest name first.

    Longest first is not a preference: a namespace name contains its project name, and replacing
    the short one first corrupts the long one beyond recognition.
    """
    blob = json.dumps(record)
    for i, value in enumerate(
        sorted({s for s in secrets if s and len(s) > 3}, key=len, reverse=True)
    ):
        blob = blob.replace(value, f"<estate-{i:02d}>")
    return json.loads(blob)


def main() -> int:
    reached = {}
    grammar, declared, namespaces = automation(reached)
    names = {d["name"] for d in declared}
    by_uuid, held = vcenter(reached, names)
    ops = operations(reached, names, set(namespaces))

    joined, bare, carrying, unreadable = 0, 0, 0, 0
    per_workload = []
    for d in declared:
        if d["uuid"] not in by_uuid:
            continue
        joined += 1
        tags = held.get(d["uuid"], {})
        owned = {k: v for k, v in tags.items() if k.startswith(OWNED_PREFIXES)}
        declares = {c: d["labels"].get(lbl) for c, lbl in ENGINE_LABELS.items()}
        n_declared = sum(1 for v in declares.values() if v)
        if owned:
            carrying += 1
        else:
            bare += 1
        unreadable += 1 if n_declared and not owned else 0
        per_workload.append(
            {
                "name": d["name"],
                "namespace": d["namespace"],
                "declares": {k: v for k, v in declares.items() if v},
                "carries": owned,
                "foreignCategories": len(tags) - len(owned),
            }
        )

    record = {
        "reached": reached,
        "grammar": grammar or {},
        "workloads": {
            "declaredByAutomation": len(declared),
            "joinedToAMachine": joined,
            "carryingOwnedMetadata": carrying,
            "carryingNone": bare,
            "declaringButUnprojected": unreadable,
        },
        "perWorkload": per_workload,
        "operations": ops or {},
        "corpus": corpus(),
        "engineLabels": ENGINE_LABELS,
    }

    # Label values that name an application are estate values too. Scrubbing them on both the
    # declared and the carried side keeps the correspondence visible while publishing neither.
    app_values = {d["labels"].get(ENGINE_LABELS["app"]) for d in declared}
    secrets = (
        set(names)
        | set(namespaces)
        | {v for v in app_values if v}
        | {
            os.environ.get("VCFA_HOST"),
            os.environ.get("VC_HOST"),
            os.environ.get("OPS_HOST"),
            os.environ.get("VCFA_ORG"),
            os.environ.get("VCFA_USER"),
            os.environ.get("VC_USER"),
        }
    )
    record = scrub(record, secrets)

    blob = json.dumps(record)
    for value in secrets:
        if value and len(value) > 3 and value in blob:
            print(f"REFUSING to write: {value!r} survived the scrub", file=sys.stderr)
            return 2

    OUT.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"wrote {OUT.name}: planes {reached}, {joined} workloads joined, "
        f"{carrying} carrying owned metadata, {bare} carrying none"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
