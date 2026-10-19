#!/usr/bin/env python3
"""triage.py: what is in the alert queue, which definitions fill it, and what your failure record kept.

A method for responding to incidents is easy to write and hard to check. These are the checks:

  1. WHAT IS ACTUALLY IN THE QUEUE. Every alert instance on the platform, split by whether it is still open,
     how long it has stood, what impact badge it carries and how concentrated it is across definitions and
     objects. The question is not "what is broken" but "is this queue made of incidents at all": an alert open
     for two months is a condition, one that opened and closed within the hour behaved like an event;
  2. WHICH DEFINITIONS FILL IT (--rank). The open alerts counted by the definition that raised them, commonest
     first, with each one's impact badge and median age: the first rows of a routing table;
  3. WHAT THE RECORD KEPT (--corpus). Point it at a markdown file of recorded failures and it reports, per entry,
     whether the symptom was stated, the root cause named, its layer classified, a fix recorded, evidence cited
     and another entry cross-linked. `failure-record.template.md` beside this script is a record entry that
     carries every one of those, in the words the audit looks for.

Every alert is read, page by page, to the list's declared total: the list answers newest first, so a single page
holds the newest alerts and none of the oldest, which are the ones the queue profile exists to find. A read that is
refused or comes back short stops the run (exit 4). Read-only throughout: GETs on the alert list, and a file read.

Run:
  export OPS_HOST=<operations-fqdn>
  export OPS_BROKER_HOST=<identity-broker-fqdn>   # omit if the broker shares the Ops FQDN
  export OPS_API_TOKEN_FILE=<api-token file>      # mode 0600 (or OPS_API_TOKEN, the value itself)
  export OPS_OWNER="PCA"                          # the owner prefix your own alert definitions carry
  export OPS_TLS_VERIFY=false                     # only on a self-signed lab CA
  python3 triage.py --standing       # the thirty-second read: what has been open longest, oldest first
  python3 triage.py                  # the queue profile; writes triage.json
  python3 triage.py --rank           # the definitions that fill the queue, commonest first
  python3 triage.py --corpus /path/to/your/failure-record.md      # adds the record audit
  python3 triage.py --corpus record.md --entry '^### (F-\\d+):'    # your own heading shape

Exit: 0 the read completed - 4 a read was refused or came back short
"""

import argparse
import collections
import datetime as dt
import json
import os
import re
import statistics
import sys
import time

from opslib import bearer, ops

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
PAGE = 1000
OPEN_STATUSES = ("NEW", "ACTIVE", "UPDATED")   # every status but CANCELED is a condition still open

# What a well-kept failure record carries, as (label, pattern, the question it answers). The audit reports how many
# entries carry each, which is the practice's own funnel. failure-record.template.md carries every one.
TRACES = [
    ("symptom", r"\*\*Symptom", "the observation, stated before any cause"),
    ("root cause", r"\*\*Root cause", "the cause, named"),
    ("layer", r"\*\*Root cause\s*\((?:[^)]*\b(?:information contract|structural|processing logic|"
               r"architectur|platform[- ]config|infrastructure)\b[^)]*)\)", "the cause classified to a layer"),
    ("fix", r"\*\*(?:Fix|Discipline|Workaround|Prevention)", "what to do instead"),
    ("evidence", r"\*\*(?:Reference|Evidence)", "where the finding came from"),
    ("cross-link", r"\b[A-Z]-\d+\b", "another entry this one depends on"),
]
LAYERS = (("information contract", "information contract"), ("structural", "structural design"),
          ("processing logic", "processing logic"), ("architectur", "architectural"),
          ("platform-config", "platform configuration"), ("platform config", "platform configuration"),
          ("infrastructure", "infrastructure"))


def stop(msg):
    print(f"FATAL: {msg}; nothing is reported, because a partial queue reads as a smaller, younger one")
    sys.exit(4)


def days_since(ms, now):
    return (now - dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc)).days


def median(values):
    return statistics.median_low(values) if values else None


def all_alerts(tok):
    """Every alert instance, page by page, to the list's declared total; exit 4 on a refusal or a short read."""
    out, page = [], 0
    while True:
        st, body = ops("GET", "/api/alerts", tok, params={"pageSize": PAGE, "page": page, "_no_links": "true"})
        if st != 200 or not isinstance(body, dict):
            stop(f"the alert list answered HTTP {st}")
        items = body.get("alerts") or []
        out += items
        total = (body.get("pageInfo") or {}).get("totalCount")
        if total is None:
            stop("the alert list declared no total")
        if len(out) >= total or not items:
            break
        page += 1
    if len(out) != total:
        stop(f"the alert list read {len(out)} of the {total} it declared")
    return out


def open_alerts(alerts):
    return [a for a in alerts if a.get("status") in OPEN_STATUSES and a.get("startTimeUTC")]


def standing_alerts(alerts, top=10):
    """The thirty-second question: how much of what is paging you has been open for weeks?

    An alert that opened forty days ago and that nobody has taken is not an incident, whatever its criticality
    says; it is a monitoring decision somebody made once and never revisited. Age and control state answer that
    before any diagnosis starts. Sorting oldest first puts the alerts that are NOT incidents at the top, which is
    the opposite of what a console does.
    """
    now = dt.datetime.now(dt.timezone.utc)
    rows = sorted(({"ageDays": days_since(a["startTimeUTC"], now), "controlState": a.get("controlState"),
                    "criticality": a.get("alertLevel"), "impact": a.get("alertImpact")} for a in open_alerts(alerts)),
                  key=lambda r: -r["ageDays"])
    return {"open": len(rows), "notTaken": sum(1 for r in rows if r["controlState"] == "OPEN"), "oldest": rows[:top]}


def profile_queue(alerts, owner):
    """Every alert instance, profiled by whether it behaves like an incident."""
    now = dt.datetime.now(dt.timezone.utc)
    live = open_alerts(alerts)
    closed = [a for a in alerts if a.get("status") == "CANCELED"]
    ages = sorted(days_since(a["startTimeUTC"], now) for a in live)
    durations = sorted(round((a["cancelTimeUTC"] - a["startTimeUTC"]) / 3600000, 2) for a in closed
                       if a.get("cancelTimeUTC") and a.get("startTimeUTC") and a["cancelTimeUTC"] > a["startTimeUTC"])
    by_impact = {}
    for impact in sorted({a.get("alertImpact") for a in live if a.get("alertImpact")}):
        got = sorted(days_since(a["startTimeUTC"], now) for a in live if a.get("alertImpact") == impact)
        by_impact[impact] = {"open": len(got), "medianAgeDays": median(got), "oldestDays": got[-1] if got else None}
    defs = collections.Counter(a.get("alertDefinitionName") for a in live)
    return {"instances": len(alerts), "open": len(live), "closed": len(closed),
            "byStatus": dict(collections.Counter(a.get("status") for a in alerts)),
            "openFromOwnedDefinitions": sum(1 for a in live
                                            if str(a.get("alertDefinitionName") or "").startswith(owner + " - ")),
            "ageDays": {"min": ages[0] if ages else None, "median": median(ages), "max": ages[-1] if ages else None,
                        "startedInTheLastWeek": sum(1 for d in ages if d < 7),
                        "standingOverAMonth": sum(1 for d in ages if d >= 31),
                        "standingOverAYear": sum(1 for d in ages if d >= 366)},
            "closedDurationHours": {"median": median(durations), "underAnHour": sum(1 for d in durations if d < 1),
                                    "overADay": sum(1 for d in durations if d > 24), "counted": len(durations)},
            "byImpact": by_impact,
            "byLevel": dict(collections.Counter(a.get("alertLevel") for a in live)),
            "distinctDefinitions": len(defs), "distinctObjects": len({a.get("resourceId") for a in live}),
            "topSixShare": sum(n for _, n in defs.most_common(6)),
            "controlStates": dict(collections.Counter(a.get("controlState") for a in live)),
            "suspended": sum(1 for a in live if a.get("suspendUntilTimeUTC"))}


def rank_definitions(alerts, owner, top=10):
    """The open alerts by the definition that raised them, commonest first: the first rows of a routing table, each
    with its impact badge and median age. A definition your own content defines is shown by its owner prefix only in
    the record, since its name is yours."""
    now = dt.datetime.now(dt.timezone.utc)
    by_def = collections.defaultdict(list)
    for a in open_alerts(alerts):
        by_def[a.get("alertDefinitionName") or "(unnamed)"].append(a)
    rows = []
    for name, items in sorted(by_def.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:top]:
        ages = sorted(days_since(a["startTimeUTC"], now) for a in items)
        rows.append({"definition": name, "open": len(items),
                     "impact": collections.Counter(a.get("alertImpact") for a in items).most_common(1)[0][0],
                     "objects": len({a.get("resourceId") for a in items}), "medianAgeDays": median(ages),
                     "owned": name.startswith(owner + " - ")})
    return rows


def audit_corpus(path, entry_pattern):
    """How much of the method each recorded failure kept. Generic on purpose: the heading pattern is an argument, and
    the traces are patterns over the entry body, so this audits whatever record you keep. A funnel, not a score."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    parts = re.split(entry_pattern, text, flags=re.M)
    entries = [(parts[i], parts[i + 1]) for i in range(1, len(parts) - 1, 2)]
    if not entries:
        return {"error": f"no entries matched {entry_pattern!r} in {os.path.basename(path)}"}
    counts, layers = collections.Counter(), collections.Counter()
    for _, body in entries:
        for name, pattern, _why in TRACES:
            if re.search(pattern, body, re.I):
                counts[name] += 1
        if re.search(r"(CORRECTED|corrected|supersedes|was wrong|mis-?diagnos)", body):
            counts["corrects an earlier reading"] += 1
        if re.search(r"\b(HTTP\s*)?(200|201|204|400|401|403|404|405|409|410|500|502|503)\b", body):
            counts["quotes an HTTP status"] += 1
        if re.search(r"\blog(s|ging| file| search)?\b", body, re.I):
            counts["mentions a log"] += 1
        m = re.search(r"\*\*Root cause\s*\(([^)]{3,80})\)", body, re.I)
        if m:
            t = m.group(1).lower()
            for needle, label in LAYERS:
                if needle in t:
                    layers[label] += 1
                    break
            else:
                layers["other wording"] += 1
    return {"file": os.path.basename(path), "entries": len(entries), "carrying": dict(counts),
            "layerTags": dict(layers.most_common()), "layerTagged": sum(layers.values())}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0], allow_abbrev=False)
    ap.add_argument("--standing", action="store_true", help="print the open queue oldest first and stop")
    ap.add_argument("--rank", action="store_true", help="print the definitions that fill the queue and stop")
    ap.add_argument("--corpus", help="a markdown file of recorded failures to audit")
    ap.add_argument("--entry", default=r"^### ([A-Z]-\d+):",
                    help="the heading pattern that starts one entry (default: '### G-123:')")
    args = ap.parse_args()
    owner = os.environ.get("OPS_OWNER", "PCA")
    out_dir = os.environ.get("OUT_DIR", os.path.dirname(os.path.abspath(__file__)))

    if args.standing or args.rank:
        alerts = all_alerts(bearer())
        if args.standing:
            r = standing_alerts(alerts)
            print(f"{r['open']} open alert(s) of {len(alerts):,} read; {r['notTaken']} of them OPEN, which nobody "
                  f"has assigned, suspended or suppressed. Oldest first:\n")
            for row in r["oldest"]:
                print(f"  {row['ageDays']:>5} days  {str(row['controlState'] or '-'):<10} {str(row['impact'] or '-'):<11}"
                      f" {row['criticality'] or ''}")
            print("\nAnything at the top of that list has been standing, not happening. It is a monitoring decision "
                  "somebody made once, and it is not the thing to diagnose.")
        if args.rank:
            print(f"\nThe definitions that fill the open queue, commonest first:\n")
            for row in rank_definitions(alerts, owner):
                print(f"  {row['open']:>4} open on {row['objects']:>3} object(s)  {str(row['impact']):<11} median "
                      f"{row['medianAgeDays']:>4} days  {row['definition']}")
            print("\nEach row is a routing-table row to write: the symptom, the owner who gets it, and the first read.")
        return

    print("triage.py: what is in the queue, and what the record kept\n")
    alerts = all_alerts(bearer())
    queue = profile_queue(alerts, owner)
    ranked = rank_definitions(alerts, owner)
    a = queue["ageDays"]
    print(f"  THE QUEUE: {queue['instances']:,} alert instance(s), read whole; {queue['open']} open, "
          f"{queue['closed']} closed (by status {queue['byStatus']})")
    print(f"     the open ones are {a['median']} days old at the median, oldest {a['max']}; "
          f"{a['startedInTheLastWeek']} started in the last week and {a['standingOverAMonth']} have stood over a month")
    print(f"     they come from {queue['distinctDefinitions']} definition(s) on {queue['distinctObjects']} object(s); "
          f"the six commonest account for {queue['topSixShare']} of {queue['open']}")
    print(f"     control states {queue['controlStates']}, suspended {queue['suspended']}")
    for impact, v in queue["byImpact"].items():
        print(f"     {impact:<11} {v['open']:>4} open, median age {v['medianAgeDays']:>4} days, oldest {v['oldestDays']}")
    cd = queue["closedDurationHours"]
    print(f"     the {cd['counted']} closed ones lasted {cd['median']} hours at the median; "
          f"{cd['underAnHour']} under an hour, {cd['overADay']} over a day")

    corpus = None
    if args.corpus:
        corpus = audit_corpus(args.corpus, args.entry)
        if "error" in corpus:
            print(f"\n  THE RECORD: {corpus['error']}")
        else:
            n = corpus["entries"]
            print(f"\n  THE RECORD: {n} recorded failure(s) in {corpus['file']}")
            for name, _pattern, why in TRACES:
                got = corpus["carrying"].get(name, 0)
                print(f"     {got:>4} of {n} ({round(100 * got / n):>3}%)  {name:<12} {why}")
            for extra in ("corrects an earlier reading", "quotes an HTTP status", "mentions a log"):
                got = corpus["carrying"].get(extra, 0)
                print(f"     {got:>4} of {n} ({round(100 * got / n):>3}%)  {extra}")
            if corpus["layerTagged"]:
                print(f"     layer tags among the {corpus['layerTagged']} that carry one: {corpus['layerTags']}")

    # A run without --corpus does not blank the corpus block a previous run captured (G-166): an optional probe
    # writes a section of a record, and it does not get to delete one.
    if corpus is None:
        prior = os.path.join(out_dir, "triage.json")
        if os.path.exists(prior):
            try:
                with open(prior, encoding="utf-8") as fh:
                    kept = (json.load(fh) or {}).get("corpus")
            except ValueError:
                kept = None
            if kept:
                corpus = dict(kept)
                corpus.setdefault("capturedBy", "an earlier run with --corpus")
                print("\n  THE RECORD: carrying forward the corpus audit captured earlier; this run did not re-audit it")

    record_rank = [dict(r, definition=(owner + " - <your definition>") if r["owned"] else r["definition"])
                   for r in ranked]
    payload = {"captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "owner": owner,
               "queue": queue, "rank": record_rank, "corpus": corpus}
    text = UUID.sub("{{id}}", json.dumps(payload, indent=1, ensure_ascii=False))
    for var in ("OPS_HOST", "OPS_BROKER_HOST"):
        v = os.environ.get(var)
        assert not v or v not in text, f"{var} reached the record"
    # The queue is reported as counts, ages and product definition names: which of an estate's machines is unhappy
    # is that estate's business, so no object is named.
    assert "resourceId" not in text, "a resource identifier reached the record"
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "triage.json"), "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    print("\nwrote triage.json; the queue is reported as counts, ages and definitions, and no object is named")


if __name__ == "__main__":
    main()
