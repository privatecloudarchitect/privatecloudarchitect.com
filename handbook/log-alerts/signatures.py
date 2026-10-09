#!/usr/bin/env python3
"""signatures.py: find the identifier the platform writes for a failure, then try a query on stored events.

Read-only. Three subcommands, each answering one question a log alert depends on:

  catalog   Which event types can my build emit, and what does each one say?
            Each vCenter's event catalog (`EventManager.description.eventInfo`): every event type it knows, with
            its message text. Extended types (`esx.*`, `com.vmware.vc.*`) carry their identifier before a `|` in
            `fullFormat`. Filter by identifier prefix (`--family esx.problem.storage`) or by a word in the
            message (`--grep permanently`), which is how you go from the words you know to the identifier.
            Needs pyVmomi and VC_HOST (one or more, comma separated), VC_USER, VC_PASSWORD; VC_TLS_VERIFY=false
            for a self-signed CA.

  seen      Which identifiers have my hosts and vCenters actually written?
            The `[vob.*]` and `[esx.*]` identifiers in the hosts' own `vobd` records over --days, searched in
            six-hour slices (a search returns at most 2,000 events) with the firewall ruleset flood and labelled
            test lines left out; and the `vc_event_type` values vCenter's event stream carried, counted.

  try       Does this query match the records I expect, and nothing else?
            One query (`--vc-event <id>`, or `--app <name> --text <token>`, optionally `--within field=value`;
            `--text` alone shows which applications write a word, which is why a condition fixes `--app`)
            over --days: how many events, on which hosts, three samples, the VCF Operations object kind the
            samples' `vmw_vr_ops_id` names (the kind an alert on them takes), and the exact search body it sent, so
            the same query can become a log symptom. `--body FILE` sends a search body as it stands.

  monitor   What did Log Management build from my condition, and when does it run?
            Log Management runs each log symptom as an OpenSearch monitor, and OpenSearch logs the definition it
            stores (`TransportIndexMonitorAction`) into the same store where the platform's own logs are collected,
            as they are on the reference estate. For a symptom name, the latest logged definition: its schedule, the
            window as a range on the event's own timestamp, and each filter as the query it became (an exact `term`
            for `vc_event_type` and `appname`, a `match_phrase` on the whole line for `text`).

  bindings  Which objects can my logs raise alerts on?
            A record belongs to the object its `vmw_vr_ops_id` names, and an alert counts only records of its own
            object kind. Over --hours: for each object kind, how many objects and records, and which applications
            wrote them; and for vCenter's events about a virtual machine, the object each event type binds to (on
            the reference estate most bind to the VM's host, not the VM).

  fields    Does every field my query names exist here?
            Log Management's field catalog (`GET /api/v2/fields`), tallied by source and category, and with
            `--check a,b,c` each named field present or missing. Content packs are gone on 9.1, so a field an
            older query names exists only if a management pack or an operator defines it, and a condition on a
            missing field never fires and never says why.

Every subcommand prints a summary and, with --out DIR, writes `signatures-<subcommand>.record.json` (a catalog read
with --grep writes `signatures-catalog-grep.record.json`, a try with --label NAME `signatures-try-NAME.record.json`) with every
estate value (host, vCenter, cluster and datastore names, device and filesystem identifiers, addresses) replaced by
a placeholder; it refuses to write a record in which one survived. The environment for `seen` and `try` is
lmlib.py's (OPS_HOST, OPS_API_TOKEN, ...).

  python3 signatures.py catalog [--family PREFIX ...] [--grep WORD] [--out DIR]
  python3 signatures.py seen    [--days N] [--out DIR]
  python3 signatures.py fields  [--check NAME,NAME,...] [--out DIR]
  python3 signatures.py bindings [--hours N] [--out DIR]
  python3 signatures.py monitor --name "<symptom name>" [--out DIR [--label NAME]]
  python3 signatures.py try     (--vc-event ID | [--app APP] --text TOKEN | --body FILE) [--within FIELD=VALUE] [--days N]
                                [--out DIR [--label NAME]]
"""

from __future__ import annotations

import collections
import json
import os
import re
import ssl
import sys
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# Families an ESX storage alert set draws on, plus the host-path and vCenter types the exercises use.
FAMILIES = ("esx.problem.storage", "esx.clear.storage", "esx.problem.scsi", "esx.clear.scsi", "esx.problem.psastor",
            "esx.clear.psastor", "esx.problem.vmfs", "esx.clear.vmfs", "esx.problem.vmsyslogd", "com.vmware.vc.HA.Vmcp")
BUILTIN = ("HostConnectionLostEvent", "HostDisconnectedEvent", "VmFailedMigrateEvent", "BadUsernameSessionEvent")
# The forwarder's firewall ruleset writes flood vobd and would truncate the slices; labelled test lines are not
# the platform's own records. Both are left out of `seen`.
FLOOD = ("esx.audit.net.firewall.config.changed", "vob.net.firewall.config.changed")
LABEL = "labelled test line"
IDENT = re.compile(r"\[((?:vob|esx)\.[A-Za-z0-9_.]+)\]")
DEVICE = re.compile(r"\b(?:naa|eui|t10|mpx)\.[A-Za-z0-9_.:-]+")
FSID = re.compile(r"\[[0-9a-f]{8}-[0-9a-f]{8}(?:-[0-9a-f]{4}-[0-9a-f]{12})?\]")
IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
ENRICH = ("hostname", "vmw_vcenter", "vmw_cluster", "vmw_datacenter", "vmw_host", "source")


def hit_fields(hit: dict) -> dict[str, str]:
    """A search hit's indexed fields (appname, hostname, vc_event_type, the vmw_* enrichment) by name."""
    return {f.get("internalName"): f.get("value") for f in (hit.get("msgContent") or {}).get("fields") or []}


# ---------------------------------------------------------------- catalog: what the build can emit
def catalog(families: tuple[str, ...], grep: str | None) -> dict:
    try:
        from pyVim.connect import Disconnect, SmartConnect
        from pyVmomi import vim
    except ImportError as exc:
        raise SystemExit("catalog needs pyVmomi (pip install pyvmomi); seen and try need only the standard library") from exc
    verify = os.environ.get("VC_TLS_VERIFY", "true").strip().lower() not in ("0", "false", "no", "off")
    ctx = ssl.create_default_context() if verify else ssl._create_unverified_context()
    out = {}
    for host in [h.strip() for h in os.environ["VC_HOST"].split(",") if h.strip()]:
        si = SmartConnect(host=host, user=os.environ["VC_USER"], pwd=os.environ["VC_PASSWORD"], sslContext=ctx)
        try:
            content = si.RetrieveContent()
            events = {}
            for e in content.eventManager.description.eventInfo:
                key = e.key if isinstance(e.key, str) else getattr(e.key, "_wsdlName", str(e.key))
                text = e.fullFormat or ""
                if key in ("EventEx", "ExtendedEvent") and "|" in text:
                    key, text = text.split("|", 1)
                wanted = key.startswith(families) or key in BUILTIN
                if grep:
                    wanted = re.search(rf"(?<![\w]){re.escape(grep)}(?![\w])", text, re.I) is not None
                if wanted:
                    events[key] = {"category": e.category, "text": text}
            view = content.viewManager.CreateContainerView(content.rootFolder, [vim.HostSystem], True)
            builds = sorted({f"{h.config.product.version} {h.config.product.build}" for h in view.view if h.config})
            view.Destroy()
            out[host] = {"version": content.about.version, "build": content.about.build, "host_builds": builds,
                         "types": len(content.eventManager.description.eventInfo), "events": events}
        finally:
            Disconnect(si)
    return out


# ---------------------------------------------------------------- seen: what the estate has written
def now_ms() -> int:
    from lmlib import now_ms as _now

    return _now()


def window(days: float) -> tuple[int, int]:
    end = now_ms()
    return end - int(days * 86400000), end


def seen(s, days: float, scrub) -> dict:
    start, end = window(days)
    counts: collections.Counter[str] = collections.Counter()
    hosts: dict[str, set[str]] = collections.defaultdict(set)
    example: dict[str, str] = {}
    truncated, read, step = 0, 0, 6 * 3600000
    t = start
    while t < end:
        body = {"query": {"bool": {
            "must": [{"term": {"appname": "vobd"}}],
            "must_not": [{"match_phrase": {"text": f}} for f in (*FLOOD, LABEL)],
            "filter": [{"range": {"timestamp": {"gte": t, "lt": min(t + step, end)}}}]}}, "size": 2000}
        ev = s.search(body).get("events") or {}
        hits = ev.get("hits") or []
        truncated += (ev.get("total") or 0) > len(hits)
        for h in hits:
            read += 1
            fields = hit_fields(h)
            host = fields.get("hostname") or ""
            text = re.sub(r"\s+", " ", (h.get("msgContent") or {}).get("originalText", ""))
            for ident in IDENT.findall(text):
                counts[ident] += 1
                if host:
                    hosts[ident].add(scrub.add_host(host, "esx"))
                example.setdefault(ident, shape(clean(scrub, text), ident))
        t += step
    agg = s.search({"query": {"bool": {"must": [{"exists": {"field": "vc_event_type"}}],
                                       "must_not": [{"match_phrase": {"text": LABEL}}],
                                       "filter": [{"range": {"timestamp": {"gte": start, "lte": end}}}]}},
                    "size": 0, "aggs": {"t": {"multi_terms": {"terms": [{"field": "vc_event_type"}], "size": 1000}}}})
    vc = {b["key"][0]: b["doc_count"] for b in ((agg.get("aggregations") or {}).get("buckets") or [])}
    return {"window_days": days, "vobd": {"records_read": read, "truncated_slices": int(truncated),
            "excluded": [*FLOOD, LABEL],
            "identifiers": {k: {"records": n, "hosts": len(hosts[k]), "example": example[k]} for k, n in counts.most_common()}},
            "vc_event_types": dict(sorted(vc.items(), key=lambda kv: -kv[1]))}


# ---------------------------------------------------------------- try: does the query match what you expect
def query_body(vc_event: str | None, app: str | None, text: str | None, within: list[tuple[str, str]],
               start: int, end: int, size: int = 3) -> dict:
    """The search body for one candidate condition: the shape a log symptom's filters take, as a search."""
    must: list[dict] = []
    if vc_event:
        must.append({"term": {"vc_event_type": vc_event}})
    if app:
        must.append({"term": {"appname": app}})
    if text:
        must.append({"match_phrase": {"text": text}})
    must += [{"term": {f: v}} for f, v in within]
    return {"query": {"bool": {"must": must, "must_not": [{"match_phrase": {"text": LABEL}}],
                               "filter": [{"range": {"timestamp": {"gte": start, "lte": end}}}]}}, "size": size}


def try_query(s, body: dict, scrub) -> dict:
    ev = s.search(body).get("events") or {}

    def agg(terms: list[str], size: int) -> list[dict]:
        q = dict(body, size=0, aggs={"a": {"multi_terms": {"terms": [{"field": f} for f in terms], "size": size}}})
        return (s.search(q).get("aggregations") or {}).get("buckets") or []

    by_app = [{"appname": b["key"][0], "events": b["doc_count"]} for b in agg(["appname"], 30)]
    hits = list(ev.get("hits") or [])[:3]
    fixed = any("appname" in (c.get("term") or {}) for c in body["query"]["bool"]["must"])
    if not fixed:  # a bare word: one record from each application that writes it, which is the lesson
        hits = []
        for row in by_app[:6]:
            q = json.loads(json.dumps(body))
            q["query"]["bool"]["must"].append({"term": {"appname": row["appname"]}})
            hits += list((s.search(dict(q, size=1)).get("events") or {}).get("hits") or [])
    samples, kinds = [], collections.Counter()
    for h in hits:
        fields = hit_fields(h)
        kinds[object_kind(s, fields.get("vmw_vr_ops_id"))] += 1
        for k in ENRICH:
            if fields.get(k):
                scrub.add_host(fields[k], "host" if k in ("hostname", "source", "vmw_host") else k.replace("vmw_", ""))
        text = re.sub(r"\s+", " ", (h.get("msgContent") or {}).get("originalText", ""))
        if fields.get("vc_event_type"):
            # vCenter renders its catalog text with object, account and datastore names no list can hold; the record
            # keeps the event type and the header, and the catalog has the text with its placeholders.
            text = text.split(" vcenter-server:", 1)[0] + " vcenter-server: <the catalog text of " + fields["vc_event_type"] + ">"
        samples.append({"appname": fields.get("appname"), "vc_event_type": fields.get("vc_event_type"),
                        "text": clean(scrub, text)[:300]})
    rows = [{"host": scrub.add_host(b["key"][0], "host"), "appname": b["key"][1], "events": b["doc_count"]}
            for b in agg(["hostname", "appname"], 100)]
    return {"body": body, "events": ev.get("total") or sum(r["events"] for r in rows), "by_application": by_app,
            "by_host": rows, "object_kinds": dict(kinds), "samples": samples}


def object_kind(s, ops_id: str | None) -> str:
    """The VCF Operations object kind a record's `vmw_vr_ops_id` names: the kind an alert on these records takes."""
    if not ops_id:
        return "none: the record names no inventory object"
    st, r = s.ops("GET", f"/api/resources/{ops_id}")
    return ((r or {}).get("resourceKey") or {}).get("resourceKindKey") or f"unresolved (HTTP {st})"


def shape(text: str, ident: str) -> str:
    """A record up to and including its identifier: the format a condition and a labelled line need, without the
    message after it, which can name datastores, machines and devices."""
    at = text.find("[" + ident + "]")
    return text[: at + len(ident) + 2] if at >= 0 else text[:120]


# An account (`user@domain`, also with its domain already a placeholder) or a datastore path in a record is an
# estate value no registry holds.
ESTATE_SHAPES = re.compile(r"(?<![\w{}])[\w.-]+@(?:\{\{|(?!\d+\b)[\w.-])|/vmfs/volumes/\S+")


# ---------------------------------------------------------------- bindings: which objects records belong to
def bindings(s, hours: float, days: float) -> dict:
    """Records by the object kind their vmw_vr_ops_id names, and vCenter's VM events by the kind they bind to."""
    cache: dict[str, str] = {}

    def kind(rid: str | None) -> str:
        if not rid:
            return "no inventory object"
        if rid not in cache:
            st, r = s.ops("GET", f"/api/resources/{rid}")
            cache[rid] = ((r or {}).get("resourceKey") or {}).get("resourceKindKey") or f"unresolved (HTTP {st})"
        return cache[rid]

    end = now_ms()
    body = {"query": {"bool": {"must": [{"exists": {"field": "vmw_vr_ops_id"}}],
                               "filter": [{"range": {"timestamp": {"gte": end - int(hours * 3600000), "lte": end}}}]}},
            "size": 0, "aggs": {"a": {"multi_terms": {"terms": [{"field": "vmw_vr_ops_id"}, {"field": "appname"}], "size": 5000}}}}
    objects: dict[str, set] = collections.defaultdict(set)
    records: collections.Counter[str] = collections.Counter()
    apps: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for b in (s.search(body).get("aggregations") or {}).get("buckets") or []:
        k = kind(b["key"][0])
        objects[k].add(b["key"][0])
        records[k] += b["doc_count"]
        apps[k][b["key"][1]] += b["doc_count"]
    kinds = {k: {"objects": len(objects[k]), "records": records[k], "applications": [a for a, _ in apps[k].most_common(6)]}
             for k, _ in records.most_common()}
    start = end - int(days * 86400000)
    body = {"query": {"bool": {"must": [{"term": {"vc_event_obj_type": "VirtualMachine"}}],
                               "filter": [{"range": {"timestamp": {"gte": start, "lte": end}}}]}},
            "size": 0, "aggs": {"a": {"multi_terms": {"terms": [{"field": "vc_event_type"}], "size": 60}}}}
    vm_events = []
    for b in (s.search(body).get("aggregations") or {}).get("buckets") or []:
        et = b["key"][0]
        ev = s.search({"query": {"bool": {"must": [{"term": {"vc_event_type": et}}],
                                          "filter": [{"range": {"timestamp": {"gte": start, "lte": end}}}]}}, "size": 5}).get("events") or {}
        seen = collections.Counter(kind(hit_fields(h).get("vmw_vr_ops_id")) for h in ev.get("hits") or [])
        vm_events.append({"vc_event_type": et, "events": b["doc_count"], "binds_to": dict(seen)})
    return {"window_hours": hours, "kinds": kinds, "vm_events_window_days": days, "vm_events": vm_events}


# ---------------------------------------------------------------- monitor: what a condition became
def monitor_definition(s, name: str, hours: float = 24) -> dict:
    """The latest definition OpenSearch logged for the monitor named `name`: schedule, window and filter clauses."""
    end = now_ms()
    body = {"query": {"bool": {"must": [{"match_phrase": {"text": "TransportIndexMonitorAction"}}, {"match_phrase": {"text": name}}],
                               "filter": [{"range": {"timestamp": {"gte": end - int(hours * 3600000), "lte": end}}}]}},
            "size": 20, "sort": [{"timestamp": {"order": "desc"}}]}
    for h in (s.search(body).get("events") or {}).get("hits") or []:
        text = (h.get("msgContent") or {}).get("originalText", "")
        at = text.rfind('"name":"' + name + '"')
        if at < 0:
            continue
        seg = text[at:]
        sch = re.search(r'"enabled":(true|false)[^{}]*?"schedule":\{"period":\{"interval":(\d+),"unit":"(\w+)"\}\}', seg)
        rng = re.search(r'"range":\{"(\w+)":\{"from":"\{\{period_end\}\}\|\|-(\w+)"', seg)
        end_q = seg.find('"aggregations"')
        q = seg[: end_q if end_q > 0 else 4000]
        clauses = [{"query": "term", "field": f.removeprefix("fields."), "value": v}
                   for f, v in re.findall(r'"term":\{"([\w.]+)":\{"value":"([^"]*)"', q)]
        clauses += [{"query": "match_phrase", "field": f, "value": v}
                    for f, v in re.findall(r'"match_phrase":\{"(\w+)":\{"query":"([^"]*)"', q)]
        return {"found": True, "name": name, "enabled": (sch.group(1) == "true") if sch else None,
                "schedule": f"{sch.group(2)} {sch.group(3).lower().rstrip('s') if sch.group(2) == '1' else sch.group(3).lower()}" if sch else None,
                "window": f"the last {rng.group(2)} by {rng.group(1)}" if rng else None, "clauses": clauses}
    return {"found": False, "name": name}


# ---------------------------------------------------------------- records
# An account (`user@domain`). An RFC 5424 structured-data id (`esx@4413`, `ops@4413`: a name at an enterprise
# number) is product vocabulary, not an account.
ACCOUNT = re.compile(r"(?<![\w{}])[\w.-]+@(?!\d+\b)[\w.-]+")


def clean(scrub, text: str) -> str:
    """One line of evidence: registered names first, then devices, filesystems, addresses, ids and accounts, so a
    later truncation cannot leave half of a value behind."""
    for v in sorted(set(ACCOUNT.findall(text)), key=len, reverse=True):  # before names: an account holds a domain
        text = text.replace(v, scrub.add(v, "account"))
    text = scrub.scrub(text)
    for rx, cat in ((DEVICE, "device"), (IPV4, "address"), (UUID, "uuid")):
        for v in sorted(set(rx.findall(text)), key=len, reverse=True):
            text = text.replace(v, scrub.add(v, cat))
    for v in sorted(set(FSID.findall(text)), key=len, reverse=True):
        text = text.replace(v, "[" + scrub.add(v.strip("[]"), "filesystem") + "]")
    return text


def scrub_text(scrub, obj):
    """Registered names first (longest first), then the shapes no list can hold: devices, filesystems, addresses."""
    text = json.dumps(scrub.scrub_obj(obj))
    for rx, cat in ((DEVICE, "device"), (FSID, "filesystem"), (IPV4, "address"), (UUID, "uuid")):
        for v in sorted(set(rx.findall(text)), key=len, reverse=True):
            text = text.replace(v, scrub.add(v, cat).strip("[]") if cat != "filesystem" else "[" + scrub.add(v, cat) + "]")
    return json.loads(text)


def write(out_dir: Path | None, name: str, record: dict, scrub) -> None:
    if not out_dir:
        return
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"signatures-{name}.record.json"
    scrubbed = scrub_text(scrub, record)
    if ESTATE_SHAPES.search(json.dumps(scrubbed)):
        raise SystemExit(f"refusing to write {path.name}: an account or a datastore path survived scrubbing")
    scrub.write(path, scrubbed)
    print(f"wrote {path.name}")


def parse_args(argv: list[str]) -> dict:
    if not argv or argv[0] not in ("catalog", "seen", "try", "fields", "monitor", "bindings"):
        raise SystemExit(__doc__)
    a = {"cmd": argv[0], "family": [], "grep": None, "days": 7.0, "out": None, "vc_event": None, "app": None,
         "text": None, "within": [], "body": None, "label": None, "check": [], "name": None, "hours": 24.0}
    rest = argv[1:]
    while rest:
        x = rest.pop(0)
        if x == "--family" and rest:
            a["family"].append(rest.pop(0))
        elif x in ("--days", "--hours") and rest and re.fullmatch(r"\d+(\.\d+)?", rest[0]):
            a[x[2:]] = float(rest.pop(0))
        elif x == "--within" and rest and "=" in rest[0]:
            a["within"].append(tuple(rest.pop(0).split("=", 1)))
        elif x == "--check" and rest:
            a["check"] = [n.strip() for n in rest.pop(0).split(",") if n.strip()]
        elif x in ("--grep", "--vc-event", "--app", "--text", "--label", "--name") and rest:
            a[x[2:].replace("-", "_")] = rest.pop(0)
        elif x in ("--out", "--body") and rest:
            a[x[2:]] = Path(rest.pop(0))
        else:
            raise SystemExit(f"unknown argument {x!r}")
    if a["cmd"] == "try" and not (a["vc_event"] or a["text"] or a["body"]):
        raise SystemExit("try needs --vc-event ID, or --text TOKEN (with --app APP for a condition), or --body FILE")
    return a


def main(argv: list[str]) -> int:
    a = parse_args(argv)
    from lmlib import Scrubber

    scrub = Scrubber()
    taken = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if a["cmd"] == "catalog":
        cat = catalog(tuple(a["family"]) or FAMILIES, a["grep"])
        record = {"read_at": taken, "families": list(a["family"]) or list(FAMILIES) + list(BUILTIN),
                  "grep": a["grep"], "vcenters": {}}
        for host, v in cat.items():
            name = scrub.add_host(host, "vcenter")
            record["vcenters"][name] = v
            print(f"{name}: vCenter {v['version']} {v['build']}; hosts {v['host_builds']}; "
                  f"{v['types']} event types, {len(v['events'])} kept")
        ids = [set(v["events"]) for v in cat.values()]
        record["same_on_every_vcenter"] = bool(ids) and all(i == ids[0] for i in ids)
        for key, e in sorted(next(iter(cat.values()))["events"].items()) if cat else []:
            print(f"  {key}  {e['text'][:110]}")
        write(a["out"], "catalog-grep" if a["grep"] else "catalog", record, scrub)
        return 0
    from lmlib import Session

    s = Session()
    if a["cmd"] == "bindings":
        record = {"read_at": taken, **bindings(s, a["hours"], a["days"])}
        print(f"records with an inventory object over {a['hours']:g} hours, by the object kind they bind to:")
        for k, v in record["kinds"].items():
            print(f"  {k}: {v['objects']} objects, {v['records']} records; applications {v['applications']}")
        print(f"vCenter events about a virtual machine over {a['days']:g} days, and the object kind each binds to:")
        for e in record["vm_events"]:
            print(f"  {e['events']:>7}  {e['vc_event_type']:<58} {e['binds_to']}")
        write(a["out"], "bindings", record, scrub)
        return 0
    if a["cmd"] == "monitor":
        if not a["name"]:
            raise SystemExit("monitor needs --name \"<symptom name>\"")
        record = {"read_at": taken, **monitor_definition(s, a["name"])}
        if not record.get("found"):
            print(f"no logged monitor definition named {a['name']!r} in the last 24 hours")
            return 1
        print(f"monitor {a['name']}: enabled {record['enabled']}; runs every {record['schedule']}; counts lines whose own timestamp is within {record['window']}")
        for c in record["clauses"]:
            print(f"  {c['query']:<13} {c['field']:<22} {c['value']}")
        write(a["out"], f"monitor-{a['label']}" if a["label"] else "monitor", record, scrub)
        return 0
    if a["cmd"] == "fields":
        st, fields = s.li("GET", "/api/v2/fields")
        if st != 200:
            raise SystemExit(f"FATAL: GET /api/v2/fields -> HTTP {st}")
        fields = fields or []
        names = {f.get("internalName") for f in fields} | {f.get("displayName") for f in fields}
        kinds = collections.Counter(f"{f.get('fieldSource')}/{f.get('fieldCategory')}" for f in fields)
        record = {"read_at": taken, "fields": len(fields), "by_source_and_category": dict(sorted(kinds.items())),
                  "check": {n: n in names for n in a["check"]}}
        print(f"{len(fields)} fields: " + ", ".join(f"{k} {v}" for k, v in sorted(kinds.items())))
        for n, ok in record["check"].items():
            print(f"  {'present' if ok else 'MISSING'}  {n}")
        write(a["out"], "fields", record, scrub)
        return 1 if not all(record["check"].values()) else 0
    if a["cmd"] == "seen":
        record = {"read_at": taken, **seen(s, a["days"], scrub)}
        vb = record["vobd"]
        print(f"vobd over {a['days']:g} days: {vb['records_read']} records, {len(vb['identifiers'])} identifiers, "
              f"{vb['truncated_slices']} truncated slices")
        for k, v in list(vb["identifiers"].items())[:25]:
            print(f"  {v['records']:>7}  {v['hosts']:>3} host{'s' if v['hosts'] != 1 else ' '}  {k}")
        print(f"vc_event_type over {a['days']:g} days: {len(record['vc_event_types'])} types")
        write(a["out"], "seen", record, scrub)
        return 0
    start, end = window(a["days"])
    body = (json.loads(a["body"].read_text(encoding="utf-8")) if a["body"]
            else query_body(a["vc_event"], a["app"], a["text"], a["within"], start, end))
    record = {"read_at": taken, "window_days": a["days"], **try_query(s, body, scrub)}
    print(json.dumps(body))
    print(f"{record['events']} events; by application: " + ", ".join(f"{r['appname']} {r['events']}" for r in record["by_application"]))
    for r in record["by_host"][:12]:
        print(f"  {r['events']:>6}  {r['appname'] or '-':<10} {r['host']}")
    print(f"  the records name: {record['object_kinds']} (the object kind an alert on them takes)")
    for x in record["samples"]:
        print(f"  sample: {x['text'][:160]}")
    write(a["out"], f"try-{a['label']}" if a["label"] else "try", record, scrub)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
