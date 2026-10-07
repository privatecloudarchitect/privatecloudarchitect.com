#!/usr/bin/env python3
"""events.py: read your own organization's event surface, what a lifecycle operation fired, and whether
your subscriptions can actually dispatch.

Read-only. It creates no subscription, deploys nothing, and changes nothing. Five answers:

  --topics          which event topics your organization publishes, and which of them are blockable
  --recent          the lifecycle events the broker has recorded, grouped by the request that caused them
  --subscriptions   every subscription in the organization, each checked for the quiet failures below
  --workflow ID     whether the dispatch plane resolves one workflow id, before you bind anything to it
  --record          the topics and the correlation count, written as JSON

Why this exists: four different mistakes produce a subscription that is accepted, enabled and silent, and none
of them returns an error. A topic your organization does not publish is accepted and never fires. A binding
written without its type keeps neither runnable field. A subscriber that names the workflow instead of the
identity subscribing is stored and dispatches nothing. And a workflow id the Automation host cannot resolve is
stored too, even though the Orchestrator itself answers for it, because the Automation host is what dispatches.
--subscriptions checks every subscription for all four; --workflow checks the last one before you bind.

Exit codes: 0 when everything checked is sound; 2 when --subscriptions or --workflow finds a subscription or
workflow an event cannot reach, so a scheduler can raise the alarm.

Usage:
    export VCFA_HOST=automation.example.net
    export VCFA_TOKEN=<a tenant bearer>
    python events.py --topics
"""
from __future__ import annotations
import argparse, json, os, sys
from collections import Counter, defaultdict
from urllib import error as _er, parse as _up, request as _rq
import ssl

HOST = os.environ.get("VCFA_HOST", "")
TOKEN = os.environ.get("VCFA_TOKEN", "")
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE          # lab appliances commonly carry a private CA


def call(path: str):
    """GET that returns (status, body) rather than raising, for reads whose 404 is the answer."""
    if not HOST or not TOKEN:
        sys.exit("set VCFA_HOST and VCFA_TOKEN first")
    req = _rq.Request(f"https://{HOST}{path}", headers={
        "Authorization": f"Bearer {TOKEN}", "Accept": "application/json"})
    try:
        with _rq.urlopen(req, context=CTX, timeout=60) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw else None)
    except _er.HTTPError as e:
        return e.code, None


def get(path: str):
    st, body = call(path)
    if st != 200:
        sys.exit(f"GET {path.split('?')[0]} answered {st}")
    return body


def paged(path: str) -> list[dict]:
    """Every element of a paged collection, read to the total it declares."""
    out, page = [], 0
    sep = "&" if "?" in path else "?"
    while True:
        j = get(f"{path}{sep}page={page}&size=200")
        out += j.get("content", [])
        if j.get("last", True) or not j.get("content"):
            break
        page += 1
    total = j.get("totalElements")
    if total is not None and len(out) != total:
        sys.exit(f"read {len(out)} of a declared {total} from {path}; refusing to report on a partial list")
    return out


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


def workflow_resolves(workflow_id: str) -> tuple[int, str]:
    """Ask the Automation host, which dispatches, not the Orchestrator, which only stores. A workflow can answer
    on the Orchestrator and still be unknown to the host that has to reach it."""
    st, body = call("/vro/workflows/" + _up.quote(str(workflow_id), safe=""))
    return st, ((body or {}).get("name") or "") if st == 200 else ""


def cannot_hold(sub: dict, published: dict[str, bool]) -> str:
    """A blocking subscription on a topic that can be watched and not gated: it runs, and holds nothing."""
    topic = sub.get("eventTopicId")
    if sub.get("blocking") and topic in published and not published[topic]:
        return "it is marked blocking on a topic that cannot hold an operation, so it watches and gates nothing"
    return ""


def problems(sub: dict, published: dict[str, bool]) -> list[str]:
    """The reasons an event cannot reach this subscription's workflow. Empty means none was found."""
    out = []
    topic = sub.get("eventTopicId")
    if topic not in published:
        out.append("its topic is not published in this organization, so it never fires")
    if sub.get("type") != "RUNNABLE" or not sub.get("runnableType") or not sub.get("runnableId"):
        out.append("no runnable is bound, so it dispatches nothing")
    elif sub.get("runnableType") == "extensibility.vro":
        st, _name = workflow_resolves(sub["runnableId"])
        if st != 200:
            out.append(f"its workflow does not resolve through the Automation host (HTTP {st}), so no event reaches it")
    sid = str(sub.get("subscriberId") or "")
    if not sid:
        out.append("it names no subscriber identity")
    elif sid.startswith("extensibility."):
        out.append("its subscriber names the workflow rather than the identity subscribing, so it dispatches nothing")
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


def show_subscriptions() -> int:
    published = {t["id"]: bool(t.get("blockable")) for t in topics()}
    subs = paged("/event-broker/api/subscriptions")
    bad = held = 0
    print(f"{len(subs)} subscription{'' if len(subs) == 1 else 's'}\n")
    for s in sorted(subs, key=lambda x: str(x.get("name"))):
        found, hold = problems(s, published), cannot_hold(s, published)
        bad += bool(found)
        held += bool(hold and not found)
        state = "disabled" if s.get("disabled") else ("blocking" if s.get("blocking") else "watching")
        verdict = "CANNOT DISPATCH" if found else ("CANNOT HOLD" if hold else "ok")
        print(f"  {verdict:15s} {str(s.get('name'))[:40]:40s} {str(s.get('eventTopicId')):34s} {state}")
        for f in found + ([hold] if hold and not found else []):
            print(f"        - {f}")
    print(f"\n  {bad} of {len(subs)} cannot dispatch, {held} cannot hold the operation they block"
          + ("" if not (bad or held) else "; the platform reports none of them as an error"))
    return 2 if (bad or held) else 0


def show_workflow(workflow_id: str) -> int:
    st, name = workflow_resolves(workflow_id)
    if st == 200:
        print(f"resolves through the Automation host: {name}")
        return 0
    print(f"does not resolve through the Automation host (HTTP {st}), so no event can reach it: bind nothing to "
          "this id. Take the id from GET /vro/workflows on the Automation host.")
    return 2


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
    ap.add_argument("--subscriptions", action="store_true")
    ap.add_argument("--workflow", metavar="ID")
    ap.add_argument("--record", action="store_true")
    a = ap.parse_args()
    if a.topics: show_topics()
    elif a.recent: show_recent()
    elif a.subscriptions: sys.exit(show_subscriptions())
    elif a.workflow: sys.exit(show_workflow(a.workflow))
    elif a.record: show_record()
    else: ap.print_help()
