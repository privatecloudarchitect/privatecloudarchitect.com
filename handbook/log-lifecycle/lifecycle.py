#!/usr/bin/env python3
"""lifecycle.py: what Log Management does with an event after it arrives, read and proven on your own estate.

Three commands, for the chapter at privatecloudarchitect.com/handbook/log-lifecycle:

  census    Read-only. Every partition with its order, filter, retention, archive, event count and oldest
            timestamp; how far back a search reaches, from the events held per day; the external storage, every
            forwarder, mask and filter, and the volume by day and by application. Then the checks the chapter teaches:
            retentions the shard budget cannot hold (with --size), a retention longer than the days the store holds,
            nothing outliving retention, a syslog forwarder that hides the source, forwarding without TLS, a mask or
            filter with no condition, and filters that also take events from every forwarder.
  plan      No estate needed. The days each partition can hold under the shard budget for a size, a replica count
            and a number of partitions, as the chapter's planner computes them.
  trial     Proves one rule before you trust it, on labelled lines only. A throwaway filter, mask or partition is
            created with a condition no other event can match (an application name made for the run), labelled lines
            are sent to a syslog listener you name, the store is read back, and the rule is deleted and read back
            absent. `trial forwarder` creates nothing: it runs Log Management's connection test against a
            destination you name. Without --send, every trial prints its plan and changes nothing.

Standard library Python 3. The sign-in, the Log Management token and the search are the log-alerts folder's lmlib.py
(which takes the metrics-collection sign-in and the log-collection scrubber), found beside this folder. Environment:
OPS_HOST, OPS_API_TOKEN; optional OPS_BROKER_HOST, OPS_REALM, OPS_TLS_VERIFY.

  python3 lifecycle.py census [--size small|medium|large] [--replicas N] [--out DIR]
  python3 lifecycle.py plan --size medium --replicas 3 --partitions 4 [--retention NAME=DAYS ...]
  python3 lifecycle.py trial mask --target ssl://LISTENER:PORT [--selector REGEX] [--sample TEXT] [--send] [--out DIR]
  python3 lifecycle.py trial filter --target ssl://LISTENER:PORT [--send] [--out DIR]
  python3 lifecycle.py trial partition --target ssl://LISTENER:PORT [--retention-days N] [--send] [--out DIR]
  python3 lifecycle.py trial forwarder --host HOST --port PORT [--protocol SYSLOG|RAW] [--transport TCP|UDP] [--tls] [--out DIR]

Exit codes: 0 done (census: no BAD finding), 1 a BAD finding or a trial that did not behave as the chapter says,
2 a usage or sign-in error.
"""

from __future__ import annotations

import argparse
import json
import re
import secrets
import socket
import ssl
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent


def _beside(folder: str, marker: str) -> Path:
    for p in (HERE.parent / folder, HERE.parents[3] / "deploy/privatecloudarchitect/companion/staging/handbook" / folder):
        if (p / marker).is_file():
            return p
    raise SystemExit(f"FATAL: {folder}/{marker} is not beside this folder; run from the companion repository's handbook/ tree")


sys.path.insert(0, str(_beside("log-alerts", "lmlib.py")))

from lmlib import Scrubber, Session  # noqa: E402

SHARDS = {"small": 700, "medium": 800, "large": 900}  # per replica (Log Management Detailed Design, 9.1)
PREFIX = "pca-trial-"
DAY_MS = 86_400_000
SAFE = "labelled test line, safe to ignore"


# ── reading ────────────────────────────────────────────────────────────────────────────────────────
def now_ms() -> int:
    return int(time.time() * 1000)


def iso_ms(ms: int | None) -> str | None:
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if ms else None


def get(s: Session, path: str):
    st, body = s.li("GET", path)
    if st != 200:
        raise SystemExit(f"FATAL: GET {path} -> HTTP {st}: {json.dumps(body)[:200]}")
    return body


def items(body) -> list[dict]:
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for k in ("partitions", "externalStorageResponseList", "items", "configs", "rules", "forwarders"):
            if isinstance(body.get(k), list):
                return body[k]
    return []


def describe(constraints: dict | None) -> str:
    """A rule's condition in words: each clause as field and value, or 'no condition'."""
    b = (constraints or {}).get("bool") or {}
    parts = []
    for kind in ("filter", "must", "should", "must_not"):
        for clause in b.get(kind) or []:
            for op, arg in clause.items():
                if isinstance(arg, dict):
                    f = arg.get("field") if op == "exists" else ", ".join(f"{k}={v}" for k, v in arg.items())
                    parts.append(("NOT " if kind == "must_not" else "") + (f"{f} exists" if op == "exists" else f"{op} {f}"))
    if not parts and constraints and not b:
        parts.append(json.dumps(constraints)[:80])
    return "; ".join(parts) or "no condition"


def search_count(s: Session, query: dict, hours: float, aggs: dict | None = None) -> dict:
    t = now_ms()
    body = {"query": {"bool": {**query, "filter": [{"range": {"timestamp": {"gte": t - int(hours * 3_600_000), "lte": t}}}]}},
            "size": 0}
    if aggs:
        body["aggregations"] = aggs
    return s.search(body)


def hourly_total(s: Session, query: dict, hours: float) -> int:
    r = search_count(s, query, hours, {"h": {"date_histogram": {"field": "timestamp", "fixed_interval": "1h"}}})
    return sum(b.get("doc_count") or 0 for b in (r.get("aggregations") or {}).get("buckets", []))


def volume(s: Session) -> dict:
    days = search_count(s, {"must": [{"match_all": {}}]}, 24 * 31, {"d": {"date_histogram": {"field": "timestamp", "fixed_interval": "1d"}}})
    per_day = [{"day": iso_ms(int(b["key"][0]))[:10], "events": b.get("doc_count") or 0} for b in (days.get("aggregations") or {}).get("buckets", [])]
    total = hourly_total(s, {"must": [{"match_all": {}}]}, 24)
    with_app = hourly_total(s, {"must": [{"exists": {"field": "appname"}}]}, 24)
    top = search_count(s, {"must": [{"match_all": {}}]}, 24, {"t": {"multi_terms": {"terms": [{"field": "appname"}], "size": 15}}})
    apps = [{"appname": (b.get("key") or [None])[0], "events": b.get("doc_count") or 0,
             "share": round((b.get("doc_count") or 0) / total, 4) if total else None}
            for b in (top.get("aggregations") or {}).get("buckets", [])]
    return {"events_per_day": per_day, "last_24h": total, "last_24h_with_appname": with_app, "top_applications_24h": apps,
            "depth": depth(per_day)}


def depth(per_day: list[dict]) -> dict:
    """How far back a search reaches, from the volume by day: the run of whole days at full volume that ends yesterday.

    A partition's oldest event is the oldest timestamp it holds, and a source that sends old lines late pulls it back
    by days without bringing any history with it, so the day counts, not that timestamp, measure the depth. A day
    counts as full at half the busiest whole day or more: a median would be pulled down by the near-empty days that
    late lines leave behind the store's real history."""
    days = sorted(per_day, key=lambda d: d["day"])
    whole = days[:-1]  # the last bucket is today, still filling
    if not whole:
        return {"full_days": 0, "first_full_day": None, "events_before": 0}
    busiest = max(d["events"] for d in whole)
    first = len(whole)
    while first > 0 and whole[first - 1]["events"] >= busiest / 2:
        first -= 1
    return {"full_days": len(whole) - first, "first_full_day": whole[first]["day"] if first < len(whole) else None,
            "busiest_day": busiest, "events_before": sum(d["events"] for d in whole[:first])}


def census(s: Session, size: str | None, replicas: int) -> tuple[dict, list[tuple[str, str]]]:
    t = now_ms()
    parts = sorted(items(get(s, "/api/v2/logs/partitions")), key=lambda p: p.get("order") or 0)
    stores = items(get(s, "/api/v2/storages"))
    fwds, masks, filters = (items(get(s, p)) for p in ("/api/v2/logs/forwarders", "/api/v2/logs/masks", "/api/v2/logs/filters"))
    out = {
        "read_at": iso_ms(t), "version": (get(s, "/api/v2/version") or {}).get("version"),
        "partitions": [{
            "name": p.get("name"), "order": p.get("order"), "built_in": bool(p.get("isDefault")), "enabled": p.get("enabled"),
            "condition": describe(p.get("constraints")) if p.get("constraints") else ("catch-all" if p.get("order") == 1000 else "none"),
            "retention_days": round((p.get("retentionPeriodSeconds") or 0) / 86400, 2), "archive": bool((p.get("archiveConfig") or {}).get("enabled")),
            "events": p.get("partitionCount"), "size_reported": p.get("partitionSize"),
            "oldest_event": iso_ms(p.get("oldestLogTime")), "oldest_event_age_days": round((t - p["oldestLogTime"]) / DAY_MS, 2) if p.get("oldestLogTime") else None,
            "created": iso_ms(p.get("createdAt")),
        } for p in parts],
        "external_storage": [{"name": x.get("name"), "type": x.get("type") or x.get("storageType")} for x in stores],
        "forwarders": [{"name": f.get("name"), "destination": f"{f.get('host')}:{f.get('port')}", "protocol": f.get("protocol"),
                        "transport": f.get("transportProtocol"), "tls": f.get("sslEnabled"), "enabled": f.get("enabled"),
                        "condition": describe(f.get("constraints"))} for f in fwds],
        "masks": [{"name": m.get("name"), "field": m.get("fieldName"), "selector": m.get("selector"), "enabled": m.get("isEnabled"),
                   "condition": describe(m.get("constraints"))} for m in masks],
        "filters": [{"name": f.get("name"), "enabled": f.get("enabled"), "condition": describe(f.get("constraints"))} for f in filters],
        "volume": volume(s),
    }
    return out, checks(out, size, replicas)


def checks(c: dict, size: str | None, replicas: int) -> list[tuple[str, str]]:
    """(level, finding): BAD loses or exposes data, WARN deserves a decision, INFO is worth knowing."""
    f: list[tuple[str, str]] = []
    parts = [p for p in c["partitions"] if p["enabled"]]
    if size:
        most = SHARDS[size] // max(len(parts), 1)
        f.append(("INFO", f"shard budget: {SHARDS[size]} per replica at size {size} over {len(parts)} active partitions, "
                          f"at most {most} days each; more replicas add disk, not shard days"))
        asked = sum(p["retention_days"] for p in parts)
        if asked > SHARDS[size]:
            f.append(("BAD", f"the partitions' retentions add up to {asked:g} days, past the budget of {SHARDS[size]} shards per replica"))
        for p in parts:
            if p["retention_days"] > most:
                f.append(("WARN", f"partition {p['name']!r} asks for {p['retention_days']:g} days, more than an even share of {most}: it fits only while the others take less"))
    d = c["volume"]["depth"]
    if d["first_full_day"]:
        f.append(("INFO", f"the store holds {d['full_days']} whole days at full volume, from {d['first_full_day']}, plus today; "
                          f"{d['events_before']:,} events are stamped earlier (a partial day, or lines a source sent late)"))
    for p in parts:
        want = p["retention_days"]
        created = datetime.fromisoformat(p["created"].replace("Z", "+00:00")).timestamp() * 1000 if p["created"] else None
        lived = (now_ms() - created) / DAY_MS if created else None
        if p["oldest_event"]:
            f.append(("INFO", f"partition {p['name']!r}: oldest timestamp {p['oldest_event']}, retention "
                              f"{'no time limit' if not want else f'{want:g} days'}; a late line moves that timestamp, so read the depth above"))
        if want and lived and lived > want + 1 and d["first_full_day"] and d["full_days"] < want - 1:
            f.append(("WARN", f"partition {p['name']!r} keeps {want:g} days, but the store as a whole holds {d['full_days']} whole days: "
                              "read that partition's own history before relying on its retention"))
        if not p["archive"]:
            f.append(("INFO", f"partition {p['name']!r} has no archive: nothing it holds outlives retention or capacity"))
    if not c["external_storage"]:
        f.append(("INFO", "no external storage is defined, so no partition can archive"))
    for x in c["forwarders"]:
        if x["protocol"] == "SYSLOG":
            f.append(("WARN", f"forwarder {x['name']!r} uses SYSLOG: its receiver records Log Management, not the host, as each event's source"))
        if not x["tls"]:
            f.append(("WARN", f"forwarder {x['name']!r} sends without TLS"))
        if x["transport"] == "UDP":
            f.append(("WARN", f"forwarder {x['name']!r} uses UDP: a lost datagram is a lost event"))
        if x["condition"] == "no condition":
            f.append(("INFO", f"forwarder {x['name']!r} has no condition: it forwards every event"))
    if c["forwarders"] and c["filters"]:
        f.append(("WARN", f"{len(c['filters'])} filter(s) and {len(c['forwarders'])} forwarder(s): a filtered event is never forwarded, so each filter also removes its events from every forwarder's feed"))
    for m in c["masks"]:
        if m["condition"] == "no condition":
            f.append(("BAD", f"mask {m['name']!r} has no condition: it applies to every event"))
        if m["selector"] and "(" not in m["selector"]:
            f.append(("INFO", f"mask {m['name']!r} selector has no capture group, which the 9.1 page asks for; prove it with `trial mask --selector`"))
    for x in c["filters"]:
        if x["condition"] == "no condition":
            f.append(("BAD", f"filter {x['name']!r} has no condition"))
    for name, n in (("forwarders", len(c["forwarders"])), ("filters", len(c["filters"]))):
        if n >= 9:
            f.append(("WARN", f"{n} of 10 {name}: the limit is ten"))
    v = c["volume"]
    if v["last_24h"]:
        f.append(("INFO", f"last 24 hours: {v['last_24h']:,} events, {1 - v['last_24h_with_appname'] / v['last_24h']:.0%} with no application name"))
    return f


# ── planning ───────────────────────────────────────────────────────────────────────────────────────
def plan(size: str, replicas: int, partitions: int, retention: dict[str, float]) -> list[str]:
    """The shard arithmetic of the 9.1 design page: a day of retention costs one shard per partition on each replica,
    against a fixed budget per replica. The page gives the even case (a medium store with eight partitions holds at
    most 100 days); that partitions with unequal retention share the budget by their sum is this tool's inference from
    the same rule."""
    budget = SHARDS[size]
    lines = [f"size {size}: {budget} shards per replica, {replicas} replica(s), {partitions} partitions counting Audit Records and Default",
             f"evenly, each partition can hold at most {budget // partitions} days ({budget} / {partitions})"]
    if retention:
        used = sum(retention.values())
        rest = partitions - len(retention)
        for name, days in retention.items():
            lines.append(f"  {name}: {days:g} days")
        left = budget - used
        lines.append(f"those {len(retention)} take {used:g} of {budget} shards per replica; "
                     + (f"{left:g} remain for the other {rest} partition(s), about {left // max(rest, 1):g} days each" if left >= 0
                        else f"OVER by {-left:g}: a larger size, or fewer or shorter partitions"))
    lines.append("more replicas add disk, not shard days: each replica holds its portion of every day's index and spends a shard on it")
    lines.append("disk is the second limit: the store removes the oldest events once its disk reaches its threshold, whatever the retention")
    return lines


# ── trial ──────────────────────────────────────────────────────────────────────────────────────────
def scoped(app: str) -> dict:
    assert re.fullmatch(r"pcatrial[0-9a-f]{8}[a-z]", app), app
    return {"bool": {"filter": [{"match_phrase": {"appname": app}}], "must": [], "must_not": [], "should": []}}


def iso_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def send(target: str, lines: list[str]) -> None:
    """Octet-counted RFC 5424 lines over one TLS session (RFC 5425). Refuses a clear-text target."""
    u = urlparse(target)
    if u.scheme.lower() != "ssl" or not u.hostname or not u.port:
        raise SystemExit(f"target {target!r} is not ssl://host:port; refusing to send in clear text")
    ctx = ssl._create_unverified_context()  # the listener's root is private to its proxy; the lines carry nothing secret
    with socket.create_connection((u.hostname, u.port), timeout=15) as raw, ctx.wrap_socket(raw, server_hostname=u.hostname) as tls:
        for m in lines:
            tls.sendall(f"{len(m.encode())} {m}".encode())


def line(nonce: str, app: str, seq: int, extra: str = "") -> str:
    return f"<14>1 {iso_now()} pcatrial-{nonce}.invalid {app} 1 - - pcatrial{nonce} seq={seq} {extra}({SAFE})".replace("  ", " ")


def stored(s: Session, app: str, since: int) -> list[dict]:
    t = now_ms() + 600_000
    body = {"query": {"bool": {"must": [{"match_phrase": {"appname": app}}],
                               "filter": [{"range": {"timestamp": {"gte": since - 600_000, "lte": t}}}]}}, "size": 500}
    hits = ((s.search(body).get("events") or {}).get("hits")) or []
    return [{"text": (h.get("msgContent") or {}).get("originalText") or "", "ingest_ms": int((h.get("msgContent") or {}).get("ingestTimestamp") or 0)} for h in hits]


def found(s: Session, phrase: str, since: int) -> int:
    t = now_ms() + 600_000
    body = {"query": {"bool": {"must": [{"match_phrase": {"text": phrase}}],
                               "filter": [{"range": {"timestamp": {"gte": since - 600_000, "lte": t}}}]}}, "size": 50}
    return len(((s.search(body).get("events") or {}).get("hits")) or [])


def seq_of(text: str) -> int | None:
    m = re.search(r"\bseq=(-?\d+)\b", text)
    return int(m.group(1)) if m else None


def residue(s: Session) -> list[str]:
    left = []
    for path in ("/api/v2/logs/filters", "/api/v2/logs/masks", "/api/v2/logs/partitions", "/api/v2/logs/forwarders"):
        left += [f"{path}: {x.get('name')}" for x in items(get(s, path)) if str(x.get("name", "")).startswith(PREFIX)]
    return left


def drip(target: str, nonce: str, app: str, span: int, step: int, extra=lambda i: "") -> list[dict]:
    sent, t0, i = [], time.time(), 0
    while time.time() < t0 + span:
        x = extra(i)
        send(target, [line(nonce, app, i, x)])
        sent.append({"seq": i, "sent_ms": now_ms()})
        i += 1
        time.sleep(step)
    return sent


def trial(s: Session, a: argparse.Namespace) -> tuple[dict, bool]:
    """One rule, scoped to an application name made for this run, proven on labelled lines and removed."""
    nonce = secrets.token_hex(4)
    app = f"pcatrial{nonce}{a.kind[0]}"
    rec: dict = {"kind": a.kind, "read_at": iso_ms(now_ms()), "version": (get(s, "/api/v2/version") or {}).get("version"), "span_s": a.span, "step_s": a.step}
    if a.kind == "forwarder":
        body = {"name": f"{PREFIX}{nonce}-test", "host": a.host, "port": a.port, "protocol": a.protocol,
                "transportProtocol": a.transport, "sslEnabled": a.tls}
        st, out = s.li("POST", "/api/v2/logs/forwarders/test", body)
        if isinstance(out, dict) and isinstance(out.get("errorDetails"), str) and "CERTIFICATE" in out["errorDetails"]:
            out = {**out, "errorDetails": f"the receiver's certificate, {len(out['errorDetails'])} characters (trust its issuer, or give it one you trust)"}
        rec.update({"destination": f"{a.host}:{a.port}", "protocol": a.protocol, "transport": a.transport, "tls": a.tls, "status": st, "answer": out})
        print(f"connection test to {a.host}:{a.port} {a.protocol}/{a.transport}{' TLS' if a.tls else ''}: HTTP {st} {json.dumps(out)[:300]}")
        return rec, st == 200
    left = residue(s)
    if left:
        raise SystemExit(f"refusing: rules from an earlier trial are still present: {left}")
    since = now_ms()
    if a.kind == "filter":
        path, body = "/api/v2/logs/filters", {"name": f"{PREFIX}{nonce}-filter", "enabled": True, "constraints": scoped(app)}
    elif a.kind == "mask":
        path, body = "/api/v2/logs/masks", {"name": f"{PREFIX}{nonce}-mask", "isEnabled": True, "fieldName": a.field,
                                            "selector": a.selector, "maskValue": a.mask_value, "constraints": scoped(app)}
    else:
        path, body = "/api/v2/logs/partitions", {"name": f"{PREFIX}{nonce}-partition", "enabled": True, "constraints": scoped(app),
                                                 "retentionPeriodSeconds": int(a.retention_days * 86400), "archiveConfig": {"enabled": False}}
    assert body["constraints"] == scoped(app)
    sample = a.sample
    if a.kind == "mask" and not sample:
        sample = "password=pcafake-{hex}"
    before = None
    if a.kind == "mask":  # one line stored before the mask exists: does the mask change what is already stored?
        before = sample.replace("{hex}", secrets.token_hex(6))
        send(a.target, [line(nonce, app, -1, before + " ")])
        time.sleep(5)
    t_create = now_ms()
    st, out = s.li("POST", path, body)
    rid = out.get("id") if isinstance(out, dict) else None
    rec.update({"rule": {k: v for k, v in body.items() if k != "constraints"}, "condition": f"appname = {app} (made for this run)",
                "create_status": st, "created_at": iso_ms(t_create)})
    if not rid:
        rec["create_answer"] = out
        print(f"create refused: HTTP {st} {json.dumps(out)[:300]}")
        return rec, False
    ok = True
    try:
        values: dict[int, str] = {}

        def extra(i: int) -> str:
            if a.kind != "mask":
                return ""
            values[i] = sample.replace("{hex}", secrets.token_hex(6))
            return values[i] + " "

        sent = drip(a.target, nonce, app, a.span, a.step, extra)
        control = f"pcatrial{nonce}c"  # no rule names it: proves the lines reach the store at all
        send(a.target, [line(nonce, control, n) for n in range(3)])
        time.sleep(a.settle)
        rec["control_stored"] = len(stored(s, control, since))
        kept = stored(s, app, since)
        seqs = {seq_of(e["text"]): e for e in kept}
        rec["sent"] = len(sent)
        if a.kind == "filter":
            rec.update({"stored": len([q for q in seqs if q is not None]), "expected": 0})
            ok = rec["stored"] == 0 and rec["control_stored"] > 0
            print(f"filter: {len(sent)} lines sent after the filter was created, {rec['stored']} stored; control lines with no rule: "
                  f"{rec['control_stored']} of 3 stored ({'as the chapter says' if ok else 'NOT as the chapter says: read the record'})")
        elif a.kind == "mask":
            rows = []
            for q in sorted(k for k in seqs if k is not None):
                want = before if q == -1 else values.get(q)
                text = seqs[q]["text"]
                rows.append({"seq": q, "value_still_stored": bool(want and want in text), "mask_value_stored": a.mask_value in text,
                             "ingested_after_create_s": round((seqs[q]["ingest_ms"] - t_create) / 1000, 1)})
            rec["lines"] = rows
            masked = [r for r in rows if r["seq"] >= 0 and r["mask_value_stored"] and not r["value_still_stored"]]
            unmasked = [r for r in rows if r["seq"] >= 0 and r["value_still_stored"]]
            rec["first_masked_after_s"] = masked[0]["ingested_after_create_s"] if masked else None
            rec["last_unmasked_after_s"] = unmasked[-1]["ingested_after_create_s"] if unmasked else None
            rec["search_finds_masked_value"] = found(s, values[max(values)], since) if values else None
            rec["line_before_mask_still_stored_and_found"] = bool(rows and rows[0]["seq"] == -1 and rows[0]["value_still_stored"] and found(s, before, since))
            ok = bool(masked) and rec["search_finds_masked_value"] == 0
            print(f"mask: {len(masked)} of {len([r for r in rows if r['seq'] >= 0])} lines stored masked; first masked line ingested "
                  f"{rec['first_masked_after_s']} s after the mask was created, last unmasked {rec['last_unmasked_after_s']} s; "
                  f"a search for a masked value finds {rec['search_finds_masked_value']}; the line stored before the mask "
                  f"{'still carries its value and is found' if rec['line_before_mask_still_stored_and_found'] else 'is not as expected'}")
        else:
            stat = s.li("GET", f"/api/v2/logs/partitions/status/{rid}")[1] or {}
            rec.update({"partition_events": stat.get("partitionCount"), "order": stat.get("order"),
                        "first_event_after_create_s": round((stat["oldestLogTime"] - t_create) / 1000, 1) if stat.get("oldestLogTime") else None,
                        "plain_search_found": len([q for q in seqs if q is not None])})
            ok = rec["partition_events"] == len(sent)
            print(f"partition: order {rec['order']}, {rec['partition_events']} of {len(sent)} lines in it, the first "
                  f"{rec['first_event_after_create_s']} s after it was created; a search with no partition named found {rec['plain_search_found']}")
    finally:
        rec["delete_status"] = s.li("DELETE", f"{path}/{rid}")[0]
        rec["absent_after"] = s.li("GET", f"{path}/{rid}")[0] == 404
        if a.kind == "partition":
            time.sleep(60)
            rec["found_after_delete"] = len(stored(s, app, since))
            print(f"partition deleted (HTTP {rec['delete_status']}); its lines found a minute later: {rec['found_after_delete']}")
        rec["residue"] = residue(s)
        print(f"rule deleted: HTTP {rec['delete_status']}, read back absent: {rec['absent_after']}, residue: {rec['residue'] or 'none'}")
    return rec, ok and rec["absent_after"] and not rec["residue"]


# ── command line ───────────────────────────────────────────────────────────────────────────────────
def write(out: str | None, name: str, rec: dict, register) -> None:
    if not out:
        return
    sc = Scrubber()
    register(sc)
    Path(out).mkdir(parents=True, exist_ok=True)
    p = Path(out) / name
    sc.write(p, rec)  # refuses to write when a registered estate value survived the scrub
    print("wrote", p)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("census")
    c.add_argument("--size", choices=sorted(SHARDS))
    c.add_argument("--replicas", type=int, default=1)
    c.add_argument("--out")
    p = sub.add_parser("plan")
    p.add_argument("--size", choices=sorted(SHARDS), required=True)
    p.add_argument("--replicas", type=int, default=1)
    p.add_argument("--partitions", type=int, required=True, help="active partitions, counting Audit Records and Default")
    p.add_argument("--retention", action="append", default=[], metavar="NAME=DAYS")
    t = sub.add_parser("trial")
    t.add_argument("kind", choices=["filter", "mask", "partition", "forwarder"])
    t.add_argument("--target", help="ssl://LISTENER:PORT, a syslog listener whose events reach this Log Management")
    t.add_argument("--send", action="store_true", help="create the rule and send the lines; without it, print the plan")
    t.add_argument("--field", default="text")
    t.add_argument("--selector", default=r"(pcafake-[0-9a-f]{12})")
    t.add_argument("--sample", help="the text a line carries for a mask trial; {hex} is replaced by a fresh random value")
    t.add_argument("--mask-value", default="********")
    t.add_argument("--retention-days", type=float, default=1)
    t.add_argument("--span", type=int, default=120, help="seconds to keep sending lines")
    t.add_argument("--step", type=int, default=15, help="seconds between lines")
    t.add_argument("--settle", type=int, default=150, help="seconds to wait before reading the store")
    t.add_argument("--host")
    t.add_argument("--port", type=int)
    t.add_argument("--protocol", default="SYSLOG", choices=["SYSLOG", "RAW"])
    t.add_argument("--transport", default="TCP", choices=["TCP", "UDP"])
    t.add_argument("--tls", action="store_true")
    t.add_argument("--out")
    a = ap.parse_args(argv)

    if a.cmd == "plan":
        ret = {}
        for r in a.retention:
            name, _, days = r.partition("=")
            ret[name] = float(days)
        print("\n".join(plan(a.size, a.replicas, a.partitions, ret)))
        return 0

    if a.cmd == "trial":
        if a.kind == "forwarder" and not (a.host and a.port):
            ap.error("trial forwarder needs --host and --port")
        if a.kind != "forwarder" and not a.target:
            ap.error(f"trial {a.kind} needs --target ssl://LISTENER:PORT")
        if a.kind == "mask" and a.sample and "{hex}" not in a.sample:
            ap.error("--sample must contain {hex}, the value the mask should hide")
        if a.kind != "forwarder" and not a.send:
            print(f"plan: a throwaway {a.kind} whose condition is an application name made for this run, labelled lines every "
                  f"{a.step} s for {a.span} s to {a.target}, the store read after {a.settle} s, then the {a.kind} deleted and read "
                  "back absent. Nothing is created or sent without --send.")
            return 0

    s = Session()
    if a.cmd == "census":
        rec, found_ = census(s, a.size, a.replicas)
        print(f"Log Management {rec['version']}, read {rec['read_at']}")
        for p_ in rec["partitions"]:
            print(f"  partition {p_['order']:>4}  {p_['name']:<24} {p_['condition'][:40]:<40} retention "
                  f"{'none' if not p_['retention_days'] else str(p_['retention_days']) + ' d':<8} archive {'on' if p_['archive'] else 'off':<3} "
                  f"events {p_['events']:>13,}  oldest {p_['oldest_event']}")
        dd = rec["volume"]["depth"]
        print(f"  depth: {dd['full_days']} whole days at full volume from {dd['first_full_day']}, plus today")
        print(f"  external storage {len(rec['external_storage'])}, forwarders {len(rec['forwarders'])}, masks {len(rec['masks'])}, filters {len(rec['filters'])}")
        for level, text in found_:
            print(f"{level:4}  {text}")
        rec["findings"] = [{"level": lv, "finding": tx} for lv, tx in found_]

        def reg(sc):
            for x in rec["forwarders"]:
                sc.add(x["destination"].rsplit(":", 1)[0], "destination")
            for x in rec["external_storage"]:
                sc.add(x["name"], "storage")
        write(a.out, "census.record.json", rec, reg)
        return 1 if any(lv == "BAD" for lv, _ in found_) else 0

    rec, ok = trial(s, a)

    def reg(sc):
        if a.kind == "forwarder":
            sc.add(a.host, "destination")
        elif a.target:
            sc.add(urlparse(a.target).hostname, "listener")
    write(a.out, f"trial-{a.kind}.record.json", rec, reg)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
