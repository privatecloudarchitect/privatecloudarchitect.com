#!/usr/bin/env python3
"""events.py: read your own organization's event surface, and what a lifecycle operation fired.

Read-only. It creates no subscription, deploys nothing, and changes nothing. Three answers:

  --topics     which event topics your organization publishes, and which of them are blockable
  --recent     the lifecycle events the broker has recorded, grouped by the request that caused them
  --record     both, written as JSON in the shape the handbook chapter renders

Why this exists: the topic catalogue differs by organization type, and a subscription to a topic your
organization does not publish does not fail, it simply never fires. Read the list against the
organization you are actually gating before you write the subscription.

Usage:
    export VCFA_HOST=automation.example.net
    export VCFA_TOKEN=<a tenant bearer>
    python events.py --topics
"""
from __future__ import annotations
import argparse, json, os, sys
from collections import Counter, defaultdict
from urllib import request as _rq
import ssl

HOST = os.environ.get("VCFA_HOST", "")
TOKEN = os.environ.get("VCFA_TOKEN", "")
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE          # lab appliances commonly carry a private CA


def get(path: str):
    if not HOST or not TOKEN:
        sys.exit("set VCFA_HOST and VCFA_TOKEN first")
    req = _rq.Request(f"https://{HOST}{path}", headers={
        "Authorization": f"Bearer {TOKEN}", "Accept": "application/json"})
    with _rq.urlopen(req, context=CTX, timeout=60) as r:
        return json.loads(r.read().decode())


def topics() -> list[dict]:
    return get("/event-broker/api/topics?size=500").get("content", [])


def events() -> list[dict]:
    out, page = [], 0
    while page < 10:
        j = get(f"/event-broker/api/events?page={page}&size=200")
        out += j.get("content", [])
        if len(out) >= j.get("totalElements", 0) or not j.get("content"):
            break
        page += 1
    return out


def show_topics() -> None:
    ts = topics()
    block = [t for t in ts if t.get("blockable")]
    print(f"{len(ts)} topics, {len(block)} blockable\n")
    for t in sorted(ts, key=lambda x: x["id"]):
        print(f"  {'blockable' if t.get('blockable') else '    -    '}  {t['id']:38s} {t.get('name')}")
    legacy = [t for t in ts if t["id"].startswith("compute.")]
    print(f"\n  compute.* family present: {bool(legacy)}"
          + ("" if legacy else "   <- a classic IaaS topic name will never fire here"))


def show_recent() -> None:
    ev = events()
    by = defaultdict(list)
    for e in ev:
        by[e.get("correlationId")].append(e)
    print(f"{len(ev)} events in {len(by)} correlations\n")
    for cid, evs in sorted(by.items(), key=lambda kv: min(str(x.get('timeStamp')) for x in kv[1]))[-8:]:
        evs.sort(key=lambda x: str(x.get("timeStamp")))
        c = Counter(x["eventTopicId"] for x in evs)
        first = str(evs[0].get("timeStamp"))[:19]
        print(f"  {first}  correlation {str(cid)[:36]}  ({len(evs)} events)")
        for k, n in sorted(c.items()):
            print(f"        {k:38s} x{n}")


def show_record() -> None:
    ts = topics()
    print(json.dumps({
        "topics": {"total": len(ts),
                   "blockable": sorted(t["id"] for t in ts if t.get("blockable")),
                   "computeFamilyPresent": any(t["id"].startswith("compute.") for t in ts)},
        "correlations": len({e.get("correlationId") for e in events()}),
    }, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--topics", action="store_true")
    ap.add_argument("--recent", action="store_true")
    ap.add_argument("--record", action="store_true")
    a = ap.parse_args()
    if a.topics: show_topics()
    elif a.recent: show_recent()
    elif a.record: show_record()
    else: ap.print_help()
