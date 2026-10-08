#!/usr/bin/env python3
"""Deploy the WTPC POSTURE alert bundle — POST the symptom + alert definitions and enable them in the WTPC
policy ONLY (never Default). Public API (/api/symptomdefinitions, /api/alertdefinitions) — supported.

Reads the generated artifacts (content/wtpc-alerts.{symptoms,alerts}.json). On POST the server
assigns ids (it rejects a client id), so this maps the generator's slug ids -> server ids and
rewires each alert's symptom-set references before POSTing the alerts. Portable: the WTPC + Default
policies resolve by name at runtime.

A converge, not a redeploy: each definition is adopted by NAME and written only when it differs from
the live one, compared field by field the way the server stores it (a condition value sent as "1" is kept as
"1.0", a symptom set in the server's own order). A write is read back and must hold every field it set and
leave the rest alone. Each alert's switch in the WTPC and Default policies is read from the policy
export, set only where it is not already LOCAL as wanted, and re-sent until the export shows it held, because
a switch can answer 200 and not be recorded. So a re-run on a converged estate writes nothing.

SCOPING (the estate's hard rule): each alert is ENABLED in the WTPC policy and DISABLED in Default — so it
fires only on objects whose EFFECTIVE policy is WTPC (never all objects). NOTE: precedence still
applies — an alert fires on a member only when WTPC is that member's effective policy; run the
effective-policy parity check (validate_live.py --parity) if members are shadowed by another policy.

Usage (from this folder):
  python deploy_alerts.py              # dry-run: what would change, read-only
  python deploy_alerts.py --execute    # converge: write what differs, read it back, switch what is not held
  python deploy_alerts.py --self-test  # the converge's branches offline (no API)
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys
import time

from lib._alerts import find_existing, switch_states
from lib._client import ops_client
from lib._names import same

HERE = os.path.dirname(os.path.abspath(__file__))
SYMPTOMS = os.path.join(HERE, "content", "wtpc-alerts.symptoms.json")
ALERTS = os.path.join(HERE, "content", "wtpc-alerts.alerts.json")
WTPC_POLICY = "PCA - WTPC - prod-latency-critical-db"


def load(path, key):
    if not os.path.exists(path):
        # build_alerts.py writes these; it cannot until an executed build.py has written the super metric record
        sys.exit(f"skipped: {os.path.basename(path)} does not exist yet. build_alerts.py writes it once an executed "
                 f"build.py has recorded the super metric ids (a dry run records none).")
    return json.load(open(path, encoding="utf-8"))[key]


NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def resolve_policies(c, required: bool):
    pols = c.get("/api/policies", params={"_no_links": "true", "pageSize": 500}).json()["policySummaries"]
    wtpc = next((p["id"] for p in pols if same(p["name"], WTPC_POLICY)), None)
    default = next((p["id"] for p in pols if p.get("defaultPolicy")), None)
    if not wtpc and required:
        raise SystemExit(f"policy {WTPC_POLICY!r} not found — run the step-4 policy instantiation first")
    return wtpc, default


def canon(value, key=None):
    """A definition's comparable form: numbers compare as numbers and a symptom set as a set, because the server
    stores a condition value sent as "1" as "1.0" and keeps a set's ids in its own order. Ids are not compared."""
    if isinstance(value, dict):
        return {k: canon(v, k) for k, v in value.items() if k != "id"}
    if isinstance(value, list):
        items = [canon(v) for v in value]
        return sorted(items, key=json.dumps) if key == "symptomDefinitionIds" else items
    if isinstance(value, str) and NUMBER.fullmatch(value):
        return float(value)
    return value


def drift(body: dict, live: dict) -> list[str]:
    """The fields the generated body sets that the live definition does not hold."""
    return sorted(k for k in body if k != "id" and canon(body[k], k) != canon(live.get(k), k))


def converge(c, endpoint: str, body: dict, ident, execute: bool, kind: str, short: str):
    """Adopt-or-create one definition by name: write only when it differs, then read back what the write did.
    Returns (id or None, outcome)."""
    if ident:
        live = c.get(f"{endpoint}/{ident}").json()
        fields = drift(body, live)
        if not fields:
            print(f"   in step: {short}")
            return ident, "in step"
        if not execute:
            print(f"   DRY-RUN would UPDATE {kind} {short} ({', '.join(fields)})")
            return ident, "would update"
        c.put(endpoint, json={**body, "id": ident})
        back = c.get(f"{endpoint}/{ident}").json()
        wrong = drift(body, back)
        moved = sorted(k for k in live if k not in body and k != "id" and live.get(k) != back.get(k))
        if wrong or moved:
            raise SystemExit(f"read-back after updating {kind} {short!r}: not as written {wrong}, changed unasked {moved}")
        print(f"   updated: {short} ({', '.join(fields)}), read back")
        return ident, "updated"
    if not execute:
        print(f"   DRY-RUN would POST {kind} {short} (new)")
        return None, "would create"
    got = c.post(endpoint, json=body).json()
    back = c.get(f"{endpoint}/{got['id']}").json()
    wrong = drift(body, back)
    if wrong:
        raise SystemExit(f"read-back after creating {kind} {short!r} ({got['id']}): not as written {wrong}")
    print(f"   POSTed: {short} -> {got['id'][:24]}, read back")
    return got["id"], "created"


def scope(c, alerts: list[tuple[str, str, str, str]], wtpc, default, execute: bool,
          pause: float = 10) -> collections.Counter:
    """Each alert LOCAL on in the WTPC policy and LOCAL off in Default, read from the policy export.

    Enable first: a WTPC policy that only inherits an alert from Default would lose it if Default were switched
    off first. A switch can answer 200 and not be recorded, so each phase re-sends what the
    export does not yet show, up to six times, and stops loudly if it still does not hold."""
    out = collections.Counter()
    kinds = [(aid, ak, rk) for _name, aid, ak, rk in alerts]
    short = {aid: name.split(" - ", 2)[-1] for name, aid, _ak, _rk in alerts}
    if not kinds:
        return out
    if not wtpc:
        print(f"   DRY-RUN {len(kinds)} alert(s) would be switched on in {WTPC_POLICY!r} once it exists, and off in Default")
        out["would switch"] += 2 * len(kinds)
        return out
    for pid, on, label in ((wtpc, True, "on in WTPC"), (default, False, "off in Default")):
        if not pid:
            continue
        sent, needed = 0, None
        for attempt in range(7):
            state = switch_states(c, [pid], kinds)
            todo = [aid for aid, _ak, _rk in kinds if state[(pid, aid)] != ("LOCAL", on)]
            needed = len(todo) if needed is None else needed
            if not todo:
                print(f"   {label}: all {len(kinds)} held, LOCAL in the export"
                      + (f" ({needed} switched, {sent - needed} re-sent)" if sent else ""))
                out["switch in step"] += len(kinds) - needed
                out["switched"] += needed
                out["re-sent"] += sent - needed
                break
            if not execute:
                for aid in todo:
                    print(f"   DRY-RUN would switch {short[aid]} {label} (now {state[(pid, aid)][0]} {state[(pid, aid)][1]})")
                out["would switch"] += len(todo)
                break
            if attempt == 6:
                raise SystemExit(f"{label}: {[short[a] for a in todo]} did not hold after 6 sends")
            for aid in todo:
                c.put(f"/api/alertdefinitions/{aid}/{'enable' if on else 'disable'}", params={"policyId": pid})
                sent += 1
            time.sleep(pause)
    return out


def deploy(c, execute: bool) -> int:
    symptoms = load(SYMPTOMS, "symptomDefinitions")
    alerts = load(ALERTS, "alertDefinitions")
    wtpc, default = resolve_policies(c, required=execute)
    print(f"WTPC alert deploy · {'EXECUTE' if execute else 'DRY-RUN'}  (policy {str(wtpc)[:8]})")
    counts = collections.Counter()

    # 1) symptoms, adopted by name and written only on a difference. find_existing and the per-definition reads
    #    are GETs, so they run in dry-run too and the preview is truthful.
    existing_sym = find_existing(c, "/api/symptomdefinitions", "symptomDefinitions")
    id_map: dict[str, str] = {}
    print(f"1) {len(symptoms)} symptom definitions")
    for s in symptoms:
        body = {k: v for k, v in s.items() if k != "id"}
        sid, outcome = converge(c, "/api/symptomdefinitions", body, existing_sym.get(s["name"]), execute,
                                "symptom", s["name"].split(" - ")[-1])
        id_map[s["id"]] = sid or f"<server-id:{s['id']}>"
        counts[outcome] += 1

    # 2) alerts: remap symptom refs to server ids, then the same converge.
    existing_alert = find_existing(c, "/api/alertdefinitions", "alertDefinitions")
    scoped: list[tuple[str, str, str, str]] = []
    print(f"2) {len(alerts)} alert definitions")
    for a in alerts:
        body = {k: v for k, v in a.items() if k != "id"}
        for st in body["states"]:
            ss = st["base-symptom-set"]
            ss["symptomDefinitionIds"] = [id_map[sid] for sid in ss["symptomDefinitionIds"]]
        aid, outcome = converge(c, "/api/alertdefinitions", body, existing_alert.get(a["name"]), execute,
                                "alert", a["name"].split(" - ", 2)[-1])
        counts[outcome] += 1
        if aid:
            scoped.append((a["name"], aid, body["adapterKindKey"], body["resourceKindKey"]))

    # 3) each alert on in the WTPC policy and off in Default: never all objects
    print("3) on in the WTPC policy ONLY, off in Default (read from the policy export)")
    counts += scope(c, scoped, wtpc, default, execute)
    print(f"\n{'done' if execute else 'dry-run complete'}: " + ", ".join(f"{n} {k}" for k, n in sorted(counts.items()))
          + ". Firing is precedence-gated: a member pages only when WTPC is its effective policy (--parity).")
    return 0


class _FakeInstance:
    """Offline stand-in for the instance: stores a numeric value as "x.0" and a symptom set reversed (as the server
    normalizes them), records every write, drops the first switch it receives, and can ignore one field on PUT."""

    class _R:
        def __init__(self, value):
            self._value = value

        def json(self):
            return self._value

    def __init__(self, ignore_field=None):
        self.defs, self.switches, self.writes, self.ignore, self._dropped = {}, {}, [], ignore_field, False

    @staticmethod
    def stored(value, key=None):
        if isinstance(value, dict):
            return {k: _FakeInstance.stored(v, k) for k, v in value.items()}
        if isinstance(value, list):
            items = [_FakeInstance.stored(v) for v in value]
            return items[::-1] if key == "symptomDefinitionIds" else items
        return f"{float(value)}" if isinstance(value, str) and NUMBER.fullmatch(value) else value

    def get(self, path, params=None):
        return self._R(json.loads(json.dumps(self.defs[path.rsplit("/", 1)[1]])))

    def post(self, path, json=None):
        ident = f"Def-{len(self.defs)}"
        self.defs[ident] = {**self.stored(json), "id": ident}
        self.writes.append(("POST", ident))
        return self._R({"id": ident})

    def put(self, path, json=None, params=None):
        if params:                                        # an alert switch
            if not self._dropped:
                self._dropped = True                      # answered 200, never recorded
                self.writes.append(("DROPPED", path))
                return self._R({})
            on = path.endswith("/enable")
            self.switches[(params["policyId"], path.split("/")[3])] = on
            self.writes.append(("ENABLE" if on else "DISABLE", path))
            return self._R({})
        body = {k: v for k, v in json.items() if k != self.ignore}
        self.defs[json["id"]] = {**self.defs[json["id"]], **self.stored(body)}
        self.writes.append(("PUT", json["id"]))
        return self._R({})

    def states(self, c, policy_ids, alerts):
        return {(p, a): ("LOCAL", self.switches[(p, a)]) if (p, a) in self.switches else ("INHERITED", True)
                for p in policy_ids for a, _ak, _rk in alerts}


def self_test() -> int:
    """The converge's branches, offline: in step, drift written and read back, a write that did not hold, a
    dropped switch re-sent, enable before disable, and a dry run that writes nothing."""
    global switch_states
    body = {"name": "PCA - WTPC - t", "adapterKindKey": "VMWARE", "resourceKindKey": "HostSystem",
            "state": {"condition": {"value": "1", "operator": "GT"}}}
    alert = {"name": "PCA - WTPC - a", "states": [{"base-symptom-set": {"symptomDefinitionIds": ["S1", "S2"]}}]}
    fake = _FakeInstance()
    fake.defs["X"] = {**fake.stored(body), "id": "X"}
    fake.defs["A"] = {**fake.stored(alert), "id": "A"}
    assert converge(fake, "/api/symptomdefinitions", body, "X", True, "symptom", "t") == ("X", "in step")
    assert converge(fake, "/api/alertdefinitions", alert, "A", True, "alert", "a") == ("A", "in step")
    assert not fake.writes, fake.writes                   # normalization alone is not drift
    changed = {**body, "state": {"condition": {"value": "2", "operator": "GT"}}}
    assert converge(fake, "/api/symptomdefinitions", changed, "X", False, "symptom", "t")[1] == "would update"
    assert not fake.writes, "a dry run wrote"
    assert converge(fake, "/api/symptomdefinitions", changed, "X", True, "symptom", "t")[1] == "updated"
    assert fake.writes == [("PUT", "X")], fake.writes
    stubborn = _FakeInstance(ignore_field="state")
    stubborn.defs["X"] = {**stubborn.stored(body), "id": "X"}
    try:
        converge(stubborn, "/api/symptomdefinitions", changed, "X", True, "symptom", "t")
        raise AssertionError("a write that did not hold was accepted")
    except SystemExit as e:
        assert "not as written ['state']" in str(e), e
    switch_states, real = fake.states, switch_states
    try:
        counts = scope(fake, [("PCA - WTPC - x - a", "A", "VMWARE", "HostSystem"),
                              ("PCA - WTPC - x - b", "B", "VMWARE", "HostSystem")], "W", "D", True, pause=0)
    finally:
        switch_states = real
    kinds = [w[0] for w in fake.writes if w[0] in ("DROPPED", "ENABLE", "DISABLE")]
    assert kinds == ["DROPPED", "ENABLE", "ENABLE", "DISABLE", "DISABLE"], kinds    # re-sent, enables first
    assert fake.switches == {("W", "A"): True, ("W", "B"): True, ("D", "A"): False, ("D", "B"): False}
    assert counts["switched"] == 4 and counts["re-sent"] == 1, counts
    print("self-test: in step skipped, drift written and read back, a write that did not hold refused, "
          "a dropped switch re-sent, every enable before any disable, a dry run writes nothing")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Deploy + enable the WTPC posture alert bundle (public API)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true", help="POST + enable (default: dry-run)")
    mode.add_argument("--self-test", action="store_true", help="exercise the converge offline (no API)")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    with ops_client() as c:
        return deploy(c, args.execute)


if __name__ == "__main__":
    sys.exit(main())
