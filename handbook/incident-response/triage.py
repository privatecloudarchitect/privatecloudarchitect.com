#!/usr/bin/env python3
"""triage.py: two measurements an incident practice needs about itself.

A method for responding to incidents is easy to write and hard to check. These are the two checks:

  1. WHAT IS ACTUALLY IN THE QUEUE. Every alert instance on the platform, split by whether it is still
     standing, how long it has been standing, what impact badge it carries and how concentrated it is across
     definitions and objects. The question this answers is not "what is broken" but "is this queue made of
     incidents at all". An alert that has been active for two months is a condition; an alert that opened and
     closed within the hour behaved like an event. A practice aimed at the second while the queue is made of
     the first is aimed at nothing;
  2. WHAT THE RECORD KEPT. A scar corpus is the output of an incident practice, so the corpus is where the
     practice can be audited. Point this at a markdown file of recorded failures and it reports, per entry,
     whether the symptom was stated, the root cause named, its layer classified, a fix recorded, evidence
     cited and another entry cross-linked, plus how many entries correct an earlier reading, and whether the
     evidence was an API read or a log.

The second half is deliberately generic: it takes the heading pattern and the label names as arguments, so it
audits whatever record you keep rather than the one this handbook keeps.

Read-only throughout. The alert half issues GETs; the corpus half reads a file.

Run:
  export OPS_HOST=<operations-fqdn>
  export OPS_BROKER_HOST=<identity-broker-fqdn>   # omit if the broker shares the Ops FQDN
  export OPS_REALM=CUSTOMER
  export OPS_API_TOKEN=<api-token>                # minted in the operations console
  export OPS_OWNER="PCA"                          # the owner prefix your content carries
  export OPS_TLS_VERIFY=false                     # only on a self-signed lab CA
  python3 triage.py
  python3 triage.py --corpus /path/to/your/failure-record.md      # adds the second half
  python3 triage.py --corpus record.md --entry '^### (F-\\d+):'    # your own heading shape
"""

import argparse
import collections
import datetime as dt
import json
import os
import re
import statistics
import time

from opslib import bearer, ops

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

# What a well-kept failure record carries, as (label, the question it answers). The audit reports how many
# entries carry each, which is the practice's own funnel.
TRACES = [
    ("symptom", r"\*\*Symptom", "the observation, stated before any cause"),
    ("root cause", r"\*\*Root cause", "the cause, named"),
    ("layer", r"\*\*Root cause\s*\((?:[^)]*\b(?:information contract|structural|processing logic|"
               r"architectur|platform[- ]config)\b[^)]*)\)", "the cause classified to a layer"),
    ("fix", r"\*\*(?:Fix|Discipline|Workaround|Prevention)", "what to do instead"),
    ("evidence", r"\*\*Reference", "where the finding came from"),
    ("cross-link", r"\b[A-Z]-\d+\b", "another entry this one depends on"),
]


def days_since(ms, now):
    return (now - dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc)).days


def profile_queue(tok, owner):
    """Every alert instance, profiled by whether it behaves like an incident."""
    out, n = [], 0
    while True:
        st, body = ops("GET", "/api/alerts", tok, params={"pageSize": 2000, "page": n, "_no_links": "true"})
        items = (body.get("alerts") or []) if isinstance(body, dict) else []
        out += items
        total = ((body.get("pageInfo") or {}).get("totalCount") if isinstance(body, dict) else None)
        n += 1
        if not items or total is None or len(out) >= total or n > 20:
            break
    now = dt.datetime.now(dt.timezone.utc)
    active = [a for a in out if a.get("status") == "ACTIVE"]
    closed = [a for a in out if a.get("status") == "CANCELED"]
    ages = sorted(days_since(a["startTimeUTC"], now) for a in active if a.get("startTimeUTC"))
    durations = sorted(round((a["cancelTimeUTC"] - a["startTimeUTC"]) / 3600000, 2) for a in closed
                       if a.get("cancelTimeUTC") and a.get("startTimeUTC")
                       and a["cancelTimeUTC"] > a["startTimeUTC"])
    by_impact = {}
    for impact in sorted({a.get("alertImpact") for a in active if a.get("alertImpact")}):
        got = sorted(days_since(a["startTimeUTC"], now) for a in active
                     if a.get("alertImpact") == impact and a.get("startTimeUTC"))
        by_impact[impact] = {"active": len(got), "medianAgeDays": got[len(got) // 2] if got else None,
                             "oldestDays": got[-1] if got else None}
    defs = collections.Counter(a.get("alertDefinitionName") for a in active)
    top = defs.most_common(6)
    return {"instances": len(out), "active": len(active), "closed": len(closed),
            "activeFromOwnedDefinitions": sum(1 for a in active
                                              if str(a.get("alertDefinitionName") or "").startswith(owner + " - ")),
            "ageDays": {"min": ages[0] if ages else None,
                        "median": ages[len(ages) // 2] if ages else None,
                        "max": ages[-1] if ages else None,
                        "startedInTheLastWeek": sum(1 for d in ages if d < 7),
                        "standingOverAMonth": sum(1 for d in ages if d >= 31),
                        "standingOverAYear": sum(1 for d in ages if d >= 366)},
            "closedDurationHours": {"median": durations[len(durations) // 2] if durations else None,
                                    "underAnHour": sum(1 for d in durations if d < 1),
                                    "overADay": sum(1 for d in durations if d > 24),
                                    "counted": len(durations)},
            "byImpact": by_impact,
            "byLevel": dict(collections.Counter(a.get("alertLevel") for a in active)),
            "distinctDefinitions": len(defs), "distinctObjects": len({a.get("resourceId") for a in active}),
            "topShare": sum(n for _, n in top),
            "controlStates": dict(collections.Counter(a.get("controlState") for a in active)),
            "suspended": sum(1 for a in active if a.get("suspendUntilTimeUTC"))}


def audit_corpus(path, entry_pattern):
    """How much of the method each recorded failure kept.

    Generic on purpose: the heading pattern is an argument, and the traces are regexes over the entry body,
    so this audits whatever record you keep. It reports a funnel, not a score.
    """
    text = open(path, encoding="utf-8").read()
    parts = re.split(entry_pattern, text, flags=re.M)
    entries = [(parts[i], parts[i + 1]) for i in range(1, len(parts) - 1, 2)]
    if not entries:
        return {"error": f"no entries matched {entry_pattern!r} in {os.path.basename(path)}"}
    counts = collections.Counter()
    layers = collections.Counter()
    for _, body in entries:
        head = body.split("\n", 1)[0]
        for name, pattern, _why in TRACES:
            if re.search(pattern, body, re.I):
                counts[name] += 1
        if re.search(r"(CONFIRMED|VERIFIED|FOUND|PROVEN|MEASURED|RESOLVED)\s+(live|by|on|\d)", head, re.I):
            counts["heading claims verification"] += 1
        if re.search(r"(CORRECTED|corrected|supersedes|was wrong|mis-?diagnos)", body):
            counts["corrects an earlier reading"] += 1
        # The evidence plane the finding came from, approximated by what it quotes.
        if re.search(r"\b(HTTP\s*)?(200|201|204|400|401|403|404|405|409|410|500|502|503)\b", body):
            counts["quotes an HTTP status"] += 1
        if re.search(r"\blog(s|ging| file| search)?\b", body, re.I):
            counts["mentions a log"] += 1
        m = re.search(r"\*\*Root cause\s*\(([^)]{3,80})\)", body, re.I)
        if m:
            t = m.group(1).lower()
            for needle, label in (("information contract", "information contract"),
                                  ("structural", "structural design"),
                                  ("processing logic", "processing logic"),
                                  ("architectur", "architectural"),
                                  ("platform-config", "platform configuration"),
                                  ("platform config", "platform configuration")):
                if needle in t:
                    layers[label] += 1
                    break
            else:
                layers["other wording"] += 1
    return {"file": os.path.basename(path), "entries": len(entries),
            "carrying": {k: v for k, v in counts.items()},
            "layerTags": dict(layers.most_common()),
            "layerTagged": sum(layers.values())}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", help="a markdown file of recorded failures to audit")
    ap.add_argument("--entry", default=r"^### ([A-Z]-\d+):",
                    help="the heading pattern that starts one entry (default: '### G-123:')")
    args = ap.parse_args()
    owner = os.environ.get("OPS_OWNER", "PCA")
    out_dir = os.environ.get("OUT_DIR", ".")
    print("triage.py: what is in the queue, and what the record kept\n")

    queue = profile_queue(bearer(), owner)
    a = queue["ageDays"]
    print(f"  THE QUEUE: {queue['instances']:,} alert instance(s); {queue['active']} still active, "
          f"{queue['closed']} closed")
    print(f"     the active ones are {a['median']} days old at the median, oldest {a['max']}; "
          f"{a['startedInTheLastWeek']} started in the last week and {a['standingOverAMonth']} have stood "
          f"over a month")
    print(f"     they come from {queue['distinctDefinitions']} definition(s) on {queue['distinctObjects']} "
          f"object(s); the six commonest account for {queue['topShare']} of {queue['active']}")
    print(f"     control states {queue['controlStates']}, suspended {queue['suspended']}")
    for impact, v in queue["byImpact"].items():
        print(f"     {impact:<11} {v['active']:>4} active, median age {v['medianAgeDays']:>4} days")
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
            for extra in ("heading claims verification", "corrects an earlier reading",
                          "quotes an HTTP status", "mentions a log"):
                got = corpus["carrying"].get(extra, 0)
                print(f"     {got:>4} of {n} ({round(100 * got / n):>3}%)  {extra}")
            if corpus["layerTagged"]:
                print(f"     layer tags among the {corpus['layerTagged']} that carry one: {corpus['layerTags']}")

    # A run without --corpus must not blank the corpus block a previous run captured. This is G-166 a
    # third time: an optional probe writes a section of a record, and it does not get to delete one. Here
    # it was worse than an empty render, because the chapter's builder reads corpus["carrying"] directly
    # and stopped with a TypeError. Loud is better than silent, and neither is acceptable.
    if corpus is None:
        prior = os.path.join(out_dir, "triage.json")
        if os.path.exists(prior):
            try:
                kept = (json.load(open(prior, encoding="utf-8")) or {}).get("corpus")
            except ValueError:
                kept = None
            if kept:
                corpus = dict(kept)
                corpus.setdefault("capturedBy", "an earlier run with --corpus")
                print("\n  THE RECORD: carrying forward the corpus audit captured earlier; this run did "
                      "not re-audit it and has not erased it")

    payload = {"captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "owner": owner, "queue": queue, "corpus": corpus}
    text = UUID.sub("{{id}}", json.dumps(payload, indent=1, ensure_ascii=False))
    for var in ("OPS_HOST", "OPS_BROKER_HOST"):
        v = os.environ.get(var)
        assert not v or v not in text, f"{var} reached the record"
    # No alert instance names an object in this record: the queue is reported as counts and ages, because
    # which of an estate's machines is currently unhappy is that estate's business.
    assert "resourceId" not in text, "a resource identifier reached the record"
    os.makedirs(out_dir, exist_ok=True)
    open(os.path.join(out_dir, "triage.json"), "w", encoding="utf-8").write(text + "\n")
    print(f"\nwrote triage.json; the queue is reported as counts and ages, and no object is named")


if __name__ == "__main__":
    main()
