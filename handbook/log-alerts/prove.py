#!/usr/bin/env python3
"""prove.py: prove each host-record alert of a bundle with labelled lines, on one host you choose.

A new log alert counts the stored lines whose own timestamp is inside its window, so history can prove it only for an
event that happened in the last window, and most estates have never had a device loss at all. A line in the host's own
record format can: Log Management files it as it files the host's records, and the line's HOSTNAME decides which host it
belongs to, so the alert raises on that host.

For every host-record symptom of the bundle (an `appname` and a `text` condition) that carries a `prove` sample, it
builds the line that host writes (RFC 5424, the application's facility, ESX's structured data), adds a label
(`pcalmtest<nonce>`, "labelled test line, safe to ignore"), repeats it one more time than the symptom's threshold,
and sends the lines over TLS to the syslog target you name, which should be the one the host itself uses. Then it
reads, minute by minute, which of the bundle's alerts raised on that host.

Without --send it prints the lines and sends nothing. With --send it refuses to run while an enabled notification
rule selects neither alert definitions nor resources, because the alerts it raises would be sent wherever that rule
points. What it leaves: the lines stay in Log Management until retention removes them, and each alert cancels itself
after its window and the bundle's auto-cancel time. vCenter-event symptoms cannot be fed by a syslog line; they wait
for the first real event.

  python3 prove.py --scope scope.json --host <esx fqdn> --target ssl://<listener>:<port> [--only SP-02,SP-08]
  python3 prove.py --scope scope.json --host <esx fqdn> --target ssl://<listener>:<port> --send [--minutes 15] [--out DIR]
  python3 prove.py ... --send --backdate 10      # the lines carry a timestamp ten minutes old
  python3 prove.py ... --send --until-clear --minutes 30   # keep reading until every raised alert has cleared

It also reads the lines back from Log Management by their label and reports when they were indexed, so each alert's
delay splits into the line reaching the store and the store raising the alert. A monitor counts the lines whose own
timestamp falls inside the trigger's window, so `--backdate` longer than the window shows what a late line does: one
held in a buffer through an outage, or written by a host whose clock is behind.

The environment is lmlib.py's. Standard library only.
"""

from __future__ import annotations

import json
import secrets
import socket
import ssl
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from deploy import BUNDLE, definition_name, load  # noqa: E402

# PRI = facility * 8 + severity (RFC 5424). ESX sends vobd as daemon.info and vmkernel as local6.info.
PRI = {"vobd": 3 * 8 + 6, "vmkernel": 22 * 8 + 6}


def line(hostname: str, sample: dict, label: str, when: str) -> str:
    """One RFC 5424 message in the form an ESX 9.1.1 host writes it, with the label appended to the message."""
    pri = PRI.get(sample["app"], 1 * 8 + 6)
    return (f"<{pri}>1 {when} {hostname} {sample['app']} {sample['procid']} - {sample['sd']} "
            f"{sample['message']} ({label}, labelled test line, safe to ignore)")


def send(target: str, messages: list[str]) -> None:
    """Octet-counted frames (RFC 5425: MSG-LEN SP SYSLOG-MSG) over one TLS session. Refuses a clear-text target."""
    u = urlparse(target)
    if u.scheme.lower() != "ssl" or not u.hostname:
        raise SystemExit(f"target {target!r} is not ssl://host:port; refusing to send in clear text")
    # The listener presents a certificate from the proxy's own root, which this workstation does not hold; the
    # lines carry nothing secret, so the session is encrypted without verifying the listener.
    ctx = ssl._create_unverified_context()
    with socket.create_connection((u.hostname, u.port or 6514), timeout=15) as raw, \
            ctx.wrap_socket(raw, server_hostname=u.hostname) as tls:
        for m in messages:
            tls.sendall(f"{len(m.encode())} {m}".encode())


def plan(b: dict, only: set[str] | None) -> tuple[dict[str, list[str]], list[dict]]:
    """Which alerts each host-record line can raise, and the lines to send: one per distinct sample, repeated one
    more time than the highest threshold among the symptoms that share it (a warning above 4 and a critical above 10
    on the same record need eleven, not sixteen)."""
    keyed = {s["key"]: s for s in b["symptoms"]}
    by_alert: dict[str, list[str]] = {}
    lines: dict[tuple[str, str], dict] = {}
    for a in b["alerts"]:
        if only and a["id"] not in only:
            continue
        refs = a.get("anyOf") or [k for g in a.get("allOf") or [] for k in g]
        provable = [k for k in refs if keyed[k].get("prove")]
        if not provable:
            continue
        by_alert[a["id"]] = provable
        for k in provable:
            sample = keyed[k]["prove"]
            row = lines.setdefault((sample["app"], sample["message"]), {"sample": sample, "copies": 0, "keys": []})
            row["copies"] = max(row["copies"], int(keyed[k]["trigger"]["value"]) + 1)
            row["keys"].append(k)
    return by_alert, list(lines.values())


def indexed_after(s, label: str, sent: float) -> dict:
    """The lines found in Log Management by their label, and how long after sending the first one was ingested."""
    end = int(time.time() * 1000)
    ev = s.search({"query": {"bool": {"must": [{"match_phrase": {"text": label}}],
                                      "filter": [{"range": {"timestamp": {"gte": end - 6 * 3600000, "lte": end + 600000}}}]}},
                   "size": 200}).get("events") or {}
    ingest = sorted(int((h.get("msgContent") or {}).get("ingestTimestamp") or 0) for h in ev.get("hits") or [])
    return {"copies": len(ingest), "seconds_after_send": round(ingest[0] / 1000 - sent, 1) if ingest else None}


def parse_args(argv: list[str]) -> dict:
    a = {"scope": None, "bundle": BUNDLE, "host": None, "target": None, "send": False, "only": None, "minutes": 15, "out": None,
         "backdate": 0, "until_clear": False}
    rest = list(argv)
    while rest:
        x = rest.pop(0)
        if x in ("--scope", "--bundle", "--out") and rest:
            a[x[2:]] = Path(rest.pop(0))
        elif x in ("--host", "--target") and rest:
            a[x[2:]] = rest.pop(0)
        elif x == "--only" and rest:
            a["only"] = {i.strip() for i in rest.pop(0).split(",") if i.strip()}
        elif x in ("--minutes", "--backdate") and rest and rest[0].isdigit():
            a[x[2:]] = int(rest.pop(0))
        elif x == "--send":
            a["send"] = True
        elif x == "--until-clear":
            a["until_clear"] = True
        else:
            raise SystemExit(f"unknown argument {x!r}")
    if not (a["scope"] and a["host"] and a["target"]):
        raise SystemExit("--scope, --host and --target are required")
    return a


def main(argv: list[str]) -> int:
    a = parse_args(argv)
    b, scope = load(a["bundle"]), json.loads(a["scope"].read_text(encoding="utf-8"))
    label = f"pcalmtest{secrets.token_hex(4)}"
    by_alert, lines = plan(b, a["only"])
    when = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    for r in lines:
        print(f"x{r['copies']:<3} {line(a['host'], r['sample'], label, when)[:170]}")
    print("can raise:", {aid: len(keys) for aid, keys in by_alert.items()})
    if not a["send"]:
        print("preview only; rerun with --send")
        return 0
    from lmlib import Scrubber, Session, catch_all_rules

    s = Session()
    blocking = catch_all_rules(s)
    if blocking:
        raise SystemExit(f"refusing: enabled notification rules select every alert: {blocking}")
    hosts = s.paged("/api/resources", "resourceList", {"resourceKind": b["kind"]["resourceKind"], "name": a["host"]})
    host_id = next((h["identifier"] for h in hosts if h["resourceKey"]["name"] == a["host"]), None)
    if host_id is None:
        raise SystemExit(f"VCF Operations has no {b['kind']['resourceKind']} named {a['host']!r}")
    index = {x["name"]: x["id"] for x in s.paged("/api/alertdefinitions", "alertDefinitions",
                                                {"adapterKind": b["kind"]["adapterKind"], "resourceKind": b["kind"]["resourceKind"]})}
    ids = {x["id"]: index.get(definition_name(b, scope["owner"], x["condition"])) for x in b["alerts"]}
    missing = sorted(k for k, v in ids.items() if not v)
    if missing:
        print(f"not deployed, so cannot raise: {missing}")
    sent = time.time()
    when = datetime.fromtimestamp(sent - a["backdate"] * 60, UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    send(a["target"], [line(a["host"], r["sample"], label, when) for r in lines for _ in range(r["copies"])])
    print(f"sent {sum(r['copies'] for r in lines)} lines naming {a['host']} at {when}, label {label}")
    first: dict[str, int] = {}
    last: dict[str, dict] = {}
    gone: dict[str, int] = {}
    while time.time() - sent < a["minutes"] * 60:
        time.sleep(60)
        for aid, def_id in sorted(ids.items()):
            if not def_id:
                continue
            q = s.must("POST", "/api/alerts/query", {"alertDefinitionId": [def_id], "activeOnly": False},
                       params={"page": 0, "pageSize": 100}) or {}
            mine = [x for x in q.get("alerts") or []
                    if x.get("resourceId") == host_id and int(x.get("startTimeUTC") or 0) >= int(sent * 1000) - 60000]
            if mine:
                first.setdefault(aid, min(int(x["startTimeUTC"]) for x in mine))
                last[aid] = {"status": mine[0].get("status"), "level": mine[0].get("alertLevel")}
                ends = [int(x["cancelTimeUTC"]) for x in mine if x.get("cancelTimeUTC")]
                if ends and len(ends) == len(mine):
                    gone.setdefault(aid, max(ends))
        print(datetime.now(UTC).strftime("%H:%M:%SZ"), "raised:", sorted(first), "cleared:", sorted(gone))
        if a["until_clear"] and first and set(gone) >= set(first) and set(first) >= set(by_alert):
            break
    raised = {aid: {"seconds_after_send": round(first[aid] / 1000 - sent), **last[aid],
                    **({"cleared_seconds_after_send": round(gone[aid] / 1000 - sent)} if aid in gone else {})} for aid in first}
    indexed = indexed_after(s, label, sent)
    print(f"indexed: {indexed['copies']} of {sum(r['copies'] for r in lines)} lines, the first {indexed['seconds_after_send']} s after sending"
          + (f"; their timestamp is {a['backdate']} min before the send" if a["backdate"] else ""))
    for x in b["alerts"]:
        aid = x["id"]
        verdict = (f"raised {raised[aid]['seconds_after_send']} s after the lines, {raised[aid]['level']}"
                   + (f", cleared at {raised[aid]['cleared_seconds_after_send']} s" if "cleared_seconds_after_send" in raised.get(aid, {}) else "")
                   if aid in raised
                   else "sent, not raised" if aid in by_alert else "no host-record line; waits for a real event")
        print(f"{aid}: {verdict}")
    if a["out"]:
        scrub = Scrubber()
        scrub.add_host(a["host"], "esx")
        scrub.add_host(urlparse(a["target"]).hostname, "listener")
        scrub.add(host_id, "resource-id")
        a["out"].mkdir(parents=True, exist_ok=True)
        out = a["out"] / "proof.record.json"
        scrub.write(out, {"read_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "sent_at": when,
                          "bundle": b["bundle"], "host": a["host"], "target": a["target"], "minutes": a["minutes"],
                          "lines": [{"app": r["sample"]["app"], "copies": r["copies"], "symptoms": r["keys"]} for r in lines],
                          "backdated_minutes": a["backdate"], "indexed": indexed, "can_raise": by_alert, "raised": raised,
                          "not_raised": sorted(set(by_alert) - set(raised)),
                          "vcenter_channel_only": sorted({x["id"] for x in b["alerts"]} - set(by_alert))})
        print(f"wrote {out.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
